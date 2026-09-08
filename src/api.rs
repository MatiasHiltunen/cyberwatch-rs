use std::{
    collections::{BTreeMap, HashMap},
    sync::{Arc, Mutex as StdMutex},
    time::Duration,
};

use axum::{
    Json, Router,
    body::Body,
    extract::{DefaultBodyLimit, MatchedPath, Path, Query, State, rejection::QueryRejection},
    http::{HeaderMap, HeaderName, HeaderValue, Request, StatusCode, header},
    middleware::{Next, from_fn, from_fn_with_state},
    response::{IntoResponse, Response},
    routing::{any, get, post},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tokio::sync::{Mutex, Semaphore};
use tower_http::{
    compression::CompressionLayer,
    request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer},
    services::{ServeDir, ServeFile},
    trace::TraceLayer,
};
use tracing::error;
use url::Url;

use crate::{
    Config, Repository,
    db::ItemFilter,
    models::{
        CveDetail, PageCursor, RefreshAccepted, SourceDescriptor, SourceHealth, Stats,
        ValidationRecord,
    },
    refresh::RefreshCoordinator,
};

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub repository: Repository,
    pub refresh: RefreshCoordinator,
    pub source_descriptors: Arc<Vec<SourceDescriptor>>,
    stats_cache: Arc<Mutex<Option<(tokio::time::Instant, Stats)>>>,
    metrics: Arc<StdMutex<BTreeMap<(String, u16), Observation>>>,
    admission: Arc<Semaphore>,
}

impl AppState {
    pub fn new(
        config: Arc<Config>,
        repository: Repository,
        refresh: RefreshCoordinator,
        source_descriptors: Vec<SourceDescriptor>,
    ) -> Self {
        Self {
            config,
            repository,
            refresh,
            source_descriptors: Arc::new(source_descriptors),
            stats_cache: Arc::new(Mutex::new(None)),
            metrics: Arc::new(StdMutex::new(BTreeMap::new())),
            admission: Arc::new(Semaphore::new(64)),
        }
    }
}

pub fn router(state: AppState) -> Router {
    let web_dir = state.config.web_dir.clone();
    let index_path = web_dir.join("index.html");
    let static_files = ServeDir::new(web_dir).not_found_service(ServeFile::new(index_path));
    let request_id_header = HeaderName::from_static("x-request-id");

    Router::new()
        .route("/health", get(health))
        .route("/ready", get(ready))
        .route("/metrics", get(metrics))
        .route("/api/v1/items", get(list_items))
        .route("/api/v1/items/{id}", get(get_item))
        .route("/api/v1/cves/{cve_id}", get(get_cve))
        .route("/api/v1/cves/{cve_id}/evidence", get(get_cve_evidence))
        .route("/api/v1/stats", get(stats))
        .route("/api/v1/sources", get(sources))
        .route("/api/v1/refresh", post(refresh))
        .route("/api/v1/refresh/status", get(refresh_status))
        .route("/api", any(api_not_found))
        .route("/api/{*path}", any(api_not_found))
        .fallback_service(static_files)
        .layer(DefaultBodyLimit::max(64 * 1_024))
        .layer(from_fn_with_state(state.clone(), observe_and_bound))
        .layer(CompressionLayer::new())
        .layer(PropagateRequestIdLayer::new(request_id_header.clone()))
        .layer(SetRequestIdLayer::new(request_id_header, MakeRequestUuid))
        .layer(TraceLayer::new_for_http().make_span_with(|request: &Request<Body>| {
            tracing::info_span!("http_request", method = %request.method(),
                route = request.extensions().get::<MatchedPath>().map(MatchedPath::as_str).unwrap_or("static"))
        }))
        .layer(from_fn(security_headers))
        .with_state(state)
}

#[derive(Default)]
struct Observation {
    count: u64,
    seconds: f64,
    buckets: [u64; 6],
}
const BUCKETS: [f64; 6] = [0.005, 0.025, 0.1, 0.5, 1.0, 10.0];

