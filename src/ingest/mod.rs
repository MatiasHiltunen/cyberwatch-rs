pub mod cisa;
pub mod epss;
pub mod feeds;
pub mod github;
pub mod http;
pub mod nvd;
pub mod source;
pub mod validate;

use std::{panic::AssertUnwindSafe, sync::Arc, time::Duration};

use anyhow::{Result, anyhow};
use chrono::Utc;
use futures::{FutureExt, StreamExt, stream::FuturesUnordered};
use tokio::{sync::Semaphore, time::timeout};
use tracing::{info, warn};

use crate::{
    Config,
    ingest::{
        cisa::CisaKevSource,
        feeds::FeedSource,
        github::GithubAdvisorySource,
        nvd::NvdSource,
        source::{SourceContext, SourceRegistry},
    },
    models::{IngestionRunInput, RefreshReport, SourceDescriptor, now_rfc3339},
};

pub fn build_registry(config: &Config) -> Result<SourceRegistry> {
    let mut registry = SourceRegistry::new();
    if config.source_enabled("nvd") {
        registry.register(NvdSource)?;
    }
    if config.source_enabled("cisa-kev") {
        registry.register(CisaKevSource)?;
    }
    if config.source_enabled("github-advisories") {
        registry.register(GithubAdvisorySource)?;
    }

    for feed in &config.feeds {
        let source_id = format!("feed-{}", feed.id);
        if config.source_enabled(&source_id) {
            registry.register(FeedSource::new(
                feed.clone(),
                config.source_timeout.as_secs(),
                config.source_retry_attempts,
            ))?;
        }
    }
    Ok(registry)
}

pub async fn run_sources(
    context: SourceContext,
    registry: Arc<SourceRegistry>,
    job_id: &str,
) -> RefreshReport {
    let started_at = now_rfc3339();
    let semaphore = Arc::new(Semaphore::new(context.config.source_concurrency));
    let mut tasks = FuturesUnordered::new();

    for adapter in registry.adapters() {
        let context = context.clone();
        let semaphore = semaphore.clone();
        let job_id = job_id.to_owned();
        tasks.push(async move {
            let permit = semaphore
                .acquire_owned()
                .await
                .map_err(|_| anyhow!("source concurrency semaphore closed"))?;
            let result = run_one_source(context, adapter, &job_id).await;
            drop(permit);
            result
        });
    }

    let mut report = RefreshReport {
        job_id: job_id.to_owned(),
        started_at,
        sources_total: registry.len(),
        ..RefreshReport::default()
    };
    while let Some(result) = tasks.next().await {
        match result {
            Ok(outcome) => {
                report.fetched = report.fetched.saturating_add(outcome.fetched);
                report.upserted = report.upserted.saturating_add(outcome.upserted);
                match outcome.status.as_str() {
                    "success" => report.sources_succeeded += 1,
                    "skipped" => report.sources_skipped += 1,
                    _ => report.sources_failed += 1,
                }
                if let Some(error) = outcome.error {
                    report.errors.push(error);
                }
            }
            Err(error) => {
                report.sources_failed += 1;
                report
                    .errors
                    .push(format!("source worker failed: {error:#}"));
            }
        }
    }
    report.finished_at = now_rfc3339();
    report
}

struct SourceRunOutcome {
    status: String,
    fetched: usize,
    upserted: usize,
    error: Option<String>,
}

