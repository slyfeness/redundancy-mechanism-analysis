import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from ledger_grpo.event_price import EventPriceConfig, score_event_prices
from ledger_grpo.sampler_grpo import adapt_sampler_trajectory
from test_native_tool_coordinates import ByteTokenizer, response


def fixture(root, dataset, encode_response=response, *, task='Implement identity', near_repeat=False):
    coding = dataset == "scicode"
    folder = root / "step_01" if coding else root
    folder.mkdir(parents=True, exist_ok=True)
    call_key = "call_id" if coding else "tool_call_id"
    result_key = "model_visible_return" if coding else "observation"
    draft = "def identity(value):\n    return value\n"
    empty_sha = hashlib.sha256(b"").hexdigest()
    read = ("read_code", {}, {"status": "OK", "current_code": "", "code_sha256": empty_sha}) if coding else (
        "search", {"query": "identity data transform algorithm example" if near_repeat else 'fixture'},
        {"results": [{"doc_id": "D1", "corpus_id": "fixture-corpus", "snippet": "Seen text"}]})
    repeat = ('search', {'query':'identity data transform algorithm sample'}, read[2]) if near_repeat and not coding else read
    submit = ("submit_code", {"code": draft}, {"status": "ACCEPTED",
                                               "code_sha256": hashlib.sha256(draft.encode()).hexdigest()}) if coding else (
        "submit_answer", {"answer": "fixture"}, {"accepted": True})
    rounds, events, messages = [], [], [{'role':'user','content':task}]
    prompt = task
    for n, (name, args, observation) in enumerate((read, repeat, submit), 1):
        call = {"id": f"c{n}", "function": {"name": name, "arguments": json.dumps(args)}}
        envelope = f"<tool_call><function={name}>{json.dumps(args)}</function></tool_call>"
        request = {"messages": messages.copy(), "return_token_ids": True, "logprobs": True, "stream": False}
        reply = encode_response(prompt, envelope, [call])
        for label, payload in (("request", request), ("response", reply)):
            for extension in ("body", "json"):
                (folder / f"round_{n:02d}_{label}.{extension}").write_text(json.dumps(payload), encoding="utf-8")
        rounds.append({"round": n, "http_status": 200, "native_capture": {"valid": True},
                       "tool_calls": [{"id": call["id"], "name": name, "arguments": args}]})
        events.append({"event_id": f"E{n:03d}", "batch_id": f"B{n:03d}", "batch_ordinal": 1,
                       call_key: call["id"], "name": name, "arguments": args, result_key: observation})
        content = json.dumps(observation)
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        prompt += f"{envelope}<tool_response>\n{content}\n</tool_response>"
    body = {"trajectory_id": "fixture", "rounds": rounds, "tool_events": events, "stop_reason": "MODEL_FINAL_STOP",
            "final_validity_state": "VALID_FINAL", "final_answer": "fixture"}
    if coding:
        step = {"step_index": 1, "rounds": rounds, "tool_events": events, "stop_reason": "MODEL_SUBMIT_STOP",
                "submitted_code": draft}
        body = {"trajectory_id": "fixture", "steps": [step], "stop_reason": "MODEL_SUBMIT_STOP", "status": "SUBMITTED"}
    (root / "trajectory.json").write_text(json.dumps(body), encoding="utf-8")


