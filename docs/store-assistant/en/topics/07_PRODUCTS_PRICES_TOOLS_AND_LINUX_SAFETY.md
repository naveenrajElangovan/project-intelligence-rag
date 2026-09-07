# Linux BOT — products, prices, tools, and safe operation

**Page ID:** T2STORE-BOT-TOOLS-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-BOT-TOOLS-ES`

## [TOOLS-SCOPE] Scope

This page covers product search, automatic catalog updates, price changes, label configuration and printing, tables, navigation, integrated tools, PDF documents, and safe Linux operating boundaries.

## [PRODUCT-CATALOG-AUTO] How products update

BOT automatically receives and processes product and price information during initialization and when updates become available.

- Store users do not upload a catalog.
- There is no authorized procedure to create, replace, or edit product files.
- An update may include new products, changes, deletions, or new prices.
- Wait for initialization to finish before deciding information is missing.

## [PRODUCT-MISSING] Product not found

1. Confirm that you are in the correct store.
2. Wait for BOT loading to finish.
3. Search by product key, barcode, and description when those fields are available.
4. Review active filters and change to **All** when appropriate.
5. Check whether the product appears in POS.
6. If it remains missing, retain key, code, description, time, and both screens and escalate.

Do not select a similar product or try to create it manually.

## [PRODUCT-PRICE-DIFFERENCE] Price differs between POS, BOT, and label

1. Identify the exact product by key and barcode.
2. Record the price displayed by POS.
3. Record **Current price** and **New price** in BOT when displayed.
4. Check for pending work under **Price printing**.
5. Do not manually change the price or finish printing that was not performed.
6. Escalate if the difference continues after the authorized workflow.

## [PRICE-NOTIFICATION] Products requiring a price update

BOT may show how many products need updating.

1. Open **Price change printing** or **Price printing**.
2. Review the product total.
3. Identify new products and price changes.
4. Check whether separate printing groups or moments exist.
5. Complete each group before marking the task finished.

Day closure may remain blocked until this work is complete.

## [PRICE-FORMAT] Choose a format

Visible formats may include:

- **Large — 8 shelf labels per sheet**.
- **Small — 16 shelf labels per sheet**.
- **Signage — full sheet**.

1. Select the format required by the commercial procedure.
2. Review status, type, facing, arrow, strikethrough, and size when displayed.
3. Use **Preview configuration**.
4. Apply changes only to selected products or to all when the dialog clearly states the scope.

## [PRICE-PER-PRODUCT] Per-product configuration

1. Select the exact product.
2. Open **Edit product printing**.
3. Read whether the change applies only to this print or modifies configuration.
4. Select arrow, format, or visible options.
5. Use **Save Configuration** once.
6. Wait for **Configuration saved**.

If **Error saving configuration** appears, retry once only after reviewing the fields. If it continues, escalate.

## [PRICE-PREVIEW] Preview

1. Open **Print preview**.
2. Review description, price, arrow, strikethrough, size, and color.
3. Use **Previous**, **Next**, or **Go to page** to review every page.
4. Correct before printing.

A preview does not mean the document printed.

## [PRICE-PAPER-COLOR] Printing by color

BOT may separate:

- Blue sheets for New, In & Out, and Temporary products.
- Yellow sheets for catalog products.
- White sheets for pharmacy products.

Always follow the visible store message:

1. Load the indicated paper.
2. Confirm the number of sheets.
3. Select **Print** once.
4. Wait for the sent status.
5. Physically review the output.
6. Select **Finish** only when the group is complete.

## [PRICE-END-DAY] Price printing blocks closure

If **Unable to close the day** lists **Price printing**:

1. Open that item.
2. Review pending products and pages.
3. Complete or resolve printing according to the screen.
4. Return to **Day closure**.

Do not close BOT to remove the blocker.

## [TABLE-SEARCH] Search within a table

1. Read the search-field prompt.
2. Use product key, barcode, description, or other requested value.
3. Clear earlier filters when no results appear.
4. Wait for the table to finish updating.
5. Confirm a product or movement with more than one detail before selecting it.

## [TABLE-EMPTY] Empty table or list

An empty list may mean there are no items for the filter, not that something failed.

1. Check filters and current page.
2. Change to **All** when available.
3. Clear search.
4. Confirm the process date or status.
5. If a confirmed item should exist, retain its folio and escalate.

## [TABLE-PAGINATION] Pagination

- Use **Previous** and **Next** to move through results.
- Under **Go to page**, enter only a number within the displayed total.
- Review every page before saying a product or movement does not exist.
- Do not change pages while a confirmation is processing.

## [DIALOG-CONFIRM] Confirmation dialogs

Before selecting **Accept**, **Apply**, **Replace**, **Confirm**, or **Finish**:

1. Read the full title and description.
2. Identify what will be created, changed, replaced, or closed.
3. Verify amount, products, quantities, and scope.
4. When uncertain, use **Cancel** or **Back**.

Do not use confirmation to test what happens.

## [KEYBOARD] Keyboard and focus

- **F1** may accept when shown beside a button.
- **Enter** may continue or submit when displayed.
- **Esc** may cancel or return when displayed.
- Letter shortcuts such as **D**, **C**, or **I** apply only on the screen that displays them.
- If the cursor is not in the correct field, select that field before typing.

Do not treat a shortcut from another screen as global.

## [TOOLS-OPEN] Open operational tools

1. Select **Operational tools**.
2. Choose only a tool approved for your role.
3. Wait for **Initializing Content ...**.
4. Then wait for **Loading Content ...**.
5. Perform the task inside the tool.
6. Return through the visible BOT control.

Do not change the address, configuration, or content engine.

## [TOOLS-BLANK] Blank tool or missing content

1. Wait for loading messages to finish.
2. Do not refresh repeatedly.
3. Use the visible control to return to BOT.
4. Open it once more only when no operation was active.
5. If it remains blank, retain the tool name, time, and screen and escalate.

## [TOOLS-INIT-ERROR] Content initialization error

**Related messages:**

- **Web content restart required.**
- **There was an error initializing web content.**

Store response:

1. Do not clear caches or files.
2. Do not use commands.
3. Return to BOT when a visible control is available.
4. Preserve pending work and the message.
5. Contact authorized support.

The word “restart” in the message does not authorize restarting Linux.

## [TOOLS-EXTERNAL-SESSION] Tool requests access or login

Use only the official account assigned for that tool. The Tiendas 2.0 assistant does not reset credentials for external services. Do not save passwords in unrecognized fields. If access fails, identify the tool and contact its authorized support.

## [PDF-GENERATION] Generate and review reports

BOT may prepare product, reception, transfer, shrinkage, inventory, order, shift, and day reports.

1. Complete the movement and wait for a folio when applicable.
2. Open **Reports**, **Preview**, or the visible control.
3. Review heading, store, date, folio, totals, and pages.
4. Print once.
5. Retain every page.

Do not repeat the movement to generate the PDF again.

## [PDF-FAILURE] Report does not open or print

1. Confirm whether the movement already has a folio.
2. If it does, do not repeat the movement.
3. Try opening the preview once more only when BOT provides the control.
4. For a printing error, use the printer guidance.
5. If the PDF still does not open, retain folio, report name, and time and escalate.

## [LINUX-BOUNDARY] Permitted and prohibited Linux actions

### Permitted

- Use visible POS/BOT controls.
- Check power, paper, and accessible cables.
- Reconnect Zebra once.
- Close and reopen the application only with authorization and no active operation.
- Capture sanitized evidence.

### Prohibited

- Open a terminal and execute commands.
- Edit or move files.
- Install programs, tools, or drivers.
- Change permissions, services, processes, network, clock, or configuration.
- Delete cache, data, or local databases.
- Use technical credentials.

## [LINUX-RESTART] Decide whether the application may be restarted

Do not close or restart during a payment, Zebra import, comparison, print, reception, transfer, shrinkage, order, adjustment, shift closure, or day closure.

If no operation is active and authorized procedure permits it:

1. Record the screen and time.
2. Close using the application control.
3. Open it through the normal launcher.
4. Verify store, version, session, and previous state.

If uncertain, escalate before closing.

## [TOOLS-FAQ] Quick answers

**Where do I upload products?** Nowhere; updating is automatic.

**Can I edit a price?** Only through visible authorized options, never through files.

**What should I do with a blank BOT page?** Return, try once, and escalate if it continues.

**Does “engine restart” mean restart Linux?** No.

**Does a preview mean it printed?** No.

## [TOOLS-ESCALATE] Escalation information

BOT or POS, store, terminal, version, product or tool, key/barcode when applicable, screen, filter, page, step, folio, date, time, and message. Capture without names, credentials, customer, or payment data.

## [TOOLS-QA] QA pending

- Confirm tools visible by role.
- Capture loading, empty, and error states.
- Validate label formats and colors.
- Confirm price-printing closure blockers.
- Verify every report and page.
- Confirm shortcuts by Linux screen.

