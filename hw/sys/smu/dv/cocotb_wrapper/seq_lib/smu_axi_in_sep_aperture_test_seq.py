# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound SMN traffic into the SEP aperture, on the SEP=1 wrapper.

S0..S3 are ``smu_dtp_sep_dm_dmi_test``: the TEST_DEV posture leaves SEP debug
open and the SEP debug module answers on its system bus. With SEP-scope debug
enabled the SEP inbound filter admits all inbound traffic
(``hw/sys/sep/doc/fabric.adoc``, "Traffic Filter Decode").

S4: the system bus programs the SEP aperture to SEP_REGION_SIZE 0x1100_0000 at
    SEP_GLOBAL_BASE_ADDR 0x0400_0000: non-empty, clear of the SMC window at its
    reset values, and covering SEP-local 0x0 .. 0x10FF_FFFF, since the SEP
    inbound path subtracts the base (``fabric.adoc``, "Address Remapping").
S5: ext_in round trips into SEP SRAM (local 0x1000_0000, 256 KiB,
    ``sep_addr.h``) through the crossbar's SEP port: write-then-read under
    AxID 0x00, 0xFF, 0x55 and 0xAA, under AxCACHE, AxQOS and AxREGION at 0x0
    and 0xF, AxLOCK 0 and 1 and all eight AxPROT encodings, and reads at every
    legal AxSIZE and at the eight byte offsets of a word. Each is OKAY and
    reads back what was written, the narrow reads the bytes of the last word.
S6: INCR bursts of AxLEN 0x00, 0x55, 0xAA and 0xFF write a byte pattern into
    SRAM and read it back OKAY, and the longest reads and writes back OKAY
    again while the master holds RREADY and BREADY back. WRAP and FIXED bursts
    are not sent to SEP SRAM: no specification states how the SEP fabric or
    the SRAM port answers them, and the SRAM port asserts against them.
S7: a write to the entropy pool drain aperture terminates SLVERR
    (``fabric.adoc``: "Writes to it terminate with BRESP=SLVERR"), and a read and
    a write of SEP-local 0x0, which no component owns, are not OKAY.
S8: every aperture address bit reaches the crossbar's SEP port on both
    channels: with the window at [4 GiB, 8 GiB) a byte is read and written back
    unchanged at 4 GiB + 2^k for each k below 32 and at 4 GiB itself, and with
    the window at the single byte 2^56 - 1 the same there, each completing
    with a response; the aperture then returns to its RDL reset values, and a
    byte at the reset base completes with a response. The aperture ports
    settle at each programmed window. SEP-local 0x1000_0000, the SEP SRAM
    base, returns the first S6 pattern byte OKAY, and SEP-local 0x2000_0000,
    the eFuse SHIM control word, reads and writes OKAY; the other responses
    are recorded.

