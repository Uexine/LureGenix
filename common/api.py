"""Общие настройки HTTP API и безопасные сообщения об ошибках."""

import logging
from contextlib import closing

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)
FIELD_NAMES = {
    "node_id": "сервер",
    "type": "тип приманки",
    "name": "название",
    "filename": "имя файла",
    "node_path": "каталог",
    "target_kind": "тип пути",
    "generation_mode": "режим генерации",
    "ids": "выбранные события",
    "clear_all": "очистка журнала",
    "subnet": "подсеть",
    "hostname": "имя сервера",
    "ip": "IP-адрес",
    "agent_id": "идентификатор агента",
    "credential": "ключ агента",
    "event_id": "идентификатор события",
    "token_id": "идентификатор приманки",
    "action": "действие",
    "status": "статус",
    "deployed_path": "путь размещения",
    "attempt": "попытка размещения",
}


def create_app(*, lifespan=None, database=None):
    """Создаёт API с русскими ошибками и проверкой БД, если передано подключение."""
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        """Указывает ошибочные поля, не возвращая введённые пароли и ключи."""
        fields = dict.fromkeys(
            next(
                (
                    FIELD_NAMES[part]
                    for part in error.get("loc", ())
                    if part in FIELD_NAMES
                ),
                "данные запроса",
            )
            for error in exc.errors()
        )
        detail = "Проверьте поля: " + ", ".join(fields) + "."
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        """Сохраняет HTTP-статус и переводит стандартные ошибки маршрутизации."""
        detail = (
            {
                "Not Found": "Адрес не найден.",
                "Method Not Allowed": "Метод запроса не поддерживается.",
            }.get(exc.detail, exc.detail)
            if isinstance(exc.detail, str)
            else exc.detail
        )
        return JSONResponse(
            status_code=exc.status_code, content={"detail": detail}, headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        """Скрывает внутренние сведения об исключении от клиента."""
        logger.error("Unhandled request error (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Внутренняя ошибка сервиса. Проверьте журнал приложения."
            },
        )

    if database is not None:
        import psycopg2

        @app.get("/health")
        def health():
            """Проверяет не только процесс сервиса, но и доступность PostgreSQL."""
            with closing(database()) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            return {"status": "ok"}

        @app.exception_handler(psycopg2.Error)
        async def database_error(request: Request, exc: psycopg2.Error):
            """Возвращает 503 при сбое БД, не раскрывая SQL и реквизиты соединения."""
            logger.error("Database request failed (%s)", type(exc).__name__)
            return JSONResponse(
                status_code=503,
                content={"detail": "Хранилище временно недоступно. Повторите попытку."},
            )

    return app
