use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, SecondsFormat, Utc};
use reqwest::header::{HeaderName, HeaderValue};
use serde_json::Value;

use crate::{
    classifier::{classify, content_hash, first_sentence, normalize_severity, severity_from_score},
    ingest::{
        http::{FetchPolicy, parse_json, send_limited},
        source::{SourceAdapter, SourceContext, SourceOutput},
    },
    models::{EvidenceInput, IngestBatch, ItemInput, SourceDescriptor, SyncUpdate, now_rfc3339},
};

pub struct NvdSource;

#[async_trait]
impl SourceAdapter for NvdSource {
    fn descriptor(&self) -> SourceDescriptor {
        SourceDescriptor {
            id: "nvd".into(),
            name: "NIST National Vulnerability Database".into(),
            kind: "structured".into(),
            region: "United States".into(),
            language: "en".into(),
            role: "vulnerability-database".into(),
            trust: 3,
            timeout_seconds: 180,
            retry_attempts: 2,
        }
    }

    async fn run(&self, context: &SourceContext) -> Result<SourceOutput> {
        let descriptor = self.descriptor();
        let now = Utc::now();
        let cursor = context
            .repository
            .get_sync_state("cursor:nvd:last_modified")
            .await?;
        let mut start = cursor
            .as_deref()
            .and_then(|value| DateTime::parse_from_rfc3339(value).ok())
            .map(|value| {
                value.with_timezone(&Utc)
                    - ChronoDuration::minutes(context.config.nvd_overlap_minutes)
            })
            .unwrap_or_else(|| now - ChronoDuration::days(context.config.nvd_initial_window_days));
        if start > now {
            start = now - ChronoDuration::days(1);
        }
        if now - start > ChronoDuration::days(119) {
            start = now - ChronoDuration::days(119);
        }

        let start_text = nvd_timestamp(start);
        let end_text = nvd_timestamp(now);
        let mut start_index = 0_usize;
        let mut total_results = usize::MAX;
        let mut batch = IngestBatch::default();
        let mut fetched = 0_usize;
        let mut pages = 0_usize;

        while start_index < total_results {
            pages += 1;
            if pages > 500 {
                bail!("NVD pagination exceeded the safety limit");
            }

            let results_per_page = context.config.nvd_results_per_page.to_string();
            let start_index_text = start_index.to_string();
            let request = context
                .http
                .get("https://services.nvd.nist.gov/rest/json/cves/2.0")
                .query(&[
                    ("lastModStartDate", start_text.as_str()),
                    ("lastModEndDate", end_text.as_str()),
                    ("resultsPerPage", results_per_page.as_str()),
                    ("startIndex", start_index_text.as_str()),
                ]);
            let request = if let Some(api_key) = &context.config.nvd_api_key {
                request.header(
                    HeaderName::from_static("apikey"),
                    HeaderValue::from_str(api_key).context("NVD_API_KEY contains invalid bytes")?,
                )
            } else {
                request
            };

            let response = send_limited(
                request,
                &FetchPolicy {
                    timeout: context
                        .config
                        .source_timeout
                        .max(std::time::Duration::from_secs(120)),
                    retries: context.config.source_retry_attempts.max(2),
                    max_bytes: context.config.max_source_response_bytes,
                    allow_not_modified: false,
                },
            )
            .await
            .with_context(|| format!("NVD page starting at {start_index} failed"))?;
            let payload: Value = parse_json(&response, "NVD CVE response")?;
            total_results = payload
                .get("totalResults")
                .and_then(Value::as_u64)
                .and_then(|value| usize::try_from(value).ok())
                .ok_or_else(|| anyhow!("invalid NVD CVE response: totalResults is missing"))?;
            let vulnerabilities = payload
                .get("vulnerabilities")
                .and_then(Value::as_array)
                .ok_or_else(|| anyhow!("invalid NVD CVE response: vulnerabilities is missing"))?;

            if vulnerabilities.is_empty() {
                break;
            }
            fetched = fetched.saturating_add(vulnerabilities.len());
            for wrapper in vulnerabilities {
                let Some(cve) = wrapper.get("cve") else {
                    continue;
                };
                if let Some((item, evidence)) = parse_cve(cve, &descriptor) {
                    batch.items.push(item);
                    batch.evidence.push(evidence);
                }
            }
            start_index = start_index.saturating_add(vulnerabilities.len());
        }

        batch.sync_updates.push(SyncUpdate {
            key: "cursor:nvd:last_modified".into(),
            value: now.to_rfc3339_opts(SecondsFormat::Millis, true),
        });
        let candidate_upserts = batch.items.len();
        Ok(SourceOutput {
            batch,
            fetched,
            candidate_upserts,
            skipped: false,
            note: Some(format!("processed {pages} NVD page(s)")),
        })
    }
}

