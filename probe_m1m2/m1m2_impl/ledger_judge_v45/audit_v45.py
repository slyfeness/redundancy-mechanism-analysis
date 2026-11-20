"""Verify the v4.5 artifacts, dispatch cap, offline replay, and publication."""

from argparse import ArgumentParser, Namespace
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from probe_v45 import CAP, PRIVATE, add_args, digest, export, read, rows
from rules_v45 import normalized, proper

FULL = Path(__file__).resolve().parent.parent / "m2_v61_full"
if FULL.is_dir():
    sys.path.append(str(FULL))
from publish_check import SECRET, grams, public_stage, words

DIRECTORY = "probe_m1m2/m1m2_impl/ledger_judge_v45/"
REVOKED = "probe_m1m2/m1m2_impl/ledger_judge_v44/FREEZE.json"
PUBLIC = {DIRECTORY + name for name in ("probe_v45.py", "rules_v45.py", "report_v45.py",
                                       "test_v45.py", "audit_v45.py", "run.sbatch", "REPORT.md")} | {REVOKED}
PREFIX = "ledger_judge_v45/"
REVOKED_FIELDS = {"status": "revoked", "superseded_by": "ledger-judge-v4.5", "reason": "manual_review_failed"}


def key(row):
    return row["trajectory_id"], row["stage_id"]


def signal_key(row):
    return row["id"]


def decode(blob):
    return list(map(json.loads, blob.decode("utf-8").splitlines()))


def verify_data(before, old_signals, stages, signals, events, checks, sample):
    old_index = {key(row): row for row in before}
    index = {key(row): row for row in stages}
    if len(index) != 430 or len(stages) != 430 or list(index) != list(map(key, before)):
        raise ValueError("Stage coverage or order changed")
    if list(index) != list(map(key, signals)) or list(index) != list(map(key, old_signals)):
        raise ValueError("signal table coverage changed")
    case_index = {signal_key(row): row for row in checks}
    if len(case_index) != len(checks) or len({(r["question_id"], r["var"], normalized(r["name"])) for r in checks}) != len(checks):
        raise ValueError("eligibility pair was requested multiple times")
    event_set = {(key(row), row["event"]) for row in events}
    for current, reference in zip(signals, old_signals, strict=True):
        sid = key(current)
        row, old = index[sid], old_index[sid]
        if current.keys() != reference.keys() or any(current[field] != reference[field] for field in
                ("C_new", "gen_tokens", "return_tokens", "invalid")):
            raise ValueError("credit or token cost differs from v4.4")
        if any(row[field] != old[field] for field in ("searches", "new_docids", "seen_docids", "C_new", "outcome",
                                                     "judge_raw", "input_tokens", "ledger_after_v43", "first_invalid")):
            raise ValueError("v4.4 immutable Stage fields changed")
        tags = row["labels"]
        if tags.get("strict_repeat") != old["labels"].get("strict_repeat") or tags["invalid"] != old["labels"]["invalid"]:
            raise ValueError("filtered or strict_repeat Stage changed")
        if [r["judge_main_name"] for r in row["items"]] != [r["judge_main_name"] for r in old["items"]]:
            raise ValueError("inherited extraction changed")
        if len(row["searches"]) != len(row["items"]):
            raise ValueError("per-search trace alignment changed")
        for item in row["items"]:
            name = item["main_name"]
            if name not in (None, "none") and not proper(name):
                raise ValueError("capitalization-invalid name retained")
            check = case_index.get(item.get("eligibility_check"))
            if item["attribution"] == "wrong_candidate":
                if item["backfilled"] or not check or check["result"] != "yes":
                    raise ValueError("wrong candidate lacks positive eligibility")
            if check and (normalized(check["name"]) != normalized(name) or check["var"] != item["var"]):
                raise ValueError("eligibility receipt does not match search slot")
        for field in ("F_new", "F_corrected"):
            if type(current[field]) is not int or current[field] != int(tags[field]) or tags[field] != ((sid, field) in event_set):
                raise ValueError("candidate event and M3 signal disagree")
        if current["idle_type"] != row["idle_type"] or current["protected_new_hypothesis"] != tags["protected_new_hypothesis"]:
            raise ValueError("idle or protection signal disagrees")
    for event in events:
        sid = event["stage_id"]
        if not event["var"] or not 1 <= event["first_stage"] < event["confirmation_stage"]:
            raise ValueError("candidate event is missing a concrete var or recurrence")
        for delta, label in ((-1, "before"), (0, "current"), (1, "after")):
            expected = index.get((event["trajectory_id"], sid + delta), {}).get("searches", [])
            if expected != event["search_window"][label]:
                raise ValueError("candidate event window differs from original searches")
    sample_slots = set()
    for entry in sample:
        row = index[key(entry)]
        i = entry["query_index"] - 1
        if i < 0 or entry != {**{f: row[f] for f in ("trajectory_id", "stage_id", "judge_raw")},
                              "query_index": i + 1, "query": row["searches"][i], **row["items"][i]}:
            raise ValueError("audit sample row is unbound")
        sample_slots.add((*key(entry), i))
    if len(sample_slots) != 70 or len(sample) != 70:
        raise ValueError("expected 70 distinct search slots")


