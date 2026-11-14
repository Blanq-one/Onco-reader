// Checks the pure helpers of the multiple-reports view (app/js/batch_logic.js) without a browser.
// Run by tests/test_app_batch.py: node tests/js/batch_logic.mjs   Prints one JSON object.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const L = await import(pathToFileURL(path.join(root, 'app', 'js', 'batch_logic.js')).href);

const blocked = (f) => f.guardrail_flags.includes('clinical_claim_blocked');
const f = (verdict, flags = [], review = false) => ({ verdict, guardrail_flags: flags, needs_human_review: review });
const findings = [f('supported'), f('supported'), f('contradicted', [], true), f('insufficient_evidence'), f('insufficient_evidence', ['clinical_claim_blocked'], true)];

const a = L.pseudonymizer(), b = L.pseudonymizer();
const first = ['TCGA-AA-0003-01', 'TCGA-AA-0001-01', 'TCGA-AA-0003-01'].map(a);
const other = ['TCGA-AA-0001-01'].map(b);
const masked = L.maskGroups([{ label: 'x', total: 3, ids: ['TCGA-AA-0003-01', 'TCGA-AA-0001-01'], kind: 'included' }], L.pseudonymizer());
console.log(JSON.stringify({
  labels: [0, 1, 25, 26, 27].map(L.reportLabel), tally: L.tally(findings, blocked), first, other, masked,
  leaks: JSON.stringify(masked).includes('TCGA'),
}));
