# Canonical question index — Tiendas 2.0 Linux

**Page ID:** T2STORE-QUESTIONS-EN  
**Version:** `v1.3.0`  
**Status:** Detailed draft; QA pending  
**Sibling page:** `T2STORE-QUESTIONS-ES`

## [QUESTION-PURPOSE] Purpose

This index helps the assistant recognize different ways of asking the same question and route the answer to the correct operational section. It does not replace the linked procedure. Before answering, the assistant must read the entire target section and follow its retry and escalation boundaries.

## [QUESTION-ROUTING-RULES] Selection rules

1. Answer in the language used by the question.
2. Distinguish POS from BOT; if unclear, ask which application the person is using.
3. Prioritize the current visible state over the original intent.
4. If a payment, folio, receipt, or ambiguous movement exists, apply the do-not-repeat rule first.
5. If several sections apply, begin with the one that prevents loss, duplication, or a double charge.
6. Cite the exact page and section identifier used.
7. Do not fill gaps with technical or general knowledge.

## [QUESTION-AUTH] Access, user, and password

Equivalent questions:

- “I can't sign in.”
- “My user account doesn't work.”
- “It says invalid credentials.”
- “The password is wrong.”
- “It is stuck signing in.”
- “Can I sign in without internet?”
- “My offline authorization expired.”
- “It asks me to change my password.”
- “I forgot my password.”
- “The session is locked.”
- “How do I unlock it?”

Routes:

- Normal sign-in: `T2STORE-AUTH`, `[AUTH-LOGIN-NORMAL]`.
- Rejection and retry limit: `[AUTH-INVALID]`.
- Offline or expired authorization: `[AUTH-OFFLINE]`.
- Password: `[AUTH-PASSWORD-WARNING]`, `[AUTH-PASSWORD-REQUIRED]`, `[AUTH-PASSWORD-FAILED]`.
- Locking: `[AUTH-SESSION-LOCK]`, `[AUTH-SESSION-UNLOCK]`.
- Processing: `[AUTH-PROCESSING]`.

## [QUESTION-PERMISSION] Permissions and authorization

Equivalent questions:

- “It won't let me do it.”
- “The button is disabled.”
- “The option is missing.”
- “It asks for a supervisor.”
- “Who can authorize?”
- “Authorization was rejected.”
- “Can I use another user account?”

Routes:

- Principle and roles: `T2STORE-ROLES`, `[ROLE-PRINCIPLE]`, `[ROLE-STORE-USER]`, `[ROLE-AUTHORIZER]`.
- Rejection or absence: `[ROLE-PERMISSION-DENIED]`, `[ROLE-MISSING-MENU]`, `[ROLE-BUTTON-DISABLED]`.
- Authorization: `[ROLE-AUTHORIZATION-WAITING]`, `[ROLE-AUTHORIZATION-FAILED]`, `[ROLE-AUTHORIZATION-SUCCEEDED]`.

## [QUESTION-POS-START] POS, initialization, and shift

Equivalent questions:

- “POS won't start.”
- “POS is stuck loading.”
- “How do I open the shift?”
- “I didn't receive funding.”
- “The funding receipt didn't print.”
- “It looks like a shift is already open.”
- “How do I add more funding?”

Routes:

- Startup: `T2STORE-POSOPS`, `[POSOPS-START]`.
- Open shift: `[POSOPS-OPEN-SHIFT]`.
- Additional funding: `[POSOPS-ADDITIONAL-FUNDING]`.
- Funding printing: `T2STORE-PRINT`, `[PRINT-FUNDING]`.
- Shift duplication: `T2STORE-ROLES`, `[ROLE-SHIFT-OWNERSHIP]`.

## [QUESTION-SALE] Products, quantities, and sale

Equivalent questions:

- “It won't scan the code.”
- “It can't find the product.”
- “How do I search by description?”
- “I entered the wrong quantity.”
- “How do I multiply items?”
- “I want to check the price.”
- “The sale was left pending.”
- “It won't let me finish the sale.”

