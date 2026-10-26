"""Import test for ops."""

import ops
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert ops is not None
