"""Import test for lmqa_models."""

import lmqa_models
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_models is not None
