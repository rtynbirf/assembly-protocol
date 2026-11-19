#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 validate_graph.py BUILD_GRAPH.json
python3 lex_naturae.py claims.json
echo "CANON: STRUCTURE PASS + lex-naturae valid=true"
