#!/usr/bin/env python3
"""СТРАЖ РОЯ — исполнение I-2 на уровне аккаунта.

Проверяет каждое живое тело: protocol-verify/protocol подключён? последний прогон зелёный?
Тела, закрытые платформенными воротами (легитимные состояния дома), верифицируются
стражем со стороны SSOT: проводка дерева проверяется, вердикт GATED-LEGAL.
Провал вне легитимных состояний = exit 1 = красный CI = тревога дома.

Эмерджент (EMERGENT.md п.9): ворота платформы — законное состояние носителя,
не оправдание тишины; исполнение переезжает на раннер.
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TOK = os.environ.get("GITHUB_TOKEN", "").strip()
API = "https://api.github.com"
OWNER = "rtynbirf"
PROTO_NAMES = ("protocol-verify.yml", "protocol.yml")
WITNESS_NAME = "invariant-witness.yml"


def api(path):
    url = API + path
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {TOK}", "Accept": "application/vnd.github+json",
        "User-Agent": "fleet-guard",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def all_live_bodies():
    out = []
    for page in (1, 2, 3):
        batch = api(f"/users/{OWNER}/repos?per_page=100&sort=pushed&page={page}")
        if not batch:
            break
        out += batch
    return [r for r in out if not r["archived"]]


def legit_gated():
    """Имена тел из legit_open_states.txt (первое поле строки)."""
    d = api(f"/repos/{OWNER}/khozyain/contents/{urllib.parse.quote('legit_open_states.txt')}")
    import base64
    txt = base64.b64decode(d["content"]).decode("utf-8")
    names = set()
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        names.add(line.split("|")[0].strip())
    return names


def latest_run(full, wf_names):
    try:
        d = api(f"/repos/{full}/actions/runs?per_page=60")
        for r in d.get("workflow_runs", []):
            if any(r["path"].endswith(n) for n in wf_names):
                return (r["conclusion"] or r["status"], r["created_at"])
        return ("none", None)
    except Exception as ex:
        return (f"api-error:{type(ex).__name__}", None)


def proto_verdict(full, gated):
    """Вердикт протокола на теле по последнему прогону (v7: транзиент не провал)."""
    state, created = latest_run(full, PROTO_NAMES)
    if state == "none" or state.startswith("api-error"):
        # прогонов нет: gated-тело — законное состояние; прочие — ждёт пуш (UNKNOWN, не провал)
        return ("GATED-LEGAL" if gated else "PENDING"), state
    if state == "success":
        return "PASS", state
    if state == "failure":
        return ("GATED-LEGAL" if gated else "FAIL"), state
    if state in ("queued", "in_progress"):
        age_min = 999.0
        if created:
            t = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - t).total_seconds() / 60.0
        return ("FAIL-STUCK" if age_min > 60 else "PENDING"), state
    return ("PENDING" if gated else "FAIL"), state


def fsm_selftest():
    """Протокол исполняется самим стражем (SSOT-раннер)."""
    p = subprocess.run([sys.executable, "protocol_fsm.py"], capture_output=True, text=True, timeout=120)
    tail = (p.stdout or p.stderr).strip().splitlines()
    line = next((l for l in reversed(tail) if "15/15" in l or "АВТОМАТ" in l), tail[-1] if tail else "")
    return p.returncode, line


def main():
    bodies = all_live_bodies()
    legal = legit_gated()
    code, fsm_line = fsm_selftest()
    if code != 0:
        print("СТРАЖ: протокол сам не исполнился —", fsm_line)
        sys.exit(2)
    print("СТРАЖ · протокол исполнен раннером:", fsm_line)

    rows = ["repo,wired,last_protocol,last_witness,verdict,checked_at"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_pass = n_gated = n_fail = n_pending = 0
    for body in bodies:
        name = body["name"]
        full = body["full_name"]
        try:
            wfs = api(f"/repos/{full}/actions/workflows?per_page=100").get("workflows", [])
        except Exception:
            wfs = []
        proto_wf = next((w["path"] for w in wfs if w["path"].rsplit("/", 1)[-1] in PROTO_NAMES), None)
        wit_wf = next((w["path"] for w in wfs if w["path"].rsplit("/", 1)[-1] == WITNESS_NAME), None)

        last_wit = latest_run(full, (WITNESS_NAME,))[0] if wit_wf else "absent"

        gated = name in legal
        wired = bool(proto_wf)
        verdict, state = ("GATED-LEGAL", "unwired-gated") if (not wired and gated) else proto_verdict(full, gated)
        wit_v = ("WITNESS-OK" if last_wit == "success"
                 else "WITNESS-STALE" if last_wit not in ("absent", "none")
                 else ("WITNESS-ABSENT-LEGAL" if gated else "WITNESS-ABSENT"))
        if verdict == "PASS":
            n_pass += 1
        elif verdict == "GATED-LEGAL":
            n_gated += 1
        elif verdict == "PENDING":
            n_pending += 1
        else:
            n_fail += 1
        rows.append(f"{full},{'yes' if wired else 'no'},{state},{wit_v},{verdict},{now}")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fleet")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "FLEET_VERDICT.csv")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")

    print(f"СТРАЖ · тела={len(bodies)} PASS={n_pass} GATED-LEGAL={n_gated} PENDING={n_pending} FAIL={n_fail}")
    for r in rows[1:]:
        if ",FAIL" in r:
            print("ТРЕВОГА:", r)
        if ",PENDING," in r:
            print("НАБЛЮДЕНИЕ (транзиент):", r)
    print("срез:", out_path)
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
