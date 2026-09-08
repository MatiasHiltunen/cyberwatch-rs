use std::{
    collections::{BTreeMap, HashMap},
    path::Path,
    sync::Arc,
    time::Duration,
};

use anyhow::{Context, Result, anyhow};
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use libsql::{Builder, Database, Row, TransactionBehavior, params};
use tokio::sync::Mutex;

use crate::models::{
    EvidenceInput, EvidenceRecord, IngestBatch, IngestionRunInput, ItemPage, ItemRecord,
    PageCursor, SourceCacheEntry, SourceHealth, Stats, ValidationInput, ValidationRecord,
    now_rfc3339,
};

const ITEM_SELECT: &str = r#"
SELECT
    i.id,
    i.kind,
    i.cve_id,
    i.title,
    i.summary,
    i.url,
    i.source_id,
    i.source_name,
    i.source_region,
    i.source_language,
    i.source_trust,
    i.severity,
    i.cvss_score,
    i.published_at,
    i.source_updated_at,
    i.ingested_at,
    COALESCE(i.published_at, i.source_updated_at, i.ingested_at) AS effective_timestamp,
    i.exploited,
    i.kev_date_added,
    i.remediation,
    i.due_date,
    i.ransomware_use,
    i.vendor,
    i.product,
    COALESCE((
        SELECT GROUP_CONCAT(category, char(31))
        FROM item_categories ic
        WHERE ic.item_id = i.id
    ), '') AS categories,
    v.confidence,
    v.independent_sources,
    v.authoritative_sources,
    v.severity_disagreement,
    v.cvss_disagreement,
    v.uncorroborated_exploitation,
    v.epss_probability,
    v.epss_percentile
FROM items i
LEFT JOIN cve_validation v ON v.cve_id = i.cve_id
"#;

#[derive(Debug, Clone, Default)]
pub struct ItemFilter {
    pub kind: Option<String>,
    pub category: Option<String>,
    pub severity: Option<String>,
    pub confidence: Option<String>,
    pub source: Option<String>,
    pub region: Option<String>,
    pub query: Option<String>,
    pub exploited: Option<bool>,
    pub limit: usize,
    pub offset: usize,
    pub cursor: Option<PageCursor>,
}

#[derive(Clone)]
pub struct Repository {
    database: Arc<Database>,
    write_gate: Arc<Mutex<()>>,
}

impl Repository {
    pub async fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
        {
            tokio::fs::create_dir_all(parent).await.with_context(|| {
                format!("failed to create database directory {}", parent.display())
            })?;
        }

