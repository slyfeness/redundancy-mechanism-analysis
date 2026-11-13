from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "phase1_zhurong-fixture"


def run(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, **kwargs).stdout.strip()


def test_portable_zip_is_deterministic_and_requires_the_detached_checksum(tmp_path):
    from runpy import run_path

    packaging = run_path(str(ROOT / "scripts/package_artifacts.py"))
    run("git", "init", "-q", cwd=tmp_path)
    run("git", "config", "user.name", "Synthetic Fixture", cwd=tmp_path)
    run("git", "config", "user.email", "fixture@example.invalid", cwd=tmp_path)
    run("git", "config", "core.autocrlf", "false", cwd=tmp_path)
    for name in packaging["ROOT_FILES"] | set(packaging["DELIVERY_TOOLS"]):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic\n")
    for folder in packaging["SOURCE_DIRS"]:
        file = tmp_path / folder / "fixture.md"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic\n")
    raw = tmp_path / "private"
    raw.mkdir()
    (raw / "trajectory.json").write_bytes(b"must stay out")
    run("git", "add", ".", cwd=tmp_path)
    run("git", "commit", "-qm", "fixture snapshot", cwd=tmp_path)
    commit = run("git", "rev-parse", "HEAD", cwd=tmp_path)
    receipt = tmp_path / "artifacts" / RUN_ID
    receipt.mkdir(parents=True)
    for name in packaging["PUBLIC_REPORTS"]:
        (receipt / name).write_bytes(b"synthetic\n")
    (receipt / "run_manifest.json").write_text(json.dumps({"code_commit": commit, "synthetic": True}), encoding="utf-8")

    base = (sys.executable, str(ROOT / "scripts/package_artifacts.py"), "--run-id", RUN_ID, "--code-commit", commit)
    first = tmp_path / run(*base, "--output", "first", cwd=tmp_path)
    second = tmp_path / run(*base, "--output", "second", cwd=tmp_path)
    assert sha256(first.read_bytes()).digest() == sha256(second.read_bytes()).digest()
    verify = (sys.executable, str(ROOT / "scripts/verify_artifacts.py"), "--package", str(first))
    assert "verified" in run(*verify)
    with ZipFile(first) as archive:
        assert "private/trajectory.json" not in archive.namelist()
        assert "manifest.json" in archive.namelist()
    first.with_suffix(".zip.sha256").write_text("0" * 64, encoding="ascii")
    rejected = subprocess.run(verify, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "detached SHA-256 mismatch" in rejected.stderr
