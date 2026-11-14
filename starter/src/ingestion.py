"""Read PDF pages and preserve source locations and extraction failures."""
from pathlib import Path
import hashlib
import json
import re
import unicodedata
from pypdf import PdfReader
from .models import DocumentPage


def normalize_text(text: str) -> str:
    """Normalize Unicode and join wrapped lines; preserve blank-line paragraphs."""
    text = unicodedata.normalize('NFC', text).replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = re.split(r'\n\s*\n', text)
    return '\n\n'.join(' '.join(p.split()) for p in paragraphs if p.strip())


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    pages = []
    for number, page in enumerate(PdfReader(path).pages, 1):
        metadata = {}
        try:
            # Extract available text directly; no OCR or inferred corrections.
            text = normalize_text(page.extract_text() or '')
            if not text:
                metadata['extraction_error'] = 'empty_text'
        except Exception as error:
            text = ''
            metadata['extraction_error'] = f'{type(error).__name__}: {error}'
        pages.append(DocumentPage(document_id, source, number, text, metadata))
    return pages


def load_corpus(root: Path) -> tuple[list[DocumentPage], list[dict]]:
    manifest = json.loads((root / 'data/manifest.json').read_text())
    pages, issues = [], []
    for document in manifest['documents']:
        path = root / document['source_path_or_url']
        if hashlib.sha256(path.read_bytes()).hexdigest() != document['sha256']:
            raise ValueError(f'Source checksum mismatch: {path}')
        extracted = load_pdf(path, document['document_id'], document['source_path_or_url'])
        if len(extracted) != document['physical_page_count']:
            raise ValueError(f'Page count mismatch: {path}')
        selected = set(document['selected_pages'])
        for page in extracted:
            if 'extraction_error' in page.metadata:
                issues.append({'document_id': page.document_id, 'page': page.page,
                               'selected': page.page in selected, 'error': page.metadata['extraction_error']})
            if page.page in selected:
                if not page.text:
                    raise ValueError(f'Selected page could not be extracted: {page.document_id}:{page.page}')
                page.metadata.update({key: document[key] for key in
                                      ('publication_year', 'document_type', 'topic', 'language', 'country_context')})
                pages.append(page)
    if len(pages) < 30:
        raise ValueError('The corpus must contain at least 30 eligible content pages.')
    return pages, issues
