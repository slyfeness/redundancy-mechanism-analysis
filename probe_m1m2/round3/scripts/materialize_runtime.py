"""Copy the frozen pilot into an isolated extension with bounded substitutions.
This never edits historical source files. Execute locally before deployment.
"""
import ast,hashlib,json
from pathlib import Path
S=Path(__file__).resolve().parent
P=S.parent/'private/source'
def replace(text,old,new):
    assert text.count(old)==1,old[:100]
    return text.replace(old,new,1)

a=(P/'actor.py').read_text(encoding='utf-8')
a=replace(a,'REPETITIONS = 8','REPETITIONS = 2')
a=replace(a,'MODEL_NAME = "Qwen/Qwen3.5-4B"\nMODEL_REV = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"',
'''SIZE = os.environ["LEDGER_ACTOR_SIZE"]
assert SIZE in {"4B", "9B"}
MODEL_NAME = "Qwen/Qwen3.5-" + SIZE
MODEL_REV = {"4B": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
             "9B": "c202236235762e1c871ad0ccb60c8ee5ba337b9a"}[SIZE]
from plan import build_tasks, reusable_receipt''')
a=replace(a,'    assert json.loads((path / "SOURCE_RECEIPT.json").read_bytes())["revision"] == MODEL_REV',
'''    if SIZE == "4B":
        assert json.loads((path / "SOURCE_RECEIPT.json").read_bytes())["revision"] == MODEL_REV
    else:
        # Historical 9B directory predates SOURCE_RECEIPT. Do not invent one.
        assert path == Path("/file_storage01/home/weiyu/lanyi/models/Qwen3.5-9B")
        assert (path / "model.safetensors.index.json").is_file()''')
a=replace(a,'assert len(sample) == len({row["id"] for row in sample}) == 16','assert len(sample) == len({row["id"] for row in sample}) == 100')
start=a.index('    tasks = [dict(');end=a.index('    config = ',start)
a=a[:start]+'''    tasks = build_tasks(sample)
    assert tasks == json.loads((sample_file.parent / "task_manifest.json").read_bytes())["tasks"]
    reuse_rows = json.loads((sample_file.parent / "reuse_manifest.json").read_bytes())[SIZE]
    reused = {row["run_id"]: row for row in reuse_rows}
'''+a[end:]
a=replace(a,'    assert tasks == json.loads((reference / "task_manifest.json").read_bytes())["tasks"]',
'''    old_tasks = {t["run_id"]: t for t in json.loads((reference / "task_manifest.json").read_bytes())["tasks"]}
    assert all(t == old_tasks[t["run_id"]] for t in tasks if t["run_id"] in reused)''')
a=replace(a,'changed = {"model", "model_revision"}','changed = {"model", "model_revision", "samples_per_query"}')
a=replace(a,'    (root / "trajectories").mkdir()',
'''    (root / "trajectories").mkdir()
    (root / "verdicts").mkdir()
    for task in tasks:
        if task["run_id"] not in reused:
            continue
        row = reused[task["run_id"]]
        folder = Path(row["trajectory_dir"])
        vp = Path(row["verdict_path"])
        trace_sha = hashlib.sha256((folder / "trajectory.json").read_bytes()).hexdigest()
        assert trace_sha == row["trajectory_sha256"]
        assert hashlib.sha256(vp.read_bytes()).hexdigest() == row["verdict_sha256"]
        reusable_receipt(task, json.loads(vp.read_bytes()), json.loads((folder / "TERMINAL.json").read_bytes()), trace_sha, old_tasks[task["run_id"]])
        (root / "trajectories" / task["run_id"]).symlink_to(folder, target_is_directory=True)
        (root / "verdicts" / (task["run_id"] + ".json")).symlink_to(vp)
    write_json(root / "REUSE_RECEIPT.json", {"read_only_existing": reuse_rows, "reused": len(reused), "new": len(tasks)-len(reused)})''')
