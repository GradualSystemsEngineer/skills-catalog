# Skills Catalog: implementation plan

For: Claude Opus 5.5, medium effort, running in Claude Code.
Source of truth: `docs/design.md` (the "design doc"), which answers the PRD (`docs/prd.pdf`; read the text copy `docs/prd.txt`, since PDF rendering is not installed on this machine). Read both in full once before starting. This plan does not repeat it; it fixes the order of work, pins every detail the design doc leaves open, and says how to check each step.

## 0. How to work

- **Build what the design doc says and nothing more.** No extra modules, flags, config, abstractions, logging framework, or "while I'm here" features. If something seems missing, check section 3 of this plan; if it is not pinned there, pick the simplest option and note it in one line under "Decisions made during build" at the bottom of the README.
- **Budget: under 700 lines in `src/`.** Six modules, flat functions, standard library where it does the job (`argparse`, `sqlite3`, `hashlib`, `tempfile`).
- **Work milestone by milestone (section 4).** Do not start a milestone until the previous one's "done when" check has actually been run and passed. Paste the passing output into your status note; do not claim a check you did not run.
- **Commit at the end of every milestone** with a plain message (`M2: client and CLI`). The history is part of what the reviewer reads.
- **Stop and ask Aaron** only for: a failed M0 gate you cannot fix in 10 minutes, or anything that would change a decision in the design doc's D4 to D13 table. Everything else: decide, note, continue.
- **Do not write Aaron's words for him.** README sections about how the four hours were spent and how AI was used get a `TODO(aaron)` placeholder, not invented prose.
- If the clock runs short, cut in the design doc's order (section 10). Never cut the paraphrase test, the consistency test, the fresh-clone rehearsal, or the README.

## 1. Before starting (facts checked on Aaron's machine, 2026-11-16)

| Item | State | Action |
| --- | --- | --- |
| `uv` | 0.13.8 (Homebrew) | Ready |
| SQLite FTS5 | Works in Homebrew Python 3.12 (SQLite 3.54.1) | Re-check in M0 with the Python `uv` selects |
| Python | 3.12.16 (Homebrew) | Pin `requires-python = ">=3.12"`, `.python-version` = `3.12` |
| Claude Code | 2.1.325 | This is the demo assistant; name this version in the README |
| MCP Python SDK | Latest is 2.3.0 (2026-10-02) | Depend on `mcp>=2.3,<3`; commit `uv.lock` |
| PRD | `docs/prd.pdf`, text copy `docs/prd.txt` | Read the text copy once alongside the design doc. Its four Input/Output examples are listed below |
| Repo location | `~/Code/skills-catalog` (outside iCloud, on purpose) | Build here. `docs/design.md` and `docs/prd.pdf` are already in place; the folder is not yet a git repo |

The PRD's four Input/Output examples, which the M3 gate and the README walk-through use verbatim:

| PRD | Input | Expected output | How it is exercised |
| --- | --- | --- | --- |
| FR-01 | Developer 1 publishes skill "release-note-draft" (manifest + a template file) | Stored and available to others; confirmation returned | `catalog publish examples/dev1/release-note-draft` |
| FR-02 | Developer 2 asks their assistant "is there a skill for writing release notes?" | The assistant returns "release-note-draft" with its description | That exact sentence, typed to Claude Code in `examples/dev2` |
| FR-03 | Developer 2 asks their assistant "get me the release-note-draft skill" | The assistant returns the skill, intact and ready to use | That exact sentence, typed to Claude Code in `examples/dev2` |
| FR-04 | Developer 1 re-publishes "release-note-draft" with an edit | A new version is stored; the previous version is still available; history shows both | Edit the example, `catalog publish` again, then ask the assistant "show me the history of release-note-draft" and "get me version 1 of release-note-draft" |

MCP SDK v2 facts, verified against the official docs:

- Class is `MCPServer`. The docs show two import paths: `from mcp.server.mcpserver import MCPServer` (migration guide) and `from mcp.server import MCPServer` (PyPI quickstart). Use the first; confirm it imports in M0.
- Tools: `@mcp.tool()` on a type-hinted function; the docstring is the tool description.
- Stdio: `mcp.run(transport="stdio")`.
- Tool failures the model should read: `raise ToolError("message")` from `mcp.server.mcpserver.exceptions`.
- Result fields are snake_case: `is_error`, `structured_content`.
- `create_connected_server_and_client_session` was **removed** in v2. For the in-memory and subprocess test APIs, read `https://py.sdk.modelcontextprotocol.io/v2/llms-full.txt` (search "Testing" and "stdio_client") during M3 rather than guessing. Fallback for in-memory tests: `await mcp.call_tool(name, args)`, which returns a `CallToolResult`.

