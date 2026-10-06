#!/bin/bash
# Smoke-test an installed AIDRIN module. Run after `module load aidrin`, from a directory
# on the filesystem users will use (e.g. $SCRATCH), on a login node and on a compute node.
#
#   hpc/smoke-test.sh
#
# Exits non-zero if any check fails. Ctrl-C during a long run is still a manual check.
set -uo pipefail

work=$(mktemp -d "$PWD/aidrin-smoke.XXXXXX")
trap 'rm -rf "$work"' EXIT
cd "$work"
fails=0

check() {
    local name=$1; shift
    if "$@" > out.txt 2> err.txt; then
        echo "PASS $name"
    else
        echo "FAIL $name"; sed 's/^/    /' err.txt | tail -5
        fails=$((fails + 1))
    fi
}

printf 'zip,age,income,label\n94720,34,50000,a\n94704,45,62000,b\n10001,29,48000,a\n60601,51,70000,b\n94720,34,51000,a\n' > t.csv
printf 'file-path: %s/t.csv\nimage_dir: %s/imgs\nmetrics:\n  - completeness\n' "$work" "$work" > b.yaml

check "list" aidrin list
check "data-quality" aidrin data-quality t.csv
check "k-anonymity" sh -c 'aidrin run k-anonymity t.csv "zip,age" | grep -q k-Value'
check "hipaa-compliance (pgeocode)" sh -c 'aidrin run hipaa-compliance t.csv zip | grep -q VALID_POSTAL_CODE'
check "batch writes images to image_dir" sh -c 'aidrin batch b.yaml && ls imgs/*.png'

# A host PYTHONPATH must not reach the container's Python.
mkdir leak && echo 'raise ImportError("host package leaked into the container")' > leak/numpy.py
check "host PYTHONPATH isolated" env PYTHONPATH="$work/leak" aidrin list

# Only the module's own aidrin-mcp (a -mcp version), not another install found on PATH.
mcp=$(dirname "$(command -v aidrin)")/aidrin-mcp
if [ -x "$mcp" ]; then
    # Handshake, then a tool call that reads the test CSV (the same file access as a real
    # client). A client keeps stdin open, so do the same and stop once the reply (id 2) arrives.
    mcp_roundtrip() {
        coproc MCP { timeout 180 "$mcp"; }
        printf '%s\n' \
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
            '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
            '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"run_data_quality_check","arguments":{"file_path":"'"$work/t.csv"'"}}}' >&"${MCP[1]}"
        while IFS= read -r line <&"${MCP[0]}"; do
            echo "$line" >> mcp.out
            [[ $line == *'"id":2'* ]] && break
        done
        kill "$MCP_PID" 2> /dev/null
        grep -q serverInfo mcp.out && grep '"id":2' mcp.out | grep '"isError":false' | grep -q 'Overall Completeness'
    }
    check "aidrin-mcp handshake + run_data_quality_check over stdio" mcp_roundtrip
fi

echo "startup: $( { TIMEFORMAT=%R; time aidrin list > /dev/null; } 2>&1 )s for 'aidrin list'"
[ "$fails" -eq 0 ] && echo "all checks passed" || echo "$fails check(s) failed"
exit "$fails"
