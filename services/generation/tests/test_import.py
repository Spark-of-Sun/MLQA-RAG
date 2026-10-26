"""Import test for generation."""

import generation
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert generation is not None
