<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC feature list — designer review

Derived from the pinned specification only (sealed derivation, fresh sub-context; no RTL, no tests, no testlists were read). Every row cites the spec section it came from. Status of every record is `candidate`: nothing below is approved until the designer says so.

| Overall disposition | Reviewer | Reviewed at | Blocking comment |
|---|---|---|---|
| `PENDING` (`APPROVE` / `RETURN`) |  |  |  |

**Sources pinned:** `hw/sys/smc/doc/overview.adoc` @ `2f40548ea787`; `hw/sys/smc/doc/clk_rst.adoc` @ `146f602eadc8`; `hw/sys/smc/doc/periphs.adoc` @ `e0df122d885d`; `hw/sys/smc/doc/cpu.adoc` @ `f2cb50de26b0`; `hw/sys/smc/doc/interrupts.adoc` @ `f2cb50de26b0`; `hw/sys/smc/doc/rom.adoc` @ `79b3f4883813`; `hw/sys/smc/doc/fabric.adoc` @ `9333ff3c0515`; `hw/sys/smc/doc/dma.adoc` @ `70964fc0a624`; `hw/sys/smc/doc/dfd.adoc` @ `63552821c2ad`; `hw/sys/smc/doc/zeroer.adoc` @ `2f40548ea787`; `hw/sys/smc/doc/scan_protection.adoc` @ `2ecc7b227e39`; `hw/sys/smc/doc/memmap.adoc` @ `e0df122d885d`; `hw/sys/smc/doc/port_table.adoc` @ `f2cb50de26b0`

| Features | Scenarios | Contested-state scenarios | Interactions | Open spec questions |
|---:|---:|---:|---:|---:|
| 127 | 543 | 67 | 18 | 55 |

## 1. Questions that need a designer's answer

Each is a value or behaviour the specification does not pin. Until answered, every feature it names is derived on an assumption the reviewer has not confirmed. Sorted by severity.

| Decision | ID | Severity | Category | Question | Observed in spec | Features affected |
|---|---|---|---|---|---|---|
| `ANSWER` / `WAIVE` / `RETURN` | SF-014 | **Critical** | SF-MISSING | can the filter decode algorithm be restated in or pinned alongside this chapter? Without entry priority, the address granule and its widening direction, the exact admit-or-block outcome of an overlapping entry set cannot be predicted from the pinned text, and this is the SMC's primary access control | the fabric chapter states that the SMC filters share the decode algorithm of a common filter block - entry priority, match conditions, address range granule and its widening direction, and the response returned to a blocked initiator - and that the algorithm is documented once with that IP, which is not among the pinned sources | `SMC-FILT-IN`, `SMC-FILT-OUT`, `SMC-FILT-NS`, `SMC-FAB-ERRSLV` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-030 | **Critical** | SF-AMBIGUOUS | for this SMC configuration, what is the exact reset state of all sixteen inbound filter entries, and what selects a non-blocking default? A security control whose reset value cannot be pinned cannot be given a checkable expected value | the chapter states that the default filter configuration varies by chiplet type and that most SMC instances default to blocking all external transactions, without saying which instances differ, how they differ, or how the default is selected at integration | `SMC-FILT-IN`, `SMC-FAB-ERRSLV` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-001 | **High** | SF-CONFLICT | which address holds DFX_CTRL_STATUS.STATUS_SMU, and is the memory repair section quoting a stale address or does the DFT status block genuinely alias into the telemetry window? | the memory repair section places the DFX control status register holding mem_repair_done and mem_repair_success at 0xC000_B800, but the component address map assigns BASE+0x000_B000 through BASE+0x000_BFFF to the telemetry receiver and puts DFT control and status at BASE+0x000_D800 through BASE+0x000_DFFF | `SMC-MEMREPAIR`, `SMC-MAP-DECODE`, `SMC-MAP-SPARE`, `SMC-TELEM-RX` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-002 | **High** | SF-CONFLICT | what is the scratchpad size visible in the SMC address map, and if the array is 1 MiB how is the remainder reached - a windowed aperture, a different base, or is the 1 MiB figure a generator maximum rather than the SMC configuration? | the cache and memory hierarchy table gives the local SRAM scratchpad a default size of 1 MiB in 32 banks, while the component address map allocates the scratchpad region BASE+0x006_0000 through BASE+0x007_FFFF, which is 128 KB, inside a 256 KB memory region shared with the 128 KB ROM | `SMC-SPM`, `SMC-MAP-DECODE`, `SMC-SRAM-INIT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-003 | **High** | SF-CONFLICT | which network and which protocol does each of PLIC, CLINT and the per-core watchdog timers actually present, and is the fabric table describing the network segment rather than the endpoint protocol? | the fabric subordinate table lists PLIC, CLINT and the watchdog timer as AXI4 high-performance subordinates, while the interrupt controller table gives PLIC and CLINT an AXI4-Lite interface and the watchdog timers an APB4 interface | `SMC-FAB-AXI4`, `SMC-FAB-AXIL`, `SMC-INT-PLICID`, `SMC-CLINT`, `SMC-WDT`, `SMC-FAB-MGR-CPU` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-010 | **High** | SF-CONFLICT | is the CLA debug interrupt actually non-maskable with a direct core path like the bus error units, or is it an ordinary PLIC source and the DFD wording loose? | the CLA action list describes the debug interrupt as raising a non-maskable interrupt to the CPU, but the interrupt map routes the CLA interrupt through cpu_interrupts_o bit 321 into the PLIC, where it is subject to priority, enable and threshold masking, unlike the bus error units which the interrupt chapter explicitly calls out as bypassing the PLIC | `SMC-CLA-ACTION`, `SMC-INT-INTERNAL`, `SMC-BEU-NMI` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-011 | **High** | SF-MISSING | how does an external controller or BMC request a cool reset - through which register or port, and with what handshake and completion indication? | the reset source table lists a cool reset activated by an external controller or BMC, but names no register, no port and no protocol for that activation; the only concrete cool reset entry point in the pinned set is the GPIO pin 61 input | `SMC-RST-COOL`, `SMC-RST-PRIMARY`, `SMC-ISOLATE-CTRL` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-012 | **High** | SF-MISSING | for each advanced reset feature, which register enables it, which reset events does it apply to, and exactly what state is retained or forced? | the advanced reset features table names reference clock forcing, configuration hold, SRAM preservation and debug state preservation in one line each, with no register, no enable, no scope statement and no description of which reset events each applies to | `SMC-RST-RETAIN` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-015 | **High** | SF-MISSING | what are the numeric values of SMC_ID, OTHER_ID and MMODE_ID, how wide is the field, and which AXI signal carries it on output_axi? | the source ID table names SMC_ID, OTHER_ID and MMODE_ID for the three outbound traffic paths but gives no numeric encoding, no field width and no position within the AXI transaction | `SMC-FAB-SRCID`, `SMC-FILT-IN`, `SMC-FILT-OUT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-016 | **High** | SF-MISSING | which register controls or reports the configuration lock, which descriptor fields does it cover, and what exactly is the response to a write attempted while locked? | the DMA configuration lock is described only as protection against modification during active transfers, with no register, no scope statement over which fields are locked, and no statement of what a locked write does - silently dropped, error response, or status flag | `SMC-DMA-CTRL`, `SMC-DMA-REGIF` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-017 | **High** | SF-MISSING | which register requests an abort, are already-issued AXI transactions allowed to complete or are they abandoned, and precisely which state is preserved and readable afterwards? | the DMA abort capability is described as safe transfer abort with state preservation, with no register, no statement of what happens to already-issued AXI beats and outstanding responses, and no definition of which state is preserved | `SMC-DMA-CTRL`, `SMC-DMA-OUTSTANDING` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-018 | **High** | SF-MISSING | which configuration values does the zeroer validate, what constitutes an invalid configuration, and what does hardware do on rejection - refuse the trigger, set a status flag, or raise an error response? | the zeroer configuration table states that hardware validates configuration parameters, without naming which parameters are checked, which combinations are rejected, or what a rejected configuration produces | `SMC-ZERO-REGIF`, `SMC-ZERO-FSM` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-019 | **High** | SF-MISSING | which register aborts a zeroing operation, what is the defined state of the partially zeroed region afterwards, and when does busy deassert relative to the outstanding write responses? | the zeroer safe abort is one table line with no register, no statement of how much of the region is left zeroed, and no definition of when the busy indication drops relative to outstanding write responses | `SMC-ZERO-FSM`, `SMC-ZERO-OUTSTANDING`, `SMC-ZERO-IRQ` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-020 | **High** | SF-MISSING | what is the subsystem reset protocol - the ordering of isolation, reset control assertion and completion sampling, the timeout if any, and the behaviour when a subsystem withholds its completion? | the port table declares a 32-entry subsystem reset control output, a subsystem configuration output and a completion input defaulting to all ones, but no pinned chapter describes the sequencing between them - when control is asserted, how long completion is awaited, or what happens if completion never arrives | `SMC-SSRST`, `SMC-ISOLATE-CTRL`, `SMC-RST-COOL` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-021 | **High** | SF-MISSING | which resets can be overridden through this struct, what is each member's name and polarity, and does an override take precedence over a concurrently asserted functional reset source? | the reset override input is declared as a typed struct carrying all SMC reset override enables and active-low values, but its members are not enumerated anywhere in the pinned set, so the set of overridable resets is unknown | `SMC-RST-OVERRIDE`, `SMC-RST-PRIMARY`, `SMC-RST-WARM` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-022 | **High** | SF-MISSING | what is the full error-handling behaviour for a corrected single-bit error and for a detected double error in each protected array, and how is the cluster double error output asserted, observed and cleared? | the cache table states parity on the L1 instruction cache and SECDED ECC on the L1 data cache and the scratchpad, and the port table declares a cluster double error detection output, but no pinned text says what a single-bit error does (silent correction, counter, interrupt), what a double error does to the requesting core, or how the double-error output is cleared | `SMC-CPU-ECC`, `SMC-SPM`, `SMC-CPU-L1CACHE`, `SMC-BEU` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-023 | **High** | SF-MISSING | what is the behavioural difference between PRIMARY and SECONDARY mode at the SMC boundary, and which ports or registers carry the synchronization the mode selects? | the system timer is described as a 64-bit timer for multi-chiplet time synchronization with PRIMARY and SECONDARY modes, but no pinned chapter states how the two modes differ at the SMC boundary - what a primary drives, what a secondary consumes, or how a secondary's count is aligned | `SMC-OCTS`, `SMC-GPIO-STRAPS` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-027 | **High** | SF-AMBIGUOUS | what are the exact counts - debug bus width, number of nodes, event-action pairs per node, independent match events and counters - since a coverage contract cannot enumerate per-instance cells without them? | the CLA is described with a set of nodes each holding several event-action pairs, several independent match events, and a small pool of counters, on a fixed-width debug bus whose width is never stated | `SMC-CLA-EVENT`, `SMC-CLA-EAP`, `SMC-DFD-DBGBUS`, `SMC-CLA-ACTION` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-038 | **High** | SF-AMBIGUOUS | in which index space are IDs 156 through 187 defined, and what is the mapping between an SMC mailbox channel number and the external ID it is said to take? | the external mailbox interrupt output is described as 32 interrupts mapped to IDs 156 through 187, but no pinned chapter defines an index space in which those IDs are meaningful; the SMC's own mailbox interrupts occupy vector bits 288 through 319 | `SMC-MBX`, `SMC-INT-MBX-SMC` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-053 | **High** | SF-AMBIGUOUS | which side is authoritative for the peripheral block offsets - the component address map and the address space layout, or the implemented decode that sits 0x2000 lower with I3C relocated to BASE+0x003_A000? Until that is answered no peripheral aperture in this chapter has a checkable expected address, and SF-001 cannot be answered independently of it. | DV measured the implemented peripheral decode and found every peripheral block above the GPIO interface at the component address map offset minus 0x2000, with I3C moved out of the low window altogether. The implemented map places AVSBus at BASE+0x000_4000 where the map row (memmap.adoc:116) gives BASE+0x000_6000, I2C at 0x000_5000 against 0x000_7000 (:119), UART at 0x000_6000 against 0x000_8000 (:122), the eFuse map and eFuse interface together at 0x000_7000 through 0x000_8FFF against 0x000_9000 and 0x000_A000 (:125, :128), the telemetry receiver at 0x000_9000 against 0x000_B000 (:131), the system timer OCTS at 0x000_A000 against 0x000_C000 (:134), the DTP control registers at 0x000_B000 through 0x000_B7FF against 0x000_D000 (:137), the DFT control and status at 0x000_B800 against 0x000_D800 (:140), and the six I3C controllers at 0x003_A000 through 0x003_FFFF against BASE+0x000_4000 + N*0x500 inside the 8 KB I3C region (:113, layout :52). The layout rows for the peripheral controllers (:55, 0x000_6000-0x000_8FFF) and for security, timing and DFT (:58, 0x000_9000-0x000_DFFF) carry the same offsets as the detail rows, so the two spec tables agree with each other and disagree with the implementation. Measured responses: reads at the map own OCTS, DTP and DFT offsets 0xC000_C000, 0xC000_D000, 0xC000_D800 and 0xC000_DFF8 and at the map sixth I3C instance 0xC000_5900 all return DECERR; reads at the map AVSBus, I2C, UART, eFuse and telemetry offsets complete but answer from the next block up, not the named one. SF-001 sees one facet of the same 0x2000 shift from the other side, quoting the DFX control status register at 0xC000_B800, which is the implemented address, against the map 0x000_D800 row. Implementation sources measured: hw/sys/smc/rtl/crossbars/smc_periph_axi_lite_xbar_pkg.sv:110-147 and hw/sys/smc/regs/gen/c/smc_addr.h:54-80. | `SMC-AVSBUS`, `SMC-EFUSE-IF`, `SMC-I2C`, `SMC-MAP-DECODE`, `SMC-MAP-SPARE`, `SMC-OCTS`, `SMC-PERIPH-DECODE`, `SMC-UART` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-054 | **High** | SF-AMBIGUOUS | which side is authoritative for the external-window block offsets - the two window tables, or the implemented map in which every mandatory block above the eFuse SHIM sits 0x1000 higher and the eFuse SHIM takes the window base? The captured straps need their own answer: are they external-window registers at BASE+0x040_5800 as :252 says, or reset-unit registers, in which case SF-007 is moot and the supplementary table should not list them. | DV measured the implemented external window and found every mandatory block 0x1000 above its row, with the eFuse SHIM taking the window base. The GPIO PLL and PVT clock-observation interface and control blocks, the GPIO PoC/PBias control and the GPIO refclk control occupy 0xC040_1000 through 0xC040_102F where the rows (memmap.adoc:222, :225, :228, :231) give BASE+0x040_0000 through BASE+0x040_002F; the 65 per-pad control blocks start at 0xC040_1100 + N*0x20 against BASE+0x040_0100 + N*0x20 (:233); the PLL wrapper is at 0xC040_2000 against BASE+0x040_1000 (:236); the PVT wrapper at 0xC040_3000 against BASE+0x040_2000 (:238); and the eFuse SHIM control block is at 0xC040_0000 - the address :222 gives the PLL clock-observation interface - against BASE+0x040_3000 (:241). The captured GPIO straps are not in this window at all: STRAPS_LO and STRAPS_HI are reset-unit registers at 0xC000_2090 and 0xC000_2094 (hw/sys/smc/bootrom/prod/registers/smc_top_regs.h:187,190), and a read at the supplementary row addresses BASE+0x040_5800 and BASE+0x040_5804 (:252) returns DECERR. The window base itself (:208, :212) is not in dispute: the mandatory region starts at 0xC040_0000 and the supplementary region at 0xC040_4000 as declared, so what moved is the contents, not the window. SF-007 asks where the top of the window is; this finding is about which addresses the blocks inside it occupy. Implementation sources measured: smc_top_regs.h:9433-9503 (clock-observation, PoC/PBias, refclk and per-pad control), :10527 (PLL wrapper), :12408 (PVT wrapper), :13222 (eFuse SHIM control). | `SMC-EXTWIN-MAND`, `SMC-EXTWIN-SUPP`, `SMC-FILT-AXIL-PROT`, `SMC-GPIO-EXTCTRL`, `SMC-GPIO-STRAPS`, `SMC-PVT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-004 | **Medium** | SF-CONFLICT | which two peripheral interrupt bits carry the GPIO OR reductions, given that bit 30 is assigned to the AXI hang detector OR in the indexed map? | the indexed interrupt map drives the lower-half and upper-half GPIO OR reductions onto peripheral_interrupts_o bits 28 and 29, while the port table states the raw GPIO vector is already OR-reduced into peripheral_interrupts_o[30:29] | `SMC-INT-PERIPHMAP`, `SMC-GPIO-IRQ`, `SMC-FAB-HANGDET` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-005 | **Medium** | SF-CONFLICT | how many PLIC sources are active and how many reserved, and which specific indices are the reserved ones? | the PLIC section describes 332 interrupt sources as 327 active and 5 reserved, while the interrupt source summary table for the same block says 332 sources of which 326 are active | `SMC-INT-PLICID`, `SMC-INT-VECTOR` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-006 | **Medium** | SF-CONFLICT | how are the three telemetry receiver instances addressed - a shared wrapper like the UART and I2C entries, or three distinct apertures the address map does not yet show? | the peripheral summary gives the telemetry receiver 3 instances and the interrupt map carries three telemetry interrupts, but the component address map lists the telemetry receiver as 1 instance occupying a single 4 KB region with no per-instance stride | `SMC-TELEM-RX`, `SMC-PERIPH-DECODE`, `SMC-INT-PERIPHMAP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-007 | **Medium** | SF-CONFLICT | what is the true top address of the AXI-Lite external window, and do the strap registers sit inside it or in a separate aperture? | the address space layout and the component address map both bound the AXI-Lite external window at BASE+0x040_57FF, but the supplementary region table places the captured GPIO strap registers at BASE+0x040_5800 and BASE+0x040_5804, outside that bound | `SMC-EXTWIN-SUPP`, `SMC-GPIO-STRAPS`, `SMC-MAP-DECODE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-008 | **Medium** | SF-CONFLICT | which bits of the 64-bit descriptor fields are implemented, and what happens to a programmed value whose upper bits exceed the 56-bit hardware width - truncation, an error, or undefined? | the transfer parameter table describes 64-bit source address, destination address, transfer size and strides, while the type definitions state 56-bit transfer length and stride widths matching the address width, and the AXI master characteristics give a 56-bit address | `SMC-DMA-XFER`, `SMC-DMA-REGIF`, `SMC-DMA-BURST` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-009 | **Medium** | SF-CONFLICT | which bits of the 64-bit destination address and size registers are implemented, and does programming a value above the 56-bit range raise the validation or overflow condition the chapter mentions? | the zeroer configuration table gives a 64-bit destination byte address and a 64-bit byte count, while the AXI master characteristics give a 56-bit address width | `SMC-ZERO-REGIF`, `SMC-ZERO-AXI`, `SMC-ZERO-DATA` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-013 | **Medium** | SF-MISSING | which register fields carry the hysteresis, threshold and per-module enables, what are their reset values, and which functional blocks are individually gateable? | the clock gating parameter table gives a 6-bit programmable hysteresis, a per-module activity detection, a configurable enable threshold and individual module gating, but names no register, no reset default and no list of which modules are gated | `SMC-CLKGATE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-024 | **Medium** | SF-MISSING | where is the PVT digital control and status interface specified - which registers exist in the PVT wrapper aperture, and what does the thermal sensor input gate or report? | PVT is named in the boundary and appears as an aperture in the external window and as two ports, but the peripheral summary does not list it and no pinned chapter describes its digital control and status interface | `SMC-PVT`, `SMC-EXTWIN-MAND`, `SMC-GPIO-EXTCTRL` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-025 | **Medium** | SF-MISSING | which clock is the FLR trigger sampled against at the SMC boundary, and is there a PCIe clock port the port table omits or is the input treated as asynchronous? | the FLR section states that the trigger crosses from the PCIe clock domain into the SMC and reference domains, but the port table declares no PCIe clock input and the FLR active input is listed without an associated clock | `SMC-FLR-CDC`, `SMC-FLR-SEQ` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-026 | **Medium** | SF-MISSING | which core interrupt input and architectural cause does a bus error unit drive, and what is the acknowledge and clear sequence software must perform? | bus error unit interrupts are described as connecting directly to each core's interrupt input with non-maskable-like behavior, but the pinned text does not say which core interrupt input or architectural cause is used, nor how the interrupt is acknowledged and cleared | `SMC-BEU-NMI`, `SMC-BEU` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-028 | **Medium** | SF-MISSING | can the asset class definitions be restated or pinned alongside this chapter, so that the scan and scandump obligation attached to each class is verifiable from the pinned set alone? | the scan protection chapter classifies SMC eFuse content into Class 1a, 1b, 2 and 3 but states that those classes are defined authoritatively in a lifecycle controller chapter that is not among the pinned sources | `SMC-SCAN-CLASS1`, `SMC-SCAN-NOSECRET`, `SMC-SCAN-RANGEMAP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-029 | **Medium** | SF-MISSING | is any I3C behaviour normative for this milestone beyond aperture decode and the tied-low interrupt bits, and if not should I3C be declared out of scope for the SMC verification boundary? | I3C is instantiated six times, occupies an 8 KB aperture, and contributes six interrupt vector bits, but the peripheral summary states it is a work in progress to be documented when officially verified and the memory map explicitly omits its register block | `SMC-PERIPH-DECODE`, `SMC-PERIPH-PARAM`, `SMC-INT-PERIPHMAP`, `SMC-CLK-PERIPH` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-031 | **Medium** | SF-AMBIGUOUS | does the error-slave sentence apply only to the inbound filter, or is there an outbound case in which an unmatched transaction also errors rather than being permitted? | the chapter states that the inbound filter blocks traffic matching no entry while the outbound filter permits it, but a later paragraph says without qualification that transactions no entry admits are routed to an error slave which returns a decode error | `SMC-FILT-OUT`, `SMC-FILT-NS`, `SMC-FAB-ERRSLV` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-032 | **Medium** | SF-AMBIGUOUS | does hardware reject or clamp a zero region size, or is the consequence purely a firmware obligation? If the latter, what is the exact observable behaviour of a local access once the windows are collapsed? | firmware is told it must not program the region size CSR to zero because that collapses both windows and routes SMC CPU accesses out through the output fabric, but no hardware guard, minimum value or error response is specified | `SMC-FAB-APERTURE`, `SMC-MAP-DUALBASE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-033 | **Medium** | SF-AMBIGUOUS | what are the widths, reset values and units of the FLR pre-reset delay and reset assertion duration counters, and is the unit one reference clock cycle or a prescaled tick? | the two FLR timing registers are named but their field widths, reset values and time units are not given; the section says only that the timing operates in the reference clock domain | `SMC-FLR-SEQ` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-034 | **Medium** | SF-AMBIGUOUS | is any other status bit, error flag or side channel available to distinguish a dropped reserved-bank request from a rejected malformed command, or is the ambiguity intended and software expected never to touch the reserved banks? | the chapter states that reading a reserved stream bank returns zero with no bus error, which is the same value returned for a command that was not set up correctly, and explicitly notes that software cannot distinguish a dropped request from a rejected one by the returned value | `SMC-DMA-STREAM-RSVD`, `SMC-DMA-STREAM0` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-035 | **Medium** | SF-AMBIGUOUS | how many cycles wide is each completion pulse, in which clock domain, and is the PLIC source edge-latched so that a single-cycle pulse cannot be missed? | the DMA and zeroer completion interrupts are described as falling-edge pulses of their respective busy outputs, but the pulse width, the clock domain it is measured in, and whether the PLIC latches it are not stated | `SMC-DMA-IRQ`, `SMC-ZERO-IRQ`, `SMC-INT-INTERNAL`, `SMC-PLIC-CLAIM` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-036 | **Medium** | SF-AMBIGUOUS | at cold reset, do all four cores fetch from the ROM vector, or does one core boot while the others are held, and what is the reset value of each per-core reset vector input? | the ROM chapter gives a single cold-reset CPU vector while the CPU chapter gives each core an independently configurable 56-bit reset vector, without saying whether all four cores take the ROM vector at cold reset or whether only one core starts | `SMC-CPU-RSTVEC`, `SMC-CPU-EXEC`, `SMC-ROM-MAP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-037 | **Medium** | SF-AMBIGUOUS | is tying the I3C interrupt sources to zero the specified behaviour for this release, so that the vector bits reading zero is a checkable requirement, or is it a temporary integration state that a test must not lock in? | the six I3C interrupt vector entries note that the peripheral-domain I3C interrupt sources are currently tied to zero, using wording that describes the present state rather than a specification requirement | `SMC-INT-PERIPHMAP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-039 | **Medium** | SF-AMBIGUOUS | which reset does this input gate, is the gate level-sensitive or edge-triggered, and where does it sit in the fuse sense, repair and MBIST ordering? | the external boot sequence completion input is described as gating reset release, without saying which reset is gated, whether the gating is level or edge based, and how it relates to the fuse sense and memory repair ordering the CPU chapter gives | `SMC-PWRSEQ-GATE`, `SMC-MEMREPAIR`, `SMC-RST-PRIMARY` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-044 | **Medium** | SF-UNTESTABLE | is there any defined post-reset value or initialization guarantee for these registers, or should verification treat their post-reset content as unconstrained and check only the post-initialization behaviour? | the chapter states that the PLIC priority and enable registers have no hardware reset and that the machine interrupt enable CSR also has no reset value, so no post-reset expected value exists for them and undefined content can block setting the global interrupt enable | `SMC-PLIC-INIT`, `SMC-PLIC-PRIO`, `SMC-PLIC-ENABLE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-045 | **Medium** | SF-TERM | are BP_POWERGOOD and BP_RESETN the board-level names of the power-good input and the cold reset input respectively, and should one naming be made canonical? | the reset chapter names the board signals BP_POWERGOOD and BP_RESETN while the port table declares a power-good input and a cold reset input under different names, with no statement that they are the same nets | `SMC-RST-POR`, `SMC-RST-COLD`, `SMC-RST-TAP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-046 | **Medium** | SF-TERM | are Core Reset and Warm Reset the same reset level under two names, and can one term be made canonical across the chapter? | the chapter says the two primary reset levels are Primary Reset and Core Reset, and the reset source table uses Core Reset as the scope of the watchdog and debug resets, but the section that follows is headed Warm Reset and no text equates the two terms | `SMC-RST-WARM`, `SMC-RST-PRIMARY` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-051 | **Medium** | SF-AMBIGUOUS | is the set of cluster-bound global interrupts exactly the four per-core watchdog timers, or are there others? Without a closed list the PLIC source inventory cannot be completed | the chapter says that additional global interrupts are bound inside the CPU cluster and do not appear on the raw vector, giving the per-core watchdog timers at indices 328 to 331 only as an example, so the complete set of cluster-bound globals is not enumerated | `SMC-INT-PLICID`, `SMC-INT-VECTOR`, `SMC-WDT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-055 | **Medium** | SF-AMBIGUOUS | for each of these four windows, which side is authoritative - the declared extent or the implemented one? Is the miscellaneous wrapper 2 KiB or 0x20C, and is the CLA 36 KiB or 16 KiB? And are the Debug Unit and Address Remapping regions meant to be reachable from an inbound manager at all, or only from the CPU and JTAG paths - in which case the layout table should say so, and SF-043 should be answered against that scope rather than against the table as written. | DV measured four declared windows that the implementation does not decode over their declared extent. The miscellaneous wrapper row (memmap.adoc:107) declares BASE+0x000_2800 through BASE+0x000_2FFF, 2 KiB, but the generated register map gives the block a length of 0x20C (hw/sys/smc/regs/gen/c/smc_addr.h:27-28) and a read at the declared top 0xC000_2FF8 returns DECERR. The CLA is declared as 36 KiB from BASE+0x016_0000 through BASE+0x016_8FFF in both the layout row (:74) and the component map row (:178), but the block is 0x4000 long (smc_addr.h:412-413) and a read at 0xC016_8FF8 returns SLVERR. The Debug Unit region (:43, BASE+0x000_1000 through BASE+0x000_1FFF) and the Address Remapping region (:80, BASE+0x080_0000 through BASE+0x1FF_FFFF) have no rule at all in the local crossbar: hw/sys/smc/rtl/crossbars/smc_local_xbar_pkg.sv:279-321 gives the watchdog and debug front port only BASE+0x000_0000 through BASE+0x000_0FFF and has no rule covering BASE+0x080_0000, so 0xC000_1000 returns DECERR and 0xC080_0000 returns no response at all. SF-043 asks what occupies BASE+0x080_0000 through BASE+0x0FF_FFFF inside the remapping region; the new fact is that the region carries no decode rule, so neither that hole nor the M-mode and Xvisor regions above it (:185, :188) are reachable from an inbound manager. | `SMC-CPU-DEBUG`, `SMC-FAB-PRIVREMAP`, `SMC-MAP-DECODE`, `SMC-MAP-SPARE` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-040 | **Low** | SF-AMBIGUOUS | in which clock domain are the 16 pipeline stages, and what consumer requires that specific delay? | the delayed fuse reset output is described as delayed by 16 pipeline stages without naming the clock the stages are in or the purpose of the delay | `SMC-EFUSE-IF` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-041 | **Low** | SF-AMBIGUOUS | is there any required frequency relationship or ratio bound between the SMC clock and the peripheral clock that the AXI-Lite CDC bridges depend on, or is the crossing fully asynchronous with no ratio constraint? | the peripheral clock domain has a stated 100 MHz minimum but no upper limit, which is left to the integrator, and no relationship to the SMC clock frequency is given | `SMC-CLK-PERIPH`, `SMC-PERIPH-CDC` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-042 | **Low** | SF-AMBIGUOUS | are the two unexposed synchronized resets internal only, or does the port table omit them? Their observability decides whether their synchronization can be checked at the SMC boundary at all | the reset synchronization table names four synchronized reset signals, but the port table exposes only the primary reset synchronized to the SMC clock and to the reference clock; the warm reset in the SMC domain and the primary reset in the peripheral domain appear on no port | `SMC-RST-SYNC`, `SMC-RST-WARM`, `SMC-CLK-PERIPH` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-043 | **Low** | SF-AMBIGUOUS | what occupies BASE+0x080_0000 through BASE+0x0FF_FFFF, and should an access there decode to a remap region or to the error slave? | the address space layout assigns BASE+0x080_0000 through BASE+0x1FF_FFFF to address remapping, but the component map places the M-mode region at BASE+0x100_0000 and the Xvisor region at BASE+0x180_0000, leaving BASE+0x080_0000 through BASE+0x0FF_FFFF unassigned inside the declared remapping region | `SMC-MAP-DECODE`, `SMC-FAB-PRIVREMAP` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-047 | **Low** | SF-TERM | should the port be renamed to reflect that it carries a synchronisation bit rather than an interrupt, so that integrators do not wire it into an interrupt aggregator? | the port is named as an interrupt output but its description states it is a software-controlled global synchronisation bit and explicitly not an interrupt aggregate output | `SMC-SYNC-BIT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-048 | **Low** | SF-TERM | is the interface width parameter the same quantity as the documented total CPU interrupt count, and can a single name be used? | the classification section refers to system-wide events being delivered over an interface named by a width parameter that is defined nowhere in the pinned set, while the vector map uses a differently named total interrupt count | `SMC-INT-VECTOR` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-049 | **Low** | SF-TYPO | can the unterminated literal be closed and the rubric directive converted to an AsciiDoc heading, so that the filtering section is addressable as a section reference? | the address remapping paragraph contains an unterminated inline literal around the remap module path, and the traffic filtering heading is written as a reStructuredText rubric directive rather than an AsciiDoc heading, so it does not render as a section | `SMC-FAB-ALIAS`, `SMC-FILT-IN`, `SMC-FILT-OUT` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-050 | **Low** | SF-AMBIGUOUS | what is the normative access-control requirement for the lock matrix, expressed as behaviour rather than as a claim about an existing test? A specification's assertion about verification cannot serve as the requirement being verified | the chapter closes with a verification claim that an existing test covers the relocated lock words functionally and that moving them does not change access-control behaviour, but it does not state the behavioural requirement that claim is made against - which lock and unlock combinations must succeed or be refused | `SMC-EFUSE-LOCKS`, `SMC-SCAN-CLASS1`, `SMC-SCAN-DOWNSTREAM` |
| `ANSWER` / `WAIVE` / `RETURN` | SF-052 | **Low** | SF-MISSING | what is the lifecycle state encoding, and which SMC behaviour depends on it, given that the lifecycle controller itself is out of the verification boundary? | the lifecycle state input is declared as a differentially encoded 8-bit value with one named tie value, but the encoding table mapping values to lifecycle states is not in the pinned set, and no pinned text says what the SMC does with the value | `SMC-LCSTATE`, `SMC-SCAN-CLASS1` |

## 2. Features — one row per distinct producer → transport → consumer behaviour

Tick **Reviewed** when the intent and the triad match what the design does. If the spec section cited does not say what the row claims, that is a `RETURN`, not a fix to the row.

| Reviewed | Key | Intent | Producer → Transport → Consumer | Spec ref | Scenarios | Contested | Open SF |
|---|---|---|---|---|---:|---:|---|
| [ ] | `SMC-CLK-SMC` | clk_smc_i clocks the CPU cluster, the local fabric and the fabric control logic | clk_smc_i from the platform PLL output → SMC primary clock domain distribution → CPU cluster and caches, AXI crossbar and interconnect, address remap and filter control logic | `clk_rst.adoc#The` §SMC Clock Domain | 3 | 0 | — |
| [ ] | `SMC-CLK-REF` | clk_ref_i provides the stable low-speed timing base for timers, reset synchronization, PLL reference and debug | clk_ref_i from the platform PLL reference clock → reference clock domain distribution → CLINT, OCTS system timer, reset-domain-crossing synchronizers, JTAG/debug infrastructure, PLL frequency synthesis | `clk_rst.adoc#The` §Reference Clock Domain | 4 | 0 | — |
| [ ] | `SMC-CLK-PERIPH` | clk_periph_i clocks the peripheral controllers in the SMC peripheral wrapper independently of the CPU clock | clk_periph_i from the platform clock generation infrastructure → peripheral clock domain inside smc_external_peripheral_wrapper → AVSBus controller, I2C controller, UART 16550, I3C controller | `clk_rst.adoc#The` §Peripheral Clock Domain | 3 | 1 | SF-029, SF-041, SF-042 |
| [ ] | `SMC-CLK-TELEM` | the telemetry receiver captures ATB data on the clock supplied with that data stream | clk_telemetry_i sourced from the telemetry data interface by the integrator → telemetry clock domain, reset by rst_telemetry_ni → telemetry receiver capture and processing logic | `clk_rst.adoc#The` §Telemetry Clock Domain; hw/sys/smc/doc/port_table.adoc#clk_telemetry_i@f2cb50de | 2 | 0 | — |
| [ ] | `SMC-PERIPH-CDC` | register accesses are decoded at SMC clock speed and cross into the peripheral clock per master port | CPU fabric register access arriving at the peripheral register crossbar on clk_smc → peripheral register crossbar on clk_smc, then a per-master-port AXI-Lite CDC bridge → the addressed peripheral controller in the clk_periph domain | `clk_rst.adoc#The` §Peripheral Clock Domain | 3 | 1 | SF-041 |
| [ ] | `SMC-CLKGATE` | per-module clock gating with hysteresis trades responsiveness against dynamic power | per-module activity detection and the gating enable/threshold configuration → clock gating cells with 6-bit programmable hysteresis → the gated functional block's clock | `clk_rst.adoc#Clock` §and Reset-Based Power Management Integration | 5 | 1 | SF-013 |
| [ ] | `SMC-RST-POR` | BP_POWERGOOD is stretched into powergood_stable which qualifies the SMC functional cold reset path | BP_POWERGOOD board power-good indicator on powergood_i → power-good stretcher producing powergood_stable → the SMC functional cold reset qualification path and powergood_stable_o to external systems | `clk_rst.adoc#Reset` §Architecture; hw/sys/smc/doc/port_table.adoc#powergood_i@f2cb50de | 4 | 1 | SF-045 |
| [ ] | `SMC-RST-TAP` | pwr_on_rst_ni combined with pad TRST forms the effective TAP reset, so JTAG/TDR state resets only on POR | BP_POWERGOOD routed into the JTAG/DTP stack as pwr_on_rst_ni, and the pad TRST signal → the AND of TRSTN and pwr_on_rst_ni inside jtag_ptap → TAP and TDR reset state | `clk_rst.adoc#Reset` §Architecture | 3 | 0 | SF-045 |
| [ ] | `SMC-RST-COLD` | BP_RESETN drives the SMC functional cold reset path once power-good is stable, excluding JTAG/TDR state | BP_RESETN on the cold reset input → the SMC functional cold reset path, qualified by powergood_stable → rst_primary_no and the SMC functional logic it holds | `clk_rst.adoc#SMC` §Reset Sources and Characteristics; hw/sys/smc/doc/port_table.adoc#rst_cold_ni@f2cb50de | 2 | 0 | SF-045 |
| [ ] | `SMC-RST-PRIMARY` | rst_primary_no is the top-level functional reset for the CPU, fabric, peripherals and SMC configuration registers | power-on reset, cool reset or functional cold reset activation → rst_primary_no distributed through the reset unit → CPU cores and caches, fabric infrastructure, peripheral controllers, SMC control and configuration registers | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | 5 | 1 | SF-011, SF-021, SF-039, SF-046 |
| [ ] | `SMC-RST-COOL` | a cool reset is a primary-class reset that allows selective subsystem isolation | external controller or BMC request, or rst_cool_n_from_pin_i on GPIO pin 61 → the reset unit cool reset sequence → the isolated subsystems and the SMC primary reset path | `clk_rst.adoc#SMC` §Reset Sources and Characteristics; `periphs.adoc#SMC` §Peripheral Summary | 3 | 0 | SF-011, SF-020 |
| [ ] | `SMC-RST-WARM` | rst_warm_no targets the cores, their private caches and the core-local blocks without disturbing the rest of the SMC | cascaded primary reset, watchdog timeout, or a debug-interface reset → rst_warm_no distributed through the reset unit → CPU cores and private caches, PLIC, CLINT, per-core watchdog timers, bus error units | `clk_rst.adoc#Warm` §Reset (rst_warm_no) | 5 | 1 | SF-021, SF-042, SF-046 |
| [ ] | `SMC-RST-SYNC` | every reset is asserted asynchronously and deasserted synchronously in its target clock domain through multi-stage synchronizers | an asserted reset source in the reset unit → prim_rst_sync synchronization primitives with multiple flip-flop stages in the target domain → rst_primary_smc_clk_no, rst_warm_smc_clk_no, rst_primary_ref_clk_no and rst_primary_periph_clk_no consumers | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | 5 | 1 | SF-042 |
| [ ] | `SMC-ISOLATE-CTRL` | isolate_req_o for each of 32 subsystems is the logical OR of the software, pin and FLR isolation sources | ISOLATE_REQ_REG software writes, isolate_req_pin_i with ISOLATE_REQ_PINEN_REG, and FLR detection with ISOLATE_REQ_SMCEN_REG → the reset unit isolation aggregation logic → isolate_req_o[31:0] to the 32 isolated subsystems | `clk_rst.adoc#Isolation` §Control Architecture; hw/sys/smc/doc/port_table.adoc#isolate_req_o@f2cb50de | 5 | 1 | SF-011, SF-020 |
| [ ] | `SMC-FLR-SEQ` | an FLR trigger runs a two-stage timed sequence that isolates subsystems and then asserts cool reset for a programmed duration | the synchronized and edge-detected FLR active signal → a two-stage state machine with down-counters in the reference clock domain → subsystem isolation and the cool reset assertion delivered to the isolated subsystems | `clk_rst.adoc#Programmable` §Reset Timing | 4 | 1 | SF-025, SF-033 |
| [ ] | `SMC-FLR-CDC` | the FLR trigger crosses from the PCIe clock domain into the SMC and reference domains and is edge-detected there | cfg_flr_pf_active_i in the PCIe clock domain → multi-stage synchronizers into the SMC clock domain and into the reference clock domain → rising-edge detection that initiates the isolation and reset sequence | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization; hw/sys/smc/doc/port_table.adoc#cfg_flr_pf_active_i@f2cb50de | 4 | 1 | SF-025 |
| [ ] | `SMC-REPAIR-BYPASS` | skip_mem_repair_o bypasses SRAM repair for FLR or pin isolation and for the BYPASS_SRAM_REPAIR strap | FLR-triggered or pin-based isolation assertion, or the BYPASS_SRAM_REPAIR strap on GPIO pin 13 → the reset unit skip_mem_repair_o output → the memory repair and MBIST logic in the boot sequence | `clk_rst.adoc#Memory` §Test Bypass; `cpu.adoc#Memory` §Repair | 4 | 0 | — |
| [ ] | `SMC-RST-RETAIN` | reference clock forcing, configuration hold, SRAM preservation and debug state preservation carry selected state across a reset | a reset event in the reset unit with the corresponding advanced feature enabled → the reset unit retention and clock-forcing controls → the forced clock source, the retained configuration, the preserved SRAM contents and the preserved debug state | `clk_rst.adoc#Advanced` §Subsystem Reset Capabilities | 4 | 0 | SF-012 |
| [ ] | `SMC-RST-OVERRIDE` | jtag_reset_ctrl_i lets the DTP override SMC reset values through JTAG IC_RESET | DTP driving jtag_reset_ctrl_i through the JTAG IC_RESET path → the typed reset-override control struct carrying enables and active-low values → the SMC reset unit reset outputs | hw/sys/smc/doc/port_table.adoc#jtag_reset_ctrl_i@f2cb50de | 2 | 0 | SF-021 |
| [ ] | `SMC-SSRST` | the reset unit drives reset control and configuration to 32 subsystems and consumes their completion status | the SMC reset unit subsystem reset sequencer → ss_reset_ctrl_o and ss_config_o out, ss_reset_complete_i back → the 32 controlled subsystems and the sequencer that waits on their completion | hw/sys/smc/doc/port_table.adoc#ss_reset_ctrl_o@f2cb50de; `periphs.adoc#SMC` §Peripheral Summary | 4 | 1 | SF-020 |
| [ ] | `SMC-SYNC-BIT` | SYNC_REG.sync in the reset unit drives sync_irq_o as a software-controlled global synchronisation signal, not an interrupt aggregate | a software write to SYNC_REG.sync in the reset unit → the reset unit register output path → sync_irq_o to external systems | hw/sys/smc/doc/port_table.adoc#sync_irq_o@f2cb50de | 2 | 0 | SF-047 |
| [ ] | `SMC-PWRSEQ-GATE` | ext_boot_seq_done_i reports memory repair and shadow-register override completion and gates reset release | the external boot and repair controller driving ext_boot_seq_done_i → the eFuse controller boot-gating path → the reset release that is withheld until the signal asserts | hw/sys/smc/doc/port_table.adoc#ext_boot_seq_done_i@f2cb50de | 2 | 1 | SF-039 |
| [ ] | `SMC-CPU-EXEC` | the Rocket cluster executes RV64GC firmware on four in-order cores at three privilege levels | instruction stream fetched after reset release → the four-core Rocket cluster in-order five-stage pipelines → architectural state updated by retired instructions | `cpu.adoc#Processor` §Core Overview | 4 | 0 | SF-036 |
| [ ] | `SMC-CPU-RSTVEC` | each core has an independent reset and a 56-bit programmable reset vector, defaulting to the cold-reset ROM vector | rst_core_N_ni and reset_vector_N_i for cores 0 to 3 → the per-core reset and reset-vector configuration path → the core's first instruction fetch address after reset release | `cpu.adoc#Reset,` §Boot, and Initialization; `rom.adoc#Boot` §ROM | 4 | 1 | SF-036 |
| [ ] | `SMC-CPU-L1CACHE` | each core has a private 4 KiB two-way L1 instruction cache and a 4 KiB two-way L1 data cache with distinct write policies | core instruction fetch and data access → the private L1 instruction and data cache arrays, sized by icache and dcache tag/data configuration → the core pipeline on a hit and the cluster memory path on a miss | `cpu.adoc#Cache` §and Memory Hierarchy | 5 | 0 | SF-022 |
| [ ] | `SMC-CPU-ECC` | the L1 instruction cache is parity protected while the L1 data cache and scratchpad carry SECDED ECC, with double errors reported out of the cluster | a corrupted word read from the I-cache, D-cache or scratchpad array → the parity and SECDED ECC check logic in the cluster memory path → the corrected data returned to the core and cluster_ded_o raised on a double error | `cpu.adoc#Cache` §and Memory Hierarchy; hw/sys/smc/doc/port_table.adoc#cluster_ded_o@f2cb50de | 4 | 0 | SF-022 |
| [ ] | `SMC-SPM` | the shared local SRAM gives deterministic accesses independent of cache state with per-bank sizing and power management | a core load or store to the scratchpad region → the cluster TileLink path to the banked scratchpad interface → the addressed scratchpad bank through scratch_ram_intf_req_o and scratch_ram_intf_rsp_i | `cpu.adoc#Cache` §and Memory Hierarchy; hw/sys/smc/doc/port_table.adoc#scratch_ram_intf_req_o@f2cb50de | 4 | 0 | SF-002, SF-022 |
| [ ] | `SMC-SRAM-INIT` | hardware initializes SRAM on reset, reports completion and can be disabled for custom boot procedures | reset deassertion with disable_sram_auto_init_i deasserted → the cluster hardware SRAM initialization engine → initialized SRAM contents and init_mem_done_o presented to control logic | `cpu.adoc#Reset,` §Boot, and Initialization; hw/sys/smc/doc/port_table.adoc#init_mem_done_o@f2cb50de | 4 | 1 | SF-002 |
| [ ] | `SMC-MEMREPAIR` | repair data sensed from eFuse configures redundant SRAM elements before MBIST and before the cluster is released | fuse_sense_done_o asserted by the eFuse controller after sensing completes → the BIRA repair flow reading the eFuse BIRA repair_data field and configuring redundant memory elements → the repaired SRAM arrays, and the DFX control status bits the ROM firmware reads | `cpu.adoc#Memory` §Repair | 6 | 1 | SF-001, SF-039 |
| [ ] | `SMC-TL2AXI` | the cluster-internal TileLink bus is protocol-bridged to AXI4 and AXI4-Lite at the cluster boundary | a TileLink transaction issued inside the CPU cluster → the TileLink-to-AXI protocol bridges at the cluster boundary → the SMC fabric on the AXI4 L2 frontend and the AXI4-Lite MMIO port | `cpu.adoc#Cache` §and Memory Hierarchy; `cpu.adoc#System` §Interfaces | 2 | 0 | — |
| [ ] | `SMC-CLUSTER-ISO` | each cluster AXI port is drained and held at safe values before a cluster reset takes effect, and the boundary self-isolates on cold boot | a pending cluster reset, or cold boot before SRAM initialization completes → two axi_isolate instances each sized for four outstanding transactions, plus the clamped non-AXI status crossings → the SMC fabric on the other side of the cluster boundary | `cpu.adoc#Cluster` §Boundary Isolation | 7 | 2 | — |
| [ ] | `SMC-ISO-DRAIN` | the control logic withholds a pending cluster reset until the isolation logic reports that both ports have drained | smc_cpu_ctrl_wrap asserting isolate_req_i when a software cluster reset is pending → the isolate_req_i and drained_o handshake between control logic and the isolation blocks → the withheld cluster reset, released only after drained_o asserts | `cpu.adoc#Drain` §Handshake | 4 | 1 | — |
| [ ] | `SMC-ISO-RDC` | the isolate control flops and the axi_isolate flops sit in different reset domains, making the asynchronous watchdog warm reset a reset-domain crossing | a watchdog-timeout warm reset asserted asynchronously, or a synchronous CPU CSR reset-control write → the isolate-control flops held by the cluster uncore/core reset and the axi_isolate flops held by primary reset → the axi_isolate state that observes the crossing | `cpu.adoc#Reset-Domain` §Crossing | 2 | 1 | — |
| [ ] | `SMC-WDT` | each core has a dedicated watchdog with a configurable timeout and a staged warning before reset, disableable during debug | expiry of a per-core watchdog counter without a software kick → the per-core watchdog timer block at its mapped offset and its timeout outputs → the warning interrupt, the reset unit through wdt_first_timeout_o, and external systems through wdt_second_timeout_o | `cpu.adoc#Watchdog` §Timer System; `interrupts.adoc#SMC` §interrupt sources | 6 | 1 | SF-003, SF-051 |
| [ ] | `SMC-BEU` | the per-core bus error units monitor AXI traffic and capture and classify decode, slave and timeout errors with their transaction context | an erroring AXI transaction observed on a core's bus path → the per-core bus error unit at its mapped offset → the error status, classification and captured address and transaction context read by management software | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | 6 | 1 | SF-022, SF-026 |
| [ ] | `SMC-BEU-NMI` | bus error unit interrupts bypass the PLIC and reach each core directly as a non-maskable interrupt | a bus error unit raising its interrupt → the direct per-core interrupt connection, bypassing the PLIC → the CPU core interrupt input, regardless of PLIC configuration or masking | `interrupts.adoc#Bus` §Error Unit interrupts | 2 | 0 | SF-010, SF-026 |
| [ ] | `SMC-CPU-DEBUG` | a dedicated APB interface and JTAG give per-core access to registers, memory and breakpoints independently of functional resets | an external debugger driving the JTAG port or the debug APB interface → the RISC-V debug module at its mapped aperture, per core → core registers, memory, hardware and software breakpoints, and the overridden reset vector | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de; `memmap.adoc#SMC` §Component Address Map | 6 | 0 | SF-055 |
| [ ] | `SMC-ROM-MAP` | a 128 KiB read-only region is mapped and holds the cold-reset boot image | a CPU fetch or load targeting the ROM region → the SMC address decode for the ROM aperture → the read-only ROM contents returned to the core | `rom.adoc#Boot` §ROM; `memmap.adoc#SMC` §Component Address Map | 2 | 0 | SF-036 |
| [ ] | `SMC-ROM-INTF` | the CPU TileLink memory path is converted to a non-AXI ROM macro interface that returns one 64-bit word per request | a CPU ROM access arriving over the cluster internal TileLink memory path → smc_cpu_wrapper converting it to rom_intf_req_o with clock, enable and a 14-bit 64-bit-word address, with write controls tied to read mode → the ROM macro returning one 64-bit word on rom_intf_rsp_i, and the 11-bit rom_cfg_i forwarded to prim_rom | `rom.adoc#ROM` §Architecture; `rom.adoc#ROM` §Hardware Configuration | 6 | 0 | — |
| [ ] | `SMC-ROM-ENDIAN` | the ROM endianness control reverses the eight bytes of each returned word, sourced from the eFuse shadow registers | the ROM endianness bit in the eFuse shadow-register output driving rom_flip_endianness_i → the ROM response byte-reversal stage → the 64-bit word delivered to the CPU | `rom.adoc#ROM` §Hardware Configuration | 3 | 0 | — |
| [ ] | `SMC-FAB-AXI4` | the AXI4 network carries bandwidth-sensitive traffic between the CPU cluster, SRAM, DMA, filtering and the external AXI ports | a fabric manager issuing an AXI4 transaction → the AXI4 high-performance crossbar on a 64-bit data bus → the addressed AXI4 subordinate | `fabric.adoc#Dual-Network` §Architecture | 4 | 1 | SF-003 |
| [ ] | `SMC-FAB-AXIL` | the AXI4-Lite network gives reliable deterministic access to peripherals, sensors and configuration registers | a CPU MMIO or configuration access → the AXI4-Lite low-performance crossbar → the addressed peripheral block or configuration register | `fabric.adoc#Dual-Network` §Architecture | 3 | 0 | SF-003 |
| [ ] | `SMC-FAB-WIDTHS` | the fabric carries the declared address, strobe and user widths, and prepends ID bits at each stage so responses return to the originating port | a transaction entering the fabric at a port with its declared ID width → crossbar and multiplexer stages that prepend ID bits and carry the declared address, strobe and user widths → the subordinate seeing the widened ID, and the originating port receiving the response back on its own ID | `fabric.adoc#AXI` §Common Signal Widths; `fabric.adoc#AXI` §ID Widths by Fabric Stage | 7 | 0 | — |
| [ ] | `SMC-FAB-OUTSTANDING` | each fabric stage bounds its outstanding transactions and applies backpressure rather than dropping requests | a manager issuing more requests than the stage's outstanding limit allows → the outstanding-transaction counters in the output fabric, fabric crossbars, AXI4-Lite crossbar and error slave → the backpressured manager and the eventually completed transactions | `fabric.adoc#Fabric` §Configuration Parameters | 5 | 1 | — |
| [ ] | `SMC-FAB-MGR-CPU` | the CPU cluster reaches local resources on a low-latency path and system resources on a filtered and remapped path, with separate MMIO and L2 coherent interfaces | the CPU cluster issuing a transaction on one of its four interface types → the local fabric path, the external filtered and remapped path, the MMIO path with privilege-based control, or the L2 coherent path → SRAM, PLIC, CLINT and WDT locally, or system resources beyond the output fabric | `fabric.adoc#Fabric` §Traffic Managers | 4 | 0 | SF-003 |
| [ ] | `SMC-FAB-MGR-ALIASPATH` | traffic from the DMA controller, the JTAG2AXI bridge and the log engine passes through alias remap and then filtering before reaching its destination | the DMA controller, the JTAG2AXI bridge or the log engine issuing a transaction → alias remap logic followed by the traffic filters → the destination subordinate reached after remapping and filtering | `fabric.adoc#Fabric` §Traffic Managers | 4 | 1 | — |
| [ ] | `SMC-FAB-ERRSLV` | a transaction that reaches no valid subordinate is answered by the error slave on either network | a manager issuing a transaction to an unmapped address or one no filter entry admits → the fabric decode routing the transaction to the error slave → the originating manager receiving a decode error response | `fabric.adoc#Fabric` §Traffic Subordinates; `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | 3 | 1 | SF-014, SF-030, SF-031 |
| [ ] | `SMC-FAB-ALIAS` | eight configurable regions translate local SMC addresses to global system addresses and set the cacheable attribute, defaulting to transparent at reset | a locally initiated transaction whose address falls in a configured alias region → the alias remap logic applying the region's remap offset and cacheable flag → the downstream fabric stage receiving the translated address and attribute | `fabric.adoc#Alias` §Remapping | 6 | 1 | SF-049 |
| [ ] | `SMC-FAB-PRIVREMAP` | outbound SMC transactions are translated through separate Machine-mode and Xvisor remap regions according to the originating master's privilege | an outbound transaction from a master at Machine-mode or Xvisor privilege → the privilege-controlled remap stage with its M-mode and Xvisor regions → the translated outbound address presented to the outbound filter and system NoC | `fabric.adoc#Privilege-Controlled` §Remapping | 4 | 0 | SF-043, SF-055 |
| [ ] | `SMC-FAB-APERTURE` | GLOBAL_BASE, LOCAL_BASE and REGION_SIZE describe the SMC aperture, with REGION_SIZE sizing both the local-alias window and the global aperture | firmware programming the aperture CSRs, or the reset default → the input fabric local and global split sized by REGION_SIZE → the fabric decode that routes an access to local resources or out through the output fabric | `fabric.adoc#Local` §and Remote Resource Access | 5 | 1 | SF-032 |
| [ ] | `SMC-FILT-IN` | sixteen inbound filter entries admit external traffic by address, source ID and protection attribute, blocking everything no entry admits | an external master presenting a transaction on an inbound AXI port → the sixteen-entry inbound axi_filter_wrap evaluating address, source ID and protection attributes on 56-bit addresses → the protected SMC resource on a match, or the error slave when no entry admits the transaction | `fabric.adoc#Inbound` §Filtering | 7 | 1 | SF-014, SF-015, SF-030, SF-049 |
| [ ] | `SMC-FILT-OUT` | sixteen outbound filter entries restrict SMC-initiated requests by destination address, security attribute and source ID, permitting what matches no entry | an SMC-initiated outbound transaction after any privilege remap stage → the sixteen-entry outbound filter sharing the inbound register structure → the external destination reached, or the blocked initiator | `fabric.adoc#Outbound` §Filtering | 6 | 0 | SF-014, SF-015, SF-031, SF-049 |
| [ ] | `SMC-FILT-NS` | an entry's allow_ns field is an equality test against the transaction NS bit, so one entry covers exactly one security state | a transaction carrying aw.prot[1] on a write or ar.prot[1] on a read → the allow_ns comparison inside axi_filter_wrap → the admitted transaction, the next entry on a fall-through, or the error slave returning a decode error | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | 5 | 0 | SF-014, SF-031 |
| [ ] | `SMC-FILT-AXIL-PROT` | prim_axil_prot_filter requires an exact match on all three protection bits and errors everything else when enabled | an AXI4-Lite transaction carrying a three-bit protection value → prim_axil_prot_filter comparing it against awprot_requirement or arprot_requirement under the write and read filter enables → the protected AXI-Lite peripheral on a match, or an error response otherwise | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | 5 | 0 | SF-054 |
| [ ] | `SMC-FAB-PROT-PASS` | the fabric passes AXI protection bits through unmodified so downstream slaves see the originating master's attributes | a master issuing a transaction with a given protection value → the fabric and its filters, which only admit or block and never rewrite the protection bits → the downstream slave observing the original protection attributes | `fabric.adoc#Protection` §Bit Pass-Through | 2 | 0 | — |
| [ ] | `SMC-FAB-SRCID` | each outbound transaction carries a source ID identifying the privilege level and routing path it took | an outbound SMC transaction routed direct to the NoC, through the Xvisor remap, or through the M-mode remap → the outbound path that tags the transaction with its source ID and cacheable flag → the system NoC receiving the tagged transaction | `fabric.adoc#Outbound` §Traffic Flow; `fabric.adoc#Source` §ID by Traffic Path | 5 | 0 | SF-015 |
| [ ] | `SMC-FAB-EXTPORT` | three external AXI inputs and one external AXI output connect the SMC fabric to the system NoC, JTAG debug and SEP | an external system master on sys_axi_in, jtag_axi_in or sep_axi_in, or the SMC output fabric → the input fabric for inbound ports and the output fabric for output_axi → the addressed SMC subordinate inbound, or the external system resource outbound | `fabric.adoc#Fabric` §Traffic Subordinates; hw/sys/smc/doc/port_table.adoc#sys_axi_in_req_i@f2cb50de | 5 | 0 | — |
| [ ] | `SMC-FAB-HANGDET` | three AXI hang detectors report a stalled master through one interrupt, with software identifying and clearing the condition through dedicated registers | a stalled AXI master on the sys_axi, sep_axi or data_accel path detected by its hang detector → the OR of the three detector interrupt outputs routed onto the peripheral interrupt vector → the interrupt vector bit and the HANG_DET control registers software reads to identify and clear the condition | `interrupts.adoc#Exact` §Indexed Map | 7 | 1 | SF-004 |
| [ ] | `SMC-DMA-REGIF` | the DMA frontend exposes an AXI4-Lite control interface with atomic command submission and status reading | software writing configuration and commands over AXI4-Lite → the DMA frontend register interface with a 9-bit address space and 64-bit data → the DMA frontend command processing and status registers | `dma.adoc#DMA` §Controller Integration; `dma.adoc#Control` §Interface | 3 | 0 | SF-008, SF-016 |
| [ ] | `SMC-DMA-XFER` | the DMA moves data in linear, 2D, repeated and scatter-gather patterns without CPU intervention | a transfer descriptor programmed into the shared source, destination, length, stride and repetition registers → the DMA frontend converting the descriptor into linear iDMA requests carried by the AXI4 master → the destination memory region holding the moved data | `dma.adoc#Transfer` §Capabilities; `dma.adoc#Transfer` §Parameters | 7 | 1 | SF-008 |
| [ ] | `SMC-DMA-STREAM0` | reading NEXT_ID_0 launches a transfer built from the shared descriptor registers, tagged and tracked as stream 0 | a software read of NEXT_ID_0 after programming the shared descriptor registers → the frontend stream 0 transfer-ID and status-tracking context → the launched transfer and its STATUS_0 and DONE_0 status | `dma.adoc#Stream` §Support | 4 | 1 | SF-034 |
| [ ] | `SMC-DMA-STREAM-RSVD` | streams 1 through 15 decode normally but are non-functional, returning zero and never updating | a software access to the NEXT_ID, STATUS or DONE bank of a stream index above zero → the register file, generated with all sixteen stream banks regardless of the configured stream count → the returned value of zero, with no transfer started and no bus error | `dma.adoc#Stream` §Support | 5 | 1 | SF-034 |
| [ ] | `SMC-DMA-BURST` | the backend calculates optimal burst lengths, fragments at page boundaries and handles address alignment | a linear iDMA request from the frontend → the iDMA backend burst calculation and fragmentation logic → the AXI4 master burst sequence presented to memory | `dma.adoc#Performance` §Features; `dma.adoc#AXI4` §Master Characteristics | 3 | 0 | SF-008 |
| [ ] | `SMC-DMA-OUTSTANDING` | the DMA master bounds its concurrent AXI transactions, reorders within a small buffer and couples read and write addresses | the iDMA backend issuing AXI transactions faster than they retire → the master outstanding-transaction limit, the internal re-order buffer and the read/write address coupling → the AXI4 memory path and the backpressured backend | `dma.adoc#AXI4` §Master Characteristics; `dma.adoc#DMA` §Configuration Parameters | 4 | 2 | SF-017 |
| [ ] | `SMC-DMA-FIFO` | FIFO buffering between the frontend and midend pipelines operation and absorbs back-pressure without losing commands | the DMA frontend emitting processed transfer descriptors → the frontend-to-midend FIFO of depth 4 and the midend-to-backend passthrough → the backend consuming the buffered requests | `dma.adoc#Command` §Processing; `dma.adoc#DMA` §Configuration Parameters | 3 | 1 | — |
| [ ] | `SMC-DMA-ARB` | the request manager routes requests and responses between control and master interfaces, passing through when there is one of each | one or more control interfaces presenting requests → per-master round-robin arbiters, per-master tracking FIFOs of depth 4 and a single-entry response buffer → the master interfaces executing the requests and the control interfaces receiving the routed responses | `dma.adoc#DMA` §Request Manager | 7 | 1 | — |
| [ ] | `SMC-DMA-CTRL` | configuration is protected against modification during an active transfer and a transfer can be aborted safely with state preserved | software attempting a configuration write during an active transfer, or requesting an abort → the DMA frontend configuration lock and abort control logic → the protected configuration registers and the safely stopped transfer with its preserved state | `dma.adoc#Control` §Interface; `dma.adoc#Status` §Monitoring and Control | 5 | 2 | SF-016, SF-017 |
| [ ] | `SMC-DMA-ERR` | AXI error responses encountered during a transfer are reported immediately with a classification software can act on | an AXI error response returned to the DMA master during a transfer → the DMA error status and classification logic in the frontend → the error status registers read by software | `dma.adoc#Control` §Interface; `dma.adoc#Status` §Monitoring and Control | 3 | 1 | — |
| [ ] | `SMC-DMA-IRQ` | the DMA raises a completion interrupt as a falling-edge pulse when its busy indication deasserts | the falling edge of the DMA busy output at transfer completion → the DMA completion pulse routed onto the SMC internal interrupt bits → cpu_interrupts_o bit 322 and the PLIC source derived from it | `interrupts.adoc#Exact` §Indexed Map; `dma.adoc#Response` §Path | 3 | 0 | SF-035 |
| [ ] | `SMC-DMA-CG` | a single hysteresis clock gater serves the DMA frontend, request manager and backend, enabled by frontend wakeup or backend busy | a frontend wakeup or backend busy indication, under cg_enable_i and test mode → the single prim_clk_gater_hysteresis with a 6-bit hysteresis width → the frontend, request manager and backend clocks | `dma.adoc#Clock` §Gating Configuration | 5 | 0 | — |
| [ ] | `SMC-ZERO-REGIF` | software programs a destination address and size and triggers the zeroing operation through the control and status register | software writing DEST_ADDR, SIZE and the control and status register over AXI4-Lite → the zeroer register interface in the register clock domain, with hardware parameter validation → the zeroer state machine that starts on the trigger | `zeroer.adoc#Operation` §Control; `zeroer.adoc#Memory` §Zeroer Integration | 4 | 0 | SF-009, SF-018 |
| [ ] | `SMC-ZERO-FSM` | the zeroer walks idle, address-issue and data-issue states and returns to idle with a status update and optional interrupt | the trigger written to the control and status register → the three-state machine ST_IDLE, ST_ISSUE_ADDR and ST_ISSUE_DATA → the issued AXI write addresses and zero data beats, and the final idle state with its status | `zeroer.adoc#State` §Machine; `zeroer.adoc#Operation` §Flow | 8 | 3 | SF-018, SF-019 |
| [ ] | `SMC-ZERO-AXI` | the zeroer issues optimally sized AXI4 write bursts up to the AXI maximum length with automatic alignment and page handling | the zeroer address phase calculating burst patterns for the programmed region → the AXI4 master with 56-bit address, 64-bit data, 4-bit ID and 12-bit user → the destination memory receiving the write bursts | `zeroer.adoc#AXI4` §Master Characteristics | 5 | 0 | SF-009 |
| [ ] | `SMC-ZERO-DATA` | hardware generates zero data with correct strobes, asserts last on burst completion, tracks the remaining size and detects overflow | the zeroer data phase for each issued address beat → the zero data generator, strobe calculator, last-beat logic, size tracker and overflow detector → the destination memory bytes that are cleared, and exactly those | `zeroer.adoc#Data` §Generation and Control | 6 | 0 | SF-009 |
| [ ] | `SMC-ZERO-OUTSTANDING` | the zeroer tracks in-flight writes, backpressures at its maximum and runs its data stream independently of response timing | the zeroer pipelining write addresses ahead of their responses → the 32-bit in-flight counter and built-in flow control allowing up to 32 concurrent transactions → the AXI memory path and the completion status derived from the tracked write responses | `zeroer.adoc#Outstanding` §Transaction Management; `zeroer.adoc#Memory` §Zeroer Integration | 5 | 2 | SF-019 |
| [ ] | `SMC-ZERO-ERR` | AXI error responses are detected and reported in the error status rather than silently discarded | an AXI write error response returned to the zeroer master → the zeroer write-response tracking and error status logic → the error status register read by software | `zeroer.adoc#Status` §Features; `zeroer.adoc#Outstanding` §Transaction Management | 2 | 1 | — |
| [ ] | `SMC-ZERO-IRQ` | the zeroer raises a completion interrupt as a falling-edge pulse of its busy output, under an enable | the falling edge of the zeroer busy output at operation completion → the zeroer completion pulse routed onto the SMC internal interrupt bits, under the completion interrupt enable → cpu_interrupts_o bit 323 and the PLIC source derived from it | `interrupts.adoc#Exact` §Indexed Map; `zeroer.adoc#Status` §Features | 3 | 0 | SF-019, SF-035 |
| [ ] | `SMC-ZERO-CG` | the AXI and register clocks are gated by their own enable expressions with glitch-free gating and a test override | the disable_cg control, the zeroer busy indication, register activity and the reset state → prim_clkgater instances implementing the AXI and register clock enable expressions → the AXI clock enabled only during active zeroing and the register clock independent of AXI activity | `zeroer.adoc#Clock` §Gating Control; `zeroer.adoc#Clock` §Domain Characteristics | 4 | 0 | — |
| [ ] | `SMC-INT-VECTOR` | the cpu_interrupts_o vector is assembled from four source groups occupying declared, non-overlapping ranges with reserved bits tied low | the external, peripheral, mailbox and internal interrupt source groups → the vector assembly in the SMC base block → the cpu_interrupts_o bus presented to the CPU cluster and PLIC | `interrupts.adoc#SMC` §CPU Interrupt Vector Map | 4 | 0 | SF-005, SF-048, SF-051 |
| [ ] | `SMC-INT-EXTSYNC` | the 256 external interrupt inputs are three-stage synchronized into the SMC clock domain before entering the vector | ext_interrupts_i asserted in the integration's own domain → the three-stage synchronizer into clk_smc in the SMC base block → cpu_interrupts_o bits 255 down to 0 | `interrupts.adoc#Exact` §Indexed Map; hw/sys/smc/doc/port_table.adoc#ext_interrupts_i@f2cb50de | 3 | 1 | — |
| [ ] | `SMC-INT-PERIPHMAP` | each peripheral interrupt source is driven onto its declared bit of the peripheral interrupt range 287 down to 256 | the individual peripheral interrupt sources named in the indexed map → the peripheral interrupt assembly in the SMC peripherals block, with CDC where the source is in another domain → the corresponding cpu_interrupts_o bit in the range 287 down to 256 | `interrupts.adoc#Exact` §Indexed Map | 14 | 1 | SF-004, SF-006, SF-029, SF-037 |
| [ ] | `SMC-INT-MBX-SMC` | the 32 inbound SMC mailbox channel interrupts occupy vector bits 319 down to 288 | the inbound interrupt of each of the 32 mailbox channels → the mailbox interrupt vector routed into cpu_interrupts_o by the SMC base block → cpu_interrupts_o bits 319 down to 288 | `interrupts.adoc#Exact` §Indexed Map | 3 | 1 | SF-038 |
| [ ] | `SMC-INT-INTERNAL` | the four internal interrupt sources occupy vector bits 320 through 323 | the CLA clock-stop status, the CLA debug interrupt, the DMA completion pulse and the zeroer completion pulse → the internal interrupt assignment in the SMC base block → cpu_interrupts_o bits 320 through 323 | `interrupts.adoc#Exact` §Indexed Map; `interrupts.adoc#Trace` §Notes | 4 | 0 | SF-010, SF-035 |
| [ ] | `SMC-INT-PLICID` | the PLIC exposes 332 global sources over a 4 MB aperture, with the SMC vector contributing sources at one plus the raw bit index | a raw cpu_interrupts_o bit, or a global source bound inside the CPU cluster → the PLIC source index mapping and the PLIC aperture decode → the PLIC source register state read and claimed by software | `interrupts.adoc#SMC` §CPU Interrupt Vector Map; `interrupts.adoc#RISC-V` §PLIC | 4 | 0 | SF-003, SF-005, SF-051 |
| [ ] | `SMC-PLIC-PRIO` | each interrupt source has a configurable priority that decides which pending source is delivered first | software writing a source's priority register → the PLIC hardware prioritization logic → the interrupt delivered to the enabled context | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | 2 | 0 | SF-044 |
| [ ] | `SMC-PLIC-ENABLE` | per-core and per-context enables let each core handle only the subset of interrupts it is configured for | software writing a context's enable bit for a source → the PLIC per-context enable array → the interrupt delivered, or not delivered, to that core and context | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | 3 | 0 | SF-044 |
| [ ] | `SMC-PLIC-THRESHOLD` | a per-context threshold filters out sources whose priority does not exceed it, and can be adjusted dynamically | software writing a context's threshold register → the PLIC threshold comparison against each pending source's priority → the filtered or released interrupt delivery to that context | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | 2 | 1 | — |
| [ ] | `SMC-PLIC-CLAIM` | the atomic claim and completion protocol delivers each pending interrupt exactly once and re-arms it on completion | a pending, enabled source above the context threshold → the PLIC atomic claim and completion registers for that context → the claiming core, which receives the source ID once and completes it to re-arm | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | 4 | 2 | SF-035 |
| [ ] | `SMC-PLIC-INIT` | PLIC priority and enable registers and the mie CSR have no hardware reset, so software must initialize them before enabling external interrupts | reset deassertion leaving PLIC priority and enable registers and the mie CSR at unreset values → the software initialization sequence writing known values before setting the global enable → interrupt delivery that becomes possible only after that initialization | `interrupts.adoc#RISC-V` §PLIC | 3 | 0 | SF-044 |
| [ ] | `SMC-PLIC-CONTEXT` | separate machine-mode and supervisor-mode contexts with their own enables and thresholds keep interrupt configuration isolated per core and per privilege | software configuring a specific core and privilege context → the per-context enable and threshold state in the PLIC → interrupt delivery to that core at that privilege level, unaffected by other contexts | `interrupts.adoc#Multi-Context` §Architecture and Privilege Level Integration | 5 | 0 | — |
| [ ] | `SMC-CLINT` | the CLINT provides a shared 64-bit timer with per-core compare and low-latency inter-core software interrupts, bypassing the PLIC | the shared 64-bit timer counter reaching a core's compare value, or a core writing another core's software interrupt register → the CLINT block in the reference clock domain at its 64 KiB aperture → the targeted core's timer or software interrupt input | `interrupts.adoc#RISC-V` §CLINT and Precise System Management Timing; `interrupts.adoc#Precision` §Timer Management and Inter-Core Coordination | 6 | 1 | SF-003 |
| [ ] | `SMC-PERIPH-DECODE` | every integrated peripheral decodes at its mapped offset with its declared instance count and bus protocol | a CPU or external master access to a peripheral register offset → the peripheral register crossbar decode across the AXI4-Lite and APB4 apertures → the addressed peripheral instance | `periphs.adoc#SMC` §Peripheral Summary; `memmap.adoc#SMC` §Component Address Map | 4 | 1 | SF-006, SF-029, SF-053 |
| [ ] | `SMC-PERIPH-PARAM` | the SMC instantiates several peripherals at values that differ from the IP defaults | the SMC configuration and padring packages supplying parameter values at instantiation → the parameter threading into each peripheral instance → the peripheral behaviour that the overridden value changes | `periphs.adoc#SMC` §Peripheral Parameter Overrides | 5 | 0 | SF-029 |
| [ ] | `SMC-GPIO-PAD` | the GPIO wraps exchange data with the pad ring under per-wrap direction and interface selection controls | a software write to a GPIO output register, or a pad input transition → the GPIO wrap and pad ring data and enable paths → the driven pad through core2pad_o, or the captured input read back from the GPIO registers | hw/sys/smc/doc/port_table.adoc#pad2core_i@f2cb50de; `periphs.adoc#SMC` §Peripheral Summary | 5 | 0 | — |
| [ ] | `SMC-GPIO-IRQ` | the raw GPIO interrupt vector presents one bit per wrap and software identifies the source from the GPIO status registers | a GPIO wrap raising its interrupt from a configured pad condition → the raw gpio_interrupt_o vector out of the padring, one bit per bonded and unbonded wrap → external consumers of the raw vector, and software reading the GPIO status registers to identify the source | hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de; `periphs.adoc#SMC` §Peripheral Summary | 3 | 1 | SF-004 |
| [ ] | `SMC-GPIO-STRAPS` | bonded GPIO pad values are latched at cold reset and presented read-only to software and to the boot flow | the bonded GPIO pad values present at cold reset → the adopter-owned strap capture in the external window → the read-only strap registers, and the boot consumers of individual straps | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | 5 | 1 | SF-007, SF-023, SF-054 |
| [ ] | `SMC-GPIO-EXTCTRL` | the external window exposes PLL and PVT clock observation GPIOs, per-pad control and the power-on and bias controls | software writing the external-window GPIO control registers, or the PLL and PVT observation clock inputs → the mandatory external window apertures and the padring observation mux → the observed clock driven onto a pad, and the configured pad ring per-pad controls | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region; hw/sys/smc/doc/port_table.adoc#pll_clk_obs_i@f2cb50de | 5 | 0 | SF-024, SF-054 |
| [ ] | `SMC-PVT` | the PVT wrapper aperture and the thermal sensor input give software a digital view of process, voltage and temperature monitoring | the PVT monitoring hardware and the cat_therm_i thermal sensor input → the PVT wrapper in the mandatory external window → the PVT status readable by software over AXI-Lite | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region; hw/sys/smc/doc/port_table.adoc#cat_therm_i@f2cb50de | 3 | 0 | SF-024, SF-054 |
| [ ] | `SMC-TELEM-RX` | the telemetry receivers accept ATB data with a valid and ready handshake and support a flush handshake | an ATB source presenting telemetry data, ID and valid on its receiver channel → the telemetry receiver in the telemetry clock domain, with its ready and flush handshakes → the decoded telemetry available in the telemetry receiver registers and its interrupt | hw/sys/smc/doc/port_table.adoc#telemetry_atdata_i@f2cb50de; `periphs.adoc#SMC` §Peripheral Summary | 5 | 2 | SF-001, SF-006 |
| [ ] | `SMC-OCTS` | the OCTS 64-bit timer runs in the reference clock domain, presents its count externally and operates in a primary or secondary mode | the reference clock advancing the OCTS 64-bit counter, with the chiplet-is-primary strap selecting the mode → the system timer OCTS block at its mapped aperture → timer_count_o presented to external systems and the OCTS registers read by software | `periphs.adoc#SMC` §Peripheral Summary; hw/sys/smc/doc/port_table.adoc#timer_count_o@f2cb50de (+1) | 5 | 0 | SF-023, SF-053 |
| [ ] | `SMC-UART` | four UART 16550 instances provide serial communication with FIFOs and interrupts in the peripheral clock domain | software writing the UART transmit registers, or an external serial input → the UART 16550 instance in the peripheral clock domain behind the UART wrapper aperture → the serial line driven out, the received data in the FIFO, and the raw UART interrupt output | `periphs.adoc#SMC` §Peripheral Summary; hw/sys/smc/doc/port_table.adoc#uart_interrupt_o@f2cb50de | 4 | 0 | SF-053 |
| [ ] | `SMC-LOGENG` | four log engine instances transfer log messages to the UART interface by DMA | software submitting a log message to a log engine instance → the DMA-based log engine transfer over AXI4-Lite → the UART interface that emits the message, and the log-engine interrupt combined into the UART interrupt bit | `periphs.adoc#SMC` §Peripheral Summary; `interrupts.adoc#Exact` §Indexed Map | 3 | 0 | — |
| [ ] | `SMC-I2C` | three I2C instances support controller and target modes over I2C, SMBus and PMBus in the peripheral clock domain | software driving an I2C instance, or an external bus device driving the lines → the I2C controller in the peripheral clock domain behind the I2C wrapper aperture → the addressed bus device in controller mode, or the receive FIFO and interrupt in target mode | `periphs.adoc#SMC` §Peripheral Summary; `clk_rst.adoc#The` §Peripheral Clock Domain | 6 | 1 | SF-053 |
| [ ] | `SMC-AVSBUS` | the AVSBus controller manages voltage rails and power conditions over its serial interface in the peripheral clock domain | software issuing an AVSBus command through the controller registers → the AVSBus controller in the peripheral clock domain at its mapped aperture → the voltage rail device that receives the command, and the AVSBus interrupt raised on completion | `periphs.adoc#SMC` §Peripheral Summary; `clk_rst.adoc#The` §Peripheral Clock Domain | 3 | 0 | SF-053 |
| [ ] | `SMC-MBX` | 32 bidirectional FIFO mailbox pairs carry inter-processor and inter-chiplet messages with per-channel interrupts in both directions | a local or remote agent writing a message into a mailbox channel FIFO → the 32 inbound and 32 outbound mailbox FIFOs of depth 2 at the mailbox aperture → the reading agent, the per-channel inbound interrupt into the CPU vector, and the external mailbox interrupt outputs | `periphs.adoc#SMC` §Peripheral Summary; `memmap.adoc#SMC` §Component Address Map | 6 | 2 | SF-038 |
| [ ] | `SMC-EFUSE-IF` | the eFuse controller exposes its map and interface apertures, drives the adopter eFuse SHIM, publishes shadow registers and serves a JTAG access path | software or JTAG accessing the eFuse apertures, and the eFuse controller issuing SHIM commands → the eFuse map and interface apertures, the bank control AXI-Lite path and the SHIM command request and response path → the eFuse SHIM, the shadow register output to its consumers, and the fuse sense and delayed fuse reset outputs | hw/sys/smc/doc/port_table.adoc#efuse_bank_ctrl_req_o@f2cb50de; `memmap.adoc#SMC` §Component Address Map | 6 | 0 | SF-040, SF-053 |
| [ ] | `SMC-EFUSE-LOCKS` | the LOCKS field is the sole enforcement point for read and write access control over the SMC fuse map, with violations reported by interrupt | an APB access to a fuse-map field whose lock state is set in the LOCKS shadow words → the purely combinational shadow-register access control comparing the address against the field map → the gated APB write-enable and read-data paths, and the locked-field access violation interrupt | `scan_protection.adoc#eFuse` §Shadow Register Scan Protection; `scan_protection.adoc#Downstream` §Lock Path | 6 | 1 | SF-050 |
| [ ] | `SMC-LCSTATE` | the differentially encoded lifecycle state input is presented to the SMC internal registers | the lifecycle controller driving the differentially encoded lifecycle state input → the lifecycle state path into the SMC internal registers → the SMC internal register view of the lifecycle state | hw/sys/smc/doc/port_table.adoc#lc_state_i@f2cb50de | 2 | 0 | SF-052 |
| [ ] | `SMC-NDM-RST` | the NDM reset register block lives in the miscellaneous wrapper and its request is synchronized and OR-reduced onto the interrupt vector | an NDM reset request raised through the NDM reset register block → the miscellaneous wrapper aperture and the synchronization and OR-reduction into the peripheral interrupt vector → the NDM reset request interrupt bit and the reset consumers of the request | `memmap.adoc#Spare` §SMC Register Blocks; `interrupts.adoc#Exact` §Indexed Map | 2 | 0 | — |
| [ ] | `SMC-DFD-DBGBUS` | a selection fabric routes chosen internal signals onto a fixed-width debug bus sampled every cycle | internal signals of interest and the external debug bus input → the selection fabric that chooses which signals are driven onto the debug bus under software control → the CLA event engine evaluating the resulting bus value each cycle | `dfd.adoc#Debug` §Bus | 3 | 0 | SF-027 |
| [ ] | `SMC-CLA-EVENT` | the event engine evaluates seven event types in parallel against the debug bus | the debug bus value presented each cycle, with the programmed masks, match values and counts → the CLA event engine evaluating signal match, edge, transition, ones count, any change, time match and counter events in parallel → the event-action pairs that fire on a satisfied event | `dfd.adoc#Core` §Logic Analyzer | 8 | 1 | SF-027 |
| [ ] | `SMC-CLA-EAP` | an event-action pair binds events to actions, is enabled only once fully programmed, and records which pair fired with a debug-bus snapshot | one or more events computed from the debug bus satisfying a programmed pair → the event-action pair binding, the global pair enable and the trigger status and snapshot registers → the triggered actions, the status flag naming the firing pair, and the latched debug-bus snapshot | `dfd.adoc#Core` §Logic Analyzer | 5 | 1 | SF-027 |
| [ ] | `SMC-CLA-ACTION` | a firing event-action pair can raise a debug interrupt, stop clocks, toggle a GPIO, drive a cross-trigger, capture trace or drive a custom output | a firing event-action pair → the CLA action outputs → the CPU interrupt input, the clock stop control, the observable GPIO pin, the cross-trigger output, the trace subsystem and the reserved custom outputs | `dfd.adoc#Actions` §and Cross-Triggering | 7 | 1 | SF-010, SF-027 |
| [ ] | `SMC-CLA-XTRIG` | cross-trigger inputs arm or fire local actions and cross-trigger outputs propagate local events outward | an event elsewhere in the system on the cross-trigger input, or a local CLA event → the cross-trigger subsystem input and output paths → the armed or fired local action, or the external debug block receiving the propagated event | `dfd.adoc#Actions` §and Cross-Triggering; hw/sys/smc/doc/port_table.adoc#xtrigger_ss_i@f2cb50de | 2 | 0 | — |
| [ ] | `SMC-CLA-CLKSTOP` | the debug control clock-stop enable gates the CLA clock stop and its halt status is reported outward | the DTP asserting the debug control clock-stop enable, and a CLA clock-stop action → the DFD clock-stop enable gating and the halt status output → the DTP and the internal interrupt bit driven by the halt status | hw/sys/smc/doc/port_table.adoc#tdr_dbg_ctrl_clock_stop_en_i@f2cb50de; hw/sys/smc/doc/dfd.adoc#Interrupts@63552821 | 3 | 0 | — |
| [ ] | `SMC-DFD-TRACE` | captured debug activity is timestamped, packetized, merged and written to memory over the fabric on a common time base | samples and events captured by the CLA trace capture action → encoding and packetization, the trace network merge, and the trace master writing over the fabric through the trace memory interface → the trace memory holding the timestamped packets for offline analysis | hw/sys/smc/doc/dfd.adoc#Trace@63552821; hw/sys/smc/doc/port_table.adoc#trace_mem_req_o@f2cb50de | 5 | 1 | — |
| [ ] | `SMC-SCAN-CLASS1` | the LOCKS shadow words are excluded from every scan chain and are never dumpable, in any lifecycle state or debug grant | DFT scan shift or a debug scandump attempting to reach the shadow array → the separately named Class 1 shadow array carrying the reserved scan-exclusion naming handle → the scan chain and scandump, which contain no LOCKS flop | `scan_protection.adoc#SMC` §eFuse Asset Classification; hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | 3 | 0 | SF-028, SF-050, SF-052 |
| [ ] | `SMC-SCAN-RANGEMAP` | the Class 1 shadow range is derived from the generated register metadata rather than hard-coded, and a malformed range is a build failure | the generated register map metadata giving the LOCKS offset and width → the Class 1 shadow range parameter derived from that metadata and elaboration-time range assertions → the Class 1 shadow array allocation and the resulting word split | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | 4 | 0 | SF-028 |
| [ ] | `SMC-SCAN-DOWNSTREAM` | no scannable flop downstream of the LOCKS shadow words re-derives the lock decision | the Class 1 shadow words holding the lock state → the purely combinational access-control comparison with no intermediate state element → the APB write-enable and read-data paths the comparison gates, and the single sequential consumer that carries only a violation event | `scan_protection.adoc#Downstream` §Lock Path | 2 | 0 | SF-050 |
| [ ] | `SMC-SCAN-NOSECRET` | the SMC fuse map holds no confidentiality or secret-bearing asset, so the secret disconnection controls are inactive | the SMC eFuse controller configuration with no Class 1a and no Class 2 content → the secure test-mode input tied inactive and the secret shadow range parameter left empty → the shadow register logic, which applies no confidentiality masking and instantiates no secret-bearing chain | `scan_protection.adoc#SMC` §eFuse Asset Classification; `scan_protection.adoc#Notes` §for DFT | 3 | 0 | SF-028 |
| [ ] | `SMC-DFT-TESTMODE` | the test enable drives clock-gater and AXI cell test inputs while the scan reset bypasses the reset synchronizers | the test controller driving the test enable and the scan reset → the DFT distribution of those controls to all modules → the clock-gater test ports, the AXI cell test inputs and the bypassed reset synchronizers | hw/sys/smc/doc/port_table.adoc#test_en_i@f2cb50de | 3 | 0 | — |
| [ ] | `SMC-MAP-DECODE` | every functional region of the SMC address space decodes to its component over its declared extent | a master issuing an access to an SMC address → the SMC address decode across the declared address space layout → the component that owns that region, or the error slave outside any region | `memmap.adoc#Address` §Space Organization; `memmap.adoc#SMC` §Component Address Map | 4 | 1 | SF-001, SF-002, SF-007, SF-043, SF-053, SF-055 |
| [ ] | `SMC-MAP-DUALBASE` | SMC resources are reachable at either the fixed local alias base or the programmable global base, with identical routing inside the aperture | a master addressing an SMC resource at its local alias address or at its global address → the fabric routing sized by the aperture CSRs → the same SMC resource reached either way | `memmap.adoc#Memory` §Map; `fabric.adoc#Local` §and Remote Resource Access | 5 | 0 | SF-032 |
| [ ] | `SMC-MAP-IFSTD` | SMC registers follow the declared bus widths, alignment rules and little-endian byte ordering | a register access issued on AXI4-Lite or APB4 → the standard AMBA interface with its declared address and data widths → the addressed register, accessed at its required alignment and byte order | `memmap.adoc#Register` §Interface Standards | 4 | 0 | — |
| [ ] | `SMC-EXTWIN-MAND` | the mandatory region of the adopter extension window exposes the pad controls, PLL, PVT and eFuse SHIM blocks every integration must implement | a master accessing an offset inside the mandatory external window region → the smc_external AXI-Lite window decode for the mandatory region → the adopter-implemented pad control, PLL, PVT or eFuse SHIM block at that offset | `memmap.adoc#AXI-Lite` §External Window; `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | 5 | 0 | SF-024, SF-054 |
| [ ] | `SMC-EXTWIN-SUPP` | the supplementary region is optional, treated identically by hardware, and the unallocated remainder of the window reaches the chip-level adopter port | a master accessing an offset in the supplementary region or in the unallocated remainder of the window → the smc_external window decode, which treats both regions identically, and the passthrough to the chip-level adopter external port → the adopter block at that offset, or the chip-level adopter external port | `memmap.adoc#AXI-Lite` §External Window; `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | 5 | 1 | SF-007, SF-054 |
| [ ] | `SMC-MAP-SPARE` | the chip config, scratch, NDM reset, misc wrapper, base config, DFX status and GPIO power-on and bias control blocks are programmer visible | a software access to one of the system or spare register blocks → the AXI4-Lite decode of the system control and fabric control apertures → the addressed register block and the configuration or status it holds | `memmap.adoc#Spare` §SMC Register Blocks | 6 | 0 | SF-001, SF-053, SF-055 |

