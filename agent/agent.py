import os
import time
import requests

SERVER = "http://gateway:8000"

WATCH = "/tmp/passwords.txt"

last = None

if os.path.exists(WATCH):
    last = os.stat(WATCH).st_atime


while True:

    if os.path.exists(WATCH):

        new = os.stat(WATCH).st_atime

        if last and new != last:

            requests.post(
                SERVER + "/event",
                json={
                    "token_id": 1,
                    "action": "file_opened",
                    "file": WATCH
                }
            )

        last = new

    time.sleep(3)