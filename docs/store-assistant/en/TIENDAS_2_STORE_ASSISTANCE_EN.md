# Tiendas 2.0 Store Assistant — Linux

**Document:** T2.0-STORE-EN  
**Application release:** POS and BOT `v1.3.0`  
**Platform:** Store Linux environment  
**Status:** Draft; requires visual evidence, QA validation, and product-owner approval  
**Audience:** Authorized store personnel

This document contains operational answers for store users. It contains no Linux administration instructions or internal technical details.

## [SCOPE-01] How the assistant must respond

- Answer in English when the question is asked in English.
- If it is unclear whether the question concerns POS or BOT, first ask which application the person is using.
- Use only published and verified instructions for Linux release `v1.3.0`.
- Do not invent technical causes. Describe the visible symptom, safe action, and escalation boundary.
- Never request passwords, PINs, complete card details, security codes, or customer information.
- If guidance is not verified, answer: **“I could not find verified guidance for this situation. Retain the requested information and contact authorized support.”**

## [START-01] Before starting an operation

1. Confirm whether you are using **Point of Sale (POS)** or **Back Office Store (BOT)**.
2. Confirm that the screen displays the expected store and version.
3. Use only your own user account; do not share credentials.
4. Do not close the application while a screen says **Processing**, **Loading**, **Preparing print**, **Validating**, or equivalent.
5. For support, retain the application, store, register or terminal, approximate time, step performed, exact message, and folio or ticket when one exists.

## [AUTH-01] Log in to POS or BOT

**Role:** authorized store user.  
**Starting point:** access screen with **User** and **Password** fields.

1. Enter your user in **User**.
2. Enter your password in **Password** without showing it to other people.
3. Select **Log In** once.
4. Wait while **Logging In ...** is displayed.

**Expected result:** the home screen allowed for your role appears.  
**Safe retry:** correct a typing error and try one more time. Do not keep attempting continuously.  
**Escalate when:** correct credentials remain rejected, the screen does not advance, or a terminal-configuration message appears. Do not change files or Linux settings.  
**QA:** POS and BOT screenshots pending.

## [AUTH-02] User or password rejected

POS may display **Unable to log in. Try again.** BOT may display **Incorrect user or password** or **Invalid user or password. Try again.**

1. Confirm that the user belongs to the person trying to sign in.
2. Re-enter the password once, respecting uppercase and lowercase letters.
3. If it fails again, stop trying and contact authorized support.

Do not ask another person for their password and do not send a password through chat, a photograph, or email.

## [AUTH-03] Sign-in without connectivity

The application may allow offline access only when a valid local authorization already exists for that user.

- Attempt to log in normally once.
- If offline access is accepted, continue only with the functions that the application makes available.
- If offline access is rejected or expired, do not change the computer date, network, or configuration files.
- Retain the time, terminal, and visible message, then contact authorized support.

Do not promise that every operation will work without connectivity.

## [AUTH-04] Password expiring soon or update required

The screen may display **Your password is about to expire** or **Password update required**.

1. Read whether the update is optional or required before continuing.
2. In **New password**, enter a password that meets the displayed minimum length and contains at least one uppercase letter, one lowercase letter, and one number.
3. Enter the same value in **Confirm password**.
4. Select **Update password** once.
5. Wait for **Password updated**, then select **Accept**.

If **Passwords do not match** appears, enter both fields again. If **Unable to update password** appears, make no more than one additional attempt and then contact authorized support. If the password has expired and the application directs you to support, there is no authorized store-level recovery.

## [AUTH-05] Locked session and unlocking

1. On **Session locked**, enter the authorized user and password requested by the screen.
2. Confirm once and wait for the result.
3. If a mandatory password change is requested, complete it before continuing.
4. If you cannot unlock the session, use **Close Session** only when the screen allows it and no operation is processing.

Do not restart Linux or terminate processes to bypass the lock.

## [AUTH-06] Authorization for protected actions

Some actions request the credentials of a responsible person, shift manager, or manager.

