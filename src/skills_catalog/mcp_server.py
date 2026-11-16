"""Assistant face: MCP tools over stdio. Nothing here may write to stdout."""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("skills-catalog")


@mcp.tool()
def ping() -> str:
    """Health check for the skills catalog MCP server."""
    return "pong"


def run() -> None:
    mcp.run(transport="stdio")
