# chisel-verify

A sandbox for hardware verification of parameterized Chisel modules with ChiselTest and cocotb.
ChiselTest suites under `src/test/scala/`, and cocotb testbenches under `tests/<Module>/`.
Each DUT is elaborated to SystemVerilog in `generated/<pkg>/` via `sbt runMain`.

## Makefile

Run from the repo root:

| Target       | What it does                                                  |
| ------------ | ------------------------------------------------------------- |
| `make chiselsim` | Runs the ChiselTest / scalatest suite (`sbt test`).       |
| `make gen`       | Elaborates every DUT to `generated/<pkg>/<Module>.sv` in one sbt session. |
| `make cocotb`    | Runs every cocotb testbench under `tests/`.               |
| `make`           | Both `chiselsim` and `cocotb`.                            |
| `make clean`     | Cleans generated SV, cocotb outputs, and `sbt clean`.     |
| `make extraclean`| `make clean`, and ensures all build artifacts clean.      |

Per-DUT, from `tests/<Module>/`:

| Target       | What it does                                                  |
| ------------ | ------------------------------------------------------------- |
| `make gen`   | Force-regenerates just `<Module>.sv`.                         |
| `make clean` | Cleans this test dir's cocotb outputs.                        |
| `make sim`   | Created by cocotb.                                            |
