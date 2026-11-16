"""Assistant face: three MCP tools over stdio. Nothing here may write to stdout."""

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from skills_catalog import client
from skills_catalog.client import CatalogError, Config

mcp = MCPServer("skills-catalog")


def _call(fn, *args):
    try:
        return fn(Config.from_env(), *args)
    except CatalogError as e:
        raise ToolError("\n".join([e.message] + [p["message"] for p in e.problems]))


@mcp.tool()
def discover_skills(query: str) -> dict[str, Any]:
    """Search the team's shared skills catalog. Use when the user asks whether a skill exists for a task, wants to find or browse skills, or before writing a new skill. Pass a few keywords describing the need, including synonyms (for example 'release notes changelog'), not a full sentence. Returns ranked matches with descriptions. An empty result means nothing in the catalog matches; say so plainly."""
    return _call(client.discover, query)


@mcp.tool()
def retrieve_skill(name: str, version: int | None = None) -> dict[str, Any]:
    """Download a skill from the shared catalog and install it into this project's skills folder, verified and unchanged. Use when the user asks to get, install, pull or use a catalog skill. Installs the latest version unless `version` is given; pass `version` to get an earlier one. Returns a receipt with the version, digest and location. Safe to call without backing anything up: it replaces an installed copy only when that copy exactly matches a published version, so nothing is lost; a copy with local edits is left untouched and the tool returns an error saying so. Receipt status: 'installed' (new), 'updated' (replaced an unmodified published version), 'up_to_date' (already identical, nothing changed)."""
    return _call(client.retrieve, name, version)


@mcp.tool()
def skill_history(name: str) -> dict[str, Any]:
    """List every published version of a catalog skill, newest first, with date, author and which files changed. Use when the user asks what changed, who published, or which versions exist."""
    return {"name": name, "versions": _call(client.history, name)}


def run() -> None:
    mcp.run(transport="stdio")
