"""Count-only report for the M3–M7 variants and the no-update HF smoke."""

from argparse import ArgumentParser
import json
from pathlib import Path

MODES = {"v1": "v1", "kappa_0_3": "κ=0.3", "beta_c_0": "β_c=0"}
GROUPS = {"all_correct": "全对", "mixed": "有对有错", "all_wrong": "全错"}


def read(path):
    return json.loads(path.read_bytes())


def number(value):
    return f"{value:.8g}" if value is not None else "—"


def pct(n, d):
    return f"{100*n/d:.2f}%" if d else "—"


def render(data, smoke):
    lines = [
        "# M3–M7 离线验收",
        f"- round4 {data['input_trajectories']} 条｜可用 {data['trajectories']} 条、{data['questions']} 题、{data['units']} 个单元｜不足 8 条的组 {data['incomplete_groups']}。",
        f"- 全部训练题排除 {data['excluded_questions_all']} 题（含零断言 {data['excluded_zero_all']}）｜round4 排除 {data['excluded_questions_round4']} 题｜测试题读取 {data['test_read']}。",
        f"- 严格 N3 {data['strict_units']} 单元｜与冻结 M2 严格标记差异 {data['strict_changed_vs_frozen_m2']} 单元。",
        f"- N2 字面重复诊断覆盖 {data['N2_covered']}，标记 {data['N2_exact']}｜D 诊断覆盖 {data['D_covered']}｜诊断计分 0。",
        f"- 一组前向和反向 {smoke['group_size']} 条、{smoke['records']} 个 native span、{smoke['action_tokens']} 个生成 token。",
        f"- 有限 loss {number(smoke['loss'])}｜有限梯度范数 {number(smoke['grad_norm'])}"
        f"｜掩码外直接梯度元素 {smoke['off_mask_grad_elements']}｜非零生成位置梯度 {smoke['nonzero_action_grad_positions']}。",
        f"- 优化器步 {smoke['optimizer_steps']}｜保存参数 {smoke['saved_model_parameters']}"
        f"｜参数探针变化 {smoke['changed_parameter_probes']}｜KL {smoke['kl_coefficient']:.0f}。",
        "",
        "| 试算 | 第一路守恒最大误差 | 符号翻转 | NaN/Inf |",
        "|---|---:|---:|---:|",
    ]
    for mode, label in MODES.items():
        group = data["formula"][mode]
        lines.append(f"| {label} | {group['conservation_max']:.3g} | {group['sign_flips']} | {group['nonfinite']} |")
    lines += ["", "| 试算 | 组类 | 题数 | 单元 | A_st=0 占单元 | 其中无同伴 | 其中效用相等 |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for variant, label in MODES.items():
        for key, name in GROUPS.items():
            group = data["formula"][variant]["groups"][key]
            zero = group["no_peer"] + group["equal_peer"]
            lines.append(f"| {label} | {name} | {group['groups']} | {group['units']} | {zero} ({pct(zero,group['units'])})"
                         f" | {group['no_peer']} ({pct(group['no_peer'],zero)}) | {group['equal_peer']} ({pct(group['equal_peer'],zero)}) |")
    lines += ["", "| 试算 | 组类 | 严格重复单元数 | 严格重复平均 A | 非重复且无进展单元数 | 非重复且无进展平均 A |",
              "|---|---|---:|---:|---:|---:|"]
    for variant, label in MODES.items():
        for key, name in GROUPS.items():
            group = data["formula"][variant]["groups"][key]
            repeat, other = group["repeat"], group["nonrepeat_no_progress"]
            lines.append(f"| {label} | {name} | {repeat['n']} | {number(repeat['mean_A'])}"
                         f" | {other['n']} | {number(other['mean_A'])} |")
    lines += ["", "| 试算 | 组类 | 指标 | P0 | P5 | P25 | P50 | P75 | P95 | P100 |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for variant, label in MODES.items():
        for category, title in GROUPS.items():
            for name, values in data["formula"][variant]["groups"][category]["quantiles"].items():
                lines.append(f"| {label} | {title} | {name} | " + " | ".join(map(number, values or [None] * 7)) + " |")
    lines += ["", f"- 私有逐步核验样例 {data['examples']} 条。"]
    return "\n".join(lines) + "\n"


def main():
    parser = ArgumentParser()
    for arg in ("counts", "smoke", "report"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    args.report.write_text(render(read(args.counts), read(args.smoke)), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
