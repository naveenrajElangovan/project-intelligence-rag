import json
from pathlib import Path


ROOT = Path(__file__).parents[1] / "corpora" / "T3B-COMPANY"


def _front_matter(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    return {
        key.strip(): value.strip()
        for line in lines[1:end]
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def test_every_department_has_policy_isolated_spanish_english_pair() -> None:
    manifest = json.loads((ROOT / "corpus-manifest.json").read_text())
    for department in manifest["departments"]:
        directory = ROOT / "departments" / department
        es = _front_matter(directory / "es.md")
        en = _front_matter(directory / "en.md")
        policy = f"department:T3B-COMPANY:{department}"
        assert es["access_policy_id"] == policy
        assert en["access_policy_id"] == policy
        assert es["section_id"] == en["section_id"]
        assert es["source_revision"] == en["source_revision"]
        assert es["translation_of"] == f"{es['section_id']}:en"
        assert en["translation_of"] == f"{en['section_id']}:es"
        assert "EVIDENCE_REQUIRED" in (directory / "es.md").read_text()
        assert "EVIDENCE_REQUIRED" in (directory / "en.md").read_text()


def test_synthetic_personas_cover_every_department_and_special_role() -> None:
    manifest = json.loads((ROOT / "corpus-manifest.json").read_text())
    personas = json.loads((ROOT / "test-personas.json").read_text())
    scopes = {
        scope
        for persona in personas["personas"]
        for scope in persona["departmentScopes"]
    }
    roles = {persona["projectRole"] for persona in personas["personas"]}
    assert set(manifest["departments"]) <= scopes
    assert {"CATALOG_PUBLISHER", "TECHNICAL_LEAD", None} <= roles