Claude Code facts, verified against its docs:

- `.mcp.json` at the project root; an entry with no `type` is stdio; `command`, `args`, `env`.
- `${VAR}` and `${VAR:-default}` expand in `command`, `args` and `env`.
- Interactive sessions ask the user to approve each `.mcp.json` server. The README must say so.
- The docs do **not** state the working directory a stdio server is launched in. M0 finds out.

## 2. Repository layout

Exactly the tree in design doc section 10, plus:

```
.gitignore            .venv/  __pycache__/  *.db  .DS_Store  .pytest_cache/
.python-version       3.12
docs/design.md        the design doc (already there)
docs/prd.pdf, prd.txt the PRD and a text copy (already there)
tests/conftest.py     shared fixtures (section 5)
tests/skills/         small fixture skills for the tests (section 5)
```

`pyproject.toml`: project name `skills-catalog`, package `skills_catalog` under `src/`, script `catalog = "skills_catalog.cli:main"`. Runtime deps: `mcp>=2.3,<3`, `fastapi`, `uvicorn`, `httpx`, `pyyaml`. Dev group: `pytest`, plus whatever async pytest plugin the MCP v2 docs use in their testing page (`anyio` ships with `mcp` and has a pytest plugin; prefer it over adding `pytest-asyncio`).

## 3. Pinned decisions

These settle everything the design doc leaves to the builder. Follow them as written.

### domain.py (pure, no I/O)

- `parse_manifest(data: bytes) -> (frontmatter: dict, body: str)`. Decode UTF-8; the file must start with a line that is exactly `---`, and have a later line that is exactly `---`. Accept `\n` and `\r\n` when *finding* the delimiters; never modify the stored bytes. Parse with `yaml.safe_load`; the result must be a mapping.
- `validate(files) -> list[Problem]` where `Problem = {"code", "message"}`. Collect **all** problems, do not stop at the first. Codes: `manifest_missing`, `frontmatter_invalid`, `name_missing`, `name_invalid`, `description_missing`, `description_too_long`, `body_missing`, `path_invalid`, `path_duplicate`, `too_many_files`, `too_large`. Messages follow the examples in design doc section 4 word for word where one is given.
- Name regex: `^[a-z0-9]+(-[a-z0-9]+)*$`, length 1 to 64. `name` and `description` must be strings (YAML can yield other types; treat a non-string as missing/invalid).
- Path rule: POSIX separators only; reject empty, absolute (`/` prefix), any `..` or `.` or empty segment, backslash, and any character below 0x20 or 0x7F. `validate_path(path)` is its own function because the client calls it too before writing to disk.
- Limits: 512 files, `16 * 1024 * 1024` bytes total, checked on decoded bytes.
- `version_digest(entries) -> str`: `entries` is a list of `[path, sha256_hex, executable_bool]` sorted by path; return `"sha256:" + sha256(json.dumps(entries, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()`. Service and client both call this one function.
- `diff_files(prev, curr) -> {"added", "modified", "removed"}`, each a sorted list of paths. Modified means same path with a different `sha256` or `executable`. For version 1, every file is "added".

### store.py

- One function opens a connection: `sqlite3.connect(path, isolation_level=None)` (manual transactions), `PRAGMA foreign_keys` not needed. `init(conn)` runs the three `CREATE ... IF NOT EXISTS` statements from design doc section 5 verbatim. Open one connection per request; do not share connections across threads.
- `publish(conn, name, description, body, author, files) -> (version, digest, published_at)`:
  `BEGIN IMMEDIATE` → `SELECT COALESCE(MAX(version), 0) + 1 FROM versions WHERE name = ?` → insert `versions` row → insert `files` rows → `DELETE FROM skills_fts WHERE name = ?` then `INSERT INTO skills_fts` → `COMMIT`. Any exception: `ROLLBACK` and re-raise. `BEGIN IMMEDIATE` is what makes two concurrent publishes become n and n+1.
