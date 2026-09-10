#!/usr/bin/env bash
# Резервная копия базы. Кладёт сжатый дамп в ./backups и удаляет старые.
#
# Разовый запуск:  ./scripts/backup-db.sh
# Ежедневно в 3:30 (ставится один раз):
#   (crontab -l 2>/dev/null; echo "30 3 * * * $(pwd)/scripts/backup-db.sh >> $(pwd)/backups/backup.log 2>&1") | crontab -
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP_DAYS="${KEEP_DAYS:-14}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
COMPOSE_FILE=docker-compose.prod.yml

set -a
# shellcheck disable=SC1091
[ -f .env ] && . ./.env
set +a

DB_NAME="${POSTGRES_DB:-delivery}"
DB_USER="${POSTGRES_USER:-delivery}"

mkdir -p "$BACKUP_DIR"
FILE="${BACKUP_DIR}/${DB_NAME}-$(date +%F-%H%M).sql.gz"

# Дамп пишется во временный файл: прерванный бэкап не должен выглядеть как
# готовый и не должен вытеснить исправную копию при ротации.
TMP="${FILE}.part"
if docker compose -f "$COMPOSE_FILE" exec -T db \
     pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip -9 > "$TMP"; then
  mv "$TMP" "$FILE"
  chmod 600 "$FILE"
  printf '[%s] OK %s (%s)\n' "$(date '+%F %T')" "$FILE" "$(du -h "$FILE" | cut -f1)"
else
  rm -f "$TMP"
  printf '[%s] ОШИБКА: дамп не создан\n' "$(date '+%F %T')" >&2
  exit 1
fi

# Ротация — только после успешного дампа.
DELETED="$(find "$BACKUP_DIR" -name "${DB_NAME}-*.sql.gz" -mtime "+${KEEP_DAYS}" -print -delete | wc -l)"
[ "$DELETED" -gt 0 ] && printf '[%s] удалено старых копий: %s\n' "$(date '+%F %T')" "$DELETED"
exit 0
