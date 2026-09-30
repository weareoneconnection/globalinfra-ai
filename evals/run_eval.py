import json
from pathlib import Path

path = Path(__file__).parent / 'datasets' / 'cases.jsonl'
rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
# V1 deterministic smoke evaluation. Replace with live API/model regression as implementation grows.
passed = sum(1 for r in rows if r.get('expected_type') and r.get('expected_risk'))
print(json.dumps({"dataset":"cases","total":len(rows),"schema_valid":passed,"schema_pass_rate":passed/len(rows)}, indent=2))
