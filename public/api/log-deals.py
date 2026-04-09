"""
api/log-deals.py — Vercel serverless function
Reads a PDF, extracts deals via Claude, then logs them to Affinity.
"""

import os
import json
import base64
import requests
from http.server import BaseHTTPRequestHandler
import cgi
import io

AFFINITY_API_KEY = os.environ.get("AFFINITY_API_KEY")
AFFINITY_LIST_ID = os.environ.get("AFFINITY_LIST_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

AFFINITY_BASE = "https://api.affinity.co"
AFFINITY_HEADERS = {
    "Authorization": f"Bearer {AFFINITY_API_KEY}",
    "Content-Type": "application/json"
}


def extract_deals_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """Send PDF to Claude and extract structured deal list."""
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract all companies from this deal list. "
                            "Return ONLY a JSON array, no markdown, no preamble. "
                            "Each object must have exactly these keys: "
                            "\"name\" (company name), \"domain\" (website domain, e.g. acme.com), "
                            "\"pitch\" (one-sentence description of what they do). "
                            "If domain is missing, make your best guess from the company name. "
                            "Example: [{\"name\": \"Acme\", \"domain\": \"acme.com\", \"pitch\": \"AI for procurement.\"}]"
                        )
                    }
                ]
            }
        ]
    }

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json=payload,
        timeout=60
    )
    r.raise_for_status()
    text = r.json()["content"][0]["text"].strip()
    # Strip any accidental markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def find_or_create_org(name: str, domain: str) -> tuple[int, str]:
    r = requests.get(
        f"{AFFINITY_BASE}/organizations",
        headers=AFFINITY_HEADERS,
        params={"term": domain},
        timeout=15
    )
    r.raise_for_status()
    for org in r.json().get("organizations", []):
        if domain in org.get("domains", []):
            return org["id"], "found"
    payload = {"name": name, "domain": domain}
    r2 = requests.post(f"{AFFINITY_BASE}/organizations", headers=AFFINITY_HEADERS, json=payload, timeout=15)
    r2.raise_for_status()
    return r2.json()["id"], "created"


def add_to_list(org_id: int) -> int:
    payload = {"entity_id": org_id, "entity_type": 0}
    r = requests.post(
        f"{AFFINITY_BASE}/lists/{AFFINITY_LIST_ID}/list-entries",
        headers=AFFINITY_HEADERS,
        json=payload,
        timeout=15
    )
    if r.status_code == 422:
        r2 = requests.get(
            f"{AFFINITY_BASE}/lists/{AFFINITY_LIST_ID}/list-entries",
            headers=AFFINITY_HEADERS,
            params={"organization_id": org_id},
            timeout=15
        )
        r2.raise_for_status()
        entries = r2.json()
        if entries:
            return entries[0]["id"]
    r.raise_for_status()
    return r.json()["id"]


def get_field_ids() -> dict:
    r = requests.get(f"{AFFINITY_BASE}/lists/{AFFINITY_LIST_ID}/fields", headers=AFFINITY_HEADERS, timeout=15)
    r.raise_for_status()
    return {f["name"].lower(): f["id"] for f in r.json()}


def set_field_dropdown(entry_id: int, field_id: int, option_text: str):
    r = requests.get(f"{AFFINITY_BASE}/fields/{field_id}", headers=AFFINITY_HEADERS, timeout=15)
    if not r.ok:
        return False
    options = r.json().get("dropdown_options", [])
    option_id = next((o["id"] for o in options if o["text"].lower() == option_text.lower()), None)
    if not option_id:
        return False
    r2 = requests.post(
        f"{AFFINITY_BASE}/field-values",
        headers=AFFINITY_HEADERS,
        json={"field_id": field_id, "list_entry_id": entry_id, "value": option_id},
        timeout=15
    )
    return r2.ok


def add_note(org_id: int, pitch: str):
    r = requests.post(
        f"{AFFINITY_BASE}/notes",
        headers=AFFINITY_HEADERS,
        json={
            "organization_ids": [org_id],
            "content": f"**Inbound Pitch (Deal Networks)**\n\n{pitch}"
        },
        timeout=15
    )
    return r.ok


def process_deals(pdf_bytes: bytes) -> dict:
    log = []
    logged = []
    failed = []

    def L(type_, msg):
        log.append({"type": type_, "msg": msg})

    try:
        L("info", "Extracting deals from PDF via Claude...")
        deals = extract_deals_from_pdf(pdf_bytes)
        L("ok", f"Found {len(deals)} deal(s) in PDF")
    except Exception as e:
        L("err", f"PDF extraction failed: {e}")
        return {"logged": [], "failed": [], "log": log}

    try:
        field_ids = get_field_ids()
    except Exception as e:
        L("err", f"Could not fetch Affinity field IDs: {e}")
        return {"logged": [], "failed": [], "log": log}

    for deal in deals:
        name = deal.get("name", "Unknown")
        domain = deal.get("domain", "")
        pitch = deal.get("pitch", "")
        L("info", f"Processing: {name}")
        try:
            org_id, status = find_or_create_org(name, domain)
            L("ok", f"  Org {status}: {name} (id={org_id})")

            entry_id = add_to_list(org_id)
            L("ok", f"  Added to pipeline (entry={entry_id})")

            src_id = field_ids.get("internal source")
            if src_id and set_field_dropdown(entry_id, src_id, "Deal Networks"):
                L("ok", "  Internal Source → Deal Networks")
            else:
                L("warn", "  Could not set Internal Source")

            if add_note(org_id, pitch):
                L("ok", "  Note added")
            else:
                L("warn", "  Note failed")

            stat_id = field_ids.get("status")
            if stat_id and set_field_dropdown(entry_id, stat_id, "Passed"):
                L("ok", "  Status → Passed")
            else:
                L("warn", "  Could not set Status")

            logged.append(name)
        except Exception as e:
            L("err", f"  Error: {e}")
            failed.append(name)

    return {"logged": logged, "failed": failed, "log": log}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        ctype, pdict = cgi.parse_header(self.headers.get("content-type", ""))
        if ctype != "multipart/form-data":
            self._json(400, {"error": "Expected multipart/form-data"})
            return

        pdict["boundary"] = bytes(pdict["boundary"], "utf-8")
        pdict["CONTENT-LENGTH"] = int(self.headers.get("content-length", 0))
        fields = cgi.parse_multipart(self.rfile, pdict)

        pdf_files = fields.get("pdf")
        if not pdf_files:
            self._json(400, {"error": "No PDF uploaded"})
            return

        pdf_bytes = pdf_files[0] if isinstance(pdf_files[0], bytes) else pdf_files[0].encode()
        result = process_deals(pdf_bytes)
        self._json(200, result)

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
