from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DB_DIR = PROJECT_ROOT / "db"
DB_PATH = DB_DIR / "candor.duckdb"

RAW_SCHEMA = "raw"