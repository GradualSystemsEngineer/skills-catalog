"""FR-01 / UC-01: publish a skill; a skill missing name, description or body is rejected with an explanation."""

import base64

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
