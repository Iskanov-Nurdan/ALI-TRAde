# Развёртывание на сервере (alitrade.tw1.ru)

Боевой контур: `docker-compose.prod.yml` (Postgres + Django/gunicorn + nginx + certbot).
Разворачивается одной командой — `./deploy.sh`.

## 0. Что нужно на сервере

- Ubuntu/Debian с доступом по SSH
- A-запись домена `alitrade.tw1.ru` указывает на IP сервера
- Открыты порты 80 и 443

Установка Docker, если его нет:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

## 1. Развернуть в один клик

```bash
git clone <адрес-репозитория> alitrade && cd alitrade
./deploy.sh
```

Скрипт сам: проверит Docker → создаст `.env` со сгенерированными секретами → соберёт
образы → поднимет сервисы → применит миграции и `collectstatic` → проверит, что домен
смотрит на этот сервер → выпустит сертификат Let's Encrypt → переключит nginx на HTTPS
и включит автопродление.

Первый запуск с демо-данными:

```bash
./deploy.sh --seed
```

> Пароль администратора печатается при первой генерации `.env`. Он же лежит в `.env`
> в переменной `ADMIN_PASSWORD`.

## 2. Проверка

```bash
curl -I https://alitrade.tw1.ru/health/
docker compose -f docker-compose.prod.yml ps
```

Сайт: https://alitrade.tw1.ru
Админка Django: https://alitrade.tw1.ru/django-admin/

## 3. Обновление кода

```bash
git pull && ./deploy.sh
```

Повторный запуск идемпотентен: `.env` не перезаписывается, сертификат переиспользуется,
миграции применяются автоматически.

## 4. Частые команды

```bash
# Логи всех сервисов / только API
docker compose -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.prod.yml logs -f api

# Перезапуск
docker compose -f docker-compose.prod.yml restart

# Применить правку конфига nginx — именно пересоздание, а не reload:
# редакторы (и sed -i) заменяют файл целиком, а bind-mount привязан к inode,
# поэтому старый контейнер продолжает видеть прежнюю версию.
docker compose -f docker-compose.prod.yml up -d --force-recreate nginx

# Остановка (данные в томах сохраняются)
docker compose -f docker-compose.prod.yml down

# Создать суперпользователя
docker compose -f docker-compose.prod.yml exec api python manage.py createsuperuser

# Бэкап базы
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U delivery delivery | gzip > backup-$(date +%F).sql.gz

# Восстановление из бэкапа
gunzip -c backup-2026-09-10.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db psql -U delivery -d delivery

# Ручное продление сертификата
docker compose -f docker-compose.prod.yml --profile certbot run --rm certbot renew
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

## 5. Если сертификат не выпустился

Сайт останется работать по HTTP, ошибки деплоя не будет. Причины:

- DNS ещё не обновился — подождите и запустите `./deploy.sh` снова;
- порт 80 закрыт файрволом: `sudo ufw allow 80,443/tcp`;
- превышен лимит Let's Encrypt на домен `tw1.ru` (он общий для клиентов Timeweb —
  50 сертификатов в неделю на зарегистрированный домен). В этом случае используйте
  собственный домен или сертификат от хостинга.

Работать только по HTTP: `ENABLE_SSL=false` в `.env`.

## 6. Безопасность

Базовое укрепление сервера — файрвол, fail2ban, автообновления, права на `.env`:

```bash
sudo ./scripts/harden-server.sh
```

Скрипт идемпотентен. Вход по паролю он отключает только если на сервере уже
настроены SSH-ключи, иначе оставляет как есть и объясняет, что сделать, — потерять
доступ к серверу хуже, чем оставить пароль ещё на день.

Доступ к админке Django можно ограничить своим адресом — это надёжнее лимита
попыток. Раскомментируйте нужные строки в `nginx/admin_access.conf`:

```nginx
allow 203.0.113.10;   # ваш адрес, узнать: curl -s ifconfig.me
deny all;
```

Затем `docker compose -f docker-compose.prod.yml up -d --force-recreate nginx`.

Что уже включено: TLS с HSTS, заголовки против кликджекинга и MIME-sniffing,
скрытая версия nginx, лимиты (20 запросов/сек на API, 5 попыток в минуту на вход,
10 в минуту на админку), троттлинг DRF, JWT с ротацией и чёрным списком, secure-куки,
Postgres без публикации порта наружу, непривилегированный пользователь в контейнере.

Отдельно стоит включить защиту от DDoS в панели Timeweb: рейт-лимиты nginx
не спасают от объёмной атаки — она положит канал раньше, чем дойдёт до сервера.

## 7. Резервные копии

Разовая копия:

```bash
./scripts/backup-db.sh
```

Ежедневно в 3:30 — поставить один раз:

```bash
mkdir -p backups
(crontab -l 2>/dev/null; echo "30 3 * * * $(pwd)/scripts/backup-db.sh >> $(pwd)/backups/backup.log 2>&1") | crontab -
crontab -l
```

Копии лежат в `backups/`, хранятся 14 дней (`KEEP_DAYS`), в гит не попадают.
Восстановление:

```bash
gunzip -c backups/delivery-2026-09-10-0330.sql.gz |   docker compose -f docker-compose.prod.yml exec -T db psql -U delivery -d delivery
```

Копии лежат на том же сервере, что и база, — от потери сервера это не спасает.
Раз в неделю скачивайте свежий дамп к себе: `scp root@СЕРВЕР:~/alitrade/backups/*.gz .`

## 8. Структура боевого контура

| Сервис | Образ | Роль |
|---|---|---|
| `db` | postgres:16.4-alpine | база, том `postgres_data` |
| `api` | сборка из `backend/Dockerfile` | Django + gunicorn (3 воркера), непривилегированный пользователь |
| `nginx` | nginx:1.27-alpine | статика фронтенда, прокси на API, TLS, rate limiting, gzip |
| `certbot` | certbot/certbot | разовый выпуск сертификата (профиль `certbot`) |
| `certbot-renew` | certbot/certbot | автопродление раз в 12 ч (профиль `ssl`) |

Конфиг nginx выбирается переменной `NGINX_CONF` в `.env`: `http` — до выпуска
сертификата, `https` — после (переключает `deploy.sh`).
