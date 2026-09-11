<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU feature list — designer review

Derived from the pinned specification only (sealed derivation, fresh sub-context; no RTL, no tests, no testlists were read). Every row cites the spec section it came from. Status of every record is `candidate`: nothing below is approved until the designer says so.

| Overall disposition | Reviewer | Reviewed at | Blocking comment |
|---|---|---|---|
| `PENDING` (`APPROVE` / `RETURN`) |  |  |  |

**Sources pinned:** `hw/sys/smu/doc/SMU_SPEC.md` @ `f2cb50de26b0`; `hw/sys/smu/doc/port_table.adoc` @ `b25ee97a3b26`

| Features | Scenarios | Contested-state scenarios | Interactions | Open spec questions |
|---:|---:|---:|---:|---:|
| 49 | 206 | 53 | 6 | 56 |

## 1. Questions that need a designer's answer

Each is a value or behaviour the specification does not pin. Until answered, every feature it names is derived on an assumption the reviewer has not confirmed. Sorted by severity.

| Decision | ID | Severity | Category | Question | Observed in spec | Features affected |
|---|---|---|---|---|---|---|
| `ANSWER` / `WAIVE` / `RETURN` | SF-001 | **Critical** | SF-MISSING | where is the aperture CSR block defined - what are the register offsets, the base and size field widths and encodings, their reset values, and which port (SMC local fabric, crossbar, or JTAG2AXI) accepts writes to them? | the crossbar apertures are described only as CSR-programmed. No register name, offset, field layout, bit width, reset value, or access port is given anywhere in the pinned sources, so the central in-scope behaviour cannot be stimulated from the specification alone. | `SMU-XBAR-APERTURE`, `SMU-XBAR-CONN`, `SMU-XBAR-DEFAULT`, `SMU-XBAR-DECERR` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-002 | **High** | SF-MISSING | what exactly does the crossbar return for an atomic transaction on each initiator port - which response code, on which channel, with how many beats, and is the write data drained? | AXI atomics are stated to be Rejected / not supported with ATOPs = 1 b0, but no observable response is given - no RRESP/BRESP encoding, no statement of whether the write data is consumed, and no statement of whether the transaction is answered at all. | `SMU-XBAR-ATOP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-003 | **High** | SF-MISSING | what is the required behaviour when the aperture CSR changes while a transaction decoded under the old map is in flight - must software quiesce first, does the fabric hold the old decode for in-flight beats, or is the outcome unconstrained? | the CDC notes say the crossbar addr_map is built combinationally from the CSR base and size and is not stability-checked against in-flight transactions, but no required behaviour is stated for a reprogram that overlaps an in-flight transaction. | `SMU-XBAR-APERTURE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-005 | **High** | SF-MISSING | what arbitration does the crossbar apply when two initiators target one target port, and is there a bound on the latency or a starvation guarantee a checker can assert? | performance and backpressure are named as verification areas, but the crossbar arbitration policy between concurrent initiators, any fairness guarantee, and any bounded-latency requirement are never stated. | `SMU-XBAR-CONN`, `SMU-XBAR-DEFAULT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-006 | **High** | SF-MISSING | how does axi_iw_converter behave when more distinct 10-bit IDs are outstanding than the 6-bit output space allows - does it stall the initiator, serialize, or is there a hard outstanding limit per port? | the 10-bit to 6-bit ID conversion into SEP and SMC is named but no conversion policy is given - no table depth, no outstanding-transaction limit, and no statement of whether the converter stalls, remaps or reuses IDs when the input ID space is oversubscribed. | `SMU-IDW-SEP`, `SMU-IDW-SMC` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-008 | **High** | SF-MISSING | for an unmatched ext_in access, what read data accompanies the DECERR, is every beat of a burst answered with DECERR, and is the write data phase consumed? | an unmatched ext_in access is stated to produce DECERR, but no read-data value, no per-beat response for a burst, and no statement of whether the write data phase is drained are given. The SEP=0 error slave by contrast does specify 0xBADCAB1E, so the omission here is visible against the spec own precedent. | `SMU-XBAR-DECERR` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-011 | **High** | SF-MISSING | what is the token width and the exact complement operation, which mailbox index is used in each direction, and is there a required completion window for the SEP response? | the mailbox challenge-response is called the primary real SMC to SEP interoperability path, but the token width, the definition of the complement, the mailbox index used in each direction, the required ordering, and any timeout are all absent, so no checker value can be derived. | `SMU-MBOX-XCHG` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-017 | **High** | SF-MISSING | what is the pulse-sync pulse width and the maximum request-to-destination latency, how is a source port mapped to destinations, and what value is driven on the acknowledge outputs while they are unused? | the CTM path gives no protocol timing - no pulse width for pulse-sync mode, no synchronization latency bound, no mapping from a source request on one port to a destination, and no statement of what the SMU drives on xtrig_ctm_dst_ack_o while acknowledgement is unused. | `SMU-XTRIG-CTM`, `SMU-XTRIG-MODE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-019 | **High** | SF-MISSING | what is the clock-stop handshake sequence and its acknowledge, what is the maximum latency from request to dtp_stop_clks_o, and what state must SMC reach before clocks may stop? | the clock-stop path names a DTP to SMC handshake but gives no sequence, no acknowledge signal, no bounded latency from xtrig_clk_stop_req_i to dtp_stop_clks_o, and no statement of what the SMC CLA does when clocks are stopped. | `SMU-CLKSTOP-REQ`, `SMU-CLKSTOP-OUT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-021 | **High** | SF-MISSING | what is the lc_state_o encoding, what does the doubling of LC_STATE_WIDTH represent (redundant copy, complement, or two independent fields), and what value corresponds to each lifecycle state? | the lifecycle state output is 8 bits, described only as 2 * LC_STATE_WIDTH, with one concrete value given (8 hf0 for SEP=0). The encoding of a lifecycle state, and the reason the field is doubled, are not stated, so no SEP=1 expected value exists. | `SMU-LC-STATE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-024 | **High** | SF-MISSING | when dbg_disable is asserted, what does a JTAG2AXI access to the SMC fabric do - is it dropped, does it return an error, or does it never complete - and which TDR reads back what for a blocked STAP selection? | dbg_disable gating is described qualitatively - STAP selection, iJTAG SIB access and the SMC fabric JTAG2AXI bridge are blocked, with the observable given only as BYPASS fallback or no AXI traffic. What a gated access actually does (silently dropped, error response, or no completion) is not stated. | `SMU-LC-DBGDIS` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-027 | **High** | SF-MISSING | what is the required order and relative timing of the SMU reset outputs, and how many synchronizer stages define the deassertion delay in each domain? | the reset outputs and their domains are listed but no sequencing is specified - no required assertion or deassertion order between rst_cold_stable_ref_clk_no, rst_primary_ref_clk_no and rst_primary_smc_clk_no, and no synchronizer stage count or cycle budget. | `SMU-RST-COLD`, `SMU-RST-PRIMARY` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-028 | **High** | SF-MISSING | which reset outputs does ext_boot_seq_done_i gate, and is there a timeout or a defined held state if it never asserts? | ext_boot_seq_done_i is said to gate reset release, but which resets it gates and what happens if it never asserts are not stated, so neither the held state nor a timeout expectation can be pinned. | `SMU-BOOTSEQ-GATE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-029 | **High** | SF-CONFLICT | which signal is the DTP power-on reset - the SMC-qualified powergood_stable, or rst_cold_ni directly - and if both contribute, how are they combined? | the clock and reset section states that DTP uses pwr_on_rst_ni = powergood_stable, taken from the SMC powergood_stable_o, as its power-on reset, while the port table states that rst_cold_ni also serves as the DTP power-on reset. The two sources name different sources for the same reset. | `SMU-PWRGOOD`, `SMU-RST-COLD` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-036 | **High** | SF-MISSING | which downstream resets can the IC_RESET TDR override, and what SMU-level observable shows an override is active? | the IC_RESET TDR is said to override downstream resets, but the set of overridden resets is never named and no observable is given for an override being in effect. | `SMU-ICRESET` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-049 | **High** | SF-MISSING | where are ISSUE-7, ISSUE-9 and ISSUE-16 recorded, and is the ISSUE-16 outbound-filter bypass an accepted behaviour or a defect that changes the expected SEP egress path? | three open review items are cited by identifier only - ISSUE-16 on SMC-egress SEP outbound traffic bypassing the SEP outbound filter, ISSUE-9 on SEP eFuse shadow_regs tied 0 at the wrapper, and ISSUE-7 on SEP mailbox interrupt observation - together with a source file smu_rtl_suspected_issues.md that is not a pinned source. The claims they carry, one of which is a security bypass, cannot be resolved. | `SMU-XBAR-CONN`, `SMU-EFUSE-SHIM-SEP`, `SMU-SEP-MBOX-IRQ` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-004 | **Medium** | SF-MISSING | are overlapping apertures illegal by construction, prevented by the CSR, or merely undefined - and if a design assertion fires, what is the functional expectation at the port? | a no-overlap SVA is listed as a crossbar verification-relevant property, but the specification never states the requirement it checks nor the behaviour when software programs overlapping SEP and SMC apertures. | `SMU-XBAR-APERTURE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-007 | **Medium** | SF-MISSING | how are the two additional crossbar ID bits formed on the way in, and what guarantees the original 8-bit inbound ID is restored on the response? | the 8-bit maximum input ID is stated to become a 10-bit crossbar ID, but the widening rule is not given - whether the two added bits encode the initiator port index, are zero-extended, or are allocated some other way, and how the response path restores the original value. | `SMU-IDW-IN` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-009 | **Medium** | SF-AMBIGUOUS | when the external SMN port is unused and tied off, what terminates an unmatched sep_out or smc_out access - is there an internal timeout or error terminator, or is tying the port off only legal when no unmatched access can occur? | ext_out is the catch-all for unmatched sep_out and smc_out accesses, while the outbound response port is documented as tie to 0 if unused. With the port tied off an unmatched internal access has no terminating agent and the specification does not say what releases the initiator. | `SMU-XBAR-DEFAULT`, `SMU-EXT-SMN` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-010 | **Medium** | SF-MISSING | is the alias remap applied to both read and write channels, and what is the required behaviour for a burst that starts inside the 1 GB window and would cross its top - is it truncated, errored, or illegal by construction? | the SEP to SMC alias window is given an exact base, size and alias base, but nothing is said about a burst that starts inside the window and would cross its upper boundary, nor about whether the remap applies to reads, writes or both. | `SMU-ALIAS-REMAP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-012 | **Medium** | SF-MISSING | what is the bit-index to SMC interrupt-source mapping, what polarity and sensitivity does each line have, and are the lines synchronized inside the SMU or required to be synchronous already? | 256 external interrupts are aggregated to SMC, but there is no mapping from ext_interrupts_i bit index to an SMC interrupt source, no polarity, no level-versus-edge statement, and no synchronization requirement for a source asynchronous to clk_smu_i. | `SMU-INT-AGG` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-013 | **Medium** | SF-MISSING | which SMC mailbox drives each bit of ext_mailbox_interrupts_o, and what event sets and clears it? | the 32-bit mailbox interrupt output is declared, but which mailbox drives which bit, and what sets and clears a bit, are not stated. | `SMU-MBOX-IRQ-OUT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-014 | **Medium** | SF-UNTESTABLE | is there an SMU boundary observation for the SEP mailbox interrupts, or is this behaviour only verifiable inside the SEP subsystem - and where is ISSUE-7 recorded? | the SEP mailbox interrupts are described as an internal [7:0] signal with no SMU boundary port, to be observed via the wrapper with a note pointing at ISSUE-7, which is not among the pinned sources. No SMU-level observation point is pinnable. | `SMU-SEP-MBOX-IRQ` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-015 | **Medium** | SF-CONFLICT | which indices of the CTM arrays are externally assignable - [7:2] with [1:0] reserved, or all of [7:0] with the reservation applying only inside DTP? | the specification table says there are 8 external CTM ports with DTP [1:0] reserved for SMC, while the port table describes the same array as SMU external ports [7:0]. With XTRIG_NUM_INT_CT = 8 the two statements claim the same two indices are both SMC-reserved and externally assignable. | `SMU-XTRIG-CTM` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-016 | **Medium** | SF-CONFLICT | is xtrig_clk_stop_req_i[0] usable by an external requester or is it consumed internally by SMC, and if the latter what is an external driver of that bit expected to see? | the specification table says there are 8 clock-stop request ports with DTP [0] reserved for SMC, while the port table describes the same array as SMU external ports [7:0] with port [0] reserved for SMC internally. | `SMU-CLKSTOP-REQ` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-018 | **Medium** | SF-MISSING | which clause of OCAH Cross Trigger v1.0 defines the CTP wire-OR and P2P encodings, and what drives each of the four signals in each of the four port groups in each mode? | the CTP wire-OR and P2P protocols are named and OCAH Cross Trigger v1.0 is listed as a standard, but no clause is cited and the encoding of the four dout, dout_en, din and din_en signals per group, and the direction-control rule, are not given in the pinned sources. | `SMU-XTRIG-CTP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-020 | **Medium** | SF-MISSING | what is the DefaultCfg value of XTRIG_INT_CT_MODE, and which modes are legal per cross trigger? | XTRIG_INT_CT_MODE is listed with the default config-dependent, so the mode of the non-reserved cross triggers cannot be pinned to any value. | `SMU-XTRIG-MODE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-022 | **Medium** | SF-MISSING | what condition asserts lc_sigint_err_o, is it sticky or does it follow the fault, and what does it read when SEP=0? | lc_sigint_err_o is declared as a lifecycle signal integrity error with no assertion condition, no clearing rule, and no stated value in a SEP=0 build. | `SMU-LC-SIGINT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-023 | **Medium** | SF-MISSING | what do the four codes of each lcc_demote_state output mean, what distinguishes state 1 from state 2, and what are they driven to when SEP=0? | the two lifecycle demote outputs are 2 bits each with no encoding, no explanation of why there are two, no relation to the SMC lifecycle-demote function listed in the sub-block table, and no SEP=0 value. | `SMU-LC-DEMOTE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-025 | **Medium** | SF-MISSING | what is the security_disable encoding, what does SMC do differently when it is asserted, and is any of that observable at the SMU boundary? | SEP is stated to drive security_disable into SMC, but the signal width and encoding, the SMC behaviour it changes, and any observable at the SMU boundary are not given. | `SMU-LC-SECDIS` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-026 | **Medium** | SF-MISSING | what is the fuse-sense sequence and its ordering against reset release, how long is the delay on fuse_reset_n_delayed_o, and must SMC and SEP fuse sense complete in a particular order? | the fuse-sense handshake is named as part of security bring-up, but no sequence is given - the relation between fuse_sense_done_o and sep_fuse_sense_done_o, the delay that defines fuse_reset_n_delayed_o, and the ordering against reset release are all absent. | `SMU-FUSE-SENSE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-030 | **Medium** | SF-AMBIGUOUS | what debounce or qualification produces powergood_stable from powergood_i, and is powergood_stable_o exposed anywhere an SMU-level test can sample it? | powergood_stable is used as the DTP power-on reset source but the qualification that turns powergood_i into powergood_stable is not described, and powergood_stable_o does not appear in the port table, so the intermediate signal cannot be observed or timed. | `SMU-PWRGOOD` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-031 | **Medium** | SF-MISSING | what does SMC do on receiving the SEP watchdog reset request, within what latency, and what SMU-level observable shows that it happened? | the SEP watchdog timeout is said to produce a SEP reset request into SMC, but what SMC does with it, over what latency, and whether the request or its effect is observable at the SMU boundary are not stated. | `SMU-SEPWDT-RST` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-032 | **Medium** | SF-MISSING | which watchdog drives wdt_first_timeout_o and wdt_second_timeout_o, are they sticky until a reset, and how do they relate to the SEP watchdog path? | the two watchdog timeout outputs are declared with a consumer but no source is named, no assert or clear semantics are given, and their relation to the SEP watchdog reset request is not stated. | `SMU-WDT-TIMEOUT`, `SMU-SEPWDT-RST` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-033 | **Medium** | SF-MISSING | what is CPU_CLUSTER_COUNT for the SMU, and what is the handshake between ndmreset_request_i and ndmreset_process_o? | the non-debug-module reset ports are sized by CPU_CLUSTER_COUNT, which is never given a value in the pinned sources, and the request-to-process protocol is not described. | `SMU-NDMRESET` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-034 | **Medium** | SF-MISSING | what are the fields of reset_ctrl_t, what is the isolate to reset to complete sequence per subsystem, and what does cfg_flr_pf_active_i change? | the 32-subsystem isolation and reset control ports are declared but reset_ctrl_t content, the sequencing protocol, the meaning of the ss_reset_complete_i default of 32 hFFFFFFFF, and the effect of cfg_flr_pf_active_i are all unstated. | `SMU-SSRESET` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-035 | **Medium** | SF-UNTESTABLE | is any SMU-level expectation intended for jtag_ic_reset_ext_o beyond the disabled tie-off, or is this port verifiable only at the integrator level? | the external IC_RESET override slice has an integrator-defined type that the SMU explicitly does not define, so no expected value for the port can be derived at the SMU boundary beyond its tie-off when the feature is disabled. | `SMU-ICRESET` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-037 | **Medium** | SF-MISSING | what mechanism asserts the DTP boot-stall, and what SMU-level observable distinguishes a stalled SMC from one that has not yet started fetching? | boot-stall is named as a DTP function interacting with SMC boot, but no mechanism is given - no JTAG instruction, no register, no SMC-side signal, and no observable for SMC being stalled. | `SMU-BOOTSTALL` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-038 | **Medium** | SF-MISSING | what address window and data width does the DTP JTAG2AXI bridge present into the SMC local fabric, and what observable effect does the pipeline depth have? | the JTAG2AXI bridge into the SMC local fabric is named with a pipeline depth of 3 but no address window, no data width, and no statement of the AXI protocol variant on that path, so no access can be constructed from the specification. | `SMU-JTAG2AXI-SMC` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-039 | **Medium** | SF-MISSING | what is the address map of the SMC and SEP OTP as seen through the OTP-over-JTAG AXI-Lite bridge, and what response is expected for a legal and for an illegal offset? | the OTP-over-JTAG path is given as AXI4-Lite 32/32 with no address map for the SMC or SEP OTP and no expected response, so an access can be driven but nothing about its result can be checked. | `SMU-OTPAXI-SMC`, `SMU-OTPAXI-SEP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-041 | **Medium** | SF-MISSING | what does the SEP=0 SEP-OTP error slave return for a write, and is 0xBADCAB1E the full 32-bit read data for every offset? | the SEP=0 SEP-OTP error slave is specified as DECERR with 0xBADCAB1E, but only for what appears to be a read; the write response and whether the pattern appears on the full 32-bit data are not stated. | `SMU-SEPOTP-ERRSLV` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-042 | **Medium** | SF-MISSING | is clk_ref_i required to be the same clock as clk_smu_i for the SEP=0 build, or must the SEP-OTP error path work across an asynchronous boundary? | the CDC note records that the SEP=0 SEP-OTP error slave sits on clk_ref_i while its driving DTP AXI-Lite is on clk_smu_i and asks for review if the clocks differ, but states no requirement, so there is no pass condition for a differing-clock case. | `SMU-SEPOTP-ERRSLV`, `SMU-CLK-DOMAINS` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-043 | **Medium** | SF-MISSING | is the 512-bit SEP debug bus required to be sampled coherently in SMC, and if not, what consumer-side rule makes a skewed sample acceptable? | the SEP debug bus is described as synchronized into SMC as a 512-bit vector, with no statement of whether coherency across the vector is required or how a consumer is meant to tolerate skew between bits. | `SMU-CLK-DOMAINS` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-044 | **Medium** | SF-MISSING | what address window does each external port occupy from its subsystem point of view, and what does SMC or SEP do when it receives the DECERR tie-off response? | the SMC AXI-Lite external port and the SEP AXI extension port are both documented as tie to DECERR if unused, but neither the address window they occupy nor the subsystem behaviour on receiving a DECERR is stated. | `SMU-SMC-AXIL-EXT`, `SMU-SEP-AXI-EXT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-045 | **Medium** | SF-MISSING | what is the required state of the functional interfaces while test_en_i is asserted, and is any functional traffic legal in that configuration? | the DFT ports are described by what they drive but no required behaviour is stated for the functional outputs while test_en_i is asserted, so no checker expectation exists for the scan configuration. | `SMU-DFT-SCAN` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-046 | **Medium** | SF-MISSING | which memories does the automatic initialization cover, how long does it take, and what does init_mem_done_o read when disable_sram_auto_init_i is asserted? | the memory initialization ports are declared with no sequence, no latency, no statement of which memories are initialized, and no definition of init_mem_done_o when automatic initialization is disabled. | `SMU-MEMINIT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-047 | **Medium** | SF-MISSING | what consumes mem_repair_done_i, mem_repair_success_i, mem_repair_abort_i and the MBIST status inputs inside the SMU, and what drives skip_mem_repair_o? | the memory repair and MBIST status inputs and skip_mem_repair_o are declared with a source or a destination but never with both, and no behaviour is attributed to them, so they name no producer-transport-consumer path and could not enter the feature list. | `SMU-FUSE-SENSE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-048 | **Medium** | SF-MISSING | what is the eFuse shim command protocol and its response encoding for SMC and for SEP, and what does smc_shadow_regs_o contain? | the eFuse shim command interfaces are declared by type only, with no protocol, no command set and no response encoding, and smc_shadow_regs_o has no stated content. | `SMU-EFUSE-SHIM-SMC`, `SMU-EFUSE-SHIM-SEP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-050 | **Medium** | SF-MISSING | what are the SMU values of NUM_GPIO_WRAPS, NUM_UART, CPU_CLUSTER_COUNT, NUM_TELEMETRY_RECEIVERS and TRC_RAM_INSTANCES? | several port-array widths used throughout the port table are never given a value in the pinned sources - NUM_GPIO_WRAPS, NUM_UART, CPU_CLUSTER_COUNT, NUM_TELEMETRY_RECEIVERS and TRC_RAM_INSTANCES - so the widths of gpio_interrupt_o, uart_interrupt_o and the related arrays cannot be pinned. | `SMU-IRQ-PASSTHRU`, `SMU-NDMRESET` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-051 | **Medium** | SF-MISSING | what latency and polarity apply to the GPIO and UART interrupt pass-throughs at the SMU boundary, and what is the observable relationship between sync_irq_o and a write to SYNC_REG.sync? | the three SMC-sourced outputs are described as passed through from SMC with no latency, polarity, or clock-domain relationship stated at the SMU boundary, and sync_irq_o is defined only by naming an SMC register bit. | `SMU-IRQ-PASSTHRU` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-052 | **Medium** | SF-AMBIGUOUS | what is the direction, width and producer of feat_ctrl at the SMU boundary, and which block consumes it? | feat_ctrl is listed in the interface table as lifecycle feature control with direction Mixed, typed sep_efuse_map_lc_disable_reg_t, and it appears in no port-table row. Neither its producer nor its consumer can be identified, so the lifecycle feature-control leg could not be admitted as a feature. | — |
| `ANSWER` / `WAIVE` / `RETURN` | SF-053 | **Medium** | SF-MISSING | what drives smc_region_size_o, in what units is it expressed, and is it the same size field the crossbar SMC aperture uses? | smc_region_size_o is declared as an SMC address region size output to external systems, with no producer named, no units, and no stated relation to the aperture CSR that programs the SMC region. | `SMU-XBAR-APERTURE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-054 | **Medium** | SF-AMBIGUOUS | in a SEP=0 build, is any aperture CSR present and meaningful, or is the entire aperture mechanism absent along with the crossbar? | the specifications table describes the crossbar and its CSR-programmed apertures unconditionally, while the sub-block table marks u_smu_axi_xbar present only when SEP=1. A reader cannot tell whether the aperture behaviour exists at all in a SEP=0 build. | `SMU-NOSEP`, `SMU-XBAR-APERTURE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-055 | **Medium** | SF-UNTESTABLE | is the Verification Alignment section intended as normative design content, or should it be marked informative so that it is not read as a specification of behaviour? | the Verification Alignment section states facts about the verification collateral - which test lists are enrolled, which inventory is deferred, and where stimulus lives. These are claims about tests, not behaviours of the SMU, so they yield no producer, transport or consumer and no observable design requirement. | — |
| `ANSWER` / `WAIVE` / `RETURN` | SF-040 | **Low** | SF-AMBIGUOUS | does forcing the SEP OTP pipeline depth mean it is immune to a non-default Cfg value, and if so what happens when the SMC depths are configured to something other than 3? | the configuration table gives SMC_OTP_RD/WR_PL_DEPTH a default of 3 and in the same row says the SEP OTP read and write depths are forced to 2 h3, which is the same number, so the word forced carries no observable consequence. | `SMU-OTPAXI-SEP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-056 | **Low** | SF-TERM | can distinct names be assigned to the SMN-facing crossbar ports, the SMC AXI-Lite external peripheral port and the SEP AXI extension port? | the document uses SMN both for the chiplet-external fabric and for the SMU port facing it, and uses external port for the crossbar ext_in and ext_out ports as well as for the SMC AXI-Lite external port and the SEP AXI extension port. The same term names four different interfaces. | `SMU-EXT-SMN`, `SMU-SMC-AXIL-EXT`, `SMU-SEP-AXI-EXT` |

## 2. Features — one row per distinct producer → transport → consumer behaviour

Tick **Reviewed** when the intent and the triad match what the design does. If the spec section cited does not say what the row claims, that is a `RETURN`, not a fix to the row.

| Reviewed | Key | Intent | Producer → Transport → Consumer | Spec ref | Scenarios | Contested | Open SF |
|---|---|---|---|---|---:|---:|---|
| [ ] | `SMU-XBAR-CONN` | the smu_axi_xbar routes each of the three initiator ports only to the two target ports the matrix permits | crossbar initiator (slave) ports sep_out(0), smc_out(1) and ext_in(2) → smu_axi_xbar, a 3x3 fully connected AXI4 crossbar in the clk_smu_i domain → crossbar target (master) ports sep_in(0), smc_in(1) and ext_out(2) | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Specifications (+1) | 11 | 4 | SF-001, SF-005, SF-049 |
| [ ] | `SMU-XBAR-APERTURE` | the SMC aperture CSR programs the crossbar address map that selects sep_in, smc_in or the default port | the SMC aperture CSR (u_smc aperture CSR) → the smu_axi_xbar addr_map, built combinationally from the CSR base and size fields → the crossbar address decode that selects sep_in, smc_in or ext_out | `SMU_SPEC.md` §Overview; `SMU_SPEC.md` §Specifications (+3) | 9 | 3 | SF-001, SF-003, SF-004, SF-053, SF-054 |
| [ ] | `SMU-XBAR-DEFAULT` | accesses from sep_out or smc_out that match no aperture fall through to the external SMN port | the sep_out or smc_out initiator issuing an address that matches no programmed aperture → the crossbar default (catch-all) master port selection → ext_out and, beyond it, the external SMN fabric at the SMU port | `SMU_SPEC.md` §Data Paths | 4 | 1 | SF-001, SF-005, SF-009 |
| [ ] | `SMU-XBAR-DECERR` | ext_in has no default master port, so an unmatched inbound SMN access is answered with a decode error | the external SMN master driving ext_in with an address that matches no aperture → the crossbar address decode, which has no default master port for ext_in → the ext_in response channel returning DECERR to the external SMN master | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Error Handling | 5 | 2 | SF-001, SF-008 |
| [ ] | `SMU-XBAR-ATOP` | the crossbar is built with ATOPs = 1 b0, so atomic transactions are rejected rather than performed | any crossbar initiator issuing an AXI atomic (ATOP) transaction → smu_axi_xbar instantiated with ATOPs = 1 b0 → the initiator response channel - the atomic is rejected and the target never performs it | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Error Handling (+2) | 5 | 1 | SF-002 |
| [ ] | `SMU-IDW-IN` | an inbound SMN transaction with an 8-bit AXI ID is carried on the 10-bit crossbar ID and its response returns with the original ID | the external SMN master driving smu_axi_in_req_i with an 8-bit AXI ID → the crossbar input ID widening to the 10-bit internal crossbar ID → the selected crossbar target port, and the return path that restores the originating 8-bit ID | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Interfaces | 4 | 2 | SF-007 |
| [ ] | `SMU-IDW-SEP` | u_iw_conv_sep narrows the 10-bit crossbar ID to the SEP 6-bit inbound ID and restores it on the response | the crossbar sep_in master port presenting a 10-bit AXI ID → u_iw_conv_sep (axi_iw_converter) → the SEP inbound AXI port, which accepts a 6-bit ID | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Sub-Blocks | 4 | 2 | SF-006 |
| [ ] | `SMU-IDW-SMC` | u_iw_conv_smc narrows the 10-bit crossbar ID to the SMC 6-bit inbound ID and restores it on the response | the crossbar smc_in master port presenting a 10-bit AXI ID → u_iw_conv_smc (axi_iw_converter) → the SMC inbound AXI port, which accepts a 6-bit ID | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Sub-Blocks | 4 | 2 | SF-006 |
| [ ] | `SMU-EXT-SMN` | the SMU presents one inbound and one outbound SMN AXI port with the declared address, data, user and ID widths | the external SMN fabric on smu_axi_in_req_i, and the crossbar on smu_axi_out_req_o → axi_56_64 inbound with an 8-bit ID and axi_out outbound with a 10-bit ID, 56-bit address, 64-bit data and 12-bit user → the crossbar ext_in slave port, and the external SMN fabric at the SMU port | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Interfaces (+2) | 5 | 1 | SF-009, SF-056 |
| [ ] | `SMU-ALIAS-REMAP` | a dedicated SEP-to-SMC port remaps the fixed 1 GB region at 0x40000000 down to 0x00000000 without traversing the crossbar | SEP issuing an access inside SEP_SMC_REGION_BASE = 0x40000000, size 0x40000000 (1 GB) → sep_ext_to_smc_axi_local_alias_remap (axi_window_remap), which bypasses the crossbar → SMC at SEP_SMC_REGION_ALIAS_BASE = 0x00000000 | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Sub-Blocks (+1) | 6 | 1 | SF-010 |
| [ ] | `SMU-NOSEP` | with SEP=0 the crossbar and SEP are removed and SMC connects directly to the external SMN port through ID converters | the SMU top-level parameter SEP set to 0 → the SEP=0 structural composition using u_iw_conv_smc_out and u_iw_conv_smc_in in place of the crossbar → SMC and the external SMN port, connected directly | `SMU_SPEC.md` §Configuration Parameters; `SMU_SPEC.md` §Architecture Block Overview (+2) | 4 | 0 | SF-054 |
| [ ] | `SMU-SEPOTP-ERRSLV` | in a SEP=0 build the SEP-OTP debug path is terminated by an error slave that answers DECERR with a fixed data pattern | the DTP OTP-over-JTAG AXI-Lite manager targeting the SEP OTP path in a SEP=0 build → u_sep_otp_axil_err_slv (prim_axi_lite_err_slv), clocked on clk_ref_i → the DTP AXI-Lite response channel | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Error Handling (+1) | 4 | 2 | SF-041, SF-042 |
| [ ] | `SMU-MBOX-XCHG` | SMC and SEP interoperate by exchanging a token and its complement through the mailboxes | SMC writing a token to an outbound mailbox → the SMC-to-SEP mailbox path and the SEP-to-SMC return path → SEP, which reads and verifies the token, and SMC, which pops the complement response | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Features Feature 5 | 6 | 2 | SF-011 |
| [ ] | `SMU-SEP-MBOX-IRQ` | a SEP mailbox raises one of its eight interrupts into SMC | a SEP mailbox (sep_pkg NUM_MAILBOXES = 8) raising its interrupt → the internal SEP mailbox interrupt vector [7:0] carried into SMC → SMC, which takes the interrupt | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Interfaces (+1) | 3 | 1 | SF-014, SF-049 |
| [ ] | `SMU-INT-AGG` | the SMU aggregates 256 external interrupt lines into SMC | external interrupt sources driving ext_interrupts_i → the SMU aggregation of Cfg.NUM_INT_TO_SMC = 256 interrupt lines → SMC, whose interrupt controller takes them | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Configuration Parameters (+1) | 5 | 1 | SF-012 |
| [ ] | `SMU-MBOX-IRQ-OUT` | the 32 SMC mailboxes present their interrupts on ext_mailbox_interrupts_o | the SMC mailboxes (smc_pkg NUM_MAILBOXES = 32) → ext_mailbox_interrupts_o [NUM_MAILBOXES-1:0] → external targets | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Interfaces (+1) | 4 | 1 | SF-013 |
| [ ] | `SMU-IRQ-PASSTHRU` | raw GPIO and UART interrupts and the software sync bit are passed through from SMC to the SMU boundary | SMC - the GPIO wrap padring interrupt vector, the UART instances and the reset-unit SYNC_REG.sync bit → the SMU boundary outputs gpio_interrupt_o, uart_interrupt_o and sync_irq_o → external consumers, which read SMC status registers to identify the source | `port_table.adoc` §port gpio_interrupt_o; `port_table.adoc` §port uart_interrupt_o (+1) | 4 | 0 | SF-050, SF-051 |
| [ ] | `SMU-XTRIG-CTM` | the SMU exposes eight internal cross-trigger ports to the external cross-trigger network, two of which are reserved for SMC | DTP cross-trigger sources, and the external cross-trigger network driving xtrig_ctm_dst_req_i and xtrig_ctm_src_ack_i → the XTRIG_NUM_INT_CT = 8 internal-CT port composition with DTP [1:0] reserved for SMC → the DTP cross-trigger matrix, and the external cross-trigger network via xtrig_ctm_src_req_o and xtrig_ctm_dst_ack_o | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Features Feature 6 (+2) | 6 | 2 | SF-015, SF-017 |
| [ ] | `SMU-XTRIG-CTP` | the SMU exposes sixteen CTP channels as four request and acknowledge port groups toward the GPIO pad ring | the DTP CTP logic driving the outbound groups, and the GPIO pad ring driving the inbound data → the XTRIG_NUM_CTP = 16 CTP port groups req_out, req_in, ack_in and ack_out, each carrying dout, dout_en, din and din_en → the GPIO pad ring on the outbound direction and the DTP CTP logic on the inbound direction | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Features Feature 6 (+2) | 6 | 1 | SF-018 |
| [ ] | `SMU-XTRIG-MODE` | the SMU concatenates the configured internal-CT mode with two zero bits so the SMC-reserved cross triggers run in pulse-sync mode | the SMU build configuration field Cfg.XTRIG_INT_CT_MODE → the SMU concatenation {Cfg.XTRIG_INT_CT_MODE, 2 b00} presented to DTP → the DTP per-internal-CT mode selection | `SMU_SPEC.md` §Configuration Parameters; `SMU_SPEC.md` §Specifications | 3 | 0 | SF-017, SF-020 |
| [ ] | `SMU-CLKSTOP-REQ` | the SMU exposes eight clock-stop request ports into the DTP clock-stop aggregation, one of which is reserved for SMC | external clock-stop requesters driving xtrig_clk_stop_req_i → the XTRIG_NUM_CLK_STOP_REQ = 8 request port composition with port [0] reserved for SMC internally → the DTP clock-stop aggregation | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Features Feature 6 (+1) | 4 | 2 | SF-016, SF-019 |
| [ ] | `SMU-CLKSTOP-OUT` | DTP drives dtp_stop_clks_o from either the JTAG DEBUG_CONTROL instruction or the SMC CLA clock-stop | DTP, driven either by the JTAG DEBUG_CONTROL instruction or by the SMC CLA clock-stop → dtp_stop_clks_o → the PLL clock gates | `port_table.adoc` §port dtp_stop_clks_o; `SMU_SPEC.md` §Features Feature 6 (+1) | 4 | 1 | SF-019 |
| [ ] | `SMU-LC-STATE` | the SMU broadcasts an 8-bit lifecycle state driven by SEP, or a fixed value when SEP is absent | the SEP lifecycle controller when SEP=1, and the fixed value 8 hf0 when SEP=0 → lc_state_o, 2 * LC_STATE_WIDTH = 8 bits → external systems | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Security Considerations (+1) | 4 | 1 | SF-021 |
| [ ] | `SMU-LC-DBGDIS` | the SEP lifecycle controller gates DTP debug resources through dbg_disable, while the OTP bridges stay enabled | the SEP lifecycle controller driving dbg_disable_o (dbg_disable_t) → the DTP dbg_disable_i input → DTP debug gating of STAP selection, iJTAG SIB access and the SMC fabric JTAG2AXI bridge | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Error Handling (+1) | 7 | 1 | SF-024 |
| [ ] | `SMU-LC-SECDIS` | SEP drives the security_disable indication into SMC as part of the lifecycle broadcast | SEP → the security_disable signal from SEP into SMC → SMC | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Features Feature 7 (+1) | 3 | 1 | SF-025 |
| [ ] | `SMU-LC-DEMOTE` | the SEP lifecycle demote state is presented on two 2-bit SMU outputs | the SEP lifecycle demote logic → lcc_demote_state_1_o [1:0] and lcc_demote_state_2_o [1:0] → external lifecycle logic | `SMU_SPEC.md` §Interfaces; `port_table.adoc` §port lcc_demote_state_1_o (+1) | 2 | 0 | SF-023 |
| [ ] | `SMU-LC-SIGINT` | the SMU presents a lifecycle signal-integrity error indication to external systems | the SMU lifecycle broadcast path, driven by the SEP lifecycle controller in a SEP=1 build → lc_sigint_err_o → external systems | `port_table.adoc` §port lc_sigint_err_o; `SMU_SPEC.md` §Security Considerations | 2 | 0 | SF-022 |
| [ ] | `SMU-SEC-TOKEN` | the SMU passes a 256-bit security-disable token digest to SEP, tied to zero in the SMU build | the SMU top-level parameter SEP_SEC_DISABLE_TOKEN, tied 256 b0 at SMU → the parameter connection from SMU into SEP → the SEP security-disable comparison | `SMU_SPEC.md` §Configuration Parameters; `SMU_SPEC.md` §Security Considerations | 2 | 0 | — |
| [ ] | `SMU-EFUSE-SHIM-SMC` | the SMC eFuse controller reaches its external shim through the SMU boundary ports | the SMC eFuse controller → smc_efuse_bank_ctrl_req_o and resp_i (smc_axil_32_32) plus smc_efuse_shim_command_req_o and resp_i → the external SMC eFuse shim | `port_table.adoc` §port smc_efuse_bank_ctrl_req_o; `port_table.adoc` §port smc_efuse_shim_command_req_o (+2) | 3 | 0 | SF-048 |
| [ ] | `SMU-EFUSE-SHIM-SEP` | the SEP eFuse controller reaches its external shim through the SMU boundary ports | the SEP eFuse controller → sep_efuse_bank_ctrl_req_o and resp_i (efuse_axil) plus sep_efuse_shim_command_req_o and resp_i → the external SEP eFuse shim | `port_table.adoc` §port sep_efuse_bank_ctrl_req_o; `port_table.adoc` §port sep_efuse_shim_command_req_o (+1) | 2 | 0 | SF-048, SF-049 |
| [ ] | `SMU-FUSE-SENSE` | SMC and SEP report fuse-sense completion as part of the security bring-up | the SMC and SEP fuse-sense logic → fuse_sense_done_o, sep_fuse_sense_done_o and fuse_reset_n_delayed_o → the memory repair logic and external systems | `SMU_SPEC.md` §Security Considerations; `port_table.adoc` §port fuse_sense_done_o (+3) | 5 | 1 | SF-026, SF-047 |
| [ ] | `SMU-RST-COLD` | the SMU takes an asynchronously asserted, synchronously deasserted cold reset and republishes it on the reference clock | the system cold reset rst_cold_ni → the SMU cold-reset distribution and its reference-clock synchronizer → the composed subsystems, and downstream subsystems through rst_cold_stable_ref_clk_no | `port_table.adoc` §port rst_cold_ni; `port_table.adoc` §port rst_cold_stable_ref_clk_no (+1) | 5 | 2 | SF-027, SF-029 |
| [ ] | `SMU-RST-PRIMARY` | the SMU publishes the primary reset synchronized into the SMC clock and reference clock domains | the SMU reset sequencing logic → rst_primary_smc_clk_no and rst_primary_ref_clk_no → SMC, SEP, DTP, the crossbar and the IW converters, plus downstream subsystems | `SMU_SPEC.md` §Clock and Reset; `port_table.adoc` §port rst_primary_smc_clk_no (+1) | 4 | 1 | SF-027 |
| [ ] | `SMU-PWRGOOD` | DTP is held in power-on reset until SMC reports a stable power-good | powergood_i from the supply supervisor, qualified by SMC into powergood_stable_o → the DTP pwr_on_rst_ni input driven from powergood_stable → DTP, whose power-on reset it is | `SMU_SPEC.md` §Clock and Reset; `port_table.adoc` §port powergood_i | 3 | 1 | SF-029, SF-030 |
| [ ] | `SMU-CLK-DOMAINS` | the SMU composes five clock domains, each with its own reset, across the three subsystems | the five SMU clock inputs clk_smu_i, clk_ref_i, clk_periph_i, clk_telemetry_i and clk_sep_wdt_i → the SMU clock and reset domain composition, including the gated variant gated_clk_periph_i3c_o → SMC, SEP, DTP, the crossbar, the peripheral logic, the telemetry receivers and the SEP watchdog | `SMU_SPEC.md` §Clock and Reset; `SMU_SPEC.md` §Interfaces | 6 | 2 | SF-042, SF-043 |
| [ ] | `SMU-BOOTSEQ-GATE` | reset release waits for the external memory-repair and shadow-register override completion | the external boot and repair controller driving ext_boot_seq_done_i → the SMU reset-release gate → the SMU reset release toward the composed subsystems | `port_table.adoc` §port ext_boot_seq_done_i; `SMU_SPEC.md` §Clock and Reset | 3 | 1 | SF-028 |
| [ ] | `SMU-MEMINIT` | the SMU runs or suppresses automatic SRAM initialization and reports completion | control logic driving disable_sram_auto_init_i → the SMU memory initialization sequence → control logic observing init_mem_done_o | `port_table.adoc` §port disable_sram_auto_init_i; `port_table.adoc` §port init_mem_done_o | 3 | 1 | SF-046 |
| [ ] | `SMU-SEPWDT-RST` | a SEP watchdog timeout raises a SEP reset request into SMC | the SEP watchdog timing out and driving sep_wdt_timer_rst_req → the SEP-to-SMC reset request path, crossing from the clk_sep_wdt_i domain → SMC, which receives the SEP reset request | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Clock and Reset | 3 | 1 | SF-031, SF-032 |
| [ ] | `SMU-WDT-TIMEOUT` | the first and second watchdog timeouts are published to the reset unit and to external systems | the SMC watchdog → wdt_first_timeout_o and wdt_second_timeout_o → the reset unit for the first timeout and external systems for the second | `port_table.adoc` §port wdt_first_timeout_o; `port_table.adoc` §port wdt_second_timeout_o | 3 | 1 | SF-032 |
| [ ] | `SMU-NDMRESET` | the debug infrastructure requests a non-debug-module reset per CPU cluster and observes its progress | the debug infrastructure driving ndmreset_request_i per CPU cluster → the SMU non-debug-module reset request path → the debug infrastructure observing ndmreset_process_o | `port_table.adoc` §port ndmreset_request_i; `port_table.adoc` §port ndmreset_process_o | 3 | 1 | SF-033, SF-050 |
| [ ] | `SMU-SSRESET` | the SMC reset unit sequences 32 external subsystems through isolation, configuration and reset-control ports | the SMC reset unit → isolate_req_o, ss_config_o and ss_reset_ctrl_o [31:0], with ss_reset_complete_i and cfg_flr_pf_active_i returning status → the 32 external subsystems | `port_table.adoc` §port isolate_req_o; `port_table.adoc` §port ss_reset_complete_i (+3) | 6 | 1 | SF-034 |
| [ ] | `SMU-ICRESET` | an IC_RESET TDR loaded over JTAG overrides downstream resets until it is cleared or a power-on reset occurs | the DTP IC_RESET TDR loaded over JTAG when Cfg.JTAG_IC_RESET_ENABLE = 1 → the DTP reset override path and the jtag_ic_reset_ext_o override slice → the downstream SMU resets and the integrator-defined external override targets | `SMU_SPEC.md` §Operating Modes; `SMU_SPEC.md` §Sub-Blocks (+2) | 6 | 1 | SF-035, SF-036 |
| [ ] | `SMU-BOOTSTALL` | DTP can hold SMC boot through the boot-stall and debug-control path | the DTP boot-stall and debug-control state driven over JTAG → the DTP-to-SMC boot-stall path → SMC boot | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Features Feature 3 (+1) | 3 | 1 | SF-037 |
| [ ] | `SMU-DFT-SCAN` | the SMU distributes the DFT test enable to its clock gaters and AXI cells and bypasses reset synchronizers under scan reset | the test controller driving test_en_i and scan_rst_ni → the SMU DFT distribution to clock-gater test ports and AXI cell test inputs, and the reset synchronizer bypass → the clock gaters, the AXI cells and the reset synchronizers | `port_table.adoc` §port test_en_i; `port_table.adoc` §port scan_rst_ni | 4 | 0 | SF-045 |
| [ ] | `SMU-JTAG2AXI-SMC` | the DTP JTAG2AXI bridge gives JTAG access to the SMC local fabric and its CSRs | the DTP JTAG2AXI bridge driven from the primary JTAG TAP → the DTP-to-SMC local fabric AXI path, with SMC_RD and SMC_WR pipeline depths of 3 → the SMC local fabric and its CSRs | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Features Feature 3 (+2) | 4 | 2 | SF-038 |
| [ ] | `SMU-OTPAXI-SMC` | DTP reaches the SMC OTP over an AXI4-Lite bridge driven from JTAG | the DTP OTP-over-JTAG AXI-Lite manager → an AXI4-Lite 32/32 path with SMC_OTP_RD and SMC_OTP_WR pipeline depths of 3 → the SMC OTP | `SMU_SPEC.md` §Interfaces; `SMU_SPEC.md` §Sub-Blocks (+2) | 3 | 1 | SF-039 |
| [ ] | `SMU-OTPAXI-SEP` | DTP reaches the SEP OTP over an AXI4-Lite bridge whose pipeline depths the SMU forces | the DTP OTP-over-JTAG AXI-Lite manager → an AXI4-Lite 32/32 path with the SEP OTP read and write pipeline depths forced to 2 h3 → the SEP OTP in a SEP=1 build | `SMU_SPEC.md` §Interfaces; `SMU_SPEC.md` §Configuration Parameters (+1) | 3 | 0 | SF-039, SF-040 |
| [ ] | `SMU-SMC-AXIL-EXT` | SMC reaches adopter peripherals through an AXI-Lite port at the SMU boundary | SMC → smc_external_req_o and smc_external_resp_i (smc_axil_32_32) → adopter peripherals | `port_table.adoc` §port smc_external_req_o; `SMU_SPEC.md` §Interfaces | 2 | 0 | SF-044, SF-056 |
| [ ] | `SMU-SEP-AXI-EXT` | SEP reaches adopter peripherals through an AXI extension port at the SMU boundary | SEP → sep_external_req_o and sep_external_resp_i (sep_32_64_6_12_axi) → adopter peripherals | `port_table.adoc` §port sep_external_req_o; `SMU_SPEC.md` §Sub-Blocks | 2 | 0 | SF-044, SF-056 |

## 3. Scenarios — what each feature must be shown to do

Grouped by feature. `Proof` is the minimum evidence class the scenario demands: `DECODE` (a static/decoded outcome), `CONNECTIVITY` (the path exists and carries), `LIVE` (the real consumer is reached and reacts).

### `SMU-XBAR-CONN` — SMU crossbar 3x3 connectivity matrix

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XBAR-CONN.S1` | a sep_out access that matches the SMC aperture is delivered at smc_in | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-049 |
| [ ] | `SMU-XBAR-CONN.S2` | a smc_out access that matches the SEP aperture is delivered at sep_in | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-CONN.S3` | an ext_in access that matches the SEP aperture is delivered at sep_in | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-CONN.S4` | an ext_in access that matches the SMC aperture is delivered at smc_in | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-CONN.S5` | sep_out has no route to sep_in - an initiator cannot reach its own inbound port | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-CONN.S6` | smc_out has no route to smc_in | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-CONN.S7` | ext_in has no route to ext_out | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-CONN.S8` | **[contested]** contested state - sep_out and ext_in target smc_in in the same cycle; both transactions complete or error within a bounded window and neither response is lost | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-005 |
| [ ] | `SMU-XBAR-CONN.S9` | **[contested]** contested state - sep_out to smc_in and smc_out to sep_in run concurrently in opposite directions and neither path starves | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-005 |
| [ ] | `SMU-XBAR-CONN.S10` | **[contested]** contested state - the external SMN slave applies sustained backpressure on ext_out while a sep_out to smc_in transfer is in progress; the internal path still completes within a bounded window | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Features Feature 4 | SF-005 |
| [ ] | `SMU-XBAR-CONN.S11` | **[contested]** contested state - rst_primary_smc_clk_no asserts with a crossbar burst outstanding; no response is emitted after reset and the fabric routes correctly after release | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Clock and Reset | — |

