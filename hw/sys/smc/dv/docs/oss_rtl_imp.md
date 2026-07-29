# OSS SMC RTL Instantiation Notes

Source context: `hw/oss-example`, `hw/sys/smc/dv`, `hw/sys/smu/dv` (`--dut smu_wrapper`).
Purpose: document how OSS uses RTL, how `hw/oss-example` relates to the SMC DV sandbox, and how to modify the OSS SMC environment to instantiate `smc_wrapper`.

---

## 1. Two different `hw/` trees

| Path | Role |
|------|------|
| Repo-root `hw/` | Real DUT RTL (source of truth). Bender pulls this into compile filelists. |
| `hw/` | OSS DV sandbox mirror (`configs/`, VIP, TB, cocotb). Not a second copy of DUT RTL. |

`--dut smc` resolves via `hw/common/dv/configs/duts.toml`:

```toml
[duts.smc]
root = "hw/sys/smc/dv"   # repo-relative path: hw/sys/smc/dv/
```

---

## 2. Current OSS SMC flow (`--dut smc`)

### DUT instantiation

- TB: `hw/sys/smc/dv/tb/tb_top.sv` → module `smc_uvm_top`
- DUT: bare `smc u_dut (...)` (direct clocks / AXI / `pad2core`)
- Config: `hw/sys/smc/dv/smc_sim_cfg.toml`
- Bender targets: `["smc", "simulation"]`
- Does **not** pull `hw/oss-example`

### RTL closure (Bender → `smc_bender.f`)

Major contributors under repo-root `hw/`:

| Area | Paths |
|------|--------|
| SMC top / subsys | `hw/smc/smc.sv`, `smc_cpu`, `smc_fabric`, `smc_peripherals`, `smc_reset_unit`, `smc_misc`, `smc_dfd`, … |
| Periph wraps | `hw/periph/{gpio,i2c_wrap,i3ccore_wrap,uart_*,efuse,dfd,telemetry_*}` |
| Comp / IP | `hw/comp/{i2c,uart_16550,log_engine,…}`, `hw/ip/{avsbus,system_timer_octs,axi_*mailbox*,…}` |
| Common / vendor | `hw/common/*`, OpenTitan `prim`, `deps/{axi,apb,common_cells,el2,…}` |

TB-only extras (not DUT RTL): memory/eFuse behavioral models under `models/`, Verilator stubs under `tb/verilator_stubs/`.

### How to run (bare SMC)

```bash
cd <repo>
source bin/setup_env.sh
export TMPDIR=/localdev/$USER/TMPDIR && mkdir -p "$TMPDIR"
python3 -m pip install -e hw/common/dv
source bin/setup_env.sh

python3 tools/dv/run_dv.py --dut smc --list
python3 tools/dv/run_dv.py --dut smc --items smoke --tool vcs
python3 tools/dv/run_dv.py --dut smc --build-only --tool vcs
```

Outputs: `hw/sys/smc/dv/build/runs/<timestamp>__<tool>__*/`.

Architecture: PyUVM-on-cocotb (`env/` + `seq_lib/` + `tests/`), shared VIP under `hw/common/dv/vip/`. No Synopsys SVT on the OSS path.

---

## 3. `hw/oss-example` — release-oriented OSS wrapper

See `hw/oss-example/README.md`.

### Layout

| Path | Role |
|------|------|
| `wrapper/smc/smc_wrapper.sv` | OSS SMC DUT: `smc` + `smc_ip_integration` + padring |
| `wrapper/smc/smc_ip_integration*.sv` | PLL / PVT / GPIO / JTAG / xtrig integration |
| `wrapper/smc/*pad*`, `gpio_macro_wrapper.sv` | Pad bundles / GPIO shims |
| `wrapper/sep/`, `wrapper/smu/` | SEP / full SMU chiplet wrappers |
| `models/{pads,pll,pvt,efuse}/` | Behavioral replacements for proprietary macros |
| `filelists/oss_wrapper_sources.f` | Portable wrapper+model manifest (`OCAH_ROOT`) |
| `tb/occp_i2c_rom_smoke/` | Dual-`smu_wrapper` OCCP I2C ROM smoke (standalone make) |

