"""Map a captured Account Opening application to a SAP Business One
`BusinessPartners` payload (Service Layer / DI API schema, v10).

This is the single place that knows how our canonical record (schema v2, see
03-data-model-and-erp-mapping.md) becomes a SAP Business Partner. Field names below
are the verified Service Layer property names.

FULL FIELD MAP (canonical -> SAP BusinessPartners)
──────────────────────────────────────────────────────────────────────────────
 company.company_name .................. CardName
 (fixed)  ............................... CardType = "cCustomer"
 (generated / series) .................. CardCode           see _card_code()
 company.trading_name .................. FreeText (also kept in Notes)
 company.pin_number (KRA) .............. FederalTaxID
 company.vat_number .................... <SAP_VAT_FIELD>    (default AdditionalID)
 company.registration_no ............... Notes / U_RegNo
 approval.customer_group ............... GroupCode          via SAP_GROUP_MAP
 approval.price_list ................... PriceListNum       via SAP_PRICELIST_MAP
 approval.payment_terms ................ PayTermsGrpCode    via SAP_TERMS_MAP
 approval.credit_limit ................. CreditLimit
 approval.account_number ............... CardCode (if provided, overrides generated)
 (env) SAP_CURRENCY .................... Currency
 purchasing_contact.phone .............. Phone1
 purchasing_contact.* .................. ContactEmployees[] (Position "Purchasing")
 accounts_contact.email ................ EmailAddress   + ContactEmployees[] ("Accounts")
 accounts_contact.phone ................ Phone2
 directors[] ........................... ContactEmployees[] (Position from role/"Director")
 directors[0].address / delivery ....... BPAddresses[] (bo_BillTo / bo_ShipTo)
 delivery (if different) ............... BPAddresses[] bo_ShipTo (+ own contact)
 operations / category / product lines . Notes (human summary, for the accounts team)
 meta.submission_id .................... Notes (traceability back to the portal record)
──────────────────────────────────────────────────────────────────────────────
Values left unmapped (empty in SAP_*_MAP) are omitted so SAP applies its own default.
"""

from __future__ import annotations

import json
import os

from reference_data import (
    BUSINESS_CATEGORY_LABEL,
    ORDER_BY_LABEL,
    PAYMENT_METHODS_LABEL,
    PAYMENT_TERMS_LABEL,
    PRODUCT_LINES_LABEL,
    labels,
)


def _env_map(name: str) -> dict:
    """Parse a JSON object env var into {our_value: sap_code}; skip blank codes."""
    raw = os.getenv(name, "") or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out = {}
    for k, v in (data or {}).items():
        if v is None or str(v).strip() == "":
            continue
        out[k] = v
    return out


