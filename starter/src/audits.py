"""Export and summarize source-linked evidence and manual assessments."""
import csv
import json
import shutil
from pathlib import Path
from .evaluation import canonical, summarize
from .workflow import (digest, load_prepared, read_jsonl, write_csv, write_json, write_jsonl)


def export_audits(root: Path) -> None:
    state, prepared = load_prepared(root)
    output = root / 'results' / state['prepared_id']
    folder = output / 'audits'
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / 'coherence.csv').exists():
        shutil.copyfile(prepared / 'coherence.csv', folder / 'coherence.csv')
    for split in ('dev', 'test'):
        path = output / split / 'traces.jsonl'
        if not path.exists():
            continue
        evidence, metadata, grounding = [], [], []
        for trace in read_jsonl(path):
            if split == 'test':
                grounding.append(dict(strategy=trace['strategy'], question_id=trace['id'],
                    question=trace['question'], hits=json.dumps(trace['hits'], ensure_ascii=False),
                    score='', reason='', reviewer=''))
            for rank, hit in enumerate(trace['hits'], 1):
                base = dict(strategy=trace['strategy'], question_id=trace['id'], rank=rank,
                            chunk_id=hit['chunk_id'], source=hit['metadata']['source'], page=hit['metadata']['page'])
                evidence.append(dict(base, text=hit['text'], automatic_hit=int(trace['hit_labels'][rank-1]),
                    gold=json.dumps(trace['gold_evidence'], ensure_ascii=False),
                    accepted='', supporting_quote='', reason='', reviewer='', trace_sha256=digest(path)))
                if split == 'test':
                    metadata.append(dict(base, metadata=json.dumps(hit['metadata'], ensure_ascii=False),
                                         metadata_correct='', reason='', reviewer=''))
        candidates = [(f'evidence_{split}.csv', evidence)]
        if split == 'test':
            candidates += [('metadata.csv', metadata), ('grounding.csv', grounding)]
        for name, rows in candidates:
            if rows and not (folder / name).exists():
                write_csv(folder / name, list(rows[0]), rows)
    print(f'Audit forms saved to {folder}; score, reason and reviewer fields intentionally blank.')


def review_evidence(root: Path, split: str, labels: Path) -> None:
    state, prepared = load_prepared(root)
    output = root / 'results' / state['prepared_id']
    if split == 'dev' and ((output / 'selection.json').exists() or (output / 'test/traces.jsonl').exists()):
        raise ValueError('Review dev evidence before configuration selection and test exposure.')
    path = output / split / 'traces.jsonl'
    traces = read_jsonl(path)
    lookup = {(t['strategy'], t['id']): t for t in traces}
    pages = {(p['document_id'], p['page']): p['text'] for p in read_jsonl(prepared / 'pages.jsonl')}
    equivalents, decisions = {}, {}
    with labels.open(newline='') as handle:
        for row in csv.DictReader(handle):
            if not row['accepted'].strip():
                continue
            if row['accepted'] not in ('0', '1') or not row['reason'].strip() or not row['reviewer'].strip():
                raise ValueError('Each reviewed label needs 0/1, reason and reviewer.')
            if row['trace_sha256'] != digest(path):
                raise ValueError('Review form refers to stale traces.')
            trace = lookup[row['strategy'], row['question_id']]
            hit = trace['hits'][int(row['rank'])-1]
            if hit['chunk_id'] != row['chunk_id']:
                raise ValueError('Review chunk mismatch.')
            if row['accepted'] == '1':
                quote = row['supporting_quote'].strip()
                meta = hit['metadata']
                if any(meta.get(k) != v for k,v in trace['filter_requested'].items()):
                    raise ValueError('Equivalent evidence violates the question-provided scope.')
                if not quote or canonical(quote) not in canonical(hit['text']) or canonical(quote) not in canonical(pages[meta['document_id'], meta['page']]):
                    raise ValueError('Accepted evidence needs a quote verified in the hit and original normalized source.')
                equivalents.setdefault(trace['id'], []).append((meta['document_id'], meta['page'], quote, row))
            key = (trace['id'], hit['chunk_id'])
            if key in decisions and decisions[key]['accepted'] != row['accepted']:
                raise ValueError('Conflicting labels for the same question/chunk across strategies.')
            decisions[key] = row
    if not decisions:
        raise ValueError('No reviewed labels were supplied.')
    for trace in traces:
        labels_out = list(trace['hit_labels'])
        trace.setdefault('automatic_hit_labels', list(labels_out))
        trace.setdefault('evidence_reviews', [])
        for rank, hit in enumerate(trace['hits']):
            for doc, page, quote, review in equivalents.get(trace['id'], []):
                if hit['metadata']['document_id'] == doc and hit['metadata']['page'] == page and canonical(quote) in canonical(hit['text']):
                    labels_out[rank] = True
                    trace['evidence_reviews'].append(review)
            decision = decisions.get((trace['id'], hit['chunk_id']))
            if decision:
                labels_out[rank] = decision['accepted'] == '1'
                trace['evidence_reviews'].append(decision)
        trace.update(hit_labels=labels_out, hit1=bool(labels_out and labels_out[0]), hit3=any(labels_out))
    write_jsonl(path, traces)
    write_json(output / split / 'metrics.json', summarize(traces))
    print('Reviewed evidence applied consistently to matching chunks across strategies; metrics recomputed.')


