"""Build once using the chosen interpreter and Hermes' pinned plugin installer."""
import os
import re
import subprocess
from pathlib import Path
import yaml
from .common import write


def plugin_source(value):
    source, sep, ref = value.rpartition("@")
    if not sep or not re.fullmatch(r"[0-9a-fA-F]{40}", ref):
        raise ValueError("plugin ref: expected source@40-character-commit-SHA")
    local = Path(source).expanduser()
    return (local.resolve().as_uri() if local.exists() else source), ref


def build(args):
    root, hermes = Path(args.out).resolve(), Path(args.hermes).resolve()
    home = root / "home"
    hh = home / ".hermes"
    hh.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, "HOME": str(home), "HERMES_HOME": str(hh), "PYTHONPATH": str(hermes), "HERMES_DISABLE_LAZY_INSTALLS": "1"}
    installed = []
    for spec in filter(None, (args.pa, args.hb2, args.fish)):
        source, ref = plugin_source(spec)
        subprocess.run([args.python, "-m", "hermes_cli.main", "plugins", "install", source,
                        "--ref", ref, "--no-enable", "--no-deps"], cwd=hermes, env=env,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        installed.append({"source": source, "ref": ref})
    names = sorted(yaml.safe_load(p.read_text())["name"] for p in (hh / "plugins").glob("*/plugin.yaml"))
    if "personal-assistant" not in names:
        raise ValueError("plugins: personal-assistant was not installed")
    config = {"model": {"provider": "openai-codex", "default": "gpt-6.1-sol"},
              "agent": {"reasoning_effort": "low", "service_tier": ""}, "plugins": {"enabled": names},
              # Built-in browser_* tools: the tripwire watches their clicks. Hermes' default Browser Use mode
              # (one browser_exec tool running Python) needs the terminal toolset, which the lab withholds.
              "browser": {"backend": "off", "allow_private_urls": False}, "tools": {"tool_search": False}}
    if getattr(args, "browser", "local") == "browserbase":
        # Real sites block bare headless Chromium; keys come from the runner's environment, never the home.
        config["browser"]["cloud_provider"] = "browserbase"
    (hh / "config.yaml").write_text(yaml.safe_dump(config))
    summary = {"names": names, "plugins": installed, "config": str(hh / "config.yaml")}
    write(root / "lab-home.json", summary)
    return summary
