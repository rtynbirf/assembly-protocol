#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
КОМПЕНДИУМ СТРАЖА: реальные артефакты дома, байт-в-байт, с пломбами sha256.

Ни одно положение не считается написанным — только исполненным. Улики —
настоящие файлы дома (singulyar, ветка rumu) в момент до и после С188:
  - CHANGELOG_до_С188.md  = git show b61517e:CHANGELOG.md
  - CHANGELOG_С188.md     = git show 9adbc2d:CHANGELOG.md
  - versions_*.json       = то же для data/versions.json
  - сабж_C186/C187.txt    =subjects коммитов, заявлявших «CHANGELOG С184/С185/С186»
  - сабж_C178.txt         =subject латки С178, записи которой не существовало

Перед каждым прогоном пломба улики сверяется с МАНИФЕСТ_ПЛОМБ.json —
подменённая улика останавливает компендиум (закон пломб дома).
"""
import hashlib
import json
import os
import sys

from летопись_fsm import СтражFSM

ДИР = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'страж_фикстуры')

# (имя случая, файлы подмены, заявки, ожидаемый вердикт, дыры, которые ОБЯЗАНЫ быть среди найденных)
СЛУЧАИ = [
    ("дом до С188 (реальный): ходы С178/С184/С185 без записей",
     {'CHANGELOG.md': 'CHANGELOG_до_С188.md', 'data/versions.json': 'versions_до_С188.json'},
     None, "ДРЕЙФ ЕСТЬ", [178, 184, 185]),
    ("заявка С187 «CHANGELOG С184–С187» против реального файла до С188",
     {'CHANGELOG.md': 'CHANGELOG_до_С188.md', 'data/versions.json': 'versions_до_С188.json'},
     None, "ДРЕЙФ ЕСТЬ", [184, 185], 'сабж_C187.txt'),
    ("заявка С186 «CHANGELOG С184/С185/С186» против реального файла до С188",
     {'CHANGELOG.md': 'CHANGELOG_до_С188.md', 'data/versions.json': 'versions_до_С188.json'},
     None, "ДРЕЙФ ЕСТЬ", [184, 185], 'сабж_C186.txt'),
    ("дом после С188 (реальный): С184/С185 зажились, С178 держится",
     {'CHANGELOG.md': 'CHANGELOG_С188.md', 'data/versions.json': 'versions_С188.json'},
     None, "ДРЕЙФ ЕСТЬ", [178]),
]


def пломбы_чисты():
    манифест = json.load(open(os.path.join(ДИР, 'МАНИФЕСТ_ПЛОМБ.json'), encoding='utf-8'))
    чисто = True
    for имя, пломба in sorted(манифест.items()):
        п = os.path.join(ДИР, имя)
        if not os.path.isfile(п):
            print('  ПАЛ улика %s отсутствует' % имя)
            чисто = False
            continue
        факт = hashlib.sha256(open(п, 'rb').read()).hexdigest()
        if факт != пломба:
            print('  ПАЛ пломба %s: манифест %s, файл %s' % (имя, пломба[:12], факт[:12]))
            чисто = False
        else:
            print('  OK  пломба %s (%s…)' % (имя, факт[:12]))
    return чисто


def случай_прогон(файлы, заявки_файл):
    import tempfile, shutil
    дир = tempfile.mkdtemp(prefix='страж_реал_')
    try:
        заявки = None
        for путь_в_репо, имя in файлы.items():
            os.makedirs(os.path.join(дир, os.path.dirname(путь_в_репо)), exist_ok=True)
            src = os.path.join(ДИР, имя)
            dst = os.path.join(дир, путь_в_репо)
            open(dst, 'wb').write(open(src, 'rb').read())
        if заявки_файл:
            сабж = open(os.path.join(ДИР, заявки_файл), encoding='utf-8').read().strip()
            заявки = [('0000000', сабж)]
        m = СтражFSM()
        m.лимит_коммитов = 0
        вер = m.прогон(дир, заявки=заявки)
        числа = sorted({int(d.split(':')[0][1:]) for d in m.дыры
                        if d.startswith('С') and d.split(':')[0][1:].isdigit()})
        return вер, числа, m.дыры
    finally:
        shutil.rmtree(дир, ignore_errors=True)


def main():
    print("КОМПЕНДИУМ СТРАЖА: реальный дом, байт-в-байт.")
    if not пломбы_чисты():
        print("ПЛОМБЫ НАРУШЕНЫ — улики подменены, компендиум остановлен.")
        return 1
    print("-" * 78)
    ok, fail = 0, []
    for случай in СЛУЧАИ:
        имя, файлы, _, ожид, обязаны = случай[:5]
        заявки_файл = случай[5] if len(случай) > 5 else None
        вер, числа, дыры = случай_прогон(файлы, заявки_файл)
        если_есть = set(обязаны) <= set(числа)
        если_вердикт = вер == ожид
        if если_есть and если_вердикт:
            ok += 1
            print("  OK  %s\n      -> %s, дыры: %s" % (имя, вер, числа))
        else:
            fail.append(имя)
            print("  ПАЛ %s\n      -> %s, дыры: %s (обязаны: %s)" % (имя, вер, числа, обязаны))
    print("-" * 78)
    print("КОМПЕНДИУМ: %d/%d реальных случаев — механизм обязан отказать там, где дом врал, и держать там, где дом цел." % (ok, len(СЛУЧАИ)))
    if fail:
        print("ПРОВАЛ: %d" % len(fail))
        return 1
    print("КОМПЕНДИУМ ИСПОЛНЕН: 0 провалов.")
    return 0


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main())
