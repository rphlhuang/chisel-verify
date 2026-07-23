#!/usr/bin/env bash
# Chisel -> CHIRRTL -> BTOR2 -> btormc bounded model checking, with a
# per-module accounting table that classifies every assertion into one of
# five outcomes. The table is version-stamped because the lowerable LTL
# fragment moves between CIRCT releases.
#
# Usage: formal_check.sh <gate> <glob>...
#   gate  1 = exit non-zero if any module FAILs or ERRORs (use for real
#             designs); 0 = always exit 0 (use for the characterization probe).
#   glob  one or more shell globs of .fir (CHIRRTL) files to check.
#
# Columns:
#   src  AssertProperty(...) calls in the matching .scala (single-Module
#        files only; '-' when the mapping is ambiguous)
#   hw   verif.clocked_assert ops in `firtool --ir-hw` (survived Chisel +
#        FIRRTL folding) -- the robust denominator
#   bad  `bad` instructions in the emitted .btor2 (reached the checker)
#   res  residual: a dangling 2^64-1 operand id => an unlowered LTL op
#        leaked into emission (e.g. |=>, .delay, ###)
#   verdict  PASS (UNSAT) / FAIL (SAT+witness) / ERROR / SKIP
#
# Outcome mapping (the "5 outcomes"):
#   didn't elaborate -> the sbt CHIRRTL emission failed, so no .fir exists here
#   rewritten        -> a |=> was hand-converted to warmedUp(n) && past(n) |-> b
#   folded / vacuous -> src>hw (pre-HW) or hw>bad (in lowering); no `bad`
#   residual LTL op  -> res=yes
#   checked          -> btormc verdict PASS/FAIL
set -u

FIRTOOL="${FIRTOOL:-firtool}"
BTORMC="${BTORMC:-btormc}"
LAYERS="${BTOR2_LAYERS:-Verification,Verification.Assert,Verification.Assume}"
SENTINEL=18446744073709551615

gate="$1"; shift

fail=0
rows=""
details=""

for glob in "$@"; do
  for fir in $glob; do
    [ -e "$fir" ] || continue
    name=$(basename "$fir" .fir)
    dir=$(dirname "$(dirname "$fir")")
    btor="$dir/btor2/$name.btor2"
    hwir="$dir/btor2/$name.hw.mlir"
    mkdir -p "$dir/btor2"

    # Lower to HW (assertion census) and to BTOR2 (checking). firtool exits
    # non-zero on the known leftover-cast crash after writing valid BTOR2, so
    # ignore its status and validate by inspecting the output instead.
    "$FIRTOOL" --ir-hw --enable-layers="$LAYERS" "$fir" > "$hwir"  2>/dev/null || true
    "$FIRTOOL" --btor2 --enable-layers="$LAYERS" "$fir" > "$btor"  2> "$btor.log" || true

    hw=$(grep -c 'verif.clocked_assert' "$hwir" 2>/dev/null); hw=${hw:-0}
    if [ -s "$btor" ]; then bad=$(grep -cE '^[0-9]+ bad ' "$btor"); else bad=0; fi

    # src is only trustworthy when the source file defines exactly one Module.
    scala=$(grep -rlE "class[[:space:]]+$name[^A-Za-z0-9_].*extends[[:space:]]+(Module|RawModule)" src/main/scala 2>/dev/null | head -1)
    if [ -n "$scala" ] && [ "$(grep -cE 'extends[[:space:]]+(Module|RawModule)' "$scala")" = "1" ]; then
      src=$(grep -c 'AssertProperty' "$scala")
    else
      src="-"
    fi

    res="no"
    note=""
    if [ ! -s "$btor" ]; then
      verdict="ERROR"; note="firtool emitted no BTOR2 (see $btor.log)"; fail=1
    elif grep -q "$SENTINEL" "$btor"; then
      res="yes"; verdict="ERROR"; note="unlowered LTL op leaked (|=> / .delay / ### ?)"; fail=1
    elif [ "$bad" -eq 0 ]; then
      verdict="SKIP"; note="no assertion reached btor2"
    else
      wit=$("$BTORMC" "$btor" 2> "$btor.mc.log"); rc=$?
      if [ "$rc" -ne 0 ]; then
        verdict="ERROR"; note="btormc rc=$rc: $(head -1 "$btor.mc.log")"; fail=1
      elif [ -n "$wit" ]; then
        verdict="FAIL"; note="witness below"; fail=1
        details="${details}--- $name btormc counterexample ---"$'\n'"$(printf '%s' "$wit" | sed 's/^/    /')"$'\n'
      else
        verdict="PASS"
      fi
    fi

    # Vacuity accounting (folding is legitimate but worth surfacing).
    vac=""
    if [ "$src" != "-" ] && [ "$src" -gt "$hw" ]; then vac="$((src - hw)) folded pre-HW"; fi
    if [ "$res" = "no" ] && [ "$bad" -lt "$hw" ]; then
      d=$((hw - bad)); [ -n "$vac" ] && vac="$vac, "; vac="${vac}${d} folded in lowering"
    fi
    if [ -n "$vac" ]; then note="${note:+$note; }vacuous: $vac"; fi

    rows="${rows}$(printf '%-16s %3s %3s %3s %5s  %-7s %s' "$name" "$src" "$hw" "$bad" "$res" "$verdict" "$note")"$'\n'
  done
done

CHISEL=$(grep -m1 'chiselVersion' build.sbt | grep -oE '"[0-9][0-9.]*"' | tr -d '"')
FT=$("$FIRTOOL" --version 2>/dev/null | grep -oE 'firtool-[0-9.]+' | head -1)

echo
echo "==================== Formal (BTOR2 BMC) census ===================="
echo "chisel ${CHISEL:-?} | ${FT:-firtool?} | layers=$LAYERS"
echo "-------------------------------------------------------------------"
printf '%-16s %3s %3s %3s %5s  %-7s %s\n' MODULE src hw bad res VERDICT NOTES
printf '%s' "$rows"
echo "-------------------------------------------------------------------"
echo "src=AssertProperty(src)  hw=clocked_assert(--ir-hw)  bad=btor2 assertions"
echo "res=unlowered LTL leaked   PASS=UNSAT  FAIL=SAT+witness  SKIP=vacuous/no bad"
if [ -n "$details" ]; then echo; printf '%s' "$details"; fi
echo

if [ "$gate" = "1" ]; then exit "$fail"; else exit 0; fi
