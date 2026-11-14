"""Versioned corpus preparation and embedding execution."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import importlib.metadata
import json
import platform
import statistics
import time
import numpy as np
from .chunking import fixed_size, by_paragraph
from .evaluation import canonical, gold_evidence
from .ingestion import load_corpus
from .store import validate_filters


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))


def read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def chunk_backing(config: dict, strategy: str) -> str:
    return config['strategies'][strategy].get('chunks_from', strategy)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def validate_benchmark(questions: list[dict], pages: list) -> None:
    by_page = {(p.document_id, p.page): p for p in pages}
    if len(questions) < 20 or len({q['id'] for q in questions}) != len(questions):
        raise ValueError('Require at least 20 questions with unique IDs.')
    for split, minimum in [('dev', 15), ('test', 5)]:
        if sum(q['split'] == split for q in questions) < minimum:
            raise ValueError(f'Insufficient {split} questions.')
    if sum(bool(q.get('filter')) for q in questions) < 3 or not any(q.get('filter') for q in questions if q['split'] == 'test'):
        raise ValueError('Require three filter questions including at least one in test.')
    for q in questions:
        if q['split'] not in ('dev', 'test') or not q['question'] or not q['expected_answer']:
            raise ValueError(f'Invalid benchmark question: {q["id"]}')
        filters = validate_filters(q.get('filter'))
        for gold in gold_evidence(q):
            source = by_page.get((gold['source_id'], gold['page']))
            if source is None or not gold['quote'] or canonical(gold['quote']) not in canonical(source.text):
                raise ValueError(f'Gold evidence missing from normalized source: {q["id"]}')
            if any(source.metadata.get(k) != v for k, v in filters.items()):
                raise ValueError(f'Gold evidence violates question filter: {q["id"]}')


def prepare(root: Path) -> dict:
    started = time.perf_counter()
    config = read_json(root / 'configs/lab.json')
    if config['strategies']['A']['chunking'] != 'fixed' or config['strategies']['B']['chunking'] != 'paragraph_sentence' or config['strategies']['C'] != {'chunks_from': 'B', 'filters': True}:
        raise ValueError('This experiment requires A=fixed, B=paragraph/sentence, C=B plus filters.')
    for strategy, settings in config['strategies'].items():
        if type(settings['filters']) is not bool:
            raise ValueError(f'{strategy}: filters must be boolean.')
        if 'chunks_from' in settings:
            backing = settings['chunks_from']
            if backing not in config['strategies'] or 'chunks_from' in config['strategies'][backing]:
                raise ValueError(f'{strategy}: chunks_from must name a direct chunk configuration.')
        elif settings['chunking'] not in ('fixed', 'paragraph_sentence', 'semantic'):
            raise ValueError(f'{strategy}: unsupported chunking method.')
        elif settings['chunking'] in ('paragraph_sentence', 'semantic') and settings['overlap'] != 0:
            raise ValueError(f'{strategy}: paragraph/sentence and semantic chunking use zero overlap.')
        if settings.get('chunking') == 'semantic' and not (
            0 < settings['breakpoint_percentile'] < 100
            and 0 < settings['min_chunk_size'] <= settings['chunk_size']
            and type(settings['buffer_size']) is int and settings['buffer_size'] >= 0
        ):
            raise ValueError(f'{strategy}: invalid semantic threshold, minimum size or buffer.')
    if config['retrieval'] != {'top_k': 3, 'metric': 'cosine', 'search': 'exact'}:
        raise ValueError('The frozen retrieval protocol requires exact cosine top-3.')
    if config['selection_rule'] != ['dev_evidence_hit3_desc', 'dev_hit1_desc', 'chunk_count_asc', 'strategy_id_asc']:
        raise ValueError('Unsupported selection rule; implementation and protocol must agree.')
    questions = read_json(root / 'benchmark/questions.json')
    pages, issues = load_corpus(root)
    validate_benchmark(questions, pages)
    input_paths = ['configs/lab.json', 'data/manifest.json', 'benchmark/questions.json', 'benchmark/protocol.json']
    inputs = {name: digest(root / name) for name in input_paths}
    # Freeze the implementation too: changing code creates a new prepared study.
    inputs.update({str(p.relative_to(root)): digest(p) for p in sorted((root / 'starter/src').glob('*.py'))})
    prepared_id = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:20]
    output = root / 'artifacts/prepared' / prepared_id
    if (output / 'prepared.json').exists():
        existing = load_prepared(root, output)[0]
        write_json(root / 'artifacts/current_prepared.json', {'path': str(output.relative_to(root)), 'prepared_id': prepared_id})
        return existing
    strategies = {}
    stats = {}
    semantic_runs = {}
    for strategy, settings in config['strategies'].items():
        if 'chunks_from' in settings:
            continue
        if settings['chunking'] == 'semantic':
            from .semantic import build_semantic_chunks
            chunks, run, vectors = build_semantic_chunks(pages, settings, config['model'])
            semantic_runs[strategy] = (run, vectors)
        else:
            chunks = []
            for page in pages:
                chunks.extend(fixed_size(page, settings['chunk_size'], settings['overlap']) if settings['chunking'] == 'fixed'
                              else by_paragraph(page, settings['chunk_size']))
        strategies[strategy] = chunks
        sizes = [len(c.text) for c in chunks]
        stats[strategy] = dict(chunk_count=len(chunks), total_characters=sum(sizes),
                               min_characters=min(sizes), max_characters=max(sizes),
                               median_characters=statistics.median(sizes),
                               p95_characters=float(np.percentile(sizes, 95)))
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / 'pages.jsonl', [asdict(p) for p in pages])
    for strategy, chunks in strategies.items():
        write_jsonl(output / f'chunks_{strategy}.jsonl', [asdict(c) for c in chunks])
    # No gold answers, evidence, or gold source IDs are transported to the encoder.
    write_jsonl(output / 'queries.jsonl', [{k: q[k] for k in ('id', 'split', 'question', 'filter')} for q in questions])
    write_json(output / 'extraction_issues.json', issues)
    semantic_summary = {}
    for strategy, (run, vectors) in semantic_runs.items():
        vector_path = output / f'semantic_{strategy}.npz'
        np.savez_compressed(vector_path, vectors=vectors)
        run['vectors_sha256'] = digest(vector_path)
        write_json(output / f'semantic_{strategy}.json', run)
        semantic_summary[strategy] = {k: run[k] for k in
            ('threshold', 'distance_count', 'token_statistics', 'model_loading_seconds', 'embedding_seconds', 'total_seconds', 'service_cost')}
    samples = []
    for i, page in enumerate(sorted(pages, key=lambda p: (p.document_id, p.page))[:10], 1):
        position = len(page.text) // 2
        while position < len(page.text) - 1 and page.text[position].isspace():
            position += 1
        for strategy in config['strategies']:
            backing = chunk_backing(config, strategy)
            chunk = next(c for c in strategies[backing] if c.document_id == page.document_id and c.page == page.page
                         and c.metadata['start_char'] <= position < c.metadata['end_char'])
            samples.append(dict(sample_id=f's{i:02}', strategy=strategy, document_id=page.document_id,
                                page=page.page, anchor_char=position, chunk_id=chunk.chunk_id, text=chunk.text,
                                score='', reason='', reviewer=''))
    write_csv(output / 'coherence.csv', list(samples[0]), samples)
    state = dict(prepared_id=prepared_id, config=config, input_hashes=inputs,
                 corpus_pages=len(pages), corpus_characters=sum(len(p.text) for p in pages),
                 question_counts={s: sum(q['split'] == s for q in questions) for s in ('dev', 'test')},
                 chunk_statistics={s: dict(stats[chunk_backing(config, s)]) for s in config['strategies']},
                 semantic_chunking=semantic_summary,
                 preprocessing_seconds=time.perf_counter() - started,
                 files={p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
                 created_at=datetime.now(timezone.utc).isoformat())
    write_json(output / 'prepared.json', state)
    write_json(root / 'artifacts/current_prepared.json', {'path': str(output.relative_to(root)), 'prepared_id': prepared_id})
    return state


def load_prepared(root: Path, directory: Path | None = None, verify_inputs: bool = True):
    directory = directory or root / read_json(root / 'artifacts/current_prepared.json')['path']
    state = read_json(directory / 'prepared.json')
    for name, expected in state['files'].items():
        if digest(directory / name) != expected:
            raise ValueError(f'Prepared file changed: {name}; regenerate the study.')
    if verify_inputs:
        for name, expected in state['input_hashes'].items():
            if digest(root / name) != expected:
                raise ValueError(f'Study input changed: {name}; run prepare again.')
    return state, directory


def embed(root: Path, output: Path, prepared: Path | None, device: str, cost: float | None) -> None:
    from .embeddings import MyEmbedder
    import torch
    state, directory = load_prepared(root, prepared, verify_inputs=False)
    config = state['config']['model']
    torch.set_num_threads(4)
    started = time.perf_counter()
    encoder = MyEmbedder(config['name'], config['revision'], device, config['max_tokens'], config['precision'], config['batch_size'])
    load_seconds = time.perf_counter() - started
    if encoder.dimensions != config['dimensions']:
        raise ValueError('Model dimensions do not match the frozen configuration.')
    arrays, ids, times, token_stats = {}, {}, {}, {}
    keys = [s for s, settings in state['config']['strategies'].items() if 'chunks_from' not in settings]
    for key in keys + ['queries']:
        rows = read_jsonl(directory / ('queries.jsonl' if key == 'queries' else f'chunks_{key}.jsonl'))
        texts = [r['question' if key == 'queries' else 'text'] for r in rows]
        lengths = [len(v) for v in encoder.model.tokenizer(texts, truncation=False, padding=False)['input_ids']]
        token_stats[key] = dict(total_tokens=sum(lengths), maximum_tokens=max(lengths), count=len(lengths))
        if max(lengths) > config['max_tokens']:
            raise ValueError(f'{key} exceeds the token limit; repair chunking before encoding.')
        started = time.perf_counter()
        arrays[key] = np.asarray(encoder.embed_documents(texts), dtype=np.float32)
        if device == 'cuda':
            torch.cuda.synchronize()
        times[key] = time.perf_counter() - started
        ids[key] = [r['id' if key == 'queries' else 'chunk_id'] for r in rows]
        arrays['ids_' + key] = np.asarray(ids[key], dtype=str)
        print(f'{key}: encoded {len(rows)} rows in {times[key]:.2f}s', flush=True)
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / 'vectors.npz', **arrays)
    packages = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
    metadata = dict(prepared_id=state['prepared_id'], model=config, device=device,
                    device_name=torch.cuda.get_device_name(0) if device == 'cuda' else platform.processor() or platform.machine(),
                    python=platform.python_version(), packages=packages, load_seconds=load_seconds,
                    embedding_seconds=times, token_statistics=token_stats,
                    torch_cuda_version=torch.version.cuda,
                    cpu_threads=torch.get_num_threads(),
                    peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated() if device == 'cuda' else None,
                    service_cost=0.0 if device == 'cpu' and cost is None else cost,
                    currency='USD', cost_scope='Compute service only; excludes electricity, hardware and network.',
                    vectors_sha256=digest(output / 'vectors.npz'),
                    created_at=datetime.now(timezone.utc).isoformat())
    write_json(output / 'embedding_run.json', metadata)
    print(f'Embeddings and measured run metadata saved to {output}')


def validate_embedding_output(state: dict, directory: Path, output: Path):
    metadata = read_json(output / 'embedding_run.json')
    if metadata['prepared_id'] != state['prepared_id'] or metadata['model'] != state['config']['model']:
        raise ValueError('Embedding identity/settings mismatch; refusing incompatible vectors.')
    if digest(output / 'vectors.npz') != metadata['vectors_sha256']:
        raise ValueError('Embedding checksum mismatch.')
    vectors = {}
    with np.load(output / 'vectors.npz', allow_pickle=False) as archive:
        keys = [s for s, settings in state['config']['strategies'].items() if 'chunks_from' not in settings]
        for key in keys + ['queries']:
            rows = read_jsonl(directory / ('queries.jsonl' if key == 'queries' else f'chunks_{key}.jsonl'))
            expected = [r['id' if key == 'queries' else 'chunk_id'] for r in rows]
            if archive['ids_' + key].tolist() != expected:
                raise ValueError(f'Vector row order/IDs mismatch: {key}')
            values = archive[key]
            if values.shape != (len(expected), state['config']['model']['dimensions']) or values.dtype != np.float32:
                raise ValueError(f'Invalid vector shape/type: {key}')
            if not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=0.005):
                raise ValueError(f'Invalid/non-normalized vectors: {key}')
            vectors[key] = values
    return metadata, vectors
