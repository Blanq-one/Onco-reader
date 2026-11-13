"""Repo hygiene checks: secrets, raw data, personal info, overclaiming language.

The checks themselves live in scripts/scan_repo.py, so `python scripts/scan_repo.py`
and this test always agree. Scope and banned phrases are documented there.
To allow a deliberate mention of a banned phrase, add the marker
`allow-phrase` on the same line.
"""
import importlib.util
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("scan_repo", os.path.join(ROOT, "scripts", "scan_repo.py"))
scan_repo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_repo)


class TestHygiene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = scan_repo.repo_files(ROOT)

    def assertClean(self, problems):
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_scan_covers_the_repo(self):
        rel = {os.path.relpath(p, ROOT).replace(os.sep, "/") for p in self.files}
        for expected in ["README.md", "src/engine/engine.py", "src/guardrails/rules.py", "contract/validate_findings.py"]:
            self.assertIn(expected, rel)

    def test_no_overclaiming_language(self):
        self.assertClean(scan_repo.check_overclaiming(self.files, ROOT))

    def test_no_secrets(self):
        self.assertClean(scan_repo.check_secrets(self.files, ROOT))

    def test_no_raw_data_or_huge_files(self):
        self.assertClean(scan_repo.check_raw_data(self.files, ROOT))

    def test_no_personal_info(self):
        self.assertClean(scan_repo.check_personal_info(self.files, ROOT))

    def test_gitignore_blocks_data_and_env(self):
        self.assertClean(scan_repo.check_gitignore(ROOT, self.files))

    def test_env_example_has_key_names_only(self):
        path = os.path.join(ROOT, ".env.example")
        if not os.path.exists(path):
            self.skipTest("no .env.example")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                key, _, value = line.strip().partition("=")
                if line.strip().startswith("#") or not key:
                    continue
                if any(w in key.upper() for w in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
                    self.assertEqual(value.strip(), "", f"{key} must be empty in .env.example")

    def test_command_line_agrees(self):
        self.assertEqual(scan_repo.main(["--quiet"]), 0)


class TestScannerCatchesProblems(unittest.TestCase):
    """Plant one problem of each kind in a temp folder; the scanner must report each."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text="", size=None):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text if size is None else "x" * size)
        return path

    def test_each_check_fires(self):
        # Fixture strings are split with + so this file does not trip the real repo scan.
        claim = self.write("src/app_text.md", "Our tool is production ready.\n")  # allow-phrase
        allowed = self.write("src/ok.md", "Never say production ready.  allow-phrase\n")
        key = self.write("server/config.py", 'API_KEY = "' + "abcdefghijklmnop1234" + '"\n')
        env = self.write("server/.env", "LLM_API_KEY" + "=abcd1234efgh5678\n")
        url = self.write("README.md", "Data: https://bucket.example.com/f?X-Amz-" + "Signature=abcdef0123456789abcdef\n")
        raw = self.write("data/clinical.tsv", "sampleID\tER\n")
        big = self.write("out/huge.json", size=scan_repo.MAX_FILE_BYTES + 1)
        rows = self.write("out/rows.json", " ".join(f"TCGA-A1-{i:04d}" for i in range(25)))
        mail = self.write("docs/team.md", "Contact someone@" + "university.edu\n")
        safe_mail = self.write("docs/example.md", "Contact jane.doe@example.com\n")
        code = self.write("src/plain.py", "key = load_settings()\nTOKEN_LIMIT = 4096\n")
        self.assertEqual(scan_repo.check_secrets([code], self.root), [], "ordinary code is not a secret")
        files = [claim, allowed, key, env, url, raw, big, rows, mail, safe_mail]

        over = scan_repo.check_overclaiming(files, self.root)
        self.assertEqual(len(over), 1)
        self.assertIn("src/app_text.md", over[0])
        secrets = "\n".join(scan_repo.check_secrets(files, self.root))
        for rel in ["server/config.py", "server/.env", "README.md"]:
            self.assertIn(rel, secrets)
        raw_problems = "\n".join(scan_repo.check_raw_data(files, self.root))
        for rel in ["data/clinical.tsv", "out/huge.json", "out/rows.json"]:
            self.assertIn(rel, raw_problems)
        personal = scan_repo.check_personal_info(files, self.root)
        self.assertEqual(len(personal), 1)
        self.assertIn("university.edu", personal[0])
        self.assertEqual(scan_repo.check_gitignore(self.root, files), [".gitignore is missing"])
        self.write(".gitignore", "*.tsv\n")
        gi = "\n".join(scan_repo.check_gitignore(self.root, files))
        self.assertIn("does not list .env", gi)
        self.assertIn(".env would be committed", gi)


if __name__ == "__main__":
    unittest.main()
