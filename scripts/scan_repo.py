r"""Repo hygiene scan: secrets, raw data, personal info and overclaiming language.

One command, from anywhere:
    python scripts/scan_repo.py          # prints PASS, or every problem (exit code 1)
    python scripts/scan_repo.py --quiet  # exit code only

tests/test_repo_hygiene.py runs these same checks, so a person and the test
suite always see the same result. Standard library only.

What is scanned:
  * secrets, raw data, large files, personal info: every file git would commit
    (tracked plus untracked-but-not-ignored). Without git, every file under the
    repo except the folders in SKIP_DIRS.
  * overclaiming language: user-facing places only (OVERCLAIM_SCOPE). tests/,
    docs/ and CLAUDE.md are left out because they quote the banned phrases on
    purpose. Add the marker `allow-phrase` on a line to allow a deliberate mention.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv", ".pytest_cache"}
TEXT_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".md", ".json", ".txt", ".yml", ".yaml", ".toml",
            ".csv", ".cfg", ".ini", ".sh", ".ps1", ".bat", ".ipynb", ".example", ".env", ""}
OVERCLAIM_SCOPE = ["src", "app", "server", "contract", "scripts", "out", "README.md"]

# The banned list lives here once; the allow-phrase markers keep this file from flagging itself.
BANNED_PHRASES = [
    "production ready", "production-ready", "production level", "production-level",  # allow-phrase
    "clinically validated", "clinical grade", "clinical-grade",  # allow-phrase
    "hipaa compliant", "fda approved", "fda-approved", "regulatory compliant",  # allow-phrase
]
SECRET_PATTERNS = [
    ("openai-style key", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("quoted secret", re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]")),
    # Upper-case env-style names only, with a token-like value holding a letter and a digit,
    # so ordinary code such as `key = load()` or `TOKEN_LIMIT = 4096` is not flagged.
    ("env secret value", re.compile(r"(?m)^\s*(?:export\s+)?[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)\s*=\s*"
                                    r"(?=[^\s]*\d)(?=[^\s]*[A-Za-z])[A-Za-z0-9_\-./+=]{8,}\s*$")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("signed or private URL", re.compile(r"https?://\S+[?&](?:token|sig|signature|x-amz-signature|access_token|key|auth)=[A-Za-z0-9%._\-]{16,}", re.I)),
]
MAX_FILE_BYTES = 5 * 1024 * 1024
RAW_DATA_EXT = {".tsv", ".csv", ".gz", ".zip", ".parquet", ".svs", ".tif", ".tiff", ".h5", ".npz", ".maf", ".vcf", ".bam"}
ALLOWED_DATA_FILES = {"edge_cases.csv"}  # small hand-written files are fine
# Many distinct participant barcodes in one file means per-patient rows were copied in.
BARCODE = re.compile(r"\bTCGA-[A-Z0-9]{2}-[A-Z0-9]{4}\b")
MAX_DISTINCT_BARCODES = 20
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@([\w-]{1,63}(?:\.[\w-]{1,63})*\.[a-z]{2,24})\b", re.I)
SAFE_EMAIL_DOMAINS = re.compile(r"(?:^|\.)(?:example\.(?:com|org|net)|example|test|invalid|localhost|users\.noreply\.github\.com)$", re.I)


def repo_files(root=ROOT):
    """Files git would commit, as absolute paths. Falls back to walking the folder."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=root, capture_output=True, timeout=60)
        if out.returncode == 0:
            names = [n for n in out.stdout.decode("utf-8", "replace").split("\0") if n]
            return sorted(os.path.join(root, n) for n in names if os.path.isfile(os.path.join(root, n)))
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        found += [os.path.join(dirpath, f) for f in filenames]
    return sorted(found)


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _lines(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in TEXT_EXT or os.path.getsize(path) > MAX_FILE_BYTES:
        return []
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return []
    if b"\0" in data[:4096]:  # binary
        return []
    return list(enumerate(data.decode("utf-8", "ignore").splitlines(), 1))


def in_overclaim_scope(path, root=ROOT):
    rel = _rel(path, root)
    return any(rel == s or rel.startswith(s + "/") for s in OVERCLAIM_SCOPE)


def check_overclaiming(files, root=ROOT):
    problems = []
    for path in files:
        if not in_overclaim_scope(path, root):
            continue
        for n, line in _lines(path):
            low = line.lower()
            if "allow-phrase" in low:
                continue
            for phrase in BANNED_PHRASES:
                if phrase in low:
                    problems.append(f"{_rel(path, root)}:{n}: overclaiming phrase '{phrase}'")
    return problems


def check_secrets(files, root=ROOT):
    problems = []
    for path in files:
        for n, line in _lines(path):
            for name, pat in SECRET_PATTERNS:
                if pat.search(line):
                    problems.append(f"{_rel(path, root)}:{n}: possible {name}")
    return problems


def check_raw_data(files, root=ROOT):
    problems = []
    for path in files:
        rel, name = _rel(path, root), os.path.basename(path)
        if os.path.getsize(path) >= MAX_FILE_BYTES:
            problems.append(f"{rel}: file is over {MAX_FILE_BYTES // (1024 * 1024)} MB")
        if os.path.splitext(name)[1].lower() in RAW_DATA_EXT and name not in ALLOWED_DATA_FILES:
            problems.append(f"{rel}: possible raw data file (extension {os.path.splitext(name)[1]})")
        barcodes = {m.group(0) for _, line in _lines(path) for m in BARCODE.finditer(line)}
        if len(barcodes) >= MAX_DISTINCT_BARCODES:
            problems.append(f"{rel}: {len(barcodes)} distinct TCGA participant barcodes, looks like per-patient data")
    return problems


def check_personal_info(files, root=ROOT):
    problems = []
    for path in files:
        for n, line in _lines(path):
            for m in EMAIL.finditer(line):
                if not SAFE_EMAIL_DOMAINS.search(m.group(1)):
                    problems.append(f"{_rel(path, root)}:{n}: email address with domain {m.group(1)}")
    return problems


def check_gitignore(root=ROOT, files=None):
    problems = []
    gi = os.path.join(root, ".gitignore")
    if not os.path.exists(gi):
        return [".gitignore is missing"]
    with open(gi, encoding="utf-8", errors="ignore") as fh:
        content = fh.read()
    if ".env" not in content:
        problems.append(".gitignore does not list .env")
    if "data" not in content:
        problems.append(".gitignore does not cover data folders")
    files = repo_files(root) if files is None else files
    for path in files:
        if os.path.basename(path) == ".env":
            problems.append(f"{_rel(path, root)}: .env would be committed")
    return problems


CHECKS = [("overclaiming", check_overclaiming), ("secrets", check_secrets), ("raw data", check_raw_data),
          ("personal info", check_personal_info)]


def scan(root=ROOT):
    """Return {check name: [problems]} for the repo at root."""
    files = repo_files(root)
    result = {name: fn(files, root) for name, fn in CHECKS}
    result["gitignore"] = check_gitignore(root, files)
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    result = scan(ROOT)
    problems = [(name, p) for name, items in result.items() for p in items]
    if "--quiet" not in argv:
        if problems:
            print(f"FAIL: {len(problems)} problem(s)")
            for name, p in problems:
                print(f"  [{name}] {p}")
        else:
            print(f"PASS ({len(repo_files(ROOT))} files scanned: " + ", ".join(result) + ")")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
