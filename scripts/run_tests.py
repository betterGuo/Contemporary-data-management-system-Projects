"""Run tests and write real scenario coverage and results, including parameterized cases."""
from pathlib import Path
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest


class Evidence:
    def __init__(self):
        self.cases = {}
        self.results = []

    def pytest_collection_modifyitems(self, items):
        for item in items:
            self.cases[item.nodeid] = [case for marker in item.iter_markers("case") for case in marker.args]

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when in {"setup", "teardown"} and report.failed):
            self.results.append({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome, "durationSeconds": round(report.duration, 6), "cases": self.cases.get(report.nodeid, [])})


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    output = root / "docs" / "evidence" / "stage1"
    output.mkdir(parents=True, exist_ok=True)
    evidence = Evidence()
    status = pytest.main(["tests", "-q", "--junitxml=" + str(output / "pytest.xml")], plugins=[evidence])
    covered = sorted({case for row in evidence.results if row["outcome"] == "passed" for case in row["cases"]})
    required = {f"T{index:02d}" for index in range(1,89)} | {f"E{index:02d}" for index in range(1,5)}
    result = {"executedAt": datetime.now(timezone.utc).isoformat(), "exitCode": int(status), "summary": {state: sum(row["outcome"] == state for row in evidence.results) for state in ["passed", "failed", "skipped"]}, "coveredCases": covered, "uncoveredCases": sorted(required-set(covered)), "results": evidence.results}
    (output / "test-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"summary": result["summary"], "uncoveredCases": result["uncoveredCases"]}, ensure_ascii=False))
    raise SystemExit(status)
