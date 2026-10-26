"""Import test for lmqa_objectstore."""

import lmqa_objectstore
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_objectstore is not None
