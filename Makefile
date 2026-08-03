# auto-discover every cocotb testbench dir: tests/<package>/<Module>/Makefile
COCOTB_DIRS := $(patsubst %/Makefile,%,$(shell find tests -name Makefile))

SBT_MAINS := $(shell grep -rlE '^[[:space:]]*object [A-Za-z0-9_]+Main extends App' src/main/scala | while read -r f; do \
	pkg=$$(grep -m1 -E '^package ' "$$f" | sed -E 's/^package[[:space:]]+//'); \
	grep -oE '^[[:space:]]*object [A-Za-z0-9_]+Main' "$$f" | sed -E "s/^[[:space:]]*object /$$pkg./"; \
	done | sort -u)

# *ChirrtlMain apps emit CHIRRTL (.fir) for the formal flow
CHIRRTL_MAINS := $(shell grep -rlE '^[[:space:]]*object [A-Za-z0-9_]+ChirrtlMain extends App' src/main/scala | while read -r f; do \
	pkg=$$(grep -m1 -E '^package ' "$$f" | sed -E 's/^package[[:space:]]+//'); \
	grep -oE '^[[:space:]]*object [A-Za-z0-9_]+ChirrtlMain' "$$f" | sed -E "s/^[[:space:]]*object /$$pkg./"; \
	done | sort -u)

FORCE ?= 0
CHISELSIM_CMD = $(if $(filter 1,$(FORCE)),testOnly *,test)
FIRTOOL      ?= firtool
BTORMC       ?= btormc
BTOR2_LAYERS ?= Verification,Verification.Assert,Verification.Assume
FORMAL_LOG   ?= generated/formal-summary.log
# btormc is a BOUNDED model checker (its own default is -kmax 20). Make the bound
# explicit so the log records what a result was actually bounded by, and so it can
# be raised per-run:  make mallet KMAX=60
KMAX         ?= 20
# Per-job wall-clock bound (seconds) for the mallet matrix. A timeout is a
# verdict (TIMEOUT), never a hang -- applied uniformly to every engine.
TIMEOUT      ?= 120
MALLET_LOG   ?= generated/mallet-report.log

.PHONY: all chiselsim cocotb gen formal formal-gen btor2 mallet mallet-legacy clean extraclean help

all: chiselsim cocotb

help:
	@echo "Targets:"
	@echo "  chiselsim  - run the Chisel scalatest suite (sbt test)"
	@echo "  cocotb     - run every cocotb testbench under tests/"
	@echo "  gen        - re-elaborate every Chisel App to SystemVerilog"
	@echo "  formal     - lower every *ChirrtlMain design to BTOR2 and BMC it (btormc)"
	@echo "  mallet     - per-property formal report (needs a mallet props sidecar)"
	@echo "               KMAX=<n> sets the btormc bound (default $(KMAX)) for formal+mallet"
	@echo "  clean      - clean generated SV, cocotb sim outputs, sbt target"

chiselsim:
	sbt "$(CHISELSIM_CMD)"

gen:
	sbt "$(foreach m,$(SBT_MAINS),; runMain $(m))"

btor2: formal

# for every *ChirrtlMain, Chisel --> chirrtl (.fir) 
formal-gen:
	sbt "$(foreach m,$(CHIRRTL_MAINS),; runMain $(m))"

