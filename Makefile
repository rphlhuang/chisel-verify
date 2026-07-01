COCOTBTESTS = Adder Mac
SBT_MAINS = arithmetic.AdderMain arithmetic.MacMain

.PHONY: all chiselsim cocotb gen clean extraclean help

all: chiselsim cocotb

help:
	@echo "Targets:"
	@echo "  chiselsim  - run the Chisel scalatest suite (sbt test)"
	@echo "  cocotb     - run every cocotb testbench under tests/"
	@echo "  gen        - re-elaborate every Chisel App to SystemVerilog"
	@echo "  clean      - clean generated SV, cocotb sim outputs, sbt target"

chiselsim:
	sbt test

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
	rm -rf target project/target project/project build .bsp