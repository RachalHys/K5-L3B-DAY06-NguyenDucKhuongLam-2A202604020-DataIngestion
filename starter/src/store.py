"""Persistent, exact cosine retrieval in PostgreSQL/pgvector; no fallback store."""
import math
import re
from typing import Any
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from .models import Chunk

FILTER_TYPES = {'publication_year': int, 'document_type': str, 'topic': str}


def validate_filters(filters: dict | None) -> dict:
    filters = filters or {}
    for key, value in filters.items():
        if key not in FILTER_TYPES or type(value) is not FILTER_TYPES[key]:
            raise ValueError(f'Unsupported filter or value type: {key}')
    return filters


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, table: str = 'stroke_chunks') -> None:
        if dimensions < 1 or not re.fullmatch(r'[a-z][a-z0-9_]*', table):
            raise ValueError('Invalid dimensions or SQL table name.')
        self.database_url, self.dimensions = database_url, dimensions
        self.table = sql.Identifier(table)
        self.table_name = table

    def _vector(self, vector) -> str:
        values = [float(x) for x in vector]
        if len(values) != self.dimensions or not all(math.isfinite(x) for x in values) or not any(values):
            raise ValueError('Vector has wrong dimensions, non-finite values, or zero norm.')
        return '[' + ','.join(map(str, values)) + ']'

    def create_schema(self) -> None:
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            connection.execute(sql.SQL('''CREATE TABLE IF NOT EXISTS {} (
                strategy text NOT NULL, chunk_id text NOT NULL, text text NOT NULL,
                metadata jsonb NOT NULL, embedding vector({}),
                PRIMARY KEY (strategy, chunk_id))''').format(self.table, sql.Literal(self.dimensions)))
            row = connection.execute('SELECT format_type(a.atttypid,a.atttypmod) FROM pg_attribute a '
                                     'WHERE a.attrelid = %s::regclass AND a.attname = %s',
                                     (self.table_name, 'embedding')).fetchone()
            if row[0] != f'vector({self.dimensions})':
                raise ValueError('Existing table uses different vector dimensions; use a separate table.')

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors) or len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError('Chunk/vector count mismatch or duplicate chunk IDs.')
        encoded = [self._vector(v) for v in vectors]
        rows = [(strategy, c.chunk_id, c.text,
                 Jsonb(dict(c.metadata, document_id=c.document_id, source=c.source, page=c.page)), v)
                for c, v in zip(chunks, encoded)]
        # Replace the strategy snapshot atomically, including chunks removed by document updates.
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            connection.execute(sql.SQL('DELETE FROM {} WHERE strategy = %s').format(self.table), (strategy,))
            with connection.cursor() as cursor:
                cursor.executemany(sql.SQL('INSERT INTO {} VALUES (%s,%s,%s,%s,%s::vector)').format(self.table), rows)

    def count(self, strategy: str) -> int:
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            return connection.execute(sql.SQL('SELECT count(*) FROM {} WHERE strategy=%s').format(self.table),
                                      (strategy,)).fetchone()[0]

    def snapshot_ids(self, strategy: str) -> set[str]:
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            rows = connection.execute(sql.SQL('SELECT chunk_id FROM {} WHERE strategy=%s').format(self.table), (strategy,))
            return {r[0] for r in rows}

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if top_k < 1:
            raise ValueError('top_k must be positive.')
        vector = self._vector(query_vector)
        conditions = [sql.SQL('strategy = %s')]
        parameters = [vector, strategy]
        for key, value in validate_filters(filters).items():
            conditions.append(sql.SQL('metadata ->> %s = %s'))
            parameters.extend([key, str(value)])
        query = sql.SQL('''SELECT chunk_id,text,metadata,1-(embedding <=> %s::vector) AS score
            FROM {} WHERE {} ORDER BY embedding <=> %s::vector,chunk_id LIMIT %s''').format(
                self.table, sql.SQL(' AND ').join(conditions))
        parameters.extend([vector, top_k])
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(chunk_id=r[0], text=r[1], metadata=r[2], score=r[3]) for r in rows]
