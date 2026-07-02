import random

import cocotb
from cocotb.triggers import Timer

SEED = 42
WIDTH = 8
MAX = 1 << WIDTH
NUM_TESTS = 200


async def check_sum(dut, a, b):
    dut.io_a.value = a
    dut.io_b.value = b
    await Timer(1, unit="ns")
    assert dut.io_s.value == a + b, f"Expected a + b = {a} + {b} = {a + b}, got {dut.io_s.value}."
    
@cocotb.test()
async def test_zero(dut):
    await check_sum(dut, 0, 0)

@cocotb.test()
async def test_max_value(dut):
    await check_sum(dut, (MAX - 1), (MAX - 1))

@cocotb.test()
async def test_fuzz(dut):
    rng = random.Random(SEED)
    for i in range(NUM_TESTS):
        await check_sum(dut, rng.randint(0, (MAX-1)), rng.randint(0, (MAX-1)))
