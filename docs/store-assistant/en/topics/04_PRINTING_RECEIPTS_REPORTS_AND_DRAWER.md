# Linux POS and BOT — printing, receipts, reports, and cash drawer

**Page ID:** T2STORE-PRINT-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-PRINT-ES`

## [PRINT-SCOPE] Scope and safety

This page covers only visible printing controls and messages. It contains no printer configuration, drivers, services, device paths, Bluetooth setup, system permissions, or Linux commands.

A printing failure does not mean the business operation failed. Before repeating anything, confirm whether a ticket, folio, authorization, or success message already exists.

## [PRINT-ASK-FIRST] Questions the assistant must ask

1. Was printing started from POS or BOT?
2. Which document was expected?
3. Did the operation already show success, a ticket, or a folio?
4. Which printer message is displayed?
5. Was the output complete, partial, blank, or absent?
6. Are one or several copies required?

## [PRINT-PHYSICAL-CHECK] Permitted physical check

A store user may:

- Confirm that the printer has power.
- Check that an accessible cable is not loose.
- Confirm that paper is present and loaded according to the approved physical guide.
- Check for a visible jam without dismantling the equipment.
- Retain every sheet produced.

The user must not open technical covers, change ports, install drivers, edit configuration, execute commands, or disconnect equipment during active printing.

## [PRINT-POS-ERROR] POS displays “Printer Error”

**Related message:** **Check that the thermal printer is correctly connected.**

1. Determine whether the sale or movement already finished.
2. If a ticket or folio exists, do not repeat the movement.
3. Perform the permitted physical check.
4. If a reprint flow exists for the document, use it once.
5. If the error continues, stop trying and escalate.

Do not claim that POS can diagnose paper, cover, or exact connection type unless the screen explicitly says so.

## [PRINT-BOT-STATES] Visible BOT printing states

- **Printer idle:** no active print.
- **Preparing print:** BOT is creating or preparing the document; do not repeat.
- **Searching for an available printer...:** wait; do not change selection or close BOT.
- **Print sent** or **Document sent to print:** physically confirm that output appears.
- **Print error** or **Unable to process printing...:** first verify whether the movement already has a folio, then perform the permitted physical check.

“Sent” alone does not guarantee that paper came out completely.

## [PRINT-REPRINT-SALE] Reprint a POS sales ticket

**Starting point:** **Reprint ticket**.  
**Fields:** **Date (DD/MM/YYYY)** and **Ticket number**.

1. Obtain the original ticket date and number.
2. Enter both values.
3. Select **Search**.
4. Confirm **Ticket located**.
5. Check store, register, date, and amount when displayed.
6. Select **Reprint ticket** once.
7. Wait for the result and retain the copy marked as a reprint.

If **Ticket not located** appears, check the date and number once. Do not try consecutive numbers or use another ticket.

## [PRINT-NO-PAPER-AFTER-SALE] Sale complete with no paper

1. Do not charge again.
2. Confirm that POS closed the sale and assigned a ticket.
3. For card, CoDi, or E-vale, retain the available receipt or folio.
4. Physically check the printer.
5. Reprint with the correct ticket.
6. If it cannot be located, escalate; do not reconstruct the receipt manually.

## [PRINT-PARTIAL] Partial or unreadable document

1. Retain the incomplete document.
2. Check whether it includes a ticket or folio.
3. Do not repeat the sale, return, relief, transfer, shrinkage, reception, order, or closure.
4. Use the document's print or reprint flow only when one exists.
5. If the second output is also partial, stop attempting.

For documents requiring signatures or stamps, use a complete copy; do not handwrite information that the system should have printed.

## [PRINT-DUPLICATE] Duplicate copies printed

- Do not repeat the operation.
- Compare ticket, folio, date, time, and amount.
- Retain every copy and mark or manage them according to official store procedure.
- If identifiers differ, treat the case as possible duplicate operations and escalate immediately.

## [PRINT-BLANK] Blank paper printed

1. Retain the sheet as evidence.
2. Do not repeat the business operation.
3. Perform only the approved physical paper check.
4. Reprint once when the document and folio are confirmed.
5. If another blank sheet prints, escalate.

Do not change paper type, configuration, or equipment without authorized instruction.

## [PRINT-SALES-RECEIPT] Sales receipt

It may include store, register, seller, ticket number, products, quantities, prices, tax, cash, other payments, change, and service or payment information.

Before giving it to the customer, confirm that it belongs to the current sale and is readable. For electronic payments, retain customer or merchant copies as directed by the document itself.

## [PRINT-RETURN-CANCEL] Return and total cancellation

- A return generates a document identified as **RETURN**.
- A complete cancellation may generate **TOTAL CANCELLATION**.
- Missing printing does not authorize repeating the return or cancellation.
- Retain the authorizer, original ticket, amount, and time.

## [PRINT-FUNDING] Cash fund

The **CASH FUND** document records the amount and spaces for recipient and issuer signatures. If the shift is already open, do not repeat opening because paper is missing. Recover printing through an authorized flow or escalate.

## [PRINT-RELIEF] Cash-relief receipt

It may show the type, amount, operator, and authorization signature. Confirm that its number and destination match the movement. Do not repeat a confirmed relief to obtain another sheet.

## [PRINT-EXPENSE] Expense withdrawal and settlement

- **EXPENSE WITHDRAWAL** includes a receipt number, amount, and required signatures.
- Settlement may include the used amount and returned difference.
- The printed text determines which names, signatures, or validations are required.
- Do not manually alter the receipt code.

## [PRINT-SALES-SUMMARY] Sales summary

The **SALES SUMMARY** document may show funding, sales, cash, E-vale, cards/CoDi, reliefs, returns, cash in drawer, and receipts to verify. It may require District Manager authorization. Escalate a difference; do not correct it with new movements without authorization.

## [PRINT-POS-LISTS] POS shrinkage or transfer lists

POS may print product lists for shrinkage or transfer, including quantities. These lists support coordination with BOT; they do not prove that BOT completed the movement. Retain the list until a final folio exists.

## [PRINT-SERVICE-AIRTIME] Services and airtime

The ticket may include a reference, authorization, and folio. If the operation succeeded but did not print, do not repeat the service or recharge. Retain the visible result and use authorized recovery.

## [PRINT-CODI-CARD] Electronic-payment receipts

They may include a ticket, authorization, folio, operator, or masked card information. Never copy or share complete payment data. If the terminal and POS show different results, use the ambiguous-payment procedure before reprinting.

## [PRINT-BOT-PRICE] BOT labels and price changes

1. Open **Price printing**.
2. Review filters, products, current price, new price, and type.
3. Select large label, small label, or signage as displayed.
4. Use **Preview**.
5. If BOT separates blue, yellow, and white paper, load the requested color.
6. Select **Print** once for each group.
7. Wait for **Document sent to print**.
8. Compare a printed sample with the preview before selecting **Finish**.

Do not mark printing complete when pages or products are missing.

## [PRINT-BOT-TRANSFER] BOT transfers

- A merchandise transfer may confirm three copies.
- A product transfer may confirm two copies.
- Always confirm the actual message displayed by the operation.
- Review folio, origin, destination, products, quantities, and comment.
- Complete the original stamps, names, and signatures required by the document.

Do not repeat a transfer because one copy is missing.

## [PRINT-BOT-SHRINKAGE] BOT shrinkage

The report records the folio, authorization, products, pieces or grams, and amounts. It may require the Shift Manager and District Manager stamp, name, and signatures. If a folio exists, do not record shrinkage again because printing failed.

## [PRINT-BOT-INVENTORY] BOT inventory

Retain the comparison, recount, and adjustment report with its folio. Printing does not replace visible confirmation that the adjustment finished. If the PDF or print fails after a folio exists, do not repeat the adjustment.

## [PRINT-BOT-ORDER] Efficient order

BOT may generate lists for Supplies, Normal Order, and Fresh Produce and Meat, plus the summary and sent order. Review items, boxes, stock, and final order. Modified items may be identified in the document. Do not confirm an additional order because the PDF is missing.

## [PRINT-BOT-CLOSE] Shift and day closure

- Shift closure may confirm two copies.
- Day closure generates a cover and may include sales, reliefs, expenses, cash delivery, shrinkage, and transfers.
- Retain the folio and every page.
- Do not repeat closure when a folio exists even if one copy fails.

## [PRINT-CASH-DRAWER] Cash drawer connected to printer

When POS requests opening the drawer, the responsible cashier must authorize it. If it does not open:

1. Confirm printer power.
2. Check the accessible connection without moving other equipment.
3. Do not force the drawer.
4. Do not repeat the command several times.
5. Escalate with store, register, time, and message.

## [PRINT-ESCALATE] Evidence for support

Retain: POS or BOT, store, register or terminal, version, expected document, operation, ticket or folio, time, print message, observed physical state, number of expected and produced sheets, and every copy. Redact customer and payment data.

## [PRINT-FAQ] Quick answers

**No ticket printed. Should I repeat the sale?** No.

**BOT says “Print sent.” Is it complete?** Confirm that all paper output appeared.

**Can I reprint with another number?** No.

**Can I restart the print service?** Not as a store-user action.

**What if half a page printed?** Retain it, confirm the folio, and use one authorized reprint.

## [PRINT-QA] QA pending

- Confirm every document and copy count.
- Validate differences between the POS thermal printer and BOT document printer.
- Confirm which physical errors the interface actually detects.
- Verify available reprinting by document type.
- Capture Linux states with sanitized information.

