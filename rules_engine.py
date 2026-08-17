"""Rules engine: propose price list, customer group and payment terms for a
submitted application, and raise advisory flags for the reviewer.

The paper form does NOT ask the customer for a credit limit — that sits in the
form's "For Internal Use Only" box, so the accounts team SETS it at review time
(Phase 2). This engine therefore proposes the ERP-facing group/price-list/terms
and surfaces risk & KYC flags; it never decides on its own. Tune the thresholds
below with the finance owner (open question #1 in 06-open-questions.md).
"""

from __future__ import annotations

from reference_data import PAYMENT_TERMS_LABEL

# ---- tunable settings ------------------------------------------------------ #
LONG_TERMS = {"net_45", "net_60"}          # terms that really want trade references
DEFAULT_PAYMENT_TERMS = "net_30"           # if the applicant left it blank

# Default price list per customer group
PRICE_LIST_BY_GROUP = {
    "Retail": "Standard retail",
    "Wholesale": "Wholesale",
    "Distributor": "Distributor",
    "Corporate": "Key account",
}

# Map the form's free-text "Type of Business" / category to a customer group.
GROUP_BY_CATEGORY = {
    "supermarket": "Corporate",
    "hypermarket": "Corporate",
    "online_platform": "Retail",
    "agrovet": "Retail",
    "pet_shop": "Retail",
    "vet": "Retail",
    "breeder": "Retail",
    "pet_boarding": "Retail",
    "security_firm": "Corporate",
    "b2b": "Wholesale",
    "shelter": "Retail",
}


def _group_from_type(type_of_business: str, categories: list[str]) -> str:
    """Best-guess customer group from the 'Type of Business' text, then category."""
    t = (type_of_business or "").lower()
    if "distribut" in t:
        return "Distributor"
    if "wholesal" in t:
        return "Wholesale"
    if "retail" in t:
        return "Retail"
    for cat in categories or []:
        if cat in GROUP_BY_CATEGORY:
            return GROUP_BY_CATEGORY[cat]
    return "Retail"


def propose(record: dict) -> dict:
    """Return {"proposal": {...}, "flags": [{"level","message"}, ...]}."""
    company = record.get("company") or {}
    operations = record.get("operations") or {}
    payment = record.get("payment") or {}
    directors = [d for d in (record.get("directors") or []) if (d or {}).get("name")]
    refs = [r for r in (record.get("trade_references") or []) if (r or {}).get("supplier_name")]
    att_kinds = {(a or {}).get("kind") for a in (record.get("attachments") or [])}

    categories = company.get("business_category") or []
    req_terms = payment.get("payment_terms") or ""
    terms = req_terms if req_terms in PAYMENT_TERMS_LABEL else DEFAULT_PAYMENT_TERMS

    group = _group_from_type(company.get("type_of_business", ""), categories)
    price_list = PRICE_LIST_BY_GROUP.get(group, "Standard retail")

    proposal = {
        "credit_limit": 0,             # accounts set the real figure at review
        "payment_terms": terms,
        "price_list": price_list,
        "customer_group": group,
    }

    flags: list[dict] = []

    def flag(level, message):
        flags.append({"level": level, "message": message})

    # --- Credit / terms risk (advisory) ---
    if req_terms in LONG_TERMS and len(refs) < 2:
        flag("warn", f"{PAYMENT_TERMS_LABEL.get(req_terms, req_terms)} requested with "
                     f"{'no' if not refs else 'only one'} trade reference "
                     f"(the form asks for two).")
    if not refs:
        flag("warn", "No trade references were provided.")

    # --- Completeness / KYC (advisory in Phase 2) ---
    if not directors:
        flag("warn", "No director / partner / proprietor was listed.")
    if not company.get("pin_number"):
        flag("warn", "No KRA PIN captured.")
    if not att_kinds:
        flag("warn", "No supporting documents were attached.")
    else:
        if "kra_pin" not in att_kinds:
            flag("info", "No KRA PIN certificate attached.")
        if "business_reg" not in att_kinds:
            flag("info", "No business registration certificate attached.")
        if "id" not in att_kinds:
            flag("info", "No ID / passport copy of a signatory attached.")

    if not operations.get("product_lines"):
        flag("info", "No product lines of interest were selected.")

    return {"proposal": proposal, "flags": flags}
