<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS TB Upgrade Roadmap — Full Peripheral BFM / Memory-Model

| Field | Value |
|-------|-------|
| Status | Draft roadmap (planning only; not yet executed) |
| Owner | minshaoho |
| Date | 2026-07-21 |
| Scope | `hw/sys/smc/dv/` only (OSS path; no Synopsys SVT) |
| Related | `SMC_VPLAN.md`, `oss_smc_dev.md`, `smc_oss_execution_guide.md`, SEP refs below |
| Aspiration (non-OSS) | `dv/smc/tb/smc_synopsys_vip_overview.md` (legacy SVT AMBA VIP) |

---

## 1. Goal

Raise the OSS SMC testbench from a **CSR/fabric + pin-VIP + DECERR-terminator**
bench to a **SEP-parity (then better) peripheral BFM / memory-model environment**:

1. DUT-owned memories and fabric slaves have **functional responders** (preload,
   RW, counters, golden compare) — not just DECERR hang-avoidance.
2. External protocols that SMC owns at the pad boundary have **DUT-attached BFMs**
   (real pin traffic through the DUT, not cocotb↔cocotb or VIP self-tests).
3. Firmware boot has a **deterministic PASS/FAIL** path on both Verilator and
   Xcelium.
4. VPLAN claims match what the TB can actually defend (no hollow “Done”).

**Promotion rule (same as `SMC_VPLAN.md` P2):** a work item is Done only when
the blocker is cleared **and** the owning test PASSes on **both** simulators.

---

## 2. Baseline (current maturity)

### 2.1 Relative position

```
Legacy Synopsys SVT AMBA VIP     ████████████  100%  (aspiration; NOT on OSS path)
OSS SEP (memory + SPI + FW)      █████████░░░  ~70–75%
OSS SMC (CSR + pin VIP + DECERR) ██████░░░░░░  ~45–55%
```

### 2.2 What SMC already has (keep)

| Asset | Location | Honest capability |
|-------|----------|-------------------|
| Active AXI masters (SEP_IN / SYS_IN / JTAG / eFuse AXIL) | `tb/tb_top.sv` + `cocotb/env/smc_*_axi_agent.py` | Real CSR/fabric stimulus |
| CPU ROM/scratch/cache responder | `shims/mem/tb_smc_cpu_mem_responder.sv` | Banks exist; FW image still gated |
| Output-fabric mini RAM | `tb_top` `output_mem` | OKAY slave for DMA/zeroer/filter |
| Python golden store | `cocotb/env/smc_memory_model.py` | TB-local only; not DUT backdoor |
| Pin VIP wrappers | I2C / I3C / UART / CPU JTAG via `ocah_*_vip` | Pin smoke / partial protocol |
| Macro boundary responders | `prim_axi_lite_err_slv` on PLL/PVT/DTP/extension | Decode/route only (S13a) |
| P2-15 LC eFuse JTAG matrix | `tb_lc_state_*` + `ej_axi` | Done |

### 2.3 What SEP has that SMC lacks (primary target)

Reference layout: `hw/sys/sep/dv/`

| SEP pattern | SEP path | SMC gap |
|-------------|----------|---------|
| Dense mem shims (TCM/SRAM/ROM/KM/OTBN) | `sep/dv/shims/mem/tb_*.sv` | Only CPU mem responder |
| Functional OTP/eFuse responder | `shims/analog/tb_sep_efuse_responder.sv` | Verilator stub / resp-code only |
| SPI flash BFM on **DUT pins** | `tb_top` + `OcahSpiFlash` | SPI lift deferred; VIP self-test |
| FW boot + PASS mailbox | `+cpu_boot` + `sep_outbound_mbx` | Image-gated; no closed PASS loop |
| Deep goldens / scoreboards | `sep_*_golden.py` | Mostly SAMPLE + CSR count |
| Documented shim plan | `SEP_OSS_ROM_SRAM_OTP_SHIM_PLAN.md` | This document |

### 2.4 Explicit non-goals

- Do **not** put Synopsys SVT VIP on the OSS path (license / product boundary).
- Do **not** treat DECERR terminators as functional PLL/PVT/extension models.
- Do **not** claim Cadence-I3C / hard-macro internal behaviour as SMC unit DV
  unless a real model is wired (prefer IP-level DV ownership).
- Do **not** promote a test to Done on Verilator-only or with `proxy=True`
  masquerading as protocol proof.

---

## 3. Target architecture

```
```
cocotb / PyUVM  (agents · BFMs · goldens · scoreboards)
        |
        v  pin / AXI flat ports
   tb/tb_top.sv   <--- single integration boundary
        |
   +----+----+-----------+----------------+
   |         |           |                |
   v         v           v                v
 mem       AXI/AXIL    pad BFMs      macro models
 responders masters    SPI/I2C/      RW stub OR
 ROM/out   (SEP_IN…)   UART/AVS…    DECERR+VPLAN scope
 (SEP pattern)
```
```

**Principles (copy from SEP shim plan):**

- Shims live under `hw/sys/smc/dv/`; DUT RTL stays unchanged.
- `tb_top.sv` is the only integration boundary.
- Prefer `ocah_*_vip` + Apache-2.0 BFMs over commercial VIP.
- Every new model documents **DEFENDS / DOES NOT DEFEND** in VPLAN.

---

## 4. Phased upgrade plan

### Phase U0 — Honesty & freeze overclaims (1–2 days)

**Why first:** stop counting DECERR sweeps / fake BFMs as Done while building real infra.

| ID | Task | Deliverable | Done when |
|----|------|-------------|-----------|
| U0-1 | VPLAN / testlist audit of hollow P2-A names | Updated `SMC_VPLAN.md` rows for SPI/UART/sideband/I3C CCC | Claims say reachability / pin-smoke / deferred where true |
| U0-2 | Tag tests: `reachability` vs `protocol` vs `firmware` | Optional tags in testlists | `--tag protocol` does not include DECERR sweeps |
| U0-3 | Keep S13a / boundary-responder scope language | Already in VPLAN | No regression of wording |