### `SMU-XBAR-APERTURE` — CSR-programmed SEP and SMC crossbar apertures

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XBAR-APERTURE.S1` | a programmed SMC aperture base and size routes a matching address to smc_in | `LIVE` | `SMU_SPEC.md` §Overview; `SMU_SPEC.md` §Sub-Blocks | SF-001, SF-054 |
| [ ] | `SMU-XBAR-APERTURE.S2` | a programmed SEP aperture base and size routes a matching address to sep_in | `LIVE` | `SMU_SPEC.md` §Overview; `SMU_SPEC.md` §Sub-Blocks | SF-001 |
| [ ] | `SMU-XBAR-APERTURE.S3` | reprogramming an aperture moves the decode boundary - an address that previously matched no longer matches and the new range does | `LIVE` | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Features Feature 4 | SF-001 |
| [ ] | `SMU-XBAR-APERTURE.S4` | the programmable global-base remap shifts the decoded region by the programmed base | `LIVE` | `SMU_SPEC.md` §Features Feature 4 | SF-001 |
| [ ] | `SMU-XBAR-APERTURE.S5` | the programmed SMC region size is reflected on smc_region_size_o | `CONNECTIVITY` | `port_table.adoc` §port smc_region_size_o | SF-053 |
| [ ] | `SMU-XBAR-APERTURE.S6` | **[contested]** contested state - the aperture CSR is rewritten while a transaction decoded under the old map is in flight; that transaction completes or errors within a bounded window and no response is lost | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `SMU_SPEC.md` §Sub-Blocks | SF-003 |
| [ ] | `SMU-XBAR-APERTURE.S7` | **[contested]** contested state - the SEP and SMC apertures are programmed to overlap; a single address is never delivered to two targets | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | SF-004 |
| [ ] | `SMU-XBAR-APERTURE.S8` | an aperture programmed with zero size matches no address | `DECODE` | `SMU_SPEC.md` §Overview; `SMU_SPEC.md` §Sub-Blocks | — |
| [ ] | `SMU-XBAR-APERTURE.S9` | **[contested]** contested state - an aperture CSR write is concurrent with a decode of an address inside that aperture issued by another initiator | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `SMU_SPEC.md` §Data Paths | SF-003 |

### `SMU-XBAR-DEFAULT` — ext_out default master port for unmatched internal accesses

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XBAR-DEFAULT.S1` | an unmatched sep_out access is routed to ext_out | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-DEFAULT.S2` | an unmatched smc_out access is routed to ext_out | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-XBAR-DEFAULT.S3` | the response returned by the external SMN slave on the default path is delivered back to the originating initiator carrying its own ID | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Interfaces | — |
| [ ] | `SMU-XBAR-DEFAULT.S4` | **[contested]** contested state - an unmatched access while the external SMN slave withholds its response completes or errors within a bounded window rather than hanging the initiator | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Features Feature 4 | SF-009 |