a=replace(a,'"reference_job": 184534,','"reference_job": 184534 if SIZE == "9B" else 190085,')
a=replace(a,'        def execute(index, task):\n            server = servers[index % len(servers)]',
'''        def execute(index, task):
            if task["run_id"] in reused:
                return json.loads((root / "trajectories" / task["run_id"] / "TERMINAL.json").read_bytes())
            server = servers[index % len(servers)]''')
a=replace(a,'"rollouts": len(generated), "reused": 0, "generated": len(generated),',
          '"rollouts": len(generated), "reused": len(reused), "generated": len(generated)-len(reused),')
a=replace(a,'        assert len(set(fingerprints)) == 1',
'''        assert len(set(fingerprints)) == 1
        frozen_fingerprints = json.loads((reference / "ACTORS_READY.json").read_bytes())["fingerprints"]
        assert fingerprints == frozen_fingerprints, "Loaded weights fingerprint differs from frozen model"''')
ast.parse(a);(S/'actor.py').write_text(a,encoding='utf-8',newline='\n')

s=(P/'score.py').read_text(encoding='utf-8')
s=replace(s,'assert len(tasks) == 128 and len(questions) == 16','assert len(tasks) == 200 and len(questions) == 100')
s=replace(s,'"questions_with_1_to_6_successes_and_mean_successful_tool_calls_at_least_5"',
          '"questions_with_mixed_success_and_mean_successful_tool_calls_at_least_5"')
s=replace(s,'1 <= sum(row["correct"] for row in group) <= 6','0 < sum(row["correct"] for row in group) < len(group)')
ast.parse(s);(S/'score.py').write_text(s,encoding='utf-8',newline='\n')
(S/'wiki.py').write_bytes((P/'wiki.py').read_bytes())

b=(P/'run.sbatch').read_text(encoding='utf-8')
b=replace(b,'#SBATCH --job-name=dsw-frozen4b-pilot','#SBATCH --job-name=dsw-paired100')
b=replace(b,'DEDUP="$2"','DEDUP="$2"\nexport LEDGER_ACTOR_SIZE="$3"\n[[ "$LEDGER_ACTOR_SIZE" == 4B || "$LEDGER_ACTOR_SIZE" == 9B ]]')
b=replace(b,'ROOT="$STORE/pilot-4b-$SLURM_JOB_ID"','ROOT="$STORE/probe_m1m2/round3/run-$LEDGER_ACTOR_SIZE-$SLURM_JOB_ID"')
b=replace(b,'export LEDGER_PILOT_STORE="$STORE" LEDGER_ACTOR_MODEL="$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"',
'''export LEDGER_PILOT_STORE="$STORE"
if [[ "$LEDGER_ACTOR_SIZE" == 4B ]]; then
    export LEDGER_ACTOR_MODEL="$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
    REFERENCE="$STORE/pilot-4b-190085"
else
    export LEDGER_ACTOR_MODEL="$BASE/models/Qwen3.5-9B"
    REFERENCE="$STORE/pilot-184534"
fi''')
b=replace(b,'"$READY" "$STORE/pilot-184534"','"$READY" "$REFERENCE"')
(S/'run.sbatch').write_text(b,encoding='utf-8',newline='\n')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'source':'/persist_data/home/weiyu/lanyi/projects/deepsearch-world-pilot/actor4b-v1',
        'baseline_hashes':{n:sha(P/n) for n in ['actor.py','score.py','wiki.py','run.sbatch']},
        'extension_hashes':{n:sha(S/n) for n in ['actor.py','score.py','wiki.py','run.sbatch','plan.py']},
        'changes':['100 questions, 2 repetitions, historical seed stride 8 retained',
                   '4B/9B identity selected explicitly; no generation settings changed',
                   '32 preverified existing trajectories/verdicts reused read-only per model',
                   'local grader prompt and request unchanged; mixed-success statistic generalized'],
        'unchanged_generation_workers':8,'optimizer_steps':0}
(S.parent/'runtime_derivation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
