"""Import test for lmqa_keys."""

import lmqa_keys
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_keys is not None
