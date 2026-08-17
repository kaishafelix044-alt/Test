"""ERP-agnostic adapter seam.

`ErpAdapter` is the one interface the rest of the app talks to. The concrete
adapter is chosen by the `ERP_BACKEND` env var (sapb1 | erpnext | "").
Nothing above this line changes when SAP B1 is swapped for ERPNext later.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class ErpError(RuntimeError):
    """A problem talking to the ERP (connection, auth, or create failure)."""


class DuplicateCustomerError(ErpError):
    """A customer with the same tax id already exists in the ERP."""

    def __init__(self, card_code: str, message: str = ""):
        self.card_code = card_code
        super().__init__(message or f"Customer already exists as {card_code}.")


class ErpAdapter(ABC):
    backend: str = "none"

    @abstractmethod
    def ping(self) -> dict:
        """Connect / authenticate and return a small status dict."""

    @abstractmethod
    def lookup_reference_data(self) -> dict:
        """Return the ERP's own groups / price lists / payment terms (to help mapping)."""

    @abstractmethod
    def find_customer_by_tax_id(self, tax_id: str) -> str | None:
        """Return an existing customer code for this tax id, or None."""

    @abstractmethod
    def create_customer(self, record: dict) -> dict:
        """Create the customer master. Return {'card_code': str, 'backend': str}."""


def get_adapter() -> ErpAdapter | None:
    """Return the configured adapter, or None when ERP integration is off."""
    backend = (os.getenv("ERP_BACKEND", "") or "").strip().lower()
    if backend in ("", "none", "off"):
        return None
    if backend == "sapb1":
        from sapb1_adapter import SAPB1Adapter
        return SAPB1Adapter()
    if backend == "erpnext":
        raise ErpError("ERPNext adapter is not implemented yet (Phase 4).")
    raise ErpError(f"Unknown ERP_BACKEND '{backend}'.")
