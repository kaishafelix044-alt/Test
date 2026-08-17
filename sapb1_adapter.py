"""SAP Business One adapter — Service Layer (v10).

Talks to the Service Layer over HTTPS using only the standard library. Handles
login (session cookie), a duplicate check by KRA PIN (FederalTaxID), and the
BusinessPartners create. Field mapping lives in sap_mapping.py.

CLI helpers (after filling .env):
    python -m sapb1_adapter --ping        # test login + print company info
    python -m sapb1_adapter --reference   # print BP Groups / Price Lists / Payment Terms codes
    python -m sapb1_adapter --dry-run FILE # build & print the BP payload from a record.json
"""

from __future__ import annotations

import json
import os
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from env_loader import load_dotenv
from erp_adapter import DuplicateCustomerError, ErpAdapter, ErpError
from sap_mapping import build_business_partner, mapping_warnings


class SAPB1Adapter(ErpAdapter):
    backend = "sapb1"

    def __init__(self):
        load_dotenv()  # ensure .env is available even if the server didn't load it
        self.base = (os.getenv("SAP_SL_URL", "") or "").strip().rstrip("/")
        self.company_db = os.getenv("SAP_COMPANY_DB", "").strip()
        self.username = os.getenv("SAP_USERNAME", "").strip()
        self.password = os.getenv("SAP_PASSWORD", "")
        self.verify_ssl = (os.getenv("SAP_VERIFY_SSL", "false").strip().lower()
                           in ("1", "true", "yes", "on"))
        self._cookie = ""
        missing = [n for n, v in {
            "SAP_SL_URL": self.base, "SAP_COMPANY_DB": self.company_db,
            "SAP_USERNAME": self.username, "SAP_PASSWORD": self.password}.items() if not v]
        if missing:
            raise ErpError("SAP is not fully configured — set: " + ", ".join(missing))

    # -- transport ---------------------------------------------------------- #
    def _ctx(self) -> ssl.SSLContext:
        if self.verify_ssl:
            return ssl.create_default_context()
        return ssl._create_unverified_context()

    def _request(self, method: str, path: str, body: dict | None = None,
                 authed: bool = True) -> tuple[int, dict, dict]:
        url = self.base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if authed and self._cookie:
            headers["Cookie"] = self._cookie
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=45, context=self._ctx()) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                set_cookies = resp.headers.get_all("Set-Cookie") or []
                payload = json.loads(raw) if raw.strip() else {}
                return resp.status, payload, {"set_cookie": set_cookies}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                msg = json.loads(detail).get("error", {}).get("message", {})
                msg = msg.get("value", detail) if isinstance(msg, dict) else msg
            except (json.JSONDecodeError, AttributeError):
                msg = detail
            raise ErpError(f"SAP {method} {path} -> HTTP {exc.code}: {msg}") from exc
        except URLError as exc:
            raise ErpError(f"Cannot reach SAP Service Layer at {self.base}: {exc.reason}") from exc

    def login(self) -> None:
        _, _, meta = self._request("POST", "/Login", {
            "CompanyDB": self.company_db, "UserName": self.username, "Password": self.password,
        }, authed=False)
        pairs = []
        for raw in meta.get("set_cookie", []):
            first = raw.split(";", 1)[0].strip()
            if first.startswith(("B1SESSION=", "ROUTEID=")):
                pairs.append(first)
        if not any(p.startswith("B1SESSION=") for p in pairs):
            raise ErpError("SAP login did not return a B1SESSION cookie.")
        self._cookie = "; ".join(pairs)

    def logout(self) -> None:
        if self._cookie:
            try:
                self._request("POST", "/Logout")
            except ErpError:
                pass
            self._cookie = ""

    def _ensure_login(self) -> None:
        if not self._cookie:
            self.login()

    # -- ErpAdapter API ----------------------------------------------------- #
    def ping(self) -> dict:
        self._ensure_login()
        status, data, _ = self._request("GET", "/CompanyService_GetCompanyInfo")
        return {"backend": self.backend, "connected": True,
                "company": data.get("CompanyName", self.company_db),
                "sl_url": self.base}

    def lookup_reference_data(self) -> dict:
        self._ensure_login()

        def rows(path):
            _, data, _ = self._request("GET", path)
            return data.get("value", [])

        groups = rows("/BusinessPartnerGroups?$select=Code,Name,Type&$top=200")
        cust_groups = [{"code": g.get("Code"), "name": g.get("Name")}
                       for g in groups if g.get("Type") in (None, "bbpgt_CustomerGroup")]
        price_lists = [{"code": p.get("PriceListNo"), "name": p.get("PriceListName")}
                       for p in rows("/PriceLists?$select=PriceListNo,PriceListName&$top=200")]
        terms = [{"code": t.get("GroupNumber"), "name": t.get("PaymentTermsGroupName")}
                 for t in rows("/PaymentTermsTypes?$select=GroupNumber,PaymentTermsGroupName&$top=200")]
        return {"customer_groups": cust_groups, "price_lists": price_lists, "payment_terms": terms}

    def find_customer_by_tax_id(self, tax_id: str) -> str | None:
        if not tax_id:
            return None
        self._ensure_login()
        flt = quote(f"FederalTaxID eq '{tax_id}'", safe="")
        _, data, _ = self._request(
            "GET", f"/BusinessPartners?$select=CardCode,CardName&$filter={flt}&$top=1")
        rows = data.get("value", [])
        return rows[0].get("CardCode") if rows else None

    def create_customer(self, record: dict) -> dict:
        self._ensure_login()
        pin = (record.get("company") or {}).get("pin_number") or ""
        existing = self.find_customer_by_tax_id(pin)
        if existing:
            raise DuplicateCustomerError(existing)
        payload = build_business_partner(record)
        _, data, _ = self._request("POST", "/BusinessPartners", payload)
        card_code = data.get("CardCode")
        if not card_code:
            raise ErpError("SAP created the partner but returned no CardCode.")
        return {"card_code": card_code, "backend": self.backend,
                "warnings": mapping_warnings(record)}


# ------------------------------------------------------------------------- #
# CLI helpers
# ------------------------------------------------------------------------- #
def _main(argv: list[str]) -> int:
    load_dotenv()
    if "--dry-run" in argv:
        idx = argv.index("--dry-run")
        path = argv[idx + 1] if idx + 1 < len(argv) else "record.json"
        record = json.loads(open(path, encoding="utf-8").read())
        print(json.dumps(build_business_partner(record), indent=2, ensure_ascii=False))
        for w in mapping_warnings(record):
            print("WARNING:", w, file=sys.stderr)
        return 0

    try:
        adapter = SAPB1Adapter()
    except ErpError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        if "--ping" in argv:
            print(json.dumps(adapter.ping(), indent=2))
        elif "--reference" in argv:
            print(json.dumps(adapter.lookup_reference_data(), indent=2, ensure_ascii=False))
        else:
            print("usage: python -m sapb1_adapter [--ping | --reference | --dry-run FILE]")
            return 1
    except ErpError as exc:
        print(exc, file=sys.stderr)
        return 2
    finally:
        adapter.logout()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
