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
    var alertActions = ["alert", "compromise", "open", "access", "modify", "delete", "monitor_error", "deployment_failed"];

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
        const actions = {toggleSidebar: function () { window.toggleSidebar(); }, logout: logout,
            generateToken: generateToken, loadNodes: loadNodes, loadTokens: loadTokens,
            loadEvents: loadEvents, loadNetworkMap: loadNetworkMap, markAllEventsRead: markAllEventsRead,
            scanNetwork: scanNetwork, showMap: function () { showSection("map"); }, retryToken: retryToken,
            markEventRead: markEventRead,
            passwordDialog: function () { document.getElementById("passwordDialog").showModal(); },
            closePasswordDialog: function () { document.getElementById("passwordDialog").close(); }};
        document.addEventListener("click", function (event) {
            var control = event.target.closest("[data-action]");
            if (control && !control.disabled && actions[control.dataset.action]) {
                actions[control.dataset.action](control.dataset.tokenId || control.dataset.eventId);
            }
        });
        document.getElementById("tokensFilterSearch").addEventListener("input", applyTokensFilter);
        document.getElementById("tokensFilterType").addEventListener("change", applyTokensFilter);
        document.getElementById("passwordForm").addEventListener("submit", async function (event) {
            event.preventDefault();
            var form = event.target;
            var password = document.getElementById("newPassword").value;
            if (password !== document.getElementById("confirmPassword").value) {
                showNotification("Пароли не совпадают", "error");
                return;
            }
            var button = form.querySelector("[type='submit']");
            button.disabled = true;
            try {
                var result = await apiPut("password", {current_password: document.getElementById("currentPassword").value, new_password: password});
                if (result.ok) {
                    form.reset();
                    document.getElementById("passwordDialog").close();
                    showNotification("Пароль изменён", "success");
                } else {
                    showNotification("Не удалось изменить пароль: проверьте текущий пароль и длину нового", "error");
                }
            } finally { button.disabled = false; }
        });
        document.querySelector("[data-action='logout']").addEventListener("keydown", function (event) {
            if (event.key === "Enter" || event.key === " ") { event.preventDefault(); logout(); }
        });
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
                if (window.matchMedia("(max-width:780px)").matches) {
                    document.getElementById("sidebar").classList.remove("collapsed");
                    document.getElementById("mainContent").classList.remove("expanded");
                }
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
        loadGenerationStatus();
        loadTokens();
        loadEvents();
        loadNetworkMap();
        initWebSocket();
        document.getElementById("deploymentMode").addEventListener("change", function () {
            document.getElementById("tokenNodePath").disabled = this.value === "auto";
        });
    });

    async function loadGenerationStatus() {
        var result = await apiGet("generation-status");
        var label = document.getElementById("generatorStatus");
        label.textContent = !result.ok ? "Генератор недоступен" : result.data.mode === "template" ? "Генератор: шаблоны" :
            "LLM: " + result.data.model + (result.data.ready ? " · готова" : " · недоступна");
    }

    async function scanNetwork() {
        var button = document.getElementById("btnScan");
        var status = document.getElementById("scanStatus");
        button.disabled = true;
        status.textContent = "Поиск серверов…";
        try {
            var result = await api("scan", {method: "POST", body: {subnet: document.getElementById("scanSubnet").value.trim()}});
            if (!result.ok) {
                status.textContent = "Обнаружение недоступно";
                showNotification(apiError(result, "Ошибка обнаружения"), "error");
                return;
            }
            status.textContent = "Найдено: " + result.data.hosts.length;
            document.getElementById("scanResults").textContent = result.data.hosts.map(function (host) { return host.ip + ":" + host.ssh_port; }).join(", ");
        } finally {
            button.disabled = false;
        }
    }

    async function retryToken(tokenId) {
        var result = await api("tokens/" + encodeURIComponent(tokenId) + "/retry", {method: "POST", body: {}});
        showNotification(result.ok ? "Размещение поставлено в очередь повторно" : "Повторное размещение недоступно", result.ok ? "success" : "error");
        loadTokens();
    }

    async function loadTokenTypes() {
        const select = document.getElementById("typeSelect");
        if (!select) return;
        var res = await apiGet("token-types");
        if (res.status === 401) return;
        if (!res.ok || !Array.isArray(res.data)) {
            select.innerHTML = "<option value=\"\">Генератор недоступен</option>";
            showNotification("Не удалось получить типы приманок", "error");
            return;
        }
        select.innerHTML = res.data.map(function (t) {
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

    async function loadNodes() {
        const res = await apiGet("nodes");
        if (res.status === 401) return;
        if (!res.ok) { showNotification("Сервис узлов недоступен", "error"); return; }
        const data = Array.isArray(res.data) ? res.data : [];
        const tbody = document.getElementById("nodesTable");
        const select = document.getElementById("nodeSelect");
        var selectedNode = select.value;
        document.getElementById("nodeCount").textContent = data.filter(function (n) { return n.status === "online" && n.enrolled !== false; }).length;

        select.innerHTML = data.length
            ? data.map(function (n) {
                return "<option value=\"" + escapeHtml(n.id) + "\"" + (n.enrolled === false ? " disabled" : "") + ">" + escapeHtml(n.hostname || "node" + n.id) + " (" + escapeHtml(n.ip || "-") + ") · " + (n.enrolled === false ? "Нет агента" : n.status === "online" ? "В сети" : "Не в сети") + "</option>";
            }).join("")
            : "<option value=\"\">Нет зарегистрированных серверов</option>";
        if (data.some(function (n) { return String(n.id) === selectedNode && n.enrolled !== false; })) select.value = selectedNode;

        if (data.length === 0) {
            tbody.innerHTML = "<tr><td colspan=\"5\" style=\"text-align:center;color:var(--text-secondary);\">Нет данных о нодах</td></tr>";
            return;
        }
        tbody.innerHTML = data.map(function (node) {
            return "<tr><td>#" + escapeHtml(node.id) + "</td><td><strong>" + escapeHtml(node.hostname || "-") + "</strong></td><td>" + escapeHtml(node.ip || "-") + "</td>" +
                "<td><span class=\"status-badge\">" + (node.status === "online" ? "Активен" : "Не в сети") + "</span></td>" +
                "<td><button type=\"button\" class=\"btn btn-outline\" style=\"padding:4px 8px;\" title=\"Просмотр ноды на карте сети\" data-action=\"showMap\"><i class=\"fas fa-eye\"></i></button></td></tr>";
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
                return placement.indexOf(search) >= 0 || path.indexOf(search) >= 0 || (t.name || "").toLowerCase().indexOf(search) >= 0 || (t.type || "").toLowerCase().indexOf(search) >= 0 || (t.id || "").toLowerCase().indexOf(search) >= 0;
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
            tbody.innerHTML = "<tr><td colspan=\"5\" style=\"text-align:center;color:var(--text-secondary);\">Нет honeytoken'ов" + (tokensFilter.search || tokensFilter.type ? " по фильтру" : "") + "</td></tr>";
            return;
        }
        tbody.innerHTML = list.map(function (t) {
            var id = t.id || "-";
            var type = t.type || "-";
            var placement = t.name || (t.node_id ? "Сервер #" + t.node_id : "-");
            var path = t.path || "-";
            var created = t.created_at ? new Date(t.created_at).toLocaleString() : "-";
            var statuses = { pending: "Ожидает агента", deployed: "Размещён", failed: "Ошибка размещения", legacy: "Старая запись" };
            var status = statuses[t.deployment_status] || "Старая запись";
            var error = t.deployment_error ? "<div>" + escapeHtml(t.deployment_error) + "</div>" : "";
            var integrity = {modified: "Файл изменён", missing: "Файл удалён", error: "Ошибка мониторинга"}[t.integrity_status];
            if (integrity && t.deployment_status === "deployed") error += "<div>" + integrity + "</div>";
            var retry = t.deployment_status === "failed" ? "<button class=\"btn btn-outline\" data-action=\"retryToken\" data-token-id=\"" + escapeHtml(id) + "\" title=\"Повторить размещение\"><i class=\"fas fa-redo\"></i></button>" : "";
            return "<tr><td><code>" + escapeHtml(id) + "</code> / " + escapeHtml(type) + "<div>" + escapeHtml(t.generation_source || "-") + "</div></td><td>" + escapeHtml(placement) + "</td><td><code style=\"font-size:0.85em;\">" + escapeHtml(path) + "</code></td><td>" + escapeHtml(status) + error + retry + "</td><td>" + created + "</td></tr>";
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

    async function loadTokens() {
        const res = await apiGet("tokens");
        if (res.status === 401) return;
        if (!res.ok) { showNotification("Сервис приманок недоступен", "error"); return; }
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
            typeSelect.value = tokensFilter.type;
        }
        renderTokensTable();
        document.querySelectorAll(".tokens-table thead .sortable").forEach(function (th) {
            th.onclick = function () { sortTokensBy(th.getAttribute("data-sort")); };
        });
    }

    async function loadEvents() {
        const res = await apiGet("events");
        if (res.status === 401) return;
        if (!res.ok) { showNotification("Журнал событий недоступен", "error"); return; }
        const data = Array.isArray(res.data) ? res.data : [];
        document.getElementById("eventCount").textContent = data.length;

        const alertCount = data.filter(function (e) { return alertActions.indexOf(e.action) >= 0; }).length;
        document.getElementById("alertCount").textContent = alertCount;

        const unreadRes = await apiGet("events/unread_count");
        const unreadCount = unreadRes.ok ? unreadRes.data.count : null;
        var badge = document.getElementById("sidebarEventBadge");
        if (badge) {
            badge.textContent = unreadCount === null ? "?" : unreadCount;
            badge.style.display = unreadCount === null || unreadCount > 0 ? "" : "none";
        }

        const html = data.length === 0
            ? "<div style=\"text-align:center;padding:40px;color:var(--text-secondary);\">Нет событий</div>"
            : data.map(eventRow).join("");

        document.getElementById("eventsList").innerHTML = html;
        document.getElementById("eventsListFull").innerHTML = html;
    }

    function eventRow(event) {
        const rawDate = event.observed_at || event.created_at || event.time;
        const date = rawDate ? new Date(rawDate) : new Date();
        const action = event.action || event.type || "event";
        var displayName = (event.source_hostname && event.source_hostname.trim()) ? event.source_hostname.trim() : (event.token_id || event.source || "-");
        let icon = "fa-info-circle", color = "var(--primary)";
        if (action === "heartbeat") { icon = "fa-heartbeat"; color = "var(--secondary)"; }
        else if (alertActions.indexOf(action) >= 0) { icon = "fa-exclamation-triangle"; color = "var(--danger)"; }
        var readClass = (event.read_at) ? " event-item-read" : "";
        return "<div class=\"event-item" + readClass + "\" data-event-id=\"" + escapeHtml(event.id || "") + "\"><div class=\"event-icon\" style=\"color:" + color + ";\"><i class=\"fas " + icon + "\"></i></div>" +
            "<div class=\"event-content\"><div class=\"event-title\"><strong>" + escapeHtml(action) + "</strong> для " + escapeHtml(displayName) + "</div>" +
            "<div class=\"event-time\"><i class=\"far fa-clock\" style=\"margin-right:4px;\"></i>" + date.toLocaleString() + "</div></div>" +
            "<div class=\"event-type\">" + escapeHtml(event.file_path || "N/A") + "</div>" +
            (!event.read_at && event.id ? "<button type=\"button\" class=\"btn btn-outline\" data-action=\"markEventRead\" data-event-id=\"" + escapeHtml(event.id) + "\" title=\"Подтвердить событие\"><i class=\"fas fa-check\"></i></button>" : "") + "</div>";
    }

    async function markEventRead(eventId) {
        const result = await apiPut("events/" + encodeURIComponent(eventId) + "/read");
        if (!result.ok) showNotification(apiError(result, "Не удалось подтвердить событие"), "error");
        loadEvents();
    }

    async function markAllEventsRead() {
        var btn = document.querySelector("#section-events [data-action='markAllEventsRead']");
        if (btn) { btn.disabled = true; btn.innerHTML = "<i class=\"fas fa-spinner fa-spin\"></i> ..."; }
        var res = await apiPut("events/read_all");
        if (res.status === 401) {
            if (btn) { btn.disabled = false; btn.innerHTML = "<i class=\"fas fa-check-double\"></i> Прочитано"; }
            return;
        }
        if (res.ok) {
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
        return div.innerHTML.replace(/\"/g, "&quot;").replace(/'/g, "&#39;");
    }

    async function generateToken() {
        var btn = document.getElementById("btnGenerate");
        var nodeId = document.getElementById("nodeSelect").value;
        var type = document.getElementById("typeSelect").value;
        var name = (document.getElementById("tokenName").value || "").trim();
        var nodePath = (document.getElementById("tokenNodePath") ? document.getElementById("tokenNodePath").value || "" : "").trim();
        var auto = document.getElementById("deploymentMode").value === "auto";
        var filename = document.getElementById("tokenFilename").value.trim();
        if (!nodeId) {
            showNotification("Нет зарегистрированного Linux-агента", "error");
            return;
        }
        if (!auto && (!nodePath.startsWith("/") || nodePath.split("/").indexOf("..") >= 0)) {
            showNotification("Укажите абсолютный путь к каталогу Linux-сервера", "error");
            return;
        }
        btn.disabled = true;
        btn.innerHTML = "<i class=\"fas fa-spinner fa-spin\"></i> Генерация...";
        var payload = { node_id: nodeId, type: type, name: name, filename: filename, target_kind: "directory" };
        if (!auto) payload.node_path = nodePath;
        var res = await apiPost("generate", payload);
        btn.disabled = false;
        btn.innerHTML = "<i class=\"fas fa-plus\"></i> Создать и разместить";
        if (res.status === 401) return;
        if (res.ok) {
            showNotification("Приманка создана и ожидает размещения агентом", "success");
            if (document.getElementById("tokenName")) document.getElementById("tokenName").value = "";
            /* Каталог и путь на ноде не очищаем — удобно создавать несколько приманок подряд */
            loadTokens();
            loadEvents();
            loadNetworkMap();
        } else {
            showNotification(apiError(res, "Ошибка создания приманки"), "error");
        }
    }

    var wsReconnectCount = 0;
    var wsReconnectTimer = null;
    function initWebSocket() {
        clearTimeout(wsReconnectTimer);
        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = protocol + "//" + window.location.host + "/ws/events";
        if (ws && ws.readyState !== WebSocket.CLOSED) return;
        if (!getToken()) return;
        ws = new WebSocket(url, ["luregenix", "bearer." + getToken()]);
        ws.onopen = function () {
            wsReconnectCount = 0;
            updateWsStatus(true);
        };
        ws.onmessage = function (ev) {
            var payload = {};
            try { payload = JSON.parse(ev.data); } catch { return; }
            if (!payload || !payload.action) return;
            loadEvents();
            loadTokens();
            loadNetworkMap();
            if (alertActions.indexOf(payload.action) >= 0) {
                showNotification("Тревога: " + (payload.token_id || ""), "error");
            }
        };
        ws.onerror = function () { updateWsStatus(false); };
        ws.onclose = function (event) {
            updateWsStatus(false);
            if (event.code === 1008) { logout(); return; }
            if (!getToken()) return;
            wsReconnectCount++;
            var delay = Math.min(15000, 3000 * wsReconnectCount);
            wsReconnectTimer = setTimeout(initWebSocket, delay);
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
    var colors = {success: "#10b981", error: "#ef4444", info: "#3b82f6"};
    var bg = colors[type] || colors.info;

    var n = document.createElement("div");
    document.getElementById("notification")?.remove();
    n.id = "notification";
    n.style.cssText =
        "position:fixed;top:20px;right:20px;" +
        "padding:16px 24px;" +
        "background:" + bg + ";" +
        "color:#ffffff;" +
        "font-weight:500;" +
        "border-radius:6px;max-width:calc(100% - 40px);box-sizing:border-box;overflow-wrap:anywhere;" +
        "box-shadow:0 10px 15px -3px rgba(0,0,0,0.3);" +
        "z-index:9999;" +
        "opacity:1;";
    n.textContent = message;
    document.body.appendChild(n);
    setTimeout(function () { n.remove(); }, 3000);
    }

    function logout() {
        clearAuth();
        clearTimeout(wsReconnectTimer);
        if (ws) ws.close();
        window.location.href = "/";
    }

    setInterval(function () {
        loadNodes();
        loadTokens();
        loadEvents();
    }, 30000);

    async function loadNetworkMap() {
        var container = document.getElementById("networkMap");
        if (!container) return;
        var nodesRes = await apiGet("nodes");
        var tokensRes = await apiGet("tokens");
        if (nodesRes.status === 401 || tokensRes.status === 401) return;
        if (!nodesRes.ok || !tokensRes.ok) {
            container.textContent = "Карта сети недоступна";
            return;
        }
        var nodes = Array.isArray(nodesRes.data) ? nodesRes.data : [];
        var tokens = Array.isArray(tokensRes.data) ? tokensRes.data : [];
        var byNode = {};
        nodes.forEach(function (n) {
            byNode[n.id] = { node: n, tokens: [] };
        });
        tokens.forEach(function (t) {
            var nid = t.node_id || "unknown";
            if (!byNode[nid]) byNode[nid] = { node: { id: nid, hostname: "node_" + nid, ip: "-" }, tokens: [] };
            byNode[nid].tokens.push({ token: t, path: t.deployed_path || t.path, name: t.name });
        });
        container.innerHTML = Object.keys(byNode).map(function (nid) {
            var item = byNode[nid];
            var n = item.node;
            var list = item.tokens;
            var statusClass = n.status === "online" ? "status-active" : "status-warning";
            var statusText = n.status === "online" ? "Активен" : "Не в сети";
            var hostname = escapeHtml(n.hostname || "node_" + n.id);
            var ip = escapeHtml(n.ip || "-");
            var tokensHtml = list.length === 0
                ? "<div class=\"map-token-empty\">Нет приманок</div>"
                : list.map(function (x) {
                    var path = escapeHtml(x.path || "-");
                    var name = escapeHtml(x.name || x.token.type || "-");
                    return "<div class=\"map-token-item\"><i class=\"fas fa-file\"></i> " + name + (path ? " <code>" + path + "</code>" : "") + "</div>";
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
