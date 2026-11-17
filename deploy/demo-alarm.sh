#!/bin/sh
# Temperature alarm on demand for a live demo (only for a stand filled by seed-demo).
#   sh deploy/demo-alarm.sh        — restart the demo simulator with «door_left_open» on demo-fridge-1:
#                                    alarm ≈ 5 min after the command, recovery ≈ 13–14 min after it;
#   sh deploy/demo-alarm.sh stop   — back to the usual demo program.
# The readings go through the public ingest like a real device, so the incident, the notification event and the
# Telegram message (if a bot and recipients are configured) are the real ones. Run from the repository root.
set -eu
docker rm -f coldkeeper-alarm >/dev/null 2>&1 || true
if [ "${1:-}" = "stop" ]; then
	docker compose --profile demo up -d simulator
	exit 0
fi
docker compose --profile demo stop simulator
docker compose --profile demo run -d --rm --name coldkeeper-alarm simulator \
	coldkeeper-sim live --url http://proxy --scenario demo-fridge-1=door_left_open
echo "Сценарий запущен: тревога по «Холодильный шкаф №1» примерно через 5 минут. Вернуть обычную демо-программу: sh deploy/demo-alarm.sh stop"