def summarize_audits(root: Path) -> None:
    state, _ = load_prepared(root)
    output = root / 'results' / state['prepared_id']
    folder = output / 'audits'
    forms = {}
    for name, column, allowed in [('coherence', 'score', {'0','1','2'}),
                                  ('grounding', 'score', {'0','1','2'}),
                                  ('metadata', 'metadata_correct', {'0','1'})]:
        with (folder / f'{name}.csv').open(newline='') as handle:
            forms[name] = list(csv.DictReader(handle))
        for row in forms[name]:
            if row[column] not in allowed or not row['reason'].strip() or not row['reviewer'].strip():
                raise ValueError(f'{name}: incomplete score/reason/reviewer; manual evaluation remains pending.')
    traces = read_jsonl(output / 'test/traces.jsonl')
    _, prepared = load_prepared(root)
    with (prepared / 'coherence.csv').open(newline='') as handle:
        expected_coherence = {(r['strategy'], r['sample_id'], r['chunk_id']) for r in csv.DictReader(handle)}
    actual_coherence = [(r['strategy'], r['sample_id'], r['chunk_id']) for r in forms['coherence']]
    expected_grounding = {(t['strategy'], t['id']) for t in traces}
    actual_grounding = [(r['strategy'], r['question_id']) for r in forms['grounding']]
    expected_metadata = {(t['strategy'], t['id'], str(i), h['chunk_id'])
                         for t in traces for i,h in enumerate(t['hits'],1)}
    actual_metadata = [(r['strategy'],r['question_id'],r['rank'],r['chunk_id']) for r in forms['metadata']]
    for expected, actual in [(expected_coherence, actual_coherence), (expected_grounding, actual_grounding),
                             (expected_metadata, actual_metadata)]:
        if len(actual) != len(expected) or set(actual) != expected:
            raise ValueError('Audit contains duplicate, missing, or mismatched source/query samples.')
    result = []
    for strategy in state['config']['strategies']:
        coherence = [r for r in forms['coherence'] if r['strategy'] == strategy]
        grounding = [r for r in forms['grounding'] if r['strategy'] == strategy]
        metadata = [r for r in forms['metadata'] if r['strategy'] == strategy]
        actual = [t for t in traces if t['strategy'] == strategy]
        if len(coherence) != 10 or len(grounding) != len(actual) or len(metadata) != sum(len(t['hits']) for t in actual):
            raise ValueError('Manual audit sample counts do not match the required source/query samples.')
        checked = {(r['question_id'], r['chunk_id']): r['metadata_correct'] == '1' for r in metadata}
        filtered = [t for t in actual if t['filter_requested']]
        compliant = sum(bool(t['hits']) and all(checked[t['id'], h['chunk_id']] and
                          all(h['metadata'].get(k) == v for k,v in t['filter_requested'].items())
                          for h in t['hits']) for t in filtered)
        scores = [int(r['score']) for r in grounding]
        result.append(dict(strategy=strategy, coherence_n=len(coherence),
            coherence_mean=sum(int(r['score']) for r in coherence)/len(coherence),
            metadata_correct_n=sum(r['metadata_correct']=='1' for r in metadata), metadata_n=len(metadata),
            filter_compliant_n=compliant if filtered else None, filter_n=len(filtered),
            filter_compliance=compliant/len(filtered) if filtered else None,
            grounding_counts={str(i): scores.count(i) for i in (0,1,2)},
            grounding_mean=sum(scores)/len(scores),
            reviewers=sorted({r['reviewer'] for rows in forms.values() for r in rows})))
    write_json(output / 'manual_audit_summary.json', result)
    print(f'Manual audit summary saved to {output}; reviewer identities retained.')
