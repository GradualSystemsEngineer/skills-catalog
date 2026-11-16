"""Human face: the `catalog` command. The only module that prints."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="catalog")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mcp", help="run the assistant (MCP stdio) server")
    args = parser.parse_args()
    if args.command == "mcp":
        from skills_catalog.mcp_server import run

        run()
