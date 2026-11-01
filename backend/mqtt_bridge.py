"""MQTT -> HTTPS bridge.

Task 1 asks the fridge to publish over MQTT; Task 4 asks for HMAC-signed ingest over HTTP. This
keeps both: the ESP32 signs on the device and publishes that same JSON body to
`coldchain/<device_id>/reading`, and this process forwards it verbatim to /api/sensor. Nothing here
signs anything, so the bridge cannot become the trusted party — a compromised bridge can replay or
drop messages, but cannot invent a reading.

    mosquitto -p 1883
    API_BASE=http://127.0.0.1:8000 MQTT_HOST=127.0.0.1 python backend/mqtt_bridge.py

Expected payload, exactly as simulator.py sends it:
    {"device_id":"fridge-1","temperature":5.0,"door_open":false,"ts":1793481143.18,
     "nonce":"...","signature":"...","power_ok":true,"battery":100.0,"compressor_on":false,
     "buffered":false}

When that is accepted and the answer names a batch status, the bridge publishes
`{"batch_status":"Discard"}` on coldchain/<device_id>/command so the node can latch its red LED.

A forward that fails is reported and dropped: the broker redelivers only while it holds a session
for this client, so run the bridge beside the API rather than as the only thing that survives a
redeploy.
"""
import json
import os
import sys

import paho.mqtt.client as mqtt
import requests

API = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")
BROKER = os.getenv("MQTT_HOST", "127.0.0.1")
PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC = "coldchain/+/reading"


def on_message(client, _userdata, message):
    try:
        body = json.loads(message.payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("dropped, not JSON:", message.topic, message.payload[:80])
        return
    if not isinstance(body, dict):
        print("dropped, not an object:", message.topic)
        return
    device = body.setdefault("device_id", message.topic.split("/")[1])
    try:
        r = requests.post(f"{API}/api/sensor", json=body, timeout=15)
        print(message.topic, r.status_code, r.text[:120])
        echo_command(client, device, r)
    except requests.RequestException as x:
        print(message.topic, "forward failed:", type(x).__name__, str(x)[:120])


def echo_command(client, device_id, response):
    """Send the ingest answer back to coldchain/<device>/command.

    A node on MQTT never sees /api/sensor's reply, and Task 2 wants its red LED latched while a batch
    reads Discard - which only the server knows, because the budget is per batch and batches move.
    Only batch_status travels: this is a status echo, not a control channel, and it stays unsigned
    because nothing the node does with it can change a stored reading.
    """
    try:
        reply = response.json() if response.ok else None
    except ValueError:
        return
    if isinstance(reply, dict) and "batch_status" in reply:
        client.publish(f"coldchain/{device_id}/command",
                       json.dumps({"batch_status": reply["batch_status"]}), qos=1)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="coldchain-bridge")
    client.on_message = on_message
    try:
        client.connect(BROKER, PORT)
    except OSError as x:
        sys.exit(f"cannot reach MQTT broker {BROKER}:{PORT} — {x}")
    client.subscribe(TOPIC, qos=1)
    print(f"forwarding {TOPIC} -> {API}/api/sensor")
    client.loop_forever()


if __name__ == "__main__":
    main()