        let database = Builder::new_local(path)
            .build()
            .await
            .with_context(|| format!("failed to open local Turso database {}", path.display()))?;
        let repository = Self {
            database: Arc::new(database),
            write_gate: Arc::new(Mutex::new(())),
        };
        repository.migrate().await?;
        Ok(repository)
    }

    async fn connection(&self) -> Result<libsql::Connection> {
        let connection = self
            .database
            .connect()
            .context("failed to open database connection")?;
        let _ = connection
            .execute_batch("PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;")
            .await
            .context("failed to configure database connection")?;
        Ok(connection)
    }

    async fn migrate(&self) -> Result<()> {
        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        let _ = connection
            .execute_batch(include_str!("schema.sql"))
            .await
            .context("failed to apply database schema")?;
        Ok(())
    }

    pub async fn ready(&self) -> Result<()> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'items'",
                (),
            )
            .await?;
        rows.next()
            .await?
            .ok_or_else(|| anyhow!("database readiness query returned no row"))?;
        Ok(())
    }

    pub async fn apply_batch(&self, batch: &IngestBatch) -> Result<usize> {
        if batch.is_empty() {
            return Ok(0);
        }

        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .await
            .context("failed to start ingestion transaction")?;

        for item in &batch.items {
            transaction
                .execute(
                    r#"
INSERT INTO items (
    id, kind, cve_id, title, summary, url, source_id, source_name, source_region,
    source_language, source_trust, severity, cvss_score, published_at,
    source_updated_at, ingested_at, exploited, kev_date_added, remediation,
    due_date, ransomware_use, vendor, product, raw_json, content_hash
) VALUES (
    ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15,
    ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23, ?24, ?25
)
ON CONFLICT(id) DO UPDATE SET
    kind = excluded.kind,
    cve_id = COALESCE(excluded.cve_id, items.cve_id),
    title = CASE WHEN excluded.source_trust >= items.source_trust THEN excluded.title ELSE items.title END,
    summary = CASE
        WHEN excluded.source_trust >= items.source_trust AND excluded.summary <> '' THEN excluded.summary
        ELSE items.summary
    END,
    url = CASE WHEN excluded.source_trust >= items.source_trust THEN excluded.url ELSE items.url END,
    source_id = CASE WHEN excluded.source_trust >= items.source_trust THEN excluded.source_id ELSE items.source_id END,
    source_name = CASE WHEN excluded.source_trust >= items.source_trust THEN excluded.source_name ELSE items.source_name END,
    source_region = CASE WHEN excluded.source_trust >= items.source_trust THEN excluded.source_region ELSE items.source_region END,
    source_language = CASE WHEN excluded.source_trust >= items.source_trust THEN excluded.source_language ELSE items.source_language END,
    source_trust = MAX(items.source_trust, excluded.source_trust),
    severity = CASE
        WHEN (CASE excluded.severity WHEN 'critical' THEN 5 WHEN 'high' THEN 4 WHEN 'medium' THEN 3 WHEN 'low' THEN 2 WHEN 'none' THEN 1 ELSE 0 END)
           >= (CASE items.severity WHEN 'critical' THEN 5 WHEN 'high' THEN 4 WHEN 'medium' THEN 3 WHEN 'low' THEN 2 WHEN 'none' THEN 1 ELSE 0 END)
        THEN COALESCE(excluded.severity, items.severity)
        ELSE items.severity
    END,
    cvss_score = CASE
        WHEN excluded.cvss_score IS NULL THEN items.cvss_score
        WHEN items.cvss_score IS NULL THEN excluded.cvss_score
        ELSE MAX(items.cvss_score, excluded.cvss_score)
    END,
    published_at = CASE
        WHEN items.published_at IS NULL THEN excluded.published_at
        WHEN excluded.published_at IS NULL THEN items.published_at
        ELSE MIN(items.published_at, excluded.published_at)
    END,
    source_updated_at = CASE
        WHEN items.source_updated_at IS NULL THEN excluded.source_updated_at
        WHEN excluded.source_updated_at IS NULL THEN items.source_updated_at
        ELSE MAX(items.source_updated_at, excluded.source_updated_at)
    END,
    ingested_at = excluded.ingested_at,
    exploited = MAX(items.exploited, excluded.exploited),
    kev_date_added = COALESCE(excluded.kev_date_added, items.kev_date_added),
    remediation = COALESCE(excluded.remediation, items.remediation),
    due_date = COALESCE(excluded.due_date, items.due_date),
    ransomware_use = COALESCE(excluded.ransomware_use, items.ransomware_use),
    vendor = COALESCE(excluded.vendor, items.vendor),
    product = COALESCE(excluded.product, items.product),
    raw_json = CASE WHEN excluded.source_trust >= items.source_trust THEN excluded.raw_json ELSE items.raw_json END,
    content_hash = excluded.content_hash
"#,
                    params![
                        item.id.as_str(),
                        item.kind.as_str(),
                        item.cve_id.as_deref(),
                        item.title.as_str(),
                        item.summary.as_str(),
                        item.url.as_str(),
                        item.source_id.as_str(),
                        item.source_name.as_str(),
                        item.source_region.as_str(),
                        item.source_language.as_str(),
                        i64::from(item.source_trust),
                        item.severity.as_deref(),
                        item.cvss_score,
                        item.published_at.as_deref(),
                        item.source_updated_at.as_deref(),
                        item.ingested_at.as_str(),
                        bool_to_i64(item.exploited),
                        item.kev_date_added.as_deref(),
                        item.remediation.as_deref(),
                        item.due_date.as_deref(),
                        item.ransomware_use.as_deref(),
                        item.vendor.as_deref(),
                        item.product.as_deref(),
                        item.raw_json.as_deref(),
                        item.content_hash.as_str(),
                    ],
                )
                .await
                .with_context(|| format!("failed to upsert item {}", item.id))?;

            transaction
                .execute(
                    "DELETE FROM item_categories WHERE item_id = ?1",
                    [item.id.as_str()],
                )
                .await?;
            for category in &item.categories {
                transaction
                    .execute(
                        "INSERT OR IGNORE INTO item_categories (item_id, category) VALUES (?1, ?2)",
                        (item.id.as_str(), category.as_str()),
                    )
                    .await?;
            }

            transaction
                .execute(
                    "DELETE FROM item_cves WHERE item_id = ?1",
                    [item.id.as_str()],
                )
                .await?;
            for cve in &item.cves {
                transaction
                    .execute(
                        "INSERT OR IGNORE INTO item_cves (item_id, cve_id) VALUES (?1, ?2)",
                        (item.id.as_str(), cve.as_str()),
                    )
                    .await?;
            }
        }

        upsert_evidence_in_transaction(&transaction, &batch.evidence).await?;

        for update in &batch.sync_updates {
            transaction
                .execute(
                    r#"
INSERT INTO sync_state (key, value, updated_at) VALUES (?1, ?2, ?3)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
"#,
                    (update.key.as_str(), update.value.as_str(), now_rfc3339()),
                )
                .await?;
        }

        for update in &batch.cache_updates {
            transaction
                .execute(
                    r#"
INSERT INTO source_cache (source_id, etag, last_modified, content_hash, updated_at)
VALUES (?1, ?2, ?3, ?4, ?5)
ON CONFLICT(source_id) DO UPDATE SET
    etag = excluded.etag,
    last_modified = excluded.last_modified,
    content_hash = excluded.content_hash,
    updated_at = excluded.updated_at
"#,
                    params![
                        update.source_id.as_str(),
                        update.etag.as_deref(),
                        update.last_modified.as_deref(),
                        update.content_hash.as_str(),
                        now_rfc3339(),
                    ],
                )
                .await?;
        }

        transaction
            .commit()
            .await
            .context("failed to commit ingestion batch")?;
        Ok(batch.items.len())
    }

    pub async fn upsert_evidence(&self, evidence: &[EvidenceInput]) -> Result<()> {
        if evidence.is_empty() {
            return Ok(());
        }
        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .await?;
        upsert_evidence_in_transaction(&transaction, evidence).await?;
        transaction.commit().await?;
        Ok(())
    }

    pub async fn upsert_validations(&self, validations: &[ValidationInput]) -> Result<()> {
        if validations.is_empty() {
            return Ok(());
        }
        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .await?;
        for validation in validations {
            transaction
                .execute(
                    r#"
INSERT INTO cve_validation (
    cve_id, confidence, independent_sources, authoritative_sources,
    severity_disagreement, cvss_disagreement, uncorroborated_exploitation,
    missing_canonical, canonical_status, epss_probability, epss_percentile,
    calculated_at
) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)
ON CONFLICT(cve_id) DO UPDATE SET
    confidence = excluded.confidence,
    independent_sources = excluded.independent_sources,
    authoritative_sources = excluded.authoritative_sources,
    severity_disagreement = excluded.severity_disagreement,
    cvss_disagreement = excluded.cvss_disagreement,
    uncorroborated_exploitation = excluded.uncorroborated_exploitation,
    missing_canonical = excluded.missing_canonical,
    canonical_status = excluded.canonical_status,
    epss_probability = excluded.epss_probability,
    epss_percentile = excluded.epss_percentile,
    calculated_at = excluded.calculated_at
"#,
                    params![
                        validation.cve_id.as_str(),
                        validation.confidence.as_str(),
                        validation.independent_sources,
                        validation.authoritative_sources,
                        bool_to_i64(validation.severity_disagreement),
                        bool_to_i64(validation.cvss_disagreement),
                        bool_to_i64(validation.uncorroborated_exploitation),
                        bool_to_i64(validation.missing_canonical),
                        validation.canonical_status.as_deref(),
                        validation.epss_probability,
                        validation.epss_percentile,
                        validation.calculated_at.as_str(),
                    ],
                )
                .await?;
        }
        transaction.commit().await?;
        Ok(())
    }

    pub async fn record_ingestion_run(&self, run: &IngestionRunInput) -> Result<()> {
        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        connection
            .execute(
                r#"
INSERT INTO ingestion_runs (
    job_id, source_id, source_name, source_kind, status, fetched, upserted,
    error, started_at, finished_at, duration_ms
) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
"#,
                params![
                    run.job_id.as_str(),
                    run.source_id.as_str(),
                    run.source_name.as_str(),
                    run.source_kind.as_str(),
                    run.status.as_str(),
                    i64::try_from(run.fetched).unwrap_or(i64::MAX),
                    i64::try_from(run.upserted).unwrap_or(i64::MAX),
                    run.error.as_deref(),
                    run.started_at.as_str(),
                    run.finished_at.as_str(),
                    i64::try_from(run.duration_ms).unwrap_or(i64::MAX),
                ],
            )
            .await?;
        Ok(())
    }

    pub async fn get_sync_state(&self, key: &str) -> Result<Option<String>> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query("SELECT value FROM sync_state WHERE key = ?1", [key])
            .await?;
        Ok(rows
            .next()
            .await?
            .map(|row| row.get::<String>(0))
            .transpose()?)
    }

    pub async fn set_sync_states(&self, values: &[(&str, String)]) -> Result<()> {
        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        let transaction = connection.transaction().await?;
        for (key, value) in values {
            transaction
                .execute(
                    r#"
INSERT INTO sync_state (key, value, updated_at) VALUES (?1, ?2, ?3)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
"#,
                    (*key, value.as_str(), now_rfc3339()),
                )
                .await?;
        }
        transaction.commit().await?;
        Ok(())
    }

    pub async fn delete_sync_states(&self, keys: &[String]) -> Result<()> {
        if keys.is_empty() {
            return Ok(());
        }
        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        let transaction = connection.transaction().await?;
        for key in keys {
            transaction
                .execute("DELETE FROM sync_state WHERE key = ?1", [key.as_str()])
                .await?;
        }
        transaction.commit().await?;
        Ok(())
    }

    pub async fn source_backoff_until(&self, source_id: &str) -> Result<Option<DateTime<Utc>>> {
        let key = format!("source:{source_id}:backoff_until");
        self.get_sync_state(&key)
            .await?
            .map(|value| {
                DateTime::parse_from_rfc3339(&value)
                    .map(|date| date.with_timezone(&Utc))
                    .context("invalid persisted source backoff timestamp")
            })
            .transpose()
    }

    pub async fn mark_source_failure(
        &self,
        source_id: &str,
        base: Duration,
        maximum: Duration,
    ) -> Result<DateTime<Utc>> {
        let count_key = format!("source:{source_id}:failure_count");
        let until_key = format!("source:{source_id}:backoff_until");
        let previous = self
            .get_sync_state(&count_key)
            .await?
            .and_then(|value| value.parse::<u32>().ok())
            .unwrap_or(0);
        let count = previous.saturating_add(1).min(31);
        let multiplier = 1_u64
            .checked_shl(count.saturating_sub(1))
            .unwrap_or(u64::MAX);
        let seconds = base
            .as_secs()
            .saturating_mul(multiplier)
            .min(maximum.as_secs());
        let seconds_i64 = i64::try_from(seconds).unwrap_or(i64::MAX);
        let until = Utc::now() + ChronoDuration::seconds(seconds_i64);
        self.set_sync_states(&[
            (count_key.as_str(), count.to_string()),
            (until_key.as_str(), until.to_rfc3339()),
        ])
        .await?;
        Ok(until)
    }

    pub async fn clear_source_failure(&self, source_id: &str) -> Result<()> {
        self.delete_sync_states(&[
            format!("source:{source_id}:failure_count"),
            format!("source:{source_id}:backoff_until"),
        ])
        .await
    }

    pub async fn get_source_cache(&self, source_id: &str) -> Result<Option<SourceCacheEntry>> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                "SELECT etag, last_modified, content_hash FROM source_cache WHERE source_id = ?1",
                [source_id],
            )
            .await?;
        let Some(row) = rows.next().await? else {
            return Ok(None);
        };
        Ok(Some(SourceCacheEntry {
            etag: row.get(0)?,
            last_modified: row.get(1)?,
            content_hash: row.get(2)?,
        }))
    }

    pub async fn list_items(&self, filter: &ItemFilter) -> Result<ItemPage> {
        let limit = filter.limit.clamp(1, 200);
        let fetch_limit = limit.saturating_add(1);
        let source = filter.source.as_ref().map(|value| format!("%{value}%"));
        let region = filter.region.as_ref().map(|value| format!("%{value}%"));
        let query = filter.query.as_ref().map(|value| format!("%{value}%"));
        let exploited = filter.exploited.map(bool_to_i64);
        let cursor_timestamp = filter
            .cursor
            .as_ref()
            .map(|cursor| cursor.timestamp.clone());
        let cursor_id = filter.cursor.as_ref().map(|cursor| cursor.id.clone());

        let sql = format!(
            r#"{ITEM_SELECT}
WHERE (?1 IS NULL OR i.kind = ?1)
  AND (?2 IS NULL OR EXISTS (
      SELECT 1 FROM item_categories category_filter
      WHERE category_filter.item_id = i.id AND category_filter.category = ?2
  ))
  AND (?3 IS NULL OR i.severity = ?3)
  AND (?4 IS NULL OR v.confidence = ?4)
  AND (?5 IS NULL OR LOWER(i.source_name) LIKE LOWER(?5))
  AND (?6 IS NULL OR LOWER(i.source_region) LIKE LOWER(?6))
  AND (?7 IS NULL OR LOWER(i.title) LIKE LOWER(?7)
       OR LOWER(i.summary) LIKE LOWER(?7)
       OR LOWER(COALESCE(i.cve_id, '')) LIKE LOWER(?7))
  AND (?8 IS NULL OR i.exploited = ?8)
  AND (?9 IS NULL
       OR COALESCE(i.published_at, i.source_updated_at, i.ingested_at) < ?9
       OR (COALESCE(i.published_at, i.source_updated_at, i.ingested_at) = ?10 AND i.id < ?11))
ORDER BY COALESCE(i.published_at, i.source_updated_at, i.ingested_at) DESC, i.id DESC
LIMIT ?12 OFFSET ?13
"#
        );

        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                &sql,
                params![
                    filter.kind.as_deref(),
                    filter.category.as_deref(),
                    filter.severity.as_deref(),
                    filter.confidence.as_deref(),
                    source.as_deref(),
                    region.as_deref(),
                    query.as_deref(),
                    exploited,
                    cursor_timestamp.as_deref(),
                    cursor_timestamp.as_deref(),
                    cursor_id.as_deref(),
                    i64::try_from(fetch_limit).unwrap_or(201),
                    i64::try_from(if filter.cursor.is_some() {
                        0
                    } else {
                        filter.offset
                    })
                    .unwrap_or(i64::MAX),
                ],
            )
            .await?;

        let mut items = Vec::with_capacity(fetch_limit);
        while let Some(row) = rows.next().await? {
            items.push(item_from_row(&row)?);
        }

        let next_cursor = if items.len() > limit {
            items.pop();
            items.last().map(|item| PageCursor {
                timestamp: item.effective_timestamp.clone(),
                id: item.id.clone(),
            })
        } else {
            None
        };

        Ok(ItemPage {
            items,
            next_cursor: next_cursor.map(|cursor| {
                use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
                URL_SAFE_NO_PAD.encode(serde_json::to_vec(&cursor).unwrap_or_default())
            }),
        })
    }

    pub async fn get_item(&self, id: &str) -> Result<Option<ItemRecord>> {
        self.get_single_item("i.id = ?1", id).await
    }

    pub async fn get_cve_item(&self, cve_id: &str) -> Result<Option<ItemRecord>> {
        self.get_single_item("i.kind = 'cve' AND i.cve_id = ?1", cve_id)
            .await
    }

    async fn get_single_item(&self, predicate: &str, value: &str) -> Result<Option<ItemRecord>> {
        let sql = format!("{ITEM_SELECT} WHERE {predicate} LIMIT 1");
        let connection = self.connection().await?;
        let mut rows = connection.query(&sql, [value]).await?;
        rows.next()
            .await?
            .map(|row| item_from_row(&row))
            .transpose()
    }

    pub async fn get_evidence(&self, cve_id: &str) -> Result<Vec<EvidenceRecord>> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                r#"