**Exit:** readers cannot mistake DECERR/fake for full peripheral coverage.

---

### Phase U1 — Memory / slave model parity with SEP (1–2 weeks) — **P0**

**Goal:** every SMC-owned fabric/memory path that tests already hit has a
functional responder, not a hang or silent drop.

| ID | Task | Deliverable | SEP reference | Done when |
|----|------|-------------|---------------|-----------|
| U1-1 | Enlarge / parameterize output-fabric RAM | `shims/mem/tb_smc_output_mem_responder.sv` (or expand `output_mem`) with `+smc_output_hex` | `tb_sep_sram_responder.sv` | DMA/zeroer/filter tests preload + golden match |
| U1-2 | SYS_OUT / external AXI slave model | Cocotb or SV responder with OKAY/SLVERR inject knobs | `sep_outbound_mbx.sv` | At least one directed WR/RD + inject-error test PASS both sims |
| U1-3 | Wire Python `SmcMemoryModel` as golden only | Doc + scoreboard hooks | SEP goldens | No claim of DUT backdoor |
| U1-4 | CPU mem responder FW preload path | Document `+smc_rom_hex`, default smoke image | SEP `+cpu_boot` / TCM | One FW smoke can load without manual hacks |
| U1-5 | Macro windows policy decision | Per-window: **RW stub** *or* **DECERR + out-of-scope** | SEP eFuse = functional | Written in this file §5 + VPLAN |

**Exit:** fabric/DMA/CPU memory paths match SEP’s “responder-backed” pattern.

---

### Phase U2 — Pad lift + first real external BFM (SPI) (1–2 weeks) — **P0**

**Goal:** close the largest SEP gap — DUT-attached SPI flash.

| ID | Task | Deliverable | Done when |
|----|------|-------------|-----------|
| U2-1 | Lift Octal SPI pads to `tb_top` (stability-safe) | Flat `tb_spi_*` ports; Verilator + Xcelium build green | No ICO/blowup; smoke still PASS |
| U2-2 | Bind `OcahSpiFlash` to DUT SPI pins | Shared VIP usage like SEP | JEDEC ID / read / write sequence through DUT SPI host |
| U2-3 | Replace hollow `smc_spi_loopback_test` | Real DUT-path test or rename + demote old | VPLAN P2-13 SPI half Done (both sims) |
| U2-4 | Optional: SPI CS + memory image preload | `+smc_spi_flash_hex` | DMA-from-flash or host-read test |

**Exit:** SMC has SEP-class SPI BFM attachment.

---

### Phase U3 — Firmware boot closure (1–2 weeks) — **P0** / VPLAN P2-1

**Goal:** deterministic CPU firmware regression like SEP’s cpu group.

| ID | Task | Deliverable | Done when |
|----|------|-------------|-----------|
| U3-1 | OSS-safe hello / scratch PASS firmware | `fw/` or `dv/.../fw` image + build recipe | Binary reproducible |
| U3-2 | Bring-up: reset vector + ROM load + run | Sequence + plusargs | CPU fetches from responder |
| U3-3 | PASS magic (scratch or mailbox) | Scoreboard gate | `smc_cpu_firmware_boot_test` PASS both sims |
| U3-4 | Register as `p2_phase_c` leaf when ready | testlist + VPLAN P2-1 | Promotion criterion met |

**Exit:** P2-1 Done; unlocks P2-9 (DMI) later.

---

### Phase U4 — Protocol BFM depth (2–4 weeks) — **P1** / VPLAN Phase A

Upgrade pin-smoke to **DUT-attached** protocol proofs. Order by leverage.

| ID | Protocol | Current | Target | VPLAN |
|----|----------|---------|--------|-------|
| U4-1 | UART | RX drive / TX resolvable | Full echo or TX capture vs programmed DUT UART | P2-13 |
| U4-2 | I2C / SMBus / PMBus | Often cocotb↔cocotb; SMBus partial | DUT controller master/target + ARA/PEC/Host Notify | P2-11 |
| U4-3 | I3C | SDR-directed; CCC/IBI deferred | DAA/SETDASA/GETSTATUS + IBI (fix upstream VIP if needed) | P2-12 |
| U4-4 | AVSBus | Fake Python / CSR bounded | Pad-level device BFM, ACK+data | P2-3 |
| U4-5 | OCTS | CSR / fake | Real timer/sync transaction BFM | P2-4 |
| U4-6 | Telemetry | Inputs tied 0 | ATB pad lift + receiver BFM | P2-5 |

**Per-protocol Done checklist:**

1. Pads lifted / polarity adapter documented.
2. BFM binds to DUT (not mock handles).
3. At least one directed transaction asserts DUT-visible side effect (CSR, IRQ, or memory).
4. PASS on Verilator **and** Xcelium.
5. VPLAN row updated; hollow alias demoted or deleted.

---

### Phase U5 — Macro / analog models (parallel, policy-driven) — **P1**

| Window | Address | Default policy | Upgrade option |
|--------|---------|----------------|----------------|
| PLL | 0xC000_3000 | Keep DECERR terminator **or** RW stub CSR mirror | Functional PLL model = IP DV |
| PVT | 0xC000_7000 | Same | Sensor model = IP DV |
| Extension (Cadence I3C) | 0xC040_0000 | DECERR unless Cadence-free stub appears | Prefer IP-level DV |
| DTP CSR | 0xC000_F000 | **Unreachable from SEP_IN** (local-xbar hole) — keep S13a proof | Need alternate master path if ever required |
| GPIO_CTRL / REFCLK | periph | Prefer RW stub if CSR tests claim content | — |
| OTP/eFuse array | eFuse path | SEP-style behavioral responder + preload | P2-6 |

**Rule:** if a test enumerates many addresses inside a DECERR window, either
(a) add an RW stub that distinguishes addresses, or (b) demote the test to
reachability and point to S13a.

---

### Phase U6 — Agents, monitors, scoreboards — **P1**

