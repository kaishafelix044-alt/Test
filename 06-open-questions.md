# 6. Open Questions (decide before/while building)

Grouped by who typically owns the answer. These don't block starting Phase 1, but Phase 3
(ERP write) needs the ERP section resolved.

## For the accounts / finance owner
1. **Credit terms rules:** what default payment terms and credit limit should the rules
   engine propose, and by what signal (customer group? first order value? none — always manual)?
2. **Who may approve credit,** and is there a limit above which a second approver is needed?
3. **Customer code series:** does SAP B1 auto-assign `CardCode`, or do we generate a code
   (and by what pattern)? Same question for ERPNext naming series.
4. **Mandatory KYC documents:** exact list required before an account can be approved
   (KRA PIN cert, ID, business registration, others?).
5. **Price lists & customer groups:** the current valid list in each ERP, and the default
   for a new customer.

## For IT / ERP admin
6. **SAP B1 Service Layer:** host/port, a test company DB, and a least-privilege service
   account (create Business Partner). Is the Service Layer enabled and reachable?
7. **ERPNext:** test site URL, API key/secret, and which **company** the `credit_limits`
   attach to.
8. **ERPNext go-live date** (to align Phase 4 with cutover) and whether both run in parallel
   for a period.
9. **Hosting** for the Python server (which internal machine; is it reachable by salespeople
   in the field, or only on-network → do we need a public/VPN endpoint?).
10. **Email:** reuse the existing Microsoft Graph app registration, or a new one scoped to
    this tool? Which mailbox sends, and who receives the accounts notification?

## For legal / compliance (Kenya)
11. Sign-off that **drawn signature + audit trail** meets the bar for your credit agreements,
    or a decision to budget for a certified e-signature provider.
12. Confirm Loki Ventures' **Data Protection Act** registration and the consent wording to
    put on the form.

## Product / UX
13. Should the customer receive a **copy of their signed PDF** by email automatically?
14. Do salespeople need a **status view** ("has my customer been approved yet?"), or is
    that accounts-only?
15. Language: English only, or English + Swahili on the customer-facing form?

---

### How to use this file
As each answer lands, record it inline here and, if it changes a design doc, update that doc
too. Anything still open when we reach a phase that needs it becomes a blocker to flag.
