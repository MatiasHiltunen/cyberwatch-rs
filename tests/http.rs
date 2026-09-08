use std::sync::Arc;

use axum::{
    Router,
    body::{Body, to_bytes},
    http::{Request, StatusCode},
};
use cyberwatch_rs::{
    Config, Repository, SourceContext, SourceRegistry,
    api::{AppState, router},
    demo,
    refresh::RefreshCoordinator,
};
use serde_json::Value;
use tower::ServiceExt;

async fn application() -> (tempfile::TempDir, Router, Arc<Config>) {
    let directory = tempfile::tempdir().unwrap();
    let mut config = Config::from_lookup(|key| match key {
        "DEMO_MODE" => Some("true".into()),
        _ => None,
    })
    .unwrap();
    config.database_path = directory.path().join("test.db");
    config.web_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("web");
    let config = Arc::new(config);
    let repository = Repository::open(&config.database_path).await.unwrap();
    demo::prepare(&repository, true).await.unwrap();
    let refresh = RefreshCoordinator::start(
        SourceContext {
            config: config.clone(),
            repository: repository.clone(),
            http: reqwest::Client::new(),
        },
        Arc::new(SourceRegistry::new()),
    );
    let app = router(AppState::new(config.clone(), repository, refresh, vec![]));
    (directory, app, config)
}

async fn get(app: &Router, path: &str) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
    let response = app
        .clone()
        .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let body = to_bytes(response.into_body(), 1_000_000)
        .await
        .unwrap()
        .to_vec();
    (status, headers, body)
}

