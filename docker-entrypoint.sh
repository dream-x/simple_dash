#!/bin/sh
set -eu

mkdir -p /data

if [ ! -f /data/dashboard_config.json ]; then
  cp /app/dashboard_config.json /data/dashboard_config.json
fi

if [ ! -f /data/ports_catalog.json ]; then
  cp /app/ports_catalog.json /data/ports_catalog.json
fi

SCAN_SUBNETS="${SUBNETS:-${SUBNET:-}}"
RUNTIME_ARGS=""

append_arg() {
  name="$1"
  value="$2"
  if [ -n "$value" ]; then
    RUNTIME_ARGS="$RUNTIME_ARGS $name $value"
  fi
}

append_arg "--discover-ports" "${DISCOVER_PORTS:-}"
append_arg "--ports" "${PORTS:-}"
append_arg "--host-discovery" "${HOST_DISCOVERY:-}"
append_arg "--concurrency" "${CONCURRENCY:-}"
append_arg "--port-concurrency" "${PORT_CONCURRENCY:-}"
append_arg "--port-timeout" "${PORT_TIMEOUT:-}"
append_arg "--service-timeout" "${SERVICE_TIMEOUT:-}"
append_arg "--dns-timeout" "${DNS_TIMEOUT:-}"
append_arg "--netbios-timeout" "${NETBIOS_TIMEOUT:-}"
append_arg "--arp-timeout" "${ARP_TIMEOUT:-}"
append_arg "--discovery-concurrency" "${DISCOVERY_CONCURRENCY:-}"
append_arg "--discovery-timeout" "${DISCOVERY_TIMEOUT:-}"

if [ -n "$SCAN_SUBNETS" ]; then
  python /app/generate_dashboard.py "$SCAN_SUBNETS" \
    --config /data/dashboard_config.json \
    --ports-catalog /data/ports_catalog.json \
    --output /data/index.html \
    --watch-interval "$SCAN_INTERVAL" \
    $RUNTIME_ARGS \
    ${EXTRA_ARGS:-} &
else
  python /app/generate_dashboard.py \
    --config /data/dashboard_config.json \
    --ports-catalog /data/ports_catalog.json \
    --output /data/index.html \
    --watch-interval "$SCAN_INTERVAL" \
    $RUNTIME_ARGS \
    ${EXTRA_ARGS:-} &
fi
scanner_pid=$!

python /app/serve_dashboard.py --port "$PORT" --directory /data &
server_pid=$!

stop() {
  kill "$scanner_pid" "$server_pid" 2>/dev/null || true
  wait "$scanner_pid" "$server_pid" 2>/dev/null || true
}

trap stop INT TERM EXIT
wait "$server_pid"
