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
    var validSectionIds = ["dashboard", "nodes", "tokens", "events", "map"];
    var supportsUnreadCount = true;
    var supportsMarkAllRead = true;
    var PATH_UNREAD_COUNT = "events/unread_count";
    var PATH_READ_ALL = "events/read_all";

    function getSectionFromPath() {
        var path = (window.location.pathname || "").replace(/\/$/, "");
        if (path === "/dashboard" || path === "") return "dashboard";
        var m = path.match(/\/dashboard\/([a-z]+)/);
        var id = m ? m[1] : "dashboard";
        return validSectionIds.indexOf(id) >= 0 ? id : "dashboard";
    }

    function updateUrlForSection(id, replace) {
        var path = "/dashboard" + (id === "dashboard" ? "" : "/" + id);
        if (replace) {
            history.replaceState({ section: id }, "", path);
        } else {
            history.pushState({ section: id }, "", path);
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.getElementById("userName").textContent = getUsername();
        const avatar = document.getElementById("userAvatar");
        const u = getUsername();
        avatar.textContent = u ? u.charAt(0).toUpperCase() : "A";

        document.querySelectorAll(".sidebar-nav a[data-section]").forEach(function (a) {
            a.addEventListener("click", function (e) {
                e.preventDefault();
                var id = a.getAttribute("data-section");
                updateUrlForSection(id, false);
                showSection(id);
            });
        });

        window.addEventListener("popstate", function (e) {
            var id = (e.state && e.state.section) ? e.state.section : getSectionFromPath();
            showSection(id);
        });

        if (window.location.pathname === "/dashboard.html" || window.location.pathname === "/dashboard.html/") {
            history.replaceState({ section: "dashboard" }, "", "/dashboard");
        }
        var initialSection = getSectionFromPath();
        updateUrlForSection(initialSection, true);
        showSection(initialSection);

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
        if (validSectionIds.indexOf(id) < 0) id = "dashboard";
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
        if (id === "events") loadEvents();
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
                "<td><button type=\"button\" class=\"btn btn-outline\" style=\"padding:4px 8px;\" title=\"Просмотр ноды на карте сети\" onclick=\"showSection('map')\"><i class=\"fas fa-eye\"></i></button></td></tr>";
        }).join("");
    }

    var tokensData = [];
    var tokensSort = { field: "created_at", dir: -1 };
    var tokensFilter = { type: "", search: "" };

    function sortTokensBy(field) {
        if (tokensSort.field === field) tokensSort.dir = -tokensSort.dir;
        else { tokensSort.field = field; tokensSort.dir = 1; }
        renderTokensTable();
    }

    function applyTokensFilter() {
        var searchEl = document.getElementById("tokensFilterSearch");
        var typeEl = document.getElementById("tokensFilterType");
        tokensFilter.search = (searchEl && searchEl.value) ? searchEl.value.trim().toLowerCase() : "";
        tokensFilter.type = (typeEl && typeEl.value) ? typeEl.value.trim() : "";
        renderTokensTable();
    }

    function renderTokensTable() {
        var list = tokensData.slice();
        var search = tokensFilter.search;
        var typeFilter = tokensFilter.type;
        if (search) {
            list = list.filter(function (t) {
                var placement = (t.placement || "").toLowerCase();
                var path = (t.path || "").toLowerCase();
                return placement.indexOf(search) >= 0 || path.indexOf(search) >= 0 || (t.type || "").toLowerCase().indexOf(search) >= 0 || (t.id || "").toLowerCase().indexOf(search) >= 0;
            });
        }
        if (typeFilter) list = list.filter(function (t) { return (t.type || "") === typeFilter; });
        var field = tokensSort.field;
        var dir = tokensSort.dir;
        list.sort(function (a, b) {
            var va = a[field];
            var vb = b[field];
            if (field === "created_at") {
                va = va ? new Date(va).getTime() : 0;
                vb = vb ? new Date(vb).getTime() : 0;
            } else {
                va = (va || "").toString().toLowerCase();
                vb = (vb || "").toString().toLowerCase();
            }
            if (va < vb) return -dir;
            if (va > vb) return dir;
            return 0;
        });
        var tbody = document.getElementById("tokensTable");
        if (!tbody) return;
        document.getElementById("tokenCount").textContent = tokensData.length;
        if (list.length === 0) {
            tbody.innerHTML = "<tr><td colspan=\"4\" style=\"text-align:center;color:var(--text-secondary);\">Нет honeytoken'ов" + (tokensFilter.search || tokensFilter.type ? " по фильтру" : "") + "</td></tr>";
            return;
        }
        tbody.innerHTML = list.map(function (t) {
            var id = t.id || "-";
            var type = t.type || "-";
            var placement = t.placement || "-";
            var path = t.path || "-";
            var created = t.created_at ? new Date(t.created_at).toLocaleString() : "-";
            return "<tr><td><code>" + escapeHtml(id) + "</code> / " + escapeHtml(type) + "</td><td>" + escapeHtml(placement) + "</td><td><code style=\"font-size:0.85em;\">" + escapeHtml(path) + "</code></td><td>" + created + "</td></tr>";
        }).join("");
        updateTokensSortIcons();
    }

    function updateTokensSortIcons() {
        document.querySelectorAll(".tokens-table thead .sortable").forEach(function (th) {
            var field = th.getAttribute("data-sort");
            var icon = th.querySelector(".sort-icon");
            if (!icon) return;
            icon.className = "sort-icon fas " + (tokensSort.field === field ? (tokensSort.dir > 0 ? "fa-sort-up" : "fa-sort-down") : "fa-sort");
        });
    }

    async function loadTokens(refresh) {
        const res = await apiGet("tokens");
        if (res.status === 401) return;
        tokensData = Array.isArray(res.data) ? res.data : [];
        var typeSelect = document.getElementById("tokensFilterType");
        if (typeSelect) {
            var types = [];
            tokensData.forEach(function (t) {
                if (t.type && types.indexOf(t.type) < 0) types.push(t.type);
            });
            types.sort();
            typeSelect.innerHTML = "<option value=\"\">Все типы</option>" + types.map(function (x) {
                return "<option value=\"" + escapeHtml(x) + "\">" + escapeHtml(x) + "</option>";
            }).join("");
        }
        renderTokensTable();
        document.querySelectorAll(".tokens-table thead .sortable").forEach(function (th) {
            th.onclick = function () { sortTokensBy(th.getAttribute("data-sort")); };
        });
    }

    async function loadEvents(refresh) {
        const res = await apiGet("events");
        if (res.status === 401) return;
        const data = Array.isArray(res.data) ? res.data : [];
        document.getElementById("eventCount").textContent = data.length;

        const alertCount = data.filter(function (e) { return e.action === "alert" || e.action === "compromise"; }).length;
        document.getElementById("alertCount").textContent = alertCount;

        var unreadCount = data.length;
        if (supportsUnreadCount) {
            try {
                var unreadRes = await apiGet(PATH_UNREAD_COUNT);
                if (unreadRes.status === 404) supportsUnreadCount = false;
                else if (unreadRes.ok && unreadRes.data && typeof unreadRes.data.count === "number") unreadCount = unreadRes.data.count;
            } catch (e) {
                supportsUnreadCount = false;
                unreadCount = 0;
            }
        }
        var badge = document.getElementById("sidebarEventBadge");
        if (badge) {
            badge.textContent = unreadCount;
            badge.style.display = unreadCount > 0 ? "" : "none";
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
        var displayName = (event.source_hostname && event.source_hostname.trim()) ? event.source_hostname.trim() : (event.token_id || event.source || "-");
        let icon = "fa-info-circle", color = "var(--primary)";
        if (action === "heartbeat") { icon = "fa-heartbeat"; color = "var(--secondary)"; }
        else if (action === "access" || action === "compromise") { icon = "fa-download"; color = "var(--warning)"; }
        else if (action === "alert") { icon = "fa-exclamation-triangle"; color = "var(--danger)"; }
        var readClass = (event.read_at) ? " event-item-read" : "";
        return "<div class=\"event-item" + readClass + "\" data-event-id=\"" + (event.id || "") + "\"><div class=\"event-icon\" style=\"color:" + color + ";\"><i class=\"fas " + icon + "\"></i></div>" +
            "<div class=\"event-content\"><div class=\"event-title\"><strong>" + escapeHtml(action) + "</strong> для " + escapeHtml(displayName) + "</div>" +
            "<div class=\"event-time\"><i class=\"far fa-clock\" style=\"margin-right:4px;\"></i>" + date.toLocaleString() + "</div></div>" +
            "<div class=\"event-type\">" + escapeHtml(event.file_path || "N/A") + "</div></div>";
    }

    async function markAllEventsRead() {
        var btn = document.querySelector("#section-events .btn[onclick*='markAllEventsRead']");
        if (btn) { btn.disabled = true; btn.innerHTML = "<i class=\"fas fa-spinner fa-spin\"></i> ..."; }
        if (!supportsMarkAllRead) {
            loadEvents();
            if (btn) { btn.disabled = false; btn.innerHTML = "<i class=\"fas fa-check-double\"></i> Прочитано"; }
            return;
        }
        var res = await (window.apiPut || apiPut || function (path, body) { return api(path, { method: "PUT", body: body || {} }); })(PATH_READ_ALL, {});
        if (res.status === 401) {
            if (btn) { btn.disabled = false; btn.innerHTML = "<i class=\"fas fa-check-double\"></i> Прочитано"; }
            return;
        }
        if (res.status === 404) {
            supportsMarkAllRead = false;
            showNotification("Функция «Прочитано» недоступна на сервере", "error");
        } else if (res.ok) {
            showNotification("Все события отмечены прочитанными", "success");
        } else {
            showNotification("Не удалось отметить прочитанными", "error");
        }
        loadEvents();
        if (btn) { btn.disabled = false; btn.innerHTML = "<i class=\"fas fa-check-double\"></i> Прочитано"; }
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
    window.showSection = showSection;
    window.loadNodes = loadNodes;
    window.loadTokens = loadTokens;
    window.loadEvents = loadEvents;
    window.loadNetworkMap = loadNetworkMap;
    window.generateToken = generateToken;
    window.markAllEventsRead = markAllEventsRead;
    window.sortTokensBy = sortTokensBy;
    window.applyTokensFilter = applyTokensFilter;
    window.logout = logout;
})();
