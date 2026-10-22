"""Read-only checks of the seeded stage-one baseline and real MongoDB explain."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect
from app.services.statistics_service import statistics


def verify(db):
    survey = db.surveys.find_one({"demoKey": "stats"})
    if not survey:
        raise AssertionError("Run scripts/seed_demo.py first")
    result = statistics(db, survey)
    questions = {q["questionId"]: q for q in result["questions"]}
    assert result["submissionCount"] == 4
    assert result["respondentCount"] == 4
    assert [x["count"] for x in questions["stage"]["options"]] == [3, 1]
    assert [x["count"] for x in questions["places"]["options"]] == [2, 4, 2]
    from decimal import Decimal
    assert Decimal(questions["age"]["average"]) == 60
    assert {x["value"] for x in questions["comment"]["values"]} == {"甲", "乙", "丙", "丁"}
    repeated = statistics(db, db.surveys.find_one({"demoKey": "multiple"}))
    assert (repeated["submissionCount"], repeated["respondentCount"]) == (2, 1)
    index = db.responses.index_information()["single_response_per_user"]
    assert index["unique"] and index["partialFilterExpression"] == {"repeatMode": "single"}
    explain = db.surveys.find({"ownerId": survey["ownerId"]}).sort([("createdAt", -1), ("_id", -1)]).explain()
    assert "owner_recent" in json.dumps(explain, default=str)
    return {
        "status": "passed", "checks": ["four-sample counts", "zero-included decimal average", "all text contents", "distinct respondents versus submissions", "partial unique index", "owner_recent query plan"],
        "statistics": result, "multipleStatistics": repeated,
        "explain": explain, "collections": {name: db[name].count_documents({}) for name in ["users", "surveys", "responses"]},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    settings = Settings()
    with connect(settings.mongodb_uri) as client:
        result = verify(client[settings.mongodb_db])
    content = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n")
    print(json.dumps({"status": result["status"], "checks": result["checks"], "collections": result["collections"]}, ensure_ascii=False))