### `SMU-XBAR-DECERR` — Decode error for unmatched external inbound accesses

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XBAR-DECERR.S1` | an unmatched ext_in read is answered with DECERR | `DECODE` | `SMU_SPEC.md` §Error Handling | SF-008 |
| [ ] | `SMU-XBAR-DECERR.S2` | an unmatched ext_in write is answered with DECERR | `DECODE` | `SMU_SPEC.md` §Error Handling | SF-008 |
| [ ] | `SMU-XBAR-DECERR.S3` | every beat of an unmatched ext_in burst is accounted for and the burst terminates | `LIVE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Data Paths | SF-008 |
| [ ] | `SMU-XBAR-DECERR.S4` | **[contested]** contested state - an unmatched ext_in access issued while a matched ext_in access is outstanding; the matched access still completes normally | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Error Handling | — |
| [ ] | `SMU-XBAR-DECERR.S5` | **[contested]** contested state - error during error; a second unmatched ext_in access is issued while the first decode-error response is still outstanding, and both receive their own error response | `LIVE` | `SMU_SPEC.md` §Error Handling | — |

### `SMU-XBAR-ATOP` — AXI atomic operations rejected at the crossbar

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XBAR-ATOP.S1` | an atomic issued on sep_out is rejected and is not performed at the target | `LIVE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Specifications | SF-002 |
| [ ] | `SMU-XBAR-ATOP.S2` | an atomic issued on smc_out is rejected and is not performed at the target | `LIVE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Specifications | SF-002 |
| [ ] | `SMU-XBAR-ATOP.S3` | an atomic issued on ext_in is rejected and is not performed at the target | `LIVE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Specifications | SF-002 |
| [ ] | `SMU-XBAR-ATOP.S4` | an ordinary access issued on the same path immediately after a rejected atomic completes normally | `LIVE` | `SMU_SPEC.md` §Error Handling | — |
| [ ] | `SMU-XBAR-ATOP.S5` | **[contested]** contested state - an atomic is rejected while an ordinary transaction is outstanding on the same initiator; the ordinary transaction is neither corrupted nor reordered | `LIVE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Data Paths | — |

### `SMU-IDW-IN` — External inbound 8-bit to 10-bit crossbar ID widening

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-IDW-IN.S1` | an 8-bit ext_in ID reaches the target and the response returns carrying the identical 8-bit ID | `LIVE` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Interfaces | SF-007 |
| [ ] | `SMU-IDW-IN.S2` | **[contested]** two concurrent ext_in transactions with different IDs return responses tagged with their own IDs | `LIVE` | `SMU_SPEC.md` §Specifications | — |
| [ ] | `SMU-IDW-IN.S3` | **[contested]** contested state - several ext_in transactions sharing one ID are outstanding together and their responses return in order | `LIVE` | `SMU_SPEC.md` §Specifications | — |
| [ ] | `SMU-IDW-IN.S4` | every 8-bit inbound ID value is transportable end to end | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Interfaces | SF-007 |

