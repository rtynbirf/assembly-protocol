#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 validate_graph.py BUILD_GRAPH.json
# lex_naturae.py коды выхода: 0 = valid, 1 = valid + предупреждения графа, 2 = invalid.
# Провал — только 2. Предупреждения печатаются, не роняют канон.
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
set +e
python3 lex_naturae.py claims.json > "$tmp" 2>&1
code=$?
set -e
python3 - "$tmp" "$code" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
if not d.get("valid") or sys.argv[2] == "2":
    print("lex-naturae: INVALID — claims не подтверждены")
    sys.exit(2)
for w in d.get("graph_warnings", []):
    print("WARNING:", w)
print(f"lex-naturae: valid=true, claims={d['claim_count']}, предупреждений графа={len(d['graph_warnings'])} (exit 1 = valid + предупреждения)")
PYEOF
echo "CANON: STRUCTURE PASS + lex-naturae valid=true"
