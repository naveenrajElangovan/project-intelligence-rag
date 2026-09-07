# Roles, permissions, and safe operation — Tiendas 2.0 Linux

**Page ID:** T2STORE-ROLES-EN  
**Version:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Sibling page:** `T2STORE-ROLES-ES`

## [ROLE-SCOPE] Purpose and scope

This page explains how to guide a store user when a function depends on their role, a permission, or another person's authorization. It describes only what the user can see and do in POS or BOT on Linux.

It does not identify technical components, internal permission names, server rules, or configuration. The application decides whether the person is authorized.

## [ROLE-PRINCIPLE] Primary rule

- Each person must sign in with their own user account.
- A protected authorization must be completed by the authorized person with their own credentials.
- Passwords must not be shared, a session must not be left open for another person, and restrictions must not be bypassed.
- The presence of a button does not mean the user has permission to complete the action.
- If the application rejects an action, do not repeat it with borrowed credentials.

## [ROLE-IDENTIFY-CONTEXT] Identify the context before providing guidance

The assistant must confirm:

1. Whether the person is in POS or BOT.
2. The visible name of the screen or action.
3. The exact message shown.
4. Whether another person's authorization is requested.
5. Whether the operation already produced a receipt, folio, or visible change.
6. Whether the screen is still processing.

Never ask for a password or ask the user to include one in a screenshot.

## [ROLE-STORE-USER] Store operator

A store operator can use the functions shown and allowed by their session. Depending on their assignment, this may include:

- Signing in and unlocking their own session.
- Opening and operating a POS shift after prerequisites are met.
- Searching, scanning, and selling products.
- Receiving payments through enabled methods.
- Reviewing visible states and recovering documents when permitted.
- Performing BOT tasks allowed by their menu and authorization.

Documentation must never promise access to a function. If the screen asks for authorization or displays a rejection, follow the protected-action procedure.

## [ROLE-AUTHORIZER] Authorizer or supervisor

Some higher-risk actions may request additional authorization. When the dialog appears:

1. Read the text and confirm which action is being authorized.
2. The authorizer must be physically present and review the operation.
3. The authorizer enters their own credentials without sharing them.
4. Wait for the visible result before continuing.
5. If authorization is rejected, stop the action and contact the authorized manager.

An authorization must not be reused for another action, another sale, or a later movement.

## [ROLE-PROTECTED-ACTIONS] Actions that may be protected

The application may request permission or authorization for actions such as:

- Canceling products or an entire sale.
- Processing a return.
- Opening the drawer outside the normal flow.
- Reprinting certain documents.
- Recording or confirming cash movements.
- Confirming receptions, transfers, shrinkage, or adjustments.
- Confirming an efficient order.
- Closing a shift or day.
- Changing operational data available on screen.

The exact list may vary by assignment. The visible dialog in the released version is the definitive evidence.

## [ROLE-PERMISSION-DENIED] Action rejected because of permission

**Symptom:** the button is disabled, the option is missing, the application reports insufficient permission, or it requests another user.

**Safe response:**

1. Confirm that the correct user signed in.
2. Do not close or repeat an operation that is already processing.
3. If authorization is offered, ask the authorized person to review the action.
4. If no authorization option exists, do not try alternative routes.
5. Retain application, screen, action, user without password, time, and message.
6. Contact the authorized manager.

Do not explain how to modify permissions.

## [ROLE-MISSING-MENU] An option or menu is missing

Visible causes may include the role, current day or shift state, an unmet prerequisite, or the function not being available in that application.

1. Confirm POS or BOT and the starting screen.
2. Verify that sign-in finished successfully.
3. Check whether the required day or shift is open.
4. Review visible notices or blockers.
5. Do not switch users merely to search for the option.
6. If it remains missing, retain a sanitized screenshot and escalate.

The assistant must not claim which permission is missing unless the screen identifies it.

## [ROLE-BUTTON-DISABLED] Button is visible but disabled

A disabled button commonly means a selection, required value, previous state, or authorization is missing. First review the screen for:

- Empty required fields.
- No selected row, category, terminal, or document.
- Invalid quantity.
- Operation still loading.
- A blocker reported on screen.

Do not recommend restarting merely because a button is disabled.

## [ROLE-SUPERVISOR-CREDENTIALS] Safe authorization entry

- The operator must not know or type the authorizer's password.
- The authorizer must confirm that the dialog matches the expected action.
- The password field must not be photographed.
- If credentials are rejected, an obvious entry error may be corrected once.
- After another rejection, stop attempts to avoid further locking.

## [ROLE-AUTHORIZATION-WAITING] Authorization processing or no response

