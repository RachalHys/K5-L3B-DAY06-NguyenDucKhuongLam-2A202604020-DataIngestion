"""Semantic boundaries from real buffered BGE-M3 sentence embeddings."""
from datetime import datetime, timezone
import time
import numpy as np
from .chunking import by_semantic, sentence_spans
from .embeddings import MyEmbedder
from .models import Chunk, DocumentPage


def build_semantic_chunks(pages: list[DocumentPage], settings: dict, model: dict) -> tuple[list[Chunk], dict, np.ndarray]:
    import torch
    torch.set_num_threads(4)
    started = time.perf_counter()
    units, texts, page_ranges, page_spans = [], [], [], []
    for page in pages:
        spans = sentence_spans(page, settings['chunk_size'])
        first = len(units)
        for i, (start, end) in enumerate(spans):
            window_start = spans[max(0, i - settings['buffer_size'])][0]
            window_end = spans[min(len(spans) - 1, i + settings['buffer_size'])][1]
            units.append(dict(document_id=page.document_id, page=page.page,
                              start_char=start, end_char=end,
                              window_start=window_start, window_end=window_end))
            texts.append(page.text[window_start:window_end])
        page_ranges.append((first, len(units)))
        page_spans.append(spans)
    load_started = time.perf_counter()
    encoder = MyEmbedder(model['name'], model['revision'], 'cpu', model['max_tokens'],
                         model['precision'], model['batch_size'])
    load_seconds = time.perf_counter() - load_started
    if encoder.dimensions != model['dimensions']:
        raise ValueError('Semantic embedding dimensions differ from the frozen model.')
    lengths = [len(tokens) for tokens in encoder.model.tokenizer(texts, truncation=False, padding=False)['input_ids']]
    if max(lengths) > model['max_tokens']:
        raise ValueError('Semantic sentence window exceeds the frozen token limit; no truncation performed.')
    encode_started = time.perf_counter()
    vectors = np.asarray(encoder.embed_documents(texts), dtype=np.float32)
    embedding_seconds = time.perf_counter() - encode_started
    distances_by_page = []
    for first, last in page_ranges:
        values = vectors[first:last]
        distances = (1 - np.clip(np.sum(values[:-1] * values[1:], axis=1), -1, 1)).tolist()
        distances_by_page.append(distances)
        for i in range(first, last):
            units[i]['tokens'] = lengths[i]
            units[i]['distance_to_next'] = distances[i - first] if i < last - 1 else None
    all_distances = [d for distances in distances_by_page for d in distances]
    threshold = float(np.percentile(all_distances, settings['breakpoint_percentile'])) if all_distances else 0.0
    chunks = []
    for page, spans, distances in zip(pages, page_spans, distances_by_page):
        chunks.extend(by_semantic(page, spans, distances, threshold,
                                  settings['chunk_size'], settings['min_chunk_size']))
    run = dict(model=model, device='cpu', cpu_threads=torch.get_num_threads(), settings=settings,
               method='Buffered sentence-window cosine distance; one corpus-wide percentile threshold; source text only.',
               sentence_segmentation='Punctuation/blank-line regex; long units split at word boundaries to respect the character cap.',
               method_reference='https://github.com/langchain-ai/langchain-experimental/blob/main/libs/experimental/langchain_experimental/text_splitter.py',
               threshold=threshold, distance_count=len(all_distances), units=units,
               token_statistics=dict(count=len(lengths), total_tokens=sum(lengths), maximum_tokens=max(lengths)),
               model_loading_seconds=load_seconds, embedding_seconds=embedding_seconds,
               total_seconds=time.perf_counter() - started,
               service_cost=0.0, cost_scope='Local CPU compute service only; excludes electricity, hardware and network.',
               created_at=datetime.now(timezone.utc).isoformat())
    print(f'Semantic: encoded {len(units)} source windows in {embedding_seconds:.2f}s; threshold={threshold:.6f}; {len(chunks)} chunks.', flush=True)
    return chunks, run, vectors
