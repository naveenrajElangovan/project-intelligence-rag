#!/usr/bin/env python3
"""Validate and build an immutable bilingual Tiendas 3B product release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path


REQUIRED_COLUMNS = (
    "sku",
    "name_es",
    "name_en",
    "brand",
    "category_code",
    "category_es",
    "category_en",
    "subcategory_code",
    "subcategory_es",
    "subcategory_en",
    "presentation_es",
    "presentation_en",
    "assortment_type",
    "lifecycle_state",
    "availability_scope",
    "regions",
    "effective_date",
)
PRICE_COLUMNS = frozenset(
    {"price", "precio", "regular_price", "sale_price", "currency"}
)


class CatalogValidationError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sku_set_sha256(skus: list[str]) -> str:
    return sha256_bytes(("\n".join(sorted(skus)) + "\n").encode())


def read_catalog(path: Path) -> tuple[bytes, list[dict[str, str]]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    fieldnames = tuple(reader.fieldnames or ())
    missing = sorted(set(REQUIRED_COLUMNS).difference(fieldnames))
    if missing:
        raise CatalogValidationError(f"Missing required columns: {', '.join(missing)}")
    populated_prices = [
        column
        for column in PRICE_COLUMNS.intersection(fieldnames)
        if any((row.get(column) or "").strip() for row in csv.DictReader(text.splitlines()))
    ]
    if populated_prices:
        raise CatalogValidationError(
            "Price data requires a separately approved authoritative feed: "
            + ", ".join(sorted(populated_prices))
        )
    rows = [
        {key: (value or "").strip() for key, value in row.items()}
        for row in csv.DictReader(text.splitlines())
    ]
    if not rows:
        raise CatalogValidationError("The catalog contains no product rows.")
    seen: dict[str, dict[str, str]] = {}
    for number, row in enumerate(rows, start=2):
        absent = [column for column in REQUIRED_COLUMNS if not row.get(column)]
        if absent:
            raise CatalogValidationError(
                f"Row {number} is missing required fields: {', '.join(absent)}"
            )
        sku = row["sku"]
        if sku in seen:
            conflict = seen[sku] != row
            raise CatalogValidationError(
                f"Duplicate SKU {sku!r} is {'conflicting' if conflict else 'repeated'}."
            )
        seen[sku] = row
        if row["lifecycle_state"].upper() != "ACTIVE":
            raise CatalogValidationError(
                f"SKU {sku!r} is not ACTIVE; inactive products cannot enter the active release."
            )
        try:
            date.fromisoformat(row["effective_date"])
        except ValueError as error:
            raise CatalogValidationError(
                f"SKU {sku!r} has an invalid effective_date; use YYYY-MM-DD."
            ) from error
        if row["availability_scope"].upper() != "NATIONAL" and not _regions(row):
            raise CatalogValidationError(
                f"SKU {sku!r} requires one or more regions for non-national availability."
            )
    return raw, rows


def validate_manifest(
    manifest: dict[str, object], raw: bytes, rows: list[dict[str, str]]
) -> dict[str, object]:
    required = (
        "releaseId",
        "effectiveDate",
        "declaredActiveSkuCount",
        "categoryTotals",
        "sourceCsvSha256",
        "approver",
        "sourceSystemVersion",
    )
    missing = [key for key in required if manifest.get(key) in (None, "", {})]
    if missing:
        raise CatalogValidationError(
            "Manifest is missing required values: " + ", ".join(missing)
        )
    try:
        date.fromisoformat(str(manifest["effectiveDate"]))
    except ValueError as error:
        raise CatalogValidationError("Manifest effectiveDate must be YYYY-MM-DD.") from error
    if str(manifest["sourceCsvSha256"]).lower() != sha256_bytes(raw):
        raise CatalogValidationError("The immutable source CSV checksum does not match.")
    if int(manifest["declaredActiveSkuCount"]) != len(rows):
        raise CatalogValidationError(
            "Declared active-SKU count differs from parsed unique active SKUs."
        )
    actual_totals = dict(sorted(Counter(row["category_code"] for row in rows).items()))
    declared_totals = {
        str(key): int(value)
        for key, value in dict(manifest["categoryTotals"]).items()
    }
    if declared_totals != actual_totals:
        raise CatalogValidationError(
            f"Category totals disagree: declared={declared_totals}, actual={actual_totals}"
        )
    return {
        **manifest,
        "declaredActiveSkuCount": len(rows),
        "categoryTotals": actual_totals,
        "sourceCsvSha256": sha256_bytes(raw),
        "skuSetSha256": sku_set_sha256([row["sku"] for row in rows]),
        "status": "APPROVED",
    }


def build(source: Path, manifest_path: Path, output_root: Path, activate: bool) -> Path:
    raw, rows = read_catalog(source)
    manifest = validate_manifest(json.loads(manifest_path.read_text()), raw, rows)
    release_id = str(manifest["releaseId"])
    if not release_id or any(value in release_id for value in ("/", "\\", "..")):
        raise CatalogValidationError("releaseId is not safe for an immutable directory name.")
    release_dir = output_root / "releases" / release_id
    if release_dir.exists():
        raise CatalogValidationError(f"Immutable release {release_id!r} already exists.")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".catalog-release-", dir=output_root))
    try:
        shutil.copyfile(source, temporary / "source.csv")
        approved = temporary / f"t3b-products-{release_id}.csv"
        _write_approved_csv(approved, rows)
        es = temporary / f"productos-{release_id}-es.md"
        en = temporary / f"products-{release_id}-en.md"
        _write_document(es, rows, manifest, "es")
        _write_document(en, rows, manifest, "en")
        manifest.update(
            {
                "approvedCsvFileName": approved.name,
                "approvedCsvSha256": sha256_bytes(approved.read_bytes()),
                "spanishDocumentSha256": sha256_bytes(es.read_bytes()),
                "englishDocumentSha256": sha256_bytes(en.read_bytes()),
                "spanishProductCount": len(rows),
                "englishProductCount": len(rows),
            }
        )
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        (temporary / "answer-contract.json").write_text(
            json.dumps(_answer_contract(manifest), ensure_ascii=False, indent=2) + "\n"
        )
        release_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, release_dir)
        if activate:
            pointer = output_root / "active-release.json"
            draft = output_root / ".active-release.tmp"
            draft.write_text(
                json.dumps(
                    {
                        "releaseId": release_id,
                        "manifestSha256": sha256_bytes(
                            (release_dir / "manifest.json").read_bytes()
                        ),
                    },
                    indent=2,
                )
                + "\n"
            )
            os.replace(draft, pointer)
        return release_dir
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def rollback(output_root: Path, release_id: str) -> Path:
    """Atomically reactivate a prior immutable release after checksum verification."""

    release_dir = output_root / "releases" / release_id
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.is_file():
        raise CatalogValidationError(f"Release {release_id!r} does not exist.")
    manifest = json.loads(manifest_path.read_text())
    checks = {
        str(manifest["approvedCsvFileName"]): str(manifest["approvedCsvSha256"]),
        f"productos-{release_id}-es.md": str(manifest["spanishDocumentSha256"]),
        f"products-{release_id}-en.md": str(manifest["englishDocumentSha256"]),
    }
    for name, expected in checks.items():
        path = release_dir / name
        if not path.is_file() or sha256_bytes(path.read_bytes()) != expected:
            raise CatalogValidationError(
                f"Release {release_id!r} failed checksum verification for {name}."
            )
    pointer = output_root / "active-release.json"
    draft = output_root / ".active-release.tmp"
    draft.write_text(
        json.dumps(
            {
                "releaseId": release_id,
                "manifestSha256": sha256_bytes(manifest_path.read_bytes()),
            },
            indent=2,
        )
        + "\n"
    )
    os.replace(draft, pointer)
    return release_dir


def _write_approved_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows({column: row[column] for column in REQUIRED_COLUMNS} for row in rows)


def _write_document(
    path: Path, rows: list[dict[str, str]], manifest: dict[str, object], language: str
) -> None:
    spanish = language == "es"
    lines = [
        "# Catálogo maestro de productos activos" if spanish else "# Active product master catalog",
        "",
        f"- release_id: `{manifest['releaseId']}`",
        f"- effective_date: `{manifest['effectiveDate']}`",
        f"- active_sku_count: `{len(rows)}`",
        f"- source_system_version: `{manifest['sourceSystemVersion']}`",
        "",
    ]
    for row in rows:
        name = row["name_es" if spanish else "name_en"]
        category = row["category_es" if spanish else "category_en"]
        subcategory = row["subcategory_es" if spanish else "subcategory_en"]
        presentation = row["presentation_es" if spanish else "presentation_en"]
        section_id = f"product:{row['sku']}"
        lines.extend(
            [
                f"## {name}",
                "",
                f"- section_id: `{section_id}`",
                f"- translation_of: `{section_id}:{'en' if spanish else 'es'}`",
                f"- sku: `{row['sku']}`",
                f"- brand: {row['brand']}",
                f"- category_code: `{row['category_code']}`",
                f"- category: {category}",
                f"- subcategory_code: `{row['subcategory_code']}`",
                f"- subcategory: {subcategory}",
                f"- presentation: {presentation}",
                f"- assortment_type: `{row['assortment_type']}`",
                f"- lifecycle_state: `{row['lifecycle_state']}`",
                f"- availability_scope: `{row['availability_scope']}`",
                f"- regions: {', '.join(_regions(row))}",
                f"- effective_date: `{row['effective_date']}`",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _regions(row: dict[str, str]) -> list[str]:
    return [value.strip() for value in row["regions"].split("|") if value.strip()]


def _answer_contract(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "intent": "LIST_ALL_PRODUCTS",
        "releaseId": manifest["releaseId"],
        "effectiveDate": manifest["effectiveDate"],
        "verifiedActiveSkuTotal": manifest["declaredActiveSkuCount"],
        "categoryTotals": manifest["categoryTotals"],
        "artifact": {
            "type": "PRODUCT_CATALOG",
            "releaseId": manifest["releaseId"],
            "fileName": manifest["approvedCsvFileName"],
            "format": "csv",
            "itemCount": manifest["declaredActiveSkuCount"],
            "sha256": manifest["approvedCsvSha256"],
        },
        "exhaustiveStatementEs": "El archivo CSV adjunto, no este resumen, es el resultado exhaustivo.",
        "exhaustiveStatementEn": "The attached CSV, not this short summary, is the exhaustive result.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--rollback", metavar="RELEASE_ID")
    args = parser.parse_args()
    if args.rollback:
        release = rollback(args.output, args.rollback)
    elif args.source is not None and args.manifest is not None:
        release = build(args.source, args.manifest, args.output, args.activate)
    else:
        parser.error("--source and --manifest are required unless --rollback is used")
    print(release)


if __name__ == "__main__":
    main()
