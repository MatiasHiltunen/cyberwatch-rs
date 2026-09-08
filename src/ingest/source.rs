use std::{collections::HashSet, sync::Arc};

use anyhow::{Result, bail};
use async_trait::async_trait;
use reqwest::Client;
use url::Url;

use crate::{
    Config, Repository,
    models::{IngestBatch, SourceDescriptor},
};

#[derive(Clone)]
pub struct SourceContext {
    pub config: Arc<Config>,
    pub repository: Repository,
    pub http: Client,
}

#[derive(Debug, Clone, Default)]
pub struct SourceOutput {
    pub batch: IngestBatch,
    pub fetched: usize,
    pub candidate_upserts: usize,
    pub skipped: bool,
    pub note: Option<String>,
}

impl SourceOutput {
    pub fn unchanged(note: impl Into<String>) -> Self {
        Self {
            skipped: true,
            note: Some(note.into()),
            ..Self::default()
        }
    }

    pub fn validate(&self, descriptor: &SourceDescriptor) -> Result<()> {
        let mut item_ids = HashSet::new();
        for item in &self.batch.items {
            if item.id.trim().is_empty() || item.id.len() > 240 {
                bail!("source {} emitted an invalid item ID", descriptor.id);
            }
            if !matches!(item.kind.as_str(), "news" | "cve") {
                bail!(
                    "source {} emitted invalid item kind {}",
                    descriptor.id,
                    item.kind
                );
            }
            if item.source_id != descriptor.id {
                bail!(
                    "source {} emitted item {} with mismatched source ID {}",
                    descriptor.id,
                    item.id,
                    item.source_id
                );
            }
            if item.title.trim().is_empty() || item.title.len() > 1_000 {
                bail!("source {} emitted an invalid title", descriptor.id);
            }
            let url = Url::parse(&item.url)
                .map_err(|error| anyhow::anyhow!("item {} URL is invalid: {error}", item.id))?;
            if !matches!(url.scheme(), "http" | "https") {
                bail!("item {} URL must use HTTP or HTTPS", item.id);
            }
            if let Some(score) = item.cvss_score {
                if !(0.0..=10.0).contains(&score) {
                    bail!("item {} has CVSS score outside 0-10", item.id);
                }
            }
            if !item_ids.insert(item.id.as_str()) && item.kind == "news" {
                bail!(
                    "source {} emitted duplicate news item {}",
                    descriptor.id,
                    item.id
                );
            }
        }

        for evidence in &self.batch.evidence {
            if !is_cve_id(&evidence.cve_id) {
                bail!(
                    "source {} emitted invalid CVE ID {}",
                    descriptor.id,
                    evidence.cve_id
                );
            }
            if evidence.source_id != descriptor.id {
                bail!(
                    "source {} emitted evidence with mismatched source ID",
                    descriptor.id
                );
            }
            if let Some(score) = evidence.cvss_score {
                if !(0.0..=10.0).contains(&score) {
                    bail!(
                        "evidence for {} has CVSS score outside 0-10",
                        evidence.cve_id
                    );
                }
            }
        }
        Ok(())
    }
}

#[async_trait]
pub trait SourceAdapter: Send + Sync {
    fn descriptor(&self) -> SourceDescriptor;
    async fn run(&self, context: &SourceContext) -> Result<SourceOutput>;
}

#[derive(Default)]
pub struct SourceRegistry {
    adapters: Vec<Arc<dyn SourceAdapter>>,
    ids: HashSet<String>,
}

impl SourceRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register<T>(&mut self, adapter: T) -> Result<()>
    where
        T: SourceAdapter + 'static,
    {
        self.register_arc(Arc::new(adapter))
    }

    pub fn register_arc(&mut self, adapter: Arc<dyn SourceAdapter>) -> Result<()> {
        let descriptor = adapter.descriptor();
        if descriptor.id.trim().is_empty() {
            bail!("source adapters require a non-empty ID");
        }
        if !self.ids.insert(descriptor.id.clone()) {
            bail!("duplicate source adapter ID {}", descriptor.id);
        }
        self.adapters.push(adapter);
        Ok(())
    }

    pub fn adapters(&self) -> Vec<Arc<dyn SourceAdapter>> {
        self.adapters.clone()
    }

    pub fn descriptors(&self) -> Vec<SourceDescriptor> {
        self.adapters
            .iter()
            .map(|adapter| adapter.descriptor())
            .collect()
    }

    pub fn len(&self) -> usize {
        self.adapters.len()
    }

    pub fn is_empty(&self) -> bool {
        self.adapters.is_empty()
    }
}

fn is_cve_id(value: &str) -> bool {
    let Some(rest) = value.strip_prefix("CVE-") else {
        return false;
    };
    let mut parts = rest.split('-');
    matches!(
        (parts.next(), parts.next(), parts.next()),
        (Some(year), Some(sequence), None)
            if year.len() == 4
                && year.bytes().all(|byte| byte.is_ascii_digit())
                && sequence.len() >= 4
                && sequence.len() <= 8
                && sequence.bytes().all(|byte| byte.is_ascii_digit())
    )
}

#[cfg(test)]
mod tests {
    use anyhow::Result;
    use async_trait::async_trait;

    use super::*;

    struct Dummy;

    #[async_trait]
    impl SourceAdapter for Dummy {
        fn descriptor(&self) -> SourceDescriptor {
            SourceDescriptor {
                id: "dummy".into(),
                name: "Dummy".into(),
                kind: "test".into(),
                region: "Global".into(),
                language: "en".into(),
                role: "test".into(),
                trust: 1,
                timeout_seconds: 30,
                retry_attempts: 0,
            }
        }

        async fn run(&self, _context: &SourceContext) -> Result<SourceOutput> {
            Ok(SourceOutput::default())
        }
    }

    #[test]
    fn rejects_duplicate_adapter_ids() {
        let mut registry = SourceRegistry::new();
        registry.register(Dummy).expect("first adapter");
        assert!(registry.register(Dummy).is_err());
    }
}
