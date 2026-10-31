"""Find out why MQTT messages from the ESP32 do not reach the backend.

Typical cause on Windows: the Mosquitto *service* listens on 127.0.0.1 only (the backend connects there)
while the ESP32 publishes to the laptop's network address — reaching another broker, or nothing at all.

The check, for the backend's broker and every IPv4 address of this computer (same port):
1. TCP connect → is a broker listening there (i.e. could the ESP32 connect)?
2. MQTT connect + subscribe '#' for a few seconds → which topics flow on that broker.
3. A probe message published on each broker → which addresses are the *same* broker.
Firewall rules for incoming LAN connections cannot be tested from this computer itself.
"""
from __future__ import annotations

import socket
import threading
import time
import uuid
from collections import Counter


def local_ipv4() -> list[str]:
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; selects the outgoing interface
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    return [ip for ip in dict.fromkeys(ips) if not ip.startswith("127.") and not ip.startswith("169.254.")]


def tcp_open(host: str, port: int, timeout: float = 1.0) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as exc:
        return False, exc.strerror or str(exc)


def diagnose(backend_host: str, port: int, prefix: str, username: str | None = None, password: str | None = None,
             listen_s: float = 4.0, extra_hosts: list[str] | None = None) -> dict:
    import paho.mqtt.client as mqtt

    lan = local_ipv4()
    hosts = list(dict.fromkeys([backend_host, "127.0.0.1", *lan, *(extra_hosts or [])]))
    res: dict[str, dict] = {}
    clients: dict[str, mqtt.Client] = {}
    probe_id = uuid.uuid4().hex[:10]
    for h in hosts:
        ok, err = tcp_open(h, port)
        r = res[h] = {"host": h, "port": port, "listening": ok, "error": err, "mqtt_ok": False, "topics": Counter(),
                      "samples": {}, "probes_seen": set(), "is_backend": h == backend_host, "lan": h in lan}
        if not ok:
            continue
        ev = threading.Event()

        def on_connect(c, ud, flags, rc, props, r=r, ev=ev):
            if not rc.is_failure:
                r["mqtt_ok"] = True
                c.subscribe("#", qos=0)
            else:
                r["error"] = f"broker refused: {rc}"
            ev.set()

        def on_message(c, ud, msg, r=r):
            if msg.topic.startswith(f"structurasense-probe/{probe_id}/"):
                r["probes_seen"].add(msg.topic.rsplit("/", 1)[1])
                return
            r["topics"][msg.topic] += 1
            r["samples"].setdefault(msg.topic, msg.payload[:160].decode("utf-8", "replace"))

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ss-diag-{probe_id}-{len(clients)}", clean_session=True)
        if username:
            c.username_pw_set(username, password)
        c.on_connect, c.on_message = on_connect, on_message
        try:
            c.connect(h, port, keepalive=10)
        except OSError as exc:
            r["error"] = str(exc)
            continue
        c.loop_start()
        ev.wait(3)
        clients[h] = c
    time.sleep(0.5)
    for i, (h, c) in enumerate(clients.items()):
        if res[h]["mqtt_ok"]:
            res[h]["probe_tag"] = str(i)
            c.publish(f"structurasense-probe/{probe_id}/{i}", b"probe")
    time.sleep(listen_s)
    for c in clients.values():
        c.loop_stop()
        c.disconnect()

    tag_to_host = {r["probe_tag"]: h for h, r in res.items() if "probe_tag" in r}
    out = []
    for h, r in res.items():
        same = sorted(tag_to_host[t] for t in r["probes_seen"] if t in tag_to_host and tag_to_host[t] != h)
        out.append({**{k: v for k, v in r.items() if k not in ("topics", "samples", "probes_seen", "probe_tag")},
                    "same_broker_as": same,
                    "topics": [{"topic": t, "count": n, "sample": r["samples"].get(t)} for t, n in r["topics"].most_common(10)]})
    return {"backend_broker": f"{backend_host}:{port}", "lan_addresses": lan, "listen_s": listen_s, "brokers": out,
            **verdict(out, backend_host, prefix, port)}


def verdict(brokers: list[dict], backend_host: str, prefix: str, port: int) -> dict:
    by = {b["host"]: b for b in brokers}
    be = by.get(backend_host)
    lan = [b for b in brokers if b["lan"]]
    same_as_backend = set(be["same_broker_as"]) if be else set()

    def traffic(b):
        return sum(t["count"] for t in b["topics"])

    if be is None or not be["listening"]:
        return {"status": "no_broker", "summary": f"No MQTT broker is running at {backend_host}:{port}.",
                "fix": "Install Mosquitto (mosquitto.org) and run scripts\\start-broker.ps1 as administrator — it starts the broker "
                       "for this computer and the network. The backend reconnects by itself.", "suggest_host": None}
    if traffic(be):
        topics = [t["topic"] for t in be["topics"]]
        ok = [t for t in topics if t.startswith(prefix + "/")]
        if ok:
            return {"status": "ok", "summary": f"Messages are arriving on the backend's broker ({', '.join(ok[:3])}).",
                    "fix": "If they are rejected, the message list below says why (e.g. bind the topic to a device).", "suggest_host": None}
        return {"status": "wrong_topic", "summary": f"Messages arrive, but on {', '.join(topics[:3])} — the backend only listens to '{prefix}/…'.",
                "fix": f"Change TOPIC in the sketch to start with '{prefix}/' (e.g. '{prefix}/sensors') and bind it to the device.",
                "suggest_host": None}
    other = [b for b in brokers if b["host"] != backend_host and b["host"] not in same_as_backend and traffic(b)]
    if other:
        b = other[0]
        return {"status": "other_broker", "summary": f"Your device's messages are on a different broker at {b['host']}:{port} "
                f"({', '.join(t['topic'] for t in b['topics'][:3])}), not on the one the backend uses ({backend_host}:{port}). "
                "On Windows this is usually the Mosquitto service plus a second broker you started yourself.",
                "fix": f"Click 'Use {b['host']}' (the backend then connects to that broker), or stop the extra broker.",
                "suggest_host": b["host"]}
    unreachable = [b for b in lan if not b["listening"]]
    if lan and len(unreachable) == len(lan):
        return {"status": "localhost_only", "summary": f"The broker only accepts connections from this computer (127.0.0.1). "
                f"Your ESP32 cannot connect to {', '.join(b['host'] for b in lan)}:{port}.",
                "fix": "Start Mosquitto with 'listener 1883 0.0.0.0' and 'allow_anonymous true' — run scripts\\start-broker.ps1 "
                       "as administrator (it stops the localhost-only service and starts a network broker).",
                "suggest_host": None}
    lan_ok = [b for b in lan if b["listening"]]
    return {"status": "silent", "summary": f"The broker is reachable on {', '.join(b['host'] for b in lan_ok) or backend_host}:{port}, "
            "but nothing published anything during the check.",
            "fix": f"Check the ESP32 Serial Monitor for 'MQTT connected'. MQTT_HOST in the sketch must be "
                   f"{lan_ok[0]['host'] if lan_ok else 'this laptop’s IP'}; both must be on the same Wi-Fi; allow TCP {port} "
                   "in Windows Defender Firewall (Private networks).",
            "suggest_host": None}
