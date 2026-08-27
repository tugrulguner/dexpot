## Summary and motivation

<!-- What changed, and which concrete user or maintainer problem does it solve? -->

## Related issue or direct-PR reason

<!-- Use `Closes #<issue-number>` for tracked work. If there is no issue, explain why this is a small, scoped direct PR such as a focused fix, test, documentation repair, or maintenance change. -->

## Scope and non-goals

<!-- State what this PR changes and what it deliberately leaves alone. -->

## Safety and compatibility

<!-- Address handler/route contracts, parser and response behavior, bounded admission, shutdown, platform constraints, and GIL and free-threaded execution as applicable. -->

## Verification and behavioral evidence

<!-- List exact commands and results so a reviewer can reproduce them. -->

- [ ] `make check`
- [ ] `make build`
- [ ] Relevant real socket, subprocess, saturation, or artifact checks
- [ ] Behavior exercised through the real HTTP or CLI surface when applicable

## Documentation and changelog

- [ ] Updated README, roadmap, examples, coding-agent guidance, or contributor documentation when their contract changed.
- [ ] Added `changelog.d/<issue-number>.<type>.md` for tracked user-facing work; or
- [ ] Added a unique `changelog.d/+<identifier>.<type>.md` orphan fragment for a small direct user-facing change; or
- [ ] This has no user-visible effect and should receive the maintainer-applied `skip-changelog` label.
- [ ] Did not edit `CHANGELOG.md`, package versions, or `uv.lock` manually.

## Reviewer guidance

<!-- Point reviewers to the riskiest boundary, exact files, negative cases, concurrency modes, and evidence they should reproduce. -->
