COCOTBTESTS = Adder Mac
SBT_MAINS = arithmetic.AdderMain arithmetic.MacMain

FORCE ?= 0
CHISELSIM_CMD = $(if $(filter 1,$(FORCE)),testOnly *,test)

.PHONY: all chtest cocotb gen clean extraclean help

all: chiselsim cocotb

help:
	@echo "Targets:"
	@echo "  chiselsim  - run the Chisel scalatest suite (sbt test)"
	@echo "  cocotb     - run every cocotb testbench under tests/"
	@echo "  gen        - re-elaborate every Chisel App to SystemVerilog"
	@echo "  clean      - clean generated SV, cocotb sim outputs, sbt target"

chtest:
	sbt "$(CHISELSIM_CMD)"

gen:
	sbt "$(foreach m,$(SBT_MAINS),; runMain $(m))"

cocotb:
	@for tt in $(COCOTBTESTS); do \
		$(MAKE) -C tests/$$tt || exit $$?; \
	done

clean:
	@for tt in $(COCOTBTESTS); do \
		$(MAKE) -C tests/$$tt clean || true; \
	done
	rm -rf generated
	sbt clean

extraclean: clean
	-pkill -f sbt
	rm -rf target project/target project/project build .bsp