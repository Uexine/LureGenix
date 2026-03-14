from fastapi import FastAPI
import docker
import os
from generator import generate_env,generate_passwords

app=FastAPI()

client=docker.from_env()


@app.post("/generate")
def generate(data:dict):

    token_type=data["token_type"]
    placement=data["placement"]
    path=data["path"]

    if token_type=="env":
        content=generate_env()
    else:
        content=generate_passwords()

    if placement=="host":

        with open(path,"w") as f:
            f.write(content)

    elif placement=="container":

        container=client.containers.get(data["container"])

        cmd=f"bash -c 'echo \"{content}\" > {path}'"

        container.exec_run(cmd)

    return {"status":"created"}