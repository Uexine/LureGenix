(function () {
    if (!getToken()) {
        window.location.href = "/";
        return;
    }

    let ws = null;
    const sections = {
        dashboard: { title: "Дашборд безопасности", subtitle: "Отслеживайте активность honeytoken'ов в реальном времени" },
        nodes:     { title: "Ноды", subtitle: "Активные ноды сети" },
        tokens:    { title: "Honeytokens", subtitle: "Список созданных приманок" },
        events:    { title: "События", subtitle: "Журнал событий" },
    };

    document.addEventListener("DOMContentLoaded", function () {
        document.getElementById("userName").textContent = getUsername();
        const avatar = document.getElementById("userAvatar");
        const u = getUsername();
        avatar.textContent = u ? u.charAt(0).toUpperCase() : "A";

        document.querySelectorAll(".sidebar-nav a[data-section]").forEach(function (a) {
            a.addEventListener("click", function (e) {
                e.preventDefault();
                showSection(a.getAttribute("data-section"));
            });
        });

        showSection("dashboard");
        loadNodes();
        loadTokens();
        loadEvents();
        initWebSocket();
    });

    function showSection(id) {
        document.querySelectorAll(".section-content").forEach(function (el) {
            el.classList.toggle("hidden", el.id !== "section-" + id);
        });
        document.querySelectorAll(".sidebar-nav a[data-section]").forEach(function (a) {
            a.classList.toggle("active", a.getAttribute("data-section") === id);
        });
        const s = sections[id];
        if (s) {
            document.getElementById("pageTitle").textContent = s.title;
            document.getElementById("pageSubtitle").textContent = s.subtitle;
        }
    }

    async function loadNodes(refresh) {
        const res = await apiGet("nodes");
        if (res.status === 401) return;
        const data = Array.isArray(res.data) ? res.data : [];
        const tbody = document.getElementById("nodesTable");
        const select = document.getElementById("nodeSelect");
        document.getElementById("nodeCount").textContent = data.length;

        select.innerHTML = data.length
            ? data.map(function (n) {
                return "<option value=\"" + (n.id || 1) + "\">" + (n.hostname || "node" + n.id) + " (" + (n.ip || "-") + ")</option>";
            }).join("")
            : "<option value=\"1\">agent1 (127.0.0.1)</option>";

        if (data.length === 0) {
            tbody.innerHTML = "<tr><td colspan=\"5\" style=\"text-align:center;color:var(--text-secondary);\">Нет данных о нодах</td></tr>";
            return;
        }
        tbody.innerHTML = data.map(function (node) {
            return "<tr><td>#" + node.id + "</td><td><strong>" + (node.hostname || "-") + "</strong></td><td>" + (node.ip || "-") + "</td>" +
                "<td><span class=\"status-badge status-active\"><i class=\"fas fa-circle\" style=\"font-size:0.6rem;margin-right:4px;\"></i> Активен</span></td>" +
                "<td><button class=\"btn btn-outline\" style=\"padding:4px 8px;\"><i class=\"fas fa-eye\"></i></button></td></tr>";
        }).join("");
    }

    async function loadTokens(refresh) {
        const res = await apiGet("tokens");
        if (res.status === 401) return;
        const data = Array.isArray(res.data) ? res.data : [];
        document.getElementById("tokenCount").textContent = data.length;

        const tbody = document.getElementById("tokensTable");
        if (data.length === 0) {
            tbody.innerHTML = "<tr><td colspan=\"4\" style=\"text-align:center;color:var(--text-secondary);\">Нет honeytoken'ов</td></tr>";
            return;
        }
        tbody.innerHTML = data.map(function (t) {
            const id = t.id || "-";
            const type = t.type || "-";
            const placement = t.placement || "-";
            const path = t.path || "-";
            const created = t.created_at ? new Date(t.created_at).toLocaleString() : "-";
            return "<tr><td><code>" + escapeHtml(id) + "</code> / " + escapeHtml(type) + "</td><td>" + escapeHtml(placement) + "</td><td><code style=\"font-size:0.85em;\">" + escapeHtml(path) + "</code></td><td>" + created + "</td></tr>";
        }).join("");
    }

    async function loadEvents(refresh) {
        const res = await apiGet("events");
        if (res.status === 401) return;
        const data = Array.isArray(res.data) ? res.data : [];
        document.getElementById("eventCount").textContent = data.length;

        const alertCount = data.filter(function (e) { return e.action === "alert" || e.action === "compromise"; }).length;
        document.getElementById("alertCount").textContent = alertCount;
        var badge = document.getElementById("sidebarEventBadge");
        if (badge) {
            badge.textContent = data.length;
            badge.style.display = data.length > 0 ? "" : "none";
        }

        const html = data.length === 0
            ? "<div style=\"text-align:center;padding:40px;color:var(--text-secondary);\">Нет событий</div>"
            : data.map(eventRow).join("");

        document.getElementById("eventsList").innerHTML = html;
        document.getElementById("eventsListFull").innerHTML = html;
    }

    function eventRow(event) {
        const rawDate = event.created_at || event.time;
        const date = rawDate ? new Date(rawDate) : new Date();
        const action = event.action || event.type || "event";
        const tokenId = event.token_id || event.source || "-";
        let icon = "fa-info-circle", color = "var(--primary)";
        if (action === "heartbeat") { icon = "fa-heartbeat"; color = "var(--secondary)"; }
        else if (action === "access" || action === "compromise") { icon = "fa-download"; color = "var(--warning)"; }
        else if (action === "alert") { icon = "fa-exclamation-triangle"; color = "var(--danger)"; }
        return "<div class=\"event-item\"><div class=\"event-icon\" style=\"color:" + color + ";\"><i class=\"fas " + icon + "\"></i></div>" +
            "<div class=\"event-content\"><div class=\"event-title\"><strong>" + escapeHtml(action) + "</strong> для токена " + escapeHtml(tokenId) + "</div>" +
            "<div class=\"event-time\"><i class=\"far fa-clock\" style=\"margin-right:4px;\"></i>" + date.toLocaleString() + "</div></div>" +
            "<div class=\"event-type\">" + escapeHtml(event.file_path || "N/A") + "</div></div>";
    }

    function escapeHtml(s) {
        if (s == null) return "";
        var div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    }

    async function generateToken() {
        var btn = document.getElementById("btnGenerate");
        var nodeId = document.getElementById("nodeSelect").value;
        var type = document.getElementById("typeSelect").value;
        var name = (document.getElementById("tokenName").value || "").trim();
        btn.disabled = true;
        btn.innerHTML = "<i class=\"fas fa-spinner fa-spin\"></i> Генерация...";
        var res = await apiPost("generate", { node_id: nodeId, type: type, name: name });
        btn.disabled = false;
        btn.innerHTML = "<i class=\"fas fa-plus\"></i> Сгенерировать";
        if (res.status === 401) return;
        if (res.ok) {
            showNotification("Honeytoken создан", "success");
            document.getElementById("tokenName").value = "";
            loadTokens();
            loadEvents();
        } else {
            var msg = "Ошибка создания токена";
            if (res.data && res.data.detail) {
                msg += ": " + (typeof res.data.detail === "string" ? res.data.detail : (Array.isArray(res.data.detail) ? res.data.detail.map(function(d) { return d.msg || d.loc || JSON.stringify(d); }).join(", ") : JSON.stringify(res.data.detail)));
            }
            showNotification(msg, "error");
        }
    }

    function initWebSocket() {
        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = protocol + "//" + window.location.host + "/ws/events";
        ws = new WebSocket(url);
        ws.onopen = function () {
            updateWsStatus(true);
        };
        ws.onmessage = function (ev) {
            var payload = {};
            try { payload = JSON.parse(ev.data); } catch (e) {}
            var list = document.getElementById("eventsList");
            if (list && list.innerHTML.indexOf("spinner") === -1) {
                var wrap = document.createElement("div");
                wrap.innerHTML = eventRow(payload);
                list.insertBefore(wrap.firstChild, list.firstChild);
            }
            var ec = document.getElementById("eventCount");
            if (ec) ec.textContent = parseInt(ec.textContent || "0", 10) + 1;
            if (payload.action === "alert" || payload.action === "compromise") {
                var ac = document.getElementById("alertCount");
                if (ac) ac.textContent = parseInt(ac.textContent || "0", 10) + 1;
                showNotification("Тревога: " + (payload.token_id || ""), "error");
            }
        };
        ws.onerror = ws.onclose = function () {
            updateWsStatus(false);
            setTimeout(initWebSocket, 5000);
        };
    }

    function updateWsStatus(connected) {
        var el = document.getElementById("wsStatus");
        var text = document.getElementById("wsStatusText");
        if (!el) return;
        el.className = "status-badge " + (connected ? "status-active" : "status-warning");
        if (text) text.textContent = connected ? "WebSocket подключен" : "WebSocket отключен";
    }

    function showNotification(message, type) {
        type = type || "info";
        var bg = type === "success" ? "var(--secondary)" : type === "error" ? "var(--danger)" : "var(--primary)";
        var n = document.createElement("div");
        n.style.cssText = "position:fixed;top:20px;right:20px;padding:16px 24px;background:" + bg + ";color:white;border-radius:12px;box-shadow:0 10px 15px -3px rgba(0,0,0,0.3);z-index:9999;";
        n.textContent = message;
        document.body.appendChild(n);
        setTimeout(function () { n.remove(); }, 3000);
    }

    function logout() {
        clearAuth();
        window.location.href = "/";
    }

    setInterval(function () {
        loadNodes();
        loadTokens();
        loadEvents();
    }, 30000);

    window.toggleSidebar = function () {
        document.getElementById("sidebar").classList.toggle("collapsed");
        document.getElementById("mainContent").classList.toggle("expanded");
    };
    window.loadNodes = loadNodes;
    window.loadTokens = loadTokens;
    window.loadEvents = loadEvents;
    window.generateToken = generateToken;
    window.logout = logout;
})();
