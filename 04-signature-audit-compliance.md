# 4. Digital Signature, Audit Trail & Compliance

Chosen approach: **drawn (canvas) signature with a full audit trail** — appropriate and
defensible for internal customer-credit onboarding, without the cost/integration of a
certified provider. We keep the door open to upgrade later.

## 4.1 What we capture at signing time

| Item | Purpose |
|------|---------|
| Signature image (canvas → PNG, base64) | The visible mark |
| Signatory full name (typed) | Who signed |
| Signatory ID / passport number | Identity binding |
| Signatory role (e.g. Director, Proprietor) | Authority to bind the customer |
| Timestamp (UTC, server-stamped) | When |
| Device metadata: IP, user-agent | Where/how |
| Capture mode + salesperson ID | Context (self-serve vs assisted, by whom) |
| Explicit consent checkbox (data processing + credit terms) | Lawful basis |
| SHA-256 hash of the full payload | Tamper evidence |

## 4.2 What we produce

1. A **signed PDF** of the completed form: all answers + the signature image + an audit
   block (the metadata above) rendered at the bottom. This is the human-readable record.
2. The **canonical JSON** record with the same data + hash, stored server-side.
3. On any later change (approval, ERP creation), append to an **immutable audit log**
   (who, what, when) rather than overwriting.

## 4.3 Tamper evidence (lightweight, no PKI needed)

- Hash the canonical payload at submission; store the digest with the record.
- On approval, hash again including the approver's action; chain the digests.
- Any later edit that doesn't match the stored hash is flagged. This gives
  "tamper-evident" without running a certificate authority.

## 4.4 Kenyan legal & KYC context (verify with counsel before go-live)

- **Electronic signatures are legally recognised** in Kenya (Kenya Information and
  Communications Act; Business Laws (Amendment) Act, 2020). A drawn signature + robust
  audit trail is generally acceptable for commercial onboarding; a *certified/advanced*
  e-signature carries stronger evidentiary weight if ever disputed — that's the upgrade path.
- **KYC data to collect for a credit customer:** KRA PIN (required), national ID / passport
  of the signatory, business registration certificate (for companies), physical address,
  and trade/bank references. These double as the attachments in the data model.
- **Data Protection Act, 2019:** capture explicit consent, state the purpose, store data
  securely, and honour access/deletion requests. Loki Ventures should be (or confirm it is)
  a registered data controller with the ODPC.

> ⚠️ These are engineering notes, not legal advice. Have the finance/legal owner sign off on
> the signature standard and the KYC document list before this replaces the paper form.

## 4.5 Upgrade path if certified signatures are later required

Because signing is isolated behind the form + PDF step, swapping to DocuSign/Adobe Sign
(or a local Kenyan provider) later means replacing that one step — the data model,
dashboard, and ERP adapters are unaffected.
