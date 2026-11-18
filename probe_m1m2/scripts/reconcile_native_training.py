"""Refresh only probe outputs after a successful CPU native-input audit."""
import csv
import json
from pathlib import Path

O = Path(__file__).resolve().parents[1]
N = O / 'native_training'
s = json.loads((N / 'native_training_summary.json').read_bytes())
assert s['mask_checks_passed'] == s['native_training_input_checks_passed'] == 20
assert s['model_calls'] == s['optimizer_steps'] == 0
assert s['source_hashes_unchanged'] and s['trajectory_hashes_unchanged']
(O / 'stage_mapping_check.csv').write_bytes((N / 'stage_mapping_check.csv').read_bytes())
summary = json.loads((O / 'structure_summary.json').read_bytes())
summary['previous_scope_mapping_pass'] = summary['mapping_pass']
summary['mapping_pass'] = s['stage_mapping_complete']
summary['mapping_scope'] = 'native CPU preparation and Stage ownership; no actual optimizer run'
summary['native_mask_construction_pass'] = s['mask_checks_passed']
summary['native_training_spans'] = s['training_spans']
summary['native_context_zero_tokens'] = s['mask_zero_context_tokens']
(O / 'structure_summary.json').write_text(json.dumps(summary, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
report = (O / 'REPORT.md').read_text(encoding='utf-8')
needle = '[已验证] 共 89,695 个生成 token'
new = (f"[已验证] CPU 作业 {s['job_id']}：**20/20 原生输入与掩码核对通过，完整 Stage 唯一归属 {s['stage_mapping_complete']}/20**；"
       f"228 次调用合为 {s['training_spans']} 个最大 span，{s['mask_zero_context_tokens']:,} 个 span 内观测/模板位置为 0。"
       "三个样本的原始 prompt IDs 与采样时模板核验 IDs 全部一致；生成文本 decode→encode 的独立诊断见 "
       "[roundtrip_diagnostic.json](native_training/roundtrip_diagnostic.json)，不用于构建训练输入。"
       "[逐轨迹检查](stage_mapping_check.csv) 将掩码正确性与 Stage 规则缺失分开。\n\n")
assert needle in report
report = report.replace(needle, new + needle, 1)
report = report.replace('观测在下一轮原生 prompt 上标 -1，**不是**伪造训练 mask。',
    '新导出的 stage_ids 在实际 span 的零掩码位置标 -1；原样本中的下一轮 prompt 观测坐标另行保留。')
report = report.replace('旧阶段坐标不能直接当 veRL 的 response 轴', '旧生成轴不能直接当含观测间隙的训练 span 轴')
report = report.replace('不提供完整 Agent Loop mask。', '提供逐调用原生 IDs/logprob；mask 由训练 span 构造。')
report += (f"\n[已验证] 本次修订新增 CPU 作业 {s['job_id']}；真实训练输入函数离线通过，"
           "未执行模型 forward、概率重算、反向或优化器。旧验证文件保留历史口径，新结果以 native_training/ 为准。\n")
(O / 'REPORT.md').write_text(report, encoding='utf-8')
print(json.dumps({'mask_pass': 20, 'stage_pass': s['stage_mapping_complete'], 'spans': s['training_spans']}))
