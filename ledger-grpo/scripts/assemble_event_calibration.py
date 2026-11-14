"""Join independently graded branch receipts for the existing audit-events command."""

import argparse
import hashlib
import json
from pathlib import Path

from ledger_grpo.event_pair_calibration import paired_calibration_row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--grades', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw_audit, raw_grades = args.audit.read_bytes(), args.grades.read_bytes()
    audit, grades = json.loads(raw_audit), json.loads(raw_grades)
    audit_sha, grade_sha = (hashlib.sha256(data).hexdigest() for data in (raw_audit, raw_grades))
    if audit['protocol'] != 'browsecomp-matched-single-event-prefix-v1':
        raise ValueError('expected an audited BrowseComp event prefix manifest')
    events = {(row['trajectory_sha256'], row['event_id']): row for row in audit['pairs']}
    if len(events) != len(audit['pairs']):
        raise ValueError('duplicate event bindings in prefix audit')
    output = []
    for case in json.loads(args.cases.read_bytes()):
        event = events[case['trajectory_sha256'], case['event_id']]
        results, receipts = [], []
        for name in case['branch_results']:
            path = args.cases.parent / name
            raw = path.read_bytes()
            receipt = hashlib.sha256(raw).hexdigest()
            results.append((json.loads(raw), grades.get(receipt)))
            receipts.append(receipt)
        fields = {key: value for key, value in case.items() if key != 'branch_results'}
        row = paired_calibration_row(fields, event, audit_sha, results)
        output.append(dict(row, branch_result_sha256=receipts, grade_file_sha256=grade_sha))
    if not output:
        raise ValueError('no reviewed events in the case manifest')
    with args.output.open('x', encoding='utf-8') as handle:
        for row in output:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
