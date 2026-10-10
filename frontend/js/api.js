function getToken() {
    return sessionStorage.getItem("token");
}

function getUsername() {
    return sessionStorage.getItem("username") || "Администратор";
}

function clearAuth() {
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("username");
}

function userError(message, fallback = "Не удалось выполнить действие. Повторите попытку.") {
    if (typeof message !== "string") return fallback;
    const translations = {
        "File already exists; choose a different filename": "Файл уже существует. Выберите другое имя файла.",
        "Previously deployed file has changed; refusing to overwrite": "Ранее размещённый файл изменён. Перезапись запрещена.",
        "Invalid filename": "Некорректное имя файла.",
        "Target must be an absolute path without '..'": "Укажите абсолютный путь без '..'.",
        "Specify an absolute Linux path without '..'": "Укажите абсолютный путь Linux без '..'.",
        "No existing writable directory in AGENT_AUTO_DIRS": "Нет доступного для записи каталога для автоматического размещения.",
        "Target is outside AGENT_ALLOWED_DIRS": "Каталог не входит в список разрешённых для агента.",
        "Monitor path is outside AGENT_ALLOWED_DIRS": "Путь мониторинга не входит в список разрешённых для агента.",
        "Target directory does not exist": "Каталог размещения не существует.",
        "File payload exceeds the agent size limit": "Размер файла превышает ограничение агента.",
        "File payload checksum mismatch": "Контрольная сумма файла не совпадает. Размещение отменено.",
        "Filename must contain only a filename, without directories": "Укажите только имя файла, без каталогов.",
        "Unsupported honeytoken type": "Неподдерживаемый тип приманки.",
        "Node not found; install and register a Linux agent first": "Сервер не найден. Сначала установите и зарегистрируйте Linux-агент.",
        "This legacy node has no enrolled Linux agent": "Для этой старой ноды не зарегистрирован Linux-агент.",
        "Only a failed deployment can be retried": "Повторить можно только неудачное размещение.",
        "Specify a valid network CIDR": "Укажите корректную подсеть в формате CIDR.",
        "Discovery supports IPv4 networks of at most 256 addresses": "Поддерживаются только подсети IPv4 размером не более 256 адресов.",
        "Network is outside DISCOVERY_ALLOWED_CIDRS": "Подсеть не входит в список разрешённых для сканирования.",
        "A discovery scan is already running": "Сканирование уже выполняется. Дождитесь завершения.",
        "Generation capacity exceeded; try again later": "Генератор занят. Повторите попытку позже.",
        "Backend service unavailable": "Сервис временно недоступен. Повторите попытку.",
        "Backend request failed": "Не удалось выполнить запрос к сервису.",
        "Invalid response from backend service": "Сервис вернул некорректный ответ.",
        "Current password required": "Введите текущий пароль.",
        "Current password is incorrect": "Текущий пароль неверен.",
        "Password must contain at least 12 characters and at most 72 UTF-8 bytes": "Пароль должен содержать не менее 12 символов и не более 72 байт UTF-8.",
        "Event not found": "Событие не найдено.",
        "Event storage unavailable": "Хранилище событий временно недоступно.",
        "Forbidden": "Недостаточно прав для выполнения действия.",
    };
    if (Object.hasOwn(translations, message)) return translations[message];
    if (/Permission denied|Operation not permitted/.test(message)) return "Недостаточно прав для доступа к файлу или каталогу.";
    if (/No such file or directory/.test(message)) return "Файл или каталог не найден.";
    if (/No space left on device/.test(message)) return "На сервере закончилось свободное место.";
    if (/Read-only file system/.test(message)) return "Файловая система доступна только для чтения.";
    // Older agents and validation libraries may still return English diagnostics.
    return /^[А-Яа-яЁё]/.test(message) ? message : fallback;
}

function apiError(result, fallback = "Ошибка сервера") {
    let detail = result.data && result.data.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) detail = detail.detail;
    if (Array.isArray(detail)) return "Проверьте заполнение полей: " + [...new Set(detail.map(item => {
        const fields = {node_id: "сервер", type: "тип приманки", name: "название", filename: "имя файла", node_path: "каталог", target_kind: "тип пути", generation_mode: "режим генерации", ids: "выбранные события", clear_all: "очистка журнала", subnet: "подсеть"};
        return fields[(item.loc || [])[1]] || "данные запроса";
    }))].join(", ") + ".";
    return userError(detail, fallback);
}

async function api(path, {method = "GET", body} = {}) {
    const token = getToken();
    if (!token) {
        window.location.href = "/";
        return {ok: false, status: 401};
    }
    const options = {
        method,
        headers: {"Content-Type": "application/json", "Authorization": "Bearer " + token},
    };
    if (body !== undefined && method !== "GET") options.body = JSON.stringify(body);
    try {
        const response = await fetch("/api/" + path.replace(/^\/+/, ""), options);
        if (response.status === 401) {
            clearAuth();
            window.location.href = "/";
            return {ok: false, status: 401};
        }
        const data = await response.json().catch(() => ({detail: "Неверный ответ сервера"}));
        return {ok: response.ok, data, status: response.status};
    } catch {
        return {ok: false, data: {detail: "Нет соединения с сервером"}, status: 0};
    }
}

const pendingGets = new Map();

function apiGet(path) {
    // Views and socket updates can request the same data at the same time.
    if (!pendingGets.has(path)) {
        pendingGets.set(path, api(path).finally(() => pendingGets.delete(path)));
    }
    return pendingGets.get(path);
}

function apiPost(path, body) {
    return api(path, {method: "POST", body});
}

function apiPut(path, body = {}) {
    return api(path, {method: "PUT", body});
}
