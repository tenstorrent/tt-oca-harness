# OCAH OSS shared DV (hw/common/dv)

Shared DV collateral for the OCAH tree: protocol VIP (`vip/ocah_<proto>_vip/`), shared
configs (`configs/`), `sva/`, `shims/`, and shared firmware (`fw/`).

See the [Shared Design Verification and VIP Guide](docs/index.adoc) for the
detailed architecture, package catalog, deployment, checker/reference-model
contracts, and contributor workflow.

Install the VIP packages from the repository root with:

```bash
python3 -m pip install -e hw/common/dv
```

Use Python 3.11, 3.12, or 3.13 for this package. Python 3.14 is not part of
the current support contract because the selected cocotb release rejects Python
versions newer than 3.13.

Each VIP package is hierarchical:

```text
vip/ocah_<proto>_vip/
  __init__.py      # thin shim re-exporting the stable public API from cocotb/
  README.md
  interface/       # SV interfaces shared by the cocotb and UVM flows (where present)
  cocotb/          # all cocotb (Python) VIP code, incl. examples/
  uvm/             # SV-UVM agent collateral (added as it lands)
  cov/             # framework-neutral SV coverage models (where present)
```

Shared VIP imports use the top-level `ocah_<proto>_vip` packages under `vip/`;
the root `__init__.py` re-exports the cocotb public API, so consumers never
import from the subfolders directly. `ocah_jtag_vip` is the reference
implementation for the SV-UVM side: its README carries the "Template
Contract" (frozen item/event API, env-level reuse and commercial-VIP
override, monitor-disable knob, nested vendor interface) that every OCAH
SV-UVM VIP follows. New protocol VIPs should provide master, slave, item,
monitor, checker, and commercial-simulator coverage hook files when the
protocol shape supports them. For example:

```python
from ocah_axi_vip import OcahAxiLiteMasterAgent
```

## VIP Ownership and Promotion Policy

Start new protocol behavior beside its first consumer. Promotion is a maturity
decision, not a directory cleanup:

1. **DUT-local** (`hw/<...>/<dut>/dv/`): hierarchy bindings, address maps,
   loopback fixtures, lifecycle/security policy, and DUT-specific reference
   models. The DUT DV maintainers own these files.
2. **IP/domain-local reusable** (`hw/ip/<ip>/dv/` or another domain-owned
   location): custom protocol behavior reused by related integrations but not
   yet protocol-neutral.
3. **Shared VIP** (`hw/common/dv/vip/ocah_<protocol>_vip/`): a
   protocol-neutral, versioned API owned by the shared DV maintainers and
   validated by at least one real DUT consumer.

Keep the thin signal-binding adapter local after promotion. Shared code must
not hard-code `cocotb.top`, DUT hierarchy, register addresses, instance counts,
or lifecycle policy.

### Promotion checklist

Promote a local helper only when every required item is true:

- [ ] A second independent consumer needs the behavior, or the implemented
      standard/protocol surface is demonstrably stable and broadly reusable.
- [ ] Public methods use plain Python values or OCAH item/result dataclasses;
      backend objects are hidden except for explicitly documented debug escapes.
- [ ] `__init__.py` exports the stable surface from
      `ocah_<protocol>_vip`; callers do not import implementation subfolders.
- [ ] `README.md` documents construction, API, backend/version/license policy,
      limitations, and the owning maintainer group.
- [ ] At least one runnable example exists under `cocotb/examples/`; complex
      APIs should also provide `MANUAL.md`.
- [ ] Timeouts, unsupported operations, and error responses are deterministic
      and documented.
- [ ] At least one named DUT regression gates the promoted behavior.
- [ ] DUT-specific binding and policy remain in the DUT tree, with a link to
      the shared package.

If any gate is missing, mark the helper/package experimental or deferred and
document the missing promotion trigger. Do not create a second shared VIP for
a protocol already represented here; extend the existing stable wrapper.

