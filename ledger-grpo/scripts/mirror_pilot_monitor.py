"""Read-only, finite SFTP mirror of one Ledger pilot's small status artifacts.

Uses the system sftp executable and existing SSH authentication in BatchMode.
No credential files are inspected, no remote shell command is executed, and no
job is submitted/cancelled. Default is one snapshot; --watch-seconds is bounded.
--offline-dir exercises the same validation/rendering without any connection.

Raw downloads are retained under snapshots/. Only allowlisted scalar summaries
and schema-sanitized events enter HTML. Missing files never imply zero updates.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
import uuid

from ledger_grpo.observability import read_events, render_monitor, summarize_events


ARMS = ("P0", "resume_base", "outcome", "ledger", "trajectory", "targeted", "shuffled", "uniform")
FILES = (
    "STATUS.json", "metrics.jsonl", "PHASES.json", "RESULT.json", "PAIRED_COMPARISONS.json",
    "scored/SCORE_COMPARISON.json",
) + tuple(path for arm in ARMS for path in (f"EVAL-{arm}.json", f"{arm}/metrics.jsonl", f"{arm}/STATUS.json"))
EVENT_FILES = ("metrics.jsonl",) + tuple(f"{arm}/metrics.jsonl" for arm in ARMS)
REMOTE_BASE = "/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/runs"
MAX_BYTES = 20_000_000


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _json_write(path, value):
    _atomic(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))


def _read_json(path):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        return None


def _code(value, default="unknown"):
    return value if isinstance(value,str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}",value) else default


def _number(value):
    return value if type(value) in (int,float) and math.isfinite(value) else None


def _boolean(value):
    return value if type(value) is bool else None


def _status(raw):
    """Never propagate arbitrary exceptions, prompts, paths, or free-form text."""
    if not isinstance(raw,dict):
        return {"state":"unknown"}
    capable = raw.get("actual_update_capable")
    return {"state":_code(raw.get("state")),"phase":_code(raw.get("phase")),
            "phase_state":_code(raw.get("phase_state")),"phase_elapsed_seconds":_number(raw.get("phase_elapsed_seconds")),
            "optimizer_steps_committed":_number(raw.get("optimizer_steps_committed")),
            "checkpoints_persisted":_number(raw.get("checkpoints_persisted")),
            "actual_update_capable":{arm:_boolean(capable[arm]) for arm in ARMS if arm in capable}
            if isinstance(capable,dict) else None}


def _paired(raw):
    result=[]
    if not isinstance(raw,dict):
        return result
    for key in (f"{left}_minus_{right}" for left in ARMS for right in ARMS if left != right):
        item=raw.get(key)
        if not isinstance(item,dict):
            continue
        row={"comparison":key,"state":_code(item.get("state")),"task_count":_number(item.get("task_count")),
             "training_seed_count":_number(item.get("training_seed_count"))}
        for metric in ("accuracy_delta","cost_delta"):
            value=item.get(metric)
            if not isinstance(value,dict):
                row[metric]=None
                continue
            interval=value.get("ci95")
            row[metric]={"estimate":_number(value.get("estimate")),
                         "ci95":[_number(v) for v in interval] if isinstance(interval,list) and len(interval)==2 else None}
        result.append(row)
    return result


def _sftp_get(host, remote_run, snapshot, *, timeout, max_bytes):
    if not re.fullmatch(r"(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9][A-Za-z0-9_.-]*",host):
        raise ValueError("host must be an existing SSH alias or plain host name")
    # No shell interpolation. Quotes/control characters are rejected before the
    # OpenSSH batch grammar is used; get paths are fixed allowlisted filenames.
    if any(c in remote_run for c in ('"',"\\","\n","\r","\0")):
        raise ValueError("unsafe remote path")
    commands=[]
    for name in FILES:
        local=snapshot/name
        local.parent.mkdir(parents=True,exist_ok=True)
        quoted_local=local.resolve().as_posix()
        if '"' in quoted_local or "\n" in quoted_local or "\r" in quoted_local:
            raise ValueError("unsafe local output path")
        commands.append(f'-get "{remote_run}/{name}" "{quoted_local}"')
    commands.append("bye")
    command=["sftp","-q","-oBatchMode=yes","-oStrictHostKeyChecking=yes","-oConnectTimeout=15","-b","-",host]
    try:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    except OSError:
        return {"state":"sftp_unavailable","returncode":None}
    started=time.monotonic()
    sent=False
    while True:
        try:
            process.communicate(input=("\n".join(commands)+"\n").encode() if not sent else None,timeout=.2)
            return {"state":"connected" if process.returncode==0 else "transfer_failed","returncode":process.returncode}
        except subprocess.TimeoutExpired:
            sent=True
            oversized=any(p.is_file() and p.stat().st_size>max_bytes for p in (snapshot/name for name in FILES))
            if oversized or time.monotonic()-started>=timeout:
                process.kill()
                process.communicate()
                return {"state":"size_limit" if oversized else "timeout","returncode":process.returncode}
        except KeyboardInterrupt:
            process.kill()
            process.communicate()
            raise


def _offline_get(source, snapshot, max_bytes):
    source=Path(source).resolve()
    for name in FILES:
        path=source/name
        if not path.is_file():
            continue
        # Offline fixtures cannot redirect this allowlist to credentials outside
        # their root via a symlink; neither raw trajectories nor env are opened.
        if not path.resolve().is_relative_to(source):
            raise ValueError("offline file escapes its source directory")
        if path.stat().st_size>max_bytes:
            continue
        _atomic(snapshot/name,path.read_bytes())
    return {"state":"offline_fixture","returncode":None}


def _banner(text):
    return ('<aside style="padding:16px;margin:18px 0;border:2px solid #a6b7ce;background:#fff9e8">'
            +html.escape(text)+"</aside>")


def _evaluation_table(latest):
    columns = (("accuracy", "正确率", True), ("mean_generated_tokens", "生成 token", False),
               ("mean_measured_return_tokens", "已核对返回 token", False), ("mean_tool_calls", "工具调用", False),
               ("mean_exact_repeat_events", "完全重复事件", False), ("mean_unmarked_event_cost", "未标记事件成本", False),
               ("mean_budget_exhausted", "预算截断率", True), ("mean_explicit_abandon", "明确放弃率", True))
    rows = []
    audit = _read_json(latest.parent/'REASONING_AUDIT.json') or {}
    review_arms = None
    for name in ('BLIND_RESULT_REVIEW_ALL_ARMS.json', 'BLIND_RESULT_REVIEW.json'):
        review = _read_json(latest.parent/name)
        if isinstance(review, dict) and isinstance(review.get('arms'), dict):
            review_arms = review['arms']
            break
    overlap = _read_json(latest.parent/'RETRIEVAL_OVERLAP_AUDIT.json')
    overlap_arms = overlap.get('arms') if isinstance(overlap, dict) and overlap.get(
        'protocol') == 'prefix-visible-exact-docid-and-snippet-overlap-v1' else None
    for arm in ARMS:
        try:
            evaluation_raw = (latest/f'EVAL-{arm}.json').read_bytes()
            result = json.loads(evaluation_raw)
        except (OSError, ValueError):
            continue
        if not isinstance(result,dict):
            continue
        summary_sha = hashlib.sha256(evaluation_raw).hexdigest()
        cells = []
        for key,_,percent in columns:
            if key == 'accuracy' and result.get('resolved_count') != result.get('sample_count'):
                known = _number(result.get('resolved_count'))
                total = _number(result.get('sample_count'))
                cells.append(f'已判 {known:g}/{total:g}' if known is not None and total is not None else '—')
                continue
            value = _number(result.get(key))
            cells.append("—" if value is None else f"{value:.1%}" if percent else f"{value:,.2f}")
        gap = _read_json(latest.parent/'gap-audit'/f'EVAL-{arm}.json')
        gap_info = gap.get('gap_review') if isinstance(gap, dict) else None
        gap_cell = '—'
        if isinstance(gap_info, dict) and gap_info.get('evaluation_sha256') == summary_sha:
            known = _number(gap_info.get('observed'))
            total = _number(gap_info.get('expected'))
            rate = _number(gap.get('mean_necessary_gap_closure'))
            if known is not None and total is not None and 0 <= known <= total and total > 0:
                gap_cell = f'{rate:.1%}' if known == total and rate is not None and 0 <= rate <= 1 else f'已判 {known:g}/{total:g}'
        cells.append(gap_cell)
        usage = (audit.get('arms', {}).get(arm) or result.get('reasoning_usage') or {})
        reasoning = _number(usage.get('reasoning_derived_tokens_per_round'))
        counted = _number(usage.get('reasoning_derived_rounds'))
        total = _number(usage.get('reasoning_rounds'))
        cells.append(f'{reasoning:,.1f} ({counted:g}/{total:g})'
                     if reasoning is not None and counted is not None and total is not None else '—')
        if isinstance(overlap_arms, dict):
            measured = overlap_arms.get(arm)
            measured = measured if isinstance(measured, dict) else {}
            counts = measured.get('totals')
            counts = counts if isinstance(counts, dict) else {}
            samples = _number(measured.get('sample_count'))
            seen = _number(counts.get('fully_seen_events'))
            rewritten = _number(counts.get('fully_seen_new_arguments_events'))
            covered = _number(counts.get('covered_search_events'))
            recorded = _number(counts.get('recorded_search_events'))
            if (measured.get('summary_sha256') == summary_sha and samples == result.get('sample_count')
                    and None not in (samples, seen, rewritten, covered, recorded)
                    and samples > 0 and 0 <= rewritten <= seen <= covered <= recorded):
                cells.extend((f'{seen/samples:.2f}', f'{rewritten/samples:.2f}', f'{covered:g}/{recorded:g}'))
            else:
                cells.extend(('—', '—', '—'))
        if isinstance(review_arms, dict):
            scored = review_arms.get(arm)
            cell = '—'
            if isinstance(scored, dict) and scored.get('evaluation_sha256') == summary_sha:
                rate = _number(scored.get('diagnostic_accuracy'))
                n = _number(scored.get('samples'))
                correct = _number(scored.get('equivalent'))
                if (None not in (rate, n, correct) and n == result.get('sample_count')
                        and n > 0 and 0 <= correct <= n and rate == correct/n):
                    cell = f'{rate:.2%} ({correct:g}/{n:g})'
            cells.append(cell)
        rows.append(f'<tr><td>{arm}</td>' + ''.join(f'<td>{v}</td>' for v in cells) + '</tr>')
    if not rows:
        return '<p>等待固定题集结果。</p>'
    headings = ''.join(f'<th>{label}</th>' for _,label,_ in columns) + '<th>必要缺口闭合率</th><th>思考 token/轮（重分词）</th>'
    if isinstance(overlap_arms, dict):
        headings += '<th>全旧片段调用/轨迹</th><th>新参数但全旧片段/轨迹</th><th>片段可核对调用</th>'
    if isinstance(review_arms, dict):
        headings += '<th>独立盲评答对率</th>'
    return f'<div style="overflow-x:auto"><table><tr><th>运行</th>{headings}</tr>{"".join(rows)}</table></div>'


def mirror_once(*, job_id, output_dir=None, host="zhurong-hpc", remote_run=None,
                offline_dir=None, timeout=45, max_bytes=MAX_BYTES, refresh_seconds=15):
    job_id=str(job_id)
    if not re.fullmatch(r"[0-9]{1,12}",job_id):
        raise ValueError("job_id must contain decimal digits only")
    if not 1<=timeout<=60 or type(max_bytes) is not int or not 1<=max_bytes<=MAX_BYTES:
        raise ValueError("timeout or file size limit is out of range")
    remote_run=remote_run or f"{REMOTE_BASE}/pilot-{job_id}"
    remote=PurePosixPath(remote_run)
    if not remote.is_absolute() or ".." in remote.parts or remote.name!=f"pilot-{job_id}":
        raise ValueError("remote_run must be an absolute path to this exact pilot job")
    output=Path(output_dir) if output_dir is not None else Path(__file__).resolve().parents[1]/"outputs"/f"pilot-{job_id}"
    output=output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    previous=_read_json(output/"MIRROR_STATE.json") or {}
    if previous.get("job_id") not in (None,job_id) or previous.get("remote_run") not in (None,remote_run):
        raise ValueError("output directory is bound to a different job or remote run")
    started=_now()
    snapshot_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"-"+uuid.uuid4().hex[:8]
    snapshot=output/"snapshots"/snapshot_id
    snapshot.mkdir(parents=True)
    transfer=_offline_get(offline_dir,snapshot,max_bytes) if offline_dir is not None else _sftp_get(host,remote_run,snapshot,timeout=timeout,max_bytes=max_bytes)
    last_good=dict(previous.get("last_good",{}))
    files={}
    for name in FILES:
        path=snapshot/name
        item={"state":"remote_missing_or_unreadable" if transfer["state"] in {"connected","offline_fixture"} else "remote_unknown",
              "last_success_utc":last_good.get(name),"bytes":None,"sha256":None}
        if path.is_file():
            size=path.stat().st_size
            item["bytes"]=size
            if size>max_bytes:
                item["state"]="oversized_rejected"
            else:
                raw=path.read_bytes()
                item["sha256"]=hashlib.sha256(raw).hexdigest()
                try:
                    if name.endswith(".jsonl"):
                        events=read_events(path,allow_incomplete_tail=True)
                        tail=bool(raw and not raw.endswith(b"\n"))
                        if tail and not events:
                            raise ValueError("no complete event prefix")
                        item["event_count"]=len(events)
                        item["state"]="partial_prefix" if tail else "ok"
                    else:
                        parsed=json.loads(raw)
                        if not isinstance(parsed,list if name=="PHASES.json" else dict):
                            raise ValueError("wrong summary shape")
                        item["state"]="ok"
                    _atomic(output/"latest"/name,raw)
                    last_good[name]=started
                    item["last_success_utc"]=started
                except (ValueError,UnicodeError,TypeError,KeyError):
                    item["state"]="partial_or_invalid_rejected"
        files[name]=item
    current_status=files["STATUS.json"]["state"]=="ok"
    controller=_status(_read_json(output/"latest/STATUS.json"))
    if not current_status:
        controller={"state":"unknown","last_known":controller}
    metadata={"job_id":job_id,"remote_run":remote_run,"snapshot_started_utc":started,"snapshot_completed_utc":_now(),
              "transfer":transfer,"files":files,"last_good":last_good,"controller":controller,
              "scheduler_state":"not_queried","offline_fixture":offline_dir is not None}
    _json_write(snapshot/"DOWNLOAD_MANIFEST.json",metadata)
    _json_write(output/"MIRROR_STATE.json",metadata)

    combined=[]
    cards=[]
    for name in EVENT_FILES:
        path=output/"latest"/name
        events=read_events(path,allow_incomplete_tail=True)
        combined.extend(events)
        arm="controller" if name=="metrics.jsonl" else name.split("/")[0]
        target=output/"pages"/(arm+".html")
        render_monitor(path,target,refresh_seconds=refresh_seconds)
        detail=files[name]
        notice=(f'作业 {job_id} · 本次快照 {started} · 本次文件状态 {detail["state"]} · '
                f'最近有效下载 {detail["last_success_utc"] or "从未取得"}。缺失不表示零更新；保留的旧数据不是本次实测。')
        page=target.read_text(encoding="utf-8")
        _atomic(target,page.replace("<h1>",_banner(notice)+"<h1>",1).encode("utf-8"))
        runs=summarize_events(events)["runs"]
        committed=sum(v["optimizer_committed_count"] for v in runs.values()) if events else None
        computed=sum(v["computed_batch_count"] for v in runs.values()) if events else None
        cards.append({"arm":arm,"file_state":detail["state"],"last_success_utc":detail["last_success_utc"],
                      "observed_commits":committed,"computed_batches":computed})
    # read_events already applied nested field whitelists; the combined file is
    # sanitized derived data, while snapshots retain original bytes privately.
    aggregate=b"".join((json.dumps(e,ensure_ascii=False,allow_nan=False)+"\n").encode() for e in combined)
    _atomic(output/"overview-events.jsonl",aggregate)
    render_monitor(output/"overview-events.jsonl",output/"trends.html",refresh_seconds=refresh_seconds)
    trend_notice=f'作业 {job_id} · 镜像尝试 {started} · 各文件是否新鲜请先查看 overview.html；某些曲线可能保留旧快照。'
    trend=(output/"trends.html").read_text(encoding="utf-8")
    _atomic(output/"trends.html",trend.replace("<h1>",_banner(trend_notice)+"<h1>",1).encode())

    escape=lambda value:html.escape("未知" if value is None else str(value))
    card_rows="".join(f'<tr><td><a href="pages/{c["arm"]}.html">{c["arm"]}</a></td><td>{escape(c["file_state"])}</td>'
                       f'<td>{escape(c["computed_batches"])}</td><td>{escape(c["observed_commits"])}</td><td>{escape(c["last_success_utc"])}</td></tr>' for c in cards)
    missing=[name for name,item in files.items() if item["state"] not in {"ok","partial_prefix"}]
    paired=_paired(_read_json(output/"latest/PAIRED_COMPARISONS.json"))
    pair_text=html.escape(json.dumps(paired,ensure_ascii=False,indent=2,allow_nan=False))
    phase_text=html.escape(json.dumps(controller,ensure_ascii=False,indent=2,allow_nan=False))
    page=(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
          f'<meta http-equiv="refresh" content="{refresh_seconds}"><title>Ledger pilot {job_id}</title>'
          '<style>body{font:15px system-ui;color:#173154;background:#f5f7fb;max-width:1200px;margin:28px auto;padding:0 20px}'
          'section{background:white;padding:18px;margin:18px 0;border:1px solid #dbe3ee;border-radius:8px}'
          'table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #dde4ef}'
          'pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#245aa8}</style>'
          f'<h1>Ledger-GRPO 作业 {job_id}</h1><p>快照尝试：{escape(started)} · 传输：{escape(transfer["state"])}</p>'
          '<p><b>running 只代表控制器状态，不代表服务已就绪、已产生轨迹或已提交训练更新。</b>'
          '本脚本不查询 Slurm，排队状态及作业最终终态仍为未知。计数仅来自已观测回执；远程缺失不补零。</p>'
          +('<p><b>离线样例，不是真实作业结果。</b></p>' if offline_dir is not None else '')+
          f'<section><h2>控制器快照</h2><pre>{phase_text}</pre></section>'
          '<section><h2>分臂记录</h2><table><tr><th>运行</th><th>本次文件状态</th><th>优势计算批次</th><th>已观测 optimizer 提交</th><th>最近有效下载</th></tr>'
          f'{card_rows}</table><p><a href="trends.html">查看所有运行的趋势页</a></p></section>'
          '<section><h2>固定题集观测</h2><p>各成本为每条轨迹均值。返回成本取可核对部分。'
          '思考长度由记录字段重分词，括号给出可估计轮次和总轮次。</p>'
          f'{_evaluation_table(output/"latest")}</section>'
          '<section><h2>固定任务配对比较</h2><p>单训练 seed 的探索性区间；不代表跨 seed 可靠性，也不证明收敛或非劣。</p>'
          f'<p>本次摘要状态：{escape(files["PAIRED_COMPARISONS.json"]["state"])} · 最近有效下载：{escape(files["PAIRED_COMPARISONS.json"]["last_success_utc"])}</p><pre>{pair_text}</pre></section>'
          f'<section><h2>远程缺失、未知或暂不可解析文件</h2><pre>{html.escape(chr(10).join(missing) or "无")}</pre>'
          '<p>未执行的实验臂不会伪造评测。原始下载保留在本地 snapshots 目录，不嵌入页面。</p></section></html>')
    _atomic(output/"overview.html",page.encode("utf-8"))
    return {"job_id":job_id,"snapshot_utc":started,"transfer_state":transfer["state"],
            "controller_state":controller["state"],"missing_or_unknown_count":len(missing),
            "overview":str(output/"overview.html")}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id",required=True)
    parser.add_argument("--host",default="zhurong-hpc")
    parser.add_argument("--remote-run")
    parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--offline-dir",type=Path)
    parser.add_argument("--watch-seconds",type=int,default=0,help="0=one snapshot; finite watch, at most 86400 seconds")
    parser.add_argument("--interval-seconds",type=int,default=20)
    parser.add_argument("--timeout",type=int,default=45)
    args=vars(parser.parse_args(argv))
    duration=args.pop("watch_seconds"); interval=args.pop("interval_seconds")
    if not 0<=duration<=86400 or not 1<=interval<=60:
        parser.error("watch duration must be 0..86400 and interval 1..60 seconds")
    deadline=time.monotonic()+duration
    try:
        while True:
            result=mirror_once(**args,refresh_seconds=interval)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False),flush=True)
            remaining=deadline-time.monotonic()
            if duration==0 or remaining<=0:
                return 0
            time.sleep(min(interval,remaining))
    except KeyboardInterrupt:
        return 0
    except (ValueError,OSError,TypeError,KeyError):
        parser.exit(2,"mirror could not validate or render this snapshot; no raw remote content was printed\n")


if __name__=="__main__":
    raise SystemExit(main())
