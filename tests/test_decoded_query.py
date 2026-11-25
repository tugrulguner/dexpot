from typing import Annotated

from dexpot import Dex, Query, Request
from test_repeated_query import exchange


def test_decoded_query_pairs_preserve_order_and_raw_query():
    app = Dex()

    @app.get("/filters")
    def filters(request: Request):
        pairs = request.query_pairs()
        assert type(pairs) is tuple and all(type(pair) is tuple for pair in pairs)
        return {"raw": request.query, "pairs": pairs}

    raw = "tag=tea+time&flag&&%74ag=%2B%26%3D&empty=&caf%C3%A9=%E2%98%95"
    assert exchange(app, f"/filters?{raw}".encode("ascii")) == (
        200,
        {
            "raw": raw,
            "pairs": [
                ["tag", "tea time"],
                ["flag", ""],
                ["tag", "+&="],
                ["empty", ""],
                ["café", "☕"],
            ],
        },
    )
    assert exchange(app, b"/filters") == (200, {"raw": "", "pairs": []})


def test_decoding_is_opt_in_and_preserves_typed_scalar_behavior():
    app = Dex()

    @app.get("/raw")
    def raw(request: Request, tag: Annotated[str, Query("tag")]):
        return {"raw": request.query, "tag": tag}

    @app.get("/decoded")
    def decoded(request: Request):
        try:
            return {"pairs": request.query_pairs()}
        except ValueError as exc:
            return 422, {"detail": str(exc)}

    assert exchange(app, b"/raw?tag=ok&extra=%FF") == (
        200,
        {"raw": "tag=ok&extra=%FF", "tag": "ok"},
    )
    assert exchange(app, b"/raw?tag=ok&%74ag=ok") == (
        422,
        {"detail": "query parameter 'tag': repeated"},
    )
    for target in (b"/decoded?ok=1&x=%FF", b"/decoded?%FF=1"):
        assert exchange(app, target) == (422, {"detail": "invalid query encoding"})
    assert exchange(app, b"/decoded?=value") == (200, {"pairs": [["", "value"]]})
    assert exchange(app, b"/decoded?x=%GG")[0] == 400
