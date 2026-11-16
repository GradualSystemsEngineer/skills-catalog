"""FR-01 / UC-01: publish a skill; a skill missing name, description or body is rejected with an explanation."""

import base64
import os

import pytest
from conftest import EXAMPLE, row_counts, snapshot

from skills_catalog import client
from skills_catalog.client import CatalogError


def test_publish_with_supporting_file_is_available_complete(cfg):
    receipt = client.publish(cfg, EXAMPLE, author="dev1")
    assert receipt["name"] == "release-note-draft"
    assert receipt["version"] == 1
    assert receipt["digest"].startswith("sha256:")

    package = client.fetch(cfg, "release-note-draft")
    stored = {f["path"]: base64.b64decode(f["content_b64"]) for f in package["files"]}
    assert stored == {path: data for path, (data, _) in snapshot(EXAMPLE).items()}
    assert package["author"] == "dev1"


@pytest.mark.parametrize(
    "missing, code, message",
    [
        ("name", "name_missing", "name is missing. Add name: your-skill-name to the frontmatter."),
        ("description", "description_missing", "description is missing. Say what the skill does and when to use it."),
        ("body", "body_missing", "SKILL.md has no instruction body."),
    ],
)
def test_missing_field_rejected_with_explanation_and_nothing_stored(cfg, db_path, make_skill, missing, code, message):
    client.publish(cfg, EXAMPLE)  # so the tables are not empty
    before = row_counts(db_path)
    kwargs = {"name": "broken-skill", "folder": "broken"}
    kwargs[missing] = "\n" if missing == "body" else None
    with pytest.raises(CatalogError) as err:
        client.publish(cfg, make_skill(**kwargs))
    assert err.value.code == "invalid_skill"
    assert {"code": code, "message": message} in err.value.problems
    assert row_counts(db_path) == before


def test_every_problem_is_reported_at_once(cfg, make_skill):
    with pytest.raises(CatalogError) as err:
        client.publish(cfg, make_skill(name="Not Valid", description=None, body="", folder="bad"))
    codes = {p["code"] for p in err.value.problems}
    assert codes == {"name_invalid", "description_missing", "body_missing"}


def test_folder_without_manifest_is_rejected(cfg, tmp_path):
    folder = tmp_path / "no-manifest"
    folder.mkdir()
    (folder / "README.md").write_text("hello")
    with pytest.raises(CatalogError) as err:
        client.publish(cfg, folder)
    assert err.value.problems == [{"code": "manifest_missing", "message": "No SKILL.md found at the top of the skill folder."}]


def test_symlink_is_refused_before_sending(cfg, make_skill, db_path):
    folder = make_skill()
    (folder / "link.md").symlink_to(folder / "SKILL.md")
    with pytest.raises(CatalogError) as err:
        client.publish(cfg, folder)
    assert err.value.code == "symlink"
    assert row_counts(db_path)["versions"] == 0


def test_finder_metadata_is_never_published(cfg, make_skill):
    import base64

    import httpx

    clean = client.publish(cfg, make_skill(body="Same.\n"))
    cluttered = client.publish(cfg, make_skill(body="Same.\n", extra_files={".DS_Store": b"\x00Bud1", "sub/.DS_Store": b"\x00"}))
    assert cluttered["digest"] == clean["digest"]
    assert [f["path"] for f in client.fetch(cfg, "demo-skill")["files"]] == ["SKILL.md"]

    # A client that sends one anyway is refused, so no published version can disagree with an installed copy.
    raw = {"author": "x", "files": [
        {"path": p, "executable": False, "content_b64": base64.b64encode(d).decode()}
        for p, d in (("SKILL.md", b"---\nname: other-skill\ndescription: d\n---\nbody\n"), (".DS_Store", b"\x00"))
    ]}
    r = httpx.post(cfg.url + "/skills", json=raw)
    assert r.status_code == 422
    assert [p["code"] for p in r.json()["problems"]] == ["path_invalid"]


def _post_raw(cfg, files):
    import httpx

    return httpx.post(cfg.url + "/skills", json={"author": "x", "files": [
        {"path": p, "executable": False, "content_b64": base64.b64encode(d).decode()} for p, d in files
    ]})


GOOD_MANIFEST = b"---\nname: demo-skill\ndescription: d\n---\nbody\n"


@pytest.mark.parametrize(
    "extra, message",
    [
        ((("A.txt", b"first"), ("a.txt", b"second")),
         "a.txt and A.txt differ only in letter case or Unicode form, so they would be the same file."),
        ((("café.md", b"1"), ("café.md", b"2")),
         "café.md and café.md differ only in letter case or Unicode form, so they would be the same file."),
        ((("a", b"x"), ("a/b", b"y")), "a is a file, but a/b needs it to be a folder."),
    ],
)
def test_paths_that_cannot_coexist_on_disk_are_rejected(cfg, db_path, extra, message):
    r = _post_raw(cfg, (("SKILL.md", GOOD_MANIFEST), *extra))
    assert r.status_code == 422
    assert {"code": "path_conflict", "message": message} in r.json()["problems"]
    assert row_counts(db_path)["versions"] == 0


@pytest.mark.parametrize(
    "front, code",
    [
        ('name: "bad\\n"\ndescription: d', "name_invalid"),          # a trailing newline is not part of a valid name
        ("name: demo-skill\ndescription: 2026-99-99", "frontmatter_invalid"),  # PyYAML raises ValueError here
        ("name: demo-skill\ndescription: " + "[" * 5000, "frontmatter_invalid"),  # RecursionError
    ],
)
def test_awkward_manifests_get_an_explanation_not_a_server_error(cfg, db_path, front, code):
    r = _post_raw(cfg, (("SKILL.md", f"---\n{front}\n---\nbody\n".encode()),))
    assert r.status_code == 422
    assert code in [p["code"] for p in r.json()["problems"]]
    assert row_counts(db_path)["versions"] == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_unreadable_subfolder_stops_the_publish(cfg, make_skill, db_path):
    folder = make_skill(extra_files={"secret/mine.md": "x"})
    os.chmod(folder / "secret", 0)
    try:
        with pytest.raises(CatalogError) as err:
            client.publish(cfg, folder)
    finally:
        os.chmod(folder / "secret", 0o755)
    assert err.value.code == "unreadable"
    assert err.value.message.startswith("secret in ")
    assert row_counts(db_path)["versions"] == 0
