document.getElementById("loginBtn").onclick = async () => {
    let username = document.getElementById("username").value;
    let password = document.getElementById("password").value;
    let errorDiv = document.getElementById("error");
    
    console.log("Trying login with:", username, password);
    
    try {
        let r = await fetch("/api/login", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({username, password})
        });
        
        console.log("Response status:", r.status);
        let data = await r.json();
        console.log("Response data:", data);
        
        if (r.status !== 200) {
            errorDiv.innerText = "Login failed: " + (data.detail || "Unknown error");
            return;
        }
        
        localStorage.setItem("token", data.token);
        window.location = "/dashboard.html";
    } catch (e) {
        console.error("Error:", e);
        errorDiv.innerText = "Error connecting to server";
    }
};