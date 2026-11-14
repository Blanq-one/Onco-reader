// Pure helpers for the multiple-reports view (no DOM), so they can be tested with Node.

// "Report 1", "Report 2", ... in the order the reports were added.
export const reportLabel = (i) => 'Report ' + (i + 1);

// Verdict tally for one report's findings. Blocked claims are counted on their own, not as insufficient evidence.
export function tally(findings, isBlocked) {
  const t = { total: findings.length, supported: 0, contradicted: 0, insufficient: 0, blocked: 0, review: 0 };
  for (const f of findings) {
    if (isBlocked(f)) t.blocked++;
    else if (f.verdict === 'supported') t.supported++;
    else if (f.verdict === 'contradicted') t.contradicted++;
    else t.insufficient++;
    if (f.needs_human_review) t.review++;
  }
  return t;
}

// Per-report pseudonyms for sample barcodes: "Sample 1", "Sample 2", ... in order of first use.
// A new pseudonymizer per report, so the same barcode in two reports gets unrelated names.
export function pseudonymizer() {
  const seen = new Map();
  return (id) => {
    if (!seen.has(id)) seen.set(id, 'Sample ' + (seen.size + 1));
    return seen.get(id);
  };
}
export const maskGroups = (groups, pseudo) => groups.map((g) => ({ ...g, ids: (g.ids || []).map(pseudo) }));