SELECT cve_id, source_id, source_name, evidence_type, status, severity, cvss_score,
       exploited, vendor, product, published_at, updated_at, summary, url,
       authoritative, observed_at
FROM cve_evidence
WHERE cve_id = ?1
ORDER BY authoritative DESC, source_name ASC, evidence_type ASC
"#,
                [cve_id],
            )
            .await?;
        let mut evidence = Vec::new();
        while let Some(row) = rows.next().await? {
            evidence.push(EvidenceRecord {
                cve_id: row.get(0)?,
                source_id: row.get(1)?,
                source_name: row.get(2)?,
                evidence_type: row.get(3)?,
                status: row.get(4)?,
                severity: row.get(5)?,
                cvss_score: row.get(6)?,
                exploited: row.get::<Option<i64>>(7)?.map(|value| value != 0),
                vendor: row.get(8)?,
                product: row.get(9)?,
                published_at: row.get(10)?,
                updated_at: row.get(11)?,
                summary: row.get(12)?,
                url: row.get(13)?,
                authoritative: row.get::<i64>(14)? != 0,
                observed_at: row.get(15)?,
            });
        }
        Ok(evidence)
    }

    pub async fn get_validation(&self, cve_id: &str) -> Result<Option<ValidationRecord>> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                r#"
SELECT cve_id, confidence, independent_sources, authoritative_sources,
       severity_disagreement, cvss_disagreement, uncorroborated_exploitation,
       missing_canonical, canonical_status, epss_probability, epss_percentile,
       calculated_at
