"""Verify the detached checksum, archive inventory and each packaged file."""

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from package_artifacts import allowed


def require(test, message):
    if not test:
        raise ValueError(message)


def verify(path):
    line = path.with_suffix(".zip.sha256").read_text(encoding="ascii").strip()
    require(line == f"{sha256(path.read_bytes()).hexdigest()}  {path.name}", "detached SHA-256 mismatch")
    with ZipFile(path) as package:
        entries = package.namelist()
        require(len(set(entries)) == len(entries), "duplicate path in archive")
        for name in entries:
            parts = PurePosixPath(name)
            require(not parts.is_absolute() and ".." not in parts.parts and "\\" not in name,
                    "unsafe archive entry")
        checks = {}
        for line in package.read("SHA256SUMS").decode().splitlines():
            digest, name = line.split("  ", 1)
            require(name not in checks, "duplicate checksum")
            checks[name] = digest
        require(set(checks) == set(entries) - {"SHA256SUMS"}, "archive/checksum extent mismatch")
        for name, digest in checks.items():
            require(sha256(package.read(name)).hexdigest() == digest, f"content mismatch: {name}")
        manifest = json.loads(package.read("manifest.json"))
        reported = {item["path"]: item for item in manifest["files"]}
        require(len(reported) == len(manifest["files"]) and set(reported) == set(checks) - {"manifest.json"},
                "manifest extent mismatch")
        for name, item in reported.items():
            require(allowed(name, manifest["run_id"]), f"file outside public package scope: {name}")
            require(item["sha256"] == checks[name] and item["bytes"] == package.getinfo(name).file_size,
                    f"manifest mismatch: {name}")
    print(f"verified {path.name}, {len(reported)} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    verify(parser.parse_args().package)