## 3. Scenarios — what each feature must be shown to do

Grouped by feature. `Proof` is the minimum evidence class the scenario demands: `DECODE` (a static/decoded outcome), `CONNECTIVITY` (the path exists and carries), `LIVE` (the real consumer is reached and reacts).

### `SMC-CLK-SMC` — SMC clock domain distribution

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLK-SMC.S1` | the CPU cluster and its cache hierarchies advance on clk_smc_i | `LIVE` | `clk_rst.adoc#The` §SMC Clock Domain; hw/sys/smc/doc/port_table.adoc#clk_smc_i@f2cb50de | — |
| [ ] | `SMC-CLK-SMC.S2` | the AXI crossbar and interconnect move data on clk_smc_i | `LIVE` | `clk_rst.adoc#The` §SMC Clock Domain | — |
| [ ] | `SMC-CLK-SMC.S3` | the address remap engines and filtering logic are clocked in this domain | `CONNECTIVITY` | `clk_rst.adoc#The` §SMC Clock Domain | — |

### `SMC-CLK-REF` — Reference clock domain

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLK-REF.S1` | CLINT and the OCTS system timer advance on the reference clock | `LIVE` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| [ ] | `SMC-CLK-REF.S2` | the reference domain is the synchronization anchor for reset domain crossings | `CONNECTIVITY` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| [ ] | `SMC-CLK-REF.S3` | debug and JTAG operate on the reference clock independently of system operational state | `LIVE` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| [ ] | `SMC-CLK-REF.S4` | the reference clock is consumed as the PLL reference for frequency synthesis | `CONNECTIVITY` | `clk_rst.adoc#The` §Reference Clock Domain | — |

