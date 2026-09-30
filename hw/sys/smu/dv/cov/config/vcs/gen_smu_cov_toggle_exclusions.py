#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write smu_toggle_exclusions.el from urg's toggle template and the raw report.

The SMU scope grades every net of `smu`, `smu_wrapper` and `smu_axi_xbar`.
Some of those nets carry bits no SMU logic reads or
writes, and each class below states that fact and what would retire it:

* MEM-MACRO: the data words of the subsystem RAM, ROM and TCM interfaces. The
  SMU only routes them between the SMC and SEP ports and the macros in
  `hw/top/smc_ip_integration.sv` and `hw/top/sep_ip_integration.sv`.
* MEM-MACRO-CONTROL: the remaining fields of those interfaces -- address,
  request, enable, write-enable and the handshake back -- which the same
  whole-struct connections carry and which the owning CPU, crypto engine or
  controller alone drives.
* AXSIZE-BUS-WIDTH: AxSIZE[2] of every AXI4 channel. Each carries a 64-bit data
  bus, and a transfer size above the bus width is not a legal AXI4 transfer.
* SEP-OTP-DBG-TIED: the two OTP bridge terms of the SEP debug-disable vector,
  which the SEP lifecycle controller ties low.
* EXT-TRNG-STREAM-TIED: the external TRNG AXI-stream requests, which the
  reference SEP integration shell ties to zero.
* SEP-DEBUG-LANES: the SEP half of the external debug bus, SEP-internal
  status lanes the SMU only concatenates and forwards.
* JTAG2AXI-FIXED: the AXI attributes the DTP JTAG2AXI bridges hold constant,
  on the nets that carry only bridge traffic.
* AXI-DATA, AXI-USER: write data, write strobe, read data and the user
  sideband of every AXI and AXI-Lite channel these units carry. The crossbar
  and the ID converters decode addresses and ids and pass these words
  through untouched.
* RTL-CONSTANT, UNION-ALIAS, SEP-OWNED: the facts
  `smu_wrapper_toggle_exclusions.el` states for the wrapper's ports, where
  the same nets recur as ports of `smu`.
* LC-SIGINT-ENCODED: the lifecycle integrity error, which the SEP eFuse shadow
  registers make unreachable by re-encoding the word they export; its
  condition rows in `smu.sv` go with it.
* ATOP-DISABLED: AWATOP, which the crossbar is built not to carry.
* FIXED-OUTBOUND-ATTRIBUTES: bench scope: the AXI attributes on the SMC's
  outbound path, up to the crossbar port only the SMC feeds, that both SMC
  masters a bench can drive hold constant; SMC CPU traffic retires it. Past that port the channel also carries SEP
  traffic, so it stays graded.
* SEP-INITIATOR-FIXED: AxLEN, AxLOCK, AxQOS, AxBURST[1], AxPROT[2:1] and ID
  bits 2 and 5 on the SEP's outbound and SMC channels, which every SEP
  initiator that reaches them drives as constants.
* OUTBOUND-FIXED-ATTRIBUTES: bench scope for the SMC half: AxQOS, AxLOCK,
  AxBURST[1] and AxPROT[2:1] on the crossbar's ext_out port, which the SEP
  initiators and the SMC masters a bench can drive all hold constant; SMC CPU
  traffic retires it.
* DECERR-SLAVE-RESPONSE, SEP-EXTERNAL-WINDOW, TRNG-WINDOW, SMC-EXTERNAL-WINDOW:
  the response code of the DECERR slaves on the SEP external and TRNG ports, and
  the address bits the decode that feeds each window holds fixed.
* EFUSE-COMMAND-LENGTH: the fuse-command word-count bits no command source sets.
* ID-REMAP-TABLE: the inbound ID bits above the index the crossbar's ID
  remappers hand out.
* SEP-EXTERNAL-ID: ID bit 2 on the SEP external aperture port, which no
  initiator of that target sets.
* ZEROER-WRITE-ONLY: read ID bit 3 on the SMC's outbound path, which only the
  zeroer, a write-only engine, would set.
* EFUSE-SHIM-CSR-OKAY: the response code of the eFuse bank-control CSR port,
  which the shim's register block never makes an error.
* EFUSE-SHIM-DEBUG: the eFuse shim debug-bus bits that only a read state the
  machine lacks (bit 3, a design fact) or a counter fault would set (bits 4
  and 12, bench scope: this bench injects no counter fault).
* DTP-CSR-OFFSET: the DTP CSR address bits the window rebase keeps 0.
* TRNG-R-ACCEPT: RREADY on the external TRNG port, which the width converter
  above it keeps high.
* OUTBOUND-B-ACCEPT: BREADY on ext_out, which every outbound initiator keeps
  high as its responses arrive.
* OTP-BRIDGE-DEPTH: the OTP ports' request readies, which fall only past a
  depth the OTP bridges never reach.
* BENCH-SEP-OUT-DEPTH, BENCH-SMC-SHIM-OTP-PACING, BENCH-NO-ECC-INJECTION:
  bench scope, not design facts: the SEP outbound readies, which the bench's
  buffering keeps high; the SMC eFuse shim readies, which the bench's JTAG
  pacing keeps high; and the SMC cluster DED output, which this bench has no
  way to raise.
* TRNG-B-ACCEPT: BREADY on the external TRNG port, which falls only with two
  responses held and the port's responder admits one write at a time.
* BENCH-SMC-EXTERNAL-DEPTH: bench scope: AWREADY of the SMC external window,
  which falls only with two writes queued behind a held response, a depth the
  bench's inbound traffic does not reach through the SMC crossbars.
* KM-RESET-OVERRIDE-X: the Key Manager reset override, which no leaf applies
  because lifting it leaves the Key Manager ROM request X.
* XBAR-CONNECTIVITY: the input-port bits of the crossbar's output ID that the
  connectivity matrix never sets on a given output.
* APERTURE-ALIGNMENT: the SMC aperture bits no programmable setting reaches.
* REGISTER-WIDTH: the SEP region-size bits above the register field.

The SEP aperture takes no class: the SEP firmware images program the region
size and `smu_dtp_sep_dm_sba_test` walks the base and size. On the SEP's
channels only the fields SEP-INITIATOR-FIXED names are taken; the address,
size, cache, region and the other ID bits are driven by
`smu_sep_sba_fabric_sweep_test` and `smu_sep_lsu_fabric_test`, so a hole there
is a stimulus gap.

Apart from the classes from FIXED-OUTBOUND-ATTRIBUTES on and MEM-MACRO-CONTROL,
AXSIZE-BUS-WIDTH, EXT-TRNG-STREAM-TIED and JTAG2AXI-FIXED, whose facts name
them, no class takes an address, id, length, size, burst, cache, protection,
QoS, region, lock or atomic field, nor a valid, ready or enable: those are
decode and handshake, and a hole in one is a stimulus gap.

An entry names only what the raw report marks uncovered. A field every bit of
which is uncovered in both directions is excluded whole; otherwise each
uncovered range is excluded, in the direction the report marks missing, with
every index of a multi-dimensional range written out; the report's "Other bits
of" row stands for the declared bits no row lists, and those are written out
the same way. A class that names a bit window applies it to one-dimensional
ranges only.

A condition row or branch arm is taken only where the raw report marks it
Not Covered.

The inputs are the templates urg writes for the merged database and the raw
report the runner writes beside it::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl+cond+branch -report <dir>
    python3 gen_smu_cov_toggle_exclusions.py fullexclude_module.tgl \\
        <run dir>/cov/report_raw/modinfo.txt \\
        --cond fullexclude_module.cond --branch fullexclude_module.branch [--check]

The templates land in urg's working directory. They carry each module
checksum and every signature, so no field name, expression or signature below
is typed by hand. `--check` exits 1 when the committed file is
out of date instead of rewriting it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "smu_toggle_exclusions.el"
WRAPPER_FILE = HERE / "smu_wrapper_toggle_exclusions.el"
MODULES = ("smu", "smu_wrapper", "smu_axi_xbar")