async fn observe_and_bound(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    // Only router templates and a single static fallback label enter the metric map.
    let route = request
        .extensions()
        .get::<MatchedPath>()
        .map(MatchedPath::as_str)
        .unwrap_or("static")
        .to_owned();
    let probe = matches!(request.uri().path(), "/health" | "/ready" | "/metrics");
    let started = tokio::time::Instant::now();
    let permit = if probe {
        None
    } else {
        state.admission.try_acquire().ok()
    };
    let response = if !probe && permit.is_none() {
        ApiError::unavailable("server is busy; retry later").into_response()
    } else if request.uri().to_string().len() > 4096 {
        ApiError::bad_request("request URI is too long").into_response()
    } else {
        match tokio::time::timeout(
            Duration::from_secs(if probe { 2 } else { 10 }),
            next.run(request),
        )
        .await
        {
            Ok(response) => response,
            Err(_) => ApiError::unavailable("request deadline exceeded").into_response(),
        }
    };
    let seconds = started.elapsed().as_secs_f64();
    if let Ok(mut metrics) = state.metrics.lock() {
        let metric = metrics
            .entry((route, response.status().as_u16() / 100))
            .or_default();
        metric.count += 1;
        metric.seconds += seconds;
        for (index, bound) in BUCKETS.iter().enumerate() {
            if seconds <= *bound {
                metric.buckets[index] += 1;
            }
        }
    }
    response
}

async fn metrics(State(state): State<AppState>) -> Response {
    use std::fmt::Write;
    let mut output = String::from(
        "# HELP cyberwatch_http_requests_total HTTP responses by route and status class.\n# TYPE cyberwatch_http_requests_total counter\n# HELP cyberwatch_http_request_duration_seconds Request handler latency.\n# TYPE cyberwatch_http_request_duration_seconds histogram\n",
    );
    if let Ok(metrics) = state.metrics.lock() {
        for ((route, status), metric) in metrics.iter() {
            let labels = format!("route=\"{route}\",status_class=\"{status}xx\"");
            let _ = writeln!(
                output,
                "cyberwatch_http_requests_total{{{labels}}} {}",
                metric.count
            );
            let _ = writeln!(
                output,
                "cyberwatch_http_request_duration_seconds_sum{{{labels}}} {}",
                metric.seconds
            );
            let _ = writeln!(
                output,
                "cyberwatch_http_request_duration_seconds_count{{{labels}}} {}",
                metric.count
            );
            for (index, bound) in BUCKETS.iter().enumerate() {
                let _ = writeln!(
                    output,
                    "cyberwatch_http_request_duration_seconds_bucket{{{labels},le=\"{bound}\"}} {}",
                    metric.buckets[index]
                );
            }
            let _ = writeln!(
                output,
                "cyberwatch_http_request_duration_seconds_bucket{{{labels},le=\"+Inf\"}} {}",
                metric.count
            );
        }
    }
    output.push_str("# HELP cyberwatch_refresh_enabled Whether outbound refresh is enabled.\n# TYPE cyberwatch_refresh_enabled gauge\n");
    let _ = writeln!(
        output,
        "cyberwatch_refresh_enabled {}",
        u8::from(state.config.refresh_allowed())
    );
    (
        [(
            header::CONTENT_TYPE,
            "text/plain; version=0.0.4; charset=utf-8",
        )],
        output,
    )
        .into_response()
}

async fn health(State(state): State<AppState>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "version": env!("CARGO_PKG_VERSION"),
        "demo_mode": state.config.demo_mode,
        "refresh_enabled": state.config.refresh_allowed()
    }))
}

async fn ready(State(state): State<AppState>) -> Result<Json<serde_json::Value>, ApiError> {
    state.repository.ready().await.map_err(|error| {
        error!(error = %error, "database readiness probe failed");
        ApiError::unavailable("database is not ready")
    })?;
    Ok(Json(serde_json::json!({"status": "ready"})))
}

#[derive(Debug, Deserialize)]
struct ItemQuery {
    kind: Option<String>,
    category: Option<String>,
    severity: Option<String>,
    confidence: Option<String>,
    source: Option<String>,
    region: Option<String>,
    q: Option<String>,
    exploited: Option<bool>,
    limit: Option<usize>,
    offset: Option<usize>,
    cursor: Option<String>,
}

