# 🖥 Установка бота на VPS (пошагово, для новичка)

Ниже — как поставить бота на обычный VPS с **Ubuntu 22.04/24.04**, чтобы он
работал круглосуточно и сам перезапускался. Делай строго по шагам.

Подойдёт самый дешёвый VPS: **1 CPU, 1 ГБ RAM, 10 ГБ диска** — за глаза.
Провайдеры: Timeweb, Aeza, HostVDS, Vultr, Hetzner, DigitalOcean и т. п.

---

## Шаг 1. Купи VPS
При заказе выбери:
- ОС: **Ubuntu 24.04** (или 22.04),
- регион: любой (для TON/Telegram лучше Европа),
- после оплаты провайдер пришлёт: **IP-адрес**, **логин** (обычно `root`) и **пароль**.

## Шаг 2. Подключись к серверу по SSH
- **Windows:** установи [Termius](https://termius.com) или используй встроенный
  `ssh` в PowerShell.
- **Mac/Linux:** открой Терминал.

Подключение (подставь свой IP):
```bash
ssh root@ВАШ_IP
```
Введи пароль (при вводе он не отображается — это нормально). Согласись с `yes`,
если спросит про отпечаток ключа.

## Шаг 3. Обнови систему и поставь нужное
Скопируй и выполни целиком:
```bash
apt update && apt -y upgrade
apt -y install python3 python3-venv python3-pip git nano
```

## Шаг 4. Залей код бота на сервер
**Вариант А — если код у тебя в GitHub-репозитории:**
```bash
cd /opt
git clone https://github.com/ТВОЙ_АККАУНТ/ТВОЙ_РЕПО.git shop
cd shop/telegram_shop_bot
```
**Вариант Б — загрузить папку с компьютера** (выполни это в терминале
**своего компьютера**, не на сервере):
```bash
scp -r telegram_shop_bot root@ВАШ_IP:/opt/shop
```
затем на сервере: `cd /opt/shop`.

Дальше во всех командах рабочая папка — та, где лежит `run.py`.

## Шаг 5. Виртуальное окружение и зависимости
```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## Шаг 6. Настрой `.env`
```bash
cp .env.example .env
nano .env
```
Впиши `BOT_TOKEN`, `ADMIN_IDS`, `PAYMENT_METHOD`, `CURRENCY`, `PAYMENT_DETAILS`
(и, если нужно, `TON_WALLET`/`TON_RATE`, `BACKUP_CHAT_ID`/`BACKUP_INTERVAL_HOURS`).
Сохрани: **Ctrl+O → Enter**, выйди: **Ctrl+X**.

## Шаг 7. Проверь, что запускается
```bash
.venv/bin/python run.py
```
Должна появиться строка `Бот @… запущен`. Проверь бота в Telegram (`/start`).
Останови проверочный запуск: **Ctrl+C**.

## Шаг 8. Автозапуск 24/7 через systemd
Узнай абсолютный путь к папке: выполни `pwd` (например, `/opt/shop`).
Создай сервис:
```bash
nano /etc/systemd/system/shop-bot.service
```
Вставь (поправь `WorkingDirectory` на вывод `pwd`, если он другой):
```ini
[Unit]
Description=Telegram Shop Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/shop
ExecStart=/opt/shop/.venv/bin/python run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Сохрани (Ctrl+O, Enter, Ctrl+X) и запусти:
```bash
systemctl daemon-reload
systemctl enable --now shop-bot
systemctl status shop-bot        # должно быть "active (running)"
```

## Шаг 9. Как управлять ботом
```bash
journalctl -u shop-bot -f        # смотреть логи в реальном времени (выход — Ctrl+C)
systemctl restart shop-bot       # перезапустить
systemctl stop shop-bot          # остановить
systemctl start shop-bot         # запустить
```

## Шаг 10. Как обновить бота потом
Если ставил через git:
```bash
cd /opt/shop && git pull
.venv/bin/pip install -r telegram_shop_bot/requirements.txt
systemctl restart shop-bot
```
Файл `.env` и база `data/shop.db` при обновлении не трогаются — данные сохранятся.

---

## 🔐 Немного про безопасность
- Никому не давай токен бота и содержимое `.env`.
- Смени пароль root или заведи ключи SSH (по желанию).
- Простой firewall (боту не нужны открытые порты — он сам ходит наружу):
  ```bash
  apt -y install ufw
  ufw allow OpenSSH
  ufw --force enable
  ```
- Настрой **бэкапы в Telegram** (`BACKUP_CHAT_ID`, `BACKUP_INTERVAL_HOURS`) —
  тогда даже при потере сервера у тебя останется копия базы с товарами и заказами.

## ❓ Если бот не стартует
```bash
systemctl status shop-bot        # краткая причина
journalctl -u shop-bot -n 50     # последние 50 строк лога с ошибкой
```
Частые причины: не заполнен `.env`, неверный `BOT_TOKEN`, неправильный путь в
`WorkingDirectory`/`ExecStart` сервиса.
