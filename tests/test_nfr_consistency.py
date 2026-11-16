"""Consistency NFR: a retrieved skill is byte-for-byte and bit-for-bit what was published, nothing more."""

import os

from conftest import snapshot

from skills_catalog import client


def test_publish_then_retrieve_is_identical(cfg, tmp_path):
    src = tmp_path / "src" / "awkward-files"
    (src / "scripts").mkdir(parents=True)
    (src / "deep" / "er" / "still").mkdir(parents=True)
    # CRLF line endings in the manifest itself as well as in a supporting file.
    (src / "SKILL.md").write_bytes(b"---\r\nname: awkward-files\r\ndescription: Edge cases. Use in tests.\r\n---\r\nBody.\r\n")
    (src / "binary.bin").write_bytes(bytes(range(256)) * 4)
    (src / "windows.txt").write_bytes(b"line one\r\nline two\r\n")
    (src / "no-newline.md").write_bytes(b"ends without a newline")
    (src / "scripts" / "run.sh").write_bytes(b"#!/bin/sh\necho hi\n")
    os.chmod(src / "scripts" / "run.sh", 0o755)
    (src / "deep" / "er" / "still" / "nested.md").write_bytes(b"nested\n")
    (src / "notes-über-ç.md").write_bytes("non-ASCII name, non-ASCII content: ü ç 字\n".encode())
    (src / "empty.txt").write_bytes(b"")

    published = client.publish(cfg, src)
    receipt = client.retrieve(cfg, "awkward-files")

    original, retrieved = snapshot(src), snapshot(receipt["location"])
    assert set(retrieved) == set(original)  # nothing missing, nothing extra
    for path, (data, executable) in original.items():
        assert retrieved[path] == (data, executable), path
    assert retrieved["scripts/run.sh"][1] is True
    assert receipt["digest"] == published["digest"]
    assert receipt["files"] == len(original)
