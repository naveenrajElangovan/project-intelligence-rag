# Linux POS — sales, shifts, and cash

**Page ID:** T2STORE-POS-OPS-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-POS-OPS-ES`

## [POSOPS-SCOPE] Scope

This page covers visible daily POS work: initialization, shift opening, funding, products, quantities, pending sales, cancellations, returns, cash reliefs, withdrawals, expenses, sales summaries, and closure. Electronic payments and printers have separate pages.

## [POSOPS-START] Checks when starting POS

1. Confirm that the heading says **Point of Sale**.
2. Check the visible store and version.
3. Log in with the cashier account that will operate the register.
4. Wait for operational data to finish loading.
5. Do not start a sale while **Loading...** or an initialization error is displayed.

If **There was a problem loading the store's operational data** appears, use **Retry** once. If it continues, do not operate with potentially incomplete information; escalate.

## [POSOPS-OPEN-SHIFT] Open a shift

**Role:** cashier with permission and authorized shift manager.  
**Starting point:** initialized POS with no active shift on the register.  
**Visible route:** **Shift & Session** and the open-shift option.

### Procedure

1. Verify cashier name, register, and store.
2. Select shift opening.
3. When **Shift manager: Enter your credentials to authorize** appears, the responsible person enters their own credentials.
4. Review the displayed initial-fund amount.
5. Confirm once.
6. Wait for open-shift confirmation and the **CASH FUND** document to print.
7. Retain the receipt and complete the recipient and issuer signatures.

### Failures and boundaries

- **Action not allowed. You do not have permission to start a shift:** cancel and request the correct role.
- No printout but shift confirmed: do not open another shift; use reprinting guidance or support.
- No visible result: do not repeat opening until the status is confirmed with BOT or support.

## [POSOPS-ADDITIONAL-FUNDING] Additional funding

1. Handle the additional-fund request or notice displayed by POS.
2. Confirm the amount and the responsible person delivering cash.
3. Obtain the requested authorization.
4. Confirm once and wait for the movement to finish.
5. Retain the receipt.

Do not use a manual relief as a substitute for funding that has no result. Retain amount, time, register, and screen and escalate.

## [POSOPS-ADD-PRODUCT] Add a product

**Starting point:** main sale screen with an open shift.

1. Scan the barcode once.
2. Confirm the description, price, and added quantity.
3. If the product has no readable code, open the visible no-code product or search workflow.
4. Search with the fields offered by the screen and select the correct product.
5. Before payment, physically compare the item with the description.

If the product is not found or its price cannot be verified, do not select a similar item. Retain the barcode, description, and observed price and consult BOT or support.

## [POSOPS-QUANTITY] Multiply or correct quantity

1. Select the correct cart item.
2. Use the visible quantity or multiplication function.
3. Enter the exact quantity.
4. Review the line total and sale total.

If the total exceeds the maximum sale amount, reduce or correct the list. Do not split a sale solely to bypass the limit without an authorized procedure.

## [POSOPS-PRICE-CHECK] Check a price

1. Open **Check price** when available.
2. Scan or search for the product.
3. Read the displayed description and price.
4. Return to the sale without adding the product when the check is informational only.

If BOT and POS display different prices, do not change files or manually enter a catalog. Retain the barcode, both prices, time, and screens and escalate.

## [POSOPS-PENDING-SALE] Pending sale

An open sale must be completed or correctly cancelled before shift closure.

- Return to the pending sale through the visible option.
- Review products and any payments already started.
- If no payment occurred, complete or cancel with the required authorization.
- If an electronic payment is ambiguous, do not cancel or repeat until support confirms the result.

Closing the window does not safely remove a pending sale.

## [POSOPS-CANCEL-PRODUCT] Cancel products

1. Select the exact product in the cart.
2. Enter the quantity to cancel.
3. Confirm that it is not greater than the sold quantity.
4. Request the visible authorization.
5. Confirm and verify that the cart and total update.

If **This product is not in the cart** or a quantity warning appears, return to the cart and correct the selection. Do not add or cancel different products to balance the total.

## [POSOPS-CANCEL-SALE] Cancel the complete sale

1. Verify that this is the correct sale and no electronic payment is ambiguous.
2. Select complete cancellation.
3. Obtain the requested authorization.
4. Confirm once.
5. Wait for POS to show the result and generate **TOTAL CANCELLATION** when applicable.

Retain the ticket, authorization, and receipt. If the screen does not finish, do not cancel again; escalate with the time and sale details.

## [POSOPS-RETURN] Perform a return

1. Open the return workflow.
2. Enter or locate the original ticket as requested by the screen.
3. Verify items, quantities, and amount.
4. Obtain the required authorization.
5. Confirm once and wait for the result.
6. Retain the **RETURN** receipt, including the authorizer.

Do not process a second return because printing failed. Use authorized document recovery or escalate.

## [POSOPS-OPEN-DRAWER] Open the cash drawer

1. Confirm that opening is required for an authorized operation.
2. Select **Open drawer**.
3. When **Enter the responsible cashier's credentials to authorize** appears, that person enters their own credentials.
4. Confirm once.

The drawer may depend on the physical printer connection. If it does not open, do not strike or force it. Check printer power and the accessible connection and escalate if it continues.

## [POSOPS-CASH-RELIEF] Perform a cash relief

**Visible controls:** **Postpone**, **Perform relief**, **Relief amount**, **Confirm amount**, and **Confirm Cash Relief**.

1. Read the type and destination: tombola, expense, initial-fund recovery, or additional-fund recovery as displayed.
2. Count the cash before entering it.
3. Enter and confirm the amount.
4. Review the amount shown under **Withdraw**.
5. Select **Confirm Cash Relief** once.
6. Wait for confirmation and printing.
7. Retain the relief number and requested signatures.

If a number or receipt already exists, do not repeat the relief when printing fails.

## [POSOPS-EXPENSE-WITHDRAWAL] Expense withdrawal

1. Open **Expense withdrawal**.
2. Enter the authorized amount.
3. Confirm with the shift manager when requested.
4. Wait for the **Receipt number**.
5. Print and complete the cashier and shift-manager names and signatures.

The document states when signatures are required for validity. Do not treat an incomplete receipt as settled.

## [POSOPS-EXPENSE-SETTLEMENT] Settle an expense

1. Open the settlement workflow.
2. Scan or enter the correct pending receipt.
3. Review withdrawn amount, used amount, and difference returned to the register.
4. Obtain authorization from the user who opened the shift when requested.
5. Confirm once and retain the new receipt.

### Messages

- **Invalid receipt:** do not continue with that document.
- **Unable to read the code:** physically inspect the code; do not invent numbers.
- **No pending receipt found:** confirm the receipt and shift.
- **Authorization from the user who opened the shift is required:** wait for that person or escalate.

## [POSOPS-SUMMARY] Sales summary

1. Open the shift sales summary.
2. Review sales, cash, E-vale, cards/CoDi, reliefs, and returns.
3. Request District Manager authorization when the screen requires it.
4. Confirm cash in drawer and receipts that must be checked.
5. Print once and retain the **SALES SUMMARY** document.

Do not correct differences by creating new movements without authorization.

## [POSOPS-CLOSE-SHIFT] Close a shift

**Prerequisites:** no pending sale, resolved payments, and recorded shift movements.

1. Select **Close shift** or **Close shift and session**.
2. If **Shift closure unavailable** appears, first complete or cancel the indicated sale.
3. Review any pending recovery or relief.
4. Obtain required authorization.
5. Confirm once and wait for BOT.
6. Do not close POS while closure is processing.
7. Retain the folio and receipt when displayed.

If BOT does not respond or shows differences, do not repeat closure; compare folio, register, shift, amount, and time with the responsible person.

## [POSOPS-SAFE-RESTART] POS does not respond

Before considering closing POS, identify whether a payment, print, cancellation, return, relief, or closure is active. If a financial operation is ambiguous, do not restart. Retain the screen and time and contact support.

Only when there is no active operation and the authorized procedure permits it, close and reopen the application through its normal launcher. Never use commands or terminate processes.

## [POSOPS-FAQ] Quick answers

**Can I open another shift when the fund receipt did not print?** No. First confirm the existing shift status.

**Can I close a shift with an open sale?** No. POS requires the sale to be completed or cancelled.

**Can I repeat a relief when no paper came out?** Not when a confirmation or relief number already exists.

**Can I select a similar product when the code is missing?** No.

**What should I do with a return that did not print?** Do not repeat it; retain the ticket and escalate.

## [POSOPS-ESCALATE] Escalation information

Application, store, register, shift, user without password, screen, step, date and time, ticket or folio, amount, and exact message. For payments, also use the payment evidence checklist. For printing, retain every copy.

## [POSOPS-QA] QA pending

- Confirm exact Linux routes and shortcuts.
- Confirm permissions by operation.
- Confirm automatic printing and copy counts.
- Validate pending-sale recovery.
- Capture success, empty, blocked, and failure states.