### `SMC-CLK-PERIPH` — Peripheral clock domain

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLK-PERIPH.S1` | AVSBus, I2C, UART 16550 and I3C operate on clk_periph_i | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | — |
| [ ] | `SMC-CLK-PERIPH.S2` | the domain operates at the stated 100 MHz minimum frequency | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | SF-041 |
| [ ] | `SMC-CLK-PERIPH.S3` | **[contested]** [BOUNDED-LIVENESS] the peripheral clock is scaled independently of clk_smc and traffic still completes or errors within a bound | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | SF-041 |

### `SMC-CLK-TELEM` — Telemetry clock domain

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLK-TELEM.S1` | incoming ATB telemetry data is captured on clk_telemetry_i with no dedicated SMC PLL | `LIVE` | `clk_rst.adoc#The` §Telemetry Clock Domain | — |
| [ ] | `SMC-CLK-TELEM.S2` | rst_telemetry_ni resets the telemetry receiver logic | `LIVE` | hw/sys/smc/doc/port_table.adoc#rst_telemetry_ni@f2cb50de | — |

### `SMC-PERIPH-CDC` — Peripheral register crossing into the peripheral clock

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PERIPH-CDC.S1` | the peripheral register crossbar decodes and routes at SMC clock speed, not peripheral clock speed | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | — |
| [ ] | `SMC-PERIPH-CDC.S2` | each master port targeting a peripheral-domain block delivers the access through its own AXI-Lite CDC bridge | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | SF-041 |
| [ ] | `SMC-PERIPH-CDC.S3` | **[contested]** [BOUNDED-LIVENESS] a register access in flight across the CDC bridge when the peripheral reset asserts completes or errors within a bound | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain; `clk_rst.adoc#Reset` §Synchronization Domains | — |

### `SMC-CLKGATE` — Activity-based clock gating

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLKGATE.S1` | an individually disabled module has its clock gated off | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | SF-013 |
| [ ] | `SMC-CLKGATE.S2` | per-module activity detection re-enables a gated clock | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | — |
| [ ] | `SMC-CLKGATE.S3` | the 6-bit programmable hysteresis prevents gating oscillation under varying load | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | SF-013 |
| [ ] | `SMC-CLKGATE.S4` | the configurable enable threshold delays gating after activity ceases | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | SF-013 |
| [ ] | `SMC-CLKGATE.S5` | **[contested]** [BOUNDED-LIVENESS] activity arriving while the hysteresis countdown is in progress restores the clock without a glitch and without losing the request | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | — |

### `SMC-RST-POR` — Power-on reset root

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-POR.S1` | BP_POWERGOOD is stretched into powergood_stable | `LIVE` | `clk_rst.adoc#Reset` §Architecture | SF-045 |
| [ ] | `SMC-RST-POR.S2` | the SMC functional cold reset path stays gated until powergood_stable is asserted | `LIVE` | `clk_rst.adoc#Primary` §Reset Activation Sources | — |
| [ ] | `SMC-RST-POR.S3` | powergood_stable_o presents the debounced power-good to external systems | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#powergood_stable_o@f2cb50de | — |
| [ ] | `SMC-RST-POR.S4` | **[contested]** [BOUNDED-LIVENESS] power-good deasserting mid-operation drives the SMC back into full initialization within a bound | `LIVE` | `clk_rst.adoc#SMC` §Reset Sources and Characteristics | — |

### `SMC-RST-TAP` — TAP and TDR reset from power-good

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-TAP.S1` | the effective TAP reset is the AND of TRSTN and pwr_on_rst_ni | `LIVE` | `clk_rst.adoc#Reset` §Architecture | — |
| [ ] | `SMC-RST-TAP.S2` | loss of power-good forces TAP and TDR logic into reset even with TRST released | `LIVE` | `clk_rst.adoc#Reset` §Architecture | — |
| [ ] | `SMC-RST-TAP.S3` | JTAG and TDR reset state survives rst_primary_no asserted alone | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |

### `SMC-RST-COLD` — Functional cold reset

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-COLD.S1` | asserting the cold reset input asserts rst_primary_no with asynchronous assertion and synchronous deassertion | `LIVE` | hw/sys/smc/doc/port_table.adoc#rst_cold_ni@f2cb50de; `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | SF-045 |
| [ ] | `SMC-RST-COLD.S2` | the cold reset path excludes the JTAG/TDR reset state | `LIVE` | `clk_rst.adoc#Primary` §Reset Activation Sources | — |

### `SMC-RST-PRIMARY` — Primary reset scope

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-PRIMARY.S1` | CPU cores and cache hierarchies are held while rst_primary_no is asserted | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| [ ] | `SMC-RST-PRIMARY.S2` | fabric infrastructure is held while rst_primary_no is asserted | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| [ ] | `SMC-RST-PRIMARY.S3` | peripheral controllers and interfaces are held while rst_primary_no is asserted | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| [ ] | `SMC-RST-PRIMARY.S4` | SMC control and configuration registers return to their reset values after primary reset | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| [ ] | `SMC-RST-PRIMARY.S5` | **[contested]** [BOUNDED-LIVENESS] primary reset asserted with fabric transactions in flight terminates them within a bound and leaves no bus hung | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no); `cpu.adoc#Cluster` §Boundary Isolation | — |

### `SMC-RST-COOL` — Cool reset with selective isolation

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-COOL.S1` | an externally initiated cool reset drives the primary reset path | `LIVE` | `clk_rst.adoc#Primary` §Reset Activation Sources | SF-011 |
| [ ] | `SMC-RST-COOL.S2` | rst_cool_n_from_pin_i on GPIO pin 61 initiates the cool reset sequence | `LIVE` | hw/sys/smc/doc/port_table.adoc#rst_cool_n_from_pin_i@f2cb50de | — |
| [ ] | `SMC-RST-COOL.S3` | selective subsystem isolation accompanies the cool reset | `LIVE` | `clk_rst.adoc#SMC` §Reset Sources and Characteristics; `clk_rst.adoc#Isolation` §Control Architecture | SF-011 |

### `SMC-RST-WARM` — Warm reset scope and activation

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-WARM.S1` | warm reset is cascaded from primary reset | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources | — |
| [ ] | `SMC-RST-WARM.S2` | an internal or external watchdog timeout activates warm reset | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources | SF-046 |
| [ ] | `SMC-RST-WARM.S3` | a debug-interface initiated reset activates warm reset | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources | SF-046 |
| [ ] | `SMC-RST-WARM.S4` | warm reset holds cores, private caches, PLIC, CLINT, per-core watchdogs and bus error units and nothing wider | `LIVE` | `clk_rst.adoc#Warm` §Reset (rst_warm_no) | SF-046 |
| [ ] | `SMC-RST-WARM.S5` | **[contested]** [BOUNDED-LIVENESS] warm reset asserted while primary reset is deasserting settles to a single defined post-reset state | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources; `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |

### `SMC-RST-SYNC` — Reset synchronization across clock domains

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-SYNC.S1` | reset assertion is asynchronous to the target clock | `LIVE` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |
| [ ] | `SMC-RST-SYNC.S2` | reset deassertion is synchronous to the target clock | `LIVE` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |
| [ ] | `SMC-RST-SYNC.S3` | the multi-stage synchronizer provides metastability protection on the deassertion edge | `CONNECTIVITY` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |
| [ ] | `SMC-RST-SYNC.S4` | all four named synchronized reset signals reach their declared target domains | `CONNECTIVITY` | `clk_rst.adoc#Reset` §Synchronization Domains; hw/sys/smc/doc/port_table.adoc#rst_primary_smc_clk_no@f2cb50de | SF-042 |
| [ ] | `SMC-RST-SYNC.S5` | **[contested]** [BOUNDED-LIVENESS] a reset asserted while the target clock is gated or stopped still takes effect, and deassertion is held until the clock returns | `LIVE` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity; `clk_rst.adoc#Clock` §Gating Control Parameters | — |

### `SMC-ISOLATE-CTRL` — Subsystem isolation request aggregation

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ISOLATE-CTRL.S1` | a software write to ISOLATE_REQ_REG asserts isolation for the selected subsystem | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| [ ] | `SMC-ISOLATE-CTRL.S2` | isolate_req_pin_i asserts isolation for subsystems enabled in ISOLATE_REQ_PINEN_REG | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| [ ] | `SMC-ISOLATE-CTRL.S3` | FLR detection asserts isolation for subsystems enabled in ISOLATE_REQ_SMCEN_REG | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| [ ] | `SMC-ISOLATE-CTRL.S4` | the final per-subsystem isolation state is the OR of all three sources | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| [ ] | `SMC-ISOLATE-CTRL.S5` | **[contested]** [BOUNDED-LIVENESS] FLR isolation asserting while software isolation is being cleared keeps the subsystem isolated, with a bounded settle | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |

### `SMC-FLR-SEQ` — FLR programmable reset timing sequence

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FLR-SEQ.S1` | the pre-reset delay from FLR trigger to cool reset assertion equals ISOLATE_REQ_FLR_COUNTER_VALUE | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing | SF-033 |
| [ ] | `SMC-FLR-SEQ.S2` | the cool reset hold time equals ISOLATE_REQ_FLR_RESET_COUNTER_VALUE | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing | SF-033 |
| [ ] | `SMC-FLR-SEQ.S3` | the sequence is timed in the reference clock domain independently of the SMC clock frequency | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing | SF-033 |
| [ ] | `SMC-FLR-SEQ.S4` | **[contested]** [BOUNDED-LIVENESS] a second FLR request arriving during an in-progress sequence reaches a bounded defined outcome rather than restarting indefinitely | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing; `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | — |

### `SMC-FLR-CDC` — FLR trigger clock domain crossing

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FLR-CDC.S1` | the FLR active signal is synchronized into the SMC clock domain | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | SF-025 |
| [ ] | `SMC-FLR-CDC.S2` | the FLR active signal is synchronized into the reference clock domain | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | SF-025 |
| [ ] | `SMC-FLR-CDC.S3` | rising-edge detection on the synchronized signal initiates the sequence exactly once per trigger | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | — |
| [ ] | `SMC-FLR-CDC.S4` | **[contested]** [BOUNDED-LIVENESS] operation is reliable regardless of the PCIe-to-SMC clock frequency relationship, including a trigger near the synchronizer sampling edge | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | SF-025 |

