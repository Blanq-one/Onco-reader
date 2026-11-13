r"""Fresh-clone check: prove that a stranger can clone this repo and get everything working.

Run from the repo root (it only reads this repo; all work happens in a temp folder):
    python scripts/fresh_clone_check.py .
    python scripts/fresh_clone_check.py https://github.com/OWNER/REPO.git --branch main
    python scripts/fresh_clone_check.py . --data-dir ../challenge-ref/data/tcga-brca --keep

It clones the COMMITTED state (uncommitted changes are not included; it warns
when the source folder has some), then runs, printing PASS or FAIL per step:
   1. git clone into a temp folder
   2. the unit tests (python -m unittest discover -s tests), with TCGA_DATA_DIR set
   3. the engine on contract/demo_report.md -> out/findings.json
   4. contract/validate_findings.py on that findings file
   5. scripts/make_audit.py on contract/demo_report.md -> out/audit.json
   6. the organizers' format/validate.py on that audit.json
   7. server/serve.py on a free port, then: /api/health, /app/ (when app/ exists),
      POST /api/extract, POST /api/audit (validated with step 4's validator),
      POST /api/audit-json (validated with step 6's validator), and that the
      server refuses hidden files, path traversal, oversized bodies, bad JSON
      and other web pages.
Exit code: 0 all passed, 1 a step failed, 2 bad arguments or setup (no git, no data).

The organizers' validator needs jsonschema (python -m pip install jsonschema);
without it step 6 and the audit-json check FAIL with that hint.
Standard library only.
"""
import argparse
import http.client
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8")  # read child output as UTF-8 whatever the console uses
RESULTS = []


def default_data_dir():
    env = os.environ.get("TCGA_DATA_DIR")
    if env:
        return env if os.path.isabs(env) else os.path.join(HERE, env)
    return os.path.join(HERE, "..", "challenge-ref", "data", "tcga-brca")


def record(step, ok, detail=""):
    RESULTS.append(ok)
    line = f"{'PASS' if ok else 'FAIL'}  {step}"
    if detail:
        line += f"  ({detail})" if ok else "\n" + "\n".join("        " + x for x in str(detail).splitlines()[-15:])
    print(line, flush=True)
    return ok


def run(cmd, cwd, timeout, env=None):
    """Run a command; return (exit code, combined output). Never raises."""
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env or CHILD_ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout} s"
    except OSError as err:
        return -1, f"could not start: {err}"


def validate_shared(validator, path):
    """Run the organizers' format/validate.py on one file; return (ok, detail)."""
    if not os.path.isfile(validator):
        return False, f"organizers' validator not found: {validator} (pass --validator)"
    code, out = run([sys.executable, validator, path], cwd=os.path.dirname(path), timeout=120)
    if "pip install jsonschema" in out:
        return False, "the organizers' validator needs jsonschema: python -m pip install jsonschema"
    return code == 0, out.strip()


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port, method, path, body=None, headers=None, timeout=300):
    """One request to the local server; return (status, content type, body bytes) or (0, '', error text)."""
    h = dict(headers or {})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, r.getheader("Content-Type") or "", data
    except (OSError, http.client.HTTPException) as err:
        return 0, "", f"{err.__class__.__name__}: {err}".encode()


def as_json(data):
    try:
        return json.loads(data)
    except ValueError:
        return None


def rmtree(path):
    def onerror(func, p, _exc):  # git makes pack files read-only on Windows
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


# ---------- steps ----------
def step_clone(src, branch, dest):
    if os.path.isdir(src):
        code, out = run(["git", "-C", src, "status", "--porcelain"], cwd=src, timeout=60)
        if code == 0 and out.strip():
            n = len(out.strip().splitlines())
            print(f"NOTE  {src} has {n} uncommitted change(s); the clone checks the committed state only.", flush=True)
    cmd = ["git", "clone", "--quiet"] + (["--branch", branch] if branch else []) + [src, dest]
    code, out = run(cmd, cwd=os.path.dirname(dest), timeout=600)
    head = run(["git", "-C", dest, "log", "-1", "--format=%h %s"], cwd=dest, timeout=60)[1].strip() if code == 0 else ""
    return record("1. clone", code == 0, head if code == 0 else out)


def step_tests(repo, data_dir):
    env = dict(CHILD_ENV, TCGA_DATA_DIR=data_dir)
    code, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=repo, timeout=1800, env=env)
    ran = re.search(r"Ran (\d+) tests?", out)
    tail = re.search(r"^(OK.*|FAILED.*)$", out, re.M)
    summary = f"{ran.group(1) if ran else '?'} tests, {tail.group(1) if tail else 'no result line'}"
    return record("2. unit tests", code == 0, summary if code == 0 else out)


