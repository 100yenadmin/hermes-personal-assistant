"""Static contracts for optional Chief of Staff guidance; no profile access."""
import json
from pathlib import Path
import re

import pytest
import yaml

from personal_assistant.entry import SCHEMA


ROOT = Path(__file__).resolve().parents[1]
COS_SKILLS = ("cos-daily", "cos-weekly", "cos-scout", "cos-radar")
OPERATIONS = set(SCHEMA["parameters"]["properties"]["operation"]["enum"])
STATE_REFERENCE = ROOT / "skills/cos-weekly/references/recommendation-state.md"


def check_operations_and_no_install(text):
    operations = set(re.findall(r'pa\(\s*operation="([a-z_]+)"', text))
    assert operations, "expected concrete PA calls"
    assert operations <= OPERATIONS, operations - OPERATIONS
    without_prohibition = re.sub(r"\bnever install\b", "", text, flags=re.I)
    assert not re.search(r"\binstall\b", without_prohibition, flags=re.I)


@pytest.mark.parametrize("name", COS_SKILLS)
def test_cos_skill_contract(name):
    path = ROOT / "skills" / name / "SKILL.md"
    assert path.is_file()
    assert path.stat().st_size < 6000
    text = path.read_text()
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == name
    assert frontmatter["description"]
    assert frontmatter["metadata"]["openclaw"]["skillKey"] == name
    metadata = frontmatter["metadata"]["hermes"]
    assert metadata["pa_mode"] == "chief_of_staff"
    assert metadata["category"] == "productivity" and metadata["tags"]
    assert "pa_mode: chief_of_staff" in text
    assert f"cos:{name.removeprefix('cos-')}:" in text  # its stable note ID
    assert "/pa mode chief-of-staff on" in text
    assert "recommendation-state.md" in text
    check_operations_and_no_install(text)


def test_shared_state_reference_uses_real_operations():
    check_operations_and_no_install(STATE_REFERENCE.read_text())


def test_pa_setup_cos_guidance_uses_real_operations():
    text = (ROOT / "skills/pa-setup/SKILL.md").read_text()
    check_operations_and_no_install(text)
    assert '"section":"chief_of_staff"' in text
    assert "/pa mode chief-of-staff on" in text
    for name in ("question-bank.md", "where-answers-go.md"):
        reference = (ROOT / "skills/pa-setup/references" / name).read_text()
        assert "cos_" in reference
        if 'pa(operation=' in reference:
            check_operations_and_no_install(reference)


def test_cos_inventory_is_optional():
    from scripts import probe_installed_version, validate_pack

    optional = set(COS_SKILLS)
    assert not optional & set(probe_installed_version.REQUIRED_SKILLS)
    assert not optional & validate_pack.REQUIRED_SKILLS
    component = json.loads((ROOT / "support-control/component.json").read_text())
    assert set(component["optional_skills"]["chief_of_staff"]) == optional
    assert not optional & set(component["required_skills"])
    for path in (ROOT / "openclaw.plugin.json",
                 ROOT / "skills/travel-action-pack-manifest/openclaw.plugin.json"):
        inventory = json.loads(path.read_text())["skills"]
        assert optional <= {Path(item).name for item in inventory}
