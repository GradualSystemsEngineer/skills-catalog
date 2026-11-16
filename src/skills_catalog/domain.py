"""Skill rules: parse the manifest, validate a skill, compute digests. Pure functions, no I/O.

A skill's files are a list of dicts: {"path": str, "executable": bool, "data": bytes}.
"""

import hashlib
import json
import re
import unicodedata

import yaml

MANIFEST = "SKILL.md"
MAX_FILES = 512
MAX_BYTES = 16 * 1024 * 1024
MAX_NAME = 64
NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def valid_name(name) -> bool:
    """1 to 64 lowercase letters, digits and single hyphens. The whole string must match: no trailing newline."""
    return isinstance(name, str) and len(name) <= MAX_NAME and NAME_RE.fullmatch(name) is not None


class ManifestError(ValueError):
    pass


def parse_manifest(data: bytes) -> tuple[dict, str]:
    """Split SKILL.md into (frontmatter mapping, body). Raises ManifestError."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ManifestError("SKILL.md is not valid UTF-8.")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ManifestError("SKILL.md must start with a line that is exactly ---, followed by YAML frontmatter.")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        raise ManifestError("SKILL.md frontmatter is not closed: add a line that is exactly --- after it.")
    try:
        front = yaml.safe_load("".join(lines[1:end]))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f": line {mark.line + 2}" if mark else ""
        raise ManifestError(f"SKILL.md frontmatter is not valid YAML{where}.")
    except RecursionError:
        raise ManifestError("SKILL.md frontmatter is nested too deeply.")
    except ValueError as e:  # PyYAML raises plain ValueError for values like an impossible date (2026-99-99)
        raise ManifestError(f"SKILL.md frontmatter has a value that cannot be read ({e}). Quote it to make it text.")
    if front is None:
        front = {}
    if not isinstance(front, dict):
        raise ManifestError("SKILL.md frontmatter must be a set of key: value pairs.")
    return front, "".join(lines[end + 1:])


IGNORED_FILES = frozenset({".DS_Store"})  # Finder metadata: never read from a skill folder, never accepted in one


def validate_path(path) -> str | None:
    """Return why a file path is not allowed, or None if it is fine."""
    bad = f"{path!r} is not allowed: paths must stay inside the skill."
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return f"{path!r} is not allowed: paths must be relative and use / separators."
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        return f"{path!r} is not allowed: paths must not contain control characters."
    if any(seg in ("", ".", "..") for seg in path.split("/")):
        return bad
    if path.split("/")[-1] in IGNORED_FILES:
        return f"{path!r} is not allowed: it is Finder metadata, not part of a skill."
    return None


def _fold(path: str) -> str:
    """The form a case-insensitive, Unicode-normalizing filesystem (macOS, Windows) compares names in."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", path).casefold())


def path_conflicts(paths: list[str]) -> list[str]:
    """Why these (individually valid) paths cannot all exist on disk at once, or [] if they can.

    Two paths that differ only in letter case or Unicode form would be one file on macOS. A path that is
    a file cannot also be a folder holding another path. Exact duplicates are reported elsewhere.
    """
    problems = []
    by_fold = {}
    for p in paths:
        other = by_fold.setdefault(_fold(p), p)
        if other != p:
            problems.append(f"{p} and {other} differ only in letter case or Unicode form, so they would be the same file.")
    for p in paths:
        parts = _fold(p).split("/")
        for i in range(1, len(parts)):
            ancestor = by_fold.get("/".join(parts[:i]))
            if ancestor is not None:
                problems.append(f"{ancestor} is a file, but {p} needs it to be a folder.")
                break
    return problems


def _problem(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def validate(files: list[dict]) -> list[dict]:
    """Check a whole skill. Returns every problem found, empty if the skill is valid."""
    problems = []
    seen = set()
    for f in files:
        reason = validate_path(f["path"])
        if reason:
            problems.append(_problem("path_invalid", reason))
        elif f["path"] in seen:
            problems.append(_problem("path_duplicate", f"{f['path']} appears more than once."))
        seen.add(f["path"])
    valid_paths = [p for p in seen if validate_path(p) is None]
    problems += [_problem("path_conflict", m) for m in path_conflicts(sorted(valid_paths))]
    if len(files) > MAX_FILES:
        problems.append(_problem("too_many_files", f"Skill has {len(files)} files; the limit is {MAX_FILES}."))
    total = sum(len(f["data"]) for f in files)
    if total > MAX_BYTES:
        problems.append(_problem("too_large", f"Skill is {total / 2**20:.1f} MiB; the limit is 16 MiB."))

    manifest = next((f for f in files if f["path"] == MANIFEST), None)
    if manifest is None:
        problems.append(_problem("manifest_missing", "No SKILL.md found at the top of the skill folder."))
        return problems
    try:
        front, body = parse_manifest(manifest["data"])
    except ManifestError as e:
        problems.append(_problem("frontmatter_invalid", str(e)))
        return problems

    name = front.get("name")
    if name is None or name == "":
        problems.append(_problem("name_missing", "name is missing. Add name: your-skill-name to the frontmatter."))
    elif not valid_name(name):
        problems.append(_problem(
            "name_invalid",
            f"name {name!r} is not valid: use 1 to {MAX_NAME} lowercase letters, digits and single hyphens.",
        ))
    desc = front.get("description")
    if not isinstance(desc, str) or not desc.strip():
        problems.append(_problem("description_missing", "description is missing. Say what the skill does and when to use it."))
    elif len(desc) > 1024:
        problems.append(_problem("description_too_long", f"description is {len(desc)} characters; the limit is 1024."))
    if not body.strip():
        problems.append(_problem("body_missing", "SKILL.md has no instruction body."))
    return problems


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_digest(entries: list) -> str:
    """Fingerprint of a skill state. entries: [path, sha256_hex, executable_bool], any order."""
    canon = sorted([[p, h, bool(x)] for p, h, x in entries])
    blob = json.dumps(canon, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def diff_files(prev: list, curr: list) -> dict:
    """Compare two [path, sha256, executable] lists. prev is [] for version 1."""
    before = {p: (h, bool(x)) for p, h, x in prev}
    after = {p: (h, bool(x)) for p, h, x in curr}
    return {
        "added": sorted(p for p in after if p not in before),
        "modified": sorted(p for p in after if p in before and after[p] != before[p]),
        "removed": sorted(p for p in before if p not in after),
    }
