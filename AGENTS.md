# Project instructions for coding agents

## Documentation sync is mandatory

This is a local homelab project. When changing any user-facing behavior, command, config schema, generated UI, Docker/Just workflow, or feature in this repository:

1. Update **both** `README.md` (English, default) and `README.ru.md` (Russian) in the same change — they are translations of each other and must stay in sync.
2. Document new commands, env vars, config keys, examples, and troubleshooting notes.
3. Keep examples aligned with `Justfile`, `dashboard_config.json`, Docker files, and `generate_dashboard.py --help`.
4. If a feature is removed or renamed, remove/rename it in both READMEs.
5. Run at least:
   ```bash
   just validate
   just test
   ```
   before final response when possible. New behaviour added to `generate_dashboard.py` should come with a unit test in `tests/`.

Do not leave documentation stale after code/config changes.

## Simple Dash operator workflow

For day-to-day operation by other agents/teammates, use the project skill:

```text
.pi/skills/simple-dash-operator/SKILL.md
```

Default local setup:

```bash
cp .env.example .env
cp dashboard_config.json dashboard_config.local.json
just validate
just dev
```

Keep `.env`, `dashboard_config.local.json`, `dashboard_overrides.json`, `index.html`, `data.json`, and `*.state.json` out of git.

## Networking note

`serve_dashboard.py` listens on `0.0.0.0` and the dashboard is unauthenticated — it exposes IP/MAC/hostnames and service banners. Treat it as an inside-the-LAN tool: don't forward port 8080 through NAT, don't bind it to a public IP.
