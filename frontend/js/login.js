async function login() {
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    const errorDiv = document.getElementById('error');
    const loginBtn = document.getElementById('loginBtn');

    // Простая валидация
    if (!username || !password) {
        errorDiv.innerText = 'Заполните все поля';
        return;
    }

    // Блокируем кнопку
    loginBtn.disabled = true;
    loginBtn.innerHTML = '<span>Вход...</span> <i class="fas fa-spinner fa-spin"></i>';

    try {
        console.log('Sending login request...');
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password })
        });

        const data = await response.json();
        console.log('Response:', response.status, data);

        if (!response.ok) {
            throw new Error(data.detail || 'Ошибка входа');
        }

        if (data.token) {
            localStorage.setItem('token', data.token);
            if (data.username) localStorage.setItem('username', data.username);
            // Плавный редирект
            loginBtn.innerHTML = '<span>Успех!</span> <i class="fas fa-check"></i>';
            setTimeout(() => {
                window.location.href = '/dashboard.html';
            }, 500);
        } else {
            throw new Error('Токен не получен');
        }

    } catch (error) {
        console.error('Login error:', error);
        errorDiv.innerText = error.message || 'Ошибка соединения с сервером';
        
        // Разблокируем кнопку
        loginBtn.disabled = false;
        loginBtn.innerHTML = '<span>Войти</span> <i class="fas fa-arrow-right"></i>';
    }
}

// Добавляем обработчик Enter
document.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        login();
    }
});

// Очистка ошибки при вводе
document.querySelectorAll('input').forEach(input => {
    input.addEventListener('input', () => {
        document.getElementById('error').style.display = 'none';
    });
});