Routes:

- Add or search: `T2STORE-POSOPS`, `[POSOPS-ADD-PRODUCT]`.
- Quantity: `[POSOPS-QUANTITY]`.
- Price check: `[POSOPS-PRICE-CHECK]`.
- Pending sale: `[POSOPS-PENDING-SALE]`.
- Missing product: `T2STORE-TOOLS`, `[PRODUCT-MISSING]`.

## [QUESTION-CANCEL-RETURN] Cancellations and returns

Equivalent questions:

- “I want to remove a product.”
- “Cancel the entire sale.”
- “The customer wants to return it.”
- “The return didn't print.”
- “It closed after canceling.”
- “It asks for authorization to return.”

Routes:

- Product: `T2STORE-POSOPS`, `[POSOPS-CANCEL-PRODUCT]`.
- Entire sale: `[POSOPS-CANCEL-SALE]`.
- Return: `[POSOPS-RETURN]`.
- Document: `T2STORE-PRINT`, `[PRINT-RETURN-CANCEL]`.
- Permission: `T2STORE-ROLES`, `[ROLE-PROTECTED-ACTIONS]`.

## [QUESTION-PAYMENT-GENERAL] Payment processing or unknown result

Equivalent questions:

- “The payment is stuck processing.”
- “I don't know whether it charged.”
- “The customer says money was deducted.”
- “POS returned without a result.”
- “The internet went down while charging.”
- “Should I try again?”
- “A voucher printed but POS did not finish.”

Priority route: `T2STORE-PAY`, `[PAY-SCOPE]`, `[PAY-PROCESSING]`, `[PAY-AMBIGUOUS-CHECKLIST]`, `[PAY-RETRY]`.

Immediate response: do not repeat the payment; retain method, amount, time, terminal, screen, and permitted proof; verify through the approved flow or escalate.

## [QUESTION-CASH] Cash and mixed payment

Equivalent questions:

- “How do I charge cash?”
- “I entered the received amount incorrectly.”
- “It doesn't show the change.”
- “The drawer didn't open after charging.”
- “Can I combine payments?”
- “One part passed and another did not.”

Routes:

- Cash: `T2STORE-PAY`, `[PAY-CASH]`.
- Mixed: `[PAY-MIXED]`.
- Drawer: `T2STORE-PRINT`, `[PRINT-CASH-DRAWER]`.
- Partial result: `[PAY-AMBIGUOUS-CHECKLIST]`.

## [QUESTION-CARD] Card and Santander

Equivalent questions:

- “The terminal is unavailable.”
- “It does not detect the card.”
- “The card was declined.”
- “The terminal approved but POS did not.”
- “It says not to remove the card.”
- “The terminal connection failed.”
- “How do I cancel the card payment?”
- “How do I reconcile the charge?”

Routes: `T2STORE-PAY`, `[PAY-CARD]`, `[PAY-PROCESSING]`, `[PAY-CARD-DECLINED]`, `[PAY-CARD-APPROVED-POS-PENDING]`, `[PAY-CANCEL]`, `[PAY-AMBIGUOUS-CHECKLIST]`.

## [QUESTION-CODI] CoDi

Equivalent questions:

- “The QR doesn't appear.”
- “The QR doesn't work.”
- “The customer already paid.”
- “CoDi is still waiting.”
- “CoDi expired.”
- “CoDi was rejected.”
- “I canceled the QR.”
- “Should I generate another code?”

Routes: `T2STORE-PAY`, `[PAY-CODI]`, `[PAY-PROCESSING]`, `[PAY-CODI-DECLINED]`, `[PAY-CODI-TIMEOUT]`, `[PAY-CANCEL]`.

If the customer shows a charge or acceptance, do not generate another QR.

## [QUESTION-VOUCHER] E-vale or voucher

Equivalent questions:

- “It doesn't detect the voucher card.”
- “How do I check the balance?”
- “The balance is insufficient.”
- “The voucher was rejected.”
- “The provider failed.”
- “The device doesn't respond.”
- “Can I swipe it again?”

