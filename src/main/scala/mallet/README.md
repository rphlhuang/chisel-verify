# mallet

> Note: `mallet` was written with Claude Code assistance, but this README is written by rphlhuang. All misspellings, mistakes, and misconceptions are my own.

## Overview
`mallet` is a fully open-source formal verification harness for the Chisel stack that issues correctness properties derived from AXI memory map annotations to multiple independent model-checking engines, producing an adjudication matrix to support agile verification of scientific-computing accelerators. 
Since properties should be rendered from the design, io/spec/property drift is caught compile-time, crucial for building agentic loops.
Inspired by [FLAG: Formal and LLM-assisted SVA Generation for Formal Specifications of On-Chip Communication Protocols](http://arxiv.org/abs/2504.17226), `mallet` takes a formal-first approach that centers around a custom grammar for all properties. Each `mallet` property has a 3 representations -- (natural language (English), Chisel assertion, abstract syntax tree) -- for three separate but cohesive purposes:

1) Natural language: for human and LLM interpretability. Studies show that [LLMs have poor temporal reasoning skills](http://arxiv.org/abs/2406.09170) so natural language improves the LLM's understanding of the assertion set. Natural language also helps the human engineer interpret the formal engine's (btormc's) verdict, as it becomes divorced from the original Chisel syntax as it is lowered down from Chisel assertions to btor2.
2) Chisel assertions: what gets written to the Chisel file, alongside the your Chisel code. By tying Chisel assertions to the other two representations, we prevent the LLM from generating invalid syntax and assertion types that are supported by chisel3.ltl but unsupported by CIRCT.
3) Abstract syntax tree (AST): for pre-SMT solving simplifications. By representing the property using `mallet`'s custom algebraic data types, we can SAT solve to remove trivial, vacuous, and contradictory properties from the set pre-btor2-lowering.

## Docs

### Basics: `mallet`'s Algebraic Data Types (ADTs)

`mallet` properties have three stacked levels of ADTs. All `properties` are made of `boolean` expressions, and all `boolean` expressions consist of the composition of `word` types.

| Level | Type | Cases | Represents... |
| ----- | ---- | ----- | ------------- |
| word | `Term` | Sig, Slice, Lit | a bus value: a signal, a bit-slice, a constant |
| boolean | `Expr` | B, Not, And, Or, Cmp, Past, True/False | a 1-bit condition |
| properties | `Prop` | Implies, Always | a whole assertion |

`Term` and `Expr` are explicitly different for type safety; `Not(Sig(awaddr))` on a 32-bit AXI-Lite bus wouldn't make sense and causes compile errors.

### Basics: Protocol Contracts

To facilitate formal verification for a multiplicity of common communication protocols, `mallet` ships protocol contracts (see `src/main/scala/mallet/contract`) to automatically verify Chisel modules that inherit from certain constrained interfaces. Currently supported protocols are:

- AMBA AXI-Lite, 32-bit <-- axi.HasAxiLite32IO from `chisel-axi-utils`

### Basics: Adjudication

A `mallet` run queues up threads for each {property, backend engine} combination, and reports them in an *adjudication matrix*. After all combinations have executed or the timeout (default: 120s) is reached, the matrix is populated with the results from each backend. These results combine to compose a verdict for each property, which can take one of the following values:

- PROVEN   = An unbounded proof was found.
- NOCEX    = No counterexample was found within `kmax` cycles. Bounded, not a proof.
- REFUTED  = A counterexample exists, and all engines agree.
- CONFLICT = A counterexample exists, but one one enginer found a CEX another ruled out.
- VACUOUS  = Proves nothing, so was simplified away or the antecedent of the implication was unreachable.

In addition, assumptions (`AssumeProperty()` in Chisel) are labelled with ASSUMED.