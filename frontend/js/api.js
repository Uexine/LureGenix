/**
 * Единый модуль для запросов к API. Все вызовы идут через /api/, с JWT в заголовке.
 */
const API_BASE = "";

function getToken() {
    return localStorage.getItem("token");
}

function getUsername() {
    return localStorage.getItem("username") || "Admin";
}

function setAuth(token, username) {
    if (token) localStorage.setItem("token", token);
    if (username) localStorage.setItem("username", username);
}

function clearAuth() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
}

/**
 * GET/POST к API с авторизацией. При 401 — редирект на логин.
 * @param {string} path - путь без ведущего слэша, например "events", "tokens"
 * @param {object} opts - { method, body }
 * @returns {Promise<{ ok: boolean, data?: any, status: number }>}
 */
async function api(path, opts = {}) {
    const token = getToken();
    if (!token) {
        window.location.href = "/";
        return { ok: false, status: 401 };
    }
    const url = (path.startsWith("/") ? path : "/api/" + path).replace(/\/+/g, "/");
    const headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token,
    };
    const options = {
        method: opts.method || "GET",
        headers,
    };
    if (opts.body !== undefined && opts.method !== "GET") {
        options.body = typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
    }
    try {
        const r = await fetch(url, options);
        if (r.status === 401) {
            clearAuth();
            window.location.href = "/";
            return { ok: false, status: 401 };
        }
        const data = r.ok ? await r.json().catch(() => ({})) : await r.json().catch(() => ({ detail: "Ошибка сервера" }));
        return { ok: r.ok, data, status: r.status };
    } catch (e) {
        console.error("api error", path, e);
        return { ok: false, data: { detail: String(e.message) }, status: 0 };
    }
}

async function apiGet(path) {
    return api(path, { method: "GET" });
}

async function apiPost(path, body) {
    return api(path, { method: "POST", body });
}
