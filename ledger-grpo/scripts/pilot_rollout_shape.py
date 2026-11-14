"""Adapt the frozen recorder's batch cardinality for development task selection."""

import hashlib
import inspect
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class PilotBatchShape:
    query_count: int
    samples_per_query: int

    def __post_init__(self):
        if type(self.query_count) is not int or not 1 <= self.query_count <= 16 or self.samples_per_query != 8:
            raise ValueError('pilot requires 1–16 complete eight-sample question groups')

    def verify_groups(self, query_ids):
        counts = Counter(query_ids)
        if len(counts) != self.query_count or any(n != self.samples_per_query for n in counts.values()):
            raise ValueError('native group counts do not match the pilot batch')


def adapt_rollout_shape(function, artifact):
    original = inspect.getsource(function)
    replacements = {'BatchShape(16, 8)': 'PilotBatchShape(len(rows), 8)',
                    "'query_count': 16": "'query_count': len(rows)",
                    "'shape': [16, 8]": "'shape': [len(rows), 8]"}
    if any(original.count(old) != 1 for old in replacements):
        raise ValueError('frozen rollout cardinality boundary changed')
    source = original
    for old,new in replacements.items():
        source = source.replace(old,new)
    # Each of the eight 128 literals is the total sample count, worker cap,
    # seed stride, or the denominator of a batch-level diagnostic.
    source, count = re.subn(r'\b128\b', '(len(rows)*8)', source)
    if count != 8:
        raise ValueError(f'unexpected frozen sample-count literal inventory: {count}')
    artifact.write_text(source, encoding='utf-8')
    namespace = dict(function.__globals__)
    namespace['PilotBatchShape'] = PilotBatchShape
    exec(compile(source, str(artifact), 'exec'), namespace)
    return namespace[function.__name__], {'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
                                          'adapted_sha256': hashlib.sha256(source.encode()).hexdigest()}
