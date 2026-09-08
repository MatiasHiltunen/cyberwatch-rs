use anyhow::{Context, Result, anyhow};
use async_trait::async_trait;
use serde_json::Value;

use crate::{
    classifier::{classify, content_hash},
    ingest::{
        http::{FetchPolicy, FetchResponse, parse_json, send_limited},
        source::{SourceAdapter, SourceContext, SourceOutput},
    },
    models::{
        EvidenceInput, IngestBatch, ItemInput, SourceCacheUpdate, SourceDescriptor, SyncUpdate,
        now_rfc3339,
    },
};

const CISA_KEV_URLS: &[&str] = &[
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    "https://raw.githubusercontent.com/cisagov/kev-data/develop/known_exploited_vulnerabilities.json",
];

pub struct CisaKevSource;

#[async_trait]
impl SourceAdapter for CisaKevSource {
    fn descriptor(&self) -> SourceDescriptor {
        SourceDescriptor {
            id: "cisa-kev".into(),
            name: "CISA Known Exploited Vulnerabilities".into(),
            kind: "structured".into(),
            region: "United States".into(),
            language: "en".into(),
            role: "exploitation-catalog".into(),
            trust: 3,
            timeout_seconds: 120,
            retry_attempts: 2,
        }
    }

    async fn run(&self, context: &SourceContext) -> Result<SourceOutput> {
        let descriptor = self.descriptor();
        let cache = context.repository.get_source_cache(&descriptor.id).await?;
        let mut failures = Vec::new();
        let mut selected: Option<(FetchResponse, Value, String)> = None;

        for url in CISA_KEV_URLS {
            match send_limited(
                context.http.get(*url),
                &FetchPolicy {
                    timeout: context.config.source_timeout,
                    retries: context.config.source_retry_attempts.max(1),
                    max_bytes: context.config.max_source_response_bytes,
                    allow_not_modified: false,
                },
            )
            .await
            {
                Ok(response) => {
                    let response_hash = content_hash(&response.body);
                    if cache
                        .as_ref()
                        .is_some_and(|entry| entry.content_hash == response_hash)
                    {
                        let mut output = SourceOutput::unchanged("CISA KEV catalog is unchanged");
                        output.batch.cache_updates.push(SourceCacheUpdate {
                            source_id: descriptor.id.clone(),
                            etag: response.etag,
                            last_modified: response.last_modified,
                            content_hash: response_hash,
                        });
                        return Ok(output);
                    }
                    match parse_json::<Value>(&response, "CISA KEV") {
                        Ok(payload)
                            if payload
                                .get("vulnerabilities")
                                .and_then(Value::as_array)
                                .is_some() =>
                        {
                            selected = Some((response, payload, response_hash));
                            break;
                        }
                        Ok(payload) => failures.push(format!(
                            "{url}: JSON lacks vulnerabilities array; top-level keys={:?}",
                            payload.as_object().map(|value| value
                                .keys()
                                .take(12)
                                .cloned()
                                .collect::<Vec<_>>())
                        )),
                        Err(error) => failures.push(format!("{url}: {error:#}")),
                    }
                }
                Err(error) => failures.push(format!("{url}: {error:#}")),
            }
        }

        let (response, payload, response_hash) = selected.ok_or_else(|| {
            anyhow!(
                "all CISA KEV endpoints failed validation: {}",
                failures.join(" | ")
            )
        })?;
        let vulnerabilities = payload
            .get("vulnerabilities")
            .and_then(Value::as_array)
            .context("invalid CISA KEV JSON")?;
        let observed_at = now_rfc3339();
        let mut batch = IngestBatch::default();

        for record in vulnerabilities {
            let Some(cve_id) = record
                .get("cveID")
                .and_then(Value::as_str)
                .map(str::to_ascii_uppercase)
            else {
                continue;
            };
            let vendor = string_field(record, "vendorProject");
            let product = string_field(record, "product");
            let title = string_field(record, "vulnerabilityName")
                .unwrap_or_else(|| format!("{cve_id} — known exploited vulnerability"));
            let summary = string_field(record, "shortDescription").unwrap_or_default();
            let remediation = string_field(record, "requiredAction");
            let due_date = string_field(record, "dueDate");
            let date_added = string_field(record, "dateAdded");
            let ransomware = string_field(record, "knownRansomwareCampaignUse");
            let notes = string_field(record, "notes");
            let raw_json = serde_json::to_string(record).ok();
            let url = notes
                .as_deref()
                .and_then(first_http_url)
                .unwrap_or_else(|| {
                    "https://www.cisa.gov/known-exploited-vulnerabilities-catalog".into()
                });
            let published_at = date_added.as_deref().map(date_to_timestamp);
            let combined = format!(
                "{title} {summary} {}",
                remediation.as_deref().unwrap_or_default()
            );

            batch.items.push(ItemInput {
                id: format!("cve:{cve_id}"),
                kind: "cve".into(),
                cve_id: Some(cve_id.clone()),
                title: title.clone(),
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
                source_updated_at: None,
                ingested_at: observed_at.clone(),
                exploited: true,
                kev_date_added: date_added.clone(),
                remediation: remediation.clone(),
                due_date: due_date.clone(),
                ransomware_use: ransomware.clone(),
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
                evidence_type: "known-exploitation".into(),
                status: Some("KNOWN_EXPLOITED".into()),
                severity: None,
                cvss_score: None,
                exploited: Some(true),
                vendor,
                product,
                published_at,
                updated_at: None,
                summary: Some(summary),
                url: Some(url),
                raw_json,
                authoritative: true,
                observed_at: observed_at.clone(),
            });
        }

        batch.cache_updates.push(SourceCacheUpdate {
            source_id: descriptor.id.clone(),
            etag: response.etag.clone(),
            last_modified: response.last_modified.clone(),
            content_hash: response_hash,
        });
        if let Some(version) = payload.get("catalogVersion").and_then(Value::as_str) {
            batch.sync_updates.push(SyncUpdate {
                key: "cursor:cisa-kev:catalog-version".into(),
                value: version.to_owned(),
            });
        }
        let candidate_upserts = batch.items.len();
        Ok(SourceOutput {
            batch,
            fetched: vulnerabilities.len(),
            candidate_upserts,
            skipped: false,
            note: Some(format!("source_url={}", response.final_url)),
        })
    }
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn date_to_timestamp(date: &str) -> String {
    if date.contains('T') {
        date.to_owned()
    } else {
        format!("{date}T00:00:00Z")
    }
}

fn first_http_url(notes: &str) -> Option<String> {
    notes
        .split(|character: char| character.is_whitespace() || matches!(character, ';' | ','))
        .map(|part| part.trim_matches(|character: char| matches!(character, '(' | ')' | '[' | ']')))
        .find(|part| part.starts_with("https://") || part.starts_with("http://"))
        .map(ToOwned::to_owned)
}
