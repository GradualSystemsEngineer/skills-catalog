"""FR-04 / UC-04: every publish is a new version; earlier versions stay retrievable; history is visible."""

import os

import pytest
from conftest import EXAMPLE, row_counts, snapshot

from skills_catalog import client
from skills_catalog.client import CatalogError


def test_identical_republish_still_creates_a_version(cfg):
    first = client.publish(cfg, EXAMPLE)
    client.retrieve(cfg, "release-note-draft")
    second = client.publish(cfg, EXAMPLE)
    assert (first["version"], second["version"]) == (1, 2)
    assert first["digest"] == second["digest"]
    assert [v["version"] for v in client.history(cfg, "release-note-draft")] == [2, 1]

    receipt = client.retrieve(cfg, "release-note-draft")
    assert receipt["status"] == "up_to_date"
    assert receipt["version"] == 2


def test_latest_by_default_and_v1_still_retrievable(cfg, make_skill):
    client.publish(cfg, make_skill(body="First.\n"), author="dev1")
    client.publish(cfg, make_skill(body="Second.\n"), author="dev1")
    skill = os.path.join(cfg.skills_dir, "demo-skill", "SKILL.md")

    assert client.retrieve(cfg, "demo-skill")["version"] == 2
    assert open(skill).read().endswith("Second.\n")
    assert client.retrieve(cfg, "demo-skill", version=1)["status"] == "updated"
    assert open(skill).read().endswith("First.\n")


def test_history_shows_all_versions_newest_first_with_changes(cfg, make_skill):
    client.publish(cfg, make_skill(extra_files={"a.md": "a"}), author="dev1")
    client.publish(cfg, make_skill(body="Changed.\n", extra_files={"b.md": "b"}), author="dev2")
    history = client.history(cfg, "demo-skill")
    assert [(v["version"], v["author"]) for v in history] == [(2, "dev2"), (1, "dev1")]
    assert history[0]["changes"] == {"added": ["b.md"], "modified": ["SKILL.md"], "removed": []}
    assert history[1]["changes"] == {"added": ["SKILL.md", "a.md"], "modified": [], "removed": []}
    assert all(v["published_at"].endswith("Z") and v["digest"].startswith("sha256:") for v in history)


def test_v1_to_v2_to_v1_with_a_file_removed_in_v2(cfg, make_skill):
    folder = make_skill(extra_files={"notes/extra.md": "only in v1"})
    client.publish(cfg, folder)
    (folder / "notes" / "extra.md").unlink()
    (folder / "notes").rmdir()
    client.publish(cfg, folder)
    installed = os.path.join(cfg.skills_dir, "demo-skill")

    client.retrieve(cfg, "demo-skill", version=1)
    assert set(snapshot(installed)) == {"SKILL.md", "notes/extra.md"}
    client.retrieve(cfg, "demo-skill")
    assert set(snapshot(installed)) == {"SKILL.md"}
    assert client.history(cfg, "demo-skill")[0]["changes"]["removed"] == ["notes/extra.md"]
    client.retrieve(cfg, "demo-skill", version=1)
    assert set(snapshot(installed)) == {"SKILL.md", "notes/extra.md"}


def test_malformed_update_leaves_existing_versions_untouched(cfg, db_path, make_skill):
    client.publish(cfg, make_skill(body="Good.\n"))
    before = row_counts(db_path)
    with pytest.raises(CatalogError) as err:
        client.publish(cfg, make_skill(description=None, body="Broken update.\n"))
    assert err.value.code == "invalid_skill"
    assert row_counts(db_path) == before
    assert [v["version"] for v in client.history(cfg, "demo-skill")] == [1]
    client.retrieve(cfg, "demo-skill")
    assert open(os.path.join(cfg.skills_dir, "demo-skill", "SKILL.md")).read().endswith("Good.\n")


def test_missing_version_is_explained(cfg):
    client.publish(cfg, EXAMPLE)
    with pytest.raises(CatalogError) as err:
        client.retrieve(cfg, "release-note-draft", version=7)
    assert err.value.code == "version_not_found"
    assert err.value.message == "Skill 'release-note-draft' has no version 7. Latest is 1."