### Hierarchy

```
smc_wrapper                         ← oss-example SMC DUT
 ├── smc u_smc                      ← real RTL: hw/smc/smc.sv
 └── smc_ip_integration             ← + padring_ext, gpio/pll/pvt models
```

### Bender targets (`Bender.yml`)

```yaml
# Pulls OSS models + smc_ip_integration (+ smu_wrapper, etc.)
- target: smu_oss_wrapper
  files:
    - hw/oss-example/models/...
    - hw/oss-example/wrapper/smc/smc_ip_integration*.sv
    - hw/oss-example/wrapper/smu/smu_wrapper.sv
    # ...

# smc_wrapper.sv is only compiled when BOTH targets are set
- target: all(smc_wrapper, smu_oss_wrapper)
  files:
    - hw/oss-example/wrapper/smc/smc_wrapper.sv
```

To instantiate `smc_wrapper`, bender targets need at least:

`smc` + `smu_oss_wrapper` + `smc_wrapper`

### Standalone oss-example smoke (not `run_dv`)

```bash
source bin/setup_env.sh
make -C hw/oss-example/tb/occp_i2c_rom_smoke sim WAVE=0
```

This boots two `smu_wrapper` chiplets with production ROM / OCCP over I2C — separate from the bare OSS SMC cocotb catalog.

---

## 4. Contrast: bare SMC vs `smc_wrapper`

| | `--dut smc` (today) | Target `--dut smc_wrapper` |
|--|---------------------|----------------------------|
| DUT module | `smc u_dut` | `smc_wrapper u_dut` |
| Clocks / reset | `clk_smc_i`, `rst_cold_ni` direct | `BP_REFCLK`, `BP_RESETN`, `BP_POWERGOOD` |
| GPIO / I2C | TB `pad2core` lifts | `GPIO_PAD` / `BP_*` inouts |
| Internal XMR | `u_dut.u_smc_peripherals...` | `u_dut.u_smc.u_smc_peripherals...` |
| PLL/PVT/DTP | TB DECERR terminators | Usually via `smc_ip_integration` OSS models |
| Bender | `smc`, `simulation` | `smc`, `smu_oss_wrapper`, `smc_wrapper` |

**Do not** replace `smc u_dut` inside the existing `tb_top.sv` in place — port semantics and cocotb XMRs will break. Add a parallel wrapper flow (same pattern as SMU).

---

## 5. Reference pattern already landed: `--dut smu_wrapper`

Template under `hw/sys/smu/dv/`:

| Piece | Location |
|-------|----------|
| DUT registry | `duts.toml` → `[duts.smu_wrapper]` |
| Sim config | `smu_wrapper_sim_cfg.toml` |
| TB top | `tb/tb_wrapper_top.sv` → `smu_wrapper` |
| Bender | `["smu","smc","dtp","sep","sep_el2","smu_oss_wrapper"]` |
| Shadows | `exclude` buggy oss-example files; compile `models/wrapper/*` |
| Tests | `cocotb/wrapper/` (nested flavor; separate from bare-`smc`) |

Run:

```bash
python3 tools/dv/run_dv.py --dut smu_wrapper --items smoke --seed 1 \
  --stage flist --stage c_compile --stage hdl_compile --stage sim
```

Known shadows (Verilator):

- `hw/oss-example/wrapper/smu/smu_wrapper.sv` → `shims/wrapper/smu_wrapper.sv`
- `hw/oss-example/wrapper/smc/smc_padring_ext.sv` → `models/wrapper/smc_padring_ext.sv` (ASSIGNIN)

---

## 6. How to modify OSS SMC to instantiate `smc_wrapper`

Recommended: add **`--dut smc_wrapper`**, keep `--dut smc` for the existing pin/CSR cocotb regression.

### Step A — Register DUT

