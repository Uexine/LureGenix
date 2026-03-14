async function loadNodes(){

let r=await fetch("/api/nodes")
let data=await r.json()

let table=document.getElementById("nodes")

data.forEach(n=>{

table.innerHTML+=`
<tr>
<td>${n.id}</td>
<td>${n.hostname}</td>
<td>${n.ip}</td>
</tr>
`

})

}

async function generate(){

let node=document.getElementById("node").value
let type=document.getElementById("type").value

await fetch("/api/generate",{
method:"POST",
headers:{
"Content-Type":"application/json"
},
body:JSON.stringify({
node_id:node,
file_type:type
})
})

alert("Honeytoken created")

}

function startWS(){

let ws=new WebSocket("ws://localhost:8080/ws/events")

ws.onmessage=(event)=>{

let data=JSON.parse(event.data)

let list=document.getElementById("events")

list.innerHTML+=`<li>${data.message}</li>`

}

}

loadNodes()
startWS()
