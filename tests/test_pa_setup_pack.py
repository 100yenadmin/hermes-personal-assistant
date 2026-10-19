from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_manual_template_description_fits_skill_manage_create_limit():
    template = (ROOT / "skills/pa-setup/references/manual-template.md").read_text()
    skill = template.split("```markdown\n", 1)[1].split("```", 1)[0]
    _, frontmatter, _ = skill.split("---", 2)
    description = yaml.safe_load(frontmatter)["description"]

    assert isinstance(description, str)
    assert 0 < len(description) <= 60
