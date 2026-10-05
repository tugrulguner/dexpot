---
title: Build guides
description: Task-oriented paths from a typed Dexpot route to validated HTTP behavior, with common failure diagnosis.
---

Start with the [quick start](/quick-start/) for installation and the smallest successful route. These guides deepen that path without making first-run setup a reference manual. Each page is also available as Markdown for offline and agent use.

- [Build a typed JSON API](/guides/typed-api/): bind a path, validated body, request context, and response; run and test the real server.
- [Trace a request through Dexpot](/guides/request-lifecycle/): follow registration, compilation, parser selection, admission, binding, and response ownership.
- [Deploy within current boundaries](/guides/deployment/): choose a process model, configure bounded admission, operate shutdown, and place TLS/proxy responsibilities.
- [Benchmark without overclaiming](/guides/benchmarking/): match correctness, define measurement boundaries, and report reproducible evidence.

For exact parameter and HTTP behavior, see [routes and handlers](/route-contract/) and the [HTTP boundary](/http-boundary/). The [execution model](/execution-model/) documents defaults and admission behavior.
