# SMU Register Reference

## Overview

The SMU top has no register file of its own; state is reached through the CSRs of
its sub-blocks and through the AXI crossbar apertures. Verification touches four
mechanisms:

| Interface | Type | Access Method |
|-----------|------|---------------|
| SMU AXI crossbar apertures | Address decode driven by CSR base/size | `smu_axi_in`/`smu_axi_out` + `sep/smc_global_base` CSRs |
| SMC CSRs (aperture, reset unit, mailboxes, GPIO/PLL/PVT/eFuse) | AXI4-Lite / memory-mapped | SMC fabric |
| SEP CSRs (aperture, filter/remap, `feat_ctrl`, mailboxes) | Memory-mapped over crossbar `sep_in` | Crossbar SEP aperture (`SEP=1`) |
| DTP TDRs / XTRIG CSRs | JTAG scan / AXI4-Lite | `axil_xtrig_*` and JTAG2AXI bridges |

Full register detail for each sub-block is maintained in that block's reference
(`dv/dtp/doc/DTP_CSR.md`, SMC/SEP RDL). This OCAH open-source document summarizes
the SMU-level addressing and the CSRs the SMU verification plan exercises.

## Register Sources

| Source | Path |
|--------|------|
| SMU crossbar | `hw/smu/rtl/smu_axi_xbar.sv`, `hw/smu/rtl/smu_axi_xbar_pkg.sv` |
| SMU config / fixed regions | `hw/smu/rtl/smu_pkg.sv` |
| SMC base config RDL | `hw/smc/smc_misc/data/registers/rdl/smc_base_config.rdl` |
| SMC mailbox RDL | `axil_mailbox_smc_wrap.rdl` |
| SEP mailbox / system CSRs | `hw/sep/sep_pkg.sv`, `sep_system_csr`, `sep_system_peripherals` |
| DTP CSR reference | `dv/dtp/doc/DTP_CSR.md`, `dv/oss/hw/sys/dtp/dv/docs/DTP_CSR.md` |
| Suspected register hazards | `dv/smu/tb/doc/smu_rtl_suspected_issues.md` |

## Part A: AXI Crossbar Apertures

The crossbar (`smu_axi_xbar`) uses `NumInputs=3`, `NumOutputs=3`, `NumAddrRules=2`,
`MaxInputIdW=8`, `XbarOutputIdW=10`; data 64-bit, address 56-bit, user 12-bit.
Address rules are runtime/CSR-driven:

| Rule | Target port | Base | End |
|------|-------------|------|-----|
| 0 | `sep_in` | `sep_global_base_addr_i` | base + `sep_region_size_i` |
| 1 | `smc_in` | `smc_global_base_addr_i` | base + `smc_region_size_i` |
| — | `ext_out` | default (catch-all) master port for `sep_out`/`smc_out` | — |

Reset-default apertures (from the testplans; verify against RDL at bring-up):
SEP `0x0000_0000`–`0x3FFF_FFFF`, SMC `0x4000_0000`–`0x7FFF_FFFF` (SMC base reset
`0x4000_0000`, size `0x0100_0000` = 16 MiB), External `0x8000_0000`+.

| Config | Value | Notes |
|--------|-------|-------|
| `ATOPs` | `1'b0` | AXI atomics unsupported (rejected) |
| `MaxMstTrans` / `MaxSlvTrans` | `8` / `8` | Outstanding transaction limits |
| `LatencyMode` | `CUT_ALL_PORTS` | Registered crossbar outputs |
| `en_default_mst_port` (sep_out/smc_out) | → `ext_out` | Unmatched accesses route to external |
| `ext_in` default port | none | Unmatched `ext_in` accesses decode-error |
| SVA `sep_smc_no_overlap_a` | — | Asserts SEP/SMC apertures never overlap |

### Programmable base/size CSRs

| Signal (SMU boundary) | Type | Source | Description |
|-----------------------|------|--------|-------------|
| `smc_global_base_o` | `smc_pkg::smc_axi_addr_t` | SMC CSR | SMC aperture base |
| `smc_region_size_o [31:0]` | 32-bit | SMC CSR | SMC aperture size |
| `sep_global_base_o` | 56-bit | SEP CSR | SEP aperture base (tied `0` when `SEP=0`) |
| `sep_region_size_o` | 56-bit | SEP CSR | SEP aperture size (tied `0` when `SEP=0`) |

### SEP→SMC alias remap (fixed, non-CSR)

| Constant (`smu_pkg.sv`) | Value | Description |
|-------------------------|-------|-------------|
| `SEP_SMC_REGION_BASE` | `0x4000_0000` | SEP-side base of the SMC alias window |
| `SEP_SMC_REGION_SIZE` | `0x4000_0000` (1 GB) | Alias window size |
| `SEP_SMC_REGION_ALIAS_BASE` | `0x0000_0000` | Remapped SMC-side base |

## Part B: Mailboxes

Mailboxes are the primary SMC↔SEP interoperability channel.

| Bank | Count | Base | Source |
|------|-------|------|--------|
| SMC mailboxes | `smc_pkg::NUM_MAILBOXES = 32` | `0x10A0_0000` | `axil_mailbox_smc_wrap.rdl` |
| SEP mailboxes | `sep_pkg::NUM_MAILBOXES = 8` | `0x10A0_0000` | `sep_pkg` / SEP CSR |

