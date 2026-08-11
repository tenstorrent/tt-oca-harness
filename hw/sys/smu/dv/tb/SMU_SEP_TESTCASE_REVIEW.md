# SMU_SEP — Testcase Review Packet

## Decisions required

1. Is this the right testcase **set** for SMU_SEP P2?
2. Is the **OWNS** split pairwise correct (no silent double-count)?

### Newly proposed testcases (origin:derived)

_None in this revision._ All 16 plan records reuse pinned anchors (`origin: given`).

### Review-budget note (augment)

Pin lists 40 anchors; policy max_cards_per_packet is 16. This plan allocates 16 pinned anchors and leaves the remaining pinned names unused-this-rev (available for a P3 / packet-split amendment). Unused pinned names include e.g. smu_sep_axi_extension_decode_test, smu_sep_debug_bus_test, smu_sep_external_irq_test, smu_ic_reset_sep_ext_slice_test, and strict/AES/OTBN/WDT variants.

### Possible OWNS overlap to decide

- Contested: SEP-SMC-ALIAS-REMAP is owned by SEP_SMU_003, but SEP_SMU_004 allocates INT-ALIAS-MAILBOX which jointly proves alias+mailbox. Single-feature alias proof remains on 003; confirm this split.
- Contested: SEP-FEAT-CTRL-EXPORT.S1 on SEP_SMU_006 vs .S2/.S3 on SEP_SMU_007 — confirm profile vs variants partition.

## Allocated testcases (pinned reuse)

| ID | Anchor | Origin | OWNS | Scenarios | Approve set |
|---|---|---|---|---|---|
| `SEP_SMU_001` | `smu_sep_smoke_test` | given | Boot/reset/fuse/ROM foundation only (no xbar/mailbox/filter) | 8 | [ ] |
| `SEP_SMU_002` | `smu_fuse_sense_handshake_test` | given | sep_fuse_sense_done_o export only | 1 | [ ] |
| `SEP_SMU_003` | `smu_sep_smc_alias_remap_consistency_test` | given | Alias remap path and SMC aperture bound only | 3 | [ ] |
| `SEP_SMU_004` | `smu_sep_alias_mailbox_interrupt_probe_test` | given | Mailbox data + IRQ crossing only (alias used as transport) | 7 | [ ] |
| `SEP_SMU_005` | `smu_sep_smc_xbar_programmable_addr_test` | given | SMU xbar SEP ports only (not alias path) | 8 | [ ] |
| `SEP_SMU_006` | `smu_lifecycle_security_handoff_test` | given | LC state + feat_ctrl profile + security_disable export | 5 | [ ] |
| `SEP_SMU_007` | `smu_feat_ctrl_monitor_test` | given | feat_ctrl fail-closed and demote profiles only | 2 | [ ] |
| `SEP_SMU_008` | `smu_sep_wdt_reset_to_smc_test` | given | WDT bark vs bite into SMC IRQ path only | 3 | [ ] |
| `SEP_SMU_009` | `smu_sep_outbound_demux_decode_test` | given | Outbound demux decode only | 3 | [ ] |
| `SEP_SMU_010` | `smu_sep_filter_rule_matrix_test` | given | Inbound+outbound filter rule matrix only | 5 | [ ] |
| `SEP_SMU_011` | `smu_sep_ap_stee_output_remap_test` | given | AP/STEE remap regions only | 3 | [ ] |
| `SEP_SMU_012` | `smu_sep_memory_integrity_test` | given | TCM/SRAM/ROM port observability only | 3 | [ ] |
| `SEP_SMU_013` | `smu_sep_km_otbn_memory_test` | given | AES/OTBN/KM SMU-visible ports only | 3 | [ ] |
| `SEP_SMU_014` | `smu_sep_dma_test` | given | DMA CSR and TCM preload only | 2 | [ ] |
| `SEP_SMU_015` | `smu_sep_spi_bridge_test` | given | SPI req/IRQ mux only | 2 | [ ] |
| `SEP_SMU_016` | `smu_sep_efuse_test` | given | eFuse bank/command/JTAG-OTP only | 3 | [ ] |