- The authorizing person must enter their own credentials.
- If **Authorization failed, try again** appears, confirm that the person has the required role and make one additional attempt.
- If POS says that the user differs from the user signed in to POS, use the user required by the operation.
- Expense settlement may require the user who opened the shift.
- A sales summary may require District Manager authorization.

Do not use borrowed credentials. If the required role is unavailable, retain the operation and contact authorized support.

## [POS-01] POS initialization

After login, POS loads the store's operational data. If **There was a problem loading the store's operational data** appears:

1. Do not start a sale.
2. Select **Retry** once.
3. If it fails again, retain the store, register, time, and message; contact authorized support.

Do not modify configuration files or use Linux commands.

## [POS-02] Sale, search, and quantities

- Scan the product or use the available search.
- Verify description, quantity, and price before taking payment.
- For products without a barcode, use only the visible authorized workflow.
- If **This product is not in the cart** appears, return to the list and select an existing product.
- If the total exceeds the maximum sale amount, adjust the list before continuing.
- Do not continue when the product or price cannot be verified; consult BOT or support according to store procedure.

## [POS-03] Closing a shift with a pending sale

If **Shift closure unavailable** says that the pending sale must be completed or cancelled:

1. Return to the pending sale.
2. Complete payment or cancel the sale using the visible option and required authorization.
3. Return to **Close shift**.

Do not close the application to try to remove the pending sale.

## [POS-04] Open a shift and receive funding

1. Sign in with the user who will operate the register.
2. Open the shift from **Shift & Session**.
3. When authorization appears, the shift manager must enter their own credentials.
4. Verify the **Initial funding** amount before accepting.
5. Wait for confirmation and retain the cash-fund receipt.

If **Action not allowed. You do not have permission to start a shift** appears, do not use another account without authorization. Contact the store supervisor. If the receipt does not print, do not open another shift; use the printing guidance.

## [POS-05] Cash reliefs, withdrawals, and expenses

- For a **Cash relief**, verify amount and destination before **Confirm Cash Relief**.
- For an expense withdrawal, retain the receipt number and complete the names and signatures requested by the document.
- To settle an expense, use the correct pending receipt. If POS displays **Invalid receipt**, **Unable to read the code**, or **No pending receipt found**, do not enter a different movement as a replacement.
- Settlement may require the same user who opened the shift.
- Do not repeat a relief or withdrawal when POS already displayed confirmation or generated a receipt.

## [POS-06] Cancellations and returns

1. Confirm whether you are cancelling one product, the complete sale, or performing a return.
2. Review the product, quantity, ticket, and amount before continuing.
3. Obtain the authorization requested by the screen.
4. Wait for the final result and retain the cancellation or return receipt.

Do not cancel more units than exist in the sale. If the operation remains processing or produces no verifiable result, do not repeat it; retain the ticket, time, amount, and authorization and escalate.

## [PAY-01] General rule for electronic payments

While **Processing payment...** is displayed:

- Do not select the payment method again.
- Do not close POS.
- Do not remove the card when POS displays **Do not remove the card yet.**
- Do not start a second sale for the same charge.

Treat the payment as complete only when POS displays a final result and the sale produces its expected receipt or closure.

## [PAY-02] Santander card payment

1. Select **Debit Card** or **Credit Card**.
2. Follow the visible instructions on POS and the payment terminal.
3. Wait for **Transaction successful** or **Transaction declined**.
4. If approved, confirm that POS closes the sale and produces the expected receipt.

**Ambiguous result:** if the terminal appears to approve but POS does not finish, do not repeat the charge. Retain the ticket, authorization when displayed, amount, time, register, and terminal receipt; contact authorized support.

## [PAY-03] CoDi payment

1. Select **CoDi**.
2. Ask the customer to scan the code displayed under **Scan to pay**.
3. Wait while POS displays **Processing payment...**.
4. Continue only after **Transaction successful** appears.

If **Transaction declined** appears, follow the visible option to try later or use another method. If the customer reports a debit but POS does not confirm it, do not generate another code or repeat the charge; retain the amount, time, register, and visible folio or authorization, then escalate.

## [PAY-04] E-vale card payment

