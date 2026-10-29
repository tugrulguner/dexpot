# Changelog

All notable changes to dexpot will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as files in [`changelog.d/`](changelog.d/) until release
preparation assembles them here. Run `make changelog-draft` to preview the next release.

<!-- towncrier release notes start -->

## [0.8.0] - 2026-10-28

### Added

- Add a bounded installed-wheel regression screen with exact native-response validation, GIL-mode provenance, sampled resource checks, preserved trial records and fail-closed candidate comparisons.
- Add synchronous `app.lifespan(factory)` application resources with process-local acquisition, reverse-order cleanup, partial-startup rollback and worker-restart acquisition. Outstanding handlers retain their resources after bounded drain; deferred cleanup can run on a different thread, and forced process termination can skip cleanup. Yielded values are not automatically injected into handlers. Lifecycle performance acceptance is limited to the controlled Linux screen; macOS and unrestricted performance remain unqualified. The experimental socket-I/O redesign is not included.

### Changed

- Add a supporting worker-lifecycle diagram alongside the preserved execution and response-contract illustrations, and correct website explanations of serve-time scheduler selection and connection-owner capacity lifetime.
- Checked nested Struct response contracts on GIL-enabled Python can select a registration-bound direct preparer after canonical validation. Unsupported contracts retain the canonical fallback, and FT preparation is unchanged. Historical same-host measurements showed a 4.841% median nested-throughput gain with increased registration CPU and retained metadata; this is not a universal or release-to-release speedup claim. See the retained [experiment and tradeoffs](https://github.com/tugrulguner/dexpot/blob/main/docs/gil-nested-direct-experiment.md).
- The checked-response engines now re-export the same finite-value, length, omission, generic-substitution, type-info, and record-detection helpers; response preparation and compilation strategies remain separate.
- Update the public author email for dexpot and dexpot-native to tugrul@modepot.io.

### Fixed

- Clarify that serving mode follows the active GIL state rather than the interpreter build flag, and distinguish shipped v0.7.1 scheduling changes from their bounded pre-release benchmark evidence.
- Empty and whitespace Item IDs in the browser preview are now rejected before numeric coercion.


## [0.7.1] - 2026-10-21

### Changed

- Add visible social links and public website feedback routes.
- Adds privacy-safe browser-local playground outcome events. The shared `playground_preview_started` / `playground_preview_completed` contract includes only bounded project, mode, result, failure class, and an ephemeral per-attempt correlation ID; it excludes request values and output. No library telemetry was added.
- Compile eligible flat checked-response projections on free-threaded CPython only when replacing the native whole-codec fallback; retain existing graph preparers and unsupported schemas or values unchanged.
- Compile narrow required nested Struct/list response preparation at registration on free-threaded Darwin, with worker-owned executable/guard state and captured slot getters. Keep the existing graph for unsupported schemas and values, and retain GIL/Linux selection and native encoding. Skip Mach policy RPCs for direct captures while preserving the incumbent fallback policy scope and restoration.
- Give each Darwin preparation worker its own ctypes policy-call wrappers and argument metadata, while preserving the existing policy selection, borrowed thread port and failure-safe restoration behavior.
- On free-threaded macOS, connection owners yield only after at least 1 ms of accumulated thread CPU across successfully completed keep-alive responses. Runtime diagnostics expose the selected budget. Paired with owner-lifetime scheduling policy, the rebuilt artifact passed the scoped macOS FT flat, nested and mixed HTTP gates; this does not establish a general cross-platform performance improvement.
- Reuse the immutable HTTP path-validation character table across requests instead of rebuilding it, avoiding repeated set allocation and shared-set copying on free-threaded Python without changing URI validation.
- Synchronize response-contract visuals and documentation with the v0.7.0 checked-output behavior.
- The README and homepage now show the original execution overview alongside the response-contract diagram.
- The homepage now presents the execution overview before the response-contract diagram.
- Use Dexpot cyan accents for primary actions, links, selected states, and focus indicators across light and dark themes.
- Use the existing flask cyan for the Dexpot wordmark suffix across canonical artwork, site branding, and image derivatives.

### Fixed

- Align the narrow documentation homepage hero with the content's 16px page gutters instead of applying a second horizontal inset.
- Applications now bind the scheduler at `serve()` startup using the actual GIL state after imports; late GIL changes are reported without changing the running mode.
- Correct the Dexpot wordmark suffix colour; the final artwork uses the existing flask cyan.
- Defer below-the-fold homepage diagrams and reserve their intrinsic dimensions to reduce loading competition and layout shifts.
- Keep a direct, clearly labeled Feedback action visible in compact navigation, while retaining ModePot in the menu and keeping feedback context limited to the canonical public page.
- Keep free-threaded connection capacity reserved until its owner thread has fully exited, preventing replacement threads from exceeding the process-wide limit.
- Keep personal GitHub, LinkedIn and X links beside the creator attribution with restrained text sizing instead of crowding project navigation.
- On macOS free-threaded serving, dexpot now applies fixed timeshare scheduling only for the lifetime of each connection-owning worker, restoring that worker's prior policy before exit. This is paired with the existing bounded CPU-budget response-turn handoff; it does not alter process power settings or the main/acceptor thread policy.
- Sanitize website analytics URLs and acquisition properties to exclude query strings, fragments, campaign values and ad identifiers, with intercepted real-SDK privacy regression coverage.
- The documentation homepage now exposes its feedback action, and linked README diagrams resolve to their raw image assets.


## [0.7.0] - 2026-10-10

### Added

- Add immutable `Response` and bytes-only `RawResponse` envelopes for custom headers, raw bodies, and explicit empty responses.
- Add a runnable `examples/response_policy.py` showing checked JSON, raw output, custom headers, and bodyless responses.

### Changed

- Validate and project declared `response=T` values before sending success bytes, including existing and nested Structs and factory defaults. Reject malformed or non-finite checked output with sanitized errors; keep `response=None` generic.
- Preserve registration-owned response schema metadata and default-factory identity without executing application factories during registration or serving-thread binding.
- On free-threaded macOS, retain native checked preparation for default-free flat Struct contracts without post-init callbacks, avoiding redundant untyped decoding and re-encoding.

### Fixed

- Scope free-threaded macOS scheduling changes to nested checked preparation and restore the worker's original policy before encoding or socket I/O, including validation-failure paths.


## [0.6.0] - 2026-10-05

### Added

- Browser-local contract explorer on the examples page illustrates bounded CRUD requests and computed responses without running Python or a hosted backend.
- Launch the Dexpot documentation site at https://dexpot.modepot.io.

### Changed

- Add a compact Dexpot family mark for the documentation header, favicon, and small-size brand contexts.
- Add a runnable typed endpoint and direct learning links to the Dexpot homepage.
- Add family, repository, community, and creator links to the Dexpot site header.
- Added task-oriented guides for building, tracing, deploying, and benchmarking Dexpot, with Markdown downloads generated from their canonical sources.
- Align the Dexpot homepage, documentation, and playground with the shared ModePot typography, neutral palette, header, and control styles.
- Align the README introduction and add direct links to the Dexpot website resources.
- Align the framework homepage hero spacing and family navigation sizing across product sites.
- Expose the source-generated project roadmap as a secondary action in the homepage hero.
- Improved the documentation site's search, social-preview, structured-data, and AI-agent discovery metadata.
- Instrument dexpot.modepot.io with privacy-conscious shared ModePot PostHog page analytics.
- Match the Dexpot homepage to the shared framework landing composition while preserving its interpreter-adaptive claims and alpha boundary.
- Move the alpha caution to immediately follow the homepage hero so visitors see adoption boundaries before the feature overview.
- Reject detectable asynchronous or uninspectable handlers during registration while preserving direct invokers for supported callable objects, classes, and `functools.partial` handlers, with class annotations resolved in the effective constructor namespace, including `functools.partialmethod` constructors.
- Replaced the crowded Dexpot hero and social artwork with a minimal lockup built from the existing compact mark.
- Standardized the README hero to 600px and added a visible link to the ModePot family.
- The README prominently links to the project website beside the ModePot family link.
- The browser-local CRUD playground now shows measured client-side run time and a clearer request/response layout.
- The playground now pairs typed Python route code with a bounded browser-local request/response workbench and clearly separated, reproducible loopback latency evidence measured against a local Dexpot server.
- The website now publishes generated README and roadmap pages with revision-linked snapshot provenance.

### Fixed

- Add a canonical ModePot return link across the documentation site.
- Keep long runtime and serving-model table content within narrow mobile viewports.
- Make horizontally scrollable homepage code blocks keyboard-reachable and visibly focused.


## [0.5.1] - 2026-09-22

### Changed

- Align public and contributor guidance with v0.5.0's free-threaded connection cap and current roadmap.

### Fixed

- Make `dexpot add skills` reject malformed or duplicate managed markers without modifying shared instruction files.


## [0.5.0] - 2026-09-20

### Added

- Bound free-threaded active connections per process with configurable `DEXPOT_MAX_CONNECTIONS` admission and reject excess connections with 503 before creating a thread.

### Changed

- Keep route body and response declarations local to each registration and resolve annotations per registration, preventing shared handlers from leaking schemas or stale annotation state across applications.


## [0.4.1] - 2026-09-12

### Changed

- Reject unsupported Expect headers before reading bodies and reject invalid pool or queue settings before serving.

### Fixed

- Keep parsed HEAD responses bodyless and accept exact-size request heads split across delimiter boundaries.


## [0.4.0] - 2026-09-05

### Added

- Add typed Request injection with parsed metadata, raw path parameters, raw body bytes, and the validated body object. Route decorators accept explicit `annotation_locals` for postponed factory-local aliases without borrowing caller scope.

### Changed

- Precompile endpoint invokers so supported handlers avoid per-request argument-container construction.


## [0.3.0] - 2026-09-01

### Added

- Add an automatically detected optional Rust request-head parser backend with a pure-Python fallback, differential parity tests, and standard/free-threaded wheel builds. ([#20](https://github.com/tugrulguner/dexpot/issues/20))

### Changed

- Clarify dexpot's performance strategy across GIL and free-threaded CPython, optional Rust acceleration, and coding-agent skills.
- Compile registered endpoints into one immutable application and router plan before serving traffic, and reject late route registration.
- Keep the execution diagram's shared Python-handler label inside its card, identify the optional Rust/PyO3 request-head parser explicitly, and surface that parser prominently in the README.
- Refresh the README and roadmap with the visual execution map, native parser path, and shared ModePot community links.
- Refresh the execution-diagram URL so GitHub displays the corrected generated image instead of its cached predecessor.

### Fixed

- Keep installed Dexpot application guidance focused on downstream usage and verification instead of repository maintenance.


## [0.2.0] - 2026-08-28

### Added

- Add a runnable example progression for typed routing, thread-safe CRUD, and bounded HTTP behavior, with real-server acceptance tests.

### Changed

- Dexpot now bounds and validates HTTP input, distinguishes 404 from 405, applies explicit HTTP/1.x connection semantics, and redacts unexpected handler failures. ([#14](https://github.com/tugrulguner/dexpot/issues/14))
- Make contribution paths actionable with structured issue forms, a pull request template, and issue-based or unique changelog fragments.
- Strengthen contributor onboarding with explicit intent, scope, safety, evidence, and exact-head review contracts.

### Fixed

- Ignore deleted changelog fragments when enforcing pull request release notes.


## [0.1.1] - 2026-08-26

### Added

- Add an optimized dexpot project image with a public-API-accurate handler to the README hero. ([#6](https://github.com/tugrulguner/dexpot/pull/6))

### Changed

- Reduce the README project image to match the presentation scale used across the potion projects. ([#7](https://github.com/tugrulguner/dexpot/pull/7))

### Fixed

- Make `dexpot serve module:app` load application modules from the command's working directory. ([#8](https://github.com/tugrulguner/dexpot/pull/8))


## [0.1.0] - 2026-08-25

### Added

- Add the initial dexpot serving core, typed routing API, adaptive scheduler, CLI, tests, and CI. ([#1](https://github.com/tugrulguner/dexpot/pull/1))
- Add `dexpot add skills` for six coding agents, expanded framework documentation and roadmap, and release-ready repository automation. ([#3](https://github.com/tugrulguner/dexpot/pull/3))

### Changed

- Add compiled endpoint plans, duplicate-route detection, and DEXPOT_WORKERS multiprocess serving on GIL builds. ([#2](https://github.com/tugrulguner/dexpot/pull/2))
