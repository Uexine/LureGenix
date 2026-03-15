// Состояние приложения
let token = localStorage.getItem("token");
if (!token) {
    window.location = "/";
}

let ws = null;
let eventCount = 0;
let tokenCount = 0;

// Инициализация при загрузке
document.addEventListener('DOMContentLoaded', () => {
    loadNodes();
    loadEvents();
    loadTokens();
    initWebSocket();
    updateStats();
});

// Тоггл сайдбара
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    sidebar.classList.toggle('collapsed');
    mainContent.classList.toggle('expanded');
}

function checkAuth(r) {
    if (r && r.status === 401) {
        localStorage.removeItem("token");
        window.location = "/";
        return true;
    }
    return false;
}

// Загрузка нод
async function loadNodes() {
    try {
        let r = await fetch("/api/nodes", {
            headers: { "Authorization": `Bearer ${token}` }
        });
        if (checkAuth(r)) return;
        let data = await r.json();
        
        let tbody = document.getElementById("nodesTable");
        document.getElementById("nodeCount").textContent = data.length;
        
        if (data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-secondary);">Нет активных нод</td></tr>`;
            return;
        }
        
        tbody.innerHTML = data.map(node => `
            <tr>
                <td>#${node.id}</td>
                <td><strong>${node.hostname}</strong></td>
                <td>${node.ip}</td>
                <td><span class="status-badge status-active"><i class="fas fa-circle" style="font-size: 0.6rem; margin-right: 4px;"></i> Активен</span></td>
                <td>${new Date().toLocaleTimeString()}</td>
                <td>
                    <button class="btn btn-outline" style="padding: 4px 8px;" onclick="showNodeDetails(${node.id})">
                        <i class="fas fa-eye"></i>
                    </button>
                </td>
            </tr>
        `).join('');
        
    } catch (e) {
        console.error("Nodes error:", e);
        showError("Ошибка загрузки нод");
    }
}

// Загрузка событий
async function loadEvents() {
    try {
        let r = await fetch("/api/events", {
            headers: { "Authorization": `Bearer ${token}` }
        });
        if (checkAuth(r)) return;
        let data = await r.json();
        
        let list = document.getElementById("eventsList");
        eventCount = data.length;
        document.getElementById("eventCount").textContent = eventCount;
        
        if (data.length === 0) {
            list.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-secondary);">Нет событий</div>';
            return;
        }
        
        list.innerHTML = data.map(event => createEventElement(event)).join('');
        
    } catch (e) {
        console.error("Events error:", e);
    }
}

// Создание элемента события (API: token_id, action, file_path, created_at)
function createEventElement(event) {
    const rawDate = event.created_at || event.time;
    const date = rawDate ? new Date(rawDate) : new Date();
    const timeStr = date.toLocaleTimeString();
    const dateStr = date.toLocaleDateString();
    const action = event.action || event.type || 'event';
    const tokenId = event.token_id || event.source || '-';

    let icon = 'fa-info-circle';
    let color = 'var(--primary)';
    switch (action) {
        case 'heartbeat':
            icon = 'fa-heartbeat';
            color = 'var(--secondary)';
            break;
        case 'access':
        case 'compromise':
            icon = 'fa-download';
            color = 'var(--warning)';
            break;
        case 'alert':
            icon = 'fa-exclamation-triangle';
            color = 'var(--danger)';
            break;
    }

    return `
        <div class="event-item">
            <div class="event-icon" style="color: ${color};">
                <i class="fas ${icon}"></i>
            </div>
            <div class="event-content">
                <div class="event-title">
                    <strong>${action}</strong> для токена ${tokenId}
                </div>
                <div class="event-time">
                    <i class="far fa-clock" style="margin-right: 4px;"></i>
                    ${dateStr} ${timeStr}
                </div>
            </div>
            <div class="event-type">${event.file_path || 'N/A'}</div>
        </div>
    `;
}

// Загрузка токенов
async function loadTokens() {
    try {
        let r = await fetch("/api/tokens", {
            headers: { "Authorization": `Bearer ${token}` }
        });
        if (checkAuth(r)) return;
        let data = await r.json();
        
        tokenCount = data.length;
        document.getElementById("tokenCount").textContent = tokenCount;
        
    } catch (e) {
        console.error("Tokens error:", e);
    }
}

