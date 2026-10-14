"""CI gate for the Phase 9.1 AI-outbound competition evidence suite."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))

database_file = Path(tempfile.gettempdir()) / "globalinfra_competition_eval.db"
if database_file.exists():
    database_file.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{database_file}"
os.environ.setdefault("LLM_MODE", "mock")

from app.competition import evaluate_competition_cases  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.seed import seed  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    seed(db)
    result = evaluate_competition_cases(db, include_cases=True)

print(json.dumps(result, indent=2, ensure_ascii=False))
if result["status"] != "PASSED" or result["total_cases"] != 30:
    sys.exit(1)
