# Phase 3 — SAP Business One adapter (create the customer master)

This turns an **approved** application into a real Business Partner in SAP Business One via
the **Service Layer**, stores the returned `CardCode`, and flips the record to `created`.
Everything is stdlib-only and driven by `.env` — no new dependencies.

## New files
- `env_loader.py` — loads `.env` into the environment at startup.
- `erp_adapter.py` — the ERP-agnostic `ErpAdapter` interface + `get_adapter()` factory.
- `sapb1_adapter.py` — the SAP B1 Service Layer adapter (login, dedupe, create, reference dump).
- `sap_mapping.py` — maps a captured record → SAP `BusinessPartners` payload (the full field map is in its docstring and in `03-data-model-and-erp-mapping.md`).

## 1. Configure `.env` (SAP section)
Fill the `TODO` values:

```dotenv
ERP_BACKEND="sapb1"
SAP_SL_URL="https://<host>:50000/b1s/v1"   # your TEST server
SAP_COMPANY_DB="SBODEMOKE"                 # your TEST company DB
SAP_USERNAME="manager"
SAP_PASSWORD="********"
SAP_VERIFY_SSL="false"                     # sandboxes use a self-signed cert
SAP_CURRENCY="KES"
```

## 2. Point the value maps at your DB
SAP wants **numeric** codes for group / price list / payment terms. Dump yours:

```powershell
python -m sapb1_adapter --ping        # confirm login works
python -m sapb1_adapter --reference   # prints your BP Groups, Price Lists, Payment Terms + codes
```

Then fill the maps in `.env` (our value → the SAP code you saw), e.g.:

```dotenv
SAP_GROUP_MAP='{"Retail":"104","Wholesale":"105","Distributor":"106","Corporate":"107"}'
SAP_PRICELIST_MAP='{"Standard retail":"1","Wholesale":"2","Distributor":"3","Key account":"4"}'
SAP_TERMS_MAP='{"net_30":"1","net_45":"4","net_60":"5"}'
```
Any value left blank is simply omitted on create, and the reviewer sees a warning — SAP then
uses its own default for that field. Nothing is sent wrong.

**CardCode:** if you set `SAP_BP_SERIES` to a numbering-series number, SAP auto-assigns the code.
Otherwise we generate `<SAP_CARDCODE_PREFIX><KRA-PIN>` (e.g. `CP051234567X`). If the accounts
team typed an **Account number** at approval, that value is used as the CardCode.

## 3. End-to-end test (against the TEST DB)
1. `python account_server.py`
2. Open the form (`/account-capture.html`), submit a test application.
3. Open the dashboard (`/accounts-dashboard.html`), open the application, set the credit limit /
   group / terms in the **For internal use only** box, and **Approve**.
4. On the approved record, click **Preview SAP payload** — this calls the mapping (no write) and
   shows the exact `BusinessPartners` JSON + any mapping warnings. Sanity-check it.
5. Click **Create in SAP**. On success the record shows `✓ Created in sapb1 as <CardCode>`, the
   status becomes **Created**, and a `created` entry is hash-chained into the audit log.
6. Verify the Business Partner exists in your SAP test client.

Duplicate protection: before creating, the adapter looks up `FederalTaxID` (KRA PIN). If a BP
already exists it refuses with `409` and shows the existing CardCode — no duplicate is made.

## Command-line dry run (no SAP needed)
Preview the payload for any stored record without connecting:
```powershell
python -m sapb1_adapter --dry-run submissions/<id>/record.json
```

## Field mapping (summary)
`company_name→CardName`, `pin_number→FederalTaxID`, `vat_number→AdditionalID` (configurable via
`SAP_VAT_FIELD`), `approval.credit_limit→CreditLimit`, `customer_group→GroupCode`,
`price_list→PriceListNum`, `payment_terms→PayTermsGrpCode`, purchasing/accounts/director contacts
→ `ContactEmployees[]`, registered/delivery addresses → `BPAddresses[]` (BillTo/ShipTo), and a
human summary (category, product lines, portal ref) → `Notes`. Full table in `sap_mapping.py`.

## Troubleshooting
- **"SAP is not fully configured"** — a `SAP_*` value is blank in `.env`.
- **Cannot reach Service Layer** — check `SAP_SL_URL`, the `:50000` port, VPN, and that the
  Service Layer service is running. Self-signed cert → keep `SAP_VERIFY_SSL="false"`.
- **HTTP 400 from SAP on create** — usually a mandatory field or a bad code in a value map; the
  exact SAP message is passed straight through to the dashboard.

## Next: Phase 4 (ERPNext)
`get_adapter()` already routes on `ERP_BACKEND`. Implementing `ERPNextAdapter` with the same
three methods (`lookup_reference_data`, `find_customer_by_tax_id`, `create_customer`) and flipping
`ERP_BACKEND=erpnext` switches the backend — no form, mapping-shape, or dashboard change.
