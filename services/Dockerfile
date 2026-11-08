FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG SERVICE_DIR
# Сначала зависимости: изменения кода не должны заново запускать pip install.
COPY ${SERVICE_DIR}/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt
# Шрифт с кириллицей нужен только сервису, собирающему PDF.
RUN if [ "$SERVICE_DIR" = "services/honeytoken_service" ]; then \
      apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
      && rm -rf /var/lib/apt/lists/*; \
    fi
COPY common ./common
COPY ${SERVICE_DIR}/ ./
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
