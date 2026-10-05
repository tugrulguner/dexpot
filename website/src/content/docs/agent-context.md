---
title: Coding-agent context
description: Install Dexpot's project-local framework guidance for Claude Code, Cursor, Windsurf, Copilot, Cline, or Codex.
---

Dexpot ships project-local guidance so coding agents can work from the framework's current contract instead of guessing from familiar API frameworks.

## Install guidance

Auto-detect agents already configured in the current project:

```bash
dexpot add skills
```

Or target an agent explicitly:

```bash
dexpot add skills --agent claude
dexpot add skills --agent cursor
dexpot add skills --agent windsurf
dexpot add skills --agent copilot
dexpot add skills --agent cline
dexpot add skills --agent codex
```

Install into another project:

```bash
dexpot add skills --path ./my-api
```

## What the guidance covers

The installed content describes:

- the shipped route and handler contract;
- msgspec request bodies and responses;
- standard-GIL and free-threaded execution modes;
- overload and HTTP safety boundaries;
- the optional parser-only native extension;
- current non-features; and
- the verification commands expected for Dexpot applications.

Shared Copilot and Codex instruction files use a bounded managed block so existing project guidance is preserved.

The canonical guidance source is maintained with Dexpot at [`src/dexpot/templates/skills/dexpot.md`](https://github.com/tugrulguner/dexpot/blob/main/src/dexpot/templates/skills/dexpot.md).