- `published_at`: UTC, ISO 8601, seconds precision, `Z` suffix.
- `search(conn, query) -> list`: lowercase; extract tokens with `re.findall(r"\w+", query)`; drop stop words (a short hard-coded set: a, an, the, for, to, of, in, on, and, or, is, my, me, i, with, that, this, do, we, have, any, there, skill, skills); if nothing is left, use the original tokens; if there were no tokens at all, return `[]`. Build `'"tok1" OR "tok2"'` and pass it as a **bound parameter** to `MATCH`. Order by `bm25(skills_fts, 10.0, 5.0, 1.0)`, `LIMIT 10`. Join to `versions` on the latest version for description, version, author, date.
- "skill" and "skills" are stop words on purpose: every query through the assistant contains them, and they match everything.
- `list_all(conn)`: latest version of every skill, ordered by name, no cap. `count_skills(conn)`: `COUNT(DISTINCT name)`.
- `get_version(conn, name, version=None)`, `history(conn, name)` (newest first, with `changes` computed by `diff_files` against the previous version; no file bytes).

### server.py

- `create_app(db_path) -> FastAPI`. Routes are plain `def` (not `async def`), so FastAPI runs them in its thread pool and blocking SQLite is fine.
- The five routes in design doc section 6, with those status codes. Publish body: `{"author": str | null, "files": [{"path", "executable", "content_b64"}]}`. The service computes everything else.
- Error bodies exactly as in section 6. Three error codes: `invalid_skill` (422, with `problems`), `skill_not_found` (404), `version_not_found` (404, "Skill 'x' has no version 7. Latest is 3.").
- A request body that is not the expected shape, or base64 that does not decode, is also `invalid_skill` with one problem (`request_invalid`), not FastAPI's default 422 body. Simplest way: accept the body as a plain `dict` and check it by hand.
- Discover response: `{"query": "...", "matches": [{"name", "description", "version", "author", "published_at"}], "catalog_size": 14}`.
- `catalog serve` binds `127.0.0.1:8321`, database at `./catalog.db` in the directory it is run from. `--db` and `--port` flags on `serve` only. These are flags, not new environment variables.

### client.py

- `Config(url, skills_dir)` with `Config.from_env()` reading `CATALOG_URL` (default `http://127.0.0.1:8321`) and `CATALOG_SKILLS_DIR` (default `./.claude/skills`, resolved to an absolute path). Every client function takes a `Config`; none reads the environment itself. That is what lets tests run without touching env vars.
- One exception type: `CatalogError(code, message, problems=None)`. `httpx.ConnectError` and timeouts become `CatalogError("unreachable", "Cannot reach the catalog at <url>. Is \`catalog serve\` running?")`. HTTP error bodies map straight onto it.
- `read_skill_dir(path) -> files`: `os.walk` with sorted names for a stable order; a symlink (file or directory) raises `CatalogError("symlink", ...)`; executable = `bool(st_mode & 0o111)`; paths relative, joined with `/`. **One ignored name:** `.DS_Store` (`domain.IGNORED_FILES`) is skipped, so Finder metadata neither gets published nor makes an installed copy look locally edited; `validate_path` rejects it, so the service never stores one. Nothing else is ignored.
- `publish(cfg, path, author)`, `discover(cfg, query)`, `history(cfg, name)`, `fetch(cfg, name, version=None) -> package`, `install(cfg, package, force=False) -> receipt`, and `retrieve(cfg, name, version=None, force=False)` = `install(fetch(...))`. **Keep `fetch` and `install` separate**: the corrupted-download test calls `install` with a tampered package, which is how it stays mock-free.
- `install` steps, in this order:
  1. `validate_path` on every path in the package (never trust the wire for where to write).
  2. `os.makedirs(skills_dir, exist_ok=True)`; staging folder = `tempfile.mkdtemp(dir=skills_dir, prefix=".staging-")`.
  3. Write files; for each, check size and SHA-256 of the bytes written; `chmod` 0o755 if executable else 0o644; then recompute `version_digest` and compare with the package's. Any failure: `shutil.rmtree(staging)` and raise `CatalogError("verification_failed", ...)`. Wrap the whole thing in `try/except BaseException` so staging is never left behind.
  4. Classify the destination `<skills_dir>/<name>/`: absent / same digest as requested / matches another published version / matches none. "Installed digest" = `read_skill_dir` on it, hashed with `version_digest`. "Matches another published version" = that digest appears in `history(cfg, name)`.
  5. Act per the table in design doc section 7. Swap = `os.rename(dest, aside)`, `os.rename(staging, dest)`, `shutil.rmtree(aside)`; if the second rename fails, rename `aside` back. `aside` is `.old-<name>-<random>` in the skills dir.
  6. Local edits and not `force`: remove staging, raise `CatalogError("local_changes", "<location> has local changes that match no published version. It was left untouched. Publish it, move it, or run \`catalog retrieve <name> --force\`.")`. With `force`, swap as in step 5.
