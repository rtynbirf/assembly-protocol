#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
МЕХАНИЗМ ПРОТОКОЛА: конечный автомат.

Не текст О протоколе, а исполнитель протокола:
  - вердикты v7 — состояния автомата (терминальные и нетерминальные);
  - П4/ЗАПЛАТ-6 — контур состояний: РАСХОЖДЕНИЕ -> УСЛОВИЯ -> ИСПОЛНЕНИЕ
    -> РЕАЛИЗАЦИЯ -> ОЖИДАНИЕ -> ИСПРАВИТЬ -> ПРОВЕРКА;
  - незаконные переходы (перескок через рамку, минуя прогон, выход из
    терминала, возврат без корня) = ProtocolViolation;
  - 12 векторов прогона первого исполнителя — векторы автомата:
    автомат обязан классифицировать их так же, как формула v7.

Судья по-прежнему ручной: автомат исполняет решения, не выносит их за
судью. Но порядок расследования теперь не договорённость, а таблица
переходов: перескочить нельзя.
"""

EXIT_OK = 0


class ProtocolViolation(Exception):
    pass


TERMINAL = ("ВЕРИФИЦИРОВАНО", "НЕСВЕРЯЕМО", "UNKNOWN")
VERDICT_STATES = TERMINAL + ("ПУСТО", "СОГЛАСОВАНО-НЕВЕРНО", "РАСХОЖДЕНИЕ")

# (откуда, событие) -> куда. Вся свобода автомата — эта таблица.
TABLE = {
    ("ПРОВЕРКА", "прогон"): "СХОДСТВО",
    ("СХОДСТВО", "сошлись"): "ПРЕДУСЛОВИЯ",
    ("СХОДСТВО", "не_сошлись"): "ВИНА",
    ("ПРЕДУСЛОВИЯ", "чисты"): "СВЕРКА",
    ("ПРЕДУСЛОВИЯ", "нарушены"): "ПУСТО",
    ("СВЕРКА", "возможна"): "СВЕРКА_ВЫХОДА",
    ("СВЕРКА", "невозможна"): "НЕСВЕРЯЕМО",
    ("СВЕРКА_ВЫХОДА", "пройдена"): "ВЕРИФИЦИРОВАНО",
    ("СВЕРКА_ВЫХОДА", "не_пройдена"): "СОГЛАСОВАНО-НЕВЕРНО",
    ("ВИНА", "без_вины"): "UNKNOWN",
    ("ВИНА", "есть_вина"): "РАСХОЖДЕНИЕ",
    ("СОГЛАСОВАНО-НЕВЕРНО", "расследовать"): "РАСХОЖДЕНИЕ",
    ("ПУСТО", "расследовать"): "УСЛОВИЯ",
    ("РАСХОЖДЕНИЕ", "условия"): "УСЛОВИЯ",
    ("УСЛОВИЯ", "негодны"): "ИСПРАВИТЬ",
    ("УСЛОВИЯ", "чисто"): "ИСПОЛНЕНИЕ",
    ("ИСПОЛНЕНИЕ", "негодно"): "ИСПРАВИТЬ",
    ("ИСПОЛНЕНИЕ", "чисто"): "РЕАЛИЗАЦИЯ",
    ("РЕАЛИЗАЦИЯ", "негодна"): "ИСПРАВИТЬ",
    ("РЕАЛИЗАЦИЯ", "чисто"): "ОЖИДАНИЕ",
    ("ОЖИДАНИЕ", "негодно"): "ИСПРАВИТЬ",
    ("ИСПРАВИТЬ", "вернуться"): "ПРОВЕРКА",
}

FRAME_STATE = {"условия": "УСЛОВИЯ", "исполнение": "ИСПОЛНЕНИЕ",
               "реализация": "РЕАЛИЗАЦИЯ", "ожидание": "ОЖИДАНИЕ"}
FRAME_NEG = {"условия": "негодны", "исполнение": "негодно",
             "реализация": "негодна", "ожидание": "негодно"}


class ProtocolFSM:
    """Переходы только по TABLE. Чужой переход — ProtocolViolation."""

    def __init__(self):
        self.state = "ПРОВЕРКА"
        self.trace = []

    def fire(self, event):
        key = (self.state, event)
        if key not in TABLE:
            raise ProtocolViolation("незаконный переход: %s --%s--> ?" % key)
        self.state = TABLE[key]
        self.trace.append("%s --%s--> %s" % (key[0], event, self.state))
        return self.state

    def verdict(self):
        if self.state == "РАСХОЖДЕНИЕ":
            return "ДЕФЕКТ -> ЗАПЛАТ-6"
        if self.state in VERDICT_STATES:
            return self.state
        return None  # автомат посреди пути — вердикта ещё нет

    def decide(self, sohli, precond, crit, fault=None):
        """Один прогон: двое исполнителей -> развилки -> вердикт."""
        self.fire("прогон")
        if not sohli:
            self.fire("не_сошлись")
            self.fire("есть_вина" if fault else "без_вины")
        else:
            self.fire("сошлись")
            if not precond:
                self.fire("нарушены")
            else:
                self.fire("чисты")
                if crit is None:
                    self.fire("невозможна")
                else:
                    self.fire("возможна")
                    self.fire("пройдена" if crit else "не_пройдена")
        return self.state

    def zaplat6(self, root):
        """Контур ЗАПЛАТ-6: рамки строго по порядку, возврат только с корнем."""
        if root not in FRAME_STATE:
            raise ProtocolViolation("ЗАПЛАТ-6 без корня не возвращается к прогону")
        if self.state in ("СОГЛАСОВАНО-НЕВЕРНО", "ПУСТО"):
            self.fire("расследовать")
        if self.state != "УСЛОВИЯ":
            self.fire("условия")            # из РАСХОЖДЕНИЯ
        for frame in ("условия", "исполнение", "реализация", "ожидание"):
            if self.state != FRAME_STATE[frame]:
                raise ProtocolViolation("рамка не на очереди: ждали %s, стоим в %s"
                                        % (FRAME_STATE[frame], self.state))
            if root == frame:
                self.fire(FRAME_NEG[frame])
                self.fire("вернуться")
                return self.trace
            self.fire("чисто")
        raise ProtocolViolation("ЗАПЛАТ-6 дошёл до конца без корня")  # недостижимо при pre-check


# ---- векторы: 12 случаев прогона + 1 синтетический (для достижимости ДЕФЕКТА) ----

VECTORS = [
    ("2+2",                                    True,  True,  True,  None, "ВЕРИФИЦИРОВАНО"),
    ("НОД(48,18)",                             True,  True,  True,  None, "ВЕРИФИЦИРОВАНО"),
    ("сортировка [3,1,2]",                     True,  True,  True,  None, "ВЕРИФИЦИРОВАНО"),
    ("цепь Маркова, 3 шага",                   True,  True,  True,  None, "ВЕРИФИЦИРОВАНО"),
    ("свет: [вкл;щёлк;щёлк] против [вкл]",     True,  True,  True,  None, "ВЕРИФИЦИРОВАНО"),
    ("арифметика: 2·3+4 против 2·(3+2)",       True,  True,  True,  None, "ВЕРИФИЦИРОВАНО"),
    ("дверь: расстегни—сними, пуговица сломана", True, False, False, None, "ПУСТО"),
    ("хлеб: замесить—выпекать, духовка обесточена", True, False, False, None, "ПУСТО"),
    ("ЗАПЛАТ-6: хлеб, корень в условиях",      True,  False, False, None, "ПУСТО"),
    ("логист. карта: не сошлись без вины",     False, True,  None,  False, "UNKNOWN"),
    ("стакан: закрытое наблюдение",            True,  True,  None,  None, "НЕСВЕРЯЕМО"),
    ("2+2, ожидание из записи: 5",             True,  True,  False, None, "СОГЛАСОВАНО-НЕВЕРНО"),
    ("[вектор автомата] не сошлись по вине",   False, True,  None,  True, "ДЕФЕКТ -> ЗАПЛАТ-6"),
]

ILLEGAL = [
    # (как довести автомат до состояния, какое событие запрещено, почему)
    ("дойти до ПРОВЕРКИ и сослаться минуя прогон", lambda: fresh_and_fire("сошлись"),
     "ПРОВЕРКА --сошлись--> ? (минуя прогон)"),
    ("после вины прыгнуть к исполнению", lambda: fresh_fault().fire("исполнение"),
     "РАСХОЖДЕНИЕ --исполнение--> ? (минуя условия)"),
    ("из условий прыгнуть к реализации", lambda: to_cond().fire("реализация"),
     "УСЛОВИЯ --реализация--> ? (минуя исполнение)"),
    ("из ожидания вернуться минуя исправить", lambda: to_wait().fire("вернуться"),
     "ОЖИДАНИЕ --вернуться--> ? (только через ИСПРАВИТЬ)"),
    ("из терминала ВЕРИФИЦИРОВАНО выйти", lambda: to_verdict(0).fire("прогон"),
     "ВЕРИФИЦИРОВАНО --прогон--> ? (терминальное состояние)"),
    ("из терминала НЕСВЕРЯЕМО расследовать", lambda: to_verdict(9).fire("расследовать"),
     "НЕСВЕРЯЕМО --расследовать--> ? (менять надо прибор, не расследование)"),
]


def fresh_fault():
    m = ProtocolFSM()
    m.decide(False, True, None, fault=True)
    return m


def to_ras():
    return fresh_fault()


def to_cond():
    m = fresh_fault()
    m.fire("условия")
    return m


def to_wait():
    m = fresh_fault()
    m.fire("условия")
    m.fire("чисто")
    m.fire("чисто")
    m.fire("чисто")
    return m


def to_verdict(idx):
    case, sohli, precond, crit, fault, _exp = VECTORS[idx]
    m = ProtocolFSM()
    m.decide(sohli, precond, crit, fault)
    return m


def fresh_and_fire(event):
    m = ProtocolFSM()
    m.fire(event)
    return m


def main():
    print("МЕХАНИЗМ ПРОТОКОЛА: конечный автомат. Проверка:")
    ok, fail = 0, []
    counts = {}
    got_verdicts = set()
    for case, sohli, precond, crit, fault, expected in VECTORS:
        m = ProtocolFSM()
        m.decide(sohli, precond, crit, fault)
        got = m.verdict()
        counts[got] = counts.get(got, 0) + 1
        got_verdicts.add(got)
        if got == expected:
            ok += 1
            print("  OK  %-44s -> %s" % (case, got))
        else:
            fail.append((case, expected, got))
            print("  ПАЛ %-44s ждали %s, автомат дал %s" % (case, expected, got))

    walks = [("хлеб", "ЗАПЛАТ-6: хлеб, корень в условиях", "условия"),
             ("2+2/5", "2+2, ожидание из записи: 5", "ожидание")]
    for tag, src, root in walks:
        idx = [v[0] for v in VECTORS].index(src)
        m = ProtocolFSM()
        m.decide(VECTORS[idx][1], VECTORS[idx][2], VECTORS[idx][3], VECTORS[idx][4])
        m.zaplat6(root)
        if m.state == "ПРОВЕРКА" and len(m.trace) >= 3:
            ok += 1
            print("  OK  контур %s: корень в %s, вернулся на ПРОВЕРКУ (%d переходов)"
                  % (tag, root.upper(), len(m.trace)))
        else:
            fail.append((tag, "ПРОВЕРКА", m.state))

    caught = 0
    for name, fn, label in ILLEGAL:
        try:
            fn()
            print("  ПРОПУСТИЛ незаконный: %s" % label)
            fail.append((name, "ProtocolViolation", "переход прошёл"))
        except ProtocolViolation:
            caught += 1
            print("  OK  пойман: %s" % label)
    n_illegal = len(ILLEGAL)

    # достижимость — из ФАКТИЧЕСКИ полученных вердиктов, не из ожиданий
    need = {"ВЕРИФИЦИРОВАНО", "ПУСТО", "НЕСВЕРЯЕМО", "UNKNOWN",
            "СОГЛАСОВАНО-НЕВЕРНО", "ДЕФЕКТ -> ЗАПЛАТ-6"}
    all_reachable = need <= got_verdicts

    print("-" * 78)
    total = len(VECTORS) + len(walks)
    print("АВТОМАТ ПРОТОКОЛА: векторы+контуры %d/%d; незаконные переходы пойманы %d/%d;"
          % (ok, total, caught, n_illegal))
    print("  счёт векторов: " + ", ".join("%s: %d" % (k, v) for k, v in sorted(counts.items(), key=lambda x: -x[1])))
    print("  все 6 вердиктов достижимы: %s" % ("да" if all_reachable else "НЕТ"))
    print("МЕХАНИЗМ: порядок расследования — таблица переходов, перескочить нельзя;")
    print("  ЗАПЛАТ-6 не возвращается к прогону без корня; терминалы без выхода.")
    if fail or not all_reachable:
        print("ПРОВАЛ: %d" % len(fail))
        return 1
    print("МЕХАНИЗМ ИСПОЛНЕН: 0 провалов.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
