use anyhow::{Context, Result, anyhow};
use async_trait::async_trait;
use reqwest::header::{ACCEPT, AUTHORIZATION, HeaderValue, USER_AGENT};
use serde_json::Value;

use crate::{
    classifier::{classify, content_hash, normalize_severity},
    ingest::{
        http::{FetchPolicy, parse_json, send_limited},
        source::{SourceAdapter, SourceContext, SourceOutput},
    },
    models::{EvidenceInput, IngestBatch, ItemInput, SourceDescriptor, now_rfc3339},
};

pub struct GithubAdvisorySource;

#[async_trait]
impl SourceAdapter for GithubAdvisorySource {
    fn descriptor(&self) -> SourceDescriptor {
        SourceDescriptor {
            id: "github-advisories".into(),
            name: "GitHub Reviewed Security Advisories".into(),
            kind: "structured".into(),
            region: "Global".into(),
            language: "en".into(),
            role: "advisory-database".into(),
            trust: 2,
            timeout_seconds: 120,
            retry_attempts: 2,
        }
    }

    async fn run(&self, context: &SourceContext) -> Result<SourceOutput> {
        let descriptor = self.descriptor();
        let mut batch = IngestBatch::default();
        let mut fetched = 0_usize;
        let observed_at = now_rfc3339();

        for page in 1..=context.config.github_advisory_pages {
            let page_text = page.to_string();
            let mut request = context
                .http
                .get("https://api.github.com/advisories")
                .query(&[
                    ("type", "reviewed"),
                    ("sort", "updated"),
                    ("direction", "desc"),
                    ("per_page", "100"),
                    ("page", page_text.as_str()),
                ])
                .header(ACCEPT, "application/vnd.github+json")
                .header(
                    USER_AGENT,
                    concat!("cyberwatch-rs/", env!("CARGO_PKG_VERSION")),
                )
                .header("X-GitHub-Api-Version", "2022-11-28");
            if let Some(token) = &context.config.github_token {
                request = request.header(
                    AUTHORIZATION,
                    HeaderValue::from_str(&format!("Bearer {token}"))
                        .context("GITHUB_TOKEN contains invalid bytes")?,
                );
            }

            let response = send_limited(
                request,
                &FetchPolicy {
                    timeout: context.config.source_timeout,
                    retries: context.config.source_retry_attempts,
                    max_bytes: context.config.max_source_response_bytes,
                    allow_not_modified: false,
                },
            )
            .await?;
            let advisories: Value = parse_json(&response, "GitHub advisory response")?;
            let advisories = advisories
                .as_array()
                .ok_or_else(|| anyhow!("invalid GitHub advisory response: expected an array"))?;
            fetched = fetched.saturating_add(advisories.len());

            for advisory in advisories {
                let Some(cve_id) = advisory
                    .get("cve_id")
                    .and_then(Value::as_str)
                    .map(str::to_ascii_uppercase)
                else {
                    continue;
                };
                let summary = advisory
                    .get("summary")
                    .and_then(Value::as_str)
                    .unwrap_or("GitHub reviewed security advisory")
                    .to_owned();
                let description = advisory
                    .get("description")
                    .and_then(Value::as_str)
                    .unwrap_or(&summary)
                    .to_owned();
                let severity = advisory
                    .get("severity")
                    .and_then(Value::as_str)
                    .and_then(normalize_severity);
                let cvss_score = advisory
                    .pointer("/cvss/score")
                    .and_then(Value::as_f64)
                    .or_else(|| {
                        advisory
                            .pointer("/cvss/score")
                            .and_then(Value::as_str)
                            .and_then(|value| value.parse().ok())
                    });
                let published_at = string(advisory, "published_at");
                let updated_at = string(advisory, "updated_at");
                let url = string(advisory, "html_url")
                    .or_else(|| string(advisory, "url"))
                    .unwrap_or_else(|| format!("https://github.com/advisories?query={cve_id}"));
                let (vendor, product) = package(advisory);
                let raw_json = serde_json::to_string(advisory).ok();
                let combined = format!("{summary} {description}");

                batch.items.push(ItemInput {
                    id: format!("cve:{cve_id}"),
                    kind: "cve".into(),
                    cve_id: Some(cve_id.clone()),
                    title: format!("{cve_id}: {summary}"),
                    summary: description.clone(),
                    url: url.clone(),
                    source_id: descriptor.id.clone(),
                    source_name: descriptor.name.clone(),
                    source_region: descriptor.region.clone(),
                    source_language: descriptor.language.clone(),
                    source_trust: descriptor.trust,
                    severity: severity.clone(),
                    cvss_score,
                    published_at: published_at.clone(),
                    source_updated_at: updated_at.clone(),
                    ingested_at: observed_at.clone(),
                    exploited: false,
                    kev_date_added: None,
                    remediation: None,
                    due_date: None,
                    ransomware_use: None,
                    vendor: vendor.clone(),
                    product: product.clone(),
                    raw_json: raw_json.clone(),
                    content_hash: content_hash(raw_json.as_deref().unwrap_or(&combined).as_bytes()),
                    categories: classify(&combined),
                    cves: vec![cve_id.clone()],
                });
                batch.evidence.push(EvidenceInput {
                    cve_id,
                    source_id: descriptor.id.clone(),
                    source_name: descriptor.name.clone(),
                    evidence_type: "reviewed-advisory".into(),
                    status: Some("REVIEWED".into()),
                    severity,
                    cvss_score,
                    exploited: None,
                    vendor,
                    product,
                    published_at,
                    updated_at,
                    summary: Some(description),
                    url: Some(url),
                    raw_json,
                    authoritative: false,
                    observed_at: observed_at.clone(),
                });
            }

            if advisories.len() < 100 {
                break;
            }
        }

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

fn string(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
}

fn package(advisory: &Value) -> (Option<String>, Option<String>) {
    let Some(vulnerability) = advisory
        .get("vulnerabilities")
        .and_then(Value::as_array)
        .and_then(|values| values.first())
    else {
        return (None, None);
    };
    (
        vulnerability
            .pointer("/package/ecosystem")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
        vulnerability
            .pointer("/package/name")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
    )
}