| ID | Task | Done when |
|----|------|-----------|
| U6-1 | Split SAMPLE-only agents from protocol agents in docs/env | Naming cannot imply protocol when SAMPLE-only |
| U6-2 | AXI slave monitor on output / SYS_OUT | Protocol checks beyond OKAY count |
| U6-3 | Protocol goldens for I2C/UART/SPI (byte-level) | Mismatch fails test |
| U6-4 | Retire `proxy=False` on CSR/DECERR-only items | Scoreboard evidence matches truth |

---

### Phase U7 — Fault inject / security depth — **P2** / VPLAN Phase B·C

| ID | Task | Depends on | VPLAN |
|----|------|------------|-------|
| U7-1 | ECC SBE/DBE inject hooks | Memory responders with ECC observability | P2-7 |
| U7-2 | DFD/DBS fault + debug-bus capture | tb_top taps | P2-8 |
| U7-3 | JTAG DMI | U3 FW boot | P2-9 |
| U7-4 | Cross-domain DTP (honest map) | Alternate master or map fix; not SEP_IN hole | P2-10 |
| U7-5 | OTP burn / shadow | U5 eFuse responder | P2-6 |
| U7-6 | OCCP / secure-boot negative | U3 + security hooks | P2-2 |
| U7-7 | FuSa random error | Framework | P2-14 |

**Already Done:** P2-15 eFuse JTAG LC matrix.

---

## 5. Macro window policy (decision log)

| Window | SEP_IN reachable? | Near-term TB | Long-term |
|--------|-------------------|--------------|-----------|
| PLL | Yes | DECERR terminator + S13a | Optional RW stub; function = IP DV |
| PVT | Yes | DECERR terminator + S13a | Optional RW stub; function = IP DV |
| Extension | Yes | DECERR terminator + S13a | Cadence-free stub only if available |
| DTP CSR | **No** (local-xbar hole) | Assert idle + upstream DECERR | Needs map/master change outside OSS unit scope |
| GPIO_CTRL | Partial / DECERR today | Prefer RW stub for CSR sweeps | — |

Update this table when a model lands; sync `SMC_VPLAN.md` Defense scope.

---

## 6. Suggested execution order (critical path)

```
U0 honesty
   │
   ├─► U1 memory/slave responders  ──┐
   │                                 ├─► U3 firmware boot ──► U7-3 DMI …
   └─► U2 SPI pad lift + OcahSpiFlash ┘
            │
            └─► U4 protocol depth (UART → I2C/SMBus → I3C → AVS/OCTS → telemetry)
                     │
                     └─► U5/U6 parallel polish → U7 fault/security
```

**Do not** start U4 AVSBus/OCTS or U7 FuSa before U1/U2/U3 — those three define
SEP parity.

---

## 7. Effort sketch (calendar, one owner)

| Phase | Effort | Cumulative |
|-------|--------|------------|
| U0 Honesty | 1–2 days | ~2 d |
| U1 Memory/slave | 1–2 weeks | ~2–3 w |
| U2 SPI BFM | 1–2 weeks | ~3–5 w |
| U3 Firmware | 1–2 weeks | ~4–7 w |
| U4 Protocol depth | 2–4 weeks | ~6–11 w |
| U5 Macro policy/stubs | parallel with U4 | — |
| U6 Scoreboard polish | 1 week | ~7–12 w |
| U7 Fault/security | 2–4 weeks | ~9–16 w |

SEP-parity milestone ≈ end of **U3** (~1–2 months).  
“Full peripheral BFM” claim ≈ end of **U4** with both sims green.

---

## 8. Acceptance milestones

### M1 — SEP parity (must ship)

- [ ] Output / SYS_OUT memory responders with preload
- [ ] SPI flash BFM on DUT pins; JEDEC + read proof
- [ ] One FW boot test with PASS magic (both sims)
- [ ] VPLAN P2-1 + P2-13(SPI) promoted only after dual-sim PASS
- [ ] No DECERR sweep listed as register-content coverage

### M2 — Peripheral BFM complete (SMC-owned pads)

- [ ] UART echo or equivalent DUT TX proof
- [ ] I2C path through DUT controller (not VIP↔VIP only)
- [ ] I3C CCC/IBI or VPLAN explicit deferral with VIP bug link
- [ ] AVSBus + OCTS pad BFMs replace fake Python
- [ ] Telemetry ATB lift or documented out-of-scope

### M3 — Security / fault depth

- [ ] eFuse responder + OTP program path (P2-6)
- [ ] ECC / DFD inject (P2-7/8)
- [ ] DMI (P2-9) after FW
- [ ] P2-15 remains green through tb_top changes

---

## 9. Mapping to existing VPLAN P2 IDs

| Upgrade phase | Closes / enables |
|---------------|------------------|
| U1 | Infra for P2-1, fabric depth |
| U2 | P2-13 (SPI half) |
| U3 | P2-1; enables P2-9 |
| U4-1..6 | P2-13 UART, P2-11, P2-12, P2-3, P2-4, P2-5 |
| U5 OTP | P2-6 |
| U7 | P2-2, P2-7, P2-8, P2-9, P2-10, P2-14 |
| Done already | P2-15 |

---

## 10. File / directory touch plan (when implementing)

```
hw/sys/smc/dv/
├── docs/
│   ├── SMC_VPLAN.md              # sync defense scope + P2 promotion
│   └── smc_ossupgrade.md         # this roadmap
├── tb/tb_top.sv                  # pad lifts, responder instances
├── shims/
│   ├── mem/                      # expand: output, optional SPM, …
│   └── analog/                   # future: eFuse responder (SEP pattern)
├── cocotb/
│   ├── env/                      # agents, goldens, monitors
│   ├── seq_lib/                  # real BFM sequences
│   └── tests/                    # promote / demote leaf tests
└── testlists/                    # tags: reachability | protocol | firmware
```

Shared VIP reuse: `hw/common/dv/vip/` (`ocah_axi_vip`, `ocah_spi_vip`,
`ocah_i2c_vip`, `ocah_i3c_vip`, `ocah_uart_vip`, `ocah_memory_image` if banks fit).

---

## 11. Risks

| Risk | Mitigation |
|------|------------|
| SPI/telemetry pad lift destabilizes Verilator | Incremental lift; gate behind define; keep smoke green |
| Shared `build/cocotb/verilator` races across sessions | Serialize rebuilds; document exclusive use |
| Cadence / hard-macro models unavailable in OSS | Keep DECERR + IP-DV ownership; do not fake content |
| I3C VIP CCC/IBI upstream bugs | Document deferral; SDR remains; track VIP fix |
| FW image / toolchain not OSS-safe | Minimal bare-metal PASS image under `hw/sys/smc/dv/assets` |

---

## 12. Immediate next actions (start here)

1. **U0-1** — Mark P2-A hollow claims in `SMC_VPLAN.md` / test docstrings (SPI loopback, sideband fake BFM, I3C CCC name).
2. **U1-1** — Extract / enlarge output-fabric memory responder with hex preload (SEP SRAM pattern).
3. **U2-1** — Spike SPI pad lift on Verilator (build-only), then bind `OcahSpiFlash`.
4. **U3-1** — Identify minimal SMC FW PASS image + `+smc_rom_hex` recipe.

Do not start new DECERR address sweeps; they do not move this roadmap.

---

## 13. Revision history

| Date | Change |
|------|--------|
| 2026-07-21 | Initial roadmap: baseline vs SEP, phases U0–U7, milestones M1–M3 |

---

## 14. Progress Log (append-only — do not rewrite §§1–13)

### 2026-07-21 — Execution start: close U0 / U1 / U2-1 gaps

**Policy this session:** keep the roadmap text above unchanged; implement
fixes in TB/code and record evidence here.

#### U0 — Honesty (done)

| Item | Change |
|------|--------|
| `smc_spi_loopback_test` | Class docstring: library self-test only; pads lifted but VIP not bound |
| `smc_sideband_avsbus_octs_bfm_test` | Class docstring: fake BFM, no DUT pad drive |
| `smc_i3c_ccc_ibi_full_test` | Class docstring: CCC/IBI not driven (matches module KNOWN GAP) |
| `smc_uart_loopback_test` | Class docstring: pin-wire / no echo |

#### U1-1 — Output-fabric memory responder (done in code)

| Item | Detail |
|------|--------|
| New shim | `shims/mem/tb_smc_output_mem_responder.sv` |
| Features | Byte-strobe AXI OKAY slave; counters; `+smc_output_hex=<path>` preload; mem retained across reset |
| `tb_top.sv` | Inline `output_mem` always_ff removed; instantiates `u_output_mem` |
| `smc_sim_cfg.toml` | Added shim to `build.sources` |
| Observables | Unchanged: `tb_output_axi_{write,read}_count`, `last_addr`, `last_wdata` |

#### U2-1 — SPI pad lift (done in code; BFM bind still open)

| Item | Detail |
|------|--------|
| `tb_top` ports | `tb_spi_enable/clk/txd/cs_*/clk_*/dqs_*/dq_*/rxd/rxds/mem_rebar_ipad` |
| DUT connect | All `spi_*` ports wired (were previously unconnected) |
| Idle defaults | `_bring_up()` in `smc_base_test.py` sets enable=0, cs_n=1, oe/ie negated high |
| Still open (U2-2) | Octal-pad ↔ classic `OcahSpiFlash` (CS/SCK/MOSI/MISO) adapter + DUT-path JEDEC test |

#### Not done this session

- U2-2 OcahSpiFlash on DUT pins
- U3 firmware PASS closure
- U4 protocol depth (UART echo / DUT I2C / AVS pad BFM)
- Dual-sim regression of the tb_top change (needs exclusive Verilator rebuild)

#### Next concrete steps

1. Rebuild + smoke: `smc_cold_reset_test`, `smc_output_fabric_wr_rd_responder_test`, `smc_dma_sanity_test`
2. Optional preload proof: ship a tiny `smc_output.hex` + directed readback test
3. U2-2: design octal SPI pad adapter (map host CS/SCK/DQ0 ↔ `tb_spi_*`)
4. U3-1: locate/create minimal `+smc_rom_hex` PASS image

### 2026-07-21 — Tool policy: VCS first, Verilator last

**Decision (user):** all bring-up / gap-closing sims use **VCS** (`--tool vcs`,
Python 3.11). Verilator is reserved for a final dual-sim verification pass
after the TB upgrades stabilize. A mid-flight Verilator `--rebuild` of the
U1/U2 change was stopped; smoke re-targeted to VCS.

#### VCS results (U1/U2-1 bring-up)

Recipe:

```bash
export TMPDIR=/localdev/$USER/TMPDIR; mkdir -p "$TMPDIR"
python3 tools/dv/run_dv.py --dut smc --tool vcs --rebuild \
  --items smc_cold_reset_test smc_output_fabric_wr_rd_responder_test
```

| Test | VCS status | Notes |
|------|------------|-------|
| `smc_cold_reset_test` | **PASS** | rebuild after output-mem shim + SPI pad lift |
| `smc_output_fabric_wr_rd_responder_test` | **PASS** | `u_output_mem` path |
| `smc_dma_sanity_test` | **PASS** | uses output-mem counters |
| `smc_zeroer_dma_timeout_test` | **PASS** | uses output-mem counters |
| `smc_gpio_output_driveback_test` | **PASS** | previously blocked by Verilator race |
| `smc_gpio_irq_type_matrix_test` | **PASS** | |
| `smc_macro_axil_routing_test` | **PASS** | |
| `smc_sideband_avsbus_octs_bfm_test` | **PASS** | |
| `smc_spi_loopback_test` | **PASS** | first ERROR was `UnicodeEncodeError` from em-dash in class docstring under VCS-embedded Py3.9 logging; fixed to ASCII |

Run dirs:

- `hw/sys/smc/dv/build/runs/20260721_025245__vcs__multi/` (smoke 2/2)
- `hw/sys/smc/dv/build/runs/20260721_025323__vcs__multi/` (6/7 then SPI re-run PASS)
- `hw/sys/smc/dv/build/runs/20260721_025508__vcs__smc_spi_loopback_test/`

**Lesson:** `@pyuvm.test()` class docstrings must stay ASCII-safe — VCS cocotb path logs them through a Py3.9 ascii stream and treats `UnicodeEncodeError` Traceback as hard-fail even when the scenario passed.

### 2026-07-21 — U2-2 SPI pad BFM + U3 FW boot bring-up (VCS)

**Tooling lesson:** prior "VCS PASS" results for U1/U2-1 used a **stale Jul-13 `simv`**.
`--rebuild` alone did not always remake; deleting `hw/sys/smc/dv/build/cocotb/vcs/`
forced a real compile and exposed two real bugs:

1. `tb_smc_output_mem_responder.sv` — VCS **ICPD** (`initial` + `always_ff` both drive `mem`);
   fixed by using `always`.
2. Plusarg format — VCS requires `$value$plusargs("smc_output_hex=%s", ...)`.

#### U2-2 — SPI pad-attached OcahSepSpiFlash (Done, VCS PASS)

| Item | Detail |
|------|--------|
| `tb_spi_miso_ext` | New TB input; when `tb_spi_enable`, drives `pad2core[0]` |
| Test | `smc_spi_pad_bfm_test` — TB host on `tb_spi_*` + `OcahSepSpiFlash` JEDEC `0x9F` |
| Proof | Log: `SPI pad BFM JEDEC OK: 0x20BA18` |
| Scope honesty | Bare `smc` has no SPI host IP; this is pad-lift + BFM bind, not DUT-controller JEDEC |

#### U1-1 compile fixes (required for real VCS)

| Item | Detail |
|------|--------|
| ICPD | `always` instead of `always_ff` in output-mem responder |
| Plusarg | `smc_output_hex=%s` |

#### U3 — FW boot path (partial; not Done)

Infrastructure landed and VCS-proven where noted:

| Item | Status |
|------|--------|
| CPU_CTRL addresses | Fixed to `0xC003_9000/9020/9080` in `smc_cpu_vip_utils.py` |
| `+smc_scratch_ram_hex` absolute path | Required (sim cwd = `attempt_*/make`) |
| `hello_world.ecc.hex` asset | `hw/sys/smc/dv/assets/` |
| boot_stall pad 60 | Default `pad2core[60]=0` (was sticky-stalling fuse_reset) |
| `disable_sram_auto_init_i=1` | Preserve preload (auto-zero would wipe hex) |
| eFuse bank DECERR + fuse-cmd ACK | Unconnected ports previously hung fabric under `+skip_fuse_sense` |
| Boot sideband ties | `ext_boot_seq_done_i=1`, `sep_wdt_reset_n_i=1`, etc. |
| Pulse reset | Hold cores → write vectors 0..3 → pulse-start `0x1FF` |
| Test | `smc_cpu_firmware_boot_test` (not in default CI groups yet) |

**Observed on VCS after the above:**

- CPU **does run**: `rom_reads ≈ 1e6` (default vector `0xC004_0000` / ROM window).
- Scratch boot **not closed**: after hold+revector to `0xC006_0000`, still
  `scratch_reads=0`, `scratch_writes=0`, `last_scratch=0` — Chipyard does not
  appear to take the CPU_CTRL reset-vector redirect for IF, or scratch banking
  / fetch path still mismatches the ECC hex layout.
- Remaining U3 work: prove reset-vector → PC path (or early hold before fuse
  release), then bank-correct scratch preload / ROM-linked PASS image.

#### VCS results (this wave)

| Test | VCS status |
|------|------------|
| `smc_cold_reset_test` | **PASS** (clean rebuild) |
| `smc_output_fabric_wr_rd_responder_test` | **PASS** |
| `smc_dma_sanity_test` / `smc_zeroer_dma_timeout_test` | **PASS** |
| `smc_spi_pad_bfm_test` | **PASS** (JEDEC 0x20BA18) |
| `smc_cpu_ctrl_scratch_window_test` / `smc_cpu_sanity_test` | **PASS** |
| `smc_cpu_firmware_boot_test` | **FAIL** (CPU alive on ROM; scratch PASS not reached) |

Run dirs:

- `hw/sys/smc/dv/build/runs/20260721_030901__vcs__multi/` (cold/SPI/output PASS)
- `hw/sys/smc/dv/build/runs/20260721_034400__vcs__multi/` (SPI PASS + FW FAIL with rom_reads)

### 2026-07-21 — U3 FW boot Done + U4-1 UART DUT TX (VCS)

#### U3 — Firmware boot (Done, VCS PASS)

Closed `smc_cpu_firmware_boot_test` with a sync-free RV64 stub image.

| Item | Detail |
|------|--------|
| Image | `assets/min_pass.ecc.hex` via `gen_64b_ecc.py` (64-bit data + 8-bit ECC) |
| Root cause 1 | Broken hex packed one 32b insn/word → high half `0x00000000` illegal |
| Root cause 2 | RV64 `lui` sign-extends `0xC0039080` → 56b AXI miss; fixed with `lui/slli32/srli32/addi` |
| Boot sequence | `+smc_hold_cpu_boot` (pad60) → program vectors → release → poll SCRATCH0 |
| PASS proof | CSR `0xC0039080 == 0xACAFACA1` + scratch IF evidence (pre-release baseline) |
| PC evidence | `wb_pc0` advanced past store; `isolate=0` |
| CI | Tagged `u3_fw_boot`; added to `vplan_gaps` group |
| Out of scope | Full Freedom-metal `hello_world` (CLINT MSIP barrier at `0xC800_*` unreachable) |

#### U4-1 — UART DUT TX capture (Done, VCS PASS)

Deepened `smc_uart_loopback_test` from pin-wire to real DUT TX:

| Item | Detail |
|------|--------|
| Path | AXI → UART_EN + 16550 DLL/LCR → THR `0xA5` → pad12 → `OcahUartConsole` sink |
| Divisor | `round(1/(periph_ns*1e-9*16*115200))` from env cfg (seed-randomized clocks) |
| VIP fix | `ocah_uart_console.py` `with_timeout(..., t, "us")` for cocotb 1.9 |
| Proof | Log: `UART DUT TX OK: THR 0xA5 captured on pad12 @ 115200 baud` |