Routes: `T2STORE-PAY`, `[PAY-EVALE]`, `[PAY-EVALE-NOT-DETECTED]`, `[PAY-EVALE-BALANCE]`, `[PAY-RETRY]`.

## [QUESTION-SERVICES] Services and airtime

Equivalent questions:

- “The service payment wasn't applied.”
- “The top-up did not arrive.”
- “I entered the wrong number.”
- “The airtime receipt didn't print.”
- “The provider didn't respond.”
- “Should I sell the top-up again?”

Routes: `T2STORE-PAY`, `[PAY-SERVICE]`, `[PAY-AIRTIME]`, `[PAY-AMBIGUOUS-CHECKLIST]`; printing in `T2STORE-PRINT`, `[PRINT-SERVICE-AIRTIME]`.

Do not repeat a top-up or service with an ambiguous result.

## [QUESTION-PRINT] Printer, receipt, and drawer

Equivalent questions:

- “It doesn't print.”
- “It says printer error.”
- “It printed blank.”
- “It printed only part.”
- “It printed twice.”
- “How do I reprint?”
- “BOT says printing sent but nothing came out.”
- “The drawer won't open.”

Routes: `T2STORE-PRINT`, `[PRINT-PHYSICAL-CHECK]`, `[PRINT-POS-ERROR]`, `[PRINT-BOT-STATES]`, `[PRINT-REPRINT-SALE]`, `[PRINT-PARTIAL]`, `[PRINT-DUPLICATE]`, `[PRINT-BLANK]`, `[PRINT-CASH-DRAWER]`.

First confirm the movement; never repeat a sale, payment, or movement only to obtain paper.

## [QUESTION-BOT-DAY] BOT, dashboard, and store day

Equivalent questions:

- “BOT doesn't finish starting.”
- “How do I start the day?”
- “It says a day already exists.”
- “I don't see a POS request.”
- “The dashboard doesn't update.”
- “I can't close the day.”
- “Which pending items block closure?”

Routes: `T2STORE-BOTOPS`, `[BOTOPS-START]`, `[BOTOPS-START-DAY]`, `[BOTOPS-DASHBOARD]`, `[BOTOPS-POS-REQUEST]`, `[BOTOPS-END-DAY-BLOCKERS]`, `[BOTOPS-END-DAY]`.

## [QUESTION-CASH-OPS] Cash, reliefs, and expenses

Equivalent questions:

- “POS requested funding.”
- “How do I authorize a relief?”
- “The relief doesn't appear.”
- “How do I record an expense?”
- “How do I settle the expense?”
- “How do I deliver values?”
- “The movement folio was lost.”

Routes:

- POS: `T2STORE-POSOPS`, `[POSOPS-ADDITIONAL-FUNDING]`, `[POSOPS-CASH-RELIEF]`, `[POSOPS-EXPENSE-WITHDRAWAL]`, `[POSOPS-EXPENSE-SETTLEMENT]`.
- BOT: `T2STORE-BOTOPS`, `[BOTOPS-INITIAL-FUND]`, `[BOTOPS-ADDITIONAL-FUND]`, `[BOTOPS-RELIEF]`, `[BOTOPS-EXPENSE]`, `[BOTOPS-CASH-DELIVERY]`.
- Printing: `T2STORE-PRINT`, `[PRINT-FUNDING]`, `[PRINT-RELIEF]`, `[PRINT-EXPENSE]`.

## [QUESTION-MERCHANDISE] Reception, transfers, and shrinkage

Equivalent questions:

- “Where do I receive merchandise?”
- “The quantities do not match.”
- “I confirmed reception and it didn't print.”
- “How do I transfer to another store?”
- “The incoming transfer doesn't appear.”
- “How do I record shrinkage?”
- “The movement was left pending.”

