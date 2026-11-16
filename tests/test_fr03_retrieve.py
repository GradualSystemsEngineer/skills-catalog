"""FR-03 / UC-03: retrieve a named skill, verified; not found is clear; failures never damage local files."""

import base64
import os
import shutil

import httpx
import pytest
from conftest import EXAMPLE, snapshot

from skills_catalog import client
from skills_catalog.client import CatalogError
from skills_catalog.domain import sha256_hex, version_digest


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
    """Flip one bit: same length, so only the SHA-256 comparison can catch it."""
    first = package["files"][0]
    data = bytearray(base64.b64decode(first["content_b64"]))
    data[0] ^= 1
    first["content_b64"] = base64.b64encode(bytes(data)).decode()
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


# The install rule: never destroy something the catalog can't give back.


def test_rule_1_absent_folder_is_installed(cfg, make_skill):
    folder = make_skill()
    client.publish(cfg, folder)
    assert client.classify_installed(cfg, "demo-skill") == {"state": "not_installed", "latest": 1}
    assert client.retrieve(cfg, "demo-skill")["status"] == "installed"
    assert snapshot(os.path.join(cfg.skills_dir, "demo-skill")) == snapshot(folder)
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]


def test_rule_2_same_digest_changes_nothing(cfg, make_skill):
    client.publish(cfg, make_skill())
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    before, inode = snapshot(installed), os.stat(installed).st_ino
    assert client.retrieve(cfg, "demo-skill")["status"] == "up_to_date"
    assert snapshot(installed) == before
    assert os.stat(installed).st_ino == inode  # not swapped for an identical copy
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]


def test_rule_3_other_published_version_is_replaced(cfg, make_skill):
    client.publish(cfg, make_skill(body="One.\n"))
    v1 = snapshot(make_skill(body="One.\n"))
    v2_folder = make_skill(body="Two.\n", extra_files={"two.md": "2"})
    client.publish(cfg, v2_folder)
    client.retrieve(cfg, "demo-skill", version=1)
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    assert snapshot(installed) == v1
    assert client.classify_installed(cfg, "demo-skill")["versions"] == [1]
    assert client.retrieve(cfg, "demo-skill")["status"] == "updated"
    assert snapshot(installed) == snapshot(v2_folder)
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]  # no staging or aside folder left


def _install_then_assert_refused(cfg, installed):
    before = snapshot(installed)
    assert client.classify_installed(cfg, "demo-skill") == {"state": "modified", "latest": 1}
    with pytest.raises(CatalogError) as err:
        client.retrieve(cfg, "demo-skill")
    assert err.value.code == "local_changes"
    assert snapshot(installed) == before
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]


def test_rule_4_local_edits_are_refused_and_untouched(cfg, make_skill):
    client.publish(cfg, make_skill(extra_files={"notes.md": "published"}))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    with open(os.path.join(installed, "mine.md"), "w") as f:
        f.write("an added file counts too\n")
    _install_then_assert_refused(cfg, installed)


def test_executable_bit_alone_counts_as_modified(cfg, make_skill):
    client.publish(cfg, make_skill(extra_files={"run.sh": "echo hi\n"}))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    os.chmod(os.path.join(installed, "run.sh"), 0o755)
    _install_then_assert_refused(cfg, installed)


def test_symlink_inside_folder_counts_as_modified(cfg, make_skill):
    client.publish(cfg, make_skill())
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    os.symlink("SKILL.md", os.path.join(installed, "link.md"))
    with pytest.raises(CatalogError) as err:
        client.retrieve(cfg, "demo-skill")
    assert err.value.code == "local_changes"
    assert os.path.islink(os.path.join(installed, "link.md"))


def test_failed_swap_leaves_original_in_place(cfg, make_skill, monkeypatch):
    client.publish(cfg, make_skill(body="One.\n"))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    before = snapshot(installed)
    client.publish(cfg, make_skill(body="Two.\n"))

    real_rename = os.rename

    def failing_rename(src, dst):
        if os.path.basename(src).startswith(".staging-"):
            raise OSError("simulated failure moving the new version in")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", failing_rename)
    with pytest.raises(OSError):
        client.retrieve(cfg, "demo-skill")
    monkeypatch.undo()
    assert snapshot(installed) == before
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]


def test_finder_metadata_is_not_a_local_edit(cfg, make_skill):
    client.publish(cfg, make_skill(extra_files={"notes/a.md": "a"}))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    for where in ("", "notes"):
        with open(os.path.join(installed, where, ".DS_Store"), "wb") as f:
            f.write(b"\x00\x00\x00\x01Bud1")
    assert client.classify_installed(cfg, "demo-skill")["state"] == "matches"
    assert client.retrieve(cfg, "demo-skill")["status"] == "up_to_date"
    assert os.path.exists(os.path.join(installed, "notes", ".DS_Store"))  # up to date means untouched


def test_tampered_version_digest_is_rejected(cfg):
    client.publish(cfg, EXAMPLE)
    package = client.fetch(cfg, "release-note-draft")
    package["digest"] = "sha256:" + "0" * 64
    with pytest.raises(CatalogError) as err:
        client.install(cfg, package)
    assert err.value.code == "verification_failed"
    assert os.listdir(cfg.skills_dir) == []


