"""Serve the Loki Ventures Account Opening Form, validate + store each
submission, generate a signed record, and email the accounts team.

Forked from the Loki Ventures questionnaire_server.py pattern (InvoTrak /
ReceivingPlaybook). Standard-library only; PDF generation uses reportlab if it
is installed, otherwise a self-contained printable HTML record is produced.

Phases 1-2 of the Customer Account Creation automation:
  - Phase 1: capture form -> validate -> store -> signed record -> email.
  - Phase 2: accounts review dashboard APIs (list / detail+proposal / files /
    approve-reject with an append-only, hash-chained audit log).

The schema mirrors the paper Account Opening Form (docs/Acount Opening Form.pdf):
company info, directors/partners (each signs), delivery address, purchasing &
accounts contacts, business operations, two trade references, payment terms, the
return-policy acknowledgement, and the final authorisation signature. The credit
limit is NOT collected from the applicant — the accounts team sets it at review
(the form's "For Internal Use Only" box), which is the approval step here.

The ERP write (SAP B1 / ERPNext) is deliberately NOT here yet — that is Phases
3-4, behind the adapter, wired to the "approved" state produced here.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from env_loader import load_dotenv
from reference_data import (
    BUSINESS_CATEGORY_LABEL,
    ORDER_BY_LABEL,
    PAYMENT_METHODS_LABEL,
    PAYMENT_TERMS_LABEL,
    PRODUCT_LINES_LABEL,
    get_reference_data,
    labels,
)
from rules_engine import propose

load_dotenv()  # read .env before evaluating the config constants below

ROOT = Path(__file__).resolve().parent
SUBMISSIONS = ROOT / "submissions"
FORM_FILE = "account-capture.html"
DASHBOARD_FILE = "accounts-dashboard.html"
RECIPIENT = os.getenv("ACCOUNTS_RECIPIENT", "felixk@loki-ventures.com")
REVIEW_TOKEN = os.getenv("REVIEW_TOKEN", "")  # if set, review APIs require it
MAX_BODY_BYTES = 25 * 1024 * 1024  # room for several signatures + a few attachments
MAX_ATTACHMENTS = 8
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_DIRECTORS = 20

ALLOWED_DOC_KINDS = {"id", "kra_pin", "business_reg", "other"}
VALID_STATUSES = {"pending", "approved", "rejected", "created"}
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PIN_RE = re.compile(r"[A-Za-z]\d{9}[A-Za-z]")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", (value or "").strip()).strip("-")
    return cleaned[:50] or "unnamed"


def _s(container: dict, *path: str) -> str:
    """Safely fetch a nested string value."""
    cur = container
    for key in path:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(key)
    return cur.strip() if isinstance(cur, str) else ("" if cur is None else str(cur))


def _contact_errors(sub: dict, key: str, who: str) -> list[str]:
    errors = []
    if not _s(sub, key, "name"):
        errors.append(f"{who} contact name is required.")
    if not _s(sub, key, "phone"):
        errors.append(f"{who} contact phone is required.")
    email = _s(sub, key, "email")
    if not email:
        errors.append(f"{who} contact email is required.")
    elif not EMAIL_RE.fullmatch(email):
        errors.append(f"{who} contact email is invalid.")
    return errors


# --------------------------------------------------------------------------- #
# Validation — mirrors the canonical schema in 03-data-model-and-erp-mapping.md
# --------------------------------------------------------------------------- #
def validate(sub: dict) -> list[str]:
    errors: list[str] = []
    if sub.get("version") != "2":
        errors.append("Unsupported form version.")

    # Company information
    if not _s(sub, "company", "company_name"):
        errors.append("Company name is required.")
    if not _s(sub, "company", "type_of_business"):
        errors.append("Type of business is required.")
    cats = (sub.get("company") or {}).get("business_category")
    if not isinstance(cats, list) or not cats:
        errors.append("At least one business category is required.")
    pin = _s(sub, "company", "pin_number")
    if not pin:
        errors.append("KRA PIN number is required.")
    elif not PIN_RE.fullmatch(pin):
        errors.append("KRA PIN format is invalid.")

    # Directors / partners / proprietor — each signs
    directors = sub.get("directors")
    if not isinstance(directors, list) or not directors:
        errors.append("At least one director / partner / proprietor is required.")
    else:
        if len(directors) > MAX_DIRECTORS:
            errors.append("Too many directors listed.")
        for i, d in enumerate(directors, 1):
            d = d or {}
            if not str(d.get("name", "")).strip():
                errors.append(f"Director {i}: name is required.")
            if not str(d.get("id_no", "")).strip():
                errors.append(f"Director {i}: ID number is required.")
            if not d.get("signature_base64"):
                errors.append(f"Director {i}: signature is required.")

    # Delivery address (only when marked different)
    delivery = sub.get("delivery") or {}
    if delivery.get("different"):
        if not str(delivery.get("name", "")).strip():
            errors.append("Delivery contact name is required.")
        if not str(delivery.get("address", "")).strip():
            errors.append("Delivery address is required.")
        if not delivery.get("signature_base64"):
            errors.append("Delivery address signature is required.")

    # Department contacts
    errors += _contact_errors(sub, "purchasing_contact", "Purchasing")
    errors += _contact_errors(sub, "accounts_contact", "Accounts")

    # Business operations
    if not _s(sub, "operations", "nature_of_business"):
        errors.append("Nature of business is required.")
    prods = (sub.get("operations") or {}).get("product_lines")
    if not isinstance(prods, list) or not prods:
        errors.append("At least one product line of interest is required.")

    # Trade references — first one required
    refs = sub.get("trade_references") or []
    first = refs[0] if refs else {}
    if not str((first or {}).get("supplier_name", "")).strip():
        errors.append("At least one trade reference (supplier name) is required.")
    if not str((first or {}).get("phone", "")).strip():
        errors.append("The first trade reference needs a phone number.")

    # Payment terms & conditions
    payment = sub.get("payment") or {}
    if not isinstance(payment.get("preferred_methods"), list) or not payment.get("preferred_methods"):
        errors.append("At least one preferred payment method is required.")
    if payment.get("payment_terms") not in PAYMENT_TERMS_LABEL:
        errors.append("Valid payment terms are required.")
    if not isinstance(payment.get("order_by"), list) or not payment.get("order_by"):
        errors.append("Select how goods will be ordered.")

    # Return & expiry policy acknowledgement
    if not sub.get("policy_ack"):
        errors.append("The Return & Expiry Goods Policy must be acknowledged.")

    # Authorisation & signature
    if not _s(sub, "authorization", "name"):
        errors.append("Authorising name is required.")
    if not _s(sub, "authorization", "position"):
        errors.append("Authorising position is required.")
    if not _s(sub, "authorization", "date"):
        errors.append("Authorisation date is required.")
    auth = sub.get("authorization") or {}
    if not auth.get("signature_base64"):
        errors.append("An authorisation signature is required.")
    if not auth.get("consent_data_processing"):
        errors.append("Data-processing consent is required.")

    # Attachments
    atts = sub.get("attachments") or []
    if not isinstance(atts, list) or len(atts) > MAX_ATTACHMENTS:
        errors.append("Too many attachments.")
    for a in atts if isinstance(atts, list) else []:
        if (a or {}).get("kind") not in ALLOWED_DOC_KINDS:
            errors.append("An attachment has an invalid type.")
    return errors


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def _decode_b64(data: str) -> bytes | None:
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None


def _save_signature(folder: Path, b64: str, filename: str) -> str | None:
    """Write a base64 PNG signature to the folder; return the filename or None."""
    blob = _decode_b64(b64 or "")
    if not blob:
        return None
    (folder / filename).write_bytes(blob)
    return filename


def store_submission(sub: dict, raw_body: bytes, meta_extra: dict) -> dict:
    """Write record, signatures and attachments to a per-submission folder.
    Returns a summary dict (with an on-disk manifest, no base64 blobs)."""
    SUBMISSIONS.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    stem = f"{stamp}-{safe_name(_s(sub, 'company', 'company_name'))}-{uuid.uuid4().hex[:8]}"
    folder = SUBMISSIONS / stem
    folder.mkdir(parents=True, exist_ok=True)

    # Audit metadata
    meta = dict(sub.get("meta") or {})
    meta.update({
        "submission_id": stem,
        "received_at": now.isoformat(),
        "payload_hash": hashlib.sha256(raw_body).hexdigest(),
        **meta_extra,
    })
    sub["meta"] = meta
    sub.setdefault("approval", {})
    sub["approval"].update({
        "status": "pending",
        "credit_limit": None, "payment_terms": None, "price_list": None,
        "customer_group": None, "account_manager": None, "account_number": None,
        "approved_by": None, "erp_customer_code": None, "erp_backend": None,
    })

    # Signatures: directors, delivery, authorisation. Keep the base64 in `sub`
    # (used to build the signed record) but reference files in the JSON record.
    record = json.loads(json.dumps(sub))
    for i, d in enumerate(record.get("directors") or []):
        fname = _save_signature(folder, d.get("signature_base64", ""), f"director-{i:02d}-signature.png")
        d["signature_base64"] = fname or ""
    if (record.get("delivery") or {}).get("signature_base64"):
        fname = _save_signature(folder, record["delivery"]["signature_base64"], "delivery-signature.png")
        record["delivery"]["signature_base64"] = fname or ""
    if (record.get("authorization") or {}).get("signature_base64"):
        fname = _save_signature(folder, record["authorization"]["signature_base64"], "authorization-signature.png")
        record["authorization"]["signature_base64"] = fname or ""

    # Attachments -> files; keep a manifest without the blobs in the JSON record
    manifest = []
    for i, a in enumerate(sub.get("attachments") or []):
        blob = _decode_b64((a or {}).get("data") or "")
        if blob is None or len(blob) > MAX_ATTACHMENT_BYTES:
            continue
        kind = a.get("kind", "other")
        ext = Path(a.get("filename", "")).suffix or (".pdf" if "pdf" in (a.get("mime") or "") else ".bin")
        fname = f"{i:02d}-{safe_name(kind)}{ext}"
        (folder / fname).write_bytes(blob)
        manifest.append({"kind": kind, "filename": a.get("filename"), "mime": a.get("mime"), "stored": fname})
    record["attachments"] = manifest

    (folder / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # Signed human-readable record (embeds all signatures inline from `sub`)
    html_record = build_html_record(sub, meta, manifest)
    html_path = folder / "signed-application.html"
    html_path.write_text(html_record, encoding="utf-8")

    auth_sig = _decode_b64((sub.get("authorization") or {}).get("signature_base64") or "")
    pdf_path = try_build_pdf(folder, sub, meta, manifest, auth_sig)

    return {"stem": stem, "folder": folder, "html_path": html_path, "pdf_path": pdf_path, "manifest": manifest}


# --------------------------------------------------------------------------- #
# Signed record (HTML always; PDF if reportlab present)
# --------------------------------------------------------------------------- #
def build_html_record(sub: dict, meta: dict, manifest: list[dict]) -> str:
    co = sub.get("company", {})
    op = sub.get("operations", {})
    pay = sub.get("payment", {})
    auth = sub.get("authorization", {})
    delivery = sub.get("delivery", {})

    def rows(pairs):
        return "".join(
            f"<tr><th>{escape(str(k))}</th><td>{escape('' if v is None else str(v))}</td></tr>"
            for k, v in pairs
        )

    cats = labels(co.get("business_category"), BUSINESS_CATEGORY_LABEL)
    if "other" in (co.get("business_category") or []) and co.get("business_category_other"):
        cats += f" ({co['business_category_other']})"
    prods = labels(op.get("product_lines"), PRODUCT_LINES_LABEL)
    if "other" in (op.get("product_lines") or []) and op.get("product_lines_other"):
        prods += f" ({op['product_lines_other']})"

    def sig_img(b64):
        return (f'<img class="sig" src="data:image/png;base64,{escape(b64)}">'
                if b64 else "<span style='color:#9f3d31'>(not signed)</span>")

    directors_html = "".join(
        f"<tr><td>{escape(d.get('name',''))}</td><td>{escape(d.get('id_no',''))}</td>"
        f"<td>{escape(d.get('address',''))}</td><td>{escape(d.get('mobile',''))}</td>"
        f"<td>{sig_img(d.get('signature_base64',''))}</td></tr>"
        for d in (sub.get("directors") or [])
    ) or "<tr><td colspan=5>None provided</td></tr>"

    refs = sub.get("trade_references") or []
    refs_html = "".join(
        f"<tr><td>{escape(r.get('supplier_name',''))}</td><td>{escape(r.get('contact_person',''))}</td>"
        f"<td>{escape(r.get('email',''))}</td><td>{escape(r.get('phone',''))}</td></tr>"
        for r in refs if (r or {}).get("supplier_name")
    ) or "<tr><td colspan=4>None provided</td></tr>"

    docs_html = "".join(f"<li>{escape(m.get('kind',''))}: {escape(m.get('filename') or '')}</li>" for m in manifest) or "<li>None</li>"

    delivery_html = ""
    if delivery.get("different"):
        delivery_html = f"""<h2>Delivery address</h2><table>{rows([
          ("Name", delivery.get("name")), ("ID number", delivery.get("id_no")),
          ("Address", delivery.get("address")), ("Mobile", delivery.get("mobile"))])}</table>
          {sig_img(delivery.get("signature_base64",""))}"""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Account Opening Form — {escape(_s(sub,'company','company_name'))}</title>
<style>
 body{{font:13px/1.5 Segoe UI,Arial,sans-serif;color:#17332f;max-width:840px;margin:24px auto;padding:0 20px}}
 h1{{font-size:20px;border-bottom:3px solid #123c35;padding-bottom:8px;margin-bottom:2px}}
 .sub{{color:#63706d;margin:0 0 18px}}
 h2{{font-size:14px;text-transform:uppercase;letter-spacing:.05em;color:#123c35;margin:22px 0 6px}}
 table{{border-collapse:collapse;width:100%;margin-bottom:8px}}
 th,td{{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid #e4e7e2;font-size:13px}}
 th{{color:#63706d;font-weight:600}}
 table.kv th{{width:210px}}
 .sig{{border:1px solid #cbd2ce;border-radius:8px;max-width:240px;background:#fff}}
 .audit{{background:#f3f6f3;border:1px solid #dfe5df;border-radius:8px;padding:12px;margin-top:12px;font-size:12px;color:#3d4a47}}
 .audit code{{word-break:break-all}}
 @media print{{body{{margin:0}}}}
</style></head><body>
<h1>Loki Ventures Limited — Account Opening Form</h1>
<p class="sub">Reference {escape(meta.get('submission_id',''))} · Status: PENDING REVIEW</p>

<h2>Company information</h2><table class="kv">{rows([
  ("Company name", co.get("company_name")), ("Trading name", co.get("trading_name")),
  ("Registration no.", co.get("registration_no")), ("Type of business", co.get("type_of_business")),
  ("Business category", cats), ("PIN number", co.get("pin_number")),
  ("VAT number", co.get("vat_number")), ("Year established", co.get("year_established"))])}</table>

<h2>Directors / Partners / Proprietor</h2>
<table><tr><th>Name</th><th>ID</th><th>Address</th><th>Mobile</th><th>Signature</th></tr>{directors_html}</table>

{delivery_html}

<h2>Purchasing contact</h2><table class="kv">{rows([
  ("Main contact", _s(sub,'purchasing_contact','name')), ("Position", _s(sub,'purchasing_contact','position')),
  ("Email", _s(sub,'purchasing_contact','email')), ("Phone", _s(sub,'purchasing_contact','phone'))])}</table>

<h2>Accounts contact</h2><table class="kv">{rows([
  ("Main contact", _s(sub,'accounts_contact','name')), ("Position", _s(sub,'accounts_contact','position')),
  ("Email", _s(sub,'accounts_contact','email')), ("Phone", _s(sub,'accounts_contact','phone'))])}</table>

<h2>Business operations</h2><table class="kv">{rows([
  ("Nature of business", op.get("nature_of_business")), ("Number of branches", op.get("number_of_branches")),
  ("Average monthly orders", op.get("avg_monthly_orders")), ("Product lines of interest", prods)])}</table>

<h2>Trade references</h2>
<table><tr><th>Supplier</th><th>Contact person</th><th>Email</th><th>Phone</th></tr>{refs_html}</table>

<h2>Payment terms &amp; conditions</h2><table class="kv">{rows([
  ("Preferred method", labels(pay.get("preferred_methods"), PAYMENT_METHODS_LABEL)),
  ("Payment terms", PAYMENT_TERMS_LABEL.get(pay.get("payment_terms",""), pay.get("payment_terms",""))),
  ("Goods ordered by", labels(pay.get("order_by"), ORDER_BY_LABEL))])}</table>

<h2>Supporting documents</h2><ul>{docs_html}</ul>

<h2>Return &amp; expiry goods policy</h2>
<p>{'Acknowledged and agreed.' if sub.get('policy_ack') else 'NOT acknowledged.'}</p>

<h2>Signatures &amp; authorisation</h2>
<p>I, the undersigned, certify that the information provided is accurate and agree to the terms
outlined in this application form, including the return policy and expiry of goods.</p>
<table class="kv">{rows([
  ("Name", auth.get("name")), ("Position", auth.get("position")), ("Date", auth.get("date")),
  ("Signed at (UTC)", auth.get("signed_at")),
  ("Consent given", "Yes" if auth.get("consent_data_processing") else "No")])}</table>
{sig_img(auth.get("signature_base64",""))}

<div class="audit"><b>Audit trail</b><br>
 Submission ID: {escape(meta.get('submission_id',''))}<br>
 Received (UTC): {escape(meta.get('received_at',''))}<br>
 Capture mode: {escape(meta.get('capture_mode',''))} · Salesperson: {escape(meta.get('salesperson_name',''))}<br>
 Source IP: {escape(meta.get('source_ip',''))}<br>
 User agent: {escape(meta.get('user_agent',''))}<br>
 Payload SHA-256: <code>{escape(meta.get('payload_hash',''))}</code>
</div>
</body></html>"""


