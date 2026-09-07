# Linux BOT — Zebra inventory and efficient order

**Page ID:** T2STORE-INVENTORY-ORDER-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-INVENTORY-ORDER-ES`

## [INV-SCOPE] Scope and warnings

This page covers Zebra inventory counting, Sales Floor and Warehouse import, POS synchronization, comparison, recount, adjustment, and efficient orders.

Do not edit, rename, manually copy, fabricate, or move files through Linux. Every transfer is performed through visible BOT controls.

## [INV-BEFORE] Before starting inventory

1. Confirm that BOT and POS belong to the same store.
2. Check that the operating day is in the required state.
3. Verify that the authorized Zebra scanner has power.
4. Confirm that no other count is active for the same scope.
5. Determine the visible type: Facing, Group, Item, Rule 13, or Recount.
6. Coordinate who will count the Sales Floor and Warehouse.

Do not start while BOT is loading operational data or POS communication cannot be verified.

## [INV-RULE13] Rule 13

1. Open **Inventory**.
2. Select the **Rule 13** workflow.
3. Review the scope in **Start inventory count**.
4. Select **Run Rule 13** once.
5. Wait; the screen warns that this may take several minutes.
6. Review the result: it may report no products with stock at or below zero or display how many were found.

Do not close BOT or run it again while it is processing.

## [INV-SELECT-LAYOUT] Select the count layout

1. Under **Inventory type**, select Facing, Group, or Item according to the assigned task.
2. Use **Search** to find the correct scope.
3. Review the selection before continuing.
4. Select **Next**.

Do not choose a similar scope when the requested one is missing. Retain its expected name and escalate.

## [INV-CONNECT-ZEBRA] Connect Zebra

1. Physically connect the authorized scanner to the BOT computer with the approved cable.
2. Allow the device to complete its visible connection.
3. Keep BOT on the inventory screen.
4. Do not open Linux folders or search for files manually.

If BOT displays **Device not found**, physically disconnect and reconnect once, then retry from the screen.

## [INV-DOWNLOAD] Download products to Zebra

1. Confirm the selected type and scope.
2. Connect Zebra.
3. Select **Download** once.
4. Do not disconnect while processing.
5. Wait for **File download** and the number of successfully downloaded products.
6. Confirm through the scanner workflow that the list is available before going to the floor.

If **Download error** appears, make one new attempt only after reconnecting physically and confirming that no process is active.

## [INV-ZEBRA-ERRORS] Visible Zebra errors

- **Device not found:** reconnect once, then escalate.
- **There was a problem with the file:** do not edit or rename; retain the message and escalate.
- **ADB tool not found:** do not install anything; this requires authorized support.
- **Device permission missing:** do not change Linux permissions; reconnect and accept only a visible device prompt if one exists, then escalate if it continues.
- **Unable to download file:** confirm physical connection and make no more than one additional attempt through BOT.

## [INV-COUNT-FLOOR] Count the Sales Floor

1. Open the downloaded list on the scanner.
2. Walk the assigned physical scope.
3. Enter each product and quantity according to the scanner procedure.
4. Do not include Warehouse stock in the Sales Floor count.
5. Review skipped items or unusual quantities before finishing.
6. Finish the count on the scanner so it generates its file.

The Sales Floor file ends in `_1.txt`. Do not change the name.

## [INV-COUNT-WAREHOUSE] Count the Warehouse

1. Open the corresponding count on the scanner.
2. Walk only the Warehouse.
3. Enter each product and quantity.
4. Review before finishing.
5. Finish so the file is generated.

The Warehouse file ends in `_0.txt`. Do not change the name.

## [INV-IMPORT-START] Start import

1. Return to BOT and connect Zebra.
2. Open **Inventory count**.
3. Review **Required files**.
4. Confirm whether **Sales Floor pending** and **Warehouse pending** appear.
5. Select **Import file** once.

BOT searches for generated files. The user must not select paths or manually copy files.

## [INV-IMPORT-FLOOR] Import Sales Floor

1. Wait for BOT to identify the `_1.txt` file.
2. Review **Do you want to import ... items into this inventory count?**.
3. Confirm that it is Sales Floor and the count is reasonable.
4. Select **Accept**.
5. Wait for **File imported successfully** and **Sales Floor imported** with a quantity.

If the quantity is unexpected, cancel before accepting and review the physical count.

## [INV-IMPORT-WAREHOUSE] Import Warehouse

1. Wait for BOT to identify the `_0.txt` file.
2. Confirm that it is Warehouse.
3. Review the item count.
4. Select **Accept**.
5. Wait for **Warehouse imported** with a quantity.

Do not use the Sales Floor file as Warehouse or vice versa.

## [INV-NO-FILES] No files found to import

1. Confirm that both scanner counts were completed.
2. Confirm that the connected device is the one used for counting.
3. Reconnect once.
4. Select **Import file** one more time.
5. If files remain unavailable, do not fabricate or rename them; escalate.

## [INV-REPLACE] Replace previously imported information

BOT may show **Sales Floor information already exists**, **Warehouse information already exists**, or **Replace file**.

1. Identify which part was already imported.
2. Compare previous and new quantities when visible.
3. Select **Cancel** when uncertain.
4. Select **Replace** only when the new file is the correct recount and replacement is authorized.
5. Wait for new confirmation.

Replacement removes that part's prior information from this count; it is not a test action.

## [INV-BOTH-READY] Confirm both files

Before comparison, the screen must show Sales Floor and Warehouse imported with their quantities. If **1 file remaining** or **2 files remaining** appears, do not continue to adjustment.

## [INV-SYNC] Synchronize with POS

1. Open **Synchronization** or **Validate inventory information**.
2. Read the reminder that sales information must be current.
3. Start validation once.
4. Wait during **Validating point-of-sale connection**.
5. Do not close BOT or POS or disconnect Zebra while active.

If validation fails, review visible POS last connection and use **Revalidate** once. If it continues, escalate.

## [INV-COMPARISON] Comparison

BOT compares scanner counts with inventory and deducts sales recorded during counting. The process may take several minutes.

- Do not repeat import.
- Do not create a parallel adjustment.
- Wait for the difference result.
- If there are no differences, retain confirmation and close according to the screen.

## [INV-DISCREPANCIES] Differences found

1. Review the products with differences.
2. Use visible criteria: cost difference over $100, piece difference over 2, or both.
3. Select only items that require recount.
4. Print or use the authorized list when offered.
5. Perform a new physical count.

Do not change quantities just to match the system.

## [INV-RECOUNT] Recount

1. Select **Recount**.
2. Download the selected list to Zebra when requested.
3. Count Sales Floor and Warehouse again as applicable.
4. Import the new files without editing.
5. Confirm replacement only for the recounted part.
6. Run comparison again.

## [INV-ADJUSTMENT] Inventory adjustment

1. Review final differences after recount.
2. Obtain required authorization.
3. Select **Inventory adjustment** once.
4. Wait for success and a folio.
5. Review the number of adjusted items.
6. Retain the folio and report.

If no folio appears, do not repeat adjustment. Retain the screen, time, quantities, and POS/BOT state and escalate.

## [ORDER-NOTIFICATION] Find an efficient order

**Efficient order available** appears in BOT's incoming-message area.

1. Review BOT home.
2. Open the message once.
3. Confirm that it belongs to the current day and store.

Do not search for or upload a file to create the order.

## [ORDER-BLOCKED] Order blocked by pending reception

BOT may list a pending **Merchandise reception** or **Transfer**.

1. Record the displayed reference.
2. Leave the order without confirming it.
3. Complete the correct reception or transfer.
4. Return to the efficient-order message.

Do not create a new reception when one with the same reference is pending.

## [ORDER-CATEGORIES] Categories and filters

The order may contain:

- **Fresh Produce and Meat**.
- **Normal Order**.
- **Supplies**.

Use search, **All**, **Priority only**, or **Priority first** as displayed. Review every category even when it has no modified items.

## [ORDER-STOCK] Enter stock

When BOT enables stock entry:

1. Review product, facing, and location.
2. Enter Sales Floor and Warehouse stock in the offered fields.
3. Verify unit, pieces, boxes, or packaging.
4. Review total stock and stock days when displayed.
5. Continue only after completing required fields.

## [ORDER-QUANTITIES] Suggested and final order

1. Compare **Suggested** with **Final order**.
2. Review daily sales, stock days, packaging, and optimal boxes when displayed.
3. Modify only authorized quantities.
4. Check that final quantity uses the correct unit.
5. Review the summary of automatic and modified items.

## [ORDER-PRINT-LIST] Print the preparation list

Use **Print product list** when available. The list may be Supplies, Normal Order, stock entry, or Fresh Produce and Meat. While printing, do not confirm the order or generate another list. Missing paper does not change the quantities saved on screen.

## [ORDER-CONFIRM] Confirm the order

**Permission:** replenishment-request confirmation authorization is required.

1. Open **Order summary**.
2. Verify total, automatic, modified, items, and boxes.
3. Confirm that no category remains pending.
4. The authorized person selects **Confirm order** once.
5. Wait for order generation.
6. Retain the folio and **Efficient order sent** document.

Do not confirm again because printing is missing or visibly delayed.

## [ORDER-END-DAY] Order and day closure

An available unprocessed efficient order may block closure. Open the item shown under **Unable to close the day**, complete the order, and return to closure. Do not close BOT to bypass it.

## [INV-ORDER-ESCALATE] Evidence for support

Store, terminal, version, inventory type or order category, screen, step, time, quantities, permitted file names only, Sales Floor/Warehouse status, POS connection state, folio, and exact message. Do not attach count files through unauthorized channels.

## [INV-ORDER-FAQ] Quick answers

**Where do I edit the Zebra file?** It must not be edited.

**Can I rename `_1.txt` or `_0.txt`?** No.

**Which is Sales Floor?** `_1.txt`.

**Which is Warehouse?** `_0.txt`.

**Can I import one file and adjust?** No; BOT must show both required files as imported.

**Can I confirm an order twice?** No.

**Why can I not close the day?** Check whether the efficient order is still pending.

## [INV-ORDER-QA] QA pending

- Capture every Zebra error on Linux.
- Confirm visible inventory-type names.
- Verify replacement and recount with seeded data.
- Measure duration without publishing limits before approval.
- Confirm adjustment and order roles.
- Capture every category, summary, folio, and closure blocker.

