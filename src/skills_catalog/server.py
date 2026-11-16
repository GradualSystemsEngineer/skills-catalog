"""The catalog service: five JSON routes over one SQLite file.

Routes are plain `def`, so FastAPI runs them in its thread pool; each request opens its own connection.
"""

import base64
import binascii
from contextlib import closing
from typing import Any

from fastapi import Body, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from skills_catalog import domain, store

REQUEST_SHAPE = "Request body must be {author, files: [{path, executable, content_b64}]}."


def _invalid(problems: list[dict]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "invalid_skill", "problems": problems})


def _request_invalid(message: str = REQUEST_SHAPE) -> JSONResponse:
    return _invalid([{"code": "request_invalid", "message": message}])


def _skill_not_found(name: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "skill_not_found", "message": f"No skill named '{name}' in the catalog."},
    )


def _decode_files(body: Any) -> list[dict] | str:
    """Check the publish body by hand. Returns decoded files, or a message saying what is wrong."""
    if not isinstance(body, dict) or not isinstance(body.get("files"), list):
        return REQUEST_SHAPE
    if body.get("author") is not None and not isinstance(body["author"], str):
        return REQUEST_SHAPE
    files = []
    for f in body["files"]:
        if not (
            isinstance(f, dict)
            and isinstance(f.get("path"), str)
            and isinstance(f.get("executable"), bool)
            and isinstance(f.get("content_b64"), str)
        ):
            return REQUEST_SHAPE
        try:
            data = base64.b64decode(f["content_b64"], validate=True)
        except (binascii.Error, ValueError):
            return f"{f['path']}: content_b64 is not valid base64."
        files.append({"path": f["path"], "executable": f["executable"], "data": data})
    return files


def create_app(db_path) -> FastAPI:
    app = FastAPI(title="Skills Catalog")
    with closing(store.connect(db_path)):
        pass  # create the tables once at startup

    def db():
        return closing(store.connect(db_path))

    @app.exception_handler(RequestValidationError)
    def _bad_request(request, exc):
        return _request_invalid()

    @app.post("/skills", status_code=201)
    def publish(body: Any = Body(None)):
        files = _decode_files(body)
        if isinstance(files, str):
            return _request_invalid(files)
        problems = domain.validate(files)
        if problems:
            return _invalid(problems)
        front, text = domain.parse_manifest(next(f["data"] for f in files if f["path"] == domain.MANIFEST))
        for f in files:
            f["sha256"] = domain.sha256_hex(f["data"])
            f["size"] = len(f["data"])
        with db() as conn:
            version, digest, published_at = store.publish(
                conn, front["name"], front["description"], text, body.get("author"), files
            )
        return {"name": front["name"], "version": version, "digest": digest, "published_at": published_at}

    @app.get("/skills")
    def discover(q: str | None = None):
        with db() as conn:
            matches = store.list_all(conn) if q is None else store.search(conn, q)
            return {"query": q, "matches": matches, "catalog_size": store.count_skills(conn)}

    @app.get("/skills/{name}")
    def latest(name: str):
        with db() as conn:
            package = store.get_version(conn, name)
        return package if package else _skill_not_found(name)

    @app.get("/skills/{name}/versions")
    def versions(name: str):
        with db() as conn:
            entries = store.history(conn, name)
        return {"name": name, "versions": entries} if entries else _skill_not_found(name)

    @app.get("/skills/{name}/versions/{version}")
    def one_version(name: str, version: int):
        with db() as conn:
            package = store.get_version(conn, name, version)
            newest = None if package else store.latest_version(conn, name)
        if package:
            return package
        if newest is None:
            return _skill_not_found(name)
        return JSONResponse(
            status_code=404,
            content={
                "error": "version_not_found",
                "message": f"Skill '{name}' has no version {version}. Latest is {newest}.",
            },
        )

    return app
