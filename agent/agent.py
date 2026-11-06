"""Linux-агент: размещение файлов, наблюдение inotify и доставка событий из журнала."""

import base64
import errno
import hashlib
import json
import logging
import os
import secrets
import socket
import stat
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
AGENT_SECRET = os.getenv("AGENT_SECRET", "")
NODE_HOSTNAME = os.getenv("NODE_HOSTNAME") or socket.gethostname()
NODE_IP = os.getenv("NODE_IP", "")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
TASK_POLL_INTERVAL = int(os.getenv("TASK_POLL_INTERVAL", "10"))
ALLOWED_DIRS = [
    p.strip()
    for p in os.getenv("AGENT_ALLOWED_DIRS", "/etc,/var/www,/home,/opt").split(",")
    if p.strip()
]
AUTO_DIRS = [
    p.strip()
    for p in os.getenv(
        "AGENT_AUTO_DIRS", "/var/www/html,/var/www,/opt,/home,/etc"
    ).split(",")
    if p.strip()
]
STATE_FILE = Path(
    os.getenv("AGENT_STATE_FILE", "~/.local/state/luregenix/agent.json")
).expanduser()
FILE_MODE = int(os.getenv("AGENT_FILE_MODE", "0644"), 8)
if FILE_MODE not in (0o600, 0o640, 0o644):
    raise ValueError("AGENT_FILE_MODE должен быть 0600, 0640 или 0644.")
DENIED_PATHS = (
    "/opt/luregenix-agent",
    "/etc/luregenix-agent.env",
    "/etc/systemd",
    "/etc/init.d",
    "/etc/cron.d",
    "/etc/cron.daily",
    "/etc/cron.hourly",
    "/etc/cron.weekly",
    "/etc/cron.monthly",
    "/etc/crontab",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/etc/pam.d",
    "/etc/ssh",
    "/etc/ld.so.preload",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/profile",
    "/etc/profile.d",
    "/etc/environment",
    "/etc/security",
    "/etc/network",
)


def allowed_path(path):
    """Проверяет разрешённые корни и исключает пути, способные изменить работу ОС."""
    resolved = os.path.realpath(path)
    if any(
        resolved == denied or resolved.startswith(denied + "/")
        for denied in DENIED_PATHS
    ):
        return False
    if ".ssh" in Path(resolved).parts or Path(resolved).name in (
        ".bashrc",
        ".bash_profile",
        ".profile",
        ".zshrc",
    ):
        return False
    if Path(resolved).suffix.lower() in (
        ".sh",
        ".py",
        ".php",
        ".pl",
        ".rb",
        ".so",
        ".service",
        ".timer",
    ):
        return False
    return any(
        os.path.commonpath([resolved, os.path.realpath(root)]) == os.path.realpath(root)
        for root in ALLOWED_DIRS
    )


def target_file(task, records=()):
    """Выбирает ручной путь или свободный каталог с наименьшим числом приманок."""
    filename = task["filename"]
    if filename in ("", ".", "..") or any(c in filename for c in "/\\\x00\r\n"):
        raise ValueError("Некорректное имя файла.")
    target = task.get("target_path", "")
    if target:
        if not os.path.isabs(target) or ".." in Path(target).parts:
            raise ValueError("Укажите абсолютный путь без '..'.")
        path = (
            target
            if task.get("target_kind") == "file"
            else os.path.join(target, filename)
        )
    else:
        counts = {}
        for record in records:
            if (
                record.get("status") in ("writing", "deployed")
                and record.get("file_state") != "missing"
                and record.get("path")
            ):
                parent = os.path.dirname(os.path.abspath(record["path"]))
                counts[parent] = counts.get(parent, 0) + 1
        directories = []
        for candidate in AUTO_DIRS:
            if not os.path.isabs(candidate):
                continue
            candidate = os.path.abspath(candidate)
            if (
                candidate in directories
                or not allowed_path(os.path.join(candidate, filename))
                or not os.access(candidate, os.W_OK | os.X_OK)
            ):
                continue
            try:
                descriptor = open_directory(candidate)
            except OSError:
                continue
            os.close(descriptor)
            directories.append(candidate)
        if not directories:
            raise ValueError("Нет доступного для записи каталога в AGENT_AUTO_DIRS.")
        available = [
            directory
            for directory in directories
            if not os.path.lexists(os.path.join(directory, filename))
        ]
        if not available:
            raise FileExistsError(
                "Файл с таким именем уже существует во всех доступных каталогах. Выберите другое имя."
            )
        # При равной загрузке сохраняем приоритет из AGENT_AUTO_DIRS.
        directory = min(available, key=lambda item: counts.get(item, 0))
        path = os.path.join(directory, filename)
    if not allowed_path(path):
        raise ValueError("Каталог не входит в список AGENT_ALLOWED_DIRS.")
    if not os.path.isdir(os.path.dirname(path)):
        raise ValueError("Каталог размещения не существует.")
    return os.path.abspath(path)


def open_directory(path):
    """Открывает каталог по компонентам, запрещая переход через символьные ссылки."""
    # Дескрипторы каталогов защищают запись от подмены ссылки между проверкой и открытием.
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in Path(path).parts[1:]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def write_file(path, payload, token_id):
    """Создаёт новый файл без перезаписи, сохраняет метку приманки и безопасные права."""
    directory = open_directory(os.path.dirname(path))
    try:
        descriptor = os.open(
            os.path.basename(path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.setxattr(stream.fileno(), "user.luregenix.token_id", token_id.encode())
            os.fchmod(stream.fileno(), FILE_MODE)
            os.fsync(stream.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)


def owned_file(path, token_id):
    """Отличает собственную приманку от чужого файла при восстановлении после сбоя."""
    try:
        return (
            stat.S_ISREG(os.lstat(path).st_mode)
            and os.getxattr(
                path, "user.luregenix.token_id", follow_symlinks=False
            ).decode()
            == token_id
        )
    except OSError:
        return False


def discover_ip():
    """Берёт заданный IP или определяет исходящий адрес по маршруту к шлюзу."""
    if NODE_IP:
        return NODE_IP
    parsed = urlsplit(GATEWAY_URL)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.connect(
            (parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        )
        address = connection.getsockname()[0]
        if address.startswith("127."):
            try:
                # connect у UDP выбирает маршрут, но не отправляет пакеты на этот адрес.
                connection.connect(("192.0.2.1", 9))
                address = connection.getsockname()[0]
            except OSError:
                pass
        return address


def deployment_error(exc):
    """Переводит ошибки файловой системы в понятный текст для веб-интерфейса."""
    if isinstance(exc, FileExistsError):
        return "Файл уже существует. Выберите другое имя файла."
    if isinstance(exc, OSError):
        return {
            errno.EACCES: "Недостаточно прав для доступа к файлу или каталогу.",
            errno.EPERM: "Операция с файлом запрещена.",
            errno.ENOENT: "Файл или каталог не найден.",
            errno.ENOTDIR: "Путь содержит файл вместо каталога или символьную ссылку.",
            errno.ELOOP: "Символьные ссылки в пути размещения запрещены.",
            errno.ENOSPC: "На сервере закончилось свободное место.",
            errno.EROFS: "Файловая система доступна только для чтения.",
            errno.ENOTSUP: "Файловая система не поддерживает метки владельца приманки.",
        }.get(exc.errno, "Не удалось записать файл. Проверьте журнал агента.")
    message = str(exc)
    if message and "А" <= message[0] <= "я":
        return message[:1000]
    return "Не удалось разместить файл. Проверьте журнал агента."


class Agent:
    """Хранит идентичность, задания и очередь событий независимо от доступности сервера."""

    def __init__(self, monitor):
        """Загружает локальный журнал и восстанавливает наблюдение за размещёнными файлами."""
        self.monitor = monitor
        self.node_id = None
        self.session = requests.Session()
        self.session.verify = os.getenv("AGENT_CA_FILE") or True
        self.state = {"tasks": {}, "events": []}
        if STATE_FILE.exists():
            # Повреждённый журнал не сбрасываем: иначе можно потерять очередь и повторить запись.
            self.state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        self.state.setdefault("agent_id", str(uuid.uuid4()))
        self.state.setdefault("credential", secrets.token_urlsafe(48))
        self.state["events"] = [
            event
            for event in self.state["events"]
            if event.get("action") != "heartbeat"
        ]
        self.session.headers.update(
            {
                "X-Agent-Id": self.state["agent_id"],
                "X-Agent-Token": self.state["credential"],
            }
        )
        self.persist()
        self.watches = {}
        self.last_alert = {}
        self.monitor_failures = set()
        for record in self.state["tasks"].values():
            if record["status"] == "deployed":
                self.restore_monitor(
                    {"token_id": record["token_id"], "deployed_path": record["path"]}
                )

    def persist(self):
        """Атомарно сохраняет журнал и синхронизирует его с диском перед сетевыми операциями."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = STATE_FILE.with_suffix(".tmp")
        descriptor = os.open(
            str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(self.state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_FILE)
        if sys.platform == "linux":
            directory = os.open(str(STATE_FILE.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def request(self, method, path, **kwargs):
        """Обращается к API со своим ключом агента и обязательной проверкой TLS-сертификата."""
        response = self.session.request(
            method, f"{GATEWAY_URL}/api/{path}", timeout=10, **kwargs
        )
        response.raise_for_status()
        return response.json()

    def register(self):
        """Регистрирует ноду или обновляет её heartbeat, сохраняя подтверждённое время связи."""
        result = self.request(
            "POST",
            "register",
            headers={"X-Agent-Secret": AGENT_SECRET},
            json={
                "hostname": NODE_HOSTNAME,
                "ip": discover_ip(),
                "agent_id": self.state["agent_id"],
                "credential": self.state["credential"],
            },
        )
        self.node_id = result["node_id"]
        self.state["node_id"] = self.node_id
        self.state["last_registration"] = time.time()
        self.persist()

    def queue_event(self, token_id, action, path=""):
        """Записывает событие с UUID и временем обнаружения до первой попытки доставки."""
        self.state["events"].append(
            {
                "event_id": str(uuid.uuid4()),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "token_id": token_id,
                "action": action,
                "file_path": path,
                "source_hostname": NODE_HOSTNAME,
            }
        )
        self.persist()

    def flush_events(self):
        """Доставляет очередь; временные сбои не удаляют события, отклонённые сохраняются отдельно."""
        deadline = time.monotonic() + 2
        while self.state["events"] and time.monotonic() < deadline:
            if "event_id" not in self.state["events"][0]:
                self.state["events"][0]["event_id"] = str(uuid.uuid4())
                self.persist()
            try:
                result = self.request(
                    "POST", "agent/event", json=self.state["events"][0]
                )
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code not in (
                    400,
                    403,
                    404,
                    409,
                    422,
                ):
                    raise
                rejected = self.state.setdefault("rejected_events", [])
                rejected.append(self.state["events"].pop(0))
                self.state["rejected_events"] = rejected[-100:]
                self.persist()
                logger.error(
                    "Отклонённое событие сохранено в локальном журнале (HTTP %s)",
                    exc.response.status_code,
                )
                continue
            if result.get("status") != "ok":
                raise RuntimeError("Событие не сохранено сервером.")
            self.state["events"].pop(0)
            self.persist()

    def watch(self, token_id, path):
        """Наблюдает за родительским каталогом, чтобы видеть удаление и замену файла."""
        from inotify_simple import flags

        if not allowed_path(path):
            raise ValueError("Путь мониторинга не входит в список AGENT_ALLOWED_DIRS.")
        parent = os.path.dirname(path)
        for entry in self.watches.values():
            if entry["parent"] == parent:
                entry["files"][os.path.basename(path)] = token_id
                return
        mask = (
            flags.OPEN
            | flags.ACCESS
            | flags.MODIFY
            | flags.CLOSE_WRITE
            | flags.ATTRIB
            | flags.DELETE
            | flags.MOVED_FROM
            | flags.MOVED_TO
            | flags.CREATE
            | flags.DELETE_SELF
            | flags.MOVE_SELF
            | flags.ONLYDIR
            | flags.DONT_FOLLOW
        )
        descriptor = self.monitor.add_watch(parent, mask)
        self.watches[descriptor] = {
            "parent": parent,
            "files": {os.path.basename(path): token_id},
        }

    def deploy(self, task):
        """Проверяет содержимое и размещает файл один раз на попытку, используя журнал восстановления."""
        key = task["token_id"]
        record = self.state["tasks"].get(key)
        if (
            record
            and record["status"] == "failed"
            and record.get("attempt", 1) != task.get("attempt", 1)
        ):
            record = None
        if record and record["status"] in ("deployed", "failed"):
            return record
        try:
            payload = base64.b64decode(task["content_base64"], validate=True)
            if len(payload) > 1_000_000:
                raise ValueError("Размер файла превышает ограничение агента (1 МБ).")
            if hashlib.sha256(payload).hexdigest() != task["sha256"]:
                raise ValueError(
                    "Контрольная сумма файла не совпадает. Размещение отменено."
                )
            path = (
                record["path"]
                if record else target_file(task, self.state["tasks"].values())
            )
            if record is None:
                record = {
                    "status": "writing",
                    "path": path,
                    "token_id": task["token_id"],
                }
                self.state["tasks"][key] = record
                self.persist()
            if os.path.lexists(path):
                if not owned_file(path, task["token_id"]):
                    raise FileExistsError(
                        "Файл уже существует. Выберите другое имя файла."
                    )
                # После сбоя файл мог записаться без подтверждения серверу: сверяем владельца и хеш.
                with os.fdopen(
                    os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb"
                ) as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != task["sha256"]:
                        raise ValueError(
                            "Ранее размещённый файл изменён. Перезапись запрещена."
                        )
            else:
                write_file(path, payload, task["token_id"])
            self.monitor_events(timeout=0)
            self.watch(task["token_id"], path)
            record.update(status="deployed", error="", file_state="present")
        except Exception as exc:
            logger.warning("Размещение %s не выполнено (%s)", key, type(exc).__name__)
            record = {
                "status": "failed",
                "path": record["path"] if record else "",
                "token_id": task["token_id"],
                "error": deployment_error(exc),
            }
        self.state["tasks"][key] = record
        record["attempt"] = task.get("attempt", 1)
        self.persist()
        return record

    def poll_tasks(self):
        """Получает задания своей ноды и восстанавливает наблюдение за готовыми приманками."""
        tasks = self.request("GET", "agent/tasks", params={"node_id": self.node_id})
        for task in tasks:
            if task["status"] == "deployed":
                self.restore_monitor(task)
            else:
                self.report_deployment(task, self.deploy(task))

    def restore_monitor(self, task):
        """Восстанавливает наблюдение и сверяет файл, не создавая удалённую приманку заново."""
        key = task["token_id"]
        record = self.state["tasks"].get(key)
        if (
            not record
            or record["status"] != "deployed"
            or record["path"] != task["deployed_path"]
        ):
            record = {
                "status": "deployed",
                "path": task["deployed_path"],
                "token_id": key,
                "announced": True,
            }
            self.state["tasks"][key] = record
            self.persist()
        watch_error = None
        try:
            self.watch(key, task["deployed_path"])
            self.monitor_failures.discard(key)
        except (OSError, ValueError) as exc:
            watch_error = exc
        # Проверка нужна и при недоступном родительском каталоге; stat не вызывает чтение приманки.
        file_state = self.check_file(record)
        if watch_error is not None and key not in self.monitor_failures:
            if file_state == "present":
                self.queue_event(key, "monitor_error", task["deployed_path"])
            self.monitor_failures.add(key)
            logger.warning("Ошибка мониторинга %s: %s", task["deployed_path"], watch_error)

    def check_file(self, record):
        """Обнаруживает пропажу файла даже после простоя; состояние и тревогу сохраняет вместе."""
        path = record["path"]
        try:
            if not allowed_path(path):
                raise ValueError("Путь мониторинга не входит в список AGENT_ALLOWED_DIRS.")
            directory = open_directory(os.path.dirname(path))
            try:
                metadata = os.stat(
                    os.path.basename(path), dir_fd=directory, follow_symlinks=False
                )
            finally:
                os.close(directory)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Вместо приманки обнаружен каталог или символьная ссылка.")
            state, action = "present", None
        except FileNotFoundError:
            state, action = "missing", "delete"
        except (OSError, ValueError) as exc:
            state, action = "error", "monitor_error"
            if record.get("file_state") != state:
                logger.warning("Не удалось проверить приманку %s: %s", path, exc)
        if record.get("file_state") != state:
            record["file_state"] = state
            if action:
                self.queue_event(record["token_id"], action, path)
            else:
                self.persist()
        return state

    def report_deployment(self, task, record):
        """Подтверждает результат серверу и добавляет уведомление о размещении в локальную очередь."""
        result = self.request(
            "PUT",
            f"agent/tasks/{task['id']}/result",
            json={
                "node_id": self.node_id,
                "status": record["status"],
                "deployed_path": record["path"]
                if record["status"] == "deployed"
                else "",
                "error": record.get("error", ""),
                "attempt": task.get("attempt", 1),
            },
        )
        if result.get("status") != "ok":
            raise RuntimeError("Результат размещения не сохранён сервером.")
        # Событие и отметку announced сохраняем вместе, чтобы сбой между записями не дал дубль.
        if not record.get("announced"):
            record["announced"] = True
            self.queue_event(
                task["token_id"],
                "deployed" if record["status"] == "deployed" else "deployment_failed",
                record["path"],
            )

    def monitor_events(self, timeout=1000):
        """Сводит события inotify в действия над приманками и подавляет повторы в течение 2 секунд."""
        from inotify_simple import flags

        batch = {}
        for event in self.monitor.read(timeout=timeout):
            if event.mask & flags.Q_OVERFLOW:
                self.queue_event(
                    f"node_{self.node_id}", "monitor_error", "inotify queue overflow"
                )
                continue
            entry = self.watches.get(event.wd)
            if not entry:
                continue
            if event.mask & (flags.DELETE_SELF | flags.MOVE_SELF | flags.IGNORED):
                for filename, token_id in entry["files"].items():
                    batch[token_id] = (
                        "delete",
                        os.path.join(entry["parent"], filename),
                        4,
                    )
                self.watches.pop(event.wd, None)
                if not event.mask & flags.IGNORED:
                    try:
                        self.monitor.rm_watch(event.wd)
                    except OSError:
                        pass
                continue
            token_id = entry["files"].get(event.name)
            if not token_id:
                continue
            action, priority = "open", 1
            if event.mask & (flags.DELETE | flags.MOVED_FROM):
                action, priority = "delete", 4
            elif event.mask & (
                flags.MODIFY
                | flags.CLOSE_WRITE
                | flags.ATTRIB
                | flags.MOVED_TO
                | flags.CREATE
            ):
                action, priority = "modify", 3
            elif event.mask & flags.ACCESS:
                action, priority = "access", 2
            previous = batch.get(token_id)
            if not previous or priority > previous[2]:
                batch[token_id] = (
                    action,
                    os.path.join(entry["parent"], event.name),
                    priority,
                )
        now = time.monotonic()
        for token_id, (action, path, _) in batch.items():
            cooldown_key = (token_id, action)
            record = self.state["tasks"].get(token_id)
            if action == "delete" and record and record.get("file_state") == "missing":
                continue
            if now - self.last_alert.get(cooldown_key, -10) >= 2:
                if record:
                    if action == "delete":
                        record["file_state"] = "missing"
                    elif action == "modify":
                        record["file_state"] = "present"
                self.queue_event(token_id, action, path)
                self.last_alert[cooldown_key] = now


def main():
    """Запускает единственный экземпляр агента и чередует heartbeat, задания и доставку событий."""
    if sys.platform != "linux":
        raise SystemExit("Запускайте агент непосредственно на целевом Linux-сервере.")
    if len(AGENT_SECRET) < 32:
        raise SystemExit(
            "Задайте AGENT_SECRET: секрет регистрации, настроенный на основном сервере."
        )
    if not 1 <= HEARTBEAT_INTERVAL <= 120 or not 1 <= TASK_POLL_INTERVAL <= 60:
        raise SystemExit(
            "Интервал heartbeat должен быть 1..120 секунд, опрос заданий — 1..60 секунд."
        )
    gateway = urlsplit(GATEWAY_URL)
    if (
        gateway.scheme not in ("http", "https")
        or not gateway.hostname
        or gateway.username
        or gateway.password
        or gateway.query
        or gateway.fragment
    ):
        raise SystemExit(
            "GATEWAY_URL должен быть HTTP(S)-адресом без логина, пароля и параметров."
        )
    import fcntl

    from inotify_simple import INotify

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Один журнал обслуживает только один процесс, иначе возможно повторное размещение.
    with open(STATE_FILE.with_suffix(".lock"), "w") as lock, INotify() as monitor:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        agent = Agent(monitor)
        heartbeat_at = poll_at = delivery_at = 0
        while True:
            now = time.monotonic()
            if now >= heartbeat_at:
                try:
                    agent.register()
                    heartbeat_at = now + HEARTBEAT_INTERVAL
                except Exception as exc:
                    logger.warning("Ошибка регистрации или heartbeat: %s", exc)
                    heartbeat_at = now + 10
            if agent.node_id and now >= poll_at:
                try:
                    agent.poll_tasks()
                except Exception as exc:
                    logger.warning("Ошибка получения заданий: %s", exc)
                poll_at = now + TASK_POLL_INTERVAL
            agent.monitor_events()
            if time.monotonic() >= delivery_at:
                try:
                    agent.flush_events()
                except Exception as exc:
                    logger.warning("Ошибка доставки событий: %s", exc)
                delivery_at = time.monotonic() + 5


if __name__ == "__main__":
    main()
