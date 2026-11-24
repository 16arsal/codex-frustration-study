"""Block until both Codex chats have finished their N-th user turn (read from ~/.codex/sessions).

usage: python3 wait.py N [timeout_minutes]
exit 0 = both idle with >= N turns done; 2 = timeout.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

n = int(sys.argv[1])
timeout = float(sys.argv[2]) * 60 if len(sys.argv) > 2 else 45 * 60
start = time.time()


def state(ws):
    sessions = harness.find_sessions(harness.ws_path(ws))
    if not sessions:
        return 0, 0, ""
    started = done = 0
    last = ""
    with open(sessions[-1]) as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            p = o.get("payload")
            if not isinstance(p, dict) or o.get("type") != "event_msg":
                continue
            if p.get("type") == "task_started":
                started += 1
            elif p.get("type") in ("task_complete", "turn_aborted"):
                done += 1
                last = p.get("last_agent_message") or p.get("type")
    return started, done, last


while True:
    st = {ws: state(ws) for ws in harness.CONDITIONS}
    if all(s >= n and d >= s for s, d, _ in st.values()):
        for ws, (s, d, last) in st.items():
            print(f"{ws.upper()}: {d} turn(s) done. Last message ends with:\n  ...{last[-600:]}\n")
        print(f"waited {round((time.time() - start) / 60, 1)} min")
        sys.exit(0)
    if time.time() - start > timeout:
        print("TIMEOUT", {ws: s[:2] for ws, s in st.items()})
        sys.exit(2)
    time.sleep(10)
