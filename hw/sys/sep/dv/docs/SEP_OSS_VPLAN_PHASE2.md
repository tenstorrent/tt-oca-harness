<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS VPLAN — Phase 2 (basic-feature breadth)

> **Phase 2 — ACTIVE.** Breadth-first basic functional coverage: grow the Phase-1
> baseline of 32 testcases so that **every IP has its basic functional behavior
> covered**. Coverage intent comes from public RTL, specifications, and current
> tests. The closed Phase-1 record is in `verification_plan_phase1.adoc`. Per-test
> detail cards and the basic-feature ledger live in `SEP_OSS_VPLAN_PHASE2_DETAIL.txt`.

## Ground rules (summary)

- **Coverage completeness is primary; compression is the technique.** No-overlap,
 merge, and randomized-representative rules are the *means* to reach ≥60% with ~100
 tests, not the goal. When they conflict, completeness wins.
- **Source traceability gate.** Every Phase-2 basic-feature test traces to at
  least one public RTL, specification, test, sequence, or firmware source.
  Empty `OCAH-REFS` fields are rejected except for harness smoke tests.
- **In scope (Phase 2):** smoke/CSR/status sanity, real datapath/mode, the cross-
 subsystem happy path, plus the basic access-control and status-clear/RW1C contracts
 that make a basic test truthful.
- **Deferred (later phase):** advanced corner cases, error injection, security
 permutations, negative-path matrices — recorded as `GAP (deferred)` in the ledger.
- **No-Coding Gate.** A test is not ready for implementation until its detail card
 in `SEP_OSS_VPLAN_PHASE2_DETAIL.txt` is complete (owner, toml, ledger GAP closed,
 OCAH refs, mapping outcome, checker boxes, run/fuse mode, DV-infra, deltas).

## Top-Down Strategy — OSS-Unique Value (2026-06-25, two fresh-agent reviews)

**OCAH SEP DV is BOTTOM-UP** (IP-by-IP, ~700 tests, ~100% complete) — it is the authority
for **IP-internal** behavior. **OSS SEP DV is TOP-DOWN**: its unique value is the work OCAH's
per-IP testbenches *structurally cannot do* — **(A) system-integration / cross-IP edges** and
**(B) holes** OCAH's bottom-up approach leaves. Re-walking an IP's internal mode/feature matrix
on bare-sep, when OCAH already owns it ~100%, is **redundant** except for the thin slice where the
integration genuinely differs (real fabric routing, entropy bring-up, sideload, real CPU frontdoor,
status-clear/RW1C that makes a basic test truthful).

