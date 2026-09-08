use anyhow::{Context, Result};
use async_trait::async_trait;
use feed_rs::model::Entry;
use reqwest::{StatusCode, header};

use crate::{
    classifier::{classify, content_hash, extract_cves, stable_id, strip_html, truncate_chars},
    config::FeedConfig,
    ingest::{
        http::{FetchPolicy, send_limited},
        source::{SourceAdapter, SourceContext, SourceOutput},
    },
    models::{
        EvidenceInput, IngestBatch, ItemInput, SourceCacheUpdate, SourceDescriptor, now_rfc3339,
    },
};

pub struct FeedSource {
    feed: FeedConfig,
    default_timeout_seconds: u64,
    default_retries: usize,
}

impl FeedSource {
    pub fn new(feed: FeedConfig, default_timeout_seconds: u64, default_retries: usize) -> Self {
        Self {
            feed,
            default_timeout_seconds,
            default_retries,
        }
    }
}

#[async_trait]
impl SourceAdapter for FeedSource {
    fn descriptor(&self) -> SourceDescriptor {
        SourceDescriptor {
            id: format!("feed-{}", self.feed.id),
            name: self.feed.name.clone(),
            kind: "feed".into(),
            region: self.feed.region.clone(),
            language: self.feed.language.clone(),
            role: self.feed.role.clone(),
            trust: self.feed.trust,
            timeout_seconds: self
                .feed
                .timeout_seconds
                .unwrap_or(self.default_timeout_seconds),
            retry_attempts: self.feed.retry_attempts.unwrap_or(self.default_retries),
        }
    }

    async fn run(&self, context: &SourceContext) -> Result<SourceOutput> {
        let descriptor = self.descriptor();
        let cache = context.repository.get_source_cache(&descriptor.id).await?;
        let mut request = context.http.get(&self.feed.url);
        if let Some(cache) = &cache {
            if let Some(etag) = &cache.etag {
                request = request.header(header::IF_NONE_MATCH, etag);
            }
            if let Some(last_modified) = &cache.last_modified {
                request = request.header(header::IF_MODIFIED_SINCE, last_modified);
            }
        }

        let response = send_limited(
            request,
            &FetchPolicy {
                timeout: std::time::Duration::from_secs(descriptor.timeout_seconds),
                retries: descriptor.retry_attempts,
                max_bytes: context.config.max_source_response_bytes,
                allow_not_modified: true,
            },
        )
        .await?;
        if response.status == StatusCode::NOT_MODIFIED {
            return Ok(SourceOutput::unchanged("HTTP 304 Not Modified"));
        }

        let response_hash = content_hash(&response.body);
        if cache
            .as_ref()
            .is_some_and(|entry| entry.content_hash == response_hash)
        {
            let mut output = SourceOutput::unchanged("response content hash is unchanged");
            output.batch.cache_updates.push(SourceCacheUpdate {
                source_id: descriptor.id.clone(),
                etag: response.etag,
                last_modified: response.last_modified,
                content_hash: response_hash,
            });
            return Ok(output);
        }

        let bytes = response.body.clone();
        let parsed = tokio::task::spawn_blocking(move || feed_rs::parser::parse(bytes.as_slice()))
            .await
            .context("feed parser task failed")?
            .context("invalid RSS, Atom, RDF, or JSON feed")?;
        let fetched = parsed.entries.len();
        let observed_at = now_rfc3339();
        let mut batch = IngestBatch::default();

        for entry in parsed.entries.into_iter().take(250) {
            if let Some((item, evidence)) = map_entry(&entry, &descriptor, &observed_at) {
                batch.items.push(item);
                batch.evidence.extend(evidence);
            }
        }
        batch.cache_updates.push(SourceCacheUpdate {
            source_id: descriptor.id.clone(),
            etag: response.etag,
            last_modified: response.last_modified,
            content_hash: response_hash,
        });
        let candidate_upserts = batch.items.len();
        Ok(SourceOutput {
            batch,
            fetched,
            candidate_upserts,
            skipped: false,
            note: None,
        })
    }
}

fn map_entry(
    entry: &Entry,
    descriptor: &SourceDescriptor,
    observed_at: &str,
) -> Option<(ItemInput, Vec<EvidenceInput>)> {
    let title = entry
        .title
        .as_ref()
        .map(|value| strip_html(&value.content))
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "Untitled security update".into());
    let url = entry
        .links
        .iter()
        .find(|link| link.rel.as_deref().is_none_or(|rel| rel == "alternate"))
        .or_else(|| entry.links.first())
        .map(|link| link.href.clone())
        .filter(|value| value.starts_with("http://") || value.starts_with("https://"))?;
    let summary = entry
        .summary
        .as_ref()
        .map(|value| strip_html(&value.content))
        .or_else(|| {
            entry
                .content
                .as_ref()
                .and_then(|content| content.body.as_deref())
                .map(strip_html)
        })
        .unwrap_or_default();
    let summary = truncate_chars(&summary, 8_000);
    let combined = format!("{title} {summary}");
    let cves = extract_cves(&combined);
    let published_at = entry.published.as_ref().map(|value| value.to_rfc3339());
    let updated_at = entry.updated.as_ref().map(|value| value.to_rfc3339());
    let key = if entry.id.trim().is_empty() {
        url.as_str()
    } else {
        entry.id.as_str()
    };
    let id = stable_id("news", &format!("{}:{key}", descriptor.id));
    let hash_material = format!("{title}\n{summary}\n{url}\n{updated_at:?}");
    let lower_text = combined.to_lowercase();
    let actively_exploited = lower_text.contains("actively exploited");
    let authoritative = descriptor.trust == 3
        && (descriptor.role.contains("official") || descriptor.role.contains("government"));

    let item = ItemInput {
        id,
        kind: "news".into(),
        cve_id: cves.first().cloned(),
        title,
        summary: summary.clone(),
        url: url.clone(),
        source_id: descriptor.id.clone(),
        source_name: descriptor.name.clone(),
        source_region: descriptor.region.clone(),
        source_language: descriptor.language.clone(),
        source_trust: descriptor.trust,
        severity: None,
        cvss_score: None,
        published_at: published_at.clone(),
        source_updated_at: updated_at.clone(),
        ingested_at: observed_at.to_owned(),
        exploited: actively_exploited,
        kev_date_added: None,
        remediation: None,
        due_date: None,
        ransomware_use: None,
        vendor: None,
        product: None,
        raw_json: None,
        content_hash: content_hash(hash_material.as_bytes()),
        categories: classify(&combined),
        cves: cves.clone(),
    };
    let evidence = cves
        .into_iter()
        .map(|cve_id| EvidenceInput {
            cve_id,
            source_id: descriptor.id.clone(),
            source_name: descriptor.name.clone(),
            evidence_type: "news-mention".into(),
            status: None,
            severity: None,
            cvss_score: None,
            exploited: actively_exploited.then_some(true),
            vendor: None,
            product: None,
            published_at: published_at.clone(),
            updated_at: updated_at.clone(),
            summary: Some(summary.clone()),
            url: Some(url.clone()),
            raw_json: None,
            authoritative,
            observed_at: observed_at.to_owned(),
        })
        .collect();
    Some((item, evidence))
}