def step_engine(repo, data_dir):
    out_file = os.path.join(repo, "out", "findings.json")
    code, out = run([sys.executable, os.path.join("src", "engine", "engine.py"), "--data-dir", data_dir,
                     "--report", os.path.join("contract", "demo_report.md"), "--out", out_file], cwd=repo, timeout=600)
    m = re.search(r"\((\d+) findings, (\d+) contract problems\)", out)
    ok = code == 0 and os.path.isfile(out_file)
    record("3. engine on contract/demo_report.md", ok, (m.group(0).strip("()") if m else "out/findings.json written") if ok else out)
    return out_file if ok else None


def step_validate_findings(repo, path, label):
    code, out = run([sys.executable, os.path.join("contract", "validate_findings.py"), path], cwd=repo, timeout=120)
    return record(label, code == 0, out.strip().splitlines()[-1] if code == 0 and out.strip() else out)


def step_make_audit(repo, data_dir, validator):
    out_file = os.path.join(repo, "out", "audit.json")
    script = os.path.join(repo, "scripts", "make_audit.py")
    if not os.path.isfile(script):
        record("5. make_audit.py on contract/demo_report.md", False, "scripts/make_audit.py is not in the clone")
        return record("6. organizers' validate.py on audit.json", False, "no audit.json to check")
    code, out = run([sys.executable, script, os.path.join("contract", "demo_report.md"), "--data-dir", data_dir,
                     "--out", out_file], cwd=repo, timeout=600)
    m = re.search(r"\((\d+) claim_check findings\)", out)
    ok = code == 0 and os.path.isfile(out_file)
    record("5. make_audit.py on contract/demo_report.md", ok, (m.group(0).strip("()") if m else "written") if ok else out)
    if not ok:
        return record("6. organizers' validate.py on audit.json", False, "no audit.json to check")
    good, detail = validate_shared(validator, out_file)
    return record("6. organizers' validate.py on audit.json", good, "valid" if good else detail)


def step_server(repo, data_dir, validator, tmp):
    port = free_port()
    log_path = os.path.join(tmp, "server.log")
    log = open(log_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen([sys.executable, os.path.join("server", "serve.py"), "--data-dir", data_dir,
                                 "--port", str(port)], cwd=repo, env=CHILD_ENV, stdout=log, stderr=subprocess.STDOUT)
    except OSError as err:
        log.close()
        return record("7. server starts", False, f"could not start: {err}")
    try:
        _server_checks(proc, port, repo, validator, tmp, log_path)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)
        log.close()


