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
    legal AxSIZE and at the eight byte offsets of a word. Each is OKAY, returns
    the issued id, and reads back what was written.
S6: INCR bursts of AxLEN 0x00, 0x55, 0xAA and 0xFF write a byte pattern into
    SRAM and read it back OKAY; WRAP bursts of 2, 4, 8 and 16 beats and FIXED
    bursts read OKAY.
S7: a write to the entropy pool drain aperture terminates SLVERR
    (``fabric.adoc``: "Writes to it terminate with BRESP=SLVERR"), and a read and
    a write of SEP-local 0x0, which no component owns, are not OKAY.
S8: every aperture address bit reaches the crossbar's SEP port on both
    channels: with the window at [4 GiB, 8 GiB) a byte is read and written back
    unchanged at 4 GiB + 2^k for each k below 32 and at 4 GiB itself, and with
    the window at the single byte 2^56 - 1 the same there, each completing
    with a response; the aperture then returns to its RDL reset values.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import with_timeout
from ocah_axi_vip import RESP_OKAY, RESP_SLVERR, worst_resp

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    SEP_BASE_ONES,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
    SEP_SIZE_ONES,
    smu_dtp_sep_dm_sba_test_seq,
)
from seq_lib.smu_tb_pins import smc_primary_reset

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"
SRAM_LOCAL = c_header_u32(_SEP_ADDR_H, "OCH_SEP_TOP_SEP_SRAM_BASE_ADDR")
SRAM_SIZE = c_header_u32(_SEP_ADDR_H, "OCH_SEP_TOP_SEP_SRAM_SIZE")
ENTROPY_POOL_LOCAL = c_header_u32(_SEP_ADDR_H, "OCH_SEP_TOP_ENTROPY_POOL_BASE_ADDR")

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
WRAP_BEATS = (2, 4, 8, 16)


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
        await self._port_settles("sep_global_base_o", base)
        await self._port_settles("sep_region_size_o", size)

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
            resp_r, data, rid = await self._ax(
                master, write=False, addr=addr, payload=8, label=f"rt_rd{n}", **attrs
            )
            want_id = attrs.get("id")
            if resp_w != RESP_OKAY or resp_r != RESP_OKAY or data[:8] != word:
                bad.append((attrs, resp_w, resp_r, data[:8].hex()))
            if want_id is not None and rid is not None and rid != want_id:
                bad.append((attrs, "rid", rid))
        for size in range(4):
            resp, _, _ = await self._ax(
                master, write=False, addr=addr, payload=1 << size, size=size, label=f"sz{size}"
            )
            if resp != RESP_OKAY:
                bad.append(({"size": size}, resp))
        for offset in range(8):
            resp, _, _ = await self._ax(
                master, write=False, addr=addr + offset, payload=1, size=0, label=f"off{offset}"
            )
            if resp != RESP_OKAY:
                bad.append(({"offset": offset}, resp))
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
        for beats in WRAP_BEATS:
            resp, _, _ = await self._ax(
                master,
                write=False,
                addr=base,
                payload=beats * 8,
                size=3,
                burst=AXI_BURST_WRAP,
                label=f"wrap{beats}",
            )
            if resp != RESP_OKAY:
                bad.append(("WRAP", beats, resp))
        resp, _, _ = await self._ax(
            master,
            write=False,
            addr=base,
            payload=4 * 8,
            size=3,
            burst=AXI_BURST_FIXED,
            label="fixed4",
        )
        if resp != RESP_OKAY:
            bad.append(("FIXED", 4, resp))
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

    async def _touch(self, master, addr: int) -> None:
        """Read one byte, then write the same byte back."""
        _, data, _ = await self._ax(
            master, write=False, addr=addr, payload=1, size=0, label=f"rd@{addr:x}"
        )
        await self._ax(
            master,
            write=True,
            addr=addr,
            payload=data[:1] or bytes(1),
            size=0,
            label=f"wr@{addr:x}",
        )

    async def _address_bits(self, master, jtag, sb) -> None:
        completed = 0
        await self._window(jtag, FOUR_GIB, SEP_SIZE_ONES)
        for addr in [FOUR_GIB] + [FOUR_GIB + (1 << k) for k in range(32)]:
            await self._touch(master, addr)
            completed += 1
        await self._window(jtag, SEP_BASE_ONES, 1)
        await self._touch(master, SEP_BASE_ONES)
        completed += 1
        await self._window(jtag, SEP_GLOBAL_BASE_RESET, SEP_REGION_SIZE_RESET)
        self._log(f"CHK-AXIIN-SEP-ADDRESS-BITS completed={completed} of 34")
        sb.expect_eq(
            "CHK-AXIIN-SEP-ADDRESS-BITS", completed, 34, evidence="CHK-AXIIN-SEP-ADDRESS-BITS"
        )
        self.steps["S8"] = True

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
        await self._address_bits(master, jtag, sb)
