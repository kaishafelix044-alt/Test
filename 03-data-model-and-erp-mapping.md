# 3. Data Model and ERP Field Mapping

This is the heart of the ERP-agnostic design: one canonical customer record, mapped to
each ERP's field names in exactly one place per ERP.

## 3.1 Canonical customer record (our schema, `version: "2"`)

This schema is a **faithful digital replica of the paper Account Opening Form**
(`docs/Acount Opening Form.pdf`). Section numbers below match the form. Two deliberate
differences from a generic B2B form:

1. **No customer-facing credit limit.** The form only asks the customer for payment terms
   (30/45/60 days). The credit limit lives in the form's "For Internal Use Only" box, so the
   **accounts team sets it at review** (see `approval` block). 
2. **No customer bank fields.** The form's "Banking Information" is *Loki's own* bank/M-PESA
   details, printed for the customer — shown read-only, never collected. See `reference_data.LOKI_BANKING`.

Every Director/Partner/Proprietor signs (`directors[].signature_base64`), the Delivery contact
signs if different, and there is a final binding Authorisation signature — mirroring the paper form.

```jsonc
{
  "version": "2",
  "meta": { "submission_id": "", "received_at": "iso", "capture_mode": "self_serve | assisted",
            "salesperson_name": "", "salesperson_id": "", "source_ip": "", "user_agent": "", "payload_hash": "sha256" },
  "company": {                              // Section 1 — Company Information
    "company_name": "string",
    "trading_name": "string|null",
    "registration_no": "string|null",       // BN / cert. of registration
    "type_of_business": "string",            // free text e.g. "Retailer, Wholesaler, Distributor"
    "business_category": ["online_platform","pet_shop", "..."],  // multi; see reference_data.BUSINESS_CATEGORY
    "business_category_other": "string|null",
    "pin_number": "string",                  // KRA PIN — required
    "vat_number": "string|null",
    "year_established": "string|null"
  },
  "directors": [                            // Section 2A — each signs
    { "name": "", "address": "", "mobile": "", "id_no": "", "signature_base64": "png|filename", "signed_at": "iso" }
  ],
  "delivery": {                             // Section 2B — only if different
    "different": true, "name": "", "address": "", "mobile": "", "id_no": "",
    "signature_base64": "png|filename", "signed_at": "iso"
  },
  "purchasing_contact": { "name": "", "position": "", "email": "", "phone": "" },   // Section 3
  "accounts_contact":   { "name": "", "position": "", "email": "", "phone": "" },   // Section 3 (invoicing/payments)
  "operations": {                           // Section 4 — Business Operations
    "nature_of_business": "string", "number_of_branches": "string|null",
    "avg_monthly_orders": "string|null",
    "product_lines": ["dog_food","cat_food", "..."], "product_lines_other": "string|null"
  },
  "trade_references": [                      // Section 5 — two suppliers
    { "supplier_name": "", "contact_person": "", "email": "", "phone": "" }
  ],
  "payment": {                              // Section 7 — Payment Terms & Conditions
    "preferred_methods": ["bank_transfer","cheque","mobile_money"],   // multi
    "payment_terms": "net_30 | net_45 | net_60",                      // 30/45/60 Days
    "order_by": ["lpo","email","whatsapp"]                            // multi
  },
  "policy_ack": true,                       // Section 8 — Return & Expiry Goods Policy acknowledged
  "attachments": [ { "kind": "id | kra_pin | business_reg | other", "filename": "", "stored": "" } ],
  "authorization": {                        // Signatures and Authorization
    "name": "", "position": "", "date": "YYYY-MM-DD",
    "signature_base64": "png|filename", "signed_at": "iso", "consent_data_processing": true
  },
  "approval": {                             // "For Internal Use Only" — set by accounts at review
    "status": "pending | approved | rejected | created",
    "reviewed_by": "string|null", "reviewed_at": "iso|null",
    "credit_limit": 0,                      // accounts assign this (form has no customer field)
    "payment_terms": "string", "price_list": "string", "customer_group": "string",
    "account_manager": "string|null", "account_number": "string|null", "approved_by": "string|null",
    "erp_backend": "sapb1 | erpnext | null", "erp_customer_code": "string|null", "notes": "string|null"
  }
}
```

