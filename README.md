# LureGenix

Система развёртывания и мониторинга файловых honeytoken для серверов Linux.
Приманки размещаются агентом в существующих каталогах Linux-хоста.

## Запуск

Нужны Docker Compose v2 и Python 3.10+. Из корня проекта:

```bash
python3 tools/setup_env.py --local
docker compose up -d --build
```

Интерфейс: http://localhost:8080. Логин: `admin`, пароль первого входа
выводится настройщиком и хранится в `BOOTSTRAP_ADMIN_PASSWORD` локального `.env`.
Для доступа по IP в изолированном стенде используйте `--lan` вместо `--local`.
Миграции запускаются автоматически; `database_init` завершается с кодом 0.
Потерянный `.env` можно восстановить из сохранившихся контейнеров:
`python3 tools/setup_env.py --recover-env --local`. Не удаляйте том БД.

## Агент

На целевом Linux-сервере нужны systemd, python3-venv и python3-pip.
Для основного сервера:

```bash
python3 tools/configure_agent.py --url http://127.0.0.1:8080 --output agent-install.env
sudo bash agent/install.sh agent-install.env
rm agent-install.env
```

Для другого сервера создайте конфигурацию с доступным ему адресом приложения,
передайте только её и папку `agent/`, выполните установку на этом сервере.
`--node-ip` и `--hostname` задают адрес и имя ноды. Корневой `.env` не передавайте.

## Работа

Выберите ноду, тип приманки, шаблоны или LLM, каталог и имя файла либо автоподбор.
После статуса «Размещён» файл находится по пути из таблицы. Чтение, изменение и
удаление вызывают события и уведомления; журнал можно подтверждать и очищать.
Агент не перезаписывает существующие файлы и сохраняет события при потере связи.
Обнаружение серверов TCP/22 разрешается через `DISCOVERY_ALLOWED_CIDRS` в `.env`.

Ollama не запускается по умолчанию. Для локальной LLM:

```bash
docker compose --profile llm up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b
```

Диагностика: `docker compose logs --tail=100`,
`sudo journalctl -u luregenix-agent -n 50 --no-pager`.
HTTPS и ограничения защиты: [SECURITY.md](SECURITY.md).