FROM cve_validation WHERE cve_id = ?1
"#,
                [cve_id],
            )
            .await?;
        let Some(row) = rows.next().await? else {
            return Ok(None);
        };
        Ok(Some(ValidationRecord {
            cve_id: row.get(0)?,
            confidence: row.get(1)?,
            independent_sources: row.get(2)?,
            authoritative_sources: row.get(3)?,
            severity_disagreement: row.get::<i64>(4)? != 0,
            cvss_disagreement: row.get::<i64>(5)? != 0,
            uncorroborated_exploitation: row.get::<i64>(6)? != 0,
            missing_canonical: row.get::<i64>(7)? != 0,
            canonical_status: row.get(8)?,
            epss_probability: row.get(9)?,
            epss_percentile: row.get(10)?,
            calculated_at: row.get(11)?,
        }))
    }

    pub async fn stats(&self) -> Result<Stats> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                r#"
SELECT
    COUNT(*) AS total_items,
    COALESCE(SUM(CASE WHEN kind = 'news' THEN 1 ELSE 0 END), 0) AS news_items,
    COALESCE(SUM(CASE WHEN kind = 'cve' THEN 1 ELSE 0 END), 0) AS cve_items,
    COALESCE(SUM(CASE WHEN kind = 'cve' AND severity = 'critical' THEN 1 ELSE 0 END), 0) AS critical_cves,
    COALESCE(SUM(CASE WHEN kind = 'cve' AND severity = 'high' THEN 1 ELSE 0 END), 0) AS high_cves,
    COALESCE(SUM(CASE WHEN kind = 'cve' AND exploited = 1 THEN 1 ELSE 0 END), 0) AS exploited_cves,
    COALESCE(SUM(CASE WHEN kind = 'cve' AND kev_date_added IS NOT NULL THEN 1 ELSE 0 END), 0) AS kev_cves,
    COALESCE(SUM(CASE WHEN kind = 'cve' AND EXISTS (
        SELECT 1 FROM cve_validation v WHERE v.cve_id = items.cve_id
    ) THEN 1 ELSE 0 END), 0) AS validated_cves,
    COUNT(DISTINCT source_id) AS sources_seen
