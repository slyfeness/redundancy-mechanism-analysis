"""Prepare native-capture copies of the two frozen cross-task samplers."""

import argparse
import hashlib
from pathlib import Path


SOURCE_SHA256 = {
    "sage": "f8bc7deb0548157095da927c303bf886429b6c997909d55a8883290cc63c2524",
    "scicode": "d5eba3fd500abfe362c89694d3db672fdba31c9f0beea471ad4f039a01509ce5",
}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"expected one matching sampler anchor: {old[:90]}")
    return text.replace(old, new, 1)


def prepare_source(dataset, source):
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256[dataset]:
        raise ValueError("sampler source differs from its frozen version")
    text = data.decode("utf-8")
    text = replace_once(text, "import requests\n",
                        "import requests\nfrom ledger_grpo.native_capture import capture_status, native_chat_request\n")
    if dataset == "sage":
        text = replace_once(text, "   rq=folder/f'round_{n:02d}_request.json'",
                            "   b=native_chat_request(b)\n   rq=folder/f'round_{n:02d}_request.json'")
        text = replace_once(text, "   am={'role':'assistant'",
                            "   rec['native_capture']=capture_status(z)\n"
                            "   if not rec['native_capture']['valid']:stop='NATIVE_CAPTURE_INVALID';break\n"
                            "   am={'role':'assistant'")
        text = replace_once(text, "def main():\n ap=", "def main():\n global O\n ap=")
        text = replace_once(text, "a=ap.parse_args();src=O/",
                            "ap.add_argument('--native-output',type=Path,required=True);a=ap.parse_args()\n"
                            " if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',a.attempt):"
                            "ap.error('attempt must be a simple directory name')\n"
                            " src=O/")
        text = replace_once(text, ";root=O/'trajectories'/a.phase/a.attempt;",
                            ";O=a.native_output.resolve();O.mkdir(parents=True,exist_ok=False);"
                            "root=O/'trajectories'/a.phase/a.attempt;")
        text = replace_once(text, "len(rows)==len(items) and not errs else 'PARTIAL'",
                            "len(rows)==len(items) and not errs and not any(r['stop_reason']=='NATIVE_CAPTURE_INVALID' for r in rows) else 'PARTIAL'")
    else:
        text = replace_once(text, "  rq=sf/f'round_{n:02d}_request.json'",
                            "  b=native_chat_request(b)\n  rq=sf/f'round_{n:02d}_request.json'")
        text = replace_once(text, "  assistant={'role':'assistant'",
                            "  rr['native_capture']=capture_status(z)\n"
                            "  if not rr['native_capture']['valid']:stop='NATIVE_CAPTURE_INVALID';break\n"
                            "  assistant={'role':'assistant'")
        text = replace_once(text, "   if s['submitted_code'] is not None:previous.append(s['submitted_code'])",
                            "   if s['stop_reason']=='NATIVE_CAPTURE_INVALID':break\n"
                            "   if s['submitted_code'] is not None:previous.append(s['submitted_code'])")
        text = replace_once(text, "def main():\n ap=", "def main():\n global OUT\n ap=")
        text = replace_once(text, "a=ap.parse_args();manifest=",
                            "ap.add_argument('--native-output',type=Path,required=True);a=ap.parse_args();manifest=")
        text = replace_once(text, " sandbox_smoke();gpus=",
                            " OUT=a.native_output.resolve();OUT.mkdir(parents=True,exist_ok=False)\n"
                            " sandbox_smoke();gpus=")
        text = replace_once(text, "  submitted=[x for x in out if x['status']=='SUBMITTED']",
                            "  if any(x['stop_reason']=='NATIVE_CAPTURE_INVALID' for x in out):"
                            "raise RuntimeError('five-target native capture gate failed')\n"
                            "  submitted=[x for x in out if x['status']=='SUBMITTED']")
        text = replace_once(text, "dump(OUT/'GENERATION_COMPLETE.json',{'status':'PASS'",
                            "dump(OUT/'GENERATION_COMPLETE.json',{'status':'PARTIAL' if any("
                            "x['stop_reason']=='NATIVE_CAPTURE_INVALID' for x in allrows) else 'PASS'")
    compile(text, str(source), "exec")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=tuple(SOURCE_SHA256), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generated = prepare_source(args.dataset, args.source)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(generated)
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
