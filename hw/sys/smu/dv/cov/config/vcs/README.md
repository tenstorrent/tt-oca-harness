<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU VCS coverage scope

`smu_wrapper_cov_scope.hier` is passed to VCS at compile time as `-cm_hier`
plus `-cm_common_hier` (`[coverage.vcs]` in `smu_sim_cfg.toml`), so what it
drops never enters the coverage database. `gen_smu_cov_scope.py` writes it
from the build filelists; regenerate it after a build and `--rebuild`, and
`--check` tells whether the committed file is stale. The contents are not
fingerprinted, and VCS accepts a stale file silently.

    python3 tools/dv/run_dv.py --dut smu --items smoke      # any build
    python3 nonfree/hw/sys/smu/dv/cov/config/vcs/gen_smu_cov_scope.py

## Generators

Every `.hier` and `.el` file in this directory is generated. The generators
are the `hw/sys/smu/dv/cov/config/vcs/` scripts of the `nonfree` companion,
which this README names by file name: `gen_smu_cov_scope.py`,
`gen_smu_cov_toggle_exclusions.py`, `gen_smu_wrapper_toggle_exclusions.py` and
`gen_smu_wrapper_group_exclusions.py`. The commands in this README run them
from the repository root with the companion at `nonfree/`. Each takes
`--check`, which exits 1 when the committed file differs from what it would
write. The facts stay here: the class tables below state what each class
excludes, why, and what retires it. A reader without the companion derives
the same files from the same merged database: urg's `-dump full_exclusions`
templates carry every checksum and signature, the run's raw report
(`cov/report_raw/modinfo.txt`) marks which points are uncovered where a class
is gated on it, and the class tables say which points each class takes.

## The rule

The scope follows the rule `hw/sys/sep/dv/cov/config/vcs/sep_cov_scope.hier`
states and `hw/sys/smc/dv/cov/config/vcs/smc_cov_scope.hier` applies, so the
three subsystems' signoff figures are read on one definition: the bench and
the library and interconnect cells leave the database, a block graded on a
bench of its own leaves as an instance tree, and the rest stays graded.

| Drop | Form | Why |
|---|---|---|
| TB top's own body | `-tree smu_wrapper_uvm_top 1` | testbench code; its children are named below or stay |
| `u_dut.u_smu.u_smc`, `u_dut.u_smu.u_dtp`, `u_dut.u_smu.gen_sep.u_sep` | `-tree` | SMC, DTP and SEP are graded on their own benches (`hw/sys/smc/dv`, `hw/sys/dtp/dv`, `hw/sys/sep/dv`); grading them here attributes their holes to SMU, the argument SMC uses to drop its I3C controllers |
| `u_dut.u_smc_ip_integration`, `u_dut.u_sep_ip_integration` | `-tree` | adopter-side collateral of SMC and SEP, owned by those packages |
| `u_axi_out_bridge`, `u_axi_out_cut`, `u_axi_out_if` | `-tree` | bench-side AXI egress glue carrying the outbound port to the bench slave |
| bench units (every unit compiled from a `dv/` directory: testbench tops, models, VIP and the `hw/common/dv/shims` wire models such as the open-drain cross-trigger wire) | `-module` | testbench code, wherever the bench instantiates it; no DUT source lives under `dv/`. A bench stand-in named like the product cell it replaces is listed once, as the product |
| library cells (pulp `common_cells`, OpenTitan `prim*`, OCAH `ocah_prim`) | `-module` | leaf primitives whose behaviour is the same in every design; the same list SMC drops |
| interconnect cells (vendored pulp AXI, APB, register_interface, AXI-Stream, OBI) | `-module` | the pulp `axi_xbar` inside `smu_axi_xbar` and the `axi_iw_converter` ID adapters; `smu_axi_xbar`, which configures and wraps them, stays graded, so a decode fault lands on SMU's own module |
| `axi_pkg` | `-module` | a package, which would report an assertion row with no logic behind it |
| `cov/sv` monitors | `-module` inside `begin line+cond+fsm+branch+tgl` | bench code for the code and toggle metrics; outside that block they stay in the assertion metric, which carries their `cover property` points, and their covergroups are outside `-cm_hier` altogether |

