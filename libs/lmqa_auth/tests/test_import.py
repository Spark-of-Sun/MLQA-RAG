"""Import test for lmqa_auth."""

import lmqa_auth
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_auth is not None