def try_build_pdf(folder: Path, sub: dict, meta: dict, manifest: list[dict], auth_sig: bytes | None) -> Path | None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdfcanvas
        from reportlab.lib.utils import ImageReader
    except ImportError:
        return None  # HTML record is the fallback; see README

    pdf_path = folder / "signed-application.pdf"
    c = pdfcanvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    y = height - 22 * mm

    def line(text, dy=5.6 * mm, bold=False, size=10):
        nonlocal y
        if y < 25 * mm:
            c.showPage()
            y = height - 22 * mm
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(20 * mm, y, str(text)[:115])
        y -= dy

    co = sub.get("company", {})
    op = sub.get("operations", {})
    pay = sub.get("payment", {})
    auth = sub.get("authorization", {})
    line("Loki Ventures — Account Opening Form", 8 * mm, bold=True, size=15)
    line(f"Ref {meta.get('submission_id','')}  |  Status: PENDING REVIEW", 8 * mm, size=9)

    cats = labels(co.get("business_category"), BUSINESS_CATEGORY_LABEL)
    blocks = [
        ("COMPANY", [("Company name", co.get("company_name")), ("Trading name", co.get("trading_name")),
                     ("Registration no.", co.get("registration_no")), ("Type of business", co.get("type_of_business")),
                     ("Category", cats), ("PIN", co.get("pin_number")), ("VAT", co.get("vat_number")),
                     ("Year established", co.get("year_established"))]),
        ("DIRECTORS / PARTNERS", [(f"{d.get('name','')}", f"ID {d.get('id_no','')}"
                                   f"{'  (signed)' if d.get('signature_base64') else ''}")
                                  for d in (sub.get("directors") or [])]),
        ("PURCHASING CONTACT", [("Name", _s(sub, "purchasing_contact", "name")),
                                ("Email", _s(sub, "purchasing_contact", "email")),
                                ("Phone", _s(sub, "purchasing_contact", "phone"))]),
        ("ACCOUNTS CONTACT", [("Name", _s(sub, "accounts_contact", "name")),
                              ("Email", _s(sub, "accounts_contact", "email")),
                              ("Phone", _s(sub, "accounts_contact", "phone"))]),
        ("OPERATIONS", [("Nature", op.get("nature_of_business")), ("Branches", op.get("number_of_branches")),
                        ("Avg monthly orders", op.get("avg_monthly_orders")),
                        ("Product lines", labels(op.get("product_lines"), PRODUCT_LINES_LABEL))]),
        ("PAYMENT", [("Method", labels(pay.get("preferred_methods"), PAYMENT_METHODS_LABEL)),
                     ("Terms", PAYMENT_TERMS_LABEL.get(pay.get("payment_terms", ""), "")),
                     ("Order by", labels(pay.get("order_by"), ORDER_BY_LABEL))]),
        ("AUTHORISATION", [("Name", auth.get("name")), ("Position", auth.get("position")),
                           ("Date", auth.get("date")),
                           ("Consent", "Yes" if auth.get("consent_data_processing") else "No"),
                           ("Return policy", "Acknowledged" if sub.get("policy_ack") else "Not acknowledged")]),
    ]
    for title, pairs in blocks:
        line(title, 5.6 * mm, bold=True, size=11)
        for k, v in pairs:
            line(f"   {k}: {'' if v is None else v}", 4.9 * mm, size=9.5)
        y -= 1.6 * mm

    if auth_sig:
        try:
            line("Authorised signature:", 6 * mm, bold=True)
            c.drawImage(ImageReader(folder / "authorization-signature.png"), 20 * mm, y - 26 * mm,
                        width=66 * mm, height=26 * mm, preserveAspectRatio=True, mask="auto")
            y -= 30 * mm
        except Exception:
            pass

    c.setFont("Helvetica", 7)
    c.drawString(20 * mm, 15 * mm, f"Received {meta.get('received_at','')} | IP {meta.get('source_ip','')}")
    c.drawString(20 * mm, 11 * mm, f"SHA-256 {meta.get('payload_hash','')}")
    c.showPage()
    c.save()
    return pdf_path


