use std::{process::Command, sync::Arc};

use cyberwatch_rs::{
    Config, Repository, SourceContext, SourceRegistry,
    api::{AppState, router},
    refresh::RefreshCoordinator,
};

#[tokio::test]
async fn healthcheck_checks_the_running_servers_schema_without_initializing_another_database() {
    let directory = tempfile::tempdir().unwrap();
    let mut config = Config::from_lookup(|key| match key {
        "DEMO_MODE" => Some("true".into()),
        _ => None,
    })
    .unwrap();
    config.database_path = directory.path().join("server.db");
    let config = Arc::new(config);
    let repository = Repository::open(&config.database_path).await.unwrap();
    let refresh = RefreshCoordinator::start(
        SourceContext {
            config: config.clone(),
            repository: repository.clone(),
            http: reqwest::Client::new(),
        },
        Arc::new(SourceRegistry::new()),
    );
    let app = router(AppState::new(config.clone(), repository, refresh, vec![]));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });

    for ready in [true, false] {
        if !ready {
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
        }
        let path = directory.path().to_owned();
        let output = tokio::task::spawn_blocking(move || {
            Command::new(env!("CARGO_BIN_EXE_cyberwatch-rs"))
                .arg("--healthcheck")
                .current_dir(&path)
                .env("BIND_ADDRESS", format!("0.0.0.0:{}", address.port()))
                // These values would fail startup or write a new database if the
                // healthcheck accidentally initialized the application.
                .env("ADMIN_TOKEN_FILE", path.join("missing-admin-token"))
                .env("DATABASE_PATH", path.join("must-not-exist.db"))
                .output()
                .unwrap()
        })
        .await
        .unwrap();
        assert_eq!(output.status.success(), ready, "{output:?}");
        assert!(!directory.path().join("must-not-exist.db").exists());
    }
    server.abort();
}

#[test]
fn unavailable_listener_returns_a_failure_exit_code() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    let output = Command::new(env!("CARGO_BIN_EXE_cyberwatch-rs"))
        .arg("--healthcheck")
        .env("BIND_ADDRESS", address.to_string())
        .output()
        .unwrap();
    assert!(!output.status.success());
}
