async function login(){

    const username = document.getElementById("user").value
    const password = document.getElementById("pass").value

    const res = await fetch("/api/login",{
        method:"POST",
        headers:{
            "Content-Type":"application/json"
        },
        body:JSON.stringify({
            username:username,
            password:password
        })
    })

    if(res.ok){

        window.location.href="/dashboard.html"

    }else{

        document.getElementById("error").innerText="Invalid login"

    }
}