1. Select **Voucher Card** or **E-vale Card**, as displayed.
2. Follow **Slide the card through the terminal**.
3. Wait for **Card detected** and enter the PIN only on the authorized device.
4. Wait for the balance lookup and final result.

If **Error detecting card** or **Insufficient funds** appears, do not force the operation. Use another payment method only with the customer's agreement. Never request or write down the PIN.

## [PAY-05] Cash and mixed payment

- Verify **Amount to cover**, **Amount paid**, and **Change** before closing.
- For **Mixed Payment**, confirm each amount before starting the next portion.
- If an electronic portion is ambiguous, do not replace or repeat it until authorized verification is received.
- Give change only after POS displays **Close Sale** and the corresponding amount.

## [PAY-06] Services and airtime

- Confirm provider, reference, phone number, and total before accepting.
- If confirmation does not match, correct the information before payment.
- After submitting the operation, wait for a final result; do not repeat it when there may already be a charge.
- Retain the reference, authorization, folio, amount, time, and ticket for clarification.

## [PRINT-01] POS does not print a ticket

If **Printer Error** or **Check that the thermal printer is correctly connected** appears:

1. Confirm that the printer has power.
2. Visually check that the accessible cable is connected and paper is loaded correctly.
3. Do not disconnect other equipment or change Linux settings.
4. If the sale already finished, do not charge again. Use **Reprint ticket** only with the correct ticket number and date.
5. If no ticket is found or reprinting fails, contact authorized support.

## [PRINT-02] Reprint a POS ticket

1. Open **Reprint ticket**.
2. Enter **Date (DD/MM/YYYY)** and **Ticket number**.
3. Select **Search**.
4. Confirm **Ticket located** before reprinting.
5. Select **Reprint ticket** once and wait.

If **Ticket not located** appears, verify the date and number once. Do not use a different ticket as a substitute.

## [PRINT-03] Partial, unreadable, or duplicate output

- Do not repeat the payment.
- Retain every copy produced.
- If POS confirms the sale and a ticket number exists, use the reprint workflow once.
- If an operational document requires signatures, do not treat it as valid until it is complete and signed as directed on the document.
- If the second output also fails, stop trying and contact authorized support.

## [PRINT-04] POS documents that may print

Depending on the operation, POS may generate a sale, return, total cancellation, shift opening, cash relief, expense withdrawal, expense settlement, sales summary, shrinkage or transfer list, service, or airtime receipt. Retain the ticket number, folio, authorization, and signatures requested by the document itself.

## [BOT-01] BOT initialization

If BOT displays **There was a problem loading the store's operational data**:

1. Do not start store movements.
2. Select **Retry** once.
3. If it fails again, retain the store, terminal, version, time, and message; contact authorized support.

## [BOT-02] Funding, cash reliefs, and POS requests

- Open the request from the message area or corresponding dashboard.
- Verify POS, shift, responsible user, movement type, and amount.
- For **Initial cash fund** or **Additional cash fund**, confirm once and wait for the successful processing message.
- For a cash relief, verify number, destination, amount, and responsible cashier before completing it.
- If the amount is processed with differences, retain the folio and follow the visible breakdown; do not create a second movement to compensate without authorization.

## [BOT-03] Receive merchandise

1. Open **Receive merchandise**.
2. Select the correct pending reception and confirm origin, invoice, or reference.
3. Review boxes, items, and products before processing.
4. If BOT warns that products are not in the store catalog, understand that they will be omitted; retain which products were affected before confirming.
5. Complete the reception once and retain the folio and generated document.

A pending CEDIS reception may block the efficient order. Do not create a duplicate reception when no result appears; retain the reference and escalate.

## [BOT-04] Incoming and outgoing transfers

1. Confirm whether this is an incoming transfer, a transfer to CEDIS, or a transfer to another store.
2. Verify origin, destination, reason, products, boxes, pieces, or grams.
3. Enter the required comment when displayed.
4. Read any warning about omitted products before confirming.
5. Wait for the folio and print confirmation.

Supplies or returnables may be restricted to CEDIS, and variable-weight products may be excluded according to the workflow. Retain every copy and complete the stamps, names, and signatures requested by the document.

