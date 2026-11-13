r"""Local server for Evidence Navigator (Research Claim Auditor): the app plus a small JSON API.

Run from the repo root:
    python server/serve.py
    python server/serve.py --data-dir ../challenge-ref/data/tcga-brca --port 8000
then open http://127.0.0.1:8000/app/

Endpoints (POST bodies are JSON sent with Content-Type: application/json, except /api/pdf-text):
  GET  /api/health      {"ok": true, "checksum_status": "...", "pdf_text": true|false}
  POST /api/extract     {"report": "text"} -> {"claims": [{"id", "text", "source"}], "skipped": [{"text", "reason"}]}
  POST /api/audit       {"report": "text"} or {"claims": ["...", ...]} -> the findings document
                        (contract/README.md), with skipped_sentences when a report was sent
  POST /api/audit-json  {"report": "text"} -> audit.json in the organizers' shared format v0.2
  POST /api/pdf-text    the PDF file itself (Content-Type: application/pdf) -> {"text", "pages", "truncated"};
                        501 {"error": "paste the text instead"} when pypdf is not installed
Any POST body may also carry "title" (a short report name). Claims may be plain
strings or {"text", "source"} objects, as /api/extract returns them.

Limits: JSON bodies up to 100 KB, at most 50 claims, 2000 characters per claim
(PDF uploads up to 5 MB). Errors come back as {"error": "..."} with status 400,
403, 404, 405, 411, 413, 415, 422, 500, 501 or 503.

Privacy: the server never logs request bodies, query strings, claim text or
exception messages, and every error message is fixed text that never quotes a
claim. Text the engine would withhold or redact in a finding (personal details,
barcodes) is withheld or redacted the same way by /api/extract.

Static files: only app/ (the frontend), out/*.json and contract/*.json are
served. Hidden files, .git, .env, the data folder, source code and anything
outside the repo return 404. By default the server listens on 127.0.0.1 only
and refuses requests whose Host or Origin header is not this server, so other
web pages cannot drive it from a browser.

Standard library only; pypdf is used for /api/pdf-text if it happens to be installed.
"""
import argparse
import io
import json
import logging
import os
import socket
import socketserver
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_REAL = os.path.realpath(ROOT)
sys.path.insert(0, ROOT)

from src.engine import engine as E  # noqa: E402
from src.export import audit_json as AJ  # noqa: E402

try:  # optional, only for /api/pdf-text
    import pypdf  # type: ignore
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # its warnings are noise here
except Exception:  # not installed: /api/pdf-text answers 501
    pypdf = None

# ---------- limits (change them here) ----------
MAX_BODY = 100 * 1024          # bytes, any JSON request body
MAX_CLAIMS = 50                # claims per request, whether sent as a list or extracted from a report
MAX_CLAIM_CHARS = 2000         # characters per claim (the guardrails also refuse claims over 1000 as invalid_input)
MAX_TITLE_CHARS = 200          # optional "title"
MAX_PDF_BYTES = 5 * 1024 * 1024  # a PDF upload; 100 KB is too small for most real PDFs
MAX_PDF_PAGES = 100
MAX_PDF_TEXT = 90_000          # characters returned, so the text still fits in one /api/audit body
REQUEST_TIMEOUT = 30           # seconds a client may take to send its request

DEFAULT_PORT = 8000
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
WITHHELD = "[withheld]"        # the same marker engine.audit uses for skipped sentences

# Static files: top folder -> file types served from it. Everything else is 404.
STATIC = {
    "app": {".html", ".js", ".mjs", ".css", ".svg", ".png", ".ico", ".webp", ".jpg", ".jpeg",
            ".woff", ".woff2", ".json", ".md", ".txt"},
    "out": {".json"},
    "contract": {".json"},
}
# Fixed types: on Windows, mimetypes reads the registry and can call .js "text/plain",
# which browsers refuse to run as a module.
MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
    ".ico": "image/x-icon", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".woff": "font/woff", ".woff2": "font/woff2",
}
API_ROUTES = {"/api/health": "GET", "/api/extract": "POST", "/api/audit": "POST",
              "/api/audit-json": "POST", "/api/pdf-text": "POST"}


