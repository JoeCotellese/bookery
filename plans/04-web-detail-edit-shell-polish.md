# [plan-04] Web Detail/Edit Shell Polish — IA refresh for detail and edit chrome

## Defect

Detail and edit views grew as flat field lists. Detail renders every field including empties (`—` noise); the toolbar puts destructive `Delete` adjacent to `Edit` and `Enrich`; the right-side provenance panel breaks on long paths (~3 chars per line); edit is one undifferentiated stack of inputs with free-text language and semicolon-jammed authors that drift between `en`/`eng`/`en-US`. The shell never had an information-architecture pass.

## Children

- #140 — hide empty metadata fields on detail (offer to fill on edit)
- #141 — detail toolbar grouping: separate destructive from primary
- #135 — provenance panel breaks on long paths in edit view
- #134 — edit form grouping (fieldsets, language select, author chips)

## Fix sequence

1. **Detail field filter.** Hide rows with empty values on detail. Edit form still shows all fields. Optional small `+ Add description` affordance per empty optional field.
2. **Toolbar split.** `[Edit] [Enrich]` left, `[Delete]` right with visual gap. Delete still requires confirm (per #113). Optional overflow menu for tertiary actions.
3. **Provenance panel responsive.** `min-width: 320px` (or `flex-basis`), `word-break: break-all` on path values, and at < 900px viewport stack below the form full-width instead of side-by-side.
4. **Edit form grouping.**
   - `<fieldset>` + `<legend>` for Identity / Publication / Classification — order mirrors detail.
   - Authors: textarea, one-per-line, hint copy; split on submit, stored uniformly.
   - Language: `<select>` populated from ISO 639 codes already present in catalog (with free-text fallback) — kills the en/eng/en-US drift on save.
   - Description: `rows=10`, autosize.

## Test matrix

| Axis A (field state) | Axis B (viewport) | Required behavior |
|---|---|---|
| publisher empty | 1280px | Publisher row absent on detail; present on edit |
| every field populated | 1280px | All rows render; no `—` placeholders anywhere |
| toolbar | 1280px | Delete visually separated; Delete confirm intact |
| long source path | 1280px | wraps inside panel; whole path readable |
| long source path | 768px | provenance stacks below form, full-width |
| edit submit | any | language saved as normalized ISO code |
| edit submit | any | multi-author textarea round-trips as ordered list |

The matrix lives in `tests/web/test_detail_edit_shell.py` and runs in CI.

## Out of scope

- Cover thumbnails in detail header (plan-01).
- Apply-candidate diff polish (plan-03).
- Persistent book context subhead (plan-02).
- New global heading hierarchy pass (plan-01 owns it).