### Current shared-package maturity

| Package | Maturity | Public example | Gating consumer / disposition |
|---------|----------|----------------|-------------------------------|
| `ocah_axi_vip` | **Promoted** (both sides) | `ocah_axi_vip/cocotb/examples/example_register_access.py`, `example_axi_scoreboard_selftest.py` | DTP, SEP, and SMC use the shared AXI/AXI-Lite master and slave agents through the per-side `*Sequence` APIs; the checker/reference-model/scoreboard stack is gated by the DTP jtag2axi decode-error, security-gating, and SLVERR/DECERR injection tests; DUT-local agents retain address and scoreboard policy. SV layer (interface/SVA/responder modules/passive UVM stack/UVM slave agent) is consumed by `--dut dtp --framework uvm`, where the UVM slave agent answers the SMC OTP AXI-Lite port; the UVM master side is not shipped yet |
| `ocah_jtag_vip` | **Promoted** for IEEE 1149.1 (master side) | `ocah_jtag_vip/cocotb/examples/example_idcode.py`, `example_slave_selftest.py` | DTP, SMC, and SMU consume the master TAP API; the slave side (reactive TAP device) ships selftest-validated with no gating DUT consumer yet — DUT JTAG host ports are the intended first integration; iJTAG, boundary-scan, and DUT TDR maps remain local |
| `ocah_spi_vip` | **Promoted** for single-SPI flash | `ocah_spi_vip/cocotb/examples/example_jedec_id.py` | SEP is the gating DUT consumer; true quad/octal lanes, DDR, and vendor timing remain deferred |
| `ocah_uart_vip` | Experimental / dependency-gated | `ocah_uart_vip/cocotb/examples/example_loopback.py` | SMC has a consumer, but the optional backend is not part of the locked default environment |

### Deferred and experimental capability tracker

Only **Promoted** rows in the maturity table above are safe dependencies for
release-gating tests. Experimental helpers may be used by explicitly opted-in
tests, but cannot be the sole evidence for a gate. Deferred capabilities are
follow-up work and must not block baseline transaction BFMs or portable
checkers.

| Capability | Classification / reason | Owner | Promotion condition and next action |
|------------|-------------------------|-------|-------------------------------------|
| APB shared wrapper | No shared package: no DUT exposes an APB surface to a testbench today | Shared DV + first APB adopter | Introduce a shared APB VIP only when a DUT regression gates real APB traffic |
| UART | Experimental/dependency-gated: SMC consumer exists, but the optional backend is not locked consistently | Shared UART VIP + SMC DV | Resolve backend version/license policy, lock it in the supported environment, and retain a passing SMC loopback |
| I2C | No shared package: the SMC-local clock-sampled model (`hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_protocol_vip.py`) owns I2C/SMBus/PMBus traffic because `cocotbext-i2c` edge waits miss open-drain transitions under Verilator | SMC DV | Introduce a shared I2C VIP only when a second subsystem needs one and the open-drain timing fix is protocol-neutral |
| I3C SDR | No shared package: SMC gates on CSR decode plus a line-level pull-low check; the vendored I3C core remains an RTL dependency only | SMC/SMU DV + first I3C adopter | Introduce a shared I3C VIP only with a reproducibly provisioned backend and a gating DUT smoke test |
| Entropy source/monitor | No shared package: SEP-local models drive `esrc_noise_ext_i` and check the ESRC-to-DRBG-to-EDN chain | SEP DV | Introduce a shared entropy VIP only when a second subsystem needs one and gates it with a real regression |
| Memory-image helper | Deferred: no shared package or frozen image/preload format contract | Shared DV + first firmware-bearing DUT | Define plain image/preload/result types, document ownership and format, add an example, and gate one DUT |
| True QSPI/OSPI multi-lane data | Deferred: `ocah_spi_vip` currently uses single-bit data timing for quad/octal personalities | Shared SPI VIP + SEP/SMC DV | Specify lane turnaround/SDR-DDR timing, implement real multi-lane sampling/driving, and pass a DUT transfer test |
| Vendor-accurate flash BUSY timing and commands | Deferred: the released flash model is deterministic, instant-ready, and vendor-neutral | Shared SPI VIP + activating flash adopter | Select an adopter requirement, isolate vendor behavior behind a documented profile, and add status/timing checks |
| I3C HDR-DDR/HDR-BT | Deferred: backend/API and DUT support are not part of the SDR baseline | Activating DUT | Confirm backend support and license, define HDR items/timing, and add a gating HDR consumer |
| Full iJTAG/boundary-scan promotion | Deferred: current DTP models encode fixed topology, lifecycle policy, and loopback fixtures | DTP/JTAG domain maintainers | Produce a topology/instrument-neutral model and demonstrate a second independent consumer |
| Commercial-simulator-only checker/coverage hooks | Deferred: portable checker evidence must exist before licensed-only depth can gate | Checker/DV infrastructure + protocol owner | Land portable item/checker semantics first, then add and validate commercial coverage hooks without making them mandatory for contributors |

