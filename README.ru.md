[English](README.md) · **Русский**

# Simple Dash

> Статический Homer-like дашборд для homelab: автообнаружение сервисов, ручные ссылки, bookmarks, статусы, fingerprint приложений, Docker-запуск с пересканированием каждую минуту.

![Static](https://img.shields.io/badge/static-HTML%20%2B%20JSON-79f2c0)
![No backend](https://img.shields.io/badge/backend-none-7cc7ff)
![Docker](https://img.shields.io/badge/docker-ready-2496ed)
![Python](https://img.shields.io/badge/python-3.12%2B-ffd166)

> ⚠️ Дашборд показывает топологию сети (IP, MAC, hostnames, баннеры) **без аутентификации**. Используйте только во внутренней сети — не пробрасывайте 8080 за NAT и не вешайте на публичный IP.

---

## Что умеет

- автообнаружение портов в одной или нескольких подсетях;
- host discovery через ARP и/или ICMP, чтобы видеть машины без открытых сканируемых портов;
- ручные сервисы и bookmarks, всегда отображаются и проверяются;
- статусы `online | auth | offline | error | unknown` без ping (TCP connect + HTTP probe);
- fingerprint сервисов: HTTP status, `<title>`, `Server`/`X-Powered-By`, TCP banner, reverse DNS, NetBIOS;
- автоопределение Home Assistant, Grafana, Prometheus, Portainer, Proxmox, OpenWrt, MikroTik, TrueNAS, Jellyfin, Plex, Pi-hole, AdGuard и др.;
- favicons и иконки на карточках;
- 4 режима отображения: Machines / Subnets / Groups / Table, единый поиск по всем;
- duplicate groups: один физический девайс с разными IP в разных VLAN;
- snapshot обнаруженных хостов в редактируемый `dashboard_overrides.json`;
- watch-режим переписывает файлы только при изменениях;
- Docker + healthcheck.

---

## Быстрый старт

```bash
brew install just
cp .env.example .env
cp dashboard_config.json dashboard_config.local.json
just validate
just dev
```

Открыть:

```text
http://localhost:8080
```

Исходные файлы:

- `.env` — runtime-параметры (подсети, порт UI, discovery, concurrency);
- `dashboard_config.local.json` — приватная локальная настройка (subnets, manual, bookmarks, hosts);
- `dashboard_config.json` — безопасный публичный пример для git.

---

## Команды

```bash
just --list
```

| Команда | Что делает |
|---|---|
| `just dev` | watcher + локальный HTTP-сервер |
| `just generate` | один проход → `index.html` + `data.json` |
| `just watch` | пересканирование каждые `SCAN_INTERVAL` секунд, без перезаписи если ничего не поменялось |
| `just serve` | поднять HTTP-сервер для уже сгенерированных файлов (без шумных BrokenPipe) |
| `just stop-local` | остановить локальные процессы по PID-файлам в `.pids/` |
| `just validate` | py_compile + JSON-валидация конфигов |
| `just test` | запустить unit-тесты (`unittest` из стандартной библиотеки, без зависимостей) |
| `just clean` | удалить `index.html`, `data.json`, `*.state.json` |
| `just scan-host 192.168.1.10` | скан одного хоста с catalog-портами |
| `just snapshot` | сохранить найденное в `dashboard_overrides.json` |
| `just snapshot-host 192.168.1.10` | snapshot одного хоста |
| `just docker-up` / `docker-down` / `docker-logs` / `docker-restart` / `docker-shell` | Docker-обёртки |

Доп. порты/диапазоны передаются через `PORTS`:

```bash
PORTS="1883,32400,8000-9000" just scan-host 192.168.1.152
PORTS="8000-9000,32400" just snapshot-host 192.168.1.152
```

---

## `.env`

`Justfile` автоматически загружает `.env` (`set dotenv-load := true`); `docker-compose.yml` использует те же переменные через interpolation.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `HTTP_PORT` | `8080` | порт хоста для `just dev`/`serve` и Docker mapping |
| `PORT` | `8080` | внутренний порт контейнера |
| `SUBNETS` | пусто | подсети через запятую; пусто = берётся из конфига |
| `SCAN_INTERVAL` | `60` | интервал watch-скана в секундах |
| `DISCOVER_PORTS` | `common` | `none` или `common` (читает `ports_catalog.json`) |
| `PORTS` | пусто | дополнительные порты/диапазоны, например `8000-9000,32400` |
| `HOST_DISCOVERY` | `arp` | `none`, `arp`, `icmp`, `arp,icmp` |
| `CONCURRENCY` / `PORT_CONCURRENCY` / `DISCOVERY_CONCURRENCY` | `64` / `512` / `128` | параллелизм |
| `*_TIMEOUT` (`PORT`, `SERVICE`, `DNS`, `NETBIOS`, `ARP`, `DISCOVERY`) | секунды | таймауты |
| `CONFIG` | пусто | явный путь к конфигу; пусто = auto |
| `EXTRA_ARGS` | пусто | дополнительные raw CLI-аргументы для `generate_dashboard.py` |

---

## Конфигурация

Три источника, мердж в строгой последовательности:

```text
dashboard_config.json          публичный пример, в git
  ⬇ override
dashboard_config.local.json    приватный локальный, в .gitignore
  ⬇ overlay (snapshot)
dashboard_overrides.json       снимок обнаруженных хостов/сервисов
```

Все три опциональны. `services`/`manual_services`/`bookmarks`/`groups`/`hosts` мерджатся (поздние слои добавляются к ранним). Поведение `subnets`:

- `.local.json` **перезаписывает** `subnets` публичного `.json`;
- `dashboard_overrides.json` **никогда не перезаписывает** `subnets` (это снимок данных, не источник конфига).

С `--config <path>` мердж: `<path> ← dashboard_overrides.json`.

### Подсети, сервисы, ручные ссылки

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

Поля `services` / `manual_services` / `bookmarks`:

| Поле | Описание |
|---|---|
| `port` | TCP-порт (только для `services`) |
| `name` | название |
| `url` | кастомная ссылка, шаблоны `{ip}` и `{port}` поддерживаются (`services`); для `manual_services`/`bookmarks` — нормальный URL |
| `protocol` | `http`, `https` или пусто |
| `icon` | emoji, URL или путь к иконке |
| `group` | секция/категория |
| `tags` | массив тегов для фильтрации |
| `favicon` | пробовать favicon сервиса |

URL в `manual_services` и `bookmarks` валидируется: разрешены `http://`, `https://`, `mailto:`, `tel:` и любые `<scheme>://...`. `javascript:`/`data:` отклоняются.

`duplicates` помечают один физический девайс с разными IP — на карточках появляется бейдж `duplicate: <name>`.

### Снапшот

```bash
just snapshot                          # все подсети
just snapshot-host 192.168.1.152       # один хост
PORTS="8000-9000" just snapshot-host 192.168.1.152
```

Создаёт/обновляет `dashboard_overrides.json` — список найденных хостов и их сервисов. Файл можно править руками: имена, группы, иконки, protocol/url, tags, favicon. На следующем запуске он подмешивается поверх активного конфига.

### Каталог известных портов

`ports_catalog.json` — справочник homelab-портов для `DISCOVER_PORTS=common`. Можно расширять/редактировать. Формат — те же поля что и у `services`.

---

## Режимы отображения

- **Machines** (по умолчанию) — каждая физическая машина отдельным блоком, по клику раскрываются hostname, IP, MAC, ports и сервисы;
- **Subnets** — блоки подсетей, внутри каждого — машины;
- **Groups** — Homer-like по категориям (Infrastructure, Web, Apps, Monitoring и т.д.);
- **Table** — детальная таблица для диагностики.

Поиск работает во всех режимах: IP, hostname, MAC, порт, сервис, fingerprint, группа, duplicate group.

---

## Docker

`docker-compose.yml` берёт значения из `.env` через `${VAR:-default}`.

```bash
just docker-up       # build + up -d
just docker-logs     # follow logs
just docker-down     # stop
just docker-restart  # restart
just docker-shell    # sh внутри контейнера
```

Volume `./data:/data` хранит runtime-конфиг. При первом запуске контейнер копирует `dashboard_config.json` и `ports_catalog.json` в `/data/`, дальше можно править их там же.

`docker-entrypoint.sh` форвардит env-переменные в `generate_dashboard.py` как CLI-флаги (`DISCOVER_PORTS`, `PORTS`, `HOST_DISCOVERY`, concurrency, timeouts, `EXTRA_ARGS`).

---

## JSON API

Каждый ран генерирует `data.json` рядом с `index.html`:

```text
http://localhost:8080/data.json
```

Содержит подсети, порты, найденные хосты, сервисы, статусы, HTTP-коды, fingerprint, manual services, bookmarks, группы, duplicates.

---

## Watch-режим

```bash
just watch                # отдельно
SCAN_INTERVAL=60 just dev # вместе с сервером
```

Если результат не изменился, файлы не переписываются:

```text
No changes: 10 host(s), 17 discovered. Output was not rewritten
```

При ошибках (сеть упала, неверный конфиг) интервал удваивается до `8×nominal`, затем сбрасывается на следующем успешном проходе.

---

## Структура проекта

```text
generate_dashboard.py    основной генератор
serve_dashboard.py       тихий static-сервер без BrokenPipe tracebacks
dashboard_config.json    публичный пример конфига
ports_catalog.json       каталог известных homelab-портов
docker-compose.yml       Docker
docker-entrypoint.sh     watcher + serve_dashboard.py внутри контейнера
Dockerfile
Justfile                 task runner, грузит .env
.env.example             template runtime-переменных
tests/                   unit-тесты (unittest из стандартной библиотеки)
.github/workflows/       CI и публикация Docker-образа
.pi/skills/              project skills для агентов
AGENTS.md                инструкции агентам
```

Не коммитятся: `.env`, `dashboard_config.local.json`, `dashboard_overrides.json`, `index.html`, `data.json`, `*.state.json`, `.pids/`, `__pycache__/`.

---

## Почему не ping

Ping не используется как индикатор статуса в UI. Дашборд проверяет реальные сервисы — TCP connect, HTTP/HTTPS response, HTTP status, TCP banner. ICMP/ARP применяются только для host discovery (опционально), чтобы увидеть машины без открытых сканируемых портов.

---

## Troubleshooting

**`just: command not found`** → `brew install just`.

**Не видно устройств** → проверь подсети в конфиге, что нужные порты в `services` или `PORTS`, что firewall не блокирует.

**`Address already in use`** → `just stop-local` или другой порт: `HTTP_PORT=8090 just dev`.

**Скан долго висит** → уменьши параллелизм: `PORT_CONCURRENCY=128 CONCURRENCY=32 just generate`. Для нескольких `/24` лучше `DISCOVER_PORTS=common`, точечные порты — через `PORTS` на одном IP.

**На машине больше портов чем нашлось** → полный скан конкретного IP: `PORTS="1-65535" just scan-host 192.168.1.152`. Если результат нравится — `just snapshot-host 192.168.1.152`.

**Docker не видит конфиг** → конфиг лежит в volume `./data:/data`, файл `./data/dashboard_config.json`. Если его нет, контейнер скопирует дефолт из образа при следующем рестарте.

---

## Релизы

Push тэга `v*` (например `v0.1.0`) триггерит `.github/workflows/docker-image.yml`:

1. unit-тесты как гейт;
2. multi-arch образ собирается и публикуется в `ghcr.io/<owner>/<repo>:<tag>` и `:latest`;
3. автоматически создаётся GitHub Release с auto-generated changelog и командой `docker run`.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Ручной `workflow_dispatch` пересобирает образ, но release-шаг пропускается (нет тэга в контексте).

---

## Участие

Вклад приветствуется — см. [CONTRIBUTING.ru.md](CONTRIBUTING.ru.md). Коротко: только стандартная библиотека, Python 3.12+, держите оба README синхронными и запускайте `just validate` и `just test` перед открытием PR.

---

## Лицензия

MIT. См. `LICENSE`.
