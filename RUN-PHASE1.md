# Phase 1 — Run & Test Guide

The paperless capture form + signature + server are built. This is how to run and test them.

## What Phase 1 delivers
- `account-capture.html` — the customer/salesperson application form (self-serve + assisted),
  multi-step, mobile-friendly, with a drawn **signature** and consent. Autosaves on the device.
- `account_server.py` — receives the submission, **validates** it, stores everything, generates a
  **signed record** (HTML always; PDF if `reportlab` is installed), and **emails the accounts team**.
- Each submission is stored under `submissions/<reference>/`:
  `record.json` (canonical data + audit), `signature.png`, uploaded documents, `signed-application.html`
  (and `signed-application.pdf` when reportlab is present).

> Not in Phase 1: the ERP write (SAP B1 / ERPNext) — that's Phases 3–4, behind the adapter.
> For now every application lands as **PENDING REVIEW**.

## Requirements
- Python 3.10+ (uses only the standard library).
- Optional: `pip install reportlab` to get a real PDF record instead of the HTML fallback.

## Run it (PowerShell)

```powershell
cd "C:\Users\Felix.Kaisha\Desktop\ClaudeMCP\Projects\Process Automation - Account Creation"

# Where applications are emailed (defaults to felixk@loki-ventures.com)
$env:ACCOUNTS_RECIPIENT = "accounts@loki-ventures.com"

python .\account_server.py
```

Then open **http://localhost:8000/account-capture.html**.

To change the port: `$env:ACCOUNT_PORT = "8080"` before running.

## Email setup (same pattern as InvoTrak / ReceivingPlaybook)

**Preferred — Microsoft Graph** (loki-ventures.com is Microsoft 365):
```powershell
$env:GRAPH_TENANT_ID     = "your-tenant-id"
$env:GRAPH_CLIENT_ID     = "your-app-client-id"
$env:GRAPH_CLIENT_SECRET = "your-app-secret"
$env:GRAPH_SENDER        = "authorized-sender@loki-ventures.com"
python .\account_server.py
```
The Entra app needs the Graph **Mail.Send** application permission with admin consent.

**SMTP fallback:**
```powershell
$env:SMTP_HOST = "smtp.example.com"; $env:SMTP_PORT = "587"
$env:SMTP_USERNAME = "sender@example.com"; $env:SMTP_PASSWORD = "app-password"
$env:SMTP_FROM = "sender@example.com"; $env:SMTP_USE_TLS = "true"
python .\account_server.py
```

If **no** email credentials are set, submissions are still **saved** to disk and the form shows
"saved — the team will be notified shortly" (the server reports `emailed: false`). Nothing is lost.

> Keep secrets in the PowerShell session / server environment only — never in the HTML file.

## Quick test without email
1. Start the server (no email vars needed).
2. Open the form, fill a customer, sign, submit.
3. Check `submissions/<reference>/` — you should see `record.json`, `signature.png`, and
   `signed-application.html`. Open the HTML to see the signed record + audit trail.

## Validation the server enforces (rejects with a clear message)
- KRA PIN present and correctly formatted (letter + 9 digits + letter).
- Customer legal name, contact name/phone/email, physical address/town/county.
- Requested credit limit (number, ≥ 0) and payment terms.
- Signatory name / ID / role, a drawn signature, and ticked consent.
- Submissions must carry the `X-Account-Submit: v1` header and be same-origin (basic anti-CSRF).

## Notes / limits (revisit in later phases)
- Storage is flat files (per the org pattern). Phase 5 moves this to SQLite/Postgres if volume grows.
- Reference lists (price lists, customer groups) are placeholders in the form; from Phase 3 they
  load live from the ERP adapter's `lookup_reference_data()`.
- To expose the form to salespeople in the field you'll need HTTPS + a reachable host/VPN — an
  open question in `06-open-questions.md` (#9).

## Next: Phase 2
Build the accounts **review & approval dashboard** that lists these PENDING submissions, lets the
team confirm credit terms / price list / customer group, and prepares the one-click approve that
Phase 3 wires to the ERP adapter.
