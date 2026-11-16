# Skills Catalog: design document

Nov 16, 2026 · @Aaron McDaniel

## 1. Purpose and ethos

This is a four-hour build of the PRD's core loop: publish a skill, discover it through an AI assistant, retrieve it unchanged, and version it. Nothing else gets built.

The PRD says it plainly: "a smaller, coherent, working system beats a larger broken one." The reviewer will clone the repo, run it from a short README, try the PRD's four example prompts, skim the code, and then ask me to defend it. So the design is judged on three things, in this order:

1. It works end to end on someone else's machine.
2. I can explain every part in one sentence.
3. The open questions the PRD leaves to the builder are answered in writing, with reasons.

Rules that keep it honest:

- Every piece of code traces to a line in the PRD. If it does not, it is cut.
- One way to do each thing. No plugin points, no config beyond two environment variables.
- Standards over inventions: the skill format and the assistant protocol are existing open specs.
- The PRD's own words are the code's words: skill, manifest, catalog, version, publish, discover, retrieve.
- Phase 2 is written, not built.

Not being built: authentication, de-duplication (both excluded by the PRD), embeddings, a web UI, remote hosting, drift detection, and the MCP Skills extension. Sections 12 and 13 say why each is deferred.

## 2. The system on one page

The system is three pieces: a catalog service, a client library, and two thin faces on that client.

&#91;embedded content: system overview · 3 zones, 7 parts\]

The highlighted box is the only place a model appears. It chooses what to fetch; it never handles file contents or picks where files are written.

- **Catalog service.** A small HTTP service over one SQLite file. It is the single source of truth and the only shared component.
- **Client library.** Runs on each developer's machine. It reads a skill folder to publish, and fetches, verifies and writes a skill folder to retrieve.
- **Two faces.** A CLI for people and scripts, and a local MCP server (stdio) for assistants. Both call the same client functions.

Four verbs cover the four functional requirements. Publishing is a CLI command; the assistant handles the other three:

| Verb | PRD | CLI | MCP tool |
| --- | --- | --- | --- |
| Publish | FR-01, FR-04 | `catalog publish <dir>` | CLI only; optional `publish_skill` |
| Discover | FR-02 | `catalog discover "<words>"` | `discover_skills` |
| Retrieve | FR-03, FR-04 | `catalog retrieve <name> [--version N]` | `retrieve_skill` |
| History | FR-04 | `catalog history <name>` | `skill_history` |

Two more commands start processes: `catalog serve` runs the service and `catalog mcp` runs the assistant face.

## 3. Three ideas that carry it

Each idea answers a specific PRD line, and each is one sentence in the interview.

**1. The model carries intent; a local client writes the files.**

PRD line: "A retrieved skill is complete and unchanged from what was published, no silent loss or alteration."

The real question is who writes the retrieved files on the developer's machine. A remote server cannot. So either the model writes them, or local code does. Here the assistant supplies only a name, a version or search words, and a small local client downloads, verifies and writes the files. The interview version:

> The local client owns filesystem writes and verifies the downloaded skill. The shared service owns publication and version history. MCP translates the user's intent into those operations.

**2. Versions are immutable, and each guarantee has one mechanism.**

PRD lines: "nothing partial is stored", "prior versions are retained", "the change is visible", "the existing version(s) are untouched."

- Hashes check content: every file carries a SHA-256, and the client verifies it.
- One database transaction makes publish all-or-nothing.
- Insert-only tables keep every earlier version.
- A staged install protects the developer's local copy.

**3. The assistant is the semantic layer.**

PRD line: "Through an AI assistant, in natural language, a developer can find published skills that match a described need."

The model already understands the question. It turns it into search words and judges the candidates. The catalog only needs a plain full-text index and an unambiguous empty result. No embedding model, no API key, nothing for the reviewer to download. The limit is honest: the model cannot judge a skill the index never returns, which is why section 9 keeps a paraphrase check.

## 4. Skill format and validation

