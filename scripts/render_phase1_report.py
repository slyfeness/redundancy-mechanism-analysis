"""Render a Phase 1 acceptance report using only sanitized aggregate receipts."""

import argparse
from collections import Counter
import json
from pathlib import Path
from xml.etree import ElementTree


def render(folder):
    def load(name):
        return json.loads((folder / f"{name}.json").read_bytes())

    manifest = load("run_manifest")
    metadata = load("metrics")
    acceptance = load("acceptance")
    reward = load("reward_preview_summary")
    test = ElementTree.parse(folder / "test_results.xml").find("testsuite").attrib
    inventory = load("inventory")
    totals = Counter()
    for values in metadata["splits"].values():
        totals.update(values)
    judge = acceptance["judge"]
    verification = acceptance["engineering"]
    inventory_results = inventory["result_counts"]
    lines = [
        "# 冗余 Judge 第一期运行与验收",
        "",
        f"工程状态 `{verification['status']}`。Judge 质量状态 `{judge['status']}`。",
        f"全量源码 `{manifest['code_commit']}`，本地模型 `{manifest['freeze']['model_version']}`。",
        f"清点覆盖 {inventory['expected_questions']} 题、{inventory['expected_trajectories']} 条自然轨迹。"
        f"封存 {metadata['receipt_count']} 份回执，成功解析 {metadata['annotation_count']} 条，"
        f"有 {totals['failed']} 条未产出摘要。",
        f"独立历史结果为 C {inventory_results['C']}、W {inventory_results['W']}、"
        f"N {inventory_results['N']}、未定 {inventory_results['UNCERTAIN']}。",
        "",
        "| 数据集划分 | 题数 | 轨迹 | Stage | 工具调用 | 并行组 | 解析异常记录 | 标注异常记录 | 标签弃权 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split, row in metadata["splits"].items():
        keys = ("questions", "trajectories", "stages", "tool_events", "parallel_groups",
                "parse_anomalies", "annotation_errors", "label_abstentions")
        lines.append("| " + " | ".join([split, *(str(row.get(k, 0)) for k in keys)]) + " |")
    lines += [
        "",
        f"原生 Token 通过 {totals['token_verified']} 条。并行组的各调用及原始返回分别保存。"
        f"独立逐条核查了 {verification['native_proof']['counts'].get('verified_evidence_quotes', 0)} "
        "条工具原文引文。未回注、预算停止、解析异常和标注过错的分母均保留。",
        f"缓存重放比较 {verification['replay']['compared']} 个产物，状态 "
        f"`{verification['replay']['status']}`。原来源和已列旧资产的哈希结果见 acceptance.json。",
        "",
        "## Judge 质量",
        "",
        "| 标签 | 审计集事件 | 自动阳性 | 自动弃权 | 可计价候选 | 计划人工单元 | 已完成人工核对 | 批准 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for label, row in judge["labels"].items():
        planned = row["review_plan"] or {"planned": 0, "settled": 0}
        values = [label, row["events"], row["automatic_decisions"].get("positive", 0),
                  row["automatic_decisions"].get("abstain", 0), row["automatic_priceable_events"],
                  planned["planned"], planned["settled"],
                  "已批准" if label in judge["approved_labels"] else "未批准"]
        lines.append("| " + " | ".join(map(str, values)) + " |")
    lines += [
        "",
        "人工精确率、召回率、必要动作误标率及其 95% 区间在独立审核完成后计算。"
        f"本次同源 TOKEN15 轨迹交集为 {inventory['legacy_mapping']['exact_source_hash_matches']}，"
        "B⁺ 被标记率和 B⁺ 污染率无可估分母。保护挑战类别的候选数量见 metrics.json。",
        "保护任务共 40 个审核单元，来自首次必要取证候选。其余五类在审计集的自动候选池为空，"
        "当前挑战证据不足以估计这些类别的误标率。",
        "R2a 只输出诊断。自动候选、弃权和异常的脱敏事实见 failure_cases.jsonl。"
        "人工假阳性案例待复核。原始审核包和逐项产物的访问位置见 data_access.md。",
        "",
        "## 奖励、重放与测试",
        "",
        f"固定开发集取 {manifest['cost_reference']['sample_size']} 个可计量串行工具 Stage，"
        f"事件成本中位数为 {manifest['cost_reference']['median']}。默认预览完成 "
        f"{reward['computed_groups']} 个同题组、{reward['computed_trajectories']} 条轨迹，"
        f"发生 {reward['applied_event_debits']} 个实际扣分。纯结果对照完成 "
        f"{reward['outcome_only_control']['groups']} 个组。",
        f"有效取证充分度覆盖 {totals['valid_grounding']} 条轨迹。默认预览排除的原因保存在 "
        "reward_preview_summary.json。纯结果对照用于观察缺少有效取证充分度的情况。",
        f"Python 测试 {test['tests']} 项，失败 {test['failures']}、错误 {test['errors']}。"
        "测试包括合成记录与本地 HTTP 协议夹具。真实 Judge 运行和 Slurm 回执见 execution.log。",
        "运行入口是 `inspect`、`annotate --split dev --limit-questions 5`、"
        "`annotate --split all --resume`、`export-review`、`audit`、`reward-preview`。"
        "完整命令见 README 和 REPRODUCE。",
        "",
        "本阶段共执行 0 次策略优化器更新。正式训练批准为空，独立质量审核继续待办。",
    ]
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    render(parser.parse_args().folder)


if __name__ == "__main__":
    main()