### `SMU-IDW-SEP` — Crossbar 10-bit to SEP 6-bit ID conversion

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-IDW-SEP.S1` | a transaction crossing u_iw_conv_sep arrives at SEP with a 6-bit ID and its response returns to the correct crossbar initiator | `LIVE` | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Specifications | — |
| [ ] | `SMU-IDW-SEP.S2` | **[contested]** contested state - more distinct 10-bit IDs are outstanding than the 6-bit output space can represent; every response still returns to its originator within a bounded window | `LIVE` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Sub-Blocks | SF-006 |
| [ ] | `SMU-IDW-SEP.S3` | **[contested]** contested state - reset asserts with a converted transaction outstanding and the converter routes correctly after release | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `SMU_SPEC.md` §Sub-Blocks | — |
| [ ] | `SMU-IDW-SEP.S4` | read and write responses crossing the converter are returned with IDs matching their requests | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | — |

### `SMU-IDW-SMC` — Crossbar 10-bit to SMC 6-bit ID conversion

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-IDW-SMC.S1` | a transaction crossing u_iw_conv_smc arrives at SMC with a 6-bit ID and its response returns to the correct crossbar initiator | `LIVE` | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Specifications | — |
| [ ] | `SMU-IDW-SMC.S2` | **[contested]** contested state - more distinct 10-bit IDs are outstanding than the 6-bit output space can represent; every response still returns to its originator within a bounded window | `LIVE` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Sub-Blocks | SF-006 |
| [ ] | `SMU-IDW-SMC.S3` | **[contested]** contested state - reset asserts with a converted transaction outstanding and the converter routes correctly after release | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `SMU_SPEC.md` §Sub-Blocks | — |
| [ ] | `SMU-IDW-SMC.S4` | read and write responses crossing the converter are returned with IDs matching their requests | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | — |

### `SMU-EXT-SMN` — External SMN AXI port composition at the SMU boundary

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-EXT-SMN.S1` | the full 56-bit address is carried in both directions without truncation | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications; `port_table.adoc` §port smu_axi_in_req_i | — |
| [ ] | `SMU-EXT-SMN.S2` | 64-bit data is carried without truncation in both directions | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications | — |
| [ ] | `SMU-EXT-SMN.S3` | the 12-bit user field is carried unmodified | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications | — |
| [ ] | `SMU-EXT-SMN.S4` | the outbound SMN port presents a 10-bit ID while the inbound port accepts an 8-bit ID | `DECODE` | `SMU_SPEC.md` §Interfaces; `SMU_SPEC.md` §Specifications | — |
| [ ] | `SMU-EXT-SMN.S5` | **[contested]** contested state - smu_axi_out_resp_i is tied off so no response ever returns; the originating initiator is released with a bounded error rather than hanging forever | `LIVE` | `port_table.adoc` §port smu_axi_out_resp_i; `SMU_SPEC.md` §Data Paths | SF-009 |

### `SMU-ALIAS-REMAP` — SEP to SMC fixed alias remap bypassing the crossbar

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-ALIAS-REMAP.S1` | an access at 0x40000000 is presented to SMC at address 0x00000000 | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-ALIAS-REMAP.S2` | an access at the top of the window, 0x7FFFFFFF, is presented to SMC at 0x3FFFFFFF | `LIVE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-ALIAS-REMAP.S3` | an access just below 0x40000000 is not remapped | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-ALIAS-REMAP.S4` | an access just above 0x7FFFFFFF is not remapped | `DECODE` | `SMU_SPEC.md` §Data Paths | — |
| [ ] | `SMU-ALIAS-REMAP.S5` | the remapped access bypasses the crossbar and is observed on no crossbar target port | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Architecture Block Overview | — |
| [ ] | `SMU-ALIAS-REMAP.S6` | **[contested]** contested state - a burst that starts inside the alias window and would cross its top boundary | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-010 |

### `SMU-NOSEP` — SEP=0 build composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-NOSEP.S1` | with SEP=0 SMC and the external SMN port exchange read and write traffic through the direct ID converters | `LIVE` | `SMU_SPEC.md` §Architecture Block Overview; `SMU_SPEC.md` §Sub-Blocks | — |
| [ ] | `SMU-NOSEP.S2` | with SEP=0 the SEP-facing outputs at the SMU boundary are tied off | `CONNECTIVITY` | `SMU_SPEC.md` §Configuration Parameters | — |
| [ ] | `SMU-NOSEP.S3` | with SEP=0 no crossbar aperture decode is present, so SMC traffic is not aperture-filtered | `LIVE` | `SMU_SPEC.md` §Architecture Block Overview; `SMU_SPEC.md` §Sub-Blocks | SF-054 |
| [ ] | `SMU-NOSEP.S4` | NoSepCfg is field-identical to DefaultCfg, so only the SEP parameter distinguishes the two builds | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | — |

### `SMU-SEPOTP-ERRSLV` — SEP=0 SEP-OTP AXI-Lite error slave

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-SEPOTP-ERRSLV.S1` | a SEP=0 SEP-OTP read returns DECERR with read data 0xBADCAB1E | `DECODE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Sub-Blocks | SF-041 |
| [ ] | `SMU-SEPOTP-ERRSLV.S2` | a SEP=0 SEP-OTP write returns an error response | `DECODE` | `SMU_SPEC.md` §Error Handling | SF-041 |
| [ ] | `SMU-SEPOTP-ERRSLV.S3` | **[contested]** contested state - back-to-back SEP-OTP accesses each receive their own error response | `LIVE` | `SMU_SPEC.md` §Error Handling | — |
| [ ] | `SMU-SEPOTP-ERRSLV.S4` | **[contested]** contested state - the error slave runs on clk_ref_i while its AXI-Lite manager runs on clk_smu_i; the response is correct when the two clocks differ in frequency and phase | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-042 |

### `SMU-MBOX-XCHG` — SMC to SEP mailbox challenge-response exchange

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-MBOX-XCHG.S1` | a token written by SMC to its outbound mailbox is observed by SEP at its inbound mailbox | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-011 |
| [ ] | `SMU-MBOX-XCHG.S2` | SEP writes the complement back and SMC pops the response | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-011 |
| [ ] | `SMU-MBOX-XCHG.S3` | the value SMC pops is the bitwise complement of the token it wrote | `LIVE` | `SMU_SPEC.md` §Data Paths | SF-011 |
| [ ] | `SMU-MBOX-XCHG.S4` | **[contested]** contested state - SMC writes a second token before SEP has consumed the first; both exchanges complete or the second is rejected, within a bounded window | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Features Feature 5 | SF-011 |
| [ ] | `SMU-MBOX-XCHG.S5` | **[contested]** contested state - reset is asserted between the token write and the response pop; the mailbox path is usable again after release | `LIVE` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-MBOX-XCHG.S6` | the exchange holds across the token value space | `LIVE` | `SMU_SPEC.md` §Data Paths | — |

### `SMU-SEP-MBOX-IRQ` — SEP mailbox interrupt into SMC

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-SEP-MBOX-IRQ.S1` | a SEP mailbox write asserts the corresponding SEP mailbox interrupt into SMC | `LIVE` | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Interfaces | SF-014 |
| [ ] | `SMU-SEP-MBOX-IRQ.S2` | the SEP mailbox interrupt clears after SMC services the mailbox | `LIVE` | `SMU_SPEC.md` §Sub-Blocks | SF-014 |
| [ ] | `SMU-SEP-MBOX-IRQ.S3` | **[contested]** contested state - two SEP mailbox interrupts assert in the same cycle and both are delivered | `LIVE` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Sub-Blocks | SF-014 |

### `SMU-INT-AGG` — External interrupt aggregation into SMC

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-INT-AGG.S1` | the aggregation port is 256 bits wide, matching Cfg.NUM_INT_TO_SMC | `DECODE` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Configuration Parameters | — |
| [ ] | `SMU-INT-AGG.S2` | an asserted ext_interrupts_i bit is observable as an interrupt at SMC | `LIVE` | `port_table.adoc` §port ext_interrupts_i; `SMU_SPEC.md` §Configuration Parameters | SF-012 |
| [ ] | `SMU-INT-AGG.S3` | deasserting the external interrupt line propagates to SMC | `LIVE` | `port_table.adoc` §port ext_interrupts_i | SF-012 |
| [ ] | `SMU-INT-AGG.S4` | **[contested]** contested state - all 256 lines assert in the same cycle and every one is delivered | `LIVE` | `SMU_SPEC.md` §Specifications; `port_table.adoc` §port ext_interrupts_i | — |
| [ ] | `SMU-INT-AGG.S5` | each interrupt index maps to its own SMC interrupt input | `LIVE` | `port_table.adoc` §port ext_interrupts_i | SF-012 |