- Receipt: `{"name", "version", "digest", "files": <count>, "location", "status": "installed" | "updated" | "up_to_date"}`.
- Author default: `getpass.getuser()`; `catalog publish --author` overrides it.
- Nothing in `client.py` prints.

### cli.py

`argparse` with subcommands `serve`, `mcp`, `publish <dir> [--author]`, `discover [words...]`, `retrieve <name> [--version N] [--force]`, `history <name>`. Catch `CatalogError`, print the message (and each problem on its own line) to stderr, exit 1. Success output is short and human: one line for publish and retrieve, a small aligned list for discover and history.

### mcp_server.py

- Three tools only: `discover_skills(query: str)`, `retrieve_skill(name: str, version: int | None = None)`, `skill_history(name: str)`. No destination argument, no `force` argument.
- Each tool builds `Config.from_env()`, calls the client, returns the dict. `CatalogError` → `raise ToolError(message)` with problems appended one per line.
- Zero matches is a **normal return** with `matches: []` and `"message": "No skills match 'x' (searched 14 skills)."`. It is not an error.
- Nothing may write to stdout in this process. Use `print(..., file=sys.stderr)` if you must log at all.
- Docstrings (these are the prompt; keep them close to this):
  - `discover_skills`: "Search the team's shared skills catalog. Use when the user asks whether a skill exists for a task, wants to find or browse skills, or before writing a new skill. Pass a few keywords describing the need, including synonyms (for example 'release notes changelog'), not a full sentence. Returns ranked matches with descriptions. An empty result means nothing in the catalog matches; say so plainly."
  - `retrieve_skill`: "Download a skill from the shared catalog and install it into this project's skills folder, verified and unchanged. Use when the user asks to get, install, pull or use a catalog skill. Installs the latest version unless `version` is given; pass `version` to get an earlier one. Returns a receipt with the version, digest and location."
  - `skill_history`: "List every published version of a catalog skill, newest first, with date, author and which files changed. Use when the user asks what changed, who published, or which versions exist."

### examples/

- `examples/dev1/release-note-draft/`: `SKILL.md` (name, a description that mentions release notes and changelogs and when to use it, a real short instruction body) and `assets/template.md`.
- `examples/dev2/.claude/skills/.gitkeep`.
- `examples/dev2/.mcp.json`, starting point (adjust in M0 to whatever actually works, then leave it alone):

```json
{
  "mcpServers": {
    "skills-catalog": {
      "command": "uv",
      "args": ["run", "--project", "../..", "catalog", "mcp"],
      "env": { "CATALOG_SKILLS_DIR": "${CLAUDE_PROJECT_DIR:-.}/.claude/skills" }
    }
  }
}
```

## 4. Milestones

Times are the design doc's. The gate at the end of each is mandatory.

### M0 (0:00 to 0:20): scaffold and prove the assistant path

1. `git init`, `uv init`-style scaffold, `pyproject.toml`, `.gitignore`, `.python-version`, `uv sync`, commit `uv.lock`.
2. Check FTS5: `uv run python -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"`. If it fails, stop and tell Aaron; the fallback is the scored `LIKE` search in design doc section 13.
3. Check the SDK: `uv run python -c "import mcp, importlib.metadata as m; print(m.version('mcp')); from mcp.server.mcpserver import MCPServer"`. Must print 2.x.
4. `mcp_server.py` with one trivial tool (`ping() -> "pong"`) and `cli.py` with just `catalog mcp`.
5. `examples/dev2/.mcp.json` and `.gitkeep`.
6. Have the trivial tool also return `os.getcwd()` and `os.environ.get("CATALOG_SKILLS_DIR")` so the launch directory question is answered by evidence.

**Done when:** from `examples/dev2`, `claude -p "Call the ping tool and show me exactly what it returns" --allowedTools "mcp__skills-catalog__ping"` returns pong, and the reported skills dir is the absolute path of `examples/dev2/.claude/skills`. If the relative `--project ../..` does not resolve, fix `.mcp.json` now (not later) and record what the working directory turned out to be. Then remove the cwd/env echo. Commit.

### M1 (0:20 to 1:15): domain, store, server

Order: `domain.py` → `store.py` → `server.py` → `catalog serve`.

