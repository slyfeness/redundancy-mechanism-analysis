"""Extract a v7 chain using source clauses and condition-linked citations."""
from argparse import ArgumentParser
from pathlib import Path

from chain_extractor import encode, load, prepare, replace_text
from chain_extractor_v2 import list_field, obj
from chain_extractor_v3 import run_case as run_scoped
from chain_extractor_v6 import (
    PHASES, V6Protocol, candidate_key, check_groups as check_v6_groups,
    extract_conditions as extract_v6_conditions,
)


def read_prompts(path):
    return {phase: (path / f"prompt_v7_{phase}.txt").read_text(encoding="utf-8") for phase in PHASES}


def check_groups(question, clauses, value):
    check = check_v6_groups(question, clauses, value)
    value = obj(value)
    excluded = {item for item in list_field(value, "ignored") if isinstance(item, str)}
    for group in list_field(value, "conditions"):
        group = obj(group)
        if group.get("asked") is True:
            excluded.update(item for item in list_field(group, "clauses") if isinstance(item, str))
    minimum = min(4, sum(row["id"] not in excluded for row in clauses))
    check["minimum_ordinary_conditions"] = minimum
    if check["ordinary_conditions"] < minimum:
        check["reasons"].append(f"除所问外的条件数至少为 {minimum}")
        check["valid"] = False
    return check


def extract_conditions(question, prompt, cfg, folder):
    return extract_v6_conditions(question, prompt, cfg, folder, check=check_groups)


def candidate_equivalent(first, second):
    if not isinstance(first, str) or not isinstance(second, str):
        return first is None and second is None
    first, second = candidate_key(first), candidate_key(second)
    if not first or not second:
        return False
    short, long = sorted((first.split(), second.split()), key=len)
    return first == second or (len(short) < len(long) and short[-1] == long[-1] and set(short) <= set(long))


class V7Protocol(V6Protocol):
    def merge_candidates(self, initial, operations):
        names = {row["name"].strip() for row in [*initial["candidates"], *operations]}
        representatives = {}
        for name in sorted(names, key=lambda name: (-len(name), name.casefold(), name)):
            matching = [other for other in representatives.values() if candidate_equivalent(name, other)]
            unique = list(dict.fromkeys(matching))
            representatives[name] = unique[0] if len(unique) == 1 else name

        def rename(row):
            name = row["name"].strip()
            representative = representatives[name]
            variants = self.aliases.setdefault(candidate_key(representative), set())
            if representative != name and name not in variants:
                self.merges += 1
            variants.add(name)
            return {**row, "name": representative}
        return {**initial, "candidates": [rename(row) for row in initial["candidates"]]}, [
            rename(row) for row in operations]

    @staticmethod
    def fact_conditions(item, row, condition_ids):
        supplied = list_field(item, "conditions")
        valid = list(dict.fromkeys(cid for cid in supplied if isinstance(cid, str) and cid in condition_ids))
        row.update(conditions=valid,
                   invalid_conditions=[cid for cid in supplied if not isinstance(cid, str) or cid not in condition_ids])

    records_start_claims = True


def run_case(data, frozen, prompts, cfg, out, progress=None):
    protocol = V7Protocol(frozen["answer_type"])
    result = run_scoped(data, frozen["conditions"], prompts, cfg, out, "S", progress, protocol=protocol)
    return {**result, "candidate_merges": protocol.merges}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config_v7.json"))
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--conditions", type=Path)
    args = parser.parse_args()
    cfg = load(args.config)
    if (cfg["reasoning_effort"], cfg["temperature"], cfg["max_tokens"]) != ("medium", 0, 16384):
        raise ValueError("v7 requires medium, temperature 0 and 16384 output tokens")
    data = prepare(load(args.trajectory), load(args.terminal or args.trajectory.with_name("TERMINAL.json")),
                   cfg["thought_truncation"])
    prompts = read_prompts(Path(__file__).parent)
    frozen = load(args.conditions) if args.conditions else extract_conditions(
        data["question"], prompts["C"], cfg, args.output / "condition_checkpoint")
    run_case(data, frozen, prompts, cfg, args.output)
    replace_text(args.output / "CONDITIONS.json", encode(frozen) + "\n")


if __name__ == "__main__":
    main()
