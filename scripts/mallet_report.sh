#!/usr/bin/env bash
# mallet_report.sh -- per-PROPERTY formal report.
#
# `make formal` is a per-MODULE census (how many assertions survived lowering).
# This is the complementary per-property view: it names every property, says
# where it died, and prints the English sentence alongside the verdict.
#
# Usage: mallet_report.sh <gate> <kmax> <fir-glob>
#   gate  1 = exit non-zero on FAIL/ERROR, 0 = always exit 0
#   kmax  bound passed to btormc (btormc's own default is 20)
#
# The join, and why it is built this way:
#   Property identity is by LABEL, not by position. `AssertProperty(..., label=)`
#   carries a name all the way to the last IR before BTOR2 export, so a property
#   that folds away is simply a label present in the sidecar and absent from the
#   IR -- its neighbours' verdicts do not shift. Position is still used for the
#   IR->btor2 mapping, because nothing between FlattenModules and
#   ConvertHWToBTOR2 can add or drop an assert.
#
#   Note the DUT's own unlabelled assertions (e.g. arithmetic.Mac's) are inlined
#   by FlattenModules and DO emit `bad` lines. So we enumerate EVERY
#   clocked_assert in order and record label-or-"-", rather than grepping only
#   for labels, which would misalign the indices.

set -uo pipefail

FIRTOOL=${FIRTOOL:-firtool}
BTORMC=${BTORMC:-btormc}
BTORSIM=${BTORSIM:-btorsim}
RIC3=${RIC3:-rIC3}
LAYERS=${BTOR2_LAYERS:-Verification,Verification.Assert,Verification.Assume}
SENTINEL=18446744073709551615
# MALLET_VCD=1 (default): on a counterexample, replay the btormc witness through
# btorsim to produce a VCD waveform next to the .btor2. Set 0 to skip.
MALLET_VCD=${MALLET_VCD:-1}
# MALLET_REACH=1 (default): antecedent-reachability (cover) pass -- flags a
# property that only passes because its trigger is never reachable (VACUOUS).
MALLET_REACH=${MALLET_REACH:-1}
# MALLET_PROVE=1 (default): try rIC3 (unbounded IC3/PDR) for a real proof. If the
# whole module is proven, NOCEX becomes PROVEN. Falls back silently to bounded.
MALLET_PROVE=${MALLET_PROVE:-1}
PROVE_TMO=${PROVE_TMO:-60}    # seconds before giving up on the rIC3 proof

# timeout(1) is absent on macOS; alarm() survives exec, so this is portable.
tmo() { perl -e 'alarm shift; exec @ARGV or die' "$@"; }

# Ordered clocked_assert labels (or "-") from a flattened-IR file. Shared by the
# main and reachability passes. Requires the op form so firtool's own error text
# (which contains the string "verif.clocked_assert") is not miscounted.
extract_assert_labels() {
  python3 -c '
import re,sys
op  = re.compile(r"^\s*verif\.clocked_assert %")
lbl = re.compile(r"label \"([A-Za-z0-9_]+)\"")
for line in open(sys.argv[1], errors="replace"):
    if op.search(line):
        L = lbl.search(line); print(L.group(1) if L else "-")
' "$1"
}

GATE=${1:-1}
KMAX=${2:-20}
GLOB=${3:-'generated/*/chirrtl/*.fir'}

fail=0
rows=$(mktemp)
details=$(mktemp)
trap 'rm -f "$rows" "$details"' EXIT

n_pass=0; n_fail=0; n_vac=0; n_err=0; n_unlab=0; n_asm=0; n_proven=0

