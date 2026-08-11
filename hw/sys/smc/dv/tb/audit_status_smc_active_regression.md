# SMC_ACTIVE_REGRESSION — DV 品質流程狀態圖

- **IP**: `SMC_ACTIVE_REGRESSION`（umbrella：`testlists/all.toml` leaf tests，不含 `deferred.toml`）
- **Milestone**: `L1-WAVE`（Skill 2 Layer-1 / `NO-CHECKBOX`；尚無 per-IP pin）
- **Pin**: none（`STANDALONE-REQUEST` until Skill 1 opens a real IP pin）
- **最後更新**: 2026-08-07T11:55:00+08:00
- **目前狀態**: **Blocking fix-loop** — DFX/zeroer/ecc/efuse_lc_neg Blocking closed；下一修 access_matrix
  ◀━━ 現在在這裡
- **Board path**: `hw/sys/smc/dv/tb/audit_status_smc_active_regression.md`
- **Sibling CG boards**: `audit_status_smc_clock_gating{,_p0,_p2}.md`（DFT 仍 #4413）

圖例：`[x]` 完成 ｜ `[!]` 阻擋中 ｜ `[ ]` 未開始 ｜ `◀━━ 現在在這裡`

---

## Scope

| Set | Count |
|---|---|
| Active leaf (`all.toml` transitive) | 107 |
| Prior grades (CLOCK_GATING + early smoke) | ~18 |
| **This L1 wave (was unaudited)** | **89 / 89 graded** |
| Sim seed=1 (L1 snapshot) | PASS **56** · FAIL **33** |
| Sim seed=1 (post remediation spot-check) | 原 33 FAIL → **PASS**（見 Fix note） |
| Deferred (out of scope) | 10 |

**Mode note:** `MODE=NO-CHECKBOX` / `STANDALONE-REQUEST` — Layer 1 only。`0/0 PROVEN — NOT READY` =
**no closure claim**（缺 pin/card），不自動等於 test 壞掉。Closure 需後續 Skill 1 IP pin + card + Layer 2。

---

## Progress

```
   [ ] Skill 1 per-IP pins (not started for non-CG)
   [x] Skill 2 L1 wave — 89 unaudited
   [x] Re-audit smc_register_sanity_test (PASS log after boot_stall pad-57)
   [x] Owner triage: sim FAIL remediation (addr map / pad / VIP / expectations)
   [x] L1 re-audit 97 NO-CHECKBOX on post-remediation PASS logs (run_id cursor/grok/4.5-reaudit-20260806)
   [ ] Blocking fix-loop → resim → reaudit  ◀━━ 現在在這裡
   [ ] Skill 1 → 1.5 → 2 CHECKBOX for prioritized IPs
```

### L1 rollup (89 grades — snapshot at first L1 wave close; superseded by 97 reaudit)

| Metric | Value |
|---|---|
| Schema valid | **89 / 89** |
| Findings (open) | 🔴 Blocking **62** · 🟠 Major **97** · 🟡 Minor **11** |
| Tests with ≥1 Blocking | **47** |
| PASS + Blocking (fake-pass risk) | **17** |
| FAIL + 0 Blocking (at L1 close) | **3** (`i3c_to_fabric`, `axi_error_response_depth`, `cpu_firmware_boot`) — **all now sim PASS** |

