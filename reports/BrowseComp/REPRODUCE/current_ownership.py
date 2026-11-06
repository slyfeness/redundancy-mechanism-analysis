"""Apply an explicit administrative handoff without rewriting frozen scope data."""
import csv, hashlib, json
from pathlib import Path

def load_effective_scope(scope_path, handoff_path=None):
 scope_path=Path(scope_path)
 with scope_path.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
 handoff_path=Path(handoff_path) if handoff_path else scope_path.parent/'CURRENT_OWNER_HANDOFF_001.json'
 if not handoff_path.exists():return rows
 hand=json.loads(handoff_path.read_text(encoding='utf-8'))
 if hand['scope_sha256']!=hashlib.sha256(scope_path.read_bytes()).hexdigest():raise ValueError('Frozen scope SHA mismatch')
 by_id={r['case_id']:r for r in rows};seen=set()
 for transfer in hand['transfers']:
  cid=transfer['case_id']
  if cid not in by_id or cid in seen:raise ValueError('Unknown or duplicate handoff case')
  row=by_id[cid]
  if transfer['from']!=row['owner'] or transfer['to'] not in ['ROOT','PEER'] or transfer['to']==row['owner']:raise ValueError('Invalid owner transition')
  if transfer.get('decision_absent_at_transfer') is not True:raise ValueError('Only previously unstarted cases can transfer')
  row['owner']=transfer['to'];seen.add(cid)
 return rows
