"""Registered Linux agents and explicitly scoped, read-only TCP discovery."""

import hashlib
import ipaddress
import os
import secrets
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.database import connect as get_db
from common.database import utc_timestamp

app = FastAPI(docs_url=None, redoc_url=None)
scan_lock = threading.Lock()


@app.get("/health")
def health():
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/nodes")
def nodes():
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, hostname, ip, CASE WHEN last_heartbeat > now() - interval '150 seconds' THEN 'online' ELSE 'offline' END, last_heartbeat, credential_hash IS NOT NULL FROM nodes ORDER BY id"
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "hostname": r[1],
            "ip": str(r[2]),
            "status": r[3],
            "last_heartbeat": utc_timestamp(r[4]),
            "enrolled": r[5],
        }
        for r in rows
    ]


class Registration(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    ip: str
    agent_id: str
    credential: str = Field(min_length=32, max_length=256)


@app.post("/register")
def register(data: Registration):
    try:
        identity = str(UUID(data.agent_id))
        address = str(ipaddress.ip_address(data.ip))
    except ValueError:
        raise HTTPException(400, "Invalid agent identity or IP address")
    digest = hashlib.sha256(data.credential.encode()).hexdigest()
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        # Serialise enrollment to prevent simultaneous re-enrollment taking over a node.
        cur.execute("SELECT pg_advisory_xact_lock(71024001)")
        cur.execute(
            "SELECT id, credential_hash FROM nodes WHERE agent_id=%s FOR UPDATE",
            (identity,),
        )
        row = cur.fetchone()
        if row:
            if not row[1] or not secrets.compare_digest(row[1], digest):
                raise HTTPException(
                    403, "Agent identity already enrolled with another credential"
                )
            node_id = row[0]
            cur.execute(
                "UPDATE nodes SET hostname=%s, ip=%s, status='online', last_heartbeat=now(), updated_at=now() WHERE id=%s",
                (data.hostname, address, node_id),
            )
        else:
            cur.execute(
                "SELECT id, credential_hash FROM nodes WHERE hostname=%s AND ip=%s FOR UPDATE",
                (data.hostname, address),
            )
            old = cur.fetchone()
            if old and old[1]:
                raise HTTPException(
                    409, "A different agent is already enrolled on this host"
                )
            if old:
                node_id = old[0]
                cur.execute(
                    "UPDATE nodes SET agent_id=%s, credential_hash=%s, status='online', last_heartbeat=now() WHERE id=%s",
                    (identity, digest, node_id),
                )
            else:
                cur.execute(
                    "INSERT INTO nodes(hostname,ip,agent_id,credential_hash,status,last_heartbeat) VALUES(%s,%s,%s,%s,'online',now()) RETURNING id",
                    (data.hostname, address, identity, digest),
                )
                node_id = cur.fetchone()[0]
    return {
        "status": "ok",
        "node_id": node_id,
        "hostname": data.hostname,
        "ip": address,
    }


class Credential(BaseModel):
    agent_id: str = Field(max_length=36)
    credential: str = Field(min_length=32, max_length=256)


@app.post("/authenticate")
def authenticate(data: Credential):
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, hostname, credential_hash FROM nodes WHERE agent_id=%s",
            (data.agent_id,),
        )
        row = cur.fetchone()
    if (
        not row
        or not row[2]
        or not secrets.compare_digest(
            row[2], hashlib.sha256(data.credential.encode()).hexdigest()
        )
    ):
        raise HTTPException(401, "Invalid agent credential")
    return {"node_id": row[0], "hostname": row[1]}


class ScanRequest(BaseModel):
    subnet: str = Field(max_length=64)


def scan_network(value):
    try:
        subnet = ipaddress.ip_network(value, strict=True)
        allowed = [
            ipaddress.ip_network(s.strip())
            for s in os.getenv("DISCOVERY_ALLOWED_CIDRS", "").split(",")
            if s.strip()
        ]
    except ValueError:
        raise HTTPException(400, "Specify a valid network CIDR")
    if (
        subnet.version != 4
        or subnet.num_addresses > 256
        or subnet.is_loopback
        or subnet.is_multicast
    ):
        raise HTTPException(
            400, "Discovery supports IPv4 networks of at most 256 addresses"
        )
    if not any(subnet.subnet_of(net) for net in allowed if net.version == 4):
        raise HTTPException(403, "Network is outside DISCOVERY_ALLOWED_CIDRS")
    if not scan_lock.acquire(blocking=False):
        raise HTTPException(429, "A discovery scan is already running")
    try:

        def probe(address):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                connection.settimeout(0.5)
                return (
                    {"ip": str(address), "ssh_port": 22}
                    if connection.connect_ex((str(address), 22)) == 0
                    else None
                )

        with ThreadPoolExecutor(max_workers=16) as pool:
            found = [result for result in pool.map(probe, subnet.hosts()) if result]
        return {"subnet": str(subnet), "hosts": found}
    finally:
        scan_lock.release()


@app.post("/scan")
def scan(data: ScanRequest):
    return scan_network(data.subnet)
