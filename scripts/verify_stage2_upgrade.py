"""Verify original data and statistics after additive question-library migration."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bson import BSON
from app.database import connect
from scripts.backup_project import statistics_snapshot


def verify(source, target):
    counts = {}
    for name in ("users", "responses", "surveys", "survey_versions"):
        count = 0
        for original in source[name].find({}):
            restored = target[name].find_one({"_id": original["_id"]})
            assert restored is not None, f"Missing original {name} document"
            if name in ("surveys", "survey_versions"):
                assert set(restored)-set(original) <= {"questionRefs"}, "Unexpected changes to legacy survey shape"
                projected = {key: restored[key] for key in original}
                projected["schemaVersion"] = original.get("schemaVersion", 1)
                assert len(restored.get("questionRefs", [])) == len(original["questions"]), "Incomplete instance mapping"
                for ref in restored.get("questionRefs", []):
                    version = target.question_versions.find_one({"_id": ref["questionVersionId"]})
                    assert version is not None and version["questionId"] == ref["questionId"]
            else:
                projected = restored
            assert BSON.encode(projected) == BSON.encode(original), f"Legacy {name} data changed"
            count += 1
        counts[name] = count
    old_stats = statistics_snapshot(source)
    actual = {(row["surveyId"], row["definitionVersion"]): row for row in statistics_snapshot(target)}
    assert all(actual[(row["surveyId"], row["definitionVersion"])] == row for row in old_stats), "Original statistics changed"
    return {"status": "passed", "originalDocumentsVerified": counts, "originalDefinitionsStatisticsVerified": len(old_stats),
            "responseBsonPreserved": True, "legacyInstancesAndContentPreserved": True, "originalAccountBsonPreserved": True,
            "note": "Source and target are read only; additional stage-two records are allowed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-uri", default="mongodb://localhost:27017/")
    parser.add_argument("--target-uri", default="mongodb://localhost:27018/?replicaSet=survey-rs")
    parser.add_argument("--source-database", default="survey_project1")
    parser.add_argument("--target-database", default="survey_project1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("验证记录已存在，请使用新路径。")
    with connect(args.source_uri) as source, connect(args.target_uri) as target:
        result = verify(source[args.source_database], target[args.target_database])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
