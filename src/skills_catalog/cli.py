"""Human face: the `catalog` command. The only module that prints."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="catalog")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the catalog service on 127.0.0.1")
    serve.add_argument("--db", default="./catalog.db", help="SQLite file (default ./catalog.db)")
    serve.add_argument("--port", type=int, default=8321)
    sub.add_parser("mcp", help="run the assistant (MCP stdio) server")
    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        from skills_catalog.server import create_app

        uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)
    elif args.command == "mcp":
        from skills_catalog.mcp_server import run

        run()