FROM items
"#,
                (),
            )
            .await?;
        let row = rows
            .next()
            .await?
            .ok_or_else(|| anyhow!("statistics query returned no row"))?;
        let mut stats = Stats {
            total_items: row.get(0)?,
            news_items: row.get(1)?,
            cve_items: row.get(2)?,
            critical_cves: row.get(3)?,
            high_cves: row.get(4)?,
            exploited_cves: row.get(5)?,
            kev_cves: row.get(6)?,
            validated_cves: row.get(7)?,
            sources_seen: row.get(8)?,
            categories: BTreeMap::new(),
            generated_at: now_rfc3339(),
        };

        let mut category_rows = connection
            .query(
                "SELECT category, COUNT(*) FROM item_categories GROUP BY category ORDER BY COUNT(*) DESC",
                (),
            )
            .await?;
        while let Some(category) = category_rows.next().await? {
            stats.categories.insert(category.get(0)?, category.get(1)?);
        }
        Ok(stats)
    }

    pub async fn list_source_health(&self) -> Result<Vec<SourceHealth>> {
        #[derive(Default)]
        struct Aggregate {
            name: String,
            kind: String,
            last_status: String,
            last_run_at: Option<String>,
            last_success_at: Option<String>,
            failures_24h: i64,
            last_error: Option<String>,
        }

        let cutoff = (Utc::now() - ChronoDuration::hours(24)).to_rfc3339();
        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                r#"
SELECT source_id, source_name, source_kind, status, error, finished_at
FROM ingestion_runs
ORDER BY id DESC
LIMIT 10000
"#,
                (),
            )
            .await?;
        let mut aggregates: HashMap<String, Aggregate> = HashMap::new();
        while let Some(row) = rows.next().await? {
            let source_id: String = row.get(0)?;
            let source_name: String = row.get(1)?;
            let source_kind: String = row.get(2)?;
            let status: String = row.get(3)?;
            let error: Option<String> = row.get(4)?;
            let finished_at: String = row.get(5)?;
            let aggregate = aggregates.entry(source_id).or_default();
            if aggregate.last_run_at.is_none() {
                aggregate.name = source_name;
                aggregate.kind = source_kind;
                aggregate.last_status.clone_from(&status);
                aggregate.last_run_at = Some(finished_at.clone());
                aggregate.last_error = error;
            }
            if status == "success" && aggregate.last_success_at.is_none() {
                aggregate.last_success_at = Some(finished_at.clone());
            }
            if status == "failed" && finished_at >= cutoff {
                aggregate.failures_24h += 1;
            }
        }

        let mut health = Vec::with_capacity(aggregates.len());
        for (source_id, aggregate) in aggregates {
            let backoff_until = self
                .get_sync_state(&format!("source:{source_id}:backoff_until"))
                .await?;
            health.push(SourceHealth {
                source_id,
                source_name: aggregate.name,
                source_kind: aggregate.kind,
                last_status: aggregate.last_status,
                last_run_at: aggregate.last_run_at,
                last_success_at: aggregate.last_success_at,
                failures_24h: aggregate.failures_24h,
                last_error: aggregate.last_error,
                backoff_until,
            });
        }
        health.sort_by(|left, right| left.source_name.cmp(&right.source_name));
        Ok(health)
    }

    pub async fn cve_ids_for_validation(&self, limit: usize) -> Result<Vec<String>> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(
                r#"
SELECT i.cve_id
FROM items i
LEFT JOIN cve_validation v ON v.cve_id = i.cve_id
WHERE i.kind = 'cve' AND i.cve_id IS NOT NULL
ORDER BY
    CASE WHEN v.calculated_at IS NULL THEN 0 ELSE 1 END,
    v.calculated_at ASC,
    COALESCE(i.source_updated_at, i.published_at, i.ingested_at) DESC
LIMIT ?1
"#,
                [i64::try_from(limit).unwrap_or(i64::MAX)],
            )
            .await?;
        let mut ids = Vec::new();
        while let Some(row) = rows.next().await? {
            ids.push(row.get(0)?);
        }
        Ok(ids)
    }

    pub async fn cleanup_retention(
        &self,
        news_retention_days: i64,
        ingestion_run_retention_days: i64,
    ) -> Result<()> {
        let _guard = self.write_gate.lock().await;
        let connection = self.connection().await?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .await?;
        if news_retention_days > 0 {
            let cutoff = (Utc::now() - ChronoDuration::days(news_retention_days)).to_rfc3339();
            transaction
                .execute(
                    "DELETE FROM items WHERE kind = 'news' AND COALESCE(published_at, source_updated_at, ingested_at) < ?1",
                    [cutoff],
                )
                .await?;
        }
        let run_cutoff =
            (Utc::now() - ChronoDuration::days(ingestion_run_retention_days)).to_rfc3339();
        transaction
            .execute(
                "DELETE FROM ingestion_runs WHERE finished_at < ?1",
                [run_cutoff],
            )
            .await?;
        transaction.commit().await?;
        Ok(())
    }
}

