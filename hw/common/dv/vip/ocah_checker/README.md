# ocah_checker — Common Checker Evidence

SPDX-License-Identifier: Apache-2.0

`ocah_checker` supplies protocol-neutral comparison evidence, required-check
tracking, timeout and status semantics, and finalization for OCAH tests.
Protocol legality remains in each `ocah_<protocol>_vip` checker. The cocotb
layer is `cocotb/checker.py` (`OcahChecker`); the SV-UVM twin is
`uvm/ocah_checker_uvm_pkg.sv` (class `ocah_checker`), which every
`ocah_<protocol>_vip` UVM checker extends. The per-protocol classes carry only
their protocol checks and identity, never a copy of the evidence mechanics.
The normative contract is `hw/common/dv/docs/vip-checker-model.adoc`.

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

- no checks ran, unless the owner declares the stream idle with
  `finalize(require_checks=False)`;
- any retained finding failed;
- any configured `required_ids` were never observed; or
- it is called a second time (one checker reports one summary).

`clear()` resets retained evidence, required-ID observations, and the
finalized state; the required-ID configuration stays.

| Member | Contract |
|---|---|
| `expect_equal(id, observed, expected, context="")` | Exact equality, observed first |
| `expect_true(id, condition, context="")` | Boolean evidence |
| `expect_not_timed_out(id, *, timed_out, timeout_ns, context="")` | Completion under a declared bound; the bound rides in the context |
| `expect_timeout(id, *, timed_out, timeout_ns, context="")` | An explicitly expected, bounded timeout |
| `expect_rw1c(id, *, before, after, mask, context="")` | Write-one-to-clear status: the mask bits were set before the clearing write and are clear after it |
| `expect_sticky(id, *, first, second, mask, context="")` | Sticky status: the mask bits read set twice with no clearing write between |
| `expect_pulse(id, *, asserted, deasserted, context="")` | Pulse-only event: asserted for the event and deasserted after completion |
| `finalize(*, require_checks=True)` | One summary; raises on the defects above |
| `clear()`, `finalized`, `findings`, `failures`, `missing_ids`, `check_count`, `pass_count` | State and retained evidence |

## Evidence grammar

Checker IDs use stable uppercase `CHK-<ID>` names matching
`CHK-[A-Z0-9][A-Z0-9_-]*`; an invalid ID is a configuration defect
(`ValueError` in cocotb, `uvm_fatal` in SV-UVM):

```text
CHK-DATA PASS expected=0xa5 observed=0xa5 context=addr=0x1000
CHK-RESP FAIL expected=0x0 observed=0x3 context=write
CHECKER_SUMMARY name=example checks=2 passed=1 failed=1 missing=0
```

Each line must identify the independent expectation, DUT observation, and
useful context such as address, response, field, loop, or seed. Do not emit PASS
before the comparison succeeds. Integers render in hexadecimal, booleans as
`true`/`false`, bytes as a hexadecimal payload, other values by `repr()`; an
empty context renders as `-`.

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

## Reset, interrupt, and status helpers

Three helpers judge status behavior against its register description and name
the real source CSR or signal in the identifier or the context:

```python
before = await csr.read(STATUS)
await csr.write(STATUS, DONE)
after = await csr.read(STATUS)
checker.expect_rw1c("CHK-DONE-RW1C", before=before, after=after, mask=DONE, context="csr=STATUS.DONE")
checker.expect_sticky("CHK-ERR-STICKY", first=first_read, second=second_read, mask=ERR)
checker.expect_pulse("CHK-IRQ-PULSE", asserted=irq_seen, deasserted=irq_released, context="signal=irq_o")
```

A `W1C`/`RW1C` field is sticky and must clear by write; a live-condition
status bit is judged by its edges; an interrupt output follows the interrupt
controller's contract while the source register behind it is judged
separately. An aggregate interrupt wire is never recorded in place of the
status register that drives it.

## Monitor and protocol-checker integration

OCAH monitors re-raise a checker verdict (`AssertionError`, which includes
`OcahCheckerError`) from a subscriber callback and count any other subscriber
exception in `callback_errors`, exposed through `get_statistics()`, so one
defective subscriber cannot kill sampling and cannot pass silently either:
the owning scoreboard or harness records the count against zero at drain
(`CHK-AXI-DRAIN`, `CHK-<PROTO>-MON-CALLBACKS`). An attached protocol checker
retains its findings before raising, and the owning test or scoreboard calls
its finalization method after traffic.

The ownership boundary is:

- `ocah_checker`: exact evidence, counters, required IDs, timeout and status
  checks, and finalization;
- `ocah_<protocol>_vip`: protocol item legality and structural checks;
- DUT `cocotb/assertions/`: pure DUT-specific invariants;
- DUT `cocotb/env/`: lifecycle-owning scoreboards, predictors, and reference
  models;
- tests/sequences: expected values, configuration, and one mandatory
  finalization call.

## SV-UVM layer

`uvm/ocah_checker_uvm_pkg.sv` carries the same grammar and policy for SV-UVM:
`expect_equal`/`expect_true`/`expect_equal_words`, the timeout helpers
`expect_not_timed_out`/`expect_timeout`, and the status helpers
`expect_rw1c`/`expect_sticky`/`expect_pulse` route PASS evidence through
`uvm_info` (`UVM_LOW`) and FAIL evidence through `uvm_error` so the `uvm-log`
parse policy fails the run. `finalize(require_checks = 1)` emits the
`CHECKER_SUMMARY` once and errors on zero checks (unless the owner passes `0`
to declare the stream idle), on missing `required_ids`, and on a second call.
Dependent VIP manifests list the package ahead of their own; the flow's
source-list expansion dedup-merges the entry when several VIPs are consumed
together.

## Runner authority

`CHK-*` and `CHECKER_SUMMARY` lines are durable, auditable log evidence. They do
not replace the runner result contract. For cocotb flows, passing
`results.xml` remains the test authority and native schema-1 `result.json`
remains the run authority. Missing or failing structured results cannot be
overridden by positive checker text.

## Validation

The core proves itself without a simulator; the selftest exercises every rule
positively and then makes each one fail:

```bash
uv run --locked --group dv python hw/common/dv/vip/ocah_checker/cocotb/examples/example_checker.py
uv run --locked --group dv python hw/common/dv/vip/ocah_checker/cocotb/examples/example_checker_selftest.py
```

On a simulator, `OCAH_CHECKER_SELFTEST_NEGATIVE` arms a required identifier no
scenario records on the JTAG harness, so finalization must report
`missing=1` in both realizations; each command exits non-zero:

```bash
OCAH_CHECKER_SELFTEST_NEGATIVE=1 python3 tools/dv/run_dv.py --dut ocah_jtag_vip --items ocah_jtag_idcode_test --tool verilator
python3 tools/dv/run_dv.py --dut ocah_jtag_vip --framework uvm --items ocah_jtag_idcode_test \
    --skip-unimplemented --plusarg=+OCAH_CHECKER_SELFTEST_NEGATIVE
```

The per-family must-fail entry points are listed in the contract chapter.
