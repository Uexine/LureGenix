document.getElementById("loginBtn").onclick = async () => {
    let username = document.getElementById("username").value;
    let password = document.getElementById("password").value;
    try {
        let r = await fetch("/api/login", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({username, password})
        });
        if (r.status !== 200) {
            document.getElementById("error").innerText = "Invalid login";
            return;
        }
        let data = await r.json();
        localStorage.setItem("token", data.token);
        window.location = "/dashboard.html";
    } catch (e) {
        document.getElementById("error").innerText = "Error connecting";
    }
};