# chirrtl (.fir) --> {.hw.mlir, .btor2 (BMC)} --> btormc
# Also assertion lowering stats, with cols:
#   hw   verif.clocked_assert ops in firtool --ir-hw (survived Chisel+FIRRTL)
#   bad  `bad` instructions in the .btor2 (reached btormc)
#   fold vacuous assertions folded away by the compiler (hw-bad)
#   res  residual: dangling 2^64-1 operand id => an unlowered LTL op leaked (|=>)
formal: formal-gen
	@fail=0; nmod=0; t_hw=0; t_bad=0; t_fold=0; t_res=0; t_pass=0; t_fl=0; t_skip=0; t_err=0; \
	tbl=$$(mktemp); det=$$(mktemp); \
	shopt -s nullglob 2>/dev/null || true; \
	for fir in generated/*/chirrtl/*.fir; do \
	  [ -e "$$fir" ] || continue; \
	  nmod=$$((nmod+1)); \
	  name=$$(basename "$$fir" .fir); \
	  base=$$(dirname $$(dirname "$$fir"))/btor2/$$name; \
	  mkdir -p "$$(dirname "$$base")"; \
	  $(FIRTOOL) --ir-hw --enable-layers=$(BTOR2_LAYERS) "$$fir" > "$$base.hw.mlir" 2>/dev/null || true; \
	  $(FIRTOOL) --btor2  --enable-layers=$(BTOR2_LAYERS) "$$fir" > "$$base.btor2"  2> "$$base.btor2.log" || true; \
	  hw=$$(grep -c 'verif.clocked_assert' "$$base.hw.mlir" 2>/dev/null); hw=$${hw:-0}; \
	  if [ -s "$$base.btor2" ]; then bad=$$(grep -cE '^[0-9]+ bad ' "$$base.btor2"); else bad=0; fi; \
	  scala=$$(grep -rlE "class[[:space:]]+$$name[^A-Za-z0-9_].*extends[[:space:]]+(Module|RawModule)" src/main/scala 2>/dev/null | head -1); \
	  if [ -n "$$scala" ] && [ "$$(grep -cE 'extends[[:space:]]+(Module|RawModule)' "$$scala")" = "1" ]; then src=$$(grep -vE '^[[:space:]]*//' "$$scala" | grep -c 'AssertProperty'); else src="-"; fi; \
	  res=no; note=; \
	  if [ ! -s "$$base.btor2" ]; then \
	    verdict=ERROR; note="firtool emitted no BTOR2 (see $$base.btor2.log)"; fail=1; t_err=$$((t_err+1)); \
	  elif grep -q '18446744073709551615' "$$base.btor2"; then \
	    res=yes; verdict=ERROR; note="unlowered LTL op leaked (|=> / .delay / ### ?)"; fail=1; t_err=$$((t_err+1)); t_res=$$((t_res+1)); \
	  elif [ "$$bad" -eq 0 ]; then \
	    verdict=SKIP; note="no assertion reached btor2 (all folded/vacuous)"; t_skip=$$((t_skip+1)); \
	  else \
	    wit=$$($(BTORMC) -kmax $(KMAX) "$$base.btor2" 2> "$$base.mc.log"); rc=$$?; \
	    if [ "$$rc" -ne 0 ]; then verdict=ERROR; note="btormc rc=$$rc: $$(head -1 "$$base.mc.log")"; fail=1; t_err=$$((t_err+1)); \
	    elif [ -n "$$wit" ]; then verdict=FAIL; note="counterexample below"; fail=1; t_fl=$$((t_fl+1)); \
	      { echo "--- $$name btormc counterexample ---"; printf '%s\n' "$$wit" | sed 's/^/    /'; } >> "$$det"; \
	    else verdict=PASS; note=; t_pass=$$((t_pass+1)); fi; \
	  fi; \
	  fold=$$((hw-bad)); { [ "$$res" = yes ] || [ "$$fold" -lt 0 ]; } && fold=0; \
	  vac=; \
	  if [ "$$src" != "-" ] && [ "$$src" -gt "$$hw" ]; then vac="$$((src-hw)) pre-HW"; fi; \
	  if [ "$$res" = no ] && [ "$$fold" -gt 0 ]; then [ -n "$$vac" ] && vac="$$vac, "; vac="$${vac}$$fold in-lowering"; fi; \
	  if [ -n "$$vac" ]; then note="$${note:+$$note; }vacuous: $$vac"; fi; \
	  t_hw=$$((t_hw+hw)); t_bad=$$((t_bad+bad)); t_fold=$$((t_fold+fold)); \
	  printf '  %-16s %3s %3s %4s %5s %5s  %-7s %s\n' "$$name" "$$src" "$$hw" "$$bad" "$$fold" "$$res" "$$verdict" "$$note" >> "$$tbl"; \
	done; \
	CH=$$(grep -m1 chiselVersion build.sbt | grep -oE '"[0-9][0-9.]*"' | tr -d '"'); \
	FT=$$($(FIRTOOL) --version 2>/dev/null | grep -oE 'firtool-[0-9.]+' | head -1); \
	mkdir -p "$$(dirname "$(FORMAL_LOG)")"; \
	{ \
	echo "================ make formal @ $$(date '+%Y-%m-%d %H:%M:%S') ================"; \
	echo "chisel $$CH | $$FT | kmax=$(KMAX) | layers=$(BTOR2_LAYERS)"; \
	echo "---------------------------------------------------------------"; \
	printf '  %-16s %3s %3s %4s %5s %5s  %-7s %s\n' MODULE src hw bad fold res VERDICT NOTES; \
	cat "$$tbl"; \
	echo "---------------------------------------------------------------"; \
	printf '  %d modules | hw=%d bad=%d folded=%d residual=%d | PASS=%d FAIL=%d SKIP=%d ERROR=%d\n' \
	  "$$nmod" "$$t_hw" "$$t_bad" "$$t_fold" "$$t_res" "$$t_pass" "$$t_fl" "$$t_skip" "$$t_err"; \
	echo "  src=AssertProperty(source)  hw=clocked_assert(--ir-hw)  bad=btor2 asserts"; \
	echo "  fold=folded in lowering(hw-bad)  res=unlowered leak"; \
	echo "  PASS = no counterexample within $(KMAX) cycles (bounded), NOT a proof"; \
	if [ -s "$$det" ]; then echo; cat "$$det"; fi; \
	} | tee -a "$(FORMAL_LOG)"; \
	rm -f "$$tbl" "$$det"; \
	echo "  (appended to $(FORMAL_LOG))"; \
	echo; \
	exit $$fail

mallet: formal-gen
	@mkdir -p "$$(dirname "$(MALLET_LOG)")"
	python3 scripts/mallet/run.py --kmax $(KMAX) --timeout $(TIMEOUT) 'generated/*/chirrtl/*.fir'

# old bash script
mallet-legacy: formal-gen
	@mkdir -p "$$(dirname "$(MALLET_LOG)")"; \
	out=$$(mktemp); \
	bash scripts/mallet_report.sh 1 $(KMAX) 'generated/*/chirrtl/*.fir' > "$$out" 2>&1; rc=$$?; \
	tee -a "$(MALLET_LOG)" < "$$out"; rm -f "$$out"; \
	echo "  (appended to $(MALLET_LOG))"; \
	exit $$rc

cocotb:
	@for dir in $(COCOTB_DIRS); do \
		$(MAKE) -C $$dir sim || exit $$?; \
	done

clean:
	@for dir in $(COCOTB_DIRS); do \
		$(MAKE) -C $$dir clean || true; \
	done
	rm -rf generated
	sbt clean

extraclean: clean
	-pkill -f sbt
	rm -rf target project/target project/project build .bsp