### `SMC-REPAIR-BYPASS` — Memory repair bypass control

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-REPAIR-BYPASS.S1` | FLR-triggered isolation asserts skip_mem_repair_o | `LIVE` | `clk_rst.adoc#Memory` §Test Bypass | — |
| [ ] | `SMC-REPAIR-BYPASS.S2` | pin-based isolation asserts skip_mem_repair_o | `LIVE` | `clk_rst.adoc#Memory` §Test Bypass | — |
| [ ] | `SMC-REPAIR-BYPASS.S3` | the BYPASS_SRAM_REPAIR strap on GPIO pin 13 bypasses the repair logic | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| [ ] | `SMC-REPAIR-BYPASS.S4` | a normal cold reset sequence executes repair when no bypass is asserted | `LIVE` | `cpu.adoc#Memory` §Repair | — |

### `SMC-RST-RETAIN` — Advanced reset retention and forcing features

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-RETAIN.S1` | a stable reference clock is forced during resets for timing reliability | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |
| [ ] | `SMC-RST-RETAIN.S2` | selected configuration is retained across a reset for fast recovery | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |
| [ ] | `SMC-RST-RETAIN.S3` | memory contents are kept intact across the reset events that select SRAM preservation | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |
| [ ] | `SMC-RST-RETAIN.S4` | debug and signal state is maintained through the reset | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |

### `SMC-RST-OVERRIDE` — DTP reset override through JTAG

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-RST-OVERRIDE.S1` | an asserted override enable forces the corresponding SMC reset to the supplied active-low value | `LIVE` | hw/sys/smc/doc/port_table.adoc#jtag_reset_ctrl_i@f2cb50de | SF-021 |
| [ ] | `SMC-RST-OVERRIDE.S2` | with every override enable tied to zero the functional reset behaviour is unchanged | `LIVE` | hw/sys/smc/doc/port_table.adoc#jtag_reset_ctrl_i@f2cb50de | SF-021 |

### `SMC-SSRST` — Subsystem reset control and completion

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SSRST.S1` | ss_reset_ctrl_o drives the per-subsystem reset control for all 32 subsystems | `LIVE` | hw/sys/smc/doc/port_table.adoc#ss_reset_ctrl_o@f2cb50de | SF-020 |
| [ ] | `SMC-SSRST.S2` | ss_config_o carries the per-subsystem configuration | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#ss_config_o@f2cb50de | — |
| [ ] | `SMC-SSRST.S3` | ss_reset_complete_i is consumed and its default all-ones value permits the sequence to advance | `LIVE` | hw/sys/smc/doc/port_table.adoc#ss_reset_complete_i@f2cb50de | SF-020 |
| [ ] | `SMC-SSRST.S4` | **[contested]** [BOUNDED-LIVENESS] a subsystem that never returns completion leaves the sequencer in a bounded and observable state rather than hung silently | `LIVE` | hw/sys/smc/doc/port_table.adoc#ss_reset_complete_i@f2cb50de | SF-020 |

### `SMC-SYNC-BIT` — Global synchronisation bit

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SYNC-BIT.S1` | a software write to SYNC_REG.sync is reflected on sync_irq_o | `LIVE` | hw/sys/smc/doc/port_table.adoc#sync_irq_o@f2cb50de | — |
| [ ] | `SMC-SYNC-BIT.S2` | sync_irq_o does not aggregate any interrupt source | `DECODE` | hw/sys/smc/doc/port_table.adoc#sync_irq_o@f2cb50de | SF-047 |

### `SMC-PWRSEQ-GATE` — External boot sequence gating of reset release

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PWRSEQ-GATE.S1` | reset release is withheld until ext_boot_seq_done_i asserts | `LIVE` | hw/sys/smc/doc/port_table.adoc#ext_boot_seq_done_i@f2cb50de | SF-039 |
| [ ] | `SMC-PWRSEQ-GATE.S2` | **[contested]** [BOUNDED-LIVENESS] ext_boot_seq_done_i never asserting leaves the reset held in an observable state rather than releasing on an undefined path | `LIVE` | hw/sys/smc/doc/port_table.adoc#ext_boot_seq_done_i@f2cb50de | SF-039 |

### `SMC-CPU-EXEC` — Four-core RV64GC execution

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CPU-EXEC.S1` | all four cores fetch and retire instructions after reset release | `LIVE` | `cpu.adoc#Processor` §Core Overview | SF-036 |
| [ ] | `SMC-CPU-EXEC.S2` | the I, M, A, F, D and C extensions of RV64GC execute correctly | `LIVE` | `cpu.adoc#Processor` §Core Overview | — |
| [ ] | `SMC-CPU-EXEC.S3` | machine, supervisor and user privilege levels are all reachable and enforced | `LIVE` | `cpu.adoc#Processor` §Core Overview | — |
| [ ] | `SMC-CPU-EXEC.S4` | a 56-bit physical address issued by a core reaches a system-facing destination | `LIVE` | `cpu.adoc#Processor` §Core Overview; `fabric.adoc#AXI` §Common Signal Widths | — |

### `SMC-CPU-RSTVEC` — Per-core reset and programmable reset vector

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CPU-RSTVEC.S1` | rst_core_N_ni resets core N independently of the other cores | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization | — |
| [ ] | `SMC-CPU-RSTVEC.S2` | reset_vector_N_i sets the 56-bit first fetch address of core N | `LIVE` | `cpu.adoc#Processor` §Core Overview | SF-036 |
| [ ] | `SMC-CPU-RSTVEC.S3` | the cold-reset CPU vector is 0xC004_0000 | `LIVE` | `rom.adoc#Boot` §ROM | SF-036 |
| [ ] | `SMC-CPU-RSTVEC.S4` | **[contested]** [BOUNDED-LIVENESS] one core held in reset while the others execute leaves the running cores undisturbed | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization | — |

### `SMC-CPU-L1CACHE` — Per-core L1 cache hierarchy

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CPU-L1CACHE.S1` | the L1 instruction cache is 4 KiB organized as 32 sets by 2 ways | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| [ ] | `SMC-CPU-L1CACHE.S2` | the L1 data cache is 4 KiB organized as 32 sets by 2 ways | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| [ ] | `SMC-CPU-L1CACHE.S3` | the instruction cache is write-through | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| [ ] | `SMC-CPU-L1CACHE.S4` | the data cache is write-back, so a dirty line reaches memory only on eviction | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| [ ] | `SMC-CPU-L1CACHE.S5` | cache size and associativity follow the icache and dcache tag/data configuration inputs | `CONNECTIVITY` | `cpu.adoc#Cache` §and Memory Hierarchy; hw/sys/smc/doc/port_table.adoc#l1_icache_tag_intf_req_o@f2cb50de | — |

### `SMC-CPU-ECC` — Cluster memory error protection

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CPU-ECC.S1` | an instruction cache parity error is detected | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | SF-022 |
| [ ] | `SMC-CPU-ECC.S2` | a single-bit data cache error is corrected by SECDED | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | SF-022 |
| [ ] | `SMC-CPU-ECC.S3` | a single-bit scratchpad error is corrected by SECDED | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | SF-022 |
| [ ] | `SMC-CPU-ECC.S4` | a double error is detected and reported on cluster_ded_o | `LIVE` | hw/sys/smc/doc/port_table.adoc#cluster_ded_o@f2cb50de; `cpu.adoc#Cache` §and Memory Hierarchy | SF-022 |

### `SMC-SPM` — Shared scratchpad memory

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SPM.S1` | scratchpad access latency is deterministic and independent of cache state | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| [ ] | `SMC-SPM.S2` | every scratchpad bank is reachable through its own request and response interface | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#scratch_ram_intf_req_o@f2cb50de | SF-002 |
| [ ] | `SMC-SPM.S3` | per-bank power gating is applied without corrupting the contents of active banks | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| [ ] | `SMC-SPM.S4` | the scratchpad region decodes in the SMC memory map and is readable and writable by a core | `LIVE` | `memmap.adoc#SMC` §Component Address Map | SF-002 |

### `SMC-SRAM-INIT` — Automatic SRAM initialization

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SRAM-INIT.S1` | SRAM is initialized automatically by hardware after reset | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization | — |
| [ ] | `SMC-SRAM-INIT.S2` | disable_sram_auto_init_i suppresses the automatic initialization | `LIVE` | hw/sys/smc/doc/port_table.adoc#disable_sram_auto_init_i@f2cb50de | — |
| [ ] | `SMC-SRAM-INIT.S3` | init_mem_done_o asserts exactly when memory is ready for use | `LIVE` | hw/sys/smc/doc/port_table.adoc#init_mem_done_o@f2cb50de | — |
| [ ] | `SMC-SRAM-INIT.S4` | **[contested]** [BOUNDED-LIVENESS] a CPU access attempted before init_mem_done_o reaches a bounded defined outcome rather than returning indeterminate data | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization; `cpu.adoc#Cluster` §Boundary Isolation | — |

### `SMC-MEMREPAIR` — BIRA memory repair in the boot sequence

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-MEMREPAIR.S1` | fuse_sense_done_o assertion triggers the repair operation | `LIVE` | `cpu.adoc#Memory` §Repair; hw/sys/smc/doc/port_table.adoc#fuse_sense_done_o@f2cb50de | — |
| [ ] | `SMC-MEMREPAIR.S2` | repair data is read from the 16-kilobit eFuse BIRA repair_data field and applied to the arrays | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| [ ] | `SMC-MEMREPAIR.S3` | the mem_repair_done bit reports repair completion in the DFX control status register | `LIVE` | `cpu.adoc#Memory` §Repair | SF-001 |
| [ ] | `SMC-MEMREPAIR.S4` | the mem_repair_success bit reports whether the repair succeeded | `LIVE` | `cpu.adoc#Memory` §Repair | SF-001 |
| [ ] | `SMC-MEMREPAIR.S5` | MBIST operations begin only after repair completes or is bypassed | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| [ ] | `SMC-MEMREPAIR.S6` | **[contested]** [BOUNDED-LIVENESS] the CPU cluster reset is not released until both repair and MBIST complete, so no core touches SRAM before repair | `LIVE` | `cpu.adoc#Memory` §Repair | SF-039 |

### `SMC-TL2AXI` — Cluster boundary protocol bridging

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-TL2AXI.S1` | an internal TileLink transaction appears as a well-formed AXI4 transaction on the L2 frontend | `LIVE` | `cpu.adoc#System` §Interfaces | — |
| [ ] | `SMC-TL2AXI.S2` | an internal TileLink MMIO access appears as a well-formed AXI4-Lite transaction with 56-bit addressing | `LIVE` | `cpu.adoc#System` §Interfaces | — |

### `SMC-CLUSTER-ISO` — Cluster AXI boundary isolation

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLUSTER-ISO.S1` | up to four outstanding transactions on each wrapped AXI port are drained before isolation completes | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| [ ] | `SMC-CLUSTER-ISO.S2` | **[contested]** [BOUNDED-LIVENESS] a new transaction presented to the isolated L2 frontend slave port is blocked rather than terminated | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| [ ] | `SMC-CLUSTER-ISO.S3` | **[contested]** [BOUNDED-LIVENESS] a new transaction presented to the isolated MMIO master port is terminated with an SLVERR response | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| [ ] | `SMC-CLUSTER-ISO.S4` | no X value propagates from the cluster boundary into the fabric during the isolation window | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| [ ] | `SMC-CLUSTER-ISO.S5` | the non-AXI status crossings wb_pc_valid, wb_reg_pc and the per-core wdt_reset are clamped to constants over the isolation window | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| [ ] | `SMC-CLUSTER-ISO.S6` | the boundary self-isolates on cold boot | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| [ ] | `SMC-CLUSTER-ISO.S7` | isolation releases only once SRAM initialization completes and the cores and uncore are out of reset | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |

### `SMC-ISO-DRAIN` — Cluster isolation drain handshake

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ISO-DRAIN.S1` | isolate_req_i is asserted whenever a software reset of the cluster is pending | `LIVE` | `cpu.adoc#Drain` §Handshake | — |
| [ ] | `SMC-ISO-DRAIN.S2` | drained_o asserts only once both axi_isolate instances have drained and isolated their ports | `LIVE` | `cpu.adoc#Drain` §Handshake | — |
| [ ] | `SMC-ISO-DRAIN.S3` | the control logic does not apply the reset before drained_o asserts | `LIVE` | `cpu.adoc#Drain` §Handshake | — |
| [ ] | `SMC-ISO-DRAIN.S4` | **[contested]** [BOUNDED-LIVENESS] a reset requested with transactions in flight drains and then resets within a bound, leaving no fabric response outstanding | `LIVE` | `cpu.adoc#Drain` §Handshake; `cpu.adoc#Cluster` §Boundary Isolation | — |

### `SMC-ISO-RDC` — Isolate-control reset-domain crossing

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ISO-RDC.S1` | **[contested]** [BOUNDED-LIVENESS] an asynchronous watchdog warm reset crossing into axi_isolate leaves the boundary in a defined state and is followed by a cold reset | `LIVE` | `cpu.adoc#Reset-Domain` §Crossing | — |
| [ ] | `SMC-ISO-RDC.S2` | the CPU CSR reset-control write path is synchronous and crosses no reset domain | `LIVE` | `cpu.adoc#Reset-Domain` §Crossing | — |

### `SMC-WDT` — Per-core watchdog timers

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-WDT.S1` | each of the four watchdog instances decodes at its own offset | `DECODE` | `interrupts.adoc#Interrupt` §controllers (MMIO); `memmap.adoc#SMC` §Component Address Map | SF-003 |
| [ ] | `SMC-WDT.S2` | a programmed timeout expires after the configured interval | `LIVE` | `cpu.adoc#Watchdog` §Timer System | — |
| [ ] | `SMC-WDT.S3` | the staged warning is delivered before the reset stage, allowing software intervention | `LIVE` | `cpu.adoc#Watchdog` §Timer System; `interrupts.adoc#SMC` §interrupt sources | — |
| [ ] | `SMC-WDT.S4` | wdt_first_timeout_o reaches the reset unit and wdt_second_timeout_o reaches external systems | `LIVE` | hw/sys/smc/doc/port_table.adoc#wdt_first_timeout_o@f2cb50de | — |
| [ ] | `SMC-WDT.S5` | watchdog monitoring is disabled during debugging so no false trigger occurs | `LIVE` | `cpu.adoc#Watchdog` §Timer System | — |
| [ ] | `SMC-WDT.S6` | **[contested]** [BOUNDED-LIVENESS] a second timeout arriving while the first warning is unserviced escalates to reset within a bound instead of stalling | `LIVE` | `interrupts.adoc#SMC` §interrupt sources; `cpu.adoc#Watchdog` §Timer System | — |

### `SMC-BEU` — Per-core bus error capture

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-BEU.S1` | each of the four bus error units decodes at its own offset | `DECODE` | `interrupts.adoc#Interrupt` §controllers (MMIO); `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-BEU.S2` | a decode error is captured and classified as such | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| [ ] | `SMC-BEU.S3` | a slave error is captured and classified as such | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| [ ] | `SMC-BEU.S4` | a timeout error is captured and classified as such | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| [ ] | `SMC-BEU.S5` | the error address and transaction context are preserved for fault analysis | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| [ ] | `SMC-BEU.S6` | **[contested]** [BOUNDED-LIVENESS] a second bus error arriving while the first capture is unread reaches a defined and observable outcome | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | SF-026 |

### `SMC-BEU-NMI` — Bus error NMI delivery

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-BEU-NMI.S1` | a bus error unit interrupt reaches its core without passing through the PLIC | `LIVE` | `interrupts.adoc#Bus` §Error Unit interrupts | SF-026 |
| [ ] | `SMC-BEU-NMI.S2` | delivery is immediate regardless of PLIC configuration or interrupt masking | `LIVE` | `interrupts.adoc#Bus` §Error Unit interrupts; `interrupts.adoc#SMC` §interrupt sources | SF-026 |

### `SMC-CPU-DEBUG` — Per-core debug access

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CPU-DEBUG.S1` | the debug module aperture decodes and the debugger reads and writes per-core registers | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de; `memmap.adoc#SMC` §Component Address Map | SF-055 |
| [ ] | `SMC-CPU-DEBUG.S2` | the debugger reads and writes memory through the debug path | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| [ ] | `SMC-CPU-DEBUG.S3` | a hardware breakpoint halts the targeted core | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| [ ] | `SMC-CPU-DEBUG.S4` | a software breakpoint halts the targeted core | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| [ ] | `SMC-CPU-DEBUG.S5` | debug capability continues to function across a functional reset | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| [ ] | `SMC-CPU-DEBUG.S6` | the debugger overrides the reset vector so a core restarts at a chosen address | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |

### `SMC-ROM-MAP` — Boot ROM aperture

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ROM-MAP.S1` | the 128 KiB region from 0xC004_0000 through 0xC005_FFFF decodes to the ROM | `DECODE` | `rom.adoc#Boot` §ROM | — |
| [ ] | `SMC-ROM-MAP.S2` | the region is read-only, so a write does not modify its contents | `LIVE` | `rom.adoc#Boot` §ROM | — |

### `SMC-ROM-INTF` — ROM macro interface

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ROM-INTF.S1` | a CPU ROM access is converted into a rom_intf_req_o request | `LIVE` | `rom.adoc#ROM` §Architecture | — |
| [ ] | `SMC-ROM-INTF.S2` | the request carries clock, enable and a 14-bit 64-bit-word address | `LIVE` | `rom.adoc#ROM` §Architecture | — |
| [ ] | `SMC-ROM-INTF.S3` | the write controls are tied to read mode so no write ever reaches the macro | `CONNECTIVITY` | `rom.adoc#ROM` §Architecture | — |
| [ ] | `SMC-ROM-INTF.S4` | the response returns exactly one 64-bit word per request | `LIVE` | `rom.adoc#ROM` §Architecture | — |
| [ ] | `SMC-ROM-INTF.S5` | the ROM macro boundary is not AXI-Lite and is separate from the CPU MMIO and peripheral AXI-Lite paths | `DECODE` | `rom.adoc#ROM` §Architecture | — |
| [ ] | `SMC-ROM-INTF.S6` | the 11-bit rom_cfg_i value is forwarded unchanged to the ROM macro configuration input | `CONNECTIVITY` | `rom.adoc#ROM` §Hardware Configuration | — |

### `SMC-ROM-ENDIAN` — ROM response endianness control

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ROM-ENDIAN.S1` | with the control asserted the eight bytes of each 64-bit word are returned in reversed order | `LIVE` | `rom.adoc#ROM` §Hardware Configuration | — |
| [ ] | `SMC-ROM-ENDIAN.S2` | with the control deasserted the word passes through unchanged | `LIVE` | `rom.adoc#ROM` §Hardware Configuration | — |
| [ ] | `SMC-ROM-ENDIAN.S3` | the control is sourced from the ROM endianness bit of the eFuse shadow-register output | `CONNECTIVITY` | `rom.adoc#ROM` §Hardware Configuration | — |

### `SMC-FAB-AXI4` — High-performance AXI4 network

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-AXI4.S1` | the CPU cluster reaches SRAM over the AXI4 network | `LIVE` | `fabric.adoc#Network` §Characteristics | — |
| [ ] | `SMC-FAB-AXI4.S2` | an external AXI input port reaches a local AXI4 subordinate | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | SF-003 |
| [ ] | `SMC-FAB-AXI4.S3` | the 64-bit data width is preserved end to end on the AXI4 network | `LIVE` | `fabric.adoc#Dual-Network` §Architecture; `fabric.adoc#AXI` §Common Signal Widths | — |
| [ ] | `SMC-FAB-AXI4.S4` | **[contested]** [BOUNDED-LIVENESS] two managers targeting one subordinate concurrently both complete within a bound with no response mis-delivery | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers; `fabric.adoc#Fabric` §Traffic Subordinates | — |

### `SMC-FAB-AXIL` — AXI4-Lite peripheral and configuration network

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-AXIL.S1` | a CPU MMIO access reaches a peripheral register block over AXI4-Lite | `LIVE` | `fabric.adoc#Network` §Characteristics | — |
| [ ] | `SMC-FAB-AXIL.S2` | fabric configuration registers are reachable over the AXI4-Lite network | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | — |
| [ ] | `SMC-FAB-AXIL.S3` | internal AXI4-Lite peripheral paths using a 32-bit data width carry a 4-bit strobe | `LIVE` | `fabric.adoc#AXI` §Interface Widths | — |

### `SMC-FAB-WIDTHS` — AXI signal and ID widths across fabric stages

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-WIDTHS.S1` | system-facing external ports carry a 56-bit address | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| [ ] | `SMC-FAB-WIDTHS.S2` | SMC-internal interfaces carry a 32-bit address | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| [ ] | `SMC-FAB-WIDTHS.S3` | the 8-bit write strobe selects bytes within the 64-bit data beat | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| [ ] | `SMC-FAB-WIDTHS.S4` | the 12-bit user sideband is carried on all AXI4 channels | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| [ ] | `SMC-FAB-WIDTHS.S5` | the inbound port ID widths of 6, 2 and 6 bits are accepted at the system, JTAG and SEP inputs | `LIVE` | `fabric.adoc#AXI` §ID Widths by Fabric Stage | — |
| [ ] | `SMC-FAB-WIDTHS.S6` | the ID widens through the declared stages of 4, 6 and 8 bits as crossbars prepend originating-port bits | `LIVE` | `fabric.adoc#AXI` §ID Widths by Fabric Stage | — |
| [ ] | `SMC-FAB-WIDTHS.S7` | a response returns on the ID of the port that originated the request | `LIVE` | `fabric.adoc#AXI` §ID Widths by Fabric Stage | — |

### `SMC-FAB-OUTSTANDING` — Fabric outstanding-transaction limits

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-OUTSTANDING.S1` | the output fabric allows up to MaxTrans of 32 outstanding transactions per AXI ID | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| [ ] | `SMC-FAB-OUTSTANDING.S2` | the fabric crossbars allow up to FABRIC_MAX_TRANS of 32 outstanding transactions per AXI ID | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| [ ] | `SMC-FAB-OUTSTANDING.S3` | the AXI4-Lite crossbar allows up to four outstanding writes and four outstanding reads | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| [ ] | `SMC-FAB-OUTSTANDING.S4` | the error slave allows up to ERR_SLV_MAX_TRANS of 32 outstanding transactions across all IDs | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| [ ] | `SMC-FAB-OUTSTANDING.S5` | **[contested]** [BOUNDED-LIVENESS] reaching an outstanding limit backpressures the manager and every accepted transaction still completes within a bound | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |

### `SMC-FAB-MGR-CPU` — CPU cluster manager routing paths

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-MGR-CPU.S1` | the local path reaches SRAM, PLIC, CLINT and the watchdog timers with minimal latency | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | SF-003 |
| [ ] | `SMC-FAB-MGR-CPU.S2` | the external path carries CPU traffic through filtering and remapping | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| [ ] | `SMC-FAB-MGR-CPU.S3` | the MMIO interface carries register access with privilege-based control | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| [ ] | `SMC-FAB-MGR-CPU.S4` | the L2 coherent path carries cache-coherent high-bandwidth operations | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |

### `SMC-FAB-MGR-ALIASPATH` — Alias-remapped manager path for DMA, JTAG2AXI and the log engine

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-MGR-ALIASPATH.S1` | DMA traffic is alias-remapped and filtered before reaching its destination | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers; `dma.adoc#DMA` §Controller Integration | — |
| [ ] | `SMC-FAB-MGR-ALIASPATH.S2` | JTAG2AXI bridge traffic is alias-remapped and filtered before reaching its destination | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| [ ] | `SMC-FAB-MGR-ALIASPATH.S3` | log engine traffic is alias-remapped and filtered before reaching its destination | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| [ ] | `SMC-FAB-MGR-ALIASPATH.S4` | **[contested]** [BOUNDED-LIVENESS] all three managers active concurrently on the shared remap and filter path all complete or error within a bound | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |

### `SMC-FAB-ERRSLV` — Error slave for invalid addresses

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-ERRSLV.S1` | an unmapped address on the AXI4 network returns a decode error | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | SF-031 |
| [ ] | `SMC-FAB-ERRSLV.S2` | an unmapped address on the AXI4-Lite network returns a decode error | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | — |
| [ ] | `SMC-FAB-ERRSLV.S3` | **[contested]** [BOUNDED-LIVENESS] more unmapped requests arriving than the error slave outstanding limit are backpressured and each still receives its error response | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |

### `SMC-FAB-ALIAS` — Alias address remapping

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-ALIAS.S1` | eight independently configurable regions are present and addressable | `DECODE` | `fabric.adoc#Alias` §Remapping; `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-FAB-ALIAS.S2` | an address inside a region's configured input range selects that region | `LIVE` | `fabric.adoc#Alias` §Remapping | — |
| [ ] | `SMC-FAB-ALIAS.S3` | the region's remap offset translates the outgoing address | `LIVE` | `fabric.adoc#Alias` §Remapping | — |
| [ ] | `SMC-FAB-ALIAS.S4` | the region's cacheable flag is applied to the locally initiated transaction | `LIVE` | `fabric.adoc#Alias` §Remapping; `fabric.adoc#Outbound` §Traffic Flow | — |
| [ ] | `SMC-FAB-ALIAS.S5` | at reset the remap logic is transparent and the local alias base 0xC000_0000 addresses local resources | `LIVE` | `fabric.adoc#Alias` §Remapping | — |
| [ ] | `SMC-FAB-ALIAS.S6` | **[contested]** [BOUNDED-LIVENESS] reprogramming a region while a matching transaction is in flight leaves that transaction with a single defined translation and a bounded completion | `LIVE` | `fabric.adoc#Alias` §Remapping | — |

