"""Compare raw input and historical checksums, then frozen full-run outputs."""

import argparse
from hashlib import sha256
from pathlib import Path

from redundancy_judge.common import atomic_json, read_json


def sha(path):
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare(original, verification):
    before = Path(read_json(original / "config.json")["input_index"]).parent
    after = verification / "inventory-after"
    a, b = (read_json(path / "inventory.json") for path in (before, after))
    criteria = ("status", "source_artifacts", "legacy_assets", "private_output_sha256")
    original_inputs = {key: a[key] == b[key] for key in criteria}
    original_inputs["dataset_ready"] = a["status"] == b["status"] == "READY"
    actual, replay = original / "real", verification / "replay/real"
    names = {path.name for path in actual.glob("*.jsonl")}
    names |= {"metrics.json", "run_manifest.json", "reference_cost.json", "acceptance.json",
              "approved_labels.json", "reward_preview_summary.json", "human_review_template.csv",
              "protection_sampling.json"}
    outputs = {}
    for name in sorted(names):
        actual_path, replay_path = actual / name, replay / name
        actual_sha = sha(actual_path) if actual_path.is_file() else None
        replay_sha = sha(replay_path) if replay_path.is_file() else None
        outputs[name] = {"sha256": actual_sha, "replay_sha256": replay_sha,
                         "equal": actual_sha is not None and actual_sha == replay_sha}
    ok = all(original_inputs.values()) and all(row["equal"] for row in outputs.values())
    return {"status": "PASS" if ok else "FAIL", "original_inputs": original_inputs,
            "artifacts": outputs, "compared": len(outputs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.original, args.verification)
    atomic_json(args.verification / "replay_verification.json", result)
    print(result["status"], result["compared"], "compared artifacts", flush=True)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