async fn upsert_evidence_in_transaction(
    transaction: &libsql::Transaction,
    evidence: &[EvidenceInput],
) -> Result<()> {
    for record in evidence {
        transaction
            .execute(
                r#"
INSERT INTO cve_evidence (
    cve_id, source_id, source_name, evidence_type, status, severity, cvss_score,
    exploited, vendor, product, published_at, updated_at, summary, url, raw_json,
    authoritative, observed_at
) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17)
ON CONFLICT(cve_id, source_id, evidence_type) DO UPDATE SET
    source_name = excluded.source_name,
    status = excluded.status,
    severity = excluded.severity,
    cvss_score = excluded.cvss_score,
    exploited = excluded.exploited,
    vendor = excluded.vendor,
    product = excluded.product,
    published_at = excluded.published_at,
    updated_at = excluded.updated_at,
    summary = excluded.summary,
    url = excluded.url,
    raw_json = excluded.raw_json,
    authoritative = excluded.authoritative,
    observed_at = excluded.observed_at
"#,
                params![
                    record.cve_id.as_str(),
                    record.source_id.as_str(),
                    record.source_name.as_str(),
                    record.evidence_type.as_str(),
                    record.status.as_deref(),
                    record.severity.as_deref(),
                    record.cvss_score,
                    record.exploited.map(bool_to_i64),
                    record.vendor.as_deref(),
                    record.product.as_deref(),
                    record.published_at.as_deref(),
                    record.updated_at.as_deref(),
                    record.summary.as_deref(),
                    record.url.as_deref(),
                    record.raw_json.as_deref(),
                    bool_to_i64(record.authoritative),
                    record.observed_at.as_str(),
                ],
            )
            .await?;
    }
    Ok(())
}

