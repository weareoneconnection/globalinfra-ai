from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
required = [
    'README.md', 'docker-compose.yml', 'apps/web/package.json',
    'services/api/app/main.py', 'services/api/requirements.txt',
    'packages/country-packs/my/manifest.yaml',
    'packages/domain-packs/rail/manifest.yaml',
    'workflows/owner-letter.yaml', 'docs/ARCHITECTURE.md'
]
missing = [p for p in required if not (root / p).exists()]
json.loads((root / 'apps/web/package.json').read_text())
json.loads((root / 'data/demo/owner_notice_case.json').read_text())
if missing:
    raise SystemExit(f'Missing required files: {missing}')
print('GlobalInfra AI V1.0 package structure: OK')
print(f'Root: {root}')
print(f'Files: {sum(1 for p in root.rglob("*") if p.is_file())}')
