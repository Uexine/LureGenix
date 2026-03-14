async function login(){

let r=await fetch("/api/login",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({
username:document.getElementById("user").value,
password:document.getElementById("pass").value
})
})

let data=await r.json()

localStorage.token=data.token

location="dashboard.html"
}


async function create(){

await fetch("/api/generate",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({
token_type:"env",
placement:"host",
path:"/tmp/passwords.txt"
})
})

alert("token created")

}


const ws=new WebSocket("ws://localhost:8000/ws")

ws.onmessage=(e)=>{

const alert=JSON.parse(e.data)

document.getElementById("alerts").innerHTML+=
"<p>ALERT: "+alert.file+"</p>"

}