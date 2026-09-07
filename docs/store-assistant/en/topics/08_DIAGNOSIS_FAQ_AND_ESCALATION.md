# Diagnosis, FAQs, and escalation — Tiendas 2.0 Linux

**Page ID:** T2STORE-SUPPORT-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-SUPPORT-ES`

## [SUPPORT-SCOPE] Purpose

This page helps the assistant understand a question, route it to the correct procedure, and respond safely when evidence is insufficient. It does not replace operational pages.

## [SUPPORT-CLASSIFY] Classify the question

First identify a category:

- Access, password, session, or authorization.
- POS: shift, product, sale, cash, cancellation, or return.
- Payment: cash, card, CoDi, E-vale, service, or airtime.
- Printing: ticket, label, report, PDF, or drawer.
- BOT: day, POS request, merchandise, transfer, shrinkage, expense, or closure.
- Products and prices.
- Inventory and Zebra.
- Efficient order.
- Integrated tools.
- Out of scope.

## [SUPPORT-CLARIFY] Minimum clarification questions

Ask only what is necessary:

1. Are you using POS or BOT?
2. Which screen do you see?
3. What is the exact message?
4. What action happened immediately before it?
5. Does a ticket, folio, or authorization already exist?
6. Is the screen still processing?

For payments add: which method was used, and does the customer or terminal show a charge? Never request sensitive information.

## [SUPPORT-ANSWER-FORMAT] Format for a useful answer

1. First state whether to wait, stop, or continue.
2. Summarize the visible state without inventing a cause.
3. Give numbered steps using button names.
4. State the expected result.
5. Warn what must not be repeated.
6. List information to retain.
7. Define when to contact support.

## [SUPPORT-PROCESSING] Rule for processing states

When the screen displays **Processing**, **Loading**, **Validating**, **Preparing print**, **Searching for a printer**, **Logging In**, or equivalent:

- Do not repeat the button.
- Do not change workflows.
- Do not close the application.
- Wait for a final result or visible retry option.
- If no result appears, retain the time and screen and escalate.

Do not publish exact waiting times until QA and product approve them.

## [SUPPORT-DUPLICATE] Duplicate-prevention rule

Do not repeat a sale, payment, funding, relief, expense, reception, transfer, shrinkage, adjustment, order, or closure when any of these exists:

- Ticket.
- Folio.
- Authorization.
- External receipt.
- Success message.
- Ambiguous state after submission.

First confirm the result through an authorized procedure.

## [SUPPORT-NO-EVIDENCE] Response when verified guidance is unavailable

Use this response:

> I could not find verified guidance for this Tiendas 2.0 Linux store situation. Do not make technical changes or repeat an operation that could create a duplicate movement. Retain the application, store, terminal, time, message, and folio or ticket when one exists, and contact authorized support.

When possible, add the closest POS or BOT page link without inventing a solution.

## [SUPPORT-OFF-TOPIC] Out-of-scope questions

The assistant must decline:

- Linux commands or administration.
- Installation, configuration, or deployment.
- Source code, libraries, events, databases, or logs.
- Passwords, secrets, tokens, or technical credentials.
- Hardware repair or dismantling.
- General topics unrelated to Tiendas 2.0.
- Android, Windows, or macOS.

Suggested response:

> This assistant covers only visible POS and BOT operation and troubleshooting for Linux stores. I can help with access, sales, payments, printing, merchandise, inventory, orders, cash, and closure.

## [SUPPORT-PRIVACY] Information that must never be requested

- Current or new password.
- PIN.
- Complete card number.
- Security code or expiration date.
- Token, secret, or technical account.
- Customer personal information.
- Photographs containing banking information.
- Internal configuration or inventory files through unauthorized channels.

## [SUPPORT-SCREENSHOT] Safe screenshots

Before sharing a screenshot:

1. Hide full names.
2. Hide the user when unnecessary.
3. Remove passwords and sensitive fields.
4. Hide cards, PINs, bank references, and customer data.
5. Retain the application, screen, message, approximate date, and permitted folio.

## [SUPPORT-AUTH-QUICK] Quick access questions

**My user cannot sign in.** Check the user and re-enter the password once. If it fails again, stop attempting and escalate.

**It says password expired.** Use the form when offered; if it directs you to support, there is no store-level resolution.

**It requests another user.** Read the requested role; the authorized person enters their own credentials.

**Can I share my password?** No.

**Can I sign in without internet?** Only when the application accepts local authorization and enables functions.

## [SUPPORT-POS-QUICK] Quick POS questions

**A product does not appear.** Search by code, key, and description; do not use another product.

**The price differs.** Compare POS, BOT, and label work; do not edit catalogs.

**I cannot close the shift.** Complete or cancel the pending sale and resolve payments.

**The fund receipt did not print.** Do not open another shift; confirm status and recover the document.

**A return did not print.** Do not repeat the return.

## [SUPPORT-PAY-QUICK] Quick payment questions

**The terminal approved and POS did not.** Do not repeat; retain the receipt and escalate.

**CoDi is still processing.** Do not generate another QR.

**E-vale does not recognize the card.** Retry only when POS offers it and no charge occurred.

**No ticket printed.** Do not charge again.

**Can I ask for the PIN?** No.

## [SUPPORT-PRINT-QUICK] Quick printing questions

**POS printer error.** Confirm the operation, power, paper, and accessible connection; reprint only with a confirmed ticket.

**BOT says print sent.** Physically confirm every sheet.

**Partial or blank sheet.** Retain it, do not repeat the movement, and use authorized recovery.

**Drawer does not open.** Physically check the printer without forcing the drawer; escalate.

## [SUPPORT-BOT-QUICK] Quick BOT questions

**A day already exists.** Do not start another.

**Reception did not print.** Confirm the folio; do not duplicate it.

**The day will not close.** Handle every listed blocker.

**A movement is missing from the dashboard.** Retain the folio and check connectivity; do not recreate it.

## [SUPPORT-INVENTORY-QUICK] Quick inventory questions

**Zebra does not appear.** Reconnect once from the screen; do not use commands.

**No file found.** Finish the count on the same Zebra; do not fabricate files.

**Can I rename it?** No.

**Which file is Sales Floor?** `_1.txt`.

**Which file is Warehouse?** `_0.txt`.

**One file is missing.** Do not continue to adjustment.

## [SUPPORT-ORDER-QUICK] Quick order questions

**Where does it appear?** In incoming messages as **Efficient order available**.

**It is blocked.** Complete the listed pending reception or transfer.

**Can I change suggested quantity?** Only authorized quantities reviewed before confirmation.

**It did not print.** Do not confirm another order when a folio exists.

## [SUPPORT-SEVERITY] Escalation priority

### Immediate

- Possible duplicate charge or ambiguous payment.
- Unresolved cash difference.
- Different folios indicating possible duplication.
- Exposed sensitive data.
- Financial operation blocked without a result.

### Before continuing the process

- Required user or permission unavailable.
- Catalog or price cannot be verified.
- Reception, transfer, inventory, order, or closure has no result.
- POS and BOT display different states.

### May be retained for support without stopping unrelated safe operations

- An additional copy did not print when the movement and primary document are verified.
- A nonessential integrated tool is temporarily blank.
- A query or filter is empty after confirming that it does not affect a pending movement.

Final priority must follow the organization's official support procedure.

## [SUPPORT-HANDOFF] Escalation template

**Application:** POS/BOT  
**Store:**  
**Register/terminal:**  
**Visible version:**  
**Date and time:**  
**Screen:**  
**Operation:**  
**Step before the problem:**  
**Exact message:**  
**Ticket/folio/authorization:**  
**Amount or quantity, if applicable:**  
**Visible POS/BOT/device state:**  
**Is it still processing?:**  
**Could there be a duplicate or charge?:**  
**Sanitized evidence attached:** Yes/No

## [SUPPORT-QA] Criteria for approving an answer

Publish an answer only when:

1. The function exists in Linux `v1.3.0`.
2. Visible wording was confirmed.
3. Role and permission were confirmed.
4. The procedure was reproduced in QA.
5. The result and folio were observed.
6. The do-not-repeat boundary was validated.
7. The support boundary was defined.
8. A sanitized screenshot exists.
9. The Spanish page contains the same fact.
10. The product owner approved it.

