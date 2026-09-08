use std::collections::{BTreeSet, HashMap, HashSet};

use anyhow::{Result, anyhow};
use futures::{StreamExt, stream};
use serde_json::Value;

use crate::{
    classifier::normalize_severity,
    ingest::{
        epss,
        http::{FetchPolicy, parse_json, send_limited},
        source::SourceContext,
    },
    models::{EvidenceInput, EvidenceRecord, ValidationInput, now_rfc3339},
};

#[derive(Debug, Clone, Default)]
pub struct ValidationSummary {
    pub validated: usize,
    pub warnings: Vec<String>,
}

pub async fn run(context: &SourceContext) -> Result<ValidationSummary> {
    let cve_ids = context
        .repository
        .cve_ids_for_validation(context.config.validation_batch_size)
        .await?;
    if cve_ids.is_empty() {
        return Ok(ValidationSummary::default());
    }

    let concurrency = context.config.validation_concurrency;
    let canonical_results = stream::iter(cve_ids.iter().cloned().map(|cve_id| {
        let context = context.clone();
        async move {
            let result = fetch_canonical_evidence(&context, &cve_id).await;
            (cve_id, result)
        }
    }))
    .buffer_unordered(concurrency)
    .collect::<Vec<_>>()
    .await;

    let mut canonical_evidence = Vec::new();
    let mut warnings = Vec::new();
    for (cve_id, result) in canonical_results {
        match result {
            Ok(Some(evidence)) => canonical_evidence.push(evidence),
            Ok(None) => {}
            Err(error) => warnings.push(format!(
                "CVE Program validation failed for {cve_id}: {error:#}"
            )),
        }
    }
    context
        .repository
        .upsert_evidence(&canonical_evidence)
        .await?;

    let epss_scores = match epss::fetch_scores(context, &cve_ids).await {
        Ok(scores) => scores,
        Err(error) => {
            warnings.push(format!("FIRST EPSS enrichment failed: {error:#}"));
            HashMap::new()
        }
    };

    let evidence_results = stream::iter(cve_ids.iter().cloned().map(|cve_id| {
        let repository = context.repository.clone();
        async move {
            let result = repository.get_evidence(&cve_id).await;
            (cve_id, result)
        }
    }))
    .buffer_unordered(concurrency)
    .collect::<Vec<_>>()
    .await;

    let mut validations = Vec::with_capacity(evidence_results.len());
    for (cve_id, evidence) in evidence_results {
        match evidence {
            Ok(evidence) => validations.push(calculate_validation(
                &cve_id,
                &evidence,
                epss_scores.get(&cve_id).copied(),
            )),
            Err(error) => warnings.push(format!("evidence query failed for {cve_id}: {error:#}")),
        }
    }
    context.repository.upsert_validations(&validations).await?;

    Ok(ValidationSummary {
        validated: validations.len(),
        warnings,
    })
}

async fn fetch_canonical_evidence(
    context: &SourceContext,
    cve_id: &str,
) -> Result<Option<EvidenceInput>> {
    let url = format!("https://cveawg.mitre.org/api/cve/{cve_id}");
    let response = send_limited(
        context.http.get(&url),
        &FetchPolicy {
            timeout: context.config.source_timeout,
            retries: context.config.source_retry_attempts,
            max_bytes: context
                .config
                .max_source_response_bytes
                .min(8 * 1_024 * 1_024),
            allow_not_modified: false,
        },
    )
    .await?;
    let payload: Value = parse_json(&response, "CVE Program record")?;
    let record_id = payload
        .pointer("/cveMetadata/cveId")
        .and_then(Value::as_str)
        .unwrap_or(cve_id)
        .to_ascii_uppercase();
    if record_id != cve_id {
        return Err(anyhow!(
            "CVE Program returned record {record_id} for {cve_id}"
        ));
    }

    let status = payload
        .pointer("/cveMetadata/state")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let published_at = payload
        .pointer("/cveMetadata/datePublished")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let updated_at = payload
        .pointer("/cveMetadata/dateUpdated")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let cna = payload.pointer("/containers/cna");
    let summary = cna
        .and_then(|value| value.get("descriptions"))
        .and_then(Value::as_array)
        .and_then(|values| {
            values
                .iter()
                .find(|value| value.get("lang").and_then(Value::as_str) == Some("en"))
                .or_else(|| values.first())
        })
        .and_then(|value| value.get("value"))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let affected = cna
        .and_then(|value| value.get("affected"))
        .and_then(Value::as_array)
        .and_then(|values| values.first());
    let vendor = affected
        .and_then(|value| value.get("vendor"))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let product = affected
        .and_then(|value| value.get("product"))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let reference_url = cna
        .and_then(|value| value.get("references"))
        .and_then(Value::as_array)
        .and_then(|values| values.first())
        .and_then(|value| value.get("url"))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
        .unwrap_or(url);

    Ok(Some(EvidenceInput {
        cve_id: record_id,
        source_id: "cve-program".into(),
        source_name: "CVE Program canonical record".into(),
        evidence_type: "canonical-record".into(),
        status,
        severity: None,
        cvss_score: None,
        exploited: None,
        vendor,
        product,
        published_at,
        updated_at,
        summary,
        url: Some(reference_url),
        raw_json: serde_json::to_string(&payload).ok(),
        authoritative: true,
        observed_at: now_rfc3339(),
    }))
}