The `-module` lines are generated because VCS scopes by design unit or
instance and a library cell is instantiated where no `-tree` reaches it. VCS
warns `VCM-HFUFF` once per listed unit the elaboration did not instantiate;
that is the list being a superset of one build, not an error.

What stays graded is the SMU's own logic: `hw/top/smu_wrapper.sv`,
`hw/sys/smu/rtl/smu.sv`, `smu_axi_xbar.sv` and any other unit instantiated under `u_smu` outside the three subsystem trees.
urg's `hierarchy.txt` for a finished run is the check: at the top it lists
`u_dut` and the `cov/sv` monitors and nothing else, and under `u_dut` it lists
`u_smu` and, below it, only those units.

## Two populations

`../verilator/smu_wrapper_cov_scope.vlt` keeps a narrower set: it turns
coverage off for `hw/sys/smu/rtl/*` as well, so the public Verilator figure
is the wrapper and the `cov/sv` points, while the VCS figure is the SMU block
under the rule above. Verilator's `coverage_off` takes source-path globs
only, and the public runner compiles the coverage-instrumented model in a
fixed time budget, so widening its population is a separate decision with a
measurement of its own. Quote the flow with the number.

## Toggle on every net

Toggle covers every net of the units the scope keeps, in both directions, as
on the SMC scope. `-cm_tgl portsonly` is not used: with `u_smu` graded the
kept population is no longer one wiring module, and `smu.sv` and
`smu_axi_xbar.sv` hold the region registers, address decode and ID
remapping whose internal nets a ports-only count would hide. SMC grades a
unit of OpenTitan origin on its ports only, at report time; no unit the SMU
scope keeps is of OpenTitan origin (the OpenTitan units in the build are
library cells above or sit inside the SEP and SMC trees), so there is no such
file here.

`-cm_noconst` and `-cm_seqnoconst` drop nets a constant drives from the toggle
population, so a port tied off is not a hole; the DTP scope sets the same two
options.

## Port toggle exclusions

`smu_wrapper.sv` is wiring: three instances, no assign, no process, no
generate. Every port is a point-to-point connection to a subsystem port, so
the wrapper's ports are graded per field, with the fields below left out
through
`smu_wrapper_toggle_exclusions.el` (`-elfile`, named by the policy's
`[[native_files]]`). `gen_smu_wrapper_toggle_exclusions.py` writes that file
from urg's `-dump full_exclusions tgl` template of the merged database, so the
module checksum and every field signature come from urg, and `--check` tells
whether the committed file is stale.

