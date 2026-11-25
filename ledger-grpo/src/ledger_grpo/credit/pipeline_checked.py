"""Retry a capped request once with the same payload and configuration."""
from .pipeline_rules import normalize_q3


def request_with_truncation_retry(folder, key, number, prompt, payload, cfg, send):
    value, error, receipts = send(folder, key, prompt, payload, cfg, max_retries=0)
    receipt, = receipts
    first = {"attempt":number,"receipt":receipt,"truncation_retry":False}
    if receipt["finish_reason"] != "length":
        return value,error,[first],False
    first["errors"]=["output_truncated"]
    value,error,receipts=send(folder,key+".length-retry",prompt,payload,cfg,max_retries=0)
    receipt,=receipts
    last={"attempt":number,"receipt":receipt,"truncation_retry":True}
    truncated=receipt["finish_reason"]=="length"
    return (None if truncated else value),("retry_output_truncated" if truncated else error),[first,last],truncated


def flags(attempts):
    return {"truncation_retry":any(a["truncation_retry"] for a in attempts),
            "truncation_retry_count":sum(a["truncation_retry"] for a in attempts),
            "truncation_retry_truncated":sum(a["truncation_retry"] and a["receipt"]["finish_reason"]=="length"
                                           for a in attempts)}


def checked(folder,phase,prompt,body,cfg,check,send):
    attempts,errors=[],[]
    for number in range(1,4):
        payload={**body,"上一次校验错误":errors} if errors else body
        parsed,error,new,terminal=request_with_truncation_retry(folder,f"{phase}.try{number}",number,prompt,payload,cfg,send)
        errors=[error] if error else check(parsed)
        new[-1]["errors"]=errors
        attempts.extend(new)
        if not errors or terminal:
            break
    return {"passed":not errors,"parsed":parsed if not errors else None,"attempts":attempts,**flags(attempts)}


def checked_q3(folder,prompt,body,cfg,expected,send):
    merged,claims,attempts,errors={},[],[],[]
    stray_keys=[]
    for number in range(1,4):
        payload={**body,"上一次校验错误":errors} if errors else body
        parsed,error,new,terminal=request_with_truncation_retry(folder,f"Q3.try{number}",number,prompt,payload,cfg,send)
        stray=[]
        if error:
            errors=[error]
        else:
            value=parsed
            if isinstance(parsed,dict) and isinstance(parsed.get("verdicts"),dict):
                raw=parsed["verdicts"]
                stray=[key for key in raw if key not in expected]
                value={**parsed,"verdicts":{key:verdict for key,verdict in raw.items() if key in expected}}
            verdicts,current_claims,errors=normalize_q3(value,expected)
            merged.update(verdicts)
            if current_claims is not None:
                claims=current_claims
            missing=sorted(expected-merged.keys())
            if missing:
                errors.append("缺少以下证据的裁决："+"、".join(missing))
        for item in new:
            item["q3_stray_keys"]=[]
        new[-1]["errors"]=errors
        new[-1]["q3_stray_keys"]=stray
        attempts.extend(new)
        stray_keys.extend(stray)
        if not errors or terminal:
            break
    return {"passed":not errors,"attempts":attempts,"parsed":{"verdicts":merged,"claims":claims},
            "unjudged_evidence":sorted(expected-merged.keys()),"q3_stray_keys":stray_keys,**flags(attempts)}
