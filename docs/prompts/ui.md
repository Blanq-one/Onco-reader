# Task: build the frontend (folder: app/)

Goal: the frontend is the best part of this project. A judge opens it, finishes
the whole workflow alone, checks one number against its calculation, and
inspects one limitation, with nobody narrating.

Read first: CLAUDE.md, contract/README.md, contract/FRONTEND_BRIEF.md,
contract/mock_findings.json, and out/findings.json (real data).

## Constraints
- Zero-install static site: HTML, CSS and vanilla JavaScript (ES modules). No
  build step, no CDN, no web fonts (system font stack). Works offline.
- Served with `python -m http.server` from the repo root; the app lives at
  http://localhost:8000/app/. Use hash routing (#/results, #/claim/claim-003).
- Charts are inline SVG written by hand. No chart libraries.
- Edit only app/. Do not change the engine, contract or tests.

## Data
- Default: load ../out/findings.json. The query string ?data=contract/mock_findings.json
  loads another file (use it to test blocked states and the mock banner).
- If is_mock is true, show a loud SAMPLE DATA banner.
- Handle nulls everywhere: evidence.value, robustness, cohort_trace (can be
  empty), evidence.breakdown (optional), data_notes (optional).
- Optional live mode: the local server may offer POST /api/audit.
  Request: {"claims": ["..."]} or {"report": "text"}. Response: same shape as
  findings.json. Errors: {"error": "..."} with a 4xx status. GET /api/health
  returns {"ok": true}. On load, call /api/health. If it answers, show a
  "Run your own claims" box with inline progress. If it does not answer, hide
  the box without any error message.

## Pages
1. Start (#/): one-line purpose, data release and checksum badge, a big
   "Open the demo findings" button, the live box if available, link to About.
2. Results (#/results): summary strip (counts of supported, contradicted,
   insufficient, needs review), claim list with verdict badges (icon plus text,
   never color alone), filters (verdict, needs review, flags), search, sort.
   Filters and scroll survive going into a claim and back.
3. Claim detail (#/claim/:id): verdict card with the headline number as
   "n of denominator"; cohort funnel from cohort_trace as animated SVG;
   "Show me the calculation" panel (calculation text, source files, a copy
   button); limitation banner always visible; next actions list; robustness
   toggle (show alt_rule and alt_value, say whether the verdict changes);
   needs-review block with reason and approve / reject / ask-for-more (saved in
   localStorage); breakdown bar chart when evidence.breakdown exists, with a
   marker for groups under interpretation_config.min_group_size samples or
   min_events deaths; previous and next claim arrows.
4. Compare (#/compare?a=claim-002&b=claim-006): two claims side by side in the
   same rows, differences highlighted. Entry points on each card and a
   multi-select on Results.
5. Review queue (#/review): only needs_human_review items, one at a time,
   progress "2 of 5 reviewed", decision plus optional note; finishing goes to
   the Summary.
6. Summary (#/summary): decisions, counts and all next actions on one printable
   page (print stylesheet), plus a download of the findings JSON.
7. About (#/about): data release, checksum status, data_notes table (which
   clinical column was used and why, with alternatives), the rules (no clinical
   claims, no individual patients), what each verdict means.
8. Not found: friendly page with a link home.

## States
- Blocked flags (clinical_claim_blocked, individual_level_request_blocked,
  reidentification_blocked, phi_like_input, prompt_injection_suspected,
  invalid_input): a clear blocked state, no number, no result styling.
- data_cannot_answer: says what is missing and shows next actions.
- low_event_count: warning style plus the review flag.
- Empty, loading, error: each has a designed state.

## Navigation, motion, quality
- Persistent top bar and breadcrumbs. Opening a page with no data loaded
  redirects to Start and returns to the intended page afterwards.
- Shortcuts: j/k or arrows move between claims, / focuses search, c compares,
  ? opens a shortcut overlay, Esc closes dialogs.
- Transitions under 250 ms: page fade and slide, funnel bars animate in order,
  numbers count up once. Respect prefers-reduced-motion by turning motion off.
- Dark theme by default, light theme toggle, design tokens as CSS variables.
- Keyboard-only use works, visible focus rings, WCAG AA contrast, responsive
  down to a phone width.
- Words: Supported, Contradicted, Insufficient evidence. Never imply clinical
  advice or readiness for real-world use.

## Process
Work in milestones and commit after each on your branch:
1. Shell, routing, data loading, mock banner.
2. Results and Claim detail (funnel, calculation, limitation, next actions, all states).
3. Compare, Review queue, Summary, About, live box.
4. Polish: transitions, shortcuts, accessibility pass, print stylesheet.
After each milestone load both data files and check for console errors. Use
Playwright to screenshot pages if it is installed; otherwise list the manual
checks you could not run.

## Final report (short)
What is done, what is missing, how to run it, and any change you need in other
folders.
