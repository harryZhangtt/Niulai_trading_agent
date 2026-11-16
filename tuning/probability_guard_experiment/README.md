# Provider-free O2 probability guard experiment

This directory is the complete inert vertical experiment selected by the
2026-11-07 probability-authority architecture escalation. It implements one
stdlib-only authority boundary and leaves all existing validators, runtimes,
schedulers, hooks, and external-effect paths untouched.

## Run

From this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -I -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -I experiment.py --check receipt.json
```

To reproduce the frozen receipt after an intentional source change:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -I experiment.py --write receipt.json
```

The first command runs the comprehensive transition/adversarial suite. The second
reruns the nominal vertical and named falsifier probes, recomputes frozen source
hashes, and requires byte-for-byte equality with `receipt.json`. Temporary probe
state is created only below this directory and is removed automatically.

## Files

- `probability_guard.py`: typed identity/events/receipts and authority state machine.
- `PROTOCOL.md`: frozen hypothesis, transitions, falsifier, effects, and limits.
- `experiment.py`: deterministic nominal/failure runner and receipt generator.
- `tests/test_probability_guard.py`: unit, E2E, process-boundary, and tamper tests.
- `receipt.json`: deterministic public experiment receipt; no secret/outcome bytes.

## Allowed claim

A provider-free experiment can enforce these structural receipt semantics under
its stated process boundary. This does not establish same-user hostile security,
durable production key management, intended-runtime acceptance, probability
quality, transport validity, factor validity, or any investment action.
