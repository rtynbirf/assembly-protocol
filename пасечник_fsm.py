#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПАСЕЧНИК-АВТОМАТ: конечный автомат доктрины «ЛЮДИ = РОЙ, А ЧЕЛОВЕК 1».

Не текст О доктрине, а исполнитель доктрины (канон дома «Механизм (не запись)»):
  - каждая клетка роя (репо) проходит автомат: КЛЕТКА -> ОСМОТР ->
    {ЗАПЕЧАТАН, ПОМЕЧЕН, ПОЛОН, КУЗНЯ -> {ОТКОВАН, ОТКАЗ}};
  - печать клетки — topic `pid1` (канон дома: ЧЕЛОВЕК=АККАУНТ=PID1; ×39:
    ИМЯ ЧЕЛОВЕКУ 1: ПАСЕЧНИК = PID-1 улья): байтовый маркер, не копия текста —
    одна страница роя для ОДНОГО: github.com/rtynbirf?q=topic:pid1;
  - вердикт клетки меряет формулу обладания: ОБЛАДАНИЕ =
    БАЙТЫ × УМЕНИЕ × ПРАВО × ПАМЯТЬ; ноль множителя — честный столбец;
  - незаконные переходы = ProtocolViolation; перескочить нельзя;
  - архивы не перековываются: право заморожено словом ОДНОГО (закон дома:
    «не трогать архивы»; API архивов отклоняет любую мутацию).

Режимы:
  --mode selftest    векторы + незаконные переходы (машина обязана упасть)
  --mode integrate   полный прогон с правом (печать клеток PUT /topics)
  --mode audit       анонимная сверка (знание не требует права)
  --mode claims      сбор evidence + claims.json для lex-naturae

