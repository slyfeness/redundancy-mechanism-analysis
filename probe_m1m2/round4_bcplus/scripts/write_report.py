"""Render the short Chinese report from the public numeric receipts."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATS = json.loads((ROOT / "signal_summary.json").read_bytes())
RECEIPT = json.loads((ROOT / "execution_receipt.json").read_bytes())
GROUPS = ("0/8", "1–7/8", "8/8")
MODES = {"any_u": "搜索或打开 / u", "any_u_prime": "搜索或打开 / u′",
         "open_u": "只打开 / u", "open_u_prime": "只打开 / u′"}


def pct(f):
    return "—" if f is None else f"{100*f:.1f}%"


def ratio(value):
    return f'{value["n"]}/{value["denominator"]}（{pct(value["fraction"])}）'


def number(value):
    return "—" if value is None else f"{value:.3f}"


def verdict(value):
    return "待确认" if value is None else "通过" if value else "未通过"


def progress_table():
    rows = ["|进展口径|至少一次进展|有进展的 Stage|每轨迹最小 / 中位 / 最大|答对 / 交卷答错 / 未交卷均值|",
            "|---|---:|---:|---|---|"]
    for mode, label in (("any", "搜索或打开"), ("open", "只打开")):
        progress = STATS["progress"][mode]
        dist = progress["distribution_per_trajectory"]
        values = " / ".join(str(dist[key]) for key in ("min", "median", "max"))
        means = " / ".join(number(progress["by_outcome"][key]["mean"])
                           for key in ("correct", "incorrect_submitted", "no_submission"))
        rows.append(f"|{label}|{ratio(progress['trajectories_with_gain'])}|{ratio(progress['stages_with_gain'])}|{values}|{means}|")
    return rows


def main():
    criteria = STATS["criteria"]
    passed = sum(item["pass"] is True for item in criteria["any"].values())
    if STATS["complete_outcome_groups"] != 50 or STATS["complete_stage_groups"] != 50:
        opening = f"已取得部分信号。完整结果组 {STATS['complete_outcome_groups']}/50，完整过程组 {STATS['complete_stage_groups']}/50。"
    elif passed == 4:
        opening = "按主口径，学习信号达到本轮四条暂定标准。"
    else:
        opening = f"按主口径，信号充足性通过 {passed}/4 条暂定标准。"
    lines = [
        "# LedgerCredit 在 BrowseComp-Plus 上的信号充足性",
        "",
        f"**[已验证]** {opening} 4B 共封存 {STATS['sealed']}/400 条，"
        f"正常交卷 {STATS['submitted']} 条，答对 {STATS['correct']}/{STATS['resolved_outcomes']} 条。",
        "固定切分 664/166，从训练部分抽 50 题，每题 8 次。复用轨迹及本轮测试题均为 0。"
        "采样和本地 gpt-oss-120b 判分沿用 round3。检索与删除作业 183352 的源码哈希和工具定义一致，"
        "使用 Qwen3-Embedding-8B、FAISS、top-5、512 token 片段，只开放 Search。",
        "",
        f"1. **结果信号 [已验证]** 有非零 `A_out` 的题为 {ratio(STATS['outcome_signal']['total'])}。"
        + "，".join(f"{group} 组 {ratio(STATS['outcome_signal'][group])}" for group in GROUPS)
        + "。全错组也可能因交卷状态不同而有结果优势。",
        "",
        "2. **重复调用 [已验证]**",
        "",
        "|口径|总量 / 全部 Stage|落在有结果信号组|落在 ρₓ>0 组|落在全错组|",
        "|---|---:|---:|---:|---:|",
    ]
    for kind, title in (("strict_repeat", "严格重复"), ("repeat_union", "规则并集")):
        repeat = STATS["repetition"][kind]
        lines.append(f"|{title}|" + "|".join(ratio(repeat[key]) for key in
                     ("all", "in_A_out_nonzero_groups", "in_rho_positive_groups", "in_all_wrong_groups")) + "|")
    lines += ["", "各规则次数为 " + "，".join(f"{key} {value['n']}" for key, value in STATS["rules"].items()) + "。",
              "", "3. **重复 Stage 的优势 [已验证]** 差值为重复 Stage 的 A 减同轨迹非重复 Stage 的平均 A。",
              "", "|口径|严格重复平均差 / A=0|规则并集平均差 / A=0|",
              "|---|---|---|"]
    for variant, label in MODES.items():
        entries = STATS["variants"][variant]["repeat_signal"]
        values = [f"{number(entries[key]['repeat_minus_same_trajectory_nonrepeat']['mean'])} / {ratio(entries[key]['zero_advantage'])}"
                  for key in ("strict_repeat", "repeat_union")]
        lines.append(f"|{label}|" + "|".join(values) + "|")
    wrong_repeat = [
        STATS["variants"][mode]["repeat_signal_all_wrong"]["strict_repeat"]
        ["repeat_minus_same_trajectory_nonrepeat"]["mean"] for mode in ("any_u", "any_u_prime")
    ]
    lines += ["", f"全错组内，按主进展口径，严格重复的同轨迹平均差在 u 和 u′ 下分别为 "
              f"{number(wrong_repeat[0])} 和 {number(wrong_repeat[1])}。"]
    lines += ["", "4. **进展 [已验证]** 每题平均 "
              + f"`evidence_docs` {STATS['annotation_counts']['evidence_docs']['mean']:.2f} 篇、"
              + f"`gold_docs` {STATS['annotation_counts']['gold_docs']['mean']:.2f} 篇。"
              + "首次返回任一标注中的新文档计 1，每篇仅计一次。", "", *progress_table(),
              "", "5. **第二路 [已验证]**", "",
              "|口径|至少一个同伴|A_st 非零|全错组 A_st 负 / 零 / 正|全错组 A_st 最小 / 中位 / 最大|",
              "|---|---:|---:|---|---|"]
    for variant, label in MODES.items():
        path = STATS["variants"][variant]["second_path"]
        wrong = path["all_wrong"]
        signs = " / ".join(str(wrong[key]) for key in ("negative", "zero", "positive"))
        values = " / ".join(number(wrong["distribution"][key]) for key in ("min", "median", "max"))
        lines.append(f"|{label}|{ratio(path['comparable'])}|{ratio(path['nonzero'])}|{signs}|{values}|")
    lines += ["", "6. **与普通 GRPO 的差异 [已验证]** 下表是 `|A − A_out| > 0.05` 的策略 token 比例。",
              "", "|口径|0/8|1–7/8|8/8|全部|", "|---|---:|---:|---:|---:|"]
    for variant, label in MODES.items():
        fractions = [pct(STATS["token_comparison"][group]["delta_vs_grpo_gt_005"][variant]["fraction"])
                     for group in (*GROUPS, "all")]
        lines.append(f"|{label}|" + "|".join(fractions) + "|")
    lines += ["", "7. **暂定标准 [已验证]**", "", "|标准|搜索或打开|只打开|", "|---|---|---|"]
    for index, title in enumerate(("非零结果组 ≥30%", "严格重复落在非零结果组 ≥50%", "至少一次进展 ≥50% 且答对轨迹均值更高",
                                   "可比 Stage ≥60%"), 1):
        cells = []
        for progress in ("any", "open"):
            key = next(key for key in criteria[progress] if key.startswith(f"{index}_"))
            row = criteria[progress][key]
            cells.append(f"{pct(row['value'])}，{verdict(row['pass'])}")
        lines.append(f"|{index} {title}|" + "|".join(cells) + "|")
    failures = 400 - STATS["resolved_outcomes"]
    lines += ["", "**局限与待确认问题。** [已验证] 组标准差用总体口径。每条同题其他轨迹取一个权重最大的同伴，"
              "权重须大于 0.5。并行共享推理及非 Stage 的生成 token 保留 A_out。"
              f"有 {STATS['terminal_returns_not_fed']} 次末尾返回未被回填，其追加模型输入成本记 0。"
              f"其中 {STATS['progress']['any']['unfed_stages_with_gain']} 次仍按返回内容计入进展。"
              f"有 {STATS['trailing_open_tool_rounds']} 轮的末尾调用缺少结束标记，按实际生成序列的终点计量。"
              f"无法解析的工具返回 {STATS['unparsed_returns']} 次，未作为进展或严格重复依据。"
              f"未解析的轨迹结果 {failures} 条，过程判断请求与优化器步数均为 0。",
              "[推断] 证据 DocID 命中是取证代理。该检索仅提供 Search，打开口径用于展示信号对工具能力的依赖。"
              "暂定阈值的通过情况来自 50 题的离线信号，训练后的准确率和成本变化仍待验证。",
              "", f"采样和判分作业 `{RECEIPT['gpu']['job_id']}`，耗时 `{RECEIPT['gpu']['runtime']}`。"
              f"首次本地判分 {STATS['new_judge_requests']} 次，失败 {STATS['new_judge_failures']} 次。"
              f"同一判分口径重试 {STATS['judge_retries']} 次，恢复 {STATS['judge_recovered']} 条。"
              "末次重试仅将请求等待上限从 60 秒延长到 240 秒。"
              "逐题分布、组内分母和完整值见 [signal_summary.json](signal_summary.json)。"]
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