### `SMU-MBOX-IRQ-OUT` — SMC mailbox interrupt outputs at the SMU boundary

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-MBOX-IRQ-OUT.S1` | the mailbox interrupt output is 32 bits wide, matching smc_pkg NUM_MAILBOXES | `DECODE` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Interfaces | — |
| [ ] | `SMU-MBOX-IRQ-OUT.S2` | an SMC mailbox interrupt appears on the corresponding output bit | `LIVE` | `port_table.adoc` §port ext_mailbox_interrupts_o; `SMU_SPEC.md` §Interfaces | SF-013 |
| [ ] | `SMU-MBOX-IRQ-OUT.S3` | the output bit clears when the mailbox is serviced | `LIVE` | `port_table.adoc` §port ext_mailbox_interrupts_o | SF-013 |
| [ ] | `SMU-MBOX-IRQ-OUT.S4` | **[contested]** contested state - several mailbox interrupts assert at once and each appears on its own bit | `LIVE` | `SMU_SPEC.md` §Specifications; `port_table.adoc` §port ext_mailbox_interrupts_o | — |

### `SMU-IRQ-PASSTHRU` — SMC-sourced raw interrupt and sync outputs at the SMU boundary

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-IRQ-PASSTHRU.S1` | a raw GPIO wrap interrupt appears on the matching bit of gpio_interrupt_o | `LIVE` | `port_table.adoc` §port gpio_interrupt_o | SF-050, SF-051 |
| [ ] | `SMU-IRQ-PASSTHRU.S2` | a UART interrupt appears on the matching bit of uart_interrupt_o in the peripheral clock domain | `LIVE` | `port_table.adoc` §port uart_interrupt_o; `SMU_SPEC.md` §Clock and Reset | SF-051 |
| [ ] | `SMU-IRQ-PASSTHRU.S3` | sync_irq_o reflects the software-controlled SYNC_REG.sync bit and is not an aggregate of any interrupt | `LIVE` | `port_table.adoc` §port sync_irq_o | SF-051 |
| [ ] | `SMU-IRQ-PASSTHRU.S4` | both bonded and unbonded GPIO wraps present a bit on gpio_interrupt_o | `CONNECTIVITY` | `port_table.adoc` §port gpio_interrupt_o | SF-050 |

### `SMU-XTRIG-CTM` — Cross-trigger CTM port composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XTRIG-CTM.S1` | a DTP cross-trigger source request appears on xtrig_ctm_src_req_o | `LIVE` | `port_table.adoc` §port xtrig_ctm_src_req_o; `SMU_SPEC.md` §Features Feature 6 | SF-017 |
| [ ] | `SMU-XTRIG-CTM.S2` | an external destination request on xtrig_ctm_dst_req_i reaches the DTP cross-trigger matrix | `LIVE` | `port_table.adoc` §port xtrig_ctm_dst_req_i; `SMU_SPEC.md` §Features Feature 6 | SF-017 |
| [ ] | `SMU-XTRIG-CTM.S3` | ports [1:0] are reserved for SMC and are not assignable to an external cross-trigger source | `DECODE` | `SMU_SPEC.md` §Specifications; `port_table.adoc` §port xtrig_ctm_src_req_o | SF-015 |
| [ ] | `SMU-XTRIG-CTM.S4` | in pulse-sync mode the source and destination acknowledge ports are unused | `DECODE` | `port_table.adoc` §port xtrig_ctm_src_ack_i; `port_table.adoc` §port xtrig_ctm_dst_ack_o | SF-017 |
| [ ] | `SMU-XTRIG-CTM.S5` | **[contested]** contested state - requests on several CTM ports in the same cycle are all delivered | `LIVE` | `SMU_SPEC.md` §Specifications; `SMU_SPEC.md` §Features Feature 6 | — |
| [ ] | `SMU-XTRIG-CTM.S6` | **[contested]** contested state - a CTM request asserted while the primary reset is deasserting is either delivered or cleanly dropped, never partially | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `SMU_SPEC.md` §Features Feature 6 | — |

### `SMU-XTRIG-CTP` — Cross-trigger CTP GPIO port composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XTRIG-CTP.S1` | each of the four CTP groups presents 16 bits on each of its four signals | `CONNECTIVITY` | `SMU_SPEC.md` §Specifications; `port_table.adoc` §port xtrig_ctp_req_out_dout_o | — |
| [ ] | `SMU-XTRIG-CTP.S2` | a CTP request driven by DTP appears on xtrig_ctp_req_out_dout_o with its output enable asserted | `LIVE` | `port_table.adoc` §port xtrig_ctp_req_out_dout_o | SF-018 |
| [ ] | `SMU-XTRIG-CTP.S3` | a CTP input driven on xtrig_ctp_req_in_din_i reaches the DTP CTP logic when the corresponding input enable is set | `LIVE` | `port_table.adoc` §port xtrig_ctp_req_in_din_i | SF-018 |
| [ ] | `SMU-XTRIG-CTP.S4` | an acknowledge driven by DTP appears on xtrig_ctp_ack_out_dout_o with its enable | `LIVE` | `port_table.adoc` §port xtrig_ctp_ack_out_dout_o | SF-018 |
| [ ] | `SMU-XTRIG-CTP.S5` | **[contested]** contested state - wire-OR contention, with two sources driving the same CTP channel in the same cycle | `LIVE` | `SMU_SPEC.md` §Features Feature 6 | SF-018 |
| [ ] | `SMU-XTRIG-CTP.S6` | unused CTP data inputs tied to 0 leave the corresponding channel inert | `CONNECTIVITY` | `port_table.adoc` §port xtrig_ctp_req_in_din_i; `port_table.adoc` §port xtrig_ctp_ack_in_din_i | — |

### `SMU-XTRIG-MODE` — Per-internal-CT mode composition into DTP

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-XTRIG-MODE.S1` | DTP receives mode bits [1:0] equal to 0, placing the two SMC-reserved cross triggers in pulse-sync mode | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | — |
| [ ] | `SMU-XTRIG-MODE.S2` | the remaining mode bits presented to DTP are the configured Cfg.XTRIG_INT_CT_MODE value, unmodified | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | SF-020 |
| [ ] | `SMU-XTRIG-MODE.S3` | a cross trigger configured in pulse-sync mode ignores its acknowledge port | `LIVE` | `SMU_SPEC.md` §Configuration Parameters; `port_table.adoc` §port xtrig_ctm_src_ack_i | SF-017 |

### `SMU-CLKSTOP-REQ` — Clock-stop request port composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-CLKSTOP-REQ.S1` | an external clock-stop request reaches the DTP clock-stop aggregation | `LIVE` | `port_table.adoc` §port xtrig_clk_stop_req_i; `SMU_SPEC.md` §Features Feature 6 | SF-019 |
| [ ] | `SMU-CLKSTOP-REQ.S2` | port [0] is reserved for SMC internally and is not assignable to an external requester | `DECODE` | `SMU_SPEC.md` §Specifications; `port_table.adoc` §port xtrig_clk_stop_req_i | SF-016 |
| [ ] | `SMU-CLKSTOP-REQ.S3` | **[contested]** contested state - several clock-stop requests assert at once and the aggregation reflects all of them | `LIVE` | `SMU_SPEC.md` §Features Feature 6; `port_table.adoc` §port xtrig_clk_stop_req_i | — |
| [ ] | `SMU-CLKSTOP-REQ.S4` | **[contested]** contested state - a clock-stop request asserts while an AXI transaction is in flight; the transaction completes or errors within a bounded window | `LIVE` | `SMU_SPEC.md` §Features Feature 6; `SMU_SPEC.md` §Data Paths | — |

### `SMU-CLKSTOP-OUT` — DTP clock-stop output to the PLL clock gates

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-CLKSTOP-OUT.S1` | a JTAG DEBUG_CONTROL clock stop asserts dtp_stop_clks_o | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o; `SMU_SPEC.md` §Operating Modes | SF-019 |
| [ ] | `SMU-CLKSTOP-OUT.S2` | an SMC CLA clock-stop request asserts dtp_stop_clks_o | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o; `SMU_SPEC.md` §Features Feature 6 | SF-019 |
| [ ] | `SMU-CLKSTOP-OUT.S3` | dtp_stop_clks_o deasserts once the requesting source releases | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o | — |
| [ ] | `SMU-CLKSTOP-OUT.S4` | **[contested]** contested state - both sources request a stop and the output stays asserted until both release | `LIVE` | `port_table.adoc` §port dtp_stop_clks_o; `SMU_SPEC.md` §Features Feature 6 | SF-019 |

### `SMU-LC-STATE` — Lifecycle state broadcast at the SMU boundary

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-LC-STATE.S1` | lc_state_o is 8 bits wide, equal to 2 * LC_STATE_WIDTH | `DECODE` | `SMU_SPEC.md` §Specifications; `port_table.adoc` §port lc_state_o | — |
| [ ] | `SMU-LC-STATE.S2` | with SEP=1 lc_state_o follows the SEP lifecycle controller | `LIVE` | `SMU_SPEC.md` §Security Considerations; `port_table.adoc` §port lc_state_o | SF-021 |
| [ ] | `SMU-LC-STATE.S3` | with SEP=0 lc_state_o reads 8 hf0 | `DECODE` | `SMU_SPEC.md` §Security Considerations; `port_table.adoc` §port lc_state_o | — |
| [ ] | `SMU-LC-STATE.S4` | **[contested]** contested state - lc_state_o is stable across the reset release edge and shows no transient value that is neither the pre-reset nor the post-reset state | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `SMU_SPEC.md` §Security Considerations | SF-021 |

### `SMU-LC-DBGDIS` — Lifecycle debug disable from SEP into DTP

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-LC-DBGDIS.S1` | with dbg_disable asserted, STAP selection is blocked | `LIVE` | `SMU_SPEC.md` §Security Considerations | SF-024 |
| [ ] | `SMU-LC-DBGDIS.S2` | with dbg_disable asserted, iJTAG SIB access is blocked | `LIVE` | `SMU_SPEC.md` §Security Considerations | — |
| [ ] | `SMU-LC-DBGDIS.S3` | with dbg_disable asserted, the SMC fabric JTAG2AXI bridge produces no AXI traffic | `LIVE` | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Error Handling | SF-024 |
| [ ] | `SMU-LC-DBGDIS.S4` | the SMC OTP JTAG2AXI bridge remains enabled while dbg_disable is asserted | `LIVE` | `SMU_SPEC.md` §Security Considerations | — |
| [ ] | `SMU-LC-DBGDIS.S5` | the SEP OTP JTAG2AXI bridge remains enabled while dbg_disable is asserted | `LIVE` | `SMU_SPEC.md` §Security Considerations | — |
| [ ] | `SMU-LC-DBGDIS.S6` | a debug resource blocked by dbg_disable falls back to BYPASS | `LIVE` | `SMU_SPEC.md` §Error Handling | SF-024 |
| [ ] | `SMU-LC-DBGDIS.S7` | **[contested]** contested state - dbg_disable asserts while a JTAG2AXI transaction is in flight; the transaction completes or errors within a bounded window and no partial write reaches the fabric | `LIVE` | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Error Handling | SF-024 |

### `SMU-LC-SECDIS` — Security disable from SEP into SMC

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-LC-SECDIS.S1` | SEP drives security_disable into SMC and the connection is present in a SEP=1 build | `CONNECTIVITY` | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Sub-Blocks | — |
| [ ] | `SMU-LC-SECDIS.S2` | the security_disable value SMC receives follows the SEP lifecycle state | `LIVE` | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Features Feature 7 | SF-025 |
| [ ] | `SMU-LC-SECDIS.S3` | **[contested]** contested state - security_disable changes while SMC is mid-transaction; the new value is delivered within a bounded window and SMC keeps making progress | `LIVE` | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Clock and Reset | SF-025 |

### `SMU-LC-DEMOTE` — Lifecycle demote state outputs

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-LC-DEMOTE.S1` | both demote outputs are 2 bits wide and present at the SMU boundary | `CONNECTIVITY` | `port_table.adoc` §port lcc_demote_state_1_o; `port_table.adoc` §port lcc_demote_state_2_o | — |
| [ ] | `SMU-LC-DEMOTE.S2` | the demote outputs follow the SEP lifecycle demote state | `LIVE` | `SMU_SPEC.md` §Interfaces; `port_table.adoc` §port lcc_demote_state_1_o | SF-023 |

### `SMU-LC-SIGINT` — Lifecycle signal integrity error output

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-LC-SIGINT.S1` | lc_sigint_err_o is present at the SMU boundary and is inert during normal operation | `CONNECTIVITY` | `port_table.adoc` §port lc_sigint_err_o | SF-022 |
| [ ] | `SMU-LC-SIGINT.S2` | lc_sigint_err_o is driven to a defined value in a SEP=0 build rather than floating | `CONNECTIVITY` | `port_table.adoc` §port lc_sigint_err_o; `SMU_SPEC.md` §Security Considerations | SF-022 |

