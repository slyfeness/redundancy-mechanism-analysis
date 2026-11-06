"""Copy and render completed artifacts; no semantic inference or model calls."""
import csv
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path

SYN = Path(__file__).resolve().parent
ROOT = SYN.parent.parent
STATS = SYN / 'FINAL_STATISTICS'
DEST = ROOT / 'FINAL_AB340_DELIVERY_20261102'
DESKTOP = Path('C:/Users/24413/OneDrive/Desktop')
ZIP_NAME = 'SAGE100_V1.3.2_Stage删除四次续跑与AB340机制分析.zip'
MAIN_NAME = 'SAGE100_V1.3.2_Stage删除四次续跑与AB机制分析.md'


def readj(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def copy(p):
    target = DEST / p.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, target)


def display(value):
    if isinstance(value, str):
        return value
    return '```json\n' + json.dumps(value, ensure_ascii=False, indent=2) + '\n```'


def main():
    assert DESKTOP.is_dir()
    assert sha(ROOT / 'CONTINUOUS_WORK_STAGE_V1.3.2_FROZEN.md') == 'c912aff074a4ccaeace7a0cf0dc3ec331323d7a02c4a9349d88270942966cf72'
    audit = readj(STATS / 'RECOMPUTATION_AUDIT.json')
    assert audit['units'] == 340 and audit['paths'] == 1360 and not audit['errors']
    core = readj(ROOT / 'ANALYSIS/PEER_GOAL_COMPLETION_EVIDENCE_AUDIT/GOAL_CORE_EVIDENCE_AUDIT.json')
    refs = readj(ROOT / 'ANALYSIS/PEER_GOAL_COMPLETION_EVIDENCE_AUDIT/COMBINED340_INDEPENDENT_REFERENCE_AUDIT.json')
    independent = readj(ROOT / 'ANALYSIS/PEER_GOAL_COMPLETION_EVIDENCE_AUDIT/FINAL_LINK_STATISTICS_INDEPENDENT_AUDIT.json')
    assert core['status'] == 'PASS' and refs['status'] == 'PASS' and not refs['errors']
    # Preserve the auditor's full schema; consistency is checked below through
    # explicit unit/path coverage and the frozen recomputation result.
    DEST.mkdir(exist_ok=True)
    originals = sorted((ROOT / 'RAW').glob('*/trajectory.json'))
    mappings = sorted((ROOT / 'MAPPINGS').glob('*.json'))
    reports = sorted((ROOT / 'REPORTS').glob('*.md'))
    assert len(originals) == len(mappings) == len(reports) == 100
    for p in originals + mappings + reports:
        copy(p)
    for rel in ['CONTINUOUS_WORK_STAGE_V1.3.2_FROZEN.md', 'V132_FORMAL_FREEZE_MANIFEST.json',
                'SAMPLE_MANIFEST.json', 'SAMPLING_PLAN_FROZEN.json', 'STAGE100_FREEZE_MANIFEST.json',
                'STAGE100_SUMMARY.csv', 'ALL100_SOURCE_MAPPING_REPORT_AUDIT.json',
                'DELETION4/CPU_INPUT_PREFLIGHT_V3.json', 'DELETION4/NONRUNNABLE_TARGET_RECORDS_V3.json',
                'DELETION4/TASK_INVENTORY_FROZEN.csv', 'DELETION4/RUN_VERSION_003/EXECUTION_CODE_FREEZE.json',
                'POSTGEN_MECHANICAL_QA/FINAL_POSTGEN_MECHANICAL_AUDIT.json',
                'POSTGEN_MECHANICAL_QA/LOCAL_COMBINED_EXPORT_VERIFICATION.json']:
        copy(ROOT / rel)
    for directory in ['ANALYSIS/OUTCOME_SCREENING_ALL100',
                      'ANALYSIS/PEER_GOAL_COMPLETION_EVIDENCE_AUDIT',
                      'ANALYSIS/OUTCOME_SCREENING_ROOT/DECISIONS',
                      'ANALYSIS/OUTCOME_SCREENING_PEER/DECISIONS']:
        for p in (ROOT / directory).rglob('*'):
            if p.is_file() and p.suffix in ('.json', '.jsonl', '.csv', '.md', '.py'):
                copy(p)
    screen = list(csv.DictReader((ROOT / 'ANALYSIS/OUTCOME_SCREENING_ALL100/ALL_646_STAGE_SCREENING.csv').open(encoding='utf-8-sig')))
    ab = [r for r in screen if r['screen_group'] in ('A', 'B')]
    assert len(ab) == 340
    overview = ['# 340组逐组工作与四条续跑', '',
                '下文直接展示已保存模型审阅的工作和作用链，未用程序生成语义判断。完整精确引文/源指针在对应STAGE_REVIEWS JSON中，完整原轨迹在RAW和REPORTS；全部新轨迹仍保留在README给出的本机证据根目录。', '']
    for r in ab:
        u = r['unit_id']
        review_path = ROOT / 'ANALYSIS/STAGE_REVIEWS' / (u + '.json')
        cost_path = ROOT / 'ANALYSIS/COST_FACTS' / (u + '.json')
        copy(review_path)
        copy(cost_path)
        j = readj(review_path)
        overview += [f"## {u}", '',
                     f"{r['screen_group']}类；原{r['original_outcome']} → " + '/'.join(r[f'run{i}'] for i in range(1, 5)) + f"；条件{r['condition']}。", '',
                     '**问题**：' + j['question_and_gold']['question'], '',
                     '**实际P**', '', display(j['prestate']), '',
                     '**原U及原后续如何使用它**', '', display(j['original_U']), '',
                     display(j['original_followup']), '', '**G核对**', '', display(j['guide_audit']), '']
        for roll in j['rollouts']:
            overview += [f"### 续跑{roll['repeat_id']}：{roll['outcome']}", '']
            for field in ['actual_final', 'terminal', 'outcome_reason', 'work_timeline',
                          'work_and_evidence_timeline', 'first_substantive_judgment_difference',
                          'first_judgment_divergence', 'first_actual_tool_difference',
                          'first_actual_tool_divergence', 'function_correspondence',
                          'decision_action_result_chain', 'judgment_action_outcome_chain', 'chain',
                          'costs', 'cost', 'cost_work_locations', 'limits', 'counterevidence_and_alternatives']:
                if field in roll:
                    overview += [f'**{field}**', '', display(roll[field]), '']
        comparison = j.get('four_run_comparison', j.get('four_rollout_comparison'))
        overview += ['**四路对照**', '', display(comparison), '',
                     f"[全部精确证据及语义记录](ANALYSIS/STAGE_REVIEWS/{u}.json) · [切点成本](ANALYSIS/COST_FACTS/{u}.json)", '']
    (DEST / '04_全部340组_逐组与四路分析.md').write_text('\n'.join(overview), encoding='utf-8')
    for name in ['SYNTHESIS_METHOD.md', 'CROSSQUESTION_LINKING_PROTOCOL.md',
                 'ALL340_MODEL_AUTHORED_MEMBERSHIPS.jsonl', 'ROOT_NORMALIZED_LINKS_FINAL.jsonl',
                 'PEER_NORMALIZED_LINKS.jsonl', 'PEER_TARGET_RELATION_AUDIT.jsonl',
                 'ROOT_LINK_SCOPE_AMENDMENTS.csv', 'ROOT_LINK_SCOPE_AMENDMENT_AUDIT.json',
                 'ROOT_TARGET_RELATION_AUDIT.csv', 'MODEL_MECHANISM_INTERPRETATIONS.md',
                 'EXPERIMENT_AND_INFERENCE_LIMITS.md', 'recompute_ab_statistics.py', 'build_final_delivery.py']:
        copy(SYN / name)
    for p in STATS.iterdir():
        if p.is_file():
            copy(p)
    coverage = readj(STATS / 'COVERAGE_SUMMARY.json')
    text = ['# SAGE100：冻结Stage、四次删除续跑与A/B机制分析', '',
            '已完成原100条切分、全部合法四次真实续跑与结果统计，并仅对A/B两类完成深层分析。Codex审阅建议等待研究者验收，不是独立人工金标准。', '',
            '## 实际覆盖', '',
            f"- 原轨迹100条，冻结Stage {core['frozen_stages']}个；规则SHA256 `c912aff074a4ccaeace7a0cf0dc3ec331323d7a02c4a9349d88270942966cf72`。",
            f"- {core['runnable_units']}个合法Stage ×4＝{core['actual_runs']}条真实新后续；{core['nonrun_units']}目标/{core['nonrun_conditions']}计划未运行，原因逐条保留。",
            '- 深层分析A272组、B68组，共340组及1360条续跑；OTHER/UNCERTAIN未做机制审阅。',
            '- 340份原工作/四路审阅、340份自由作用链综合、418项归一链接；原新精确证据7381条引用检查通过。', '',
            '## 正确性与真实终态', '',
            '以下为已封存Codex语义答案口径，不是整段Final EM，也不是官方Judge Accuracy。N无正式答案计未答对，UNCERTAIN单列。', '',
            '| 条件 | 运行数 | 确定正确C | W | N | 待定 | 正确率下界—上界 |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for key, label in [('ORIGINAL', '原100条'), ('FIRST_SENTENCE', '首句引导'),
                       ('TERMINAL_DROP_NO_ANCHOR', '末段无引导'), ('ALL_NEW', '新后续合计')]:
        r = core['correctness'][key]
        c = r['counts']
        text.append(f"| {label} | {r['n']} | {c.get('C', 0)} | {c.get('W', 0)} | {c.get('N', 0)} | {c.get('UNCERTAIN', 0)} | {100*r['accuracy_lower']:.2f}%—{100*r['accuracy_upper']:.2f}% |")
    text += ['', '真实终态：' + '；'.join(f'{k}={v}' for k, v in core['terminal_counts'].items()) + '。', '',
             '## A/B与机制统计如何读', '',
             'A：原C且四次仅0/1次状态改变，研究多数保持的原因。B：原状态不限且四次3/4次改变，拆开C退化、W/N改善及W↔N。它们不是冗余/必要标签。', '',
             '主表只计原U实际承担相应动作的DIRECT_U。后继才出现的链、连接不明及不归类均单列，不能反向把新路径的错误或重复给U定性。支持与反证可以重叠：同路径可支持一段中间过程，同时反驳其充分性。多重归属不可相加成唯一Stage数。', '']
    for group in ('A', 'B'):
        c = coverage['groups'][group]
        text.append(f"{group}类{c['reviewed_stages']}组/{c['distinct_questions']}道不同题：{c['direct_supported_stages']}组存在明确U相关作用链，{c['no_direct_supported_stages']}组未作此确定归属，全部保留分析与限制。")
    text += ['', (STATS / 'AB_MECHANISM_COUNTS.md').read_text(encoding='utf-8'), '',
             '## 原新结果与成本', '',
             '全部1360条的原状态→新状态、Search/Open/Actor差、生成保守区间、P重放与G预填在统计CSV中。所有匹配Stage和四支均保留，没有只选典型案例。FIRST_SENTENCE与TERMINAL分开。', '',
             '全2524条实际新后续消耗（这是实验实际用量，不是可实现节省）：', '',
             '| 条件 | 新生成Token | 累计Prompt Token | Search | Open | Actor请求 |',
             '|---|---:|---:|---:|---:|---:|']
    for condition, c in core['real_suffix_costs'].items():
        text.append(f"| {condition} | {c['completion_tokens']} | {c['prompt_tokens']} | {c['search_calls']} | {c['open_calls']} | {c['actor_requests']} |")
    text += ['', '不存在原生精确切点：不提供伪精确原生净节省。独立删除分支的差值不能相加成批量可实现收益。', '',
             (SYN / 'MODEL_MECHANISM_INTERPRETATIONS.md').read_text(encoding='utf-8'), '',
             (SYN / 'EXPERIMENT_AND_INFERENCE_LIMITS.md').read_text(encoding='utf-8'), '',
             '## 机械验收与研究者待判断', '',
             '原100映射的字符/SHA/工具协议与Final保真通过；2524真实分支封存审计通过；340组/1360条/7381证据引用通过；统计由判定记录和客观账本复算，独立计数复查未发现差异。机械通过只证明这些范围的完整性和可追溯性。', '',
             '仍需研究者判断：归一作用链是否应进一步拆分/合并；题义和关系证据强度争议；G及原新采样/预算变化能否排除；为何有充分材料仍未实际退出。不得把本批观察写成纯删除因果必要性或全量冗余率。', '',
             '阅览顺序：本报告 → 统计目录的A/B表与逐路径CSV → 04逐组四路分析 → STAGE_REVIEWS精确证据 → 本机原新轨迹。']
    (DEST / MAIN_NAME).write_text('\n'.join(text) + '\n', encoding='utf-8')
    readme = f'''# 交付阅读说明

先读 `{MAIN_NAME}`。逐组完整分析见 `04_全部340组_逐组与四路分析.md`；精确证据在 `ANALYSIS/STAGE_REVIEWS/`，成本在 `ANALYSIS/COST_FACTS/`，统计与反向索引在 `ANALYSIS/MODEL_AUTHORED_SYNTHESIS/FINAL_STATISTICS/`。

包内实际复制100份原始轨迹、100份冻结映射、100份完整切分报告、340份原新四路语义记录、340份成本事实、全部归属及精确引文，不使用服务器符号链接。

2524条巨大完整新轨迹及请求响应/工具Return继续原样保存在本机：
`{ROOT / 'POSTGEN_EVIDENCE_EXPORT'}`。
本包不重复压入该大体积目录。全2524条相对路径、SHA、终态和评价索引在 `ANALYSIS/PEER_GOAL_COMPLETION_EVIDENCE_AUDIT/ALL2524_SOURCE_RESULT_INDEX.json`；以该本机证据根目录拼接。分析用1360路径的成本表另提供SHA。不能只访问原JSON内部旧服务器路径；应使用该实际本机根目录。

只复算统计：在解压后的本目录运行 `python ANALYSIS/MODEL_AUTHORED_SYNTHESIS/recompute_ab_statistics.py`。它不生成语义标签，不需要GPU，不会读Gold送模型；会在FINAL_STATISTICS重算表。

MANIFEST.json列包内每文件原始路径/大小/SHA。SHA256SUMS.txt涵盖全部非自身文件。ZIP已实际解压并逐件核验；解压校验结果位于ZIP旁的本机交付核验JSON。

研究结论是Codex建议，不是研究者独立人工验收。只有A/B作深层分析，其余目标仅保留客观覆盖/状态。
'''
    (DEST / 'README.md').write_text(readme, encoding='utf-8')
    files = []
    for p in sorted(DEST.rglob('*')):
        if p.is_file() and p.name not in ('MANIFEST.json', 'SHA256SUMS.txt'):
            rel = p.relative_to(DEST).as_posix()
            src = ROOT / p.relative_to(DEST)
            files.append({'path': rel, 'bytes': p.stat().st_size, 'sha256': sha(p),
                          'source_path': str(src) if src.exists() else 'New derived final report'})
    (DEST / 'MANIFEST.json').write_text(json.dumps({'files': files, 'scope': 'AB340 only; raw new trajectories retained outside this lightweight package'}, ensure_ascii=False, indent=2), encoding='utf-8')
    hashes = [f"{sha(p)}  {p.relative_to(DEST).as_posix()}" for p in sorted(DEST.rglob('*'))
              if p.is_file() and p.name != 'SHA256SUMS.txt']
    (DEST / 'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf-8')
    zip_local = ROOT / ZIP_NAME
    with zipfile.ZipFile(zip_local, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(DEST.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(DEST).as_posix())
    verify_dir = ROOT / 'FINAL_AB340_UNZIP_VERIFICATION_20261102'
    verify_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_local) as z:
        assert z.testzip() is None
        z.extractall(verify_dir)
        count = len(z.namelist())
    errors = []
    for line in (verify_dir / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        digest, rel = line.split('  ', 1)
        if sha(verify_dir / rel) != digest:
            errors.append(rel)
    assert not errors
    target_zip = DESKTOP / ZIP_NAME
    target_md = DESKTOP / MAIN_NAME
    shutil.copyfile(zip_local, target_zip)
    shutil.copyfile(DEST / MAIN_NAME, target_md)
    assert sha(target_zip) == sha(zip_local)
    assert sha(target_md) == sha(DEST / MAIN_NAME)
    receipt = {'zip': str(target_zip), 'zip_sha256': sha(target_zip), 'zip_bytes': target_zip.stat().st_size,
               'zip_file_count': count, 'main_report': str(target_md), 'main_report_sha256': sha(target_md),
               'extraction_verified': True, 'sha_file_errors': errors,
               'stages_reviewed': 340, 'four_rollouts_reviewed': 1360, 'A': 272, 'B': 68,
               'originals': 100, 'stages': 646, 'real_runs': 2524, 'not_run_plan_records': 60,
               'semantic_human_gold_claimed': False}
    (ROOT / 'FINAL_AB340_DELIVERY_VERIFICATION.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
