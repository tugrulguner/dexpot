"""Path/query validation tables are immutable process constants, not request work."""

import pytest

from dexpot import _http


def test_path_validation_reuses_the_same_immutable_character_table(monkeypatch):
    calls = []
    original = _http._validate_target_component

    def capture(raw, allowed):
        calls.append((raw, allowed))
        return original(raw, allowed)

    monkeypatch.setattr(_http, "_validate_target_component", capture)
    assert _http._decode_path(b"/items/7?name=a/b?c") == ("/items/7", "name=a/b?c")
    assert _http._decode_path(b"/items/%38?name=two") == ("/items/8", "name=two")
    assert len(calls) == 4
    assert isinstance(calls[0][1], frozenset)
    assert calls[0][1] is calls[2][1]
    assert calls[1][1] is calls[3][1]
    assert calls[0][1] == _http._PCHAR | frozenset(b"/")
    assert calls[1][1] == _http._PCHAR | frozenset(b"/?")


@pytest.mark.parametrize(
    "target", [b"/bad%", b"/bad%2", b"/bad%XZ", b"/x#fragment", b"/x%00", b"/x%7f", b"/x?bad\x00"]
)
def test_reused_character_table_still_rejects_invalid_targets(target):
    with pytest.raises(_http.HTTPParseError) as raised:
        _http._decode_path(target)
    assert raised.value.status == 400
