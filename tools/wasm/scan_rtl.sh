#!/usr/bin/env bash
# Reject RTL with build/run code-injection or host file I/O before verilate+emcc.
set -euo pipefail
DIR="${1:?usage: scan_rtl.sh <dir>}"
bad=0
scan(){ if grep -rniE "$2" "$DIR" --include='*.v' --include='*.sv' -l >/dev/null 2>&1; then echo "REJECT: $1"; bad=1; fi; }
scan "Verilator inline C (\$c)"        '\$c[a-z]*\s*\('
scan "DPI import/export"               '(import|export)\s+"DPI'
scan "\$system / shell exec"           '\$system\b'
scan "host file write (\$fopen/\$fwrite/\$fdisplay)" '\$f(open|write|display|printf)\b'
scan "absolute-path \`include"          '`include\s+"/'

# $readmemh/$readmemb is a SUPPORTED memory-init feature (embedded into the wasm FS), but it
# is also a host-file read. Allow it ONLY when the argument is a plain basename (no path
# separators, no '..'): $readmemh("foo.hex", ...). Reject any path/traversal/absolute read
# ($readmemh("/etc/passwd"), "../x", "sub/dir/x") which could exfiltrate runner files.
if grep -rnoE '\$readmem[bh]\s*\(\s*"[^"]+"' "$DIR" --include='*.v' --include='*.sv' >/dev/null 2>&1; then
  while IFS= read -r lit; do
    f="${lit#*\"}"; f="${f%\"}"
    case "$f" in
      */*|*..*|"") echo "REJECT: \$readmem with path/traversal arg: \"$f\" (only a bare basename is allowed)"; bad=1;;
    esac
  done < <(grep -rhoE '\$readmem[bh]\s*\(\s*"[^"]+"' "$DIR" --include='*.v' --include='*.sv' | grep -oE '"[^"]+"')
fi

if [ "$bad" = 1 ]; then echo "RTL rejected by scan_rtl"; exit 1; fi
echo "scan_rtl: OK"