| Class | Fields | Why they are not the wrapper's to toggle | Retired by |
|---|---|---|---|
| `AXI-USER` | `aw/ar/w/r/b.user` on both crossbar ports | the SMU neither reads nor writes the user sideband: the 12-bit user word (`smu_axi_xbar_pkg.sv` 50) rides beside each channel through the pulp crossbar (`smu_axi_xbar.sv` 110-142) and the ID converters (`smu.sv` 1127-1173), and no SMU unit reads it | an SMU decode or remap that reads the user sideband |
| `AXI-DATA` | `w.data`, `w.strb`, `r.data` on both crossbar ports | the data path passes through the crossbar (`smu_axi_xbar.sv` 110-142) and the ID converters (`smu.sv` 1127-1173) untouched; address and id stay graded because the crossbar decodes and remaps them | an SMU unit that inspects or rewrites data or strobe |
| `ATB-PAYLOAD` | `telemetry_atdata_i`, `telemetry_atid_i` | `smu_wrapper.sv` (454-455) and `smu.sv` (835-836) connect both words straight to the SMC telemetry receivers, which consume them and are graded on the SMC bench | SMU logic that reads the ATB data or id, or the receivers moving out of the SMC |
| `DFT` | `test_en_i`, `scan_rst_ni` | bench scope: `tb_wrapper_top.sv` (1322-1323) ties them to their functional values 0 and 1, and no leaf exercises scan insertion or the scan-mode reset bypass | a DFT bench that drives scan enable and scan reset |
| `RTL-CONSTANT` | `lsio_interface_select_o` | driven from a constant inside the SMU: the LSIO select follows the SPI enable `smu.sv` (1193, 1195) takes from `sep_io_pkg::ot_spi_pad_map`, which sets it to 1 (`sep_io_pkg.sv` 81), with SEP present; `-cm_noconst` keeps it because the constant is assigned inside the SMU | the SPI enable becoming programmable |
| `UNION-ALIAS` | `smc_shadow_regs_o.locks.*`, `smc_shadow_regs_o.fields.*` | `efuse_map_t` is a packed union (`smc_efuse_pkg.sv` 170-174); urg lists the same 8192 flops under three views, and `values` carries every bit once | `efuse_map_t` ceasing to be a union |
| `SEP-OWNED` | `sep_cpu_trace_o`, `sep_lockstep_*`, `sep_ext_interrupts_i`, `entropy_rosc_sample_clk_i`, `lc_sigint_err_o` | `smu.sv` only routes them between `u_sep` and its ports (991-993, 1000, 1030, 1187); each is graded on the SEP bench. Bench scope beside that: the CPU trace moves only under SEP firmware that drives it, the lockstep pair is inert unless the SEP CPU is built with `RV_LOCKSTEP_ENABLE` (`sep_cpu.sv` 110-115), and `lc_sigint_err_o` needs a fault injected in the SEP (`LC-SIGINT-ENCODED` below) | SMU logic that consumes one of them |
| `REGISTER-WIDTH` | `sep_region_size_o[55:32]` | `sep_cpu_ctrl` SEP_REGION_SIZE carries its size in [31:0] and reserves [63:32], so the port's upper bits are zero-extension; `smu_toggle_exclusions.el` takes the same bits of `smu`'s port | SEP_REGION_SIZE.size widening past bit 31 |

Everything else on the port list is graded per field, both directions, and a
field that stays uncovered is a stimulus gap for a leaf on this bench.

## Block exclusions