async fn list_items(
    State(state): State<AppState>,
    query: Result<Query<ItemQuery>, QueryRejection>,
) -> Result<Json<crate::models::ItemPage>, ApiError> {
    let Query(query) = query.map_err(|_| ApiError::bad_request("invalid query parameters"))?;
    let filter = validate_item_query(query)?;
    state
        .repository
        .list_items(&filter)
        .await
        .map(Json)
        .map_err(|error| ApiError::internal("failed to query intelligence items", error))
}

async fn get_item(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<crate::models::ItemRecord>, ApiError> {
    if id.is_empty() || id.len() > 240 {
        return Err(ApiError::bad_request("invalid item ID"));
    }
    state
        .repository
        .get_item(&id)
        .await
        .map_err(|error| ApiError::internal("failed to query item", error))?
        .map(Json)
        .ok_or_else(|| ApiError::not_found("item not found"))
}

async fn get_cve(
    State(state): State<AppState>,
    Path(cve_id): Path<String>,
) -> Result<Json<CveDetail>, ApiError> {
    let cve_id = validate_cve_id(&cve_id)?;
    let item = state
        .repository
        .get_cve_item(&cve_id)
        .await
        .map_err(|error| ApiError::internal("failed to query CVE", error))?
        .ok_or_else(|| ApiError::not_found("CVE not found"))?;
    let evidence = state
        .repository
        .get_evidence(&cve_id)
        .await
        .map_err(|error| ApiError::internal("failed to query CVE evidence", error))?;
    let validation = state
        .repository
        .get_validation(&cve_id)
        .await
        .map_err(|error| ApiError::internal("failed to query CVE validation", error))?;
    Ok(Json(CveDetail {
        item,
        evidence,
        validation,
    }))
}

#[derive(Serialize)]
struct EvidenceResponse {
    cve_id: String,
    evidence: Vec<crate::models::EvidenceRecord>,
    validation: Option<ValidationRecord>,
}

async fn get_cve_evidence(
    State(state): State<AppState>,
    Path(cve_id): Path<String>,
) -> Result<Json<EvidenceResponse>, ApiError> {
    let cve_id = validate_cve_id(&cve_id)?;
    let evidence = state
        .repository
        .get_evidence(&cve_id)
        .await
        .map_err(|error| ApiError::internal("failed to query CVE evidence", error))?;
    if evidence.is_empty() {
        return Err(ApiError::not_found("CVE evidence not found"));
    }
    let validation = state
        .repository
        .get_validation(&cve_id)
        .await
        .map_err(|error| ApiError::internal("failed to query CVE validation", error))?;
    Ok(Json(EvidenceResponse {
        cve_id,
        evidence,
        validation,
    }))
}

async fn stats(State(state): State<AppState>) -> Result<Json<Stats>, ApiError> {
    {
        let cache = state.stats_cache.lock().await;
        if let Some((generated, stats)) = cache.as_ref() {
            if generated.elapsed() < Duration::from_secs(10) {
                return Ok(Json(stats.clone()));
            }
        }
    }

    let stats = state
        .repository
        .stats()
        .await
        .map_err(|error| ApiError::internal("failed to calculate statistics", error))?;
    *state.stats_cache.lock().await = Some((tokio::time::Instant::now(), stats.clone()));
    Ok(Json(stats))
}

async fn sources(State(state): State<AppState>) -> Result<Json<Vec<SourceHealth>>, ApiError> {
    let existing = state
        .repository
        .list_source_health()
        .await
        .map_err(|error| ApiError::internal("failed to query source health", error))?;
    let mut by_id: HashMap<String, SourceHealth> = existing
        .into_iter()
        .map(|health| (health.source_id.clone(), health))
        .collect();
    for descriptor in state.source_descriptors.iter() {
        by_id
            .entry(descriptor.id.clone())
            .or_insert_with(|| SourceHealth {
                source_id: descriptor.id.clone(),
                source_name: descriptor.name.clone(),
                source_kind: descriptor.kind.clone(),
                last_status: "never".into(),
                last_run_at: None,
                last_success_at: None,
                failures_24h: 0,
                last_error: None,
                backoff_until: None,
            });
    }
    let mut sources: Vec<_> = by_id.into_values().collect();
    for source in &mut sources {
        if source.last_error.is_some() {
            source.last_error = Some("source failed; inspect server logs".into());
        }
    }
    sources.sort_by(|left, right| left.source_name.cmp(&right.source_name));
    Ok(Json(sources))
}

async fn refresh(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<(StatusCode, Json<RefreshAccepted>), ApiError> {
    if !state.config.refresh_allowed() {
        return Err(ApiError::unavailable("refresh is disabled"));
    }
    authorize_refresh(&headers, &state.config)?;
    let accepted = state
        .refresh
        .request("manual-api")
        .await
        .map_err(|error| ApiError::internal("failed to enqueue refresh", error))?;
    Ok((StatusCode::ACCEPTED, Json(accepted)))
}

async fn refresh_status(State(state): State<AppState>) -> Json<crate::models::RefreshStatus> {
    let mut status = state.refresh.status().await;
    if status.error.is_some() {
        status.error = Some("refresh failed; inspect server logs".into());
    }
    if let Some(report) = &mut status.report {
        for error in &mut report.errors {
            *error = "source stage failed; inspect server logs".into();
        }
    }
    Json(status)
}

async fn api_not_found() -> ApiError {
    ApiError::not_found("API route not found")
}

fn validate_item_query(query: ItemQuery) -> Result<ItemFilter, ApiError> {
    validate_enum("kind", query.kind.as_deref(), &["news", "cve"])?;
    validate_enum(
        "severity",
        query.severity.as_deref(),
        &["critical", "high", "medium", "low", "none", "unknown"],
    )?;
    validate_enum(
        "confidence",
        query.confidence.as_deref(),
        &["very-high", "high", "medium", "low", "rejected"],
    )?;
    validate_length("category", query.category.as_deref(), 80)?;
    validate_length("source", query.source.as_deref(), 120)?;
    validate_length("region", query.region.as_deref(), 120)?;
    validate_length("q", query.q.as_deref(), 240)?;

    let limit = query.limit.unwrap_or(50);
    if !(1..=200).contains(&limit) {
        return Err(ApiError::bad_request("limit must be between 1 and 200"));
    }
    let offset = query.offset.unwrap_or(0);
    if offset > 10_000 {
        return Err(ApiError::bad_request(
            "offset is too large; use cursor pagination",
        ));
    }
    let cursor = query.cursor.as_deref().map(decode_cursor).transpose()?;

    Ok(ItemFilter {
        kind: query.kind,
        category: query.category,
        severity: query.severity,
        confidence: query.confidence,
        source: query.source,
        region: query.region,
        query: query.q,
        exploited: query.exploited,
        limit,
        offset,
        cursor,
    })
}

fn decode_cursor(value: &str) -> Result<PageCursor, ApiError> {
    if value.len() > 1_024 {
        return Err(ApiError::bad_request("cursor is too long"));
    }
    let bytes = URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| ApiError::bad_request("cursor is invalid"))?;
    let cursor: PageCursor =
        serde_json::from_slice(&bytes).map_err(|_| ApiError::bad_request("cursor is invalid"))?;
    if chrono::DateTime::parse_from_rfc3339(&cursor.timestamp).is_err()
        || cursor.id.is_empty()
        || cursor.id.len() > 240
    {
        return Err(ApiError::bad_request("cursor is invalid"));
    }
    Ok(cursor)
}

fn validate_enum(name: &str, value: Option<&str>, allowed: &[&str]) -> Result<(), ApiError> {
    if value.is_some_and(|value| !allowed.contains(&value)) {
        return Err(ApiError::bad_request(format!("invalid {name} filter")));
    }
    Ok(())
}

fn validate_length(name: &str, value: Option<&str>, maximum: usize) -> Result<(), ApiError> {
    if value.is_some_and(|value| value.is_empty() || value.len() > maximum) {
        return Err(ApiError::bad_request(format!("invalid {name} filter")));
    }
    Ok(())
}

fn validate_cve_id(value: &str) -> Result<String, ApiError> {
    let value = value.to_ascii_uppercase();
    let Some(rest) = value.strip_prefix("CVE-") else {
        return Err(ApiError::bad_request("invalid CVE ID"));
    };
    let mut parts = rest.split('-');
    match (parts.next(), parts.next(), parts.next()) {
        (Some(year), Some(sequence), None)
            if year.len() == 4
                && year.bytes().all(|byte| byte.is_ascii_digit())
                && (4..=8).contains(&sequence.len())
                && sequence.bytes().all(|byte| byte.is_ascii_digit()) =>
        {
            Ok(value)
        }
        _ => Err(ApiError::bad_request("invalid CVE ID")),
    }
}

fn authorize_refresh(headers: &HeaderMap, config: &Config) -> Result<(), ApiError> {
    if let Some(origin) = headers.get(header::ORIGIN) {
        let origin = origin
            .to_str()
            .map_err(|_| ApiError::forbidden("invalid request origin"))?;
        let origin =
            Url::parse(origin).map_err(|_| ApiError::forbidden("invalid request origin"))?;
        if !matches!(origin.scheme(), "http" | "https") || origin.host().is_none() {
            return Err(ApiError::forbidden("invalid request origin"));
        }
        let host = headers
            .get(header::HOST)
            .and_then(|value| value.to_str().ok())
            .ok_or_else(|| ApiError::forbidden("request host is missing"))?;
        let origin_authority = match origin.port() {
            Some(port) => format!("{}:{port}", origin.host_str().unwrap_or_default()),
            None => origin.host_str().unwrap_or_default().to_owned(),
        };
        if !origin_authority.eq_ignore_ascii_case(host) {
            return Err(ApiError::forbidden("cross-origin refresh is not allowed"));
        }
    }

    let Some(expected) = config.admin_token.as_deref() else {
        if config.bind_address.ip().is_loopback() {
            // A local bind alone is insufficient: reject DNS-rebinding Host values.
            let host = headers
                .get(header::HOST)
                .and_then(|value| value.to_str().ok())
                .and_then(|value| value.parse::<axum::http::uri::Authority>().ok())
                .ok_or_else(|| ApiError::forbidden("a local request host is required"))?;
            let hostname = host.host().trim_start_matches('[').trim_end_matches(']');
            let local = hostname.eq_ignore_ascii_case("localhost")
                || hostname
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback());
            if !local || host.port_u16().unwrap_or(80) != config.bind_address.port() {
                return Err(ApiError::forbidden("a local request host is required"));
            }
            return Ok(());
        }
        return Err(ApiError::forbidden(
            "manual refresh requires ADMIN_TOKEN when the server is bound publicly",
        ));
    };
    let provided = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
        .or_else(|| {
            headers
                .get("x-admin-token")
                .and_then(|value| value.to_str().ok())
        })
        .unwrap_or_default();
    if !constant_time_equal(expected.as_bytes(), provided.as_bytes()) {
        return Err(ApiError::unauthorized("invalid administrative token"));
    }
    Ok(())
}

