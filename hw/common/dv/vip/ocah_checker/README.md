# ocah_checker — Common Checker Evidence

SPDX-License-Identifier: Apache-2.0

`ocah_checker` supplies protocol-neutral comparison evidence, required-check
tracking, timeout semantics, and finalization for OCAH tests. Protocol
legality remains in each `ocah_<protocol>_vip` checker. The cocotb layer is
`cocotb/checker.py` (`OcahChecker`); the SV-UVM mirror is
`uvm/ocah_checker_uvm_pkg.sv` (class `ocah_checker`), which every
`ocah_<protocol>_vip` UVM checker extends — the per-protocol classes carry
only their protocol checks and identity, never a copy of the evidence
mechanics.

## Public API

```python
from ocah_checker import OcahChecker

checker = OcahChecker(
    name="example",
    required_ids={"CHK-DATA", "CHK-NONVAC"},
)

checker.expect_equal(
    "CHK-DATA",
    observed=read_data,
    expected=expected_data,
    context="addr=0x1000",
)
checker.expect_true(
    "CHK-NONVAC",
    transaction_count > 0,
    context=f"transactions={transaction_count}",
)
checker.finalize()
```

`expect_equal()` and `expect_true()` return `True` for passing checks. A failed
comparison is retained before `OcahCheckerError` is raised in the default
fail-fast mode. Set `fail_fast=False` for monitor/scoreboard aggregation, then
call `finalize()` after stimulus.

`finalize()` fails when:

- no checks ran;
- any retained finding failed; or
- any configured `required_ids` were never observed.

`clear()` resets retained evidence and required-ID observations.

## Evidence grammar

Checker IDs use stable uppercase `CHK-<ID>` names:

```text
CHK-DATA PASS expected=0xa5 observed=0xa5 context=addr=0x1000
CHK-RESP FAIL expected=0x0 observed=0x3 context=write
CHECKER_SUMMARY name=example checks=2 passed=1 failed=1 missing=0
```

Each line must identify the independent expectation, DUT observation, and
useful context such as address, response, field, loop, or seed. Do not emit PASS
before the comparison succeeds.

A nonzero generic check count prevents an empty checker from passing, but it is
not domain non-vacuity. Tests must provide a meaningful `CHK-NONVAC` check that
proves the exercised DUT path could not pass through default, idle, stub, or
unobserved behavior.

## Timeout contract

Transaction timeout fails by default:

```python
checker.expect_not_timed_out(
    "CHK-COMPLETION",
    timed_out=result.timed_out,
    timeout_ns=1000,
)
```

Only a VPLAN that explicitly expects bounded non-completion may use:

```python
checker.expect_timeout(
    "CHK-EXPECTED-TIMEOUT",
    timed_out=result.timed_out,
    timeout_ns=200,
    context="documented unmapped window",
)
```

The expected-timeout evidence records the bound. `allow_timeout=True` in a BFM
only makes the timeout inspectable; it does not grant PASS.

A runner stage timeout is different: it is always `TIMEOUT`, exit code 124, and
cannot be converted into an expected checker PASS.

## Monitor and protocol-checker integration

OCAH monitors log and catch callback exceptions so one subscriber cannot kill
monitor sampling. Therefore an attached protocol checker must retain findings
before raising, and the owning test or scoreboard must call its finalization
method after traffic.

The ownership boundary is:

- `ocah_checker`: exact evidence, counters, required IDs, timeout checks, and
  finalization;
- `ocah_<protocol>_vip`: protocol item legality and structural checks;
- DUT `cocotb/assertions/`: pure DUT-specific invariants;
- DUT `cocotb/env/`: lifecycle-owning scoreboards, predictors, and reference
  models;
- tests/sequences: expected values, configuration, and one mandatory
  finalization call.

## SV-UVM layer

`uvm/ocah_checker_uvm_pkg.sv` carries the same grammar and policy for SV-UVM:
`expect_equal`/`expect_true`/`expect_equal_words` route PASS evidence through
`uvm_info` (`UVM_LOW`) and FAIL evidence through `uvm_error` so the `uvm-log`
parse policy fails the run, and `finalize()` emits the `CHECKER_SUMMARY` once,
erroring on zero checks (when required) and on missing `required_ids`.
Dependent VIP manifests list the package ahead of their own; the flow's
source-list expansion dedup-merges the entry when several VIPs are consumed
together.

## Runner authority

`CHK-*` and `CHECKER_SUMMARY` lines are durable, auditable log evidence. They do
not replace the runner result contract. For cocotb flows, passing
`results.xml` remains the test authority and native schema-1 `result.json`
remains the run authority. Missing or failing structured results cannot be
overridden by positive checker text.

See `cocotb/examples/example_checker.py` for a runnable plain-Python example.
