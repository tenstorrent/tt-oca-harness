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

Shared VIP imports use the top-level `ocah_<proto>_vip` packages under `vip/`.
New protocol VIPs should provide master, slave, item, monitor, checker, and
commercial-simulator coverage hook files when the protocol shape supports them.
For example:

```python
from ocah_axi_vip import OcahAxiLiteMaster
```

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
- SMC I2C/I3C split-port adapters live in `ocah_i2c_vip` /
  `ocah_i3c_vip` (`Ocah*SplitPort*`); DUT wrappers only bind TB pads.
- SMC CPU JTAG uses `ocah_jtag_vip` for bus/device bind; active-high
  `tb_cpu_jtag_reset` stays DUT-local (not mapped to bus `trst`) because
  `cocotbext-jtag` assumes IEEE active-low TRST.
- `hw/sys/smc/dv/cocotb/tests/smc_register_sanity_test.py` remains a
  DUT-local observability test (probe sampling, no bus BFM).
- `ocah_axi_vip.OcahAxiMonitor`, `OcahAxiLiteMonitor`, and
  `ocah_apb_vip.OcahApbMonitor` are OCAH-owned passive samplers that emit plain
  item dataclasses. The released master/responder BFMs remain cocotbext-backed.
