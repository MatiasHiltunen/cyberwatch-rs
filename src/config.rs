use std::{
    collections::{BTreeMap, HashSet},
    env, fs,
    net::SocketAddr,
    path::{Path, PathBuf},
    time::Duration,
};

use anyhow::{Context, Result, anyhow, bail};
use regex::Regex;
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use url::Url;

#[derive(Clone)]
pub struct Config {
    pub bind_address: SocketAddr,
    pub database_path: PathBuf,
    pub web_dir: PathBuf,
    pub refresh_interval: Duration,
    pub refresh_on_start: bool,
    pub refresh_enabled: bool,
    pub demo_mode: bool,
    pub refresh_queue_capacity: usize,
    pub source_concurrency: usize,
    pub validation_concurrency: usize,
    pub validation_batch_size: usize,
    pub http_connect_timeout: Duration,
    pub source_timeout: Duration,
    pub source_retry_attempts: usize,
    pub max_source_response_bytes: usize,
    pub source_failure_backoff: Duration,
    pub source_failure_backoff_max: Duration,
    pub nvd_api_key: Option<String>,
    pub nvd_results_per_page: usize,
    pub nvd_initial_window_days: i64,
    pub nvd_overlap_minutes: i64,
    pub github_token: Option<String>,
    pub github_advisory_pages: usize,
    pub admin_token: Option<String>,
    pub disabled_sources: HashSet<String>,
    pub feeds: Vec<FeedConfig>,
    pub news_retention_days: i64,
    pub ingestion_run_retention_days: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FeedConfig {
    pub id: String,
    pub name: String,
    pub url: String,
    #[serde(default = "default_region")]
    pub region: String,
    #[serde(default = "default_language")]
    pub language: String,
    #[serde(default = "default_trust")]
    pub trust: u8,
    #[serde(default = "default_role")]
    pub role: String,
    #[serde(default = "default_enabled")]
    pub enabled: bool,
    pub timeout_seconds: Option<u64>,
    pub retry_attempts: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
enum FeedConfigFile {
    Array(Vec<FeedConfig>),
    Object(FeedCatalog),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FeedCatalog {
    #[serde(default)]
    include_defaults: bool,
    #[serde(default)]
    feeds: Vec<FeedConfig>,
}

fn default_region() -> String {
    "Global".to_owned()
}

fn default_language() -> String {
    "en".to_owned()
}

const fn default_trust() -> u8 {
    1
}

fn default_role() -> String {
    "media".to_owned()
}

const fn default_enabled() -> bool {
    true
}

impl Config {
    pub fn from_env() -> Result<Self> {
        let _ = dotenvy::dotenv();
        Self::from_lookup(|name| env::var(name).ok())
    }

    /// Parse configuration without mutating process environment (also used by tests).
    pub fn from_lookup(lookup: impl Fn(&str) -> Option<String>) -> Result<Self> {
        let bind_address = env_or(&lookup, "BIND_ADDRESS", "127.0.0.1:8080".to_owned())?
            .parse()
            .context("BIND_ADDRESS must be a socket address such as 127.0.0.1:8080")?;

        let source_failure_backoff =
            Duration::from_secs(env_or(&lookup, "SOURCE_FAILURE_BACKOFF_SECONDS", 60_u64)?);
        let source_failure_backoff_max = Duration::from_secs(env_or(
            &lookup,
            "SOURCE_FAILURE_BACKOFF_MAX_SECONDS",
            3_600_u64,
        )?);
        if source_failure_backoff_max < source_failure_backoff {
            bail!("SOURCE_FAILURE_BACKOFF_MAX_SECONDS must not be smaller than the base delay");
        }

        let disabled_sources = lookup("DISABLED_SOURCES")
            .unwrap_or_default()
            .split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
            .collect();

        let config = Self {
            bind_address,
            database_path: PathBuf::from(env_or(
                &lookup,
                "DATABASE_PATH",
                "./data/cyberwatch.db".to_owned(),
            )?),
            web_dir: PathBuf::from(env_or(&lookup, "WEB_DIR", "./web".to_owned())?),
            refresh_interval: Duration::from_secs(env_or(
                &lookup,
                "REFRESH_INTERVAL_SECONDS",
                900_u64,
            )?),
            refresh_on_start: env_or(&lookup, "REFRESH_ON_START", true)?,
            refresh_enabled: env_or(&lookup, "REFRESH_ENABLED", true)?,
            demo_mode: env_or(&lookup, "DEMO_MODE", false)?,
            refresh_queue_capacity: env_or(&lookup, "REFRESH_QUEUE_CAPACITY", 1_usize)?
                .clamp(1, 32),
            source_concurrency: env_or(&lookup, "SOURCE_CONCURRENCY", 8_usize)?.clamp(1, 64),
            validation_concurrency: env_or(&lookup, "VALIDATION_CONCURRENCY", 8_usize)?
                .clamp(1, 64),
            validation_batch_size: env_or(&lookup, "VALIDATION_BATCH_SIZE", 250_usize)?
                .clamp(1, 2_000),
            http_connect_timeout: Duration::from_secs(env_or(
                &lookup,
                "HTTP_CONNECT_TIMEOUT_SECONDS",
                15_u64,
            )?),
            source_timeout: Duration::from_secs(env_or(
                &lookup,
                "SOURCE_TIMEOUT_SECONDS",
                120_u64,
            )?),
            source_retry_attempts: env_or(&lookup, "SOURCE_RETRY_ATTEMPTS", 2_usize)?.clamp(0, 10),
            max_source_response_bytes: env_or(
                &lookup,
                "MAX_SOURCE_RESPONSE_BYTES",
                32_usize * 1_024 * 1_024,
            )?
            .clamp(64 * 1_024, 256 * 1_024 * 1_024),
            source_failure_backoff,
            source_failure_backoff_max,
            nvd_api_key: secret_env(&lookup, "NVD_API_KEY")?,
            nvd_results_per_page: env_or(&lookup, "NVD_RESULTS_PER_PAGE", 500_usize)?
                .clamp(1, 2_000),
            nvd_initial_window_days: env_or(&lookup, "NVD_INITIAL_WINDOW_DAYS", 7_i64)?
                .clamp(1, 119),
            nvd_overlap_minutes: env_or(&lookup, "NVD_OVERLAP_MINUTES", 10_i64)?.clamp(0, 1_440),
            github_token: secret_env(&lookup, "GITHUB_TOKEN")?,
            github_advisory_pages: env_or(&lookup, "GITHUB_ADVISORY_PAGES", 3_usize)?.clamp(1, 10),
            admin_token: secret_env(&lookup, "ADMIN_TOKEN")?,
            disabled_sources,
            feeds: load_feeds(&lookup)?,
            news_retention_days: env_or(&lookup, "NEWS_RETENTION_DAYS", 730_i64)?.max(0),
            ingestion_run_retention_days: env_or(&lookup, "INGESTION_RUN_RETENTION_DAYS", 90_i64)?
                .max(1),
        };

        if config.refresh_interval < Duration::from_secs(30) {
            bail!("REFRESH_INTERVAL_SECONDS must be at least 30 seconds");
        }
        if config.source_timeout < Duration::from_secs(5) {
            bail!("SOURCE_TIMEOUT_SECONDS must be at least 5 seconds");
        }

        if config
            .admin_token
            .as_deref()
            .is_some_and(|token| token.len() < 32)
        {
            bail!("ADMIN_TOKEN must contain at least 32 bytes; generate a random secret");
        }
        if !config.bind_address.ip().is_loopback() && config.admin_token.is_none() {
            bail!("public BIND_ADDRESS requires ADMIN_TOKEN or ADMIN_TOKEN_FILE");
        }
        Ok(config)
    }

    pub fn refresh_allowed(&self) -> bool {
        self.refresh_enabled && !self.demo_mode
    }

    pub fn source_enabled(&self, id: &str) -> bool {
        !self.disabled_sources.contains(id)
    }
}

impl std::fmt::Debug for Config {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Config")
            .field("bind_address", &self.bind_address)
            .field("database_path", &self.database_path)
            .field("demo_mode", &self.demo_mode)
            .field("refresh_enabled", &self.refresh_enabled)
            .finish_non_exhaustive()
    }
}

fn secret_env(lookup: &impl Fn(&str) -> Option<String>, name: &str) -> Result<Option<String>> {
    let direct = optional_env(lookup, name);
    let file = optional_env(lookup, &format!("{name}_FILE"));
    if direct.is_some() && file.is_some() {
        bail!("set only one of {name} and {name}_FILE");
    }
    if let Some(path) = file {
        // Limit secret-file reads and avoid echoing file contents or paths in diagnostics.
        use std::io::Read;
        let mut value = String::new();
        fs::File::open(path)
            .with_context(|| format!("failed to open {name}_FILE"))?
            .take(16_385)
            .read_to_string(&mut value)
            .with_context(|| format!("failed to read {name}_FILE"))?;
        let value = value.trim();
        if value.is_empty() || value.len() > 16_384 {
            bail!("{name}_FILE must contain a nonempty secret of at most 16384 bytes");
        }
        return Ok(Some(value.to_owned()));
    }
    if direct.as_deref().is_some_and(|value| value.len() > 16_384) {
        bail!("{name} exceeds 16384 bytes");
    }
    Ok(direct)
}

fn optional_env(lookup: &impl Fn(&str) -> Option<String>, name: &str) -> Option<String> {
    lookup(name)
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
}

fn env_or<T>(lookup: &impl Fn(&str) -> Option<String>, name: &str, default: T) -> Result<T>
where
    T: std::str::FromStr,
    T::Err: std::fmt::Display,
{
    match lookup(name) {
        Some(value) if !value.trim().is_empty() => value
            .trim()
            .parse::<T>()
            .map_err(|error| anyhow!("invalid {name}: {error}")),
        _ => Ok(default),
    }
}

fn load_feeds(lookup: &impl Fn(&str) -> Option<String>) -> Result<Vec<FeedConfig>> {
    let defaults: FeedConfigFile = serde_json::from_str(include_str!("../sources.default.json"))
        .context("embedded sources.default.json is invalid")?;
    let default_feeds = catalog_parts(defaults).1;

    let override_text = if let Some(value) = optional_env(lookup, "NEWS_FEEDS_JSON") {
        Some(value)
    } else if let Some(path) = optional_env(lookup, "SOURCE_CONFIG_PATH") {
        Some(
            fs::read_to_string(Path::new(&path))
                .with_context(|| format!("failed to read SOURCE_CONFIG_PATH {path}"))?,
        )
    } else {
        None
    };

    let feeds = if let Some(text) = override_text {
        let parsed: FeedConfigFile = parse_json(&text, "source feed configuration")?;
        let (include_defaults, custom) = catalog_parts(parsed);
        if include_defaults {
            merge_feeds(default_feeds, custom)
        } else {
            custom
        }
    } else {
        default_feeds
    };

    validate_feeds(feeds)
}

fn parse_json<T: DeserializeOwned>(text: &str, label: &str) -> Result<T> {
    serde_json::from_str(text).with_context(|| format!("invalid {label}"))
}

fn catalog_parts(file: FeedConfigFile) -> (bool, Vec<FeedConfig>) {
    match file {
        FeedConfigFile::Array(feeds) => (false, feeds),
        FeedConfigFile::Object(catalog) => (catalog.include_defaults, catalog.feeds),
    }
}

fn merge_feeds(defaults: Vec<FeedConfig>, overrides: Vec<FeedConfig>) -> Vec<FeedConfig> {
    let mut merged = BTreeMap::new();
    for feed in defaults.into_iter().chain(overrides) {
        merged.insert(feed.id.clone(), feed);
    }
    merged.into_values().collect()
}

fn validate_feeds(feeds: Vec<FeedConfig>) -> Result<Vec<FeedConfig>> {
    if feeds.len() > 128 {
        bail!("at most 128 configured feeds are allowed");
    }
    let id_pattern = Regex::new(r"^[a-z0-9][a-z0-9_-]{1,63}$")?;
    let mut ids = HashSet::new();
    let mut names = HashSet::new();
    let mut validated = Vec::with_capacity(feeds.len());

    for feed in feeds {
        if !id_pattern.is_match(&feed.id) {
            bail!(
                "invalid feed id {:?}; use lowercase letters, numbers, - or _",
                feed.id
            );
        }
        if feed.name.trim().is_empty() || feed.name.len() > 160 {
            bail!("feed {} has an invalid name", feed.id);
        }
        if !ids.insert(feed.id.clone()) {
            bail!("duplicate feed id {}", feed.id);
        }
        if !names.insert(feed.name.to_lowercase()) {
            bail!("duplicate feed name {}", feed.name);
        }
        if feed
            .timeout_seconds
            .is_some_and(|seconds| !(5..=300).contains(&seconds))
        {
            bail!("feed {} timeout_seconds must be between 5 and 300", feed.id);
        }
        if feed.retry_attempts.is_some_and(|retries| retries > 10) {
            bail!("feed {} retry_attempts must not exceed 10", feed.id);
        }
        if !(1..=3).contains(&feed.trust) {
            bail!("feed {} trust must be 1, 2, or 3", feed.id);
        }
        let url = Url::parse(&feed.url)
            .with_context(|| format!("feed {} has an invalid URL", feed.id))?;
        crate::ingest::http::validate_outbound_url(&url)
            .with_context(|| format!("feed {} has an unsafe destination", feed.id))?;
        if feed.enabled {
            validated.push(feed);
        }
    }

    Ok(validated)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn configured(values: &[(&str, &str)]) -> Result<Config> {
        Config::from_lookup(|name| {
            values
                .iter()
                .find(|(key, _)| *key == name)
                .map(|(_, value)| (*value).into())
        })
    }

    #[test]
    fn public_binding_fails_closed_and_debug_never_shows_secrets() {
        assert!(configured(&[("BIND_ADDRESS", "0.0.0.0:8080")]).is_err());
        assert!(configured(&[("ADMIN_TOKEN", "short")]).is_err());
        let secret = "8c2f1a09317cb41d1b61a9b762fcc949";
        let config =
            configured(&[("BIND_ADDRESS", "0.0.0.0:8080"), ("ADMIN_TOKEN", secret)]).unwrap();
        assert!(!format!("{config:?}").contains(secret));
        assert!(configured(&[]).is_ok());
    }

    #[test]
    fn secret_files_are_loaded_without_environment_mutation() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("token");
        let secret = "d511bc1454b919454ade691737656238";
        fs::write(&path, format!("{secret}\n")).unwrap();
        let config = configured(&[("ADMIN_TOKEN_FILE", path.to_str().unwrap())]).unwrap();
        assert_eq!(config.admin_token.as_deref(), Some(secret));
        assert!(
            configured(&[
                ("ADMIN_TOKEN_FILE", path.to_str().unwrap()),
                ("ADMIN_TOKEN", secret)
            ])
            .is_err()
        );
        fs::write(&path, " ").unwrap();
        assert!(configured(&[("ADMIN_TOKEN_FILE", path.to_str().unwrap())]).is_err());
        assert!(configured(&[("GITHUB_TOKEN_FILE", "not-a-real-secret-file")]).is_err());
    }

    #[test]
    fn demo_disables_refresh_even_if_enabled_explicitly() {
        let config = configured(&[("DEMO_MODE", "true"), ("REFRESH_ENABLED", "true")]).unwrap();
        assert!(!config.refresh_allowed());
        assert!(
            !configured(&[("REFRESH_ENABLED", "false")])
                .unwrap()
                .refresh_allowed()
        );
        assert!(configured(&[("REFRESH_INTERVAL_SECONDS", "0")]).is_err());
        assert!(configured(&[("DEMO_MODE", "perhaps")]).is_err());
    }

    #[test]
    fn embedded_feed_catalog_is_valid() {
        let parsed: FeedConfigFile = serde_json::from_str(include_str!("../sources.default.json"))
            .expect("embedded catalog should parse");
        let (_, feeds) = catalog_parts(parsed);
        assert!(
            validate_feeds(feeds)
                .expect("catalog should validate")
                .len()
                >= 25
        );
    }

    #[test]
    fn overrides_replace_matching_ids() {
        let defaults = vec![FeedConfig {
            id: "one".into(),
            name: "One".into(),
            url: "https://one.example/feed".into(),
            region: "Global".into(),
            language: "en".into(),
            trust: 1,
            role: "media".into(),
            enabled: true,
            timeout_seconds: None,
            retry_attempts: None,
        }];
        let overrides = vec![FeedConfig {
            id: "one".into(),
            name: "Replacement".into(),
            url: "https://two.example/feed".into(),
            region: "Global".into(),
            language: "en".into(),
            trust: 2,
            role: "research".into(),
            enabled: true,
            timeout_seconds: None,
            retry_attempts: None,
        }];
        let merged = merge_feeds(defaults, overrides);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].name, "Replacement");
    }
}
