#!/usr/bin/env python3
"""HUMAN-LFS validator v0.3. Python 3.9+, stdlib only.

Проверяет СТРУКТУРУ и правила графа. Содержательную истинность утверждений он не проверяет:
для этого есть status + evidence (с source_ref), которые заполняет человек или проверка по первоисточнику.

  python validate_graph.py [BUILD_GRAPH.json]
  python validate_graph.py [BUILD_GRAPH.json] --update-lock   # после осознанной правки графа
"""
import hashlib
import json
import re
import sys
from datetime import date as today_date
from pathlib import Path

STATUSES = ("PASS", "FAIL", "PARTIAL", "UNKNOWN")
TEXT_FIELDS = ("id", "version", "falsification_or_revision_condition")
LIST_FIELDS = ("source", "verified_by", "replaceable_by")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRIVIAL = {"ok", "pass", "done", "yes", "true", "checked", "verified", "n/a", "na", "none", "-",
    "checked it works", "looks good", "seems fine", "all good", "works fine", "tested and ok",
    "confirmed", "approved", "accepted", "no issues", "passed", "success"}


def _text(v):
    return isinstance(v, str) and v.strip() != ""


def _id_list(v):
    return isinstance(v, list) and all(_text(x) for x in v)


def node_hash(n):
    raw = json.dumps(n, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lock_path_for(target: Path) -> Path:
    return target.with_name(target.stem + ".lock.json")


def _check_evidence(p, n, errors):
    ev = n.get("evidence", [])
    if not isinstance(ev, list):
        errors.append(f"{p}: evidence must be an array")
        return 0
    uris = {s.get("uri") for s in (n.get("source") or []) if isinstance(s, dict)}
    for j, e in enumerate(ev):
        q = f"{p}.evidence[{j}]"
        if not (isinstance(e, dict) and all(_text(e.get(k)) for k in ("check", "result", "date", "source_ref"))):
            errors.append(f"{q}: needs non-empty check, result, date, source_ref")
            continue
        if not DATE.match(e["date"]):
            errors.append(f"{q}: date must be YYYY-MM-DD")
        else:
            try:
                from datetime import date as _d
                ev_date = _d.fromisoformat(e["date"])
                if ev_date > _d.today():
                    errors.append(f"{q}: date cannot be in the future")
            except ValueError:
                errors.append(f"{q}: invalid date")
        if e["source_ref"] == "conversation":
            errors.append(f"{q}: source_ref cannot be 'conversation'")
        elif e["source_ref"] not in uris:
            errors.append(f"{q}: source_ref is not one of this node's source uri")
        for k in ("check", "result"):
            t = e[k].strip()
            if len(t) < 12 or t.lower().rstrip(".") in TRIVIAL:
                errors.append(f"{q}: {k} is vacuous")
        if e["check"].strip().lower() == e["result"].strip().lower():
            errors.append(f"{q}: check and result are identical")
    # duplicate evidence detection
    seen = set()
    for j, e in enumerate(ev):
        if isinstance(e, dict):
            key = (e.get("check","").strip().lower(), e.get("result","").strip().lower(), e.get("date",""), e.get("source_ref",""))
            if key in seen:
                errors.append(f"{p}.evidence[{j}]: duplicate of earlier evidence entry")
            seen.add(key)
    return len(ev)


def _sccs(graph):
    index, low, onstack, stack, out, counter = {}, {}, set(), [], [], [0]
    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v); onstack.add(v)
        for w in graph.get(v, []):
            if w not in graph:
                continue
            if w not in index:
                strong(w); low[v] = min(low[v], low[w])
            elif w in onstack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop(); onstack.discard(w); comp.append(w)
                if w == v:
                    break
            out.append(comp)
    for v in graph:
        if v not in index:
            strong(v)
    return out


def _lock_errors(data, lock_path):
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"lock parse error: {exc}"]
    locked = lock.get("nodes")
    if not isinstance(locked, dict):
        return ["lock: nodes must be an object"]
    cur = {n["id"]: node_hash(n) for n in data["nodes"] if isinstance(n, dict) and _text(n.get("id"))}
    errs = []
    for i, h in locked.items():
        if i not in cur:
            errs.append(f"lock: node {i!r} lost since last lock")
        elif cur[i] != h:
            errs.append(f"lock: node {i!r} changed since last lock (review, then --update-lock)")
    for i in cur:
        if i not in locked:
            errs.append(f"lock: node {i!r} is new (review, then --update-lock)")
    return errs


