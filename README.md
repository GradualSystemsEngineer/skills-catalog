# Skills Catalog

TODO: full README in M5.

## Decisions made during build

- `examples/dev2/.mcp.json` sets no `CATALOG_SKILLS_DIR`. Claude Code 2.1.325 launches the stdio server with the project folder (`examples/dev2`) as its working directory, so the default `./.claude/skills` resolves correctly; `${CLAUDE_PROJECT_DIR}` was not set for the server, so the plan's `env` entry only ever produced the default.
