# Phase 2 — Accounts Review & Approval Dashboard

The accounts team can now review each pending application, see rules-engine proposals and risk
flags, confirm the final credit terms / price list / customer group, and **approve or reject** —
with an append-only, tamper-evident audit trail. This is everything up to (but not including) the
ERP write, which is Phase 3.

## New files
- `accounts-dashboard.html` — the reviewer UI (list + detail + decision panel).
- `rules_engine.py` — proposes credit limit / terms / price list / group and raises advisory flags.
- `reference_data.py` — the valid dropdown values (placeholder now; Phase 3 adapter replaces it).
- `account_server.py` — extended with the review API (list, detail, files, approve/reject, audit).

## Run it (PowerShell)

```powershell
cd "C:\Users\Felix.Kaisha\Desktop\ClaudeMCP\Projects\Process Automation - Account Creation"

# Protect the dashboard with a shared token (STRONGLY recommended — it exposes customer PII)
$env:REVIEW_TOKEN = "choose-a-long-random-token"

python .\account_server.py
```

- Application form:  http://localhost:8000/account-capture.html
- Review dashboard:  http://localhost:8000/accounts-dashboard.html

On first load the dashboard asks for the review token (stored only in the browser session).
If `REVIEW_TOKEN` is **not** set, the review APIs are open — fine for a local test, not for anything
reachable by others. The startup log prints which mode you're in.

## What the reviewer sees
- **Tabs:** Pending / Approved / Rejected / Created / All, with a live search box.
- **Detail:** every field, the signature image, downloadable documents, and the full audit trail.
- **Review flags** (from the rules engine), e.g.:
  - credit above the senior-approval threshold (default KES 500,000),
  - an individual requesting large credit,
  - long terms (Net 45/60) with no trade references,
  - missing KYC documents.
- **Decision panel:** final credit limit / payment terms / price list / customer group are
  pre-filled with the proposal; the reviewer adjusts, adds notes, and clicks **Approve** or
  **Reject** (a reason is required to reject).

## What happens on a decision
- The submission's `record.json` `approval` block is updated (status, reviewer, timestamp, final terms).
- An entry is appended to `submissions/<id>/audit-log.jsonl` — **hash-chained** (each entry hashes
  the previous one, seeded from the original submission's payload hash), so any later tampering is
  detectable. Approved applications become **`approved` = ready to create in the ERP** (Phase 3).
- A decision can only be made once (a second attempt returns HTTP 409).

## Tuning the rules
Edit the thresholds at the top of `rules_engine.py` (`SENIOR_APPROVAL_LIMIT`,
`INDIVIDUAL_CREDIT_LIMIT`, `LONG_TERMS`, `PRICE_LIST_BY_GROUP`) with the finance owner — this is
open question #1 in `06-open-questions.md`.

## Verified in testing
Auth gate (401 without/with wrong token), list + status filtering, detail with proposal + flags,
document serving with path-traversal blocked, approve with adjusted terms, reject-requires-reason,
double-decision blocked (409), invalid-terms rejected (400), and audit-chain integrity.

## Security notes (revisit in Phase 5 hardening)
- The token is a single shared secret, not per-user accounts. For production, put the dashboard
  behind real authentication (SSO / per-reviewer logins) and HTTPS.
- Submissions contain PII and ID documents — keep the `submissions/` folder access-controlled and
  backed up; confirm Data Protection Act handling (see `04-signature-audit-compliance.md`).

## Next: Phase 3
Implement the `ErpAdapter` interface and the **SAP B1 (Service Layer)** adapter, then wire an
"Approve → Create in ERP" action that turns an `approved` record into a real Business Partner and
records the returned customer code (status → `created`).