class ApiError(Exception):
    """An error answered as {"error": message}. Messages are fixed text: never put claim text in one."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = int(status)
        self.message = message


# ---------- request bodies -> claims ----------
def _title(body, default):
    t = body.get("title")
    if not isinstance(t, str) or not t.strip() or len(t) > MAX_TITLE_CHARS:
        return default
    t = " ".join(t.split())
    # The title ends up in the output, so it gets the same pre-check as a claim.
    return t if E.run_guardrails(t).get("allowed") else default


def claims_from_body(body):
    """Return (claims, skipped, title) from {"report": text} or {"claims": [...]}. Raises ApiError."""
    has_report, has_claims = "report" in body, "claims" in body
    if has_report and has_claims:
        raise ApiError(400, 'send either "report" or "claims", not both')
    if has_report:
        report = body["report"]
        if not isinstance(report, str):
            raise ApiError(400, '"report" must be text')
        if not report.strip():
            raise ApiError(400, '"report" is empty')
        claims, skipped = E.extract_claims(report)
        title = _title(body, "Pasted report")
    elif has_claims:
        raw = body["claims"]
        if not isinstance(raw, list):
            raise ApiError(400, '"claims" must be a list')
        if not raw:
            raise ApiError(400, '"claims" is empty')
        if len(raw) > MAX_CLAIMS:
            raise ApiError(413, f"too many claims: the limit is {MAX_CLAIMS} per request")
        claims = []
        for i, item in enumerate(raw, 1):
            if isinstance(item, str):
                claims.append({"text": item, "source": item})
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                src = item.get("source")
                claims.append({"text": item["text"], "source": src if isinstance(src, str) and src else item["text"]})
            else:
                raise ApiError(400, f'claim {i} must be text or an object with a "text" field')
        skipped, title = [], _title(body, "Ad hoc claims")
    else:
        raise ApiError(400, 'send {"report": "text"} or {"claims": ["..."]}')
    if len(claims) > MAX_CLAIMS:
        raise ApiError(413, f"the report has {len(claims)} claims; the limit is {MAX_CLAIMS} per request, so split it")
    for i, c in enumerate(claims, 1):
        if len(c["text"]) > MAX_CLAIM_CHARS or len(c["source"]) > MAX_CLAIM_CHARS:
            raise ApiError(413, f"claim {i} is longer than {MAX_CLAIM_CHARS} characters, so split it")
    return claims, skipped, title


def safe_text(text):
    """Text as the engine would store it: withheld for personal details, redacted for barcodes and patients."""
    flags = E.run_guardrails(text).get("flags") or []
    return E.safe_claim_text(text, flags) if E.REDACT_FLAGS & set(flags) else text


def guard_sources(doc):
    """engine.audit keeps the full source sentence when only the trimmed claim text was pre-checked.
    Pre-check the source sentence too, and redact it the way the claim text would be."""
    for f in doc.get("findings") or []:
        src = f.get("source_sentence")
        if isinstance(src, str) and src != f.get("claim_text"):
            f["source_sentence"] = safe_text(src)
    return doc


# ---------- the server ----------
class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"  # on Windows reuse would let two servers share one port

    def __init__(self, addr, ctx, files, loopback_only):
        self.ctx = ctx
        self.files = files
        self.loopback_only = loopback_only
        self.lock = threading.Lock()  # the engine keeps module state, so one audit at a time
        if ":" in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, Handler)

    def server_bind(self):
        # Windows lets a second program bind 127.0.0.1:PORT while another listens on all
        # addresses at that port, and requests then reach the wrong server. Claim the port
        # exclusively so startup fails with a clear message instead.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer.server_bind looks up the host name, which can stall for seconds on Windows.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]

    def handle_error(self, request, client_address):
        # The default prints a traceback whose message could quote request text.
        exc = sys.exc_info()[0]
        sys.stderr.write(f"connection error: {exc.__name__ if exc else 'unknown'}\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "EvidenceNavigator"
    sys_version = ""
    timeout = REQUEST_TIMEOUT
    _route = "-"

    # ----- logging: method, a known route or file, status. Never bodies, queries or claim text.
    def log_request(self, code="-", size="-"):
        code = getattr(code, "value", code)
        sys.stderr.write(f"{self.log_date_time_string()}  {self.command or '-'} {self._route} {code}\n")

    def log_error(self, format, *args):
        code = args[0] if args and isinstance(args[0], int) else "-"
        sys.stderr.write(f"{self.log_date_time_string()}  request refused ({code})\n")

    def log_message(self, format, *args):
        pass

    # ----- responses
    def _common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'none'; object-src 'none'")

    def _send(self, status, data, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self._common_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=True).encode("ascii")
        self._send(status, data, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _error(self, status, message):
        self.close_connection = True  # the body may be unread
        self._json(status, {"error": message})

    # ----- request checks
    def _host_ok(self):
        """Stop DNS rebinding: a loopback server only answers requests addressed to a loopback name."""
        if not self.server.loopback_only:
            return True
        host = self.headers.get("Host") or ""
        try:
            name = urlsplit("//" + host).hostname
        except ValueError:
            return False
        return name in LOOPBACK

    def _origin_ok(self):
        """Browsers send Origin on cross-site POSTs. Only this server's own pages may call the API."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # not a browser cross-origin request (curl, scripts, same-origin GET)
        return origin == "http://" + (self.headers.get("Host") or "")

    def _read_body(self, limit):
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(411, "send the body with a Content-Length header")
        length = self.headers.get("Content-Length")
        if length is None:
            raise ApiError(411, "send the body with a Content-Length header")
        try:
            n = int(length)
        except ValueError:
            raise ApiError(400, "bad Content-Length header")
        if n < 0:
            raise ApiError(400, "bad Content-Length header")
        if n > limit:
            raise ApiError(413, f"the request is larger than {limit // 1024} KB")
        data = self.rfile.read(n)
        if len(data) != n:
            raise ApiError(400, "the request body was cut short")
        return data

    def _media_type(self):
        return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    def _json_body(self):
        if self._media_type() != "application/json":
            raise ApiError(415, "send JSON with Content-Type: application/json")
        data = self._read_body(MAX_BODY)
        try:
            body = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ApiError(400, "the body is not valid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "the body must be a JSON object")
        return body

    # ----- HTTP methods
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        try:
            if not self._host_ok():
                raise ApiError(403, "this server only answers requests addressed to 127.0.0.1 or localhost")
            path = urlsplit(self.path).path
            if path.startswith("/api/") or path == "/api":
                self._api(method, path)
            elif method == "POST":
                raise ApiError(405, "only /api/ paths accept POST")
            else:
                self._static(path)
        except ApiError as err:
            self._error(err.status, err.message)
        except E.PostCheckError as err:
            sys.stderr.write(f"post-check failed: {len(err.problems)} problem(s); output withheld\n")
            self._error(500, "post-check failed")
        except Exception as err:  # never crash, never echo the message (it could quote a claim)
            sys.stderr.write(f"internal error: {err.__class__.__name__}\n")
            self._error(500, "internal error")

    # ----- API
    def _api(self, method, path):
        want = API_ROUTES.get(path)
        if want is None:
            self._route = "[unknown api]"
            raise ApiError(404, "no such endpoint")
        self._route = path
        if method == "HEAD":
            method = "GET"
        if method != want:
            raise ApiError(405, f"use {want} for {path}")
        if method == "POST" and not self._origin_ok():
            raise ApiError(403, "requests from other web pages are refused")
        srv = self.server
        if path == "/api/health":
            self._json(200, {"ok": True, "checksum_status": srv.ctx.checksums["status"], "pdf_text": pypdf is not None})
        elif path == "/api/pdf-text":
            self._pdf_text()
        elif path == "/api/extract":
            self._extract(self._json_body())
        elif path == "/api/audit":
            self._audit(self._json_body())
        elif path == "/api/audit-json":
            self._audit_json(self._json_body())

    def _extract(self, body):
        if "claims" in body:
            raise ApiError(400, '/api/extract takes {"report": "text"}')
        claims, skipped, _ = claims_from_body(body)
        with self.server.lock:
            out_claims = []
            for i, c in enumerate(claims, 1):
                text = safe_text(c["text"])
                source = text if text != c["text"] else safe_text(c["source"])
                out_claims.append({"id": f"claim-{i:03d}", "text": text, "source": source})
            out_skipped = [{"text": sk["text"] if E.run_guardrails(sk["text"]).get("allowed") else WITHHELD,
                            "reason": sk["reason"]} for sk in skipped]
        self._json(200, {"claims": out_claims, "skipped": out_skipped})

    def _run_audit(self, body):
        claims, skipped, title = claims_from_body(body)
        with self.server.lock:
            doc = E.audit(self.server.ctx, claims, title, skipped)
        return guard_sources(doc)

    def _audit(self, body):
        self._json(200, self._run_audit(body))

    def _audit_json(self, body):
        if self.server.files is None:
            raise ApiError(503, "the release checksums (sources.csv) could not be read, so audit.json cannot be made")
        doc = self._run_audit(body)
        try:
            audit = AJ.build_audit(doc, self.server.files)
        except ValueError:
            raise ApiError(500, "export failed")
        self._json(200, audit)

    def _pdf_text(self):
        if pypdf is None:
            raise ApiError(501, "paste the text instead")
        if self._media_type() != "application/pdf":
            raise ApiError(415, "send the PDF file itself with Content-Type: application/pdf")
        data = self._read_body(MAX_PDF_BYTES)
        if b"%PDF-" not in data[:1024]:
            raise ApiError(400, "this is not a PDF file")
        texts, total, truncated = [], 0, False
        with self.server.lock:  # parsing is CPU heavy; one at a time
            try:
                reader = pypdf.PdfReader(io.BytesIO(data))
                if reader.is_encrypted:
                    raise ApiError(400, "the PDF is password protected; paste the text instead")
                n_pages = len(reader.pages)
                truncated = n_pages > MAX_PDF_PAGES
                for i in range(min(n_pages, MAX_PDF_PAGES)):
                    t = reader.pages[i].extract_text() or ""
                    texts.append(t)
                    total += len(t)
                    if total > MAX_PDF_TEXT:
                        truncated = True
                        break
            except ApiError:
                raise
            except Exception:
                raise ApiError(400, "could not read text from this PDF; paste the text instead")
        text = "\n\n".join(texts)[:MAX_PDF_TEXT]
        if not text.strip():
            raise ApiError(422, "no text found in this PDF (it may be scanned images); paste the text instead")
        self._json(200, {"text": text, "pages": n_pages, "truncated": truncated})

    # ----- static files
    def _redirect(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self._common_headers()
        self.end_headers()

    def _static(self, path):
        if path in ("", "/", "/app", "/index.html"):
            self._route = path or "/"
            self._redirect("/app/")
            return
        full = self._resolve(path)
        if full is None:
            self._route = "[not served]"
            raise ApiError(404, "not found")
        self._route = path
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, MIME[os.path.splitext(full)[1].lower()], {"Cache-Control": "no-cache"})

    @staticmethod
    def _bad_part(p):
        # hidden files and folders (.git, .env), __pycache__, Windows short names (GIT~1),
        # trailing dots or spaces (Windows ignores them), and alternate data streams (":").
        return (not p or p in (".", "..") or p.startswith((".", "_")) or "~" in p or ":" in p
                or p != p.rstrip(". "))

    def _resolve(self, path):
        """Map a URL path to a file under an allowed folder, or None. Checked before and after resolving links."""
        try:
            rel = unquote(path, errors="strict")
        except UnicodeDecodeError:
            return None
        if "\\" in rel or "\x00" in rel:
            return None
        parts = rel.split("/")[1:]
        if rel.endswith("/"):
            parts = parts[:-1] + ["index.html"]
        if not parts or any(self._bad_part(p) for p in parts) or parts[0] not in STATIC:
            return None
        real = os.path.realpath(os.path.join(ROOT, *parts))
        try:
            rparts = os.path.relpath(real, ROOT_REAL).split(os.sep)
        except ValueError:  # another drive
            return None
        if rparts[0] not in STATIC or any(self._bad_part(p) for p in rparts):
            return None
        ext = os.path.splitext(real)[1].lower()
        if ext not in STATIC[rparts[0]] or ext not in MIME or not os.path.isfile(real):
            return None
        return real


# ---------- startup ----------
def port_in_use(host, port):
    """True when something already answers on this port. Windows lets this server bind 127.0.0.1
    next to another program listening on [::] at the same port, and then the browser may reach
    the other program, so ask before binding."""
    if port == 0:
        return False
    if host in LOOPBACK or host in ("0.0.0.0", "::", ""):
        targets = ["127.0.0.1", "::1"]
    else:
        targets = [host]
    for target in targets:
        try:
            with socket.create_connection((target, port), timeout=0.5):
                return True
        except OSError:
            continue
    return False


def default_data_dir():
    env = os.environ.get("TCGA_DATA_DIR")
    if env:
        return env if os.path.isabs(env) else os.path.join(ROOT, env)  # relative to the repo root, as in .env.example
    return os.path.join(ROOT, "..", "challenge-ref", "data", "tcga-brca")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evidence Navigator local server: the app at /app/ and the JSON API at /api/")
    ap.add_argument("--data-dir", default=None,
                    help="TCGA-BRCA data folder (default: $TCGA_DATA_DIR, else ../challenge-ref/data/tcga-brca)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT}; 0 picks a free one)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (default 127.0.0.1, this computer only)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # never crash on characters the console cannot show
        try:
            stream.reconfigure(errors="replace", line_buffering=True)
        except Exception:
            pass

    if E._check_claim is None or E._check_document is None:
        sys.exit("src/guardrails is missing or failed to import; the server never runs without it.")
    if not hasattr(E, "extract_claims"):
        sys.exit("This engine has no extract_claims; the server needs engine v1.2.0 or later.")
    if not 0 <= args.port <= 65535:
        sys.exit("--port must be between 0 and 65535")
    data_dir = os.path.abspath(args.data_dir or default_data_dir())
    if not os.path.isdir(data_dir):
        sys.exit(f"Data folder not found: {data_dir}\n"
                 "Fetch it with: python data/tcga-brca/fetch.py (inside challenge-ref), or pass --data-dir.")

    if port_in_use(args.host, args.port):
        sys.exit(f"Port {args.port} is already in use by another program (another server?). "
                 f"Stop it or pick another port, e.g. --port {args.port + 1 if args.port < 65535 else 8001}.")
    print("Evidence Navigator (Research Claim Auditor) local server")
    print(f"Loading TCGA-BRCA data from {data_dir} ...")
    ctx = E.Context(data_dir)
    status = ctx.checksums["status"]
    if status == "verified":
        print("Data checks: PASSED (every file matches the frozen checksums in sources.csv)")
    else:
        print(f"Data checks: NOT PASSED (checksum status: {status}). Results may not describe the frozen release;"
              " every finding's limitation will say so.")
    if ctx.missing:
        print("Missing data layers: " + ", ".join(sorted(ctx.missing)))
    try:
        files = AJ.read_sources(data_dir)
    except (OSError, ValueError) as err:
        files = None
        print(f"WARNING: cannot read sources.csv ({err.__class__.__name__}); /api/audit-json is off.")
    print(f"Guardrails: {E.GUARDRAILS_SOURCE}   PDF text: {'on (pypdf)' if pypdf else 'off (pypdf not installed)'}")

    loopback_only = args.host in LOOPBACK
    try:
        httpd = Server((args.host, args.port), ctx, files, loopback_only)
    except OSError as err:
        sys.exit(f"Cannot listen on {args.host}:{args.port} ({err.strerror or err}). "
                 "Is another server running? Try --port 8001.")
    port = httpd.server_address[1]
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
    if not loopback_only:
        print(f"WARNING: listening on {args.host}, so other computers on your network can reach this server.")
    print(f"\nOpen the app:  http://{shown}:{port}/app/")
    print(f"API health:    http://{shown}:{port}/api/health")
    print("Press Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
