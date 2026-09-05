# Changelog

All notable changes to dexpot will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as files in [`changelog.d/`](changelog.d/) until release
preparation assembles them here. Run `make changelog-draft` to preview the next release.

<!-- towncrier release notes start -->

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
