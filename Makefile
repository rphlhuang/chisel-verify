# auto-discover every cocotb testbench dir: tests/<package>/<Module>/Makefile
COCOTB_DIRS := $(patsubst %/Makefile,%,$(shell find tests -name Makefile))
# each dir's SBT App object, by convention: tests/<package>/<Module> -> <package>.<Module>Main
SBT_MAINS   := $(foreach d,$(COCOTB_DIRS),$(subst /,.,$(patsubst tests/%,%,$(d)))Main)

FORCE ?= 0
CHISELSIM_CMD = $(if $(filter 1,$(FORCE)),testOnly *,test)

.PHONY: all chiseltest cocotb gen clean extraclean help

all: chiselsim cocotb

help:
	@echo "Targets:"
	@echo "  chiseltest  - run the Chisel scalatest suite (sbt test)"
	@echo "  cocotb     - run every cocotb testbench under tests/"
	@echo "  gen        - re-elaborate every Chisel App to SystemVerilog"
	@echo "  clean      - clean generated SV, cocotb sim outputs, sbt target"

chiseltest:
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