MEM_IF = (
    r"(smc_scratch_ram_intf|smc_l1_[id]cache_(tag|data)_intf|smc_rom_intf|trace_mem|"
    r"i3c_(dat|dct|rlt)_mem|(sep_)?km_(sram|rom)_mem|sep_(sram|crypto_pka_[id]mem_sram|"
    r"boot_rom|cpu_tcm)|abr_mem)_(req|rsp|resp|sink|src)(_[io])?(\[\d+\])?"
)
# The SEP-only request and response channels from the local crossbar's peripheral
# target to the SMU crossbar's sep_out port, and the dedicated SEP-to-SMC channel.
SEP_REQ = (
    r"(sep_smn_outbound_axi_req|gen_sep\.sep_out_xbar_req|sep_out_req_i|xbar_slv_req\[0\]|"
    r"sep_ext_to_smc_axi_req|smc_sep_axi_in_req)"
)
SEP_RESP = (
    r"(sep_smn_outbound_axi_resp|gen_sep\.sep_out_xbar_resp|sep_out_resp_o|xbar_slv_resp\[0\]|"
    r"sep_ext_to_smc_axi_resp|smc_sep_axi_in_resp)"
)
# The crossbar's ext_out request channel and the boundary past it.
EXT_OUT = r"(xbar_mst_req\[2\]|ext_out_req_o|smu_axi_out_req_o)"
MEM_DATA = (
    r"([a-z0-9_]*_)?(wdata|rdata|wmask|wstrobe|strb|be|wparity|rparity|parity|"
    r"mem_wr_data|mem_rd_data|wr_data_bank|wr_ecc_bank|bank_wr_data|bank_wr_ecc|"
    r"bank_dout|bank_ecc)"
)


def window_bits(base: int, lo: int, hi: int) -> tuple:
    """Windows over bits lo..hi of a fixed ``base``: a 0 bit never moves, a 1 bit never falls."""
    out: list[tuple] = []
    for bit in range(lo, hi + 1):
        direction = "1to0" if (base >> bit) & 1 else None
        if (
            out
            and out[-1][1] == bit - 1
            and (out[-1][2] if len(out[-1]) > 2 else None) == direction
        ):
            out[-1] = (out[-1][0], bit) + ((direction,) if direction else ())
        else:
            out.append((bit, bit) + ((direction,) if direction else ()))
    return tuple(out)