fn item_from_row(row: &Row) -> Result<ItemRecord> {
    let categories: String = row.get(24)?;
    Ok(ItemRecord {
        id: row.get(0)?,
        kind: row.get(1)?,
        cve_id: row.get(2)?,
        title: row.get(3)?,
        summary: row.get(4)?,
        url: row.get(5)?,
        source_id: row.get(6)?,
        source_name: row.get(7)?,
        source_region: row.get(8)?,
        source_language: row.get(9)?,
        source_trust: row.get(10)?,
        severity: row.get(11)?,
        cvss_score: row.get(12)?,
        published_at: row.get(13)?,
        source_updated_at: row.get(14)?,
        ingested_at: row.get(15)?,
        effective_timestamp: row.get(16)?,
        exploited: row.get::<i64>(17)? != 0,
        kev_date_added: row.get(18)?,
        remediation: row.get(19)?,
        due_date: row.get(20)?,
        ransomware_use: row.get(21)?,
        vendor: row.get(22)?,
        product: row.get(23)?,
        categories: categories
            .split(char::from(31))
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
            .collect(),
        confidence: row.get(25)?,
        independent_sources: row.get(26)?,
        authoritative_sources: row.get(27)?,
        severity_disagreement: row.get::<Option<i64>>(28)?.map(|value| value != 0),
        cvss_disagreement: row.get::<Option<i64>>(29)?.map(|value| value != 0),
        uncorroborated_exploitation: row.get::<Option<i64>>(30)?.map(|value| value != 0),
        epss_probability: row.get(31)?,
        epss_percentile: row.get(32)?,
    })
}