While a processing indicator remains visible:

- Do not press **Authorize**, **Accept**, or **Confirm** again.
- Do not open another dialog for the same operation.
- Do not switch users or close the application.
- Wait for a visible outcome.

If no outcome appears, retain the screen, time, operation, and any prior folio. Escalate without repeating the movement.

## [ROLE-AUTHORIZATION-FAILED] Authorization rejected

1. Read the complete message.
2. Confirm that the authorizer used their own account.
3. Correct one obvious entry error once.
4. If rejected again, safely cancel the dialog.
5. Do not use another person's credentials.
6. Contact the authorized manager to review the assignment outside the operation.

## [ROLE-AUTHORIZATION-SUCCEEDED] Authorization accepted

Accepted authorization does not always mean the complete movement finished. After authorization:

1. Return to the operation flow.
2. Complete only the reviewed action.
3. Wait for the final message.
4. Retain the generated folio or receipt.
5. If a later error appears, do not authorize or repeat again until status is confirmed.

## [ROLE-SHIFT-OWNERSHIP] Sessions and shifts

- Each cashier must use their assigned session.
- Before signing out, resolve or cancel any pending sale through the authorized flow.
- Do not open a second shift if the first appears open or funding was already recorded.
- If BOT displays a POS request, handle it for the indicated terminal and shift.
- If the shift belongs to another person or shows an unexpected state, stop and escalate.

## [ROLE-POS-BOT-BOUNDARY] Difference between POS and BOT

POS is used for register and sale operation; BOT coordinates store activities, merchandise, inventory, orders, cash, and closures. An action started in one application may require confirmation in the other.

Do not manually recreate in BOT an operation already sent from POS, and do not repeat in POS a response pending from BOT.

## [ROLE-SENSITIVE-ACTIONS] Higher-risk operations

Treat these as sensitive:

- Electronic payments and ambiguous results.
- Cancellations and returns.
- Funding, reliefs, withdrawals, expenses, and value delivery.
- Receptions, transfers, shrinkage, and adjustments.
- Inventories and count replacement.
- Order confirmation.
- Shift and day closure.

For these operations, the assistant must always state the expected outcome, what not to repeat, and what evidence to retain.

## [ROLE-DO-NOT-REPEAT] When not to repeat

Do not repeat when any of these conditions exists:

- The screen is still processing.
- A receipt, folio, authorization, or proof exists.
- An external provider indicates an accepted payment.
- The application returned to another screen without showing an outcome.
- POS and BOT show different states.
- Connectivity was lost after confirmation.

First verify the outcome through the documented path or contact authorized support.

## [ROLE-SAFE-RETRY] When a retry may be safe

A retry is acceptable only when:

1. The application shows an explicit retry option or states that the operation was not sent.
2. No receipt, folio, charge, authorization, or visible change exists.
3. The specific flow documents the retry.
4. A visible cause, such as an empty field or accessible physical connection, was corrected.

If any condition is missing, do not promise that retrying is safe.

## [ROLE-PRIVACY] Privacy and credentials

Never request or expose:

- Passwords or PINs.
- Full card number or security code.
- Tokens, technical accounts, or secrets.
- Customer personal data.
- Configuration, internal files, or technical logs.

For support, application, store, terminal, user without password, screen, time, message, and permitted folio are sufficient.

## [ROLE-ESCALATE] Information for authorized support

Retain:

- POS or BOT.
- Store and terminal.
- Approximate date and time.
- Affected user or role, without password.
- Screen and attempted action.
- Exact message.
- Day and shift state.
- Permitted receipt, folio, or reference.
- Whether the operation is still processing.
- Sanitized screenshot.

## [ROLE-ANSWER-EXAMPLES] Canonical answers

**“How do I get permission?”**  
The application uses the permissions assigned to your account. Do not try to change them in the store. If the action requests authorization, ask the authorized person to review it and enter their own credentials; if that option is not available, contact the authorized manager.

**“Let me use another account to do it.”**  
Do not share or use another person's credentials. Retain the rejection message and request authorization through the visible flow or contact the authorized manager.

**“I was authorized. Is it finished?”**  
Not necessarily. Return to the operation, wait for the final message, and retain the receipt or folio. Do not repeat if the outcome remains ambiguous.

## [ROLE-QA] Pending validation

Before publication:

- Confirm in QA which actions request authorization in POS and BOT.
- Confirm the exact text of every rejection dialog.
- Confirm which buttons are hidden or disabled by role.
- Confirm the visible relationship among terminal, session, and shift.
- Add sanitized Spanish and English screenshots.
- Record the date, tested role, and result.

