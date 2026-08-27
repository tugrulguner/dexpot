## Summary

Describe the current behavior and the focused change in this pull request.

## Related issue

Use `Closes #<issue-number>` when this work has an agreed issue. Write `Not applicable` for a small change that did not need one.

<!-- Closes #123 -->

## User-visible behavior

Describe what changes for a dexpot user. Write `None` for maintenance-only work.

## Verification

- [ ] Added or updated real-user coverage when behavior changed.
- [ ] Verified behavior through the real HTTP or CLI surface when applicable.
- [ ] `make check`
- [ ] `make build`
- [ ] Completed the relevant checks in `docs/reviewing.md`.

List the commands run and their results:

```text

```

## Documentation and contracts

- [ ] Updated the README, roadmap, examples, or coding-agent guidance when their public contract changed.
- [ ] Preserved the synchronous handler and interpreter-adaptive execution contracts.
- [ ] Kept current behavior separate from planned architecture.

## Changelog

- [ ] Added `changelog.d/<issue-number>.<type>.md` for a tracked user-facing change; or
- [ ] Added a unique `changelog.d/+<identifier>.<type>.md` orphan fragment; or
- [ ] This has no user-visible effect and should receive the `skip-changelog` label.
