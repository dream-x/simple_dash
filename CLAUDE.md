# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Start Dash is a static, no-backend home-LAN dashboard. A single Python script (`generate_dashboard.py`, ~1800 lines, no third-party dependencies) scans configured subnets, fingerprints services on open TCP ports, and writes `index.html` + `data.json` next to itself. `serve_dashboard.py` is a thin static server that swallows browser-cancel `BrokenPipeError` traces.

There is no build step. There is no framework. Edits to the generator immediately affect HTML output on the next run.

## Common commands

`Justfile` is the canonical task runner. It auto-loads `.env` (`set dotenv-load := true`), and Docker Compose interpolates the same vars.

```bash
just dev          # watcher + serve_dashboard.py together
just generate     # one-shot scan → index.html + data.json
just watch        # repeated scans every SCAN_INTERVAL; rewrites only on change
just serve        # serve already-generated files
just validate     # py_compile + json.tool on configs and ports_catalog.json
just stop-local   # pkill leftover generate_dashboard.py / serve_dashboard.py
just clean        # remove index.html, data.json, *.state.json
```

Targeted scans (use these instead of full sweeps when iterating):

```bash
just scan-host 192.168.1.152                      # one host, catalog ports
PORTS="8000-9000,32400" just scan-host 1.2.3.4    # add ad-hoc ports/ranges
just snapshot                                     # write dashboard_overrides.json
just snapshot-host 192.168.1.152                  # snapshot a single host
```

Docker (uses `docker-compose.yml` + `docker-entrypoint.sh`, runs watcher + server in one container, persists state under `./data:/data`):

```bash
just docker-up / docker-down / docker-logs / docker-restart / docker-shell
```

Unit tests live in `tests/` and use stdlib `unittest` (no extra deps). `just test` runs the suite; `just validate` covers Python syntax + JSON parsing of configs. CI (`.github/workflows/ci.yml`) runs both. A second workflow (`docker-image.yml`) builds and pushes a multi-arch image to ghcr.io on `v*` tags.

## Architecture

### Single-file generator

`generate_dashboard.py` is one file with five conceptual layers:

1. **Config loading** (`load_config`, `load_runtime_config`): merges in priority order — `dashboard_config.json` (public example, in git) ← `dashboard_config.local.json` (private, used automatically when present) ← `dashboard_overrides.json` (snapshot of discovered hosts/services, also auto-applied when present). `ports_catalog.json` supplies the `DISCOVER_PORTS=common` port set and is merged via `setdefault` so config keys win.
2. **Host discovery** (`discover_host_ips`, `arp_table_ips`, `icmp_probe`): controlled by `--host-discovery none|arp|icmp|arp,icmp`. Adds machines that have no scanned open ports. **No ping is shown as a service status** — discovery probes are not surfaced in UI.
3. **Port scanning** (`scan_hosts`, `scan_host`, `check_port_latency`): asyncio TCP-connect with two semaphores — per-host (`--concurrency`) and global (`--port-concurrency`). Lower these if a router gets noisy.
4. **Service fingerprinting** (`probe_service`, `probe_http`, `probe_banner`, `detect_app`): HTTP status/title/`Server`/`X-Powered-By` headers, TCP banner, reverse DNS, NetBIOS. Maps signatures to known apps (Home Assistant, Grafana, Plex, etc.).
5. **Rendering** (`render`, `render_machine_sections`, `render_subnet_sections`, `collect_cards`, `dashboard_json`): emits self-contained HTML with inline CSS/JS plus `data.json`. Four UI modes — Machines (default), Subnets, Groups, Table — are all generated in one pass; the front-end JS toggles them client-side.

### State and idempotency

`write_if_changed` (file-level) and the `*.state.json` signature file (run-level, via `dashboard_signature`) keep `index.html` / `data.json` byte-stable when the scan result is unchanged. This matters for git, Docker volumes, and watch mode — the README's "No changes: ... Output was not rewritten" message comes from here.

### Config inheritance is real

When editing config-handling code, remember that three config files can be active simultaneously and that the `DashboardConfig` dataclass is the merged result. Don't assume a key in `dashboard_config.json` is the live value — check `dashboard_config.local.json` and `dashboard_overrides.json` first. `--config <path>` overrides this auto-discovery.

### Docker entrypoint

`docker-entrypoint.sh` copies `dashboard_config.json` and `ports_catalog.json` into `/data/` on first run, then runs both the watcher and `serve_dashboard.py`. It forwards env vars (`DISCOVER_PORTS`, `PORTS`, `HOST_DISCOVERY`, concurrency/timeouts, `EXTRA_ARGS`) as CLI flags to the generator. `EXTRA_ARGS` is the escape hatch for any flag not yet promoted to env.

## Project-specific rules (from AGENTS.md and skill files)

- **Both READMEs are part of the contract.** The repo ships `README.md` (English, default) and `README.ru.md` (Russian) — they are translations of each other and must be updated together for any user-facing change (CLI flags, `Justfile` recipes, env vars, config schema, Docker, UI). `.pi/skills/readme-sync/SKILL.md` enforces this.
- **Never commit runtime/private files:** `.env`, `dashboard_config.local.json`, `dashboard_overrides.json`, `index.html`, `data.json`, `*.state.json`, `__pycache__/`. They are gitignored — keep it that way.
- **Do not introduce a default full `1-65535` scan.** Discovery uses `ports_catalog.json` plus opt-in `PORTS` ranges. Wide scans on big networks hang routers.
- **ICMP/ARP are host-discovery only** — never present them as a service health indicator in the UI. Service status is `online | auth | offline | error | unknown` derived from TCP/HTTP probes.
- **`dashboard_config.json` is a safe public example.** Local network details belong in `dashboard_config.local.json`.
- **The dashboard has no auth and `serve_dashboard.py` binds `0.0.0.0`.** Inside-the-LAN tool only — never forward 8080 publicly.

## Useful pointers when changing things

- New CLI flag → add to `main()` argparse, thread through `_args` in `Justfile`, expose in `.env.example`, forward in `docker-entrypoint.sh`'s `append_arg` block, document in both `README.md` and `README.ru.md`.
- New config key → parse in the appropriate `parse_*` / `*_from_dict` function, add to `DashboardConfig` dataclass, surface in `dashboard_json` if it should appear in `data.json`, document in both `README.md` and `README.ru.md`.
- New service detection → extend `detect_app` and/or `DEFAULT_SERVICE_DEFS` / `ports_catalog.json`.
- Always run `just validate` and `just test` before handing off. Add a unit test under `tests/` for new behaviour in `generate_dashboard.py`.
