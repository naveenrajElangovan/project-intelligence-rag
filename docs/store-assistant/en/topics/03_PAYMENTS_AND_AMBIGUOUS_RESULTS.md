# Linux POS — payments and ambiguous results

**Page ID:** T2STORE-PAY-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-PAY-ES`

## [PAY-SCOPE] Scope and primary rule

This page covers cash, cards, CoDi, E-vale, mixed payments, services, and airtime. The primary rule is: **when an electronic payment may have been applied, do not repeat it until the result is verified**.

Related phrases include: *stuck processing*, *terminal approved*, *did not print*, *customer was charged*, *CoDi pending*, *balance does not appear*, *card not recognized*, *payment declined*, or *service has no folio*.

## [PAY-BEFORE] Before charging

1. Confirm products, quantities, total, and any visible commission.
2. Ask the customer for the payment method.
3. Select the method once.
4. For a service or airtime, confirm provider, reference or phone number, and amount.
5. Verify that no other payment has already started for the same sale.

Do not write down a PIN, complete card number, expiration date, or security code.

## [PAY-PROCESSING] While POS displays “Processing payment”

- Wait without selecting another method.
- Do not press Accept repeatedly.
- Do not close POS.
- Do not remove the card when **Do not remove the card yet** is displayed.
- Do not generate a second CoDi QR.
- Do not start another sale to charge the same amount.

An animation or processing message does not confirm approval or rejection.

## [PAY-CASH] Cash payment

1. Select **Cash**.
2. Enter the amount received.
3. Verify **Amount to cover**, **Amount paid**, and **Change**.
4. Confirm the amount before closing.
5. Give the displayed change after POS shows **Close Sale**.
6. Retain or give the ticket according to store procedure.

If the amount was entered incorrectly, correct it before closing. Do not use later movements to compensate for incorrect change.

## [PAY-CARD] Debit or credit card

**Controls:** **Debit Card**, **Credit Card**, and the **Card Payment** screen.

1. Select the type requested by the customer.
2. Follow the visible POS and Santander terminal instructions.
3. Keep the card in place as directed by the terminal and POS.
4. Wait for a final result.
5. If **Transaction successful** appears, verify that POS closes the sale and produces the receipt.
6. If **Transaction declined** appears, inform the customer and use **Try again or use another payment method** only after the final result.

## [PAY-CARD-NOT-RESPONDING] Terminal does not respond or start

1. Do not repeatedly select the card method.
2. Confirm that the terminal has power and is physically available.
3. Read messages on both POS and the terminal.
4. If no approval appeared and the terminal never requested a card, cancel only with a visible control.
5. If it is unclear whether the transaction started, treat the result as ambiguous and escalate.

Do not disconnect the terminal or change connections during an active request.

## [PAY-CARD-APPROVED-POS-PENDING] Terminal approved but POS did not finish

This is an ambiguous result.

1. Do not charge again.
2. Do not cancel the sale yourself while POS is still processing.
3. Retain the terminal receipt.
4. Record amount, date, time, register, ticket, authorization, and permitted visible last digits.
5. Contact authorized support to confirm the status.

Never ask the customer for their complete card number or a screenshot of their banking application.

## [PAY-CARD-POS-SUCCESS-NO-PRINT] POS approved but did not print

1. Do not repeat the charge.
2. Confirm that the sale closed and a ticket number exists.
3. Retain the terminal receipt.
4. Check printer power, paper, and the accessible connection.
5. Use **Reprint ticket** with the correct date and number.
6. If the ticket cannot be located, escalate.

## [PAY-CARD-DECLINED] Declined payment

When POS displays **Transaction declined**:

1. Confirm that it is a final message and processing has ended.
2. Inform the customer without interpreting a bank reason.
3. Use another method or a new attempt only when POS permits it.
4. If the customer reports a charge, treat the result as ambiguous and do not repeat it.

The assistant must not diagnose funds, a bank block, or fraud unless the screen explicitly says so.

## [PAY-CODI] Normal CoDi payment

1. Select **CoDi**.
2. Verify the amount before showing the QR.
3. Ask the customer to scan **Scan to pay**.
4. Wait during **Processing payment...** without generating another code.
5. Continue only after **Transaction successful**.
6. Verify sale closure, ticket, authorization, and CoDi folio when displayed.

## [PAY-CODI-DECLINED] CoDi unsuccessful

If POS displays **Transaction declined** and is no longer processing, offer another method according to the screen. If the customer states that payment was sent or shows a transaction, do not repeat or generate another QR; retain the folio, amount, and time and escalate.

## [PAY-CODI-TIMEOUT] CoDi remains processing or times out

1. Do not generate another QR.
2. Do not close POS during the active check.
3. Ask the customer not to submit payment again.
4. If a final rejection or retry result appears, follow that screen.
5. If no result appears, record the register, ticket, amount, time, and visible folio or authorization and escalate.

## [PAY-EVALE] Normal E-vale payment

1. Select **Voucher Card** or **E-vale Card**.
2. When **Slide the card through the terminal** appears, ask the customer to present it.
3. Wait for **Card detected**.
4. The customer enters the PIN on the device; the cashier never requests it.
5. Wait for **Fetching balance** and review the result.
6. Confirm the amount and wait for sale closure.

## [PAY-EVALE-NOT-DETECTED] E-vale card not recognized

If **Error detecting card** appears:

1. Confirm that the correct E-vale workflow is being used.
2. Make another attempt only when the screen offers it and no charge occurred.
3. If it fails again, offer another method with the customer's agreement.
4. Do not clean, open, or adjust the device through an unauthorized action.

## [PAY-EVALE-BALANCE] Insufficient balance or lookup does not finish

- **Insufficient funds:** inform the customer of the visible balance without copying personal data; request another method or complete a mixed payment when allowed.
- **Fetching balance** without a result: do not swipe repeatedly or request the PIN multiple times. Record the time and message and escalate.
- If a charge may exist, do not repeat.

## [PAY-MIXED] Mixed payment

1. Select **Mixed Payment**.
2. Confirm the sale total.
3. Enter the first amount and method.
4. Finish and verify that portion before adding the next.
5. Review the remaining **Amount to cover**.
6. Complete the portions until POS permits **Close Sale**.

If an electronic portion becomes ambiguous, stop the mixed payment. Do not delete or replace the uncertain portion before verification.

## [PAY-SERVICE] Service payment

1. Open **Service Payment**.
2. Scan the receipt or continue to the catalog through the visible control.
3. Select the correct provider.
4. Enter and reconfirm the reference.
5. Confirm the service amount and total to pay.
6. Select **Accept** once.
7. Wait for authorization, folio, and ticket.

If the reference or total does not match, correct it before submitting. After submission, do not repeat because printing failed.

## [PAY-AIRTIME] Airtime

1. Open **Airtime Payment**.
2. Select the correct provider and amount.
3. Enter the phone number and repeat it in confirmation.
4. If **The number does not match** appears, correct it before accepting.
5. Submit once and wait for the result.
6. Retain the reference, authorization, folio, and ticket.

A phone error confirmed before submission must be corrected. After submission, do not repeat automatically.

## [PAY-CANCEL] Cancel a payment in progress

Use **Cancel** only when POS offers it and no approval exists. If the terminal, customer, or POS shows a possible approval, do not cancel or repeat without verification. Cancelling a screen alone does not guarantee that an external transaction was not applied.

## [PAY-AMBIGUOUS-CHECKLIST] Required ambiguous-result checklist

Retain:

- Store and register.
- Approximate exact date and time.
- Total amount and electronic portion.
- Type: debit, credit, CoDi, E-vale, service, or airtime.
- Ticket number if POS assigned one.
- Visible folio or authorization.
- Final message or processing screen.
- Physical terminal receipt without additional sensitive data.
- Whether POS closed the sale or left the cart open.

Do not copy the complete card number, PIN, security code, or customer bank data.

## [PAY-RETRY] When retrying is safe

A retry may be considered only when POS shows a final rejection or clearly instructs **Try again or use another payment method**, no approval receipt exists, no approval folio exists, and the customer does not report a charge.

If any of those confirmations is missing, escalate before retrying.

## [PAY-FAQ] Quick answers

**Can I charge again because no ticket printed?** No. Printing and charging are separate operations.

**Can I remove the card during Processing?** Not when POS says not to remove it.

**Can I create another CoDi?** Not while the first is pending or payment is uncertain.

**What if the customer says they were charged?** Do not repeat. Retain safe evidence and escalate.

**Can I ask for the PIN to test?** Never.

## [PAY-QA] QA pending

- Confirm cancellation and recovery for every method.
- Validate all final messages and visible transitions.
- Confirm the authorized waiting time before escalating pending states.
- Capture approval, rejection, timeout, and ambiguity without real payment data.
- Confirm reprinting after every payment type.

