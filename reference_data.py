"""Reference data shared by the capture form, server and review dashboard.

This mirrors the Loki Ventures **Account Opening Form** (docs/Acount Opening Form.pdf):
the fixed pick-lists on the form (business category, product lines, payment method
and terms, how goods are ordered), plus the ERP-facing lists the accounts team sets
at review time (price list, customer group) and Loki's own banking details, which the
form prints for the customer.

PHASE 2 NOTE: `price_lists` and `customer_groups` are placeholders. In Phase 3 the ERP
adapter's `lookup_reference_data()` (SAP B1 Service Layer / ERPNext REST) replaces
`get_reference_data()` so the dashboard dropdowns reflect the live ERP. Keep the returned
shape identical when you swap the source.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Pick-lists straight off the paper form. Each entry is [canonical_code, label].
# The label text matches the form wording so the digital form reads identically.
# --------------------------------------------------------------------------- #

# 1. Company Information -> Business Category (tick all that apply)
BUSINESS_CATEGORY: list[list[str]] = [
    ["supermarket", "Supermarket"],
    ["hypermarket", "Hypermarkets"],
    ["pet_boarding", "Pet boarding"],
    ["breeder", "Breeder"],
    ["online_platform", "Online Platform"],
    ["agrovet", "Agrovet"],
    ["pet_shop", "Pet Shop"],
    ["vet", "Vet"],
    ["security_firm", "Security firm"],
    ["b2b", "B2B"],
    ["shelter", "Shelter"],
    ["other", "Other"],
]

# 4. Business Operations -> Product Lines of Interest (tick all that apply)
PRODUCT_LINES: list[list[str]] = [
    ["dog_food", "Dog Food"],
    ["cat_food", "Cat Food"],
    ["pet_grooming", "Pet Grooming Products"],
    ["pet_accessories", "Pet Accessories"],
    ["other", "Other"],
]

# 7. Payment Terms & Conditions -> Preferred Payment Method (tick)
PAYMENT_METHODS: list[list[str]] = [
    ["bank_transfer", "Bank Transfer"],
    ["cheque", "Cheque"],
    ["mobile_money", "Mobile Money"],
]

# 7. Payment Terms & Conditions -> Payment Terms (tick). The form offers only these.
PAYMENT_TERMS: list[list[str]] = [
    ["net_30", "30 Days"],
    ["net_45", "45 Days"],
    ["net_60", "60 Days"],
]

# 7. Payment Terms & Conditions -> Goods To Be Ordered By (tick)
ORDER_BY: list[list[str]] = [
    ["lpo", "LPO"],
    ["email", "Email"],
    ["whatsapp", "WhatsApp / Message"],
]

# --------------------------------------------------------------------------- #
# ERP-facing lists the accounts team assigns at review (the "For Internal Use
# Only" box on the form). Placeholders until the Phase 3 adapter supplies them.
# --------------------------------------------------------------------------- #
PRICE_LISTS: list[str] = ["Standard retail", "Wholesale", "Distributor", "Key account"]

CUSTOMER_GROUPS: list[str] = ["Retail", "Wholesale", "Distributor", "Corporate"]

# --------------------------------------------------------------------------- #
# Loki's own banking details — the form PRINTS these for the customer (how to pay
# Loki); they are not collected from the applicant. Shown read-only on the form.
# --------------------------------------------------------------------------- #
LOKI_BANKING = {
    "bank_name": "I&M Bank Ltd",
    "branch": "Lavington Mall",
    "account_name": "Loki Ventures Ltd",
    "account_number": "2701566371210",
    "mpesa_till": "940233",  # Buy Goods Till Number
}

# Company header printed on every page of the paper form.
LOKI_COMPANY = {
    "name": "LOKI VENTURES LIMITED",
    "address": "P.O. Box 48960-00100, Mashiara Park, Kaptagat Road, Nairobi, Kenya",
    "phone": "+254 (0) 708739393 / 795350292",
    "email": "accounts@loki-ventures.com",
}

# 8. Return & Expiry Goods Policy — the acknowledged terms (verbatim from the form).
RETURN_POLICY: list[str] = [
    "Short Expiry Goods: Goods with less than 3 months remaining until expiry are "
    "non-returnable. We will not be liable for goods returned with less than 3 months "
    "to their expiration date.",
    "Damaged or Expired Goods: We are not liable for damaged or expired goods once "
    "delivered, unless noted and reported at the time of delivery.",
]

# --------------------------------------------------------------------------- #
# Code -> label lookups (used by the server, rules engine and email summary).
# --------------------------------------------------------------------------- #
BUSINESS_CATEGORY_LABEL = {code: label for code, label in BUSINESS_CATEGORY}
PRODUCT_LINES_LABEL = {code: label for code, label in PRODUCT_LINES}
PAYMENT_METHODS_LABEL = {code: label for code, label in PAYMENT_METHODS}
PAYMENT_TERMS_LABEL = {code: label for code, label in PAYMENT_TERMS}
ORDER_BY_LABEL = {code: label for code, label in ORDER_BY}


def labels(codes, mapping) -> str:
    """Join selected codes into a human string using the given label map."""
    return ", ".join(mapping.get(c, c) for c in (codes or []) if c)


def get_reference_data() -> dict:
    """Return the reference lists the capture form and dashboard need.

    Later: fold in adapter.lookup_reference_data() for price_lists / customer_groups.
    """
    return {
        "business_category": [list(p) for p in BUSINESS_CATEGORY],
        "product_lines": [list(p) for p in PRODUCT_LINES],
        "payment_methods": [list(p) for p in PAYMENT_METHODS],
        "payment_terms": [list(p) for p in PAYMENT_TERMS],
        "order_by": [list(p) for p in ORDER_BY],
        "price_lists": list(PRICE_LISTS),
        "customer_groups": list(CUSTOMER_GROUPS),
        "loki_banking": dict(LOKI_BANKING),
        "loki_company": dict(LOKI_COMPANY),
        "return_policy": list(RETURN_POLICY),
        "source": "placeholder",  # becomes "sapb1" / "erpnext" once the adapter is wired
    }
