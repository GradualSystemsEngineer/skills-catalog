"""Assistant-mediated access NFR: the three MCP tools, in memory, plus the real stdio server as a subprocess."""

import os
import sys
from pathlib import Path

import pytest
from conftest import EXAMPLE, snapshot
from mcp import Client, StdioServerParameters

from skills_catalog import client
from skills_catalog.mcp_server import mcp

pytestmark = pytest.mark.anyio


@pytest.fixture
def assistant_env(cfg, monkeypatch):
    monkeypatch.setenv("CATALOG_URL", cfg.url)
    monkeypatch.setenv("CATALOG_SKILLS_DIR", cfg.skills_dir)
    client.publish(cfg, EXAMPLE, author="dev1")
    return cfg


async def call(name, args):
    async with Client(mcp, raise_exceptions=True) as session:
        return await session.call_tool(name, args)


async def test_exactly_three_tools_are_offered():
    async with Client(mcp, raise_exceptions=True) as session:
        tools = (await session.list_tools()).tools
    assert sorted(t.name for t in tools) == ["discover_skills", "retrieve_skill", "skill_history"]
    assert all(t.description for t in tools)


async def test_discover_returns_ranked_matches(assistant_env):
    result = await call("discover_skills", {"query": "release notes changelog"})
    assert not result.is_error
    match = result.structured_content["matches"][0]
    assert match["name"] == "release-note-draft"
    assert set(match) == {"name", "description", "version", "author", "published_at"}
    assert result.structured_content["catalog_size"] == 1


async def test_discover_with_no_match_is_a_plain_empty_answer(assistant_env):
    result = await call("discover_skills", {"query": "kubernetes"})
    assert not result.is_error
    assert result.structured_content["matches"] == []
    assert result.structured_content["message"] == "No skills match 'kubernetes' (searched 1 skills)."


async def test_retrieve_installs_into_configured_folder_and_returns_receipt(assistant_env):
    result = await call("retrieve_skill", {"name": "release-note-draft"})
    assert not result.is_error
    receipt = result.structured_content
    assert receipt["status"] == "installed"
    assert receipt["version"] == 1
    assert receipt["location"] == os.path.join(assistant_env.skills_dir, "release-note-draft")
    assert snapshot(receipt["location"]) == snapshot(EXAMPLE)


async def test_retrieve_earlier_version(assistant_env):
    client.publish(assistant_env, EXAMPLE)
    result = await call("retrieve_skill", {"name": "release-note-draft", "version": 1})
    assert result.structured_content["version"] == 1


async def test_retrieve_unknown_skill_is_an_error_the_model_can_read(assistant_env):
    result = await call("retrieve_skill", {"name": "terraform-module-lint"})
    assert result.is_error
    assert "No skill named 'terraform-module-lint' in the catalog." in result.content[0].text


async def test_history_lists_versions_newest_first(assistant_env):
    client.publish(assistant_env, EXAMPLE, author="dev1")
    result = await call("skill_history", {"name": "release-note-draft"})
    versions = result.structured_content["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    assert set(versions[0]) == {"version", "digest", "author", "published_at", "changes"}


async def test_stdio_server_launches_and_speaks_the_protocol(assistant_env):
    params = StdioServerParameters(
        command=str(Path(sys.executable).parent / "catalog"),
        args=["mcp"],
        # The child gets only an allow-listed environment, so pass the catalog settings explicitly.
        env={"PATH": os.environ["PATH"], "CATALOG_URL": assistant_env.url, "CATALOG_SKILLS_DIR": assistant_env.skills_dir},
    )
    async with Client(params) as session:
        tools = (await session.list_tools()).tools
        assert sorted(t.name for t in tools) == ["discover_skills", "retrieve_skill", "skill_history"]
        result = await session.call_tool("discover_skills", {"query": "release notes"})
    assert not result.is_error
    assert result.structured_content["matches"][0]["name"] == "release-note-draft"