**Evidence this axis pays off:** OSS top-down testing in this project has already caught real bugs
OCAH's IP suites missed — the **mailbox IRQ truncation** (8→1 interrupt-vector loss), the
**inbound-filter inverted-polarity** security hole (#2868), and flagged ** KM×crypto KAT** as a
headline interconnect gap. All three are integration-seam / fan-in-out-packing bugs no single IP tb sees.

### Rep classification on the top-down value axis

| Class | Reps | Policy |
|---|---|---|
| **A — integration-edge** (cross-IP path OCAH's per-IP tb can't see) | CPU-1, CPU-2, CPU-3, FAB-1, FAB-2, SPI-3, EFL-2, EFL-3 | **Spine — keep as-is.** Highest OSS value. |
| **MIXED — A/B core + C tail** | MEM-2, EFL-1, KM-1 | Keep the integration core; trim the IP-internal tail. |
| **C — IP-internal-matrix** (re-derives OCAH-owned IP coverage; value = thin slice only) | FAB-3, RST-1, MEM-1, DMA-1, KM-2, CRY-1, CRY-2, CRY-3, SPI-1, SPI-2, PIO-1 | **Trim to the integration/status-clear slice** (one cell + its RW1C/lock/entropy-gate contract); defer the mode/variant breadth to OCAH. |

**Trim-to-slice — PROPOSED future re-tilt (NOT yet applied).** The table below is a recommendation for a
later scope decision; **the 22 basic-breadth reps remain as-planned in the counts/mapping rows for now**
(including KM-2, whose "drop" is a proposal, not a removal). Treat this as the re-tilt menu, not the
current planned set — it is applied only on explicit owner approval.

| Rep | KEEP (integration/truthful slice) | DEFER to OCAH (IP-internal breadth) |
|---|---|---|
| CRY-1 (AES) | CHK-ENTROPY: AES-masking PRNG reseed gated on real ESRC→DRBG→EDN bring-up (1 cell, e.g. CBC-256) | ECB/CBC/CTR × 128/192/256 NIST golden matrix |
| CRY-2 (HMAC) | 1 variant (SHA-512) wired + DONE RW1C over AXI — *no entropy/sideload edge; weakest rep* | SHA-256/384/512 × HMAC/plain golden matrix |
| CRY-3 (KMAC) | CHK-ENTROPY: EDN-masking-gated 1 cell + DONE RW1C | KMAC/SHAKE/cSHAKE SP800-185 golden (card itself flags it may be undeliverable) |
| DMA-1 | CHK-CFG-REGWEN busy-lock + CHK-DONE-RW1C | FIXED/INCR/WRAP × 1/2/4B copy matrix + reg-reset bash |
| FAB-3 | CHK-WOSET (write-once lock) + CHK-RO | alias/AP-STEE/in-/out-filter bank R/W bash (functional datapath is infra-gated/dead) |
| RST-1 | CHK-WKUP-EXPIRE RW1C + CHK-REGWEN-LOCK | raw WKUP-counter advance + WDOG-pet (wkup IRQ output is unused in sep) |
| MEM-1 | one CHK-WSTRB lane + CHK-SEQ (proves xbar→SRAM path) | full pattern/every-lane/boundary matrix |
| SPI-1 | CHK-PROGRAM + CHK-ERASE (TX complement of #3 RX) | dual/quad (single-bit BFM can't show lanes) |
| SPI-2 | CHK-ERR-W1C + CHK-INTR | reg-reset/R-W bit-bash + watermark breadth |
| PIO-1 | CHK-ERR-IRQ + CHK-FLUSH (RW1C/flush) | 64b TX/STATUS/WIRQT depth-model breadth |
| KM-2 | CHK-FLUSH-SEP (fold into KM-1) | raw FIFO STATUS/depth/separator mechanics — **drop standalone KM-2** unless Mode A proves uniquely reachable |

### Top-down integration / hole-hunt reps (TD-1..TD-4, PLANNED 2026-06-25)

These are integration-only / hole-hunt seams the 22 basic-breadth reps DON'T cover, all in the same
shared-resource / fan-in-out-packing bug class as the already-found bugs (mailbox 8→1 truncation, filter
polarity). **All four are in Phase-2 scope** — basic cross-subsystem happy-path + access-control/status-clear
contracts (TD-1 scoped to the basic "both complete + both take real EDN beats + membership" check; deep
fairness/starvation *stress* is deferred). Every one maps to a public source and
targets integration behavior that per-IP testbenches cannot reach.
Each has a full No-Coding-Gate card in the DETAIL file + a mapping row below.

| # | OSS test | Bucket | Seam / hole | OCAH provenance (verified) | Scenario steps | Checker idea | Stimulable now? |
|---|---|---|---|---|---|---|---|
| TD-1 | `sep_crypto_edn_multisink_arbitration_test` | `crypto` | TWO crypto-endpoint CLIENTS (AES+KMAC) contend the crypto round-robin arbiter (`u_axis_edn_crypto`, sep_crypto.sv:1015); #15's AES was the SOLE crypto client | `drbg/sep_drbg_real_sink_multi_rand_test` — stronger (real crypto-endpoint arbiter vs DRBG-level stub) | bring up entropy; overlap AES reseed/encrypt + KMAC op; prove overlapping AES/KMAC crypto-EDN beat windows; per-sink membership; compare both KAT goldens | AES+KMAC reseed in one window → both KATs pass + both sinks take real EDN beats + CHK-OVERLAP (overlapping beat windows) + per-sink membership (bit-exact per-sink routing-order = new infra, deferred — see card RISKS) | Yes (RANDCFG payload + scoreboard membership + entropy bring-up) |
| TD-2 | `sep_irq_simultaneous_fanin_no_alias_test` | `system` | Simultaneous multi-source assertion + anti-alias on `sep_internal_interrupts[8:31]` (crypto/KM/DMA); aggregator-level (like #14), NOT the CPU PIC path | `system/sep_irq_extended_connectivity_test` (the test that caught the mailbox bug) — re-express for non-mailbox bits | baseline one source; assert HMAC/KMAC/CSRNG/EDN together; prove exact vector/no alias; W1C-clear all sources | assert HMAC/KMAC/CSRNG/EDN done bits together → exact 1:1 bit map, no neighbor lights | Yes (sep_internal_interrupts_probe_o exists) |
| TD-3 | `sep_crypto_per_ip_reset_isolation_test` | `system` | Stateful neighbor survival during held HMAC/AES crypto results when a sibling `sep_sw_rst_no.<ip>` pulses; #19 covers the pulse + static non-corruption, not live-state survival | `clock/sep_clock_uvm_sw_reset_per_ip_test` — stronger (frontdoor live-result isolation vs HDL reset-wire observation) | bring up entropy; hold golden HMAC SHA-256 DIGEST + AES ECB-256 DATA_OUT; pulse AES reset and prove HMAC survives; rerun AES, pulse HMAC reset and prove AES survives | HMAC/AES held-result pair proves both directions; mid-round/all-pairs/KMAC/KM matrix deferred | Yes (frontdoor crypto results + entropy bring-up) |
| TD-4 | `sep_locked_field_access_irq_path_test` (TBD) | `efuse_lcc` | `sep_internal_interrupts[31]=locked_field_access` (sep.sv:466,787) — orphan source, no delivery test | `efuse/sep_efuse_uvm_shadow_permission_neg_test` (+ `otp_permission_neg`) — stronger (interrupt path vs denial-only) | real-sense PROD locked field; attempt locked access; prove bit31 + denial; clear/deassert real source; unlocked access stays quiet | PROD locked-field access → bit[31] asserts + clears via the REAL source path (sticky source CSR W1C, or deassert-after-access — prove-first); pairs with EFL-2 | Yes |

**Dropped (2026-06-25):** `sep_drbg_km_vs_crypto_endpoint_concurrency_test` (the former TD-4) was
**redundant with Phase-1 #15** `sep_drbg_real_sink_multi_km_aes_test`, which already drives KM keygen +
AES reseed/encrypt **concurrently** (true cocotb fork) with CHK-CONCUR + CHK5_axis1/CHK5_km membership +
CHK4 bit-exact partition. No genuinely-new *basic* edge remained (a 3-way KM+AES+KMAC saturation would be
stress, deferred); TD-1 still covers the distinct crypto-endpoint 2-client arbiter edge that #15 never
loaded. The remaining reps were **renumbered contiguously** — the locked-field test (formerly TD-5) is now
**TD-4 (TBD)**.

**Re-tilt direction (proposal):** keep the 8 A-reps + 3 MIXED cores as the spine, optionally collapse the
11 C-reps to their keep-slice (the proposed trim-to-slice table above — not yet applied), and these TD reps
add the integration/hole depth — moving the center of gravity from "re-prove every IP mode on bare-sep" to
"prove the integration and hunt the holes," the stated OSS mandate.

## Coverage Accounting Matrix (per subsystem)

Mindset checklist, not a vdb percentage (SV covergroups are compiled out under the
Verilator merge gate). `B` = basic axis in Phase-2 scope; `D` = deferred to a later
corner-case phase. Fill `done / partial / GAP` as the sweep proceeds; the per-IP
basic-feature ratio (≥60% read-off) lives in the ledger in the DETAIL file.

| Subsystem group | Owning toml | Smoke/CSR (B) | Datapath/mode (B) | Cross-subsystem (B) | Status-clear/RW1C (B) | Neg/err/sec-perm (D) | ≥60% read-off |
|---|---|---|---|---|---|---|---|
| CPU complex | cpu | baseline covered (CSR sweep = Phase-1 sep_address_map_test) | baseline/fw covered | mailbox→PIC covered; CPU-2 representative planned | existing mailbox RW1C lives in PIO/system; CPU-1/3 are reset-domain reps, not RW1C | CPU-1 needs dbg_rstb knob; timer/soft/ext IRQ tied-off deferred | planning read-off: ~13/16 baseline + CPU-2/3 planned; CPU-1 infra-gated until dbg_rstb is controllable |
| Fabric and security routing | system | baseline covered (#2 + FAB-3 CSR breadth VCS green) | baseline #16; FAB-2 inbound-rule VCS green | #20 global skip covered; FAB-2 per-entry rule VCS green | n/a-basic (no fabric RW1C; mailbox RW1C handed to Peripheral IO) | FAB-1 decode-error in scope; external-alias datapath/pressure/contention deferred | ≥60% planning read-off with 3 reps (FAB-1/2/3); FAB-2 allow/block/read_en/write_en proven in VCS, Verilator pending |
| Memory subsystem | memory | baseline SRAM smoke covered; MEM-1 SRAM breadth planned | MEM-1 byte-strobe/pattern/sequential planned; ROM read+execute baseline covered | DMA→DCCM covered by sep_dma_hash | n/a-basic (memory has no RW1C) | MEM-2 ROM write-ignored in scope; ECC/scrambler/stress deferred | ~6/6 planning read-off; 2 new reps (MEM-1/MEM-2); ROM no_cpu-unreachable (cpu only); SRAM single-beat/no-burst; scrambler off + ECC not-impl |
| Reset & timer glue | system | baseline covered (#1/#2 clock-gate; RST-1 WDT regs planned) | baseline #15/#19; RST-1 WKUP/REGWEN planned | WDT→NMI/bite covered; CPU reset-domain reps cross-referenced | bark RW1C covered; RST-1 wkup_expired RW1C planned | timeout+pause-sleep+CDC+JTAG-rst-ctrl RTL/infra-gated | planning read-off with 1 new rep (RST-1); CPU-1 remains infra-gated in CPU complex |
| DMA and data movement | cpu for DMA-1; system/SPI baseline cross-cover | DMA-1 reg/rw0c REGWEN planned | sep_dma_hash copy/SHA covered; DMA-1 modes/widths planned | hash SRAM→DCCM+IRQ, contention, SPI handshake covered | hash/contention RW1C covered; DMA-1 done/error RW1C planned | DMA-1 one opcode-error in scope; error-matrix/SHA384/abort deferred; SYS/SOC ASID infra-gated | planning read-off with 1 new rep (DMA-1); mode-specific goldens required before implementation |
| eFuse/lifecycle/security state | efuse_lcc | baseline sense/image; EFL-2 program/lock planned | lc_state_stitch covered; EFL-2 OTP program/direct-read planned | #20 sep_debug→filter and #17 JTAG/CPU mux covered; EFL-1 DEMOTE→KM planned | feat_ctrl golden per state covered; EFL-1 DEMOTE matrix + EFL-3 strap-secure_tm mask planned | dynamic-CSR secure_tm/SEC_DIS/token-mismatch/JTAG-RMA/timeout/ECC deferred | planning read-off with 3 new reps (EFL-1/2/3); EFL-3 needs a real sep_straps TEST_EN knob |
| KM and key distribution | km | KM-1 command set planned | sideload KAT quartet #4/#11/#12/#13 covered; KM-1 generate/revoke/shred planned | #15 multi-sink + #1 eFuse-arb covered; KM-1 sideload setup for shred proof planned | KM-2 mailbox IRQ RW1C planned; KAT RW1C covered | KM-1 one invalid-arg in scope; KDF(blocked)/fault-matrix/wipe/RMA deferred | ~7/7 planning read-off; 2 new `RAND-REP` reps (KM-1/KM-2); OCAH ~102→8 via merge + random |
| Crypto and entropy | crypto | engine CSR helpers exist; CRY sequence refactors planned | entropy CHK1-5 and sideload KATs covered; CRY-1/2/3 standalone modes planned | #15 multi-sink and KM→engine sideload covered | CRY-2/3 done RW1C planned; #11/#12 KAT RW1C covered | OTBN-PKA/health/multi-sink/ext-TRNG/alert deferred | planning read-off with 3 `RAND-REP` reps; real goldens/self-tests required before coverage is counted |
| Peripheral IO | system (PIO-1 mailbox); spi owns OpenTitan SPI sweep | #3 OT SPI cfg covered; PIO-1 mailbox CSR + SPI-2 host CSR planned | #3 flash READ+DMA covered; SPI-1 TX/PROGRAM/ERASE/dual/quad opcode planned | #3 SPI→DMA→SRAM and #8 mailbox→PIC covered; SPI-3 DMA-TX planned | #3 DMA RW1C and #8 mailbox IRQ RW1C covered; PIO-1/SPI-3 RW1C planned | clock-timing/type-policy deferred; Cadence-xSPI accepted-delta (licensed); GPIO/UART/I2C not-in-bare-sep | PIO-1 mailbox stays in system.toml; OpenTitan SPI is broken out into the dedicated in-scope SPI sweep (SPI-1/2/3, spi.toml). True SPI lane timing remains DV-infra-gated |

## Per-test Mapping Rows

One row per Phase-2 representative, added only after the ledger shows it closes a real
basic-feature GAP (start from the live `all.toml` baseline; strengthen before adding).
Detail card for each lives in `SEP_OSS_VPLAN_PHASE2_DETAIL.txt`.

Randomization labels used in the rows:
- `RAND-REP`: `MERGED_INTO` randomized representative that collapses an OCAH directed
 family or matrix into one seeded test.
- `RANDCFG`: directed `COVERED_BY` / `COVERED_STRONGER` representative with constrained-
 random point selection; mapping remains directed.
- `RAND-NONE`: no randomization intended (default when no label is shown).

Randomized/constrained-random plan: Phase 2 currently has **14** randomized reps:
**9 `RAND-REP`** tests and **5 `RANDCFG`** tests. Implemented random reps use
`reseed = 3` in their owning testlist for regression seed sweep.

| Type | Test | Random factors |
|---|---|---|
| `RANDCFG` | `sep_fabric_decode_error_response_test` | reserved-gap unmapped addresses, unmapped write target |
| `RANDCFG` | `sep_fabric_remap_filter_csr_bank_test` | region/entry indices, masked CSR field patterns, lock-entry choices |
| `RANDCFG` | `sep_wdt_aon_timer_internals_test` | bounded WKUP thresholds, WDOG bark values, lock values |
| `RANDCFG` | `sep_sram_datapath_breadth_test` | WSTRB mask order, legal SRAM offsets, data patterns, sequence length |
| `RANDCFG` | `sep_irq_simultaneous_fanin_no_alias_test` | vetted IRQ source subset, single-source baseline |
| `RAND-REP` | `sep_km_command_set_rand_test` | KM command args, key-generate request fields, engine shred mask |
| `RAND-REP` | `sep_km_mailbox_protocol_rand_test` | mailbox payload lengths, sequence values, separator placement |
| `RAND-REP` | `sep_aes_mode_keysize_rand_test` | key, IV/counter, plaintext, bounded block count across mode/key-size cells |
| `RAND-REP` | `sep_hmac_sha_variant_rand_test` | key length, key data, message length/content across SHA/HMAC cells |
| `RAND-REP` | `sep_kmac_mode_strength_rand_test` | key length/data, message, customization/prefix across KMAC/SHA3/SHAKE cells |
| `RAND-REP` | `sep_spi_ot_flash_cmd_rand_test` | flash address, length, data, sector/page-aligned command ranges |
| `RAND-REP` | `sep_spi_ot_host_csr_irq_rand_test` | legal CSR field values, watermarks, enable/mask settings |
| `RAND-REP` | `sep_spi_ot_dma_tx_test` | DMA length/trigger cells (`nwords` 7/11/15 -> chunks 2/3/4), flash address, data |
| `RAND-REP` | `sep_axil_mailbox_iface_rand_test` | WIRQT, FIFO fill lengths, payload words |

| # | OSS test | Subsystem | OCAH-REFS (≥1) | Mapping | Ledger GAP closed | toml | Run/Fuse | Status |
|---|---|---|---|---|---|---|---|---|
| CPU-1 | `sep_cpu_dbg_reset_independence_test` | CPU complex | clock `reset_assertion_deassertion` + `jtag_clock_independence` | COVERED_BY | CPU debug-reset domain isolation (dbg_rstb), frontdoor scope + WDT liveness contrast; JTAG-DTM debug-module reset proof deferred | cpu | no_cpu / +skip_fuse_sense | implemented; VCS dev-green + Verilator merge-gate green (`20260630_064551__verilator__all`, 3/3 CHK); GitHub #3218 Done |
| CPU-2 | `sep_pic_irq_source_map_delivery_test` | CPU complex | fw `otbn_plic_test` + system `irq_connectivity` | COVERED_STRONGER | PIC source-id map + real ISR claim for a **representative** 3-IP set (mailbox=1/OTBN=28/CSRNG=22; timer/soft/ext tied-off → deferred; full-vector isolation COVERED_BY #14) | cpu | cpu / +skip_fuse_sense | implemented; VCS dev-green + Verilator merge-gate green (`20260630_040428__verilator`, 6/6 CHK); GitHub #3219 Done |
| CPU-3 | `sep_warm_cold_reset_scratch_test` | CPU complex | clock `warm_reset_vs_cold_reset` | COVERED_STRONGER | warm/cold reset domains + dual scratch-bank retention (adds the cold-reset-clears-both leg + frontdoor/probe cross-check OCAH omits) | cpu | no_cpu / +skip_fuse_sense | implemented; VCS dev-green + Verilator merge-gate green (`20260630_064551__verilator__all`, 6/6 CHK); GitHub #3220 Done |
| FAB-1 | `sep_fabric_decode_error_response_test` | Fabric and security routing | fabric `sep_cpu_lsu_negative_matrix_test` + `sep_cpu_ifu_invalid_target_test` + `sep_fabric_xbar_error_closure_test` | COVERED_STRONGER | `[RANDCFG]` xbar decode-error / negative response (OCAH invalid-target anchors + reserved-gap unmapped reads + write target → exact DECERR) | system | no_cpu / +skip_fuse_sense | VCS dev-green (`20260625_124906__vcs`, RANDCFG + 4/4 CHK) + Verilator merge-gate green (`20260630_134050__verilator__all`; CHK-DECERR/DECERR-WR/OKAY/NONVAC); merged via PR #3256; GitHub #3226 Done |
| FAB-2 | `sep_fabric_inbound_filter_rule_matrix_test` | Fabric and security routing | fabric `sep_inbound_filter_blockbydefault_test` + `sep_inbound_filter_programming_ownership_test` | COVERED_STRONGER | inbound-filter per-entry RULE (block-by-default + allow-by-rule with rd/wr gating; src_id=0 match-all; src_id CSR R/W covered by FAB-3) + **CHK-OWNERSHIP** (2026-07-15): external master denied read+write of the filter's own config CSR 0x10A2_1000 with completed DECERR while CPU reads the rule — real port of OCAH `run_filter_ownership()` (prior claim was CSR-generic) | system | no_cpu + ext SMN master / real PROD fuse sense | VCS dev-green (`20260625_142624__vcs`, 5/5 CHK) + Verilator merge-gate green (`20260630_134050__verilator__all`; CHK-BLOCK-DEFAULT/ALLOW-RULE/READ-EN/WRITE-EN/NONVAC); merged via PR #3256; GitHub #3227 Done. CHK-OWNERSHIP added 2026-07-15 (VCS green; Verilator re-confirm in the main-sync regression) |
| FAB-3 | `sep_fabric_remap_filter_csr_bank_test` | Fabric and security routing | fabric `sep_fabric_64bit_regwidth_test` + `sep_outbound_filter_cfg_test` + `sep_cpuctrl_misc_regs_test` + system `sep_reg_sanity_test` (System-block RAL subset) | COVERED_BY | `[RANDCFG]` remap + filter CSR-bank R/W breadth (region/entry indices and masked field patterns) + 64-bit upper word + filter-locked woset + remap-valid RW + RO data_bus_width | system | no_cpu / +skip_fuse_sense | VCS dev-green (`20260625_125904__vcs`, RANDCFG + 8/8 CHK) + Verilator merge-gate green (`20260630_134050__verilator__all`; CHK-ALIAS-RW/VALID-RW/WOSET/INFILT-CFG/OUTFILT-CFG/AP-STEE-RW/RO/NONVAC); merged via PR #3256; GitHub #3228 Done |
| RST-1 | `sep_wdt_aon_timer_internals_test` | Reset & timer glue | clock `sep_clock_uvm_aon_timer_operation_test` + fw `wdt_cfg_lock_test` + `wdt_wkup_timer_test` + `wdt_pet_reset_test` | COVERED_STRONGER | `[RANDCFG]` WDT/AON-timer internals (bounded WKUP thresholds + WDOG_BARK pre/post-lock values); clk_wdt 8x-core sim-timing knob | system | no_cpu / +skip_fuse_sense | VCS dev-green (`20260625_130250__vcs`, RANDCFG + 6/6 CHK) + Verilator merge-gate green (`20260630_134050__verilator__all`; CHK-WKUP-COUNT/EXPIRE/CAUSE/WDOG-PET/REGWEN-LOCK/NONVAC); merged via PR #3256; GitHub #3229 Done |
| MEM-1 | `sep_sram_datapath_breadth_test` | Memory subsystem | sram `sep_sram_uvm_byte_strobe_test` + `byte_pattern_test` + `addr_boundary_test` + `sequential_access_test` + `write_read_test` | COVERED_BY | `[RANDCFG]` SRAM datapath breadth (all 36 contiguous WSTRB masks + randomized legal offsets/data/order, fixed boundary + seq cells; non-contiguous WSTRB infra-gated; SRAM is no-burst; `reseed = 3`) | memory | no_cpu / +skip_fuse_sense | implemented [RANDCFG]; VCS dev-green + Verilator merge-gate green (`20260630_074753__verilator`, 5/5 CHK); GitHub #3231 Done |
| MEM-2 | `sep_boot_rom_lsu_read_test` | Memory subsystem | rom `sep_rom_uvm_basic_read_test` + `sequential_read_test` + `content_verify_test` + `write_ignore_test` | COVERED_STRONGER | `[RAND-NONE]` boot ROM LSU data-read + write-silently-ignored (ROM is cpu-only, not no_cpu) | memory | cpu / +skip_fuse_sense | implemented; VCS dev-green + Verilator merge-gate green (`20260630_075013__verilator`, 4/4 CHK); GitHub #3232 Done |
| DMA-1 | `sep_dma_basic_test` | DMA and data movement | dma `sep_dma_uvm_reg_rw_test` + `cfg_regwen_test` + `range_regwen_test` + `addr_combo_test` + `mem_copy_test` (widths) + `err_opcode_test` | COVERED_BY | DMA CSR/REGWEN + copy address-mode/width breadth (full FIXED/INCR/WRAP × 1B/2B/4B) + one opcode-error (RW1C) | cpu | cpu / +skip_fuse_sense | implemented; VCS dev-green + Verilator merge-gate green (`20260630_051100__verilator`, 8/8 CHK); GitHub #3233 Done |
| EFL-1 | `sep_lcc_demote_feat_ctrl_matrix_test` (TBD) | eFuse/lifecycle/security state | lcc `sep_lcc_uvm_demote_comprehensive_test` (2.1) + `prod_dbg_flavour_test` (2.4) + `screening_vs_diagnostic_test` (3.5) | COVERED_BY | FEAT_CTRL DEMOTE matrix: DEMOTE_2/PROD_DBG_2 + DEMOTE_LOCK (distinct from #20 DEMOTE_1) | efuse_lcc | no_cpu / real PROD fuse sense | planned; GitHub #3234 Todo |
| EFL-2 | `sep_efuse_program_lock_matrix_test` (TBD) | eFuse/lifecycle/security state | efuse `sep_efuse_uvm_program_test` (1.1) + `direct_read_test` (0.5) + `permission_matrix_test` (1.3) | COVERED_BY | eFuse OTP program + deterministic physical-fail retry + write-once + direct-read + per-field LOCKS (distinct from #3 LC_STATE-only W1S) | efuse_lcc | no_cpu / real fuse sense | planned; GitHub #3235 Todo |
| EFL-3 | `sep_efuse_strap_secure_tm_latch_test` (TBD) | eFuse/lifecycle/security state | efuse `sep_efuse_uvm_shadow_strap_secure_tm_test` (2.3) | COVERED_BY | STRAP-driven secure_tm latch (TEST_EN strap → SECURE_TM at fuse-sense; FEAT_CTRL test-field mask) — the one genuine basic gap from the 2026-06-24 exhaustive sweep; needs a sep_straps TEST_EN knob in tb_top (real pin) | efuse_lcc | no_cpu / real fuse sense (TEST/DEV image) | planned; GitHub #3245 Todo |
| KM-1 | `sep_km_command_set_rand_test` (TBD) | KM and key distribution | km `cmd_hw_ver`/`cmd_rom_ver`/`cmd_stat`/`cmd_recov_ack`/`key_generate`/`key_revoke`/`engine_shred` (~10) | MERGED_INTO | `[RAND-REP]` KM command-set breadth (directed command walk + randomized legal args) | km | no_cpu / real fuse sense + km_rom_hex | planned; GitHub #3236 Todo |
| KM-2 | `sep_km_mailbox_protocol_rand_test` (TBD) | KM and key distribution | km `mailbox_cmd`/`resp`/`separator`/`flush`/`irq`/`overflow`/`underflow` (~10) | MERGED_INTO | `[RAND-REP]` KM mailbox mechanics: STATUS/separator/flush/IRQ RW1C | km | no_cpu / real fuse sense + km_rom_hex | planned; GitHub #3237 Todo |
| CRY-1 | `sep_aes_mode_keysize_rand_test` | Crypto and entropy | aes ECB/CBC/CTR × 128/192/256 (~5-8) | MERGED_INTO | `[RAND-REP]` AES standalone mode×key-size breadth (SW-key; distinct from #11 ECB-256 sideload); SepAesCfg SSOT walks all 9 {ECB,CBC,CTR}×{128,192,256} cells, per-cell ct==golden (FIPS-197+SP800-38A self-tested) + decrypt round-trip + no-alert + non-vacuity; found+fixed AES IV-ignored-when-non-idle ordering (load_key_iv waits idle between key/IV per programmers_guide) | crypto | no_cpu + bring_up_entropy / +skip_fuse_sense + +esrc_noise_force | implemented [RAND-REP]; Verilator merge-gate green (`20260701_074412__verilator`; 9 CHK-CELL + CHK-RAND-REP, TESTS=1 PASS=1); GitHub #3238 Todo→(In progress until full-suite regression) |
| CRY-2 | `sep_hmac_sha_variant_rand_test` | Crypto and entropy | hmac SHA256/384/512 × HMAC/plain + keylen (~7-10) | MERGED_INTO | `[RAND-REP]` HMAC SHA-variant breadth (distinct from #12 SHA256 sideload); GAP rep stronger than OCAH (OCAH has no SHA-384/512) — SepHmacCfg SSOT walks all 17 legal {SHA256,384,512}×{keyed all key-len, plain} cells, per-cell DIGEST==golden + RW1C done-clear + ERR-clean + keyed!=plain; golden RFC4231+FIPS-180 self-tested | crypto | no_cpu / +skip_fuse_sense | implemented [RAND-REP]; VCS not needed — Verilator merge-gate green 1st run (`20260701_070711__verilator`; CHK-CONV + 17 CHK-CELL + CHK-RAND-REP, scoreboard 934 chk/0 err, TESTS=1 PASS=1); independent OCAH-parity audit green; GitHub #3239 Todo→(In progress until full-suite regression) |
| CRY-3 | `sep_kmac_mode_strength_rand_test` | Crypto and entropy | kmac SHA3/SHAKE/cSHAKE/KMAC × 256/512 (~6-8) | MERGED_INTO | `[RAND-REP]` KMAC mode/strength breadth; new pure-Python Keccak golden (SHA3/SHAKE cross-checked vs hashlib, cSHAKE/KMAC vs NIST SP800-185) — SepKmacCfg SSOT walks 8 cells (SHA3-256/512, SHAKE/cSHAKE/KMAC-128/256), per-cell digest==golden + DONE-RW1C + ERR-clean + non-vacuity; distinct from #13 KMAC-256 sideload (cross-check only). Found KMAC needs mode=cSHAKE (#13's mode=Shake was non-standard) + cSHAKE needs non-empty customization | crypto | no_cpu + bring_up_entropy (KMAC masking reseeds from EDN) / +skip_fuse_sense + +esrc_noise_force | implemented [RAND-REP], audit-green; Verilator `20260701_153729__verilator` (TESTS=1 PASS=1, 0 logging errors) proves all 5 checkers — 8 each of CHK-DIGEST/CHK-DONE-RW1C (INTR_STATE.kmac_done set->W1C->0)/CHK-ERR/CHK-NONVAC (wrong-mode + KMAC wrong-key differ) + CHK-RAND-REP; VCS dev-green `20260701_153010__vcs`; GitHub #3240 -> In progress (full `all` regress gate remains for Done) |
| SPI-1 | `sep_spi_ot_flash_cmd_rand_test` | SPI (OpenTitan) | fw spi_ot `flash_write_read` + `sector_erase` | COVERED_STRONGER | `[RAND-REP]` CPU-firmware OT SPI flash command path: seeded legal address/word-count/data + WREN/PROGRAM/READ/ERASE/no-error + BFM golden; RDSR/WIP and dual/quad deferred; `reseed = 3` | spi | cpu / +skip_fuse_sense | implemented; VCS dev-green + Verilator merge-gate green (`20260630_103742__verilator`, 4/4 CHK + BFM golden); GitHub #3242 Done |
| SPI-2 | `sep_spi_ot_host_csr_irq_rand_test` | SPI (OpenTitan) | fw spi_ot `reg`/`interrupt`/`error_handling`/`watermark`/`enable_disable` (`accessinval`, timing, and mux-select deltas documented) | MERGED_INTO | `[RAND-REP]` OT SPI host CSR R/W + INTR mask/test + ERROR_STATUS W1C for drivable bits + TX watermark + enable gate; `reseed = 3` | spi | no_cpu / +skip_fuse_sense | implemented; VCS dev-green + Verilator merge-gate green (`20260630_115518__verilator`, 7/7 CHK); GitHub #3243 Done |
| SPI-3 | `sep_spi_ot_dma_tx_test` | SPI (OpenTitan) | fw spi_ot `dma_tx` + `dma_trigger` | COVERED_STRONGER | `[RAND-REP]` OT SPI DMA-TX datapath: seed-resolved length cells `[7,11,15]` walked in one run; SRAM data -> DMA HW handshake -> TXFIFO -> flash + BFM golden; trigger/TXWM evidence proven; `reseed = 3` | spi | cpu / +skip_fuse_sense | Done; Verilator merge-gate green (`20260630_133101__verilator`, 5/5 CHK + RAND-REP + BFM golden); GitHub #3244 Done |
| PIO-1 | `sep_axil_mailbox_iface_rand_test` | Peripheral IO | fabric `sep_mailbox_64bit_data` + `mailbox_misc_regs` (027) + `fifo_closure` (053) | MERGED_INTO | `[RAND-REP]` axil_mailbox TX breadth: 64b WRITE_DATA, STATUS visible bits, WIRQT/error IRQ RW1C, read-empty/write-full, flush; `reseed = 3` | system | no_cpu / +skip_fuse_sense | Done; Verilator merge-gate green (`20260630_132742__verilator`, 9/9 CHK + scoreboard 41/0); GitHub #3241 Done |
| TD-1 | `sep_crypto_edn_multisink_arbitration_test` | Crypto and entropy | drbg `sep_drbg_real_sink_multi_rand_test` | COVERED_STRONGER | crypto-EDN arbiter: AES+KMAC (2 crypto clients) contend `u_axis_edn_crypto`, both KATs pass + both take real EDN beats + CHK-OVERLAP (overlapping crypto-EDN beat windows) + per-sink membership (bit-exact per-sink routing-order = deferred new infra; #15's AES was the sole crypto client) | crypto | no_cpu / +skip_fuse_sense + entropy bring-up | Done; Verilator full-regression green (`20260702_035932__verilator__all`, 3 RANDCFG seeds PASS: CHK-NONVAC/BOTH-COMPLETE/BOTH-BEATS/OVERLAP/MEMBERSHIP, CHK1..CHK4 mismatch=0, CHK5_aes 32/32 + CHK5_kmac 6/6 each seed); GitHub #3247 Done |
| TD-2 | `sep_irq_simultaneous_fanin_no_alias_test` | Fabric & security routing (IRQ aggregator) | system `sep_irq_extended_connectivity_test` | COVERED_STRONGER | `[RANDCFG]` simultaneous CROSS-IP multi-source fan-in (subset >=2 + baseline from vetted HMAC/KMAC/CSRNG/EDN sources), full [8:31] anti-alias | system | no_cpu / +skip_fuse_sense | VCS dev-green (`20260625_125217__vcs`, RANDCFG + 4/4 CHK) + Verilator merge-gate green (`20260630_134050__verilator__all`; CHK-FANIN-MAP/ANTI-ALIAS/CLEAR/NONVAC); merged via PR #3256; GitHub #3248 Done |
| TD-3 | `sep_crypto_per_ip_reset_isolation_test` | Reset & timer glue | clock `sep_clock_uvm_sw_reset_per_ip_test` | COVERED_STRONGER | `[RAND-NONE]` stateful HMAC/AES held-result neighbor survival when a sibling SW-reset pulses (complements #19's pulse + static non-corruption; stronger than OCAH reset-wire observation) | system | no_cpu / +skip_fuse_sense + entropy bring-up | VCS dev-green (`20260625_150749__vcs`, RAND-NONE + 4/4 CHK) + Verilator merge-gate green (`20260630_134050__verilator__all`; CHK-NEIGHBOR-SURVIVES/SELF-RESET/REVERSE/NONVAC); merged via PR #3256; GitHub #3249 Done |
| TD-4 | `sep_locked_field_access_irq_path_test` (TBD) | eFuse/lifecycle/security state | efuse `sep_efuse_uvm_shadow_permission_neg_test` | COVERED_STRONGER | orphan `sep_internal_interrupts[31]` locked-field-access interrupt path (real trigger → assert → clear via the real source CSR/deassert path, prove-first); pairs with EFL-2 | efuse_lcc | no_cpu / real fuse sense (LC=PROD) | planned; GitHub #3250 Todo |
| _(more rows added per subsystem sweep)_ | | | | | | | | |

## Maturity Claim

A maturity number is cited from the basic-feature ledger + kept-log evidence, never
from testcase count (see "Maturity Claim Rule"). Record here, per subsystem: the
≥60% read-off, which representatives are proven by kept Verilator logs, which checker
boxes remain open, and the remaining `GAP` / `OSS_DELTA_ACCEPTED` items.

### Planning-phase status (all 9 subsystems swept — 2026-06-24)

**Phase-2 PLANNING is COMPLETE across all 9 subsystem groups.** Every group has a basic-feature
ledger (denominator/numerator + read-off) and No-Coding-Gate detail cards in
`SEP_OSS_VPLAN_PHASE2_DETAIL.txt`. **22 basic-breadth representatives (19 in the 9 subsystem sweeps + 3
in the in-scope OpenTitan SPI sweep) + 4 top-down integration/hole reps (TD-1..TD-4; a 5th candidate was
dropped as redundant with #15) = 26 total.** Planning is complete; **16 reps are now implemented and Verilator merge-gate green**
(CPU-1/2/3 + DMA-1; MEM-1/2 + SPI-1/2/3 + PIO-1; and the system bucket FAB-1/2/3 + RST-1 + TD-2/TD-3;
see **Evidence status** below), the other 10 remain `planned`. Full implementation + the Verilator merge gate of the
remaining reps are a later, separately-approved coding phase. The ≥60% basic-feature target is met by the read-offs below (mindset,
not a vdb number); the TD reps add the top-down integration/hole depth (see the Top-Down Strategy section).

| Subsystem | ≥60% read-off (stimulable basic) | New Phase-2 reps | Headline merge/defer |
|---|---|---|---|
| CPU complex | planning read-off: ~13/16 baseline + CPU-2/3; CPU-1 infra-gated | CPU-1/2/3 (TBD) | dbg_rstb controllability + timer/soft/ext IRQ tied-off deferred |
| Fabric & security routing | ≥60% planning read-off; FAB-1/2/3 Verilator merge-gate green; alias datapath deferred | FAB-1/2/3 (Verilator green) | AP/STEE+outbound+global-nonzero infra-gated; external-alias datapath deferred |
| Memory subsystem | ~6/6 planning read-off | MEM-1/2 (TBD) | ROM cpu-only; SRAM single-beat; ECC not-impl |
| Reset & timer glue | ~10/10 planning read-off | RST-1 (TBD) | heavily pre-covered; timeout/pause/CDC RTL-gated; CPU-1 infra-gated cross-ref |
| DMA & data movement | ~8/8 planning read-off | DMA-1 (TBD) | best pre-covered (3 Phase-1); SYS/SOC ASID infra-gated; mode-specific goldens required |
| eFuse/lifecycle/security | ~9/9 planning read-off | EFL-1/2/3 (TBD) | OCAH ~63→8; dynamic-CSR secure_tm/SEC_DIS/token-mismatch deferred |
| KM & key distribution | ~7/7 planning read-off | KM-1/2 (`RAND-REP`, TBD) | OCAH ~102→8; KDF blocked; wipe infra-gated |
| Crypto & entropy | ~9/9 planning read-off | CRY-1/2/3 (`RAND-REP`) | OCAH ~334→9; entropy fully covered; OTBN-PKA/health deferred; goldens required |
| Peripheral IO (mailbox) | mailbox basic planning read-off | PIO-1 (`RAND-REP`, system.toml) | axil_mailbox breadth; OT SPI broken out to its own SPI sweep row below; GPIO no bare-sep IP; UART/I2C not-instantiated |
| SPI (OpenTitan — dedicated sweep, IN-SCOPE) | ~6/6 OT SPI basic planning read-off | SPI-1/2/3 (TBD, spi.toml) | OpenTitan spi_ot: flash-cmd (SPI-1) + host-CSR/IRQ/error (SPI-2) + DMA-TX (SPI-3); Phase-1 #3/jedec cover config/RX/READ/DMA-RX. Cadence testplan/spi excluded (licensed); true dual/quad lane DV-infra-gated |

> **Note on the two OCAH counts:** the `OCAH ~N→M` figures in this per-subsystem table (e.g. KM ~102, Crypto ~334) are each sweep's RAW OCAH inventory (every directed/variant test counted in that sweep's denominator). The exhaustive cluster table further down (Target Accounting) RE-PARTITIONS OCAH by cluster and counts only the basic-relevant denominator (e.g. crypto-engines ~79 + entropy ~71), so its per-cluster numbers are deliberately smaller and are NOT meant to reconcile 1:1 with this table.

**Totals:** Phase-1 baseline 31 tests + **26 planned Phase-2 reps** (22 basic-breadth [19 subsystem-sweep
+ SPI-1/2/3] + 4 top-down integration/hole reps TD-1..TD-4) → ~57 representatives covering an OCAH SEP set
of ~700+ tests, via the no-overlap / merge / combined-per-group / randomized-representative techniques
(~10 of the 22 basic reps are randomized or combined-per-group reps that each subsume a directed family;
the 4 TD reps are integration-edge / hole-hunt, each a stronger re-expression of a verified OCAH test).

**Evidence status:** 16 of the 26 reps are implemented and Verilator merge-gate green. The system bucket **FAB-1, FAB-2, FAB-3, TD-2, TD-3, RST-1, PIO-1** (7) merged via **PR #3256** and is now **VCS dev-green + Verilator merge-gate green** in the full `all` run (`20260630_134050__verilator__all`; FAB-1 4 CHK, FAB-2 5 CHK, FAB-3 8 CHK, RST-1 6 CHK, TD-2 4 CHK, TD-3 4 CHK, PIO-1 9 CHK — all `TESTS=1 PASS=1 FAIL=0` incl. CHK-NONVAC non-vacuity). The **CPU-complex bucket** (CPU-1, CPU-2, CPU-3, DMA-1) is VCS dev-green + **Verilator merge-gate green** in the `all` run (`20260630_064551__verilator__all`; 3/3 / 6/6 / 6/6 / 8/8 CHK) and merged via **PR #3355**. The **Memory + SPI bucket** (this PR) -- **MEM-1** (`sep_sram_datapath_breadth_test`, `[RANDCFG]`), **MEM-2** (`sep_boot_rom_lsu_read_test`), **SPI-1** (`sep_spi_ot_flash_cmd_rand_test`), **SPI-2** (`sep_spi_ot_host_csr_irq_rand_test`), **SPI-3** (`sep_spi_ot_dma_tx_test`) -- is VCS dev-green + Verilator merge-gate green (per-rep logs + the full `all` run `20260630_134050__verilator__all`, 48/53; all five pass in-suite), each independently audited 100% OCAH parity or stronger. The remaining 10 reps stay `planned`.

The credit gate is unchanged: VCS-green is **development evidence only** -- no rep is *credited as proven* until a kept **Verilator** PASS log proves its checker boxes, and no maturity % is claimed beyond "planning complete; >=60% basic-feature ledger target met by read-off". The 5 failures in the `all` regression are the pre-existing, orthogonal KM-sideload quartet + `sep_drbg_real_sink_multi_km_aes` (GitHub #3266 KM-ROM-boot under all-concurrency), not caused by these buckets. Each rep also stays open until its OCAH-REFS are re-verified at implementation (OCAH is a moving target).

**Cross-cutting risks flagged on cards (to resolve at implementation, before coding the dependent CHK):**
- CPU-1 PROVE-FIRST: expose `dbg_rstb_i` as a controllable real DUT input before counting the rep.
- FAB-2 VCS-proven: per-entry inbound-filter rule enforcement frontdoor under `smc_global_base=0`.
- EFL-2 PROVE-FIRST: RTL guard (`efuse_guard`/shadow access-control) enforces the sensed LOCKS; deterministic fail injection proves retry.
- EFL-3 PROVE-FIRST: tb_top can expose `sep_straps.test_en` as a real-pin knob (today `sep_straps_idle='0`); pick a TEST/DEV image whose decoded FEAT_CTRL sets a test-group bit (else the secure_tm mask is invisible/vacuous).
- KM-2 PROVE-FIRST: SEP-side mailbox FIFO survives KM-held (else Mode A folds into KM-1).
- KM-1: command list and per-command evidence must match the claimed command family.
- CRY-1/2/3: refactor sequences, extend/build the AES(CBC/CTR/128/192), HMAC(384/512), KMAC(Keccak) goldens, NIST self-tested.
- CRY-3: KMAC/cSHAKE coverage requires a real SP800-185 golden; a cross-check fallback cannot count those cells.
- SPI-1: OcahSpiFlash true dual/quad lane + programmable WIP latency are DV-infra-gated; SPI-3 is cpu-mode unless a no_cpu proof lands first; PIO-1: split ERROR_FLAGS read-clear from IRQS W1C evidence.

### Phase-2 ≥60% Target Accounting — Planning Sweep (2026-06-24)

The ≥60% claim is a planning read-off from a multi-agent OCAH target sweep: the sweep enumerated the
OCAH SEP test set (~635-700 tests), classified BASIC vs ADVANCED, and mapped BASIC intents to
covered-by-Phase-1 / represented-by-planned-Phase-2 / GAP. The **basic-feature denominator** (what ≥60%
is measured against) is much smaller than the raw test count because **~60-70% of OCAH is ADVANCED**
(error-injection, stress, coverage-closure/P3, security-permutation, pressure) — explicitly deferred,
not in the denominator. No Phase-2 rep is credited as proven until a kept Verilator log proves its
checker boxes.

| Cluster | OCAH tests | BASIC | Covered (P1+rep) | Basic ratio | Genuine basic GAP |
|---|---|---|---|---|---|
| Crypto engines (AES/HMAC/KMAC/OTBN) | ~79 | 42 | ~38 | ~92% | within CRY-1/2/3 matrices (CFB/OFB deferred) |
| Entropy (ESRC/CSRNG/EDN/DRBG) | ~71 | 26 | 26 | ~100% | none (CHK1-5 strict; health-fail/ext-TRNG deferred) |
| KM | ~129 | 18 | 18 | 100% | none (KDF/RMA/wipe deferred) |
| Fabric + system | ~76 | 26 | 21 + 5 infra-gated | ~81% genuine→100% | 0 genuine (AP/STEE/outbound infra-gated) |
| eFuse + LCC | ~69 | 16 | 15 | ~94% | 0 (strap-driven secure_tm → now planned as EFL-3) |
| Clock/WDT/reset/CPU | ~57 | 35 | 31 | ~89% | 0 genuine (timeout-fire/lc-escalate/pause RTL-gated) |
| Memory + DMA | ~99 | 30 | 25 | ~83% | 0 genuine (ECC-not-impl/SYS-SOC-ASID/burst infra-gated) |
| SPI + mailbox | ~55 (43 in-scope) | 32 | 28 | ~88% | 0 genuine (lane-timing/clock-matrix deferred; Cadence licensed-out) |
| **TOTAL** | **~635-700** | **~225** | **~202 planned** | **~90% planning** | **0 open planned gaps; prove-first/infra gates remain** |

**Planning verdict: the ≥60% basic-feature target is met by audited mapping, not by implementation
evidence.** Why ~22 basic-breadth reps suffice for ~700 OCAH tests (the 4 TD reps are top-down depth on
top): (1) **advanced-deferral** —
~60-70% of OCAH is corner/stress/coverage-closure/security-permutation, out of the Phase-2 basic denominator;
(2) **compression** — the merge/combined/randomized reps each subsume a directed family (KM-1≈10 cmd tests,
KM-2≈10 mailbox, CRY-1/2/3 the engine matrices, SPI-1/2 the SPI families, FAB-2/3 the filter families);
(3) **Phase-1's 31 tests** already cover the heavy KATs + entropy CHK1-5 + sense/image.

**Genuine basic GAP found by the sweep — now represented by a planned rep:** eFuse **strap-driven secure_tm**
latch (OCAH efuse TEST 2.3 `sep_efuse_uvm_shadow_strap_secure_tm_test`) — a strap-pin variant distinct from
the dynamic-CSR secure_tm — is now planned as **EFL-3** (`sep_efuse_strap_secure_tm_latch_test`, TBD):
drive the `sep_straps.test_en` strap (a new real-pin tb_top knob) → `secure_tm` latches at fuse-sense →
FEAT_CTRL test-field mask is observed frontdoor. With EFL-3 planned, no open basic gap remains in the
planning matrix, but the knob is still a prove-first implementation gate.
Everything else is either
covered, advanced-deferred, RTL-gated (timeout-fire/lc-escalate/pause-in-sleep/ECC-not-impl), or
infra-gated (AP/STEE/outbound remap, SYS/SOC ASID, true SPI lane-timing) — all recorded in the ledgers.
The CRY-1/2/3 "gaps" the sweep flagged (CTR-192/256, HMAC-SHA384/512, KMAC KATs) are CELLS ALREADY INSIDE
those reps' randomized matrices — no new rep needed; the cards must just enumerate every cell.

_(populate as subsystems are swept and tests land)_