const fn bool_to_i64(value: bool) -> i64 {
    if value { 1 } else { 0 }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{classifier, models::ItemInput};

    #[tokio::test]
    async fn stores_and_reads_an_item() {
        let directory = tempfile::tempdir().expect("temp directory");
        let repository = Repository::open(&directory.path().join("test.db"))
            .await
            .expect("open repository");
        let item = ItemInput {
            id: "cve:CVE-2026-1234".into(),
            kind: "cve".into(),
            cve_id: Some("CVE-2026-1234".into()),
            title: "Test vulnerability".into(),
            summary: "A test".into(),
            url: "https://example.com/CVE-2026-1234".into(),
            source_id: "test".into(),
            source_name: "Test".into(),
            source_region: "Global".into(),
            source_language: "en".into(),
            source_trust: 3,
            severity: Some("high".into()),
            cvss_score: Some(8.0),
            published_at: Some(now_rfc3339()),
            source_updated_at: None,
            ingested_at: now_rfc3339(),
            exploited: false,
            kev_date_added: None,
            remediation: None,
            due_date: None,
            ransomware_use: None,
            vendor: Some("Example".into()),
            product: Some("Product".into()),
            raw_json: None,
            content_hash: classifier::content_hash(b"test"),
            categories: vec!["patching".into()],
            cves: vec!["CVE-2026-1234".into()],
        };
        repository
            .apply_batch(&IngestBatch {
                items: vec![item],
                ..IngestBatch::default()
            })
            .await
            .expect("apply batch");
        let stored = repository
            .get_cve_item("CVE-2026-1234")
            .await
            .expect("query")
            .expect("stored item");
        assert_eq!(stored.severity.as_deref(), Some("high"));
    }
}