shopt -s nullglob
for fir in $GLOB; do
  [ -e "$fir" ] || continue
  name=$(basename "$fir" .fir)
  dir=$(dirname "$(dirname "$fir")")
  sidecar="$dir/props/$name.props.json"

  # Only designs that carry a mallet sidecar are in scope for this report.
  [ -f "$sidecar" ] || continue

  base="$dir/btor2/$name"
  mkdir -p "$(dirname "$base")"

  # One firtool run yields both artifacts. The flattened IR goes to stderr via
  # --mlir-print-ir-after; firtool's own exit status is deliberately ignored
  # because it exits non-zero on a benign leftover-cast error after emitting
  # perfectly valid BTOR2.
  $FIRTOOL --btor2 --enable-layers="$LAYERS" "$fir" \
    --mlir-print-ir-after=hw-flatten-modules \
    > "$base.btor2" 2> "$base.final.mlir" || true

  if [ ! -s "$base.btor2" ]; then
    printf '%s\t-\t-\tERROR\tfirtool emitted no BTOR2 (see %s)\n' "$name" "$base.final.mlir" >> "$rows"
    fail=1; n_err=$((n_err+1)); continue
  fi
  if grep -q "$SENTINEL" "$base.btor2"; then
    printf '%s\t-\t-\tERROR\tunlowered LTL op leaked (dangling operand id)\n' "$name" >> "$rows"
    fail=1; n_err=$((n_err+1)); continue
  fi

  # Ordered lists of clocked_assert and clocked_assume labels, in flattened-IR
  # order. An unlabelled op (from the DUT) records "-" so indices stay aligned.
  # Asserts map to `bad` lines; assumes map to `constraint` lines; the two are
  # separate btor2 line-types, so we keep separate ordered lists.
  # python3 rather than sed: macOS ships bash 3.2 (no mapfile) and BSD sed
  # (no inline `t` branch), so neither portable-looking shell idiom works here.
  irlbl=(); asmlbl=()
  while IFS=$'\t' read -r kind l; do
    case "$kind" in assert) irlbl+=("$l");; assume) asmlbl+=("$l");; esac
  done < <(python3 -c '
import re,sys
# Require the operation form "verif.clocked_assert %..." -- firtool writes both
# the IR dump and its error messages to stderr into this same file, and an error
# string like "...used by verif.clocked_assert operations." would otherwise be
# miscounted as an assertion. A real op always has an SSA operand after it.
op  = re.compile(r"^\s*verif\.clocked_(assert|assume) %")
lbl = re.compile(r"label \"([A-Za-z0-9_]+)\"")
for line in open(sys.argv[1], errors="replace"):
    m = op.search(line)
    if m:
        L = lbl.search(line)
        print(m.group(1) + "\t" + (L.group(1) if L else "-"))
' "$base.final.mlir")

  nbad=$(grep -cE '^[0-9]+ bad ' "$base.btor2")
  ncon=$(grep -cE '^[0-9]+ constraint ' "$base.btor2")

  # Invariants: asserts->bad, assumes->constraint. If either fails we refuse to
  # attribute ANY verdict for this module -- a silently mis-attributed
  # counterexample is worse than none.
  if [ "${#irlbl[@]}" -ne "$nbad" ] || [ "${#asmlbl[@]}" -ne "$ncon" ]; then
    printf '%s\t-\t-\tUNMATCHED\t%d assert/%d bad, %d assume/%d constraint\n' \
      "$name" "${#irlbl[@]}" "$nbad" "${#asmlbl[@]}" "$ncon" >> "$rows"
    fail=1; n_err=$((n_err+1)); continue
  fi

  # Run the model checker. --stop-first=0 so ALL violated properties are
  # reported, not just the first.
  wit=$($BTORMC -kmax "$KMAX" --stop-first 0 "$base.btor2" 2> "$base.mc.log")
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '%s\t-\t-\tERROR\tbtormc rc=%d: %s\n' "$name" "$rc" "$(head -1 "$base.mc.log")" >> "$rows"
    fail=1; n_err=$((n_err+1)); continue
  fi

  # Which bad indices were violated. btormc prints "b<i>" lines for SAT props.
  violated=$(printf '%s\n' "$wit" | grep -oE '^b[0-9]+' | tr -d 'b' | sort -un | tr '\n' ' ')

  # --- reachability (cover) pass ------------------------------------------
  # The reach model (a second, cover-enabled elaboration) adds one
  # assert(!antecedent) per property. btormc VIOLATES that cover exactly when the
  # antecedent is reachable. reach_covers collects the COVER_ labels that were
  # violated -> those properties are genuinely exercised; the rest pass vacuously.
  reach_covers=" "; reach_ran=0
  reachfir="$dir/reach/$name.fir"
  if [ "$MALLET_REACH" = 1 ] && [ -f "$reachfir" ]; then
    rbase="$base.reach"
    $FIRTOOL --btor2 --enable-layers="$LAYERS" "$reachfir" \
      --mlir-print-ir-after=hw-flatten-modules > "$rbase.btor2" 2> "$rbase.mlir" || true
    if [ -s "$rbase.btor2" ] && ! grep -q "$SENTINEL" "$rbase.btor2"; then
      rlbl=(); while IFS= read -r l; do rlbl+=("$l"); done < <(extract_assert_labels "$rbase.mlir")
      rwit=$($BTORMC -kmax "$KMAX" --stop-first 0 "$rbase.btor2" 2>/dev/null)
      for bi in $(printf '%s\n' "$rwit" | grep -oE '^b[0-9]+' | tr -d 'b' | sort -un); do
        lab="${rlbl[$bi]:-}"
        case "$lab" in COVER_*) reach_covers="$reach_covers$lab ";; esac
      done
      reach_ran=1
    fi
  fi

  # --- unbounded proof pass (rIC3) ----------------------------------------
  # rIC3 on the COVER-FREE main model. UNSAT => every assertion holds for all
  # time (a real proof, not a bound), so NOCEX can be upgraded to PROVEN. SAT or
  # timeout => leave btormc's bounded verdicts as they are.
  proven=0
  if [ "$MALLET_PROVE" = 1 ] && command -v "$RIC3" >/dev/null 2>&1; then
    ric3out=$(tmo "$PROVE_TMO" "$RIC3" "$base.btor2" 2>/dev/null)
    printf '%s\n' "$ric3out" | grep -qx 'UNSAT' && proven=1
  fi

  # Turn the counterexample into a waveform. btorsim replays the witness against
  # the SAME btor2 model and dumps a VCD -- no Verilator, no SystemVerilog, no
  # signal-name remapping, because it stays in the btor2 world the check ran in.
  # --hierarchical-symbols makes `dut/state` a nested scope in the VCD.
  vcd=""
  if [ -n "$violated" ] && [ "$MALLET_VCD" = 1 ] && command -v "$BTORSIM" >/dev/null 2>&1; then
    printf '%s\n' "$wit" > "$base.cex.wit"
    if $BTORSIM "$base.btor2" "$base.cex.wit" --vcd "$base.cex.vcd" \
         --hierarchical-symbols >/dev/null 2>"$base.btorsim.log"; then
      vcd="$base.cex.vcd"
    fi
  fi

  # Walk the sidecar and emit one row per declared property.
  # Row columns: module, property, past, reach, verdict, english
  while IFS=$'\t' read -r label kind cover pname past nl; do
    if [ "$kind" = "assume" ]; then
      # An assumption is a constraint on the environment, not an obligation on
      # the design -- btormc uses it to prune traces, it never yields a
      # counterexample. Present in the IR -> ASSUMED; absent -> the compiler
      # folded it (a vacuous assumption, i.e. always true, constrains nothing).
      found=0
      for i in "${!asmlbl[@]}"; do [ "${asmlbl[$i]}" = "$label" ] && { found=1; break; }; done
      if [ "$found" = 1 ]; then
        printf '%s\t%s\t%s\t-\tASSUMED\t%s\n' "$name" "$pname" "$past" "$nl" >> "$rows"
        n_asm=$((n_asm+1))
      else
        printf '%s\t%s\t%s\t-\tVACUOUS\t%s\n' "$name" "$pname" "$past" "$nl" >> "$rows"
        n_vac=$((n_vac+1))
      fi
      continue
    fi

    # assert-kind: position among clocked_assert maps to the bad index.
    pos=-1
    for i in "${!irlbl[@]}"; do
      if [ "${irlbl[$i]}" = "$label" ]; then pos=$i; break; fi
    done

    # Antecedent reachability from the cover pass: yes / no / ? (unknown).
    reach="?"
    if [ "$cover" != "-" ] && [ "$reach_ran" = 1 ]; then
      case "$reach_covers" in *" $cover "*) reach="yes";; *) reach="no";; esac
    fi

    if [ "$pos" -lt 0 ]; then
      # Never reached the model checker: the compiler folded it to a constant.
      # SYNTACTIC vacuity (e.g. x === x).
      printf '%s\t%s\t%s\t-\tVACUOUS\t%s\n' "$name" "$pname" "$past" "$nl" >> "$rows"
      n_vac=$((n_vac+1))
    elif printf '%s' " $violated " | grep -q " $pos "; then
      # Violated: the antecedent was reachable (that is how it failed), so reach=yes.
      printf '%s\t%s\t%s\tyes\tFAIL\t%s\n' "$name" "$pname" "$past" "$nl" >> "$rows"
      fail=1; n_fail=$((n_fail+1))
      {
        echo "--- $name / $pname  (bad index $pos, label $label) ---"
        echo "    $nl"
        [ -n "$vcd" ] && echo "    waveform: $vcd  (open in GTKWave / Surfer)"
        printf '%s\n' "$wit" | sed 's/^/    /'
      } >> "$details"
    elif [ "$reach" = "no" ]; then
      # SEMANTIC vacuity: the property held only because its antecedent is never
      # reachable on this design. The pass proves nothing. This is the case the
      # reachability (cover) pass exists to surface.
      printf '%s\t%s\t%s\tno\tVACUOUS\t%s\n' "$name" "$pname" "$past" "$nl" >> "$rows"
      n_vac=$((n_vac+1))
    elif [ "$proven" = 1 ]; then
      # rIC3 proved the whole module unboundedly -- a real proof, not a bound.
      printf '%s\t%s\t%s\t%s\tPROVEN\t%s\n' "$name" "$pname" "$past" "$reach" "$nl" >> "$rows"
      n_proven=$((n_proven+1))
    else
      printf '%s\t%s\t%s\t%s\tNOCEX\t%s\n' "$name" "$pname" "$past" "$reach" "$nl" >> "$rows"
      n_pass=$((n_pass+1))
    fi
  done < <(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
for p in d["props"]:
    c=p.get("coverLabel") or "-"   # "-" not "" -- bash read collapses empty tab fields
    print("\t".join([p["label"],p.get("kind","assert"),c,p["name"],str(p["maxPast"]),p["nl"]]))
' "$sidecar")

  # Unlabelled asserts inlined from the DUT -- counted, not attributed.
  u=0
  for i in "${irlbl[@]:-}"; do [ "$i" = "-" ] && u=$((u+1)); done
  n_unlab=$((n_unlab + u))
done

CH=$(grep -m1 chiselVersion build.sbt | grep -oE '"[0-9][0-9.]*"' | tr -d '"')
FT=$($FIRTOOL --version 2>/dev/null | grep -oE 'firtool-[0-9.]+' | head -1)
MC=$($BTORMC --version 2>/dev/null | head -1)

RIC3V=$(command -v "$RIC3" >/dev/null 2>&1 && echo "$RIC3" || echo "off")
echo "================ mallet report @ $(date '+%Y-%m-%d %H:%M:%S') ================"
echo "chisel $CH | $FT | btormc $MC | rIC3=$RIC3V | kmax=$KMAX | layers=$LAYERS"
echo "-------------------------------------------------------------------------------"
printf '  %-20s %-22s %4s %5s  %-7s %s\n' MODULE PROPERTY PAST REACH VERDICT ENGLISH
while IFS=$'\t' read -r m p past reach v nl; do
  printf '  %-20s %-22s %4s %5s  %-7s %s\n' "$m" "$p" "$past" "$reach" "$v" "$nl"
done < "$rows"
echo "-------------------------------------------------------------------------------"
printf '  PROVEN=%d NOCEX=%d FAIL=%d VACUOUS=%d ASSUMED=%d ERROR=%d | %d DUT asserts\n' \
  "$n_proven" "$n_pass" "$n_fail" "$n_vac" "$n_asm" "$n_err" "$n_unlab"
echo "  PROVEN  = holds for ALL time (rIC3, unbounded). A real proof."
echo "  NOCEX   = no counterexample within $KMAX cycles (btormc, bounded). Not a proof."
echo "  VACUOUS = proves nothing: folded away, OR (REACH=no) antecedent unreachable."
echo "  REACH   = is the antecedent reachable? yes = genuinely exercised; no = vacuous."
echo "  ASSUMED = an environment constraint for the DUT (rely-guarantee)."
if [ -s "$details" ]; then echo; cat "$details"; fi
echo

[ "$GATE" = "1" ] && exit $fail
exit 0