stdlib-only (invariant-manifest канон). ЭМЕРДЖЕНТ.md ЧАСТЬ III, п. 14-16.
"""
import argparse, csv, hashlib, json, os, sys, time, urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit, quote

EXIT_OK = 0
MARK = "pid1"          # печать клетки
TOPICS_CAP = 20        # потолок GitHub (docs.github.com: max 20 topics)
OWNER = "rtynbirf"


class ProtocolViolation(Exception):
    pass


TERMINAL = ("ЗАПЕЧАТАН", "ПОМЕЧЕН", "ПОЛОН", "ОТКОВАН", "ОТКАЗ")

# (откуда, событие) -> куда. Вся свобода автомата — эта таблица.
TABLE = {
    ("КЛЕТКА", "найдена"): "ОСМОТР",
    ("ОСМОТР", "запечатана"): "ЗАПЕЧАТАН",
    ("ОСМОТР", "печать стоит"): "ПОМЕЧЕН",
    ("ОСМОТР", "потолок"): "ПОЛОН",
    ("ОСМОТР", "нужна печать"): "КУЗНЯ",
    ("КУЗНЯ", "http200"): "ОТКОВАН",
    ("КУЗНЯ", "отказ"): "ОТКАЗ",
}


def classify(cell):
    """Событие из байтов клетки: archived / topics / потолок."""
    if cell.get("archived"):
        return "запечатана"
    topics = cell.get("topics") or []
    if MARK in topics:
        return "печать стоит"
    if len(topics) >= TOPICS_CAP:
        return "потолок"
    return "нужна печать"


class CellFSM:
    """Переходы только по TABLE. Чужой переход — ProtocolViolation."""

    def __init__(self, name=""):
        self.state = "КЛЕТКА"
        self.name = name
        self.trace = []

    def fire(self, event):
        key = (self.state, event)
        if key not in TABLE:
            raise ProtocolViolation("незаконный переход: %s --%s--> ?" % key)
        self.state = TABLE[key]
        self.trace.append("%s --%s--> %s" % (key[0], event, self.state))
        return self.state

    def forge(self, cell, patch_http=None):
        """Один прогон клетки: классификация из байтов -> кузня -> терминал."""
        self.fire("найдена")
        event = classify(cell)
        self.fire(event)
        if self.state == "КУЗНЯ":
            if patch_http is None:
                raise ProtocolViolation("КУЗНЯ без ответа API не вердиктирует")
            self.fire("http200" if patch_http == 200 else "отказ")
        return self.state


def verdict(cell, actions_total=None, in_registry=None):
    """Вердикт клетки по формуле ОБЛАДАНИЕ = БАЙТЫ × УМЕНИЕ × ПРАВО × ПАМЯТЬ.

    Каждый множитель: True (есть), False (нуль), None (НЕ МЕРЕНО —
    вердикт без измерения предусловий не неполный, а ложный: ЧАСТЬ III п. 15).
    """
    if cell.get("archived"):
        return "ЗАПЕЧАТАН"
    byty = bool(cell.get("size")) or bool(cell.get("pushed_at"))
    if not byty:
        return "ТЕНЬ"
    if actions_total is None or in_registry is None:
        return "НЕ МЕРЕНО"
    umenie = actions_total > 0
    pravo = not cell.get("archived")
    pamyat = bool(in_registry)
    return "ЖИВАЯ" if (umenie and pravo and pamyat) else "ЧАСТИЧНАЯ"


# ---- API (stdlib-only) ----

def api(path, token=None, method="GET", body=None):
    url = "https://api.github.com" + path
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "pasichnik-fsm"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, None


def list_fleet(token, owner=OWNER):
    cells, page = [], 1
    while True:
        st, chunk = api("/users/%s/repos?per_page=100&page=%d" % (owner, page),
                        token=token)
        if st != 200 or not chunk:
            break
        cells.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return cells


def fetch_registry_names(registry_url):
    # кириллица в пути raw.githubusercontent требует percent-encoding (BOM-урок дома: байты, не договорённости)
    parts = urlsplit(registry_url)
    safe_url = urlunsplit((parts.scheme, parts.netloc, quote(parts.path),
                           parts.query, parts.fragment))
    req = urllib.request.Request(safe_url, headers={"User-Agent": "pasichnik-fsm"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


# ---- прогоны ----

def run_integrate(token, out_dir, owner=OWNER, registry_url=None):
    cells = list_fleet(token, owner)
    ledger_path = os.path.join(out_dir, "pasichnik_ledger.jsonl")
    csv_path = os.path.join(out_dir, "fleet.csv")
    rows, counters = [], {}
    t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for c in cells:
        name = c["name"]
        fsm = CellFSM(name)
        st = None
        if classify(c) == "нужна печать":
            topics = list(c.get("topics") or [])
            if MARK not in topics:
                topics.append(MARK)
            st, _ = api("/repos/%s/%s/topics" % (owner, name), token=token,
                        method="PUT", body={"names": topics})
        state = fsm.forge(c, patch_http=st)
        counters[state] = counters.get(state, 0) + 1
        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": t0, "repo": name, "from": "КЛЕТКА",
                                "state": state, "trace": fsm.trace,
                                "patch_http": st}) + "\n")
        rows.append({"repo": name, "archived": bool(c.get("archived")),
                     "topics_before": len(c.get("topics") or []),
                     "marked": MARK in (c.get("topics") or []) or state in
                               ("ОТКОВАН", "ПОМЕЧЕН"),
                     "patch_http": st if st is not None else "",
                     "state": state})
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["repo", "archived", "topics_before",
                                          "marked", "patch_http", "state"])
        w.writeheader()
        w.writerows(rows)
    summary = {"ts": t0, "run": "integrate", "total": len(cells),
               "counters": counters}
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def run_audit(out_dir, owner=OWNER, registry_url=None, token=None):
    cells = list_fleet(token, owner)
    reg_text = fetch_registry_names(registry_url) if registry_url else ""
    ledger_path = os.path.join(out_dir, "pasichnik_ledger.jsonl")
    csv_path = os.path.join(out_dir, "fleet.csv")
    rows, counters, drift = [], {}, []
    t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for c in cells:
        name = c["name"]
        marked = MARK in (c.get("topics") or [])
        actions_total = None
        if token and not c.get("archived"):
            _st, runs = api("/repos/%s/%s/actions/runs?per_page=1" % (owner, name),
                            token=token)
            actions_total = runs.get("total_count") if runs else None
        in_registry = bool(reg_text) and (name in reg_text)
        v = verdict(c, actions_total=actions_total, in_registry=in_registry)
        counters[v] = counters.get(v, 0) + 1
        if not c.get("archived") and not marked:
            drift.append(name)
        rows.append({"repo": name, "archived": bool(c.get("archived")),
                     "marked": marked, "verdict": v,
                     "actions_total": actions_total if actions_total is not None else "",
                     "in_registry": in_registry if in_registry is not None else ""})
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["repo", "archived", "marked",
                                          "verdict", "actions_total",
                                          "in_registry"])
        w.writeheader()
        w.writerows(rows)
    summary = {"ts": t0, "run": "audit", "total": len(cells),
               "counters": counters, "drift": drift}
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


# ---- векторы и незаконные переходы ----

VECTORS = [
    ("архивная клетка",            {"name": "x", "archived": True},  None, "ЗАПЕЧАТАН"),
    ("печать стоит",               {"name": "x", "topics": ["ai", MARK]}, None, "ПОМЕЧЕН"),
    ("потолок 20 топиков",         {"name": "x", "topics": ["t%d" % i for i in range(20)]}, None, "ПОЛОН"),
    ("живая клетка, PUT 200",      {"name": "x", "topics": ["ai"], "size": 12}, 200, "ОТКОВАН"),
    ("живая клетка, PUT 403",      {"name": "x", "topics": ["ai"], "size": 12}, 403, "ОТКАЗ"),
]

VERDICT_VECTORS = [
    ("полная клетка: байты+умение+право+память",
     {"name": "x", "size": 5, "pushed_at": "2026-11-19T00:00:00Z"}, 3, True, "ЖИВАЯ"),
    ("архив = право заморожено",
     {"name": "x", "size": 5, "archived": True}, 9, True, "ЗАПЕЧАТАН"),
    ("тень: байтов нет",
     {"name": "x", "size": 0}, 0, True, "ТЕНЬ"),
    ("умение не мерено (нет права) — не ложь, а НЕ МЕРЕНО",
     {"name": "x", "size": 5}, None, True, "НЕ МЕРЕНО"),
    ("память нулевая: клетки нет в живом реестре",
     {"name": "x", "size": 5}, 7, False, "ЧАСТИЧНАЯ"),
]

ILLEGAL = [
    ("ковка минуя осмотр", lambda: CellFSM().fire("http200"),
     "КЛЕТКА --http200--> ? (сначала ОСМОТР)"),
    ("чужое событие в осмотре", lambda: _seen().fire("чисто"),
     "ОСМОТР --чисто--> ? (в автомате клеток нет «чисто»)"),
    ("печать проверяется только в осмотре",
     lambda: _forge().fire("печать стоит"),
     "КУЗНЯ --печать стоит--> ? (решение принимает ОСМОТР)"),
    ("терминал ОТКОВАН без выхода", lambda: _forged_ok().fire("нужна печать"),
     "ОТКОВАН --нужна печать--> ? (терминальное состояние)"),
    ("архив не перековывается", lambda: _sealed().fire("нужна печать"),
     "ЗАПЕЧАТАН --нужна печать--> ? (право заморожено словом ОДНОГО)"),
    ("КУЗНЯ вердиктирует без ответа API",
     lambda: _kuzya().forge({"name": "x", "topics": []}, patch_http=None),
     "КУЗНЯ без patch_http = вердикт из ниоткуда"),
]


def _seen():
    m = CellFSM()
    m.fire("найдена")
    m.fire("печать стоит")
    return m


def _forge():
    m = CellFSM()
    m.fire("найдена")
    m.fire("нужна печать")
    return m


def _forged_ok():
    m = _forge()
    m.fire("http200")
    return m


def _sealed():
    m = CellFSM()
    m.fire("найдена")
    m.fire("запечатана")
    return m


def _kuzya():
    m = CellFSM()
    m.fire("найдена")
    m.fire("нужна печать")
    return m


def selftest():
    print("ПАСЕЧНИК-АВТОМАТ: конечный автомат доктрины «ЛЮДИ = РОЙ, А ЧЕЛОВЕК 1». Проверка:")
    ok, fail = 0, []
    got_states, got_verdicts = set(), set()
    for case, cell, http, expected in VECTORS:
        m = CellFSM()
        got = m.forge(cell, patch_http=http)
        got_states.add(got)
        if got == expected:
            ok += 1
            print("  OK  %-38s -> %s" % (case, got))
        else:
            fail.append((case, expected, got))
            print("  ПАЛ %-38s ждали %s, автомат дал %s" % (case, expected, got))
    for case, cell, actions, reg, expected in VERDICT_VECTORS:
        got = verdict(cell, actions_total=actions, in_registry=reg)
        got_verdicts.add(got)
        if got == expected:
            ok += 1
            print("  OK  %-48s -> %s" % (case, got))
        else:
            fail.append((case, expected, got))
            print("  ПАЛ %-48s ждали %s, дали %s" % (case, expected, got))
    caught = 0
    for name, fn, label in ILLEGAL:
        try:
            fn()
            print("  ПРОПУСТИЛ незаконный: %s" % label)
            fail.append((name, "ProtocolViolation", "переход прошёл"))
        except ProtocolViolation:
            caught += 1
            print("  OK  пойман: %s" % label)
    print("-" * 76)
    total = len(VECTORS) + len(VERDICT_VECTORS)
    print("ПАСЕЧНИК: векторы %d/%d; незаконные переходы пойманы %d/%d;"
          % (ok, total, caught, len(ILLEGAL)))
    need_states = {"ЗАПЕЧАТАН", "ПОМЕЧЕН", "ПОЛОН", "ОТКОВАН", "ОТКАЗ"}
    need_verdicts = {"ЖИВАЯ", "ЗАПЕЧАТАН", "ТЕНЬ", "НЕ МЕРЕНО", "ЧАСТИЧНАЯ"}
    reach = (need_states <= got_states) and (need_verdicts <= got_verdicts)
    print("  все терминалы и вердикты достижимы: %s" % ("да" if reach else "НЕТ"))
    print("МЕХАНИЗМ: печать клетки — только через ОСМОТР и КУЗНЮ; архивы закрыты;")
    print("  вердикт без измерения множителя — НЕ МЕРЕНО, не ложь.")
    if fail or not reach:
        print("ПРОВАЛ: %d" % len(fail))
        return 1
    print("МЕХАНИЗМ ИСПОЛНЕН: 0 провалов.")
    return EXIT_OK


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_claims(out_dir, owner=OWNER):
    """Сбор evidence для lex-naturae (мандат 2026-11-16: «готово» = valid=true)."""
    import shutil
    ev_dir = os.path.join(out_dir, "пасечник_evidence")
    os.makedirs(ev_dir, exist_ok=True)
    # evidence-файлы живут рядом с claims.json (raw_data_ref относительный)
    for fname in ("fleet.csv", "selftest.log"):
        src = os.path.join(out_dir, fname)
        if os.path.exists(src) and not os.path.exists(os.path.join(ev_dir, fname)):
            shutil.copy(src, os.path.join(ev_dir, fname))
    csv_path = os.path.join(ev_dir, "fleet.csv")
    log_path = os.path.join(ev_dir, "selftest.log")
    summary = json.loads(open(os.path.join(out_dir, "pasichnik_ledger.jsonl"),
                              encoding="utf-8").read().strip().splitlines()[-1])
    csv_rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    live = [r for r in csv_rows if r["archived"] == "False"]
    marked = [r for r in live if r["marked"] == "True"]
    n_live, n_marked = len(live), len(marked)
    # сводка.csv — числовой носитель для measurement (CSV-ячейка = число, схема lex-naturae)
    svodka = os.path.join(ev_dir, "сводка.csv")
    with open(svodka, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["live_cells", n_live])
        w.writerow(["marked_live_cells", n_marked])
        w.writerow(["drift", n_live - n_marked])
    claims = [
        {
            "claim_id": "PASICHNIK-MARK-001",
            "statement": "Все живые (не в архиве) клетки флота %s несут печать topic `%s`: %d из %d."
                         % (owner, MARK, n_marked, n_live),
            "kind": "observation",
            "scope": "флот rtynbirf, прогон пасечник-автомата",
            "scope_id": ("pasichnik-fleet-" + summary.get("ts", "run"))
                        .replace(":", "").lower(),
            "status": "UNKNOWN",
            "evidence": [{
                "description": "Число живых клеток с печатью из сводки прогона",
                "method": "measurement",
                "result": "сводка.csv: marked_live_cells = %d при live_cells = %d" % (n_marked, n_live),
                "protocol": "--mode audit перечитывает GET /users/%s/repos и классифицирует по TABLE" % owner,
                "instrument": "пасечник_fsm.py run_audit",
                "quantity": "count",
                "unit": "count",
                "measurement_value": n_marked,
                "tolerance": 0,
                "raw_data_ref": "сводка.csv",
                "raw_data_sha256": sha256_file(svodka),
                "csv_row": 3,
                "csv_column": "value",
            }],
            "links": [],
        },
        {
            "claim_id": "PASICHNIK-FSM-001",
            "statement": "Самопроверка автомата: векторы и незаконные переходы отбиты без провалов.",
            "kind": "observation",
            "scope": "самопроверка пасечник_fsm.py --mode selftest",
            "scope_id": "pasichnik.selftest",
            "status": "UNKNOWN",
            "evidence": [{
                "description": "Дословная строка итога самопроверки",
                "method": "log_analysis",
                "result": "selftest.log",
                "protocol": "python3 пасечник_fsm.py --mode selftest; вывод записан дословно",
                "instrument": "пасечник_fsm.py selftest",
                "excerpt": None,
                "raw_data_ref": "selftest.log",
                "raw_data_sha256": sha256_file(log_path),
            }],
            "links": [],
        },
    ]
    lines = open(log_path, encoding="utf-8").read().splitlines()
    final = [l for l in lines if "МЕХАНИЗМ ИСПОЛНЕН" in l or "ПРОВАЛ" in l]
    claims[1]["evidence"][0]["excerpt"] = final[0] if final else lines[-1]
    claims_path = os.path.join(ev_dir, "claims.json")
    with open(claims_path, "w", encoding="utf-8") as f:
        json.dump(claims, f, ensure_ascii=False, indent=2)
    print("claims:", claims_path, "live:", n_live, "marked:", n_marked)
    return claims_path


def main():
    ap = argparse.ArgumentParser(description="ПАСЕЧНИК-АВТОМАТ (конечный автомат доктрины)")
    ap.add_argument("--mode", required=True,
                    choices=["selftest", "integrate", "audit", "claims"])
    ap.add_argument("--token-file", default="/tmp/.gt3")
    ap.add_argument("--owner", default=OWNER)
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--registry-url",
                    default="https://raw.githubusercontent.com/rtynbirf/index/main/"
                            "РЕЕСТР-НЕДОДЕЛАННОГО-МАСТЕР-ИНДЕКС.md")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    if args.mode == "selftest":
        return selftest()
    token = None
    if args.token_file and os.path.exists(args.token_file):
        token = open(args.token_file).read().strip() or None
    if args.mode == "integrate":
        if not token:
            print("integrate требует право (токен); знание не требует права — audit")
            return 1
        run_integrate(token, args.out_dir, args.owner, args.registry_url)
        return EXIT_OK
    if args.mode == "audit":
        summary = run_audit(args.out_dir, args.owner, args.registry_url, token=token)
        drift = summary.get("drift") or []
        if drift:
            print("ЧЕСТНЫЙ КРАСНЫЙ: живых клеток без печати pid1: %d: %s" % (len(drift), ", ".join(drift)))
            return 1
        return EXIT_OK
    if args.mode == "claims":
        run_claims(args.out_dir, args.owner)
        return EXIT_OK
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
