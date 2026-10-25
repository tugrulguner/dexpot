"""Shared response-semantic primitives stay identical across preparation engines."""

import math
from typing import Annotated

import msgspec
import pytest

from dexpot import _response, _response_legacy
from dexpot._response_semantics import (
    check_length,
    is_record,
    omitted,
    reject_nonfinite,
    substitute,
    type_info,
)


@pytest.mark.parametrize(
    "helper", [reject_nonfinite, check_length, omitted, substitute, type_info, is_record]
)
def test_both_engines_reexport_the_shared_semantic_helper(helper):
    assert getattr(_response, helper.__name__) is helper
    assert getattr(_response_legacy, helper.__name__) is helper


def test_shared_primitives_preserve_edge_semantics():
    with pytest.raises(ValueError, match="non-finite"):
        reject_nonfinite({"nested": [math.inf]})

    info = type_info(Annotated[list[int], msgspec.Meta(min_length=2, max_length=3)])
    with pytest.raises(ValueError, match="too short"):
        check_length([1], info)
    with pytest.raises(ValueError, match="too long"):
        check_length([1, 2, 3, 4], info)

    assert omitted([], msgspec.NODEFAULT, list, True)
    assert omitted([], msgspec.NODEFAULT, list, True, wire=True) is not False
    assert not omitted([], msgspec.NODEFAULT, list, False)

    assert substitute(int, {}) is int
    assert is_record(type("Record", (), {"__attrs_attrs__": ()})())
    assert not is_record(int)
