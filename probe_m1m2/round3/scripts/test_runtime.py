import ast
import unittest
from pathlib import Path
S=Path(__file__).resolve().parent
P=S.parent/'private/source'
def literal(tree,name):
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            return ast.literal_eval(node.value)

class RuntimeTests(unittest.TestCase):
    def test_judge_prompt_unchanged(self):
        self.assertEqual(literal(ast.parse((S/'score.py').read_text()),'PROMPT'),
                         literal(ast.parse((P/'score.py').read_text()),'PROMPT'))
    def test_readonly_reuse_and_model_fingerprint_guard(self):
        text=(S/'actor.py').read_text()
        self.assertIn('if task["run_id"] in reused:',text)
        self.assertIn('reusable_receipt(task,',text)
        self.assertIn('assert fingerprints == frozen_fingerprints',text)
        self.assertIn('changed = {"model", "model_revision", "samples_per_query"}',text)
    def test_generation_settings_unchanged(self):
        for fragment in ['"temperature": 1.0, "top_p": 1.0, "top_k": 0, "context": 65536',
                         '"max_tokens_per_call": 10000, "max_actor_calls": 20',
                         '"dtype": "bfloat16", "tensor_parallel": 1, "actors": 4, "max_num_seqs": 32',
                         'factory(root / f"actor{index}", 65536, gpu=gpu, memory=.75)',
                         'ThreadPoolExecutor(max_workers=8)']:
            self.assertIn(fragment,(S/'actor.py').read_text())
            self.assertIn(fragment,(P/'actor.py').read_text())
    def test_judge_launch_unchanged_and_gpu_four(self):
        original=(P/'run.sbatch').read_text();new=(S/'run.sbatch').read_text()
        for flag in ['--tensor-parallel-size 4','--gpu-memory-utilization 0.88','--max-model-len 131072 --max-num-seqs 4 --enforce-eager',
                     '#SBATCH --gres=gpu:4','#SBATCH --cpus-per-task=24','#SBATCH --mem=384G']:
            self.assertIn(flag,new);self.assertIn(flag,original)

if __name__=='__main__':unittest.main()
