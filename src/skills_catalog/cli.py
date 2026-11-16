"""Human face: the `catalog` command. The only module that prints."""

import argparse
import sys

from skills_catalog import client
from skills_catalog.client import CatalogError, Config


def _changes(c: dict) -> str:
    return " ".join([f"+{p}" for p in c["added"]] + [f"~{p}" for p in c["modified"]] + [f"-{p}" for p in c["removed"]])


def _run(args, cfg: Config) -> None:
    if args.command == "publish":
        r = client.publish(cfg, args.dir, args.author)
        print(f"Published {r['name']} version {r['version']} ({r['digest']}).")
    elif args.command == "discover":
        r = client.discover(cfg, " ".join(args.words) or None)
        if r.get("message"):
            print(r["message"])
        width = max((len(m["name"]) for m in r["matches"]), default=0)
        for m in r["matches"]:
            print(f"{m['name']:<{width}}  v{m['version']:<3} {m['description']}")
    elif args.command == "retrieve":
        r = client.retrieve(cfg, args.name, args.version, args.force)
        what = {"installed": "Installed", "updated": "Updated to"}.get(r["status"])
        if what:
            print(f"{what} {r['name']} version {r['version']} at {r['location']} ({r['files']} files).")
        else:
            print(f"{r['name']} version {r['version']} is already up to date at {r['location']}.")
    elif args.command == "history":
        for v in client.history(cfg, args.name):
            print(f"v{v['version']:<3} {v['published_at']}  {v['author'] or '-':<12} {v['digest'][:19]}  {_changes(v['changes'])}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="catalog", description="Publish, discover, retrieve and version skills.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the catalog service on 127.0.0.1")
    serve.add_argument("--db", default="./catalog.db", help="SQLite file (default ./catalog.db)")
    serve.add_argument("--port", type=int, default=8321)
    sub.add_parser("mcp", help="run the assistant (MCP stdio) server")
    p = sub.add_parser("publish", help="publish a skill folder as a new version")
    p.add_argument("dir")
    p.add_argument("--author", help="defaults to your login name")
    p = sub.add_parser("discover", help="search the catalog; no words lists every skill")
    p.add_argument("words", nargs="*")
    p = sub.add_parser("retrieve", help="install a skill into CATALOG_SKILLS_DIR")
    p.add_argument("name")
    p.add_argument("--version", type=int, help="defaults to the latest")
    p.add_argument("--force", action="store_true", help="replace an installed copy that has local edits")
    p = sub.add_parser("history", help="list every version of a skill")
    p.add_argument("name")
    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        from skills_catalog.server import create_app

        uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)
    elif args.command == "mcp":
        from skills_catalog.mcp_server import run

        run()
    else:
        try:
            _run(args, Config.from_env())
        except CatalogError as e:
            print(e.message, file=sys.stderr)
            for problem in e.problems:
                print(f"  - {problem['message']}", file=sys.stderr)
            sys.exit(1)
