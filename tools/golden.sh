#!/bin/sh
# tools/golden.sh - golden sha1 lists of the generated files: the generator's no-regression guard.
#
#   sh tools/golden.sh write   [SET [RUST_DIR LUAU_DIR]]   record the sha1 of the current outputs
#   sh tools/golden.sh compare [SET [RUST_DIR LUAU_DIR]]   exit 1 if an output differs from its golden
#
# SET: fake    harness/fake -> harness/src/luau/gen_*.rs + harness/luau/{azalea.d.luau,GEN_REPORT.md}
#      all     = fake (default; RUST_DIR/LUAU_DIR need a single SET: compare any other output dir)
# Lists live in tools/golden/<SET>.sha1 (logical names rust/<file>, luau/<file>); header `# src:` = the label the
# generator wrote ("fake @ <digest>").
#
# `write` refuses to replace a golden that would change unless GOLDEN_FORCE=1 (then log why in tools/golden/ALLOWED_DIFF.md).
# `compare`: always strict.
#   GOLDEN_ALLOW=1: a file listed in ALLOWED_DIFF.md as - `<SET>/<logical name>` may differ (ALLOWED_DIFF.md has no such entry now).
# Env: GOLDEN_FORCE, GOLDEN_ALLOW (above).
set -u
cd "$(dirname "$0")/.." || exit 2
GOLD=tools/golden
ALLOWED=$GOLD/ALLOWED_DIFF.md
FILES="rust/gen_client.rs rust/gen_events.rs rust/gen_types.rs luau/azalea.d.luau luau/GEN_REPORT.md"

sha1() {
    if command -v sha1sum >/dev/null 2>&1; then sha1sum "$1" | cut -d' ' -f1; else shasum -a 1 "$1" | cut -d' ' -f1; fi
}

# phys RDIR LDIR logical-name -> path on disk
phys() {
    case $3 in
        rust/*) echo "$1/${3#rust/}" ;;
        luau/*) echo "$2/${3#luau/}" ;;
    esac
}

# the `src` label the generator wrote into the first line of gen_client.rs
label_of() {
    sed -n '1s/^.* from \(.*\) - DO NOT EDIT.*$/\1/p' "$1/gen_client.rs" 2>/dev/null
}

run_set() { # MODE NAME [RUST_DIR LUAU_DIR]
    mode=$1 name=$2
    case $name in
        fake) rdir=harness/src/luau ldir=harness/luau ;;
        *) echo "golden: unknown set '$name' (fake | all)" >&2; return 2 ;;
    esac
    [ -n "${3:-}" ] && rdir=$3
    [ -n "${4:-}" ] && ldir=$4
    gfile=$GOLD/$name.sha1
    files=$FILES
    nfiles=$(echo $files | wc -w | tr -d " ")
    have=$(label_of "$rdir")

    if [ "$mode" = write ]; then
        for f in $files; do
            [ -f "$(phys "$rdir" "$ldir" "$f")" ] || { echo "golden $name: missing $(phys "$rdir" "$ldir" "$f") (run the generator first)" >&2; return 1; }
        done
        mkdir -p "$GOLD"
        tmp=$(mktemp) || return 2
        {
            echo "# golden sha1 of the generated files, set '$name'. Written by tools/golden.sh (see ALLOWED_DIFF.md)."
            echo "# src: $have"
            for f in $files; do echo "$(sha1 "$(phys "$rdir" "$ldir" "$f")")  $f"; done
        } > "$tmp"
        if [ -f "$gfile" ] && ! cmp -s "$tmp" "$gfile"; then
            if [ "${GOLDEN_FORCE:-0}" != 1 ]; then
                echo "golden $name: REFUSED, $gfile would change (GOLDEN_FORCE=1 to overwrite; log the reason in $ALLOWED)" >&2
                rm -f "$tmp"; return 1
            fi
        fi
        if [ -f "$gfile" ] && cmp -s "$tmp" "$gfile"; then echo "golden $name: unchanged"; rm -f "$tmp"
        else chmod 644 "$tmp"; mv "$tmp" "$gfile"; echo "golden $name: written $gfile ($have)"; fi
        return 0
    fi

    # compare
    [ -f "$gfile" ] || { echo "golden $name: FAIL, no $gfile (run: sh tools/golden.sh write $name)"; return 1; }
    want=$(sed -n 's/^# src: //p' "$gfile")
    bad="" allowed="" n=0 miss=0
    while read -r h f; do
        case $h in '#'*|'') continue ;; esac
        n=$((n + 1))
        p=$(phys "$rdir" "$ldir" "$f")
        if [ -z "$p" ] || [ ! -f "$p" ]; then
            # a file the front end does not write at all may be listed in ALLOWED_DIFF.md too (GOLDEN_ALLOW=1 only)
            if [ "${GOLDEN_ALLOW:-0}" = 1 ] && grep -q "^- \`$name/$f\`" "$ALLOWED" 2>/dev/null; then allowed="$allowed $f(missing)"; continue; fi
            bad="$bad $f(missing)"; miss=1; continue
        fi
        [ "$(sha1 "$p")" = "$h" ] && continue
        if [ "${GOLDEN_ALLOW:-0}" = 1 ] && grep -q "^- \`$name/$f\`" "$ALLOWED" 2>/dev/null; then
            allowed="$allowed $f"
        else
            bad="$bad $f"
        fi
    done < "$gfile"
    if [ "$n" -ne "$nfiles" ]; then echo "golden $name: FAIL, $gfile lists $n files, expected $nfiles"; return 1; fi
    if [ -z "$bad" ]; then
        echo "golden $name: OK ($n files${allowed:+; allowed to differ:$allowed})"
        return 0
    fi
    echo "golden $name: FAIL, differs from $gfile:$bad (generator output changed; if intended: GOLDEN_FORCE=1 sh tools/golden.sh write $name, and log it in $ALLOWED)"
    return 1
}

mode=${1:-}
case $mode in write|compare) ;; *) sed -n '2,/^# Env:/p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;; esac
set=${2:-all}
if [ "$set" = all ]; then
    [ $# -le 2 ] || { echo "golden: RUST_DIR/LUAU_DIR need a single SET" >&2; exit 2; }
    rc=0
    for s in fake; do run_set "$mode" "$s" || rc=1; done
    exit "$rc"
fi
run_set "$mode" "$set" "${3:-}" "${4:-}"