def _log_tail(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()[-2000:]
    except OSError:
        return ""


def _server_checks(proc, port, repo, validator, tmp, log_path):
    deadline, status, data = time.time() + 180, 0, b""
    while time.time() < deadline:
        if proc.poll() is not None:
            return record("7. server starts", False, f"exited with code {proc.returncode}\n" + _log_tail(log_path))
        status, _, data = request(port, "GET", "/api/health", timeout=5)
        if status == 200:
            break
        time.sleep(0.5)
    health = as_json(data) if status == 200 else None
    if not record("7. server starts, GET /api/health", bool(health and health.get("ok") is True),
                  f"port {port}, checksums {health.get('checksum_status')}" if health else _log_tail(log_path)):
        return

    if os.path.isfile(os.path.join(repo, "app", "index.html")):
        s, ct, _ = request(port, "GET", "/app/")
        s2, ct2, _ = request(port, "GET", "/app/js/app.js") if os.path.isfile(os.path.join(repo, "app", "js", "app.js")) else (200, "text/javascript", b"")
        record("7. GET /app/", s == 200 and ct.startswith("text/html") and s2 == 200 and "javascript" in ct2,
               "index.html and a JS module served" if s == 200 else f"status {s} {ct}, app.js {s2} {ct2}")
    else:
        record("7. GET /app/", True, "skipped: no app/index.html in this repo")

    report = "ER status is recorded for most samples. We recommend further work on this.\n"
    s, _, data = request(port, "POST", "/api/extract", {"report": report})
    j = as_json(data) or {}
    ok = (s == 200 and isinstance(j.get("claims"), list) and len(j["claims"]) == 1
          and set(j["claims"][0]) == {"id", "text", "source"} and isinstance(j.get("skipped"), list)
          and len(j["skipped"]) == 1 and set(j["skipped"][0]) == {"text", "reason"})
    record("7. POST /api/extract", ok, "1 claim, 1 skipped sentence" if ok else f"status {s}: {data[:300]!r}")

    s, _, data = request(port, "POST", "/api/audit", {"claims": ["ER status is recorded for most samples."]})
    j = as_json(data) or {}
    path = os.path.join(tmp, "api_findings.json")
    with open(path, "wb") as fh:
        fh.write(data)
    if s == 200 and len(j.get("findings") or []) == 1:
        step_validate_findings(repo, path, "7. POST /api/audit, contract/validate_findings.py")
    else:
        record("7. POST /api/audit, contract/validate_findings.py", False, f"status {s}: {data[:300]!r}")

    with open(os.path.join(repo, "contract", "demo_report.md"), encoding="utf-8") as fh:
        demo = fh.read()
    s, _, data = request(port, "POST", "/api/audit-json", {"report": demo, "title": "demo_report.md"})
    path = os.path.join(tmp, "api_audit.json")
    with open(path, "wb") as fh:
        fh.write(data)
    if s == 200:
        good, detail = validate_shared(validator, path)
        record("7. POST /api/audit-json, organizers' validate.py", good, "valid" if good else detail)
    else:
        record("7. POST /api/audit-json, organizers' validate.py", False, f"status {s}: {data[:300]!r}")

    refusals = [
        ("GET /.git/config", "GET", "/.git/config", None, None, 404),
        ("GET /.env.example", "GET", "/.env.example", None, None, 404),
        ("path traversal", "GET", "/app/%2e%2e/.git/HEAD", None, None, 404),
        ("source code", "GET", "/src/engine/engine.py", None, None, 404),
        ("bad JSON", "POST", "/api/audit", b"{not json", {"Content-Type": "application/json"}, 400),
        ("body over 100 KB", "POST", "/api/audit", {"report": "a" * (101 * 1024)}, None, 413),
        ("51 claims", "POST", "/api/audit", {"claims": ["ER status is recorded."] * 51}, None, 413),
        ("claim over 2000 characters", "POST", "/api/audit", {"claims": ["x" * 2001]}, None, 413),
        ("another web page (Origin)", "POST", "/api/audit", {"claims": ["x"]}, {"Origin": "http://evil.example"}, 403),
        ("another host name (Host)", "GET", "/api/health", None, {"Host": "evil.example"}, 403),
    ]
    wrong = []
    for name, method, p, body, headers, want in refusals:
        s, _, data = request(port, method, p, body, headers)
        if s != want:
            wrong.append(f"{name}: expected {want}, got {s}")
    record("7. server refuses unsafe requests", not wrong, f"{len(refusals)} cases" if not wrong else "\n".join(wrong))

    if proc.poll() is not None:
        record("7. server still running after the checks", False, _log_tail(log_path))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Clone this repo into a temp folder and check that it works from scratch")
    ap.add_argument("source", nargs="?", default=HERE, help="repo path or URL to clone (default: this repo)")
    ap.add_argument("--branch", help="branch to clone (default: the source's current branch)")
    ap.add_argument("--data-dir", default=None,
                    help="TCGA-BRCA data folder (default: $TCGA_DATA_DIR, else ../challenge-ref/data/tcga-brca)")
    ap.add_argument("--validator", default=None,
                    help="the organizers' format/validate.py (default: two folders above --data-dir, format/validate.py)")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder for inspection")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    if shutil.which("git") is None:
        print("git is not installed or not on PATH.", file=sys.stderr)
        return 2
    data_dir = os.path.abspath(args.data_dir or default_data_dir())
    if not os.path.isdir(data_dir):
        print(f"Data folder not found: {data_dir}\nFetch it (python data/tcga-brca/fetch.py inside challenge-ref) "
              "or pass --data-dir.", file=sys.stderr)
        return 2
    validator = os.path.abspath(args.validator or os.path.join(data_dir, "..", "..", "format", "validate.py"))
    src = os.path.abspath(args.source) if os.path.isdir(args.source) else args.source

    tmp = tempfile.mkdtemp(prefix="fresh_clone_")
    repo = os.path.join(tmp, "repo")
    print(f"Source:    {src}\nData:      {data_dir}\nValidator: {validator}\nTemp:      {tmp}\n", flush=True)
    try:
        if step_clone(src, args.branch, repo):
            step_tests(repo, data_dir)
            findings = step_engine(repo, data_dir)
            if findings:
                step_validate_findings(repo, findings, "4. contract/validate_findings.py on out/findings.json")
            else:
                record("4. contract/validate_findings.py on out/findings.json", False, "no findings file to check")
            step_make_audit(repo, data_dir, validator)
            if os.path.isfile(os.path.join(repo, "server", "serve.py")):
                step_server(repo, data_dir, validator, tmp)
            else:
                record("7. server", False, "server/serve.py is not in the clone")
    finally:
        if args.keep:
            print(f"\nKept {tmp}")
        else:
            rmtree(tmp)
    failed = RESULTS.count(False)
    print(f"\n{'PASS' if not failed else 'FAIL'}: {len(RESULTS) - failed} of {len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
