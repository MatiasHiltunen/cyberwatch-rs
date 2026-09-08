use std::collections::HashMap;

use anyhow::{Result, anyhow};
use serde_json::Value;

use crate::{
    ingest::{
        http::{FetchPolicy, parse_json, send_limited},
        source::SourceContext,
    },
    models::EpssScore,
};

pub async fn fetch_scores(
    context: &SourceContext,
    cve_ids: &[String],
) -> Result<HashMap<String, EpssScore>> {
    let mut scores = HashMap::new();
    for chunk in cve_ids.chunks(100) {
        let query = chunk.join(",");
        let response = send_limited(
            context
                .http
                .get("https://api.first.org/data/v1/epss")
                .query(&[("cve", query.as_str())]),
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
        let payload: Value = parse_json(&response, "FIRST EPSS response")?;
        let rows = payload
            .get("data")
            .and_then(Value::as_array)
            .ok_or_else(|| anyhow!("invalid FIRST EPSS response: data array is missing"))?;
        for row in rows {
            let Some(cve) = row.get("cve").and_then(Value::as_str) else {
                continue;
            };
            let probability = number(row.get("epss"));
            let percentile = number(row.get("percentile"));
            if let (Some(probability), Some(percentile)) = (probability, percentile) {
                if (0.0..=1.0).contains(&probability) && (0.0..=1.0).contains(&percentile) {
                    scores.insert(
                        cve.to_ascii_uppercase(),
                        EpssScore {
                            probability,
                            percentile,
                        },
                    );
                }
            }
        }
    }
    Ok(scores)
}

fn number(value: Option<&Value>) -> Option<f64> {
    value.and_then(|value| {
        value
            .as_f64()
            .or_else(|| value.as_str().and_then(|text| text.parse().ok()))
    })
}
