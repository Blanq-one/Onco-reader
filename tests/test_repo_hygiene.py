"""Repo hygiene checks: secrets, raw data, overclaiming language.

Run from the repo root. Scans src/, app/, contract/ and README.md.
To allow a deliberate mention of a banned phrase, add the marker
`allow-phrase` on the same line.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ["src", "app", "contract"]
SCAN_FILES = ["README.md"]
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv"}
TEXT_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".md", ".json", ".txt", ".yml", ".yaml", ".toml"}

BANNED_PHRASES = [
    "production ready", "production-ready", "production level", "production-level",
    "clinically validated", "clinical grade", "clinical-grade",
    "hipaa compliant", "fda approved", "fda-approved", "regulatory compliant",
]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
MAX_FILE_BYTES = 5 * 1024 * 1024
RAW_DATA_EXT = {".tsv", ".csv", ".gz", ".zip", ".parquet", ".svs", ".tif", ".tiff", ".h5", ".npz"}
ALLOWED_DATA_FILES = {"edge_cases.csv"}  # small hand-written files are fine


def iter_files():
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
            for name in filenames:
                yield os.path.join(dirpath, name)
    for name in SCAN_FILES:
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            yield p


def text_lines(path):
    if os.path.splitext(path)[1].lower() not in TEXT_EXT:
        return []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return list(enumerate(fh.read().splitlines(), 1))
    except OSError:
        return []


class TestHygiene(unittest.TestCase):
    def test_no_overclaiming_language(self):
        for path in iter_files():
            for n, line in text_lines(path):
                low = line.lower()
                if "allow-phrase" in low:
                    continue
                for phrase in BANNED_PHRASES:
                    with self.subTest(file=os.path.relpath(path, ROOT), line=n):
                        self.assertNotIn(phrase, low)

    def test_no_secrets(self):
        for path in iter_files():
            for n, line in text_lines(path):
                for pat in SECRET_PATTERNS:
                    with self.subTest(file=os.path.relpath(path, ROOT), line=n):
                        self.assertIsNone(pat.search(line))

    def test_env_file_is_ignored(self):
        if os.path.exists(os.path.join(ROOT, ".env")):
            gi = os.path.join(ROOT, ".gitignore")
            self.assertTrue(os.path.exists(gi), ".env exists but .gitignore is missing")
            self.assertIn(".env", open(gi).read(), ".env is not listed in .gitignore")

    def test_gitignore_blocks_data_and_env(self):
        gi = os.path.join(ROOT, ".gitignore")
        self.assertTrue(os.path.exists(gi), ".gitignore is missing")
        content = open(gi).read()
        self.assertIn(".env", content)
        self.assertTrue("data/" in content or "data" in content)

    def test_no_raw_data_or_huge_files(self):
        for path in iter_files():
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1].lower()
            with self.subTest(file=os.path.relpath(path, ROOT)):
                self.assertLess(os.path.getsize(path), MAX_FILE_BYTES, "file too large")
                if ext in RAW_DATA_EXT:
                    self.assertIn(name, ALLOWED_DATA_FILES, "possible raw data file")


if __name__ == "__main__":
    unittest.main()
