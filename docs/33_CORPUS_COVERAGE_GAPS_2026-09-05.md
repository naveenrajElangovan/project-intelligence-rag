# 33 — Corpus coverage gap: 31 of 58 declared events are not indexed

Date: 2026-09-05. Established from a live Chroma manifest (5131 chunks,
schema v4) and `store-core-kotlin/.../domain/model/event/EventType.kt`.

## What was found

`EventType.kt` declares **58** events. Searching every indexed chunk's
`structure_path`, `title` and `entity_key`:

- **27 are documented** in the T2.0 corpus.
- **31 appear nowhere in it.**

This is the cause of a user-visible failure. "Give me all LOGIN_POS event
details" returned nothing because `LOGIN_POS` — declared as
`LOGIN_POS_EVENT("POS_LOGIN", 101, "0.3")` — is not in the corpus under either
name. The service was right to decline. No amount of retrieval or grounding
tuning changes that; the content is not there.

It also explains 56 evaluation cases that could not resolve. They were written
against an event registry the corpus does not contain, and are retired as
`corpus_coverage_gap` rather than as invalid cases. **Un-retire them once the
event catalogue is ingested** — they are the acceptance test for that work.

## The remedy

The authoritative source is code, not Confluence: `EventType.kt` plus the event
model classes under `store-core-kotlin/shared/.../domain/model/event/`. The
ingestion service already has a GitHub connector, so ingesting that repository
would make all 58 events answerable and close both the product gap and
the evaluation gap in one step.

## A second finding, worth fixing at the same time

`entity_key` is populated on 464 chunks, but only 41 distinct values, and the
most common are not identifiers at all:

    323  bot
     39  pos
     18  iot
     12  authorize
      6  register

Generic lowercase words are being extracted as entity keys. `validate_output`
builds its coverage contract by comparing expected identifiers against observed
`entity_key` values, so this noise weakens the completeness guarantee wherever
it applies.

## Events absent from the corpus

- `BOT_BACKUP_OPERATIONAL_STATE`
- `BOT_CONFIRM_EXPENSES`
- `BOT_COUNT_INVENTORY`
- `BOT_DECLARE_ITEM_SHRINKAGE`
- `BOT_END_STORE_DAY`
- `BOT_EXTRACT_CASH_FROM_TOMBOLA`
- `BOT_INITIALIZATION_REQUEST`
- `BOT_ITEMS_TRANSFER_ORDER`
- `BOT_LOGIN`
- `BOT_LOGOUT`
- `BOT_LOG_MANAGEMENT_VISIT`
- `BOT_PAY_CASH_EXPENSE`
- `BOT_RECEIVE_ITEMS_FROM_SUPPLIER`
- `BOT_RECEIVE_TRANSFERRED_ITEMS`
- `BOT_REQUESTED_EVENTS`
- `BOT_REQUEST_REPLENISHMENT`
- `BOT_SEND_FILE`
- `BOT_START_STORE_DAY`
- `BOT_TRANSFER_ITEMS_OUT`
- `CEDIS_ITEMS_TRANSFER_ORDER`
- `FABRIC_CATALOG_UPDATES`
- `FABRIC_CONFIRM_SHIFT_CLOSURE`
- `FABRIC_CONFIRM_STORE_DAY_CLOSURE`
- `FABRIC_INITIALIZE_BOT_STATE`
- `FABRIC_RECOMMENDED_REPLENISHMENT`
- `FABRIC_REQUEST_EVENTS`
- `POS_EXPENSE_CASH_SETTLEMENT`
- `POS_LOGIN`
- `POS_LOGOUT`
- `POS_RECEIVE_REQUESTED_CASH`
- `POS_REMITTANCE_TICKET`

## Events documented in the corpus

- `BOT_CLOSE_SHIFT_RESPONSE`
- `BOT_CONFIRM_CLOSE_POS_SHIFT`
- `BOT_FUND_POS`
- `BOT_FUND_POS_NEW_SHIFT`
- `BOT_RECEIVE_CASH_FROM_POS`
- `BOT_REQUEST_POS_CASH_RELIEF`
- `IOT_CASH_BALANCE_ADJUSTMENT`
- `IOT_CATALOGS_UPDATE`
- `IOT_CATALOGS_UPDATE_REQUEST`
- `IOT_PRICES_UPDATE`
- `IOT_TPV_CONFIGURATION_RESPONSE`
- `IOT_TWIN_UPDATE`
- `IOT_USER_INFO_UPDATE`
- `POS_CANCEL_CASH_RELIEF_REQUEST`
- `POS_CASH_DIFFERENCE`
- `POS_CLIENT_RETURN_ITEMS`
- `POS_CLOSE_SHIFT`
- `POS_CLOSE_SHIFT_REQUEST`
- `POS_EXPENSE_CASH_WITHDRAWAL`
- `POS_EXTRACT_CASH`
- `POS_PAYMENT_TRANSACTION`
- `POS_REQUEST_BULK_ITEM_SHRINKAGE`
- `POS_REQUEST_BULK_ITEM_TRANSFER`
- `POS_REQUEST_CASH`
- `POS_SALES_TICKET`
- `POS_SERVICE_TICKET`
- `POS_START_SHIFT`
