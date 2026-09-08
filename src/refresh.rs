use std::sync::Arc;

use anyhow::{Context, Result, anyhow};
use tokio::sync::{Mutex, RwLock, mpsc};
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::{
    ingest::{self, source::SourceContext},
    models::{RefreshAccepted, RefreshStatus, now_rfc3339},
};

#[derive(Debug)]
struct RefreshRequest {
    job_id: String,
    reason: String,
}

#[derive(Clone)]
pub struct RefreshCoordinator {
    sender: Option<mpsc::Sender<RefreshRequest>>,
    status: Arc<RwLock<RefreshStatus>>,
    enqueue_gate: Arc<Mutex<()>>,
}

impl RefreshCoordinator {
    pub fn start(context: SourceContext, registry: Arc<ingest::source::SourceRegistry>) -> Self {
        if !context.config.refresh_allowed() {
            return Self {
                sender: None,
                status: Arc::new(RwLock::new(RefreshStatus {
                    state: "disabled".into(),
                    ..RefreshStatus::default()
                })),
                enqueue_gate: Arc::new(Mutex::new(())),
            };
        }
        let (sender, receiver) = mpsc::channel(context.config.refresh_queue_capacity);
        let status = Arc::new(RwLock::new(RefreshStatus::default()));
        tokio::spawn(worker(receiver, status.clone(), context, registry));
        Self {
            sender: Some(sender),
            status,
            enqueue_gate: Arc::new(Mutex::new(())),
        }
    }

    pub async fn request(&self, reason: impl Into<String>) -> Result<RefreshAccepted> {
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| anyhow!("refresh is disabled"))?;
        let reason = reason.into();
        let _gate = self.enqueue_gate.lock().await;
        {
            let status = self.status.read().await;
            if matches!(status.state.as_str(), "queued" | "running") {
                return Ok(RefreshAccepted {
                    accepted: false,
                    job_id: status.job_id.clone().unwrap_or_default(),
                    state: status.state.clone(),
                });
            }
        }

        let job_id = Uuid::new_v4().to_string();
        *self.status.write().await = RefreshStatus {
            job_id: Some(job_id.clone()),
            state: "queued".into(),
            reason: Some(reason.clone()),
            queued_at: Some(now_rfc3339()),
            started_at: None,
            finished_at: None,
            report: None,
            error: None,
        };
        if let Err(error) = sender.try_send(RefreshRequest {
            job_id: job_id.clone(),
            reason,
        }) {
            *self.status.write().await = RefreshStatus::default();
            return Err(anyhow!("failed to enqueue refresh: {error}"));
        }
        Ok(RefreshAccepted {
            accepted: true,
            job_id,
            state: "queued".into(),
        })
    }

    pub async fn status(&self) -> RefreshStatus {
        self.status.read().await.clone()
    }
}

async fn worker(
    mut receiver: mpsc::Receiver<RefreshRequest>,
    status: Arc<RwLock<RefreshStatus>>,
    context: SourceContext,
    registry: Arc<ingest::source::SourceRegistry>,
) {
    while let Some(request) = receiver.recv().await {
        {
            let mut current = status.write().await;
            current.state = "running".into();
            current.started_at = Some(now_rfc3339());
            current.error = None;
        }
        info!(job_id = %request.job_id, reason = %request.reason, "starting cyber intelligence refresh");

        let result = execute_refresh(&context, registry.clone(), &request.job_id).await;
        match result {
            Ok(report) => {
                info!(
                    job_id = %request.job_id,
                    sources_succeeded = report.sources_succeeded,
                    sources_failed = report.sources_failed,
                    fetched = report.fetched,
                    upserted = report.upserted,
                    validated = report.validated,
                    "cyber intelligence refresh complete"
                );
                let mut current = status.write().await;
                current.state = "completed".into();
                current.finished_at = Some(now_rfc3339());
                current.report = Some(report);
                current.error = None;
            }
            Err(error) => {
                error!(job_id = %request.job_id, error = %error, "refresh failed");
                let mut current = status.write().await;
                current.state = "failed".into();
                current.finished_at = Some(now_rfc3339());
                current.error = Some(format!("{error:#}"));
            }
        }
    }
}

async fn execute_refresh(
    context: &SourceContext,
    registry: Arc<ingest::source::SourceRegistry>,
    job_id: &str,
) -> Result<crate::models::RefreshReport> {
    let mut report = ingest::run_sources(context.clone(), registry, job_id).await;

    match ingest::validate::run(context).await {
        Ok(validation) => {
            report.validated = validation.validated;
            for warning in validation.warnings {
                warn!(job_id, warning = %warning, "refresh validation warning");
                report.errors.push(warning);
            }
        }
        Err(error) => report
            .errors
            .push(format!("cross-validation stage failed: {error:#}")),
    }

    context
        .repository
        .cleanup_retention(
            context.config.news_retention_days,
            context.config.ingestion_run_retention_days,
        )
        .await
        .context("retention cleanup failed")?;
    report.finished_at = now_rfc3339();
    Ok(report)
}