### `SMU-SEC-TOKEN` — SEP security-disable token parameter composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-SEC-TOKEN.S1` | SEP receives the 256-bit token from the SMU parameter | `CONNECTIVITY` | `SMU_SPEC.md` §Configuration Parameters; `SMU_SPEC.md` §Security Considerations | — |
| [ ] | `SMU-SEC-TOKEN.S2` | the default SMU build presents 256 b0 on that parameter | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | — |

### `SMU-EFUSE-SHIM-SMC` — SMC eFuse shim port composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-EFUSE-SHIM-SMC.S1` | an SMC eFuse bank-control AXI-Lite access appears at the SMU boundary and its response is returned to SMC | `LIVE` | `port_table.adoc` §port smc_efuse_bank_ctrl_req_o | — |
| [ ] | `SMU-EFUSE-SHIM-SMC.S2` | an SMC eFuse command request appears at the boundary and its response is returned to SMC | `LIVE` | `port_table.adoc` §port smc_efuse_shim_command_req_o | SF-048 |
| [ ] | `SMU-EFUSE-SHIM-SMC.S3` | smc_shadow_regs_o presents the SMC eFuse shadow registers at the boundary | `CONNECTIVITY` | `port_table.adoc` §port smc_shadow_regs_o | SF-048 |

### `SMU-EFUSE-SHIM-SEP` — SEP eFuse shim port composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-EFUSE-SHIM-SEP.S1` | a SEP eFuse bank-control AXI-Lite access appears at the SMU boundary and its response is returned to SEP | `LIVE` | `port_table.adoc` §port sep_efuse_bank_ctrl_req_o | SF-049 |
| [ ] | `SMU-EFUSE-SHIM-SEP.S2` | a SEP eFuse command request appears at the boundary and its response is returned to SEP | `LIVE` | `port_table.adoc` §port sep_efuse_shim_command_req_o | SF-048 |

### `SMU-FUSE-SENSE` — Fuse-sense completion handshake at the SMU boundary

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-FUSE-SENSE.S1` | fuse_sense_done_o asserts once SMC fuse sense completes | `LIVE` | `port_table.adoc` §port fuse_sense_done_o; `SMU_SPEC.md` §Security Considerations | — |
| [ ] | `SMU-FUSE-SENSE.S2` | sep_fuse_sense_done_o asserts once SEP fuse sense completes | `LIVE` | `port_table.adoc` §port sep_fuse_sense_done_o; `SMU_SPEC.md` §Security Considerations | — |
| [ ] | `SMU-FUSE-SENSE.S3` | fuse_reset_n_delayed_o is released after the fuse-sense phase rather than with the cold reset | `LIVE` | `port_table.adoc` §port fuse_reset_n_delayed_o; `SMU_SPEC.md` §Security Considerations | SF-026 |
| [ ] | `SMU-FUSE-SENSE.S4` | skip_mem_repair_o is presented to the memory repair logic | `CONNECTIVITY` | `port_table.adoc` §port skip_mem_repair_o | SF-047 |
| [ ] | `SMU-FUSE-SENSE.S5` | **[contested]** contested state - SMC and SEP fuse sense complete in either order and the bring-up proceeds in both orderings | `LIVE` | `SMU_SPEC.md` §Security Considerations; `port_table.adoc` §port sep_fuse_sense_done_o | SF-026 |

### `SMU-RST-COLD` — Cold reset entry and reference-clock cold-reset output

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-RST-COLD.S1` | rst_cold_ni asserts asynchronously, without requiring a clock edge | `LIVE` | `port_table.adoc` §port rst_cold_ni | SF-029 |
| [ ] | `SMU-RST-COLD.S2` | rst_cold_ni deassertion is synchronized before it reaches the composed subsystems | `LIVE` | `port_table.adoc` §port rst_cold_ni | SF-027 |
| [ ] | `SMU-RST-COLD.S3` | rst_cold_stable_ref_clk_no is an active-low cold reset synchronized to the reference clock domain | `LIVE` | `port_table.adoc` §port rst_cold_stable_ref_clk_no; `SMU_SPEC.md` §Clock and Reset | SF-027 |
| [ ] | `SMU-RST-COLD.S4` | **[contested]** contested state - cold reset asserts with crossbar traffic in flight and the SMU returns to a defined state | `LIVE` | `port_table.adoc` §port rst_cold_ni; `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-RST-COLD.S5` | **[contested]** contested state - cold reset asserts while clk_ref_i is not running, and the reference-clock reset output still reaches its asserted level | `LIVE` | `port_table.adoc` §port rst_cold_stable_ref_clk_no; `SMU_SPEC.md` §Clock and Reset | — |

### `SMU-RST-PRIMARY` — Primary reset distribution to the composed subsystems

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-RST-PRIMARY.S1` | rst_primary_smc_clk_no is synchronized to clk_smu_i | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `port_table.adoc` §port rst_primary_smc_clk_no | SF-027 |
| [ ] | `SMU-RST-PRIMARY.S2` | rst_primary_ref_clk_no is synchronized to clk_ref_i | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `port_table.adoc` §port rst_primary_ref_clk_no | SF-027 |
| [ ] | `SMU-RST-PRIMARY.S3` | SMC, SEP, DTP, the crossbar and the IW converters all leave reset on the primary reset release | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-RST-PRIMARY.S4` | **[contested]** contested state - the two primary reset outputs release in a defined order, with no window in which one subsystem drives another that is still held in reset | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-027 |

### `SMU-PWRGOOD` — Power-good qualification into the DTP power-on reset

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-PWRGOOD.S1` | DTP is held in power-on reset while powergood_stable is deasserted | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-029, SF-030 |
| [ ] | `SMU-PWRGOOD.S2` | DTP becomes responsive to JTAG after powergood_stable asserts | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `port_table.adoc` §port powergood_i | SF-029 |
| [ ] | `SMU-PWRGOOD.S3` | **[contested]** contested state - powergood_i deasserts during operation and DTP returns to power-on reset | `LIVE` | `SMU_SPEC.md` §Clock and Reset; `port_table.adoc` §port powergood_i | SF-030 |

### `SMU-CLK-DOMAINS` — SMU clock and reset domain composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-CLK-DOMAINS.S1` | SMC, SEP, DTP, the crossbar and the IW converters all run on clk_smu_i under rst_primary_smc_clk_no | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-CLK-DOMAINS.S2` | the telemetry domain runs on clk_telemetry_i under rst_telemetry_ni, independently of the primary domain | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-CLK-DOMAINS.S3` | the SEP watchdog runs on the low-frequency clk_sep_wdt_i domain under rst_wdt_n | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-CLK-DOMAINS.S4` | the peripheral domain runs on clk_periph_i under rst_primary_periph_clk_no | `LIVE` | `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-CLK-DOMAINS.S5` | **[contested]** contested state - clk_ref_i runs at a frequency and phase unrelated to clk_smu_i and data crossing between the two domains is still delivered intact | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-042 |
| [ ] | `SMU-CLK-DOMAINS.S6` | **[contested]** contested state - the 512-bit SEP debug bus synchronized into SMC never presents a value mixing two source samples | `LIVE` | `SMU_SPEC.md` §Clock and Reset | SF-043 |

### `SMU-BOOTSEQ-GATE` — External boot-sequence gate on reset release

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-BOOTSEQ-GATE.S1` | reset release is held while ext_boot_seq_done_i is low | `LIVE` | `port_table.adoc` §port ext_boot_seq_done_i | SF-028 |
| [ ] | `SMU-BOOTSEQ-GATE.S2` | reset release proceeds after ext_boot_seq_done_i asserts | `LIVE` | `port_table.adoc` §port ext_boot_seq_done_i | — |
| [ ] | `SMU-BOOTSEQ-GATE.S3` | **[contested]** contested state - ext_boot_seq_done_i never asserts; the SMU stays in a defined held state and no subsystem is released on its own | `LIVE` | `port_table.adoc` §port ext_boot_seq_done_i; `SMU_SPEC.md` §Clock and Reset | SF-028 |

### `SMU-MEMINIT` — SRAM auto-initialization control and completion

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-MEMINIT.S1` | with disable_sram_auto_init_i at its 1 b0 default the initialization runs and init_mem_done_o asserts | `LIVE` | `port_table.adoc` §port disable_sram_auto_init_i; `port_table.adoc` §port init_mem_done_o | SF-046 |
| [ ] | `SMU-MEMINIT.S2` | with disable_sram_auto_init_i asserted the automatic initialization is suppressed | `LIVE` | `port_table.adoc` §port disable_sram_auto_init_i | SF-046 |
| [ ] | `SMU-MEMINIT.S3` | **[contested]** contested state - disable_sram_auto_init_i changes while an initialization is already under way | `LIVE` | `port_table.adoc` §port disable_sram_auto_init_i; `port_table.adoc` §port init_mem_done_o | SF-046 |

### `SMU-SEPWDT-RST` — SEP watchdog reset request into SMC

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-SEPWDT-RST.S1` | a SEP watchdog timeout raises the SEP reset request into SMC | `LIVE` | `SMU_SPEC.md` §Error Handling | SF-031 |
| [ ] | `SMU-SEPWDT-RST.S2` | the request originates in the SEP watchdog clock domain and is delivered into the SMC domain | `LIVE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Clock and Reset | — |
| [ ] | `SMU-SEPWDT-RST.S3` | **[contested]** contested state - a SEP watchdog timeout occurs while SEP is already held in reset | `LIVE` | `SMU_SPEC.md` §Error Handling; `SMU_SPEC.md` §Clock and Reset | SF-031 |

### `SMU-WDT-TIMEOUT` — Watchdog timeout outputs at the SMU boundary

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-WDT-TIMEOUT.S1` | the first watchdog timeout appears on wdt_first_timeout_o toward the reset unit | `LIVE` | `port_table.adoc` §port wdt_first_timeout_o | SF-032 |
| [ ] | `SMU-WDT-TIMEOUT.S2` | the second watchdog timeout appears on wdt_second_timeout_o toward external systems | `LIVE` | `port_table.adoc` §port wdt_second_timeout_o | SF-032 |
| [ ] | `SMU-WDT-TIMEOUT.S3` | **[contested]** contested state - the second timeout occurs while the first is still asserted and both outputs remain individually observable | `LIVE` | `port_table.adoc` §port wdt_first_timeout_o; `port_table.adoc` §port wdt_second_timeout_o | SF-032 |

### `SMU-NDMRESET` — Non-debug-module reset request and process ports

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-NDMRESET.S1` | an ndmreset request is reflected on the corresponding ndmreset_process_o bit | `LIVE` | `port_table.adoc` §port ndmreset_request_i; `port_table.adoc` §port ndmreset_process_o | SF-033 |
| [ ] | `SMU-NDMRESET.S2` | requests are per cluster and one cluster request does not disturb another cluster | `LIVE` | `port_table.adoc` §port ndmreset_request_i | SF-033, SF-050 |
| [ ] | `SMU-NDMRESET.S3` | **[contested]** contested state - an ndmreset request is raised while an AXI transaction from that cluster is outstanding | `LIVE` | `port_table.adoc` §port ndmreset_request_i; `SMU_SPEC.md` §Data Paths | — |

### `SMU-SSRESET` — Subsystem isolation and reset control ports

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-SSRESET.S1` | an isolation request is presented on the isolate_req_o bit for the addressed subsystem | `LIVE` | `port_table.adoc` §port isolate_req_o | SF-034 |
| [ ] | `SMU-SSRESET.S2` | ss_reset_ctrl_o presents one reset_ctrl_t element per subsystem | `CONNECTIVITY` | `port_table.adoc` §port ss_reset_ctrl_o | — |
| [ ] | `SMU-SSRESET.S3` | ss_reset_complete_i is consumed - a subsystem reporting incomplete holds the sequence for that subsystem | `LIVE` | `port_table.adoc` §port ss_reset_complete_i | SF-034 |
| [ ] | `SMU-SSRESET.S4` | ss_config_o is presented at the SMU boundary | `CONNECTIVITY` | `port_table.adoc` §port ss_config_o | — |
| [ ] | `SMU-SSRESET.S5` | cfg_flr_pf_active_i is consumed by the reset sequence | `LIVE` | `port_table.adoc` §port cfg_flr_pf_active_i | SF-034 |
| [ ] | `SMU-SSRESET.S6` | **[contested]** contested state - a subsystem never reports ss_reset_complete_i and the sequence neither advances for it nor blocks the other subsystems indefinitely | `LIVE` | `port_table.adoc` §port ss_reset_complete_i | SF-034 |

