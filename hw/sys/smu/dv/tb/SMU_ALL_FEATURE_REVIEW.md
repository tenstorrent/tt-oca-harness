# SMU_ALL Feature Semantics Review — P2 (AMENDMENT DIFF — feature_list artifact_revision 3)

**Your task:** confirm each feature's intent matches the SPEC's meaning.
Mark approve / reject / question. New keys highlighted first; others keep prior semantics (re-list for lint).

## AMENDMENT SUMMARY (Gate #1 re-opens for reverse_diff CONFIRMED-OMISSION keys)

Skill 3 reverse inventory CONFIRMED-OMISSION: six in-scope keys absent from approved FL r2.
Option B honesty: all six named by pinned SMU_SPEC / port_table at SMU boundary — **ADD**.
Boundary-rejected: **none**. Draft never bless.

| Key | Disposition | Scenarios |
|---|---|---|
| SMC-BOOT | **ADD** | 3 |
| SEP-BOOT | **ADD** | 2 |
| SMC-AXI-LITE-SHIMS | **ADD** | 2 |
| DTP-IJTAG-SCAN | **ADD** | 2 |
| INT-FUSE-SENSE-BOOT | **ADD** interaction | LIVE |
| INT-XBAR-APERTURE-INTEROP | **ADD** interaction | LIVE |

## Open questions (Critical/High SF) — unchanged this amend

- **SF-001..SF-009** remain open as on prior packet; SF-009 still blocks SMU-XBAR-APERTURE.S1/S2 exact CSR addresses (also relevant to INT-XBAR-APERTURE-INTEROP proof).

## Features — 42

