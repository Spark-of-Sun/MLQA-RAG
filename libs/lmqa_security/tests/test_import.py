"""Import test for lmqa_security."""

import lmqa_security
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_security is not None
