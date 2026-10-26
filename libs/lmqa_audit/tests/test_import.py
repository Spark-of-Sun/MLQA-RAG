"""Import test for lmqa_audit."""

import lmqa_audit
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_audit is not None
