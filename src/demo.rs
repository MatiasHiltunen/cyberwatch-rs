//! Deterministic fictional data for disconnected teaching, smoke tests and DAST.
use anyhow::{Result, bail};

use crate::{
    Repository,
    classifier::content_hash,
    models::{EvidenceInput, IngestBatch, ItemInput, SyncUpdate, ValidationInput},
};

const MODE_KEY: &str = "application:data-mode";
const DATE: &str = "2026-09-01T12:00:00Z";

pub async fn prepare(repository: &Repository, enabled: bool) -> Result<()> {
    let existing = repository.get_sync_state(MODE_KEY).await?;
    if existing.as_deref() == Some("demo") && !enabled {
        bail!("demo database cannot be used for live ingestion; choose a separate DATABASE_PATH");
    }
    if !enabled {
        return Ok(());
    }
    if existing.is_none() && repository.stats().await?.total_items != 0 {
        bail!(
            "DEMO_MODE requires a new or existing demo database; choose a separate DATABASE_PATH"
        );
    }
    let mut batch = fixture();
    batch.sync_updates.push(SyncUpdate {
        key: MODE_KEY.into(),
        value: "demo".into(),
    });
    repository.apply_batch(&batch).await?;
    repository
        .upsert_validations(&[ValidationInput {
            cve_id: "CVE-2099-99991".into(),
            confidence: "low".into(),
            independent_sources: 1,
            authoritative_sources: 0,
            severity_disagreement: false,
            cvss_disagreement: false,
            uncorroborated_exploitation: true,
            missing_canonical: true,
            canonical_status: Some("FICTIONAL DEMO".into()),
            epss_probability: None,
            epss_percentile: None,
            calculated_at: DATE.into(),
        }])
        .await?;
    Ok(())
}

pub fn fixture() -> IngestBatch {
    let examples = [
        (
            "demo:cve:critical",
            "cve",
            Some("CVE-2099-99991"),
            "critical",
            "Fictional gateway authorization bypass",
            "access-control",
            true,
        ),
        (
            "demo:cve:high",
            "cve",
            Some("CVE-2099-99992"),
            "high",
            "Fictional build runner dependency flaw",
            "supply-chain",
            false,
        ),
        (
            "demo:news:patch",
            "news",
            None,
            "medium",
            "Fictional team rolls out a verified patch",
            "patching",
            false,
        ),
        (
            "demo:news:exercise",
            "news",
            None,
            "low",
            "Fictional incident response rehearsal completed",
            "incident-response",
            false,
        ),
    ];
    let items = examples.into_iter().map(|(id, kind, cve, severity, title, category, exploited)| ItemInput {
        id: id.into(), kind: kind.into(), cve_id: cve.map(str::to_owned),
        title: format!("[DEMO] {title}"),
        summary: "Fictional classroom fixture. This is not a real vulnerability or security advisory.".into(),
        url: "https://example.invalid/fictional-training-record".into(),
        source_id: "demo-fixture".into(), source_name: "Fictional training fixtures".into(),
        source_region: "Finland".into(), source_language: "en".into(), source_trust: 1,
        severity: Some(severity.into()), cvss_score: cve.map(|_| if exploited { 9.1 } else { 7.5 }),
        published_at: Some(DATE.into()), source_updated_at: Some(DATE.into()), ingested_at: DATE.into(),
        exploited, kev_date_added: None, remediation: Some("Training exercise: verify and deploy a simulated patch.".into()),
        due_date: None, ransomware_use: None, vendor: Some("Fictional Example Systems".into()),
        product: Some("Training application".into()), raw_json: None,
        content_hash: content_hash(id.as_bytes()), categories: vec![category.into()],
        cves: cve.map(|value| vec![value.into()]).unwrap_or_default(),
    }).collect();
    IngestBatch {
        items,
        evidence: vec![EvidenceInput {
            cve_id: "CVE-2099-99991".into(),
            source_id: "demo-fixture".into(),
            source_name: "Fictional training fixtures".into(),
            evidence_type: "classroom-fixture".into(),
            status: Some("FICTIONAL DEMO".into()),
            severity: Some("critical".into()),
            cvss_score: Some(9.1),
            exploited: Some(true),
            vendor: Some("Fictional Example Systems".into()),
            product: None,
            published_at: Some(DATE.into()),
            updated_at: None,
            summary: Some("Fictional evidence for training; no real exploitation claim.".into()),
            url: Some("https://example.invalid/fictional-evidence".into()),
            raw_json: None,
            authoritative: false,
            observed_at: DATE.into(),
        }],
        ..IngestBatch::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn demo_is_idempotent_and_cannot_become_live() {
        let directory = tempfile::tempdir().unwrap();
        let repository = Repository::open(&directory.path().join("test.db"))
            .await
            .unwrap();
        prepare(&repository, true).await.unwrap();
        prepare(&repository, true).await.unwrap();
        assert_eq!(repository.stats().await.unwrap().total_items, 4);
        assert!(prepare(&repository, false).await.is_err());
    }

    #[tokio::test]
    async fn demo_does_not_contaminate_existing_data() {
        let directory = tempfile::tempdir().unwrap();
        let repository = Repository::open(&directory.path().join("test.db"))
            .await
            .unwrap();
        repository.apply_batch(&fixture()).await.unwrap();
        assert!(prepare(&repository, true).await.is_err());
    }
}