class SamplerGRPOTests(unittest.TestCase):
    def test_process_projection_keeps_native_event_and_task_provenance(self):
        with TemporaryDirectory() as tmp:
            for dataset in ('sage','scicode'):
                with self.subTest(dataset=dataset):
                    root = Path(tmp)/dataset
                    fixture(root, dataset)
                    row, _, coverage = adapt_sampler_trajectory(dataset, root, traj_id='sample', task_id='q',
                        outcome=0, tokenizer=ByteTokenizer(), process_frames=[[{'cid':'c1','text':'identity'}]])
                    process, = coverage['process_traces']
                    trace = process['trace']
                    self.assertEqual(trace['task'], 'Implement identity')
                    self.assertEqual(trace['turns'][0]['action']['kind'], 'search' if dataset=='sage' else 'read')
                    self.assertEqual(trace['turns'][0]['observations'][0]['text'], 'Seen text' if dataset=='sage' else '')
                    self.assertEqual([e['event_id'] for e in process['measured_events']], [e['event_id'] for e in row['events']])
                    self.assertEqual(trace['turns'][-1]['observations'], [])

    def test_scicode_process_frames_cannot_reference_a_later_subproblem(self):
        import shutil
        with TemporaryDirectory() as tmp:
            root = Path(tmp)/'source'
            second = Path(tmp)/'second'
            fixture(root, 'scicode', task='Implement alpha')
            fixture(second, 'scicode', task='Implement beta')
            shutil.copytree(second/'step_01', root/'step_02')
            raw_path = root/'trajectory.json'
            raw = json.loads(raw_path.read_bytes())
            second_stage = json.loads((second/'trajectory.json').read_bytes())['steps'][0]
            raw['steps'].append(dict(second_stage, step_index=2))
            raw_path.write_text(json.dumps(raw), encoding='utf-8')
            settings = dict(traj_id='sample', task_id='q', outcome=0, tokenizer=ByteTokenizer())
            frames = [[{'cid':'c1','text':'alpha'}],[{'cid':'c1','text':'beta'}]]
            _, _, coverage = adapt_sampler_trajectory('scicode', root, **settings, process_frames=frames)
            first, second = coverage['process_traces']
            self.assertEqual([s['trace']['task'] for s in (first,second)], ['Implement alpha','Implement beta'])
            self.assertLess(first['trace']['turns'][-1]['turn_id'], second['trace']['turns'][0]['turn_id'])
            self.assertGreater(second['policy_token_offset'], first['policy_token_offset'])
            with self.assertRaisesRegex(ValueError, 'visible task'):
                adapt_sampler_trajectory('scicode', root, **settings, process_frames=list(reversed(frames)))

    def test_both_sampler_formats_flow_into_targeted_token_credit(self):
        with TemporaryDirectory() as tmp:
            for dataset in ("sage", "scicode"):
                with self.subTest(dataset=dataset):
                    path = Path(tmp) / dataset
                    fixture(path, dataset)
                    row, native, coverage = adapt_sampler_trajectory(
                        dataset, path, traj_id=f"{dataset}-1", task_id="q", outcome=0, tokenizer=ByteTokenizer())
                    self.assertEqual(len(native["segments"]), 3)
                    self.assertEqual(coverage["recorded_events"], 3)
                    self.assertEqual(coverage["measured_events"], 2)
                    self.assertEqual([event["label"] for event in row["events"]], [None, "R2b"])
                    first, repeat = row["events"]
                    self.assertEqual(repeat["prior_event_id"], first["event_id"])
                    self.assertTrue(row["recording_complete"])
                    self.assertIn(0, row["response_mask"])
                    peer = dict(row, traj_id=f"{dataset}-2", outcome=1)
                    result = score_event_prices([row, peer], EventPriceConfig(2, 1000, 100))
                    self.assertEqual([debit["event_id"] for debit in result["charged"]], [repeat["event_id"]])
                    start, stop = repeat["event_tokens"]
                    self.assertTrue((result["advantages"][0, start:stop] < -1).all())
                    self.assertTrue((result["advantages"][0, first["event_tokens"][0]:first["event_tokens"][1]] == -1).all())

    def test_raw_transport_mismatch_rejects_the_sample(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, "sage")
            path = root / "round_02_request.json"
            request = json.loads(path.read_bytes())
            request["messages"][0]["content"] = "{}"
            path.write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "request body"):
                adapt_sampler_trajectory("sage", root, traj_id="sample", task_id="q", outcome=0, tokenizer=ByteTokenizer())

    def test_group_with_missing_native_reply_drops_even_if_other_samples_succeed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, "sage")
            path = root / "trajectory.json"
            trace = json.loads(path.read_bytes())
            trace["rounds"][-1]["native_capture"]["valid"] = False
            trace["stop_reason"] = "NATIVE_CAPTURE_INVALID"
            path.write_text(json.dumps(trace), encoding="utf-8")
            row, _, _ = adapt_sampler_trajectory("sage", root, traj_id="sample", task_id="q", outcome=0,
                                                 tokenizer=ByteTokenizer())
            self.assertFalse(row["recording_complete"])
            peer = dict(row, traj_id="peer", outcome=1, recording_complete=True, termination_reason="normal")
            result = score_event_prices([row, peer], EventPriceConfig(2, 1000, 100))
            self.assertEqual(result["metrics"]["invalid_training_groups"], ["q"])
            self.assertEqual(result["charged"], [])

    def test_manifest_command_writes_rows_the_existing_scorer_reads(self):
        from ledger_grpo.cli import main

        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            sources = []
            for index in range(2):
                root = base / f"sample-{index}"
                fixture(root, "sage")
                sources.append({"artifact_root": str(root), "traj_id": f"sample-{index}", "task_id": "q",
                                "outcome": index, "source_trajectory_id": "fixture",
                                "source_trajectory_sha256": hashlib.sha256((root/"trajectory.json").read_bytes()).hexdigest()})
            manifest = base / "verified.jsonl"
            manifest.write_text("\n".join(map(json.dumps, sources)), encoding="utf-8")
            tokenizer = SimpleNamespace(from_pretrained=lambda *_, **__: ByteTokenizer())
            output = base / "prepared"
            args = ["prepare-sampler-grpo", "--dataset", "sage", "--manifest", str(manifest), "--tokenizer", str(base)]
            with patch.dict("sys.modules", {"transformers": SimpleNamespace(AutoTokenizer=tokenizer)}):
                self.assertEqual(main([*args, "--output", str(output)]), 0)
                sources[0]["source_trajectory_sha256"] = "wrong"
                manifest.write_text("\n".join(map(json.dumps, sources)), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "source_trajectory_sha256"):
                    main([*args, "--output", str(base/"mismatch")])
            config = base / "config.json"
            config.write_text('{"group_size":2,"loss_denominator":1000,"median_event_cost":100}', encoding="utf-8")
            scores = base / "scores.json"
            main(["score-events", "--rows", str(output/"EVENT_ROWS.jsonl"), "--config", str(config), "--output", str(scores)])
            self.assertEqual(json.loads(scores.read_bytes())["metrics"]["charged_events"], 1)

    def test_process_artifacts_flow_through_ledger_and_native_event_diagnostics(self):
        from ledger_grpo.cli import main

        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base/'source'
            fixture(root, 'sage')
            manifest, prepared = base/'manifest.jsonl', base/'prepared'
            manifest.write_text(json.dumps({'artifact_root':str(root),'traj_id':'sample','task_id':'q','outcome':0,
                'source_trajectory_id':'fixture','source_trajectory_sha256':hashlib.sha256((root/'trajectory.json').read_bytes()).hexdigest(),
                'process_frames':[[{'cid':'c1','text':'identity'}]]}),encoding='utf-8')
            tokenizer = SimpleNamespace(from_pretrained=lambda *_, **__: ByteTokenizer())
            with patch.dict('sys.modules', {'transformers':SimpleNamespace(AutoTokenizer=tokenizer)}):
                main(['prepare-sampler-grpo','--dataset','sage','--manifest',str(manifest),'--tokenizer',str(base),
                      '--output',str(prepared),'--emit-process-traces'])
            trace = json.loads((prepared/'PROCESS_TRACES.jsonl').read_bytes())
            deltas = base/'deltas.json'
            deltas.write_text(json.dumps({trace['traj_id']:{str(t['turn_id']):{'facts':[]} for t in trace['turns']}}),encoding='utf-8')
            reports, predictions = base/'reports.jsonl', base/'predictions.jsonl'
            main(['analyze','--trajectories',str(prepared/'PROCESS_TRACES.jsonl'),'--deltas',str(deltas),'--output',str(reports)])
            command = ['diagnose-sampler-events','--prepared',str(prepared),'--reports',str(reports),'--output',str(predictions)]
            main(command)
            result = json.loads(predictions.read_bytes())
            self.assertEqual(result['source_traj_id'],'sample')
            self.assertEqual(result['events'][1]['predictions']['R1']['reason'],'exact_repeat_precedence')
            with (prepared/'PROCESS_EVENT_BINDINGS.jsonl').open('ab') as handle:
                handle.write(b' ')
            with self.assertRaisesRegex(ValueError,'prepared native batch'):
                main([*command[:-1],str(base/'rejected.jsonl')])

    def test_bound_score_artifact_runs_one_cpu_update_and_rejects_mismatched_inputs(self):
        from ledger_grpo.cli import main
        from test_hf_pilot_train import LocalCollective, TinyScorer, worker

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "sample"
            fixture(artifact, "scicode")
            row, native, _ = adapt_sampler_trajectory("scicode", artifact, traj_id="a", task_id="q",
                                                      outcome=0, tokenizer=ByteTokenizer())
            rows, batch, config, score = (root/name for name in ("rows.jsonl", "native.json", "config.json", "score.pt"))
            rows.write_text("\n".join(map(json.dumps, (row, dict(row, traj_id="b", outcome=1)))), encoding="utf-8")
            raw = {"trajectories": [native, dict(native, id="b", reward=1)],
                   "event_rows_sha256": hashlib.sha256(rows.read_bytes()).hexdigest(),
                   "policy_snapshot_sha256": "a"*64}
            batch.write_text(json.dumps(raw), encoding="utf-8")
            config.write_text('{"group_size":2,"loss_denominator":1000,"median_event_cost":100}', encoding="utf-8")
            args = ["score-events", "--rows", str(rows), "--config", str(config), "--native-batch", str(batch)]
            self.assertEqual(main([*args, "--output", str(score)]), 0)
            m = worker()
            prepared, inputs = m.load_step_inputs(batch, score)
            self.assertEqual(inputs["policy_snapshot_sha256"], "a"*64)
            model = TinyScorer()
            model.weight = torch.nn.Parameter(torch.zeros(128))
            optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=0.)
            update = m.run_update(prepared, model, optimizer, LocalCollective(),
                                  batch_identity=inputs["native_batch_sha256"], update_index=1)
            self.assertEqual(update["optimizer_steps_this_batch"], 1)
            self.assertGreater(float(model.weight.detach().abs().max()), 0.)

            changed_score = torch.load(score, weights_only=True)
            changed_score["input_binding"]["policy_snapshot_sha256"] = "b"*64
            wrong = root / "wrong.pt"
            torch.save(changed_score, wrong)
            with self.assertRaisesRegex(ValueError, "different policy snapshots"):
                m.load_step_inputs(batch, wrong)
            batch.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "native batch digest"):
                m.load_step_inputs(batch, score)
            with rows.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(ValueError, "event rows"):
                main([*args, "--output", str(root/"rejected.pt")])
