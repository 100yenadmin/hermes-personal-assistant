# Personal Assistant installed

Hermes installed the source tree but did not install its Python dependencies,
enable the plugin, start a job, or reload a running gateway.

1. Confirm the displayed source and full pinned revision are the approved ones.
2. Install the `python_dependencies` listed in `plugin.yaml` into this Hermes
   environment. Do not copy credentials or profile configuration into the
   plugin tree.
3. Run `scripts/probe_installed_version.py --json` and review the distinct
   installed, enabled, loaded, and exercised fields.
4. When the profile owner has approved activation, run
   `hermes plugins enable personal-assistant` and reload only at an agreed idle
   point. If conversation delivery is explicitly approved, install its packaged
   gateway startup hook into the approved profile first:

```bash
HERMES_HOME=/path/to/approved/profile \\
python3 ~/.hermes/plugins/personal-assistant/scripts/install_conversation_hook.py setup --dry-run --json
HERMES_HOME=/path/to/approved/profile \\
python3 ~/.hermes/plugins/personal-assistant/scripts/install_conversation_hook.py setup --json
```

The setup command copies only into
`$HERMES_HOME/hooks/personal-assistant-conversation-delivery-startup/`. It
reports the exact active profile, route validation and the separate host
permission `plugins.entries.personal-assistant.allow_gateway_injection`; it
never grants that permission. It never enables the plugin, creates jobs,
changes existing file modes, or restarts Hermes. Identical hook bytes are left
unchanged; different bytes are a collision and are not overwritten. After the
operator separately sets the host permission and exact route, restart
intentionally so Hermes discovers the hook.

5. Type `/pa setup` in a chat with the agent for a short guided setup.

Installation creates no cron jobs, reminders, calendar events, provider actions,
or downloads. The travel ledger remains in the profile at
`state/travel-ledger/travel.sqlite`.

Pinned revisions never move through `hermes plugins update`. After another full
commit SHA is approved, preserve local PA configuration with:

```bash
python3 ~/.hermes/plugins/personal-assistant/scripts/reinstall_pinned.py \
  --source 100yenadmin/hermes-personal-assistant \
  --ref <40-character-approved-commit>
```

The script force-reinstalls the approved Git revision with `--no-enable`, restores
only the documented local PA configuration names, and leaves reload/activation
to the operator.
