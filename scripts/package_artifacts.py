"""Package the public Phase 1 source and a sanitized acceptance receipt."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile


ROOT_FILES = {".env.example", ".gitattributes", ".gitignore", "README.md", "REPRODUCE.md",
              "pyproject.toml", "requirements.lock"}
SOURCE_DIRS = (".github/", "configs/", "docs/", "prompts/", "scripts/", "src/", "tests/")
PUBLIC_REPORTS = {"run_manifest.json", "metrics.json", "acceptance.json", "report.md",
                  "failure_cases.jsonl", "audit_sampling_manifest.jsonl", "human_review_template.csv",
                  "approved_labels.json", "reward_preview_summary.json", "test_results.xml", "data_access.md",
                  "inventory.json", "execution.log"}


def allowed(name, run):
    if name in ROOT_FILES:
        return True
    if name.startswith(f"artifacts/{run}/"):
        return name.removeprefix(f"artifacts/{run}/") in PUBLIC_REPORTS
    return name.startswith(SOURCE_DIRS) and not any(
        part in {".env", ".venv", "__pycache__", ".phase1-private"} for part in name.split("/")
    ) and name.endswith((".py", ".md", ".json", ".jsonl", ".yaml", ".yml", ".sh", ".sbatch", ".mmd", ".txt"))


def digest(data):
    return sha256(data).hexdigest()


def build(commit, run, output):
    if not re.fullmatch(r"phase1_[A-Za-z0-9_-]+", run):
        raise ValueError("expected a phase1_ run ID")
    commit = subprocess.check_output(["git", "rev-parse", "--verify", commit + "^{commit}"], text=True).strip()
    receipt = Path("artifacts", run, "run_manifest.json")
    if not receipt.is_file():
        raise ValueError("acceptance receipt missing")
    manifest_data = json.loads(receipt.read_bytes())
    if manifest_data["code_commit"] != commit:
        raise ValueError("acceptance receipt names a different frozen source")
    archive = subprocess.check_output(["git", "archive", "--format=zip", commit,
                                       *sorted(ROOT_FILES), *(name.rstrip("/") for name in SOURCE_DIRS)])
    files = {}
    with ZipFile(BytesIO(archive)) as source:
        files.update({name: source.read(name) for name in source.namelist() if allowed(name, run)
                      and not name.startswith("artifacts/")})
    for filename in sorted(PUBLIC_REPORTS):
        path = receipt.parent / filename
        if path.is_file():
            files[path.as_posix()] = path.read_bytes()
    if "REPRODUCE.md" not in files:
        raise ValueError("portable package requires REPRODUCE.md in the frozen source")
    manifest = {"schema_version": 1, "run_id": run, "code_commit": commit, "run": manifest_data,
               "files": [{"path": name, "purpose": "public result" if name.startswith("artifacts/") else "source",
                          "bytes": len(data), "sha256": digest(data)} for name, data in sorted(files.items())]}
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    files["SHA256SUMS"] = "".join(f"{digest(data)}  {name}\n" for name, data in sorted(files.items())).encode()
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{run}_{commit[:12]}.zip"
    with ZipFile(target, "w", ZIP_DEFLATED) as package:
        for name, data in sorted(files.items()):
            package.writestr(name, data)
    target.with_suffix(".zip.sha256").write_text(f"{digest(target.read_bytes())}  {target.name}\n", encoding="ascii")
    print(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--output", type=Path, default=Path(".phase1-private/delivery"))
    args = parser.parse_args()
    build(args.code_commit, args.run_id, args.output)


if __name__ == "__main__":
    main()
