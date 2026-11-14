"""Conservative evidence matching; manual grounding/coherence remain separate."""
from collections import defaultdict
from typing import Any
import unicodedata


def canonical(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFC', text).split()).casefold()


def gold_evidence(question: dict) -> list[dict]:
    return [{'source_id': question['gold_source_id'], 'page': question['gold_page'],
             'quote': question['evidence_quote']}] + question.get('alternative_evidence', [])


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    labels = []
    for hit in hits[:3]:
        metadata = hit['metadata']
        labels.append(any(metadata.get('document_id') == gold['source_id']
                          and metadata.get('page') == gold['page']
                          and canonical(gold['quote']) in canonical(hit['text'])
                          for gold in gold_evidence(question)))
    return {'id': question['id'], 'split': question['split'], 'question': question.get('question'),
            'gold_evidence': gold_evidence(question), 'hit1': bool(labels and labels[0]),
            'hit3': any(labels), 'hit_labels': labels, 'hits': hits[:3],
            'scoring': 'source + physical page + full normalized quote; equivalent evidence needs reviewed labels'}


def summarize(traces: list[dict[str, Any]]) -> list[dict]:
    groups = defaultdict(list)
    for trace in traces:
        groups[(trace['strategy'], trace['split'])].append(trace)
    return [dict(strategy=strategy, split=split, n=len(rows),
                 hit1_n=sum(r['hit1'] for r in rows), hit3_n=sum(r['hit3'] for r in rows),
                 hit1=sum(r['hit1'] for r in rows) / len(rows),
                 evidence_hit3=sum(r['hit3'] for r in rows) / len(rows))
            for (strategy, split), rows in sorted(groups.items())]
