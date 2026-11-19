"""Round-2 descriptive call rules. No semantic redundancy verdicts."""
import hashlib
import re
import unicodedata

def normalize_query(query):
    return ' '.join(''.join(c for c in str(query).lower()
                           if not unicodedata.category(c).startswith('P')).split())

def jaccard(a, b):
    a, b = set(normalize_query(a).split()), set(normalize_query(b).split())
    return len(a & b) / len(a | b) if a | b else 0.0

def classify(event, earlier):
    flags, matches = [], {}
    def mark(flag, events):
        flags.append(flag); matches[flag] = [e['stage_id'] for e in events]
    if event['tool'] == 'search':
        searches = [e for e in earlier if e['tool'] == 'search']
        exact = [e for e in searches if normalize_query(e['query']) == normalize_query(event['query'])]
        if exact:
            mark('S_exact', exact)
        else:
            near = [e for e in searches if jaccard(e['query'], event['query']) >= .7]
            if near: mark('S_near', near)
        if not event['docids']:
            mark('S_empty', [])
        else:
            seen = set().union(*(set(e['docids']) for e in earlier)) if earlier else set()
            if set(event['docids']) <= seen:
                mark('S_allseen', [e for e in earlier if set(e['docids']) & set(event['docids'])])
    elif event['tool'] == 'open':
        opens = [e for e in earlier if e['tool'] == 'open']
        exact = [e for e in opens if (e['docid'], e['start']) == (event['docid'], event['start'])]
        if exact: mark('O_exact', exact)
        same = [e for e in opens if e['body_sha256'] == event['body_sha256']]
        if same: mark('O_samecontent', same)
        prior_search_docs = set().union(*(set(e['docids']) for e in earlier if e['tool'] == 'search')) if earlier else set()
        if event['docid'] not in prior_search_docs: mark('O_unseen', [])
    return flags, matches

REPEAT_FLAGS = {'S_exact', 'S_allseen', 'O_exact', 'O_samecontent'}

def selftest():
    def search(sid,q,docs):return {'stage_id':sid,'tool':'search','query':q,'docids':docs}
    def opened(sid,d,start,body):return {'stage_id':sid,'tool':'open','docid':d,'start':start,
        'docids':[d], 'body_sha256':hashlib.sha256(body.encode()).hexdigest()}
    a=search('R1','A,  B C D E!',['d'])
    assert classify(a,[])[0] == []
    assert normalize_query(' A,  B! ') == 'a b'
    assert set(classify(search('R2','a b c d e',['d']),[a])[0]) == {'S_exact','S_allseen'}
    assert 'S_near' in classify(search('R2','a b c d',['e']),[a])[0]
    assert classify(search('R2','x',[]),[a])[0] == ['S_empty']
    b=opened('R2','d',0,'body')
    assert classify(b,[a])[0] == []
    assert set(classify(opened('R3','d',0,'body'),[a,b])[0]) == {'O_exact','O_samecontent'}
    assert set(classify(opened('R3','other',10,'body'),[a,b])[0]) == {'O_samecontent','O_unseen'}
    assert 'S_allseen' in classify(search('R4','anything',['d']),[b])[0]
    assert not (set(['S_near','O_unseen','S_empty']) & REPEAT_FLAGS)
    return 9
