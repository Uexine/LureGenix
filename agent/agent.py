import os
import time
import requests

SERVER="http://gateway:8000"

WATCH_DIR="/tmp"

files={}


def scan():

    for root,dirs,fs in os.walk(WATCH_DIR):

        for f in fs:

            path=os.path.join(root,f)

            files[path]=os.stat(path).st_atime


def monitor():

    while True:

        for f,last in files.items():

            try:

                new=os.stat(f).st_atime

                if new!=last:

                    requests.post(
                        SERVER+"/event",
                        json={
                            "node_id":1,
                            "token_id":1,
                            "action":"file_opened",
                            "file":f
                        }
                    )

                    files[f]=new

            except:
                pass

        time.sleep(2)


scan()
monitor()