# (class, matcher over the full field name, fact, what would retire it,
#  modules the class applies to or None for all four, bit windows (lo, hi) a
#  range must fall in or None for any bit).
CLASSES: list[tuple[str, re.Pattern[str], str, str, tuple[str, ...] | None, tuple | None]] = [
    (
        "MEM-MACRO",
        re.compile(rf"^{MEM_IF}\.({MEM_DATA}|[a-z0-9_]+\.{MEM_DATA})$"),
        "data, mask, strobe, parity and ECC words of the SMC and SEP RAM, ROM and TCM "
        "interfaces. smu.sv connects each such port of u_smc and u_sep straight to its "
        "own port, smu_wrapper.sv connects that to hw/top/smc_ip_integration.sv or "
        "hw/top/sep_ip_integration.sv, where the macros are, and no SMU logic reads or "
        "writes the words; the SMC and SEP benches grade the memories.",
        "an SMU process that reads or drives these words, or the macros moving under u_smu",
        None,
        None,
    ),
    (
        "MEM-MACRO-CONTROL",
        re.compile(rf"^{MEM_IF}\."),
        "address, request, enable, write-enable, mode and handshake fields of the SMC "
        "and SEP RAM, ROM and TCM interfaces. smu.sv connects each interface whole "
        "between u_smc or u_sep and its own port (smu.sv 865-918, 998-1039), "
        "smu_wrapper.sv carries it whole to the macros in hw/top/smc_ip_integration.sv "
        "and hw/top/sep_ip_integration.sv, and no SMU logic reads or drives a field: the "
        "fields that toggle already prove every connection, and the rest record which "
        "rows the owning CPU, Adams Bridge, PKA, Key Manager, I3C or trace controller "
        "chose to touch, which the SMC and SEP benches grade.",
        "an SMU process on one of these interfaces, or a macro moving under u_smu",
        None,
        None,
    ),
    (
        "AXSIZE-BUS-WIDTH",
        re.compile(r"\.(aw|ar)\.size$"),
        "AxSIZE[2] of the AXI4 channels. Every AXI4 channel in scope carries a 64-bit "
        "data bus (smu_axi_xbar_pkg.sv 31, the smc_pkg and sep_pkg 56_64 and 32_64 "
        "channel types), and the AXI4 specification does not allow a transfer size "
        "wider than the data bus, so AxSIZE stays at or below 3 and bit 2 cannot rise.",
        "an AXI4 channel wider than 64 bits",
        None,
        ((2, 2),),
    ),
    (
        "SEP-OTP-DBG-TIED",
        re.compile(r"^sep_dbg_disable\.(smc|sep)_otp_jtag2axi$"),
        "the SMC and SEP OTP bridge terms of the SEP debug-disable vector. "
        "sep_lifecycle_ctrl.sv (264-265) assigns both 1'b0, so the lifecycle state never "
        "closes either OTP bridge.",
        "sep_lifecycle_ctrl driving either term from the lifecycle state",
        ("smu",),
        None,
    ),
    (
        "EXT-TRNG-STREAM-TIED",
        re.compile(r"^ext_trng_axis_req(_i)?(\[\d+\])?\."),
        "the external TRNG AXI-stream requests into the SEP. hw/top/sep_ip_integration.sv "
        "(773) assigns every stream '{default: '0}, so tdata, tstrb and tvalid are "
        "constant in this integration; an adopter TRNG replaces that assignment.",
        "an integration shell that connects an external TRNG stream source",
        None,
        None,
    ),
    (
        "SEP-DEBUG-LANES",
        re.compile(r"^(sep_)?ext_debug_bus$"),
        "the SEP half, bits [383:0], of the external debug bus. sep.sv (1186-1275) "
        "packs SEP-internal status into 24 sixteen-bit lanes -- CPU trace, ECC and "
        "performance-counter strobes, interrupt and reset status, eFuse, token, remap "
        "and filter-hit debug, and reserved zero fields -- and smu.sv (1380-1383) "
        "only concatenates it under the "
        "adopter's bits and hands it to the SMC debug mux; the SEP bench grades each "
        "source.",
        "SMU logic that reads a SEP debug lane",
        ("smu",),
        ((0, 383),),
    ),
    (
        "JTAG2AXI-FIXED",
        re.compile(
            r"^(dtp_axi_smc_dbg_req\.(aw|ar)\.(id|len|lock|prot|qos|region)|"
            r"dtp_axil_(smc|sep)_otp_jtag_req\.(aw|ar)\.prot)$"
        ),
        "AXI attributes the DTP JTAG2AXI bridges drive as constants: AxID 0, AxLEN 0, "
        "INCR, AxLOCK 0, AxCACHE 4'b0010, AxPROT 3'b000, AxQOS and AxREGION 0 "
        "(hw/ip/jtag/jtag2axi/rtl/jtag2axi.sv 141-142, 1185-1219, and 76/104 for the "
        "AXI4-Lite prot outputs). smu.sv connects each bridge straight to its target "
        "(711-716, 791-794, 963), so no other master drives these nets. Only the bits "
        "those constants hold at 0 are taken; the INCR and AxCACHE bits at 1 rise on "
        "the first transfer and fall on a reset.",
        "a JTAG2AXI bridge that programs any of these attributes",
        ("smu",),
        None,
    ),
    (
        "JTAG2AXI-FIXED",
        re.compile(r"^dtp_axi_smc_dbg_req\.(aw|ar)\.burst$"),
        "AXI attributes the DTP JTAG2AXI bridges drive as constants: AxID 0, AxLEN 0, "
        "INCR, AxLOCK 0, AxCACHE 4'b0010, AxPROT 3'b000, AxQOS and AxREGION 0 "
        "(hw/ip/jtag/jtag2axi/rtl/jtag2axi.sv 141-142, 1185-1219, and 76/104 for the "
        "AXI4-Lite prot outputs). smu.sv connects each bridge straight to its target "
        "(711-716, 791-794, 963), so no other master drives these nets. Only the bits "
        "those constants hold at 0 are taken; the INCR and AxCACHE bits at 1 rise on "
        "the first transfer and fall on a reset.",
        "a JTAG2AXI bridge that programs any of these attributes",
        ("smu",),
        ((1, 1),),
    ),
    (
        "JTAG2AXI-FIXED",
        re.compile(r"^dtp_axi_smc_dbg_req\.(aw|ar)\.cache$"),
        "AXI attributes the DTP JTAG2AXI bridges drive as constants: AxID 0, AxLEN 0, "
        "INCR, AxLOCK 0, AxCACHE 4'b0010, AxPROT 3'b000, AxQOS and AxREGION 0 "
        "(hw/ip/jtag/jtag2axi/rtl/jtag2axi.sv 141-142, 1185-1219, and 76/104 for the "
        "AXI4-Lite prot outputs). smu.sv connects each bridge straight to its target "
        "(711-716, 791-794, 963), so no other master drives these nets. Only the bits "
        "those constants hold at 0 are taken; the INCR and AxCACHE bits at 1 rise on "
        "the first transfer and fall on a reset.",
        "a JTAG2AXI bridge that programs any of these attributes",
        ("smu",),
        ((0, 0), (2, 3)),
    ),
    (
        "AXI-USER",
        re.compile(r"\.(aw|ar|w|r|b)\.user$"),
        "AXI user sideband words. The pulp crossbar and the ID converters copy them "
        "beside the channel, and no SMU logic reads them.",
        "an SMU decode or remap that reads the user field",
        None,
        None,
    ),
    (
        "AXI-DATA",
        re.compile(r"\.(w\.data|w\.strb|r\.data)$"),
        "AXI and AXI-Lite write data, write strobe and read data words. The SMU decodes "
        "addresses and converts ids but passes the data path through untouched, so the "
        "bits measure the payload the SMC, SEP, DTP and bench masters chose, which "
        "their benches grade.",
        "an SMU unit that inspects or rewrites data or strobe",
        None,
        None,
    ),
    (
        "RTL-CONSTANT",
        re.compile(r"^lsio_interface_select_o$"),
        "an output smu.sv drives from a constant in this composition: the LSIO interface "
        "select follows the SPI enable, which smu.sv assigns 1 when SEP is present.",
        "the SPI enable becoming programmable",
        None,
        None,
    ),
    (
        "UNION-ALIAS",
        re.compile(r"^smc_shadow_regs_o\.(locks|fields)(\.|\[|$)"),
        "the `locks` and `fields` views of the eFuse shadow map. efuse_map_t is a packed "
        "union, so urg lists the same flops three times; the `values` view stays graded "
        "and carries every bit once.",
        "efuse_map_t ceasing to be a union",
        None,
        None,
    ),
    (
        "SEP-OWNED",
        re.compile(
            r"^(sep_cpu_trace_o|sep_lockstep_ctrl_i|"
            r"sep_lockstep_status_o|sep_ext_interrupts_i|entropy_rosc_sample_clk_i)(\.|\[|$)"
        ),
        "SEP passthroughs smu.sv only routes: the SEP CPU trace needs SEP "
        "firmware, the lockstep pair is inert without RV_LOCKSTEP_ENABLE, and the SEP "
        "external interrupts and entropy sample clock terminate inside the SEP. The "
        "SEP bench grades each of them.",
        "SMU logic consuming one of these nets",
        None,
        None,
    ),
    (
        "LC-SIGINT-ENCODED",
        re.compile(r"^(lc_sigint_err_o|sep_lc_sigint_err|efuse_lc_sigint_err)$"),
        "the lifecycle signal-integrity error. efuse_shadow_regs.sv (282-285, 350) keeps "
        "the raw 4-bit LC_STATE and re-encodes it with prim_diff_encode_multi, so the "
        "word the SEP exports is always a valid differential pair and the decoders in "
        "sep_lifecycle_ctrl.sv and smc_efuse_wrapper.sv fire only on corruption in flight.",
        "a fault-injection bench that corrupts the exported pair",
        ("smu",),
        None,
    ),
    (
        "ATOP-DISABLED",
        re.compile(r"\.aw\.atop$"),
        "AXI atomic operations. smu_axi_xbar.sv (131) builds the crossbar with ATOPs(1'b0), "
        "and tb_wrapper_top.sv ties the inbound AWATOP to 0.",
        "a crossbar built with ATOPs enabled",
        None,
        None,
    ),
    # Bench scope: the leaves reach this path only through the two SMC masters
    # named in the fact; SMC CPU traffic retires the class.
    (
        "FIXED-OUTBOUND-ATTRIBUTES",
        re.compile(
            r"^(smc_output_axi_req|gen_sep\.smc_out_xbar_req|smc_out_req_i|xbar_slv_req\[1\])"
            r"\.(aw|ar)\.(cache|prot|qos|region|lock|burst)$"
        ),
        "AxCACHE, AxPROT, AxQOS, AxREGION, AxLOCK and AxBURST on the SMC's outbound path "
        "up to the crossbar's smc_out port. The two SMC masters a toolchain-free leaf "
        "drives hold them constant: jtag2axi.sv (1184-1216) and the iDMA register "
        "frontend (idma_reg.sv.tpl, 155-159). The crossbar's ext_out side also carries "
        "SEP traffic and stays graded.",
        "outbound traffic from the SMC CPU",
        None,
        None,
    ),
    (
        "SEP-INITIATOR-FIXED",
        re.compile(rf"^{SEP_REQ}\.(aw|ar)\.(len|lock|qos)$"),
        "AXI attributes every SEP initiator that reaches the SEP's outbound and SMC "
        "paths drives as constants. The local crossbar connects only the load/store "
        "unit, the debug module's system bus and the secure DMA to the peripheral "
        "target those paths leave from (sep_local_axi_xbar_pkg.sv 140-146). The "
        "load/store unit issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and an "
        "ID that is a bus-buffer entry index below four (el2_lsu_bus_buffer.sv 213, "
        "519, 878-904; LSU_NUM_NBLOAD 4 in the sep common_defines.vh 61); the system "
        "bus issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and ID 0 "
        "(el2_dbg.sv 736-770); the DMA's AXI-Lite master drives AxPROT 0 "
        "(tlul_to_axi_lite.sv 158) and axi_lite_to_axi.sv (38-66) adds FIXED and "
        "zeroes AxLEN, AxLOCK, AxQOS and the ID (sep_dma_wrap.sv 274-285). The crossbar "
        "puts the initiator index in ID bits [5:3], at most 3 on these paths, and the "
        "outbound mux adds its port in bits [7:6] (sep_system_peripherals.sv 349-379). "
        "So AxLEN, AxLOCK, AxQOS, AxBURST[1], AxPROT[2:1] and ID bits 2 and 5 cannot "
        "move.",
        "a SEP initiator on these paths that issues bursts, locks, QoS, non-secure or instruction accesses, or IDs of four or more",
        None,
        None,
    ),
    (
        "SEP-INITIATOR-FIXED",
        re.compile(rf"^{SEP_REQ}\.(aw|ar)\.burst$"),
        "AXI attributes every SEP initiator that reaches the SEP's outbound and SMC "
        "paths drives as constants. The local crossbar connects only the load/store "
        "unit, the debug module's system bus and the secure DMA to the peripheral "
        "target those paths leave from (sep_local_axi_xbar_pkg.sv 140-146). The "
        "load/store unit issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and an "
        "ID that is a bus-buffer entry index below four (el2_lsu_bus_buffer.sv 213, "
        "519, 878-904; LSU_NUM_NBLOAD 4 in the sep common_defines.vh 61); the system "
        "bus issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and ID 0 "
        "(el2_dbg.sv 736-770); the DMA's AXI-Lite master drives AxPROT 0 "
        "(tlul_to_axi_lite.sv 158) and axi_lite_to_axi.sv (38-66) adds FIXED and "
        "zeroes AxLEN, AxLOCK, AxQOS and the ID (sep_dma_wrap.sv 274-285). The crossbar "
        "puts the initiator index in ID bits [5:3], at most 3 on these paths, and the "
        "outbound mux adds its port in bits [7:6] (sep_system_peripherals.sv 349-379). "
        "So AxLEN, AxLOCK, AxQOS, AxBURST[1], AxPROT[2:1] and ID bits 2 and 5 cannot "
        "move.",
        "a SEP initiator on these paths that issues bursts, locks, QoS, non-secure or instruction accesses, or IDs of four or more",
        None,
        ((1, 1),),
    ),
    (
        "SEP-INITIATOR-FIXED",
        re.compile(rf"^{SEP_REQ}\.(aw|ar)\.prot$"),
        "AXI attributes every SEP initiator that reaches the SEP's outbound and SMC "
        "paths drives as constants. The local crossbar connects only the load/store "
        "unit, the debug module's system bus and the secure DMA to the peripheral "
        "target those paths leave from (sep_local_axi_xbar_pkg.sv 140-146). The "
        "load/store unit issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and an "
        "ID that is a bus-buffer entry index below four (el2_lsu_bus_buffer.sv 213, "
        "519, 878-904; LSU_NUM_NBLOAD 4 in the sep common_defines.vh 61); the system "
        "bus issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and ID 0 "
        "(el2_dbg.sv 736-770); the DMA's AXI-Lite master drives AxPROT 0 "
        "(tlul_to_axi_lite.sv 158) and axi_lite_to_axi.sv (38-66) adds FIXED and "
        "zeroes AxLEN, AxLOCK, AxQOS and the ID (sep_dma_wrap.sv 274-285). The crossbar "
        "puts the initiator index in ID bits [5:3], at most 3 on these paths, and the "
        "outbound mux adds its port in bits [7:6] (sep_system_peripherals.sv 349-379). "
        "So AxLEN, AxLOCK, AxQOS, AxBURST[1], AxPROT[2:1] and ID bits 2 and 5 cannot "
        "move.",
        "a SEP initiator on these paths that issues bursts, locks, QoS, non-secure or instruction accesses, or IDs of four or more",
        None,
        ((1, 2),),
    ),
    (
        "SEP-INITIATOR-FIXED",
        re.compile(rf"^({SEP_REQ}\.(aw|ar)|{SEP_RESP}\.(b|r))\.id$"),
        "AXI attributes every SEP initiator that reaches the SEP's outbound and SMC "
        "paths drives as constants. The local crossbar connects only the load/store "
        "unit, the debug module's system bus and the secure DMA to the peripheral "
        "target those paths leave from (sep_local_axi_xbar_pkg.sv 140-146). The "
        "load/store unit issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and an "
        "ID that is a bus-buffer entry index below four (el2_lsu_bus_buffer.sv 213, "
        "519, 878-904; LSU_NUM_NBLOAD 4 in the sep common_defines.vh 61); the system "
        "bus issues AxLEN 0, INCR, AxLOCK 0, AxQOS 0, AxPROT 3'b001 and ID 0 "
        "(el2_dbg.sv 736-770); the DMA's AXI-Lite master drives AxPROT 0 "
        "(tlul_to_axi_lite.sv 158) and axi_lite_to_axi.sv (38-66) adds FIXED and "
        "zeroes AxLEN, AxLOCK, AxQOS and the ID (sep_dma_wrap.sv 274-285). The crossbar "
        "puts the initiator index in ID bits [5:3], at most 3 on these paths, and the "
        "outbound mux adds its port in bits [7:6] (sep_system_peripherals.sv 349-379). "
        "So AxLEN, AxLOCK, AxQOS, AxBURST[1], AxPROT[2:1] and ID bits 2 and 5 cannot "
        "move.",
        "a SEP initiator on these paths that issues bursts, locks, QoS, non-secure or instruction accesses, or IDs of four or more",
        None,
        ((2, 2), (5, 5)),
    ),
    # Bench scope for the SMC half: the leaves reach ext_out from the SMC only
    # through the two masters named in the fact; SMC CPU traffic retires it.
    (
        "OUTBOUND-FIXED-ATTRIBUTES",
        re.compile(rf"^{EXT_OUT}\.(aw|ar)\.(qos|lock)$"),
        "AxQOS, AxLOCK, AxBURST[1] and AxPROT[2:1] on the crossbar's ext_out port and "
        "the boundary past it, which carry only SMC and SEP traffic "
        "(smu_axi_xbar_pkg.sv 127-133). The two SMC masters a toolchain-free leaf "
        "drives hold them at 0 (jtag2axi.sv 1184-1216; the iDMA register frontend, "
        "idma_reg.sv.tpl 134 and 155-159), and every SEP initiator does too "
        "(SEP-INITIATOR-FIXED).",
        "outbound traffic from the SMC CPU",
        None,
        None,
    ),
    # Bench scope for the SMC half: the leaves reach ext_out from the SMC only
    # through the two masters named in the fact; SMC CPU traffic retires it.
    (
        "OUTBOUND-FIXED-ATTRIBUTES",
        re.compile(rf"^{EXT_OUT}\.(aw|ar)\.burst$"),
        "AxQOS, AxLOCK, AxBURST[1] and AxPROT[2:1] on the crossbar's ext_out port and "
        "the boundary past it, which carry only SMC and SEP traffic "
        "(smu_axi_xbar_pkg.sv 127-133). The two SMC masters a toolchain-free leaf "
        "drives hold them at 0 (jtag2axi.sv 1184-1216; the iDMA register frontend, "
        "idma_reg.sv.tpl 134 and 155-159), and every SEP initiator does too "
        "(SEP-INITIATOR-FIXED).",
        "outbound traffic from the SMC CPU",
        None,
        ((1, 1),),
    ),
    # Bench scope for the SMC half: the leaves reach ext_out from the SMC only
    # through the two masters named in the fact; SMC CPU traffic retires it.
    (
        "OUTBOUND-FIXED-ATTRIBUTES",
        re.compile(rf"^{EXT_OUT}\.(aw|ar)\.prot$"),
        "AxQOS, AxLOCK, AxBURST[1] and AxPROT[2:1] on the crossbar's ext_out port and "
        "the boundary past it, which carry only SMC and SEP traffic "
        "(smu_axi_xbar_pkg.sv 127-133). The two SMC masters a toolchain-free leaf "
        "drives hold them at 0 (jtag2axi.sv 1184-1216; the iDMA register frontend, "
        "idma_reg.sv.tpl 134 and 155-159), and every SEP initiator does too "
        "(SEP-INITIATOR-FIXED).",
        "outbound traffic from the SMC CPU",
        None,
        ((1, 2),),
    ),
    (
        "DECERR-SLAVE-RESPONSE",
        re.compile(r"^(sep_external_resp(_i)?|ext_trng_axil_resp(_i)?)\.(b|r)\.resp$"),
        "the response code of the SEP external aperture and the external TRNG window. "
        "hw/top/sep_ip_integration.sv (760-795) terminates both in DECERR slaves, and "
        "axi_err_slv.sv (145, 197), which prim_axi_lite_err_slv wraps, drives the code as "
        "a constant, so its bits never move.",
        "an integration that connects a peripheral to either port",
        None,
        None,
    ),
    (
        "SEP-EXTERNAL-WINDOW",
        re.compile(r"^sep_external_req(_o)?\.(aw|ar)\.addr$"),
        "address bits [31:29] of the SEP external aperture. The local crossbar sends "
        "only 0x2000_0000-0x3FFF_FFFF there (sep_local_axi_xbar.sv 192-196), so bit 29 "
        "is 1 on every request and never falls, and bits 31:30 are 0.",
        "a local crossbar rule that widens the external aperture",
        None,
        window_bits(0x2000_0000, 29, 31),
    ),
    (
        "TRNG-WINDOW",
        re.compile(r"^ext_trng_axil_req(_o)?\.(aw|ar)\.addr$"),
        "address bits [31:12] of the external TRNG window. The crypto interconnect sends "
        "only single-beat accesses to 0x1091_7000-0x1091_7FFF to that port "
        "(sep_crypto_pkg.sv 113-121, sep_crypto_axi_interconnect.sv 205-214), so those "
        "bits hold the window base on every request: a 0 there never moves and a 1 "
        "never falls.",
        "a TRNG window that moves or grows past 4 KiB",
        None,
        window_bits(0x1091_7000, 12, 31),
    ),
    (
        "EFUSE-COMMAND-LENGTH",
        re.compile(r"^(sep|smc)_efuse_shim_command_req(_o)?\.access_length_words$"),
        "bits [7:1] of the fuse-command word count. The read and program interfaces "
        "ask for one word (efuse_read_interface.sv 144, efuse_program_interface.sv 158) "
        "and the sense for the whole shadow file, 256 words of the 8192-bit arrays "
        "(efuse_shadow_regs.sv 57, 428-429; sep_efuse_pkg.sv 291, smc_efuse_pkg.sv 124), "
        "so only bits 0 and 8 move.",
        "a fuse-command source that asks for another word count",
        None,
        ((1, 7),),
    ),
    (
        "SMC-EXTERNAL-WINDOW",
        re.compile(r"^smc_external_req(_o)?\.(aw|ar)\.addr$"),
        "address bits [29:23] of the SMC external window. The SMC peripheral crossbar "
        "sends only 0xC040_0000-0xC07F_FFFF there (smc_periph_axi_lite_xbar.sv 145-149, "
        "smc_addr.h SMC_TOP_SMC_EXTERNAL), where those bits are 0.",
        "an SMC external window that moves or grows past 4 MiB",
        None,
        window_bits(0xC040_0000, 23, 29),
    ),
    (
        "ID-REMAP-TABLE",
        re.compile(
            r"^(sep_smn_inbound_axi_(req|resp)|smc_sys_axi_in_(req|resp))\.(aw|ar|b|r)\.id$"
        ),
        "ID bits [5:4] on the SEP and SMC inbound ports past the crossbar's ID width "
        "converters. Each converter is built for 16 unique slave-port IDs (smu.sv 1125, "
        "1149), so it remaps through axi_id_remap, which drives the 4-bit table index "
        "zero-extended to the 6-bit port (axi_id_remap.sv 131, 198-200).",
        "a converter built for more than 16 unique IDs",
        ("smu",),
        ((4, 5),),
    ),
    (
        "SEP-EXTERNAL-ID",
        re.compile(r"^sep_external_(req(_o)?\.(aw|ar)|resp(_i)?\.(b|r))\.id$"),
        "ID bit 2 on the SEP external aperture port. The SEP local crossbar prepends "
        "the initiator index above a 3-bit initiator ID (sep_local_axi_xbar_pkg.sv 22-23) "
        "and connects the load/store unit, the debug module's system bus, the DMA and "
        "the inbound port to that target (141-145; sep_local_axi_xbar.sv 334). The "
        "load/store unit's ID is a bus-buffer entry index below four "
        "(el2_lsu_bus_buffer.sv 213; LSU_NUM_NBLOAD 4), the system bus and the DMA send "
        "ID 0 (el2_dbg.sv 736-770; sep_dma_wrap.sv 274-285), and the inbound remapper "
        "hands out four IDs (sep_system_peripherals.sv 642; axi_id_remap.sv 131, "
        "198-200), so bit 2 stays 0.",
        "an initiator of the external aperture with IDs of four or more",
        ("smu", "smu_wrapper"),
        ((2, 2),),
    ),
    (
        "ZEROER-WRITE-ONLY",
        re.compile(
            r"^(smc_output_axi_req|gen_sep\.smc_out_xbar_req|smc_out_req_i|xbar_slv_req\[1\])"
            r"\.ar\.id$|^(smc_output_axi_resp|gen_sep\.smc_out_xbar_resp|smc_out_resp_o|"
            r"xbar_slv_resp\[1\])\.r\.id$"
        ),
        "read ID bit 3 on the SMC's outbound path. That bit is the index the data "
        "accelerator mux prepends (smc_data_accelerator_wrap.sv 234-249, smc_pkg.sv "
        "334-335: the zeroer is 1). The MMIO and JTAG ports zero-extend their IDs into it "
        "(smc_input_fabric.sv 140-145, 169-170; prim_axi_id_prepend_wrap.sv 35, 54), the "
        "log port's AXI-Lite converter sends ID 0 (axi_lite_to_axi.sv 57-64), and the "
        "zeroer never issues a read (zeroer.sv 445-446).",
        "a data accelerator at index 1 that reads",
        None,
        ((3, 3),),
    ),
    (
        "EFUSE-SHIM-CSR-OKAY",
        re.compile(r"^(sep|smc)_efuse_bank_ctrl_resp(_i)?\.(b|r)\.resp$"),
        "the response code of the eFuse bank-control CSR port. The eFuse interface shim "
        "answers it from its generated register block (efuse_interface_shim.sv 78), "
        "which reports SLVERR only for a write or readback error and ties both to 0 "
        "(efuse_shim_ctrl_reg.sv 207-214, 307, 327, 332), so the code is always OKAY.",
        "a shim register block that can report an access error",
        None,
        None,
    ),
    # Bit 3 is a design fact; bits 4 and 12 are bench scope, since this bench
    # injects no prim_count fault.
    (
        "EFUSE-SHIM-DEBUG",
        re.compile(r"^(sep|smc)_efuse_debug_bus_o$"),
        "bits 3, 4 and 12 of the eFuse shim debug bus (efuse_interface_shim.sv 577-584). "
        "Bit 3 is the top bit of the read state, whose six states (156-163) never set "
        "it; bits 4 and 12 are the read and write init-cycle counters' error outputs, "
        "which prim_count raises only when its redundant counters disagree (118-137, "
        "289-308), a fault this bench does not inject.",
        "a read state machine with more than eight states, or counter fault injection",
        ("smu_wrapper",),
        ((3, 4), (12, 12)),
    ),
    (
        "DTP-CSR-OFFSET",
        re.compile(r"^smc_axil_dtp_csr_req\.(aw|ar)\.addr$"),
        "address bits 11, 13, 15, 30 and 31 of the DTP CSR port. smc_peripherals.sv "
        "(546-548) subtracts the DTP window base 0xC000_B000 from the address, and the "
        "peripheral crossbar registers each target port (smc_periph_axi_lite_xbar_pkg.sv "
        "103), so the port holds its reset value, 0 - 0xC000_B000 = 0x3FFF_5000, or the "
        "offset of a DTP request, which is below the 2 KiB window "
        "(smc_periph_axi_lite_xbar.sv 133-136). Those bits are 0 in both.",
        "a DTP window of 2 KiB or more, or a rebase other than the window base",
        ("smu",),
        ((11, 11), (13, 13), (15, 15), (30, 31)),
    ),
    (
        "OUTBOUND-B-ACCEPT",
        re.compile(rf"^{EXT_OUT}\.b_ready$"),
        "BREADY on the crossbar's ext_out port and the boundary past it: the ready of "
        "the port's B spill register (smu_axi_xbar_pkg.sv 112, CUT_ALL_PORTS), which "
        "falls only while two responses wait there for the path back to their "
        "initiator. Every initiator that reaches ext_out takes its write response as "
        "it arrives: the SEP load/store unit and system bus tie BREADY high "
        "(el2_lsu_bus_buffer.sv 906, el2_dbg.sv 772), the SEP DMA's AXI-Lite master "
        "raises it in the state that waits for B (tlul_to_axi_lite.sv 245), the zeroer "
        "ties it high (zeroer.sv 280), JTAG2AXI raises it while a write is outstanding "
        "(jtag2axi.sv 767-770), the iDMA's follows its midend's response ready, which is "
        "tied high (idma_axi_write.sv 272, idma_nd_midend.sv 207, "
        "idma_frontend_wrapper.sv 280), and the SMC CPU takes it into a two-entry queue "
        "on its MMIO port (OCAH4CORECluster_AXI4Buffer.sv 207-216) that drains into its "
        "TileLink D channel.",
        "an initiator on the outbound path that holds write responses back",
        None,
        None,
    ),
    (
        "TRNG-R-ACCEPT",
        re.compile(r"^ext_trng_axil_req(_o)?\.r_ready$"),
        "RREADY on the external TRNG port, the ready of the R slots of the cut in front "
        "of it (sep_crypto_axi_interconnect.sv 1042-1058), which fall only while the "
        "path above cannot take a response. The crypto interconnect sends that port only "
        "single-beat reads (144, 236-241), so each read occupies one tracker of the data "
        "width converter above it (1012, AxiMaxReads 8) and brings back at most the two "
        "narrow beats of one wide beat; a tracker takes a beat whenever it holds none "
        "unforwarded (axi_dw_downsizer.sv 569-572), and a tracker is only reused once "
        "its beat has gone up. The converter therefore takes every beat as it arrives, "
        "the AXI-Lite converter between passes R straight through, and the cut never "
        "holds two.",
        "a read path to the TRNG port that admits bursts, or a buffering stage between "
        "the converter and the port",
        None,
        None,
    ),
    (
        "OTP-BRIDGE-DEPTH",
        re.compile(r"^dtp_axil_(smc|sep)_otp_jtag_resp\.(aw|w|ar)_ready$"),
        "the AW, W and AR ready of the SMC and SEP OTP JTAG2AXI ports. Each is the "
        "spill-register ready of the eFuse wrapper's access-control demux "
        "(smc_efuse_wrapper.sv 146-163, sep_efuse_wrapper.sv 250-266: MaxTrans 2, "
        "every channel spilled), which falls only with both slots holding a request "
        "the demux cannot take, that is with two of that direction already accepted "
        "below it; every target below takes two before refusing (the interface "
        "controller's demux, efuse_interface_controller.sv 310-328, MaxTrans 2, and "
        "an error slave with MAX_TRANS 2, smc_efuse_wrapper.sv 185, "
        "sep_efuse_wrapper.sv 284). A refusal therefore needs four requests of one "
        "direction outstanding, and the bridge issues at most three "
        "(jtag2axi.sv 585, 641-645; jtag_ptap.sv 916-925, 1007-1016).",
        "an OTP bridge that keeps four requests of one direction in flight",
        ("smu",),
        None,
    ),
    (
        "XBAR-CONNECTIVITY",
        re.compile(
            r"^(xbar_mst_req\[2\]\.(aw|ar)|xbar_mst_resp\[2\]\.(b|r)|ext_out_req_o\.(aw|ar)|"
            r"ext_out_resp_i\.(b|r)|smu_axi_out_req_o\.(aw|ar)|smu_axi_out_resp_i\.(b|r))\.id$"
        ),
        "the top bit of the crossbar's output ID, which carries the input port index "
        "(ext_in is port 2). smu_axi_xbar_pkg.sv (127-133) gives ext_in no path to "
        "ext_out, so on ext_out and past it that bit stays 0.",
        "a crossbar connectivity matrix that routes ext_in to ext_out",
        None,
        ((9, 9),),
    ),
    (
        "XBAR-CONNECTIVITY",
        re.compile(
            r"^(xbar_mst_req\[1\]\.(aw|ar)|xbar_mst_resp\[1\]\.(b|r)|smc_in_req_o\.(aw|ar)|"
            r"smc_in_resp_i\.(b|r)|xbar_to_smc_req\.(aw|ar)|xbar_to_smc_resp\.(b|r))\.id$"
        ),
        "the low bit of the input-port index in the crossbar's output ID on the SMC "
        "port. smu_axi_xbar_pkg.sv (127-133) routes sep_out (port 0) and ext_in (port 2) "
        "to smc_in and not smc_out (port 1), so bit 8 stays 0 there.",
        "a crossbar connectivity matrix that routes smc_out to smc_in",
        None,
        ((8, 8),),
    ),
    (
        "BENCH-SEP-OUT-DEPTH",
        re.compile(
            r"^(sep_smn_outbound_axi_resp|gen_sep\.sep_out_xbar_resp|sep_out_resp_o|"
            r"xbar_slv_resp\[0\])\.(aw|w|ar)_ready$"
        ),
        "bench scope: the AW, W and AR ready of the SEP's outbound port. The SEP keeps "
        "at most six requests in flight there: four from the load/store unit's bus "
        "buffer (LSU_NUM_NBLOAD 4 in the sep common_defines.vh 61, el2_lsu_bus_buffer.sv "
        "213), one from the debug module's system bus, whose state machine holds one "
        "request (el2_dbg.sv 144, 631), and one from the DMA's AXI-Lite master "
        "(tlul_to_axi_lite.sv 48-55). Between that port and the bench responder sit "
        "eight slots per channel: the crossbar's slave and master spill registers and "
        "its pipeline stage (smu_axi_xbar_pkg.sv 109-113, CUT_ALL_PORTS, PipelineStages "
        "1) and the bench's axi_cut in front of the responder (tb_wrapper_top.sv "
        "1018-1032), so the port's ready does not fall on this bench.",
        "a deeper SEP issue window, or removal of the bench cut",
        ("smu", "smu_axi_xbar"),
        None,
    ),
    (
        "BENCH-SMC-SHIM-OTP-PACING",
        re.compile(r"^smc_efuse_bank_ctrl_resp(_i)?\.(ar|w)_ready$"),
        "bench scope: the AR and W ready of the SMC eFuse bank-control port. Only the SMC "
        "OTP JTAG2AXI bridge reaches it: the SMC eFuse interface controller sends to the "
        "shim only addresses outside [MAP base, CTRL end] (efuse_interface_controller.sv "
        "284-307), and the SMC peripheral crossbar gives the controller only the MAP and "
        "CTRL windows (smc_periph_axi_lite_xbar.sv 114-122). The bridge launches one "
        "request per JTAG data-register update of at least 32 TCK "
        "(smu_jtag_helpers.py 229-233), and on this bench TCK is 32-48 ns "
        "against a 8-12 ns SMU clock (smu_env_cfg.py 48-61), so requests arrive at least "
        "85 clocks apart, while the shim's register block frees its holding registers "
        "within two clocks of a request (efuse_shim_ctrl_reg.sv 114-150). Neither ready "
        "falls.",
        "a shim initiator that issues requests back to back, or a TCK close to the SMU clock",
        ("smu", "smu_wrapper"),
        None,
    ),
    (
        "BENCH-NO-ECC-INJECTION",
        re.compile(r"^smc_cluster_ded_o$"),
        "bench scope: the SMC cluster's uncorrectable-error output, a registered OR of "
        "the cluster's uncorrectable ECC flags (smc_4core_cpu.sv 191-196). The SMU "
        "bench has no path to corrupt an SMC cluster memory word, so it stays low.",
        "an ECC injection path on this bench, as the SMC bench's tb_cpu_ecc_poke_* "
        "(hw/sys/smc/dv/tb/tb_top.sv 1087-1088)",
        ("smu", "smu_wrapper"),
        None,
    ),
    (
        "TRNG-B-ACCEPT",
        re.compile(r"^ext_trng_axil_req(_o)?\.b_ready$"),
        "BREADY on the external TRNG port, the ready of the B slots of the cut in front "
        "of it (sep_crypto_axi_interconnect.sv 1042-1058), which falls only while both "
        "slots hold a response (spill_register_flushable.sv 90). The port's responder "
        "admits one write at a time: hw/top/sep_ip_integration.sv (761-771) builds it "
        "with prim_axi_lite_err_slv's default MAX_TRANS of 1 (prim_axi_lite_err_slv.sv "
        "21, 88-97), and its axi_err_slv holds the next write's data until the previous "
        "response has been taken (axi_err_slv.sv 48, 86-100), so a second response exists only after "
        "the first entered the cut and a whole write crossed the cut behind it. Above "
        "the cut the AXI-Lite and width converters pass B through (axi_dw_downsizer.sv "
        "742-754), the crypto demux parks it only while another crypto target's response "
        "wins its arbiter, into a spilled slave port (sep_crypto_axi_interconnect.sv "
        "268-295, SpillB 1), and every SEP initiator takes write responses as they "
        "arrive (el2_lsu_bus_buffer.sv 906, el2_dbg.sv 772, tlul_to_axi_lite.sv 245).",
        "a TRNG responder that admits more than one write, or an initiator of the TRNG "
        "window that holds write responses back",
        None,
        None,
    ),
    (
        "BENCH-SMC-EXTERNAL-DEPTH",
        re.compile(r"^smc_external_resp(_i)?\.aw_ready$"),
        "bench scope: AWREADY of the SMC external window, the AW spill-register ready of "
        "the window demux in the adopter IP integration (hw/top/smc_ip_integration.sv "
        "214-240: MaxTrans 1, SpillAw 1), which falls only with two write requests "
        "queued behind the one the demux is serving (spill_register_flushable.sv 90; "
        "axi_lite_demux.sv 250-285, 308-327: a request waits for the previous one's "
        "data, and that data for the previous response). The window's responders, the "
        "PLL and PVT models, the straps register block and the error slave, take each "
        "request as it comes, so the queue forms only behind a held response. The one "
        "initiator on this bench that keeps writes in flight toward the window is "
        "ext_in, and with its responses held (smu_smc_inbound_window_sweep_test S4) the "
        "SMC local crossbar admits eight writes to its peripheral port "
        "(smc_local_xbar_pkg.sv 285-288), whose own cut and the peripheral crossbar's "
        "two port cuts (smc_periph_axi_lite_xbar_pkg.sv 100-103) hold six of their "
        "responses, leaving two writes at the window: one response waiting and one "
        "request waiting for its data slot.",
        "an adopter responder in the window that holds a request or a response, or an "
        "initiator that reaches the window with more writes in flight than the SMC "
        "local crossbar admits",
        ("smu", "smu_wrapper"),
        None,
    ),
    (
        "KM-RESET-OVERRIDE-X",
        re.compile(r"^jtag_sep_reset_ctrl\.ovrd\.km_jtag_rst_n_ovrd$"),
        "the Key Manager port's override in the IC_RESET SEP slice. "
        "smu_jtag_reset_override_test applies every other SEP port's override. Applying "
        "and lifting this one leaves the Key Manager's ROM request "
        "(hw/top/sep_ip_integration.sv 273, u_km_rom.req_i) X on a four-state simulator "
        "from the release on, and prim_rom's noXOnCsI assertion (prim_rom.sv 40), which "
        "the bench re-arms once the SMC primary reset has released "
        "(tb_wrapper_top.sv 498-506), fails the run. The X is a design question about "
        "the Key Manager's reset through the SEP reset controller (sep_reset_ctrl.sv "
        "280-297), not a limit of the bench.",
        "a Key Manager whose ROM request is defined after a JTAG override reset, when the "
        "leaf applies the port like every other SEP port",
        ("smu",),
        None,
    ),
    (
        "APERTURE-ALIGNMENT",
        re.compile(
            r"^(addr_map\[1\]\.(start|end)_addr|smc_end|smc_global_base_addr_i|smc_global_base_o)$"
        ),
        "SMC aperture bits no programmable setting reaches. smc_base_config.rdl (38) "
        "requires GLOBAL_BASE and LOCAL_BASE to be aligned to REGION_SIZE; JTAG2AXI "
        "reaches BASE_CONFIG through the local window, so no size below 128 KiB can be "
        "followed by another setting and base and end bits [16:0] stay 0; LOCAL_BASE is "
        "fixed at 0xC000_0000, so REGION_SIZE[31] is never legal.",
        "a programmable LOCAL_BASE or a BASE_CONFIG path outside the local window",
        None,
        ((0, 16),),
    ),
    (
        "APERTURE-ALIGNMENT",
        re.compile(r"^(smc_region_size_i|smc_region_size_o)$"),
        "SMC aperture bits no programmable setting reaches. smc_base_config.rdl (38) "
        "requires GLOBAL_BASE and LOCAL_BASE to be aligned to REGION_SIZE; JTAG2AXI "
        "reaches BASE_CONFIG through the local window, so no size below 128 KiB can be "
        "followed by another setting and base and end bits [16:0] stay 0; LOCAL_BASE is "
        "fixed at 0xC000_0000, so REGION_SIZE[31] is never legal.",
        "a programmable LOCAL_BASE or a BASE_CONFIG path outside the local window",
        None,
        ((0, 16), (31, 31)),
    ),
    (
        "REGISTER-WIDTH",
        re.compile(r"^sep_region_size_o$"),
        "SEP region-size bits above the register field. sep_cpu_ctrl SEP_REGION_SIZE "
        "carries its size in bits [31:0] and reserves [63:32] (the generated register "
        "description), so the 56-bit port is that field zero-extended and bits [55:32] "
        "cannot move; smu.sv hands the crossbar only [31:0].",
        "SEP_REGION_SIZE.size widening past bit 31",
        ("smu",),
        ((32, 55),),
    ),
]

