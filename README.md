# Customer Account Creation — End-to-End Automation

Automating the customer onboarding process at Loki Ventures: from the moment a
salesperson hands over the (now digital) form, through the customer's signature,
to the accounts team creating the customer master — with credit terms, price
list, and customer group — in the ERP.

**Design constraint that shapes everything:** the solution must be **ERP-agnostic**.
We run **SAP Business One v10** today and migrate to **ERPNext** in ~1 month. The
capture form, signature, and approval workflow stay identical; only a thin
translation layer swaps underneath.

---

## Read these in order

| # | Document | What it covers |
|---|----------|----------------|
| 1 | [01-scope-and-process.md](01-scope-and-process.md) | As-is vs to-be process, what's in/out of scope |
| 2 | [02-architecture.md](02-architecture.md) | The ERP-agnostic design and how the pieces fit |
| 3 | [03-data-model-and-erp-mapping.md](03-data-model-and-erp-mapping.md) | Canonical customer schema mapped to SAP B1 and ERPNext |
| 4 | [04-signature-audit-compliance.md](04-signature-audit-compliance.md) | Digital signature, audit trail, Kenyan legal/KYC |
| 5 | [05-roadmap-phases.md](05-roadmap-phases.md) | Phased build plan with milestones and deliverables |
| 6 | [06-open-questions.md](06-open-questions.md) | Decisions still needed before/while building |

---

## The four decisions already made

1. **Target system:** SAP B1 v10 **and** ERPNext → solution is ERP-agnostic via an adapter.
2. **Who captures:** both — a self-serve link **and** salesperson-assisted capture.
3. **Signature:** drawn (canvas) signature **with a full audit trail** (timestamp, name, ID, device/IP metadata).
4. **Automation level:** validate + prepare automatically, then **accounts team reviews and one-click approves** before the account goes live (safest for credit).

## The shape of the solution in one picture

```
  SALES / CUSTOMER              SYSTEM (ours)                     ACCOUNTS TEAM            ERP
  ───────────────              ─────────────                     ─────────────            ───
  Digital form  ──submit──▶  Validate + save + sign PDF  ──▶  Review queue (dashboard)
  (self-serve or                    │                              │  assign/confirm:
   assisted, +                 email accounts team                 │  • credit terms
   signature)                       │                              │  • price list
                                    ▼                              │  • customer group
                              Pending record                       │
                                                          one-click approve ──▶ Adapter ──▶ SAP B1  (Service Layer)
                                                                                    └──────▶ ERPNext (REST API)
```

Nothing above the "Adapter" line ever changes when we move from SAP B1 to ERPNext.
