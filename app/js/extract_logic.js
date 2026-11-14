// Pure helpers for the Extraction view: what a reviewer can change before the audit (no DOM, so Node can test them).
// A claim is { text, source, origin?, edit? }. origin ('edited' | 'added') is what the server sees; edit records how it changed:
//   { kind: 'edited', original, originalSource } | { kind: 'added', original: null } | { kind: 'checked_anyway', original }
export const MAX_CLAIMS = 50, MAX_CHARS = 2000;

// The extractor withholds sentences with personal details; the app never shows or re-sends them.
export const isWithheld = (t) => /^\[(claim )?withheld/i.test(String(t || '').trim());

export function checkText(text, claimCount) {
  const t = String(text || '').trim();
  if (!t) return 'Write the claim first.';
  if (t.length > MAX_CHARS) return 'A claim can be at most ' + MAX_CHARS + ' characters.';
  if (claimCount != null && claimCount >= MAX_CLAIMS) return 'An audit can check at most ' + MAX_CLAIMS + ' claims.';
  return '';
}

export function editClaim(claims, i, text) {
  const c = claims[i], t = String(text || '').trim();
  const err = c ? checkText(t) : 'No such claim.';
  if (err) return { ok: false, error: err };
  if (c.edit && c.edit.kind !== 'edited') { c.text = t; c.source = t; return { ok: true }; }
  if (!c.edit) c.edit = { kind: 'edited', original: c.text, originalSource: c.source };
  if (t === c.edit.original) { c.source = c.edit.originalSource; c.text = t; delete c.origin; delete c.edit; return { ok: true }; }  // put back: no longer an edit
  c.text = t; c.source = t; c.origin = 'edited';
  return { ok: true };
}

export function addClaim(ex, text) {
  const t = String(text || '').trim(), err = checkText(t, ex.claims.length);
  if (err) return { ok: false, error: err };
  ex.claims.push({ text: t, source: t, origin: 'added', edit: { kind: 'added', original: null } });
  return { ok: true, index: ex.claims.length - 1 };
}

export function checkAnyway(ex, j) {
  const s = ex.skipped[j];
  if (!s) return { ok: false, error: 'No such sentence.' };
  if (isWithheld(s.text)) return { ok: false, error: 'This sentence was withheld because it holds personal details.' };
  const err = checkText(s.text, ex.claims.length);
  if (err) return { ok: false, error: err };
  ex.skipped.splice(j, 1);
  ex.claims.push({ text: s.text, source: s.text, origin: 'added', edit: { kind: 'checked_anyway', original: s.text } });
  return { ok: true, index: ex.claims.length - 1 };
}

// Only a claim the reviewer added can be taken out again. Extracted claims stay (edit them instead).
export function removeAdded(claims, i) {
  const c = claims[i];
  if (!c || !c.edit || c.edit.kind === 'edited') return false;
  claims.splice(i, 1);
  return true;
}

// What the server needs: the reviewer's wording, and which claims a person touched.
export const claimsPayload = (claims) => claims.map((c) => (c.origin ? { text: c.text, source: c.source, origin: c.origin } : { text: c.text, source: c.source }));
export const hasReviewerChanges = (claims) => claims.some((c) => c.origin);

// review.json's reviewer_edits. A withheld original is recorded as the single word "withheld", on both sides.
export function reviewerEdits(claims) {
  return claims.filter((c) => c.edit).map((c) => {
    const w = c.edit.original != null && isWithheld(c.edit.original);
    return { kind: c.edit.kind, original_text: c.edit.kind === 'added' ? null : (w ? 'withheld' : c.edit.original), new_text: w ? 'withheld' : c.text };
  });
}
