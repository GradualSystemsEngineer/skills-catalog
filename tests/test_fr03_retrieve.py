"""FR-03 / UC-03: retrieve a named skill, verified; not found is clear; failures never damage local files."""

import base64
import os

import pytest
from conftest import EXAMPLE, snapshot

from skills_catalog import client
from skills_catalog.client import CatalogError


def test_retrieve_by_name_writes_the_skill(cfg):
    client.publish(cfg, EXAMPLE)
    receipt = client.retrieve(cfg, "release-note-draft")
    location = os.path.join(cfg.skills_dir, "release-note-draft")
    assert receipt["status"] == "installed"
    assert receipt["location"] == location
    assert receipt["files"] == 2
    assert snapshot(location) == snapshot(EXAMPLE)


def test_unknown_name_is_not_found(cfg):
    with pytest.raises(CatalogError) as err:
        client.retrieve(cfg, "release-notes")
    assert err.value.code == "skill_not_found"
    assert err.value.message == "No skill named 'release-notes' in the catalog."


def tampered(package):
    first = package["files"][0]
    first["content_b64"] = base64.b64encode(base64.b64decode(first["content_b64"]) + b"tampered").decode()
    return package


def test_corrupted_download_leaves_no_partial_folder(cfg):
    client.publish(cfg, EXAMPLE)
    with pytest.raises(CatalogError) as err:
        client.install(cfg, tampered(client.fetch(cfg, "release-note-draft")))
    assert err.value.code == "verification_failed"
    assert os.listdir(cfg.skills_dir) == []


def test_corrupted_download_leaves_installed_copy_untouched(cfg, make_skill):
    client.publish(cfg, make_skill(body="Version one.\n"))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    before = snapshot(installed)
    client.publish(cfg, make_skill(body="Version two.\n"))
    with pytest.raises(CatalogError) as err:
        client.install(cfg, tampered(client.fetch(cfg, "demo-skill")))
    assert err.value.code == "verification_failed"
    assert snapshot(installed) == before
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]


def test_package_paths_are_never_trusted(cfg, tmp_path):
    client.publish(cfg, EXAMPLE)
    package = client.fetch(cfg, "release-note-draft")
    package["files"][0]["path"] = "../escaped.md"
    with pytest.raises(CatalogError) as err:
        client.install(cfg, package)
    assert err.value.code == "verification_failed"
    assert not (tmp_path / "escaped.md").exists()


def test_locally_edited_copy_is_refused_and_preserved(cfg):
    client.publish(cfg, EXAMPLE)
    client.retrieve(cfg, "release-note-draft")
    template = os.path.join(cfg.skills_dir, "release-note-draft", "assets", "template.md")
    with open(template, "a") as f:
        f.write("my local tweak\n")
    edited = snapshot(os.path.dirname(os.path.dirname(template)))

    with pytest.raises(CatalogError) as err:
        client.retrieve(cfg, "release-note-draft")
    assert err.value.code == "local_changes"
    assert "left untouched" in err.value.message
    assert snapshot(os.path.dirname(os.path.dirname(template))) == edited

    assert client.retrieve(cfg, "release-note-draft", force=True)["status"] == "updated"
    assert snapshot(os.path.join(cfg.skills_dir, "release-note-draft")) == snapshot(EXAMPLE)
    assert os.listdir(cfg.skills_dir) == ["release-note-draft"]  # no staging or aside folders left


def test_unreachable_catalog_is_explained(tmp_path):
    cfg = client.Config(url="http://127.0.0.1:9", skills_dir=str(tmp_path))
    with pytest.raises(CatalogError) as err:
        client.discover(cfg, "anything")
    assert err.value.message == "Cannot reach the catalog at http://127.0.0.1:9. Is `catalog serve` running?"