def _with_extra_files(package, extra):
    for path, data in extra:
        package["files"].append({
            "path": path, "sha256": sha256_hex(data), "size": len(data), "executable": False,
            "content_b64": base64.b64encode(data).decode(),
        })
    package["digest"] = version_digest([[f["path"], f["sha256"], f["executable"]] for f in package["files"]])
    return package


@pytest.mark.parametrize(
    "extra",
    [(("A.txt", b"first"), ("a.txt", b"second")), (("a", b"x"), ("a/b", b"y"))],
    ids=["case-alias", "file-and-folder"],
)
def test_package_that_cannot_exist_on_disk_is_not_installed(cfg, extra):
    client.publish(cfg, EXAMPLE)
    package = _with_extra_files(client.fetch(cfg, "release-note-draft"), extra)
    with pytest.raises(CatalogError) as err:
        client.install(cfg, package)
    assert err.value.code == "verification_failed"
    assert not os.path.exists(cfg.skills_dir)  # refused before anything is written


def test_edit_made_after_the_check_is_kept(cfg, make_skill, monkeypatch):
    """A file written between classification and the swap must survive: the swap re-checks what it moved aside."""
    client.publish(cfg, make_skill(body="One.\n"))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    client.publish(cfg, make_skill(body="Two.\n"))

    real_classify = client.classify_installed

    def classify_then_edit(*args):
        result = real_classify(*args)
        with open(os.path.join(installed, "local.md"), "w") as f:
            f.write("unpublished work")
        return result

    monkeypatch.setattr(client, "classify_installed", classify_then_edit)
    with pytest.raises(CatalogError) as err:
        client.retrieve(cfg, "demo-skill")
    assert err.value.code == "local_changes"
    assert open(os.path.join(installed, "local.md")).read() == "unpublished work"
    assert open(os.path.join(installed, "SKILL.md")).read().endswith("One.\n")
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_unreadable_subfolder_counts_as_modified(cfg, make_skill):
    client.publish(cfg, make_skill())
    client.retrieve(cfg, "demo-skill")
    secret = os.path.join(cfg.skills_dir, "demo-skill", "secret")
    os.mkdir(secret)
    with open(os.path.join(secret, "mine"), "w") as f:
        f.write("x")
    os.chmod(secret, 0)
    try:
        assert client.classify_installed(cfg, "demo-skill")["state"] == "modified"
        with pytest.raises(CatalogError) as err:
            client.retrieve(cfg, "demo-skill")
        assert err.value.code == "local_changes"
    finally:
        os.chmod(secret, 0o755)
    assert open(os.path.join(secret, "mine")).read() == "x"


def test_read_only_installed_copy_is_still_replaced_cleanly(cfg, make_skill):
    client.publish(cfg, make_skill(body="One.\n", extra_files={"notes/a.md": "a"}))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    os.chmod(os.path.join(installed, "notes"), 0o555)
    os.chmod(installed, 0o555)
    client.publish(cfg, make_skill(body="Two.\n", extra_files={"notes/a.md": "a"}))
    assert client.retrieve(cfg, "demo-skill")["status"] == "updated"
    assert open(os.path.join(installed, "SKILL.md")).read().endswith("Two.\n")
    assert os.listdir(cfg.skills_dir) == ["demo-skill"]


def test_cleanup_failure_after_swap_says_what_happened(cfg, make_skill, monkeypatch):
    client.publish(cfg, make_skill(body="One.\n"))
    client.retrieve(cfg, "demo-skill")
    installed = os.path.join(cfg.skills_dir, "demo-skill")
    client.publish(cfg, make_skill(body="Two.\n"))

    real_rmtree = shutil.rmtree

    def failing_rmtree(path, *args, **kwargs):
        if os.path.basename(path).startswith(".old-"):
            raise PermissionError(13, "Permission denied", path)
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", failing_rmtree)
    with pytest.raises(CatalogError) as err:
        client.retrieve(cfg, "demo-skill")
    monkeypatch.undo()
    assert err.value.code == "cleanup_failed"
    assert err.value.message.startswith(f"Version 2 is installed at {installed}, but the previous copy could not be removed")
    assert open(os.path.join(installed, "SKILL.md")).read().endswith("Two.\n")
    leftovers = [n for n in os.listdir(cfg.skills_dir) if n.startswith(".old-demo-skill-")]
    assert len(leftovers) == 1 and leftovers[0] in err.value.message


@pytest.mark.parametrize(
    "respond, code",
    [
        (lambda: httpx.Response(502, json=[]), "http_error"),
        (lambda: httpx.Response(200, text="<html>proxy page</html>"), "bad_response"),
        (lambda: httpx.Response(200, json=["not", "an", "object"]), "bad_response"),
        (lambda: (_ for _ in ()).throw(httpx.RemoteProtocolError("peer closed connection")), "unreachable"),
    ],
    ids=["error-with-list-body", "html-200", "list-200", "disconnect"],
)
def test_unexpected_http_replies_become_catalog_errors(tmp_path, monkeypatch, respond, code):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: respond())
    cfg = client.Config(url="http://catalog.invalid", skills_dir=str(tmp_path))
    with pytest.raises(CatalogError) as err:
        client.fetch(cfg, "anything")
    assert err.value.code == code
