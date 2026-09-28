---
title: HTTP boundary
description: Dexpot request limits, HTTP framing rules, request-head parser selection, and fail-closed protocol behavior.
---

import { Aside } from '@astrojs/starlight/components';

Dexpot owns a small HTTP/1.0 and HTTP/1.1 core. It applies bounded accumulation, deadlines, framing checks, routing, and overload shedding before application code runs.

## Default limits

Every connection starts with conservative defaults:

| Limit | Default |
|---|---:|
| Request line | 8 KiB |
| Request head | 64 KiB |
| Header count | 100 |
| Request body | 16 MiB |
| Idle read timeout | 5 seconds |
| Absolute head deadline | 10 seconds |
| Absolute body deadline | 30 seconds |

Override them as one immutable policy:

```python
from dexpot import Dex, HttpLimits

app = Dex(
    limits=HttpLimits(
        request_line_bytes=4 * 1024,
        header_bytes=32 * 1024,
        header_count=64,
        body_bytes=2 * 1024 * 1024,
        idle_read_seconds=10.0,
        head_read_seconds=15.0,
        body_read_seconds=60.0,
    )
)
```

Values must be positive, and the total request-head allowance must exceed the request-line allowance. Oversized or timed-out requests receive a stable error and the connection closes.

## Request framing

Dexpot accepts validated `Content-Length` framing. Transfer encodings, including chunked request bodies, are rejected and the connection closes. Request targets must currently use origin form such as `/path?query`.

HEAD responses never include body bytes after parsing, including parser and handler errors. Automatic GET-to-HEAD routing is not provided. Requests with `Expect` are rejected with 417 and connection close before their body is read.

## Request-head parser

The pure-Python parser is the behavioral reference and fallback. The experimental `dexpot-native` extension implements the same request-line, header, Host, framing, and keep-alive semantics in Rust through PyO3.

```bash
DEXPOT_HTTP_PARSER=python dexpot serve main:app  # force Python
DEXPOT_HTTP_PARSER=native dexpot serve main:app  # require dexpot-native
DEXPOT_HTTP_PARSER=auto dexpot serve main:app    # compatible native or Python
```

The default `auto` mode falls back only when the native module is absent. ABI and initialization failures remain visible. `native` fails clearly when the extension is unavailable.

<Aside type="note" title="Parser only">
Python still owns sockets, deadlines, request bodies, pipelining, target decoding, routing, handlers, scheduling, and worker supervision. The Rust extension is not a second server implementation.
</Aside>