## [BOT-05] Record shrinkage

1. Open **Shrinkage** or **Record Shrinkage**.
2. Select the product, quantity or weight, and visible reason.
3. Review cost and amount before continuing.
4. Obtain the required authorization.
5. Confirm once and wait for the **Shrinkage record** folio.
6. Retain the document and complete the requested stamp, name, and signatures.

For variable-weight shrinkage, use the specific workflow and do not substitute pieces for grams.

## [BOT-06] Record and complete expenses

1. Open **Record expenses**.
2. Select **Expense type** and enter the required comment.
3. Verify withdrawn amount, used amount, and returned difference.
4. Confirm once and retain the folio.

Before ending the shift or day, complete the reason and comment for every pending expense. When there were no expenses, BOT may display **No expenses were recorded during the shift**.

## [BOT-07] Close a shift and close the day

To close a shift:

1. First handle the **Close shift** message for the corresponding POS.
2. Enter the denominations for the final relief and review safe, tombola, shortage, or overage.
3. Select **Finish shift** once.
4. Retain the folio and verify both copies when BOT confirms that two copies printed successfully.

To close the day:

1. Open **Day closure**.
2. Record every expense for the day before confirming.
3. Resolve each visible blocker: open POS shifts, pending price printing, or an unprocessed efficient order.
4. Confirm once and retain the day-closure folio and receipt.

Do not close BOT or repeat closure while it is processing.

## [SYNC-01] POS and BOT show different information

1. Confirm that both computers belong to the same store.
2. In BOT, review the POS **Last connection** when available.
3. Do not repeat requests, reliefs, closures, receptions, or adjustments while a screen indicates processing.
4. Use **Revalidate** only when the inventory workflow offers it.
5. If the information remains different, retain folios, times, and screens from both systems; escalate.

Do not edit databases or local files.

## [CATALOG-01] Products, catalog, and prices

Catalog updates arrive automatically in BOT. Store personnel do not upload product files.

- If a product or price is missing, wait for initialization to finish and search again.
- Review price-change notices and **Price printing**.
- Do not create or modify catalog files.
- If POS and BOT continue to show different data, retain the barcode, product key, observed price, time, and screens; contact authorized support.

## [LABEL-01] Print price changes and labels

1. Open **Price printing**.
2. Select the visible format: large shelf label, small shelf label, or signage, as applicable.
3. Review products, current price, new price, and configuration.
4. Use **Preview** before printing.
5. When BOT requests a paper color, load the indicated paper and select **Print** once.
6. Wait for **Document sent to print** before continuing with the next group.

If **Unable to process printing** appears, do not mark the work complete. Perform one safe physical printer check and retry only when BOT allows it.

## [ZEBRA-01] Download the inventory layout to the scanner

1. Connect the authorized Zebra scanner.
2. In BOT, open **Inventory** and select the inventory type.
3. Select **Download** once.
4. Wait for **File download** and the number of products downloaded.

If the message says that the device, file, tool, or permission was not found, do not use Linux commands. Physically reconnect the device once and repeat from BOT. If it fails again, retain the exact message and escalate.

## [ZEBRA-02] Import Sales Floor and Warehouse counts

1. Perform the floor and warehouse counts on the scanner.
2. Do not edit or rename the generated files.
3. Connect the scanner and open **Import file**.
4. Import the **Sales Floor** file (`_1.txt`) and **Warehouse** file (`_0.txt`) through BOT.
5. Verify the number of loaded items and that both statuses show as imported.
6. If BOT displays **Replace file**, confirm only when you are certain that the previously imported count should be replaced.

If **No files found to import** appears, do not create files manually. Confirm that the scanner generated the count and escalate if the problem persists.

## [ZEBRA-03] Comparison, recount, and adjustment

1. After both files are imported, continue to validation.
2. Wait while BOT validates the POS connection and compares sales recorded during the count.
3. Do not close BOT or repeat the import during comparison.
4. If differences exist, select the indicated items for recount.
5. Repeat the physical count and complete the adjustment only with the required authorization.
6. Retain the adjustment folio and generated report.

## [REPL-01] Efficient order available

