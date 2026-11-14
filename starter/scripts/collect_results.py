"""Summarize measured retrieval, storage and source-review outputs."""
from pathlib import Path
from statistics import mean, median
import json
import os
import psycopg
from dotenv import load_dotenv

root=Path(__file__).resolve().parents[2]
current=json.loads((root/'artifacts/current_prepared.json').read_text())
prepared=json.loads((root/current['path']/'prepared.json').read_text())
results=root/'results'/current['prepared_id']
ingestion=json.loads((results/'ingestion.json').read_text())
protocol=json.loads((root/'benchmark/protocol.json').read_text())
audit_method_path=results/'audits/method.json'
audit_method=json.loads(audit_method_path.read_text()) if audit_method_path.exists() else None
audit_summary_path=results/'manual_audit_summary.json'
audit_summary=json.loads(audit_summary_path.read_text()) if audit_summary_path.exists() else None
load_dotenv(root/'starter/.env')
with psycopg.connect(os.environ['DATABASE_URL']) as connection:
    version=connection.execute("SELECT current_setting('server_version'),extversion FROM pg_extension WHERE extname='vector'").fetchone()
metrics={};traces=[]
for split in ('dev','test'):
    path=results/split/'metrics.json'
    metrics[split]=json.loads(path.read_text()) if path.exists() else []
    if metrics[split]:
        traces += [json.loads(line) for line in (results/split/'traces.jsonl').read_text().splitlines()]
summary={
 'prepared_id':current['prepared_id'],
 'source_content_pages':prepared['corpus_pages'],
 'postgresql_version':version[0],'pgvector_version':version[1],
 'model':prepared['config']['model'],
 'backend':ingestion['embedding_run']['device'],
 'preprocessing_seconds':prepared['preprocessing_seconds'],
 'semantic_chunking':prepared.get('semantic_chunking',{}),
 'model_loading_seconds':ingestion['embedding_run']['load_seconds'],
 'embedding_seconds':ingestion['embedding_run']['embedding_seconds'],
 'token_statistics':ingestion['embedding_run']['token_statistics'],
 'database_import_and_reload':ingestion['database_import'],
 'chunk_statistics':prepared['chunk_statistics'],
 'retrieval_metrics':metrics,
 'retrieval_scoring':'Source/page plus full normalized primary or alternative quote. Gold authoring and any additional evidence reviews are disclosed separately.',
 'selected_on_dev':json.loads((results/'selection.json').read_text())['selected_strategy'],
 'benchmark_version':protocol.get('benchmark_version',1),
 'test_status':'completed' if metrics['test'] else 'not_run',
 'previous_test_ids_moved_to_dev':protocol.get('revision',{}).get('previous_test_ids',[]),
 'strategy_extension':protocol.get('strategy_extension'),
 'lookup_latency':{},
 'cost':{'compute_service_usd':ingestion['embedding_run']['service_cost'],'excludes':'Electricity, hardware and network'},
 'manual_audit_status':audit_method['status'] if audit_method else 'Human evaluation not completed.',
 'audit_method':audit_method,
 'source_review_summary':audit_summary,
 'retrieval_misses':[{'strategy':t['strategy'],'split':t['split'],'id':t['id']} for t in traces if not t['hit3']],
 'limitations':['Five test questions with primary evidence from Post-Stroke Rehabilitation (2020), also used in dev; limited source coverage and a shared benchmark/review process restrict generalization.',
                'A/B differ in chunking method and overlap. B/C isolate filtering with identical chunks and embeddings. B/D compare sentence/paragraph and semantic boundaries at the same 500-character cap and zero overlap.',
                'Semantic preprocessing adds source-window embedding work; its measured time is separate from retrieval-chunk embedding time. Regex sentence boundaries and hard size limits can still split context.',
                'Lookup timings use precomputed benchmark query vectors and exclude query encoding.']}
for s in prepared['config']['strategies']:
    timings=[t['search_seconds'] for t in traces if t['strategy']==s]
    summary['lookup_latency'][s]={'n':len(timings),'mean_seconds':mean(timings),'median_seconds':median(timings),'max_seconds':max(timings),'includes_query_encoding':False}
(results/'comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ('prepared_id','embedding_seconds','lookup_latency','selected_on_dev','manual_audit_status')},indent=2))
