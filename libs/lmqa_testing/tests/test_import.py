"""Import test for lmqa_testing."""

import lmqa_testing
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_testing is not None