Two examples define the ownership boundary:

- **DUT-local:** `hw/sys/dtp/dv/cocotb/env/dtp_scan_model.py` models the
  DTP testbench's compact BSR loopback. Its fixed topology and fixture semantics
  are not a reusable IEEE boundary-scan VIP.
- **Shared:** `ocah_axi_vip.OcahAxiMasterAgent` provides protocol-neutral AXI
  transactions and plain results. DTP, SEP, and SMC keep only their bindings,
  addresses, expected-response policy, and scoreboards locally.

Contributors should add new DUT-specific behavior under that DUT's `dv/`
directory. Add or extend shared protocol behavior only under
`hw/common/dv/vip/ocah_<protocol>_vip/` after the checklist above is met.

## Checker Ownership and Evidence

`vip/ocah_checker/` owns protocol-neutral checker evidence: stable `CHK-*`
identifiers, exact expected/observed/context formatting, required-ID tracking,
timeout checks, retained findings, and strict finalization. It is checker
infrastructure, not a protocol VIP.

Checker ownership follows these boundaries:

- each shared `ocah_<protocol>_vip` owns item-level protocol legality and
  structural checks, composed over `ocah_checker`;
- DUT `cocotb/assertions/` owns pure hierarchy/address/lifecycle invariants;
- DUT `cocotb/env/` owns lifecycle-aware scoreboards, predictors, and reference
  models;
- tests and sequences configure independent expected values and must finalize
  every checker they use.

Named evidence uses one line per concrete VPLAN intent:

```text
CHK-<ID> PASS expected=<value> observed=<value> context=<address/field/loop>
CHK-<ID> FAIL expected=<value> observed=<value> context=<address/field/loop>
CHECKER_SUMMARY name=<name> checks=<n> passed=<n> failed=<n> missing=<n>
```

Finalization fails on retained errors, zero executed checks, or missing required
IDs. A nonzero generic check count is not domain non-vacuity; tests must add a
meaningful `CHK-NONVAC` comparison when their VPLAN requires it.

Transaction timeout fails unless the VPLAN explicitly expects a bounded timeout
and records that bound. Runner stage timeout is always `TIMEOUT`/124 and cannot
be converted into checker PASS. Positive `CHK-*` text is auditable log evidence;
passing `results.xml` and native schema-1 `result.json` remain authoritative for
the runner.

## Reference Model and Scoreboard Contract

A scenario config may be the single source of truth for both stimulus and
expected results, but it must not contain simulator handles or mutable runtime
state. Prefer a frozen dataclass that records the seed, operation, dimensions,
input values, and evidence context used by:

1. the sequence or driver to program the DUT;
2. a pure or explicitly resettable reference model to compute expected values;
3. the checker or scoreboard to identify the corresponding evidence.

