async function login(){

let username=document.getElementById("user").value
let password=document.getElementById("pass").value

let r=await fetch("/api/login",{

method:"POST",

headers:{
"Content-Type":"application/json"
},

body:JSON.stringify({
username:username,
password:password
})

})

if(r.status!==200){

document.getElementById("error").innerText="Invalid credentials"

return

}

let data=await r.json()

localStorage.setItem("token",data.token)

window.location="/dashboard"

}
