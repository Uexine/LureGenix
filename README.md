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

## Переменные окружения (.env)

```env
DB_NAME=luregenix
DB_USER=admin
DB_PASSWORD=admin
JWT_SECRET=your_super_secret_key_here_min_32_chars
GROK_API_KEY=your_grok_api_key_here
# Опционально: секрет для создания новых админов (POST /api/admins)
ADMIN_SECRET=optional_admin_creation_secret
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

- **nginx** — раздача фронта и прокси на gateway и WebSocket
- **gateway** — единая точка входа, проверка JWT, проксирование на сервисы
- **auth_service** — логин по БД, выдача JWT; создание админов
- **honeytoken_service** — генерация приманок (random + Groq для pdf/docx), запись в БД и в `/tokens`
- **event_service** — приём событий (heartbeat, alert), хранение в БД, рассылка по WebSocket
- **agent** — демо-агент ноды: отправляет heartbeat раз в 60 сек
- **postgres** — БД (admins, honeytokens, events)

## Типы приманок

| Тип       | Описание                          |
|----------|------------------------------------|
| ssh_key  | Строка вида `FAKE_API_KEY=...`     |
| env      | То же (переменные окружения)       |
| password | Строка вида `password: ...`        |
| pdf/docx | Текст генерируется через Groq LLM  |

Для PDF/DOCX нужен валидный `GROK_API_KEY` (модель по умолчанию: `llama-3.1-70b-versatile`).
