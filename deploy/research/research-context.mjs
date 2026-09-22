// A reproducible view of the sealed request; never an evidence or authority source.
import { createHash } from 'node:crypto';
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const bytes = value => Buffer.byteLength(JSON.stringify(value), 'utf8');

export function buildResearchContext(request) {
  const context = structuredClone(request);
  const manifest = context.manifest || {};
  const summary = manifest.research_summary || {};
  const catalog = summary.world?.catalog;
  // Catalog is already compact [element, name, club] rows; preserve its contract.
  const focus = summary.focus || [];
  const unique = [...new Map(focus.map(row => [row.element, row])).values()];
  const groups = new Map();
  for (const row of unique) {
    // Unknown clubs cannot be assumed to share a source.
    const team = row.team == null ? `unknown:${row.element}` : String(row.team);
    if (!groups.has(team)) groups.set(team, []);
    groups.get(team).push(row.element);
  }
  const clubs = [...groups].map(([team, elements]) => ({team, elements}))
    .sort((a, b) => b.elements.length - a.elements.length || a.team.localeCompare(b.team));
  const documentBudget = request.scope_policy?.max_documents;
  const knownBudget = Number.isInteger(documentBudget) && documentBudget >= 0;
  const target = Math.ceil(unique.length * 0.9);
  let covered = 0;
  let needed = 0;
  for (const group of clubs) {
    if (covered >= target) break;
    covered += group.elements.length;
    needed++;
  }
  const capacity = knownBudget
    ? clubs.slice(0, documentBudget).reduce((sum, group) => sum + group.elements.length, 0)
    : null;
  context.acquisition_plan = {
    schema: 'mova-research-acquisition-plan-v1',
    focus_subjects: unique.length, clubs,
    target_checked_subjects: target,
    reusable_hints: (summary.reusable_evidence_hints || []).length,
    conditional_club_source_capacity: capacity,
    conditional_documents_for_target: needed,
    conditional_scope_shortfall: knownBudget ? capacity < target : null,
    assumption: 'One fresh document per club explicitly names every focus member; multi-club sources can exceed this estimate. Hints are not verified coverage.',
    priorities: ['global radar within scope_policy', 'own squad risk and captain uncertainty',
      'candidate decision uncertainty', 'uncovered club groups'],
    on_shortfall: 'Keep budgets unchanged; report not_checked and explain missing evidence.',
  };
  const receipt = {
    schema: 'mova-research-context-receipt-v1',
    request_sha256: request.request_sha256,
    context_sha256: hash(context),
    request_json_bytes: bytes(request), context_json_bytes: bytes(context),
    omitted_sections: [],
    catalog_encoding: "unchanged",
    focus_subjects: unique.length,
    catalog_subjects: Array.isArray(catalog) ? catalog.length : 0,
    prior_gameweek_signals: (summary.prior_gameweek_signals || []).length,
    reusable_hints: (summary.reusable_evidence_hints || []).length,
    acquisition_plan: context.acquisition_plan,
  };
  return {context, receipt};
}
