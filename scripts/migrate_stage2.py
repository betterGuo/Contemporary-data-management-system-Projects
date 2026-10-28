"""Explicit, resumable question-library migration. Dry-run is the default."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect, initialize_database
from app.services.library_migration import migrate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri")
    parser.add_argument("--database")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        raise FileExistsError("迁移报告已存在，请使用新文件名。")
    settings = Settings()
    with connect(args.uri or settings.mongodb_uri) as client:
        db = client[args.database or settings.mongodb_db]
        if args.apply:
            hello = client.admin.command("hello")
            if not hello.get("setName") and hello.get("msg") != "isdbgrid":
                raise RuntimeError("正式迁移需要副本集；拒绝对原单机库执行。")
            initialize_database(db)
        report = migrate(db, datetime.now(timezone.utc), apply=args.apply)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
