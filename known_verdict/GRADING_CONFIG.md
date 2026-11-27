# Known-Verdict Grading Configuration

## Symbolic Environment

| Component | Frozen value |
|---|---|
| GoeMaxima image | `mathinstitut/goemaxima:2026042200-latest` |
| Image digest | `sha256:70e3c8389bb8f14d7cb6eb2ae36f3cc989d96a85a09c80411e4943ce51f657e6` |
| stackmaxima | `2026042200` (STACK 4.12.0, Maxima 5.44.0) |
| SymPy | 1.14.0 |
| Math-Verify | 0.9.0 |

The suite calls GoeMaxima over HTTP. A typical local endpoint is
`http://127.0.0.1:18080/maxima`.

## Answer Tests

- Algebraic and matrix pairs use `ATAlgEquiv`.
- Antiderivative probes use `ATInt`.
- Unit pairs use `ATUnits` after `stack_unit_si_declare(true)`.
- The comparison preserves answer types; a one-by-one matrix is not coerced
  to a scalar.

The suite's equivalent verdicts use the same rational-simplification notion as
`ATAlgEquiv`. In particular, removable singularities are ignored when the
difference simplifies to zero. The five diagnostic probes are unscored because
their expected behavior depends on answer-test options or type conventions.

## Scoring

For equivalent pairs, an explicit equivalence verdict counts as accepted; a
negative, unparsed, timed-out, or error outcome counts as missed. For
non-equivalent pairs, only decisive outcomes enter the denominator. Errors and
unsupported inputs are reported separately and never count as correct
rejections.
