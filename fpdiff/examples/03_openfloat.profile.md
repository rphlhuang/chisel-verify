# fpdiff compatibility profile: `openfloat_add32_vs_hardfloat`

- format: exp=8 sig=24 (width 32)
- golden: `FPADD_8_24` (rtl/FPADD_8_24.sv), latency 0
- gate:   `FP_add_32_1` (rtl/FP_add_32_1.sv), latency 1
- engine: btormc, kmax 6, total solver time 0.341s

## Verdict: **DIVERGES** — see findings

_Residual: all other input-class pairs safe up to k=6_

## Waivers in force (human-signed)

| id | kind | detail | reason | signed off |
|---|---|---|---|---|
| no-subnormal-inputs | input_class | exclude subnormal on a/b | OpenFloat saturates biased exponents to >=1; subnormal inputs are treated as min-normals (finding #3/#5/#6 exemplars). Unsupported by design; flagged as bug #6 where it corrupts magnitude. | rhuang 2026-07-10 |
| no-nan-inputs | input_class | exclude nan on a/b | OpenFloat has no NaN detection; exponent saturation maps NaN to max-normal magnitude (findings #1/#8/#10/#11). | rhuang 2026-07-10 |
| no-inf-inputs | input_class | exclude inf on a/b | OpenFloat has no infinity handling; same exponent saturation as NaN (findings #2/#7/#9/#12). | rhuang 2026-07-10 |
| no-zero-inputs | input_class | exclude zero on a/b | BUG, not a deviation: 0+0 returns 2.35e-38 (finding #13, min-normal*2 from exponent saturation). Excluded here only to characterize the remaining input space; tracked as open bug. | rhuang 2026-07-10 |
| ulp-1 | output_ulp_tolerance | outputs equal within 1 ulp | OpenFloat rounds by truncation, not RNE; accept 1 ulp on well-conditioned adds. NOTE: does NOT bound cancellation cases -- see open bug: near-cancellation amplifies truncation error without bound (2^19-ulp exemplar found at ulp<=16 sweep). | rhuang 2026-07-10 |
| no-exact-cancellation | input_expr | `!((a[30:0] == b[30:0]) && (a[31] != b[31]))` | BUG, not a deviation: x + (-x) yields a large normal (3.17e+29 at e=0xf9) instead of +0; residual scales with operand exponent. Excluded only to characterize the rest; tracked as open bug. | rhuang 2026-07-10 |
| flush-subnormal-outputs | output_subnormal_flush | output_subnormal_flush | OpenFloat cannot produce subnormal outputs; results that gradually underflow in IEEE are clamped to zero or min-normal of the same sign (finding: -6.02e-36 + 6.02e-36 -> min-normal instead of 9.18e-41). | rhuang 2026-07-10 |

## Findings (one exemplar per divergent input-class pair)

### #1 (normal, normal) — 🐞 BUG
```
a    = 0x702b182e [s=0 e=0xe0 f=0x2b182e] normal ≈ 2.1180467251191588e+29
b    = 0xf900002a [s=1 e=0xf2 f=0x2a] normal ≈ -4.153858284220522e+34
gold = 0xf8fffffe [s=1 e=0xf1 f=0x7ffffe] normal ≈ -4.1538369916518464e+34
gate = 0xf9000000 [s=1 e=0xf2 f=0x0] normal ≈ -4.153837486827862e+34
ulp distance: 2
```
note: unbounded relative error under near-cancellation: alignment truncation has no sticky/guard compensation, so cancelling operands amplify the error (exemplars: 2 ulp at exp-diff 18; 524288 ulp at 1-bit-apart operands; x+(-x) -> 3.17e29 exact-cancellation case). No finite ulp waiver converges; verdict: bug class, not deviation.

---
_Every finding above was produced by btormc on a Yosys-built miter and independently re-simulated with Icarus Verilog before being reported._
