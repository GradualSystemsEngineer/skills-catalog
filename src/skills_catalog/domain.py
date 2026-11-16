"""Skill rules: parse the manifest, validate a skill, compute digests. Pure functions, no I/O.

A skill's files are a list of dicts: {"path": str, "executable": bool, "data": bytes}.
"""

import hashlib
import json
import re

import yaml

MANIFEST = "SKILL.md"
MAX_FILES = 512
MAX_BYTES = 16 * 1024 * 1024
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


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
    elif not isinstance(name, str) or len(name) > 64 or not NAME_RE.match(name):
        problems.append(_problem(
            "name_invalid",
            f"name {name!r} is not valid: use 1 to 64 lowercase letters, digits and single hyphens.",
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
