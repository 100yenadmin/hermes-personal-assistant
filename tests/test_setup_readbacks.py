import hashlib

import pytest

from personal_assistant import setup
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger

START = b"<!-- personal-assistant:start -->"
END = b"<!-- personal-assistant:end -->"


def write(path, content=b"Synthetic\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def propose(ledger, targets):
    setup.propose(ledger, [{"target": target, "summary": "Synthetic"} for target in targets])


@pytest.mark.parametrize("target,relative,extra", [
    ("user_memory", "memories/USER.md", {}),
    ("soul_section", "SOUL.md", {}),
    ("manual_skill", "skills/group/manual/SKILL.md", {"skill": "manual"}),
    ("manual_skill", "skills/manual/SKILL.md", {"path": "skills/manual/SKILL.md"}),
    ("context_file", "project/AGENTS.md", {})])
def test_each_target_resolves_and_hashes(tmp_path, target, relative, extra):
    ledger = Ledger(tmp_path)
    content = START + b"\nSynthetic\n" + END if target == "soul_section" else b"Synthetic\r\n"
    path = write(tmp_path / relative, content)
    if target == "context_file":
        extra = {"path": str(path)}
    propose(ledger, [target])
    result = setup.applied(ledger, [{"target": target, **extra}])["applied"]
    assert result == [{"target": target, "sha256": hashlib.sha256(content).hexdigest(),
                       "path": str(path), "bytes": len(content)}]
    assert setup.state(Ledger(tmp_path))["applied"] == result


@pytest.mark.parametrize("target,extra", [("user_memory", {}), ("soul_section", {}),
    ("manual_skill", {"skill": "missing"}), ("context_file", {"path": "missing"})])
def test_missing_readback_names_target_and_keeps_proposal(tmp_path, target, extra):
    ledger = Ledger(tmp_path)
    propose(ledger, [target])
    if target == "context_file":
        extra = {"path": str(tmp_path / "missing")}
    prior = setup.state(ledger)
    with pytest.raises(ValueError, match=target):
        setup.applied(ledger, [{"target": target, **extra}])
    assert setup.state(ledger) == prior


@pytest.mark.parametrize("content", [b"", b" \n"])
def test_user_memory_must_be_nonempty(tmp_path, content):
    ledger = Ledger(tmp_path)
    write(tmp_path / "memories/USER.md", content)
    propose(ledger, ["user_memory"])
    with pytest.raises(ValueError, match="user_memory"):
        setup.applied(ledger, [{"target": "user_memory"}])


@pytest.mark.parametrize("content", [b"Synthetic", START, END, END + START])
def test_soul_requires_ordered_markers(tmp_path, content):
    ledger = Ledger(tmp_path)
    write(tmp_path / "SOUL.md", content)
    propose(ledger, ["soul_section"])
    with pytest.raises(ValueError, match="soul_section"):
        setup.applied(ledger, [{"target": "soul_section"}])


def test_soul_hash_covers_only_marked_section(tmp_path):
    ledger = Ledger(tmp_path)
    section = START + b"\nSynthetic\n" + END
    path = write(tmp_path / "SOUL.md", b"Persona\n" + section + b"\nOther")
    propose(ledger, ["soul_section"])
    first = setup.applied(ledger, [{"target": "soul_section"}])["applied"]
    write(path, b"Changed persona\n" + section + b"\nChanged other")
    propose(ledger, ["soul_section"])
    assert setup.applied(ledger, [{"target": "soul_section"}])["applied"] == first
    assert first[0]["sha256"] == hashlib.sha256(section).hexdigest()
    assert first[0]["bytes"] == len(section)


def test_manual_skill_ambiguity_requires_explicit_path(tmp_path):
    ledger = Ledger(tmp_path)
    one = write(tmp_path / "skills/one/manual/SKILL.md")
    write(tmp_path / "skills/two/manual/SKILL.md")
    propose(ledger, ["manual_skill"])
    with pytest.raises(ValueError, match="manual_skill"):
        setup.applied(ledger, [{"target": "manual_skill", "skill": "manual"}])
    assert setup.applied(ledger, [{"target": "manual_skill", "path": str(one)}])["status"] == "applied"


@pytest.mark.parametrize("relative", ["SOUL.md", "skills/../SOUL.md"])
def test_manual_path_escape_rejected(tmp_path, relative):
    ledger = Ledger(tmp_path)
    write(tmp_path / "SOUL.md")
    (tmp_path / "skills").mkdir()
    propose(ledger, ["manual_skill"])
    with pytest.raises(ValueError, match="manual_skill"):
        setup.applied(ledger, [{"target": "manual_skill", "path": str(tmp_path / relative)}])


@pytest.mark.parametrize("target,relative,directory", [
    ("user_memory", "memories/USER.md", False), ("soul_section", "SOUL.md", False),
    ("manual_skill", "skills/manual/SKILL.md", False),
    ("manual_skill", "skills", True), ("context_file", "project/AGENTS.md", False)])
def test_symlink_escape_rejected(tmp_path, target, relative, directory):
    root = tmp_path / "profile"
    root.mkdir()
    ledger = Ledger(root)
    outside = write(tmp_path / "outside/SKILL.md")
    link = root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside.parent if directory else outside, target_is_directory=directory)
    path = link / "SKILL.md" if directory else link
    propose(ledger, [target])
    with pytest.raises(ValueError, match=target):
        setup.applied(ledger, [{"target": target, "path": str(path)}])


