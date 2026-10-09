# Проверка LureGenix на Linux

## Конфигурация

В `.env` задайте приватные `JWT_SECRET`, `AGENT_SECRET`, `ADMIN_SECRET` и
`BOOTSTRAP_ADMIN_PASSWORD`. `BOOTSTRAP_ADMIN_USERNAME=admin`.
Начальный администратор создается только при отсутствии администраторов в БД.
Существующие пароли не сбрасываются. Обход входа через `admin/password` удален.

Для проверки без модели: `GENERATION_MODE=template`. Все форматы приманок
доступны без Ollama; источник записывается как `template`, не `llm`.
SSH-ключи, API-ключи и пароли генерируются локально криптографическим генератором.

## Основной сервер

Нужны Docker Compose, Python 3 с поддержкой venv, Git и systemd.
На Ubuntu для агента установите `python3-venv` и `python3-pip`.
После публикации изменений в ветке `dev`:

```bash
INSTALL_HOST_AGENT=1 bash ~/deploy.sh
```

Скрипт запросит GitHub-токен и sudo для установки агента. Базовый деплой
не скачивает Ollama. SQL-миграции выполняются и для существующей базы.
Агент работает непосредственно на Linux-хосте, не внутри Docker.

## Другой сервер

На основном сервере создайте защищенный конфиг:

```bash
cd ~/LureGenix
python3 tools/configure_agent.py --url http://10.124.21.50:8080 --output /tmp/luregenix-agent.env
scp -r agent master@SERVER_IP:/tmp/luregenix-agent
scp /tmp/luregenix-agent.env master@SERVER_IP:/tmp/luregenix-agent.env
ssh -t master@SERVER_IP 'sudo bash /tmp/luregenix-agent/install.sh /tmp/luregenix-agent.env'
```

После установки удалите временные копии конфига на обоих серверах.
Секрет общий для агентов, не передавайте его недоверенным серверам.
Для недоверенных сетей используйте HTTPS с проверяемым сертификатом.
Установка через веб-интерфейс пока не реализована.

## Проверка размещения и мониторинга

1. Откройте `http://10.124.21.50:8080`, войдите настроенным администратором.
2. Выберите узел с текущим hostname/IP и статусом «В сети». Старый узел
   с именем Docker-контейнера не является агентом Linux-хоста.
3. Создайте приманку в существующем каталоге `/opt` или другом разрешенном
   каталоге. Существующие файлы агент не перезаписывает.
4. Дождитесь статуса размещения и фактического пути в списке приманок.
5. На целевом сервере прочитайте файл: `sudo cat /фактический/путь`.
6. Проверьте событие чтения в интерфейсе.

Диагностика агента:

```bash
sudo systemctl status luregenix-agent --no-pager
sudo journalctl -u luregenix-agent -n 100 --no-pager
```

## Локальная LLM

Когда загрузка станет возможной:

```bash
docker compose --profile llm up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b
```

Установите `GENERATION_MODE=llm` в `.env` и пересоздайте генератор:

```bash
docker compose up -d --no-deps honeytoken_service
```

В режиме `llm` отсутствие модели или ошибка генерации возвращаются явно.
Облачные провайдеры не используются.
