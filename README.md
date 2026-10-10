# LureGenix

Система развертывания и мониторинга файловых honeytoken для Linux.
Интерфейс: http://localhost:8080. Приманки размещает Linux-агент, не контейнер.

## Запуск

Нужны Docker Compose v2 и Python 3.10+. Для агента нужны Linux, systemd,
python3-venv и python3-pip. Команды выполняются из корня проекта:

```bash
python3 tools/setup_env.py --local
docker compose up -d --build
docker compose ps -a
```

Первый логин: `admin`. Пароль выводится при создании конфигурации и находится
в `BOOTSTRAP_ADMIN_PASSWORD` в локальном `.env`. Существующие пароли не меняются.
`database_init` должен завершиться с кодом 0; остальные сервисы остаются запущенными.
Настройки и том существующей БД сохраняются; миграции применяются автоматически.

## Linux-Агент

На Linux-хосте, где доступен основной сервер по localhost:8080:

```bash
python3 tools/configure_agent.py --url http://127.0.0.1:8080 --output agent-install.env
sudo bash agent/install.sh agent-install.env
rm agent-install.env
```

На Windows агент не работает: его нужно установить на целевой Linux-сервер.
Для второго сервера передайте папку `agent/` и защищенный конфигурационный файл.
Укажите доступный с него HTTPS-адрес основного сервера либо localhost-порт
SSH-туннеля. `localhost` второго сервера не означает основной сервер.
Агент использует тот же секрет регистрации, но хранит собственную идентичность.

## Работа

1. Войти в интерфейс и проверить, что сервер появился в разделе «Ноды».
2. Выбрать сервер, тип приманки, существующий каталог и имя файла либо автоподбор.
3. Создать приманку и дождаться статуса «Размещён». Реальный путь указан в таблице.
4. Прочитать файл на выбранном Linux-сервере: `cat /opt/backup.sql`.
5. Открыть «События»: появится обращение к приманке. Подтвердить его кнопкой с галочкой.

Агент опрашивает задания каждые 10 секунд, отправляет heartbeat каждую минуту.
Без heartbeat 150 секунд сервер отображается как offline. События при потере
связи остаются в локальной очереди и доставляются после восстановления.
Изменение и удаление файла отражаются в статусе приманки. Сбой размещения можно повторить.
Сканирование включается через `DISCOVERY_ALLOWED_CIDRS` в `.env`;
оно ищет TCP/22 и не устанавливает агенты автоматически.

## Локальная LLM

По умолчанию `GENERATION_MODE=template`: модель не скачивается.
Для Ollama:

```bash
docker compose --profile llm up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b
```

Установить `GENERATION_MODE=llm` в `.env`, затем:
`docker compose up -d --no-deps honeytoken_service`.
Файловое содержимое генерирует модель; SSH/API-ключи и пароли создаются локально.
Ошибка модели показывается явно, без подмены результата шаблоном.

## Проверка

```bash
python3 tools/smoke_test.py --api-only
python3 tools/smoke_test.py
```

Первая команда проверяет API с любой ОС. Вторая выполняется на Linux-хосте
агента: создает файл в `/opt`, читает его и подтверждает событие.
Тестовый файл остается под мониторингом; его путь выводится в конце.

Тесты кода: `python -m pip install -r requirements-dev.txt` в отдельном venv,
затем `python -m unittest discover -s tests`.
Интерфейс: `python tools/verify_dashboard.py` (Playwright и Microsoft Edge).
Диагностика: `docker compose logs --tail=100` и
`sudo journalctl -u luregenix-agent -n 50 --no-pager`.

Границы защиты и HTTPS: [SECURITY.md](SECURITY.md).
