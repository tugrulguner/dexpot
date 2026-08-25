# Changelog fragments

Each unreleased user-facing change is one file in this directory.

File name:

```text
<pr-number>.<type>.md
```

Supported types: `added`, `changed`, `deprecated`, `removed`, and `fixed`.

Write one sentence about the effect for a user. Example:

```text
42.added.md -> Add typed query-parameter binding to compiled routes.
```

Do not edit `CHANGELOG.md` directly. `make changelog-draft` previews the assembled release;
`make changelog` builds it during release preparation. Internal-only work may use the
`skip-changelog` label with maintainer approval.
