"""Check the configured local embedding model; this is not a lab benchmark."""
import os
from pathlib import Path

import numpy as np
import torch
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    model_name = os.environ.get('EMBEDDING_MODEL')
    if not model_name:
        raise SystemExit('Set EMBEDDING_MODEL in starter/.env first.')

    torch.set_num_threads(4)
    model = SentenceTransformer(
        model_name, device='cpu',
        revision=os.environ.get('EMBEDDING_REVISION') or None,
    )
    documents = model.encode([
        'Sinh viên cần nộp hồ sơ trước thời hạn.',
        'The library opens at eight in the morning.',
    ], batch_size=2, normalize_embeddings=True)
    query = model.encode(['Thời hạn nộp hồ sơ là khi nào?'], normalize_embeddings=True)
    dimensions = model.get_embedding_dimension()
    if documents.shape != (2, dimensions) or query.shape != (1, dimensions):
        raise SystemExit('Unexpected document/query embedding shapes.')
    if not np.isfinite(documents).all() or not np.isfinite(query).all():
        raise SystemExit('Non-finite embedding values.')

    print(f'Model: {model_name} | device: {model.device} | dimensions: {dimensions}')
    print(f'Maximum input length: {model.max_seq_length} tokens (longer inputs are truncated).')
    print('Local multilingual document/query embedding check: PASS')


if __name__ == '__main__':
    main()
