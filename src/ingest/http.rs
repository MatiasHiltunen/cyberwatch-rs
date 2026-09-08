use std::{
    net::{IpAddr, SocketAddr},
    sync::Arc,
    time::Duration,
};

use anyhow::{Context, Result, anyhow, bail};
use futures::StreamExt;
use reqwest::{
    RequestBuilder, StatusCode,
    dns::{Addrs, Name, Resolve, Resolving},
    header,
};
use tokio::time::{sleep, timeout};
use url::{Host, Url};

#[derive(Debug, Clone)]
pub struct FetchPolicy {
    pub timeout: Duration,
    pub retries: usize,
    pub max_bytes: usize,
    pub allow_not_modified: bool,
}

#[derive(Debug, Clone)]
pub struct FetchResponse {
    pub status: StatusCode,
    pub body: Vec<u8>,
    pub content_type: Option<String>,
    pub etag: Option<String>,
    pub last_modified: Option<String>,
    pub final_url: String,
}

pub async fn send_limited(builder: RequestBuilder, policy: &FetchPolicy) -> Result<FetchResponse> {
    let destination = builder
        .try_clone()
        .ok_or_else(|| anyhow!("request cannot be cloned"))?
        .build()
        .context("invalid source request")?;
    validate_outbound_url(destination.url())?;
    let mut last_error = None;

    for attempt in 0..=policy.retries {
        let request = builder
            .try_clone()
            .ok_or_else(|| anyhow!("HTTP request cannot be cloned for retry"))?;
        let result = timeout(policy.timeout, send_once(request, policy)).await;
        match result {
            Ok(Ok(response)) => return Ok(response),
            Ok(Err(error)) => last_error = Some(error),
            Err(_) => last_error = Some(anyhow!("source request exceeded {:?}", policy.timeout)),
        }

        if attempt < policy.retries {
            let shift = u32::try_from(attempt).unwrap_or(10).min(10);
            let delay_ms = 500_u64.saturating_mul(1_u64 << shift);
            sleep(Duration::from_millis(delay_ms)).await;
        }
    }

    Err(last_error.unwrap_or_else(|| anyhow!("source request failed")))
}

async fn send_once(builder: RequestBuilder, policy: &FetchPolicy) -> Result<FetchResponse> {
    let response = builder
        .send()
        .await
        .map_err(|error| error.without_url())
        .context("error sending source request")?;
    let status = response.status();
    let final_url = response.url().origin().ascii_serialization();
    let headers = response.headers().clone();
    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .map(ToOwned::to_owned);
    let etag = headers
        .get(header::ETAG)
        .and_then(|value| value.to_str().ok())
        .map(ToOwned::to_owned);
    let last_modified = headers
        .get(header::LAST_MODIFIED)
        .and_then(|value| value.to_str().ok())
        .map(ToOwned::to_owned);

    if status == StatusCode::NOT_MODIFIED && policy.allow_not_modified {
        return Ok(FetchResponse {
            status,
            body: Vec::new(),
            content_type,
            etag,
            last_modified,
            final_url,
        });
    }

    if let Some(length) = response.content_length() {
        if length > u64::try_from(policy.max_bytes).unwrap_or(u64::MAX) {
            bail!(
                "source response from {final_url} is too large: {length} bytes exceeds {}",
                policy.max_bytes
            );
        }
    }

    let mut body = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk
            .map_err(|error| error.without_url())
            .context("failed while reading source response body")?;
        if body.len().saturating_add(chunk.len()) > policy.max_bytes {
            bail!(
                "source response from {final_url} exceeded {} bytes",
                policy.max_bytes
            );
        }
        body.extend_from_slice(&chunk);
    }

    if !status.is_success() {
        bail!(
            "source returned HTTP {status} from {final_url}; content-type={}",
            content_type.as_deref().unwrap_or("unknown")
        );
    }

    Ok(FetchResponse {
        status,
        body,
        content_type,
        etag,
        last_modified,
        final_url,
    })
}

pub fn parse_json<T>(response: &FetchResponse, source_name: &str) -> Result<T>
where
    T: serde::de::DeserializeOwned,
{
    serde_json::from_slice(&response.body).with_context(|| {
        format!(
            "invalid {source_name} JSON from {}; content-type={}",
            response.final_url,
            response.content_type.as_deref().unwrap_or("unknown")
        )
    })
}

