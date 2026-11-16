"""Shared fixtures: the real catalog service over real HTTP, a temp database and a temp skills folder. No mocks."""

import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from skills_catalog.client import Config
from skills_catalog.server import create_app

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "dev1" / "release-note-draft"
FIXTURE_SKILLS = sorted((Path(__file__).parent / "skills").iterdir())
ALL_SKILLS = [EXAMPLE, *FIXTURE_SKILLS]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "catalog.db"


@pytest.fixture
def service(db_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(db_path), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "catalog service did not start"
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def cfg(service, tmp_path):
    return Config(url=service, skills_dir=str(tmp_path / "skills"))


@pytest.fixture
def make_skill(tmp_path):
    """Write a skill folder under tmp_path/src and return its path. A key set to None leaves it out."""

    def make(name="demo-skill", description="Demo skill for tests. Use when testing.", body="Do the thing.\n",
             extra_files=None, folder=None):
        root = tmp_path / "src" / (folder or name or "unnamed")
        root.mkdir(parents=True, exist_ok=True)
        front = "".join(f"{k}: {v}\n" for k, v in (("name", name), ("description", description)) if v is not None)
        (root / "SKILL.md").write_text(f"---\n{front}---\n{body}")
        for rel, data in (extra_files or {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return root

    return make


def row_counts(db_path) -> dict:
    with sqlite3.connect(db_path) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("versions", "files", "skills_fts")}


def snapshot(folder) -> dict:
    """Every file under folder: relative path -> (bytes, executable bit)."""
    folder = Path(folder)
    return {
        p.relative_to(folder).as_posix(): (p.read_bytes(), bool(p.stat().st_mode & 0o111))
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }
