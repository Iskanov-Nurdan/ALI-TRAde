#!/bin/sh
# Периодически перечитывает конфигурацию, чтобы подхватить обновлённый certbot'ом
# сертификат без перезапуска контейнера. Запускается штатным entrypoint'ом nginx.
(
  while :; do
    sleep 6h
    nginx -s reload 2>/dev/null || true
  done
) &