The observed value must come only from a DUT-facing driver or monitor. Never
derive expected data from the observation being checked. Models consume plain
config/transaction values and return plain expected values or item dataclasses.
Stateful models must provide deterministic reset/flush behavior, and tests must
invoke it at the same architectural boundary as the DUT reset or flush.

The checker/scoreboard owns comparison and finalization:

```text
immutable config -> DUT programming
immutable config -> reference model -> expected value/item
DUT driver/monitor -> observed value/item
expected + observed -> checker/scoreboard -> CHK-* evidence + CHECKER_SUMMARY
```

Use the common summary format for scoreboards as well as direct checkers:

```text
CHECKER_SUMMARY name=<name> checks=<n> passed=<n> failed=<n> missing=<n>
```

`failed` is the scoreboard error count. Before a failed summary, emit one
triage-ready `CHK-* FAIL` line per failed contract with exact expected,
observed, and context fields. Finalization must reject retained errors, zero
checks, and missing required IDs. Domain-specific `CHK-NONVAC` evidence must
show that the modeled path could not pass through idle, default, stub, or
unobserved behavior.

Shared protocol-neutral models may move beside their VIP only after the normal
promotion gates are met. DUT addresses, hierarchy, lifecycle/security policy,
scenario selection, and DUT-specific goldens remain under the DUT's
`cocotb/env/`; pure hierarchy invariants remain under `cocotb/assertions/`.

DUT-local packages are exposed by the OSS DV namespace bridge, which `run_dv.py`
provisions along with the shared package: it re-execs under
`uv run --project <root> --locked --group dv`, and this directory is the `ocah-dv`
uv workspace member, so the shared package resolves from source. The only
prerequisite is `uv` on PATH:

```bash
python3 tools/dv/run_dv.py --doctor --dut dtp
```

`OCAH_DV_SKIP_UV=1` skips the re-exec, for environments that already supply the
`dv` dependency group.

`--doctor --dut <name>` checks the shared package, required Python packages, the
namespace bridge, one shared VIP import, and the selected DUT-local import. If an
import fails, the report includes the setup step to rerun.

## Backend Import Policy

New OSS DV code should import protocol helpers through `ocah_<proto>_vip`
packages instead of directly importing backend packages. Notes:

- SEP/SMC AXI agents and Lite masters now use `ocah_axi_vip`
  (`OcahAxiMasterAgent` / `OcahAxiLiteMasterAgent`). Prefer `from_prefix` +
  `init_read`/`init_write` (or `*_result`) over direct `cocotbext.axi` imports.
- `hw/sys/sep/dv/cocotb/env/__init__.py` still patches cocotbext stream
  initialization before SEP AXI masters are constructed.
- SMC I3C carries no protocol-level VIP: `smc_i3c_to_fabric_test` gates on
  CSR decode plus a line-level external pull-low check. SMC I2C uses the
  DUT-local `smc_i2c_protocol_vip.py` clock-sampled model; no shared I2C
  package ships because `cocotbext-i2c` edge waits miss open-drain
  transitions under Verilator.
- SMC CPU JTAG uses `ocah_jtag_vip` for bus/device bind; active-high
  `tb_cpu_jtag_reset` stays DUT-local (not mapped to bus `trst`) because
  `cocotbext-jtag` assumes IEEE active-low TRST.
- `hw/sys/smc/dv/cocotb/tests/smc_register_sanity_test.py` drives real
  `s_axi_*` traffic into the SMC SEP_IN AXI port through the DUT-local
  `SmcSysAxiDriver`, which binds the shared `ocah_axi_vip.OcahAxiMasterAgent`.
  The local layer owns SMC/PyUVM sequencing and policy; the AXI protocol engine
  remains shared.
- `ocah_axi_vip.OcahAxiMonitor` and `OcahAxiLiteMonitor` are OCAH-owned
  passive samplers that emit plain item dataclasses. The released
  master/responder BFMs remain cocotbext-backed.
