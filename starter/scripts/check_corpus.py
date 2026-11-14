"""Read-only corpus checks for Checkpoint 1; does not open benchmark questions."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ingestion import load_corpus


def check_corpus(root: Path) -> dict:
    manifest = json.loads((root / 'data/manifest.json').read_text())
    pages, issues = load_corpus(root)
    by_page = {(page.document_id, page.page): page for page in pages}
    documents = manifest['documents']
    if len({doc['document_id'] for doc in documents}) != len(documents):
        raise ValueError('Duplicate document IDs in manifest.')
    physical_count = 0
    for document in documents:
        for field in ('source_id', 'title', 'source_url', 'license_or_permission', 'accessed_at'):
            if not document[field]:
                raise ValueError(f'Missing {field}: {document["document_id"]}')
        selected = set(document['selected_pages'])
        excluded = {int(number) for number in document['excluded_pages']}
        physical = set(range(1, document['physical_page_count'] + 1))
        if len(selected) != len(document['selected_pages']) or selected & excluded or selected | excluded != physical:
            raise ValueError(f'Page accounting mismatch: {document["document_id"]}')
        if any(not reason.strip() for reason in document['excluded_pages'].values()):
            raise ValueError(f'Missing excluded-page reason: {document["document_id"]}')
        if set(document['page_character_counts']) != {str(number) for number in selected}:
            raise ValueError(f'Character-count page IDs mismatch: {document["document_id"]}')
        for number in selected:
            if len(by_page[document['document_id'], number].text) != document['page_character_counts'][str(number)]:
                raise ValueError(f'Character count mismatch: {document["document_id"]}:{number}')
        physical_count += len(physical)
    actual = dict(document_count=len(documents), physical_page_count=physical_count,
                  eligible_content_page_count=len(pages), normalized_char_count=sum(len(page.text) for page in pages))
    if manifest['summary'] != actual:
        raise ValueError('Manifest summary does not match extracted corpus.')
    return dict(status='PASS', **actual, extraction_issues=issues,
                scope='Checks PDF integrity, extraction and manifest accounting; content relevance and permissions require source review.')


if __name__ == '__main__':
    try:
        print(json.dumps(check_corpus(Path(__file__).resolve().parents[2]), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f'{type(error).__name__}: {error}') from None
