# 1. Scope and Process

## 1.1 The process today (as-is)

| Step | Who | What happens | Pain |
|------|-----|--------------|------|
| 1 | Salesperson | Hands customer a physical paper form | Paper gets lost, illegible, delayed |
| 2 | Customer | Fills the form by hand, **signs physically** | No validation; missing fields discovered later |
| 3 | Salesperson | Returns the paper to the accounts team | Physical hand-off, transport delay |
| 4 | Accounts team | Manually keys the customer into the ERP | Re-keying errors, slow |
| 5 | Accounts team | Sets **credit terms**, assigns **price list** and **customer group** | Inconsistent rules, no audit of who approved credit |

## 1.2 The process we want (to-be)

1. **Capture** — Salesperson opens a link (or sends it to the customer). Form works on
   phone/tablet, supports **self-serve** and **assisted** modes. Required fields are
   enforced before submission is possible.
2. **Sign** — Customer draws their signature on-screen. We capture it with a full audit
   trail (name, ID number, timestamp, device/IP). A signed PDF copy of the completed
   form is generated for the record.
3. **Submit** — On submit, the record is validated, saved, and the accounts team is
   emailed (Microsoft Graph, same as InvoTrak/ReceivingPlaybook).
4. **Review** — The submission appears in an accounts-team dashboard as *Pending*. The
   team confirms/adjusts the proposed **credit terms**, **price list**, and **customer
   group** (with sensible defaults pre-filled by rules).
5. **Approve → Create** — One click. The adapter creates the customer master in the
   **current ERP** (SAP B1 today, ERPNext after migration) including credit terms, price
   list, and group. The record moves to *Created* and stores the ERP's customer code.

## 1.3 In scope

- Digital capture form (self-serve + assisted), mobile-friendly, single-file HTML.
- Mandatory drawn signature + audit trail + signed PDF.
- Document attachments (ID, KRA PIN certificate, business registration, etc.).
- Server: receive, validate, store, email, generate PDF (Python, extends existing pattern).
- Accounts review/approval dashboard.
- Rules engine (defaults) for credit terms / price list / customer group.
- **ERP-agnostic adapter** with two implementations: SAP B1 (Service Layer) and ERPNext (REST).
- Basic reporting: pipeline of pending/approved/rejected, turnaround time.

## 1.4 Out of scope (for now — revisit later)

- Certified/qualified e-signature (DocuSign/Adobe). We chose drawn + audit trail.
- Automatic credit scoring / CRB (Credit Reference Bureau) checks — can be a Phase 2 add-on.
- Full CRM. This is onboarding only, not the customer's whole lifecycle.
- Editing existing customers in the ERP (this is creation only).

## 1.5 Success criteria

- Zero paper in the standard path; signature legally defensible for internal credit onboarding.
- No manual re-keying into the ERP; created account matches submission exactly.
- Same tool works before and after the ERPNext migration with only a config switch.
- Full audit: who submitted, who approved, when, and what credit was granted.