**Done when**, with `catalog serve --db /tmp-ish/test.db` running, a short throwaway shell or Python script (do not commit it) shows:
- publish the example skill twice → 201 with versions 1 and 2;
- `GET /skills/release-note-draft` returns version 2 with both files; `/versions/1` returns version 1;
- `/versions` lists 2 then 1, with `changes`;
- `GET /skills?q=release+notes` returns the skill; `?q=kubernetes` returns `matches: []` with `catalog_size: 1`;
- a publish with no `description` returns 422 with the problem list, and `/versions` still shows exactly two versions.

Commit.

### M2 (1:15 to 2:00): client and CLI

**Done when:**
- `catalog publish examples/dev1/release-note-draft` then, with `CATALOG_SKILLS_DIR=examples/dev2/.claude/skills`, `catalog retrieve release-note-draft` → `diff -r` between the two folders shows no differences;
- edit the example, publish again, retrieve again → reports updated to v2; `catalog retrieve release-note-draft --version 1` → back to v1; run it again → "already up to date";
- hand-edit the installed copy, retrieve → refused, file still has the edit; `--force` → replaced;
- stop the service, run any command → the "Cannot reach the catalog" message, exit 1;
- no `.staging-*` or `.old-*` folders remain in the skills dir after any of the above.

Restore the example skill and clean `examples/dev2/.claude/skills` back to just `.gitkeep`. Commit.

### M3 (2:00 to 2:35): the three real tools

Replace `ping` with the three tools. Publish three or four varied skills so discovery has something to rank (reuse `tests/skills/`, section 5).

**Done when**, from `examples/dev2` with the service running:
- the PRD's four examples (table in section 1) work in order: publish by CLI, then the FR-02 and FR-03 sentences verbatim, then re-publish with an edit followed by the history and version-1 prompts. Run the assistant prompts with `claude -p "<sentence>" --allowedTools "mcp__skills-catalog__*"`; Aaron re-runs them interactively in the rehearsal;
- a prompt for something not in the catalog gets a plain "nothing matches" answer, not an error and not an invented skill;
- a prompt to retrieve a skill that does not exist relays the not-found message;
- after a retrieve, the skill folder is in `examples/dev2/.claude/skills/<name>/` and a **new** `claude` session started there lists it as available. Also note whether the session that did the retrieve picks it up without a restart; whichever is true goes in the README as observed, with the version number.
- check that the short-lived `.staging-*` folder did not show up as a skill.

Commit.

### M4 (2:35 to 3:15): tests

Write the six files in design doc section 9, covering every clause in its "What it proves" column. See section 5 below for fixtures. **Done when** `uv run pytest -q` is green, twice in a row, in under about 20 seconds. Commit.

### M5 (3:15 to 4:00): README and fresh-clone rehearsal

1. README in the order given in design doc section 11, including the D4 to D13 table, the Phase 2 list (design doc section 12, condensed), known limits (section 13), and the versions actually tested (read them from `uv.lock`, `python --version`, `claude --version`; do not copy numbers from this plan).
2. The README's run section must be exact commands in order: install `uv`, `uv sync`, `uv run catalog serve` (says where `catalog.db` appears), in a second terminal `uv run catalog publish examples/dev1/release-note-draft`, then `cd examples/dev2 && claude`, approve the `skills-catalog` server when asked, then the four prompts.
3. Re-check the status of the MCP Skills extension (SEP-2640) on its spec page before citing it; say "Final" or "beta" as the page says today.
4. **Rehearsal:** `git clone` the repo into a fresh temp directory outside iCloud, follow the README literally, top to bottom, typing nothing that is not in it. Fix the README or the code for every stumble, then rehearse again from a new clone.
5. Leave `TODO(aaron)` for: time spent per phase, how AI was used (directed / verified by hand / changed or rejected), and repo/command naming if he wants to change it.

**Done when** a fresh clone passes `uv run pytest -q` and the README walk-through with no deviation. Commit.

## 5. Test fixtures and how each hard case is tested

`tests/conftest.py`:

- `service` fixture (function scope): temp db path → `create_app(db)` → run `uvicorn.Server` in a daemon thread on a free port (bind port 0 via a socket to find one) → wait until `server.started` → yield the base URL → `server.should_exit = True` and join. This is the real service over real HTTP, no mocks.
- `cfg` fixture: `Config(url=service, skills_dir=tmp_path / "skills")`.
- `make_skill(tmp_path, name, description, body, extra_files={})` helper that writes a skill folder and returns its path.

`tests/skills/`: four or five small, clearly different skills used by the discover tests and the M3 demo, for example `release-note-draft`, `sql-migration-review`, `incident-postmortem`, `api-error-messages`, `pr-description`. Each needs a description that says what it does and when to use it.

