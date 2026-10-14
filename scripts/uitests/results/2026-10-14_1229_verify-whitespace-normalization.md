# DoD results: #320 write-verification normalization

1. Date: 2026-10-14
2. Issue: #320
3. Branch: fix/320-verify-whitespace-normalization
4. Commit: dbb035e
5. Domain: python (acceptance channel is the named pytest tests; no UI)
6. Status: PASS. (Earlier run: FAIL on the #321 test. Joe chose to delete that test and verify Kobo sync manually.)

## Unit suite

7. Default terminal width: 2773 passed, 1 failed. The failure is
   tests/e2e/test_sync_cli_push.py::test_series_push_failure_is_listed_per_book.
   It fails identically with this branch's changes stashed. Rich wraps a long path, which
   breaks a substring assertion. Filed as #321.
8. COLUMNS=300: 2774 passed, 0 failed.
8a. After deleting that test at Joe's direction (Kobo device sync is tested manually): 2773 passed, 0 failed at default width.
9. One DeprecationWarning (imghdr, from the third-party mobi package) appears on every run,
   before and after this change.

## Criteria

10. AC1 [test: test_ac1_double_space_description_is_kept]: PASS. Read-back description "a - b".
11. AC2 [test: test_ac2_html_description_is_written_as_plain_text]: PASS. Read-back "Fish & chips".
12. AC3 [test: test_ac3_padded_title_publisher_language_verify]: PASS. Read-back "Breath", "Riverhead", "en".
13. AC4 [test: test_ac4_real_description_mismatch_still_fails]: PASS. success=False, "description" in the error.
14. AC5 [test: test_ac5_add_keeps_enriched_copy]: PASS. Exit 0, no "Write failed", one enriched Breath EPUB with "performance - rejuvenate".
15. Reconciliation: 5 criteria in the issue, 5 observed, 5 passing.

## Definition of Done items from the issue

16. Acceptance test: 5/5 pass.
17. Mutation check: with the normalize_for_write call replaced by `pass`, AC1, AC2, AC3, AC5 fail
    ("Verification failed for: description" / "title, language, publisher"). AC4 passes. Restored afterwards.
18. Regression sweep (test_safe_write, test_match_pipeline, test_epub_round_trip, test_match_cli): 53 passed.
19. Committee tier (effort/S: /code-review low + acceptance-criteria lens): deferred to /submit.
20. Identifier contract: N/A, CLI only.

## Lower-level tests added

21. tests/unit/test_epub_writer.py::TestNormalizeForWrite: None handling, empty-after-strip becomes None,
    no mutation of the input. These are edge cases the acceptance test does not reach.
