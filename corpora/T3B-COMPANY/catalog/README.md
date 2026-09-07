# T3B-COMPANY product release input

This directory deliberately contains no claimed exhaustive product list. A release may be built only from the manually approved internal active-SKU export; public web pages are enrichment sources and never population authority.

Required CSV columns are listed in `source-template.csv`. One row represents one active SKU. Use `|` between multiple regions. `lifecycle_state` must be `ACTIVE`. Non-national records require at least one region. Populated price columns are rejected unless the release process is extended with a separately approved price feed.

Before approval, calculate the exact source file SHA-256, active row count, and totals by stable `category_code`, and place them in a copy of `manifest-template.json`. The approver must hold `CATALOG_PUBLISHER` in production.

Build and atomically activate a validated release:

```shell
.venv/bin/python tools/t3b_catalog_release.py \
  --source /secure/path/internal-active-skus.csv \
  --manifest /secure/path/manifest.json \
  --output corpora/T3B-COMPANY/catalog \
  --activate
```

Generated releases are immutable. Roll back only to a prior release whose manifest and artifacts still pass checksum verification:

```shell
.venv/bin/python tools/t3b_catalog_release.py \
  --output corpora/T3B-COMPANY/catalog \
  --rollback YYYY-MM-DD.N
```
