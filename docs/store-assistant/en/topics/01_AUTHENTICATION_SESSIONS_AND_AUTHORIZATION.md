# Authentication, sessions, and authorization — Linux POS and BOT

**Page ID:** T2STORE-AUTH-EN  
**Release:** `v1.3.0`  
**Status:** Detailed draft; QA and screenshots pending  
**Applications:** POS and BOT on Linux  
**Sibling page:** `T2STORE-AUTH-ES`

## [AUTH-SCOPE] Scope

This page answers store-user questions about access, passwords, locked sessions, and authorization requested inside POS or BOT. It provides no technical recovery, account administration, network configuration, or Linux commands.

User phrases may include: *I cannot sign in*, *my user is rejected*, *wrong password*, *session locked*, *it asks for a manager*, *I do not have permission*, *change password*, *password expired*, *no internet*, or *login does not finish*.

## [AUTH-PREREQ] Information the assistant must establish

Before giving steps, ask or identify:

1. Is the person using POS or BOT?
2. Do they see **Point of Sale** or **Back Office Store**?
3. What is the exact visible message?
4. Are they signing in, unlocking a session, or authorizing an action?
5. Does the screen show a password update?
6. Is any operation processing that could be affected by signing out?

Never ask the person to type or share their password in chat.

## [AUTH-LOGIN-NORMAL] Normal login

**Role:** any user enabled for the application.  
**Starting screen:** **Point of Sale** or **Back Office Store**, with **User** and **Password** fields.  
**Visible control:** **Log In**; the store and version may also be displayed.

### Procedure

1. Confirm that the displayed store is correct.
2. Enter the account assigned to the person who will operate the application.
3. Enter the password, respecting uppercase and lowercase letters.
4. Select **Log In** once.
5. While **Logging In ...** is displayed, wait and do not press the button again.
6. When the home screen appears, confirm that the user or role is the expected one.

### Successful result

The application completes loading and displays the options allowed for the user. A missing option may be a role restriction; it does not automatically mean the application is broken.

### Do not repeat

Do not press **Log In** repeatedly while loading is visible. Do not try another person's password.

### Escalation

Escalate if loading never produces a result, the app returns to login without explanation, or confirmed credentials are rejected again. Retain the application, store, terminal, visible version, time, and message—never the password.

## [AUTH-INVALID] Invalid user or password

**Related messages:**

- **Unable to log in. Try again.**
- **Incorrect user or password.**
- **Invalid user or password. Try again.**

### Canonical answer

1. Check that the user field has no added spaces at the beginning or end.
2. Visually confirm the user without exposing the password.
3. Clear and re-enter the password once.
4. If the message returns, stop attempting and contact authorized support.

### What the assistant must not say

Do not claim that a remote service, directory, token, or local database failed. Those causes are not visible to the user. Do not recommend deleting data, changing files, restarting services, or using a coworker's account.

## [AUTH-OFFLINE] Access without connectivity

POS or BOT may allow offline access only when a still-valid local authorization already exists for that user. Availability depends on the user and previously stored information.

### Safe procedure

1. Attempt normal login once.
2. If the application allows access, use only the functions that remain enabled.
3. Read any notice about limited operation or pending information.
4. Do not assume that payments, synchronization, receptions, or closures work offline.
5. If access is rejected or expired, retain the message and contact support.

### Prohibited actions

Do not change the computer date or time. Do not modify the network, files, stored credentials, or Linux configuration.

## [AUTH-PASSWORD-WARNING] Password expiring soon

**Related messages:** **Your password is about to expire** or **Your password is expiring soon**.

The screen shows the remaining days and allows an update now or continuation when the change is still optional.

### Procedure

1. If the store is in the middle of an urgent operation, use **Continue** only when the screen permits it.
2. To update, open the displayed form.
3. Enter **New password**.
4. Meet every visible requirement: displayed minimum length, one uppercase letter, one lowercase letter, and one number.
5. Enter the same value in **Confirm password**.
6. Select **Update password** once.
7. Wait for **Password updated** and select **Accept**.

The assistant must not propose a specific password or ask the user to show it.

## [AUTH-PASSWORD-REQUIRED] Mandatory update or expired password

**Related messages:**

- **Password update required**.
- **Your password must be updated to continue.**
- **The password has expired. Contact support to continue.**

### When the form permits an update

Complete the displayed fields and requirements. Do not close the app while submitting. If it fails, make no more than one additional attempt after checking that both fields match.

### When the screen directs the user to support

