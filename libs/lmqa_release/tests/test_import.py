"""Import test for lmqa_release."""

import lmqa_release
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_release is not None
