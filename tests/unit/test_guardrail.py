# ABOUTME: Meta-test for the test-isolation guardrail that blocks tests from
# ABOUTME: opening the real ~/.bookery/library.db or writing under ~/.bookery/library/.

from pathlib import Path

import pytest

from bookery.db import open_library


def test_guardrail_blocks_real_user_db() -> None:
    '''Attempting to open the real user DB path must raise a clear RuntimeError.

    This is the meta-test for the session-scoped guardrail installed by
    ``tests/conftest.py``. If the guardrail is ever removed or weakened, this
    test will start touching the user's actual ~/.bookery/library.db -- which
    is exactly the regression we are guarding against (issue #77).
    '''
    real_db = Path.home() / '.bookery' / 'library.db'
    with pytest.raises(RuntimeError, match=r'test isolation guardrail'):
        open_library(real_db)


def test_guardrail_blocks_paths_under_real_library_dir() -> None:
    '''Paths inside ~/.bookery/library/ must also be refused.'''
    nested = Path.home() / '.bookery' / 'library' / 'subdir' / 'library.db'
    with pytest.raises(RuntimeError, match=r'test isolation guardrail'):
        open_library(nested)


def test_guardrail_allows_tmp_paths(tmp_path: Path) -> None:
    '''Tmp paths from the autouse fixture must still work normally.'''
    db_path = tmp_path / 'library.db'
    conn = open_library(db_path)
    try:
        cursor = conn.execute('SELECT 1')
        assert cursor.fetchone()[0] == 1
    finally:
        conn.close()
