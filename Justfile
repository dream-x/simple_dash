# Modern alternative to Makefile.
# Install: brew install just
# Usage: just --list

set shell := ["sh", "-cu"]
set dotenv-load := true

python := env_var_or_default("PYTHON", "python3")
app := env_var_or_default("APP", "simple-dash")
config := env_var_or_default("CONFIG", "")
config_for_validate := if config == "" { "dashboard_config.json" } else { config }
config_arg := if config == "" { "" } else { "--config " + config }
output_dir := env_var_or_default("OUTPUT_DIR", ".")
output := env_var_or_default("OUTPUT", output_dir + "/index.html")
http_port := env_var_or_default("HTTP_PORT", "8080")
scan_interval := env_var_or_default("SCAN_INTERVAL", "60")
concurrency := env_var_or_default("CONCURRENCY", "64")
port_concurrency := env_var_or_default("PORT_CONCURRENCY", "512")
port_timeout := env_var_or_default("PORT_TIMEOUT", "0.35")
service_timeout := env_var_or_default("SERVICE_TIMEOUT", "1.2")
dns_timeout := env_var_or_default("DNS_TIMEOUT", "0.5")
netbios_timeout := env_var_or_default("NETBIOS_TIMEOUT", "0.45")
arp_timeout := env_var_or_default("ARP_TIMEOUT", "0.4")
discover_ports := env_var_or_default("DISCOVER_PORTS", "common")
ports_catalog := env_var_or_default("PORTS_CATALOG", "ports_catalog.json")
host_discovery := env_var_or_default("HOST_DISCOVERY", "arp")
discovery_concurrency := env_var_or_default("DISCOVERY_CONCURRENCY", "128")
discovery_timeout := env_var_or_default("DISCOVERY_TIMEOUT", "0.6")
snapshot_output := env_var_or_default("SNAPSHOT_OUTPUT", "dashboard_overrides.json")
pid_dir := env_var_or_default("PID_DIR", ".pids")
scanner_pid_file := pid_dir + "/scanner.pid"
server_pid_file := pid_dir + "/server.pid"
compose := env_var_or_default("COMPOSE", "docker compose")

# List commands
_default:
  @just --list

_args_paths := config_arg + " --output " + output + " --ports-catalog " + ports_catalog
_args_concurrency := " --concurrency " + concurrency + " --port-concurrency " + port_concurrency + " --discovery-concurrency " + discovery_concurrency
_args_timeouts := " --port-timeout " + port_timeout + " --service-timeout " + service_timeout + " --dns-timeout " + dns_timeout + " --netbios-timeout " + netbios_timeout + " --arp-timeout " + arp_timeout + " --discovery-timeout " + discovery_timeout
_args_discovery := " --discover-ports " + discover_ports + " --host-discovery " + host_discovery
_args := _args_paths + _args_concurrency + _args_timeouts + _args_discovery

# Generate index.html and data.json once
[group('local')]
generate subnets=env_var_or_default("SUBNETS", "") ports=env_var_or_default("PORTS", "") extra=env_var_or_default("EXTRA_ARGS", ""):
  @mkdir -p "{{output_dir}}"
  @ports_arg=""; [ -z "{{ports}}" ] || ports_arg="--ports {{ports}}"; \
  subnet_arg=""; [ -z "{{subnets}}" ] || subnet_arg="{{subnets}}"; \
  {{python}} generate_dashboard.py $subnet_arg {{_args}} $ports_arg {{extra}}

# Regenerate every SCAN_INTERVAL seconds, without rewriting if unchanged
[group('local')]
watch subnets=env_var_or_default("SUBNETS", "") ports=env_var_or_default("PORTS", "") extra=env_var_or_default("EXTRA_ARGS", ""):
  @mkdir -p "{{output_dir}}" "{{pid_dir}}"
  @ports_arg=""; [ -z "{{ports}}" ] || ports_arg="--ports {{ports}}"; \
  subnet_arg=""; [ -z "{{subnets}}" ] || subnet_arg="{{subnets}}"; \
  {{python}} generate_dashboard.py $subnet_arg {{_args}} $ports_arg --watch-interval {{scan_interval}} --pid-file "{{scanner_pid_file}}" {{extra}}

# Scan one host/IP with configured catalog ports. Add PORTS="..." for custom extra ports/ranges.
[group('local')]
scan-host ip ports=env_var_or_default("PORTS", "") extra=env_var_or_default("EXTRA_ARGS", ""):
  @mkdir -p "{{output_dir}}"
  @ports_arg=""; [ -z "{{ports}}" ] || ports_arg="--ports {{ports}}"; \
  {{python}} generate_dashboard.py "{{ip}}" {{_args}} $ports_arg {{extra}}

