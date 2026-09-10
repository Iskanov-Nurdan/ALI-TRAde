#!/usr/bin/env bash
# Базовое укрепление Ubuntu-сервера под этот проект: файрвол, защита SSH от
# перебора, автоматические обновления безопасности.
#
# Запускать от root на самом сервере: sudo ./scripts/harden-server.sh
# Скрипт идемпотентен — повторный запуск ничего не ломает.
set -euo pipefail

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[+] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] ОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "Запускайте от root: sudo $0"
command -v apt-get >/dev/null 2>&1 || die "Скрипт рассчитан на Debian/Ubuntu"

SSH_PORT="$(awk '/^[[:space:]]*Port[[:space:]]+[0-9]+/ {print $2; exit}' /etc/ssh/sshd_config 2>/dev/null || true)"
SSH_PORT="${SSH_PORT:-22}"

export DEBIAN_FRONTEND=noninteractive

# --- 1. Файрвол ------------------------------------------------------------
log "Настраиваю файрвол (ufw)"
apt-get -qq update >/dev/null
apt-get -y -qq install ufw >/dev/null

ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow "${SSH_PORT}/tcp" comment 'SSH' >/dev/null
ufw allow 80/tcp  comment 'HTTP' >/dev/null
ufw allow 443/tcp comment 'HTTPS' >/dev/null
ufw --force enable >/dev/null
ok "Открыты только ${SSH_PORT} (SSH), 80 и 443"

warn "Docker публикует порты в обход ufw через iptables — это нормально:"
warn "наружу смотрят только 80 и 443, порт Postgres не публикуется вовсе."

# --- 2. Защита SSH от перебора --------------------------------------------
log "Ставлю fail2ban"
apt-get -y -qq install fail2ban >/dev/null

cat > /etc/fail2ban/jail.d/sshd.local <<EOF
[sshd]
enabled  = true
port     = ${SSH_PORT}
maxretry = 5
findtime = 10m
bantime  = 1h
EOF

systemctl enable --now fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban
ok "fail2ban: 5 неудачных попыток за 10 минут — бан на час"

# --- 3. Вход по паролю -----------------------------------------------------
log "Проверяю вход по SSH"
HAS_KEYS=false
for f in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; do
  [ -s "$f" ] && HAS_KEYS=true && break
done

if [ "$HAS_KEYS" = true ]; then
  cp -n /etc/ssh/sshd_config "/etc/ssh/sshd_config.backup-$(date +%F)" 2>/dev/null || true
  cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
# Ключи уже настроены, поэтому вход по паролю закрыт: перебирать нечего.
PasswordAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 3
EOF
  if sshd -t 2>/dev/null; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd
    ok "Вход по паролю отключён, остались только ключи"
    warn "НЕ ЗАКРЫВАЙТЕ текущую сессию, пока не проверите вход в новом окне!"
  else
    rm -f /etc/ssh/sshd_config.d/99-hardening.conf
    warn "Конфигурация sshd не прошла проверку — изменения откачены"
  fi
else
  warn "SSH-ключей на сервере нет, вход по паролю оставлен включённым."
  warn "Иначе вы потеряете доступ к серверу. Как настроить ключи:"
  warn "  на своём компьютере:  ssh-keygen -t ed25519"
  warn "  затем:                ssh-copy-id root@\$(curl -s ifconfig.me)"
  warn "  после проверки входа по ключу запустите этот скрипт ещё раз."
fi

# --- 4. Автоматические обновления безопасности -----------------------------
log "Включаю автообновления безопасности"
apt-get -y -qq install unattended-upgrades >/dev/null
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
ok "Обновления безопасности ставятся автоматически"

# --- 5. Права на секреты ---------------------------------------------------
log "Закрываю права на .env"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "${PROJECT_DIR}/.env" ]; then
  chmod 600 "${PROJECT_DIR}/.env"
  ok "${PROJECT_DIR}/.env доступен только владельцу"
fi

# --- Итог ------------------------------------------------------------------
log "Готово. Состояние:"
ufw status verbose | head -12
echo
fail2ban-client status sshd 2>/dev/null | head -6 || true