## Unallocated gaps — Accept each row

| Key | Reason | Downstream (counts as) | Evidence | Accept |
|---|---|---|---|---|
| `SEP-COMPOSE-ENABLE.S2` | OUT-OF-MILESTONE | out-of-scope | SEP=0 compile-time tie-off matrix deferred to P3 | [ ] |
| `SEP-RESET-CONTROL.S4` | OUT-OF-MILESTONE | out-of-scope | reset-mid-window contested stress deferred to P3 | [ ] |
| `SEP-XBAR-APERTURE.S3` | OUT-OF-MILESTONE | out-of-scope | live aperture reprogram-under-traffic deferred to P3 | [ ] |
| `SEP-LC-STATE-EXPORT.S2` | OUT-OF-MILESTONE | out-of-scope | SEP=0 lc_state_o=8'hf0 build matrix deferred to P3 | [ ] |
| `SEP-SECURITY-DISABLE-EXPORT.S2` | BLOCKED-BY-SPEC-FINDING | blocked | blocked by open SF-005 (SEC_DIS token match exactness at SMU bind point) | [ ] |
| `SEP-SECURITY-DISABLE-EXPORT.S3` | BLOCKED-BY-SPEC-FINDING | blocked | blocked by open SF-005 (SEC_DIS token mismatch exactness) | [ ] |
| `SEP-TEST-MODE-SECURE-TM.S1` | OUT-OF-MILESTONE | out-of-scope | SECURE_TM latch timing matrix deferred to P3 | [ ] |
| `SEP-TEST-MODE-SECURE-TM.S2` | OUT-OF-MILESTONE | out-of-scope | SECURE_TM clear-on-reset matrix deferred to P3 | [ ] |
| `SEP-OUTBOUND-FILTER.S3` | BLOCKED-BY-SPEC-FINDING | blocked | blocked by open SF-001 (SMC-egress vs outbound filter relationship unspecified) | [ ] |
| `SEP-AXI-EXTENSION.S1` | OUT-OF-MILESTONE | out-of-scope | AXI extension port decode deferred to P3 (review-budget; pinned smu_sep_axi_extension_decode_test unused this rev) | [ ] |
| `SEP-AXI-EXTENSION.S2` | OUT-OF-MILESTONE | out-of-scope | AXI extension DECERR tie-off deferred to P3 | [ ] |
| `SEP-DEBUG-BUS-EXPORT.S1` | OUT-OF-MILESTONE | out-of-scope | debug bus export observability deferred to P3 (pinned smu_sep_debug_bus_test unused this rev) | [ ] |
| `SEP-EXTERNAL-IRQ.S1` | OUT-OF-MILESTONE | out-of-scope | SEP external IRQ pending deferred to P3 (pinned smu_sep_external_irq_test unused this rev) | [ ] |
| `SEP-EXTERNAL-IRQ.S2` | OUT-OF-MILESTONE | out-of-scope | SEP external IRQ clear deferred to P3 | [ ] |
| `SEP-IC-RESET-EXT-SLICE.S1` | OUT-OF-MILESTONE | out-of-scope | IC_RESET SEP slice assert deferred to P3 (pinned smu_ic_reset_sep_ext_slice_test unused this rev) | [ ] |
| `SEP-IC-RESET-EXT-SLICE.S2` | OUT-OF-MILESTONE | out-of-scope | IC_RESET SEP slice release deferred to P3 | [ ] |

## Appendix

- plan content_sha256: `62dbac82d1c065ca21815bcedd8f4cf3b3c66b695a976f21d4a9ded1df5ab1c2`
- plan_revision: 1
- feature_list_sha256: `a78ab08448e2271e9a4c9f9b4e85538f40fb53a553b5046d66d42732f8a5dcd4`
- anchor_mode: augment
