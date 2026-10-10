async function login(event) {
    event.preventDefault();
    const button = document.getElementById("loginBtn");
    if (button.disabled) return;
    const error = document.getElementById("error");
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    button.disabled = true;
    error.style.display = "none";
    try {
        const response = await fetch("/api/login", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({username, password}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(response.status === 401 ? "Неверный логин или пароль" :
                response.status === 429 ? "Слишком много попыток. Подождите минуту" : "Сервис входа недоступен");
        }
        if (!data.token) throw new Error("Сервер не выдал токен");
        localStorage.removeItem("token");
        localStorage.removeItem("username");
        sessionStorage.setItem("token", data.token);
        sessionStorage.setItem("username", data.username || username);
        window.location.href = "/dashboard";
    } catch (failure) {
        error.textContent = failure instanceof TypeError ? "Нет соединения с сервером" : failure.message;
        error.style.display = "block";
    } finally {
        button.disabled = false;
    }
}

document.getElementById("loginForm").addEventListener("submit", login);
document.getElementById("loginForm").addEventListener("input", () => {
    document.getElementById("error").style.display = "none";
});