def private():
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(names) - {""} != {f"{PREFIX}{name}.jsonl" for name in PRIVATE}:
        raise ValueError("unexpected private files")
    data = [subprocess.check_output(["git", "show", f":{PREFIX}{name}.jsonl"]) for name in PRIVATE]
    old = [subprocess.check_output(["git", "show", f"HEAD:ledger_judge_v44/{name}.jsonl"])
           for name in ("stages", "stage_signals")]
    if any(b"\0" in blob or SECRET.search(blob.decode("utf-8")) for blob in data):
        raise ValueError("private credential scan failed")
    verify_data(*(decode(blob) for blob in old + data))
    print(json.dumps({"private_sha256": {name: sha256(blob).hexdigest()
                                         for name, blob in zip(PRIVATE, data, strict=True)},
                      "v44_sha256": [sha256(blob).hexdigest() for blob in old], "credential_matches": 0}))


def compare(args):
    work = args.out
    files = {name: work / PREFIX / f"{name}.jsonl" for name in PRIVATE}
    parents = [args.v44 / "ledger_judge_v44" / f"{name}.jsonl" for name in ("stages", "stage_signals")]
    counts = read(work / "COUNTS.json")
    calls = counts["calls"]
    actual = sum(log.read_text(encoding="utf-8", errors="replace").count("POST /v1/chat/completions")
                 for log in work.glob("server-*.log"))
    checks = list(rows(files["eligibility_checks"]))
    receipts = list((work / "requests" / "eligibility").glob("*/*.json"))
    if (counts["status"] != "pending_manual_review" or counts["psi"] != 0 or counts["heldout_decoded"] != 0
            or set(calls) - {"type", "alias", "eligibility"} or not 0 < actual <= CAP
            or actual != sum(calls.values()) or actual != len(list((work / "requests").rglob("*.json")))
            or len(checks) != len(receipts) or any(path.name != "1.json" for path in receipts)):
        raise ValueError("scope or physical request count mismatch")
    verify_data(*(list(rows(path)) for path in [*parents, *files.values()]))
    with TemporaryDirectory(prefix="v45-release-replay-", dir=work) as folder:
        replica = Path(folder)
        (replica / "requests").symlink_to(work / "requests", target_is_directory=True)
        export(Namespace(**{**vars(args), "out": replica, "preflight": False, "replay": True, "url": None}))
        filenames = [f"{PREFIX}{name}.jsonl" for name in PRIVATE] + ["COUNTS.json"]
        replayed_report = (replica / "REPORT.md").read_text(encoding="utf-8")
        if any(digest(work / name) != digest(replica / name) for name in filenames):
            raise ValueError("offline replay differs")

    manifest = read(args.manifest)
    if manifest.keys() != PUBLIC or manifest[DIRECTORY + "REPORT.md"]["text"] != replayed_report:
        raise ValueError("release manifest differs from recorded report")
    if json.loads(manifest[REVOKED]["text"]) != {**read(args.v44 / "FREEZE.json"), **REVOKED_FIELDS}:
        raise ValueError("historical v4.4 fingerprints or revoked status mismatch")
    public_words, literals = set(), set()
    for path, rec in manifest.items():
        body = rec["text"]
        if sha256(body.encode()).hexdigest() != rec["sha256"] or SECRET.search(body):
            raise ValueError("release fingerprint or public credential scan failed")
        if Path(path).suffix in (".py", ".sbatch") and digest(Path(__file__).with_name(Path(path).name)) != rec["sha256"]:
            raise ValueError("published code differs from executed source")
        public_words.update(grams(body))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(body))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))

    def scan(value):
        tokens = tuple(words(value))
        if public_words.intersection(grams(value)) or (len(tokens) >= 3 and tokens in literals):
            raise ValueError("protected text matched the public release")

    plan = read(args.previous / "plan.json")
    for track in plan.values():
        payload = track["payload"]
        scan(payload["question"])
        for entity in payload["entities"]:
            scan(entity["name"])
            scan(entity["role"])
        for frame in payload["stages"]:
            scan(frame["thought_tail"])
            for query in frame["searches"]:
                scan(query)
    for row in rows(args.root / "supplement-m1-192125/stages.jsonl"):
        if row["trajectory_id"] in plan:
            for event in row["tool_events"]:
                scan(event["return_text"])
    if any(SECRET.search(path.read_text(encoding="utf-8")) for path in files.values()):
        raise ValueError("private credential scan failed")
    print(json.dumps({"audit": "PASS", "judge_calls": actual, "eligibility_pairs": len(checks),
                      "manifest_sha256": digest(args.manifest), "v44_sha256": [digest(path) for path in parents],
                      "private_sha256": {name: digest(path) for name, path in files.items()}}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("private")
    sub.add_parser("public").add_argument("manifest", type=Path)
    verify = sub.add_parser("compare")
    verify.add_argument("manifest", type=Path)
    add_args(verify)
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    elif args.mode == "private":
        private()
    else:
        compare(args)


if __name__ == "__main__":
    main()