# --------------------------------------------------------------------------- #
# Email (Microsoft Graph, SMTP fallback) — same shape as questionnaire_server.py
# --------------------------------------------------------------------------- #
def email_summary(sub: dict, meta: dict) -> tuple[str, str]:
    name = _s(sub, "company", "company_name") or "Unnamed company"
    pay = sub.get("payment", {})
    terms = PAYMENT_TERMS_LABEL.get(pay.get("payment_terms", ""), "")
    subject = f"New Account Opening Application - {name} - {terms}"
    body = "\n".join([
        "A new customer account application was submitted for review.",
        "",
        f"Reference:      {meta.get('submission_id','')}",
        f"Company:        {name}",
        f"Type / category:{_s(sub,'company','type_of_business')} | {labels((sub.get('company') or {}).get('business_category'), BUSINESS_CATEGORY_LABEL)}",
        f"KRA PIN:        {_s(sub,'company','pin_number')}",
        f"Purchasing:     {_s(sub,'purchasing_contact','name')} | {_s(sub,'purchasing_contact','phone')} | {_s(sub,'purchasing_contact','email')}",
        f"Accounts:       {_s(sub,'accounts_contact','name')} | {_s(sub,'accounts_contact','phone')} | {_s(sub,'accounts_contact','email')}",
        "",
        f"Requested terms:  {terms}",
        f"Payment methods:  {labels(pay.get('preferred_methods'), PAYMENT_METHODS_LABEL)}",
        f"Product lines:    {labels((sub.get('operations') or {}).get('product_lines'), PRODUCT_LINES_LABEL)}",
        f"Directors listed: {len(sub.get('directors') or [])}",
        "",
        f"Authorised by:  {_s(sub,'authorization','name')} ({_s(sub,'authorization','position')})",
        f"Capture mode:   {meta.get('capture_mode','')}  Salesperson: {meta.get('salesperson_name','')}",
        "",
        "NOTE: the credit limit is set by accounts at review (the form's 'For Internal Use Only' box).",
        "",
        "The signed application is attached. Full record and any uploaded documents are stored under:",
        f"  submissions/{meta.get('submission_id','')}/",
        "",
        "NEXT STEP: review and approve in the accounts dashboard (Phase 2) before the account is created in the ERP.",
    ])
    return subject, body


