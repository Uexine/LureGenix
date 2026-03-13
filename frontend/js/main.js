// Загрузка информации о деплое
async function loadDeployInfo() {
    try {
        const response = await fetch('deploy-info.json?' + Date.now());
        const data = await response.json();
        
        document.getElementById('branch').textContent = data.branch;
        document.getElementById('timestamp').textContent = new Date(data.deployed_at).toLocaleString('ru-RU');
        
        const deployInfo = document.getElementById('deploy-info');
        deployInfo.innerHTML = `
            <p><strong>Ветка:</strong> ${data.branch}</p>
            <p><strong>Коммит:</strong> ${data.commit.substring(0, 7)}</p>
            <p><strong>Время:</strong> ${new Date(data.deployed_at).toLocaleString('ru-RU')}</p>
        `;
        
    } catch (error) {
        console.error('Ошибка загрузки:', error);
        document.getElementById('deploy-info').innerHTML = '<p style="color:red">Не удалось загрузить информацию</p>';
    }
}

// Тест соединения
function testConnection() {
    const result = document.getElementById('test-result');
    result.style.display = 'block';
    result.className = '';
    result.textContent = 'Проверка...';
    
    fetch('/health')
        .then(response => {
            if (response.ok) {
                result.className = 'success';
                result.textContent = '✅ Соединение работает! Сервер отвечает.';
            } else {
                throw new Error('Сервер вернул ошибку');
            }
        })
        .catch(error => {
            result.className = 'error';
            result.textContent = '❌ Ошибка соединения: ' + error.message;
        });
}

// Запуск при загрузке
document.addEventListener('DOMContentLoaded', loadDeployInfo);