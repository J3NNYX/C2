# C2-Playroom — A Lightweight Post-Exploitation experimental project


> ⛔ **DISCLAIMER: This project is for educational and legitimate purposes only** ⛔
>
> You are solely responsible for how you use this code. Do not under any circumstances deploy it against systems you do not own or lack explicit written authorization to test.
>  The author accepts no liability for unauthorized use of this software—including but not limited to violations of local, state, federal, or international law.
---

A minimal, Python-based command-and-control (C2) framework written to practice some core offensive tradecraft: beaconing, encrypted channels, TLS fingerprint evasion, domain fronting, and process masquerading.

This is my first open-source project — a "clean" implementation of the patterns I studied in another similar tools.


## Overview

A three-component C2 architecture built for practical red team operations:

| Component | File | Role |
|-----------|------|------|
| Agent | `agent/beacon.py` | Onn the Target — Periodic beacon, Command dispatch, Result reporting |
| Server | `server/base.py` | Flask API — Task queueing, Result ingestion, Operator interface |
| Protocol | `shared/protocol.py` | Fernet-based symmetric encryption used across all channels |

<img width="855" height="285" alt="chart_1" src="https://github.com/user-attachments/assets/3bcb17cb-b938-4e96-b08a-949856e78b66" />


#### Agent Architecture (`agent/beacon.py`)

#### Beaconing — The Core Loop

The agent runs a persistent, periodic check-in loop. On every cycle it:

- 1 -> **Encrypts its unique session ID** and POSTs it to the beacon endpoint.
- 2 -> **Decrypts the server's response** — if a task is queued, dispatches it for execution.
- 3 -> **Computes the next sleep interval** using layered timing obfuscation (details below).


Each run generates a fresh UUID — no two beacons share an identifier, making session correlation harder from threat intel feeds.

### Evasion Stack

⚙️ WIP 🚧
