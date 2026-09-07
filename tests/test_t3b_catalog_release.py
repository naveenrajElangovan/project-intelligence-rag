import csv
import json

import pytest

from tools.t3b_catalog_release import (
    CatalogValidationError,
    REQUIRED_COLUMNS,
    build,
    rollback,
    sha256_bytes,
)


def _source(tmp_path, rows):
    path = tmp_path / "source.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _row(sku="SKU-1", category="FOOD"):
    return {
        "sku": sku,
        "name_es": "Producto",
        "name_en": "Product",
        "brand": "Marca",
        "category_code": category,
        "category_es": "Alimentos",
        "category_en": "Food",
        "subcategory_code": "PANTRY",
        "subcategory_es": "Despensa",
        "subcategory_en": "Pantry",
        "presentation_es": "1 pieza",
        "presentation_en": "1 item",
        "assortment_type": "CORE",
        "lifecycle_state": "ACTIVE",
        "availability_scope": "NATIONAL",
        "regions": "ALL",
        "effective_date": "2026-09-06",
    }


def _manifest(tmp_path, source, count=1, totals=None):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "releaseId": "2026-09-06.1",
                "effectiveDate": "2026-09-06",
                "declaredActiveSkuCount": count,
                "categoryTotals": totals or {"FOOD": count},
                "sourceCsvSha256": sha256_bytes(source.read_bytes()),
                "approver": "publisher-object-id",
                "sourceSystemVersion": "erp-42",
            }
        )
    )
    return path


def test_build_creates_immutable_bilingual_release_and_atomic_pointer(tmp_path) -> None:
    source = _source(tmp_path, [_row("SKU-1"), _row("SKU-2")])
    manifest = _manifest(tmp_path, source, count=2)

    release = build(source, manifest, tmp_path / "catalog", activate=True)

    approved = release / "t3b-products-2026-09-06.1.csv"
    built_manifest = json.loads((release / "manifest.json").read_text())
    answer = json.loads((release / "answer-contract.json").read_text())
    assert built_manifest["declaredActiveSkuCount"] == 2
    assert built_manifest["spanishProductCount"] == 2
    assert built_manifest["englishProductCount"] == 2
    assert built_manifest["approvedCsvSha256"] == sha256_bytes(approved.read_bytes())
    assert answer["artifact"]["itemCount"] == 2
    assert answer["exhaustiveStatementEs"].startswith("El archivo CSV adjunto")
    assert json.loads((tmp_path / "catalog" / "active-release.json").read_text())["releaseId"] == "2026-09-06.1"
    assert (release / "productos-2026-09-06.1-es.md").read_text().count("section_id: `product:") == 2
    assert (release / "products-2026-09-06.1-en.md").read_text().count("section_id: `product:") == 2

    assert rollback(tmp_path / "catalog", "2026-09-06.1") == release

    with pytest.raises(CatalogValidationError, match="already exists"):
        build(source, manifest, tmp_path / "catalog", activate=False)


def test_release_rejects_count_category_checksum_and_duplicate_failures(tmp_path) -> None:
    source = _source(tmp_path, [_row("SKU-1"), _row("SKU-1")])
    manifest = _manifest(tmp_path, source, count=2)
    with pytest.raises(CatalogValidationError, match="Duplicate SKU"):
        build(source, manifest, tmp_path / "catalog", activate=False)

    source = _source(tmp_path, [_row("SKU-1")])
    manifest = _manifest(tmp_path, source, count=2)
    with pytest.raises(CatalogValidationError, match="count differs"):
        build(source, manifest, tmp_path / "catalog-2", activate=False)

    manifest = _manifest(tmp_path, source, count=1, totals={"OTHER": 1})
    with pytest.raises(CatalogValidationError, match="Category totals disagree"):
        build(source, manifest, tmp_path / "catalog-3", activate=False)


def test_release_rejects_inactive_skus(tmp_path) -> None:
    row = _row()
    row["lifecycle_state"] = "DISCONTINUED"
    source = _source(tmp_path, [row])
    manifest = _manifest(tmp_path, source)
    with pytest.raises(CatalogValidationError, match="not ACTIVE"):
        build(source, manifest, tmp_path / "catalog", activate=False)


def test_release_rejects_missing_bilingual_and_regional_fields(tmp_path) -> None:
    row = _row()
    row["name_en"] = ""
    source = _source(tmp_path, [row])
    manifest = _manifest(tmp_path, source)
    with pytest.raises(CatalogValidationError, match="name_en"):
        build(source, manifest, tmp_path / "catalog-bilingual", activate=False)

    row = _row()
    row["availability_scope"] = "REGIONAL"
    row["regions"] = "|||"
    source = _source(tmp_path, [row])
    manifest = _manifest(tmp_path, source)
    with pytest.raises(CatalogValidationError, match="requires one or more regions"):
        build(source, manifest, tmp_path / "catalog-regional", activate=False)


def test_release_rejects_source_checksum_mismatch(tmp_path) -> None:
    source = _source(tmp_path, [_row()])
    manifest = _manifest(tmp_path, source)
    values = json.loads(manifest.read_text())
    values["sourceCsvSha256"] = "0" * 64
    manifest.write_text(json.dumps(values))

    with pytest.raises(CatalogValidationError, match="checksum does not match"):
        build(source, manifest, tmp_path / "catalog", activate=False)


def test_failed_checksum_rollback_preserves_active_pointer(tmp_path) -> None:
    source = _source(tmp_path, [_row()])
    manifest = _manifest(tmp_path, source)
    catalog = tmp_path / "catalog"
    release = build(source, manifest, catalog, activate=True)
    pointer_before = (catalog / "active-release.json").read_bytes()
    approved = release / "t3b-products-2026-09-06.1.csv"
    approved.write_bytes(approved.read_bytes() + b"corrupt")

    with pytest.raises(CatalogValidationError, match="failed checksum verification"):
        rollback(catalog, "2026-09-06.1")

    assert (catalog / "active-release.json").read_bytes() == pointer_before
