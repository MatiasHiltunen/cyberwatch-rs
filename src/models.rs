use std::collections::BTreeMap;

use chrono::{SecondsFormat, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ItemInput {
    pub id: String,
    pub kind: String,
    pub cve_id: Option<String>,
    pub title: String,
    pub summary: String,
    pub url: String,
    pub source_id: String,
    pub source_name: String,
    pub source_region: String,
    pub source_language: String,
    pub source_trust: u8,
    pub severity: Option<String>,
    pub cvss_score: Option<f64>,
    pub published_at: Option<String>,
    pub source_updated_at: Option<String>,
    pub ingested_at: String,
    pub exploited: bool,
    pub kev_date_added: Option<String>,
    pub remediation: Option<String>,
    pub due_date: Option<String>,
    pub ransomware_use: Option<String>,
    pub vendor: Option<String>,
    pub product: Option<String>,
    pub raw_json: Option<String>,
    pub content_hash: String,
    pub categories: Vec<String>,
    pub cves: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceInput {
    pub cve_id: String,
    pub source_id: String,
    pub source_name: String,
    pub evidence_type: String,
    pub status: Option<String>,
    pub severity: Option<String>,
    pub cvss_score: Option<f64>,
    pub exploited: Option<bool>,
    pub vendor: Option<String>,
    pub product: Option<String>,
    pub published_at: Option<String>,
    pub updated_at: Option<String>,
    pub summary: Option<String>,
    pub url: Option<String>,
    pub raw_json: Option<String>,
    pub authoritative: bool,
    pub observed_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationInput {
    pub cve_id: String,
    pub confidence: String,
    pub independent_sources: i64,
    pub authoritative_sources: i64,
    pub severity_disagreement: bool,
    pub cvss_disagreement: bool,
    pub uncorroborated_exploitation: bool,
    pub missing_canonical: bool,
    pub canonical_status: Option<String>,
    pub epss_probability: Option<f64>,
    pub epss_percentile: Option<f64>,
    pub calculated_at: String,
}

#[derive(Debug, Clone, Default)]
pub struct IngestBatch {
    pub items: Vec<ItemInput>,
    pub evidence: Vec<EvidenceInput>,
    pub sync_updates: Vec<SyncUpdate>,
    pub cache_updates: Vec<SourceCacheUpdate>,
}

impl IngestBatch {
    pub fn extend(&mut self, other: Self) {
        self.items.extend(other.items);
        self.evidence.extend(other.evidence);
        self.sync_updates.extend(other.sync_updates);
        self.cache_updates.extend(other.cache_updates);
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
            && self.evidence.is_empty()
            && self.sync_updates.is_empty()
            && self.cache_updates.is_empty()
    }
}

#[derive(Debug, Clone)]
pub struct SyncUpdate {
    pub key: String,
    pub value: String,
}

#[derive(Debug, Clone)]
pub struct SourceCacheUpdate {
    pub source_id: String,
    pub etag: Option<String>,
    pub last_modified: Option<String>,
    pub content_hash: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ItemRecord {
    pub id: String,
    pub kind: String,
    pub cve_id: Option<String>,
    pub title: String,
    pub summary: String,
    pub url: String,
    pub source_id: String,
    pub source_name: String,
    pub source_region: String,
    pub source_language: String,
    pub source_trust: i64,
    pub severity: Option<String>,
    pub cvss_score: Option<f64>,
    pub published_at: Option<String>,
    pub source_updated_at: Option<String>,
    pub ingested_at: String,
    pub effective_timestamp: String,
    pub exploited: bool,
    pub kev_date_added: Option<String>,
    pub remediation: Option<String>,
    pub due_date: Option<String>,
    pub ransomware_use: Option<String>,
    pub vendor: Option<String>,
    pub product: Option<String>,
    pub categories: Vec<String>,
    pub confidence: Option<String>,
    pub independent_sources: Option<i64>,
    pub authoritative_sources: Option<i64>,
    pub severity_disagreement: Option<bool>,
    pub cvss_disagreement: Option<bool>,
    pub uncorroborated_exploitation: Option<bool>,
    pub epss_probability: Option<f64>,
    pub epss_percentile: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ItemPage {
    pub items: Vec<ItemRecord>,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct EvidenceRecord {
    pub cve_id: String,
    pub source_id: String,
    pub source_name: String,
    pub evidence_type: String,
    pub status: Option<String>,
    pub severity: Option<String>,
    pub cvss_score: Option<f64>,
    pub exploited: Option<bool>,
    pub vendor: Option<String>,
    pub product: Option<String>,
    pub published_at: Option<String>,
    pub updated_at: Option<String>,
    pub summary: Option<String>,
    pub url: Option<String>,
    pub authoritative: bool,
    pub observed_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ValidationRecord {
    pub cve_id: String,
    pub confidence: String,
    pub independent_sources: i64,
    pub authoritative_sources: i64,
    pub severity_disagreement: bool,
    pub cvss_disagreement: bool,
    pub uncorroborated_exploitation: bool,
    pub missing_canonical: bool,
    pub canonical_status: Option<String>,
    pub epss_probability: Option<f64>,
    pub epss_percentile: Option<f64>,
    pub calculated_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct CveDetail {
    pub item: ItemRecord,
    pub evidence: Vec<EvidenceRecord>,
    pub validation: Option<ValidationRecord>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct Stats {
    pub total_items: i64,
    pub news_items: i64,
    pub cve_items: i64,
    pub critical_cves: i64,
    pub high_cves: i64,
    pub exploited_cves: i64,
    pub kev_cves: i64,
    pub validated_cves: i64,
    pub sources_seen: i64,
    pub categories: BTreeMap<String, i64>,
    pub generated_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SourceHealth {
    pub source_id: String,
    pub source_name: String,
    pub source_kind: String,
    pub last_status: String,
    pub last_run_at: Option<String>,
    pub last_success_at: Option<String>,
    pub failures_24h: i64,
    pub last_error: Option<String>,
    pub backoff_until: Option<String>,
}

#[derive(Debug, Clone)]
pub struct IngestionRunInput {
    pub job_id: String,
    pub source_id: String,
    pub source_name: String,
    pub source_kind: String,
    pub status: String,
    pub fetched: usize,
    pub upserted: usize,
    pub error: Option<String>,
    pub started_at: String,
    pub finished_at: String,
    pub duration_ms: u128,
}

#[derive(Debug, Clone, Serialize)]
pub struct SourceDescriptor {
    pub id: String,
    pub name: String,
    pub kind: String,
    pub region: String,
    pub language: String,
    pub role: String,
    pub trust: u8,
    pub timeout_seconds: u64,
    pub retry_attempts: usize,
}

#[derive(Debug, Clone)]
pub struct SourceCacheEntry {
    pub etag: Option<String>,
    pub last_modified: Option<String>,
    pub content_hash: String,
}

#[derive(Debug, Clone, Copy)]
pub struct EpssScore {
    pub probability: f64,
    pub percentile: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageCursor {
    pub timestamp: String,
    pub id: String,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct RefreshReport {
    pub job_id: String,
    pub started_at: String,
    pub finished_at: String,
    pub sources_total: usize,
    pub sources_succeeded: usize,
    pub sources_failed: usize,
    pub sources_skipped: usize,
    pub fetched: usize,
    pub upserted: usize,
    pub validated: usize,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RefreshStatus {
    pub job_id: Option<String>,
    pub state: String,
    pub reason: Option<String>,
    pub queued_at: Option<String>,
    pub started_at: Option<String>,
    pub finished_at: Option<String>,
    pub report: Option<RefreshReport>,
    pub error: Option<String>,
}

impl Default for RefreshStatus {
    fn default() -> Self {
        Self {
            job_id: None,
            state: "idle".to_owned(),
            reason: None,
            queued_at: None,
            started_at: None,
            finished_at: None,
            report: None,
            error: None,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct RefreshAccepted {
    pub accepted: bool,
    pub job_id: String,
    pub state: String,
}

pub fn now_rfc3339() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}