`hw/common/dv/configs/duts.toml`:

```toml
[duts.smc_wrapper]
root = "hw/sys/smc/dv"
# resolves to smc_wrapper_sim_cfg.toml under that root
```

### Step B — New `smc_wrapper_sim_cfg.toml`

Key differences vs `smc_sim_cfg.toml`:

```toml
name = "smc_wrapper"
profile = "native-cocotb"

[build]
top_module = "smc_wrapper_uvm_top"
top_file = "hw/sys/smc/dv/tb/tb_wrapper_top.sv"
bender_targets = ["smc", "smu_oss_wrapper", "smc_wrapper"]
# optionally: open_source_dv_files for efuse models

exclude_files = [
  "hw/oss-example/wrapper/smc/smc_padring_ext.sv",  # if ASSIGNIN
]
sources = [
  "hw/sys/smc/dv/models/wrapper/smc_padring_ext.sv",  # copy from SMU shim if needed
]
```

### Step C — New TB top

Create `hw/sys/smc/dv/tb/tb_wrapper_top.sv`:

```systemverilog
module smc_wrapper_uvm_top (...);
    // pad-level tri / BP_* similar to SMU wrapper TB
    smc_wrapper u_dut (
        .BP_REFCLK(...),
        .BP_RESETN(...),
        .BP_POWERGOOD(...),
        .GPIO_PAD(...),
        .sys_axi_in_req_i(...),
        // ... remaining smc_wrapper ports
    );
endmodule
```

### Step D — Cocotb / XMR updates

- Hierarchy: insert `.u_smc` under `u_dut`
- Drive I2C/SPI/UART via pads (`GPIO_PAD[37/38]`, etc.) or re-lift from wrapper to TB top
- Revisit PLL/PVT/DTP boundary (OSS models inside integration, not bare DECERR slaves)

Prefer a nested `cocotb/wrapper/` flavor (own `python_root`) so bare-`smc`
tests stay stable. SMU still uses a top-level `cocotb_wrapper/` tree.

### Step E — Validate

```bash
source bin/setup_env.sh
source bin/setup_env.sh
export TMPDIR=/localdev/$USER/TMPDIR && mkdir -p "$TMPDIR"

python3 tools/dv/run_dv.py --validate-configs
python3 tools/dv/run_dv.py --dut smc_wrapper --list
python3 tools/dv/run_dv.py --dut smc_wrapper --build-only --dry-run
python3 tools/dv/run_dv.py --dut smc_wrapper --build-only --tool vcs
```

---

## 7. Which path to use

| Goal | Use |
|------|-----|
| Existing pin/CSR cocotb regression | `--dut smc` (bare `smc`) |
| OSS release-shaped wrapper (pads + PLL/PVT models) | New `--dut smc_wrapper` (mirror `smu_wrapper`) |
| Full chiplet + ROM OCCP | `hw/oss-example/tb/occp_i2c_rom_smoke` or `--dut smu_wrapper` |

---

## 8. Key file index

| Topic | Path |
|-------|------|
| OSS example README | `hw/oss-example/README.md` |
| SMC wrapper RTL | `hw/oss-example/wrapper/smc/smc_wrapper.sv` |
| Bare OSS SMC TB | `hw/sys/smc/dv/tb/tb_top.sv` |
| Bare OSS SMC cfg | `hw/sys/smc/dv/smc_sim_cfg.toml` |
| SMU wrapper cfg (template) | `hw/sys/smu/dv/smu_wrapper_sim_cfg.toml` |
| SMU wrapper TB | `hw/sys/smu/dv/tb/tb_wrapper_top.sv` |
| SMU wrapper README | `hw/sys/smu/dv/README.md` |
| DUT registry | `hw/common/dv/configs/duts.toml` |
| Launcher docs | `README.md`, `tools/dv/` docs |
| SMC porting plan | `hw/sys/oss_smc_dev.md` |
| Bender OSS wrapper slice | `Bender.yml` (`smu_oss_wrapper`, `smc_wrapper`) |