#### U4-2 — I2C DUT host + SMBus ARA/PEC + Host Notify (Done, VCS PASS)

| Item | Detail |
|------|--------|
| Host write / PEC / ARA | Prior wave (EEPROM + ARA `@0x0C`) |
| Host Notify | VIP master → DUT target `@0x08`; ACQDATA payload `a0efbe` |
| Proof | Log: `DUT Host Notify ACQDATA OK: payload=a0efbe` |
| Deferred | SMBALERT# → FW ARA path |

#### U4-3 — I3C SDR hard-gate (partial Done, VCS PASS)

| Item | Detail |
|------|--------|
| Hard gate | `writes >= 3` on `tb_i3c0_*` |
| Deferred | CCC/IBI (`i3ccore_stub` + upstream VIP) — **blocked without hw/** |

#### U4-4 — AVSBus FSM + pad observe + sdata ACK (Done, VCS PASS)

| Item | Detail |
|------|--------|
| FSM | IDLE `0x8` → `0x10` after `AVS_CMD` |
| Pad | pads 49/50 observe; pad51 `tb_avs_sdata_ext` slave BFM |
| ACK | Fixed write ACK `0x00FFFF06` (idle_window=30 after mdata preamble) |
| Proof | Log: `AVSBus sdata ACK PASS: LATEST=0x00FFFF06 ... READBACK=0x00FFFF06` |
| Helper | `cocotb/seq_lib/smc_avsbus_slave_bfm.py` |

#### U4-5 — OCTS timer + pad observe + dual-chiplet sync (Done, VCS PASS)

| Item | Detail |
|------|--------|
| COUNT | `0x127 → 0x249` after TIMER_START (sideband test) |
| Pad | `tb_octs_sync_load_from_dut` / `tb_octs_cnt_credit_from_dut` (58/59) |
| Dual-sync | `smc_octs_dual_sync_test` — see wave note below |

#### U4-6 — Telemetry IRQ + ATB RX (Done, VCS PASS)

| Item | Detail |
|------|--------|
| IRQ | `INTR_TEST` → `tb_telemetry_irq_any` |
| ATB | `tb_telemetry0_*` lift → message → `STATUS.~EMPTY` + `PROBE_ID=0x05` |
| Proof | Log: `Telemetry U4-6 PASS: INTR_TEST IRQ + ATB msg probe_id=0x05` |

#### Dual-sim (Verilator smoke) — Done

| Test | VCS | Verilator |
|------|-----|-----------|
| `smc_cold_reset_test` | PASS | **PASS** |
| `smc_sideband_avsbus_octs_bfm_test` | **PASS** (sdata ACK hard-gate) | **PASS** (FSM+pad+OCTS; ACK soft-skip) |
| `smc_telemetry_receiver_csr_test` | PASS (ATB) | **PASS** |

Honesty: AVS sdata ACK bit timing is **VCS-authoritative**. Verilator cocotb edge scheduling skewed capture (`READBACK=0x01FFFE0D`); ACK hard-gate skipped there, FSM/pad/OCTS retained.

#### Remaining blocked / deferred (honest)

| Item | Why |
|------|-----|
| I3C CCC/IBI | DUT=`i3ccore_stub`; need real I3C IP — **skipped this wave (user)** |
| Freedom-metal `hello_world` | CLINT `0xC800_*` unreachable |

#### VCS / Verilator results (prior wave)

| Test | Status |
|------|--------|
| `smc_sideband_avsbus_octs_bfm_test` | **VCS PASS** `LATEST=READBACK=0x00FFFF06` |
| dual-sim smoke (3 tests) | **Verilator PASS** |

Bundle run dirs:
- AVS ACK VCS: `.../20260721_081950__vcs__smc_sideband_avsbus_octs_bfm_test/`
- Dual-sim: `.../20260721_082009__verilator__multi/`

### 2026-07-21 — U4-5 OCTS dual-chiplet sync (Done, VCS PASS)

I3C CCC/IBI skipped. Implemented OCTS dual-chiplet sync referencing
`dv/smc/tb` (`octs_p0_sec` / `octs_p1_credit`: DUT PRIMARY pads 58/59,
BFM SECONDARY tracks). OSS has bare `smc` (no master BFM), so TB models
both roles on one DUT.

| Item | Detail |
|------|--------|
| TB | `tb_chiplet_is_primary` → `chiplet_is_primary_i`; `tb_octs_*_ext` → pad2core[58/59] |
| Order | **SECONDARY inject first**, then PRIMARY outbound (avoids `ExpectedCountValid_A` on mode switch with live COUNT) |
| Secondary | sync-then-credit ordered pulses; COUNT in `[PRESET+CREDIT, PRESET+2*CREDIT+margin]` |
| Primary | `TIMER_START` → pad58 sync_edges≥1, pad59 credit_edges≥2 |
| Test | `smc_octs_dual_sync_test` |
| Helpers | `smc_octs_sync_bfm.py`, `smc_octs_dual_sync_test_seq.py` |
| Proof | `OCTS dual-sync PASS: secondary COUNT=0x102f primary sync_edges=1 credit_edges=16 COUNT=0x10fd` |
| Run | `.../20260721_082753__vcs__smc_octs_dual_sync_test/` |

U4-5 pad-observe-only path in `smc_sideband_avsbus_octs_bfm_test` retained;
dual-chiplet hard-gates live in the dedicated test.

### 2026-07-21 — U1-2 SYS_OUT SLVERR inject (Done, VCS PASS)

Next phase after U4 close-out. Slave-side inject is distinct from DUT
outbound-filter **DECERR** (`smc_output_filter_remap_security_test`).

| Item | Detail |
|------|--------|
| Shim | `tb_smc_output_mem_responder.force_slverr_i` → BRESP/RRESP=`2'b10`; WR skips mem update; RD poison `0xDEADBEEFDEADBEEF` |
| TB | `tb_output_force_slverr` (default 0 in bring-up) |
| Test | `smc_output_fabric_slverr_inject_test`: OKAY → SLVERR WR+RD → OKAY readback |
| Proof | Log: `U1-2 SYS_OUT SLVERR inject PASS: OKAY then SLVERR(write+read) then OKAY readback` |
| Run | `.../20260721_091223__vcs__smc_output_fabric_slverr_inject_test/` |

#### RTL bug answer (this wave)

No new **RTL** bug found that needs a `hw/` fix for fabric/U4 work. Open items are
TB gaps, stubs, or map/scope limits:

| Observation | Class |
|-------------|-------|
| I3C = `i3ccore_stub` (no CCC/IBI) | Integration stub / scope |
| Freedom-metal CLINT `0xC800_*` unreachable | Map / FW bring-up limit |
| Bare SMC no SPI host IP | Architectural (pad BFM only) |
| AVS no HW PEC / SMBALERT# path | Feature / FW deferred |
| OCTS `ExpectedCountValid_A` if credit before sync | RTL assertion (correct); TB must order pulses |
| Prior eFuse hang under `+skip_fuse_sense` | **TB gap** (fixed with err_slv) |
| U1-1 VCS ICPD on mem[] | **TB bug** (fixed: `always` not `always_ff`) |

### 2026-07-21 — U1-3 SmcMemoryModel scoreboard golden (Done, VCS PASS)

Wired TB-local `SmcMemoryModel` into `SmcScoreboard` for SYS AXI fabric traffic.
**Not a DUT backdoor** — golden is updated only when tests set `update_golden` on
OKAY writes; OKAY reads with `check_golden` compare DUT rdata vs model.

| Item | Detail |
|------|--------|
| Item flags | `SmcSysAxiItem.update_golden` / `check_golden` / `memory_region` |
| Scoreboard | OKAY-only update/check; SLVERR/DECERR never touch golden |
| Fabric | `smc_output_fabric_wr_rd_responder_test` uses scoreboard path |
| SLVERR | Inject WR does not increment `memory_model_updates_seen` |
| DMA | Predict DST golden **before** post-copy read (no golden==golden) |
| Proof | 3/3 VCS PASS: fabric WR/RD + SLVERR inject + `smc_dma_sanity_test` |
| Run | `.../20260721_092105__vcs__multi/` |

U1 fabric/memory P0 slice (U1-1/U1-2/U1-3) complete. Remaining U1: U1-5
policy already in §5 (macros stay DECERR); U1-4 superseded by U3 FW boot.
Next roadmap: U5 optional RW stub or U6/U7.

### 2026-07-21 — U5 GPIO_CTRL / REFCLK RW stub (Done, VCS PASS)

Replaced `u_gpio_ctrl_macro_model` DECERR terminator with sparse AXI-Lite RW
stub. PLL/PVT/extension remain DECERR (policy unchanged for those windows).

| Item | Detail |
|------|--------|
| Shim | `shims/mem/tb_smc_gpio_ctrl_rw_stub.sv` @ `0xC000_4440` base |
| TB | `tb_top.u_gpio_ctrl_rw_stub` on `axil_gpio_ctrl_*` |
| Tests | `smc_gpio_ctrl_full_sweep_test`: 68× unique WR→RD; `smc_gpio_refclk_ctrl_test`: 2× WR→RD |
| Monitor | Removed `(0xC000_4440, 0xC000_5000)` from `expected_decerr_ranges` |
| Honesty | OKAY storage only — **not** real padring pinmux / REFCLK analog |
| Proof | VCS 2/2 PASS |
| Run | `.../20260721_094327__vcs__multi/` |

Policy note (append): GPIO_CTRL near-term TB is now **RW stub**; PLL/PVT/extension stay DECERR.

### 2026-07-21 — U6-1/U6-2 + dual-sim (VCS + Verilator PASS)

| Item | Detail |
|------|--------|
| U6-1 | `smc_env.py` documents SAMPLE agents vs protocol agents vs bus monitors |
| U6-2 | `tb_output_axi_{b,r}*` lift + `SmcOutputAxiMonitor` OKAY/SLVERR/DECERR tallies |
| Hard-gate | `smc_output_fabric_slverr_inject_test` asserts B/R OKAY then SLVERR deltas |
| U6-4 slice | GPIO_CTRL / REFCLK VIP records use `proxy=True` (CSR stub, not protocol) |
| VCS | **7/7 PASS** `.../20260721_095658__vcs__multi/` |
| Verilator | **7/7 PASS** `.../20260721_095904__verilator__multi/` |

Dual-sim items: cold_reset, fabric slverr inject, fabric wr/rd, dma, gpio_ctrl sweep,
gpio_refclk, octs_dual_sync.

#### Remaining backlog (honest)

| Item | Status |
|------|--------|
| U6-3 I2C/UART/SPI byte goldens | Not started |
| U6-4 full proxy=False audit | Partial (GPIO only this wave) |
| U7 fault/security | Not started (needs ECC/DFD/OTP depth) |
| I3C CCC/IBI | Skipped (`i3ccore_stub`) |

### 2026-07-21 — SMBALERT# ARA + U2/U5 tails + U6-3/U6-4 (VCS PASS)

| Item | Detail |
|------|--------|
| SMBALERT# → ARA | New `smc_smbus_alert_ara_test`: DUT target @0x10, ADDRESS1=ARA, TXDATA preload, `SMBUS_CTRL.SMBALERT`, observe `tb_i2c0_smbalert` (pad39), VIP `smbus_query_ara()` → `0x20`, pad clear via hwclr |
| Honesty | TB AXI CSR stands in for FW alert assert / ARA service (not Rocket FW IRQ path) |
| U2-3 | `smc_spi_loopback_test` demoted `proxy=True` (library-only); pad path = `smc_spi_pad_bfm_test` |
| U2-4 | Pad BFM adds in-process `flash.preload` + READ `0x03` (`deadbeef`); same path as `+spi_flash_preload` |
| U5 tails | PLL/PVT stay DECERR + doc; VIP records flipped to `proxy=True` (no new RW stubs) |
| U6-3 | `SmcProtocolVipItem.expected_bytes` / `observed_bytes` + scoreboard golden gate; wired UART / I2C / SPI pad / SMBALERT / Host Notify |
| U6-4 | CSR/DECERR/proxy tests → `proxy=True` (PLL/PVT/I3C stub/JTAG proxy/AVS bounded/spi_loopback/uart_log boundary) |
| VCS | **5/5 PASS** `.../20260721_104304__vcs__multi/` (alert_ara, spi_pad, uart, i2c_master, spi_loopback) |
| Verilator | **3/4 PASS** `.../20260721_104623__verilator__multi/` — alert_ara / spi_pad / spi_loopback OK; uart FAIL = missing `cocotbext-uart` in 3.11 env (not RTL/TB logic) |

Proof logs (VCS): `SMBALERT# asserted` → `ARA OK: reply=0x20; SMBALERT# cleared`; SPI `preload READ OK: deadbeef`; UART/SPI scoreboard `golden=... obs=...`.

#### Remaining backlog (honest, post this wave)

| Item | Status |
|------|--------|
| Rocket FW SMBALERT IRQ path | Deferred (TB CSR path closed U4-2 alert) |
| U5 eFuse behavioral / PLL functional | U7-5 / IP DV |
| U6-4 residual CSR tests | Some fabric/efuse still `proxy=False` by intent |
| U7 fault/security | Not started |
| I3C CCC/IBI | Skipped (`i3ccore_stub`) |

### 2026-07-21 — U6-4 residual proxy honesty + U7-3 JTAG DMI (VCS PASS)

| Item | Detail |
|------|--------|
| U6-4 residual | Flipped mislabeled `proxy=False` → `True` for diagnostic CSR suite, OCCP scratch alias, I3C DECERR, OCTS alias, etc. |
| U7-3 test | `smc_jtag_dmi_smoke_test` — IDCODE + DTMCS.version==1 + dmstatus.version==2 |
| VIP | `SmcJtagTap` OcahJtagTap bit-bang only (no cocotbext-jtag GatedClock on DMI) |
| Prereq 1 | SEP_IN AXI write `CPU_CTRL.RESET_CTRL` bit24 `debug_reset_n` (`0x0100_010F`) — RDL default holds Rocket DM reset |
| Prereq 2 | JTAG reset pulsed **with TCK stepping** — DMI TL xbar uses sync reset; wall-time TRST left `out_woready=X` and dropped dmcontrol writes |
| Observability | `tb_cpu_debug_dmactive` / `tb_cpu_debug_dmactive_ack` |
| Hard gates | DTMCS ver=1; dmstatus=`0x00430CA2` (version=2, authenticated=1) |
| Proof | VCS **PASS** `.../20260721_120548__vcs__smc_jtag_dmi_smoke_test` |

#### Remaining backlog (honest, post U7-3)

| Item | Status |
|------|--------|
| U7-1 ECC SBE/DBE inject | Needs inject hooks |
| U7-2 DFD/DBS fault | Needs tb taps / inject |
| U7-4 Cross-domain DTP | Map hole (SEP_IN) |
| U7-5 OTP burn / shadow | Needs eFuse behavioral |
| U7-6 OCCP secure-boot negative | Name vs scratch alias still proxy |
| U7-7 FuSa random | Framework |
| I3C CCC/IBI | Skipped (`i3ccore_stub`) |
| Verilator `cocotbext-uart` | Env gap |

### 2026-07-21 — Must-catch wave (W1–W3) VCS PASS

Closed the Must-gap plan items under `hw/sys/smc/dv/` (no DUT RTL changes):

| Item | Deliverable | Evidence |
|------|-------------|----------|
| W1-a P2-1 FW boot | Keep `min_pass.ecc.hex` contract; promote P2-1 | VCS PASS `smc_cpu_firmware_boot_test` in `.../20260721_150000__vcs__must_catch_w1w2` |
| W1-b P2-6 OTP | `shims/analog/tb_smc_efuse_responder.sv` + `smc_efuse_otp_burn_shadow_test` | VCS PASS `.../20260721_150527__vcs__multi` (sense+fail+burn; needs `program_enable`) |
| W1-c UART env | Historical run used `cocotbext-uart==0.1.4`; current shared uv ownership is deferred | VCS PASS `smc_uart_loopback_test` in must_catch run |
| W2-a P2-2 OCCP | Retire scratch proxy → OTP program-fail + EFUSE_MAP signature | VCS PASS `smc_occp_sanity_secure_error_test` (`proxy=False`) |
| W2-b/c P2-7/8 | `tb_cpu_ecc_inject_*` + `tb_dfd_fault_inject` / `tb_dbs_capture_*` | VCS PASS `smc_ecc_fault_inject_test`, `smc_dfd_dbs_fault_inject_test` |
| W3 P2-11 + honesty | Linear16 helpers + VPLAN P2 table update | VCS PASS `smc_smbus_pmbus_test`; `SMC_VPLAN.md` P2 rows promoted |

**must_catch_w1w2 group (VCS): 7/7 PASS** after program_enable fix  
`hw/sys/smc/dv/build/runs/20260721_150000__vcs__must_catch_w1w2` + efuse/occp rerun `20260721_150527__vcs__multi`.

#### Remaining backlog (honest, post Must-catch)

| Item | Status |
|------|--------|
| U7-4 Cross-domain DTP | Deferred (SEP_IN map hole / unit OOS) |
| U7-7 FuSa random | Deferred (Should wave; inject hooks exist) |
| I3C CCC/IBI | Skipped (`i3ccore_stub`) |
| Verilator dual-sim rebuild | Infra: Bender flist pulls dual i3c-core trees; clean Verilator rebuild fails (define/dup). VCS is authority for this wave. |
| Freedom-metal `hello_world` / CLINT | Still out of scope for P2-1 |
| Rocket FW SMBALERT IRQ | Deferred (TB CSR path already closed) |

