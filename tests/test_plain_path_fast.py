import importlib.util
import sys
from pathlib import Path

from dexpot import _http


def oracle():
    path = Path(__file__).parent / "_fixtures/http_v070.py"
    spec = importlib.util.spec_from_file_location("dexpot_http_oracle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcome(module, fn, *args):
    try:
        return ("ok", getattr(module, fn)(*args))
    except module.HTTPParseError as exc:
        return ("error", exc.status, exc.detail, exc.version)


def test_plain_path_uses_checked_byte_fast_path(monkeypatch):
    def forbidden(*args):
        raise AssertionError("legacy path traversal")

    monkeypatch.setattr(_http, "_validate_target_component", forbidden)
    monkeypatch.setattr(_http, "unquote_to_bytes", forbidden)
    assert _http._decode_path(b"/items/7") == ("/items/7", "")


def test_all_target_octets_and_escape_cases_preserve_oracle():
    old = oracle()
    targets = [b"/item/" + bytes([b]) for b in range(256)]
    targets += [
        b"",
        b"item",
        b"/caf%C3%A9",
        b"/a%00",
        b"/a%7f",
        b"/a%2F",
        b"/a%FF",
        b"/a%",
        b"/a%0",
        b"/a?x=%FF",
        b"/a?x=%00",
        b"/a#x",
        b"/a%GG#x",
        b"/a?x=?/x",
    ]
    for target in targets:
        assert outcome(_http, "_decode_path", target) == outcome(old, "_decode_path", target), (
            target
        )


def test_all_header_octets_preserve_head_validation_and_error_precedence():
    old = oracle()
    for byte in range(256):
        head = b"GET /x HTTP/1.1\r\nHost: localhost\r\nX-Test: a" + bytes([byte]) + b"z"
        assert outcome(_http, "_parse_head_python", head, _http.HttpLimits()) == outcome(
            old, "_parse_head_python", head, old.HttpLimits()
        ), byte
        host = b"GET /x HTTP/1.1\r\nHost: a" + bytes([byte]) + b"z"
        assert outcome(_http, "_parse_head_python", host, _http.HttpLimits()) == outcome(
            old, "_parse_head_python", host, old.HttpLimits()
        ), byte
