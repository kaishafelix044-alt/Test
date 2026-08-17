# 5. Build Roadmap (Phased)

Sequenced so you get a working, useful tool early, and the risky ERP write is proven in a
sandbox before it ever touches live data. Timing matters: **ERPNext go-live is ~1 month
out**, so we build ERP-agnostic from day one and prove the ERPNext adapter during the
transition.

## Revised infrastructure direction (decided 2026-08-11)

The capture form and storage move to managed cloud so the form is **always live**:

- **Hosting:** publish the form on **Vercel** (public capture endpoint), instead of the
  internal-machine assumption below. The review dashboard stays access-controlled.
- **Datastore:** a **Neon Postgres** database becomes the system of record, replacing the
  file-based `submissions/` folder. Schema maps **one-to-one** to the canonical record in
  `03-data-model-and-erp-mapping.md`.
- **ERP sync:** Neon holds a one-to-one mapping/sync with **SAP B1**; the Phase 3 adapter
  reads/writes against Postgres and reconciles the customer master with B1 (a sync worker,
  not the serverless request path). The adapter interface is unchanged — only its storage
  backend and where it runs.

Impact on the phases below: Phase 1/2 code (validation, rules engine, dashboard) is reused;
the storage layer swaps from JSON files to Postgres, and email/PDF generation moves behind a
serverless function or the sync worker. Signature audit and the hash-chained decision log
carry over into DB columns/rows.

## Phase 0 — Foundations & decisions (½ week)
**Goal:** unblock the build.
- Confirm open questions in `06-open-questions.md` (ERP creds, code series, default rules).
- Get a **SAP B1 Service Layer** test/sandbox login and an **ERPNext** test site + API token.
- Lock the exact field list on the form with the accounts/sales owners.
- Decide hosting for the server (an internal machine, same as questionnaire_server.py).

**Deliverable:** signed-off field list + working sandbox credentials for both ERPs.

## Phase 1 — Capture + signature (1 week)
**Goal:** replace the paper form.
- Single-file HTML form: self-serve and assisted modes, mobile-friendly, full validation.
- Signature canvas + audit metadata capture + consent.
- Attachment upload (ID, KRA PIN, business reg).
- Python server: receive → validate against canonical schema → save JSON + files → email
  accounts via MS Graph → generate signed PDF. (Fork `questionnaire_server.py`.)

**Deliverable:** a real customer can complete and sign; accounts receives a clean PDF + record.
*This alone removes paper and re-keying delay, even before ERP integration.*

## Phase 2 — Review & approval dashboard (1 week)
**Goal:** structured, auditable approval.
- Accounts dashboard: list Pending / Approved / Rejected / Created.
- Detail view: all fields, attachments, signature, audit block.
- Rules engine pre-fills proposed **credit terms / price list / customer group**; reviewer
  can adjust. Dropdown values come live from the ERP adapter's `lookup_reference_data()`.
- Approve / reject with reason; immutable audit log of the decision.

**Deliverable:** end-to-end up to (but not including) ERP write; account "ready to create".

## Phase 3 — ERP adapter: SAP B1 first (1 week)
**Goal:** one-click creation in the live ERP.
- Implement `ErpAdapter` interface + `SAPB1Adapter` (Service Layer: login, create
  BusinessPartner with group/price list/terms/credit limit, read reference data).
- Test thoroughly in **sandbox**; then enable one-click "Approve → Create" to live SAP B1.
- Store returned `CardCode` on the record; state → Created.

**Deliverable:** true end-to-end onboarding on SAP B1.

## Phase 4 — ERPNext adapter + migration readiness (1 week, overlaps the ERP cutover)
**Goal:** be ready the day ERPNext goes live.
- Implement `ERPNextAdapter` (REST: create Customer + Address + Contact + credit_limits).
- Validate against the ERPNext test site using the **same submissions** used for SAP B1.
- Optional **shadow/dual-write** during transition to build confidence.
- Cutover = flip `ERP_BACKEND=erpnext`. No UI or data-model change.

**Deliverable:** seamless switch; nothing above the adapter changes.

## Phase 5 — Hardening & handover (ongoing)
- Move storage JSON → SQLite/Postgres if volume grows.
- Reporting: turnaround time, approval rates, credit granted.
- User manuals (role-by-role, InvoTrak style): salesperson, customer, accounts reviewer, admin.
- Backups, monitoring, secret rotation.

## At-a-glance

| Phase | Outcome | Depends on |
|-------|---------|-----------|
| 0 | Decisions + sandbox access | Stakeholders, IT |
| 1 | Paperless capture + signed PDF | Phase 0 |
| 2 | Review/approval dashboard | Phase 1 |
| 3 | Live creation in SAP B1 | Phase 2 + SAP sandbox |
| 4 | ERPNext ready; one-flag cutover | Phase 3 + ERPNext site |
| 5 | Hardening, reports, manuals | Phases 1–4 |

**Critical path for "end to end on the current ERP": Phases 0 → 1 → 2 → 3 (~3.5 weeks).**
ERPNext readiness (Phase 4) runs alongside your migration month.
