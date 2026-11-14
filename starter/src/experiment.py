"""Local pgvector ingestion and dev-before-test evaluation."""
from datetime import datetime, timezone
from pathlib import Path
import os
import time
from dotenv import load_dotenv
from .evaluation import evaluate_query, summarize
from .models import Chunk
from .store import PgVectorStore
from .workflow import (chunk_backing, digest, load_prepared, read_json, read_jsonl,
                       validate_embedding_output, write_json, write_jsonl)


def store_for(root: Path, dimensions: int) -> PgVectorStore:
    load_dotenv(root / 'starter/.env')
    url = os.getenv('DATABASE_URL')
    if not url:
        raise ValueError('DATABASE_URL is missing; configure starter/.env.')
    return PgVectorStore(url, dimensions)


def ingest(root: Path, embeddings: Path) -> None:
    state, directory = load_prepared(root)
    metadata, vectors = validate_embedding_output(state, directory, embeddings)
    store = store_for(root, state['config']['model']['dimensions'])
    store.create_schema()
    timings = {}
    for strategy in state['config']['strategies']:
        backing = chunk_backing(state['config'], strategy)
        chunks = [Chunk(**r) for r in read_jsonl(directory / f'chunks_{backing}.jsonl')]
        for chunk in chunks:
            chunk.metadata.update(prepared_id=state['prepared_id'], embedding_sha256=metadata['vectors_sha256'])
        counts, elapsed = [], []
        for _ in range(2):
            start = time.perf_counter()
            store.upsert(strategy, chunks, vectors[backing])
            elapsed.append(time.perf_counter() - start)
            counts.append(store.count(strategy))
        if counts != [len(chunks), len(chunks)]:
            raise RuntimeError('Re-ingestion created unexpected row counts.')
        timings[strategy] = dict(initial_import_seconds=elapsed[0], reload_seconds=elapsed[1],
                                 row_counts=counts, embedding_reused_from=backing if strategy != backing else None)
    output = root / 'results' / state['prepared_id']
    embedding_location = embeddings.resolve()
    if embedding_location.is_relative_to(root):
        embedding_location = embedding_location.relative_to(root)
    write_json(output / 'ingestion.json', dict(prepared_id=state['prepared_id'],
               embedding_output=str(embedding_location), embedding_run_sha256=digest(embeddings / 'embedding_run.json'),
               database_import=timings, embedding_run=metadata,
               backend='PostgreSQL/pgvector', metric='cosine', search='exact',
               query_embedding_timing='Benchmark query encoding is precomputed; lookup time is not end-to-end query latency.'))
    print(f'Imported {list(timings)}; reload without duplicates verified. Results: {output}')


def study(root: Path):
    state, directory = load_prepared(root)
    output = root / 'results' / state['prepared_id']
    ingestion = read_json(output / 'ingestion.json')
    embeddings = root / ingestion['embedding_output']
    if digest(embeddings / 'embedding_run.json') != ingestion['embedding_run_sha256']:
        raise ValueError('Embedding run changed after ingestion.')
    metadata, vectors = validate_embedding_output(state, directory, embeddings)
    store = store_for(root, state['config']['model']['dimensions'])
    for strategy in state['config']['strategies']:
        backing = chunk_backing(state['config'], strategy)
        expected = {r['chunk_id'] for r in read_jsonl(directory / f'chunks_{backing}.jsonl')}
        if store.snapshot_ids(strategy) != expected:
            raise ValueError(f'Database snapshot changed for {strategy}; ingest the prepared vectors again.')
    return state, directory, output, store, metadata, vectors


def run_split(root: Path, split: str) -> None:
    state, directory, output, store, metadata, vectors = study(root)
    if split == 'dev' and (output / 'test/traces.jsonl').exists():
        raise ValueError('Test was already exposed; do not tune/re-run dev for this holdout study.')
    if split == 'test':
        selection = read_json(output / 'selection.json')
        if selection['prepared_id'] != state['prepared_id'] or selection['dev_trace_sha256'] != digest(output / 'dev/traces.jsonl'):
            raise ValueError('Missing/stale configuration selection; select on dev first.')
        if selection['embedding_run_sha256'] != digest(root / read_json(output / 'ingestion.json')['embedding_output'] / 'embedding_run.json'):
            raise ValueError('Embedding execution changed after dev selection.')
        if (output / 'test/traces.jsonl').exists():
            print('Test traces already exist; retaining the recorded holdout run.')
            return
    questions = read_json(root / 'benchmark/questions.json')
    query_rows = read_jsonl(directory / 'queries.jsonl')
    query_vectors = {r['id']: v for r, v in zip(query_rows, vectors['queries'])}
    traces = []
    for strategy, settings in state['config']['strategies'].items():
        for question in (q for q in questions if q['split'] == split):
            applied = question.get('filter') if settings['filters'] else None
            start = time.perf_counter()
            hits = store.search(strategy, query_vectors[question['id']], 3, applied)
            elapsed = time.perf_counter() - start
            for hit in hits:
                if hit['metadata'].get('prepared_id') != state['prepared_id'] or hit['metadata'].get('embedding_sha256') != metadata['vectors_sha256']:
                    raise ValueError('Database contains vectors from an incompatible study.')
            trace = evaluate_query(question, hits)
            trace.update(strategy=strategy, prepared_id=state['prepared_id'], expected_answer=question['expected_answer'],
                         filter_requested=question.get('filter', {}), filter_applied=applied or {},
                         search_seconds=elapsed, query_embedding='precomputed_real_model',
                         fewer_than_three_hits=len(hits) < 3)
            traces.append(trace)
    write_jsonl(output / split / 'traces.jsonl', traces)
    write_json(output / split / 'metrics.json', summarize(traces))
    print(f'{split}: saved {len(traces)} query traces and separate metrics.')


def select(root: Path) -> None:
    state, _, output, _, _, _ = study(root)
    if (output / 'test/traces.jsonl').exists():
        raise ValueError('Test was already exposed; configuration selection is frozen.')
    traces = read_jsonl(output / 'dev/traces.jsonl')
    metrics = summarize(traces)
    if {r['strategy'] for r in metrics} != set(state['config']['strategies']) or any(r['split'] != 'dev' or r['n'] != state['question_counts']['dev'] for r in metrics):
        raise ValueError('Dev traces are incomplete.')
    ranking = sorted(metrics, key=lambda r: (-r['evidence_hit3'], -r['hit1'],
                     state['chunk_statistics'][r['strategy']]['chunk_count'], r['strategy']))
    value = dict(prepared_id=state['prepared_id'], selected_strategy=ranking[0]['strategy'],
                 selection_rule=state['config']['selection_rule'], dev_metrics=ranking,
                 dev_trace_sha256=digest(output / 'dev/traces.jsonl'),
                 embedding_run_sha256=read_json(output / 'ingestion.json')['embedding_run_sha256'],
                 selected_at=datetime.now(timezone.utc).isoformat())
    write_json(output / 'selection.json', value)
    print(f'Frozen selection from dev: {value["selected_strategy"]}. Test may now be evaluated.')
