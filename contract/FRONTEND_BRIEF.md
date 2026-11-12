# Frontend brief (for A)

Goal: the frontend is the best part of this project. A judge should be able to
open it, finish the whole workflow alone, verify one result, and inspect one
limitation, with nobody narrating. Feels smooth, looks sharp, never lies.

Build against `mock_findings.json` and `mock_report.md` first. Do not wait for
the real data. Every field you need is in `contract/README.md`.

## Stack (A decides, with these constraints)
Suggested: React + Vite + Tailwind, Framer Motion for transitions, Recharts or
D3 for the funnel chart, React Router for pages.
Constraints, whatever you pick:
- Runs from a fresh clone with 3 commands or fewer, documented in the README
  (another team will try this on Friday).
- Reads findings from one configurable path or URL (default: the mock file),
  so swapping mock for real data is a one-line change.
- No API keys or secrets in frontend code. Any LLM key lives only in the backend.
- Never commit raw TCGA files.
- Handle nulls gracefully: `value` can be null, `robustness` can be null,
  `cohort_trace` can be empty.

## Pages and routes
1. **Start (`/`)**
   - One-line purpose, the data release name, and a checksum status badge.
   - Big "Try the sample report" button (the zero-narration path).
   - Upload or paste your own report as a second option.
   - Loud "SAMPLE DATA" banner whenever `is_mock` is true.
   - Link to "How this works and what it will not do".
2. **Run (`/run`)**
   - Step-by-step progress: reading claims, running checks, assembling evidence.
   - Skeleton loaders, not spinners. A visible cancel and a clear error state.
3. **Results (`/results`)**
   - Summary strip: counts of supported, contradicted, insufficient, needs review.
   - Claim list with verdict badges (icon plus text, never color alone).
   - Filters (verdict, needs review, guardrail flags), sort, and search.
   - Filters and scroll position survive going into a claim and coming back.
4. **Claim detail (`/claim/:id`)**
   - Verdict card with the headline number shown with its denominator, such as
     "440 of 1080".
   - Cohort funnel chart from `cohort_trace`, animated step by step.
   - "Show me the calculation" panel: calculation text and source files.
   - Limitation banner, always visible, never collapsible.
   - Next actions list (from `next_actions`).
   - Robustness toggle: switch to the alternative rule and show whether the
     verdict changes.
   - Needs-review block with the reason and approve / reject / ask-for-more.
   - Previous and next claim arrows.
5. **Compare (`/compare?a=mock-002&b=mock-006`)**
   - Side by side: two claims, or one claim under two rules.
   - Same metrics in the same rows, with differences highlighted.
   - Entry points: a "Compare" button on each card and a multi-select on Results.
6. **Review queue (`/review`)**
   - Only items with `needs_human_review`, one at a time, with progress such as
     "2 of 3 reviewed".
   - Decision plus an optional note. Decisions persist in the browser.
   - Finishing the queue redirects to the Summary.
7. **Summary and export (`/summary`)**
   - Decisions, counts, and all next actions in one printable page.
   - Download findings JSON, and a print-friendly view.
8. **How it works and limits (`/about`)**
   - Data release, checksum status, rules (no clinical claims, no individual
     patient work), and what each verdict means.
9. **Not found (`/*`)**: friendly page with a link home.

## Navigation and redirection rules
- Persistent top bar: Start, Results, Review, Compare, Summary, About.
- Breadcrumbs on detail and compare pages.
- Every claim has a shareable deep link (`/claim/:id`).
- If someone opens `/results` or `/claim/:id` with no report loaded, redirect to
  `/` with a short message, and keep the intended page so they land there after
  loading.
- After a run finishes, redirect to Results.
- "Review this" on a claim goes to the Review queue positioned on that item.
- Back button always returns to the previous filter and scroll state.
- Keyboard shortcuts: `j`/`k` or arrows move between claims, `/` focuses
  search, `c` compares, `?` opens a shortcut help overlay, `Esc` closes dialogs.

## Smooth transitions
- Page transitions: short fade plus small slide, under 250 ms.
- Shared-element transition from a claim row to its detail card
  (Framer Motion `layoutId`).
- Funnel bars animate in order, so the shrink reads as a story.
- Numbers count up once on first view. Verdict badges animate in subtly.
- Skeleton screens while loading, no layout jumps.
- Respect `prefers-reduced-motion`: turn animations off completely.

## States that must exist (guardrail UX)
- **Blocked** (`clinical_claim_blocked`, `individual_level_request_blocked`):
  clear explanation, no number, no verdict styling that looks like a result.
- **Cannot answer** (`data_cannot_answer`): says what is missing and shows next actions.
- **Low event count** (`low_event_count`): warning style plus review flag.
- **Empty, loading, error, offline**: each has a designed state.
- **Mock data**: persistent banner.

## Design system
- Design tokens first (color, spacing, type scale, radius), light and dark mode.
- Verdict colors always paired with icon and label.
- Contrast that passes WCAG AA, visible focus rings, full keyboard use.
- Run axe-core or Lighthouse on every page before Friday.
- Consistent wording. Never use words that imply clinical advice, diagnosis, or
  production readiness.

## Judge-friendly extras (after the core works)
- "Guided tour" button: 4 or 5 tooltips that walk through the key screens.
- "Demo path" button that opens the most interesting claims in order.
- "Copy evidence" button on each card for citing a result.
- Compact "evidence receipt" on every card: release, samples, calculation,
  limitation, reviewer.

## Priorities
- **P0 (must):** Start, Run, Results, Claim detail with funnel, calculation
  panel, limitation banner and next actions, all guardrail states, mock banner,
  fresh-clone README.
- **P1 (should):** Compare, Review queue, Summary and export, About, filters,
  keyboard shortcuts, deep links and redirects.
- **P2 (wow):** shared-element transitions, count-up numbers, guided tour,
  demo path, dark mode polish.

## Definition of done (before the Friday repo swap)
- Fresh clone to running app in 3 commands or fewer.
- Whole flow works on mock data with no console errors.
- All guardrail states reachable from the mock file.
- Keyboard-only run-through works.
- Axe or Lighthouse accessibility check run on every page.
- No secrets, no raw data committed.
- Swapping the findings path to real data requires no code changes.
