# OCAH OSS shared DV (hw/common/dv)

Shared DV collateral for the OCAH tree: protocol VIP (`vip/ocah_<proto>_vip/`), shared
configs (`configs/`), `sva/`, `shims/`, and shared firmware (`fw/`).

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
from ocah_axi_vip import OcahAxiLiteMaster
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
| `ocah_axi_vip` | **Promoted** | `ocah_axi_vip/cocotb/examples/example_register_access.py` | DTP, SEP, and SMC use the shared AXI/AXI-Lite engines; DUT-local agents retain address and scoreboard policy |
| `ocah_jtag_vip` | **Promoted** for IEEE 1149.1 | `ocah_jtag_vip/cocotb/examples/example_idcode.py` | DTP, SMC, and SMU consume the TAP API; iJTAG, boundary-scan, and DUT TDR maps remain local |
| `ocah_spi_vip` | **Promoted** for single-SPI flash | `ocah_spi_vip/cocotb/examples/example_jedec_id.py` | SEP is the gating DUT consumer; true quad/octal lanes, DDR, and vendor timing remain deferred |
| `ocah_apb_vip` | Experimental / unadopted | No package-local example | No real DUT consumer; add an APB example and gating integration before promotion |
| `ocah_entropy_vip` | Experimental | `ocah_entropy_vip/cocotb/examples/example_deterministic_entropy.py` | No real DUT consumer; retain until a subsystem gates deterministic source/monitor behavior |
| `ocah_i2c_vip` | Experimental | `ocah_i2c_vip/cocotb/examples/example_i2c_eeprom.py` | SMC still needs DUT-local split-port/timing adaptation; upstream reusable fixes instead of creating another I2C VIP |
| `ocah_i3c_vip` | Experimental / dependency-gated | `ocah_i3c_vip/cocotb/examples/example_priv_rw.py` | SMC use is optional/non-gating until the backend is reproducibly provisioned and a DUT test gates it |
| `ocah_uart_vip` | Experimental / dependency-gated | `ocah_uart_vip/cocotb/examples/example_loopback.py` | SMC has a consumer, but the optional backend is not part of the locked default environment |

Two examples define the ownership boundary:

- **DUT-local:** `hw/sys/dtp/dv/cocotb/env/dtp_scan_model.py` models the
  DTP testbench's compact BSR loopback. Its fixed topology and fixture semantics
  are not a reusable IEEE boundary-scan VIP.
- **Shared:** `ocah_axi_vip.OcahAxiMaster` provides protocol-neutral AXI
  transactions and plain results. DTP, SEP, and SMC keep only their bindings,
  addresses, expected-response policy, and scoreboards locally.

Contributors should add new DUT-specific behavior under that DUT's `dv/`
directory. Add or extend shared protocol behavior only under
`hw/common/dv/vip/ocah_<protocol>_vip/` after the checklist above is met.

DUT-local packages are exposed by the OSS DV namespace bridge. In a clean shell,
install the shared package and source the OSS DV environment before running tests:

```bash
python3 -m pip install -e hw/common/dv
source bin/setup_env.sh
python3 tools/dv/run_dv.py --doctor --dut dtp
```

`--doctor --dut <name>` checks the shared package, required Python packages, the
namespace bridge, one shared VIP import, and the selected DUT-local import. If an
import fails, the report includes the setup step to rerun.

## Backend Import Policy

New OSS DV code should import protocol helpers through `ocah_<proto>_vip`
packages instead of directly importing backend packages. Remaining audited
notes:

- SEP/SMC AXI agents and Lite masters now use `ocah_axi_vip`
  (`OcahAxiMaster` / `OcahAxiLiteMaster`). Prefer `from_prefix` +
  `init_read`/`init_write` (or `*_result`) over direct `cocotbext.axi` imports.
- `hw/sys/sep/dv/cocotb/env/__init__.py` still patches cocotbext stream
  initialization before SEP AXI masters are constructed.
- SMC I3C uses a DUT-local bind over `ocah_i3c_vip` split-port helpers. SMC
  I2C still uses `smc_i2c_protocol_vip.py` because its Verilator/open-drain
  timing workaround has not yet been promoted into `ocah_i2c_vip`.
- SMC CPU JTAG uses `ocah_jtag_vip` for bus/device bind; active-high
  `tb_cpu_jtag_reset` stays DUT-local (not mapped to bus `trst`) because
  `cocotbext-jtag` assumes IEEE active-low TRST.
- `hw/sys/smc/dv/cocotb/tests/smc_register_sanity_test.py` drives real
  `s_axi_*` traffic into the SMC SEP_IN AXI port through the DUT-local
  `SmcSysAxiDriver`, which binds the shared `ocah_axi_vip.OcahAxiMaster`.
  The local layer owns SMC/PyUVM sequencing and policy; the AXI protocol engine
  remains shared.
- `ocah_axi_vip.OcahAxiMonitor`, `OcahAxiLiteMonitor`, and
  `ocah_apb_vip.OcahApbMonitor` are OCAH-owned passive samplers that emit plain
  item dataclasses. The released master/responder BFMs remain cocotbext-backed.
