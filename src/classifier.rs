use std::{collections::BTreeSet, sync::OnceLock};

use regex::Regex;
use sha2::{Digest, Sha256};

static CVE_REGEX: OnceLock<Regex> = OnceLock::new();
static HTML_REGEX: OnceLock<Regex> = OnceLock::new();
static SPACE_REGEX: OnceLock<Regex> = OnceLock::new();

pub fn extract_cves(text: &str) -> Vec<String> {
    let regex = CVE_REGEX.get_or_init(|| {
        Regex::new(r"(?i)\bCVE-[0-9]{4}-[0-9]{4,8}\b").expect("CVE regex is valid")
    });
    regex
        .find_iter(text)
        .map(|value| value.as_str().to_ascii_uppercase())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

pub fn strip_html(input: &str) -> String {
    let html = HTML_REGEX.get_or_init(|| Regex::new(r"(?s)<[^>]*>").expect("HTML regex is valid"));
    let spaces = SPACE_REGEX.get_or_init(|| Regex::new(r"\s+").expect("space regex is valid"));
    let without_tags = html.replace_all(input, " ");
    let decoded = without_tags
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&nbsp;", " ");
    spaces.replace_all(decoded.trim(), " ").into_owned()
}

pub fn classify(text: &str) -> Vec<String> {
    let lower = text.to_lowercase();
    let rules: &[(&str, &[&str])] = &[
        ("ransomware", &["ransomware", "extortion", "encryptor"]),
        (
            "malware",
            &[
                "malware", "trojan", "botnet", "backdoor", "spyware", "rootkit",
            ],
        ),
        (
            "phishing",
            &[
                "phishing",
                "credential theft",
                "business email compromise",
                "bec",
            ],
        ),
        (
            "zero-day",
            &["zero-day", "zero day", "0-day", "actively exploited"],
        ),
        (
            "exploit",
            &[
                "exploit",
                "remote code execution",
                "rce",
                "proof of concept",
                "poc",
            ],
        ),
        (
            "data-breach",
            &["data breach", "data leak", "stolen data", "exposed records"],
        ),
        (
            "cloud",
            &["cloud", "aws", "azure", "gcp", "kubernetes", "container"],
        ),
        (
            "identity",
            &[
                "identity",
                "authentication",
                "oauth",
                "saml",
                "active directory",
                "credential",
            ],
        ),
        (
            "network",
            &["router", "firewall", "vpn", "network", "dns", "tcp/ip"],
        ),
        (
            "supply-chain",
            &[
                "supply chain",
                "dependency confusion",
                "package repository",
                "software update",
            ],
        ),
        (
            "ot-ics",
            &[
                "industrial control",
                "ics",
                "scada",
                "operational technology",
                "plc",
            ],
        ),
        (
            "patching",
            &[
                "patch",
                "security update",
                "hotfix",
                "upgrade",
                "mitigation",
            ],
        ),
        ("mobile", &["android", "ios", "mobile", "iphone"]),
        (
            "ai-security",
            &[
                "artificial intelligence",
                "machine learning",
                "llm",
                "generative ai",
            ],
        ),
        (
            "cryptocurrency",
            &[
                "cryptocurrency",
                "crypto wallet",
                "blockchain",
                "cryptominer",
            ],
        ),
        (
            "denial-of-service",
            &["denial of service", "ddos", "dos vulnerability"],
        ),
    ];

    let mut categories = BTreeSet::new();
    for (category, keywords) in rules {
        if keywords.iter().any(|keyword| lower.contains(keyword)) {
            categories.insert((*category).to_owned());
        }
    }
    if categories.is_empty() {
        categories.insert("general-security".to_owned());
    }
    categories.into_iter().collect()
}

pub fn normalize_severity(value: &str) -> Option<String> {
    let normalized = value.trim().to_ascii_lowercase();
    match normalized.as_str() {
        "critical" | "high" | "medium" | "low" | "none" | "unknown" => Some(normalized),
        "moderate" => Some("medium".to_owned()),
        _ => None,
    }
}

pub fn severity_from_score(score: f64) -> String {
    if score >= 9.0 {
        "critical".to_owned()
    } else if score >= 7.0 {
        "high".to_owned()
    } else if score >= 4.0 {
        "medium".to_owned()
    } else if score > 0.0 {
        "low".to_owned()
    } else {
        "none".to_owned()
    }
}

pub fn severity_rank(severity: Option<&str>) -> i64 {
    match severity {
        Some("critical") => 5,
        Some("high") => 4,
        Some("medium") => 3,
        Some("low") => 2,
        Some("none") => 1,
        _ => 0,
    }
}

pub fn stable_id(prefix: &str, key: &str) -> String {
    let digest = Sha256::digest(key.as_bytes());
    format!("{prefix}:{}", hex::encode(&digest[..16]))
}

pub fn content_hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

pub fn first_sentence(text: &str, max_len: usize) -> String {
    let trimmed = text.trim();
    let sentence_end = trimmed
        .char_indices()
        .find_map(|(index, ch)| matches!(ch, '.' | '!' | '?').then_some(index + ch.len_utf8()))
        .unwrap_or(trimmed.len());
    truncate_chars(&trimmed[..sentence_end], max_len)
}

pub fn truncate_chars(text: &str, max_len: usize) -> String {
    if text.chars().count() <= max_len {
        return text.to_owned();
    }
    let truncated: String = text.chars().take(max_len.saturating_sub(1)).collect();
    format!("{}…", truncated.trim_end())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_and_deduplicates_cves() {
        assert_eq!(
            extract_cves("CVE-2025-1234 and cve-2025-1234 plus CVE-2024-99999"),
            vec!["CVE-2024-99999", "CVE-2025-1234"]
        );
    }

    #[test]
    fn categorizes_security_text() {
        let categories = classify("A ransomware campaign exploited a zero-day VPN flaw");
        assert!(categories.contains(&"ransomware".to_owned()));
        assert!(categories.contains(&"zero-day".to_owned()));
        assert!(categories.contains(&"network".to_owned()));
    }

    #[test]
    fn strips_basic_markup() {
        assert_eq!(
            strip_html("<p>Hello&nbsp;<strong>world</strong></p>"),
            "Hello world"
        );
    }
}