/// Shared ingestion client: resolves and connects only to public addresses.
/// Direct requests deliberately ignore ambient proxy variables; enforce egress at
/// the deployment boundary too, since this is not a complete network sandbox.
pub fn build_client(config: &crate::Config) -> Result<reqwest::Client> {
    reqwest::Client::builder()
        .user_agent(format!("cyberwatch-rs/{}", env!("CARGO_PKG_VERSION")))
        .connect_timeout(config.http_connect_timeout)
        .tcp_keepalive(Duration::from_secs(30))
        .pool_max_idle_per_host(8)
        .no_proxy()
        .dns_resolver(Arc::new(PublicResolver))
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            if attempt.previous().len() >= 8 {
                attempt.error("too many redirects")
            } else if validate_redirect(attempt.url(), attempt.previous()).is_err() {
                attempt.error("redirect destination is not allowed")
            } else {
                attempt.follow()
            }
        }))
        .build()
        .context("failed to build shared HTTP client")
}

fn validate_redirect(destination: &Url, previous: &[Url]) -> Result<()> {
    validate_outbound_url(destination)?;
    if let Some(origin) = previous.first() {
        // reqwest strips Authorization across hosts, but not NVD's custom apiKey.
        // Built-in credential-bearing APIs may redirect only within their origin.
        if matches!(
            origin.host_str(),
            Some("services.nvd.nist.gov" | "api.github.com")
        ) && origin.origin() != destination.origin()
        {
            bail!("credential-bearing API redirect changed origin");
        }
    }
    if previous.last().is_some_and(|url| url.scheme() == "https") && destination.scheme() != "https"
    {
        bail!("HTTPS redirect must not downgrade to HTTP");
    }
    Ok(())
}

pub fn validate_outbound_url(url: &Url) -> Result<()> {
    if !matches!(url.scheme(), "http" | "https") || url.host().is_none() {
        bail!("outbound URL must use HTTP(S) and have a host");
    }
    if !url.username().is_empty() || url.password().is_some() {
        bail!("outbound URL must not contain credentials");
    }
    let allowed = match url.host() {
        Some(Host::Ipv4(ip)) => public_address(IpAddr::V4(ip)),
        Some(Host::Ipv6(ip)) => public_address(IpAddr::V6(ip)),
        Some(Host::Domain(name)) => {
            let name = name.trim_end_matches('.').to_ascii_lowercase();
            name != "localhost"
                && !name.ends_with(".localhost")
                && !name.ends_with(".local")
                && !name.ends_with(".internal")
        }
        None => false,
    };
    if !allowed {
        bail!("outbound URL destination is not public");
    }
    Ok(())
}

fn public_address(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let [a, b, c, _] = ip.octets();
            !(ip.is_private()
                || ip.is_loopback()
                || ip.is_link_local()
                || a == 0
                || a >= 224
                || (a == 100 && (64..=127).contains(&b))
                || (a == 192 && b == 0 && (c == 0 || c == 2))
                || (a == 192 && b == 88 && c == 99)
                || (a == 198 && (b == 18 || b == 19 || (b == 51 && c == 100)))
                || (a == 203 && b == 0 && c == 113))
        }
        IpAddr::V6(ip) => {
            // Reject mapped IPv4, unique-local, link-local, multicast, translation
            // and transition ranges; allow native global unicast only.
            let segments = ip.segments();
            segments[0] & 0xe000 == 0x2000
                && segments[0] != 0x2002
                && !(segments[0] == 0x2001 && (segments[1] < 0x200 || segments[1] == 0xdb8))
                && !(segments[0] == 0x3fff && segments[1] < 0x1000)
        }
    }
}

#[derive(Debug)]
struct PublicResolver;

