(() => {
  "use strict";

  const state = {
    cursor: null,
    loading: false,
    controller: null,
    items: [],
    refreshTimer: null,
    searchTimer: null,
    adminToken: null,
    refreshEnabled: true,
  };

  const elements = {
    feed: document.querySelector("#feed"),
    filters: document.querySelector("#filters"),
    search: document.querySelector("#search"),
    kind: document.querySelector("#kind"),
    severity: document.querySelector("#severity"),
    confidence: document.querySelector("#confidence"),
    category: document.querySelector("#category"),
    exploited: document.querySelector("#exploited"),
    clearFilters: document.querySelector("#clear-filters"),
    reload: document.querySelector("#reload-button"),
    loadMore: document.querySelector("#load-more"),
    summary: document.querySelector("#results-summary"),
    refreshButton: document.querySelector("#refresh-button"),
    refreshStatus: document.querySelector("#refresh-status"),
    refreshIndicator: document.querySelector("#refresh-indicator"),
    sourcesButton: document.querySelector("#sources-button"),
    sourcesDialog: document.querySelector("#sources-dialog"),
    sourcesContent: document.querySelector("#sources-content"),
    detailDialog: document.querySelector("#detail-dialog"),
    detailKicker: document.querySelector("#detail-kicker"),
    detailTitle: document.querySelector("#detail-title"),
    detailContent: document.querySelector("#detail-content"),
    toast: document.querySelector("#toast"),
    statTotal: document.querySelector("#stat-total"),
    statCves: document.querySelector("#stat-cves"),
    statSevere: document.querySelector("#stat-severe"),
    statExploited: document.querySelector("#stat-exploited"),
    statValidated: document.querySelector("#stat-validated"),
  };

  function create(tag, options = {}) {
    const node = document.createElement(tag);
    if (options.className) node.className = options.className;
    if (options.text !== undefined) node.textContent = String(options.text);
    if (options.title) node.title = options.title;
    return node;
  }

  function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value || 0));
  }

  function formatDate(value) {
    if (!value) return "Unknown date";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  }

  function relativeDate(value) {
    if (!value) return "Unknown date";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const absolute = Math.abs(seconds);
    const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    if (absolute < 60) return formatter.format(seconds, "second");
    if (absolute < 3600) return formatter.format(Math.round(seconds / 60), "minute");
    if (absolute < 86400) return formatter.format(Math.round(seconds / 3600), "hour");
    if (absolute < 2592000) return formatter.format(Math.round(seconds / 86400), "day");
    return formatDate(value);
  }

  function safeExternalUrl(value) {
    try {
      const url = new URL(value, window.location.origin);
      if (url.protocol !== "http:" && url.protocol !== "https:") return null;
      return url.href;
    } catch {
      return null;
    }
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
    });
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok) {
      const message = body?.error?.message || `Request failed with HTTP ${response.status}`;
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function currentParameters(includeCursor = false) {
    const params = new URLSearchParams();
    const values = {
      q: elements.search.value.trim(),
      kind: elements.kind.value,
      severity: elements.severity.value,
      confidence: elements.confidence.value,
      category: elements.category.value,
    };
    for (const [key, value] of Object.entries(values)) {
      if (value) params.set(key, value);
    }
    if (elements.exploited.checked) params.set("exploited", "true");
    params.set("limit", "40");
    if (includeCursor && state.cursor) params.set("cursor", state.cursor);
    return params;
  }

  function syncUrl() {
    const params = currentParameters(false);
    params.delete("limit");
    const query = params.toString();
    history.replaceState(null, "", query ? `/?${query}` : "/");
  }

  function loadFiltersFromUrl() {
    const params = new URLSearchParams(location.search);
    elements.search.value = params.get("q") || "";
    elements.kind.value = params.get("kind") || "";
    elements.severity.value = params.get("severity") || "";
    elements.confidence.value = params.get("confidence") || "";
    elements.category.value = params.get("category") || "";
    elements.exploited.checked = params.get("exploited") === "true";
  }

  function renderSkeleton() {
    elements.feed.replaceChildren(...Array.from({ length: 5 }, () => create("div", { className: "skeleton" })));
    elements.feed.setAttribute("aria-busy", "true");
  }

  function badge(text, className = "") {
    return create("span", { className: `badge ${className}`.trim(), text });
  }

  function renderItem(item) {
    const article = create("article", { className: "item-card" });
    const main = create("div", { className: "item-main" });
    const meta = create("div", { className: "item-meta" });
    meta.append(
      create("span", { text: item.source_name }),
      create("span", { text: "•" }),
      create("time", { text: relativeDate(item.effective_timestamp) }),
      create("span", { text: "•" }),
      create("span", { text: item.kind === "cve" ? "Vulnerability" : "News" }),
    );

    const title = create("h2", { className: "item-title" });
    const titleButton = create("button", { text: item.title });
    titleButton.type = "button";
    titleButton.addEventListener("click", () => openDetail(item));
    title.append(titleButton);

    const summary = create("p", {
      className: "item-summary",
      text: item.summary || "No summary supplied by the source.",
    });
    const badges = create("div", { className: "badges" });
    if (item.cve_id) badges.append(badge(item.cve_id));
    if (item.severity) badges.append(badge(item.severity, item.severity));
    if (item.exploited) badges.append(badge("Exploited", "exploited"));
    if (item.confidence) badges.append(badge(`${item.confidence} confidence`, "confidence"));
    for (const category of (item.categories || []).slice(0, 4)) badges.append(badge(category));
    main.append(meta, title, summary, badges);

    const score = create("aside", { className: "item-score" });
    if (item.cvss_score !== null && item.cvss_score !== undefined) {
      score.append(
        create("span", { className: "score-value", text: Number(item.cvss_score).toFixed(1) }),
        create("span", { className: "score-label", text: "CVSS" }),
      );
    } else if (item.epss_probability !== null && item.epss_probability !== undefined) {
      score.append(
        create("span", { className: "score-value", text: `${(Number(item.epss_probability) * 100).toFixed(1)}%` }),
        create("span", { className: "score-label", text: "EPSS" }),
      );
    }
    article.append(main, score);
    return article;
  }

  function renderItems(items, append = false) {
    if (!append) elements.feed.replaceChildren();
    if (!items.length && !append) {
      elements.feed.append(create("div", {
        className: "empty-state",
        text: "No intelligence matched the selected filters.",
      }));
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const item of items) fragment.append(renderItem(item));
    elements.feed.append(fragment);
  }

  async function loadItems({ append = false, background = false } = {}) {
    if (state.loading && (append || background)) return;
    state.loading = true;
    if (state.controller) state.controller.abort();
    const controller = new AbortController();
    state.controller = controller;
    if (!append && !background) renderSkeleton();
    elements.loadMore.disabled = true;

    try {
      const params = currentParameters(append);
      const page = await fetchJson(`/api/v1/items?${params}`, {
        signal: controller.signal,
      });
      if (state.controller !== controller) return;
      if (!append) state.items = [];
      state.items.push(...page.items);
      state.cursor = page.next_cursor || null;
      renderItems(page.items, append);
      elements.loadMore.hidden = !state.cursor;
      elements.summary.textContent = `${formatNumber(state.items.length)} item${state.items.length === 1 ? "" : "s"} loaded`;
      elements.feed.setAttribute("aria-busy", "false");
      syncUrl();
    } catch (error) {
      if (error.name === "AbortError" || state.controller !== controller) return;
      if (!background) {
        elements.feed.replaceChildren();
        const box = create("div", { className: "error-state" });
        box.append(
          create("strong", { text: "Could not load intelligence" }),
          create("span", { text: error.message }),
        );
        elements.feed.append(box);
      }
      showToast(error.message);
    } finally {
      if (state.controller === controller) {
        state.loading = false;
        elements.loadMore.disabled = false;
        elements.feed.setAttribute("aria-busy", "false");
      }
    }
  }

  async function loadStats() {
    try {
      const stats = await fetchJson("/api/v1/stats");
      elements.statTotal.textContent = formatNumber(stats.total_items);
      elements.statCves.textContent = formatNumber(stats.cve_items);
      elements.statSevere.textContent = formatNumber(Number(stats.critical_cves) + Number(stats.high_cves));
      elements.statExploited.textContent = formatNumber(stats.exploited_cves);
      elements.statValidated.textContent = formatNumber(stats.validated_cves);
    } catch (error) {
      showToast(error.message);
    }
  }

  function detailField(label, value) {
    const field = create("div", { className: "detail-field" });
    field.append(create("span", { text: label }), create("strong", { text: value ?? "—" }));
    return field;
  }

  function externalLink(label, value) {
    const url = safeExternalUrl(value);
    if (!url) return null;
    const link = create("a", { text: label });
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  }

  async function openDetail(item) {
    elements.detailKicker.textContent = item.kind === "cve" ? item.cve_id || "Vulnerability" : item.source_name;
    elements.detailTitle.textContent = item.title;
    elements.detailContent.replaceChildren(create("div", { className: "skeleton" }));
    elements.detailDialog.showModal();

    try {
      const detail = item.kind === "cve" && item.cve_id
        ? await fetchJson(`/api/v1/cves/${encodeURIComponent(item.cve_id)}`)
        : { item, evidence: [], validation: null };
      renderDetail(detail);
    } catch (error) {
      elements.detailContent.replaceChildren(create("div", { className: "error-state", text: error.message }));
    }
  }

  function renderDetail(detail) {
    const item = detail.item;
    const container = document.createDocumentFragment();
    const grid = create("div", { className: "detail-grid" });
    grid.append(
      detailField("Severity", item.severity || "Unknown"),
      detailField("CVSS", item.cvss_score === null ? "—" : item.cvss_score),
      detailField("Confidence", item.confidence || "Not calculated"),
      detailField("EPSS", item.epss_probability === null ? "—" : `${(item.epss_probability * 100).toFixed(2)}%`),
      detailField("Vendor", item.vendor || "—"),
      detailField("Product", item.product || "—"),
      detailField("Published", formatDate(item.published_at || item.effective_timestamp)),
      detailField("Sources", item.independent_sources ?? "—"),
      detailField("Known exploited", item.exploited ? "Yes" : "No"),
    );
    container.append(grid);
    container.append(create("h3", { className: "section-title", text: "Summary" }));
    container.append(create("p", { className: "detail-summary", text: item.summary || "No summary supplied." }));

    const sourceLink = externalLink("Open original source ↗", item.url);
    if (sourceLink) {
      const paragraph = create("p");
      paragraph.append(sourceLink);
      container.append(paragraph);
    }
    if (item.remediation) {
      container.append(create("h3", { className: "section-title", text: "Remediation" }));
      container.append(create("p", { className: "detail-summary", text: item.remediation }));
    }

    if (detail.validation) {
      container.append(create("h3", { className: "section-title", text: "Cross-validation" }));
      const flags = create("div", { className: "badges" });
      flags.append(badge(`${detail.validation.independent_sources} independent sources`, "confidence"));
      flags.append(badge(`${detail.validation.authoritative_sources} authoritative sources`, "confidence"));
      if (detail.validation.severity_disagreement) flags.append(badge("Severity disagreement", "exploited"));
      if (detail.validation.cvss_disagreement) flags.append(badge("CVSS disagreement", "exploited"));
      if (detail.validation.uncorroborated_exploitation) flags.append(badge("Exploitation uncorroborated", "exploited"));
      if (detail.validation.missing_canonical) flags.append(badge("Canonical record pending"));
      container.append(flags);
    }

    if (detail.evidence?.length) {
      container.append(create("h3", { className: "section-title", text: "Source evidence" }));
      const list = create("div", { className: "evidence-list" });
      for (const evidence of detail.evidence) {
        const card = create("article", { className: "evidence-card" });
        const header = create("header");
        const identity = create("div");
        identity.append(
          create("strong", { text: evidence.source_name }),
          create("p", { text: evidence.evidence_type }),
        );
        header.append(identity, badge(evidence.authoritative ? "Authoritative" : "Independent"));
        card.append(header);
        if (evidence.summary) card.append(create("p", { text: evidence.summary }));
        const link = externalLink("View evidence ↗", evidence.url);
        if (link) {
          const paragraph = create("p");
          paragraph.append(link);
          card.append(paragraph);
        }
        list.append(card);
      }
      container.append(list);
    }
    elements.detailContent.replaceChildren(container);
  }

  async function loadSources() {
    elements.sourcesContent.replaceChildren(create("div", { className: "skeleton" }));
    elements.sourcesDialog.showModal();
    try {
      const sources = await fetchJson("/api/v1/sources");
      const list = create("div", { className: "source-list" });
      for (const source of sources) {
        const row = create("article", { className: `source-row ${source.last_status}` });
        const identity = create("div");
        identity.append(
          create("strong", { text: source.source_name }),
          create("p", {
            text: source.last_run_at
              ? `Last run ${relativeDate(source.last_run_at)} · ${source.failures_24h} failures in 24h`
              : "No ingestion run recorded yet",
          }),
        );
        if (source.last_error) identity.append(create("p", { text: source.last_error }));
        row.append(identity, create("span", { className: `source-state ${source.last_status}`, text: source.last_status }));
        list.append(row);
      }
      elements.sourcesContent.replaceChildren(list);
    } catch (error) {
      elements.sourcesContent.replaceChildren(create("div", { className: "error-state", text: error.message }));
    }
  }

  async function triggerRefresh() {
    if (!state.refreshEnabled) return;
    elements.refreshButton.disabled = true;
    try {
      const headers = {};
      if (state.adminToken) headers.Authorization = `Bearer ${state.adminToken}`;
      let accepted;
      try {
        accepted = await fetchJson("/api/v1/refresh", { method: "POST", headers });
      } catch (error) {
        if (error.status !== 401) throw error;
        const token = window.prompt("Administrative token");
        if (!token) return;
        state.adminToken = token;
        accepted = await fetchJson("/api/v1/refresh", {
          method: "POST",
          headers: { Authorization: `Bearer ${state.adminToken}` },
        });
      }
      showToast(accepted.accepted ? "Refresh queued." : "A refresh is already active.");
      await pollRefreshStatus();
    } catch (error) {
      showToast(error.message);
    } finally {
      elements.refreshButton.disabled = !state.refreshEnabled;
    }
  }

  async function pollRefreshStatus() {
    if (!state.refreshEnabled) {
      elements.refreshStatus.textContent = "Source refresh disabled";
      return;
    }
    try {
      const status = await fetchJson("/api/v1/refresh/status");
      elements.refreshIndicator.className = `status-dot ${status.state}`;
      const label = {
        idle: "No refresh has run in this process",
        queued: "Refresh queued",
        running: "Refreshing sources…",
        completed: status.finished_at ? `Refresh completed ${relativeDate(status.finished_at)}` : "Refresh completed",
        failed: "Refresh failed",
      }[status.state] || status.state;
      elements.refreshStatus.textContent = label;
      if (status.state === "completed" && status.report) {
        const finished = status.finished_at || status.report.finished_at;
        const lastSeen = elements.refreshStatus.dataset.lastFinished;
        if (finished && finished !== lastSeen) {
          elements.refreshStatus.dataset.lastFinished = finished;
          await Promise.all([loadStats(), loadItems({ background: true })]);
        }
      }
    } catch (error) {
      elements.refreshIndicator.className = "status-dot failed";
      elements.refreshStatus.textContent = "Refresh status unavailable";
    }
  }

  function resetAndLoad() {
    state.cursor = null;
    loadItems();
  }

  function showToast(message) {
    elements.toast.textContent = message;
    elements.toast.hidden = false;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      elements.toast.hidden = true;
    }, 4500);
  }

  function bindEvents() {
    for (const element of [elements.kind, elements.severity, elements.confidence, elements.category, elements.exploited]) {
      element.addEventListener("change", resetAndLoad);
    }
    elements.search.addEventListener("input", () => {
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(resetAndLoad, 350);
    });
    elements.filters.addEventListener("submit", (event) => {
      event.preventDefault();
      resetAndLoad();
    });
    elements.clearFilters.addEventListener("click", () => {
      elements.filters.reset();
      resetAndLoad();
    });
    elements.reload.addEventListener("click", resetAndLoad);
    elements.loadMore.addEventListener("click", () => loadItems({ append: true }));
    elements.refreshButton.addEventListener("click", triggerRefresh);
    elements.sourcesButton.addEventListener("click", loadSources);
    document.querySelectorAll("[data-close]").forEach((button) => {
      button.addEventListener("click", () => document.querySelector(`#${button.dataset.close}`)?.close());
    });
    for (const dialog of document.querySelectorAll("dialog")) {
      dialog.addEventListener("click", (event) => {
        const bounds = dialog.getBoundingClientRect();
        const inside = event.clientX >= bounds.left && event.clientX <= bounds.right
          && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
        if (!inside) dialog.close();
      });
    }
  }

  async function init() {
    loadFiltersFromUrl();
    bindEvents();
    try {
      const health = await fetchJson("/health");
      state.refreshEnabled = health.refresh_enabled !== false;
      elements.refreshButton.disabled = !state.refreshEnabled;
      const banner = document.querySelector("#mode-banner");
      if (health.demo_mode || !state.refreshEnabled) {
        banner.hidden = false;
        banner.textContent = health.demo_mode
          ? "Offline demonstration · All records are fictional training data. Live sources and refresh are disabled."
          : "Source refresh is disabled. The dashboard shows previously stored intelligence.";
      }
    } catch (error) {
      showToast("Service status unavailable: " + error.message);
    }
    await Promise.all([loadStats(), loadItems(), pollRefreshStatus()]);
    state.refreshTimer = window.setInterval(pollRefreshStatus, 15000);
    window.setInterval(() => loadItems({ background: true }), 60000);
  }

  init();
})();
