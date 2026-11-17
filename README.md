# Skills Catalog

A shared catalog for AI-assistant skills: one developer publishes a skill folder, and another developer's assistant finds it, installs it verified and unchanged, and can go back to any earlier version. It is a four-hour build of the PRD's core loop (publish, discover, retrieve, version) and nothing else; the design is in [`docs/design.md`](docs/design.md).

## Run it

You need macOS or Linux, [`uv`](https://docs.astral.sh/uv/), and [Claude Code](https://code.claude.com/) for the assistant part. `uv` installs Python 3.12 for you if you don't have it.

1. Install `uv` (skip if `uv --version` already works):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Get the code and install the locked dependencies:

   ```bash
   git clone https://github.com/GradualSystemsEngineer/skills-catalog.git skills-catalog
   ```

   ```bash
   cd skills-catalog
   ```

   ```bash
   uv sync
   ```

3. Optional: run the tests (about 10 seconds):

   ```bash
   uv run pytest -q
   ```

4. Start the catalog service and leave it running. It listens on `127.0.0.1:8321` and creates `catalog.db` in the folder you run it from (here, the repo root):

   ```bash
   uv run catalog serve
   ```

5. In a **second terminal**, from the repo root, publish the PRD's example skill as Developer 1 (FR-01):

   ```bash
   uv run catalog publish examples/dev1/release-note-draft
   ```

   Then publish four more small skills, so discovery has something to choose between:

   ```bash
   for d in tests/skills/*; do uv run catalog publish "$d"; done
   ```

6. Still in the second terminal, become Developer 2 and start Claude Code in their project folder:

   ```bash
   cd examples/dev2 && claude
   ```

   Claude Code asks whether to trust the folder, then whether to use the `skills-catalog` MCP server from this project's `.mcp.json`. Approve both. (The server is `uv run catalog mcp`, started by Claude Code over stdio.)

## Try the four PRD examples

Type these into Claude Code in `examples/dev2`:

1. **FR-02, discover:** `is there a skill for writing release notes?`
   The assistant returns `release-note-draft` with its description.
2. **FR-03, retrieve:** `get me the release-note-draft skill`
   The skill is written to `examples/dev2/.claude/skills/release-note-draft/`, identical to `examples/dev1/release-note-draft/`.
3. **FR-04, version.** In a **third terminal**, from the repo root, edit the skill as Developer 1 and publish again:

   ```bash
   echo "6. Keep the whole note under 200 words." >> examples/dev1/release-note-draft/SKILL.md
   ```

   ```bash
   uv run catalog publish examples/dev1/release-note-draft
   ```

   Back in Claude Code:
   - `show me the history of release-note-draft`: both versions, with which files changed.
   - `get me the release-note-draft skill`: updates the installed copy to version 2.
   - `get me version 1 of release-note-draft`: puts version 1 back.

The exceptions the PRD names:

- `is there a skill for tuning kubernetes autoscaling?`: the assistant says plainly that nothing matches.
- `get me the terraform-module-lint skill`: the assistant relays "No skill named 'terraform-module-lint' in the catalog."

The same verbs work from the command line, for people and scripts: `uv run catalog discover release notes`, `uv run catalog retrieve <name> [--version N] [--force]`, `uv run catalog history <name>`. `retrieve` writes to `CATALOG_SKILLS_DIR` (default `./.claude/skills`).

`uv run catalog status [name]` is read-only: it says whether each installed skill is current, behind, locally modified, or not in the catalog.

To reset the demo, stop the service (Ctrl-C), then from the repo root:

```bash
git checkout examples/dev1 && rm -rf catalog.db examples/dev2/.claude/skills/release-note-draft
```

## How it works

```
 Developer 1                    shared                         Developer 2
 ───────────                    ──────                         ───────────
 catalog publish ──HTTP──▶  catalog service  ◀──HTTP── local MCP server ◀─stdio─ Claude Code
   (CLI)                    (FastAPI + one                (catalog mcp: three tools)
                             SQLite file)                          │
                                                                   ▼
                                                   .claude/skills/<name>/  (verified files)
```

- **Catalog service** (`server.py`, `store.py`): five JSON routes over one SQLite file. Publishing validates the skill in memory, then one transaction assigns the next version number, inserts the version and its files, and replaces the skill's row in the full-text index. Versions and files are insert-only.
- **Client** (`client.py`): the only code that touches a developer's disk. To retrieve, it downloads the whole version in one request, writes it into a hidden staging folder, checks every file's SHA-256 and size and the version digest, and only then moves it into place. It never overwrites a copy it can't give back: an installed folder that matches no published version is left alone unless you pass `--force` on the CLI.
- **Two faces on the client:** a CLI (`cli.py`) and an MCP server (`mcp_server.py`) with three tools: `discover_skills`, `retrieve_skill`, `skill_history`. The model chooses what to fetch; it never handles file contents or chooses where files go.
- **Skills** are folders in the open [Agent Skills format](https://agentskills.io/specification.md): a `SKILL.md` with `name` and `description` in YAML frontmatter, an instruction body, and any supporting files.
- **Discovery** is SQLite FTS5 with a Porter stemmer, ranking name over description over body. The assistant turns the user's request into keywords and judges the results; there are no embeddings. A paraphrase test guards recall.

Configuration is two environment variables: `CATALOG_URL` (default `http://127.0.0.1:8321`) and `CATALOG_SKILLS_DIR` (default `./.claude/skills`, relative to where the client runs; Claude Code starts the MCP server in the project folder).

### What each test layer proves

`uv run pytest -q` runs the real service over HTTP against a temporary database and skills folder: real HTTP and SQLite, with fault injection only where a filesystem failure has to be simulated. Each PRD requirement has its own file: `test_fr01_publish.py` to `test_fr04_versions.py`, `test_nfr_consistency.py`, `test_mcp_tools.py`.

- **In-memory tool tests** prove the three tools' behaviour and result shapes.
- **The subprocess test** proves `catalog mcp` launches and speaks the protocol over stdio.
- **The walk-through above** with a real assistant proves that natural-language requests reach the right tools. No automated test stands in for it.

## Decisions

The PRD's decision log ends at D3. Continued here:

| #   | Decision                                                                                                                                              | Rationale                                                                                                                                                                      |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D4  | The assistant reaches the catalog through a local MCP server that calls a shared HTTP service                                                         | Something local has to write the retrieved files. A small client that verifies what it writes is more dependable than asking the model to do it                                |
| D5  | Skills use the open Agent Skills format                                                                                                               | A retrieved skill lands where assistants already look; no format to invent or explain                                                                                          |
| D6  | Versions are integers assigned by the service                                                                                                         | The PRD says publishing creates the version. Authors choose nothing                                                                                                            |
| D7  | Every accepted publish creates a version, identical content included                                                                                  | FR-04 says so. A version records a publication                                                                                                                                 |
| D8  | Discovery is full-text search with no embeddings                                                                                                      | The assistant supplies the language understanding. Nothing to download, no API key. A paraphrase check guards recall                                                           |
| D9  | One SQLite file holds everything                                                                                                                      | Publish is one transaction, so nothing partial is stored; zero setup                                                                                                           |
| D10 | A version travels as one complete package; the client verifies every file's hash                                                                      | One request each way. Verification does not need a request per file                                                                                                            |
| D11 | Python for the timebox                                                                                                                                | See below                                                                                                                                                                      |
| D12 | Retrieve replaces a clean installed copy and refuses to overwrite local edits                                                                         | Never destroy something the catalog cannot give back                                                                                                                           |
| D13 | Symlinks inside a skill are rejected and empty folders are not kept                                                                                   | Declared limits of the package format, stated instead of half-supported. Publishing a path that is itself a symlink to a skill folder follows it, like any other path you name |
| D14 | Two file paths that differ only in letter case or Unicode form, or a file that another path needs as a folder, are rejected at publish and at install | They cannot both exist on macOS or Windows, so the installed copy would not match its digest                                                                                   |

**The language trade-off (D11).** Python for the timebox. The client is the piece that would live on every developer's machine, so it is the piece where a single self-contained binary (Rust or Go) would be worth weighing if this were distributed for real. The service and the API would not change.

### Decisions made during build

Details the design doc left open, settled while building:

- `examples/dev2/.mcp.json` sets no `CATALOG_SKILLS_DIR`. Claude Code 2.1.325 starts the stdio server with the project folder as its working directory, so the default `./.claude/skills` lands in the right place. `${CLAUDE_PROJECT_DIR}` was not set for the server, so an `env` entry built on it only ever produced the default.
- MCP tools are annotated `-> dict[str, Any]`, not `-> dict`. With `mcp` 2.3.0 a bare `dict` produced no output schema and no `structured_content`, only text, although the SDK docs say it should. The in-memory tests caught it.
- `GET /skills/{name}/versions` returns `{"name": ..., "versions": [...]}` rather than a bare list, so the response names the skill it describes. `POST /skills` also returns `published_at`.
- `GET /skills/{name}/versions/{version}` with a version that is not a whole number returns 422 `{"error": "invalid_version", "message": ...}`, a fourth error code, rather than the publish-body error.
- The skills in `tests/skills/` serve both the discovery tests and the demo catalog.
- Names: `skills-catalog` (repo and package) and `catalog` (command).

Observed with Claude Code 2.1.325: after `retrieve_skill`, the same session listed and could invoke the new skill without a restart, and a new session listed it too. The hidden `.staging-*` folder never appeared as a skill.

## What shipped and what was left out

**Shipped:** publish (CLI), discover, retrieve and history (CLI and assistant), integer versions with history and file-level changes, verified installs that protect local edits, explicit empty results and plain-language errors for every PRD exception, and a test file per PRD requirement.

**Left out on purpose:** authentication and de-duplication (excluded by the PRD), embeddings, a web UI, remote hosting, an installation record (`catalog status` compares installed copies by hash, but nothing records which version was installed; see next steps), a `publish_skill` MCP tool (the PRD only requires discover and retrieve through the assistant), and the MCP Skills extension (see next steps).

**Known limits:**

- Author is self-declared (your login name, or `--author`), so history shows attribution, not proof.
- Symlinks are rejected and empty folders are not preserved.
- Retrieve re-checks an installed copy just before replacing it, but it does not lock the folder. Another program writing into the skill folder during the instant of the swap is not protected against.
- `.DS_Store` files are ignored: never published, and never counted as a local edit to an installed skill. No other file is ignored.
- Publish accepts a folder whose name differs from the skill's `name`; retrieve always writes `<name>/`, so what a developer receives conforms to the format.
- The service listens on localhost. "Shared" is shown by two developer folders on one machine; two real machines would need the service's bind address changed as well as `CATALOG_URL`.
- Limits per version: 512 files and 16 MiB.

**Versions tested:** Claude Code 2.1.325, MCP Python SDK (`mcp`) 2.3.0, Python 3.12.16, uv 0.13.8, FastAPI 0.163.1, uvicorn 0.54.0, macOS. Exact versions of everything are in `uv.lock`. No claim is made beyond these.

**How the four hours went:** I started by reading the whole PRD myself, to understand the problem before involving any tools. I then worked through the design with Fable 5.2 until I was happy with it, and had it write up a design document, which I read in full. Before any code was written, I had Astra 6 review that design independently. From there I moved to Claude Code, where Opus 5.5 wrote an implementation plan. I checked the plan against the design, and Opus 5.5 then did the development work, which went quickly. When the build was done, I had Astra 6 review the implementation against the PRD and the design document. I passed its findings back to Claude Code to fix the gaps, then fixed a couple of small things I found myself. Finally I ran the checks described below by hand. In total it took about 3 hours of my time.

**How AI was used** (what I directed, what I verified by hand, what I changed or rejected): 
**What I directed.** I used different models for different jobs. The strongest model, Fable 5.2, handled the design, where judgment matters most. Opus 5.5 wrote the code, because by then the plan was specific enough that the work was mostly execution. Review came from Astra 6, a different model in a different harness, so the work wasn't being graded by the same system that produced it. 

**What I verified by hand.** I read the PRD and the design document in full, and checked the implementation plan against the design before any code was written. Once it was built, I checked it myself rather than relying on the tests: 
- **Fresh clone.** I cloned the repo into an empty folder, opened a new terminal with no catalog settings, and followed this README word for word. It took 5 minutes from clone to passing tests. 
- **The demo, in a real assistant session.** In `examples/dev2` I ran the PRD’s example prompts, plus two phrasings of my own that aren’t in the tests: “anything that would help me write a changelog?” and “I need to summarize what shipped this sprint. Do we have something for that?” Both found `release-note-draft`. The retrieved folder matched the original exactly (`diff -r`), with the same file permissions.
- **Failure paths.** A publish with no description was rejected with an explanation, and the history was unchanged. Asking for a skill that doesn't exist, and searching for something that matches nothing, both got clear answers. 
- **Updates and local edits.** I went from v1 to v2 and back to v1, then edited the installed copy and asked for the latest. Retrieve refused and left my edit in place, and `catalog status` reported the copy as locally modified. 
- **The code.** I read all of it, about 840 lines in `src/`, spending the most time on the publish transaction, the digest function and the install swap. 
- **The repo.** No database files, secrets or generated files are committed, `uv.lock` is checked in, and the tests pass from a clean checkout. 

**What I changed or rejected.** I didn't accept the design review wholesale. I took most of it: every publish now creates a new version, storage and transfer are simpler, the digest format is unambiguous, and the assistant gets tested in the first 20 minutes of the build. 

I overruled it on three points: 
- It wanted retrieve to refuse whenever a copy was already installed. That would have broken the PRD's own update flow, so retrieve only refuses when the installed copy has local edits. 
- It wanted the list of changed files cut from version history. I kept it, because the PRD asks that "the change is visible". 
- It wanted the line about a single binary removed. I kept it, reworded as a trade-off rather than a plan.

## What I would build next (Phase 2, the answer to Q1)

1. **Safe updates and drift visibility.** Tell a developer whether an installed skill is current, behind, or locally edited, and update only on request. This needs a small record outside the skill folder (source, installed version, digest): a hash lookup alone can't tell, because two versions can hold identical content and an edited copy matches none. `catalog status` already does the read-only hash comparison; the installation record, which would say which of several identical versions was installed, does not exist yet.
2. **Ownership.** With no authentication, anyone can publish the next version of anyone's skill. Fine for a small trusted group; the first correctness problem once sharing widens.
3. **Discovery feedback.** Log searches that return nothing, since they show which skills the team is missing, and grow the paraphrase test into a small evaluation. Add embeddings only if measured misses justify them.
4. **Native delivery through MCP.** The Skills extension ([SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension), status Final; listed as Beta on the [extensions overview](https://modelcontextprotocol.io/extensions/overview)) lets a server offer skills to an assistant directly, described by per-file SHA-256 hashes, which this catalog already stores. It could replace the explicit install step where assistants support it. It ranks last because that support is still arriving, and the assistant still caches files locally, so it reduces drift without ending it.

If the catalog stays within one small team with clear ownership habits, items 2 and 3 swap.