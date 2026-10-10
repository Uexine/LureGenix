function getToken() {
    return sessionStorage.getItem("token");
}

function getUsername() {
    return sessionStorage.getItem("username") || "Admin";
}

function clearAuth() {
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("username");
}

function apiError(result, fallback = "Ошибка сервера") {
    let detail = result.data && result.data.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) detail = detail.detail;
    if (Array.isArray(detail)) return detail.map(item => item.msg || fallback).join(", ");
    return typeof detail === "string" ? detail : fallback;
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

function apiGet(path) {
    return api(path);
}

function apiPost(path, body) {
    return api(path, {method: "POST", body});
}

function apiPut(path, body = {}) {
    return api(path, {method: "PUT", body});
}
