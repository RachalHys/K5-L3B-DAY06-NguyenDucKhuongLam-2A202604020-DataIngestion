"""Copy actual retrieval counts into the experiment log; keep unrun splits blank."""
from pathlib import Path
import csv
import json

root=Path(__file__).resolve().parents[2]
current=json.loads((root/'artifacts/current_prepared.json').read_text())
config=json.loads((root/'configs/lab.json').read_text())
results=root/'results'/current['prepared_id']
path=root/'artifacts/experiment_log.csv'
with path.open(newline='') as f:
    reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
for row in rows:
    for split in ('dev','test'):
        metrics=results/split/'metrics.json'
        if metrics.exists():
            metric=next(r for r in json.loads(metrics.read_text()) if r['strategy']==row['strategy'])
            row[f'{split}_hit1']=f"{metric['hit1_n']}/{metric['n']}"
            row[f'{split}_hit3']=f"{metric['hit3_n']}/{metric['n']}"
        else:
            row[f'{split}_hit1']=''
            row[f'{split}_hit3']=''
    backing=config['strategies'][row['strategy']].get('chunks_from')
    row['notes']=f"Reuses {backing} vectors." if backing else ''
with path.open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
print('Experiment log synchronized from saved metrics.')
