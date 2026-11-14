"""Replay retrieval from stored vectors in a separate directory and database."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.workflow import load_prepared, validate_embedding_output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory for replay inputs and results.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    state, prepared = load_prepared(root)
    original = root / 'results' / state['prepared_id']
    ingestion = json.loads((original / 'ingestion.json').read_text())
    embeddings = root / ingestion['embedding_output']
    validate_embedding_output(state, prepared, embeddings)
    output = args.output.resolve()
    if output.is_relative_to(prepared) or output.is_relative_to(embeddings):
        raise ValueError('Choose an output directory outside the stored inputs.')
    output.mkdir(parents=True, exist_ok=False)
    for name in state['input_hashes']:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    shutil.copytree(prepared, output / 'artifacts/prepared' / state['prepared_id'])
    shutil.copytree(embeddings, output / 'artifacts/embeddings/replay')
    shutil.copyfile(root / 'artifacts/current_prepared.json', output / 'artifacts/current_prepared.json')
    load_dotenv(root / 'starter/.env')
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError('Configure DATABASE_URL in starter/.env first.')
    database = 'day06_replay_' + uuid.uuid4().hex[:12]
    replay_url = make_conninfo(database_url, dbname=database)
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    try:
        with psycopg.connect(replay_url) as connection:
            connection.execute('CREATE EXTENSION IF NOT EXISTS vector')
        env = dict(os.environ, DATABASE_URL=replay_url, PYTHONDONTWRITEBYTECODE='1')
        for command in (
            ['ingest', '--embeddings', str(output / 'artifacts/embeddings/replay')],
            ['dev'], ['select'], ['test'],
        ):
            subprocess.run([sys.executable, '-m', 'src.run', '--root', str(output), *command],
                           cwd=output / 'starter', env=env, check=True)
        replay = output / 'results' / state['prepared_id']
        for split in ('dev', 'test'):
            assert json.loads((replay / split / 'metrics.json').read_text()) == json.loads((original / split / 'metrics.json').read_text()), split
            actual = [json.loads(line) for line in (replay / split / 'traces.jsonl').read_text().splitlines()]
            expected = [json.loads(line) for line in (original / split / 'traces.jsonl').read_text().splitlines()]
            assert [(t['strategy'], t['id'], [h['chunk_id'] for h in t['hits']]) for t in actual] == [
                (t['strategy'], t['id'], [h['chunk_id'] for h in t['hits']]) for t in expected], split
        assert json.loads((replay / 'selection.json').read_text())['selected_strategy'] == json.loads((original / 'selection.json').read_text())['selected_strategy']
        print(f'Replay PASS: all dev/test metrics, top-3 IDs and selected strategy match. Results: {replay}')
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))


if __name__ == '__main__':
    main()