def _attachment(path: Path, mime: str) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": path.name,
        "contentType": mime,
        "contentBytes": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def send_graph_email(sub: dict, meta: dict, stored: dict) -> None:
    tenant = os.getenv("GRAPH_TENANT_ID", "").strip()
    client_id = os.getenv("GRAPH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GRAPH_CLIENT_SECRET", "")
    sender = os.getenv("GRAPH_SENDER", "").strip()
    missing = [n for n, v in {"GRAPH_TENANT_ID": tenant, "GRAPH_CLIENT_ID": client_id,
                              "GRAPH_CLIENT_SECRET": client_secret, "GRAPH_SENDER": sender}.items() if not v]
    if missing:
        raise RuntimeError("Missing Microsoft Graph settings: " + ", ".join(missing))

    token_request = Request(
        f"https://login.microsoftonline.com/{quote(tenant, safe='')}/oauth2/v2.0/token",
        data=urlencode({"client_id": client_id, "client_secret": client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials"}).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(token_request, timeout=30) as response:
            access_token = json.loads(response.read().decode("utf-8"))["access_token"]
    except (HTTPError, URLError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Microsoft Graph token request failed: {exc}") from exc

    subject, body = email_summary(sub, meta)
    attachments = []
    if stored.get("pdf_path"):
        attachments.append(_attachment(stored["pdf_path"], "application/pdf"))
    else:
        attachments.append(_attachment(stored["html_path"], "text/html"))

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": RECIPIENT}}],
            "attachments": attachments,
        },
        "saveToSentItems": True,
    }
    mail_request = Request(
        f"https://graph.microsoft.com/v1.0/users/{quote(sender, safe='')}/sendMail",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urlopen(mail_request, timeout=30) as response:
            if response.status not in {200, 202}:
                raise RuntimeError(f"Microsoft Graph returned HTTP {response.status}")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Microsoft Graph sendMail failed: {exc}") from exc


def send_smtp_email(sub: dict, meta: dict, stored: dict) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip() or os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "") or os.getenv("SMTP_PASS", "")
    sender = os.getenv("SMTP_FROM", "").strip() or username
    if not host or not sender:
        raise RuntimeError("SMTP_HOST and SMTP_FROM (or SMTP_USERNAME) are required")

    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = env_bool("SMTP_USE_SSL")
    use_tls = env_bool("SMTP_USE_TLS", default=not use_ssl)
    subject, body = email_summary(sub, meta)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = RECIPIENT
    message["Subject"] = subject
    message.set_content(body)
    if stored.get("pdf_path"):
        message.add_attachment(stored["pdf_path"].read_bytes(), maintype="application", subtype="pdf",
                               filename=stored["pdf_path"].name)
    else:
        message.add_attachment(stored["html_path"].read_bytes(), maintype="text", subtype="html",
                               filename=stored["html_path"].name)

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls(context=context)
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)


def send_email(sub: dict, meta: dict, stored: dict) -> None:
    if any(os.getenv(k) for k in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_SENDER")):
        send_graph_email(sub, meta, stored)
    else:
        send_smtp_email(sub, meta, stored)


# --------------------------------------------------------------------------- #
# Review / approval (Phase 2)
# --------------------------------------------------------------------------- #
SUB_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9_-]+-[0-9a-f]{8}$")
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PROTECTED_FILES = {"record.json", "audit-log.jsonl"}


def resolve_folder(sub_id: str) -> Path | None:
    """Return the submission folder only if sub_id is well-formed and inside SUBMISSIONS."""
    if not SUB_ID_RE.match(sub_id or ""):
        return None
    folder = (SUBMISSIONS / sub_id).resolve()
    try:
        folder.relative_to(SUBMISSIONS.resolve())
    except ValueError:
        return None
    return folder if (folder / "record.json").is_file() else None


def read_record(folder: Path) -> dict:
    return json.loads((folder / "record.json").read_text(encoding="utf-8"))


def write_record(folder: Path, record: dict) -> None:
    (folder / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _location(record: dict) -> str:
    delivery = record.get("delivery") or {}
    if delivery.get("different") and delivery.get("address"):
        return delivery["address"]
    directors = record.get("directors") or []
    return (directors[0].get("address") if directors else "") or ""


def summarise(record: dict) -> dict:
    meta = record.get("meta") or {}
    co = record.get("company") or {}
    pay = record.get("payment") or {}
    appr = record.get("approval") or {}
    flags = propose(record).get("flags", [])
    return {
        "id": meta.get("submission_id", ""),
        "status": appr.get("status", "pending"),
        "customer_name": co.get("company_name", ""),
        "type_of_business": co.get("type_of_business", ""),
        "location": _location(record),
        "payment_terms": pay.get("payment_terms", ""),
        "received_at": meta.get("received_at", ""),
        "warn_flags": sum(1 for f in flags if f.get("level") == "warn"),
    }


def list_submissions(status_filter: str = "") -> list[dict]:
    if not SUBMISSIONS.is_dir():
        return []
    out = []
    for folder in SUBMISSIONS.iterdir():
        if not folder.is_dir() or not (folder / "record.json").is_file():
            continue
        try:
            record = read_record(folder)
        except (json.JSONDecodeError, OSError):
            continue
        s = summarise(record)
        if status_filter and status_filter != "all" and s["status"] != status_filter:
            continue
        out.append(s)
    out.sort(key=lambda r: r.get("received_at", ""), reverse=True)
    return out


def append_audit(folder: Path, seed_hash: str, action: str, actor: str, details: dict) -> dict:
    """Append a hash-chained entry to audit-log.jsonl (tamper-evident, append-only)."""
    log = folder / "audit-log.jsonl"
    prev_hash = seed_hash
    seq = 1
    if log.is_file():
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            last = json.loads(lines[-1])
            prev_hash = last.get("entry_hash", seed_hash)
            seq = int(last.get("seq", 0)) + 1
    entry = {
        "seq": seq,
        "at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "actor": actor or "unknown",
        "details": details or {},
        "prev_hash": prev_hash,
    }
    entry["entry_hash"] = hashlib.sha256(
        (prev_hash + json.dumps(entry, sort_keys=True, ensure_ascii=False)).encode("utf-8")
    ).hexdigest()
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_audit(folder: Path) -> list[dict]:
    log = folder / "audit-log.jsonl"
    if not log.is_file():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def apply_decision(sub_id: str, body: dict) -> tuple[HTTPStatus, dict]:
    folder = resolve_folder(sub_id)
    if not folder:
        return HTTPStatus.NOT_FOUND, {"error": "Application not found."}
    record = read_record(folder)
    appr = record.setdefault("approval", {})
    if appr.get("status") in {"approved", "rejected", "created"}:
        return HTTPStatus.CONFLICT, {"error": f"Application already {appr.get('status')}."}

    action = body.get("action")
    reviewer = str(body.get("reviewer") or "").strip()
    if not reviewer:
        return HTTPStatus.BAD_REQUEST, {"error": "Reviewer name is required."}
    if action not in {"approve", "reject"}:
        return HTTPStatus.BAD_REQUEST, {"error": "Action must be approve or reject."}

    now = datetime.now(timezone.utc).isoformat()
    seed = (record.get("meta") or {}).get("payload_hash", "")

    if action == "reject":
        reason = str(body.get("notes") or "").strip()
        if not reason:
            return HTTPStatus.BAD_REQUEST, {"error": "A reason is required to reject."}
        appr.update({"status": "rejected", "reviewed_by": reviewer, "reviewed_at": now, "notes": reason})
        write_record(folder, record)
        entry = append_audit(folder, seed, "rejected", reviewer, {"reason": reason})
        return HTTPStatus.OK, {"ok": True, "status": "rejected", "audit": entry}

    # approve — the accounts team fills the "For Internal Use Only" box
    ref = get_reference_data()
    valid_terms = {t[0] for t in ref["payment_terms"]}
    try:
        credit_limit = float(body.get("credit_limit"))
        if credit_limit < 0:
            raise ValueError
    except (TypeError, ValueError):
        return HTTPStatus.BAD_REQUEST, {"error": "Credit limit must be a number ≥ 0."}
    final_terms = body.get("payment_terms")
    if final_terms not in valid_terms:
        return HTTPStatus.BAD_REQUEST, {"error": "Invalid payment terms."}
    price_list = str(body.get("price_list") or "").strip()
    group = str(body.get("customer_group") or "").strip()
    if price_list and price_list not in ref["price_lists"]:
        return HTTPStatus.BAD_REQUEST, {"error": "Invalid price list."}
    if group and group not in ref["customer_groups"]:
        return HTTPStatus.BAD_REQUEST, {"error": "Invalid customer group."}
    account_manager = str(body.get("account_manager") or "").strip()
    account_number = str(body.get("account_number") or "").strip()

    appr.update({
        "status": "approved", "reviewed_by": reviewer, "reviewed_at": now,
        "credit_limit": credit_limit, "payment_terms": final_terms,
        "price_list": price_list, "customer_group": group,
        "account_manager": account_manager, "account_number": account_number,
        "approved_by": reviewer,
        "notes": str(body.get("notes") or "").strip(),
        "erp_backend": None, "erp_customer_code": None,  # set by Phase 3 adapter
    })
    write_record(folder, record)
    entry = append_audit(folder, seed, "approved", reviewer, {
        "credit_limit": credit_limit, "payment_terms": final_terms,
        "price_list": price_list, "customer_group": group,
        "account_manager": account_manager, "account_number": account_number,
    })
    return HTTPStatus.OK, {"ok": True, "status": "approved", "audit": entry}


# --------------------------------------------------------------------------- #
# ERP create (Phase 3) — turn an approved record into a customer master
# --------------------------------------------------------------------------- #
def erp_status() -> dict:
    backend = (os.getenv("ERP_BACKEND", "") or "").strip().lower()
    return {"backend": backend or "none",
            "configured": backend not in ("", "none", "off")}


def create_in_erp(sub_id: str, reviewer: str, dry_run: bool) -> tuple[HTTPStatus, dict]:
    folder = resolve_folder(sub_id)
    if not folder:
        return HTTPStatus.NOT_FOUND, {"error": "Application not found."}
    record = read_record(folder)
    appr = record.setdefault("approval", {})
    status = appr.get("status")

    # Dry-run: build and return the exact SAP payload without connecting.
    from sap_mapping import build_business_partner, mapping_warnings
    if dry_run:
        return HTTPStatus.OK, {"dry_run": True, "status": status,
                               "payload": build_business_partner(record),
                               "warnings": mapping_warnings(record),
                               "note": ("" if status == "approved"
                                        else "Record is not approved yet — credit terms may be blank.")}

    if status == "created":
        return HTTPStatus.CONFLICT, {"error": f"Already created in ERP as "
                                     f"{appr.get('erp_customer_code')}."}
    if status != "approved":
        return HTTPStatus.BAD_REQUEST, {"error": "Approve the application before creating it in the ERP."}
    if not reviewer.strip():
        return HTTPStatus.BAD_REQUEST, {"error": "Reviewer name is required."}

    from erp_adapter import get_adapter, ErpError, DuplicateCustomerError
    try:
        adapter = get_adapter()
    except ErpError as exc:
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
    if adapter is None:
        return HTTPStatus.BAD_REQUEST, {"error": "ERP integration is off (set ERP_BACKEND)."}

    try:
        result = adapter.create_customer(record)
    except DuplicateCustomerError as exc:
        return HTTPStatus.CONFLICT, {"error": str(exc), "card_code": exc.card_code}
    except ErpError as exc:
        return HTTPStatus.BAD_GATEWAY, {"error": str(exc)}
    finally:
        try:
            adapter.logout()
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()
    appr.update({"status": "created", "erp_backend": result.get("backend"),
                 "erp_customer_code": result.get("card_code"), "created_at": now,
                 "created_by": reviewer.strip()})
    write_record(folder, record)
    seed = (record.get("meta") or {}).get("payload_hash", "")
    entry = append_audit(folder, seed, "created", reviewer, {
        "backend": result.get("backend"), "erp_customer_code": result.get("card_code")})
    return HTTPStatus.OK, {"ok": True, "status": "created",
                           "erp_customer_code": result.get("card_code"),
                           "backend": result.get("backend"),
                           "warnings": result.get("warnings", []), "audit": entry}


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class AccountHandler(SimpleHTTPRequestHandler):
    server_version = "AccountApplication/2"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == self.headers.get("Host")

    def _review_authed(self) -> bool:
        """Review APIs are open if REVIEW_TOKEN is unset (dev), else require the token."""
        if not REVIEW_TOKEN:
            return True
        supplied = self.headers.get("X-Review-Token", "")
        if not supplied:
            supplied = parse_qs(urlsplit(self.path).query).get("token", [""])[0]
        return hmac.compare_digest(supplied, REVIEW_TOKEN)

    # ---- GET: static files + review read APIs ------------------------------ #
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            super().do_GET()
            return
        if not self._review_authed():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Review token required or invalid."})
            return

        if path == "/api/reference-data":
            self._json(HTTPStatus.OK, get_reference_data())
            return
        if path == "/api/erp/status":
            self._json(HTTPStatus.OK, erp_status())
            return
        if path == "/api/submissions":
            status = parse_qs(urlsplit(self.path).query).get("status", [""])[0]
            self._json(HTTPStatus.OK, {"submissions": list_submissions(status),
                                       "auth_required": bool(REVIEW_TOKEN)})
            return

        m = re.match(r"^/api/submissions/([^/]+)$", path)
        if m:
            folder = resolve_folder(m.group(1))
            if not folder:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Application not found."})
                return
            record = read_record(folder)
            files = sorted(p.name for p in folder.iterdir()
                           if p.is_file() and p.name not in PROTECTED_FILES)
            self._json(HTTPStatus.OK, {
                "record": record,
                "recommendation": propose(record),
                "reference": get_reference_data(),
                "files": files,
                "audit": read_audit(folder),
            })
            return

        m = re.match(r"^/api/submissions/([^/]+)/files/([^/]+)$", path)
        if m:
            folder = resolve_folder(m.group(1))
            fname = m.group(2)
            if not folder or not SAFE_FILE_RE.match(fname):
                self._json(HTTPStatus.NOT_FOUND, {"error": "File not found."})
                return
            target = (folder / fname).resolve()
            try:
                target.relative_to(folder.resolve())
            except ValueError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "File not found."})
                return
            if not target.is_file() or target.name in PROTECTED_FILES:
                self._json(HTTPStatus.NOT_FOUND, {"error": "File not found."})
                return
            data = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _read_json_body(self) -> tuple[dict | None, bytes]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            return None, b""
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")), raw
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, raw

    def do_POST(self) -> None:
        path = urlsplit(self.path).path

        # ---- Review decision (approve / reject) ---------------------------- #
        m = re.match(r"^/api/submissions/([^/]+)/decision$", path)
        if m:
            if not self._review_authed():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Review token required or invalid."})
                return
            if not self._same_origin():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Origin rejected"})
                return
            body, _ = self._read_json_body()
            if body is None:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
                return
            status, payload = apply_decision(m.group(1), body)
            self._json(status, payload)
            return

        # ---- ERP create (Phase 3) ------------------------------------------ #
        m = re.match(r"^/api/submissions/([^/]+)/create-erp$", path)
        if m:
            if not self._review_authed():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Review token required or invalid."})
                return
            if not self._same_origin():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Origin rejected"})
                return
            body, _ = self._read_json_body()
            if body is None:
                body = {}
            dry_run = bool(body.get("dry_run")) or \
                parse_qs(urlsplit(self.path).query).get("dry_run", ["0"])[0] in ("1", "true")
            status, payload = create_in_erp(m.group(1), str(body.get("reviewer") or ""), dry_run)
            self._json(status, payload)
            return

        # ---- Public application submit ------------------------------------- #
        if path != "/api/submit":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        if self.headers.get("X-Account-Submit") != "v1" or not self._same_origin():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Submission origin was rejected"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Invalid submission size"})
            return

        raw = self.rfile.read(length)
        try:
            sub = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON submission"})
            return

        errors = validate(sub)
        if errors:
            self._json(HTTPStatus.BAD_REQUEST, {"error": errors[0], "errors": errors})
            return

        meta_extra = {
            "source_ip": self.client_address[0] if self.client_address else "",
            "user_agent": self.headers.get("User-Agent", ""),
        }
        try:
            stored = store_submission(sub, raw, meta_extra)
        except Exception as exc:  # storage must not lose data silently
            print(f"Failed to store submission: {exc}", file=sys.stderr)
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not save the application."})
            return

        try:
            send_email(sub, sub["meta"], stored)
        except Exception as exc:
            print(f"Submission {stored['stem']} saved but email failed: {exc}", file=sys.stderr)
            self._json(HTTPStatus.OK, {"saved": True, "emailed": False,
                                       "submission_id": stored["stem"], "email_error": str(exc)})
            return

        self._json(HTTPStatus.OK, {"saved": True, "emailed": True, "submission_id": stored["stem"]})


def main() -> None:
    host = os.getenv("ACCOUNT_HOST", "0.0.0.0")
    port = int(os.getenv("ACCOUNT_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), AccountHandler)
    print(f"Loki Account Opening Form running:  http://{host}:{port}/{FORM_FILE}")
    print(f"Accounts review dashboard:          http://{host}:{port}/{DASHBOARD_FILE}")
    print(f"Applications are emailed to {RECIPIENT} and stored in {SUBMISSIONS}")
    print("Review APIs are " + ("PROTECTED by REVIEW_TOKEN." if REVIEW_TOKEN
                                else "OPEN (set REVIEW_TOKEN to require a token)."))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
