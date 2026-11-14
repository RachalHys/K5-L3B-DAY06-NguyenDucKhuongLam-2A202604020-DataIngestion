"""Dense embeddings from a specified Sentence Transformers checkpoint."""
from typing import Protocol
import numpy as np


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, question: str) -> list[float]: ...


class MyEmbedder:
    def __init__(self, model_name: str, revision: str | None = None,
                 device: str = 'cpu', max_tokens: int = 512, precision: str = 'float32',
                 batch_size: int = 1) -> None:
        import torch
        from sentence_transformers import SentenceTransformer
        if device == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable; no CPU/mock fallback was performed.')
        if device == 'cpu' and precision != 'float32':
            raise ValueError('Use float32 for the explicit CPU encoding path.')
        if precision not in ('float16', 'float32'):
            raise ValueError('Unsupported inference precision.')
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, revision=revision, device=device,
                                         model_kwargs={'torch_dtype': torch.float16 if precision == 'float16' else torch.float32})
        self.model.max_seq_length = max_tokens
        self.dimensions = self.model.get_embedding_dimension()
        self.batch_size = batch_size

    def _encode(self, texts: list[str]) -> list[list[float]]:
        lengths = [len(x) for x in self.model.tokenizer(texts, truncation=False, padding=False)['input_ids']]
        if any(n > self.model.max_seq_length for n in lengths):
            raise ValueError('Input exceeds configured token limit; refusing silent truncation.')
        result = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                   show_progress_bar=False, convert_to_numpy=True)
        result = np.asarray(result, dtype=np.float32)
        if not np.isfinite(result).all():
            raise ValueError('Embedding provider returned non-finite vectors.')
        return result.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, question: str) -> list[float]:
        return self._encode([question])[0]
