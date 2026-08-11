# SMU_ALL Testcase Set Review — P2 (AMENDMENT DIFF — plan_revision 12)

**Your two decisions (amended records only):** (a) accept FL r3 additions as the inventory universe, (b) accept allocating the 11 new scenario/interaction keys onto `SMU_ALL_008` with explicit platform blockers (Option B; no new runnable mid-gate anchors; do not implement 008).

Rows: 8 current testcases + 32 unallocated.

## AMENDMENT SUMMARY (why this diff exists)

Triggered by Skill 3 reverse_diff CONFIRMED-OMISSION. Feature_list amended to r3 (six keys ADD).
Hard platform-gated new scenarios re-homed onto SMU_ALL_008. Draft never bless.

| Id | Prior | New | status |
|---|---|---|---|
| SMU_ALL_008 | approved r11 (53) | candidate r12 (64; +11 reverse-omission) | candidate |

## NEW / RE-OPENED testcases I am asking you to re-approve — 1

| Approve | Name | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| [ ] | SMU_ALL_008 smu_axi_crossbar_error_handling_test | Prove SEP=1 SMU 3x3 xbar connectivity/ID... | SMU 3x3 xbar connectivity matrix, SMN AX... | 64 | B |

### Scenario additions (all → SMU_ALL_008 r12)

| Scenario | To | Why on 008 |
|---|---|---|
| SMC-BOOT.S1 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| SMC-BOOT.S2 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| SMC-BOOT.S3 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| SEP-BOOT.S1 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| SEP-BOOT.S2 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| SMC-AXI-LITE-SHIMS.S1 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| SMC-AXI-LITE-SHIMS.S2 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| DTP-IJTAG-SCAN.S1 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| DTP-IJTAG-SCAN.S2 | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| INT-FUSE-SENSE-BOOT | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |
| INT-XBAR-APERTURE-INTEROP | SMU_ALL_008 r12 | platform-gated / harness blockers; Option B sink |

### Blockers on SMU_ALL_008 (allocation intent ≠ closure)

| Blocker | Affects |
|---|---|
| ISSUE-3582-sep_out-producer-unavailable | see OWNS / size_justification |
| WRAPPER-smu_axi_in-tied-off-needs-TB-unbind | see OWNS / size_justification |
| WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR | see OWNS / size_justification |
| WRAPPER-skip_fuse_sense-feat_ctrl-closed | see OWNS / size_justification |
| SYS-IN-BlockByDefault-needs-filter-program | see OWNS / size_justification |
| SEP0-feat_ctrl-tied-off-JTAG2AXI-gated | see OWNS / size_justification |
| DTP-OTP-STAP-needs-SEP1-and-real-LCC-feat_ctrl | see OWNS / size_justification |
| DTP-FEAT-GATE-needs-SEP1-real-LCC-feat_ctrl | see OWNS / size_justification |
| WRAPPER-xtrig-tied-off | see OWNS / size_justification |
| BARE-SEP0-no-sep-sysif-xbar | see OWNS / size_justification |
| SMC-BOOT-needs-ROM-firmware-or-wrapper-harness | see OWNS / size_justification |
| SEP-BOOT-needs-SEP1-TCM-preload-and-ISSUE-3582 | see OWNS / size_justification |
| AXIL-SHIM-needs-external-PLL-PVT-or-VIP-model | see OWNS / size_justification |
| IJTAG-BSR-needs-scan-loopback-or-scan-model | see OWNS / size_justification |
| INT-FUSE-SENSE-BOOT-needs-real-fuse-bringup | see OWNS / size_justification |
| INT-XBAR-APERTURE-INTEROP-needs-aperture-CSR-SF009 | see OWNS / size_justification |

## All current testcases (key inventory for lint)