fn constant_time_equal(expected: &[u8], provided: &[u8]) -> bool {
    let expected_hash: [u8; 32] = Sha256::digest(expected).into();
    let provided_hash: [u8; 32] = Sha256::digest(provided).into();
    bool::from(expected_hash.ct_eq(&provided_hash))
}

async fn security_headers(request: Request<Body>, next: Next) -> Response {
    let private_response = request.uri().path().starts_with("/api")
        || matches!(request.uri().path(), "/health" | "/ready" | "/metrics");
    let mut response = next.run(request).await;
    let headers = response.headers_mut();
    if private_response {
        headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    }
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    headers.insert(header::X_FRAME_OPTIONS, HeaderValue::from_static("DENY"));
    headers.insert(
        header::REFERRER_POLICY,
        HeaderValue::from_static("no-referrer"),
    );
    headers.insert(
        HeaderName::from_static("permissions-policy"),
        HeaderValue::from_static("camera=(), microphone=(), geolocation=()"),
    );
    headers.insert(
        HeaderName::from_static("content-security-policy"),
        HeaderValue::from_static(
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        ),
    );
    response
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    code: &'static str,
    message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            code: "bad_request",
            message: message.into(),
        }
    }

    fn unauthorized(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            code: "unauthorized",
            message: message.into(),
        }
    }

    fn forbidden(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::FORBIDDEN,
            code: "forbidden",
            message: message.into(),
        }
    }

    fn unavailable(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            code: "unavailable",
            message: message.into(),
        }
    }

    fn not_found(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            code: "not_found",
            message: message.into(),
        }
    }

    fn internal(public_message: &'static str, error_value: impl std::fmt::Display) -> Self {
        error!(error = %error_value, "{public_message}");
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            code: "internal_error",
            message: public_message.to_owned(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(serde_json::json!({
                "error": {
                    "code": self.code,
                    "message": self.message
                }
            })),
        )
            .into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn authorization_headers(host: &str, token: Option<&str>, origin: Option<&str>) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(header::HOST, host.parse().unwrap());
        if let Some(token) = token {
            headers.insert(
                header::AUTHORIZATION,
                format!("Bearer {token}").parse().unwrap(),
            );
        }
        if let Some(origin) = origin {
            headers.insert(header::ORIGIN, origin.parse().unwrap());
        }
        headers
    }

    #[test]
    fn tokenless_local_refresh_rejects_rebinding_and_cross_origin() {
        let config = Config::from_lookup(|_| None).unwrap();
        assert!(
            authorize_refresh(
                &authorization_headers("localhost:8080", None, Some("http://localhost:8080")),
                &config
            )
            .is_ok()
        );
        assert!(
            authorize_refresh(
                &authorization_headers("evil.example:8080", None, None),
                &config
            )
            .is_err()
        );
        assert!(
            authorize_refresh(
                &authorization_headers("localhost:8080", None, Some("https://evil.example")),
                &config
            )
            .is_err()
        );
        assert!(
            authorize_refresh(
                &authorization_headers("localhost:8080", None, Some("null")),
                &config
            )
            .is_err()
        );
        assert!(authorize_refresh(&HeaderMap::new(), &config).is_err());
    }

    #[test]
    fn administrative_token_is_required_and_compared_exactly() {
        let token = "01635189a3e94b4d865dc22dc5f7e601";
        let config = Config::from_lookup(|name| match name {
            "ADMIN_TOKEN" => Some(token.into()),
            "BIND_ADDRESS" => Some("0.0.0.0:8080".into()),
            _ => None,
        })
        .unwrap();
        assert!(
            authorize_refresh(
                &authorization_headers("service:8080", Some(token), None),
                &config
            )
            .is_ok()
        );
        for wrong in [None, Some("wrong-token")] {
            assert_eq!(
                authorize_refresh(&authorization_headers("service:8080", wrong, None), &config)
                    .unwrap_err()
                    .status,
                StatusCode::UNAUTHORIZED
            );
        }
    }

    #[tokio::test]
    async fn admission_rejects_overload_but_preserves_liveness() {
        use tower::ServiceExt;
        let directory = tempfile::tempdir().unwrap();
        let config = Arc::new(
            Config::from_lookup(|key| {
                if key == "REFRESH_ENABLED" {
                    Some("false".into())
                } else {
                    None
                }
            })
            .unwrap(),
        );
        let repository = Repository::open(&directory.path().join("test.db"))
            .await
            .unwrap();
        let refresh = RefreshCoordinator::start(
            crate::SourceContext {
                config: config.clone(),
                repository: repository.clone(),
                http: reqwest::Client::new(),
            },
            Arc::new(crate::SourceRegistry::new()),
        );
        let state = AppState::new(config, repository, refresh, vec![]);
        let permits = state.admission.acquire_many(64).await.unwrap();
        let app = router(state.clone());
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/items")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert!(response.headers().contains_key("x-request-id"));
        let live = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(live.status(), StatusCode::OK);
        drop(permits);
        let recovered = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/items")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(recovered.status(), StatusCode::OK);
    }

    #[test]
    fn validates_cve_ids() {
        assert_eq!(validate_cve_id("cve-2026-1234").unwrap(), "CVE-2026-1234");
        assert!(validate_cve_id("CVE-26-1").is_err());
    }

    #[test]
    fn constant_time_secret_comparison_has_correct_result() {
        assert!(constant_time_equal(b"secret", b"secret"));
        assert!(!constant_time_equal(b"secret", b"wrong"));
    }

    #[test]
    fn cursor_round_trip() {
        let cursor = PageCursor {
            timestamp: "2026-08-27T00:00:00Z".into(),
            id: "cve:CVE-2026-1234".into(),
        };
        let encoded = URL_SAFE_NO_PAD.encode(serde_json::to_vec(&cursor).unwrap());
        let decoded = decode_cursor(&encoded).unwrap();
        assert_eq!(decoded.id, cursor.id);
    }
}
