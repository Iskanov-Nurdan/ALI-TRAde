#!/usr/bin/env bash
# Разворачивает проект на сервере в один запуск: проверяет окружение, собирает
# образы, поднимает Postgres + Django + nginx и выпускает сертификат Let's Encrypt.
# Повторный запуск безопасен — работает как обновление (миграции применяются сами).
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE_FILE=docker-compose.prod.yml
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] ОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }

SEED=false
for arg in "$@"; do
  case "$arg" in
    --seed) SEED=true ;;
    -h|--help)
      cat <<'USAGE'
Использование: ./deploy.sh [--seed]

  --seed   после запуска наполнить базу демо-данными (manage.py seed_demo)

Настройки берутся из .env (создаётся автоматически из .env.production.example).
USAGE
      exit 0 ;;
    *) die "неизвестный аргумент: $arg" ;;
  esac
done

# --- 1. Проверка окружения -------------------------------------------------
log "Проверяю Docker"
command -v docker >/dev/null 2>&1 || die "Docker не установлен. Установите: curl -fsSL https://get.docker.com | sh"
docker compose version >/dev/null 2>&1 || die "Нужен плагин docker compose v2 (docker-compose-plugin)"
docker info >/dev/null 2>&1 || die "Демон Docker не запущен или нет прав. Попробуйте: sudo systemctl start docker"

# --- 2. Файл .env ----------------------------------------------------------
if [ ! -f .env ]; then
  log "Создаю .env из .env.production.example и генерирую секреты"
  cp .env.production.example .env
  rnd() { openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-"${1:-32}"; }
  SECRET_KEY_VALUE="$(rnd 50)"
  DB_PASSWORD_VALUE="$(rnd 24)"
  ADMIN_PASSWORD_VALUE="$(rnd 16)"
  DEMO_PASSWORD_VALUE="$(rnd 16)"
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=${SECRET_KEY_VALUE}|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASSWORD_VALUE}|" .env
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${ADMIN_PASSWORD_VALUE}|" .env
  sed -i "s|^DEMO_PASSWORD=.*|DEMO_PASSWORD=${DEMO_PASSWORD_VALUE}|" .env
  warn "Секреты сгенерированы. Пароль администратора: ${ADMIN_PASSWORD_VALUE}"
  warn "Сохраните .env — восстановить пароль базы из него нельзя."
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${DOMAIN:?В .env не задан DOMAIN}"
: "${POSTGRES_PASSWORD:?В .env не задан POSTGRES_PASSWORD}"
ENABLE_SSL="${ENABLE_SSL:-true}"

set_env() { # set_env КЛЮЧ ЗНАЧЕНИЕ — правит .env на месте
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

mkdir -p certbot/conf certbot/www

CERT_DIR="certbot/conf/live/${DOMAIN}"
if [ -d "$CERT_DIR" ]; then START_MODE=https; else START_MODE=http; fi
set_env NGINX_CONF "$START_MODE"

# --- 3. Сборка и запуск ----------------------------------------------------
log "Собираю образы"
compose build

log "Запускаю сервисы (режим nginx: ${START_MODE})"
NGINX_CONF="$START_MODE" compose up -d --remove-orphans

log "Жду готовности API"
for i in $(seq 1 60); do
  if compose exec -T api curl -fsS http://127.0.0.1:8000/health/ >/dev/null 2>&1; then
    printf 'API отвечает\n'; break
  fi
  [ "$i" = 60 ] && { compose logs --tail=50 api; die "API не поднялся за 120 секунд"; }
  sleep 2
done

# --- 4. Сертификат Let's Encrypt -------------------------------------------
if [ "$ENABLE_SSL" = "true" ] && [ ! -d "$CERT_DIR" ]; then
  log "Проверяю, что домен ${DOMAIN} указывает на этот сервер"
  TOKEN="deploy-check-$(date +%s)"
  mkdir -p certbot/www/.well-known/acme-challenge
  printf '%s' "$TOKEN" > "certbot/www/.well-known/acme-challenge/${TOKEN}"
  if curl -fsS --max-time 15 "http://${DOMAIN}/.well-known/acme-challenge/${TOKEN}" 2>/dev/null | grep -q "$TOKEN"; then
    rm -f "certbot/www/.well-known/acme-challenge/${TOKEN}"
    log "Выпускаю сертификат Let's Encrypt для ${DOMAIN}"
    if compose --profile certbot run --rm certbot certonly \
        --webroot -w /var/www/certbot \
        -d "${DOMAIN}" \
        --email "${CERTBOT_EMAIL:-admin@${DOMAIN}}" \
        --agree-tos --no-eff-email --non-interactive; then
      log "Сертификат получен"
    else
      warn "Certbot не смог выпустить сертификат. Сайт продолжит работать по HTTP."
      warn "Домен tw1.ru общий для многих клиентов — возможен лимит Let's Encrypt (50 сертификатов в неделю на домен)."
    fi
  else
    rm -f "certbot/www/.well-known/acme-challenge/${TOKEN}"
    warn "Домен ${DOMAIN} не отвечает на порту 80 с этого сервера — сертификат не выпускается."
    warn "Проверьте A-запись DNS и что порт 80 открыт, затем запустите ./deploy.sh ещё раз."
  fi
fi

# --- 5. Переключение на HTTPS ---------------------------------------------
if [ -d "$CERT_DIR" ]; then
  log "Включаю HTTPS"
  set_env NGINX_CONF https
  NGINX_CONF=https compose up -d --force-recreate nginx
  NGINX_CONF=https compose --profile ssl up -d certbot-renew
  SITE_URL="https://${DOMAIN}"
else
  SITE_URL="http://${DOMAIN}"
fi

# --- 6. Демо-данные --------------------------------------------------------
if [ "$SEED" = true ]; then
  log "Наполняю базу демо-данными"
  compose exec -T api python manage.py seed_demo
fi

# --- 7. Итог ---------------------------------------------------------------
log "Состояние контейнеров"
compose ps

log "Готово"
printf 'Сайт:      %s\n' "$SITE_URL"
printf 'Админка:   %s/django-admin/\n' "$SITE_URL"
printf 'Проверка:  curl -I %s/health/\n' "$SITE_URL"
printf 'Логи:      docker compose -f %s logs -f\n' "$COMPOSE_FILE"
