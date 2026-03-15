# LureGenix

Программное обеспечение для генерации honeytoken с помощью LLM в Docker-контейнерах и распределённой сети.

## Функционал

- **Авторизация** — вход в админку по логину/паролю (таблица `admins`, bcrypt)
- **Генерация приманок** — разные типы: SSH ключ, .env, пароль, PDF/DOCX (контент через Groq LLM)
- **Просмотр статусов** — список honeytoken'ов, ноды, события в реальном времени (WebSocket)
- **Создание админов** — API `POST /api/admins` (требуется JWT + опционально `ADMIN_SECRET`)
- **Уведомления о компрометации** — события с `action: alert` приходят по WebSocket и отображаются в дашборде

## Запуск

1. Создайте файл `.env` в корне (см. пример ниже).
2. Установите [Docker](https://www.docker.com/) и [Docker Compose](https://docs.docker.com/compose/).
3. Выполните:

```bash
docker compose up --build
```

4. Откройте в браузере: **http://localhost:8080**
5. Вход по умолчанию: **admin** / **password**

**Безопасность авторизации:** пароль передаётся в теле POST-запроса. Сервер не логирует его и проверяет только через bcrypt. **В production обязательно используйте HTTPS** (обратный прокси с TLS), иначе пароль идёт по сети в открытом виде. На localhost для разработки допустим HTTP.

Если при входе admin/password возвращается **401**, сбросьте пароль в БД (например, после обновления кода или старой БД):

```bash
docker exec -i luregenix-postgres-1 psql -U admin -d luregenix < db/update_admin_password.sql
```

Либо пересоздайте базу с нуля: `docker compose down -v`, затем снова `docker compose up -d`.

## Переменные окружения (.env)

```env
DB_NAME=luregenix
DB_USER=admin
DB_PASSWORD=admin
JWT_SECRET=your_super_secret_key_here_min_32_chars
GROK_API_KEY=your_grok_api_key_here
# Опционально: секрет для создания новых админов (POST /api/admins)
ADMIN_SECRET=optional_admin_creation_secret
# Опционально: разрешённые префиксы абсолютных путей для сохранения приманок (через запятую)
# ALLOWED_SAVE_PATHS=/var/app/secrets,/opt/keys
```

## Создание нового админа

Если задан `ADMIN_SECRET`, после входа в админку можно отправить запрос:

```bash
curl -X POST http://localhost:8080/api/admins \
  -H "Authorization: Bearer <ваш_jwt_токен>" \
  -H "Content-Type: application/json" \
  -d '{"username":"newadmin","password":"secure_password"}'
```

Без `ADMIN_SECRET` создание админов через API отключено (можно добавлять пользователей напрямую в БД).

## Архитектура

- **nginx** — раздача фронта, прокси API на gateway, WebSocket `/ws/` на gateway (gateway проксирует на event_service)
- **gateway** — единая точка входа, проверка JWT, проксирование на сервисы, прокси WebSocket `/ws/events` на event_service
- **auth_service** — логин по БД, выдача JWT; создание админов
- **honeytoken_service** — генерация приманок (random + Groq для pdf/docx), запись в БД. Файлы сохраняются в `TOKENS_BASE`; в форме «Каталог сохранения» задаётся **относительный** путь — создаётся подкаталог (например `production` → `/tokens/production`). Абсолютные пути разрешены только внутри `TOKENS_BASE` или при задании `ALLOWED_SAVE_PATHS` в .env.
- **event_service** — приём событий (heartbeat, alert), хранение в `event_log`, рассылка по WebSocket
- **discovery_service** — список нод из БД (таблица `nodes`), регистрация агентов; опционально список контейнеров Docker
- **agent** — регистрируется в discovery, отправляет heartbeat; при компрометации приманки — событие `action: alert`
- **postgres** — БД (admins, nodes, honeytokens, events, event_log, scans)

Если после обновления кода запрос **События** даёт ошибку, примените миграции:

```bash
docker exec -i luregenix-postgres-1 psql -U admin -d luregenix < db/02_event_log.sql
docker exec -i luregenix-postgres-1 psql -U admin -d luregenix < db/04_event_log_read_retention.sql
```

## Ноды и уведомления о компрометации

- **Ноды** заполняются из таблицы `nodes`. Агент при старте вызывает `POST /api/register` (hostname, ip) и попадает в список. Если нод в БД нет — в дашборде показывается заглушка (agent1).
- **Компрометация:** при срабатывании приманки агент или детектор должен отправить `POST /api/event` с телом `{"token_id": "<id>", "action": "alert", "file_path": "<путь>"}`. На дашборде появится тревога и уведомление (в т.ч. по WebSocket в реальном времени).

### Как протестировать уведомление о компрометации

1. **Через curl (без агента):**  
   `curl -X POST http://localhost:8080/api/event -H "Content-Type: application/json" -d "{\"token_id\":\"test-123\",\"action\":\"alert\",\"file_path\":\"/tokens/ssh_key_xxx.txt\"}"`  
   В разделе «События» появится запись с действием `alert`, счётчик «Тревоги» увеличится; при подключённом WebSocket — всплывающее уведомление.

2. **Через агента:** в коде ноды при обнаружении доступа к файлу-приманке вызовите `send_compromise(token_id, file_path)` из `agent/agent.py`. Агент отправит событие на gateway, оно попадёт в журнал и в дашборд по WebSocket.

## Типы приманок

| Тип       | Описание                          |
|----------|------------------------------------|
| ssh_key  | Строка вида `FAKE_API_KEY=...`     |
| env      | То же (переменные окружения)       |
| password | Строка вида `password: ...`        |
| pdf/docx | Текст генерируется через Groq LLM  |

Для PDF/DOCX нужен валидный `GROK_API_KEY` (модель по умолчанию: `llama-3.1-70b-versatile`).

## События и уведомления

- В разделе **«Все события»** отображаются heartbeat и алерты. Для heartbeat показывается **имя хоста** (hostname) ноды, если агент при отправке события передаёт `source_hostname` (по умолчанию агент передаёт свой hostname).
- **Колокольчик** в сайдбаре показывает количество **непрочитанных** событий. При открытии раздела «События» все события помечаются прочитанными; также есть кнопка «Прочитано».
- Старые события автоматически удаляются через **EVENT_RETENTION_DAYS** дней (по умолчанию 30). Задаётся в .env: `EVENT_RETENTION_DAYS=30`.

## Проверка генерации токенов в Docker и распределённой сети

- **Генерация:** в дашборде создайте приманку, выбрав ноду и (при необходимости) каталог сохранения и путь на ноде. Файл создаётся на сервере в `TOKENS_BASE` (в контейнере honeytoken_service), запись с `placement` сохраняется в БД.
- **Размещение на ноде:** сейчас система не копирует файл приманки на целевую ноду автоматически. Чтобы проверить сценарий «токен в контейнере/сети», можно: (1) вручную скопировать файл из тома/каталога сервера в контейнер агента по нужному пути; (2) либо доработать агент: добавить опрос API «токены для моей ноды» и раскладывать их по путям из `placement`.
