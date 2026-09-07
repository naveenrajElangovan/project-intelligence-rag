# Tiendas 2.0 Linux Store Assistant knowledge pack

This directory contains the store-facing knowledge source prepared for publication beneath the `Tiendas 2.0 Store Assistant` root in Confluence space `Store_Users_Douments`.

## Publishable documents

- `es/TIENDAS_2_STORE_ASSISTANCE_ES.md` — Spanish canonical source.
- `en/TIENDAS_2_STORE_ASSISTANCE_EN.md` — English canonical source.
- `es/topics/` — detailed Spanish retrieval pages.
- `en/topics/` — detailed English retrieval pages.

The master documents provide the shared entry point and safe answer policy. The topic pages contain the detailed procedures and canonical troubleshooting answers that should be published as sibling Confluence pages. Both layers are intended for ingestion after approval; a topic page is not a library or developer document.

## Detailed topic pages

| Topic | Spanish page | English sibling |
|---|---|---|
| Authentication, sessions, passwords, and authorization | `es/topics/01_AUTENTICACION_SESIONES_Y_AUTORIZACIONES.md` | `en/topics/01_AUTHENTICATION_SESSIONS_AND_AUTHORIZATION.md` |
| POS sales, shifts, products, cancellations, returns, and cash | `es/topics/02_POS_VENTAS_TURNOS_EFECTIVO.md` | `en/topics/02_POS_SALES_SHIFTS_AND_CASH.md` |
| Cash, card, Santander, CoDi, voucher, mixed, services, and airtime payments | `es/topics/03_PAGOS_Y_RESULTADOS_AMBIGUOS.md` | `en/topics/03_PAYMENTS_AND_AMBIGUOUS_RESULTS.md` |
| Receipts, reprinting, reports, labels, cash drawer, and print failures | `es/topics/04_IMPRESION_COMPROBANTES_REPORTES_Y_CAJON.md` | `en/topics/04_PRINTING_RECEIPTS_REPORTS_AND_DRAWER.md` |
| BOT day lifecycle, POS requests, cash, merchandise, transfers, shrinkage, and closures | `es/topics/05_BOT_DIA_EFECTIVO_MERCANCIA_Y_CIERRES.md` | `en/topics/05_BOT_DAY_CASH_MERCHANDISE_AND_CLOSURE.md` |
| Zebra exchange, floor/warehouse inventory, comparison, recount, adjustment, and efficient order | `es/topics/06_INVENTARIO_ZEBRA_Y_PEDIDO_EFICIENTE.md` | `en/topics/06_ZEBRA_INVENTORY_AND_EFFICIENT_ORDER.md` |
| Automatic catalog updates, prices, labels, tables, PDF, embedded tools, offline states, and Linux safety | `es/topics/07_PRODUCTOS_PRECIOS_HERRAMIENTAS_Y_SEGURIDAD_LINUX.md` | `en/topics/07_PRODUCTS_PRICES_TOOLS_AND_LINUX_SAFETY.md` |
| Diagnosis, short answers, privacy, safe refusal, severity, and escalation | `es/topics/08_DIAGNOSTICO_PREGUNTAS_Y_ESCALAMIENTO.md` | `en/topics/08_DIAGNOSIS_FAQ_AND_ESCALATION.md` |
| Store roles, protected operations, supervisor authorization, safe retry, and do-not-repeat rules | `es/topics/09_ROLES_PERMISOS_Y_OPERACION_SEGURA.md` | `en/topics/09_ROLES_PERMISSIONS_AND_SAFE_OPERATION.md` |
| User-question variants, intent routing, synonyms, target pages, and exact citation keys | `es/topics/10_INDICE_DE_PREGUNTAS_CANONICAS.md` | `en/topics/10_CANONICAL_QUESTION_INDEX.md` |

For Confluence, publish one page per file and keep every Spanish page beside its English sibling. Keep the bracketed section identifiers unchanged: they are the citation anchors and bilingual parity keys. The question index is a retrieval aid, while the operational topic page remains the source for the final answer.

The section identifiers are deliberately identical in both documents. They are the stable citation and parity keys to retain when the master documents are split into parallel Confluence pages.

## Publication status

Status: **DRAFT — NOT APPROVED FOR INGESTION**

Before publication, every entry marked `QA pendiente` / `QA pending` requires validation on the released Linux application in a non-production store. Add one sanitized screenshot to each final Confluence procedure, record the verification date, and obtain product-owner approval.

These documents are the only proposed store corpus content. The T3B repositories, library documentation, evidence notes, Jira, and developer Confluence pages are not store RAG sources.

## Evidence baseline

- POS: `release/v1.3.0`, commit `8f102363811fc942bb27679ecf0f9df111608308`.
- BOT: `release/v1.3.0`, commit `50ffc1cc`.
- Matching `v1.3.0` T3B runtime libraries are verification evidence only.

## Required editorial rules

1. Answer in the language used by the store user.
2. Use only visible Linux buttons, fields, messages, and safe physical checks.
3. Never expose source code, event names, libraries, endpoints, secrets, configuration files, device paths, logs, databases, or terminal commands.
4. For an ambiguous electronic payment, never recommend repeating the payment until its result is confirmed.
5. If the published pages do not verify an answer, say that verified guidance was not found and direct the user to authorized support.
6. Preserve section IDs during publication so English and Spanish pages remain structurally equivalent.
