"""The local client: the only code that touches a developer's disk. Returns data, never prints."""

import base64
import getpass
import os
import secrets
import shutil
import stat
import tempfile
from dataclasses import dataclass

import httpx

from skills_catalog.domain import NAME_RE, sha256_hex, validate_path, version_digest


class CatalogError(Exception):
    def __init__(self, code: str, message: str, problems: list | None = None):
        super().__init__(message)
        self.code, self.message, self.problems = code, message, problems or []


@dataclass
class Config:
    url: str
    skills_dir: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            url=os.environ.get("CATALOG_URL", "http://127.0.0.1:8321"),
            skills_dir=os.path.abspath(os.environ.get("CATALOG_SKILLS_DIR", "./.claude/skills")),
        )


def _request(cfg: Config, method: str, path: str, **kwargs) -> dict:
    try:
        r = httpx.request(method, cfg.url.rstrip("/") + path, timeout=30, **kwargs)
    except (httpx.ConnectError, httpx.TimeoutException):
        raise CatalogError("unreachable", f"Cannot reach the catalog at {cfg.url}. Is `catalog serve` running?")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        if body.get("error") == "invalid_skill":
            raise CatalogError("invalid_skill", "The skill was rejected; nothing was stored.", body.get("problems"))
        raise CatalogError(body.get("error", "http_error"), body.get("message", f"Catalog returned HTTP {r.status_code}."))
    return body


def read_skill_dir(path) -> list[dict]:
    """Every file under a skill folder: relative POSIX path, executable bit, bytes. Refuses symlinks."""
    if not os.path.isdir(path):
        raise CatalogError("not_a_folder", f"{path} is not a folder.")
    files = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames.sort()
        for entry in dirnames + sorted(filenames):
            full = os.path.join(dirpath, entry)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            if os.path.islink(full):
                raise CatalogError("symlink", f"{rel} is a symbolic link. Symlinks cannot be published; replace it with the file itself.")
            if entry in filenames:
                with open(full, "rb") as fh:
                    data = fh.read()
                files.append({"path": rel, "executable": bool(os.stat(full).st_mode & 0o111), "data": data})
    return files


def publish(cfg: Config, path, author: str | None = None) -> dict:
    files = [
        {"path": f["path"], "executable": f["executable"], "content_b64": base64.b64encode(f["data"]).decode("ascii")}
        for f in read_skill_dir(path)
    ]
    return _request(cfg, "POST", "/skills", json={"author": author or getpass.getuser(), "files": files})


def discover(cfg: Config, query: str | None) -> dict:
    result = _request(cfg, "GET", "/skills", params={"q": query} if query is not None else None)
    if query is not None and not result["matches"]:
        result["message"] = f"No skills match '{query}' (searched {result['catalog_size']} skills)."
    return result


def history(cfg: Config, name: str) -> list[dict]:
    return _request(cfg, "GET", f"/skills/{name}/versions")["versions"]


def fetch(cfg: Config, name: str, version: int | None = None) -> dict:
    return _request(cfg, "GET", f"/skills/{name}" + (f"/versions/{version}" if version is not None else ""))


def _installed_digest(folder) -> str | None:
    try:
        return version_digest([[f["path"], sha256_hex(f["data"]), f["executable"]] for f in read_skill_dir(folder)])
    except (CatalogError, OSError):
        return None


def _write_verified(staging: str, package: dict) -> None:
    """Write every file into staging and check it against the package. Raises on any mismatch."""
    entries = []
    for f in package["files"]:
        target = os.path.join(staging, *f["path"].split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as out:
            out.write(base64.b64decode(f["content_b64"], validate=True))
        with open(target, "rb") as back:
            written = back.read()
        if len(written) != f["size"] or sha256_hex(written) != f["sha256"]:
            raise CatalogError("verification_failed", f"{f['path']} does not match its published checksum. Nothing was installed.")
        os.chmod(target, 0o755 if f["executable"] else 0o644)
        entries.append([f["path"], f["sha256"], bool(f["executable"])])
    if version_digest(entries) != package["digest"]:
        raise CatalogError("verification_failed", "The downloaded skill does not match its published digest. Nothing was installed.")


def install(cfg: Config, package: dict, force: bool = False) -> dict:
    """Verify a fetched package in a staging folder, then put it in place as <skills_dir>/<name>/."""
    name = package.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise CatalogError("verification_failed", "The downloaded skill has an invalid name. Nothing was installed.")
    for f in package.get("files", []):
        reason = validate_path(f.get("path"))
        if reason:
            raise CatalogError("verification_failed", f"{reason} Nothing was installed.")
    os.makedirs(cfg.skills_dir, exist_ok=True)
    dest = os.path.join(cfg.skills_dir, name)
    staging = tempfile.mkdtemp(dir=cfg.skills_dir, prefix=".staging-")
    try:
        os.chmod(staging, 0o755)
        try:
            _write_verified(staging, package)
        except (KeyError, TypeError, ValueError) as e:
            raise CatalogError("verification_failed", f"The downloaded skill is malformed ({e}). Nothing was installed.")
        if not os.path.lexists(dest):
            os.rename(staging, dest)
            status = "installed"
        else:
            installed = _installed_digest(dest)
            if installed == package["digest"]:
                status = "up_to_date"
            elif force or installed in {v["digest"] for v in history(cfg, name)}:
                aside = os.path.join(cfg.skills_dir, f".old-{name}-{secrets.token_hex(4)}")
                os.rename(dest, aside)
                try:
                    os.rename(staging, dest)
                except BaseException:
                    os.rename(aside, dest)
                    raise
                shutil.rmtree(aside) if stat.S_ISDIR(os.lstat(aside).st_mode) else os.remove(aside)
                status = "updated"
            else:
                raise CatalogError(
                    "local_changes",
                    f"{dest} has local changes that match no published version. It was left untouched. "
                    f"Publish it, move it, or run `catalog retrieve {name} --force`.",
                )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "name": name,
        "version": package["version"],
        "digest": package["digest"],
        "files": len(package["files"]),
        "location": dest,
        "status": status,
    }


def retrieve(cfg: Config, name: str, version: int | None = None, force: bool = False) -> dict:
    return install(cfg, fetch(cfg, name, version), force)
