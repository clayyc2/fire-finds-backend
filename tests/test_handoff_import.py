import importlib.util
import io
import json
import hashlib
from pathlib import Path
import tarfile

import pytest

spec = importlib.util.spec_from_file_location(
    "handoff_import", Path(__file__).resolve().parents[1] / "scripts/import_handoff.py"
)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


def make_archive(tmp_path, entries):
    path = tmp_path / "in.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, kind in entries:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.mode = 0o777
            item.linkname = "/outside"
            if kind == tarfile.REGTYPE:
                item.size = 3
                archive.addfile(item, io.BytesIO(b"abc"))
            else:
                archive.addfile(item)
    return path


@pytest.mark.parametrize("entries", [
    [("../escape", tarfile.REGTYPE)],
    [("/escape", tarfile.REGTYPE)],
    [("secrets/link", tarfile.SYMTYPE)],
    [("hard", tarfile.LNKTYPE)],
    [("pipe", tarfile.FIFOTYPE)],
    [("a", tarfile.REGTYPE), ("a", tarfile.REGTYPE)],
    [("a/b", tarfile.REGTYPE), ("a", tarfile.REGTYPE)],
    [("..\\escape", tarfile.REGTYPE)],
])
def test_rejects_unsafe_archive_before_creating_output(tmp_path, entries):
    archive = make_archive(tmp_path, entries)
    destination = tmp_path / "review"
    with pytest.raises(ValueError):
        handoff.extract_for_review(archive, destination)
    assert not destination.exists()


def test_private_review_only_no_overwrite(tmp_path):
    archive = make_archive(tmp_path, [("secrets/key.txt", tarfile.REGTYPE)])
    destination = tmp_path / "review"
    assert handoff.extract_for_review(archive, destination) == 1
    assert destination.stat().st_mode & 0o777 == 0o700
    assert (destination / "secrets/key.txt").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        handoff.extract_for_review(archive, destination)


def test_checksum_and_bounded_expansion(tmp_path, monkeypatch):
    archive = make_archive(tmp_path, [("file", tarfile.REGTYPE)])
    with pytest.raises(ValueError, match="checksum"):
        handoff.verify_digest(archive, "0" * 64)
    monkeypatch.setattr(handoff, "MAX_BYTES", 2)
    with pytest.raises(ValueError, match="limits"):
        handoff.extract_for_review(archive, tmp_path / "review")


def test_assemble_validated_parts_without_overwrite(tmp_path):
    whole = b"partzeropartone"
    expected = hashlib.sha256(whole).hexdigest()
    parts = []
    for index, content in enumerate((b"partzero", b"partone")):
        name = f"archive.cms.part{index:03d}"
        (tmp_path / name).write_bytes(content)
        parts.append({"name": name, "bytes": len(content),
                      "sha256": hashlib.sha256(content).hexdigest()})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"parts": parts, "cms_bytes": len(whole), "cms_sha256": expected}))
    output = tmp_path / "archive.cms"
    handoff.assemble_parts(manifest, output, expected)
    assert output.read_bytes() == whole
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        handoff.assemble_parts(manifest, output, expected)
    parts[0]["name"] = "../archive.cms.part000"
    manifest.write_text(json.dumps({"parts": parts, "cms_bytes": len(whole), "cms_sha256": expected}))
    with pytest.raises(ValueError, match="local and sequential"):
        handoff.assemble_parts(manifest, tmp_path / "other.cms", expected)
