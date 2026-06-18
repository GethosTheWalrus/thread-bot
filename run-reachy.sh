#!/bin/sh
# Start the Reachy stack (daemon, worker, bridge) on the Raspberry Pi.
# Usage:
#   ./run-reachy.sh          start all three services
#   ./run-reachy.sh stop     stop all three services
#   ./run-reachy.sh restart  restart all three services
set -e

cd "$(dirname "$0")"

case "${1:-start}" in
  start)
    docker compose --profile reachy up -d --no-build reachy-daemon reachy-worker reachy-bridge
    ;;
  stop)
    docker compose --profile reachy stop reachy-daemon reachy-worker reachy-bridge
    ;;
  restart)
    docker compose --profile reachy restart reachy-daemon reachy-worker reachy-bridge
    ;;
  *)
    echo "Usage: $0 {start|stop|restart}" >&2
    exit 1
    ;;
esac

docker compose --profile reachy ps