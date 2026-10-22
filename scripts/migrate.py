"""Small explicit migration entry point and an isolated extension exercise."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect, initialize_database, utcnow


def run_example(db, *, apply=False):
    if not db.name.startswith("survey_project1_test_"):
        raise ValueError("示例迁移仅允许运行在 survey_project1_test_ 隔离库")
    count = db.surveys.count_documents({"displayHint": {"$exists": False}})
    modified = 0
    if apply:
        modified = db.surveys.update_many({"displayHint": {"$exists": False}}, {"$set": {"displayHint": ""}}).modified_count
        db.schema_migrations.update_one({"_id": "exercise_optional_display_hint"}, {"$setOnInsert": {"appliedAt": utcnow(), "exerciseOnly": True}}, upsert=True)
    return {"dryRun": not apply, "wouldUpdate": count, "modified": modified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    parser.add_argument("--apply", action="store_true", help="apply; default is read-only dry-run")
    parser.add_argument("--example", action="store_true", help="isolated E03 exercise, never a formal week-two requirement")
    args = parser.parse_args()
    settings = Settings()
    with connect(settings.mongodb_uri) as client:
        db = client[args.database or settings.mongodb_db]
        if args.example:
            print(run_example(db, apply=args.apply))
        elif args.apply:
            initialize_database(db)
            print("001_initial applied idempotently; existing data preserved.")
        else:
            print({"database": db.name, "migration": "001_initial", "applied": db.schema_migrations.find_one({"_id": "001_initial"}) is not None, "dryRun": True})


if __name__ == "__main__":
    main()
