# auto-discover every cocotb testbench dir: tests/<package>/<Module>/Makefile
COCOTB_DIRS := $(patsubst %/Makefile,%,$(shell find tests -name Makefile))

SBT_MAINS := $(shell grep -rlE '^[[:space:]]*object [A-Za-z0-9_]+Main extends App' src/main/scala | while read -r f; do \
	pkg=$$(grep -m1 -E '^package ' "$$f" | sed -E 's/^package[[:space:]]+//'); \
	grep -oE '^[[:space:]]*object [A-Za-z0-9_]+Main' "$$f" | sed -E "s/^[[:space:]]*object /$$pkg./"; \
	done | sort -u)

FORCE ?= 0
CHISELSIM_CMD = $(if $(filter 1,$(FORCE)),testOnly *,test)

.PHONY: all chiselsim cocotb gen clean extraclean help

all: chiselsim cocotb

help:
	@echo "Targets:"
	@echo "  chiselsim  - run the Chisel scalatest suite (sbt test)"
	@echo "  cocotb     - run every cocotb testbench under tests/"
	@echo "  gen        - re-elaborate every Chisel App to SystemVerilog"
	@echo "  clean      - clean generated SV, cocotb sim outputs, sbt target"

chiselsim:
	sbt "$(CHISELSIM_CMD)"

gen:
	sbt "$(foreach m,$(SBT_MAINS),; runMain $(m))"

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