### `SMU-ICRESET` — DTP IC_RESET TDR reset override

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-ICRESET.S1` | the reset override mode is entered only when the IC_RESET override is enabled | `LIVE` | `SMU_SPEC.md` §Operating Modes | SF-036 |
| [ ] | `SMU-ICRESET.S2` | the override is cleared by TRST or by a power-on reset | `LIVE` | `SMU_SPEC.md` §Operating Modes | SF-036 |
| [ ] | `SMU-ICRESET.S3` | the override is cleared by clearing the override enables | `LIVE` | `SMU_SPEC.md` §Operating Modes; `port_table.adoc` §port jtag_ic_reset_ext_o | SF-036 |
| [ ] | `SMU-ICRESET.S4` | with Cfg.JTAG_IC_RESET_ENABLE = 0 jtag_ic_reset_ext_o is tied to zero | `DECODE` | `port_table.adoc` §port jtag_ic_reset_ext_o; `SMU_SPEC.md` §Configuration Parameters | — |
| [ ] | `SMU-ICRESET.S5` | the override slice carries .ovrd override enables alongside active-low .val override values | `CONNECTIVITY` | `port_table.adoc` §port jtag_ic_reset_ext_o | SF-035 |
| [ ] | `SMU-ICRESET.S6` | **[contested]** contested state - a reset override is asserted while an AXI transaction is in flight | `LIVE` | `SMU_SPEC.md` §Operating Modes; `SMU_SPEC.md` §Data Paths | SF-036 |

### `SMU-BOOTSTALL` — DTP boot-stall interaction with SMC boot

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-BOOTSTALL.S1` | SMC boot is held while the DTP boot-stall is asserted | `LIVE` | `SMU_SPEC.md` §Sub-Blocks; `SMU_SPEC.md` §Features Feature 3 | SF-037 |
| [ ] | `SMU-BOOTSTALL.S2` | SMC boot proceeds once the boot-stall is released | `LIVE` | `SMU_SPEC.md` §Features Feature 3 | SF-037 |
| [ ] | `SMU-BOOTSTALL.S3` | **[contested]** contested state - the boot-stall is asserted after SMC boot has already started | `LIVE` | `SMU_SPEC.md` §Features Feature 3; `SMU_SPEC.md` §Operating Modes | SF-037 |

### `SMU-DFT-SCAN` — DFT test-enable and scan-reset composition

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-DFT-SCAN.S1` | test_en_i reaches the clock-gater test ports | `CONNECTIVITY` | `port_table.adoc` §port test_en_i | SF-045 |
| [ ] | `SMU-DFT-SCAN.S2` | test_en_i reaches the AXI cell test inputs | `CONNECTIVITY` | `port_table.adoc` §port test_en_i | SF-045 |
| [ ] | `SMU-DFT-SCAN.S3` | scan_rst_ni bypasses the reset synchronizers | `LIVE` | `port_table.adoc` §port scan_rst_ni | — |
| [ ] | `SMU-DFT-SCAN.S4` | with test_en_i at its 1 b0 default and scan_rst_ni at its 1 b1 default the functional reset path is unaffected | `LIVE` | `port_table.adoc` §port test_en_i; `port_table.adoc` §port scan_rst_ni | SF-045 |

### `SMU-JTAG2AXI-SMC` — DTP JTAG2AXI bridge into the SMC local fabric

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-JTAG2AXI-SMC.S1` | a JTAG2AXI write reaches an SMC CSR and changes it | `LIVE` | `SMU_SPEC.md` §Features Feature 3; `SMU_SPEC.md` §Architecture Block Overview | SF-038 |
| [ ] | `SMU-JTAG2AXI-SMC.S2` | a JTAG2AXI read returns the SMC CSR value | `LIVE` | `SMU_SPEC.md` §Features Feature 3 | SF-038 |
| [ ] | `SMU-JTAG2AXI-SMC.S3` | **[contested]** contested state - back-to-back JTAG2AXI accesses through the configured pipeline depth of 3 all complete and none is dropped | `LIVE` | `SMU_SPEC.md` §Configuration Parameters; `SMU_SPEC.md` §Features Feature 3 | SF-038 |
| [ ] | `SMU-JTAG2AXI-SMC.S4` | **[contested]** contested state - a JTAG2AXI access to the SMC fabric while SMC itself is generating fabric traffic | `LIVE` | `SMU_SPEC.md` §Features Feature 3; `SMU_SPEC.md` §Data Paths | — |

### `SMU-OTPAXI-SMC` — OTP-over-JTAG AXI-Lite path to the SMC OTP

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-OTPAXI-SMC.S1` | an OTP-over-JTAG read to the SMC OTP returns a response on the AXI-Lite channel | `LIVE` | `SMU_SPEC.md` §Interfaces; `SMU_SPEC.md` §Architecture Block Overview | SF-039 |
| [ ] | `SMU-OTPAXI-SMC.S2` | an OTP-over-JTAG write to the SMC OTP returns a response on the AXI-Lite channel | `LIVE` | `SMU_SPEC.md` §Interfaces | SF-039 |
| [ ] | `SMU-OTPAXI-SMC.S3` | **[contested]** contested state - back-to-back SMC OTP accesses each receive their own response in order | `LIVE` | `SMU_SPEC.md` §Configuration Parameters; `SMU_SPEC.md` §Interfaces | — |

### `SMU-OTPAXI-SEP` — OTP-over-JTAG AXI-Lite path to the SEP OTP

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-OTPAXI-SEP.S1` | an OTP-over-JTAG read to the SEP OTP returns a response when SEP=1 | `LIVE` | `SMU_SPEC.md` §Interfaces; `SMU_SPEC.md` §Architecture Block Overview | SF-039 |
| [ ] | `SMU-OTPAXI-SEP.S2` | an OTP-over-JTAG write to the SEP OTP returns a response when SEP=1 | `LIVE` | `SMU_SPEC.md` §Interfaces | SF-039 |
| [ ] | `SMU-OTPAXI-SEP.S3` | the SEP OTP read and write pipeline depths are the forced value 2 h3 and do not follow the configured SMC OTP depths | `DECODE` | `SMU_SPEC.md` §Configuration Parameters | SF-040 |

### `SMU-SMC-AXIL-EXT` — SMC AXI-Lite external peripheral port

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-SMC-AXIL-EXT.S1` | an SMC access to the external AXI-Lite port appears at the SMU boundary and its response is returned to SMC | `LIVE` | `port_table.adoc` §port smc_external_req_o | — |
| [ ] | `SMU-SMC-AXIL-EXT.S2` | with the port unused and tied to DECERR the error response is returned to SMC | `LIVE` | `port_table.adoc` §port smc_external_resp_i | SF-044 |

### `SMU-SEP-AXI-EXT` — SEP AXI extension port

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMU-SEP-AXI-EXT.S1` | a SEP access to the extension port appears at the SMU boundary and its response is returned to SEP | `LIVE` | `port_table.adoc` §port sep_external_req_o | — |
| [ ] | `SMU-SEP-AXI-EXT.S2` | with the port unused and tied to DECERR the error response is returned to SEP | `LIVE` | `port_table.adoc` §port sep_external_resp_i | SF-044 |

## 4. Interactions — crosses the spec explicitly demands

| Reviewed | Key | Intent | Features crossed | Spec ref |
|---|---|---|---|---|
| [ ] | `INT-SEP0-COMPOSITION` | in one SEP=0 build the crossbar and SEP are replaced by the direct ID converters AND the SEP-OTP path is terminated by the error slave; the two substitutions are one spec-stated composition and must be observed together | `SMU-NOSEP`, `SMU-SEPOTP-ERRSLV` | `SMU_SPEC.md` §Architecture Block Overview; `SMU_SPEC.md` §Sub-Blocks |
| [ ] | `INT-LC-DBG-BRIDGE` | with dbg_disable asserted the SMC fabric JTAG2AXI bridge is blocked while both OTP JTAG2AXI bridges stay enabled; the selectivity is only observable as one joint measurement | `SMU-LC-DBGDIS`, `SMU-JTAG2AXI-SMC`, `SMU-OTPAXI-SMC`, `SMU-OTPAXI-SEP` | `SMU_SPEC.md` §Security Considerations; `SMU_SPEC.md` §Error Handling |
| [ ] | `INT-BOOTGATE-RESET` | ext_boot_seq_done_i gates the primary reset release, so the gate and the release are one ordered observation | `SMU-BOOTSEQ-GATE`, `SMU-RST-PRIMARY` | `port_table.adoc` §port ext_boot_seq_done_i; `SMU_SPEC.md` §Clock and Reset |
| [ ] | `INT-ALIAS-XBAR` | a SEP access inside the alias window takes the dedicated remap port and is simultaneously absent from every crossbar target port | `SMU-ALIAS-REMAP`, `SMU-XBAR-CONN` | `SMU_SPEC.md` §Data Paths; `SMU_SPEC.md` §Architecture Block Overview |
| [ ] | `INT-CLKSTOP-CHAIN` | an external clock-stop request is aggregated by DTP and coordinated with the SMC CLA clock-stop onto dtp_stop_clks_o, which only a joint request-to-output observation shows | `SMU-CLKSTOP-REQ`, `SMU-CLKSTOP-OUT` | `SMU_SPEC.md` §Features Feature 6; `port_table.adoc` §port dtp_stop_clks_o |
| [ ] | `INT-XTRIG-MODE-CTM` | the mode composition presented to DTP determines whether a CTM port uses its acknowledge, so the mode value and the CTM port behaviour must be observed together | `SMU-XTRIG-MODE`, `SMU-XTRIG-CTM` | `SMU_SPEC.md` §Configuration Parameters; `port_table.adoc` §port xtrig_ctm_src_ack_i |

## 5. Derivation notes (folding and exclusion decisions, verbatim from the feature list)

# SMU feature list (P0 candidate)

Derived forward from the pinned SMU specification sources only, in an anchor-sealed context:
no test list, test source, coverage artefact, RTL or generated register description was opened
while deriving. Every feature, scenario and interaction below traces to pinned specification
text; where the specification asserts a behaviour without giving the observable a checker would
need, the gap is recorded in `SMU_SPEC_REVIEW.md` as an `SF-` finding rather than filled in here.

## Scope applied

The inventory is scoped by the pinned functional boundary alone, never by milestone. In scope is
the SMU integration surface: the 3x3 AXI crossbar and its CSR-programmed apertures, routing and
ID-width conversion between SEP, SMC and the external SMN-facing ports, rejection of unsupported
AXI atomics, interrupt aggregation to SMC, the cross-trigger and clock-stop port composition,
lifecycle broadcast, and SMU-level bring-up and reset sequencing of the composed subsystems.

Out of scope, and therefore deliberately absent: the internal behaviour of SMC, SEP and DTP. A
behaviour enters this list only where the specification names a cross-subsystem or SMU-boundary
path - for example the SEP-to-SMC mailbox exchange, the DTP-to-SMC and DTP-to-OTP bridges, and
the lifecycle signals SEP drives into DTP and SMC - and not where it restates what a subsystem
does inside itself.

## Folding and exclusions the reviewer should know about

- The SEP memory pass-throughs (SRAM, boot ROM, CPU TCM, PKA IMEM/DMEM, KM ROM/SRAM), the SMC
  CPU memory interfaces (ROM, scratch, L1 tag and data), the telemetry ATB receiver array, the
  trace-memory interfaces, the GPIO padring data ports, the PLL/PVT observation ports, the OCTS
  system timer ports and `cluster_ded_o` are **not enumerated**: each is a subsystem-internal
  interface merely presented at the SMU boundary, and its behaviour belongs to that subsystem's
  own specification. If the reviewer reads the boundary as covering them, the inventory
  understates the surface by roughly a dozen further port families.
- `SMU-XTRIG-CTP` folds sixteen CTP channels and four port groups into one feature; the count
  understates the surface by a factor of sixteen per group.
- `SMU-INT-AGG` folds 256 interrupt lines into one feature, and `SMU-MBOX-IRQ-OUT` folds 32
  mailbox interrupts into one.
- `SMU-IRQ-PASSTHRU` folds three distinct SMC-sourced output families (GPIO, UART, sync) that
  share one producer-transport-consumer shape.
- Crossbar datapath widths (56-bit address, 64-bit data, 12-bit user) are carried as scenarios of
  `SMU-EXT-SMN` rather than as a feature of their own, because the specification states them as
  properties of the transport.
- Three port families named in the sources could **not** be admitted as features because the
  specification names no consumer or no producer for them: the memory-repair and MBIST status
  inputs with `skip_mem_repair_o`, `feat_ctrl`, and `powergood_stable_o`. Each is recorded as a
  finding instead.

## Contested states

Concurrency, backpressure, request-during-busy, reset-mid-transaction, simultaneous requests from
two initiators and error-during-error are enumerated as first-class scenarios wherever the
specification admits them, each demanding bounded completion-or-error rather than a happy-path
walk. They are marked in the scenario intent with the words `contested state`.

## Interactions

Interactions are recorded only where the specification explicitly requires two features to be
observed jointly. Six such crosses were found. The absence of any other interaction is a
deliberate and authoritative answer, not an omission.

This artifact is a candidate for human review. Nothing here is approved, and no scenario is
described as covered.

---
*Machine identity:* feature list revision 1, `content_sha256` `c398fc27a8434d50`; pin revision 2; frozen at 2026-09-10T23:38:57-04:00.