TOGGLE_RE = re.compile(r'^// Toggle (\S+) "(.*)"$')
OTHER = "other bits of "
RANGES = re.compile(r"((?:\[[^\]]*\])+)$")


def template_sections(path: Path) -> dict[str, tuple[str, list[tuple[str, str]]]]:
    """Return {module: (checksum line, [(field, signature)])} for MODULES."""
    out: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    checksum = ""
    module = None
    for line in path.read_text().splitlines():
        if line.startswith("// CHECKSUM: "):
            checksum = line[3:]
        elif line.startswith("// MODULE: "):
            name = line[len("// MODULE: ") :].strip()
            module = name if name in MODULES else None
            if module:
                out[module] = (checksum, [])
        elif module:
            m = TOGGLE_RE.match(line)
            if m:
                out[module][1].append((m.group(1), m.group(2)))
    missing = [m for m in MODULES if m not in out]
    if missing:
        sys.exit(f"{path}: no template section for {', '.join(missing)}")
    return out


def report_rows(path: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Return {module: [(row name, 1->0, 0->1)]} from the raw report's toggle details."""
    text = "\n" + path.read_text()
    out: dict[str, list[tuple[str, str, str]]] = {}
    for sec in re.split(r"\n=+\nModule : ", text)[1:]:
        name = sec.split("\n", 1)[0].strip()
        if name not in MODULES or "Toggle Coverage for Module" not in sec:
            continue
        body = sec.split("Toggle Coverage for Module", 1)[1].split("\n-----", 1)[0]
        rows = out.setdefault(name, [])
        for line in body.splitlines():
            p = line.split()
            if len(p) >= 4 and p[1] in ("Yes", "No"):
                rows.append((p[0], p[2], p[3]))
            elif p[:3] == ["Other", "bits", "of"] and len(p) >= 7:
                # The bits of the field no row above lists, all with this status.
                rows.append((OTHER + p[3], p[5], p[6]))
    return out


def wrapper_excluded() -> set[str]:
    return {
        line.split()[1]
        for line in WRAPPER_FILE.read_text().splitlines()
        if line.startswith("Toggle ")
    }


def _span(rng: str, sig: str) -> tuple[int, int] | None:
    """(lo, hi) bits of a one-dimensional row, or of the whole field when rng is empty."""
    m = re.fullmatch(r"\[(\d+)(?::(\d+))?\]", rng)
    if m:
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        return min(a, b), max(a, b)
    if rng:
        return None
    m = re.search(r"\[(\d+):(\d+)\]\"?$", sig.strip('"'))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return min(a, b), max(a, b)
    return 0, 0


def _clip(span: tuple[int, int], bits) -> list[tuple[int, int, str | None]]:
    """The parts of ``span`` inside the windows, each with its window's direction."""
    if bits is None:
        return [(span[0], span[1], None)]
    out = []
    for window in bits:
        lo, hi = window[0], window[1]
        direction = window[2] if len(window) > 2 else None
        a, b = max(lo, span[0]), min(hi, span[1])
        if a <= b:
            out.append((a, b, direction))
    return out


def _dims(rng: str) -> list[tuple[int, int]]:
    return [
        (min(int(a), int(b or a)), max(int(a), int(b or a)))
        for a, b in re.findall(r"\[(\d+)(?::(\d+))?\]", rng)
    ]


def _other_entries(field: str, sig: str, rows: list[tuple[str, str, str]]) -> list[str]:
    """Index-by-index lines for the bits an "Other bits of" row covers.

    Those are the bits of the field's declared ranges that no listed row names.
    """
    out = []
    for name, t10, t01 in rows:
        if not name.startswith(OTHER) or (t10, t01) == ("Yes", "Yes"):
            continue
        dims = _dims(name[len(OTHER) + len(field) :])
        listed: set[tuple[int, ...]] = set()
        for row, _, _ in rows:
            if row.startswith(OTHER):
                continue
            rdims = _dims(row[len(field) :])
            if len(rdims) != len(dims):
                continue
            grid = [range(lo, hi + 1) for lo, hi in rdims]
            listed |= {tuple(ix) for ix in _product(grid)}
        direction = "" if (t10, t01) == ("No", "No") else ("0to1 " if t01 == "No" else "1to0 ")
        outer = [range(lo, hi + 1) for lo, hi in dims[:-1]]
        lo, hi = dims[-1]
        for head in _product(outer):
            run: list[int] = []
            for bit in list(range(lo, hi + 2)):
                if bit <= hi and (*head, bit) not in listed:
                    run.append(bit)
                    continue
                if run:
                    idx = "".join(f"[{i}]" for i in head)
                    sel = f"[{run[-1]}:{run[0]}]" if len(run) > 1 else f"[{run[0]}]"
                    out.append(f'Toggle {direction}{field} {idx}{sel} "{sig}"')
                    run = []
    return out


def _product(ranges):
    result: list[tuple[int, ...]] = [()]
    for r in ranges:
        result = [(*prefix, i) for prefix in result for i in r]
    return result


def entries(field: str, sig: str, rows: list[tuple[str, str, str]], bits=None) -> list[str]:
    """Exclusion lines for the uncovered part of one field, inside ``bits`` if given."""
    others = [r for r in rows if r[0].startswith(OTHER)]
    if others:
        listed = [r for r in rows if not r[0].startswith(OTHER)]
        return (entries(field, sig, listed, bits) if listed else []) + (
            _other_entries(field, sig, rows) if bits is None else []
        )
    if not rows or all(r[1] == "Yes" and r[2] == "Yes" for r in rows):
        return []
    if bits is None and all(r[1] == "No" and r[2] == "No" for r in rows):
        return [f'Toggle {field} "{sig}"']
    out = []
    for name, t10, t01 in rows:
        if t10 == "Yes" and t01 == "Yes":
            continue
        rng = name[len(field) :]
        if rng.count("[") > 1 and bits is not None:
            continue
        if bits is None:
            sels = [f" {rng}" if rng else ""]
        else:
            span = _span(rng, sig)
            if span is None:
                continue
            whole = not rng and span == (0, 0) and "[" not in sig
            sels = [
                ("" if whole else (f" [{hi}:{lo}]" if hi != lo else f" [{lo}]"), only)
                for lo, hi, only in _clip(span, bits)
            ]
        missing = {d for d, t in (("1to0", t10), ("0to1", t01)) if t == "No"}
        for sel, only in [(x, None) if isinstance(x, str) else x for x in sels]:
            if only is not None:
                if only in missing:
                    out.append(f'Toggle {only} {field}{sel} "{sig}"')
            elif len(missing) == 2:
                out.append(f'Toggle {field}{sel} "{sig}"')
            else:
                out.append(f'Toggle {next(iter(missing))} {field}{sel} "{sig}"')
    return out


# Condition rows and branch arms, by class: (class, module, source lines or None).
# The fact and the retiring condition are the toggle class's of the same name.
SMU_SV = HERE.parents[3] / "rtl" / "smu.sv"


def _lines_assigning(path: Path, target: str) -> frozenset[int]:
    """Source lines of ``path`` whose continuous assignment drives ``target``."""
    pattern = re.compile(rf"^\s*assign\s+{re.escape(target)}\s*=")
    lines = frozenset(
        n for n, text in enumerate(path.read_text().splitlines(), 1) if pattern.match(text)
    )
    if not lines:
        sys.exit(f"{path}: no assignment to {target}")
    return lines


POINT_CLASSES: list[tuple[str, str, frozenset[int] | None]] = [
    ("LC-SIGINT-ENCODED", "smu", _lines_assigning(SMU_SV, "lc_sigint_err_o")),
]
POINT_RE = re.compile(r"^// (Condition|Branch) ")
LINE_RE = re.compile(r"LineNumber: (\d+)")


def _point_template(path: Path) -> dict[str, tuple[str, list[tuple[int, str]]]]:
    """{module: (checksum line, [(source line, point line)])} for one metric template."""
    out: dict[str, tuple[str, list[tuple[int, str]]]] = {}
    checksum, module, line_no = "", None, 0
    for line in path.read_text().splitlines():
        if line.startswith("// CHECKSUM: "):
            checksum = line[3:]
        elif line.startswith("// MODULE: "):
            module = line[len("// MODULE: ") :].strip()
            out[module] = (checksum, [])
        elif module and (m := LINE_RE.search(line)):
            line_no = int(m.group(1))
        elif module and POINT_RE.match(line):
            out[module][1].append((line_no, line[3:]))
    return out


def _module_section(modinfo: str, module: str, metric: str) -> str:
    for sec in re.split(r"\n=+\nModule : ", "\n" + modinfo)[1:]:
        if sec.split("\n", 1)[0].strip() == module and f"{metric} Coverage for Module" in sec:
            body = sec.split(f"{metric} Coverage for Module", 1)[1]
            return body.split("\n-------", 1)[0]
    return ""


def uncovered_conditions(modinfo: str, module: str) -> set[tuple[int, str]]:
    """(source line, row values) the raw report marks Not Covered."""
    out, line_no = set(), 0
    for line in _module_section(modinfo, module, "Cond").splitlines():
        if m := re.match(r"\s*LINE\s+(\d+)", line):
            line_no = int(m.group(1))
        elif m := re.match(r"^\s*([01](?:\s+[01])*)\s+Not Covered", line):
            out.add((line_no, "".join(m.group(1).split())))
    return out


def uncovered_branches(modinfo: str, module: str) -> set[tuple[int, str]]:
    """(source line, arm value) the raw report marks Not Covered."""
    out, line_no = set(), 0
    for line in _module_section(modinfo, module, "Branch").splitlines():
        if m := re.match(r"^(\d+)\s+\S", line):
            line_no = int(m.group(1))
        elif m := re.match(r"^([01])\s+Not Covered", line):
            out.add((line_no, m.group(1)))
    return out


def point_blocks(cond: Path | None, branch: Path | None, modinfo: Path, counts) -> list[str]:
    text = modinfo.read_text()
    facts = {name: (fact, retire) for name, _, fact, retire, _, _ in CLASSES}
    out: list[str] = []
    for path, kind in ((cond, "Condition"), (branch, "Branch")):
        if path is None:
            continue
        template = _point_template(path)
        for cls, module, lines in POINT_CLASSES:
            if module not in template:
                continue
            checksum, points = template[module]
            holes = (
                uncovered_conditions(text, module)
                if kind == "Condition"
                else uncovered_branches(text, module)
            )
            picked = []
            for line_no, point in points:
                if lines is not None and line_no not in lines:
                    continue
                if kind == "Condition":
                    m = re.search(r'\(\d+ "([01]+)"\)$', point)
                    key = m.group(1) if m else None
                else:
                    m = re.search(r'\(\d+\) "\S+ ([01])"$', point)
                    key = m.group(1) if m else None
                if key is not None and (line_no, key) in holes:
                    picked.append(point)
            if picked:
                fact, retire = facts[cls]
                counts[cls] += len(picked)
                out += ["", checksum, f"MODULE: {module}", ""]
                out.append(f'ANNOTATION: "SMU-{kind.upper()}-{cls}: {fact} Retired by {retire}."')
                out += picked
    return out


def render(
    template: Path, modinfo: Path, cond: Path | None = None, branch: Path | None = None
) -> tuple[str, dict[str, int]]:
    sections = template_sections(template)
    reports = report_rows(modinfo)
    skip = {"smu_wrapper": wrapper_excluded()}
    counts: dict[str, int] = {c[0]: 0 for c in CLASSES}
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMU VCS exclusions, applied with -elfile at report time.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smu_cov_toggle_exclusions.py from urg's",
        "// `-dump full_exclusions tgl+cond+branch` templates of the merged database",
        "// and the raw report; regenerate rather than edit. README.md beside this",
        "// file states each class's fact; the ANNOTATION before each class repeats it.",
        "//==================================================",
    ]
    for module in MODULES:
        checksum, fields = sections[module]
        rows = reports.get(module, [])
        by_field: dict[str, list[tuple[str, str, str]]] = {f: [] for f, _ in fields}
        for row in rows:
            name = row[0].removeprefix(OTHER)
            while name not in by_field:
                m = RANGES.search(name)
                if not m:
                    break
                name = name[: m.start()]
            if name in by_field:
                by_field[name].append(row)
        applicable = [c for c in CLASSES if c[4] is None or module in c[4]]
        claimed: dict[str, tuple] = {}
        for field, _ in fields:
            if field in skip.get(module, set()):
                continue
            for c in applicable:
                if c[1].search(field):
                    claimed[field] = c
                    break
        block: list[str] = []
        emitted: set[tuple[str, str]] = set()
        for c in applicable:
            cls, _, fact, retire, _, bits = c
            lines: list[str] = []
            for field, sig in fields:
                if claimed.get(field) is c:
                    lines += entries(field, sig, by_field[field], bits)
            if lines:
                counts[cls] += len(lines)
                if (cls, fact) not in emitted:
                    block += ["", f'ANNOTATION: "SMU-TGL-{cls}: {fact} Retired by {retire}."']
                    emitted.add((cls, fact))
                block += lines
        if block:
            out += ["", checksum, f"MODULE: {module}", *block]
    out += point_blocks(cond, branch, modinfo, counts)
    return "\n".join(out) + "\n", counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template", type=Path, help="urg fullexclude_module.tgl")
    ap.add_argument("modinfo", type=Path, help="the run's cov/report_raw/modinfo.txt")
    ap.add_argument("--cond", type=Path, help="urg fullexclude_module.cond")
    ap.add_argument("--branch", type=Path, help="urg fullexclude_module.branch")
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args()
    text, counts = render(args.template, args.modinfo, args.cond, args.branch)
    if args.check:
        if OUTPUT.read_text() != text:
            print(f"{OUTPUT} is stale; rerun without --check", file=sys.stderr)
            return 1
        print(f"{OUTPUT} is current")
        return 0
    OUTPUT.write_text(text)
    print(f"wrote {OUTPUT}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