S9 (before S8): with the aperture grown to cover SEP-local 0x2000_0000, inbound
    traffic reaches the SEP external aperture and the external TRNG window.
    Offset 0x100 of the external aperture lies between the eFuse SHIM control
    block at its base and the execute-in-place window
    (``hw/sys/sep/dv/models/regs/sep_external.rdl``), and the fabric refuses
    an address between unit windows (``hw/sys/sep/doc/memory_map.adoc``),
    which names no response code, so there the check is that it is not OKAY.
    No external TRNG is connected, and the integrator guide terminates
    ``ext_trng_axil`` with a DECERR slave then (``doc/integrator/src/smu.adoc``,
    "External TRNG"), and the crypto demux answers a burst there with DECERR
    on every beat (``hw/sys/sep/doc/crypto.adoc``, "Single-Beat Access
    Only"), so every beat of every TRNG-window read is DECERR.
    A passive tap on the ext_in pins records every AR and every R beat
    (RID, RRESP, RLAST) and pairs each beat with its AR, so reads are graded
    beat by beat: each AR draws AxLEN + 1 beats closed by RLAST, and the
    tapped reads at each target are exactly the reads offered there.
    Every AxID, AxCACHE/AxQOS/AxREGION/AxLOCK corner, AxPROT encoding, AxSIZE
    and burst type ext_in offers at the external aperture, and each read of an
    eight-read train under distinct IDs held in flight, completes with an
    error response, on every R beat of a read, as do sixty-four reads
    (alternately single and eight-beat bursts) and sixty-four writes over four
    IDs launched together and held in flight there, and four writes launched
    together whose W trails the first AW by 64 cycles. At the TRNG window
    every AxPROT and AxSIZE read, and each of sixty-four held reads launched
    with sixty-four held writes, is DECERR on every beat. The TRNG-window writes (each AxPROT and AxSIZE,
    the sixty-four held with those reads, sixty-four held alone and four
    W-lagged) are recorded by response code and not graded (``SMU_FCOV.adoc``,
    Phase 2, states why). The eFuse shim word at the base of the external
    aperture reads and writes back OKAY under every AxPROT, under
    sixty-four reads and sixty-four writes over four IDs launched together and
    held in flight, and in a sweep of a W-lagged write against a read whose AR
    is delayed around the same lag. With the aperture restored a system-bus
    read and write of the external aperture
    each report a bus error.
S10: sixteen reads and sixteen writes, each under its own ID, are launched into SEP
    SRAM before the first response is taken, with RREADY and BREADY held back;
    every read returns the word written under its ID and every write is OKAY.
S11: the SEP debug module's system bus opens SMC inbound filter entry 0, and
    ext_in reads the SMC's VERSION_LO at its global address. The system bus
    then programs the SMC iDMA through the SEP view of the SMC window, with SMC
    outbound filter entry 0 passing all, to
    copy a block from SEP SRAM, through the crossbar's SMC-to-SEP route, to an
    address outside both apertures, which the crossbar sends to ``ext_out``.
    The destination in the bench responder holds the block ext_in wrote. A
    second copy brings the block back from ``ext_out`` into SEP SRAM over the
    same route, where ext_in reads it, and a system-bus write and read then
    leave on ``ext_out`` from the SEP, where the responder holds the word.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge, with_timeout
from ocah_axi_vip import (
    RESP_DECERR,
    RESP_OKAY,
    RESP_SLVERR,
    AxiTimingProfile,
    resp_name,
    worst_resp,
)

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    c_header_u32,
    smc_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_axi_out_addr_len_size_test_seq import DMA_CONFIG_ENABLE_ND
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    DMI_OP_WRITE,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_32,
    SBCS_SBBUSY,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SEP_BASE_ONES,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
    SEP_SIZE_ONES,
    smu_dtp_sep_dm_sba_test_seq,
)
from seq_lib.smu_filter_helpers import PASS_ALL_END, PASS_RW_CONFIG
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"
SRAM_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_SRAM_BASE_ADDR")
SRAM_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_SRAM_SIZE")
ENTROPY_POOL_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_ENTROPY_POOL_BASE_ADDR")
SEP_EXTERNAL_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_BASE_ADDR")
TRNG_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_TRNG_BASE_ADDR")
TRNG_WINDOW = c_header_u32(_SEP_ADDR_H, "SEP_TOP_TRNG_SIZE")
EFUSE_SHIM_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR")
SMC_LOCAL_BASE = smc_base_config_u32("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
DMA_REGS = {
    name: smc_addr(f"SMC_TOP_DMA_CTRL_{name}_BASE_ADDR")
    for name in (
        "CONFIG",
        "DST_ADDRESS_LO",
        "DST_ADDRESS_HI",
        "SRC_ADDRESS_LO",
        "SRC_ADDRESS_HI",
        "LENGTH_LO",
        "LENGTH_HI",
        "DST_STRIDE_LO",
        "DST_STRIDE_HI",
        "SRC_STRIDE_LO",
        "SRC_STRIDE_HI",
        "NUM_REPETITIONS_LO",
        "NUM_REPETITIONS_HI",
        "NEXT_ID_0",
        "DONE_0",
    )
}
DMA_LENGTH = 0x100
DMA_DST = 0x0200_0000
DMA_BACK_OFFSET = 0x800
# A SEP address in the SMU aperture at its sep_cpu_ctrl reset value, which the
# SEP sends out on the SMN (``hw/sys/sep/doc/fabric.adoc``).
SEP_EGRESS = (
    c_header_u32(
        _SEP_ADDR_H.parent / "blocks" / "sep_cpu_ctrl.h",
        "SEP_CPU_CTRL__SMU_GLOBAL_BASE_ADDR__ADDR_reset",
    )
    + 0x1000_6000
)
DMA_POLLS = 64

WIN_BASE = 0x0400_0000
WIN_SIZE = 0x1100_0000
UNOWNED_LOCAL = 0x0
FOUR_GIB = SEP_SIZE_ONES + 1
AXI_BURST_FIXED = 0
AXI_BURST_INCR = 1
AXI_BURST_WRAP = 2
IDS = (0x00, 0xFF, 0x55, 0xAA)
QUALIFIERS = (
    {"cache": 0x0, "qos": 0x0, "region": 0x0, "lock": 0},
    {"cache": 0xF, "qos": 0xF, "region": 0xF, "lock": 1},
)
BURST_LENS = (0x00, 0x55, 0xAA, 0xFF)
# Cycles the master holds RREADY and BREADY low before each response beat.
RESP_BACKPRESSURE_CYCLES = 4
# First byte of the S6 pattern written under response backpressure.
STALL_PATTERN_BASE = 0x77
# SEP-local 0x2000_0000 and the TRNG window are inside this window, which
# still ends below the SMC window at its reset base.
WIN_EXT_SIZE = 0x2100_0000
TRAIN = 16
# Cycles the master holds RREADY and BREADY low once a train is launched, long
# enough for the queued responses to fill every buffer back to the SEP port.
TRAIN_HOLD_CYCLES = 600
HELD = 64
# RREADY and BREADY stay low this long after each train starts
# (the VIP's pause countdown), then every response is taken.
HELD_HOLD_CYCLES = 20000
HELD_WAIT_NS = 4 * AXI_TIMEOUT_NS
# A bench choice: every held access has to complete whatever the number of
# AXI IDs in flight, and four IDs keep sixteen accesses on each.
HELD_IDS = 4
# Bit positions of the valid, ready and address fields of the SEP inbound port
# (`smu` net sep_smn_inbound_axi_req/resp): the pulp AXI4 request and response
# structs (vendor/pulp-platform/axi include/axi/typedef.svh) with a 56-bit
# address, 64-bit data, 6-bit ID and 12-bit user; the tap refuses to run on any
# other width.
SEP_IN_REQ_BITS = 302
SEP_IN_RESP_BITS = 110
SEP_IN_AW_VALID = 192
SEP_IN_AW_ADDR = 240
SEP_IN_AR_VALID = 1
SEP_IN_AR_ADDR = 43
SEP_IN_AW_READY = 109
SEP_IN_AR_READY = 108
SEP_IN_ADDR_BITS = 56
W_LAG_CYCLES = 64
W_LAG_WRITES = 4
COLLIDE_SPAN = 24


def _read_beats(addr: int, nbytes: int, size: int) -> int:
    """Beats of a read of ``nbytes`` from ``addr`` at AxSIZE ``size`` (AMBA AXI, A3.4)."""
    lane = 1 << size
    return (nbytes + addr % lane + lane - 1) // lane


def _split_bursts(
    ars: list[tuple[int, int, int]], beats: list[tuple[int, int, int]]
) -> tuple[list[tuple[int, tuple[int, ...]]], list[str]]:
    """Pair R beats with the AR each belongs to.

    ``ars`` holds (arid, araddr, arlen) and ``beats`` (rid, rresp, rlast), each
    in handshake order. Beats under one ID return in the order of that ID's
    ARs (AMBA AXI, A5.3). Returns (araddr, per-beat RRESP) for every AR, and
    every departure from AxLEN + 1 beats closed by RLAST on the last one.
    """
    queues: dict[int, list[tuple[int, int]]] = {}
    for arid, araddr, arlen in ars:
        queues.setdefault(arid, []).append((araddr, arlen + 1))
    by_id: dict[int, list[tuple[int, int]]] = {}
    for rid, rresp, rlast in beats:
        by_id.setdefault(rid, []).append((rresp, rlast))
    bursts: list[tuple[int, tuple[int, ...]]] = []
    errors: list[str] = []
    for rid in sorted(set(queues) | set(by_id)):
        stream = by_id.get(rid, [])
        pos = 0
        for araddr, want in queues.get(rid, []):
            got = stream[pos : pos + want]
            pos += len(got)
            lasts = [last for _, last in got]
            if len(got) != want or lasts != [0] * (want - 1) + [1]:
                errors.append(f"id 0x{rid:x} addr 0x{araddr:x}: {want} beats wanted, rlast {lasts}")
            bursts.append((araddr, tuple(code for code, _ in got)))
        if pos != len(stream):
            errors.append(f"id 0x{rid:x}: {len(stream) - pos} R beats with no AR")
    return bursts, errors


class smu_axi_in_sep_aperture_test_seq(smu_dtp_sep_dm_sba_test_seq):
    """Inbound SMN traffic across the SEP aperture, programmed over the SEP debug bus."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps: dict[str, bool] = {}

    def _global(self, local: int) -> int:
        return WIN_BASE + local

    async def _ax(self, master, *, write: bool, addr: int, payload, label: str, **attrs):
        if write:
            event = master.init_write(addr, payload, **attrs)
        else:
            event = master.init_read(addr, payload, **attrs)
        try:
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(f"TIMEOUT {label} addr=0x{addr:x} attrs={attrs}: {exc}") from exc
        raw = event.data
        resp = worst_resp(getattr(raw, "resp", None))
        data = bytes(getattr(raw, "data", b""))
        rid = getattr(raw, "id", None)
        return resp, data, rid

    async def _window(self, jtag, base: int, size: int) -> None:
        # Size first when it shrinks, base first when it grows, so no
        # intermediate window reaches the SMC window.
        order = (
            ((SEP_REGION_SIZE_ADDR, size), (SEP_GLOBAL_BASE_ADDR, base))
            if size <= sample(self.dut.sep_region_size_o, "sep_region_size_o")
            else ((SEP_GLOBAL_BASE_ADDR, base), (SEP_REGION_SIZE_ADDR, size))
        )
        for addr, value in order:
            await self._sba_write64(jtag, addr, value)
        settled = (
            await self._port_settles("sep_global_base_o", base),
            await self._port_settles("sep_region_size_o", size),
        )
        if settled != (base, size):
            raise AssertionError(
                f"SEP aperture ports settled at 0x{settled[0]:x}/0x{settled[1]:x}, "
                f"programmed 0x{base:x}/0x{size:x}"
            )

    async def _round_trips(self, master, sb) -> None:
        bad = []
        addr = self._global(SRAM_LOCAL)
        cells = [{"id": i} for i in IDS]
        cells += [dict(q) for q in QUALIFIERS]
        cells += [{"prot": p} for p in range(8)]
        for n, attrs in enumerate(cells):
            word = (0x5A5A_0000_5A00_0000 | n).to_bytes(8, "little")
            resp_w, _, _ = await self._ax(
                master, write=True, addr=addr, payload=word, label=f"rt_wr{n}", **attrs
            )
            resp_r, data, _ = await self._ax(
                master, write=False, addr=addr, payload=8, label=f"rt_rd{n}", **attrs
            )
            if resp_w != RESP_OKAY or resp_r != RESP_OKAY or data[:8] != word:
                bad.append((attrs, resp_w, resp_r, data[:8].hex()))
        # The last cell's word is what the narrow reads below return.
        for size in range(4):
            resp, data, _ = await self._ax(
                master, write=False, addr=addr, payload=1 << size, size=size, label=f"sz{size}"
            )
            if resp != RESP_OKAY or data[: 1 << size] != word[: 1 << size]:
                bad.append(({"size": size}, resp, data[: 1 << size].hex()))
        for offset in range(8):
            resp, data, _ = await self._ax(
                master, write=False, addr=addr + offset, payload=1, size=0, label=f"off{offset}"
            )
            if resp != RESP_OKAY or data[:1] != word[offset : offset + 1]:
                bad.append(({"offset": offset}, resp, data[:1].hex()))
        self._log(f"CHK-AXIIN-SEP-ROUND-TRIP cells={len(cells) + 12} mismatches={bad}")
        sb.expect_eq("CHK-AXIIN-SEP-ROUND-TRIP", bad, [], evidence="CHK-AXIIN-SEP-ROUND-TRIP")
        self.steps["S5"] = True

    async def _bursts(self, master, sb) -> None:
        bad = []
        base = self._global(SRAM_LOCAL)
        for length in BURST_LENS:
            beats = length + 1
            pattern = bytes((length + i) & 0xFF for i in range(beats * 8))
            resp_w, _, _ = await self._ax(
                master, write=True, addr=base, payload=pattern, size=3, label=f"incr_wr{length}"
            )
            resp_r, data, _ = await self._ax(
                master, write=False, addr=base, payload=beats * 8, size=3, label=f"incr_rd{length}"
            )
            if resp_w != RESP_OKAY or resp_r != RESP_OKAY or data != pattern:
                bad.append(("INCR", length, resp_w, resp_r))
        length = BURST_LENS[-1]
        pattern = bytes((STALL_PATTERN_BASE + i) & 0xFF for i in range((length + 1) * 8))
        master.driver.set_timing(
            AxiTimingProfile(
                r_ready_delay=RESP_BACKPRESSURE_CYCLES, b_ready_delay=RESP_BACKPRESSURE_CYCLES
            )
        )
        try:
            resp_w, _, _ = await self._ax(
                master, write=True, addr=base, payload=pattern, size=3, label="stall_wr"
            )
            resp_r, data, _ = await self._ax(
                master, write=False, addr=base, payload=len(pattern), size=3, label="stall_rd"
            )
        finally:
            master.driver.set_timing(AxiTimingProfile())
        if resp_w != RESP_OKAY or resp_r != RESP_OKAY or data != pattern:
            bad.append(("INCR under RREADY/BREADY backpressure", resp_w, resp_r))
        self._log(f"CHK-AXIIN-SEP-BURST mismatches={bad}")
        sb.expect_eq("CHK-AXIIN-SEP-BURST", bad, [], evidence="CHK-AXIIN-SEP-BURST")
        self.steps["S6"] = True

    async def _errors(self, master, sb) -> None:
        pool_w, _, _ = await self._ax(
            master,
            write=True,
            addr=self._global(ENTROPY_POOL_LOCAL),
            payload=bytes(8),
            size=3,
            label="pool_wr",
        )
        unowned_r, _, _ = await self._ax(
            master,
            write=False,
            addr=self._global(UNOWNED_LOCAL),
            payload=8,
            size=3,
            label="unowned_rd",
        )
        unowned_w, _, _ = await self._ax(
            master,
            write=True,
            addr=self._global(UNOWNED_LOCAL),
            payload=bytes(8),
            size=3,
            label="unowned_wr",
        )
        self._log(
            f"CHK-AXIIN-SEP-ERRORS entropy pool write resp={pool_w} "
            f"unowned read resp={unowned_r} unowned write resp={unowned_w}"
        )
        sb.expect_eq(
            "CHK-AXIIN-SEP-ERRORS",
            (pool_w, unowned_r != RESP_OKAY, unowned_w != RESP_OKAY),
            (RESP_SLVERR, True, True),
            evidence="CHK-AXIIN-SEP-ERRORS",
        )
        self.steps["S7"] = True

    async def _touch(self, master, addr: int) -> tuple[int, bytes, int]:
        """Read one byte, then write the same byte back; return both responses and the byte."""
        resp_r, data, _ = await self._ax(
            master, write=False, addr=addr, payload=1, size=0, label=f"rd@{addr:x}"
        )
        resp_w, _, _ = await self._ax(
            master,
            write=True,
            addr=addr,
            payload=data[:1] or bytes(1),
            size=0,
            label=f"wr@{addr:x}",
        )
        return resp_r, data[:1], resp_w

    async def _sep_port_tap(self, seen: dict[str, set[int]]) -> None:
        """Record every AW and AR address handshaken on the SEP inbound port."""
        smu = smu_scope(self.dut)
        req = hier(smu, "sep_smn_inbound_axi_req")
        resp = hier(smu, "sep_smn_inbound_axi_resp")
        if (len(req), len(resp)) != (SEP_IN_REQ_BITS, SEP_IN_RESP_BITS):
            raise AssertionError(
                f"SEP inbound port is {len(req)}/{len(resp)} bits, the tap decodes "
                f"{SEP_IN_REQ_BITS}/{SEP_IN_RESP_BITS}"
            )

        def field(bits: str, lsb: int, width: int, name: str) -> int:
            text = bits[len(bits) - lsb - width : len(bits) - lsb]
            if set(text) - {"0", "1"}:
                raise AssertionError(f"X/Z on SEP inbound {name}: {text}")
            return int(text, 2)

        while True:
            await RisingEdge(self.dut.clk_smu_i)
            q = str(req.value)
            r = str(resp.value)
            for chan, valid, ready, addr in (
                ("aw", SEP_IN_AW_VALID, SEP_IN_AW_READY, SEP_IN_AW_ADDR),
                ("ar", SEP_IN_AR_VALID, SEP_IN_AR_READY, SEP_IN_AR_ADDR),
            ):
                if field(q, valid, 1, f"{chan}_valid") and field(r, ready, 1, f"{chan}_ready"):
                    seen[chan].add(field(q, addr, SEP_IN_ADDR_BITS, f"{chan}.addr"))

    async def _ext_in_read_tap(
        self, ars: list[tuple[int, int, int]], beats: list[tuple[int, int, int]]
    ) -> None:
        """Record every AR and every R beat handshaken on the ext_in pins."""
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smu_i)
            if sample(dut.ext_in_arvalid, "ext_in_arvalid") and sample(
                dut.ext_in_arready, "ext_in_arready"
            ):
                ars.append(
                    (
                        sample(dut.ext_in_arid, "ext_in_arid"),
                        sample(dut.ext_in_araddr, "ext_in_araddr"),
                        sample(dut.ext_in_arlen, "ext_in_arlen"),
                    )
                )
            if sample(dut.ext_in_rvalid, "ext_in_rvalid") and sample(
                dut.ext_in_rready, "ext_in_rready"
            ):
                beats.append(
                    (
                        sample(dut.ext_in_rid, "ext_in_rid"),
                        sample(dut.ext_in_rresp, "ext_in_rresp"),
                        sample(dut.ext_in_rlast, "ext_in_rlast"),
                    )
                )

    async def _address_bits(self, master, jtag, sb) -> None:
        touched = {}
        issued: dict[object, int] = {}
        seen: dict[str, set[int]] = {"aw": set(), "ar": set()}
        tap = cocotb.start_soon(self._sep_port_tap(seen))
        await self._window(jtag, FOUR_GIB, SEP_SIZE_ONES)
        for addr in [FOUR_GIB] + [FOUR_GIB + (1 << k) for k in range(32)]:
            issued[addr - FOUR_GIB] = addr
            touched[addr - FOUR_GIB] = await self._touch(master, addr)
        await self._window(jtag, SEP_BASE_ONES, 1)
        issued["2^56-1"] = SEP_BASE_ONES
        touched["2^56-1"] = await self._touch(master, SEP_BASE_ONES)
        await self._window(jtag, SEP_GLOBAL_BASE_RESET, SEP_REGION_SIZE_RESET)
        issued["reset base"] = SEP_GLOBAL_BASE_RESET
        touched["reset base"] = await self._touch(master, SEP_GLOBAL_BASE_RESET)
        tap.cancel()
        arrived = {key: (addr in seen["ar"], addr in seen["aw"]) for key, addr in issued.items()}
        strays = sorted((seen["ar"] | seen["aw"]) - set(issued.values()))
        self._log(
            "OBSERVATION CHK-AXIIN-SEP-ADDRESS-BITS (read resp, byte, write resp) per SEP-local "
            f"offset {touched}"
        )
        # Two walked offsets decode to a unit the map names: SEP SRAM at its
        # base, still holding the first byte of the S6 stall pattern, and the
        # eFuse SHIM control word at the base of the external aperture.
        decoded = {
            SRAM_LOCAL: touched[SRAM_LOCAL],
            EFUSE_SHIM_LOCAL: touched[EFUSE_SHIM_LOCAL][::2],
        }
        self._log(
            f"address walk arrivals (read, write) at the SEP port={arrived} strays="
            f"{[hex(a) for a in strays]} decoded={decoded}"
        )
        sb.expect_eq(
            "CHK-AXIIN-SEP-ADDRESS-BITS",
            (arrived, strays, decoded),
            (
                dict.fromkeys(issued, (True, True)),
                [],
                {
                    SRAM_LOCAL: (RESP_OKAY, bytes([STALL_PATTERN_BASE]), RESP_OKAY),
                    EFUSE_SHIM_LOCAL: (RESP_OKAY, RESP_OKAY),
                },
            ),
            evidence="CHK-AXIIN-SEP-ADDRESS-BITS",
        )
        self.steps["S8"] = True

    async def _sba_write_status(self, jtag, addr: int, data: int) -> int:
        """A 32-bit system-bus write; returns sberror, cleared again."""
        await self._dmi(jtag, SBCS_ADDR, SBCS_SBACCESS_32 | SBCS_SBERROR_W1C, DMI_OP_WRITE)
        await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        await self._dmi(jtag, SBDATA0_ADDR, data, DMI_OP_WRITE)
        sbcs = SBCS_SBBUSY
        for _ in range(SBA_POLLS):
            sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if not sbcs & SBCS_SBBUSY:
                break
        await self._dmi(jtag, SBCS_ADDR, SBCS_SBERROR_W1C, DMI_OP_WRITE)
        return (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK

    async def _sba_read_status(self, jtag, addr: int) -> int:
        """A 32-bit system-bus read; returns sberror, cleared again."""
        await self._dmi(
            jtag,
            SBCS_ADDR,
            SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
        )
        await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        sbcs = SBCS_SBBUSY
        for _ in range(SBA_POLLS):
            sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if not sbcs & SBCS_SBBUSY:
                break
        await self._dmi(jtag, SBCS_ADDR, SBCS_SBERROR_W1C, DMI_OP_WRITE)
        return (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK

    async def _external_initiator(self, master, jtag, sb) -> None:
        """S9: inbound traffic into the SEP external aperture and the TRNG window."""
        await self._window(jtag, WIN_BASE, WIN_EXT_SIZE)
        ext = self._global(SEP_EXTERNAL_LOCAL + 0x100)
        trng = self._global(TRNG_LOCAL)
        shim = self._global(EFUSE_SHIM_LOCAL)
        ars: list[tuple[int, int, int]] = []
        r_beats: list[tuple[int, int, int]] = []
        tap = cocotb.start_soon(self._ext_in_read_tap(ars, r_beats))
        cells = [(ext, {"id": i}) for i in (0x04, 0xFF, 0x00)]
        cells += [(ext, dict(q)) for q in QUALIFIERS]
        cells += [(ext, {"prot": p}) for p in range(8)]
        cells += [(ext + off, {"size": size}) for size, off in ((0, 1), (1, 2), (2, 4), (3, 0))]
        cells += [(ext, {"size": 3, "beats": 4, "burst": AXI_BURST_INCR})]
        cells += [(ext, {"size": 3, "beats": 4, "burst": AXI_BURST_WRAP})]
        cells += [(ext, {"size": 3, "beats": 2, "burst": AXI_BURST_FIXED})]
        cells += [(ext, {"size": 3, "beats": 256, "burst": AXI_BURST_INCR})]
        cells += [(ext, {})]
        cells += [(trng, {"prot": p, "size": 2}) for p in range(8)]
        cells += [(trng + off, {"size": size}) for size, off in ((0, 1), (1, 2), (0, 3), (2, 4))]
        # Write responses at the external aperture, and the response of each
        # TRNG-window write.
        observed: list[bool] = []
        trng_writes: list[int] = []
        # (address, beats) of every read offered at each target; the ext_in tap
        # supplies the RRESP of each of its beats.
        issued: dict[str, list[tuple[int, int]]] = {"external": [], "trng": []}
        for n, (addr, attrs) in enumerate(cells):
            attrs = dict(attrs)
            beats = attrs.pop("beats", 1)
            nbytes = beats * (1 << attrs.get("size", 3))
            for write in (True, False):
                resp, _, _ = await self._ax(
                    master,
                    write=write,
                    addr=addr,
                    payload=bytes(nbytes) if write else nbytes,
                    label=f"ext{n}{'w' if write else 'r'}",
                    **attrs,
                )
                region = "trng" if trng <= addr < trng + TRNG_WINDOW else "external"
                if not write:
                    issued[region].append((addr, _read_beats(addr, nbytes, attrs.get("size", 3))))
                elif region == "external":
                    observed.append(resp != RESP_OKAY)
                else:
                    trng_writes.append(resp)
        # A read train under eight IDs, all in flight at once, so the SEP's
        # inbound ID remap hands out every index it has.
        master.driver.set_timing(AxiTimingProfile(r_ready_delay=TRAIN_HOLD_CYCLES))
        try:
            train = [master.init_read(ext, 8, size=3, id=16 * i + 3) for i in range(8)]
            for event in train:
                await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        finally:
            master.driver.set_timing(AxiTimingProfile())
        issued["external"] += [(ext, 1)] * len(train)
        shim_ok = []
        for prot in range(8):
            resp_r, data, _ = await self._ax(
                master, write=False, addr=shim, payload=4, size=2, prot=prot, label=f"shim{prot}r"
            )
            resp_w, _, _ = await self._ax(
                master,
                write=True,
                addr=shim,
                payload=data[:4] or bytes(4),
                size=2,
                prot=prot,
                label=f"shim{prot}w",
            )
            shim_ok.append((resp_r, resp_w))
        shim_word = data[:4] or bytes(4)
        held_resp = {}
        try:
            for name, addr, word, reads in (
                ("shim", shim, shim_word, HELD),
                ("external", ext, bytes(4), HELD),
                ("trng", trng, bytes(4), HELD),
                ("trng_writes", trng, bytes(4), 0),
            ):
                master.driver.set_timing(
                    AxiTimingProfile(r_ready_delay=HELD_HOLD_CYCLES, b_ready_delay=HELD_HOLD_CYCLES)
                )
                held = [
                    master.init_read(
                        addr, 4 * (1 + (i % 2) * 7), size=2, id=16 * (i % HELD_IDS) + 6
                    )
                    for i in range(reads)
                ]
                held_w = [
                    master.init_write(addr, word, size=2, id=16 * (i % HELD_IDS) + 8)
                    for i in range(HELD)
                ]
                for event in held + held_w:
                    await with_timeout(event.wait(), HELD_WAIT_NS, "ns")
                if name == "shim":
                    held_resp[name] = (
                        max((worst_resp(e.data.resp) for e in held), default=RESP_SLVERR),
                        max(worst_resp(e.data.resp) for e in held_w),
                    )
                    continue
                region = "trng" if addr == trng else "external"
                issued[region] += [
                    (addr, _read_beats(addr, 4 * (1 + (i % 2) * 7), 2)) for i in range(reads)
                ]
                if region == "trng":
                    trng_writes += [worst_resp(e.data.resp) for e in held_w]
                else:
                    observed += [worst_resp(e.data.resp) != RESP_OKAY for e in held_w]
        finally:
            master.driver.set_timing(AxiTimingProfile())
        # Writes launched together whose W trails the first AW, so their address
        # phases reach the refusing slave ahead of the data.
        lagged = []
        try:
            for addr in (ext, trng):
                master.driver.set_timing(AxiTimingProfile(w_delay=W_LAG_CYCLES))
                events = [
                    master.init_write(addr, bytes(4), size=2, id=16 * i + 5)
                    for i in range(W_LAG_WRITES)
                ]
                for event in events:
                    await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
                if addr == trng:
                    trng_writes += [worst_resp(e.data.resp) for e in events]
                else:
                    lagged += [worst_resp(e.data.resp) for e in events]
        finally:
            master.driver.set_timing(AxiTimingProfile())
        observed += [resp != RESP_OKAY for resp in lagged]
        # A shim write whose W trails its AW, with a read of the shim whose AR is
        # delayed by a swept amount, so for some delay the read and the write's
        # data reach the shim's register block in the same cycle.
        collide = []
        try:
            for ar_lag in range(W_LAG_CYCLES - COLLIDE_SPAN, W_LAG_CYCLES + COLLIDE_SPAN, 2):
                master.driver.set_timing(AxiTimingProfile(w_delay=W_LAG_CYCLES, ar_delay=ar_lag))
                wr = master.init_write(shim, shim_word, size=2, id=0x15)
                rd = master.init_read(shim, 4, size=2, id=0x16)
                for event in (wr, rd):
                    await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
                collide.append(
                    (worst_resp(wr.data.resp), worst_resp(rd.data.resp), bytes(rd.data.data)[:4])
                )
        finally:
            master.driver.set_timing(AxiTimingProfile())
        shim_ok.append(
            (
                max(c[0] for c in collide),
                max(c[1] for c in collide) if all(c[2] == shim_word for c in collide) else -1,
            )
        )
        shim_ok.append(held_resp.pop("shim"))
        tap.cancel()
        bursts, tap_errors = _split_bursts(ars, r_beats)
        tapped: dict[str, list[tuple[int, tuple[int, ...]]]] = {"external": [], "trng": []}
        for araddr, codes in bursts:
            if trng <= araddr < trng + TRNG_WINDOW:
                tapped["trng"].append((araddr, codes))
            elif ext <= araddr < ext + 256 * 8:
                tapped["external"].append((araddr, codes))
            elif araddr != shim:
                tap_errors.append(f"read at 0x{araddr:x} outside the S9 targets")
        reads = {region: Counter((a, len(c)) for a, c in tapped[region]) for region in tapped}
        ext_bad = [(hex(a), c) for a, c in tapped["external"] if RESP_OKAY in c]
        trng_bad = [(hex(a), c) for a, c in tapped["trng"] if set(c) != {RESP_DECERR}]
        await self._window(jtag, WIN_BASE, WIN_SIZE)
        # The debug module's system bus after the external initiator.
        sb_err = await self._sba_read_status(jtag, SEP_EXTERNAL_LOCAL + 0x100)
        sb_werr = await self._sba_write_status(jtag, SEP_EXTERNAL_LOCAL + 0x100, 0)
        self._log(f"CHK-AXIIN-SEP-SHIM {shim_ok} system-bus sberror={sb_err}/{sb_werr}")
        sb.expect_eq(
            "CHK-AXIIN-SEP-SHIM",
            (shim_ok, sb_err != 0, sb_werr != 0),
            ([(RESP_OKAY, RESP_OKAY)] * 10, True, True),
            evidence="CHK-AXIIN-SEP-SHIM",
        )
        # An unconnected ext_trng_axil is terminated with a DECERR slave
        # (doc/integrator/src/smu.adoc, "External TRNG") and a crypto-region
        # burst is DECERR on every beat (hw/sys/sep/doc/crypto.adoc), so every
        # R beat the ext_in tap pairs with a TRNG-window AR is DECERR. The
        # write responses are recorded and not graded; SMU_FCOV.adoc, Phase 2,
        # states why.
        write_codes = {resp_name(c): trng_writes.count(c) for c in sorted(set(trng_writes))}
        self._log(
            f"OBSERVE-AXIIN-SEP-TRNG-WRITE {len(trng_writes)} TRNG-window writes "
            f"responses={write_codes} (recorded, not graded)"
        )
        ext_beats = sum(n * k for (_, n), k in reads["external"].items())
        trng_beats = sum(n * k for (_, n), k in reads["trng"].items())
        self._log(
            f"CHK-AXIIN-SEP-EXTERNAL {len(observed)} external-aperture writes "
            f"errors={sum(observed)}; {len(tapped['external'])} external-aperture reads "
            f"({ext_beats} R beats) with an OKAY beat={ext_bad}; "
            f"{len(tapped['trng'])} TRNG-window reads ({trng_beats} R beats) "
            f"with a beat not DECERR={trng_bad}; ext_in tap ARs={len(ars)} "
            f"R beats={len(r_beats)} errors={tap_errors}"
        )
        sb.expect_eq(
            "CHK-AXIIN-SEP-EXTERNAL",
            (observed, reads["external"], ext_bad, reads["trng"], trng_bad, tap_errors),
            (
                [True] * len(observed),
                Counter(issued["external"]),
                [],
                Counter(issued["trng"]),
                [],
                [],
            ),
            evidence="CHK-AXIIN-SEP-EXTERNAL",
        )
        self.steps["S9"] = True

    async def _id_train(self, master, sb) -> None:
        """S10: reads and writes under distinct IDs in flight together."""
        base = self._global(SRAM_LOCAL) + 0x800
        words = {i: (0xC0DE_0000_0000_0000 | i).to_bytes(8, "little") for i in range(TRAIN)}
        master.driver.set_timing(
            AxiTimingProfile(r_ready_delay=TRAIN_HOLD_CYCLES, b_ready_delay=TRAIN_HOLD_CYCLES)
        )
        try:
            writes = [
                master.init_write(base + 8 * i, words[i], size=3, id=16 * i + 1)
                for i in range(TRAIN)
            ]
            for event in writes:
                await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
            reads = [master.init_read(base + 8 * i, 8, size=3, id=16 * i + 2) for i in range(TRAIN)]
            for event in reads:
                await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        finally:
            master.driver.set_timing(AxiTimingProfile())
        bad = [i for i, event in enumerate(writes) if worst_resp(event.data.resp) != RESP_OKAY]
        bad += [
            i
            for i, event in enumerate(reads)
            if worst_resp(event.data.resp) != RESP_OKAY or bytes(event.data.data)[:8] != words[i]
        ]
        self._log(f"CHK-AXIIN-SEP-ID-TRAIN mismatches={bad}")
        sb.expect_eq("CHK-AXIIN-SEP-ID-TRAIN", bad, [], evidence="CHK-AXIIN-SEP-ID-TRAIN")
        self.steps["S10"] = True

    def _smc_view(self, local: int) -> int:
        return sample(self.dut.smc_global_base_o, "smc_global_base_o") + (local - SMC_LOCAL_BASE)

    async def _smc_dma(self, master, jtag, sb) -> None:
        """S11: an SMC iDMA copy from SEP SRAM to ext_out, launched over the SEP system bus."""
        src = self._global(SRAM_LOCAL) + 0x1000
        payload = bytes((0x5B + 3 * i) & 0xFF for i in range(DMA_LENGTH))
        resp_w, _, _ = await self._ax(
            master, write=True, addr=src, payload=payload, size=3, label="dma_src"
        )
        mem = self.test.cfg.axi_out_mem
        mem.write(DMA_DST, bytes(DMA_LENGTH))
        # SMC inbound filter entry 0 over the system bus, then ext_in reads the
        # SMC at its global address before the system bus programs the iDMA.
        for addr, value in (
            (INBOUND0_START, 0),
            (INBOUND0_END, PASS_ALL_END),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._sba_write64(jtag, self._smc_view(addr), value)
        smc_resp, smc_word, _ = await self._ax(
            master,
            write=False,
            addr=self._smc_view(SMC_CHIP_CONFIG_VERSION_LO),
            payload=4,
            size=2,
            label="smc_version",
        )
        smc_version = int.from_bytes(smc_word[:4], "little")
        for addr, value in (
            (OUTBOUND0_START, 0),
            (OUTBOUND0_END, PASS_ALL_END),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._sba_write64(jtag, self._smc_view(addr), value)
        regs = {name: self._smc_view(addr) for name, addr in DMA_REGS.items()}
        for name, value in (
            ("CONFIG", DMA_CONFIG_ENABLE_ND),
            ("DST_ADDRESS_LO", DMA_DST & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", DMA_DST >> 32),
            ("SRC_ADDRESS_LO", src & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", src >> 32),
            ("LENGTH_LO", DMA_LENGTH),
            ("LENGTH_HI", 0),
            ("DST_STRIDE_LO", 0),
            ("DST_STRIDE_HI", 0),
            ("SRC_STRIDE_LO", 0),
            ("SRC_STRIDE_HI", 0),
            ("NUM_REPETITIONS_LO", 1),
            ("NUM_REPETITIONS_HI", 0),
        ):
            await self._sba_write(jtag, regs[name], value)
        # Reading NEXT_ID submits the programmed descriptor; it is read once.
        start_id = await self._sba_read(jtag, regs["NEXT_ID_0"])
        done = None
        for _ in range(DMA_POLLS):
            done = await self._sba_read(jtag, regs["DONE_0"])
            if done == start_id:
                break
        dst = mem.read(DMA_DST, DMA_LENGTH)
        back = src + DMA_BACK_OFFSET
        for name, value in (
            ("DST_ADDRESS_LO", back & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", back >> 32),
            ("SRC_ADDRESS_LO", DMA_DST & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", DMA_DST >> 32),
        ):
            await self._sba_write(jtag, regs[name], value)
        back_id = await self._sba_read(jtag, regs["NEXT_ID_0"])
        back_done = None
        for _ in range(DMA_POLLS):
            back_done = await self._sba_read(jtag, regs["DONE_0"])
            if back_done == back_id:
                break
        _, returned, _ = await self._ax(
            master, write=False, addr=back, payload=DMA_LENGTH, size=3, label="dma_back"
        )
        await self._sba_write64(jtag, OUTBOUND_START_ADDR, SEP_EGRESS)
        await self._sba_write64(jtag, OUTBOUND_END_ADDR, SEP_EGRESS + 0xFFF)
        await self._sba_write(jtag, OUTBOUND_FILTER_CONFIG, OUTBOUND_CFG_OPEN)
        await self._sba_write(jtag, SEP_EGRESS, 0x0DDBA11)
        egress = await self._sba_read(jtag, SEP_EGRESS)
        held_egress = self.test.cfg.axi_out_mem.read_int(SEP_EGRESS, 4)
        after, _, _ = await self._ax(
            master, write=False, addr=src, payload=8, size=3, label="after_dma"
        )
        self._log(
            f"CHK-AXIIN-SEP-SMC-DMA start_id={start_id} done={done} src_wr={resp_w} "
            f"back_id={back_id} back_done={back_done} egress=0x{egress:x} "
            f"held_egress=0x{held_egress:x} after={after}"
        )
        sb.expect_eq(
            "CHK-AXIIN-SEP-SMC-DMA",
            (
                resp_w,
                (smc_resp, smc_version),
                done,
                dst.hex(),
                back_done,
                returned[:DMA_LENGTH].hex(),
                (egress, held_egress),
                after,
            ),
            (
                RESP_OKAY,
                (RESP_OKAY, SMC_CHIP_CONFIG_VERSION_LO_RESET),
                start_id,
                payload.hex(),
                back_id,
                payload.hex(),
                (0x0DDBA11, 0x0DDBA11),
                RESP_OKAY,
            ),
            evidence="CHK-AXIIN-SEP-SMC-DMA",
        )
        self.steps["S11"] = True

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        await self._window(jtag, WIN_BASE, WIN_SIZE)
        self.steps["S4"] = True
        master = await make_smu_axi_master(
            cocotb.top, self.dut.clk_smu_i, smc_primary_reset(self.dut)
        )
        await self._round_trips(master, sb)
        await self._bursts(master, sb)
        await self._errors(master, sb)
        await self._external_initiator(master, jtag, sb)
        await self._id_train(master, sb)
        await self._smc_dma(master, jtag, sb)
        await self._address_bits(master, jtag, sb)
