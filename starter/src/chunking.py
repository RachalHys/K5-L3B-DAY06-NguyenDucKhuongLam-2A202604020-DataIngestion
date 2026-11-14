"""Fixed, paragraph/sentence and semantic chunks, always within one page."""
import hashlib
import re
from .models import Chunk, DocumentPage


def _chunk(page: DocumentPage, start: int, end: int) -> Chunk:
    text = page.text[start:end]
    identity = f'{page.document_id}:{page.page}:{start}:{end}:{text}'
    chunk_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return Chunk(chunk_id, page.document_id, page.source, page.page, text,
                 dict(page.metadata, document_id=page.document_id, source=page.source,
                      page=page.page, start_char=start, end_char=end))


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError('Require size > overlap >= 0.')
    chunks = []
    for start in range(0, len(page.text), size - overlap):
        end = min(start + size, len(page.text))
        if page.text[start:end].strip():
            chunks.append(_chunk(page, start, end))
        if end == len(page.text):
            break
    return chunks


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    if max_size < 1:
        raise ValueError('max_size must be positive.')
    chunks = []
    start = 0
    while start < len(page.text):
        while start < len(page.text) and page.text[start].isspace():
            start += 1
        if start == len(page.text):
            break
        limit = min(start + max_size, len(page.text))
        end = limit
        if limit < len(page.text) and not (
            page.text[limit - 1] in '.!?' and page.text[limit].isspace()
        ):
            window = page.text[start:limit]
            paragraphs = [m.start() for m in re.finditer(r'\n\n', window) if m.start() > 0]
            sentences = [m.start() for m in re.finditer(r'(?<=[.!?])\s+', window) if m.start() > 0]
            words = [m.start() for m in re.finditer(r'\s+', window) if m.start() > 0]
            boundaries = paragraphs or sentences or words
            if boundaries:
                end = start + boundaries[-1]
        while end > start and page.text[end - 1].isspace():
            end -= 1
        if end == start:
            end = limit
        chunks.append(_chunk(page, start, end))
        start = end
    return chunks


def sentence_spans(page: DocumentPage, max_size: int) -> list[tuple[int, int]]:
    """Keep source offsets; divide unusually long sentences at word boundaries."""
    boundaries = [0] + [m.end() for m in re.finditer(r'(?<=[.!?])\s+|\n\s*\n', page.text)] + [len(page.text)]
    spans = []
    for start, end in zip(boundaries, boundaries[1:]):
        while start < end and page.text[start].isspace():
            start += 1
        while end > start and page.text[end - 1].isspace():
            end -= 1
        if start == end:
            continue
        part = DocumentPage(page.document_id, page.source, page.page, page.text[start:end])
        spans.extend((start + c.metadata['start_char'], start + c.metadata['end_char'])
                     for c in by_paragraph(part, max_size))
    return spans


def by_semantic(page: DocumentPage, spans: list[tuple[int, int]], distances: list[float],
                threshold: float, max_size: int, min_size: int) -> list[Chunk]:
    if max_size < 1 or not 0 < min_size <= max_size or len(distances) != max(0, len(spans) - 1):
        raise ValueError('Invalid semantic size limits or sentence-distance alignment.')
    if not spans:
        return []
    chunks = []
    start, end = spans[0]
    for i, (next_start, next_end) in enumerate(spans[1:]):
        if next_end - start > max_size or (distances[i] > threshold and end - start >= min_size):
            chunks.append(_chunk(page, start, end))
            start = next_start
        end = next_end
    chunks.append(_chunk(page, start, end))
    return chunks
