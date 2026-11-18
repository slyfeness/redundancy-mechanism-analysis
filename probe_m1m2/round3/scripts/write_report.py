"""Format final verified counts only; do not infer missing outcomes."""
import json
from pathlib import Path
P=Path(__file__).resolve().parents[1]
s=json.loads((P/'comparison.json').read_bytes())
receipt=json.loads((P/'execution_receipt.json').read_bytes())
def pct(x):return '未知' if x is None else f'{x*100:.2f}%'
def num(x):return '未知' if x is None else f'{x:,.2f}'
lines=['# DeepSearch-World：4B / 9B 配对扩展','',
 '**[已验证]** 100 道相同题，每模型各两条，共 400 条完整记录。复用原 16 题各 32 条；新生成 84 题各 168 条。',
 '历史 16 题包含上一轮已分析的 10 题和另 6 题；因此本轮新增分析 90 题，题数没有减少。',
 '题单沿原哈希排序扩展，seed 保留原步长 8。仅替换模型身份；采样、Search/Open、判分提示和 Stage 成本口径保持一致。','',
 '## 正确率与成本','',
 '|指标|4B|9B|','|---|---:|---:|']
a=s['models']['4B']['overall'];b=s['models']['9B']['overall']
for label,field,formatting in [('封存轨迹','sealed_trajectories',str),('已判分','scored_trajectories',str),
 ('答对','correct',str),('正确率（已有判分）','accuracy',pct),('未判分','missing_outcomes',str),('提交 Final','submitted',str),
 ('总工具调用','total_tool_calls',str),('总生成 token','total_generated_tokens',str),('已知返回 token','known_obs_tokens',str),
 ('返回 token 缺失的 Stage','missing_obs',str)]:
    lines.append(f'|{label}|{formatting(a[field])}|{formatting(b[field])}|')
for label,field in [('平均调用/轨迹','tools_per_trajectory'),('平均生成 token/轨迹','gen_tokens_per_trajectory')]:
    lines.append(f'|{label}|{num(a[field]["mean"])}|{num(b[field]["mean"])}|')
for size in ['4B','9B']:
    records=[q[size] for q in s['per_question'] if q[size]['known']==2]
    lines += ['',f"**[已验证]** {size} 至少一次答对的题数：{sum(q['any_success'] for q in records)}/{len(records)}；ρ_x 取两次回答的样本成功比例。"]
lines += ['', '正常提交的答案由本地 gpt-oss-120b 按冻结口径判分，不是人工金标；未交卷按终止规则记为未成功，不调用 Judge。缺失回执不补零。每题结果及成功轨迹最低成本见 [per_question.json](per_question.json)。','',
 '## 旧样本与新增样本','', '|样本|模型|答对/已判分|正确率|','|---|---|---:|---:|']
for cohort in ['original16','new84']:
    for size in ['4B','9B']:
        r=s['models'][size]['cohorts'][cohort]
        lines.append(f"|{'原16题' if cohort=='original16' else '新84题'}|{size}|{r['correct']}/{r['scored_trajectories']}|{pct(r['accuracy'])}|")
lines += ['', '## 规则可识别的重复','',
 '|规则|4B 次数/调用占比|9B 次数/调用占比|','|---|---:|---:|']
for f in ['S_exact','S_near','S_allseen','S_empty','O_exact','O_samecontent','O_unseen']:
    x=a['rules'][f];y=b['rules'][f]
    lines.append(f"|{f}|{x['calls']} / {pct(x['fraction_of_calls'])}|{y['calls']} / {pct(y['fraction_of_calls'])}|")
x=a['any_repeat'];y=b['any_repeat']
lines.append(f"|去重并集|{x['calls']} / {pct(x['fraction_of_calls'])}|{y['calls']} / {pct(y['fraction_of_calls'])}|")
lines += ['',f"**[已验证]** 重复并集占生成 token 的可归属下界—含共享推理上界：4B {pct(x['generated_fraction_lower_bound'])}—{pct(x['generated_fraction_upper_bound'])}，9B {pct(y['generated_fraction_lower_bound'])}—{pct(y['generated_fraction_upper_bound'])}；占已知返回 token：4B {pct(x['known_obs_fraction'])}，9B {pct(y['known_obs_fraction'])}。"]
lines += ['', '**[已验证]** 并集排除 S_near、O_unseen、S_empty。**[推断]** 规则命中不等于可以安全删除：docid 见过不证明片段完全相同，近似查询也可能改变目标。',
 '成本使用真实记录的 token ID；共享并行推理不重复分摊，末尾返回缺少下一输入时留空。跨模型 token 成本不能直接代替 GPU 耗时。','',
 '20 次预算是 Actor 调用数，不是工具调用数；同轮多工具会使工具总数超过 20。','',
 f"按派发顺序命中的同轮重复 Stage：{s['same_round_rule_matches']}；同轮匹配不证明 agent 已读到那次返回，不能直接用来扣分。",'',
 '## 核对与局限','',
 f"原 20 条的 {s['round2_regression']['stages_compared']} 个 Stage 与 round2 的规则和 token 计数一致：{s['round2_regression']['all_equal']}。",
 f"缺失/异常记录 {len(s['failures'])} 条；外部模型请求 0，训练更新 0。实际新增本地判分请求 {sum(j['new_judge_requests'] for j in receipt['jobs'].values())} 次，失败和重试均为 0。",
 '本轮扩展生成、判分与规则统计。原子条件和首次支持的人工示范仍是 [round2](../round2/REPORT.md) 的 10 题/3 条轨迹，未声称新增题也已逐条人工核验。',
 '每题只有两个 seed；比较是这批配对样本的描述性结果，不当作总体性能或 Judge 质量验收。',
 '运行分段耗时见 [execution_receipt.json](execution_receipt.json)。公开 CSV 的长答案仅保留前 40 词，附截取标记、原字数和哈希；完整答案留在私有存储。原始回答和判分不变，记录见 [publication_check.json](publication_check.json)。',
 '', '完整统计：[comparison.json](comparison.json)；逐轨迹：[trajectory_outcomes.csv](trajectory_outcomes.csv)；逐 Stage：[redundancy_stage_flags.csv](redundancy_stage_flags.csv)。','']
(P/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8',newline='\n')
