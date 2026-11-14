"""Start the frozen P0 services and run the paired event schedule in one job."""

import argparse
import json
import os
from pathlib import Path
import secrets
import sys

from hf_pilot_controller import run_phase
from frozen_event_calibration import read_executions, remaining_cases
from isolate_runtime import install_runtime_isolation, ipc_path_lengths
from process_preflight import write
from run_event_deletion_plan import load_schedule, run_plan, schedule_lanes


def run_calibration(root, services, probe, execute, planned_branches):
    state = {'state': 'running', 'planned_branches': planned_branches, 'optimizer_steps_committed': 0}
    phases = []

    def phase(name, callback):
        return run_phase(root, state, phases, name, callback)

    try:
        phase('services_ready', lambda: services.start(.75, None))
        def confirm_actors():
            probes = services.actors.all(probe)
            if (len(probes) != len(services.servers) or not probes
                    or any(p['token_ids'] != probes[0]['token_ids'] for p in probes)):
                raise ValueError('Actor generation probes disagree')

        phase('actor_probes', confirm_actors)
        actors = [(actor.url, actor.folder) for actor in services.servers]
        result = phase('paired_continuations', lambda: execute(actors, services.port))
        if result['completed_branches'] != planned_branches:
            raise ValueError('planned branch coverage is incomplete')
    except BaseException:
        state.update(state='failed', failure_phase=state['phase'])
        raise
    finally:
        try:
            phase('services_shutdown', services.close)
        except BaseException:
            if state['state'] != 'failed':
                state.update(state='failed', failure_phase='services_shutdown')
                raise
        finally:
            if state['state'] != 'failed':
                state.update(state='completed', completed_branches=result['completed_branches'])
            write(root/'STATUS.json', state)
    write(root/'RESULT.json', dict(state, **result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('plan', 'audit', 'rollout', 'model', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--resume-from', type=Path, action='append', default=[])
    args = parser.parse_args()
    plan, audit, rollout, model = (getattr(args, name).resolve(strict=True) for name in ('plan','audit','rollout','model'))
    root = args.output.resolve()
    schedule, plan_sha, audit_sha = load_schedule(plan, audit, rollout)
    prior = read_executions(args.resume_from, schedule, plan_sha, audit_sha)
    schedule = remaining_cases(schedule, prior)
    if not schedule:
        parser.error('the frozen schedule has already completed')
    for name in ('tokenizer.json','chat_template.jinja','config.json','model.safetensors.index.json'):
        if not (model/name).is_file():
            raise ValueError(f'frozen model file is missing: {name}')
    store = Path(os.environ['LEDGER_PILOT_STORE']).resolve()
    if root == store or not root.is_relative_to(store):
        raise ValueError('calibration output must be under the independent pilot storage root')
    backend = Path(os.environ['LEDGER_HF_BACKEND_SOURCE']).resolve(strict=True)
    sys.path.insert(0, str(backend))
    from src.stability_controller import Services, read_hardware
    from src.resident_controller import generated_probe
    from src.rollout import runtime

    runtime(root)  # Resolve the same frozen Phase06/10 module imports as the branch worker.
    from phase10_actor import Recorder
    from phase06_runtime import make_native_agent

    if not all(callable(item) for item in (Services, generated_probe, Recorder, make_native_agent)):
        raise ValueError('frozen service or recorder entry point is unavailable')
    job = os.environ['SLURM_JOB_ID']
    ipc = ipc_path_lengths(os.environ['TMPDIR'], os.environ['VLLM_RPC_BASE_PATH'], job)
    root.mkdir(mode=0o700, exist_ok=False)
    lanes = schedule_lanes(schedule, 4)
    preflight = {'plan_sha256': plan_sha, 'audit_sha256': audit_sha, 'branches': len(schedule),
                 'branches_by_actor': [sum(map(len, lane)) for lane in lanes], 'ipc_path_bytes': ipc,
                 'backend_imports_ok': True, 'preflight_only': args.preflight_only}
    if prior:
        preflight['reused_branches'] = len(prior)
        preflight['cases_to_run'] = sorted({row['case_id'] for row in schedule})
    write(root/'PREFLIGHT.json', preflight)
    print(json.dumps(preflight), flush=True)
    if args.preflight_only:
        return

    os.chdir(root)
    install_runtime_isolation()
    snapshots = root/'policy-snapshots'
    snapshots.mkdir()
    secret, gate = secrets.token_urlsafe(32), root/'actor-gate'
    os.environ.update(OCCAM_ACTOR_ADMIN=secret, OCCAM_ACTOR_GATE=str(gate), OCCAM_SNAPSHOT_DIR=str(snapshots),
                      LEDGER_ACTOR_MODEL=str(model))
    _, hardware = read_hardware()
    write(root/'HARDWARE.json', hardware)
    devices = os.environ['CUDA_VISIBLE_DEVICES'].split(',')
    services = Services(root/'services', devices, secret, gate)
    run_calibration(root, services, generated_probe,
                    lambda actors, port: run_plan(schedule, plan_sha, audit_sha, rollout=rollout, audit=audit,
                                                  model=model, actors=actors, mcp_port=port, output=root/'branches'),
                    len(schedule))


if __name__ == '__main__':
    main()
