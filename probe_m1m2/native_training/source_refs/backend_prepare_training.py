"""Judge a frozen rollout batch and retain each request's native action history."""
import json
import math
import os
import sys
from pathlib import Path

from .batch_shape import BatchShape


def judge_protocol():
    sys.path.insert(0,'/persist_data/home/weiyu/lanyi/projects/新实验/scripts/successful_trajectory_redundancy')
    from phase09_common import official
    return official()


def load_rollout(output):
    shape = BatchShape.from_config(json.loads((output/'config_manifest.json').read_text()))
    if json.loads((output/'ROLLOUT_COMPLETE.json').read_text())['count'] != shape.trajectories:
        raise ValueError('Rollout receipt does not match the frozen batch shape')
    historical = Path('/file_storage01/home/weiyu/lanyi/projects/新实验/reports/BrowseCompPlus_RANDOM100_T1_N4_DUALACTOR')
    gold = {str(x['query_id']):x['gold'] for x in map(json.loads,(historical/'per_run_results.jsonl').read_text().splitlines())}
    queries = {str(x['query_id']):x['question'] for x in json.loads((output/'sample_manifest.json').read_text())['selected']}
    tasks = json.loads((output/'task_manifest.json').read_text())['tasks']
    trajectories = [json.loads((output/'trajectories'/t['run_id']/'trajectory.json').read_text()) for t in tasks]
    shape.verify_groups(t['query_id'] for t in tasks)
    if len({t['run_id'] for t in tasks}) != shape.trajectories:
        raise ValueError('Duplicate rollout identity')
    return tasks, trajectories, queries, gold, shape


def main():
    from vllm import LLM, SamplingParams
    output = Path(os.environ['SMOKE_RUN'])
    derived = Path(os.environ.get('SMOKE_DERIVED_OUTPUT',str(output)))
    derived.mkdir(parents=True,exist_ok=True)
    tasks, trajectories, queries, gold, shape = load_rollout(output)
    ns, identity = judge_protocol()
    llm = LLM(model='/file_storage01/home/weiyu/lanyi/models/Qwen3-32B',tensor_parallel_size=2,
              max_model_len=32768,gpu_memory_utilization=.85,max_num_seqs=16,disable_custom_all_reduce=True)
    rewards = []
    for i,(task,trajectory) in enumerate(zip(tasks,trajectories)):
        terminal = trajectory['metadata']['terminal_status']
        if terminal != 'MODEL_FINAL_STOP':
            rewards.append(0.)
            continue
        final = trajectory['rounds'][-1]['content']
        prompt = ns['create_judge_prompt'](queries[task['query_id']],final,gold[task['query_id']])
        result = llm.chat([[{'role':'user','content':prompt}]],
            SamplingParams(temperature=.7,top_p=.8,top_k=20,max_tokens=4096,seed=2026111000+i),
            chat_template_kwargs={'enable_thinking':False},use_tqdm=False)[0].outputs[0]
        parsed = ns['parse_judge_response'](result.text)
        (derived/(task['run_id']+'-judge.json')).write_text(json.dumps({'text':result.text,'token_ids':list(result.token_ids),
            'finish_reason':result.finish_reason,'parsed':parsed}))
        if result.finish_reason != 'stop' or parsed['parse_error'] or parsed['correct'] is None:
            raise RuntimeError('Unresolved reward judge: '+task['run_id'])
        rewards.append(float(parsed['correct']))
    write_training_batch(derived, tasks, trajectories, rewards, identity, shape)


def write_training_batch(derived, tasks, trajectories, rewards, identity, shape):
    shape.verify_groups(t['query_id'] for t in tasks)
    if len(tasks) != len(trajectories) or len(tasks) != len(rewards):
        raise ValueError('Training batch is missing trajectories or rewards')
    batch = []
    for task,trajectory,reward in zip(tasks,trajectories,rewards):
        group = [r for t,r in zip(tasks,rewards) if t['query_id']==task['query_id']]
        mean = sum(group)/shape.samples_per_query
        std = math.sqrt(sum((r-mean)**2 for r in group)/shape.samples_per_query)
        advantage = (reward-mean)/(std+1e-8)
        segments = []
        for record in trajectory['rounds']:
            if not record.get('response_received'):
                continue
            native = record['token_accounting']
            assert native['exact_prompt_token_ids_equal']
            prompt = native['prompt_token_ids']
            completion = native['completion_token_ids']
            choice = record['raw_response']['choices'][0]
            probabilities = (choice.get('logprobs') or {}).get('content')
            if probabilities is None or len(probabilities) != len(completion):
                raise RuntimeError('Native probability coverage incomplete: '+task['run_id'])
            segments.append({'prompt_ids':prompt,'completion_ids':completion,
                             'vllm_logprobs':[x['logprob'] for x in probabilities]})
        if not segments:
            raise RuntimeError('No actions for '+task['run_id'])
        batch.append({'id':task['run_id'],'query_id':task['query_id'],'reward':reward,'advantage':advantage,'segments':segments})
    (derived/'TRAIN_BATCH.json').write_text(json.dumps({'trajectories':batch,'judge_identity':identity,
       'query_count':shape.query_count,'samples_per_query':shape.samples_per_query,
       'advantage_normalization':'per-query population standard deviation; epsilon 1e-8',
       'loss_reduction':f'trajectory mean of action-token mean; global denominator {shape.trajectories}'}))
    print('BATCH_READY',[(x['id'],x['reward'],x['advantage']) for x in batch],flush=True)


if __name__ == '__main__':
    main()