fn calculate_validation(
    cve_id: &str,
    evidence: &[EvidenceRecord],
    epss: Option<crate::models::EpssScore>,
) -> ValidationInput {
    let sources: HashSet<&str> = evidence
        .iter()
        .map(|record| record.source_id.as_str())
        .collect();
    let authoritative: HashSet<&str> = evidence
        .iter()
        .filter(|record| record.authoritative)
        .map(|record| record.source_id.as_str())
        .collect();
    let severities: BTreeSet<String> = evidence
        .iter()
        .filter_map(|record| record.severity.as_deref())
        .filter_map(normalize_severity)
        .collect();
    let scores: Vec<f64> = evidence
        .iter()
        .filter_map(|record| record.cvss_score)
        .collect();
    let score_range = scores
        .iter()
        .copied()
        .fold(None, |range, score| match range {
            None => Some((score, score)),
            Some((minimum, maximum)) => Some((minimum.min(score), maximum.max(score))),
        });
    let exploitation_claim = evidence.iter().any(|record| record.exploited == Some(true));
    let cisa_corroboration = evidence
        .iter()
        .any(|record| record.source_id == "cisa-kev" && record.exploited == Some(true));
    let canonical = evidence
        .iter()
        .find(|record| record.source_id == "cve-program");
    let canonical_status = canonical.and_then(|record| record.status.clone());
    let rejected = canonical_status
        .as_deref()
        .is_some_and(|status| status.eq_ignore_ascii_case("REJECTED"));
    let independent_sources = i64::try_from(sources.len()).unwrap_or(i64::MAX);
    let authoritative_sources = i64::try_from(authoritative.len()).unwrap_or(i64::MAX);

    let confidence = if rejected {
        "rejected"
    } else if authoritative_sources >= 2 && independent_sources >= 3 {
        "very-high"
    } else if authoritative_sources >= 2 || (authoritative_sources >= 1 && independent_sources >= 3)
    {
        "high"
    } else if authoritative_sources >= 1 || independent_sources >= 2 {
        "medium"
    } else {
        "low"
    };

    ValidationInput {
        cve_id: cve_id.to_owned(),
        confidence: confidence.to_owned(),
        independent_sources,
        authoritative_sources,
        severity_disagreement: severities.len() > 1,
        cvss_disagreement: score_range.is_some_and(|(minimum, maximum)| maximum - minimum >= 1.0),
        uncorroborated_exploitation: exploitation_claim && !cisa_corroboration,
        missing_canonical: canonical.is_none(),
        canonical_status,
        epss_probability: epss.map(|score| score.probability),
        epss_percentile: epss.map(|score| score.percentile),
        calculated_at: now_rfc3339(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence(source: &str, authoritative: bool, severity: Option<&str>) -> EvidenceRecord {
        EvidenceRecord {
            cve_id: "CVE-2026-1234".into(),
            source_id: source.into(),
            source_name: source.into(),
            evidence_type: "test".into(),
            status: None,
            severity: severity.map(ToOwned::to_owned),
            cvss_score: None,
            exploited: None,
            vendor: None,
            product: None,
            published_at: None,
            updated_at: None,
            summary: None,
            url: None,
            authoritative,
            observed_at: now_rfc3339(),
        }
    }

    #[test]
    fn epss_does_not_increase_source_confidence() {
        let validation = calculate_validation(
            "CVE-2026-1234",
            &[evidence("community", false, None)],
            Some(crate::models::EpssScore {
                probability: 0.99,
                percentile: 0.999,
            }),
        );
        assert_eq!(validation.confidence, "low");
        assert_eq!(validation.independent_sources, 1);
    }

    #[test]
    fn detects_severity_disagreement() {
        let validation = calculate_validation(
            "CVE-2026-1234",
            &[
                evidence("nvd", true, Some("critical")),
                evidence("vendor", false, Some("medium")),
            ],
            None,
        );
        assert!(validation.severity_disagreement);
    }
}