async fn run_one_source(
    context: SourceContext,
    adapter: Arc<dyn source::SourceAdapter>,
    job_id: &str,
) -> Result<SourceRunOutcome> {
    let descriptor = adapter.descriptor();
    let started = std::time::Instant::now();
    let started_at = now_rfc3339();

    if let Some(until) = context
        .repository
        .source_backoff_until(&descriptor.id)
        .await?
    {
        if until > Utc::now() {
            let message = format!("source {} is in backoff until {until}", descriptor.id);
            context
                .repository
                .record_ingestion_run(&IngestionRunInput {
                    job_id: job_id.to_owned(),
                    source_id: descriptor.id.clone(),
                    source_name: descriptor.name.clone(),
                    source_kind: descriptor.kind.clone(),
                    status: "skipped".into(),
                    fetched: 0,
                    upserted: 0,
                    error: Some(message.clone()),
                    started_at,
                    finished_at: now_rfc3339(),
                    duration_ms: started.elapsed().as_millis(),
                })
                .await?;
            return Ok(SourceRunOutcome {
                status: "skipped".into(),
                fetched: 0,
                upserted: 0,
                error: Some(message),
            });
        }
    }

    info!(source = %descriptor.id, "starting source ingestion");
    let deadline = Duration::from_secs(descriptor.timeout_seconds.max(5));
    let execution = AssertUnwindSafe(adapter.run(&context)).catch_unwind();
    let adapter_result = match timeout(deadline, execution).await {
        Ok(Ok(result)) => result,
        Ok(Err(_panic)) => Err(anyhow!("source adapter panicked")),
        Err(_) => Err(anyhow!(
            "source adapter exceeded its {} second deadline",
            deadline.as_secs()
        )),
    };
    let result = match adapter_result {
        Ok(output) => match output.validate(&descriptor) {
            Ok(()) => context
                .repository
                .apply_batch(&output.batch)
                .await
                .map(|upserted| (output, upserted)),
            Err(error) => Err(error),
        },
        Err(error) => Err(error),
    };

    match result {
        Ok((output, upserted)) => {
            context
                .repository
                .clear_source_failure(&descriptor.id)
                .await?;
            let status = if output.skipped { "skipped" } else { "success" };
            context
                .repository
                .record_ingestion_run(&IngestionRunInput {
                    job_id: job_id.to_owned(),
                    source_id: descriptor.id.clone(),
                    source_name: descriptor.name.clone(),
                    source_kind: descriptor.kind.clone(),
                    status: status.into(),
                    fetched: output.fetched,
                    upserted,
                    error: None,
                    started_at,
                    finished_at: now_rfc3339(),
                    duration_ms: started.elapsed().as_millis(),
                })
                .await?;
            info!(
                source = %descriptor.id,
                fetched = output.fetched,
                upserted,
                status,
                note = output.note.as_deref().unwrap_or(""),
                "source ingestion complete"
            );
            Ok(SourceRunOutcome {
                status: status.into(),
                fetched: output.fetched,
                upserted,
                error: None,
            })
        }
        Err(error) => {
            let backoff_until = context
                .repository
                .mark_source_failure(
                    &descriptor.id,
                    context.config.source_failure_backoff,
                    context.config.source_failure_backoff_max,
                )
                .await?;
            let message = truncate_error(format!(
                "{} failed: {error:#}; retry after {backoff_until}",
                descriptor.name
            ));
            warn!(source = %descriptor.id, error = %message, "source ingestion failed");
            context
                .repository
                .record_ingestion_run(&IngestionRunInput {
                    job_id: job_id.to_owned(),
                    source_id: descriptor.id.clone(),
                    source_name: descriptor.name.clone(),
                    source_kind: descriptor.kind.clone(),
                    status: "failed".into(),
                    fetched: 0,
                    upserted: 0,
                    error: Some(message.clone()),
                    started_at,
                    finished_at: now_rfc3339(),
                    duration_ms: started.elapsed().as_millis(),
                })
                .await?;
            Ok(SourceRunOutcome {
                status: "failed".into(),
                fetched: 0,
                upserted: 0,
                error: Some(message),
            })
        }
    }
}

fn truncate_error(mut value: String) -> String {
    if value.len() > 2_000 {
        value.truncate(2_000);
        value.push('…');
    }
    value
}

pub fn descriptor_map(registry: &SourceRegistry) -> Vec<SourceDescriptor> {
    registry.descriptors()
}
