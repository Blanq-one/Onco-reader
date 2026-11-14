// Checks the Extraction view's edit rules (app/js/extract_logic.js) without a browser.
// Run by tests/test_app_extract.py: node tests/js/extract_logic.mjs   Prints one JSON object.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const L = await import(pathToFileURL(path.join(root, 'app', 'js', 'extract_logic.js')).href);

const fresh = () => ({
  claims: [{ text: 'RNA covers 90 percent.', source: 'RNA covers 90 percent of tumors, as noted.' }, { text: '[claim withheld: it contained personal details]', source: '[claim withheld: it contained personal details]' }],
  skipped: [{ text: 'Protein covers most tumors.', reason: 'no number' }, { text: '[withheld]', reason: 'personal details' }],
});
const out = {};
let ex = fresh();
out.editBad = L.editClaim(ex.claims, 0, '   ');
out.editLong = L.editClaim(ex.claims, 0, 'x'.repeat(L.MAX_CHARS + 1));
out.edit = L.editClaim(ex.claims, 0, 'RNA covers 99 percent.');
out.afterEdit = { ...ex.claims[0] };
L.editClaim(ex.claims, 0, 'RNA covers 98 percent.');                    // edited twice: the original is still the extracted one
out.twice = ex.claims[0].edit.original;
L.editClaim(ex.claims, 0, 'RNA covers 90 percent.');                    // put back: not an edit any more
out.reverted = { ...ex.claims[0] };
out.addBad = L.addClaim(ex, '');
out.add = L.addClaim(ex, 'Protein covers 70 percent.');
out.anyway = L.checkAnyway(ex, 0);
out.anywayWithheld = L.checkAnyway(ex, 0);                              // the withheld one is now first
out.skippedLeft = ex.skipped.map((s) => s.text);
out.payload = L.claimsPayload(ex.claims);
out.changes = L.hasReviewerChanges(ex.claims);
out.removeExtracted = L.removeAdded(ex.claims, 0);
out.removeAdded = L.removeAdded(ex.claims, ex.claims.length - 1);
out.untouched = L.hasReviewerChanges(fresh().claims);
// reviewer_edits, including a withheld original
ex = fresh();
L.editClaim(ex.claims, 1, 'Mutation data covers 60 percent.');
L.addClaim(ex, 'Added claim text.');
L.checkAnyway(ex, 0);
out.edits = L.reviewerEdits(ex.claims);
// the 50 claim limit
const full = { claims: Array.from({ length: L.MAX_CLAIMS }, (_, i) => ({ text: 'c' + i, source: 'c' + i })), skipped: [{ text: 'a sentence', reason: 'r' }] };
out.limitAdd = L.addClaim(full, 'one more');
out.limitAnyway = L.checkAnyway(full, 0);
out.isWithheld = ['[withheld]', '[claim withheld: it contained personal details]', 'RNA covers 90 percent.'].map(L.isWithheld);
console.log(JSON.stringify(out));