1. Find **Efficient order available** in BOT's incoming-message area.
2. Open the message.
3. If BOT blocks the process because CEDIS receptions are pending, complete those receptions first.
4. Review Fresh Produce and Meat, Normal Order, and Supplies as displayed.
5. Use search and the **All** or **Priority only** filters.
6. Review suggested quantity, stock, and final order; modify only authorized quantities.
7. Select **Confirm order** once.
8. Wait for confirmation, retain the folio, and complete the requested printing.

Do not close the day while BOT displays an efficient order as a blocker.

## [REPORT-01] BOT reports and PDFs

BOT may generate documents for receptions, transfers, shrinkage, inventory, efficient orders, shift closure, and day closure.

- Review the document or preview before printing.
- During **Preparing print** or **Searching for an available printer**, wait without repeating.
- **Print sent** means that the document was sent; physically confirm the output.
- **Print error** or **Unable to process printing** requires a safe physical check and, if it continues, support.
- Retain the folio and do not repeat the business movement to obtain another printout.

BOT confirms that shift closure prints two copies when it displays the corresponding message.

## [TOOLS-01] BOT integrated tools

1. Open **Operational tools** and select only an approved tool.
2. Wait for **Initializing Content ...** and **Loading Content ...**.
3. If the page remains blank, return to BOT with the visible control; do not refresh repeatedly.
4. If **Web content restart required** or **There was an error initializing web content** appears, preserve current work and contact authorized support.

Do not use commands, clear caches, or change addresses or configuration.

## [NAV-01] Tables, search, dialogs, and keyboard

- Use **Search** with product key, barcode, or description according to the visible field.
- In multi-page tables, use **Previous**, **Next**, or **Go to page**.
- Before accepting a replace, cancellation, closure, or adjustment dialog, read what information will be replaced or finalized.
- Use **F1**, **Enter**, or **Esc** only when the screen displays that key as a shortcut.
- If focus is not in the correct field, select it with the mouse or visible navigation before typing.

## [LINUX-01] Safe POS or BOT application restart

Restarting the application is the last store-level action, not the first response.

Do not restart while a payment, print, import, comparison, reception, transfer, order, adjustment, or closure is processing. If the screen is unresponsive and no result can be verified, retain the time and folio and contact support before restarting. Never restart Linux, services, or processes using commands as part of this guide.

## [ESC-01] Information for authorized support

Retain only safe operational information:

- POS or BOT.
- Store and register or terminal.
- Visible application version.
- Approximate date and time.
- Screen and step performed.
- Exact visible message.
- Folio, ticket, or authorization when one exists.
- Visible status of POS, BOT, payment terminal, printer, or Zebra.
- Sanitized photograph or screenshot without customer, credential, or payment data.

Never share passwords, PINs, tokens, complete card numbers, security codes, or customer personal information.

## [FAQ-01] Frequently asked questions

**Where do I upload the product catalog?**  
You do not upload it manually. BOT receives catalog updates automatically.

**The payment terminal approved, but POS is still processing. Should I charge again?**  
No. Retain the visible evidence and contact authorized support before repeating the payment.

**Can I rename the Zebra files?**  
No. Import the generated files without editing or renaming them.

**Which file is for the floor and which is for the warehouse?**  
The Sales Floor file ends in `_1.txt`; the Warehouse file ends in `_0.txt`.

**BOT says the document was sent, but no paper came out.**  
Do not repeat the business operation. Check power, the accessible connection, and paper; then use the authorized print or reprint option.

**Can I use Linux commands to fix POS, BOT, the printer, or Zebra?**  
No. Contact authorized support.

**Can the assistant explain events, configuration, or source code?**  
No. This assistant covers only visible Linux store operations.

## [QA-01] Required before publication

- Validate every procedure in Linux QA with seeded data.
- Confirm roles and permissions for every action.
- Confirm when printing is automatic or manual and how many copies it produces.
- Confirm the actual visible printer and device states.
- Confirm authentication and payment retry boundaries.
- Add sanitized Spanish screenshots and equivalent English evidence.
- Record the verification date and product-owner approval.
