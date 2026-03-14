if(!localStorage.getItem("token")){
    window.location="/";
}

const token = localStorage.getItem("token");

async function loadNodes(){
    try {
        let r = await fetch("/api/nodes", {
            headers: {"Authorization": `Bearer ${token}`}
        });
        if (r.ok) {
            let data = await r.json();
            let table = document.getElementById("nodes");
            data.forEach(n => {
                table.innerHTML += `
                <tr>
                    <td>${n.id}</td>
                    <td>${n.hostname}</td>
                    <td>${n.ip}</td>
                </tr>
                `;
            });
        }
    } catch (e) {}
}

async function loadEvents(){
    try {
        let r = await fetch("/api/events", {
            headers: {"Authorization": `Bearer ${token}`}
        });
        if (r.ok) {
            let data = await r.json();
            let list = document.getElementById("events");
            data.forEach(e => {
                list.innerHTML += `<li>${e.action} at ${e.created_at}</li>`;
            });
        }
    } catch (e) {}
}

async function loadTokens(){
    try {
        let r = await fetch("/api/tokens", {
            headers: {"Authorization": `Bearer ${token}`}
        });
        if (r.ok) {
            let data = await r.json();
            let list = document.getElementById("tokens");
            data.forEach(t => {
                list.innerHTML += `<li>${t.id} (${t.type}) at ${t.path}</li>`;
            });
        }
    } catch (e) {}
}

async function generate(){
    let node = document.getElementById("node").value;
    let type = document.getElementById("type").value;
    try {
        let r = await fetch("/api/generate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
                node_id: node,
                type: type
            })
        });
        if (r.ok) {
            alert("Honeytoken created");
        } else {
            alert("Error: " + r.status);
        }
    } catch (e) {
        alert("Error generating");
    }
}

function startWS(){
    let ws = new WebSocket("ws://" + window.location.host + "/ws/events");
    ws.onmessage = (event) => {
        let list = document.getElementById("events");
        list.innerHTML += `<li>${event.data}</li>`;
    };
    ws.onerror = () => console.log("WS error");
}

loadNodes();
loadEvents();
loadTokens();
startWS();