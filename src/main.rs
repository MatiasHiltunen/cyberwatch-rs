use std::{sync::Arc, time::Duration};

use anyhow::{Context, Result};
use cyberwatch_rs::{
    Config, Repository,
    api::{AppState, router},
    ingest::{self, source::SourceContext},
    refresh::RefreshCoordinator,
};
use tokio::{net::TcpListener, time::MissedTickBehavior};
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;

mod healthcheck;

fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    match args.next() {
        Some(argument) if argument == "--healthcheck" && args.next().is_none() => {
            return healthcheck::run().context("readiness probe failed");
        }
        Some(_) => anyhow::bail!("usage: cyberwatch-rs [--healthcheck]"),
        None => {}
    }
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("failed to start async runtime")?
        .block_on(run())
}

async fn run() -> Result<()> {
    init_tracing();
    let config = Arc::new(Config::from_env()?);
    let repository = Repository::open(&config.database_path).await?;
    cyberwatch_rs::demo::prepare(&repository, config.demo_mode).await?;
    let http = ingest::http::build_client(&config)?;
    let registry = Arc::new(ingest::build_registry(&config)?);
    if registry.is_empty() {
        warn!("no ingestion sources are enabled");
    }

    let source_context = SourceContext {
        config: config.clone(),
        repository: repository.clone(),
        http,
    };
    let refresh = RefreshCoordinator::start(source_context, registry.clone());

    if config.refresh_allowed() && config.refresh_on_start {
        let coordinator = refresh.clone();
        tokio::spawn(async move {
            if let Err(error) = coordinator.request("startup").await {
                warn!(error = %error, "failed to enqueue startup refresh");
            }
        });
    }
    if config.refresh_allowed() {
        spawn_scheduler(refresh.clone(), config.refresh_interval);
    }

    let state = AppState::new(config.clone(), repository, refresh, registry.descriptors());
    let app = router(state);
    let listener = TcpListener::bind(config.bind_address)
        .await
        .with_context(|| format!("failed to bind {}", config.bind_address))?;
    info!(
        address = %config.bind_address,
        database = %config.database_path.display(),
        web_dir = %config.web_dir.display(),
        sources = registry.len(),
        "cyberwatch server started"
    );

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .context("HTTP server failed")?;
    Ok(())
}

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("cyberwatch_rs=info,tower_http=info"));
    tracing_subscriber::fmt().with_env_filter(filter).init();
}

fn spawn_scheduler(coordinator: RefreshCoordinator, interval: Duration) {
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(interval);
        ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
        ticker.tick().await;
        loop {
            ticker.tick().await;
            if let Err(error) = coordinator.request("schedule").await {
                warn!(error = %error, "failed to enqueue scheduled refresh");
            }
        }
    });
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to install SIGTERM handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
    info!("shutdown signal received");
}
