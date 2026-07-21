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

.PHONY: all chiselsim cocotb gen formal formal-gen btor2 clean extraclean help

all: chiselsim cocotb

help:
	@echo "Targets:"
	@echo "  chiselsim  - run the Chisel scalatest suite (sbt test)"
	@echo "  cocotb     - run every cocotb testbench under tests/"
	@echo "  gen        - re-elaborate every Chisel App to SystemVerilog"
	@echo "  formal     - lower every *ChirrtlMain design to BTOR2 and BMC it (btormc)"
	@echo "  clean      - clean generated SV, cocotb sim outputs, sbt target"

chiselsim:
	sbt "$(CHISELSIM_CMD)"

gen:
	sbt "$(foreach m,$(SBT_MAINS),; runMain $(m))"

btor2: formal

# for every *ChirrtlMain, Chisel --> chirrtl (.fir) 
formal-gen:
	sbt "$(foreach m,$(CHIRRTL_MAINS),; runMain $(m))"

# chirrtl (.fir) --> .btor2 --> BMC with btormc
#
# NOTE: firtool errors on a 'builtin.unrealized_conversion_cast' (!ltl.property) crash, 
# so put stderr in .log and ignore firtool's exit status; will investigate later
# if btormc stdout is empty == UNSAT (assertions hold), stdout is 'sat' == violation.
formal: formal-gen
	@fail=0; \
	shopt -s nullglob 2>/dev/null || true; \
	for fir in generated/*/chirrtl/*.fir; do \
	  [ -e "$$fir" ] || continue; \
	  name=$$(basename "$$fir" .fir); \
	  out=$$(dirname $$(dirname "$$fir"))/btor2/$$name.btor2; \
	  mkdir -p "$$(dirname "$$out")"; \
	  $(FIRTOOL) --btor2 --enable-layers=$(BTOR2_LAYERS) "$$fir" > "$$out" 2> "$$out.log" || true; \
	  if [ ! -s "$$out" ]; then \
	    echo "  [ERROR] $$name: firtool produced no BTOR2 (see $$out.log)"; fail=1; continue; \
	  fi; \
	  if ! grep -qE '^[0-9]+ bad ' "$$out"; then \
	    echo "  [SKIP]  $$name: no assertions (no 'bad' state in BTOR2)"; continue; \
	  fi; \
	  wit=$$($(BTORMC) "$$out"); \
	  if [ -n "$$wit" ]; then \
	    echo "  [FAIL]  $$name: assertion violated (btormc witness)"; \
	    echo "$$wit" | sed 's/^/          /'; fail=1; \
	  else \
	    echo "  [PASS]  $$name: all assertions hold (UNSAT)"; \
	  fi; \
	done; \
	exit $$fail

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