// Deterministic structural repair for untrusted LLM research output.
// It never invents evidence: unsupported rows are dropped or downgraded.

const TRACKING = new Set(["fbclid", "gclid", "mc_cid", "mc_eid"]);

function canonicalUrl(value) {
  try {
    const url = new URL(String(value));
    if (url.protocol !== "https:" || url.username || url.password) return null;
    url.hostname = url.hostname.toLowerCase().replace(/\.$/, "");
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (TRACKING.has(key.toLowerCase()) || key.toLowerCase().startsWith("utm_")) {
        url.searchParams.delete(key);
      }
    }
    if (!url.pathname) url.pathname = "/";
    return url.toString();
  } catch {
    return null;
  }
}

function uniqueCanonicalUrls(values, allowed) {
  const output = [];
  for (const value of Array.isArray(values) ? values : []) {
    const canonical = canonicalUrl(value);
    if (canonical && allowed.has(canonical) && !output.includes(canonical)) output.push(canonical);
  }
  return output;
}

export function normalizeResearchBrief(input, request) {
  const brief = structuredClone(input || {});
  const report = {
    schema: "mova-research-normalization-v1",
    documents_received: Array.isArray(brief.documents) ? brief.documents.length : 0,
    documents_emitted: 0,
    duplicate_documents_removed: 0,
    signal_references_removed: 0,
    signals_dropped: 0,
    conflict_references_removed: 0,
    conflicts_dropped: 0,
    coverage_references_removed: 0,
    coverage_rows_added: 0,
    coverage_rows_dropped: 0,
    coverage_rows_downgraded: 0,
    changed: false,
  };

  const documents = [];
  const documentUrls = new Set();
  for (const row of Array.isArray(brief.documents) ? brief.documents : []) {
    const canonical = canonicalUrl(row?.source_url);
    if (!canonical || documentUrls.has(canonical)) {
      if (canonical) report.duplicate_documents_removed += 1;
      continue;
    }
    documentUrls.add(canonical);
    documents.push({...row, source_url: canonical});
  }
  brief.documents = documents;
  report.documents_emitted = documents.length;

  const signals = [];
  for (const row of Array.isArray(brief.signals) ? brief.signals : []) {
    const before = Array.isArray(row?.source_urls) ? row.source_urls.length : 0;
    const sourceUrls = uniqueCanonicalUrls(row?.source_urls, documentUrls);
    report.signal_references_removed += Math.max(0, before - sourceUrls.length);
    if (!sourceUrls.length) {
      report.signals_dropped += 1;
      continue;
    }
    signals.push({...row, source_urls: sourceUrls});
  }
  brief.signals = signals;

  const conflicts = [];
  for (const row of Array.isArray(brief.conflicts) ? brief.conflicts : []) {
    const before = Array.isArray(row?.source_urls) ? row.source_urls.length : 0;
    const sourceUrls = uniqueCanonicalUrls(row?.source_urls, documentUrls);
    report.conflict_references_removed += Math.max(0, before - sourceUrls.length);
    if (!sourceUrls.length) {
      report.conflicts_dropped += 1;
      continue;
    }
    conflicts.push({...row, source_urls: sourceUrls});
  }
  brief.conflicts = conflicts;

  const focus = request?.manifest?.research_summary?.focus;
  const focusElements = [];
  for (const row of Array.isArray(focus) ? focus : []) {
    const element = Number(row?.element);
    if (Number.isInteger(element) && element > 0 && !focusElements.includes(element)) {
      focusElements.push(element);
    }
  }
  const received = Array.isArray(brief.coverage?.subjects) ? brief.coverage.subjects : [];
  const receivedByElement = new Map();
  for (const row of received) {
    const element = Number(row?.player_element);
    if (focusElements.includes(element) && !receivedByElement.has(element)) {
      receivedByElement.set(element, row);
    } else {
      report.coverage_rows_dropped += 1;
    }
  }
  const materialElements = new Set(
    signals.map(row => Number(row.player_element)).filter(Number.isInteger),
  );
  const coverage = [];
  for (const element of focusElements) {
    const original = receivedByElement.get(element);
    if (!original) report.coverage_rows_added += 1;
    const before = Array.isArray(original?.source_urls) ? original.source_urls.length : 0;
    let sourceUrls = uniqueCanonicalUrls(original?.source_urls, documentUrls);
    report.coverage_references_removed += Math.max(0, before - sourceUrls.length);
    let status = original?.status || "not_checked";
    if (status === "material_signal" && !materialElements.has(element)) {
      status = sourceUrls.length ? "no_material_update" : "not_checked";
      report.coverage_rows_downgraded += 1;
    }
    if (status !== "not_checked" && !sourceUrls.length) {
      status = "not_checked";
      report.coverage_rows_downgraded += 1;
    }
    if (status === "not_checked") sourceUrls = [];
    coverage.push({
      player_element: element,
      status,
      source_urls: sourceUrls,
      note: String(original?.note || "Sin evidencia verificable en esta corrida.").slice(0, 500),
    });
  }
  brief.coverage = {subjects: coverage};

  report.changed = Object.entries(report).some(([key, value]) => (
    !["schema", "documents_received", "documents_emitted", "changed"].includes(key)
      && typeof value === "number" && value > 0
  ));
  if (report.changed) {
    const limitations = Array.isArray(brief.limitations) ? brief.limitations.slice(0, 19) : [];
    limitations.push(
      "El normalizador determinista descartó o degradó referencias sin documento sellable; no se inventó evidencia.",
    );
    brief.limitations = limitations;
  }
  return {brief, report};
}
