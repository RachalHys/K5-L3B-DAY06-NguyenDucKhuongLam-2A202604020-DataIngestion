"""Restore original PDFs from the manifest without replacing mismatched files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from urllib.request import Request, urlopen


def fetch_document(root: Path, document: dict, verify_only: bool = False) -> str:
    target = root / document['source_path_or_url']
    expected = document['sha256']
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Checksum mismatch: {target}; existing file was not replaced.')
        return 'verified'
    if verify_only:
        raise FileNotFoundError(f'Missing PDF: {target}; run again without --verify-only to download.')

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.part', delete=False) as handle:
        temporary = Path(handle.name)
        try:
            request = Request(document['source_url'], headers={'User-Agent': 'Day06-DataIngestionLab/1.0'})
            with urlopen(request, timeout=60) as response:
                shutil.copyfileobj(response, handle)
            handle.flush()
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
                raise ValueError(f'Download checksum mismatch: {document["source_id"]}; manifest unchanged.')
            handle.close()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return 'downloaded and verified'


def main() -> None:
    parser = argparse.ArgumentParser(description='Download missing corpus PDFs and verify every SHA-256.')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--verify-only', action='store_true', help='Check local files without network access.')
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        manifest = json.loads((root / 'data/manifest.json').read_text())
        for document in manifest['documents']:
            status = fetch_document(root, document, args.verify_only)
            print(f'{document["source_id"]}: {status}')
    except (OSError, ValueError) as error:
        raise SystemExit(f'{type(error).__name__}: {error}') from None
    print(f'Corpus files OK: {len(manifest["documents"])} PDFs match the manifest.')


if __name__ == '__main__':
    main()