**Challenge-response flow** (proven in `smc_sep_interoperability_strict_test`):
SMC writes `INTEROP_TOKEN` to `OUTBOUND_MAILBOX_0` (`0x10A0_0000`); SEP reads the
inbound submailbox, verifies the token, and writes `~INTEROP_TOKEN` back; SMC pops
the response from `OUTBOUND_MAILBOX_0_READ_DATA` (`0x10A0_0008`) and latches
`SMC_TEST_PASS` to scratch.

> **Register hazard — SEP mailbox submailbox stride (ISSUE-1 / GitHub #3535).**
> The RDL/RAL lays inbound/outbound submailboxes at a `0x800` stride, but the RTL
> demux decodes on `select = addr[15:12]` (a `0x1000` stride). So RAL places
> `inbound_0` at `0x10A0_0800` while the RTL decodes it at `0x10A0_1000`. The
> current `sep_pkg` derives `MAILBOX_SIZE = INBOUND_0 - OUTBOUND_0` (= `0x800`),
> which differs from the hardcoded `0x1000` cited in the issues log. **Reconcile
> the authoritative submailbox base against the current RTL/`sep_pkg` before
> writing mailbox tests for submailbox index > 0.**

## Part C: DTP-Reachable CSRs and TDRs

DTP CSRs are reached from SMC over AXI-Lite (`smc_axil_dtp_csr` →
`axil_xtrig_*`) and its TDRs over the JTAG scan chain. The SMU plan exercises:

| Register / TDR | Access | Description |
|----------------|--------|-------------|
| `DEBUG_CONTROL` | JTAG TDR | Boot-stall override/value, JTAG/CLA clock-stop enable and readback |
| `IC_RESET` | JTAG TDR | Reset override for SMC / SEP / External slices (`JTAG_IC_RESET_{SMC,SEP,EXT}_ENABLE`) |
| `IDCODE` / `JTAG_CAPS` | JTAG TDR | Device ID and DTP capability reporting |
| Cross-trigger (CTM/CTP) config | AXI-Lite XTRIG CSR | Routing masks, mode, stretch |
| JTAG2AXI (SMC fabric / SMC OTP / SEP OTP) | JTAG TDR → AXI/AXI-Lite | Debug read/write into SMC fabric and OTP |

At the SMU level, `JTAG_IC_RESET_SMC_ENABLE=1`, `JTAG_IC_RESET_SEP_ENABLE=SEP`,
`JTAG_SEP_DBG_ENABLE=SEP`; debug resources are gated by `feat_ctrl`. See
`dv/oss/hw/sys/dtp/dv/docs/DTP_CSR.md` for full TDR field layouts.

## Part D: SEP System CSRs (`SEP=1`)

Reached over the crossbar `sep_in` aperture (or the SEP→SMC alias port):

| Register block | Contents | Verification relevance |
|----------------|----------|------------------------|
| `sep_system_csr` | SEP aperture (`sep_global_base`/`sep_region_size`), fuse-sense status, straps, timeout, debug-control | Aperture programmability, fuse-sense handshake |
| `sep_system_peripherals` | Outbound (32) / inbound (16) filters, local-master remap, `feat_ctrl` | Filter/remap coverage, lifecycle gating |
| SEP mailboxes | 8 mailboxes (see Part B) | Challenge-response interop |

> Note: SEP outbound/inbound filter and AP/STEE remap CSRs have RTL present but no
> dedicated OSS test anchor yet (see `SMU_FCOV.md` coverage gaps). SEP timeout
> CSRs are marked "unused for now" (BLOCKED).

## Register Verification Notes

| Topic | Requirement |
|-------|-------------|
| Crossbar apertures | Program `sep/smc_global_base` + `region_size` before injecting cross-port traffic; verify no-overlap SVA holds |
| Unmapped access | `ext_in` unmatched accesses must decode-error; `sep_out`/`smc_out` unmatched route to `ext_out` |
| Atomics | Confirm `ATOPs=0` rejection behavior (`smu_axi_atomic_operation_test`) |
| Mailbox setup | Resolve the submailbox stride hazard (Part B) before addressing submailbox index > 0 |
| SEP aperture | Exercise programmable-address bring-up (`smu_sep_smc_xbar_programmable_addr_test`) |
| Lifecycle gating | Verify DTP debug CSRs/TDRs fall back safely when `feat_ctrl` gates the resource |
| CDC | Reprogramming crossbar apertures with live traffic is not stability-checked (ISSUE-15); avoid mid-transaction remap in tests unless testing that path |

## Access Type Legend

| Symbol | Meaning |
|--------|---------|
| RW | Read/write |
| RO | Read only |
| Mixed | Read/write behavior depends on field or state |

## Revision History

| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0 | 2026-07-07 | OSS DV Team | Initial OCAH open-source SMU register/address reference, modeled on DTP_CSR.md; covers crossbar apertures, mailboxes (with the SEP submailbox stride hazard), DTP-reachable CSRs/TDRs, and SEP system CSRs |