# Store discovered hosts/services into editable dashboard_overrides.json
[group('local')]
snapshot subnets=env_var_or_default("SUBNETS", "") ports=env_var_or_default("PORTS", "") extra=env_var_or_default("EXTRA_ARGS", ""):
  @mkdir -p "{{output_dir}}"
  @ports_arg=""; [ -z "{{ports}}" ] || ports_arg="--ports {{ports}}"; \
  subnet_arg=""; [ -z "{{subnets}}" ] || subnet_arg="{{subnets}}"; \
  {{python}} generate_dashboard.py $subnet_arg {{_args}} $ports_arg --snapshot-output "{{snapshot_output}}" {{extra}}

# Scan one host/IP with catalog ports and store editable overrides. Add PORTS="..." for custom extra ports/ranges.
[group('local')]
snapshot-host ip ports=env_var_or_default("PORTS", "") extra=env_var_or_default("EXTRA_ARGS", ""):
  @mkdir -p "{{output_dir}}"
  @ports_arg=""; [ -z "{{ports}}" ] || ports_arg="--ports {{ports}}"; \
  {{python}} generate_dashboard.py "{{ip}}" {{_args}} $ports_arg --snapshot-output "{{snapshot_output}}" {{extra}}

# Serve generated files locally without noisy BrokenPipe tracebacks
[group('local')]
serve:
  @mkdir -p "{{pid_dir}}"
  {{python}} serve_dashboard.py --port {{http_port}} --directory "{{output_dir}}" --pid-file "{{server_pid_file}}"

# Run watcher and HTTP server together
[group('local')]
dev subnets=env_var_or_default("SUBNETS", "") ports=env_var_or_default("PORTS", "") extra=env_var_or_default("EXTRA_ARGS", ""):
  @mkdir -p "{{output_dir}}" "{{pid_dir}}"
  @ports_arg=""; [ -z "{{ports}}" ] || ports_arg="--ports {{ports}}"; \
  subnet_arg=""; [ -z "{{subnets}}" ] || subnet_arg="{{subnets}}"; \
  scanner_pid=""; server_pid=""; \
  cleanup() { [ -z "$scanner_pid" ] || kill "$scanner_pid" 2>/dev/null || true; [ -z "$server_pid" ] || kill "$server_pid" 2>/dev/null || true; [ -z "$scanner_pid" ] || wait "$scanner_pid" 2>/dev/null || true; [ -z "$server_pid" ] || wait "$server_pid" 2>/dev/null || true; rm -f "{{scanner_pid_file}}" "{{server_pid_file}}"; }; \
  trap cleanup INT TERM EXIT; \
  {{python}} serve_dashboard.py --port {{http_port}} --directory "{{output_dir}}" --pid-file "{{server_pid_file}}" & \
  server_pid=$!; \
  sleep 0.2; \
  if ! kill -0 "$server_pid" 2>/dev/null; then wait "$server_pid"; exit $?; fi; \
  {{python}} generate_dashboard.py $subnet_arg {{_args}} $ports_arg --watch-interval {{scan_interval}} --pid-file "{{scanner_pid_file}}" {{extra}} & \
  scanner_pid=$!; \
  wait "$server_pid"

# Stop locally tracked Simple Dash processes via PID files
[group('local')]
stop-local:
  @for f in "{{scanner_pid_file}}" "{{server_pid_file}}"; do \
    if [ -f "$f" ]; then \
      pid=$(cat "$f" 2>/dev/null || echo ""); \
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then \
        kill "$pid" 2>/dev/null || true; \
        echo "Stopped pid $pid ($f)"; \
      fi; \
      rm -f "$f"; \
    fi; \
  done

# Validate Python and JSON config
[group('local')]
validate:
  {{python}} -m py_compile generate_dashboard.py serve_dashboard.py
  {{python}} -m json.tool "{{config_for_validate}}" >/dev/null
  @if [ ! -f dashboard_config.local.json ]; then :; else {{python}} -m json.tool dashboard_config.local.json >/dev/null; fi
  {{python}} -m json.tool "{{ports_catalog}}" >/dev/null
  @printf '%s\n' OK

# Run unit tests (stdlib unittest, no external deps)
[group('local')]
test:
  {{python}} -m unittest discover tests -v

# Remove generated local files
[group('local')]
clean:
  rm -f "{{output}}" "{{output_dir}}/data.json" "{{output}}.state.json"

# Build Docker image
[group('docker')]
docker-build:
  {{compose}} build

# Start via docker compose
[group('docker')]
docker-up:
  {{compose}} up -d --build

# Stop docker compose
[group('docker')]
docker-down:
  {{compose}} down

# Restart service
[group('docker')]
docker-restart:
  {{compose}} restart {{app}}

# Follow logs
[group('docker')]
docker-logs:
  {{compose}} logs -f {{app}}

# Shell inside container
[group('docker')]
docker-shell:
  {{compose}} exec {{app}} sh

# Stop and remove orphans
[group('docker')]
docker-clean:
  {{compose}} down --remove-orphans