**Top tags:** `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (37B+32M) · `[NO-BLIND-DELAY-SYNC]` (25M) ·
`[EXACT-EXPECTATION]` (24M) · `[NO-ALWAYS-PASS-CHECKER]` (8B) · `[NO-DUMMY-DEAD-CODE]` (10m+5M)

### Fix note — remediation (2026-08-06)

- Boot stall pad **60→57** in `tb_top.sv` + `smc_cpu_vip_utils.BOOT_STALL_PAD`; `wait_fuse_sense_done` waits fuse_reset_n + rst_warm.
- Shared CSR map: `smc_addr_map.py` (`smc_addr` / `smc_indexed_addr` / bootrom `EXTERNAL_MANDATORY`); FAIL seqs converted off hand-copied `0xC000_…`.
- Fix-loop batch1 **DONE**: DFX `DEBUG_CTRL/BUS_MUX` via `smc_addr` (was false-identity `0xC001_0208/0210`); NDM per-reg symbols — shared seq `smc_ecc_dfd_dbs_sanity_test_seq`; 4 alias PASS + L1 `findings: []` (fixloop-20260806).
- Fix-loop batch2 **DONE**: zeroer baseline AFTER preload + JTAG readback oracle; PASS `163854`/`163858`; L1 Blocking closed (`dma_timeout` 🟡1 naming Minor only).
- Fix-loop batch3 **DONE**: `ecc_fault_inject` — removed TB `ecc_probe_fire`; score DUT `cpu_scratch0_inject_fire` via live scratch boot (`+smc_hold_cpu_boot` + `min_pass.ecc.hex`); PASS `20260807_034418`; L1 `findings: []`.
- Fix-loop batch4 **DONE**: `efuse_jtag_lc_negative` — PROD via `tb_lc_state`+`ej_axi`; NON_ID/write BLOCK (DECERR+BADCAB1E); ID ALLOW `resp=OKAY` (stub rdata not scored); LC_STATE exact; PASS `20260807_035201`; L1 `findings: []`.
- OCTS dual sync pads **58/59→55/56**; UART: `cocotbext-uart==0.1.4` in `.venv`.
- I3C / AXI-error: drop stub-SLVERR assumptions (HCI_VERSION / unmapped DECERR + GPIO_CTRL).
- Firmware boot: Python released wrong pad → **pad57**; PASS magic `0xacafaca1`, `rom_reads=36`.
- `smc_register_sanity_test` re-audited on PASS log `b81477fd…`.

### Sim FAIL list (33 at L1 close — all remediated to PASS)

`gpio_output_driveback` · `gpio_irq_type_matrix` · `i2c_master_target` · `i3c_to_fabric` ·
`smbus_pmbus` · `smbus_hostnotify` · `smbus_alert_ara` · `gpio_irq_active` · `sideband_protocol_smoke` ·
`avsbus_sanity` · `avsbus_status_depth` · `uart_spi_log_engine` · `uart_log_engine_reg_rw` ·
`uart_loopback` · `spi_loopback` · `octs_dual_sync` · `axi_error_response_depth` ·
`i2c_p1_rdwr_protocol` · `i2c_error_fifo_depth` · `efuse_jtag_lc_access_matrix` · `gpio_strap_sanity` ·
`external_interrupts` · `uart_log_engine_error_boundary` · `octs_sanity` · `cpu_firmware_boot` ·
`occp_sanity_secure_error` · `efuse_otp_burn_shadow` · `i2c_multi_instance` · `efuse_map_read` ·
`efuse_shim_ctrl` · `gpio_ctrl_full_sweep` · `telemetry_receiver_csr` · `gpio_intf_full_sweep`

---

## Grade table (this wave)

| # | Testcase | Sim | L1 findings | Grade |
|---|---|---|---|---|
| 1 | `smc_irq_observe_test` | PASS | none | `grades/smc_irq_observe_test_GRADE.md` |
| 2 | `smc_irq_multi_sample_test` | PASS | 🟡1 | `grades/smc_irq_multi_sample_test_GRADE.md` |
| 3 | `smc_gpio_observe_test` | PASS | 🟠1 · 🟡1 | `grades/smc_gpio_observe_test_GRADE.md` |
| 4 | `smc_gpio_multi_sample_test` | PASS | 🟡1 | `grades/smc_gpio_multi_sample_test_GRADE.md` |
| 5 | `smc_gpio_output_driveback_test` | **FAIL** | 🔴1 | `grades/smc_gpio_output_driveback_test_GRADE.md` |
| 6 | `smc_gpio_irq_type_matrix_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_gpio_irq_type_matrix_test_GRADE.md` |
| 7 | `smc_axil_idle_test` | PASS | 🔴1 · 🟠1 · 🟡1 | `grades/smc_axil_idle_test_GRADE.md` |
| 8 | `smc_axil_burst_idle_test` | PASS | none | `grades/smc_axil_burst_idle_test_GRADE.md` |
| 9 | `smc_combined_observability_test` | PASS | 🟡1 | `grades/smc_combined_observability_test_GRADE.md` |
| 10 | `smc_irq_during_powergood_glitch_test` | PASS | 🔴1 · 🟠1 · 🟡1 | `grades/smc_irq_during_powergood_glitch_test_GRADE.md` |
| 11 | `smc_5agent_observability_test` | PASS | 🟠1 | `grades/smc_5agent_observability_test_GRADE.md` |
| 12 | `smc_6agent_observability_test` | PASS | 🟠1 | `grades/smc_6agent_observability_test_GRADE.md` |
| 13 | `smc_mailbox_idle_test` | PASS | 🟠2 | `grades/smc_mailbox_idle_test_GRADE.md` |
| 14 | `smc_mailbox_data_error_test` | PASS | 🔴1 · 🟠1 | `grades/smc_mailbox_data_error_test_GRADE.md` |
| 15 | `smc_default_reg_rd_test` | PASS | 🟠2 | `grades/smc_default_reg_rd_test_GRADE.md` |
| 16 | `smc_register_boundary_depth_test` | PASS | 🟠1 | `grades/smc_register_boundary_depth_test_GRADE.md` |
| 17 | `smc_mailbox_irq_test` | PASS | 🟠3 | `grades/smc_mailbox_irq_test_GRADE.md` |
| 18 | `smc_i2c_master_target_test` | **FAIL** | 🔴2 · 🟠1 | `grades/smc_i2c_master_target_test_GRADE.md` |
| 19 | `smc_ijtag_basic_test` | PASS | 🟠1 | `grades/smc_ijtag_basic_test_GRADE.md` |
| 20 | `smc_jtag_reset_proxy_test` | PASS | 🟠2 | `grades/smc_jtag_reset_proxy_test_GRADE.md` |
| 21 | `smc_jtag_dmi_smoke_test` | PASS | 🟠1 · 🟡1 | `grades/smc_jtag_dmi_smoke_test_GRADE.md` |
| 22 | `smc_i3c_to_fabric_test` | **FAIL** | 🟠2 | `grades/smc_i3c_to_fabric_test_GRADE.md` |
| 23 | `smc_smbus_pmbus_test` | **FAIL** | 🔴3 · 🟠1 | `grades/smc_smbus_pmbus_test_GRADE.md` |
| 24 | `smc_smbus_hostnotify_test` | **FAIL** | 🔴2 · 🟠2 | `grades/smc_smbus_hostnotify_test_GRADE.md` |
| 25 | `smc_smbus_alert_ara_test` | **FAIL** | 🔴1 · 🟠2 | `grades/smc_smbus_alert_ara_test_GRADE.md` |
| 26 | `smc_flr_sanity_test` | PASS | 🔴1 · 🟠2 | `grades/smc_flr_sanity_test_GRADE.md` |
| 27 | `smc_input_output_fabric_wr_rd_test` | PASS | none | `grades/smc_input_output_fabric_wr_rd_test_GRADE.md` |
| 28 | `smc_local_fabric_csr_depth_test` | PASS | none | `grades/smc_local_fabric_csr_depth_test_GRADE.md` |
| 29 | `smc_cpu_to_sep_axi_test` | PASS | none | `grades/smc_cpu_to_sep_axi_test_GRADE.md` |
| 30 | `smc_cpu_ctrl_map_depth_test` | PASS | 🟠1 | `grades/smc_cpu_ctrl_map_depth_test_GRADE.md` |
| 31 | `smc_cpu_ctrl_scratch_window_test` | PASS | 🟠1 | `grades/smc_cpu_ctrl_scratch_window_test_GRADE.md` |
| 32 | `smc_efuse_otp_clock_test` | PASS | 🟠4 | `grades/smc_efuse_otp_clock_test_GRADE.md` |
| 33 | `smc_efuse_otp_clock_config_depth_test` | PASS | 🟠1 | `grades/smc_efuse_otp_clock_config_depth_test_GRADE.md` |
| 34 | `smc_efuse_chip_config_read_test` | PASS | 🟠4 | `grades/smc_efuse_chip_config_read_test_GRADE.md` |
| 35 | `smc_gpio_irq_active_test` | **FAIL** | 🔴1 · 🟠2 | `grades/smc_gpio_irq_active_test_GRADE.md` |
| 36 | `smc_sideband_protocol_smoke_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_sideband_protocol_smoke_test_GRADE.md` |
| 37 | `smc_input_fabric_axi_wr_rd_test` | PASS | none | `grades/smc_input_fabric_axi_wr_rd_test_GRADE.md` |
| 38 | `smc_avsbus_sanity_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_avsbus_sanity_test_GRADE.md` |
| 39 | `smc_avsbus_status_depth_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_avsbus_status_depth_test_GRADE.md` |
| 40 | `smc_avsbus_clock_config_proxy_test` | PASS | 🔴2 · 🟠1 | `grades/smc_avsbus_clock_config_proxy_test_GRADE.md` |
| 41 | `smc_uart_spi_log_engine_test` | **FAIL** | 🔴1 | `grades/smc_uart_spi_log_engine_test_GRADE.md` |
| 42 | `smc_uart_log_engine_reg_rw_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_uart_log_engine_reg_rw_test_GRADE.md` |
| 43 | `smc_uart_loopback_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_uart_loopback_test_GRADE.md` |
| 44 | `smc_spi_loopback_test` | **FAIL** | 🔴2 · 🟠1 | `grades/smc_spi_loopback_test_GRADE.md` |
| 45 | `smc_spi_pad_bfm_test` | PASS | 🟠1 · 🟡1 | `grades/smc_spi_pad_bfm_test_GRADE.md` |
| 46 | `smc_octs_dual_sync_test` | **FAIL** | 🔴1 · 🟠2 | `grades/smc_octs_dual_sync_test_GRADE.md` |
| 47 | `smc_zeroer_dma_timeout_test` | PASS | 🟡1 | `grades/smc_zeroer_dma_timeout_test_GRADE.md` |
| 48 | `smc_output_filter_remap_security_test` | PASS | 🟠2 | `grades/smc_output_filter_remap_security_test_GRADE.md` |
| 49 | `smc_ecc_dfd_dbs_sanity_test` | PASS | none | `grades/smc_ecc_dfd_dbs_sanity_test_GRADE.md` |
| 50 | `smc_dbs_idle_test` | PASS | none | `grades/smc_dbs_idle_test_GRADE.md` |
| 51 | `smc_multi_reset_csr_persistence_test` | PASS | 🔴1 · 🟠2 | `grades/smc_multi_reset_csr_persistence_test_GRADE.md` |
| 52 | `smc_axi_error_response_depth_test` | **FAIL** | 🟠1 | `grades/smc_axi_error_response_depth_test_GRADE.md` |
| 53 | `smc_output_fabric_wr_rd_responder_test` | PASS | none | `grades/smc_output_fabric_wr_rd_responder_test_GRADE.md` |
| 54 | `smc_output_fabric_slverr_inject_test` | PASS | none | `grades/smc_output_fabric_slverr_inject_test_GRADE.md` |
| 55 | `smc_mailbox_event_irq_test` | PASS | 🟠2 | `grades/smc_mailbox_event_irq_test_GRADE.md` |
| 56 | `smc_i2c_p1_rdwr_protocol_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_i2c_p1_rdwr_protocol_test_GRADE.md` |
| 57 | `smc_i2c_error_fifo_depth_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_i2c_error_fifo_depth_test_GRADE.md` |
| 58 | `smc_efuse_jtag_lc_negative_test` | PASS | none | `grades/smc_efuse_jtag_lc_negative_test_GRADE.md` |
| 59 | `smc_efuse_jtag_lc_access_matrix_test` | **FAIL** | 🔴3 · 🟠1 | `grades/smc_efuse_jtag_lc_access_matrix_test_GRADE.md` |
| 60 | `smc_efuse_permission_boundary_test` | PASS | 🟠5 · 🟡1 | `grades/smc_efuse_permission_boundary_test_GRADE.md` |
| 61 | `smc_gpio_strap_sanity_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_gpio_strap_sanity_test_GRADE.md` |
| 62 | `smc_external_interrupts_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_external_interrupts_test_GRADE.md` |
| 63 | `smc_uart_log_engine_error_boundary_test` | **FAIL** | 🔴1 | `grades/smc_uart_log_engine_error_boundary_test_GRADE.md` |
| 64 | `octs_sanity_test` | **FAIL** | 🔴1 · 🟠1 | `grades/octs_sanity_test_GRADE.md` |
| 65 | `smc_zeroer_sanity_test` | PASS | none | `grades/smc_zeroer_sanity_test_GRADE.md` |
| 66 | `smc_dma_sanity_test` | PASS | 🟠1 | `grades/smc_dma_sanity_test_GRADE.md` |
| 67 | `smc_dfd_sanity_test` | PASS | none | `grades/smc_dfd_sanity_test_GRADE.md` |
| 68 | `smc_cpu_ecc_lint_pint_depth_test` | PASS | none | `grades/smc_cpu_ecc_lint_pint_depth_test_GRADE.md` |
| 69 | `smc_cpu_sanity_test` | PASS | 🟠1 | `grades/smc_cpu_sanity_test_GRADE.md` |
| 70 | `smc_cpu_firmware_boot_test` | **FAIL** | 🟠2 | `grades/smc_cpu_firmware_boot_test_GRADE.md` |
| 71 | `smc_occp_sanity_secure_error_test` | **FAIL** | 🔴1 · 🟠2 | `grades/smc_occp_sanity_secure_error_test_GRADE.md` |
| 72 | `smc_efuse_otp_burn_shadow_test` | **FAIL** | 🔴1 · 🟠2 | `grades/smc_efuse_otp_burn_shadow_test_GRADE.md` |
| 73 | `smc_ecc_fault_inject_test` | PASS | none | `grades/smc_ecc_fault_inject_test_GRADE.md` |
| 74 | `smc_mailbox_inbound_test` | PASS | 🟠1 | `grades/smc_mailbox_inbound_test_GRADE.md` |
| 75 | `smc_i2c_multi_instance_test` | **FAIL** | 🔴1 | `grades/smc_i2c_multi_instance_test_GRADE.md` |
| 76 | `smc_efuse_map_read_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_efuse_map_read_test_GRADE.md` |
| 77 | `smc_efuse_shim_ctrl_test` | **FAIL** | 🔴1 · 🟠1 | `grades/smc_efuse_shim_ctrl_test_GRADE.md` |
| 78 | `smc_gpio_ctrl_full_sweep_test` | **FAIL** | 🔴2 · 🟡1 | `grades/smc_gpio_ctrl_full_sweep_test_GRADE.md` |
| 79 | `smc_uart_multi_instance_test` | PASS | 🔴1 | `grades/smc_uart_multi_instance_test_GRADE.md` |
| 80 | `smc_telemetry_receiver_csr_test` | **FAIL** | 🔴2 · 🟠1 | `grades/smc_telemetry_receiver_csr_test_GRADE.md` |
| 81 | `smc_cluster_cpu_infra_test` | PASS | 🔴2 · 🟠2 | `grades/smc_cluster_cpu_infra_test_GRADE.md` |
| 82 | `smc_remap_cla_test` | PASS | 🟠1 | `grades/smc_remap_cla_test_GRADE.md` |
| 83 | `smc_mailbox_multi_instance_test` | PASS | 🟠2 | `grades/smc_mailbox_multi_instance_test_GRADE.md` |
| 84 | `smc_filter_multi_entry_test` | PASS | none | `grades/smc_filter_multi_entry_test_GRADE.md` |
| 85 | `smc_gpio_intf_full_sweep_test` | **FAIL** | 🔴1 | `grades/smc_gpio_intf_full_sweep_test_GRADE.md` |
| 86 | `smc_mailbox_field_sweep_test` | PASS | 🟠2 | `grades/smc_mailbox_field_sweep_test_GRADE.md` |
| 87 | `smc_filter_field_sweep_test` | PASS | none | `grades/smc_filter_field_sweep_test_GRADE.md` |
| 88 | `smc_xvisor_remap_test` | PASS | 🟠1 | `grades/smc_xvisor_remap_test_GRADE.md` |
| 89 | `smc_cluster_beu_test` | PASS | 🔴1 · 🟠1 | `grades/smc_cluster_beu_test_GRADE.md` |

---

## 下一 session 指令

```
SMC_ACTIVE_REGRESSION：Blocking fix-loop（DFX/zeroer/ecc/efuse_lc_neg DONE）。
下一優先：
1. smc_efuse_jtag_lc_access_matrix_test — [TIMEOUT-MUST-FAIL] / golden
2. smc_multi_reset_csr_persistence_test — cool vacuity
3. occp / otp_burn — [NO-FORCED-INTERNAL-STATE]
每批：resim seed=1 → Skill2 reaudit → 更新本 board
CHECKBOX CG 10 筆留 CLOCK_GATING 板；DFT FAIL: cg_test_mode_bypass / cg_dft_reset_bringup
```
