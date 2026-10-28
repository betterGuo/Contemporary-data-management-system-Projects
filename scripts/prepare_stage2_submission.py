"""Assemble a self-contained stage-two submission without exporting local data.

Only an explicit allowlist is copied. Existing output is never overwritten.
Original project documents and historical evidence are never changed by a build.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import unquote, urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "SUBMISSION_MANIFEST.json"
CHECK_REPORT = "SUBMISSION_CHECK.json"
NOTES = Path("docs/submissions/stage2/REFERENCE_NOTES.md")
DIRECTORIES = ("app", "scripts", "tests", "deploy", "docs")
ROOT_FILES = (
    "README.md", "pyproject.toml", "requirements.lock", ".env.example", ".gitignore",
    "大作业一第一阶段.docx", "大作业一：需求变更.docx", "实验计划.md", "第二阶段执行计划.md",
)
FINAL_DOCUMENTS = (
    "output/stage2/第二阶段项目完成报告.docx", "output/stage2/第二阶段项目完成报告.pdf",
    "output/stage2/第二阶段测试用例与结果.docx", "output/stage2/第二阶段测试用例与结果.pdf",
)
IGNORED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", ".secrets", ".DS_Store"}
LINK = re.compile(r"(!?\[[^\]\n]*\])\((<[^>\n]+>|[^)\n]+)\)")
STRING_FIELDS = {
    "passwordHash", "respondentKey", "submissionKey", "payloadHash", "tokenHash",
    "csrfTokenHash", "respondent_hmac_secret", "sessionToken", "csrfToken",
    "access_token", "refresh_token",
}
SECRET_PATTERNS = {
    "password_hash": re.compile(r"\$argon2(?:id|i|d)\$v=\d+\$[mtp=,\d]+\$[A-Za-z0-9+/]{8,}\$[A-Za-z0-9+/]{16,}|\$2[abxy]\$\d\d\$[.A-Za-z0-9/]{53}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9_.-]{24,}"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def allowed(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if path.is_symlink() or any(part in IGNORED_PARTS for part in relative.parts):
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    if path.name.endswith((".pyc", ".pyo", ".log", ".archive.gz")):
        return False
    return not (relative.parts[:2] == ("artifacts", "private"))


def source_files() -> list[Path]:
    required = [ROOT / name for name in ROOT_FILES + FINAL_DOCUMENTS] + [ROOT / NOTES]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise ValueError("Required submission files are missing: " + ", ".join(missing))
    chosen = set(required)
    for directory in DIRECTORIES:
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and allowed(path):
                chosen.add(path)
    for directory in ("artifacts/stage1", "artifacts/stage2"):
        chosen.update((ROOT / directory).glob("*.manifest.json"))
    for path in chosen:
        if not allowed(path):
            raise ValueError("Disallowed source path: " + str(path.relative_to(ROOT)))
    return sorted(chosen, key=lambda path: path.relative_to(ROOT).as_posix())


def split_link(raw: str) -> tuple[str, str]:
    value = raw.strip()
    if value.startswith("<"):
        close = value.find(">")
        return value[1:close], value[close + 1:]
    match = re.match(r"^(.*?)(\s+[\"'].*[\"'])$", value)
    return (match.group(1), match.group(2)) if match else (value, "")


def local_target(raw: str) -> tuple[str, str] | None:
    if raw.startswith(("#", "mailto:", "data:", "javascript:")):
        return None
    if raw.startswith("file://"):
        parsed = urlsplit(raw)
        return unquote(parsed.path), ("#" + parsed.fragment) if parsed.fragment else ""
    if "://" in raw:
        return None
    path, separator, fragment = raw.partition("#")
    return unquote(path), separator + fragment


def relative_url(target: Path, origin: Path, fragment: str = "") -> str:
    value = Path(os.path.relpath(target, origin.parent)).as_posix() + fragment
    return "<" + value + ">" if " " in value else value


def rewrite_markdown(source: Path, destination: Path, bundle: Path) -> list[str]:
    original = source.read_text(encoding="utf-8")
    reasons: set[str] = set()
    archive_reference = False

    def replace(match: re.Match[str]) -> str:
        nonlocal archive_reference
        label, raw = match.groups()
        url, title = split_link(raw)
        target = local_target(url)
        if target is None:
            return match.group(0)
        path_text, fragment = target
        source_target = Path(path_text)
        absolute = source_target.is_absolute()
        resolved = source_target.resolve() if absolute else (source.parent / source_target).resolve()
        if absolute and not resolved.is_relative_to(ROOT):
            reasons.add("Project-external historical Markdown link replaced with packaged reference notes")
            return label + "(" + relative_url(bundle / NOTES, destination, "#课程旧环境参考") + title + ")"
        if not resolved.is_relative_to(ROOT):
            return match.group(0)
        relative = resolved.relative_to(ROOT)
        if resolved.name.endswith(".archive.gz"):
            manifest = Path(str(relative) + ".manifest.json")
            if not (bundle / manifest).is_file():
                raise ValueError("Archive link has no packaged manifest: " + relative.as_posix())
            archive_reference = True
            reasons.add("Private BSON archive link redirected to its unchanged restoration manifest")
            if label == "[原BSON备份]":
                label = "[原BSON备份清单]"
            return label + "(" + relative_url(bundle / manifest, destination, fragment) + title + ")"
        if absolute:
            reasons.add("Project-absolute Markdown link converted to package-relative link")
            return label + "(" + relative_url(bundle / relative, destination, fragment) + title + ")"
        return match.group(0)

    changed = LINK.sub(replace, original)
    if archive_reference:
        note_url = relative_url(bundle / NOTES, destination)
        changed += "\n\n提交副本说明：原始BSON归档在本地保留，不随本包提供。上方归档链接指向原始恢复清单；新环境运行和历史数据重放的区别见[参考与归档说明](" + note_url + ")。\n"
    if changed != original:
        destination.write_text(changed, encoding="utf-8")
    return sorted(reasons)


def without_fenced_code(text: str) -> str:
    output = []
    fence = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            mark = stripped[:3]
            fence = None if fence == mark else mark if fence is None else fence
            output.append("")
        else:
            output.append(line if fence is None else "")
    return "\n".join(output)


def check_links(bundle: Path) -> dict:
    checked = 0
    broken = []
    for path in sorted(bundle.rglob("*.md")):
        if path.is_symlink():
            broken.append({"file": path.relative_to(bundle).as_posix(), "target": "disallowed symbolic link"})
            continue
        text = without_fenced_code(path.read_text(encoding="utf-8"))
        for match in LINK.finditer(text):
            url, _ = split_link(match.group(2))
            target = local_target(url)
            if target is None:
                continue
            path_text, _ = target
            checked += 1
            resolved = Path(path_text).resolve() if Path(path_text).is_absolute() else (path.parent / path_text).resolve()
            if not resolved.is_relative_to(bundle) or not resolved.exists():
                broken.append({"file": path.relative_to(bundle).as_posix(), "target": url})
    return {"checkedLocalLinks": checked, "brokenLinks": broken}


def scan_sensitive(bundle: Path) -> dict:
    findings = []
    forbidden = []
    scanned = 0
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle)
        if path.is_symlink() or any(part in IGNORED_PARTS for part in relative.parts) or path.name.endswith(".archive.gz") or (path.name.startswith(".env") and path.name != ".env.example"):
            forbidden.append(relative.as_posix())
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".docx"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        scanned += 1
        counts = Counter()
        if path.suffix == ".json" and relative.parts[0] in {"docs", "artifacts"}:
            def inspect(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in STRING_FIELDS and isinstance(item, str) and item and not item.startswith(("<", "[REDACTED", "replace-with")):
                            counts[key] += 1
                        inspect(item)
                elif isinstance(value, list):
                    for item in value:
                        inspect(item)
            inspect(json.loads(text))
        for name, pattern in SECRET_PATTERNS.items():
            counts[name] += len(pattern.findall(text))
        counts += Counter()
        if counts:
            findings.append({"file": relative.as_posix(), "fieldOrPatternCounts": dict(counts)})
    return {"textFilesScanned": scanned, "forbiddenPaths": forbidden, "sensitiveFindings": findings, "valuesPrinted": False}


def verify_directory(bundle: Path) -> dict:
    bundle = bundle.resolve()
    manifest_path = bundle / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []
    expected = {entry["path"] for entry in manifest["files"]} | {MANIFEST}
    actual = {path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()}
    for entry in manifest["files"]:
        path = (bundle / entry["path"]).resolve()
        if not path.is_relative_to(bundle) or not path.is_file() or sha256(path) != entry["sha256"]:
            mismatches.append(entry["path"])
    links = check_links(bundle)
    sensitive = scan_sensitive(bundle)
    passed = not mismatches and actual == expected and not links["brokenLinks"] and not sensitive["forbiddenPaths"] and not sensitive["sensitiveFindings"]
    return {"status": "passed" if passed else "failed", "fileCount": len(actual), "hashMismatches": mismatches, "unexpectedFiles": sorted(actual - expected), "missingFiles": sorted(expected - actual), "links": links, "sensitiveScan": sensitive}


def build(args: argparse.Namespace) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        raise ValueError("--date must have YYYY-MM-DD form")
    name = args.name or "project1_stage2_submission_" + args.date
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("--name must be a simple ASCII directory name")
    output = args.output_root.resolve()
    final = output / name
    archive = output / (name + ".zip")
    checksum = output / (name + ".zip.sha256")
    validation = output / (name + ".validation.json")
    for path in (final, archive, checksum, validation):
        if path.exists():
            raise FileExistsError("Refusing to overwrite existing submission output: " + path.name)
    sources = source_files()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ("." + name + ".build.lock")
    with lock.open("x", encoding="utf-8") as stream:
        stream.write("Exclusive stage-two submission build reservation.\n")
    stage = Path(tempfile.mkdtemp(prefix="." + name + ".staging-", dir=output))
    try:
        bundle = stage / name
        bundle.mkdir()
        transforms = []
        for source in sources:
            target = bundle / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for source in sources:
            if source.suffix == ".md" and source.relative_to(ROOT).parts[:2] != ("docs", "evidence"):
                target = bundle / source.relative_to(ROOT)
                reasons = rewrite_markdown(source, target, bundle)
                if reasons:
                    transforms.append({"path": source.relative_to(ROOT).as_posix(), "sourceSha256": sha256(source), "packagedSha256": sha256(target), "reasons": reasons})
        links = check_links(bundle)
        sensitive = scan_sensitive(bundle)
        if links["brokenLinks"]:
            raise ValueError("Packaged Markdown contains broken local links: " + json.dumps(links["brokenLinks"], ensure_ascii=False))
        if sensitive["forbiddenPaths"] or sensitive["sensitiveFindings"]:
            raise ValueError("Packaged sensitive-data check failed (values omitted): " + json.dumps(sensitive, ensure_ascii=False))
        evidence_changed = [source.relative_to(ROOT).as_posix() for source in sources if source.relative_to(ROOT).parts[:2] == ("docs", "evidence") and sha256(source) != sha256(bundle / source.relative_to(ROOT))]
        if evidence_changed:
            raise ValueError("Historical evidence bytes changed: " + ", ".join(evidence_changed))
        check = {"status": "passed", "clientDate": args.date, "applicationVersion": "2.0.0", "requiredFinalDocuments": list(FINAL_DOCUMENTS), "links": links, "sensitiveScan": sensitive, "originalEvidenceBytesUnchanged": True, "sourceFileCount": len(sources), "packagingOnlySourceTransforms": transforms, "runtimeBoundary": "Static submission checks only; no database exports, application writes or test rerun performed by this script.", "historicalPaths": "Historical evidence retains original host paths as provenance; they are not runtime dependencies. See REFERENCE_NOTES.md."}
        write_json(bundle / CHECK_REPORT, check)
        entries = [{"path": path.relative_to(bundle).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)} for path in sorted(bundle.rglob("*")) if path.is_file()]
        manifest = {"formatVersion": 1, "applicationVersion": "2.0.0", "clientDate": args.date, "packageName": name, "fileCountIncludingManifest": len(entries) + 1, "payloadFileCount": len(entries), "manifestSelfHashExcluded": True, "files": entries}
        write_json(bundle / MANIFEST, manifest)
        verification = verify_directory(bundle)
        if verification["status"] != "passed":
            raise ValueError("Staged directory verification failed: " + json.dumps(verification, ensure_ascii=False))
        staged_zip = stage / archive.name
        with zipfile.ZipFile(staged_zip, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    zipped.write(path, (Path(name) / path.relative_to(bundle)).as_posix())
        with zipfile.ZipFile(staged_zip) as zipped:
            bad = zipped.testzip()
            if bad:
                raise ValueError("ZIP CRC validation failed")
            expected = {name + "/" + entry["path"]: entry["sha256"] for entry in entries}
            expected[name + "/" + MANIFEST] = sha256(bundle / MANIFEST)
            if set(zipped.namelist()) != set(expected):
                raise ValueError("ZIP membership differs from the staged directory")
            if any(hashlib.sha256(zipped.read(member)).hexdigest() != digest for member, digest in expected.items()):
                raise ValueError("ZIP member hash validation failed")
        zip_sha = sha256(staged_zip)
        result = {"status": "passed", "clientDate": args.date, "packageName": name, "fileCount": len(entries) + 1, "uncompressedBytes": sum(entry["size"] for entry in entries) + (bundle / MANIFEST).stat().st_size, "zipBytes": staged_zip.stat().st_size, "zipSha256": zip_sha, "manifestSha256": sha256(bundle / MANIFEST), "zipCrcVerified": True, "zipMemberHashesVerified": True, "directoryVerification": verification, "packagingOnlySourceTransforms": transforms, "originalEvidenceBytesUnchanged": True, "applicationOrDatabaseModified": False}
        write_json(stage / validation.name, result)
        (stage / checksum.name).write_text(zip_sha + "  " + archive.name + "\n", encoding="utf-8")
        for path in (final, archive, checksum, validation):
            if path.exists():
                raise FileExistsError("Submission output appeared during build: " + path.name)
        bundle.rename(final)
        staged_zip.rename(archive)
        (stage / validation.name).rename(validation)
        (stage / checksum.name).rename(checksum)
        return result
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-10-28", help="Client-facing YYYY-MM-DD label")
    parser.add_argument("--name", help="Optional simple output directory name")
    parser.add_argument("--output-root", type=Path, default=ROOT / "dist")
    parser.add_argument("--verify", type=Path, help="Verify an existing unpacked submission without writing files")
    args = parser.parse_args()
    try:
        result = verify_directory(args.verify) if args.verify else build(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