def validate(path: Path, check_lock=True):
    """Возвращает (errors, data)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"JSON parse error: {exc}"], None

    errors = []
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["nodes must be a non-empty array"], data

    exit_c = (data.get("lifecycle") or {}).get("exit_criteria")
    if not (isinstance(exit_c, list) and exit_c and all(_text(x) for x in exit_c)):
        errors.append("lifecycle.exit_criteria must be a non-empty list of strings")

    ids, by_id = set(), {}
    for i, n in enumerate(nodes):
        p = f"nodes[{i}]"
        if not isinstance(n, dict):
            errors.append(f"{p}: must be an object")
            continue
        for f in TEXT_FIELDS:
            if not _text(n.get(f)):
                errors.append(f"{p}: missing or empty {f}")
        nid = n.get("id")
        if _text(nid):
            if nid in ids:
                errors.append(f"{p}: duplicate id {nid!r}")
            ids.add(nid)
            by_id[nid] = n
        if not isinstance(n.get("scaffold"), bool):
            errors.append(f"{p}: scaffold must be boolean")
        if n.get("status") not in STATUSES:
            errors.append(f"{p}: status must be one of {STATUSES}")
        for f in LIST_FIELDS:
            v = n.get(f)
            if not (isinstance(v, list) and v):
                errors.append(f"{p}: {f} must be a non-empty array")
        for j, s in enumerate(n.get("source") or []):
            if not (isinstance(s, dict) and all(_text(s.get(k)) for k in ("type", "uri", "claim"))):
                errors.append(f"{p}.source[{j}]: needs non-empty type, uri, claim")
        for f in ("verified_by", "replaceable_by"):
            for j, v in enumerate(n.get(f) or []):
                if not _text(v):
                    errors.append(f"{p}.{f}[{j}]: empty entry")

        n_ev = _check_evidence(p, n, errors)
        if n.get("status") == "PASS":
            if n_ev == 0:
                errors.append(f"{p}: status PASS requires evidence")
            srcs = [s for s in (n.get("source") or []) if isinstance(s, dict)]
            if srcs and all(s.get("uri") == "conversation" for s in srcs):
                errors.append(f"{p}: status PASS impossible: all sources are 'conversation'")

    # рёбра
    valid_deps = {}
    for nid, n in by_id.items():
        dep = n.get("depends_on")
        if not (isinstance(dep, dict) and _id_list(dep.get("build")) and _id_list(dep.get("runtime"))):
            errors.append(f"{nid}: depends_on must be {{build:[ids], runtime:[ids]}}")
            continue
        valid_deps[nid] = dep
        for kind in ("build", "runtime"):
            for t in dep[kind]:
                if t == nid:
                    errors.append(f"{nid}: depends on itself ({kind})")
                elif t not in by_id:
                    errors.append(f"{nid}: unknown {kind} dependency {t!r}")

    # build-граф: DAG
    state = {}
    def visit(u, stack):
        state[u] = 1
        for t in valid_deps.get(u, {}).get("build", []):
            if t not in by_id:
                continue
            if state.get(t) == 1:
                errors.append("build cycle: " + " -> ".join(stack + [u, t]))
            elif t not in state:
                visit(t, stack + [u])
        state[u] = 2
    for u in valid_deps:
        if u not in state:
            visit(u, [])

    # runtime-циклы: только объявленные
    declared_cycles = set()
    for k, c in enumerate(data.get("declared_runtime_cycles") or []):
        if isinstance(c, dict) and _id_list(c.get("nodes")) and c.get("nodes") and _text(c.get("reason")):
            declared_cycles.add(frozenset(c["nodes"]))
            for cn in c["nodes"]:
                if cn not in by_id:
                    errors.append(f"declared_runtime_cycles[{k}]: unknown node {cn!r}")
        else:
            errors.append(f"declared_runtime_cycles[{k}]: needs nodes[] and reason")
    rgraph = {u: [t for t in d["runtime"] if t in by_id and t != u] for u, d in valid_deps.items()}
    for comp in _sccs(rgraph):
        if len(comp) > 1 and frozenset(comp) not in declared_cycles:
            errors.append("runtime cycle not declared: " + ", ".join(sorted(comp)))

    # declared_interfaces + chroot-правило
    declared = set()
    for k, di in enumerate(data.get("declared_interfaces") or []):
        q = f"declared_interfaces[{k}]"
        if not (isinstance(di, dict) and all(_text(di.get(x)) for x in ("from", "to", "reason"))):
            errors.append(f"{q}: needs from, to, reason")
            continue
        if di.get("substitutable") is not True:
            errors.append(f"{q}: substitutable must be true")
        a, b = di["from"], di["to"]
        if a not in by_id or b not in by_id:
            errors.append(f"{q}: unknown node in {a!r} -> {b!r}")
            continue
        if by_id[a].get("role") != "INTERFACE":
            errors.append(f"{q}: 'from' node {a!r} must have role INTERFACE")
        if by_id[b].get("scaffold") is not True:
            errors.append(f"{q}: 'to' node {b!r} must be scaffold=true")
        declared.add((a, b))
    used = set()
    for nid, n in by_id.items():
        if n.get("scaffold") is not False:
            continue
        for t in valid_deps.get(nid, {}).get("runtime", []):
            if t in by_id and by_id[t].get("scaffold") is True:
                if (nid, t) in declared:
                    used.add((nid, t))
                else:
                    errors.append(f"chroot violation: {nid} (scaffold=false) needs {t} (scaffold=true) at runtime, not declared")
    for a, b in sorted(declared - used):
        errors.append(f"declared_interfaces: {a} -> {b} matches no runtime dependency (stale)")

    if check_lock and not errors:
        lp = lock_path_for(path)
        if lp.exists():
            errors.extend(_lock_errors(data, lp))
    return errors, data


def main(argv):
    update = "--update-lock" in argv
    args = [a for a in argv if not a.startswith("--")]
    target = Path(args[0]) if args else Path(__file__).with_name("BUILD_GRAPH.json")
    errors, data = validate(target, check_lock=not update)
    if errors:
        print("STRUCTURE: FAIL")
        for e in errors:
            print(f"- {e}")
        raise SystemExit(1)
    nodes = data["nodes"]
    counts = {s: sum(1 for n in nodes if n["status"] == s) for s in STATUSES}
    print(f"STRUCTURE: PASS ({len(nodes)} nodes)")
    print("CLAIMS: " + ", ".join(f"{s}={c}" for s, c in counts.items()))
    lp = lock_path_for(target)
    if update:
        lp.write_text(json.dumps({"nodes": {n["id"]: node_hash(n) for n in nodes}}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"LOCK: written {lp.name}")
    else:
        print("LOCK: ok" if lp.exists() else "LOCK: absent (run --update-lock)")
    if counts["PASS"] < len(nodes):
        print("NOTE: структурный PASS не означает истину; PASS у claim только с evidence.")


if __name__ == "__main__":
    main(sys.argv[1:])