### `SMC-FAB-PRIVREMAP` — Privilege-controlled output remapping

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-PRIVREMAP.S1` | the M-mode remap region is based at MmodeBaseAddr 0x100_0000 relative to the SMC base | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters; `memmap.adoc#SMC` §Component Address Map | SF-043, SF-055 |
| [ ] | `SMC-FAB-PRIVREMAP.S2` | the Xvisor remap region is based at XvisorBaseAddr 0x180_0000 relative to the SMC base | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters; `memmap.adoc#SMC` §Component Address Map | SF-055 |
| [ ] | `SMC-FAB-PRIVREMAP.S3` | the translation applied is selected by the originating master's privilege level | `LIVE` | `fabric.adoc#Privilege-Controlled` §Remapping | — |
| [ ] | `SMC-FAB-PRIVREMAP.S4` | with NoRemap set the remapping is disabled | `DECODE` | `fabric.adoc#Fabric` §Configuration Parameters | — |

### `SMC-FAB-APERTURE` — SMC aperture CSRs

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-APERTURE.S1` | REGION_SIZE resets to 0x0100_0000 | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access; `memmap.adoc#Memory` §Map | — |
| [ ] | `SMC-FAB-APERTURE.S2` | reprogramming REGION_SIZE resizes the local-alias window and the global aperture by the same amount | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | SF-032 |
| [ ] | `SMC-FAB-APERTURE.S3` | GLOBAL_BASE and LOCAL_BASE describe the aperture and are readable by firmware | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access; `memmap.adoc#Memory` §Map | — |
| [ ] | `SMC-FAB-APERTURE.S4` | programming REGION_SIZE to zero collapses both windows and routes SMC CPU accesses to its own resources out through the output fabric | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | SF-032 |
| [ ] | `SMC-FAB-APERTURE.S5` | **[contested]** [BOUNDED-LIVENESS] REGION_SIZE reprogrammed with a transaction in flight leaves that transaction with one defined routing and a bounded completion | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | — |

### `SMC-FILT-IN` — Inbound traffic filtering

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FILT-IN.S1` | sixteen independent inbound filter entries are present and individually configurable | `DECODE` | `fabric.adoc#Inbound` §Filtering; `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-FILT-IN.S2` | a transaction inside a configured address zone is admitted | `LIVE` | `fabric.adoc#Inbound` §Filtering | SF-014 |
| [ ] | `SMC-FILT-IN.S3` | source ID authorization admits a trusted originator and blocks an untrusted one | `LIVE` | `fabric.adoc#Inbound` §Filtering | SF-015 |
| [ ] | `SMC-FILT-IN.S4` | protection attribute filtering distinguishes secure from non-secure and privileged from user transactions | `LIVE` | `fabric.adoc#Inbound` §Filtering; `fabric.adoc#Protection` §Bit Encoding | — |
| [ ] | `SMC-FILT-IN.S5` | inbound traffic matching no entry is blocked | `LIVE` | `fabric.adoc#Traffic` §Filtering | SF-014, SF-030 |
| [ ] | `SMC-FILT-IN.S6` | the default inbound configuration blocks all external transactions until firmware programs an access policy | `LIVE` | `fabric.adoc#Inbound` §Filtering | SF-030 |
| [ ] | `SMC-FILT-IN.S7` | **[contested]** [BOUNDED-LIVENESS] reprogramming an entry while a matching inbound transaction is in flight yields one defined admit-or-block decision within a bound | `LIVE` | `fabric.adoc#Inbound` §Filtering | — |

### `SMC-FILT-OUT` — Outbound traffic filtering

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FILT-OUT.S1` | sixteen independent outbound filter entries are present, each a 32-byte control block on AXI4-Lite | `DECODE` | `fabric.adoc#Outbound` §Traffic Filter Control Registers; `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-FILT-OUT.S2` | destination address matching permits or blocks the outbound access | `LIVE` | `fabric.adoc#Outbound` §Filtering | SF-014 |
| [ ] | `SMC-FILT-OUT.S3` | the NS security attribute participates in the outbound match | `LIVE` | `fabric.adoc#Outbound` §Filtering | — |
| [ ] | `SMC-FILT-OUT.S4` | source ID participates in the outbound match | `LIVE` | `fabric.adoc#Outbound` §Filtering | SF-015 |
| [ ] | `SMC-FILT-OUT.S5` | outbound traffic matching no entry is permitted | `LIVE` | `fabric.adoc#Traffic` §Filtering | SF-014, SF-031 |
| [ ] | `SMC-FILT-OUT.S6` | outbound filtering is applied after any privilege remap stage, on the remapped address | `LIVE` | `fabric.adoc#Outbound` §Filtering | — |

### `SMC-FILT-NS` — Non-secure bit equality matching

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FILT-NS.S1` | an entry with allow_ns cleared matches only secure transactions | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | — |
| [ ] | `SMC-FILT-NS.S2` | an entry with allow_ns set matches only non-secure transactions | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | — |
| [ ] | `SMC-FILT-NS.S3` | an entry whose allow_ns does not match does not deny; the transaction falls through to the remaining entries | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | SF-014 |
| [ ] | `SMC-FILT-NS.S4` | covering both security states over one address range requires two entries | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | SF-014 |
| [ ] | `SMC-FILT-NS.S5` | a transaction no entry admits is routed to the error slave and receives a decode error response | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | SF-031 |

### `SMC-FILT-AXIL-PROT` — AXI-Lite full protection matching

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FILT-AXIL-PROT.S1` | a write whose prot equals awprot_requirement is allowed through | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| [ ] | `SMC-FILT-AXIL-PROT.S2` | a read whose prot equals arprot_requirement is allowed through | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| [ ] | `SMC-FILT-AXIL-PROT.S3` | the write and read filter enables individually gate the filtering | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| [ ] | `SMC-FILT-AXIL-PROT.S4` | a transaction whose protection value does not match receives an error response | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| [ ] | `SMC-FILT-AXIL-PROT.S5` | the filter guards the GPIO PoC and PBias control block | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite); `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |

### `SMC-FAB-PROT-PASS` — Protection bit pass-through

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-PROT-PASS.S1` | aw.prot reaches the downstream slave unmodified | `LIVE` | `fabric.adoc#Protection` §Bit Pass-Through | — |
| [ ] | `SMC-FAB-PROT-PASS.S2` | ar.prot reaches the downstream slave unmodified | `LIVE` | `fabric.adoc#Protection` §Bit Pass-Through | — |

### `SMC-FAB-SRCID` — Outbound source ID and traffic path selection

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-SRCID.S1` | direct-to-NoC traffic carries SMC_ID | `LIVE` | `fabric.adoc#Source` §ID by Traffic Path | SF-015 |
| [ ] | `SMC-FAB-SRCID.S2` | Xvisor-remapped traffic carries OTHER_ID | `LIVE` | `fabric.adoc#Source` §ID by Traffic Path | SF-015 |
| [ ] | `SMC-FAB-SRCID.S3` | M-mode-remapped traffic carries MMODE_ID | `LIVE` | `fabric.adoc#Source` §ID by Traffic Path | SF-015 |
| [ ] | `SMC-FAB-SRCID.S4` | traffic for shared resources passes through the appropriate privilege-controlled remap stage | `LIVE` | `fabric.adoc#Outbound` §Traffic Flow | — |
| [ ] | `SMC-FAB-SRCID.S5` | traffic for private memory or memory-mapped I/O bypasses the remap stages and goes directly to the system NoC | `LIVE` | `fabric.adoc#Outbound` §Traffic Flow | — |

### `SMC-FAB-EXTPORT` — External AXI ports

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-EXTPORT.S1` | sys_axi_in accepts a transaction with a 6-bit ID, 56-bit address, 64-bit data and 12-bit user | `LIVE` | hw/sys/smc/doc/port_table.adoc#sys_axi_in_req_i@f2cb50de | — |
| [ ] | `SMC-FAB-EXTPORT.S2` | jtag_axi_in accepts a transaction with a 2-bit ID | `LIVE` | hw/sys/smc/doc/port_table.adoc#jtag_axi_in_req_i@f2cb50de | — |
| [ ] | `SMC-FAB-EXTPORT.S3` | sep_axi_in accepts a transaction with a 6-bit ID | `LIVE` | hw/sys/smc/doc/port_table.adoc#sep_axi_in_req_i@f2cb50de | — |
| [ ] | `SMC-FAB-EXTPORT.S4` | output_axi presents filtered and remapped traffic with an 8-bit ID | `LIVE` | hw/sys/smc/doc/port_table.adoc#output_axi_req_o@f2cb50de | — |
| [ ] | `SMC-FAB-EXTPORT.S5` | an unused inbound port tied to zero introduces no fabric activity | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#sys_axi_in_req_i@f2cb50de | — |

### `SMC-FAB-HANGDET` — AXI hang detection and reporting

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-FAB-HANGDET.S1` | a stalled sys_axi master raises its hang detector interrupt | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-FAB-HANGDET.S2` | a stalled sep_axi master raises its hang detector interrupt | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-FAB-HANGDET.S3` | a stalled data_accel master raises its hang detector interrupt | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-FAB-HANGDET.S4` | the interrupt asserts while any of the three detectors is high | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-FAB-HANGDET.S5` | software identifies the stalled master by reading the per-path hang detector control registers | `LIVE` | `interrupts.adoc#Exact` §Indexed Map; `memmap.adoc#Base` §Config, DFX Status, and GPIO POC/PBias | — |
| [ ] | `SMC-FAB-HANGDET.S6` | the condition is cleared through the same hang detector control registers | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-FAB-HANGDET.S7` | **[contested]** [BOUNDED-LIVENESS] a second detector asserting while the first is still asserted keeps the aggregate interrupt high and both remain individually identifiable | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-DMA-REGIF` — DMA control register interface

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-REGIF.S1` | the 512-byte aperture from 0xC003_8000 through 0xC003_81FF decodes to the DMA controller | `DECODE` | `dma.adoc#DMA` §Controller Integration; `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-DMA-REGIF.S2` | AXI4-Lite reads and writes of 64-bit data within the 9-bit address space complete correctly | `LIVE` | `dma.adoc#Control` §Interface | SF-008 |
| [ ] | `SMC-DMA-REGIF.S3` | command submission and status reading are atomic | `LIVE` | `dma.adoc#Control` §Interface | — |

### `SMC-DMA-XFER` — DMA transfer types

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-XFER.S1` | a linear source-to-destination transfer moves the programmed byte count correctly | `LIVE` | `dma.adoc#Transfer` §Capabilities | SF-008 |
| [ ] | `SMC-DMA-XFER.S2` | a 2D transfer applies the programmed source stride | `LIVE` | `dma.adoc#Transfer` §Capabilities; `dma.adoc#Type` §Definitions | SF-008 |
| [ ] | `SMC-DMA-XFER.S3` | a 2D transfer applies the programmed destination stride | `LIVE` | `dma.adoc#Transfer` §Capabilities | SF-008 |
| [ ] | `SMC-DMA-XFER.S4` | the programmed repeat count is executed | `LIVE` | `dma.adoc#Transfer` §Capabilities; `dma.adoc#Type` §Definitions | — |
| [ ] | `SMC-DMA-XFER.S5` | a scatter-gather transfer moves non-contiguous regions using hardware descriptor parsing | `LIVE` | `dma.adoc#Transfer` §Capabilities; `dma.adoc#Command` §Processing | — |
| [ ] | `SMC-DMA-XFER.S6` | unaligned source and destination addresses are handled automatically | `LIVE` | `dma.adoc#Transfer` §Parameters | — |
| [ ] | `SMC-DMA-XFER.S7` | **[contested]** [BOUNDED-LIVENESS] a reset asserted mid-transfer terminates the transfer within a bound and leaves no AXI response outstanding | `LIVE` | `dma.adoc#Response` §Path; `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |

### `SMC-DMA-STREAM0` — Stream 0 transfer launch and tracking

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-STREAM0.S1` | reading NEXT_ID_0 launches a transfer from the shared source, destination, length, stride and repetition registers | `LIVE` | `dma.adoc#Stream` §Support | — |
| [ ] | `SMC-DMA-STREAM0.S2` | the launched transfer is tagged with stream index 0 and NEXT_ID_0 returns a non-zero identifier for a correctly set-up command | `LIVE` | `dma.adoc#Stream` §Support | SF-034 |
| [ ] | `SMC-DMA-STREAM0.S3` | STATUS_0 and DONE_0 track the launched transfer through to completion | `LIVE` | `dma.adoc#Stream` §Support; `dma.adoc#Status` §Monitoring and Control | — |
| [ ] | `SMC-DMA-STREAM0.S4` | **[contested]** [BOUNDED-LIVENESS] a NEXT_ID_0 read while a transfer is already in flight reaches a bounded defined outcome without corrupting the in-flight transfer | `LIVE` | `dma.adoc#Stream` §Support; `dma.adoc#Control` §Interface | — |

### `SMC-DMA-STREAM-RSVD` — Reserved DMA stream banks

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-STREAM-RSVD.S1` | reading NEXT_ID_1 through NEXT_ID_15 starts no transfer, returns zero and produces no bus error | `LIVE` | `dma.adoc#Stream` §Support | SF-034 |
| [ ] | `SMC-DMA-STREAM-RSVD.S2` | STATUS_1 through STATUS_15 are tied to zero and never update | `LIVE` | `dma.adoc#Stream` §Support | — |
| [ ] | `SMC-DMA-STREAM-RSVD.S3` | DONE_1 through DONE_15 are tied to zero and never update | `LIVE` | `dma.adoc#Stream` §Support | — |
| [ ] | `SMC-DMA-STREAM-RSVD.S4` | every stream bank decodes normally regardless of the configured stream count | `DECODE` | `dma.adoc#Stream` §Support; `dma.adoc#Detailed` §Register Map | — |
| [ ] | `SMC-DMA-STREAM-RSVD.S5` | **[contested]** [BOUNDED-LIVENESS] a reserved-bank read while stream 0 is busy completes within a bound and does not disturb the active transfer | `LIVE` | `dma.adoc#Stream` §Support | — |

### `SMC-DMA-BURST` — DMA burst optimization

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-BURST.S1` | burst lengths are calculated to move the request efficiently | `LIVE` | `dma.adoc#Performance` §Features | — |
| [ ] | `SMC-DMA-BURST.S2` | a burst that would cross a page boundary is fragmented at that boundary | `LIVE` | `dma.adoc#Performance` §Features | — |
| [ ] | `SMC-DMA-BURST.S3` | an unaligned start address is aligned before burst issue without losing or duplicating data | `LIVE` | `dma.adoc#AXI4` §Master Characteristics | — |

### `SMC-DMA-OUTSTANDING` — DMA outstanding transaction management

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-OUTSTANDING.S1` | **[contested]** up to DMA_MST_MAX_TXNS of 16 AXI transactions are concurrently outstanding per master interface | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| [ ] | `SMC-DMA-OUTSTANDING.S2` | the internal re-order buffer of depth 3 restores in-order data delivery | `LIVE` | `dma.adoc#AXI4` §Master Characteristics | — |
| [ ] | `SMC-DMA-OUTSTANDING.S3` | read and write address coupling is enabled by default | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| [ ] | `SMC-DMA-OUTSTANDING.S4` | **[contested]** [BOUNDED-LIVENESS] at the outstanding limit the backend is backpressured and every issued transaction still completes within a bound | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |

### `SMC-DMA-FIFO` — DMA frontend and midend buffering

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-FIFO.S1` | the depth-4 frontend-to-midend FIFO pipelines commands | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| [ ] | `SMC-DMA-FIFO.S2` | the midend-to-backend stage with depth zero passes requests through with no FIFO | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| [ ] | `SMC-DMA-FIFO.S3` | **[contested]** [BOUNDED-LIVENESS] back-pressure from a system overload is absorbed without losing a command | `LIVE` | `dma.adoc#Command` §Processing | — |

### `SMC-DMA-ARB` — DMA request manager routing and arbitration

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-ARB.S1` | with a single control interface and a single master interface the manager is a passthrough with no arbitration overhead | `LIVE` | `dma.adoc#DMA` §Request Manager; `dma.adoc#DMA` §Configuration Parameters | — |
| [ ] | `SMC-DMA-ARB.S2` | with multiple interfaces each master arbiter selects among pending control interface requests round robin | `LIVE` | `dma.adoc#Request` §Arbitration | — |
| [ ] | `SMC-DMA-ARB.S3` | once a master accepts a request, that request is masked from other masters until completion | `LIVE` | `dma.adoc#Request` §Arbitration | — |
| [ ] | `SMC-DMA-ARB.S4` | the depth-4 tracking FIFO records which control interface originated each accepted request | `LIVE` | `dma.adoc#Request` §Tracking | — |
| [ ] | `SMC-DMA-ARB.S5` | on completion the tracked ID is popped and the response is routed back to the originating control interface | `LIVE` | `dma.adoc#Response` §Routing | — |
| [ ] | `SMC-DMA-ARB.S6` | the single-entry response buffer decouples master and control interface timing | `LIVE` | `dma.adoc#Response` §Routing | — |
| [ ] | `SMC-DMA-ARB.S7` | **[contested]** [BOUNDED-LIVENESS] simultaneous responses to one control interface are resolved by second-level round robin and all are delivered without deadlock | `LIVE` | `dma.adoc#Response` §Routing | — |

### `SMC-DMA-CTRL` — DMA configuration lock and transfer abort

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-CTRL.S1` | the configuration lock prevents modification while a transfer is active | `LIVE` | `dma.adoc#Control` §Interface | SF-016 |
| [ ] | `SMC-DMA-CTRL.S2` | **[contested]** [BOUNDED-LIVENESS] a configuration write attempted while locked reaches a bounded defined outcome and does not corrupt the active transfer | `LIVE` | `dma.adoc#Control` §Interface | SF-016 |
| [ ] | `SMC-DMA-CTRL.S3` | an abort request stops the transfer safely | `LIVE` | `dma.adoc#Status` §Monitoring and Control | SF-017 |
| [ ] | `SMC-DMA-CTRL.S4` | transfer state is preserved across the abort for software inspection | `LIVE` | `dma.adoc#Status` §Monitoring and Control | SF-017 |
| [ ] | `SMC-DMA-CTRL.S5` | **[contested]** [BOUNDED-LIVENESS] an abort raised while AXI beats are in flight settles within a bound with no orphaned outstanding response | `LIVE` | `dma.adoc#Status` §Monitoring and Control; `dma.adoc#AXI4` §Master Characteristics | SF-017 |

### `SMC-DMA-ERR` — DMA error reporting and classification

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-ERR.S1` | an AXI error response during a transfer is recorded in the error status | `LIVE` | `dma.adoc#Status` §Monitoring and Control | — |
| [ ] | `SMC-DMA-ERR.S2` | the error classification is visible to software immediately rather than only at completion | `LIVE` | `dma.adoc#Control` §Interface | — |
| [ ] | `SMC-DMA-ERR.S3` | **[contested]** [BOUNDED-LIVENESS] a second AXI error arriving while the first is still unread reaches a defined and observable status | `LIVE` | `dma.adoc#Status` §Monitoring and Control | — |

### `SMC-DMA-IRQ` — DMA completion interrupt

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-IRQ.S1` | the completion pulse is generated on the falling edge of the DMA busy output | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| [ ] | `SMC-DMA-IRQ.S2` | the completion pulse appears at cpu_interrupts_o bit 322 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| [ ] | `SMC-DMA-IRQ.S3` | interrupt generation is configurable and maskable | `LIVE` | `dma.adoc#Status` §Monitoring and Control | — |

### `SMC-DMA-CG` — DMA clock gating

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DMA-CG.S1` | one gater gates the frontend, request manager and backend together | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| [ ] | `SMC-DMA-CG.S2` | the clock is enabled when the frontend wakes or the backend is busy | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| [ ] | `SMC-DMA-CG.S3` | the 6-bit hysteresis delays gating by the configured number of cycles | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| [ ] | `SMC-DMA-CG.S4` | cg_enable_i enables and disables clock gating | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| [ ] | `SMC-DMA-CG.S5` | clock gating is bypassed during test mode | `LIVE` | `dma.adoc#Clock` §Gating Configuration; hw/sys/smc/doc/port_table.adoc#test_en_i@f2cb50de | — |

### `SMC-ZERO-REGIF` — Zeroer register interface and trigger

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-REGIF.S1` | the 512-byte aperture from 0xC003_8200 through 0xC003_83FF decodes to the zeroer | `DECODE` | `zeroer.adoc#Memory` §Zeroer Integration; `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-ZERO-REGIF.S2` | the 64-bit DEST_ADDR and 64-bit SIZE registers are programmed and read back | `LIVE` | `zeroer.adoc#Configuration` §and Control | SF-009 |
| [ ] | `SMC-ZERO-REGIF.S3` | a write to the control and status register triggers the operation and the busy status reflects it | `LIVE` | `zeroer.adoc#Operation` §Flow | — |
| [ ] | `SMC-ZERO-REGIF.S4` | hardware validates the configuration parameters before starting | `LIVE` | `zeroer.adoc#Configuration` §and Control | SF-009, SF-018 |

### `SMC-ZERO-FSM` — Zeroer three-state operation

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-FSM.S1` | ST_IDLE waits for configuration and trigger and issues nothing | `LIVE` | `zeroer.adoc#State` §Machine States | SF-018 |
| [ ] | `SMC-ZERO-FSM.S2` | ST_ISSUE_ADDR issues the calculated AXI write addresses | `LIVE` | `zeroer.adoc#State` §Machine States; `zeroer.adoc#Operation` §Flow | — |
| [ ] | `SMC-ZERO-FSM.S3` | ST_ISSUE_DATA streams zero data matching the issued address beats | `LIVE` | `zeroer.adoc#State` §Machine States | — |
| [ ] | `SMC-ZERO-FSM.S4` | the machine returns to idle with a status update once the operation completes | `LIVE` | `zeroer.adoc#Operation` §Flow | — |
| [ ] | `SMC-ZERO-FSM.S5` | an in-progress operation can be aborted safely | `LIVE` | `zeroer.adoc#Data` §Generation and Control | SF-019 |
| [ ] | `SMC-ZERO-FSM.S6` | **[contested]** [BOUNDED-LIVENESS] a trigger written while the zeroer is busy reaches a bounded defined outcome and does not corrupt the running operation | `LIVE` | `zeroer.adoc#Operation` §Flow; `zeroer.adoc#Status` §Features | — |
| [ ] | `SMC-ZERO-FSM.S7` | **[contested]** [BOUNDED-LIVENESS] a reset asserted mid-burst returns the machine to idle within a bound with no AXI response outstanding | `LIVE` | `zeroer.adoc#State` §Machine; `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| [ ] | `SMC-ZERO-FSM.S8` | **[contested]** [BOUNDED-LIVENESS] an abort raised with write responses still outstanding settles within a bound | `LIVE` | `zeroer.adoc#Data` §Generation and Control; `zeroer.adoc#Outstanding` §Transaction Management | SF-019 |

### `SMC-ZERO-AXI` — Zeroer AXI master interface

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-AXI.S1` | the master presents a 56-bit address, 64-bit data, 4-bit ID and 12-bit user field | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | SF-009 |
| [ ] | `SMC-ZERO-AXI.S2` | bursts of up to 255 beats are issued | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |
| [ ] | `SMC-ZERO-AXI.S3` | burst sizing is calculated automatically for the programmed region | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |
| [ ] | `SMC-ZERO-AXI.S4` | an unaligned start address is handled without writing outside the programmed region | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |
| [ ] | `SMC-ZERO-AXI.S5` | a burst is fragmented automatically at a page boundary | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |

### `SMC-ZERO-DATA` — Zeroer data generation, strobes and size tracking

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-DATA.S1` | zero data is generated for every beat | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| [ ] | `SMC-ZERO-DATA.S2` | byte strobes are correct for a partial transfer | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| [ ] | `SMC-ZERO-DATA.S3` | byte strobes are correct for an unaligned start address | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| [ ] | `SMC-ZERO-DATA.S4` | the last-beat signal is asserted on the final beat of each burst | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| [ ] | `SMC-ZERO-DATA.S5` | the remaining size is tracked accurately throughout the operation | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| [ ] | `SMC-ZERO-DATA.S6` | a size overflow is detected and handled rather than silently wrapping | `LIVE` | `zeroer.adoc#Data` §Generation and Control | SF-009 |

### `SMC-ZERO-OUTSTANDING` — Zeroer outstanding transaction management

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-OUTSTANDING.S1` | in-flight writes are tracked by the counter | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |
| [ ] | `SMC-ZERO-OUTSTANDING.S2` | **[contested]** up to 32 concurrent AXI transactions are permitted | `LIVE` | `zeroer.adoc#Memory` §Zeroer Integration | — |
| [ ] | `SMC-ZERO-OUTSTANDING.S3` | **[contested]** [BOUNDED-LIVENESS] at the maximum, flow control applies back-pressure until resources free and the operation still completes within a bound | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |
| [ ] | `SMC-ZERO-OUTSTANDING.S4` | multiple write addresses are pipelined ahead of their responses | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |
| [ ] | `SMC-ZERO-OUTSTANDING.S5` | the zero data stream continues independently of response timing | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |

### `SMC-ZERO-ERR` — Zeroer AXI error handling

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-ERR.S1` | an AXI error response is detected and reported in the error status | `LIVE` | `zeroer.adoc#Status` §Features | — |
| [ ] | `SMC-ZERO-ERR.S2` | **[contested]** [BOUNDED-LIVENESS] a second error arriving while the first is still pending leaves a defined observable status and a bounded completion | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management; `zeroer.adoc#Status` §Features | — |

### `SMC-ZERO-IRQ` — Zeroer completion interrupt

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-IRQ.S1` | the pulse is generated on the falling edge of the zeroer busy output | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| [ ] | `SMC-ZERO-IRQ.S2` | the pulse appears at cpu_interrupts_o bit 323 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| [ ] | `SMC-ZERO-IRQ.S3` | the completion interrupt is optional and gated by its enable | `LIVE` | `zeroer.adoc#Configuration` §and Control | — |

### `SMC-ZERO-CG` — Zeroer dual-domain clock gating

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-ZERO-CG.S1` | the AXI clock is enabled by disable_cg, the busy indication or the reset state and gated otherwise | `LIVE` | `zeroer.adoc#Clock` §Gating Control | — |
| [ ] | `SMC-ZERO-CG.S2` | the register clock is enabled by disable_cg, register activity or the reset state and gated otherwise | `LIVE` | `zeroer.adoc#Clock` §Gating Control | — |
| [ ] | `SMC-ZERO-CG.S3` | the gating is glitch-free on both enable and disable | `LIVE` | `zeroer.adoc#Clock` §Gating Control | — |
| [ ] | `SMC-ZERO-CG.S4` | the test enable overrides the gating for manufacturing test | `LIVE` | `zeroer.adoc#Clock` §Gating Control; hw/sys/smc/doc/port_table.adoc#test_en_i@f2cb50de | — |

### `SMC-INT-VECTOR` — CPU interrupt vector assembly

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-INT-VECTOR.S1` | each of the four source groups occupies exactly its declared bit range with no overlap | `LIVE` | `interrupts.adoc#SMC` §CPU Interrupt Vector Map | — |
| [ ] | `SMC-INT-VECTOR.S2` | the vector is sized by the declared external and total interrupt counts | `DECODE` | `interrupts.adoc#SMC` §CPU Interrupt Vector Map | SF-048 |
| [ ] | `SMC-INT-VECTOR.S3` | reserved peripheral bit 287 stays zero under all peripheral activity | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-005 |
| [ ] | `SMC-INT-VECTOR.S4` | reserved tail bits 327 down to 324 stay zero | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-005 |

### `SMC-INT-EXTSYNC` — External interrupt synchronization

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-INT-EXTSYNC.S1` | each external interrupt input appears at the corresponding vector bit | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-EXTSYNC.S2` | the input is synchronized through three stages into the SMC clock domain | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-EXTSYNC.S3` | **[contested]** [BOUNDED-LIVENESS] an external pulse narrower than the synchronizer sampling window reaches a defined outcome rather than an intermediate value on the vector | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-INT-PERIPHMAP` — Peripheral interrupt bit map

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-INT-PERIPHMAP.S1` | SEP mailbox interrupt channels 0 through 7 drive bits 256 through 263 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map; hw/sys/smc/doc/port_table.adoc#sep_mailbox_interrupts_i@f2cb50de | — |
| [ ] | `SMC-INT-PERIPHMAP.S2` | telemetry receiver instances 0 through 2 drive bits 264 through 266 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-006 |
| [ ] | `SMC-INT-PERIPHMAP.S3` | the OR-reduced synchronized NDM reset request drives bit 267 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-PERIPHMAP.S4` | I3C interrupt sources map to bits 268 through 273, which read as zero while the peripheral-domain sources are tied low | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-029, SF-037 |
| [ ] | `SMC-INT-PERIPHMAP.S5` | the combined UART IRQ, UART error and log-engine interrupt for instances 0 through 3 drives bits 274 through 277 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-PERIPHMAP.S6` | the AVSBus interrupt drives bit 278 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-PERIPHMAP.S7` | I2C controller instances 0 through 2 drive bits 279 through 281 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-PERIPHMAP.S8` | the SEP watchdog reset indication drives bit 282 with inverted polarity | `LIVE` | `interrupts.adoc#Exact` §Indexed Map; hw/sys/smc/doc/port_table.adoc#sep_wdt_reset_n_i@f2cb50de | — |
| [ ] | `SMC-INT-PERIPHMAP.S9` | the eFuse locked-field access violation interrupt drives bit 283 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-PERIPHMAP.S10` | the OR of the lower half of the bonded GPIO interrupt sources drives bit 284 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-004 |
| [ ] | `SMC-INT-PERIPHMAP.S11` | the OR of the upper half of the bonded GPIO interrupt sources drives bit 285 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-004 |
| [ ] | `SMC-INT-PERIPHMAP.S12` | the OR of the three AXI hang detectors drives bit 286 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-004 |
| [ ] | `SMC-INT-PERIPHMAP.S13` | bit 287 is an unused peripheral slot tied to zero | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-PERIPHMAP.S14` | **[contested]** [BOUNDED-LIVENESS] two sources feeding the same OR-reduced bit asserting simultaneously keep the bit asserted and stay individually identifiable through the source status registers | `LIVE` | `interrupts.adoc#Exact` §Indexed Map; hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de | — |

### `SMC-INT-MBX-SMC` — SMC mailbox interrupt range

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-INT-MBX-SMC.S1` | each mailbox channel's inbound interrupt appears at its own vector bit | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-038 |
| [ ] | `SMC-INT-MBX-SMC.S2` | the 32 channels map to 32 distinct bits with no aliasing | `LIVE` | `interrupts.adoc#Exact` §Indexed Map; `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| [ ] | `SMC-INT-MBX-SMC.S3` | **[contested]** [BOUNDED-LIVENESS] several mailbox channels asserting concurrently all remain visible on their own bits | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-INT-INTERNAL` — Internal interrupt bits

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-INT-INTERNAL.S1` | the CLA clock-stop status drives bit 320 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-INTERNAL.S2` | the CLA debug interrupt drives bit 321 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-010 |
| [ ] | `SMC-INT-INTERNAL.S3` | the DMA completion pulse drives bit 322 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-INT-INTERNAL.S4` | the zeroer completion pulse drives bit 323 | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-INT-PLICID` — PLIC source identification and aperture

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-INT-PLICID.S1` | the PLIC source ID of an SMC-driven interrupt equals its raw vector bit index plus one | `LIVE` | `interrupts.adoc#SMC` §CPU Interrupt Vector Map | — |
| [ ] | `SMC-INT-PLICID.S2` | the per-core cluster-bound global sources at indices 328 through 331 do not appear on the raw vector | `LIVE` | `interrupts.adoc#SMC` §interrupt vector (`cpu_interrupts_o`) | SF-051 |
| [ ] | `SMC-INT-PLICID.S3` | the PLIC aperture from 0xC400_0000 through 0xC43F_FFFF decodes over 4 MB | `DECODE` | `interrupts.adoc#RISC-V` §PLIC; `memmap.adoc#SMC` §Component Address Map | SF-003 |
| [ ] | `SMC-INT-PLICID.S4` | 332 global sources indexed 0 through 331 are addressable in the PLIC register space | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-005, SF-051 |

### `SMC-PLIC-PRIO` — PLIC per-source priority

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PLIC-PRIO.S1` | of two pending sources the higher-priority one is delivered first | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| [ ] | `SMC-PLIC-PRIO.S2` | a source left at priority zero is never delivered | `LIVE` | `interrupts.adoc#RISC-V` §PLIC; `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |

### `SMC-PLIC-ENABLE` — PLIC per-core and per-context enables

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PLIC-ENABLE.S1` | an enabled source is delivered to the enabled context | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| [ ] | `SMC-PLIC-ENABLE.S2` | a disabled source is not delivered to that context | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| [ ] | `SMC-PLIC-ENABLE.S3` | enabling a source for one core does not deliver it to another core | `LIVE` | `interrupts.adoc#Multi-Core` §Interrupt Distribution and Load Management | — |

### `SMC-PLIC-THRESHOLD` — PLIC threshold filtering

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PLIC-THRESHOLD.S1` | a pending source whose priority does not exceed the threshold is not delivered | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| [ ] | `SMC-PLIC-THRESHOLD.S2` | **[contested]** [BOUNDED-LIVENESS] lowering the threshold while a source is pending releases that source for delivery within a bound | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |

### `SMC-PLIC-CLAIM` — PLIC atomic claim and completion

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PLIC-CLAIM.S1` | a claim returns the highest-priority pending enabled source ID | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| [ ] | `SMC-PLIC-CLAIM.S2` | completion re-arms the source so a later assertion is delivered again | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| [ ] | `SMC-PLIC-CLAIM.S3` | **[contested]** [BOUNDED-LIVENESS] two cores claiming the same source concurrently produce exactly one delivery, with the loser receiving no duplicate | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| [ ] | `SMC-PLIC-CLAIM.S4` | **[contested]** [BOUNDED-LIVENESS] a new assertion arriving inside the claim and completion window is not lost and is delivered within a bound | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |

### `SMC-PLIC-INIT` — PLIC and mie software initialization obligation

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PLIC-INIT.S1` | the PLIC priority and enable registers are writable to known values after reset | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-044 |
| [ ] | `SMC-PLIC-INIT.S2` | external interrupts are deliverable once the registers are initialized and the global enable is set | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-044 |
| [ ] | `SMC-PLIC-INIT.S3` | the mie CSR is cleared and initialized before individual enable bits and the global machine interrupt enable are set | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-044 |

### `SMC-PLIC-CONTEXT` — PLIC multi-context and per-core independence

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PLIC-CONTEXT.S1` | the machine-mode context has its own enables and threshold | `LIVE` | `interrupts.adoc#Multi-Context` §Architecture and Privilege Level Integration | — |
| [ ] | `SMC-PLIC-CONTEXT.S2` | the supervisor-mode context has its own enables and threshold | `LIVE` | `interrupts.adoc#Multi-Context` §Architecture and Privilege Level Integration | — |
| [ ] | `SMC-PLIC-CONTEXT.S3` | configuring one context does not change delivery for another privilege context | `LIVE` | `interrupts.adoc#Multi-Context` §Architecture and Privilege Level Integration | — |
| [ ] | `SMC-PLIC-CONTEXT.S4` | interrupts are delivered independently to each of the four cores | `LIVE` | `interrupts.adoc#Multi-Core` §Interrupt Distribution and Load Management | — |
| [ ] | `SMC-PLIC-CONTEXT.S5` | per-core masking lets software suppress delivery to one core while another still receives the source | `LIVE` | `interrupts.adoc#Multi-Core` §Interrupt Distribution and Load Management | — |

### `SMC-CLINT` — CLINT timer and software interrupts

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLINT.S1` | the CLINT aperture from 0xC800_0000 through 0xC800_FFFF decodes over 64 KiB | `DECODE` | `interrupts.adoc#RISC-V` §CLINT and Precise System Management Timing; `memmap.adoc#SMC` §Component Address Map | SF-003 |
| [ ] | `SMC-CLINT.S2` | the shared 64-bit timer counter advances monotonically and is readable by every core | `LIVE` | `interrupts.adoc#Precision` §Timer Management and Inter-Core Coordination | — |
| [ ] | `SMC-CLINT.S3` | a per-core compare value raises that core's timer interrupt when the counter reaches it | `LIVE` | `interrupts.adoc#Precision` §Timer Management and Inter-Core Coordination | — |
| [ ] | `SMC-CLINT.S4` | a core raises a software interrupt on another core | `LIVE` | `interrupts.adoc#RISC-V` §CLINT and Precise System Management Timing | — |
| [ ] | `SMC-CLINT.S5` | CLINT interrupts are delivered directly to the core, bypassing the PLIC | `LIVE` | `interrupts.adoc#RISC-V` §CLINT and Precise System Management Timing | — |
| [ ] | `SMC-CLINT.S6` | **[contested]** [BOUNDED-LIVENESS] a compare value written while that core's timer interrupt is already pending reaches a defined pending state within a bound | `LIVE` | `interrupts.adoc#Precision` §Timer Management and Inter-Core Coordination | — |

### `SMC-PERIPH-DECODE` — Peripheral aperture decode and instance counts

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PERIPH-DECODE.S1` | each peripheral block decodes at its mapped base offset | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-053 |
| [ ] | `SMC-PERIPH-DECODE.S2` | the declared instance count of each multi-instance peripheral is reachable at its instance stride | `DECODE` | `periphs.adoc#SMC` §Peripheral Summary; `memmap.adoc#SMC` §Component Address Map | SF-006, SF-029, SF-053 |
| [ ] | `SMC-PERIPH-DECODE.S3` | each peripheral responds on the bus protocol its summary entry declares | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary; `memmap.adoc#Register` §Interface Standards | — |
| [ ] | `SMC-PERIPH-DECODE.S4` | **[contested]** [BOUNDED-LIVENESS] an access to an instance index beyond the populated count terminates with an error rather than hanging | `LIVE` | `memmap.adoc#SMC` §Component Address Map; `fabric.adoc#Fabric` §Traffic Subordinates | SF-053 |

### `SMC-PERIPH-PARAM` — SMC peripheral parameter overrides

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PERIPH-PARAM.S1` | 32 mailboxes are instantiated with a FIFO depth of 2 | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| [ ] | `SMC-PERIPH-PARAM.S2` | the I2C target receive FIFO depth is 64 | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| [ ] | `SMC-PERIPH-PARAM.S3` | six I3C controller instances are configured | `DECODE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | SF-029 |
| [ ] | `SMC-PERIPH-PARAM.S4` | the GPIO maximum outstanding transaction parameter is 2 | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| [ ] | `SMC-PERIPH-PARAM.S5` | the GPIO default direction map sets 62 of 65 instances to input and the remaining 3 to output | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |

### `SMC-GPIO-PAD` — GPIO pad data path

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-GPIO-PAD.S1` | a pad input transition is captured and readable through the GPIO registers | `LIVE` | hw/sys/smc/doc/port_table.adoc#pad2core_i@f2cb50de | — |
| [ ] | `SMC-GPIO-PAD.S2` | a software write to a GPIO output register drives the pad | `LIVE` | hw/sys/smc/doc/port_table.adoc#core2pad_o@f2cb50de | — |
| [ ] | `SMC-GPIO-PAD.S3` | the pad-to-core and core-to-pad enables set the direction of each wrap | `LIVE` | hw/sys/smc/doc/port_table.adoc#pad2core_en_o@f2cb50de | — |
| [ ] | `SMC-GPIO-PAD.S4` | lsio_interface_select_o selects the interface for each GPIO wrap | `LIVE` | hw/sys/smc/doc/port_table.adoc#lsio_interface_select_o@f2cb50de | — |
| [ ] | `SMC-GPIO-PAD.S5` | dual-mode operation is exercised on the same wrap in both directions | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |

### `SMC-GPIO-IRQ` — GPIO interrupt reporting

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-GPIO-IRQ.S1` | each GPIO wrap drives its own bit of the raw interrupt vector | `LIVE` | hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de | — |
| [ ] | `SMC-GPIO-IRQ.S2` | software identifies the interrupting wrap by reading the GPIO status registers | `LIVE` | hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de | — |
| [ ] | `SMC-GPIO-IRQ.S3` | **[contested]** [BOUNDED-LIVENESS] two wraps in the same OR-reduced half asserting together keep the aggregate bit high and both remain identifiable | `LIVE` | hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de; `interrupts.adoc#Exact` §Indexed Map | SF-004 |

### `SMC-GPIO-STRAPS` — Cold-reset GPIO strap capture

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-GPIO-STRAPS.S1` | the bonded pad values are latched at cold reset | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | — |
| [ ] | `SMC-GPIO-STRAPS.S2` | the captured straps are readable at the low and high strap registers and are read-only to software | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | SF-007, SF-054 |
| [ ] | `SMC-GPIO-STRAPS.S3` | the BYPASS_SRAM_REPAIR strap on GPIO pin 13 is captured and reaches the repair bypass control | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| [ ] | `SMC-GPIO-STRAPS.S4` | the chiplet-is-primary strap on strap 25 is captured and reaches the system timer | `LIVE` | hw/sys/smc/doc/port_table.adoc#chiplet_is_primary_i@f2cb50de | — |
| [ ] | `SMC-GPIO-STRAPS.S5` | **[contested]** [BOUNDED-LIVENESS] a pad value changing after the capture window leaves the captured strap value unchanged | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | — |

### `SMC-GPIO-EXTCTRL` — GPIO clock observation and pad control apertures

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-GPIO-EXTCTRL.S1` | the PLL clock observation input is muxed onto the padring under its enable | `LIVE` | hw/sys/smc/doc/port_table.adoc#pll_clk_obs_i@f2cb50de | — |
| [ ] | `SMC-GPIO-EXTCTRL.S2` | the PVT process monitor clock observation input is muxed onto the padring under its enable | `LIVE` | hw/sys/smc/doc/port_table.adoc#pvt_process_clk_obs_i@f2cb50de | — |
| [ ] | `SMC-GPIO-EXTCTRL.S3` | the clock observation interface and control apertures decode at their mapped offsets | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| [ ] | `SMC-GPIO-EXTCTRL.S4` | the power-on and pad bias control block and the reference clock GPIO control block decode at their mapped offsets | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| [ ] | `SMC-GPIO-EXTCTRL.S5` | all 65 per-pad control register blocks decode at their instance stride | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |

### `SMC-PVT` — PVT digital control and status interface

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-PVT.S1` | the PVT wrapper aperture decodes at its mapped offset | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| [ ] | `SMC-PVT.S2` | cat_therm_i reaches the PVT wrapper | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#cat_therm_i@f2cb50de | SF-024 |
| [ ] | `SMC-PVT.S3` | PVT status is readable through the digital interface | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-024 |

### `SMC-TELEM-RX` — Telemetry receiver ATB ingress

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-TELEM-RX.S1` | an ATB transfer with valid high and ready high is accepted | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_atvalid_i@f2cb50de | — |
| [ ] | `SMC-TELEM-RX.S2` | the ATB data and ID are decoded per receiver instance | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_atid_i@f2cb50de | SF-006 |
| [ ] | `SMC-TELEM-RX.S3` | the flush handshake completes with the flush valid output and the flush ready input | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_afvalid_o@f2cb50de | — |
| [ ] | `SMC-TELEM-RX.S4` | **[contested]** [BOUNDED-LIVENESS] valid held with ready low backpressures the source and no telemetry data is lost once ready returns | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_atready_o@f2cb50de | — |
| [ ] | `SMC-TELEM-RX.S5` | **[contested]** [BOUNDED-LIVENESS] a flush requested while data transfers are active reaches a bounded completion without dropping accepted data | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_afvalid_o@f2cb50de | — |

### `SMC-OCTS` — System timer OCTS

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-OCTS.S1` | the 64-bit count advances on the reference clock | `LIVE` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| [ ] | `SMC-OCTS.S2` | timer_count_o presents the full 64-bit count to external systems | `LIVE` | hw/sys/smc/doc/port_table.adoc#timer_count_o@f2cb50de | SF-023 |
| [ ] | `SMC-OCTS.S3` | an asserted chiplet-is-primary input selects PRIMARY mode | `LIVE` | hw/sys/smc/doc/port_table.adoc#chiplet_is_primary_i@f2cb50de; `periphs.adoc#SMC` §Peripheral Summary | SF-023 |
| [ ] | `SMC-OCTS.S4` | a deasserted chiplet-is-primary input selects SECONDARY mode | `LIVE` | hw/sys/smc/doc/port_table.adoc#chiplet_is_primary_i@f2cb50de; `periphs.adoc#SMC` §Peripheral Summary | SF-023 |
| [ ] | `SMC-OCTS.S5` | the OCTS aperture decodes at its mapped offset over APB4 and AXI4-Lite | `DECODE` | `memmap.adoc#SMC` §Component Address Map; `periphs.adoc#SMC` §Peripheral Summary | SF-053 |

### `SMC-UART` — UART 16550 integration

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-UART.S1` | the four UART instances are reachable behind the UART wrapper aperture | `DECODE` | `memmap.adoc#SMC` §Component Address Map; `periphs.adoc#SMC` §Peripheral Summary | SF-053 |
| [ ] | `SMC-UART.S2` | a character written to a UART is transmitted on its serial output | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-UART.S3` | FIFO operation buffers transmit and receive data | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-UART.S4` | uart_interrupt_o presents one raw interrupt bit per instance in the peripheral clock domain | `LIVE` | hw/sys/smc/doc/port_table.adoc#uart_interrupt_o@f2cb50de | — |

### `SMC-LOGENG` — Log engine

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-LOGENG.S1` | four log engine instances are present and individually addressable | `DECODE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-LOGENG.S2` | a submitted log message is transferred to the UART without CPU copying | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-LOGENG.S3` | the log engine interrupt contributes to the combined UART interrupt bit for its instance | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-I2C` — I2C controller integration

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-I2C.S1` | the three I2C instances are reachable behind the I2C wrapper aperture | `DECODE` | `memmap.adoc#SMC` §Component Address Map; `periphs.adoc#SMC` §Peripheral Summary | SF-053 |
| [ ] | `SMC-I2C.S2` | a controller-mode transfer reads and writes an external target device | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-I2C.S3` | a target-mode transfer accepts data from an external controller | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-I2C.S4` | SMBus protocol operation is supported | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-I2C.S5` | PMBus protocol operation is supported | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-I2C.S6` | **[contested]** [BOUNDED-LIVENESS] a target receive FIFO filled to its 64-entry depth backpressures the bus without silently dropping bytes | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |

### `SMC-AVSBUS` — AVSBus controller integration

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-AVSBUS.S1` | the AVSBus aperture decodes at its mapped offset | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-053 |
| [ ] | `SMC-AVSBUS.S2` | a voltage-rail command is transmitted and its response is captured | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-AVSBUS.S3` | the AVSBus interrupt is raised and reaches the peripheral interrupt vector | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-MBX` — Mailbox communication channels

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-MBX.S1` | the 32 inbound and 32 outbound mailboxes decode across the mailbox aperture | `DECODE` | `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-MBX.S2` | a message written into a channel is read back in order through its FIFO | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| [ ] | `SMC-MBX.S3` | the per-channel inbound interrupt is raised when a message arrives | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-MBX.S4` | the external mailbox interrupt outputs signal the 32 channels to external targets | `LIVE` | hw/sys/smc/doc/port_table.adoc#ext_mailbox_interrupts_o@f2cb50de | SF-038 |
| [ ] | `SMC-MBX.S5` | **[contested]** [BOUNDED-LIVENESS] a write to a channel whose depth-2 FIFO is already full reaches a bounded defined outcome without silently discarding a message | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| [ ] | `SMC-MBX.S6` | **[contested]** [BOUNDED-LIVENESS] concurrent inbound and outbound activity on the same mailbox pair both complete within a bound and do not corrupt each other | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |

### `SMC-EFUSE-IF` — eFuse controller interfaces

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-EFUSE-IF.S1` | the eFuse map and eFuse interface apertures decode at their mapped offsets | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-053 |
| [ ] | `SMC-EFUSE-IF.S2` | the bank control AXI-Lite request reaches the eFuse SHIM and its response returns | `LIVE` | hw/sys/smc/doc/port_table.adoc#efuse_bank_ctrl_req_o@f2cb50de | — |
| [ ] | `SMC-EFUSE-IF.S3` | a fuse command request is issued to the SHIM and its response is consumed | `LIVE` | hw/sys/smc/doc/port_table.adoc#efuse_shim_command_req_o@f2cb50de | — |
| [ ] | `SMC-EFUSE-IF.S4` | the shadow register output presents the sensed fuse map to its consumers | `LIVE` | hw/sys/smc/doc/port_table.adoc#shadow_regs_o@f2cb50de | — |
| [ ] | `SMC-EFUSE-IF.S5` | the OTP JTAG AXI-Lite path reaches the eFuse controller and returns a response | `LIVE` | hw/sys/smc/doc/port_table.adoc#axil_smc_otp_jtag_req_i@f2cb50de | — |
| [ ] | `SMC-EFUSE-IF.S6` | fuse sense completion and the delayed fuse reset are presented on their outputs | `LIVE` | hw/sys/smc/doc/port_table.adoc#fuse_sense_done_o@f2cb50de | SF-040 |

### `SMC-EFUSE-LOCKS` — eFuse lock enforcement

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-EFUSE-LOCKS.S1` | LOCKS is the only enforcement point for read and write access control over the entire fuse map | `LIVE` | `scan_protection.adoc#eFuse` §Shadow Register Scan Protection | SF-050 |
| [ ] | `SMC-EFUSE-LOCKS.S2` | a write to a write-locked field does not change the field | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | SF-050 |
| [ ] | `SMC-EFUSE-LOCKS.S3` | a read of a read-locked field does not return the field contents | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | SF-050 |
| [ ] | `SMC-EFUSE-LOCKS.S4` | the lock decision is purely combinational with no intermediate state element between the shadow words and the gated paths | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | — |
| [ ] | `SMC-EFUSE-LOCKS.S5` | an attempted locked-field access raises the locked-field access violation interrupt | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path; `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-EFUSE-LOCKS.S6` | **[contested]** [BOUNDED-LIVENESS] a locked-field access concurrent with a permitted access leaves the permitted access unaffected and both terminate within a bound | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | — |

### `SMC-LCSTATE` — Lifecycle state input

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-LCSTATE.S1` | the 8-bit differentially encoded lifecycle state reaches the SMC internal registers | `LIVE` | hw/sys/smc/doc/port_table.adoc#lc_state_i@f2cb50de | SF-052 |
| [ ] | `SMC-LCSTATE.S2` | the unused tie value encoding TEST_DEV is accepted | `DECODE` | hw/sys/smc/doc/port_table.adoc#lc_state_i@f2cb50de | SF-052 |

### `SMC-NDM-RST` — NDM reset control block

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-NDM-RST.S1` | the NDM reset register block decodes within the miscellaneous wrapper aperture | `DECODE` | `memmap.adoc#Spare` §SMC Register Blocks; `memmap.adoc#SMC` §Component Address Map | — |
| [ ] | `SMC-NDM-RST.S2` | an NDM reset request is synchronized into the SMC clock domain and OR-reduced onto its interrupt bit | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-DFD-DBGBUS` — Programmable debug bus

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DFD-DBGBUS.S1` | the debug bus is sampled every cycle | `LIVE` | `dfd.adoc#Debug` §Bus | SF-027 |
| [ ] | `SMC-DFD-DBGBUS.S2` | software selects a different observed signal set without an RTL change and the bus value follows | `LIVE` | `dfd.adoc#Debug` §Bus | — |
| [ ] | `SMC-DFD-DBGBUS.S3` | the 512-bit external debug bus input reaches the debug bus aggregator on its 16-bit aligned lanes | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#ext_debug_bus_i@f2cb50de | — |

### `SMC-CLA-EVENT` — CLA event engine

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLA-EVENT.S1` | a signal-match event fires when the masked debug bus equals the programmed value | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | SF-027 |
| [ ] | `SMC-CLA-EVENT.S2` | an edge event fires on a rising or falling edge of the selected debug-bus signals | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EVENT.S3` | a transition event fires when a masked subset moves from the programmed value A to the programmed value B | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EVENT.S4` | a ones-count event fires when the population count of a masked subset equals the programmed value | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EVENT.S5` | an any-change event fires when any signal within a masked subset changes | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EVENT.S6` | a time-match event fires when the internal time counter reaches the programmed value | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EVENT.S7` | a counter event counts cycles following an event match and fires when the programmed count is reached | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | SF-027 |
| [ ] | `SMC-CLA-EVENT.S8` | **[contested]** [BOUNDED-LIVENESS] two event types satisfied in the same cycle both register without one masking the other | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |

### `SMC-CLA-EAP` — CLA event-action pairing and trigger status

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLA-EAP.S1` | a pair binds one or more events to one or more actions and fires those actions when the events occur | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | SF-027 |
| [ ] | `SMC-CLA-EAP.S2` | pairs are enabled together once programming is complete | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EAP.S3` | a partially programmed pairing never triggers | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EAP.S4` | the status flag records which pair triggered and the snapshot register latches the debug-bus value at the trigger moment | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| [ ] | `SMC-CLA-EAP.S5` | **[contested]** [BOUNDED-LIVENESS] two pairs firing in the same cycle both set their status flags and the snapshot holds a single defined debug-bus value | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |

### `SMC-CLA-ACTION` — CLA actions

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLA-ACTION.S1` | the debug interrupt action raises an interrupt to the CPU | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering; hw/sys/smc/doc/dfd.adoc#Interrupts@63552821 | SF-010 |
| [ ] | `SMC-CLA-ACTION.S2` | the clock stop action halts clocks to freeze the design for inspection | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| [ ] | `SMC-CLA-ACTION.S3` | the GPIO toggle action drives the externally observable enable output | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering; hw/sys/smc/doc/port_table.adoc#cla_gpio_enable_o@f2cb50de | — |
| [ ] | `SMC-CLA-ACTION.S4` | the cross-trigger out action signals other debug blocks that a local event occurred | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| [ ] | `SMC-CLA-ACTION.S5` | the trace capture action hands the event to the trace subsystem | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| [ ] | `SMC-CLA-ACTION.S6` | the reserved custom action outputs are driven for design-specific use | `CONNECTIVITY` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| [ ] | `SMC-CLA-ACTION.S7` | **[contested]** [BOUNDED-LIVENESS] a clock stop asserted while a trace write is in flight over the fabric leaves the trace write in a bounded defined state | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering; hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |

### `SMC-CLA-XTRIG` — CLA cross-triggering

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLA-XTRIG.S1` | a cross-trigger input arms or fires a local action | `LIVE` | hw/sys/smc/doc/port_table.adoc#xtrigger_ss_i@f2cb50de; `dfd.adoc#Actions` §and Cross-Triggering | — |
| [ ] | `SMC-CLA-XTRIG.S2` | a local event propagates outward on the cross-trigger output | `LIVE` | hw/sys/smc/doc/port_table.adoc#xtrigger_ss_o@f2cb50de | — |

### `SMC-CLA-CLKSTOP` — CLA clock-stop enable and status

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-CLA-CLKSTOP.S1` | with the enable asserted a CLA clock stop takes effect | `LIVE` | hw/sys/smc/doc/port_table.adoc#tdr_dbg_ctrl_clock_stop_en_i@f2cb50de | — |
| [ ] | `SMC-CLA-CLKSTOP.S2` | the halt status output reports that the CLA has stopped clocks | `LIVE` | hw/sys/smc/doc/port_table.adoc#tdr_dbg_ctrl_clocks_stopped_by_cla_o@f2cb50de | — |
| [ ] | `SMC-CLA-CLKSTOP.S3` | with the enable deasserted the CLA does not stop clocks | `LIVE` | hw/sys/smc/doc/port_table.adoc#tdr_dbg_ctrl_clock_stop_en_i@f2cb50de | — |

### `SMC-DFD-TRACE` — Trace capture and streaming

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DFD-TRACE.S1` | samples and events are encoded and packetized | `LIVE` | hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |
| [ ] | `SMC-DFD-TRACE.S2` | packets from multiple sources are merged through the trace network | `LIVE` | hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |
| [ ] | `SMC-DFD-TRACE.S3` | the trace master writes packets to memory over the trace memory interface | `LIVE` | hw/sys/smc/doc/port_table.adoc#trace_mem_req_o@f2cb50de | — |
| [ ] | `SMC-DFD-TRACE.S4` | a global timestamp with a synchronization mechanism places trace from different sources on a common time base | `LIVE` | hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |
| [ ] | `SMC-DFD-TRACE.S5` | **[contested]** [BOUNDED-LIVENESS] trace memory backpressure stalls the trace master within a bound without corrupting a packet | `LIVE` | hw/sys/smc/doc/port_table.adoc#trace_mem_resp_i@f2cb50de; hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |

### `SMC-SCAN-CLASS1` — LOCKS shadow scan exclusion

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SCAN-CLASS1.S1` | the LOCKS shadow words appear on no scan chain | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | — |
| [ ] | `SMC-SCAN-CLASS1.S2` | the LOCKS shadow words are not dumpable in any lifecycle state | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | SF-028, SF-052 |
| [ ] | `SMC-SCAN-CLASS1.S3` | the LOCKS shadow words are not dumpable under any debug grant | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | SF-028 |

### `SMC-SCAN-RANGEMAP` — Class 1 shadow range derivation

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SCAN-RANGEMAP.S1` | the Class 1 range is derived from the generated register map metadata, not from hard-coded word indices | `DECODE` | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | — |
| [ ] | `SMC-SCAN-RANGEMAP.S2` | LOCKS at fuse-map offset zero and 64 bits wide resolves to shadow words 0 and 1 | `DECODE` | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | — |
| [ ] | `SMC-SCAN-RANGEMAP.S3` | the 768-word fuse map splits into 2 Class 1 words and 766 Class 3 words | `DECODE` | `scan_protection.adoc#SMC` §shadow word allocation | — |
| [ ] | `SMC-SCAN-RANGEMAP.S4` | an ill-formed, overlapping or out-of-array range map is rejected at elaboration rather than silently losing protection | `DECODE` | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | — |

### `SMC-SCAN-DOWNSTREAM` — Downstream lock path has no scannable state

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SCAN-DOWNSTREAM.S1` | there is no state element between the Class 1 shadow words and the gated APB paths | `CONNECTIVITY` | `scan_protection.adoc#Downstream` §Lock Path | — |
| [ ] | `SMC-SCAN-DOWNSTREAM.S2` | the only sequential consumer carries an access-violation event and does not reveal or alter the lock state | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | — |

### `SMC-SCAN-NOSECRET` — Absence of SMC confidentiality and secret-bearing assets

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-SCAN-NOSECRET.S1` | the secure test-mode input is tied inactive so no secret disconnection occurs | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | — |
| [ ] | `SMC-SCAN-NOSECRET.S2` | the secret shadow range parameter is empty so no word is masked for confidentiality | `DECODE` | `scan_protection.adoc#SMC` §eFuse Asset Classification | SF-028 |
| [ ] | `SMC-SCAN-NOSECRET.S3` | the lifecycle state change completion handles are driven constant in the SMC instance and hold no SMC state | `CONNECTIVITY` | `scan_protection.adoc#Notes` §for DFT | — |

### `SMC-DFT-TESTMODE` — DFT test mode and scan reset

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-DFT-TESTMODE.S1` | the test enable reaches the clock-gater test ports so gated clocks run in test mode | `LIVE` | hw/sys/smc/doc/port_table.adoc#test_en_i@f2cb50de | — |
| [ ] | `SMC-DFT-TESTMODE.S2` | the test enable reaches the AXI cell test inputs | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#test_en_i@f2cb50de | — |
| [ ] | `SMC-DFT-TESTMODE.S3` | the scan reset bypasses the reset synchronizers during DFT | `LIVE` | hw/sys/smc/doc/port_table.adoc#scan_rst_ni@f2cb50de; `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |

### `SMC-MAP-DECODE` — SMC component address decode

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-MAP-DECODE.S1` | each declared functional region routes to its component | `DECODE` | `memmap.adoc#SMC` §Address Space Layout | SF-001, SF-002, SF-043, SF-053, SF-055 |
| [ ] | `SMC-MAP-DECODE.S2` | each region's base and top address both decode to the same component and the address immediately beyond does not | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-007, SF-053, SF-055 |
| [ ] | `SMC-MAP-DECODE.S3` | the CLA aperture decodes over its declared 36 KB extent | `DECODE` | `memmap.adoc#SMC` §Component Address Map; `dfd.adoc#Register` §Map | SF-055 |
| [ ] | `SMC-MAP-DECODE.S4` | **[contested]** [BOUNDED-LIVENESS] an access to a gap between declared regions terminates with an error rather than hanging | `LIVE` | `memmap.adoc#SMC` §Address Space Layout; `fabric.adoc#Fabric` §Traffic Subordinates | SF-043, SF-053, SF-055 |

### `SMC-MAP-DUALBASE` — Local alias and global base addressing

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-MAP-DUALBASE.S1` | the local base is fixed read-only at 0xC000_0000 | `LIVE` | `memmap.adoc#Memory` §Map | — |
| [ ] | `SMC-MAP-DUALBASE.S2` | the global base is programmable by firmware | `LIVE` | `memmap.adoc#Memory` §Map | — |
| [ ] | `SMC-MAP-DUALBASE.S3` | a resource reached at its local alias address and at its global address behaves identically | `LIVE` | `memmap.adoc#Memory` §Map | — |
| [ ] | `SMC-MAP-DUALBASE.S4` | an access outside the relevant aperture is not routed to the local resource | `LIVE` | `memmap.adoc#Memory` §Map; `fabric.adoc#Local` §and Remote Resource Access | — |
| [ ] | `SMC-MAP-DUALBASE.S5` | after global aperture reconfiguration, global addresses are usable for accesses that leave the local SMC view | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | — |

### `SMC-MAP-IFSTD` — Register interface standards

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-MAP-IFSTD.S1` | AXI4-Lite register accesses use a 32-bit address and 64-bit data | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |
| [ ] | `SMC-MAP-IFSTD.S2` | APB4 register accesses use a 32-bit address and 32-bit data | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |
| [ ] | `SMC-MAP-IFSTD.S3` | 32-bit registers sit on 4-byte boundaries and 64-bit registers on 8-byte boundaries | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |
| [ ] | `SMC-MAP-IFSTD.S4` | byte ordering is little-endian throughout | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |

### `SMC-EXTWIN-MAND` — Mandatory adopter external window

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-EXTWIN-MAND.S1` | the mandatory region decodes at the external window base | `DECODE` | `memmap.adoc#AXI-Lite` §External Window | — |
| [ ] | `SMC-EXTWIN-MAND.S2` | the 65 per-pad control blocks decode at their declared stride | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| [ ] | `SMC-EXTWIN-MAND.S3` | the PLL wrapper decodes at its declared offset | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| [ ] | `SMC-EXTWIN-MAND.S4` | the PVT wrapper decodes at its declared offset | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| [ ] | `SMC-EXTWIN-MAND.S5` | the eFuse SHIM decodes at its declared offset | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |

### `SMC-EXTWIN-SUPP` — Supplementary external window and passthrough

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-EXTWIN-SUPP.S1` | the supplementary region decodes at its declared base | `DECODE` | `memmap.adoc#AXI-Lite` §External Window | — |
| [ ] | `SMC-EXTWIN-SUPP.S2` | hardware treats the mandatory and supplementary regions identically, the split being organizational only | `LIVE` | `memmap.adoc#AXI-Lite` §External Window | — |
| [ ] | `SMC-EXTWIN-SUPP.S3` | the captured GPIO strap registers are readable in the supplementary region | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | SF-007, SF-054 |
| [ ] | `SMC-EXTWIN-SUPP.S4` | the unallocated remainder of the window is passed through to the chip-level adopter external port | `LIVE` | `memmap.adoc#AXI-Lite` §External Window | — |
| [ ] | `SMC-EXTWIN-SUPP.S5` | **[contested]** [BOUNDED-LIVENESS] an access to the passthrough remainder with no adopter responder terminates with an error rather than hanging the bus | `LIVE` | `memmap.adoc#AXI-Lite` §External Window; `fabric.adoc#Fabric` §Traffic Subordinates | — |

### `SMC-MAP-SPARE` — System and spare register blocks

| Reviewed | Scenario | Intent | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|
| [ ] | `SMC-MAP-SPARE.S1` | the chip config block is readable and writable at its mapped offset | `LIVE` | `memmap.adoc#Chip` §Config, Scratch, NDM Reset, and Misc Wrap | — |
| [ ] | `SMC-MAP-SPARE.S2` | the general-purpose scratch registers retain written values | `LIVE` | `memmap.adoc#Chip` §Config, Scratch, NDM Reset, and Misc Wrap | — |
| [ ] | `SMC-MAP-SPARE.S3` | the miscellaneous wrapper aperture decodes over its declared extent | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-055 |
| [ ] | `SMC-MAP-SPARE.S4` | the SMC base config block is accessible and carries the hang detector controls | `LIVE` | `memmap.adoc#Base` §Config, DFX Status, and GPIO POC/PBias; `interrupts.adoc#Exact` §Indexed Map | — |
| [ ] | `SMC-MAP-SPARE.S5` | the DFX control and status block is accessible and carries the memory repair status | `LIVE` | `memmap.adoc#Base` §Config, DFX Status, and GPIO POC/PBias; `cpu.adoc#Memory` §Repair | SF-001, SF-053 |
| [ ] | `SMC-MAP-SPARE.S6` | the region size output presents the configured SMC address region size to external systems | `LIVE` | hw/sys/smc/doc/port_table.adoc#smc_region_size_o@f2cb50de | — |

## 4. Interactions — crosses the spec explicitly demands

| Reviewed | Key | Intent | Features crossed | Spec ref |
|---|---|---|---|---|
| [ ] | `INT-POR-BOOT` | the cold boot chain runs in order - power-good stable, fuse sense, memory repair, MBIST, then cluster reset release and the first fetch at the ROM vector | `SMC-RST-POR`, `SMC-MEMREPAIR`, `SMC-CPU-RSTVEC`, `SMC-ROM-MAP` | `cpu.adoc#Memory` §Repair; `clk_rst.adoc#Reset` §Architecture (+1) |
| [ ] | `INT-ISO-RESET` | a pending cluster software reset isolates and drains both AXI ports before the reset is applied | `SMC-ISO-DRAIN`, `SMC-CLUSTER-ISO` | `cpu.adoc#Drain` §Handshake; `cpu.adoc#Cluster` §Boundary Isolation |
| [ ] | `INT-FLR-COOL` | an FLR trigger crosses into the SMC and reference domains, asserts isolation, waits the pre-reset delay, asserts cool reset for the hold time and bypasses memory repair | `SMC-FLR-CDC`, `SMC-ISOLATE-CTRL`, `SMC-FLR-SEQ`, `SMC-RST-COOL`, `SMC-REPAIR-BYPASS` | `clk_rst.adoc#Function` §Level Reset (FLR); `clk_rst.adoc#Programmable` §Reset Timing (+1) |
| [ ] | `INT-OUTBOUND-PATH` | outbound traffic is alias remapped, then privilege remapped, then filtered on the remapped address, and leaves carrying the source ID of the path it took | `SMC-FAB-ALIAS`, `SMC-FAB-PRIVREMAP`, `SMC-FILT-OUT`, `SMC-FAB-SRCID` | `fabric.adoc#Outbound` §Filtering; `fabric.adoc#Outbound` §Traffic Flow |
| [ ] | `INT-FILTER-ERRSLV` | an inbound transaction no filter entry admits is routed to the error slave and the initiator receives a decode error | `SMC-FILT-IN`, `SMC-FILT-NS`, `SMC-FAB-ERRSLV` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters); `fabric.adoc#Inbound` §Filtering |
| [ ] | `INT-DMA-FILTER` | a DMA transfer is subject to the fabric alias remap and filtering mechanisms on its way to the destination | `SMC-DMA-XFER`, `SMC-FAB-MGR-ALIASPATH`, `SMC-FILT-OUT` | `dma.adoc#DMA` §Controller Integration; `fabric.adoc#Fabric` §Traffic Managers |
| [ ] | `INT-DMA-IRQ-PLIC` | a DMA completion pulse reaches its vector bit, becomes the corresponding PLIC source and is claimed by a core | `SMC-DMA-IRQ`, `SMC-INT-INTERNAL`, `SMC-INT-PLICID`, `SMC-PLIC-CLAIM` | `interrupts.adoc#Exact` §Indexed Map; `interrupts.adoc#SMC` §CPU Interrupt Vector Map |
| [ ] | `INT-ZERO-IRQ-PLIC` | a zeroer completion pulse reaches its vector bit, becomes the corresponding PLIC source and is claimed by a core | `SMC-ZERO-IRQ`, `SMC-INT-INTERNAL`, `SMC-INT-PLICID`, `SMC-PLIC-CLAIM` | `interrupts.adoc#Exact` §Indexed Map; `zeroer.adoc#Status` §Features |
| [ ] | `INT-CLA-CLKSTOP-IRQ` | a CLA clock-stop action drives the halt status which in turn drives the CLA clock-stop interrupt bit | `SMC-CLA-ACTION`, `SMC-CLA-CLKSTOP`, `SMC-INT-INTERNAL` | hw/sys/smc/doc/dfd.adoc#Interrupts@63552821; `interrupts.adoc#Exact` §Indexed Map |
| [ ] | `INT-WDT-WARM` | a watchdog timeout asserts the warm reset, which crosses asynchronously into the cluster isolate logic and is followed by a cold reset | `SMC-WDT`, `SMC-RST-WARM`, `SMC-ISO-RDC` | `clk_rst.adoc#Warm` §Reset Activation Sources; `cpu.adoc#Reset-Domain` §Crossing |
| [ ] | `INT-EFUSE-LOCK-IRQ` | an attempted locked-field access raises the violation interrupt which reaches its declared peripheral interrupt bit | `SMC-EFUSE-LOCKS`, `SMC-INT-PERIPHMAP` | `scan_protection.adoc#Downstream` §Lock Path; `interrupts.adoc#Exact` §Indexed Map |
| [ ] | `INT-HANGDET-CLEAR` | a hang interrupt is identified and cleared only through the base config hang detector control registers | `SMC-FAB-HANGDET`, `SMC-MAP-SPARE` | `interrupts.adoc#Exact` §Indexed Map; `memmap.adoc#Base` §Config, DFX Status, and GPIO POC/PBias |
| [ ] | `INT-ROM-ENDIAN-FUSE` | the eFuse shadow ROM endianness bit determines the byte order of every ROM word the CPU reads | `SMC-ROM-ENDIAN`, `SMC-EFUSE-IF` | `rom.adoc#ROM` §Hardware Configuration; hw/sys/smc/doc/port_table.adoc#shadow_regs_o@f2cb50de |
| [ ] | `INT-STRAP-REPAIR` | the strap captured at cold reset on the bypass pin determines whether memory repair runs in that boot | `SMC-GPIO-STRAPS`, `SMC-REPAIR-BYPASS` | `cpu.adoc#Memory` §Repair; `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) |
| [ ] | `INT-STRAP-OCTS` | the chiplet-is-primary strap captured at cold reset selects the OCTS primary or secondary mode | `SMC-GPIO-STRAPS`, `SMC-OCTS` | hw/sys/smc/doc/port_table.adoc#chiplet_is_primary_i@f2cb50de; `periphs.adoc#SMC` §Peripheral Summary |
| [ ] | `INT-APERTURE-DECODE` | the region size CSR sizes the local alias window and the global aperture together, so reprogramming it moves both decodes at once | `SMC-FAB-APERTURE`, `SMC-MAP-DUALBASE` | `fabric.adoc#Local` §and Remote Resource Access; `memmap.adoc#Memory` §Map |
| [ ] | `INT-CDC-PERIPH-IRQ` | an interrupt raised by a peripheral in the peripheral clock domain crosses into the SMC clock domain and appears on its declared vector bit | `SMC-PERIPH-CDC`, `SMC-INT-PERIPHMAP`, `SMC-CLK-PERIPH` | `interrupts.adoc#Exact` §Indexed Map; `clk_rst.adoc#The` §Peripheral Clock Domain |
| [ ] | `INT-SCAN-LOCKPATH` | the lock protection holds only jointly - the LOCKS flops are off every scan chain and no scannable flop downstream re-derives the decision | `SMC-SCAN-CLASS1`, `SMC-SCAN-DOWNSTREAM` | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22; `scan_protection.adoc#Downstream` §Lock Path |

## 5. Derivation notes (folding and exclusion decisions, verbatim from the feature list)

# SMC feature list (P0 candidate)

Derived forward from the thirteen pinned SMC chapters alone, under a sealed derivation: no
testlist, test source, coverage artifact, RTL or RDL was opened, and the pin's anchor fields were
never read. Every feature and every scenario traces to pinned specification text.

## Scope

The inventory is scoped by the pin's functional boundary and **not** by milestone. It therefore
covers the full in-scope surface of the SMC subsystem as the pinned chapters specify it, whether
or not a P0 test could reach it. Milestone scoping belongs one layer down, on the testcase plan.

`overview.adoc` is pinned but contributes no feature of its own: every behavior it names is
stated normatively in another pinned chapter, and the parts unique to it (one SMC per chiplet,
the inter-SMC management hierarchy) are explicitly out of scope.

## Folded families — the count understates the surface

Several features deliberately fold a family of near-identical behaviors into one record with one
scenario per member. A reviewer should read the count as an understatement of the real surface:

- **`SMC-INT-PERIPHMAP`** folds the whole peripheral interrupt bit map, bits 287 down to 256,
  into fourteen scenarios. Each named source class (SEP mailbox, telemetry, NDM, I3C, UART and
  log engine, AVSBus, I2C, SEP watchdog, eFuse lock, GPIO lower and upper, hang detectors,
  reserved) is a separately closable claim about an exact bit index.
- **`SMC-FAB-MGR-ALIASPATH`** folds the DMA, JTAG2AXI and log engine managers, which the spec
  describes as sharing one remap-then-filter path.
- **`SMC-CLA-EVENT`** folds the seven CLA event types, and **`SMC-CLA-ACTION`** the six CLA
  actions, into one feature each.
- **`SMC-PERIPH-DECODE`** folds the decode of every integrated peripheral aperture and its
  instance count into four scenarios rather than one feature per peripheral block.
- **`SMC-MAP-DECODE`** folds the sixteen declared address-space regions into one decode feature.
- **`SMC-CPU-L1CACHE`** folds the per-core instruction and data caches, which differ only in
  write policy and protection scheme.

## Contested states

Scenarios whose intent begins `[BOUNDED-LIVENESS]` are the contested-state inventory:
concurrency, backpressure, request-during-busy, reset mid-transaction, error-during-error and
reconfiguration-during-flight. Each demands a bounded completion-or-error rather than an
unspecified stall. They are enumerated here so that a later plan must either allocate them or
record them unallocated with a reason; a contested case absent from this list could never be
missed downstream.

## Interactions

The eighteen interaction records capture only crossings the pinned text explicitly requires -
an ordering the spec states, a stage the spec says another stage feeds, or a protection the spec
says holds only jointly. No interaction was invented to raise the count.

## Open specification questions

Values this derivation could not pin from the specification alone were **not** invented. Each one
became a finding in `SMC_SPEC_REVIEW.md`, and several features above are consequently specified
only to the level their chapter reaches. Reviewers should read the two artifacts together.

---
*Machine identity:* feature list revision 1, `content_sha256` `d0c28f7ecce6f290`; pin revision 2; frozen at 2026-09-10T23:45:00-04:00.