def test_full_apply_dispatch_ignores_model_hash_and_uses_profile_root(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "wrong-profile"))
    paths = {"user_memory": write(profile / "memories/USER.md"),
             "soul_section": write(profile / "SOUL.md", START + b"Synthetic" + END),
             "manual_skill": write(profile / "skills/manual/SKILL.md"),
             "context_file": write(tmp_path / "project/AGENTS.md")}
    dispatch(profile, {"operation": "setup", "data": {"action": "propose", "writes": [
        {"target": target, "summary": "Synthetic"} for target in [*paths, "pa_preferences"]]}})
    result = dispatch(profile, {"operation": "setup", "data": {"action": "applied", "session_id": "untrusted",
        "readbacks": [{"target": target, "sha256": "unavailable", **(
            {"skill": "manual"} if target == "manual_skill" else
            {"path": str(path)} if target == "context_file" else {})} for target, path in paths.items()]}},
        runtime_scope={"session_id": "trusted"})
    assert result["status"] == "applied" and result["applied_session_id"] == "trusted"
    for receipt in result["applied"]:
        assert receipt["sha256"] == hashlib.sha256(paths[receipt["target"]].read_bytes()).hexdigest()
    assert "PA reads back the files and computes hashes" in SCHEMA["parameters"]["properties"]["data"]["description"]


@pytest.mark.parametrize("content", [END + START + END, START + END + START + END, START + START + END])
def test_soul_rejects_ambiguous_markers(tmp_path, content):
    # The skill shows ambiguous markers as a conflict; the readback must not pick one block.
    ledger = Ledger(tmp_path)
    write(tmp_path / "SOUL.md", b"Persona\n" + content)
    propose(ledger, ["soul_section"])
    with pytest.raises(ValueError, match="soul_section"):
        setup.applied(ledger, [{"target": "soul_section"}])
    assert setup.state(ledger)["status"] == "proposed"


def test_manual_path_must_be_skill_md(tmp_path):
    ledger = Ledger(tmp_path)
    write(tmp_path / "skills/manual/README.md", b"Synthetic")
    propose(ledger, ["manual_skill"])
    with pytest.raises(ValueError, match="manual_skill"):
        setup.applied(ledger, [{"target": "manual_skill", "path": "skills/manual/README.md"}])


def test_oversized_readback_is_rejected(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path)
    write(tmp_path / "memories/USER.md", b"x" * 65)
    monkeypatch.setattr(setup, "READBACK_MAX_BYTES", 64)
    propose(ledger, ["user_memory"])
    with pytest.raises(ValueError, match="user_memory: file is too large"):
        setup.applied(ledger, [{"target": "user_memory"}])