> On disk, `signature_base64` and each attachment's `data` are replaced by the stored **filename**
> (`director-00-signature.png`, `authorization-signature.png`, etc.); the raw base64 is never kept in `record.json`.

## 3.2 Mapping to **SAP Business One v10** (Service Layer)

Endpoint base: `https://<host>:50000/b1s/v1/` · Login: `POST /Login` `{CompanyDB, UserName, Password}`
→ session cookie. Create: `POST /BusinessPartners`.

| Canonical field | SAP B1 `BusinessPartners` field | Notes |
|---|---|---|
| (fixed) | `CardType` = `cCustomer` | fixed for customers |
| (generated code) | `CardCode` | your code series, or let series assign |
| company.company_name | `CardName` | |
| company.trading_name | `CardForeignName` / U_field | optional |
| company.pin_number | `FederalTaxID` | KRA PIN |
| company.vat_number | `VatIDNum` | |
| **approval.customer_group** | `GroupCode` | BP group (numeric code); set by accounts |
| **approval.price_list** | `PriceListNum` | maps to `PriceLists` entity; set by accounts |
| **approval.payment_terms** | `PayTermsGrpCode` | `PaymentTermsTypes` entity; net_30/45/60 |
| **approval.credit_limit** | `CreditLimit` | set by accounts at review |
| purchasing_contact / accounts_contact | `ContactEmployees` collection | two child contacts |
| *.phone / email | `Phone1`, `EmailAddress` | from purchasing contact |
| directors[] | `ContactEmployees` + U_fields | names, IDs; each signed |
| directors[].address / delivery | `BPAddresses` collection | `AddressType` bo_BillTo / bo_ShipTo |

Reference data for dropdowns: `GET /BusinessPartnerGroups`, `GET /PriceLists`,
`GET /PaymentTermsTypes`.

## 3.3 Mapping to **ERPNext** (REST API)

Base: `https://<site>/api/resource/` · Auth header: `Authorization: token <key>:<secret>`.
Create: `POST /api/resource/Customer`.

| Canonical field | ERPNext `Customer` field | Notes |
|---|---|---|
| company.company_name | `customer_name` | |
| (fixed) | `customer_type` = `Company` | |
| **approval.customer_group** | `customer_group` | link to Customer Group doctype; set by accounts |
| **approval.price_list** | `default_price_list` | link to Price List; set by accounts |
| **approval.payment_terms** | `payment_terms` | Payment Terms Template; net_30/45/60 |
| **approval.credit_limit** | `credit_limits` child: `[{company, credit_limit}]` | per company; set by accounts |
| company.pin_number | `tax_id` | KRA PIN |
| directors[].address / delivery | separate `Address` doctype | linked via Dynamic Link |
| purchasing_contact / accounts_contact | separate `Contact` doctype(s) | linked via Dynamic Link |
| company.type_of_business / category | `industry` / custom field | |
| (territory) | `territory` | default e.g. "Kenya" |

Reference data for dropdowns: `GET /api/resource/Customer Group`,
`GET /api/resource/Price List`, `GET /api/resource/Payment Terms Template`.

## 3.4 The mapping insight

- **Credit terms** = `PayTermsGrpCode` + `CreditLimit` (SAP) ≡ `payment_terms` + `credit_limits` (ERPNext).
- **Price list** = `PriceListNum` (SAP) ≡ `default_price_list` (ERPNext).
- **Customer group** = `GroupCode` (SAP) ≡ `customer_group` (ERPNext).

Each adapter owns a small dictionary translating our canonical values (e.g. `net_30`) to
the ERP's own IDs/names. Keep those tables in the adapter so a term rename in the ERP is a
one-line change.