fn parse_cve(cve: &Value, descriptor: &SourceDescriptor) -> Option<(ItemInput, EvidenceInput)> {
    let id = cve.get("id")?.as_str()?.to_ascii_uppercase();
    let description = english_description(cve)
        .unwrap_or_else(|| "No English description supplied by NVD.".into());
    let published_at = cve
        .get("published")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let updated_at = cve
        .get("lastModified")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let (cvss_score, severity) = cvss(cve);
    let (vendor, product) = first_cpe(cve).unwrap_or((None, None));
    let title = format!("{id}: {}", first_sentence(&description, 180));
    let url = format!("https://nvd.nist.gov/vuln/detail/{id}");
    let raw_json = serde_json::to_string(cve).ok();
    let observed_at = now_rfc3339();
    let categories = classify(&format!("{title} {description}"));
    let hash_material = raw_json.as_deref().unwrap_or(&description);

    let item = ItemInput {
        id: format!("cve:{id}"),
        kind: "cve".into(),
        cve_id: Some(id.clone()),
        title,
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
        content_hash: content_hash(hash_material.as_bytes()),
        categories,
        cves: vec![id.clone()],
    };
    let evidence = EvidenceInput {
        cve_id: id,
        source_id: descriptor.id.clone(),
        source_name: descriptor.name.clone(),
        evidence_type: "vulnerability-record".into(),
        status: cve
            .get("vulnStatus")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
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
        authoritative: true,
        observed_at,
    };
    Some((item, evidence))
}

fn english_description(cve: &Value) -> Option<String> {
    let descriptions = cve.get("descriptions")?.as_array()?;
    descriptions
        .iter()
        .find(|entry| entry.get("lang").and_then(Value::as_str) == Some("en"))
        .or_else(|| descriptions.first())?
        .get("value")?
        .as_str()
        .map(ToOwned::to_owned)
}

fn cvss(cve: &Value) -> (Option<f64>, Option<String>) {
    let metrics = cve.get("metrics");
    for key in [
        "cvssMetricV40",
        "cvssMetricV31",
        "cvssMetricV30",
        "cvssMetricV2",
    ] {
        let Some(entry) = metrics
            .and_then(|value| value.get(key))
            .and_then(Value::as_array)
            .and_then(|values| values.first())
        else {
            continue;
        };
        let data = entry.get("cvssData").unwrap_or(entry);
        let score = data.get("baseScore").and_then(Value::as_f64);
        let severity = data
            .get("baseSeverity")
            .or_else(|| entry.get("baseSeverity"))
            .and_then(Value::as_str)
            .and_then(normalize_severity)
            .or_else(|| score.map(severity_from_score));
        if score.is_some() || severity.is_some() {
            return (score, severity);
        }
    }
    (None, None)
}

fn first_cpe(value: &Value) -> Option<(Option<String>, Option<String>)> {
    if let Some(criteria) = value.get("criteria").and_then(Value::as_str) {
        let parts: Vec<&str> = criteria.split(':').collect();
        if parts.len() > 4 && parts.first() == Some(&"cpe") {
            return Some((decode_cpe(parts[3]), decode_cpe(parts[4])));
        }
    }
    match value {
        Value::Array(values) => values.iter().find_map(first_cpe),
        Value::Object(values) => values.values().find_map(first_cpe),
        _ => None,
    }
}

fn decode_cpe(value: &str) -> Option<String> {
    if matches!(value, "*" | "-") || value.is_empty() {
        None
    } else {
        Some(value.replace('_', " ").replace("\\!", "!"))
    }
}

fn nvd_timestamp(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Millis, true)
}
