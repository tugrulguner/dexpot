# Changelog

All notable changes to dexpot will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as files in [`changelog.d/`](changelog.d/) until release
preparation assembles them here. Run `make changelog-draft` to preview the next release.

<!-- towncrier release notes start -->

## [0.1.0] - 2026-08-25

### Added

- Add the initial dexpot serving core, typed routing API, adaptive scheduler, CLI, tests, and CI. ([#1](https://github.com/tugrulguner/dexpot/pull/1))
- Add `dexpot add skills` for six coding agents, expanded framework documentation and roadmap, and release-ready repository automation. ([#3](https://github.com/tugrulguner/dexpot/pull/3))

### Changed

- Add compiled endpoint plans, duplicate-route detection, and DEXPOT_WORKERS multiprocess serving on GIL builds. ([#2](https://github.com/tugrulguner/dexpot/pull/2))