| Approve | Id | Anchor | status | Scenarios | Tier |
|---|---|---|---|---|---|
| [ ] | SMU_ALL_001 | smu_wrapper_elaboration_sep_rtl_test | approved r2 | 6 | B |
| [ ] | SMU_ALL_002 | smu_axi_external_port_connectivity_test | approved r3 | 2 | B |
| [ ] | SMU_ALL_003 | smu_smc_smoke_test | approved r3 | 2 | B |
| [ ] | SMU_ALL_004 | smc_mailbox_int_test | approved r3 | 1 | B |
| [ ] | SMU_ALL_005 | smu_dtp_jtag_smoke_test | approved r2 | 3 | B |
| [ ] | SMU_ALL_006 | smu_clock_stop_coordination_test | approved r2 | 7 | B |
| [ ] | SMU_ALL_007 | smu_sep_smoke_test | approved r3 | 4 | B |
| [ ] | SMU_ALL_008 **(re-approve)** | smu_axi_crossbar_error_handling_test | candidate r12 | 64 | B |

## Scenarios NO testcase claims — 32 rows (unchanged acceptances this amend)

Accepting a row records you as the person who agreed to leave this hole open.

| Accept | Scenario | Reason | Evidence | Counts as |
|---|---|---|---|---|
| [ ] | DTP-OTP-AXIL.S3 | BLOCKED-BY-SPEC-FINDING | Open SF-007 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | INT-MBX-CHALLENGE-IRQ | BLOCKED-BY-SPEC-FINDING | Open SF-006 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | INT-PWRGOOD-DTP-POR | BLOCKED-BY-SPEC-FINDING | Open SF-001 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | INT-SEP0-OTP-ERR | BLOCKED-BY-SPEC-FINDING | Open SF-007 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SEP-MBX-IRQ-SMC.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-006 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SEP-SYSIF-SMU-XBAR.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-004 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMC-DECODE-APERTURE.S2 | BLOCKED-BY-SPEC-FINDING | Open SF-003 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMC-FAB-DUAL-NET.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-003 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMC-PWRGOOD-DTP-POR.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-001 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-MBX-CHALLENGE.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-006 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-PORT-CLK-RST.S2 | BLOCKED-BY-SPEC-FINDING | Open SF-001 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-PORT-SMN-AXI.S3 | BLOCKED-BY-SPEC-FINDING | Open SF-002 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-SEP-PARAM.S3 | BLOCKED-BY-SPEC-FINDING | Open SF-007 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-XBAR-APERTURE.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-009 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-XBAR-APERTURE.S2 | BLOCKED-BY-SPEC-FINDING | Open SF-009 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-XBAR-ATOP-REJECT.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-005 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-XBAR-ATOP-REJECT.S2 | BLOCKED-BY-SPEC-FINDING | Open SF-005 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | SMU-XBAR-ID-CONV.S1 | BLOCKED-BY-SPEC-FINDING | Open SF-002 blocks exact expectation for this key until the spec owner answers. | blocked |
| [ ] | DTP-IC-RESET.S2 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | DTP-XTRIG-CTP.S2 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | INT-BOOT-STALL-INTEROP | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SEP-FUSE-SENSE-HS.S3 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SEP-MEM-BOUND-PASSTHROUGH.S3 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SEP-SEC-DIS.S3 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMC-FAB-OUT-SMN.S2 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMC-FAB-OUT-SMN.S3 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMU-MBX-CHALLENGE.S3 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMU-SEP-SMC-ALIAS.S2 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMU-XBAR-APERTURE.S3 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMU-XBAR-BACKPRESSURE.S1 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMU-XBAR-BACKPRESSURE.S2 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |
| [ ] | SMU-XBAR-BACKPRESSURE.S3 | OUT-OF-MILESTONE | P3 corner/stress/contested-race; closes in milestone P3. | out-of-scope |

Boundary-rejected unallocated rows this amend: **none** (all six omission keys allocated on 008).

---
*Appendix: rendered from SMU_ALL_TESTCASE_PLAN.md @ candidate plan_revision 12, content_sha256 88105b6183cd67bac58be817e69b869ee69243a05489d75785276d07a3955af6, feature_list_sha256 4b37c7ba88aa0234689282eec80604a4181b7fec42e255479eaa83bf8f58455c, run dv_vplan_gen-SMU_ALL-P2-20260805T074000+0800-amend-reverse-omission.*