def _int_or_none(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _card_code(record: dict) -> str | None:
    """Return the CardCode to send, or None to let a numbering series assign it."""
    appr = record.get("approval") or {}
    # If an account number was set at review, honour it as the CardCode.
    if str(appr.get("account_number") or "").strip():
        return str(appr["account_number"]).strip()
    # If a numbering series is configured, let SAP assign — return None.
    if str(os.getenv("SAP_BP_SERIES") or "").strip():
        return None
    prefix = os.getenv("SAP_CARDCODE_PREFIX", "C")
    pin = (record.get("company") or {}).get("pin_number") or ""
    base = "".join(ch for ch in pin if ch.isalnum()).upper()
    return (prefix + base)[:15] if base else None


def _contact(name, position, phone="", mobile="", email=""):
    c = {"Name": (name or "")[:90], "Position": (position or "")[:90], "Active": "tYES"}
    if phone:
        c["Phone1"] = str(phone)[:50]
    if mobile:
        c["MobilePhone"] = str(mobile)[:50]
    if email:
        c["E_Mail"] = str(email)[:100]
    return c


def _contacts(record: dict) -> list[dict]:
    out = []
    for i, d in enumerate(record.get("directors") or []):
        if not (d or {}).get("name"):
            continue
        out.append(_contact(d.get("name"), "Director / Partner", mobile=d.get("mobile"),
                            email="", phone=""))
    pc = record.get("purchasing_contact") or {}
    if pc.get("name"):
        out.append(_contact(pc.get("name"), pc.get("position") or "Purchasing",
                            phone=pc.get("phone"), email=pc.get("email")))
    ac = record.get("accounts_contact") or {}
    if ac.get("name"):
        out.append(_contact(ac.get("name"), ac.get("position") or "Accounts",
                            phone=ac.get("phone"), email=ac.get("email")))
    # SAP requires unique contact Names within a BP; de-duplicate by name.
    seen, uniq = set(), []
    for c in out:
        key = c["Name"].lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def _addresses(record: dict) -> list[dict]:
    directors = record.get("directors") or []
    bill_street = (directors[0].get("address") if directors else "") or ""
    addrs = [{
        "AddressName": "Bill To",
        "AddressType": "bo_BillTo",
        "Street": bill_street[:100],
        "Country": "KE",
    }]
    delivery = record.get("delivery") or {}
    ship_street = (delivery.get("address") if delivery.get("different") else bill_street) or ""
    addrs.append({
        "AddressName": "Ship To",
        "AddressType": "bo_ShipTo",
        "Street": ship_street[:100],
        "Country": "KE",
    })
    return addrs


def _notes(record: dict) -> str:
    co = record.get("company") or {}
    op = record.get("operations") or {}
    pay = record.get("payment") or {}
    meta = record.get("meta") or {}
    parts = [
        f"Portal ref: {meta.get('submission_id','')}",
        f"Type: {co.get('type_of_business','')}",
        f"Category: {labels(co.get('business_category'), BUSINESS_CATEGORY_LABEL)}",
        f"Reg no: {co.get('registration_no','')}",
        f"Product lines: {labels(op.get('product_lines'), PRODUCT_LINES_LABEL)}",
        f"Pay method: {labels(pay.get('preferred_methods'), PAYMENT_METHODS_LABEL)}",
        f"Order by: {labels(pay.get('order_by'), ORDER_BY_LABEL)}",
    ]
    return " | ".join(p for p in parts if p.split(": ", 1)[-1])[:254]


def build_business_partner(record: dict) -> dict:
    """Build the SAP Business One BusinessPartners create payload from a record."""
    co = record.get("company") or {}
    appr = record.get("approval") or {}
    pc = record.get("purchasing_contact") or {}
    ac = record.get("accounts_contact") or {}

    group_map = _env_map("SAP_GROUP_MAP")
    price_map = _env_map("SAP_PRICELIST_MAP")
    terms_map = _env_map("SAP_TERMS_MAP")

    bp: dict = {
        "CardType": "cCustomer",
        "CardName": (co.get("company_name") or "")[:100],
        "FederalTaxID": (co.get("pin_number") or "")[:32],
        "Currency": os.getenv("SAP_CURRENCY", "KES"),
        "Notes": _notes(record),
    }

    card_code = _card_code(record)
    if card_code:
        bp["CardCode"] = card_code
    series = _int_or_none(os.getenv("SAP_BP_SERIES"))
    if series is not None and not card_code:
        bp["Series"] = series

    if co.get("trading_name"):
        bp["FreeText"] = co["trading_name"][:100]

    vat_field = os.getenv("SAP_VAT_FIELD", "AdditionalID")
    if co.get("vat_number") and vat_field:
        bp[vat_field] = str(co["vat_number"])[:32]

    # Accounts-set commercial terms
    if appr.get("credit_limit") is not None:
        try:
            bp["CreditLimit"] = float(appr["credit_limit"])
        except (TypeError, ValueError):
            pass
    grp = _int_or_none(group_map.get(appr.get("customer_group")))
    if grp is not None:
        bp["GroupCode"] = grp
    pl = _int_or_none(price_map.get(appr.get("price_list")))
    if pl is not None:
        bp["PriceListNum"] = pl
    terms = _int_or_none(terms_map.get(appr.get("payment_terms")))
    if terms is not None:
        bp["PayTermsGrpCode"] = terms

    # Header contact channels
    if pc.get("phone"):
        bp["Phone1"] = str(pc["phone"])[:20]
    if ac.get("phone"):
        bp["Phone2"] = str(ac["phone"])[:20]
    invoice_email = ac.get("email") or pc.get("email")
    if invoice_email:
        bp["EmailAddress"] = str(invoice_email)[:100]

    contacts = _contacts(record)
    if contacts:
        bp["ContactEmployees"] = contacts
        bp["ContactPerson"] = contacts[0]["Name"]
    bp["BPAddresses"] = _addresses(record)

    return bp


def mapping_warnings(record: dict) -> list[str]:
    """Non-fatal issues a reviewer should know before creating in SAP."""
    warns = []
    appr = record.get("approval") or {}
    if not _env_map("SAP_GROUP_MAP").get(appr.get("customer_group")):
        warns.append(f"Customer group '{appr.get('customer_group')}' is not mapped to a SAP "
                     f"GroupCode (SAP_GROUP_MAP) — SAP will use its default group.")
    if not _env_map("SAP_TERMS_MAP").get(appr.get("payment_terms")):
        warns.append(f"Payment terms '{appr.get('payment_terms')}' is not mapped to a SAP "
                     f"PayTermsGrpCode (SAP_TERMS_MAP) — SAP will use its default terms.")
    if not _env_map("SAP_PRICELIST_MAP").get(appr.get("price_list")):
        warns.append(f"Price list '{appr.get('price_list')}' is not mapped to a SAP "
                     f"PriceListNum (SAP_PRICELIST_MAP) — SAP will use its default price list.")
    return warns