Stop attempting. This guide has no authorized store-level recovery. Report the application, user without password, store, terminal, time, and exact message.

## [AUTH-PASSWORD-MISMATCH] Passwords do not match

1. Clear **New password** and **Confirm password**.
2. Carefully enter the new value in both fields.
3. Check the visible requirement indicators.
4. Submit once.

This message does not mean the old password is incorrect; it only means the two new values differ.

## [AUTH-PASSWORD-FAILED] Unable to update the password

1. Confirm that both fields match and satisfy every visible requirement.
2. Make one additional attempt.
3. If it fails again, retain the message and escalate.

Do not repeatedly switch between POS and BOT to change the password and do not use external tools.

## [AUTH-SESSION-LOCK] Lock a session

**Lock Session** protects a register or BOT temporarily without allowing another person to operate under an open session.

1. Confirm that no payment, print, reception, transfer, inventory, order, or closure is processing.
2. Use **Lock Session** or the visible shortcut.
3. Confirm that **Session locked** appears.

Locking a session does not close the shift or the day.

## [AUTH-SESSION-UNLOCK] Unlock a session

**Screen:** **Session locked**, with user and password fields.

1. Enter the authorized credentials requested by the screen.
2. Confirm once.
3. Wait for the previous screen to return.
4. Verify that the prior operation retained its expected state.

If a password change is required, complete it first. If the session cannot be unlocked, use **Close Session** only when available and no operation is processing; otherwise escalate.

## [AUTH-LOGOUT] Sign out

1. Correctly finish or cancel any open operation.
2. In POS, confirm whether the shift must also be closed.
3. Select **Exit / Close session** or **Close Session**.
4. Read and confirm the dialog when displayed.
5. Verify that the login screen returns.

Closing the Linux window does not replace signing out, closing the shift, or closing the day.

## [AUTH-PERMISSION] Action not allowed or authorization failed

An action may require a specific permission or authorization from another role.

### Procedure

1. Read which role the screen requests.
2. Cancel if that person is unavailable; do not try random accounts.
3. When the authorized person is present, they must enter their own credentials.
4. Confirm once and wait for the result.
5. If **Authorization failed, try again** appears, verify the role and make only one additional attempt.

### Known visible cases

- Opening a shift may be rejected when the user lacks permission.
- Opening the cash drawer requests the responsible cashier.
- Expense settlement may require the user who opened the shift.
- A sales summary may request a District Manager.
- Cancellations, returns, adjustments, and movements may request authorization depending on the operation.

## [AUTH-DIFFERENT-USER] The application requests a different user

If POS displays **The user differs from the user signed in to POS**, do not automatically change accounts. Read the protected action and use only the user required by the authorized procedure. If it is unclear who must authorize, cancel without completing the action and escalate.

## [AUTH-TERMINAL-CONFIG] Terminal configuration is required

If **Terminal configuration is required for authentication** appears:

1. Do not try to configure the computer.
2. Do not copy files from another register.
3. Retain the store, register or terminal, version, and exact message.
4. Contact authorized support.

This case has no store-user resolution.

## [AUTH-PROCESSING] The screen remains on “Logging In”

1. Wait without selecting **Log In** again.
2. Check only whether the application continues to show visible progress.
3. Do not close the window immediately after the request was submitted.
4. If no result appears and no visible retry instruction is offered, record the time and contact support.

An exact waiting time must be validated in QA before publication as a number.

## [AUTH-FAQ] Quick authentication answers

**Can I use another person's account?** No. Each person must use their own credentials, and the responsible person must enter authorization credentials.

**Can I tell the assistant my password?** No. The assistant never needs a password.

**Does locking the session close the shift?** No.

**Can I continue working offline?** Only with the options the application permits; not every function is guaranteed to be available.

**What should I do if my password expired?** Follow the form when it is available. If the screen directs you to support, stop attempting and escalate.

**Can I restart Linux to sign in?** Not as a store-level authentication procedure.

## [AUTH-ESCALATE] Safe evidence for support

Provide: POS or BOT, store, register or terminal, visible version, date and time, action type, user without password, and exact message. Do not provide passwords, customer information, tokens, or photographs containing sensitive information.

## [AUTH-QA] Pending validation

- Confirm the authorized number of retries with the product owner.
- Capture normal access, rejection, warning, and mandatory-change states in Linux POS and BOT.
- Confirm which roles can unlock each application.
- Confirm the visible offline-access behavior.
- Confirm every action that requests authorization and the displayed role text.

