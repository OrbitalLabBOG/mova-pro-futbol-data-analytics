"""Safe, read-only sealing of web evidence discovered by the research worker."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_EXCERPT_CHARS = 800
ALLOWED_MIME = {
    "text/html", "application/xhtml+xml", "text/plain", "application/json",
}
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_public_url(value: object) -> str:
    """Canonicalize one public HTTPS URL without opening the network."""
    raw = str(value).strip()
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("toda evidencia debe usar URL HTTPS pública")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("autoridad o puerto de evidencia no permitido")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("host de evidencia no público")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("IP de evidencia no pública")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [
        (key, item) for key, item in query
        if key.lower() not in TRACKING_KEYS and not key.lower().startswith("utm_")
    ]
    netloc = host if parsed.port is None else f"{host}:443"
    return urllib.parse.urlunsplit((
        "https", netloc, parsed.path or "/", urllib.parse.urlencode(query), "",
    ))


def _assert_public_resolution(url: str) -> None:
    host = urllib.parse.urlsplit(url).hostname
    try:
        rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OSError("evidence_dns_failed") from exc
    addresses = {ipaddress.ip_address(row[4][0]) for row in rows}
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("evidence_dns_not_public")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag.lower() in {"script", "style", "noscript", "svg", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag.lower() in {"script", "style", "noscript", "svg", "template"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def normalize_text(payload: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.I)
    if match:
        charset = match.group(1).strip('"\'')[:40]
    try:
        decoded = payload.decode(charset, errors="replace")
    except LookupError:
        decoded = payload.decode("utf-8", errors="replace")
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in {"text/html", "application/xhtml+xml"}:
        parser = _TextExtractor()
        parser.feed(decoded)
        decoded = " ".join(parser.parts)
    return re.sub(r"\s+", " ", html.unescape(decoded)).strip()


class SafeEvidenceFetcher:
    """Fetch public pages with strict limits and persist only minimal evidence."""

    def __init__(self, root: Path, *, timeout_seconds: int = 8,
                 max_body_bytes: int = MAX_BODY_BYTES, transport=None):
        self.root = Path(root)
        self.timeout_seconds = int(timeout_seconds)
        self.max_body_bytes = int(max_body_bytes)
        self.transport = transport

    def seal(self, *, research_run_id: str, document_id: str,
             source_url: str, evidence_text: str) -> dict:
        url = canonical_public_url(source_url)
        temporary: Path | None = None
        try:
            payload, metadata = (
                self.transport(url) if self.transport else self._fetch(url)
            )
            content_type = str(metadata.get("content_type") or "").lower()
            mime = content_type.split(";", 1)[0].strip()
            if mime not in ALLOWED_MIME:
                raise ValueError("evidence_mime_not_allowed")
            normalized = normalize_text(payload, content_type)
            needle = re.sub(r"\s+", " ", html.unescape(str(evidence_text))).strip()
            if not needle or len(needle) > MAX_EXCERPT_CHARS:
                raise ValueError("evidence_text_invalid")
            start = normalized.find(needle)
            if start < 0:
                raise ValueError("evidence_locator_not_verified")
            end = start + len(needle)
            record = {
                "schema": "mova-source-document-v1",
                "document_id": document_id,
                "research_run_id": research_run_id,
                "source_url": url,
                "final_url": canonical_public_url(metadata.get("final_url") or url),
                "fetch_status": "verified",
                "http_status": int(metadata.get("http_status") or 200),
                "content_type": content_type,
                "body_bytes": len(payload),
                "body_sha256": sha256_bytes(payload),
                "normalized_sha256": sha256_bytes(normalized.encode("utf-8")),
                "storage_mode": "minimal_excerpt",
                "locator_type": "normalized_char_range",
                "locator": f"{start}:{end}",
                "excerpt": needle,
                "excerpt_sha256": sha256_bytes(needle.encode("utf-8")),
                "error_code": None,
            }
            target = self.root / "evidence" / research_run_id / f"{document_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            body = (json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ) + "\n").encode("utf-8")
            temporary = target.with_suffix(f".json.tmp-{research_run_id[-8:]}")
            temporary.write_bytes(body)
            temporary.chmod(0o640)
            temporary.replace(target)
            temporary = None
            return {**record, "artifact_path": str(target),
                    "artifact_sha256": sha256_bytes(body)}
        except Exception as exc:  # failed discovery remains visible, never accepted evidence
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            return {
                "schema": "mova-source-document-v1", "document_id": document_id,
                "research_run_id": research_run_id, "source_url": url,
                "final_url": None, "fetch_status": "failed", "http_status": None,
                "content_type": None, "body_bytes": None, "body_sha256": None,
                "normalized_sha256": None, "storage_mode": "none",
                "locator_type": None, "locator": None, "excerpt": None,
                "excerpt_sha256": None, "artifact_path": None,
                "artifact_sha256": None, "error_code": _safe_error_code(exc),
            }

    def _fetch(self, url: str) -> tuple[bytes, dict]:
        opener = urllib.request.build_opener(_NoRedirect())
        current = url
        for _ in range(3):
            _assert_public_resolution(current)
            request = urllib.request.Request(
                current,
                headers={"User-Agent": "mova-fpl-evidence/1.0", "Accept-Encoding": "identity"},
                method="GET",
            )
            try:
                response = opener.open(request, timeout=self.timeout_seconds)
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    current = canonical_public_url(
                        urllib.parse.urljoin(current, exc.headers["Location"])
                    )
                    continue
                raise OSError(f"evidence_http_{exc.code}") from exc
            with response:
                length = response.headers.get("Content-Length")
                if length and int(length) > self.max_body_bytes:
                    raise ValueError("evidence_body_too_large")
                payload = response.read(self.max_body_bytes + 1)
                if len(payload) > self.max_body_bytes:
                    raise ValueError("evidence_body_too_large")
                return payload, {
                    "final_url": current, "http_status": int(response.status),
                    "content_type": response.headers.get("Content-Type", ""),
                }
        raise ValueError("evidence_redirect_limit")


def _safe_error_code(exc: Exception) -> str:
    """Return a stable diagnostic code without leaking URLs or response bodies."""
    message = str(exc)
    if re.fullmatch(r"evidence_[a-z0-9_]+", message):
        return message
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "evidence_timeout"
    if isinstance(exc, OSError):
        return "evidence_network_error"
    return "evidence_fetch_error"
