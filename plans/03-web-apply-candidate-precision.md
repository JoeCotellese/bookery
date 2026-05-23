# [plan-03] Web Apply-Candidate Precision — per-field control, diff state, progress, copy

## Defect

The enrich → candidate → apply flow treats the candidate as a single opaque payload. Apply is all-or-nothing; the diff is plain text with no visual distinction between change / same / clear; provider search is silent for several seconds with no indication the click registered; control labels (`Go`, `View`, `Isbn`, `Series Index`) read like internal API names rather than user actions. The user cannot reason precisely about what apply will do, when it will finish, or what the controls mean.

## Children

- #121 — per-field accept/reject when applying candidate metadata
- #133 — visual diff highlighting on apply-candidate (change / same / clear)
- #132 — loading indicator during metadata provider search
- #142 — enrich/diff copy polish (Go → Search providers, View → Compare, etc.)

## Fix sequence

1. **Per-field checkbox column on the diff view.** Defaults: all changed fields checked. Submit applies only checked fields; unselected fields preserve current values. List fields (tags, identifiers) selectable as a whole (per-item granularity is a follow-up).
2. **Diff cell state CSS.** `.diff-change` (subtle yellow bg, proposed bold), `.diff-same` (muted/small), `.diff-clear` (red tint + glyph + confirm). Server emits the class per row from a single diff helper that all renders go through.
3. **`hx-indicator` per provider row** on the enrich search. Spinner appears on `htmx:beforeRequest`, persists until that provider's results render. Submit button disabled in-flight. Cancel/Reset clears in-flight state.
4. **Copy pass on enrich/diff controls.** `Go → Search providers`, `View → Compare`, `Isbn → ISBN`, `Series Index → Series #`, confidence `1.00` → High/Medium/Low badge with numeric tooltip, enriched badge tooltip = provider + date. Stronger visual divider between ISBN field and free-text field. Drop redundant Cancel on diff.

## Test matrix

| Axis A (selection) | Axis B (field shape) | Required behavior |
|---|---|---|
| all checked | scalar (title) | proposed value written |
| all checked | list (tags) | proposed list replaces current |
| none checked | any | no-op, returns to detail unchanged |
| partial: title only | scalar | title updated; description, ISBN unchanged |
| field clears | required field (title) | confirm gate; cannot blank required without explicit ack |
| diff row: proposed == current | render | `.diff-same`, no checkbox needed |
| diff row: proposed differs | render | `.diff-change`, checkbox checked |
| diff row: proposed empty | render | `.diff-clear`, red, checkbox unchecked by default |
| enrich submit | UX | spinner appears immediately; Go disabled until results |

The matrix lives in `tests/web/test_apply_candidate.py` and runs in CI.

## Out of scope

- Per-item granularity inside list fields (tag-by-tag accept) — file as follow-up if requested.
- Background async provider search with results streamed as they arrive — current sync model is fine for v1.
- Edit-form grouping and provenance polish (plan-04).
- URL/state contract for the enrich flow (plan-02 covers it via `return_to`).
