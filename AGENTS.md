# Dexpot maintainer guidance

This entry point is for agents maintaining Dexpot itself. It is not the downstream guidance
installed by `dexpot add skills`; application guidance lives in
`src/dexpot/templates/skills/dexpot.md`.

Read and follow these authoritative project rules before changing the repository:

- [`CONTRIBUTING.md`](CONTRIBUTING.md) defines work classification, architecture contracts,
  test expectations, changelog policy, and the pull-request workflow.
- [`docs/reviewing.md`](docs/reviewing.md) defines the review and artifact-verification gates.

Use strict test-driven development for behavior and guidance changes: add a focused test,
observe the expected failure, make the smallest change, then rerun it. Run `make format` when
needed and `make check` before committing. For public API or documentation changes, also run
`make build` and the applicable checks in `docs/reviewing.md`.

Keep maintainer-only requirements here or in the authoritative contributor documents, never in
the installed application skill. Repository changes must preserve packaged skill inclusion;
contract changes must keep README, roadmap, contributor guidance, and the skill synchronized.