#[tokio::test]
async fn health_readiness_and_strict_headers_work_offline() {
    let (_directory, app, _config) = application().await;
    for path in ["/health", "/ready", "/api/v1/stats", "/"] {
        let (status, headers, _) = get(&app, path).await;
        assert_eq!(status, StatusCode::OK, "{path}");
        assert_eq!(headers["x-content-type-options"], "nosniff");
        assert_eq!(headers["x-frame-options"], "DENY");
        assert!(
            headers["content-security-policy"]
                .to_str()
                .unwrap()
                .contains("script-src 'self'")
        );
        assert!(headers.contains_key("x-request-id"));
    }
    let (_, _, body) = get(&app, "/health").await;
    let health: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(health["demo_mode"], true);
    assert_eq!(health["refresh_enabled"], false);
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/refresh")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn filters_cursor_and_detail_are_consistent() {
    let (_directory, app, _config) = application().await;
    let (status, _, body) = get(
        &app,
        "/api/v1/items?kind=cve&severity=critical&exploited=true",
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let page: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(page["items"].as_array().unwrap().len(), 1);
    assert_eq!(page["items"][0]["cve_id"], "CVE-2099-99991");
    let (_, _, body) = get(&app, "/api/v1/items?limit=2").await;
    let first: Value = serde_json::from_slice(&body).unwrap();
    let cursor = first["next_cursor"].as_str().unwrap();
    let (_, _, body) = get(&app, &format!("/api/v1/items?limit=2&cursor={cursor}")).await;
    let second: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(second["items"].as_array().unwrap().len(), 2);
    assert!(second["next_cursor"].is_null());
    for item in first["items"].as_array().unwrap() {
        assert!(
            !second["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(|other| other["id"] == item["id"])
        );
    }
    let (_, _, body) = get(&app, "/api/v1/cves/cve-2099-99991").await;
    let detail: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(detail["evidence"].as_array().unwrap().len(), 1);
    assert_eq!(detail["validation"]["confidence"], "low");
    let (_, _, body) = get(&app, "/api/v1/items?q=%27%20OR%201%3D1--").await;
    let injection: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(injection["items"].as_array().unwrap().len(), 0);
}

#[tokio::test]
async fn errors_and_metrics_have_bounded_user_input() {
    let (_directory, app, _config) = application().await;
    for path in [
        "/api/v1/items?limit=0",
        "/api/v1/items?limit=not-a-number",
        "/api/v1/items?exploited=perhaps",
        "/api/v1/items?limit=201",
        "/api/v1/items?cursor=broken",
        "/api/v1/items?kind=invalid",
        "/api/v1/cves/INVALID",
    ] {
        let (status, headers, body) = get(&app, path).await;
        assert_eq!(status, StatusCode::BAD_REQUEST, "{path}");
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(
            serde_json::from_slice::<Value>(&body).unwrap()["error"]["code"],
            "bad_request"
        );
    }
    for number in 0..25 {
        let (status, _, _) = get(&app, &format!("/api/v1/items/attacker-unique-{number}")).await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }
    let (status, _, body) = get(&app, "/api/unknown").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(
        serde_json::from_slice::<Value>(&body).unwrap()["error"]["code"],
        "not_found"
    );
    let (_, headers, body) = get(&app, "/metrics").await;
    assert!(
        headers["content-type"]
            .to_str()
            .unwrap()
            .contains("version=0.0.4")
    );
    let metrics = String::from_utf8(body).unwrap();
    assert!(metrics.contains("route=\"/api/v1/items/{id}\",status_class=\"4xx\"} 25"));
    assert!(!metrics.contains("attacker-unique"));
    assert!(metrics.contains("cyberwatch_refresh_enabled 0"));
}

#[tokio::test]
async fn readiness_detects_missing_schema_while_liveness_stays_up() {
    let (_directory, app, config) = application().await;
    let database = libsql::Builder::new_local(&config.database_path)
        .build()
        .await
        .unwrap();
    database
        .connect()
        .unwrap()
        .execute("DROP TABLE items", ())
        .await
        .unwrap();
    let (status, _, body) = get(&app, "/ready").await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(
        serde_json::from_slice::<Value>(&body).unwrap()["error"]["message"],
        "database is not ready"
    );
    assert_eq!(get(&app, "/health").await.0, StatusCode::OK);
}

struct BlockedSource;

#[async_trait::async_trait]
impl cyberwatch_rs::SourceAdapter for BlockedSource {
    fn descriptor(&self) -> cyberwatch_rs::models::SourceDescriptor {
        cyberwatch_rs::models::SourceDescriptor {
            id: "blocked-test".into(),
            name: "Blocked test source".into(),
            kind: "test".into(),
            region: "Global".into(),
            language: "en".into(),
            role: "test".into(),
            trust: 1,
            timeout_seconds: 120,
            retry_attempts: 0,
        }
    }

    async fn run(
        &self,
        _: &SourceContext,
    ) -> anyhow::Result<cyberwatch_rs::ingest::source::SourceOutput> {
        std::future::pending().await
    }
}

#[tokio::test]
async fn refresh_requires_auth_and_coalesces_duplicate_jobs_without_network() {
    let directory = tempfile::tempdir().unwrap();
    let token = "207d888aef409daba979fe68eccb0b32b";
    let config = Arc::new(
        Config::from_lookup(|key| match key {
            "ADMIN_TOKEN" => Some(token.into()),
            "BIND_ADDRESS" => Some("0.0.0.0:8080".into()),
            _ => None,
        })
        .unwrap(),
    );
    let repository = Repository::open(&directory.path().join("test.db"))
        .await
        .unwrap();
    let mut registry = SourceRegistry::new();
    registry.register(BlockedSource).unwrap();
    let refresh = RefreshCoordinator::start(
        SourceContext {
            config: config.clone(),
            repository: repository.clone(),
            http: reqwest::Client::new(),
        },
        Arc::new(registry),
    );
    let app = router(AppState::new(config, repository, refresh, vec![]));
    let request = |token: &str| {
        Request::builder()
            .method("POST")
            .uri("/api/v1/refresh")
            .header("host", "service:8080")
            .header("authorization", format!("Bearer {token}"))
            .body(Body::empty())
            .unwrap()
    };
    let rejected = app.clone().oneshot(request("wrong")).await.unwrap();
    assert_eq!(rejected.status(), StatusCode::UNAUTHORIZED);
    let accepted = app.clone().oneshot(request(token)).await.unwrap();
    assert_eq!(accepted.status(), StatusCode::ACCEPTED);
    let first: Value =
        serde_json::from_slice(&to_bytes(accepted.into_body(), 10000).await.unwrap()).unwrap();
    assert_eq!(first["accepted"], true);
    let second = app.oneshot(request(token)).await.unwrap();
    assert_eq!(second.status(), StatusCode::ACCEPTED);
    let second: Value =
        serde_json::from_slice(&to_bytes(second.into_body(), 10000).await.unwrap()).unwrap();
    assert_eq!(second["accepted"], false);
    assert_eq!(first["job_id"], second["job_id"]);
}
