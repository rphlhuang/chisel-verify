# chisel-verify

A sandbox for hardware verification of parameterized Chisel modules with ChiselTest and cocotb.
ChiselTest suites under `src/test/scala/`, and cocotb testbenches under `tests/<Module>/`.
Each DUT is elaborated to SystemVerilog in `generated/<pkg>/` via `make gen`.

## Requirements
Install all requirements from `requirements.txt` and submodule python library (note that Python version must be <= 3.13):

- `python3.12 -m venv venv` or any other Python version before it
- `pip3 install -r requirements.txt`
- `pip3 install -e chisel-axi-utils/python`

## Makefile

Run from the repo root:

| Target       | What it does                                                  |
| ------------ | ------------------------------------------------------------- |
| `make chiselsim` | Runs ChiselSim / scalatest suite (`sbt test`).            |
| `make chiselsim FORCE=1`|.    Forces ChiselSim, even if already up to date.  |
| `make gen`       | Elaborates every DUT to `generated/<pkg>/<Module>.sv` in one sbt session. |
| `make cocotb`    | Runs every cocotb testbench under `tests/`.               |
| `make`           | Both `chiseltest` and `cocotb`.                           |
| `make clean`     | Cleans generated SV, cocotb outputs, and `sbt clean`.     |
| `make extraclean`| `make clean`, and ensures all build artifacts clean.      |

Per-DUT, from `tests/<Module>/`:

| Target       | What it does                                                  |
| ------------ | ------------------------------------------------------------- |
| `make gen`   | Force-regenerates just `<Module>.sv`.                         |
| `make clean` | Cleans this test dir's cocotb outputs.                        |
| `make sim`   | Created by cocotb.                                            |

## Testbench Waveforms

- For cocotb tests using Icarus (i.e. `SIM ?= icarus`), results are in <MODULENAME>/sim_build/<MODULENAME>.fst
- For cocotb tests using Verilator, results are in <MODULENAME>/dump.vcd