Routes: `T2STORE-BOTOPS`, `[BOTOPS-RECEIVE-SELECT]`, `[BOTOPS-RECEIVE-COUNT]`, `[BOTOPS-TRANSFER-OUT]`, `[BOTOPS-TRANSFER-IN]`, `[BOTOPS-SHRINKAGE]`; documents in `T2STORE-PRINT`.

## [QUESTION-CATALOG] Catalog, product, price, and label

Equivalent questions:

- “Where do I upload the catalog?”
- “How do I update products?”
- “A new product arrived and is missing.”
- “The POS price doesn't match.”
- “There are pending price changes.”
- “How do I choose format or color?”
- “The label didn't print.”
- “The price change blocks closure.”

Routes: `T2STORE-TOOLS`, `[PRODUCT-CATALOG-AUTO]`, `[PRODUCT-MISSING]`, `[PRODUCT-PRICE-DIFFERENCE]`, `[PRICE-NOTIFICATION]`, `[PRICE-FORMAT]`, `[PRICE-PREVIEW]`, `[PRICE-PAPER-COLOR]`, `[PRICE-END-DAY]`.

Key answer: store users do not upload catalogs; BOT automatically processes received updates.

## [QUESTION-INVENTORY] Inventory and Zebra

Equivalent questions:

- “BOT doesn't detect the Zebra.”
- “How do I download products to the scanner?”
- “Where do I count floor and warehouse?”
- “It can't find the files.”
- “Which file is the floor file?”
- “Can I rename the file?”
- “Should I replace the imported data?”
- “It doesn't synchronize with POS.”
- “There are differences in the comparison.”
- “How do I recount or adjust?”

Routes: `T2STORE-INVORDER`, `[INV-CONNECT-ZEBRA]`, `[INV-DOWNLOAD]`, `[INV-ZEBRA-ERRORS]`, `[INV-COUNT-FLOOR]`, `[INV-COUNT-WAREHOUSE]`, `[INV-IMPORT-FLOOR]`, `[INV-IMPORT-WAREHOUSE]`, `[INV-NO-FILES]`, `[INV-REPLACE]`, `[INV-SYNC]`, `[INV-COMPARISON]`, `[INV-RECOUNT]`, `[INV-ADJUSTMENT]`.

Never instruct file editing, renaming, or manual manipulation.

## [QUESTION-ORDER] Efficient order and replenishment

Equivalent questions:

- “Where do I see replenishment?”
- “It says Efficient order available.”
- “It won't let me open the order.”
- “I have a pending CEDIS reception.”
- “How do I filter by priority?”
- “What is suggested quantity?”
- “Where do I enter stock?”
- “How do I confirm the order?”
- “I did not get a folio.”
- “The order blocks closure.”

Routes: `T2STORE-INVORDER`, `[ORDER-NOTIFICATION]`, `[ORDER-BLOCKED]`, `[ORDER-CATEGORIES]`, `[ORDER-STOCK]`, `[ORDER-QUANTITIES]`, `[ORDER-PRINT-LIST]`, `[ORDER-CONFIRM]`, `[ORDER-END-DAY]`.

## [QUESTION-REPORTS-TOOLS] Reports, PDF, and embedded tools

Equivalent questions:

- “The report doesn't open.”
- “The PDF is blank.”
- “Pages are missing.”
- “The report doesn't print.”
- “The BOT tool stays loading.”
- “I see a blank page.”
- “The tool session expired.”
- “How do I return to BOT?”

Routes: `T2STORE-TOOLS`, `[PDF-GENERATION]`, `[PDF-FAILURE]`, `[TOOLS-OPEN]`, `[TOOLS-BLANK]`, `[TOOLS-INIT-ERROR]`, `[TOOLS-EXTERNAL-SESSION]`.

## [QUESTION-NAVIGATION] Search, tables, dialogs, and keyboard

Equivalent questions:

- “Search finds nothing.”
- “The table is empty.”
- “How do I change pages?”
- “I can't select the row.”
- “I closed a dialog accidentally.”
- “What do Back or Cancel do?”
- “The keyboard doesn't respond.”
- “What are the shortcuts?”

