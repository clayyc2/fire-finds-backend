"""Decrypt an authenticated handoff into a NEW private review directory only.

Never installs credentials, sources .env, imports incoming code, or overwrites
the running checkout. All archive members are validated before extraction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

MAX_MEMBERS = 50000
MAX_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024


def validate_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    names: dict[str, bool] = {}
    total = 0
    for member in archive:
        path = PurePosixPath(member.name)
        if (not member.name or path.is_absolute() or ".." in path.parts
                or "\\" in member.name or any(ord(c) < 32 for c in member.name)):
            raise ValueError("Unsafe archive path")
        if str(path) == ".":
            if member.isdir():
                continue
            raise ValueError("Invalid archive root")
        if not (member.isfile() or member.isdir()):
            raise ValueError("Archive links and special files are not accepted")
        name = str(path)
        if name in names:
            raise ValueError("Duplicate archive path")
        names[name] = member.isdir()
        if member.size < 0 or member.size > MAX_FILE_BYTES:
            raise ValueError("Archive member exceeds size limit")
        total += member.size
        members.append(member)
        if len(members) > MAX_MEMBERS or total > MAX_BYTES:
            raise ValueError("Archive exceeds import limits")
    for name in names:
        if any(str(parent) in names and not names[str(parent)]
               for parent in PurePosixPath(name).parents):
            raise ValueError("Archive file/directory collision")
    return members


def extract_for_review(archive_path: Path, destination: Path) -> int:
    # Caller must choose a new path; never merge imported state with local state.
    if destination.exists() or destination.is_symlink():
        raise ValueError("Review destination already exists")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = validate_members(archive)
        destination.mkdir(mode=0o700)
        count = 0
        for member in members:
            target = destination / str(PurePosixPath(member.name))
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(mode=0o700, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Archive file content unavailable")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with source, os.fdopen(fd, "wb") as output:
                shutil.copyfileobj(source, output)
            count += 1
    return count


def verify_digest(path: Path, expected: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("Expected a SHA256 from the authenticated handoff")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected.lower():
        raise ValueError("Encrypted handoff checksum mismatch")


def assemble_parts(manifest_path: Path, output: Path, expected: str) -> None:
    """Reassemble only validated, sequential, local ciphertext parts."""
    manifest = json.loads(manifest_path.read_text())
    parts = manifest["parts"]
    if (not isinstance(parts, list) or not 1 <= len(parts) <= 256
            or manifest.get("cms_sha256") != expected):
        raise ValueError("Unexpected handoff manifest")
    total = 0
    sources = []
    for index, part in enumerate(parts):
        required_name = f"{output.name}.part{index:03d}"
        if part["name"] != required_name:
            raise ValueError("Part names must be local and sequential")
        source = manifest_path.parent / required_name
        if source.is_symlink() or not source.is_file():
            raise ValueError("Part must be a local regular file")
        size = source.stat().st_size
        if size != part["bytes"] or not 0 < size <= 4 * 1024 * 1024:
            raise ValueError("Unexpected part size")
        verify_digest(source, part["sha256"])
        total += size
        sources.append(source)
    if total != manifest["cms_bytes"] or total > MAX_BYTES:
        raise ValueError("Unexpected ciphertext size")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as destination:
        for source in sources:
            with source.open("rb") as content:
                shutil.copyfileobj(content, destination)
    verify_digest(output, expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--parts-manifest", type=Path)
    args = parser.parse_args()
    if args.parts_manifest:
        assemble_parts(args.parts_manifest, args.archive, args.sha256)
    verify_digest(args.archive, args.sha256)
    if args.key.is_symlink() or args.key.stat().st_mode & 0o077:
        raise ValueError("Private key must be a regular private file (mode 600)")
    if not args.key.is_file():
        raise ValueError("Private key must be a file")
    os.umask(0o077)
    # Temporary plaintext remains private and is removed on completion/failure.
    with tempfile.TemporaryDirectory(prefix="firefinds-handoff-") as scratch:
        plaintext = Path(scratch) / "handoff.tar.gz"
        result = subprocess.run([
            "openssl", "cms", "-decrypt", "-binary", "-inform", "DER",
            "-in", str(args.archive), "-recip", str(args.certificate),
            "-inkey", str(args.key), "-out", str(plaintext),
        ], capture_output=True, check=False)
        if result.returncode:
            raise ValueError("Handoff decryption failed; no credentials installed")
        count = extract_for_review(plaintext, args.destination)
    print(f"Extracted {count} private files for review; nothing installed or executed.")


if __name__ == "__main__":
    main()
