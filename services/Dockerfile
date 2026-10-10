FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG SERVICE
COPY services/${SERVICE}/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt
COPY common ./common
COPY services/${SERVICE}/ ./
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