Routes: `T2STORE-TOOLS`, `[TABLE-SEARCH]`, `[TABLE-EMPTY]`, `[TABLE-PAGINATION]`, `[DIALOG-CONFIRM]`, `[KEYBOARD]`.

Do not invent shortcuts not confirmed on the released screen.

## [QUESTION-OFFLINE-SYNC] Offline, local work, and synchronization

Equivalent questions:

- “The internet went down.”
- “Can I keep working?”
- “Was my work saved?”
- “Information is missing at startup.”
- “POS and BOT do not match.”
- “The movement does not arrive.”
- “Should I restart to synchronize?”

Routes: `T2STORE-AUTH`, `[AUTH-OFFLINE]`; master document `T2.0-STORE`, `[SYNC-01]`; and `T2STORE-TOOLS`, `[TOOLS-INIT-ERROR]`, `[LINUX-RESTART]`.

Do not claim an operation was saved without visible confirmation.

## [QUESTION-CLOSURE] Shift closure and day closure

Equivalent questions:

- “I can't close the shift.”
- “There is a pending sale.”
- “BOT is still waiting for POS.”
- “I can't close the day.”
- “The order or prices are blocking it.”
- “I closed it but it didn't print.”

Routes:

- POS: `T2STORE-POSOPS`, `[POSOPS-CLOSE-SHIFT]`.
- BOT: `T2STORE-BOTOPS`, `[BOTOPS-SHIFT-CLOSE-REQUEST]`, `[BOTOPS-END-DAY-BLOCKERS]`, `[BOTOPS-END-DAY]`.
- Documents: `T2STORE-PRINT`, `[PRINT-BOT-CLOSE]`.

Do not force closure or bypass blockers.

## [QUESTION-FROZEN] Unresponsive application and Linux restart

Equivalent questions:

- “POS froze.”
- “BOT doesn't respond.”
- “The screen is blank.”
- “Can I close the application?”
- “Can I restart the computer?”
- “Give me a Linux command.”

Routes: `T2STORE-TOOLS`, `[LINUX-BOUNDARY]`, `[LINUX-RESTART]`; for a payment, first use `T2STORE-PAY`, `[PAY-AMBIGUOUS-CHECKLIST]`.

Do not provide commands. Before closing, confirm that no payment, printing, import, confirmation, or closure is processing.

## [QUESTION-ESCALATION] When and how to escalate

Equivalent questions:

- “None of this works.”
- “What information should I send support?”
- “There is no guide for my message.”
- “The operation is in an unknown state.”
- “Can I send you a screenshot?”

Routes: `T2STORE-SUPPORT`, `[SUPPORT-SEVERITY]`, `[SUPPORT-HANDOFF]`, `[SUPPORT-SCREENSHOT]`, `[SUPPORT-NO-EVIDENCE]`.

Escalation must contain only sanitized operational information and never passwords, PINs, full card details, customer data, secrets, or technical files.

## [QUESTION-OUT-OF-SCOPE] Unrelated or technical questions

Equivalent questions:

- “How do I change configuration?”
- “Show me events, code, or logs.”
- “How do I access the database?”
- “How do I install or deploy?”
- “Give me the password or a token.”
- “Help me with Windows, Android, or macOS.”
- Any general question unrelated to store operation.

Route: `T2STORE-SUPPORT`, `[SUPPORT-OFF-TOPIC]`, `[SUPPORT-NO-EVIDENCE]`.

Redirect to Tiendas 2.0 Linux access, sales, payments, printing, merchandise, inventory, orders, cash, or closure.

## [QUESTION-QA] Index validation

Before publication:

- Test each Spanish variant and its English equivalent.
- Confirm retrieval reaches the indicated section and not technical evidence.
- Add real variants observed in support without personal data.
- Verify short questions, common misspellings, and exact screen messages.
- Confirm ambiguous payments always produce a do-not-repeat warning.
- Confirm out-of-scope questions do not receive general knowledge.