A skill is a folder in the open [Agent Skills format](https://agentskills.io/specification.md): a `SKILL.md` manifest plus any supporting files. This is a chosen format that satisfies the PRD's "manifest plus optional supporting files"; the PRD does not mandate it.

```
release-note-draft/
  SKILL.md              name + description in YAML frontmatter, then the instruction body
  assets/template.md    optional supporting files, any depth
```

The service validates every publish before storing anything and returns a plain explanation for each problem it finds.

| Rule | PRD source | Example explanation returned |
| --- | --- | --- |
| `SKILL.md` exists at the folder root | FR-01 | "No SKILL.md found at the top of the skill folder." |
| Frontmatter parses as YAML | FR-01, UC-04 | "SKILL.md frontmatter is not valid YAML: line 3." |
| `name` present; 1 to 64 chars; lowercase letters, digits, single hyphens | FR-01 | "name is missing. Add name: your-skill-name to the frontmatter." |
| `description` present; 1 to 1024 chars | FR-01 | "description is missing. Say what the skill does and when to use it." |
| Body has non-whitespace text after the frontmatter | FR-01 | "SKILL.md has no instruction body." |
| Paths are relative, unique, with no `..`, no control characters, no symlinks | Consistency | "scripts/../x is not allowed: paths must stay inside the skill." |
| At most 512 files and 16 MiB in total | Responsiveness | "Skill is 21 MiB; the limit is 16 MiB." |

Three notes:

- **Original bytes.** The service parses the manifest to validate and index it, and stores the bytes as received. It never re-serializes YAML or normalizes line endings.
- **One source for the name.** The catalog takes the skill's name from the manifest. The format also says the folder should carry the same name; publish does not enforce that, but retrieve always writes the folder as `<name>/`, so what a developer receives conforms.
- **The body rule is ours.** The format does not require a non-empty body. The PRD does, so the catalog checks it.

## 5. Storage model

The whole catalog is one SQLite file with two tables and one search index. Each version is stored as one complete, immutable package.

```sql
CREATE TABLE versions (
  name         TEXT NOT NULL,
  version      INTEGER NOT NULL,      -- 1, 2, 3 ... assigned by the service
  digest       TEXT NOT NULL,         -- fingerprint of this exact skill state
  description  TEXT NOT NULL,
  author       TEXT,                  -- self-declared; attribution, not authentication
  published_at TEXT NOT NULL,
  PRIMARY KEY (name, version)
);

CREATE TABLE files (
  name TEXT, version INTEGER, path TEXT,
  sha256 TEXT NOT NULL, size INTEGER NOT NULL, executable INTEGER NOT NULL,
  bytes BLOB NOT NULL,
  PRIMARY KEY (name, version, path)
);

CREATE VIRTUAL TABLE skills_fts USING fts5(name, description, body, tokenize = 'porter unicode61');
```

How it behaves:

- **Every accepted publish creates a version.** This follows FR-04 literally, including when the content matches the previous version. A version records a publication, not only a difference.
- **Insert-only.** Publishing inserts rows into `versions` and `files`. Nothing in those tables is updated or deleted, so a later publish cannot touch an earlier version.
- **Latest is derived.** The latest version is the highest committed number. There is no separate "latest" pointer to get out of step.
- **One transaction per publish.** Validation runs first, in memory. Then a single write transaction assigns the next number, inserts the version and its files, and updates the search index. The guarantee covers exactly what is inside that transaction, which is everything publish writes.
- **Concurrent publishes.** SQLite allows one writer at a time, and the primary key is the backstop. Two publishes of the same skill become n and n+1. Neither overwrites the other. Whether their changes are compatible is the authors' problem, not something the catalog can detect.
- **Version digest.** SHA-256 of a JSON array of `[path, sha256, executable]` entries sorted by path. JSON quoting makes the input unambiguous whatever characters a path contains.
- **Search index is a projection.** `skills_fts` holds one row per skill, for its latest version. Publishing replaces that row, so terms removed from a skill stop matching.

Accepted trade-off: an unchanged file is stored again in each version. At this scale that is cheaper than explaining a separate blob store.

Why SQLite: one file, real transactions, full-text search built in, and zero setup for the reviewer.

## 6. Catalog service API

Five routes, all JSON. A skill travels as one complete package in both directions.

| Route | Purpose | Success | Failure |
| --- | --- | --- | --- |
| `POST /skills` | Publish a skill or a new version | 201 with name, version, digest | 422 with the validation problems |
| `GET /skills?q=words` | Discover; no `q` lists everything | 200, ranked matches, possibly empty | none |
| `GET /skills/{name}` | The latest version, files included | 200 | 404 |
| `GET /skills/{name}/versions` | History, newest first, no file contents | 200 | 404 |
| `GET /skills/{name}/versions/{n}` | One version, files included | 200 | 404 |

Publish and retrieve use the same package shape:

```json
{
  "name": "release-note-draft",
  "version": 2,
  "digest": "sha256:9f2c...",
  "author": "aaron",
  "published_at": "2026-11-16T18:40:00Z",
  "files": [
    {"path": "SKILL.md", "sha256": "ab12...", "size": 1432, "executable": false, "content_b64": "LS0tCm5hbWU6..."},
    {"path": "assets/template.md", "sha256": "77e0...", "size": 612, "executable": false, "content_b64": "IyBSZWxlYXNl..."}
  ]
}
```

On publish the client sends only `author` and `files` (path, executable, content). The service computes names, hashes, sizes, the version number and the digest. The 16 MiB limit keeps a whole version comfortably inside one response.

A history entry is small:

```json
{"version": 2, "digest": "sha256:9f2c...", "author": "aaron", "published_at": "2026-11-16T18:40:00Z",
 "changes": {"added": [], "modified": ["SKILL.md"], "removed": []}}
```

`changes` compares a version's file list with the previous version's. It is how "the change is visible" is met, and it is a comparison of two lists, not stored data.

Errors share one shape, written so an assistant can relay them as they are:

```json
{"error": "invalid_skill", "problems": [{"code": "description_missing", "message": "description is missing. Say what the skill does and when to use it."}]}
{"error": "skill_not_found", "message": "No skill named 'release-notes' in the catalog."}
```

## 7. Client flows

The client is the only code that touches a developer's disk. Its functions return data. The CLI formats that data for people; the MCP server returns it as tool results. Nothing in the client prints, because in the MCP server standard output carries the protocol. Logs go to standard error.

**Publish (UC-01, UC-04)**

1. Walk the skill folder. Refuse symlinks. Read each file's bytes and executable bit.
2. Send everything in one `POST /skills`.
3. The service validates, commits one transaction, and returns name, version and digest.
4. If validation fails, the client returns the problems the service listed. Nothing was stored.

**Retrieve (UC-03, and "earlier version when asked" from FR-04)**

1. Fetch the version in one request: latest by default, or the number asked for.
2. Write the files into a staging folder created beside the destination, so both are on the same filesystem.
3. Check each file's SHA-256 and size, recompute the version digest, and set executable bits. Any mismatch deletes the staging folder and stops.
4. Put the staged folder in place as `<skills dir>/<name>/`, following the rule below.
5. Return name, version, digest, file count and location.

**When a copy is already installed**

The rule: never destroy something the catalog cannot give back.

| The installed folder | What retrieve does |
| --- | --- |
| Does not exist | Renames the staged folder into place |
| Has the same digest as the version asked for | Reports "already up to date" and changes nothing |
| Matches some other published version of this skill | Swaps: moves the old folder aside, renames the staged one in, then deletes the old. If the second step fails, the old folder is moved back |
| Matches no published version (local edits) | Refuses, leaves it untouched, and says why. `catalog retrieve --force` overrides from the CLI only |

This is what makes the PRD's own sequence work: publish v1, retrieve, publish v2, retrieve again, then ask for v1.

Other details:

- **Where skills land.** The destination is fixed by configuration (`CATALOG_SKILLS_DIR`, default `./.claude/skills`). The assistant cannot pass a destination path.
- **No extra files.** The client writes nothing inside the skill folder, so the retrieved folder matches Developer 1's original file for file.
- **Service address.** `CATALOG_URL`, default `http://127.0.0.1:8321`. These two variables are the only configuration.

**What "ready to use" means here**

The catalog guarantees one thing: the complete, verified files are in the configured skills folder. Whether the assistant then notices the skill is the assistant's behaviour; the README shows it working in the tested version of Claude Code. Writing into a skills folder is an installation, since it changes what the assistant can load, so the demo keeps it inside `examples/dev2`.

## 8. Assistant interface

The assistant sees three MCP tools from a local stdio server that the reviewer adds with one command. The README names the assistant and SDK versions actually tested, and makes no claim beyond them.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `discover_skills` | `query`: a few keywords, synonyms welcome | Ranked name, description, latest version, author, updated date; plus catalog size |
| `retrieve_skill` | `name`, optional `version` | A receipt: name, version, digest, files written, location |
| `skill_history` | `name` | Every version, newest first: number, date, author, digest, files changed |

Publishing is a CLI command. The PRD requires only discover and retrieve through the assistant. A fourth tool, `publish_skill`, is a ten-line addition if time remains.

The tool descriptions are the prompt. Each says when to use the tool in the developer's words, for example: "Use when the user asks whether a skill exists for a task, or before writing a new skill."

Discovery, concretely:

- The service splits the query into words, quotes each one so punctuation cannot break the search syntax, and matches any of them against name, description and body. Name and description weigh more.
- Very common words are dropped. If that leaves nothing, the original words are used.
- Matching any word favours recall. A missed skill gets reinvented, which is the PRD's core pain; a weak candidate costs the model one line of reading.
- Results are capped at 10. Listing everything is a separate case: it happens only when no query is given.

Every PRD exception is a deliberate, tested response:

| PRD exception | What the tool returns |
| --- | --- |
| UC-01: missing name, description or body | Error with each problem and how to fix it; nothing stored |
| UC-02: nothing matches | Success with zero matches: "No skills match 'x' (searched 14 skills)." |
| UC-03: skill does not exist | Error: "No skill named 'x' in the catalog." |
| UC-04: malformed update | Same as UC-01; existing versions unchanged |
| Not in the PRD: installed copy has local edits | Error explaining that the folder was left untouched and how to proceed |
| Not in the PRD: service unreachable | Error: "Cannot reach the catalog at \<url>. Is `catalog serve` running?" |

"Nothing matches" is a successful empty answer, not an error. That lets the assistant say so plainly.

## 9. Tests and traceability

Every acceptance criterion in the PRD is one named test, so the reviewer can check coverage by reading file names.

| Test file | Covers | What it proves |
| --- | --- | --- |
| `test_fr01_publish.py` | FR-01, UC-01 | Publish with a supporting file succeeds; missing name, description or body is rejected with an explanation; the database is unchanged after a rejection |
| `test_fr02_discover.py` | FR-02, UC-02 | "release notes" finds `release-note-draft` with its description; five paraphrased requests each find the expected skill; an unrelated query returns an explicit empty result; terms removed in v2 stop matching |
| `test_fr03_retrieve.py` | FR-03, UC-03 | Retrieve by name writes the skill; an unknown name returns "not found"; a corrupted download leaves no partial folder and the installed copy untouched; a locally edited copy is refused and preserved |
| `test_fr04_versions.py` | FR-04, UC-04 | Every publish creates a version, identical content included; v1 stays retrievable; history shows all; latest is the default; v1 to v2 to v1 works, with a file removed in v2; a malformed update leaves earlier versions untouched |
| `test_nfr_consistency.py` | Consistency NFR | Publish, retrieve, compare byte for byte and compare executable bits. Fixture includes a binary file, CRLF line endings, a file with no trailing newline and an executable script |
| `test_mcp_tools.py` | Assistant-mediated access NFR | The three tools return the results in section 8, called in memory; plus one test that launches the real stdio server as a subprocess and calls a tool |

What each layer proves, stated plainly in the README:

- **In-memory tool tests** prove the tools' behaviour.
- **The subprocess test** proves the server launches and speaks the protocol over stdio.
- **The scripted walk-through** with a real assistant, using the PRD's four example prompts, proves that natural-language requests reach the right tools. No automated test can stand in for it.

Tests run the real service against a temporary database and a temporary skills folder, with no mocks.

## 10. Build plan for four hours

Six small modules, each with one job. Target is under 700 lines of code before tests.

```
skills-catalog/
  README.md
  pyproject.toml                 uv project; deps: mcp (v2), fastapi, uvicorn, httpx, pyyaml, pytest
  uv.lock                        committed, so the reviewer gets the exact versions tested
  src/skills_catalog/
    domain.py                    parse manifest, validate, compute digests. Pure functions, no I/O
    store.py                     SQLite: publish transaction, lookups, search
    server.py                    the five HTTP routes
    client.py                    read folder, publish, fetch, verify, install. Returns data, never prints
    cli.py                       human face; the only module that prints
    mcp_server.py                assistant face: three tools
  tests/                         the six files in section 9
  examples/
    dev1/release-note-draft/     SKILL.md + assets/template.md  (the PRD's own example)
    dev2/.claude/skills/.gitkeep keeps the folder in git so the assistant watches it from the start
    dev2/.mcp.json               points the assistant at the catalog client
```

The assistant is tested first, not last. The access path that defines the exercise is proven before anything is built on it.

| Time | Work | Done when |
| --- | --- | --- |
| 0:00 to 0:20 | Scaffold, locked environment, a trivial MCP tool | The chosen assistant calls the trivial tool from `examples/dev2` |
| 0:20 to 1:15 | `domain.py`, `store.py`, `server.py` | `curl` can publish twice and read back both versions and the history |
| 1:15 to 2:00 | `client.py`, `cli.py` | Publish from `dev1`, retrieve into `dev2`, files match; retrieve v2 over v1 works |
| 2:00 to 2:35 | The three real tools | The PRD's four prompts work in the assistant, plus no-match and not-found |
| 2:35 to 3:15 | Acceptance and failure tests | All six test files green |
| 3:15 to 4:00 | README, fresh-clone rehearsal, fixes | A clean checkout works by following the README exactly |

If time runs short, cut in this order. None of these breaks a PRD requirement:

1. `publish_skill` as an MCP tool. It is already optional.
2. `--force` on retrieve. A locally edited copy is simply refused.
3. `catalog discover` and `catalog history` in the CLI. The assistant covers both.
4. The `changes` detail in history. Keep version, date and digest.

Never cut: the paraphrase check, the consistency test, the fresh-clone rehearsal, the README.

## 11. README commitments and decision log

The README is short and in this order: what it is in two sentences; run it, with the exact commands, Python version and where the database lives; try the four prompts; how it works; decisions; what shipped and what was left out; what I would build next.

Three things it must contain:

- **The versions tested.** Assistant, MCP SDK and Python, by number.
- **An honest record.** What shipped, what was deliberately omitted, what each test layer proves, roughly how the four hours were spent, and how AI was used: what I directed, what I verified by hand, and what I changed or rejected.
- **The language trade-off**, as written or close to it:

> Python for the timebox. The client is the piece that would live on every developer's machine, so it is the piece where a single self-contained binary (Rust or Go) would be worth weighing if this were distributed for real. The service and the API would not change.

The PRD's decision log ends at D3. The README continues it:

| # | Decision | Rationale |
| --- | --- | --- |
| D4 | The assistant reaches the catalog through a local MCP server that calls a shared HTTP service | Something local has to write the retrieved files. A small client that verifies what it writes is more dependable than asking the model to do it |
| D5 | Skills use the open Agent Skills format | A retrieved skill lands where assistants already look; no format to invent or explain |
| D6 | Versions are integers assigned by the service | The PRD says publishing creates the version. Authors choose nothing |
| D7 | Every accepted publish creates a version, identical content included | FR-04 says so. A version records a publication |
| D8 | Discovery is full-text search with no embeddings | The assistant supplies the language understanding. Nothing to download, no API key. A paraphrase check guards recall |
| D9 | One SQLite file holds everything | Publish is one transaction, so nothing partial is stored; zero setup |
| D10 | A version travels as one complete package; the client verifies every file's hash | One request each way. Verification does not need a request per file |
| D11 | Python for the timebox | See the trade-off above |
| D12 | Retrieve replaces a clean installed copy and refuses to overwrite local edits | Never destroy something the catalog cannot give back |
| D13 | Symlinks are rejected and empty folders are not kept | Declared limits of the package format, stated instead of half-supported |

## 12. Phase 2: the answer to Q1

Phase 1 makes copies safe. The PRD's problem statement is about copies drifting, so the next step is making an installed copy aware of where it stands. This section is written into the README and not built.

1. **Safe updates and drift visibility.** Tell the developer whether an installed skill is current, behind, or locally edited, and update it only on request. This needs a small record kept outside the skill folder: source, installed version and digest. A hash lookup alone is not enough, because two versions can hold identical content and a locally edited copy matches none.
2. **Ownership.** With no authentication, anyone can publish the next version of anyone's skill. That is acceptable for a small trusted group and is the first correctness problem once sharing widens. The PRD defers it; that is a reason to leave it out of the build, not to rank it low.
3. **Discovery feedback.** Log searches that return nothing, since they show which skills the team is missing, and grow the paraphrase check into a small evaluation. Add embeddings only if measured misses justify them.
4. **Native delivery through MCP.** MCP now has a Skills extension ([SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension)); the proposal reached Final in September 2026, after this PRD's decision log was written. It lets a server offer skills to an assistant directly, described by per-file SHA-256 hashes. This catalog's stored data maps onto that description, though the wire format differs. It could replace the explicit install step where the assistant supports it. It ranks last because that support is still arriving, and because the assistant still caches files locally, so it reduces drift without ending it.

If the catalog stays within one small team with clear ownership habits, items 2 and 3 swap.

## 13. Loose ends

None of these changes the design. Each is a decision or a check that should not be discovered at hour three.

Decide before starting:

- [ ] **Names.** Repo, package and command. Working names here are `skills-catalog` and `catalog`. Avoid "skillcat": a public registry already uses a near-identical name.
- [ ] **Ground rules from the company.** AI assistance is expected throughout; the company confirmed it. Still open: how to submit, and whether the four hours are honour-system.
- [ ] **Which assistant to demo with.** Pick one, test with it, and name its version in the README.

Verify in the first twenty minutes:

- [ ] **The assistant can call a trivial tool** from `examples/dev2`, launched the way the README will describe. This flushes out working-directory, packaging and approval surprises early.
- [ ] **Full-text search is available.** Run `CREATE VIRTUAL TABLE t USING fts5(x)` in the Python that uv installs. If FTS5 is missing, fall back to a simple scored `LIKE` search behind the same function.
- [ ] **MCP SDK is version 2, locked.** Version 2 renamed the server class from `FastMCP` to `MCPServer` and removed the old import path. Commit `uv.lock`.

Verify when wiring the assistant:

- [ ] **The skills folder exists before the session starts.** Claude Code picks up a new skill inside a folder it is already watching. The `.gitkeep` makes sure the folder is there after a clone.
- [ ] **Project-scoped server approval.** In an interactive session the assistant asks the reviewer to approve the server from `.mcp.json`. Say so in the README.
- [ ] **Nothing prints to standard output** in the MCP server process.

Known limits, to state and not fix:

- [ ] Author is self-declared, so history shows attribution, not proof.
- [ ] Symlinks are rejected and empty folders are not preserved.
- [ ] Publish accepts a folder whose name differs from the skill's name; the format says they should match.
- [ ] The service listens on localhost. "Shared" is shown by two developer folders on one machine. Two real machines would need the service's bind address changed as well as `CATALOG_URL`.
- [ ] The Skills extension's status should be re-checked before the README cites it: the proposal is Final, and its specification page may still be labelled beta.
