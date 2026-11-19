from ledger_grpo.ledgercredit.judge_v5 import gate, redact_answers, select_tracks, validate


def test_validate_restores_literal_span_and_counts_union_without_stopwords():
    q = 'Which artist lives in Oak-Town and won five prizes?'
    response = {
        'query_id': 'q1', 'entities': [{'var': 'P', 'name': 'Ada', 'role': 'artist'}],
        'conditions': [
            {'id': 'k1', 'question_span': 'lives in Oak–Town', 'subject': 'P',
             'claim': 'Ada lives in Oak-Town.', 'type': 'relation'},
            {'id': 'k2', 'question_span': 'won five prizes', 'subject': 'P',
             'claim': 'Ada won five prizes.', 'type': 'number'},
        ], 'answer_relation': 'Identify the artist.'
    }
    result, issues = validate('q1', q, response)
    assert not issues
    assert result['conditions'][0]['question_span'] == 'lives in Oak-Town'
    assert result['coverage_covered'] == 6
    assert result['coverage_total'] == 7
    response['conditions'][1]['subject'] = 'X'
    response['conditions'][1]['question_span'] = 'lost five prizes'
    assert validate('q1', q, response)[1] == ['span_not_found', 'unknown_subject']


def test_gate_denominators_and_zero_refs():
    assert gate(2, 2, 70, 100, 19, 20, 1, 50)['passed']
    assert not gate(2, 2, 69, 100, 19, 20, 1, 50)['passed']
    assert not gate(0, 0, 100, 100, 0, 0, 0, 0)['passed']
    assert not gate(0, 0, 100, 100, 99, 100, 2, 50)['passed']


def test_new_sample_excludes_previous_diagnostics_and_is_stable():
    old = [f't{i}' for i in range(10)]
    all_tracks = [f't{i}' for i in range(35)]
    excluded = ['t10', 't11']
    first, new = select_tracks(old, excluded, all_tracks)
    assert first == old and len(set(new)) == 10
    assert not set(new) & set(old + excluded)
    assert select_tracks(old, excluded, reversed(all_tracks))[1] == new


def test_reference_answers_removed_from_packet_with_composed_names_and_punctuation():
    assert redact_answers('Find J. Roe; ROE is the author.', ['J Roe', 'Roe']) == (
        'Find [答案实体]; [答案实体] is the author.')
    assert redact_answers('alabaster and baster', ['baster']) == 'alabaster and [答案实体]'
