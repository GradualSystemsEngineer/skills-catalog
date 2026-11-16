# Skills Catalog

TODO: full README in M5.

## Decisions made during build

- `examples/dev2/.mcp.json` sets no `CATALOG_SKILLS_DIR`. Claude Code 2.1.325 launches the stdio server with the project folder (`examples/dev2`) as its working directory, so the default `./.claude/skills` resolves correctly; `${CLAUDE_PROJECT_DIR}` was not set for the server, so the plan's `env` entry only ever produced the default.
- `GET /skills/{name}/versions` returns `{"name": ..., "versions": [...]}` rather than a bare list, so the response names the skill it describes.
- `POST /skills` also returns `published_at` alongside name, version and digest, so the CLI can confirm when.
- Observed with Claude Code 2.1.325 (`claude -p` in `examples/dev2`): after `retrieve_skill`, the same session listed and could invoke the new skill without a restart, and a new session also listed it. The short-lived `.staging-*` folder never appeared as a skill. Interactive mode to be confirmed in the rehearsal.
- The test fixtures in `tests/skills/` double as the extra catalog content for the demo, so discovery has something to rank.