`smu_toggle_exclusions.el` (`-elfile`, named by the policy's `[[native_files]]`)
leaves out toggle points of `smu`, `smu_wrapper` and `smu_axi_xbar`, and the
condition rows of the lifecycle integrity error, each for a stated fact. `gen_smu_cov_toggle_exclusions.py` writes
it from urg's `-dump full_exclusions` templates of the merged database and the
run's raw report, so every checksum and signature comes from urg, and
`--check` tells whether the committed file is stale:

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl+cond+branch -report <dir>
    python3 nonfree/hw/sys/smu/dv/cov/config/vcs/gen_smu_cov_toggle_exclusions.py \
        fullexclude_module.tgl <run dir>/cov/report_raw/modinfo.txt \
        --cond fullexclude_module.cond --branch fullexclude_module.branch

The file is generated from an `all` run, the coverage set: a point `all`
leaves uncovered is uncovered in `hosted` too, so the file holds for both.
An entry names only what the raw report marks uncovered: a toggle field wholly
uncovered is excluded whole, otherwise each uncovered range in the direction
the report marks missing, clipped to the bits a class names (and, where a
class names a direction for a bit window, only that direction); a partly
uncovered multi-dimensional range is written index by index, as are the
declared bits a report's "Other bits of" row stands for, and a class that
names a bit window leaves such a range graded; a condition row or branch arm
is taken only where the report says Not Covered. Fields
`smu_wrapper_toggle_exclusions.el` already names are skipped.

| Class | Fact | Retired by |
|---|---|---|
| `MEM-MACRO` | data, mask, strobe, parity and ECC words of the SMC and SEP RAM, ROM and TCM interfaces; `smu.sv` connects each such `u_smc`/`u_sep` port straight to its own port and `smu_wrapper.sv` connects that to `hw/top/smc_ip_integration.sv` or `hw/top/sep_ip_integration.sv`, where the macros are; no SMU logic reads or writes the words | an SMU process on these words, or the macros moving under `u_smu` |
| `MEM-MACRO-CONTROL` | address, request, enable, write-enable, mode and handshake fields of the same interfaces; `smu.sv` (869-922, 1002-1043) connects each interface whole between `u_smc` or `u_sep` and its own port, `smu_wrapper.sv` carries it whole to the macros, and no SMU logic reads or drives a field; the rows left uncovered record which rows the owning CPU or controller touched, which the SMC and SEP benches grade | an SMU process on one of these interfaces, or a macro moving under `u_smu` |
| `AXSIZE-BUS-WIDTH` | AxSIZE[2] of every AXI4 channel in scope: each carries a 64-bit data bus (`smu_axi_xbar_pkg.sv` 31 and the `smc_pkg`/`sep_pkg` channel types), and AXI4 allows no transfer size wider than the bus, so AxSIZE stays at or below 3 | an AXI4 channel wider than 64 bits |
| `SEP-OTP-DBG-TIED` | the SMC and SEP OTP bridge terms of the SEP debug-disable vector in `smu`; `sep_lifecycle_ctrl.sv` (264-265) assigns both 1'b0 | `sep_lifecycle_ctrl` driving either term from the lifecycle state |
| `EXT-TRNG-STREAM-TIED` | the external TRNG AXI-stream requests into the SEP; `hw/top/sep_ip_integration.sv` (773) assigns every stream `'{default: '0}` | an integration shell that connects an external TRNG stream source |
| `SEP-DEBUG-LANES` | bits [383:0] of the external debug bus in `smu`, the SEP half: `sep.sv` (1186-1275) packs SEP-internal status into 24 sixteen-bit lanes and `smu.sv` (1384-1387) only concatenates it under the adopter's bits for the SMC debug mux; the SEP bench grades each source | SMU logic that reads a SEP debug lane |
| `JTAG2AXI-FIXED` | the AXI attributes the DTP JTAG2AXI bridges drive as constants -- AxID 0, AxLEN 0, INCR, AxLOCK 0, AxCACHE 4'b0010, AxPROT 3'b000, AxQOS and AxREGION 0 (`jtag2axi.sv` 147-151, 1248-1283, and 84/112 for the AXI4-Lite prot outputs) -- on the nets `smu.sv` (712-717, 792-795, 965-966) connects straight from each bridge to its target; only the bits those constants hold at 0 are taken | a JTAG2AXI bridge that programs any of these attributes |
| `AXI-USER` | the user sideband, which the pulp crossbar and the ID converters copy beside the channel | an SMU decode or remap that reads it |
| `AXI-DATA` | write data, write strobe and read data of every AXI and AXI-Lite channel; the SMU decodes addresses and converts ids and passes data through | an SMU unit that inspects or rewrites data or strobe |
| `RTL-CONSTANT` | `lsio_interface_select_o` following the SPI enable `smu.sv` takes from `sep_io_pkg::ot_spi_pad_map`, which sets it to 1 with SEP present | the SPI enable becoming programmable |
| `UNION-ALIAS` | the `locks` and `fields` views of the packed-union eFuse shadow map; `values` stays graded | `efuse_map_t` ceasing to be a union |
| `SEP-OWNED` | `sep_cpu_trace_o`, the lockstep pair, `sep_ext_interrupts_i` and `entropy_rosc_sample_clk_i`, which `smu.sv` only routes and the SEP bench grades | SMU logic consuming one of them |
| `REGISTER-WIDTH` | bits [55:32] of `smu`'s `sep_region_size_o`: `sep_cpu_ctrl` SEP_REGION_SIZE carries its size in [31:0] and reserves [63:32], so the 56-bit port is that field zero-extended, and `smu.sv` hands the crossbar only [31:0] | SEP_REGION_SIZE.size widening past bit 31 |
| `LC-SIGINT-ENCODED` | design fact: `efuse_shadow_regs.sv` (282-285, 350) keeps the raw 4-bit LC_STATE and re-encodes it with `prim_diff_encode_multi`, so the word the SEP exports is always a valid differential pair and the decoders in `sep_lifecycle_ctrl.sv` and `smc_efuse_wrapper.sv` fire only on corruption in flight. Takes `lc_sigint_err_o`, `sep_lc_sigint_err` and `efuse_lc_sigint_err` in `smu`, and the uncovered rows of the `smu.sv` assignments to `lc_sigint_err_o`, which the generator finds in the source | a fault-injection bench that corrupts the exported pair |
| `ATOP-DISABLED` | `smu_axi_xbar.sv` (131) builds the crossbar with `ATOPs(1'b0)` and `tb_wrapper_top.sv` ties the inbound AWATOP to 0; takes every `aw.atop` field | a crossbar built with ATOPs enabled |
| `FIXED-OUTBOUND-ATTRIBUTES` | bench scope: AxCACHE, AxPROT, AxQOS, AxREGION, AxLOCK and AxBURST on `smc_output_axi_req` and the crossbar's `smc_out` port; the leaves reach that path only through the two SMC masters a toolchain-free leaf drives, which hold them constant (`jtag2axi.sv` 1184-1216, the iDMA frontend `idma_reg.sv.tpl` 155-159). On the crossbar's `ext_out` side and `smu_axi_out` SEP traffic moves AxCACHE and AxREGION, so only the fields `OUTBOUND-FIXED-ATTRIBUTES` names are taken there | outbound traffic from the SMC CPU |
| `SEP-INITIATOR-FIXED` | AxLEN, AxLOCK, AxQOS, AxBURST[1], AxPROT[2:1] and ID bits 2 and 5 on the SEP's outbound channel up to the crossbar's `sep_out` port and on the dedicated SEP-to-SMC channel. Only the load/store unit, the debug system bus and the secure DMA reach them (`sep_local_axi_xbar_pkg.sv` 140-146); the load/store unit issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and a bus-buffer index below four as ID (`el2_lsu_bus_buffer.sv` 213, 519, 878-904), the system bus the same attributes with ID 0 (`el2_dbg.sv` 736-770), the DMA AxPROT 0 (`tlul_to_axi_lite.sv` 158) with FIXED and zero AxLEN, AxLOCK, AxQOS and ID (`axi_lite_to_axi.sv` 38-66); the crossbar puts an initiator index of at most 3 in ID bits [5:3] | a SEP initiator on these channels that issues bursts, locks, QoS, non-secure or instruction accesses, or IDs of four or more |
| `OUTBOUND-FIXED-ATTRIBUTES` | bench scope for the SMC half: AxQOS, AxLOCK, AxBURST[1] and AxPROT[2:1] on the crossbar's `ext_out` port and `smu_axi_out`, which carry only SMC and SEP traffic; the two SMC masters a toolchain-free leaf drives hold them at 0 (`jtag2axi.sv` 1184-1216, `idma_reg.sv.tpl` 134 and 155-159) and so does every SEP initiator | outbound traffic from the SMC CPU |
| `DECERR-SLAVE-RESPONSE` | the response code of the SEP external aperture and the external TRNG window: `hw/top/sep_ip_integration.sv` (760-795) terminates both in DECERR slaves, which drive the code as a constant (`axi_err_slv.sv` 145, 197) | an integration that connects a peripheral to either port |
| `SEP-EXTERNAL-WINDOW` | address bits [31:29] of the SEP external aperture: the local crossbar sends only `0x2000_0000`-`0x3FFF_FFFF` there (`sep_local_axi_xbar.sv` 192-196), so bits 31:30 stay 0 and bit 29, 1 on every request, never falls; only that direction of bit 29 is taken | a local crossbar rule that widens the aperture |
| `TRNG-WINDOW` | address bits [31:12] of the external TRNG window: the crypto interconnect sends only single-beat accesses to `0x1091_7000`-`0x1091_7FFF` there (`sep_crypto_pkg.sv` 113-121, `sep_crypto_axi_interconnect.sv` 205-214); a 0 bit of the base is taken in both directions, a 1 bit only falling | a TRNG window that moves or grows past 4 KiB |
| `EFUSE-COMMAND-LENGTH` | bits [7:1] of the fuse-command word count on both fuse-command ports: the read and program interfaces ask for one word (`efuse_read_interface.sv` 144, `efuse_program_interface.sv` 158) and the sense for 256 (`efuse_shadow_regs.sv` 57, 428-429) | a fuse-command source that asks for another word count |
| `ID-REMAP-TABLE` | ID bits [5:4] on the SEP and SMC inbound ports: each crossbar ID converter is built for 16 unique IDs (`smu.sv` 1130, 1154), so `axi_id_remap` drives its 4-bit table index zero-extended (`axi_id_remap.sv` 131, 198-200) | a converter built for more than 16 unique IDs |
| `SEP-EXTERNAL-ID` | ID bit 2 on the SEP external aperture port: the local crossbar prepends the initiator index above a 3-bit ID (`sep_local_axi_xbar_pkg.sv` 22-23, 141-145), and the load/store unit (bus-buffer index below four, `el2_lsu_bus_buffer.sv` 213), system bus and DMA (ID 0, `el2_dbg.sv` 736-770, `sep_dma_wrap.sv` 274-285) and the inbound remapper (four IDs, `sep_system_peripherals.sv` 642) never set it | an initiator of the external aperture with IDs of four or more |
| `ZEROER-WRITE-ONLY` | read ID bit 3 on the SMC's outbound path: the data accelerator mux puts the accelerator index there (`smc_data_accelerator_wrap.sv` 234-249; the zeroer is 1, `smc_pkg.sv` 334-335), the other input-fabric ports zero-extend into it (`prim_axi_id_prepend_wrap.sv` 35, 54; `axi_lite_to_axi.sv` 57-64), and the zeroer never reads (`zeroer.sv` 445-446) | a data accelerator at index 1 that reads |
| `EFUSE-SHIM-CSR-OKAY` | the response code of the eFuse bank-control CSR port: the shim answers from its register block (`efuse_interface_shim.sv` 78), which ties the write and readback errors to 0 (`efuse_shim_ctrl_reg.sv` 207-214, 307, 327, 332) | a shim register block that can report an access error |
| `EFUSE-SHIM-DEBUG` | bits 3, 4 and 12 of the eFuse shim debug bus (`efuse_interface_shim.sv` 577-584): design fact for bit 3, which none of the six read states (156-163) sets; bench scope for bits 4 and 12, the `prim_count` redundancy errors (118-137, 289-308), which rise only when the redundant counters disagree, a fault this bench does not inject | a read state machine with more than eight states, or counter fault injection |
| `DTP-CSR-OFFSET` | address bits 11, 13, 15, 30 and 31 of the DTP CSR port: `smc_peripherals.sv` (546-548) subtracts the window base and the peripheral crossbar registers the port (`smc_periph_axi_lite_xbar_pkg.sv` 103), so it holds its reset value `0x3FFF_5000` or an offset below the 2 KiB window (`smc_periph_axi_lite_xbar.sv` 133-136), which both leave those bits 0 | a DTP window of 2 KiB or more, or a rebase other than the window base |
| `TRNG-R-ACCEPT` | RREADY on the external TRNG port, the cut's R ready (`sep_crypto_axi_interconnect.sv` 1042-1058): only single-beat reads reach the port (144, 236-241), each on its own tracker of the width converter above (1012), which takes a beat whenever it holds none unforwarded (`axi_dw_downsizer.sv` 569-572), so the cut never holds two | a TRNG read path that admits bursts, or a buffering stage between the converter and the port |
| `OUTBOUND-B-ACCEPT` | BREADY on `ext_out` and past it, the ready of the crossbar port's B spill register (`smu_axi_xbar_pkg.sv` 112): every outbound initiator takes write responses as they arrive (`el2_lsu_bus_buffer.sv` 906, `el2_dbg.sv` 772, `tlul_to_axi_lite.sv` 245, `zeroer.sv` 280, `jtag2axi.sv` 767-770, `idma_axi_write.sv` 272 with `idma_nd_midend.sv` 207 and `idma_frontend_wrapper.sv` 280), the SMC CPU into a two-entry queue on its MMIO port (`OCAH4CORECluster_AXI4Buffer.sv` 207-216) | an outbound initiator that holds write responses back |
| `OTP-BRIDGE-DEPTH` | AW, W and AR ready of the SMC and SEP OTP ports, the spill-register readies of the eFuse wrappers' access-control demuxes (`smc_efuse_wrapper.sv` 146-163, `sep_efuse_wrapper.sv` 250-266, MaxTrans 2), which fall only with four requests of one direction outstanding; the OTP bridges issue at most three (`jtag2axi.sv` 585, 641-645) | an OTP bridge that keeps four requests of one direction in flight |
| `BENCH-SEP-OUT-DEPTH` | bench scope: AW, W and AR ready of the SEP outbound port; the SEP keeps at most six requests in flight (LSU 4, system bus 1, DMA 1) against eight slots per channel through the crossbar (`smu_axi_xbar_pkg.sv` 109-113) and the bench's `axi_cut` (`tb_wrapper_top.sv` 1018-1032) | a deeper SEP issue window, or removal of the bench cut |
| `BENCH-SMC-SHIM-OTP-PACING` | bench scope: AR and W ready of the SMC eFuse bank-control port; only the SMC OTP bridge reaches it (`efuse_interface_controller.sv` 284-307, `smc_periph_axi_lite_xbar.sv` 114-122), one request per JTAG DR update, at least 85 SMU clocks apart at this bench's TCK (`smu_env_cfg.py` 48-61), while the shim frees its holding registers within two clocks (`efuse_shim_ctrl_reg.sv` 114-150) | a shim initiator that issues requests back to back, or a TCK close to the SMU clock |
| `BENCH-NO-ECC-INJECTION` | bench scope: `smc_cluster_ded_o`, a registered OR of the SMC cluster's uncorrectable ECC flags (`smc_4core_cpu.sv` 191-196); this bench cannot corrupt a cluster memory word | an ECC injection path such as the SMC bench's `tb_cpu_ecc_poke_*` (`hw/sys/smc/dv/tb/tb_top.sv` 1087-1088) |
| `TRNG-B-ACCEPT` | BREADY on the external TRNG port, the ready of the B slots of the cut in front of it (`sep_crypto_axi_interconnect.sv` 1042-1058), which falls only with both holding a response: the port's responder admits one write at a time (`hw/top/sep_ip_integration.sv` 761-771, `prim_axi_lite_err_slv` MAX_TRANS default 1; `axi_err_slv.sv` 48, 86-100), the converters above pass B through, the crypto demux parks it only behind another crypto target's response into a spilled port (268-295), and every SEP initiator takes write responses as they arrive | a TRNG responder that admits more than one write, or a TRNG window initiator that holds write responses back |
| `BENCH-SMC-EXTERNAL-DEPTH` | bench scope: AWREADY of the SMC external window, the AW spill ready of the adopter-side window demux (`hw/top/smc_ip_integration.sv` 214-240, MaxTrans 1, SpillAw 1), which falls only with two writes queued behind a held response; the window's responders take each request as it comes, and with ext_in's responses held (`smu_smc_inbound_window_sweep_test` S4) the SMC local crossbar's eight writes to its peripheral port (`smc_local_xbar_pkg.sv` 285-288) leave six responses in its port cut and the peripheral crossbar's two port cuts (`smc_periph_axi_lite_xbar_pkg.sv` 100-103) and two writes at the window | an adopter responder that holds a request or a response, or an initiator reaching the window with more writes in flight than the SMC local crossbar admits |
| `KM-RESET-OVERRIDE-X` | the Key Manager port's override in the IC_RESET SEP slice: applying and lifting it leaves `u_km_rom.req_i` (`hw/top/sep_ip_integration.sv` 273) X on a four-state simulator and `prim_rom`'s `noXOnCsI` (re-armed by `tb_wrapper_top.sv` 498-506) fails the run, so `smu_jtag_reset_override_test` stages and releases the port's control without applying it; a design question about the Key Manager's reset through `sep_reset_ctrl.sv` (280-297) | a Key Manager whose ROM request is defined after a JTAG override reset |
| `SMC-EXTERNAL-WINDOW` | address bits [29:23] of the SMC external window: the SMC peripheral crossbar sends only `0xC040_0000`-`0xC07F_FFFF` there (`smc_periph_axi_lite_xbar.sv` 145-149) | an SMC external window that moves or grows past 4 MiB |
| `XBAR-CONNECTIVITY` | the crossbar output ID carries the input port index in bits [9:8]; `smu_axi_xbar_pkg.sv` (127-133) routes ext_in (port 2) nowhere near `ext_out` and smc_out (port 1) nowhere near `smc_in`, so bit 9 on `ext_out` and past it, and bit 8 on `smc_in` and past it, stay 0 | a connectivity matrix that adds either route |
| `APERTURE-ALIGNMENT` | `smc_base_config.rdl` (38) requires GLOBAL_BASE and LOCAL_BASE to be aligned to REGION_SIZE; JTAG2AXI reaches BASE_CONFIG through the local window, so no size below 128 KiB can be followed by another setting, and base, rule start and rule end bits [16:0] stay 0; LOCAL_BASE is fixed at `0xC000_0000`, so REGION_SIZE[31] is never legal. Takes only those bits | a programmable LOCAL_BASE or a BASE_CONFIG path outside the local window |

The SEP aperture takes no class: SEP firmware images program the region size
and `smu_dtp_sep_dm_sba_test` walks the base and size. On the SEP's outbound
and dedicated SMC channels only the fields `SEP-INITIATOR-FIXED` names are
taken; `smu_sep_sba_fabric_sweep_test` and `smu_sep_lsu_fabric_test` drive the
rest, so a bit left uncovered there is a stimulus gap.

Cover properties are not excluded here. The ones a legal operating mode of
this bench cannot reach -- the two EXOKAY responses, the lifecycle
signal-integrity error and the zero SMC window -- are the Phase 2 set of
`hw/sys/smu/dv/docs/SMU_FCOV.adoc`, left out of the compile rather than
excluded from a report.

Address, id and handshake fields outside the classes that name them stay
graded, and a hole in one is a stimulus gap.

## Covergroups from vendored RTL

`-cm_hier` scopes line, condition, FSM, toggle and branch, and `-cm_common_hier`
extends it to assertions; neither reaches a covergroup. A covergroup declared
inside RTL is graded wherever the elaboration instantiates it, so the six
`cg_bus_event_fsm_transitions` groups the chipsalliance I3C core declares in
`i3c_target_fsm.sv` land in urg's GROUP score beside the wrapper's own
`cov/sv` covergroups, and none of the wrapper leaves drive an I3C bus event.
`smu_wrapper_group_exclusions.el` (`-elfile`, named by the policy's
`[[native_files]]`) drops them at report time.
`gen_smu_wrapper_group_exclusions.py` writes that file from urg's
`-dump full_exclusions group` template of the merged database, so the
definition checksum and every instance path come from urg, and `--check`
tells whether the committed file is stale. Every covergroup under `u_dut`
must fall in a class the script names; one that does not stops the script,
so a covergroup a future vendored block adds is a decision, not a silent
inclusion.

| Class | Covergroups | Why they are not the wrapper's to fill |
|---|---|---|
| `VENDORED-I3C` | `xi3c_target_fsm::cg_bus_event_fsm_transitions`, six instances | the I3C controllers' internals are graded by `hw/ip/i3ccore_wrap/dv`; the wrapper reaches them only through the SMC |

What remains in GROUP is the `u_smu_*_fcov::cg_*` set, the covergroup half of
the wrapper's functional coverage; `cov/sv` cover properties are the other
half and are read under `assertion`.

## Reading a finished run

```
python3 tools/dv/run_dv.py --dut smu --tool vcs --items all --cov
```

`all` is the coverage set, as it is for SEP: the 120 leaves of the package
regression, including the SEP firmware and lifecycle leaves whose images the
`c_compile` stage builds with the RISC-V toolchain. `hosted` is the
toolchain-free subset the workflows run and leaves that stimulus out.

The runner compiles with the scope, runs the group, merges, writes the urg
report with the exclusion files, and prints one `coverage` line with every
family as raw/effective; `smu_wrapper_coverage_policy.toml` floors `user` at
100 percent and `toggle` and `assertion` at 80 percent, and the result carries
`coverage=PASS` or `FAIL`. Nothing else is run. `toggle` is urg's TOGGLE column
after the exclusions; `user` is the cov/sv `cover property` points, which the
runner reads from the cover-property summary of `cov/report/asserts.txt`;
`assertion` is urg's ASSERT column, those points together with the
`assert property` statements left in scope. Per-port detail is in the `Port
Details` rows of the module's section in `cov/report/modinfo.txt`, with
`Excluded` and the class annotation on every field the exclusion file dropped.
The same payload, sideband and SEP-owned fields reappear as ports and nets of
`smu` and are graded there until a class of the same kind names them.

No public CI job runs the VCS flow for this DUT.