| Approve | Feature | Intent | Spec | Scenarios |
|---|---|---|---|---|
| [ ] | SMC-BOOT **NEW** | SMC boots from ROM, releases resets, runs firmware, and reports status... | hw/sys/smu/doc/SMU_SPEC.md §Feature 1 (SMC Boot and Firmware... | 3 |
| [ ] | SEP-BOOT **NEW** | With SEP=1, real SEP RTL boots from TCM/ROM under SMU with reset relea... | hw/sys/smu/doc/SMU_SPEC.md §Feature 2 (Real SEP RTL Under th... | 2 |
| [ ] | SMC-AXI-LITE-SHIMS **NEW** | SMC AXI-Lite external shims (PLL/PVT/GPIO/eFuse/extension) are present... | hw/sys/smu/doc/SMU_SPEC.md §Interfaces (SMC AXI-Lite shims) ... | 2 |
| [ ] | DTP-IJTAG-SCAN **NEW** | DTP exports BSR and iJTAG DFD/DFT secure/non-secure scan host controls... | hw/sys/smu/doc/SMU_SPEC.md §Interfaces (BSR / STAP / iJTAG s... | 2 |
| [ ] | SMU-COMPOSE-BLOCKS | At the SMU boundary the subsystem presents composed SMC, SEP (when SEP... | hw/sys/smu/doc/SMU_SPEC.md §Overview / §Architecture §Block ... | 3 |
| [ ] | SMU-PORT-CLK-RST | External clocks and cold/power-good resets enter SMU and produce docum... | hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset @88ddf2482d1e542... | 3 |
| [ ] | SMU-PORT-SMN-AXI | An external SMN master/subordinate pair at smu_axi_in/out exchanges AX... | hw/sys/smu/doc/SMU_SPEC.md §Interfaces (External SMN AXI) / ... | 4 |
| [ ] | SMU-SEP-PARAM | Compile-time SEP selects real SEP+3x3 crossbar versus tied-off SEP pat... | hw/sys/smu/doc/SMU_SPEC.md §Configuration Parameters (SEP) /... | 3 |
| [ ] | SMU-XBAR-CONNECT | Each crossbar initiator may reach only its documented target set; a ma... | hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Crossbar routing con... | 3 |
| [ ] | SMU-XBAR-APERTURE | Firmware-programmed SEP/SMC aperture base/size CSRs determine which ad... | hw/sys/smu/doc/SMU_SPEC.md §Overview (CSR-programmed apertur... | 3 |
| [ ] | SMU-XBAR-ATOP-REJECT | An AXI atomic (ATOP) request presented to the SMU crossbar is rejected... | hw/sys/smu/doc/SMU_SPEC.md §Specifications (ATOPs=1'b0) / §E... | 2 |
| [ ] | SMU-XBAR-ID-CONV | Transactions leaving the crossbar toward SEP/SMC pass 10-bit→6-bit ID ... | hw/sys/smu/doc/SMU_SPEC.md §Specifications (ID widths) / §Su... | 2 |
| [ ] | SMU-XBAR-UNMAPPED | An external SMN access matching neither SEP nor SMC aperture receives ... | hw/sys/smu/doc/SMU_SPEC.md §Data Paths (ext_in has no defaul... | 2 |
| [ ] | SMU-XBAR-BACKPRESSURE | Concurrent SEP/SMC/external traffic under subordinate backpressure com... | hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (performance/backpress... | 3 |
| [ ] | SMU-SEP-SMC-ALIAS | SEP accesses in the fixed 0x4000_0000/1GB SMC region are remapped to 0... | hw/sys/smu/doc/SMU_SPEC.md §Data Paths (SEP→SMC alias remap)... | 3 |
| [ ] | SMC-FAB-DUAL-NET | Through SMU-integrated SMC fabric, manager transactions use AXI4 for h... | hw/sys/smc/doc/fabric.adoc §Dual-Network Architecture / §Tra... | 3 |
| [ ] | SMC-FAB-IN-PORTS | External masters entering SMC through sys_axi_in, jtag_axi_in, or sep_... | hw/sys/smc/doc/fabric.adoc §Traffic Subordinates (External A... | 3 |
| [ ] | SMC-FAB-OUT-SMN | SMC-initiated outbound transactions exit through output_axi after opti... | hw/sys/smc/doc/fabric.adoc §Outbound Traffic Flow / §Source ... | 3 |
| [ ] | SMC-DECODE-APERTURE | SMC resources are reachable identically via LOCAL_BASE 0xC000_0000 or ... | hw/sys/smc/doc/memmap.adoc §Memory Map (LOCAL_BASE / GLOBAL_... | 3 |
| [ ] | SMC-MBX-CHANNELS | SMC presents 32 AXI4-Lite mailbox channels (16 inbound + 16 outbound) ... | hw/sys/smc/doc/memmap.adoc §Detailed Address Map (Mailbox | ... | 3 |
| [ ] | SMU-MBX-CHALLENGE | SMC writes a token outbound; SEP reads inbound, verifies, writes compl... | hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-re... | 3 |
| [ ] | SEP-MBX-IRQ-SMC | SEP mailbox interrupt outputs enter SMC as sep_mailbox_interrupts_i[7:... | hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (smc_ma... | 2 |
| [ ] | SMC-MBX-IRQ-EXT | SMC mailbox external interrupts are presented on SMU ext_mailbox_inter... | hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (ext_ma... | 2 |
| [ ] | SMC-PWRGOOD-DTP-POR | SMC debounced power-good is the DTP pwr_on_rst_ni source so loss of po... | hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (DTP pwr_on_rst_... | 2 |
| [ ] | SMC-RST-PRIMARY-EXPORT | SMC-generated primary resets synchronized to ref and SMC clocks are ex... | hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (rst_pr... | 2 |
| [ ] | SMC-DTP-CSR | SMC (or JTAG2AXI via SMC map) accesses DTP control / cross-trigger CSR... | hw/sys/smc/doc/memmap.adoc §Detailed Address Map (DTP Contro... | 2 |
| [ ] | DTP-JTAG-PTAP | An external JTAG host exercises the DTP PTAP through SMU jtag_ptap_cli... | hw/sys/dtp/doc/overview.adoc §Key Features (JTAG Interface) ... | 3 |
| [ ] | DTP-JTAG2AXI-SMC | When enabled and lifecycle-permitted, DTP converts JTAG debug transact... | hw/sys/dtp/doc/jtag.adoc §DTP JTAG Topology (JTAG2AXI) / §Se... | 2 |
| [ ] | DTP-OTP-AXIL | DTP JTAG2AXIL masters drive SMC and SEP OTP debug AXI-Lite ports for f... | hw/sys/dtp/doc/jtag.adoc §DTP JTAG Topology (JTAG2AXIL OTP) ... | 3 |
| [ ] | DTP-BOOT-STALL | DTP boot-stall override/value outputs hold or release SMC boot sequenc... | hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_b... | 2 |
| [ ] | DTP-IC-RESET | When IC_RESET is enabled, DTP drives override enable/value structs to ... | hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (jtag_i... | 3 |
| [ ] | DTP-FEAT-GATE | SEP-driven lifecycle feature-control into DTP gates STAP selection, iJ... | hw/sys/smu/doc/SMU_SPEC.md §Security Considerations / §Error... | 3 |
| [ ] | DTP-CLKSTOP-AGG | DTP OR-combines JTAG jtag_clock_stop with aggregated CLA xtrig_clk_sto... | hw/sys/dtp/doc/clock_stop.adoc §Clock Stop @2f40548ea7872406... | 3 |
| [ ] | DTP-XTRIG-CTM | DTP CTM source/destination req/ack arrays route internal cross-trigger... | hw/sys/dtp/doc/overview.adoc §Cross Trigger Network / §Speci... | 3 |
| [ ] | DTP-XTRIG-CTP | DTP CTP req/ack dout/din/en buses provide Wire-OR and Point-to-Point c... | hw/sys/dtp/doc/overview.adoc §Cross Trigger Network (Wire-OR... | 2 |
| [ ] | DTP-STAP-SMC-SEP | DTP STAP hosts provide secondary TAP connectivity to SMC and SEP CPU d... | hw/sys/dtp/doc/overview.adoc §Secondary TAPs (SMC/SEP debug ... | 3 |
| [ ] | SEP-SYSIF-SMU-XBAR | SEP traffic leaving SEP-local decode routes via SMU crossbar apertures... | hw/sys/sep/doc/fabric.adoc §Transaction Routing / §Local and... | 3 |
| [ ] | SEP-LC-FEAT-EXPORT | SEP LCC exports lc_state and feat_ctrl to SMC and DTP; SMU presents lc... | hw/sys/sep/doc/lifecycle_controller.adoc §Life Cycle Control... | 3 |
| [ ] | SEP-SEC-DIS | The 256-bit SEP_SEC_DISABLE_TOKEN / SEC_DIS path into SEP enables life... | hw/sys/sep/doc/security_disable.adoc §Security Disable (SEC_... | 3 |
| [ ] | SEP-WDT-RST-SMC | SEP WDT timeout presents a reset request into SMC (active-low sep_wdt_... | hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP WDT timeout ... | 2 |
| [ ] | SEP-FUSE-SENSE-HS | SMC fuse_sense_done and SEP fuse_sense_done participate in the securit... | hw/sys/smu/doc/SMU_SPEC.md §Security Considerations (fuse-se... | 3 |
| [ ] | SEP-MEM-BOUND-PASSTHROUGH | SMU passes through SEP TCM/ROM/SRAM and crypto/KM memory macro req/rsp... | hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (sep_sr... | 3 |

## Required interactions — 9

| Approve | Interaction | Intent | Spec |
|---|---|---|---|
| [ ] | INT-FUSE-SENSE-BOOT **NEW** | Fuse-sense handshake participates in SMC/SEP security bring-up before/... | hw/sys/smu/doc/SMU_SPEC.md §Security Considerations (fuse-se... |
| [ ] | INT-XBAR-APERTURE-INTEROP **NEW** | Mailbox interop depends on crossbar connectivity plus programmed SEP/S... | hw/sys/smu/doc/SMU_SPEC.md §Feature 5 (xbar programmability)... |
| [ ] | INT-MBX-CHALLENGE-IRQ | Mailbox challenge-response must raise SEP→SMC mailbox interrupts on th... | hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-re... |
| [ ] | INT-FEAT-CTRL-DTP-GATE | SEP feat_ctrl export must gate DTP JTAG2AXI/STAP debug resources per l... | hw/sys/smu/doc/SMU_SPEC.md §Security Considerations / §Error... |
| [ ] | INT-PWRGOOD-DTP-POR | SMC power-good stability must qualify DTP TAP POR so power-good loss r... | hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (pwr_on_rst_ni =... |
| [ ] | INT-CLKSTOP-SMC-CLA | DTP clock-stop aggregation must include the SMC-reserved CLA port and ... | hw/sys/dtp/doc/clock_stop.adoc §Clock Stop @2f40548ea7872406... |
| [ ] | INT-SEP0-OTP-ERR | In SEP=0 configuration, DTP SEP-OTP AXI-Lite accesses must hit the SMU... | hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP=0 SEP-OTP) /... |
| [ ] | INT-ALIAS-VS-XBAR-SMC | SEP accesses to the fixed 0x4000_0000 SMC window must use the dedicate... | hw/sys/smu/doc/SMU_SPEC.md §Data Paths (SEP→SMC alias remap ... |
| [ ] | INT-BOOT-STALL-INTEROP | DTP boot-stall must be able to hold SEP while SMC progresses, then rel... | hw/sys/smu/doc/SMU_SPEC.md §Feature 5 (SMC-executes-while-SE... |

---
*Appendix: rendered from SMU_ALL_SPEC_FEATURE_LIST.md @ candidate artifact_revision 3, content_sha256 4b37c7ba88aa0234689282eec80604a4181b7fec42e255479eaa83bf8f58455c, pin_revision 1, run dv_vplan_gen-SMU_ALL-P2-20260805T074000+0800-amend-reverse-omission.*
