if(!localStorage.getItem("token")){
    window.location="/";
}

const token = localStorage.getItem("token");

async function loadNodes(){
    let r = await fetch("/api/nodes", {
        headers: {"Authorization": `Bearer ${token}`}
    });
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

async function loadEvents(){
    let r = await fetch("/api/events", {
        headers: {"Authorization": `Bearer ${token}`}
    });
    let data = await r.json();
    let list = document.getElementById("events");
    data.forEach(e => {
        list.innerHTML += `<li>${e.action} at ${e.created_at}</li>`;
    });
}

async function loadTokens(){
    let r = await fetch("/api/tokens", {
        headers: {"Authorization": `Bearer ${token}`}
    });
    let data = await r.json();
    let list = document.getElementById("tokens");
    data.forEach(t => {
        list.innerHTML += `<li>${t.id} (${t.type}) at ${t.path}</li>`;
    });
}

async function generate(){
    let node = document.getElementById("node").value;
    let type = document.getElementById("type").value;
    await fetch("/api/generate", {
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
    alert("Honeytoken created");
}

function startWS(){
    let ws = new WebSocket("ws://" + window.location.host + "/ws/events");
    ws.onmessage = (event) => {
        let data = JSON.parse(event.data);
        let list = document.getElementById("events");
        list.innerHTML += `<li>${data}</li>`;
    };
}

loadNodes();
loadEvents();
loadTokens();
startWS();