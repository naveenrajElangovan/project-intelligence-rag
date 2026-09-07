# Linux BOT — day, cash, merchandise, and closure

**Page ID:** T2STORE-BOT-OPS-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-BOT-OPS-ES`

## [BOTOPS-SCOPE] Scope

This page covers the BOT operational lifecycle: day start, dashboard, POS requests, funding, cash reliefs, cash, expenses, cash delivery, reception, transfers, shrinkage, shift closure, and day closure.

## [BOTOPS-START] Start BOT

1. Confirm the **Back Office Store** heading.
2. Verify the visible store and version.
3. Log in with the authorized user.
4. Wait for operational loading to finish.
5. Review the dashboard before starting movements.

If an operational-data loading error appears, select **Retry** once. If it fails again, do not start the day or movements; escalate.

## [BOTOPS-START-DAY] Start the day

**Starting point:** initialized BOT, correct store date, and no operating day already open for the same date.

1. Select **Start day**.
2. Read the displayed date.
3. Confirm once.
4. Wait for the start time and daily dashboard.

If **An operating day already exists for this date** appears, do not start another day. Verify the active day and continue with that record, or escalate when the date is incorrect.

## [BOTOPS-DASHBOARD] Read the dashboard

The home screen may display total daily sales, cash, products, shrinkage, adjustments, and POS status.

- **Total points of sale:** register summary.
- **Safe** and **Tombola:** cash destinations.
- **Last connection:** visible last POS communication.
- Incoming messages: requests or pending work.

Dashboard data supports verification but does not replace a movement's final folio.

## [BOTOPS-POS-REQUEST] Handle a POS request

1. Open the pending message or card.
2. Identify POS, shift, cashier, request type, and amount.
3. Compare with the responsible person before accepting.
4. Complete visible fields.
5. Confirm once and wait for the result.
6. Retain the folio and document.

If POS no longer appears connected, do not duplicate the request. Retain the time and data from both systems and escalate.

## [BOTOPS-INITIAL-FUND] Initial cash fund

1. Open the **Initial cash fund** request.
2. Confirm POS, shift, responsible person, and amount.
3. Deliver or record cash according to store procedure.
4. Confirm once.
5. Wait for the successful initial-fund message.
6. Retain the document and verify that POS receives the result.

## [BOTOPS-ADDITIONAL-FUND] Additional cash fund

1. Open **Additional cash fund**.
2. Review POS, shift, responsible person, and amount.
3. Confirm physical delivery before approval.
4. Confirm once and wait for the result.
5. Retain the receipt.

Do not create another fund because POS is slow to update. Check the folio and last connection.

## [BOTOPS-RELIEF] Cash reliefs

BOT may display a tombola relief, initial or additional fund recovery, expense recovery, or manual relief.

1. Identify **Relief No.**, type, destination, and amount.
2. Confirm the responsible cashier.
3. Count and receive physical cash according to type.
4. Complete the requested amount.
5. Confirm once.
6. Retain the number, folio, and document.

If the final relief is processed with differences, review the visible breakdown. Do not create another relief to compensate without authorization.

## [BOTOPS-CASH-DASHBOARD] Cash dashboard

Open **Cash** or **Cash dashboard** to review movements such as cash fund, additional fund, cash sales, reliefs, corrections, expenses, shortages, overages, and cash delivery.

- Filter or review the visible period.
- Compare amount, type, POS, shift, person, and folio.
- Do not edit or recreate a movement to correct a view.
- If a confirmed movement is missing, retain its source folio and escalate.

## [BOTOPS-EXPENSE] Record expenses

1. Select **Record expenses**.
2. Open the correct pending receipt or withdrawal when applicable.
3. Select **Expense type**.
4. Enter the required comment.
5. Review withdrawn amount, used amount, and returned difference.
6. Confirm once.
7. Wait for the expense-record folio and retain the document.

Every expense needs a reason and comment before shift end. If BOT states that there were no expenses, do not create an empty one.

## [BOTOPS-CASH-DELIVERY] Cash delivery

1. Open **Cash delivery**.
2. Verify service number, security seal, and totals.
3. Enter automatic, manual, and additional reliefs as applicable.
4. Verify that the seal format meets the screen instructions.
5. Review the number of reliefs and total amount.
6. Confirm once and retain the folio.

BOT permits one cash delivery per day when stated. If a delivery already exists for the current date, do not create another.

## [BOTOPS-RECEIVE-SELECT] Select merchandise reception

1. Open **Receive merchandise**.
2. Select the correct origin: warehouse/CEDIS or another store as displayed.
3. Confirm invoice or reference and origin store.
4. Verify that the reception is pending and not completed.

A pending reception may block other work such as the efficient order.

## [BOTOPS-RECEIVE-COUNT] Review and confirm reception

1. Compare physically received boxes and items with the screen.
2. Review each product and quantity.
3. Handle differences through the visible control; do not modify files.
4. If BOT warns that products are not in the store catalog, record which ones will be omitted.
5. Confirm once.
6. Wait for the folio and document copies.

Without a folio or result, do not receive the same invoice again. Escalate with reference, origin, time, and quantities.

## [BOTOPS-TRANSFER-OUT] Outgoing transfer

1. Select products and quantities.
2. Open **Transfer**.
3. Choose **CEDIS** or **Stores**.
4. Read whether variable-weight products were removed.
5. Confirm destination, sender, and reason.
6. Enter the **Required comment**.
7. Review boxes, pieces, or grams.
8. Confirm once.
9. Retain the folio, document, and required signatures or stamps.

Supplies or returnables may be transferable only to CEDIS when BOT says so.

## [BOTOPS-TRANSFER-IN] Incoming transfer

1. Select the correct pending transfer.
2. Confirm origin, destination, invoice, or reference.
3. Review received products and quantities.
4. Record differences through the visible flow.
5. Confirm once.
6. Retain the folio, document, and receiver.

Do not process the same reference again because printing failed.

## [BOTOPS-SHRINKAGE] Record shrinkage

1. Open **Shrinkage**.
2. Search for and select the correct product.
3. Enter pieces or grams according to the displayed unit.
4. Select a **Reason** for every product.
5. Review unit cost and total amount.
6. Remove incorrect lines before confirming.
7. Obtain authorization.
8. Confirm once.
9. Wait for the shrinkage folio and retain the signed document.

For variable weight, use the specific workflow and do not manually convert units.

## [BOTOPS-SHIFT-CLOSE-REQUEST] POS shift-closure request

1. Open the **Close shift** message for the correct POS.
2. Confirm register, shift, and cashier.
3. Review sales, cash, electronic payments, reliefs, expenses, returns, and cancellations.
4. Enter final-relief denominations.
5. Compare entered total and system amount.
6. Review shortage or overage.
7. Select **Finish shift** once.
8. Retain the folio and verify two copies when BOT confirms them.

If the amount is processed with differences, do not repeat closure. Retain the breakdown and escalate.

## [BOTOPS-END-DAY-BLOCKERS] Day-closure blockers

BOT may display **Unable to close the day**. Resolve only the items listed on the screen:

- **Shift closure - POS:** complete the indicated shift.
- **Price printing:** complete or resolve the pending job.
- **Efficient order:** process the available order.
- Pending expenses: complete type and comment.
- Receptions or other pending movements when displayed.

Do not try to bypass the blocker by closing the application.

## [BOTOPS-END-DAY] Close the day

1. Open **Day closure**.
2. Review the reminder to record every expense.
3. If one is missing, select **Record expenses** and complete it.
4. Review sales, reliefs, payments, expenses, cash delivery, shrinkage, and transfers.
5. Resolve every visible blocker.
6. Confirm closure once.
7. Wait for the day-closure folio.
8. Retain the complete cover and every page.

Do not repeat closure when a folio exists even if printing fails.

## [BOTOPS-LOGOUT] Sign out of BOT

1. Confirm that no movement or processing is pending.
2. Select **Exit / Close session**.
3. Respond to **Do you want to sign out?**.
4. Verify that the login screen returns.

Signing out does not replace day closure.

## [BOTOPS-FAQ] Quick answers

**Can I start another day when BOT says one exists?** No.

**Can I duplicate a reception when it did not print?** No; first confirm the folio.

**What blocks closure?** Handle exactly the list shown by BOT.

**Can I close BOT to ignore a difference?** No.

**How many cash deliveries can I record?** Follow the displayed limit; BOT may permit only one per day.

## [BOTOPS-ESCALATE] Support information

Store, terminal, version, user without password, screen, movement, related POS and shift, amount, products or quantities, invoice or reference, folio, date, time, and exact message. Retain documents without sharing sensitive data.

## [BOTOPS-QA] QA pending

- Confirm routes, roles, and authorizations.
- Confirm copies by reception and transfer.
- Validate the complete closure blockers.
- Capture empty, difference, success, and failure states.
- Confirm recovery after lost POS/BOT connectivity.