| Case | How |
| --- | --- |
| Database unchanged after a rejected publish | Count rows in `versions`, `files`, `skills_fts` via a direct `sqlite3` connection before and after |
| Five paraphrases (never cut) | Keyword-style queries the way an assistant would send them, none copied from the description, e.g. for `release-note-draft`: "changelog for a new version", "summarize what shipped", "writing release announcement". Assert the expected skill is in the results (top 3), not that it is first |
| Explicit empty result | Query with words in no skill → 200, `matches == []`, `catalog_size` correct |
| Removed terms stop matching | v1 body has a unique word, v2 does not; query the word after v2 → no match |
| Corrupted download | `pkg = fetch(...)`, alter one file's `content_b64`, `install(cfg, pkg)` → raises `verification_failed`; the skills dir has no new folders; a previously installed copy is byte-identical to before |
| Local edits refused | Install, append to a file, retrieve again → `local_changes`; the edit is still there |
| v1 → v2 → v1 with a file removed in v2 | After v2 the removed file is gone from disk; after going back to v1 it is present again |
| Identical republish | Publish the same folder twice → versions 1 and 2 with equal digests, and history shows both. With v1 installed, retrieving v2 reports `up_to_date` (the digests are equal, so the design's table says change nothing) and the receipt names version 2 |
| Malformed update | Publish valid v1, publish invalid → 422; history still has exactly v1; retrieve still returns v1 |
| Consistency (never cut) | Fixture skill with: a binary file (all 256 byte values), a CRLF text file, a file with no trailing newline, an executable script, a nested directory, a non-ASCII filename. Publish, retrieve, compare bytes and `st_mode & 0o111` for every file, and assert the set of paths is equal in both directions (nothing extra written) |
| MCP in memory | Call each of the three tools through the SDK's in-memory client (per the v2 testing docs) with `CATALOG_URL`/`CATALOG_SKILLS_DIR` set via `monkeypatch.setenv`; assert the shapes in design doc section 8, the zero-match message, and that not-found comes back with `is_error` true |
| MCP over stdio | One test: launch `catalog mcp` as a subprocess with the SDK's stdio client, list tools (expect exactly three names), call `discover_skills` |

## 6. Traps

- **stdout in the MCP process** breaks the protocol silently. No `print` anywhere under `client.py`, `domain.py` or `mcp_server.py`. Uvicorn is never started in that process.
- **FTS5 has no upsert.** Delete the skill's row, then insert, inside the publish transaction.
- **Never pass user text into the `MATCH` expression unquoted**, and never by string formatting into SQL. Tokens are `\w+` only, each wrapped in double quotes, the whole expression bound as a parameter.
- **Python's `sqlite3` default transaction handling** will fight `BEGIN IMMEDIATE`. Use `isolation_level=None`.
- **`os.rename` onto an existing non-empty directory fails** on macOS and Linux. That is why the swap moves the old folder aside first.
- **Do not round-trip the manifest.** Store and return the received bytes. The only YAML call is `safe_load` for validation and indexing.
- **Base64 inflates by a third.** A 16 MiB skill is a roughly 22 MiB request body; that is fine for uvicorn defaults, do not add a body limit below it.
- **`executable` must be a real JSON boolean** on the wire and a Python `bool` going into `version_digest`. SQLite hands back `0`/`1`; convert when reading, or the digest will differ between service and client.
- **Hidden staging folder inside a watched skills dir.** It is dot-prefixed and short-lived; M3 checks it does not surface as a skill. If it does, stage in the skills dir's parent instead (still the same filesystem) and note the change.
- **MCP v2 names.** `FastMCP`, `mcp.server.fastmcp`, `McpError` and `create_connected_server_and_client_session` are v1 and will not import. If you find yourself writing one from memory, check the installed package.

## 7. Final checklist

- [ ] `uv run pytest -q` green on a fresh clone
- [ ] README walk-through works on a fresh clone with nothing typed that is not in the README
- [ ] The PRD's four prompts work in Claude Code from `examples/dev2`
- [ ] `src/` is under 700 lines (`wc -l src/skills_catalog/*.py`)
- [ ] `uv.lock` committed; versions in the README match it
- [ ] No `catalog.db`, `.venv`, `.DS_Store`, or installed skills committed; `examples/dev2/.claude/skills/` holds only `.gitkeep`
- [ ] `grep -rn "print(" src/skills_catalog` shows hits only in `cli.py`
- [ ] Every `TODO(aaron)` is listed in the final status note
