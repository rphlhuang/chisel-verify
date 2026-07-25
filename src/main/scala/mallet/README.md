# mallet

> Note: `mallet` was written with Claude Code, but this README is written by rphlhuang. All misspellings, mistakes, and misconceptions are my own.

## Overview

`mallet` is a formal verification workflow for Chisel centered around deriving assertion sets from communication protocol memory map annotations and optional LLM assistance. Heavily inspired by [FLAG: Formal and LLM-assisted SVA Generation for Formal Specifications of On-Chip Communication Protocols](http://arxiv.org/abs/2504.17226), `mallet` takes a formal-first, LLM-refined approach that centers around a custom grammar for all properties. Each `mallet` property has a 3 representations -- \(natural language \(English\), Chisel assertion, abstract syntax tree\) -- for three separate but cohesive purposes:

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