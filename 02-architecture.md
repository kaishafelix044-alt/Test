# 2. Solution Architecture

## 2.1 Guiding principle: the ERP is a plug-in, not the core

Everything the customer, salesperson, and accounts team touch is built against **our own
canonical customer model**. The ERP sits behind a single interface. Migrating from SAP B1
to ERPNext means writing/enabling one adapter and flipping a config flag — no change to
the form, the signature, the dashboard, or the stored data.

```
┌──────────────────────────────────────────────────────────────────────┐
│ CAPTURE LAYER   (browser, single-file HTML — one per audience)         │
│   • Customer/self-serve form      • Salesperson-assisted form          │
│   • Signature canvas + audit capture                                   │
└───────────────┬──────────────────────────────────────────────────────┘
                │ HTTPS POST (JSON + base64 signature + attachments)
┌───────────────▼──────────────────────────────────────────────────────┐
│ APPLICATION LAYER   (Python server — extends questionnaire_server.py)  │
│   • Validate against canonical schema   • Store submission + files      │
│   • Generate signed PDF                 • Email accounts (MS Graph)     │
│   • Rules engine: propose credit/price-list/group defaults             │
│   • Review dashboard API + one-click approve                           │
└───────────────┬──────────────────────────────────────────────────────┘
                │ create_customer(canonical_record)
┌───────────────▼──────────────────────────────────────────────────────┐
│ ERP ADAPTER  (interface: one method, two implementations)             │
│   ┌────────────────────────┐        ┌────────────────────────────┐    │
│   │ SAPB1Adapter           │        │ ERPNextAdapter             │    │
│   │ Service Layer (OData)  │        │ REST API (/api/resource)   │    │
│   └────────────────────────┘        └────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────┘
```

## 2.2 The adapter interface

A single contract every ERP backend implements:

```python
class ErpAdapter(Protocol):
    def health_check(self) -> bool: ...
    def create_customer(self, c: CanonicalCustomer) -> ErpResult:
        """Create BP/Customer with credit terms, price list, group.
        Returns the ERP-assigned customer code, or a structured error."""
    def lookup_reference_data(self) -> ReferenceData:
        """Fetch valid price lists, customer groups, payment terms so the
        dashboard dropdowns always reflect the live ERP."""
```

- `ERP_BACKEND = "sapb1" | "erpnext"` in config/`.env` selects the implementation.
- During the transition month we can run **dual-write** (create in both) or **shadow mode**
  (create in SAP B1, validate the same payload against ERPNext without committing) to prove
  the ERPNext path before cutover.

## 2.3 Why not build straight against each ERP?

Because the migration would then touch every layer. The canonical model + adapter means:
- The dashboard's dropdowns (price lists, groups, terms) come from `lookup_reference_data()`,
  so they're always correct for whichever ERP is live.
- Field mapping lives in exactly one file per ERP (see `03-data-model-and-erp-mapping.md`).
- We can unit-test each adapter against a sandbox without touching the UI.

## 2.4 Technology choices (reuse what already works here)

| Concern | Choice | Why |
|---------|--------|-----|
| Capture UI | Single-file HTML + vanilla JS | Matches InvoTrak/ReceivingPlaybook; no build step; easy to host |
| Signature | HTML `<canvas>` → base64 PNG | No third-party dependency; audit metadata added server-side |
| Server | Python `http.server` (extend `questionnaire_server.py`) | Already proven pattern in this org |
| Email | Microsoft Graph `Mail.Send` (SMTP fallback) | Same as existing projects; loki-ventures.com is MS365 |
| Storage | JSON records + files on disk (Phase 1) → SQLite/Postgres (Phase 2) | Start simple, matches `submissions/` pattern |
| PDF | `reportlab` or HTML→PDF (`weasyprint`) | Embeds signature + audit block |
| SAP B1 | **Service Layer** (REST/OData v4, port 50000) | Native to B1 v10; cleaner than DI API |
| ERPNext | **REST API** with token auth | Native, well-documented |

## 2.5 Security posture

- Secrets (ERP creds, Graph secret, SMTP) only in server env/`.env`, never in HTML.
- ERP service account with least privilege (create Business Partner / Customer only).
- All traffic over HTTPS; attachments virus-scanned or type/size-limited.
- Signature and audit block are hashed; the stored record keeps a tamper-evident digest.
- Data Protection Act (Kenya) consent captured on the form; see `04`.
