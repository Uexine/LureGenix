(() => {
    const storageKey = "luregenix.theme";
    const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
    let savedTheme = null;

    // Недоступное хранилище не должно мешать открытию страницы.
    try {
        savedTheme = readTheme(localStorage.getItem(storageKey));
    } catch {
        savedTheme = null;
    }

    // Принимает только две поддерживаемые темы из настроек браузера.
    function readTheme(value) {
        return value === "light" || value === "dark" ? value : null;
    }

    // Применяет палитру до загрузки стилей, чтобы избежать светлой вспышки.
    function applyTheme() {
        const theme = savedTheme || (systemTheme.matches ? "dark" : "light");
        document.documentElement.dataset.theme = theme;
        document.querySelectorAll("[data-theme-toggle]").forEach(button => {
            const dark = theme === "dark";
            const label = dark ? "Включить светлую тему" : "Включить тёмную тему";
            button.title = label;
            button.setAttribute("aria-label", label);
            button.setAttribute("aria-pressed", String(dark));
            button.querySelector("i").className = dark ? "fas fa-sun" : "fas fa-moon";
        });
    }

    // Сохраняет ручной выбор; при запрете localStorage он действует до перезагрузки.
    function toggleTheme() {
        savedTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        try {
            localStorage.setItem(storageKey, savedTheme);
        } catch {
            // Тема остаётся доступна и без сохранения в браузере.
        }
        applyTheme();
    }

    applyTheme();
    document.addEventListener("DOMContentLoaded", () => {
        applyTheme();
        document.querySelectorAll("[data-theme-toggle]").forEach(button => {
            button.addEventListener("click", toggleTheme);
        });
    });
    systemTheme.addEventListener("change", () => {
        if (!savedTheme) applyTheme();
    });
    window.addEventListener("storage", event => {
        if (event.key === storageKey || event.key === null) {
            savedTheme = readTheme(event.newValue);
            applyTheme();
        }
    });
})();
