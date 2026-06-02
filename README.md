**English** · [Русский](README.ru.md)

# Simple Dash

> A static, Homer-like dashboard for your homelab: service auto-discovery, manual links, bookmarks, status checks, application fingerprinting, and a one-container Docker run that re-scans every minute.

![Static](https://img.shields.io/badge/static-HTML%20%2B%20JSON-79f2c0)
![No backend](https://img.shields.io/badge/backend-none-7cc7ff)
![Docker](https://img.shields.io/badge/docker-ready-2496ed)
![Python](https://img.shields.io/badge/python-3.12%2B-ffd166)

> ⚠️ The dashboard exposes network topology (IPs, MACs, hostnames, banners) **without authentication**. Use it inside the LAN only — do not forward port 8080 through NAT and do not bind it to a public IP.

---

## Features

- port auto-discovery in one or more subnets;
- host discovery via ARP and/or ICMP, so machines without open scanned ports still show up;
- manual services and bookmarks, always rendered and probed;
- statuses `online | auth | offline | error | unknown` without ping (TCP connect + HTTP probe);
- service fingerprinting: HTTP status, `<title>`, `Server`/`X-Powered-By`, TCP banner, reverse DNS, NetBIOS;
- known-app detection: Home Assistant, Grafana, Prometheus, Portainer, Proxmox, OpenWrt, MikroTik, TrueNAS, Jellyfin, Plex, Pi-hole, AdGuard, and more;
- favicons and icons on cards;
- four views: Machines / Subnets / Groups / Table, with a unified search across all of them;
- duplicate groups: tag one physical device that lives on multiple IPs in different VLANs;
- snapshot of discovered hosts into an editable `dashboard_overrides.json`;
- watch mode rewrites files only when something actually changed;
- Docker + healthcheck.

---

## Quick start

```bash
brew install just
cp .env.example .env
cp dashboard_config.json dashboard_config.local.json
just validate
just dev
```

Open:

```text
http://localhost:8080
```

Source files:

- `.env` — runtime knobs (subnets, UI port, discovery, concurrency);
- `dashboard_config.local.json` — your private local setup (subnets, manual links, bookmarks, hosts);
- `dashboard_config.json` — safe public example, committed to git.

---

## Commands

```bash
just --list
```

| Command | What it does |
|---|---|
| `just dev` | watcher + local HTTP server |
| `just generate` | one-shot scan → `index.html` + `data.json` |
| `just watch` | re-scan every `SCAN_INTERVAL` seconds, rewrite only on change |
| `just serve` | serve already-generated files (no noisy BrokenPipe) |
| `just stop-local` | stop locally tracked processes via PID files in `.pids/` |
| `just validate` | py_compile + JSON validation of configs |
| `just test` | run unit tests (stdlib `unittest`, no extra deps) |
| `just clean` | remove `index.html`, `data.json`, `*.state.json` |
| `just scan-host 192.168.1.10` | scan a single host with catalog ports |
| `just snapshot` | save discovered state into `dashboard_overrides.json` |
| `just snapshot-host 192.168.1.10` | snapshot a single host |
| `just docker-up` / `docker-down` / `docker-logs` / `docker-restart` / `docker-shell` | Docker wrappers |

Extra ports/ranges go through `PORTS`:

```bash
PORTS="1883,32400,8000-9000" just scan-host 192.168.1.152
PORTS="8000-9000,32400" just snapshot-host 192.168.1.152
```

---

## `.env`

`Justfile` auto-loads `.env` (`set dotenv-load := true`); `docker-compose.yml` interpolates the same variables.

| Variable | Default | Purpose |
|---|---|---|
| `HTTP_PORT` | `8080` | host port for `just dev`/`serve` and Docker mapping |
| `PORT` | `8080` | container internal port |
| `SUBNETS` | empty | comma-separated subnets; empty = use config |
| `SCAN_INTERVAL` | `60` | watch-mode interval in seconds |
| `DISCOVER_PORTS` | `common` | `none` or `common` (loads `ports_catalog.json`) |
| `PORTS` | empty | extra ports/ranges, e.g. `8000-9000,32400` |
| `HOST_DISCOVERY` | `arp` | `none`, `arp`, `icmp`, `arp,icmp` |
| `CONCURRENCY` / `PORT_CONCURRENCY` / `DISCOVERY_CONCURRENCY` | `64` / `512` / `128` | parallelism |
| `*_TIMEOUT` (`PORT`, `SERVICE`, `DNS`, `NETBIOS`, `ARP`, `DISCOVERY`) | seconds | timeouts |
| `CONFIG` | empty | explicit config path; empty = auto |
| `EXTRA_ARGS` | empty | extra raw CLI flags for `generate_dashboard.py` |

---

## Configuration

Three sources, merged in a strict order:

```text
dashboard_config.json          public example, committed to git
  ⬇ override
dashboard_config.local.json    private local config, gitignored
  ⬇ overlay (snapshot)
dashboard_overrides.json       snapshot of discovered hosts/services
```

All three are optional. `services`/`manual_services`/`bookmarks`/`groups`/`hosts` are merged (later layers append to earlier ones). `subnets` behave specially:

- `.local.json` **overwrites** `subnets` from the public `.json`;
- `dashboard_overrides.json` **never** overwrites `subnets` (it is a data snapshot, not a config source).

With `--config <path>`, the merge is just `<path> ← dashboard_overrides.json`.

### Subnets, services, manual links

```json
{
  "subnets": ["192.168.1.0/24", "192.168.2.0/24"],
  "groups": [
    {"name": "Infrastructure", "icon": "🖧"},
    {"name": "Web", "icon": "🌐"},
    {"name": "Smart Home", "icon": "🏠"}
  ],
  "services": [
    {"port": 80, "name": "HTTP", "protocol": "http", "icon": "🌐", "group": "Web", "favicon": true},
    {"port": 8123, "name": "Home Assistant", "protocol": "http", "icon": "🏠", "group": "Smart Home", "favicon": true}
  ],
  "manual_services": [
    {"name": "Router", "url": "http://192.168.1.1", "group": "Infrastructure", "icon": "📡", "favicon": true}
  ],
  "bookmarks": [
    {"group": "Cloud", "items": [
      {"name": "GitHub", "url": "https://github.com"},
      {"name": "Cloudflare", "url": "https://dash.cloudflare.com", "icon": "☁"}
    ]}
  ],
  "hosts": {
    "192.168.1.1": {
      "name": "Router",
      "services": [
        {"port": 80, "name": "Router UI", "protocol": "http", "icon": "📡", "group": "Infrastructure"}
      ]
    },
    "aa:bb:cc:dd:ee:ff": "NAS"
  },
  "duplicates": [
    {"id": "main-router", "name": "Main Router", "hosts": ["192.168.10.1", "192.168.20.1"]}
  ]
}
```

`services` / `manual_services` / `bookmarks` fields:

| Field | Description |
|---|---|
| `port` | TCP port (for `services` only) |
| `name` | display name |
| `url` | custom link; `{ip}` and `{port}` templates supported (`services`); for `manual_services`/`bookmarks` — a regular URL |
| `protocol` | `http`, `https`, or empty |
| `icon` | emoji, URL, or icon path |
| `group` | section/category |
| `tags` | string array, used by filters/search |
| `favicon` | try the service's favicon |

URLs in `manual_services` and `bookmarks` are validated: `http://`, `https://`, `mailto:`, `tel:`, and any custom `<scheme>://...` are accepted. `javascript:` and `data:` are rejected.

`duplicates` mark one physical device with multiple IPs — cards show a `duplicate: <name>` badge.

### Snapshot

```bash
just snapshot                          # all subnets
just snapshot-host 192.168.1.152       # one host
PORTS="8000-9000" just snapshot-host 192.168.1.152
```

Creates/updates `dashboard_overrides.json` — the list of found hosts and their services. Edit by hand: names, groups, icons, protocol/url, tags, favicon. On the next run it is layered on top of the active config.

### Known-ports catalog

`ports_catalog.json` is the homelab port reference used by `DISCOVER_PORTS=common`. Extend/edit freely; fields match those of `services`.

---

## Views

- **Machines** (default) — each physical host as its own block, click to expand hostname/IP/MAC/ports/services;
- **Subnets** — subnet blocks with hosts inside;
- **Groups** — Homer-style by category (Infrastructure, Web, Apps, Monitoring, etc.);
- **Table** — detailed table for diagnostics.

Search works across all views: IP, hostname, MAC, port, service, fingerprint, group, duplicate group.

---

## Docker

`docker-compose.yml` reads values from `.env` via `${VAR:-default}`.

```bash
just docker-up       # build + up -d
just docker-logs     # follow logs
just docker-down     # stop
just docker-restart  # restart
just docker-shell    # sh inside the container
```

The `./data:/data` volume holds the runtime config. On first launch the container seeds `dashboard_config.json` and `ports_catalog.json` into `/data/`; you can edit them there afterwards.

`docker-entrypoint.sh` forwards env vars to `generate_dashboard.py` as CLI flags (`DISCOVER_PORTS`, `PORTS`, `HOST_DISCOVERY`, concurrency, timeouts, `EXTRA_ARGS`).

---

## JSON API

Every run produces `data.json` next to `index.html`:

```text
http://localhost:8080/data.json
```

It contains subnets, ports, discovered hosts, services, statuses, HTTP codes, fingerprints, manual services, bookmarks, groups, and duplicates.

---

## Watch mode

```bash
just watch                 # standalone
SCAN_INTERVAL=60 just dev  # together with the server
```

If the result is unchanged, files are not rewritten:

```text
No changes: 10 host(s), 17 discovered. Output was not rewritten
```

On errors (network down, bad config) the interval doubles up to `8× nominal`, then resets on the next successful pass.

---

## Project layout

```text
generate_dashboard.py    main generator
serve_dashboard.py       quiet static server (suppresses BrokenPipe tracebacks)
dashboard_config.json    public config example
ports_catalog.json       homelab known-ports catalog
docker-compose.yml       Docker
docker-entrypoint.sh     watcher + serve_dashboard.py inside the container
Dockerfile
Justfile                 task runner, loads .env
.env.example             runtime-variables template
tests/                   unit tests (stdlib unittest)
.github/workflows/       CI and Docker image publishing
.pi/skills/              project skills for agents
AGENTS.md                agent instructions
```

Never committed: `.env`, `dashboard_config.local.json`, `dashboard_overrides.json`, `index.html`, `data.json`, `*.state.json`, `.pids/`, `__pycache__/`.

---

## Why no ping

Ping is not used as a status indicator in the UI. The dashboard probes real services — TCP connect, HTTP/HTTPS response, HTTP status, TCP banner. ICMP/ARP are used only for host discovery (optional), so machines without open scanned ports still appear.

---

## Troubleshooting

**`just: command not found`** → `brew install just`.

**No devices visible** → check the subnets in your config, that the relevant ports are in `services` or `PORTS`, and that the firewall is not blocking.

**`Address already in use`** → `just stop-local`, or use a different port: `HTTP_PORT=8090 just dev`.

**Scan hangs / runs too long** → reduce parallelism: `PORT_CONCURRENCY=128 CONCURRENCY=32 just generate`. For multiple `/24` networks prefer `DISCOVER_PORTS=common`, and probe targeted ports via `PORTS` on a single IP.

**A host has more ports than were found** → full scan of one IP: `PORTS="1-65535" just scan-host 192.168.1.152`. If you like the result, persist it: `just snapshot-host 192.168.1.152`.

**Docker can't find the config** → it lives in the `./data:/data` volume at `./data/dashboard_config.json`. If absent, the container seeds the default from the image on the next restart.

---

## Releases

Pushing a `v*` tag (e.g. `v0.1.0`) triggers `.github/workflows/docker-image.yml`:

1. unit tests run as a gate;
2. multi-arch image is built and pushed to `ghcr.io/<owner>/<repo>:<tag>` and `:latest`;
3. a GitHub Release is created automatically with auto-generated notes and the image pull command.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Manual `workflow_dispatch` rebuilds the image but skips the GitHub Release step (no tag context).

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). In short: standard library only, Python 3.12+, keep both READMEs in sync, and run `just validate` and `just test` before opening a PR.

---

## License

MIT. See `LICENSE`.
