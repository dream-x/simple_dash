**English** · [Русский](CONTRIBUTING.ru.md)

# Contributing to Simple Dash

Thanks for considering a contribution. Simple Dash is a small, dependency-free homelab tool, and the goal is to keep it that way: easy to read, easy to run, and safe to point at a home LAN.

---

## Ground rules

- **No third-party dependencies.** The generator and server use the Python **standard library only**. If a change needs a PyPI package, it almost certainly belongs outside this project — open an issue first to discuss.
- **Python 3.12+.** Matches the Docker base image (`python:3.12-slim`) and CI.
- **Both READMEs are part of the contract.** `README.md` (English) and `README.ru.md` (Russian) are translations of each other. Any user-facing change (CLI flags, `Justfile` recipes, env vars, config schema, Docker, UI) must update **both** in the same PR. See `.pi/skills/readme-sync/SKILL.md`.
- **Never commit runtime/private files.** `.env`, `dashboard_config.local.json`, `dashboard_overrides.json`, `index.html`, `data.json`, `*.state.json`, `.pids/`, `__pycache__/` are gitignored — keep it that way.

---

## Local setup

```bash
git clone git@github.com:dream-x/simple_dash.git
cd simple_dash
cp .env.example .env
cp dashboard_config.json dashboard_config.local.json   # put your real LAN here
just validate
just dev                                                # watcher + server on http://localhost:8080
```

`Justfile` is the canonical task runner (`brew install just`). It auto-loads `.env`. The same variables drive Docker Compose. Run `just --list` to see every recipe.

Iterate with **targeted scans** instead of full sweeps so you don't hammer the router:

```bash
just scan-host 192.168.1.152                  # one host, catalog ports
PORTS="8000-9000,32400" just scan-host 1.2.3.4
just test                                     # stdlib unittest suite
```

---

## Before you open a PR

Always run, and make sure both pass:

```bash
just validate   # py_compile + json.tool on configs and ports_catalog.json
just test       # unit tests (tests/)
```

CI (`.github/workflows/ci.yml`) runs the same two steps — a PR that fails them won't merge.

New behaviour in `generate_dashboard.py` should come with a unit test under `tests/` (stdlib `unittest`, no extra deps). Keep tests isolated — write generated artifacts to a `tempfile.TemporaryDirectory()`, not the working directory.

---

## Where things go

`generate_dashboard.py` is one file with five conceptual layers: config loading, host discovery, port scanning, service fingerprinting, and rendering. When you add something, thread it through every layer it touches:

| Change | Touch these |
|---|---|
| **New CLI flag** | `main()` argparse → `_args` in `Justfile` → `.env.example` → `append_arg` in `docker-entrypoint.sh` → both READMEs |
| **New config key** | the relevant `parse_*` / `*_from_dict` → `DashboardConfig` dataclass → `dashboard_json` (if it should appear in `data.json`) → both READMEs |
| **New service detection** | `detect_app` and/or `DEFAULT_SERVICE_DEFS` / `ports_catalog.json` |

Remember config inheritance: three files can be active at once — `dashboard_config.json` (public example) ← `dashboard_config.local.json` (private) ← `dashboard_overrides.json` (snapshot). The `DashboardConfig` dataclass is the merged result; don't assume a key in the public example is the live value.

---

## Design constraints (please respect)

- **No default full `1-65535` scan.** Discovery uses `ports_catalog.json` plus opt-in `PORTS` ranges. Wide scans on big networks hang routers.
- **ICMP/ARP are host-discovery only** — never surface them as a service health indicator in the UI. Service status is `online | auth | offline | error | unknown`, derived from TCP/HTTP probes.
- **`dashboard_config.json` is a safe public example.** Real network details belong in `dashboard_config.local.json`.
- **No auth, binds `0.0.0.0`.** This is an inside-the-LAN tool. Don't add features that assume it's safe to expose publicly.

---

## Commits & pull requests

- Keep PRs focused; one logical change per PR.
- Write clear commit messages (imperative subject, a body explaining *why* when it isn't obvious).
- In the PR description, note which README sections you updated and in which languages.
- Make sure `just validate` and `just test` are green.

---

## Reporting issues

When filing a bug, include: OS, Python version, the exact `just` recipe or command, the relevant `.env`/config (with private IPs/hostnames redacted), and what you expected vs. what happened.

**Security:** because the dashboard is unauthenticated and exposes network topology, please report security-sensitive issues privately to the maintainer rather than in a public issue.

---

## Releases

Maintainers cut releases by pushing a `v*` tag, which triggers `.github/workflows/docker-image.yml` (tests → multi-arch image to `ghcr.io` → GitHub Release). See the [Releases](README.md#releases) section of the README.

---

## License

By contributing, you agree that your contributions are licensed under the MIT License (see `LICENSE`).
