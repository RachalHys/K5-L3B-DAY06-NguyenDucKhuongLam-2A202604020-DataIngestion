"""Commands for preparing, embedding and evaluating the stroke corpus."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from . import workflow


def main() -> None:
    parser = argparse.ArgumentParser(description='Stroke ingestion lab: prepare → embed → ingest → dev → select → test → audit.')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare', help='Validate corpus/gold; freeze settings; build configured chunks and source samples.')
    embed = commands.add_parser('embed', help='Encode with BGE-M3 on CPU or an available CUDA device.')
    embed.add_argument('--prepared', type=Path)
    embed.add_argument('--output', type=Path, required=True)
    embed.add_argument('--device', choices=['cpu', 'cuda'], required=True)
    embed.add_argument('--cost', type=float, help='Actual compute-service cost in USD; omit if unknown. Local CPU defaults to zero service charge.')
    ingest = commands.add_parser('ingest', help='Validate embedding identity and import into real pgvector; verify reload.')
    ingest.add_argument('--embeddings', type=Path, required=True)
    for name in ('dev', 'select', 'test', 'audit', 'summarize-audits'):
        commands.add_parser(name)
    review = commands.add_parser('review-evidence', help='Apply reviewer-supplied equivalent-evidence labels with source checks.')
    review.add_argument('--split', choices=['dev','test'], required=True)
    review.add_argument('--labels', type=Path, required=True)
    query = commands.add_parser('query', help='Encode one new question on CPU with the same BGE-M3 checkpoint; not a benchmark run.')
    query.add_argument('question')
    query.add_argument('--strategy', default='C', help='Strategy ID from configs/lab.json.')
    query.add_argument('--year', type=int)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == 'prepare':
            print(json.dumps(workflow.prepare(root), ensure_ascii=False, indent=2))
        elif args.command == 'embed':
            workflow.embed(root, args.output, args.prepared, args.device, args.cost)
        elif args.command == 'ingest':
            from .experiment import ingest
            ingest(root, args.embeddings)
        elif args.command in ('dev', 'test', 'select'):
            from .experiment import run_split, select
            select(root) if args.command == 'select' else run_split(root, args.command)
        elif args.command in ('audit', 'summarize-audits', 'review-evidence'):
            from .audits import export_audits, summarize_audits, review_evidence
            if args.command == 'audit': export_audits(root)
            elif args.command == 'summarize-audits': summarize_audits(root)
            else: review_evidence(root, args.split, args.labels)
        elif args.command == 'query':
            from .embeddings import MyEmbedder
            from .experiment import study
            import torch
            torch.set_num_threads(4)
            state, _, _, store, _, _ = study(root)
            config = state['config']['model']
            encoder = MyEmbedder(config['name'], config['revision'], 'cpu', config['max_tokens'], 'float32')
            if args.strategy not in state['config']['strategies']:
                raise ValueError(f'Unknown strategy: {args.strategy}')
            filters = {'publication_year': args.year} if state['config']['strategies'][args.strategy]['filters'] and args.year is not None else None
            print(json.dumps(store.search(args.strategy, encoder.embed_query(args.question), filters=filters), ensure_ascii=False, indent=2))
    except Exception as error:
        message = str(error)
        if os.getenv('DATABASE_URL'):
            message = message.replace(os.environ['DATABASE_URL'], '[DATABASE_URL]')
        path = root / 'results/errors.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as handle:
            handle.write(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(), command=args.command,
                                         error_type=type(error).__name__, error=message)) + '\n')
        raise SystemExit(f'{type(error).__name__}: {message}') from None


if __name__ == '__main__':
    main()