// Генерация нового токена
async function generateToken() {
    let node = document.getElementById("node").value;
    let type = document.getElementById("type").value;
    let name = document.getElementById("tokenName").value;
    
    let generateBtn = document.querySelector('.btn-primary');
    generateBtn.disabled = true;
    generateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Генерация...';
    
    try {
        let r = await fetch("/api/generate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
                node_id: node,
                type: type,
                name: name
            })
        });
        
        if (checkAuth(r)) return;
        if (r.status === 200) {
            showNotification("Honeytoken успешно создан!", "success");
            loadTokens();
            loadEvents();
            document.getElementById("tokenName").value = '';
        } else {
            let error = await r.json().catch(() => ({}));
            showNotification("Ошибка: " + (error.detail || "Неизвестная ошибка"), "error");
        }
    } catch (e) {
        showNotification("Ошибка соединения с сервером", "error");
    } finally {
        generateBtn.disabled = false;
        generateBtn.innerHTML = '<i class="fas fa-plus"></i> Сгенерировать';
    }
}

// WebSocket подключение
function initWebSocket() {
    ws = new WebSocket("ws://" + window.location.host + "/ws/events");
    
    ws.onopen = () => {
        console.log("WebSocket connected");
        updateConnectionStatus(true);
    };
    
    ws.onmessage = (event) => {
        console.log("New event:", event.data);
        let payload = {};
        try {
            payload = JSON.parse(event.data);
        } catch (e) {
            payload = { action: 'event', token_id: '-', created_at: new Date().toISOString(), file_path: '' };
        }
        let list = document.getElementById("eventsList");
        let wrap = document.createElement('div');
        wrap.innerHTML = createEventElement(payload);
        let newEl = wrap.firstChild;
        if (list.firstChild) {
            list.insertBefore(newEl, list.firstChild);
        } else {
            list.appendChild(newEl);
        }
        eventCount++;
        const ec = document.getElementById("eventCount");
        if (ec) ec.textContent = eventCount;
        if (payload.action === 'alert' || payload.action === 'compromise') {
            const ac = document.getElementById("alertCount");
            if (ac) ac.textContent = parseInt(ac.textContent || '0', 10) + 1;
            showNotification('Тревога: компрометация приманки ' + (payload.token_id || ''), 'error');
        }
        newEl.style.animation = 'slideIn 0.3s ease';
    };
    
    ws.onerror = (e) => {
        console.error("WebSocket error:", e);
        updateConnectionStatus(false);
    };
    
    ws.onclose = () => {
        console.log("WebSocket disconnected");
        updateConnectionStatus(false);
        // Пробуем переподключиться через 5 секунд
        setTimeout(initWebSocket, 5000);
    };
}

// Обновление статуса WebSocket
function updateConnectionStatus(connected) {
    let statusEl = document.querySelector('.status-badge');
    if (statusEl) {
        if (connected) {
            statusEl.className = 'status-badge status-active';
            statusEl.innerHTML = '<i class="fas fa-circle" style="font-size: 0.6rem; margin-right: 4px;"></i> WebSocket подключен';
        } else {
            statusEl.className = 'status-badge status-warning';
            statusEl.innerHTML = '<i class="fas fa-circle" style="font-size: 0.6rem; margin-right: 4px;"></i> WebSocket отключен';
        }
    }
}

// Обновление статистики
function updateStats() {
    // Здесь можно добавить логику обновления статистики
}

// Показ уведомления
function showNotification(message, type = 'info') {
    // Создаем элемент уведомления
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 16px 24px;
        background: ${type === 'success' ? 'var(--secondary)' : type === 'error' ? 'var(--danger)' : 'var(--primary)'};
        color: white;
        border-radius: 12px;
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
        z-index: 9999;
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Удаляем через 3 секунды
    setTimeout(() => {
        notification.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Показ ошибки
function showError(message) {
    showNotification(message, 'error');
}

// Детали ноды
function showNodeDetails(nodeId) {
    alert(`Детали ноды ${nodeId} (будет реализовано позже)`);
}

// Выход
function logout() {
    localStorage.removeItem("token");
    window.location = "/";
}

// Автоматическое обновление каждые 30 секунд
setInterval(() => {
    loadNodes();
    loadEvents();
    loadTokens();
}, 30000);