impl Resolve for PublicResolver {
    fn resolve(&self, name: Name) -> Resolving {
        Box::pin(async move {
            let addresses: Vec<SocketAddr> =
                tokio::net::lookup_host((name.as_str(), 0)).await?.collect();
            if addresses.is_empty()
                || addresses
                    .iter()
                    .any(|address| !public_address(address.ip()))
            {
                return Err(std::io::Error::other("DNS destination is not public").into());
            }
            Ok(Box::new(addresses.into_iter()) as Addrs)
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn local_http_fixture_checks_size_streaming_redirects_and_redaction() {
        use axum::{
            Router,
            body::{Body, Bytes},
            http::StatusCode,
            response::Redirect,
            routing::get,
        };
        let app = Router::new()
            .route("/large", get(|| async { "x".repeat(100) }))
            .route(
                "/chunked",
                get(|| async {
                    Body::from_stream(futures::stream::iter([
                        Ok::<_, std::io::Error>(Bytes::from_static(b"01234567890123456789")),
                        Ok(Bytes::from_static(b"01234567890123456789")),
                    ]))
                }),
            )
            .route(
                "/redirect",
                get(|| async { Redirect::temporary("http://127.0.0.1:1/metadata") }),
            )
            .route(
                "/error",
                get(|| async { (StatusCode::INTERNAL_SERVER_ERROR, "sensitive-provider-body") }),
            )
            .route("/cached", get(|| async { StatusCode::NOT_MODIFIED }));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let client = build_client(&crate::Config::from_lookup(|_| None).unwrap()).unwrap();
        let policy = FetchPolicy {
            timeout: Duration::from_secs(1),
            retries: 0,
            max_bytes: 32,
            allow_not_modified: true,
        };
        // Call the private transport helper to test with a local fixture. The public
        // send_limited entry point rejects loopback before any connection.
        for route in ["large", "chunked"] {
            let error = send_once(client.get(format!("http://{address}/{route}")), &policy)
                .await
                .unwrap_err();
            assert!(error.to_string().contains("bytes"), "{error}");
        }
        let error = send_once(client.get(format!("http://{address}/redirect")), &policy)
            .await
            .unwrap_err();
        assert!(format!("{error:#}").contains("redirect"));
        let error = send_once(
            client.get(format!("http://{address}/error?token=private-query-token")),
            &policy,
        )
        .await
        .unwrap_err();
        let diagnostic = format!("{error:#}");
        assert!(!diagnostic.contains("private-query-token"));
        assert!(!diagnostic.contains("sensitive-provider-body"));
        assert_eq!(
            send_once(client.get(format!("http://{address}/cached")), &policy)
                .await
                .unwrap()
                .status,
            StatusCode::NOT_MODIFIED
        );
        server.abort();
    }

    #[test]
    fn redirects_keep_api_credentials_at_the_original_https_origin() {
        let nvd = Url::parse("https://services.nvd.nist.gov/rest/json/cves/2.0").unwrap();
        let attacker = Url::parse("https://attacker.example/collect").unwrap();
        assert!(validate_redirect(&attacker, std::slice::from_ref(&nvd)).is_err());
        assert!(
            validate_redirect(
                &Url::parse("http://services.nvd.nist.gov/collect").unwrap(),
                std::slice::from_ref(&nvd)
            )
            .is_err()
        );
        assert!(
            validate_redirect(
                &Url::parse("https://services.nvd.nist.gov:8443/collect").unwrap(),
                std::slice::from_ref(&nvd)
            )
            .is_err()
        );
        assert!(validate_redirect(&nvd, std::slice::from_ref(&nvd)).is_ok());
        let feed = Url::parse("https://feeds.example.com/rss").unwrap();
        assert!(
            validate_redirect(
                &Url::parse("https://cdn.example.com/rss").unwrap(),
                std::slice::from_ref(&feed)
            )
            .is_ok()
        );
        assert!(
            validate_redirect(
                &Url::parse("http://feeds.example.com/rss").unwrap(),
                &[feed]
            )
            .is_err()
        );
    }

    #[test]
    fn rejects_private_metadata_credentials_and_transition_urls() {
        for value in [
            "http://127.0.0.1",
            "http://2130706433",
            "http://10.1.2.3",
            "http://169.254.169.254/latest",
            "http://100.100.100.200",
            "http://[::1]",
            "http://[::ffff:127.0.0.1]",
            "http://[2002:7f00:1::]",
            "http://localhost.",
            "http://service.internal",
            "https://user:password@example.com/feed",
            "file:///etc/passwd",
        ] {
            assert!(
                validate_outbound_url(&Url::parse(value).unwrap()).is_err(),
                "{value}"
            );
        }
        assert!(
            validate_outbound_url(&Url::parse("https://feeds.example.com/rss").unwrap()).is_ok()
        );
        assert!(public_address("1.1.1.1".parse().unwrap()));
        assert!(public_address("2606:4700:4700::1111".parse().unwrap()));
        assert!(!public_address("192.168.1.5".parse().unwrap()));
        assert!(!public_address("fc00::1".parse().unwrap()));
    }

    #[tokio::test]
    async fn private_request_is_rejected_before_connecting() {
        let error = send_limited(
            reqwest::Client::new().get("http://127.0.0.1:1/secret"),
            &FetchPolicy {
                timeout: Duration::from_secs(1),
                retries: 0,
                max_bytes: 100,
                allow_not_modified: false,
            },
        )
        .await
        .unwrap_err();
        assert_eq!(error.to_string(), "outbound URL destination is not public");
    }

    #[test]
    fn json_errors_do_not_disclose_response_body() {
        let response = FetchResponse {
            status: StatusCode::OK,
            body: b"provider-secret-data".to_vec(),
            content_type: None,
            etag: None,
            last_modified: None,
            final_url: "https://example.com".into(),
        };
        let error = parse_json::<serde_json::Value>(&response, "test").unwrap_err();
        assert!(!format!("{error:#}").contains("provider-secret-data"));
    }
}
