"""Import test for lmqa_logging."""

import lmqa_logging
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_logging is not None
