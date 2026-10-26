"""Import test for lmqa_db."""

import lmqa_db
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_db is not None
