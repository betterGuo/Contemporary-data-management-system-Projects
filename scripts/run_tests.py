"""Run tests and write real scenario coverage and results, including parameterized cases."""
from pathlib import Path
import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import sys
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest


class Evidence:
    def __init__(self):
        self.cases = {}
        self.results = []
        self.collection_errors = []
        self.collected = 0

    def pytest_collection_modifyitems(self, items):
        for item in items:
            self.cases[item.nodeid] = [case for marker in item.iter_markers("case") for case in marker.args]

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed or report.skipped:
            self.results.append({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome, "durationSeconds": round(report.duration, 6), "cases": self.cases.get(report.nodeid, [])})

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append({"nodeid": report.nodeid, "error": str(report.longrepr)})

    def pytest_sessionfinish(self, session):
        self.collected = session.testscollected


class Tee:
    def __init__(self, original, output):
        self.original, self.output = original, output

    def write(self, value):
        self.output.write(value)
        return self.original.write(value)

    def flush(self):
        self.output.flush()
        self.original.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


def run(output, pytest_args=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / name for name in ("pytest.xml", "pytest-output.txt", "test-results.json", ".run-started")]
    if any(path.exists() for path in paths):
        raise FileExistsError("测试输出目录已有结果或运行记录，请指定新的 --output-dir。")
    # Exclusive creation also prevents two processes from using the same output.
    with paths[3].open("x") as started:
        started.write(datetime.now(timezone.utc).isoformat() + "\n")
    started_at = datetime.now(timezone.utc)
    evidence = Evidence()
    args = ["tests", "-q", "--junitxml=" + str(paths[0]), *(pytest_args or [])]
    with paths[1].open("x") as transcript:
        with redirect_stdout(Tee(sys.stdout, transcript)), redirect_stderr(Tee(sys.stderr, transcript)):
            status = pytest.main(args, plugins=[evidence])
    ended_at = datetime.now(timezone.utc)
    by_node = {}
    priority = {"passed": 0, "skipped": 1, "failed": 2}
    for row in evidence.results:
        previous = by_node.get(row["nodeid"])
        if previous is None or priority[row["outcome"]] > priority[previous]:
            by_node[row["nodeid"]] = row["outcome"]
    covered = sorted({case for row in evidence.results if by_node[row["nodeid"]] == "passed" for case in row["cases"]})
    required = {f"T{index:02d}" for index in range(1, 89)} | {f"E{index:02d}" for index in range(1, 5)}
    result = {
        "startedAt": started_at.isoformat(), "executedAt": ended_at.isoformat(),
        "durationSeconds": round((ended_at-started_at).total_seconds(), 3),
        "invocation": "pytest.main(args, plugins=[Evidence()])", "args": args,
        "exitCode": int(status), "collectedTests": evidence.collected,
        "summary": {state: sum(outcome == state for outcome in by_node.values()) for state in ("passed", "failed", "skipped")},
        "collectionErrors": evidence.collection_errors,
        "coveredCases": covered, "uncoveredCases": sorted(required-set(covered)),
        "results": evidence.results,
    }
    with paths[2].open("x") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"summary": result["summary"], "exitCode": int(status), "output": str(output), "collectionErrors": len(evidence.collection_errors), "uncoveredCases": result["uncoveredCases"]}, ensure_ascii=False))
    return int(status)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    options, extra = parser.parse_known_args()
    default = root / "docs" / "evidence" / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    raise SystemExit(run(options.output_dir or default, extra))
