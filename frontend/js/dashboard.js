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
        map:       { title: "Карта сети", subtitle: "Ноды и приманки на них" },
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
        loadTokenTypes();
        loadTokens();
        loadEvents();
        loadNetworkMap();
        initWebSocket();
    });

    async function loadTokenTypes() {
        const select = document.getElementById("typeSelect");
        if (!select) return;
        var list = [];
        var res = await apiGet("token-types");
        if (res.status === 401) return;
        if (res.ok && Array.isArray(res.data)) list = res.data;
        if (list.length === 0) {
            list = [
                { name: "ssh_key", description: "Приватный SSH-ключ" },
                { name: "env_file", description: "Файл .env" },
                { name: "api_key", description: "Ключ API" },
                { name: "password", description: "Пароль" },
                { name: "pdf", description: "PDF" },
                { name: "docx", description: "Word" }
            ];
        }
        select.innerHTML = list.map(function (t) {
            return "<option value=\"" + escapeHtml(t.name) + "\">" + escapeHtml(t.description || t.name) + "</option>";
        }).join("");
    }

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
        if (id === "map") loadNetworkMap();
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
        var savePath = (document.getElementById("tokenSavePath") ? document.getElementById("tokenSavePath").value || "" : "").trim();
        var nodePath = (document.getElementById("tokenNodePath") ? document.getElementById("tokenNodePath").value || "" : "").trim();
        btn.disabled = true;
        btn.innerHTML = "<i class=\"fas fa-spinner fa-spin\"></i> Генерация...";
        var payload = { node_id: nodeId, type: type, name: name };
        if (savePath) payload.save_path = savePath;
        if (nodePath) payload.node_path = nodePath;
        var res = await apiPost("generate", payload);
        btn.disabled = false;
        btn.innerHTML = "<i class=\"fas fa-plus\"></i> Сгенерировать";
        if (res.status === 401) return;
        if (res.ok) {
            showNotification("Honeytoken создан", "success");
            if (document.getElementById("tokenName")) document.getElementById("tokenName").value = "";
            /* Каталог и путь на ноде не очищаем — удобно создавать несколько приманок подряд */
            loadTokens();
            loadEvents();
            loadNetworkMap();
        } else {
            var msg = "Ошибка создания токена";
            if (res.data && res.data.detail) {
                msg += ": " + (typeof res.data.detail === "string" ? res.data.detail : (Array.isArray(res.data.detail) ? res.data.detail.map(function(d) { return d.msg || d.loc || JSON.stringify(d); }).join(", ") : JSON.stringify(res.data.detail)));
            }
            showNotification(msg, "error");
        }
    }

    var wsReconnectCount = 0;
    var wsReconnectMax = 5;
    function initWebSocket() {
        if (wsReconnectCount >= wsReconnectMax) return;
        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = protocol + "//" + window.location.host + "/ws/events";
        try { if (ws && ws.readyState !== WebSocket.CLOSED) ws.close(); } catch (e) {}
        ws = new WebSocket(url);
        ws.onopen = function () {
            wsReconnectCount = 0;
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
            wsReconnectCount++;
            var delay = Math.min(15000, 3000 * wsReconnectCount);
            setTimeout(initWebSocket, delay);
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

    function parsePlacement(placement) {
        var out = { node_id: "", path: "", name: "", dir: "" };
        if (!placement || typeof placement !== "string") return out;
        placement.split(",").forEach(function (part) {
            var kv = part.trim().split(":");
            if (kv.length >= 2) {
                var k = kv[0].trim().toLowerCase();
                var v = kv.slice(1).join(":").trim();
                if (k === "node") out.node_id = v;
                else if (k === "path") out.path = v;
                else if (k === "name") out.name = v;
                else if (k === "dir") out.dir = v;
            }
        });
        return out;
    }

    async function loadNetworkMap() {
        var container = document.getElementById("networkMap");
        if (!container) return;
        var nodesRes = await apiGet("nodes");
        var tokensRes = await apiGet("tokens");
        if (nodesRes.status === 401 || tokensRes.status === 401) return;
        var nodes = Array.isArray(nodesRes.data) ? nodesRes.data : [];
        var tokens = Array.isArray(tokensRes.data) ? tokensRes.data : [];
        var byNode = {};
        nodes.forEach(function (n) {
            byNode[n.id] = { node: n, tokens: [] };
        });
        tokens.forEach(function (t) {
            var p = parsePlacement(t.placement);
            var nid = p.node_id || "1";
            if (!byNode[nid]) byNode[nid] = { node: { id: nid, hostname: "node_" + nid, ip: "-" }, tokens: [] };
            byNode[nid].tokens.push({ token: t, path: p.path, name: p.name });
        });
        container.innerHTML = Object.keys(byNode).map(function (nid) {
            var item = byNode[nid];
            var n = item.node;
            var list = item.tokens;
            var statusClass = "status-active";
            var statusText = "Активен";
            var hostname = escapeHtml(n.hostname || "node_" + n.id);
            var ip = escapeHtml(n.ip || "-");
            var tokensHtml = list.length === 0
                ? "<div class=\"map-token-empty\">Нет приманок</div>"
                : list.map(function (x) {
                    var path = escapeHtml(x.path || "-");
                    var name = escapeHtml(x.name || x.token.type || "-");
                    return "<div class=\"map-token-item\"><i class=\"fas fa-honey-pot\"></i> " + name + (path ? " <code>" + path + "</code>" : "") + "</div>";
                }).join("");
            return "<div class=\"map-node-card\"><div class=\"map-node-header\"><span class=\"map-node-title\"><i class=\"fas fa-server\"></i> " + hostname + "</span><span class=\"status-badge " + statusClass + "\">" + statusText + "</span></div><div class=\"map-node-meta\">" + ip + "</div><div class=\"map-node-tokens\">" + tokensHtml + "</div></div>";
        }).join("");
    }

    window.toggleSidebar = function () {
        document.getElementById("sidebar").classList.toggle("collapsed");
        document.getElementById("mainContent").classList.toggle("expanded");
    };
    window.loadNodes = loadNodes;
    window.loadTokens = loadTokens;
    window.loadEvents = loadEvents;
    window.loadNetworkMap = loadNetworkMap;
    window.generateToken = generateToken;
    window.logout = logout;
})();
