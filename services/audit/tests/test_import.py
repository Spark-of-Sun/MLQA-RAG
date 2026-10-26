"""Import test for audit."""

import audit
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert audit is not None
