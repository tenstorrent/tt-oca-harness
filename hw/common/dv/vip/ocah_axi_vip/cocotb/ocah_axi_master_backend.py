# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""cocotbext-axi master backend with AXI4 FIXED-burst byte lanes.

A FIXED burst repeats one address on every beat, so every beat drives the
byte lanes of that address (IHI 0022 A3.4.1, A3.4.3). ``cocotbext-axi``
0.1.28 advances the lane offset on every beat of every burst type, so a
FIXED burst narrower than the bus drives beats 1..N on the wrong lanes and
unpacks read beats from them. ``OcahAxiMasterWrite`` and
``OcahAxiMasterRead`` carry the 0.1.28 write and read-unpack loops with the
lane offset held for FIXED bursts; ``OcahAxiMaster`` composes them the way
``cocotbext.axi.AxiMaster`` does. Re-check both loops against the backend
whenever the pinned ``cocotbext-axi`` version changes.
"""

from __future__ import annotations

import logging
from typing import List, NamedTuple

from cocotb.triggers import Event
from cocotbext.axi.address_space import Region
from cocotbext.axi.axi_master import (
    AxiMaster,
    AxiMasterRead,
    AxiMasterWrite,
    AxiReadResp,
    AxiWriteRespCmd,
)
from cocotbext.axi.constants import AxiBurstType, AxiProt, AxiResp


class OcahAxiReadRespCmd(NamedTuple):
    """``AxiReadRespCmd`` plus the burst type the unpack needs."""

    address: int
    length: int
    size: int
    cycles: int
    prot: AxiProt
    burst_list: List[int]
    event: Event
    burst: AxiBurstType


class OcahAxiMasterWrite(AxiMasterWrite):
    """Write side: FIXED bursts keep their byte lanes on every beat."""

    async def _process_write(self):
        while True:
            cmd = await self.write_command_queue.get()
            self.current_write_command = cmd

            num_bytes = 2**cmd.size
            fixed = cmd.burst == AxiBurstType.FIXED

            aligned_addr = (cmd.address // num_bytes) * num_bytes
            word_addr = (cmd.address // self.byte_lanes) * self.byte_lanes

            start_offset = cmd.address % self.byte_lanes
            end_offset = ((cmd.address + len(cmd.data) - 1) % self.byte_lanes) + 1

            cycles = (len(cmd.data) + (cmd.address % num_bytes) + num_bytes - 1) // num_bytes

            cur_addr = cmd.address
            offset = 0
            cycle_offset = aligned_addr - word_addr
            n = 0
            transfer_count = 0

            burst_list = []
            burst_length = 0

            if cmd.awid is not None:
                awid = cmd.awid
            else:
                awid = self.cur_id
                self.cur_id = (self.cur_id + 1) % self.id_count

            wuser = cmd.wuser

            if self.log.isEnabledFor(logging.INFO):
                self.log.info(
                    "Write start addr: 0x%08x awid: 0x%x prot: %s data: %s",
                    cmd.address,
                    awid,
                    cmd.prot,
                    " ".join(f"{c:02x}" for c in cmd.data),
                )

            for k in range(cycles):
                start = cycle_offset
                stop = cycle_offset + num_bytes

                if k == 0:
                    start = start_offset
                if k == cycles - 1:
                    # A FIXED burst's last beat ends where its payload ends,
                    # not at the INCR end offset.
                    stop = start + (len(cmd.data) - offset) if fixed else end_offset

                strb = (
                    (self.strb_mask << start)
                    & self.strb_mask
                    & (self.strb_mask >> (self.byte_lanes - stop))
                )

                val = 0
                for j in range(start, stop):
                    val |= cmd.data[offset] << j * 8
                    offset += 1

                if n >= burst_length:
                    transfer_count += 1
                    n = 0

                    # split on burst length
                    burst_length = min(cycles - k, min(max(self.max_burst_len, 1), 256))
                    # split on 4k address boundary
                    burst_length = (
                        min(burst_length * num_bytes, 0x1000 - (cur_addr & 0xFFF)) + num_bytes - 1
                    ) // num_bytes

                    burst_list.append(burst_length)

                    aw = self.aw_channel._transaction_obj()
                    aw.awid = awid
                    aw.awaddr = cur_addr
                    aw.awlen = burst_length - 1
                    aw.awsize = cmd.size
                    aw.awburst = cmd.burst
                    aw.awlock = cmd.lock
                    aw.awcache = cmd.cache
                    aw.awprot = cmd.prot
                    aw.awqos = cmd.qos
                    aw.awregion = cmd.region
                    aw.awuser = cmd.user

                    self.active_id[awid] += 1
                    await self.aw_channel.send(aw)

                    self.log.info(
                        "Write burst start awid: 0x%x awaddr: 0x%08x awlen: %d awsize: %d awprot: %s",
                        awid,
                        cur_addr,
                        burst_length - 1,
                        cmd.size,
                        cmd.prot,
                    )

                n += 1

                if not self.wstrb_present and strb != self.strb_mask:
                    self.log.warning(
                        "Partial operation requested with wstrb not connected, "
                        "write will be zero-padded (0x%x != 0x%x)",
                        strb,
                        self.strb_mask,
                    )

                w = self.w_channel._transaction_obj()
                w.wdata = val
                w.wstrb = strb
                w.wlast = n >= burst_length

                if isinstance(wuser, int):
                    w.wuser = wuser
                else:
                    if wuser and k < len(wuser):
                        w.wuser = wuser[k]
                    else:
                        w.wuser = 0

                await self.w_channel.send(w)

                if fixed:
                    cur_addr = cmd.address
                elif k == 0:
                    cur_addr = aligned_addr + num_bytes
                else:
                    cur_addr += num_bytes
                if not fixed:
                    cycle_offset = (cycle_offset + num_bytes) % self.byte_lanes

            resp_cmd = AxiWriteRespCmd(
                cmd.address, len(cmd.data), cmd.size, cycles, cmd.prot, burst_list, cmd.event
            )
            self.tag_context_manager.start_cmd(awid, resp_cmd)

            self.current_write_command = None


class OcahAxiMasterRead(AxiMasterRead):
    """Read side: FIXED bursts unpack every beat from the same byte lanes."""

    async def _process_read(self):
        while True:
            cmd = await self.read_command_queue.get()
            self.current_read_command = cmd

            num_bytes = 2**cmd.size

            aligned_addr = (cmd.address // num_bytes) * num_bytes

            cycles = (cmd.length + num_bytes - 1 + (cmd.address % num_bytes)) // num_bytes

            burst_list = []

            cur_addr = cmd.address
            n = 0

            burst_length = 0

            if cmd.arid is not None:
                arid = cmd.arid
            else:
                arid = self.cur_id
                self.cur_id = (self.cur_id + 1) % self.id_count

            self.log.info(
                "Read start addr: 0x%08x arid: 0x%x prot: %s", cmd.address, arid, cmd.prot
            )

            for k in range(cycles):
                n += 1
                if n >= burst_length:
                    n = 0

                    # split on burst length
                    burst_length = min(cycles - k, min(max(self.max_burst_len, 1), 256))
                    # split on 4k address boundary
                    burst_length = (
                        min(burst_length * num_bytes, 0x1000 - (cur_addr & 0xFFF)) + num_bytes - 1
                    ) // num_bytes

                    burst_list.append(burst_length)

                    ar = self.ar_channel._transaction_obj()
                    ar.arid = arid
                    ar.araddr = cur_addr
                    ar.arlen = burst_length - 1
                    ar.arsize = cmd.size
                    ar.arburst = cmd.burst
                    ar.arlock = cmd.lock
                    ar.arcache = cmd.cache
                    ar.arprot = cmd.prot
                    ar.arqos = cmd.qos
                    ar.arregion = cmd.region
                    ar.aruser = cmd.user

                    self.active_id[arid] += 1
                    await self.ar_channel.send(ar)

                    self.log.info(
                        "Read burst start arid: 0x%x araddr: 0x%08x arlen: %d arsize: %d arprot: %s",
                        arid,
                        cur_addr,
                        burst_length - 1,
                        cmd.size,
                        cmd.prot,
                    )

                if cmd.burst == AxiBurstType.FIXED:
                    cur_addr = cmd.address
                elif k == 0:
                    cur_addr = aligned_addr + num_bytes
                else:
                    cur_addr += num_bytes

            resp_cmd = OcahAxiReadRespCmd(
                cmd.address,
                cmd.length,
                cmd.size,
                cycles,
                cmd.prot,
                burst_list,
                cmd.event,
                cmd.burst,
            )
            self.tag_context_manager.start_cmd(arid, resp_cmd)

            self.current_read_command = None

    async def _process_read_resp_id(self, context, cmd):
        rid = context.current_tag

        num_bytes = 2**cmd.size
        fixed = cmd.burst == AxiBurstType.FIXED

        aligned_addr = (cmd.address // num_bytes) * num_bytes
        word_addr = (cmd.address // self.byte_lanes) * self.byte_lanes

        start_offset = cmd.address % self.byte_lanes

        cycle_offset = aligned_addr - word_addr
        data = bytearray()

        resp = AxiResp.OKAY
        user = []

        first = True

        for burst_length in cmd.burst_list:
            for k in range(burst_length):
                r = await context.get_resp()

                assert self.active_id[rid] > 0, "unexpected burst ID"

                if k == burst_length - 1:
                    assert int(r.rlast), "missing rlast at end of burst"
                else:
                    assert not int(r.rlast), "unexpected rlast within burst"

                cycle_data = int(r.rdata)
                cycle_resp = AxiResp(int(getattr(r, "rresp", AxiResp.OKAY)))
                cycle_user = int(getattr(r, "ruser", 0))

                if cycle_resp != AxiResp.OKAY:
                    resp = cycle_resp

                if cycle_user is not None:
                    user.append(cycle_user)

                start = cycle_offset
                stop = cycle_offset + num_bytes

                if first:
                    start = start_offset

                for j in range(start, stop):
                    data.append((cycle_data >> j * 8) & 0xFF)

                if not fixed:
                    cycle_offset = (cycle_offset + num_bytes) % self.byte_lanes

                first = False

            self.active_id[rid] -= 1

            self.log.info("Read burst complete rid: 0x%x rresp: %s", rid, resp)

        data = data[: cmd.length]

        if not self.ruser_present:
            user = None

        if self.log.isEnabledFor(logging.INFO):
            self.log.info(
                "Read complete addr: 0x%08x prot: %s resp: %s data: %s",
                cmd.address,
                cmd.prot,
                resp,
                " ".join(f"{c:02x}" for c in data),
            )

        read_resp = AxiReadResp(cmd.address, bytes(data), resp, user)

        cmd.event.set(read_resp)

        self.in_flight_operations -= 1

        if self.in_flight_operations == 0:
            self._idle.set()


class OcahAxiMaster(AxiMaster):
    """``cocotbext.axi.AxiMaster`` composed from the FIXED-lane-correct halves."""

    def __init__(
        self, bus, clock, reset=None, reset_active_level=True, max_burst_len=256, **kwargs
    ):
        self.write_if = None
        self.read_if = None

        self.write_if = OcahAxiMasterWrite(
            bus.write, clock, reset, reset_active_level, max_burst_len, **kwargs
        )
        self.read_if = OcahAxiMasterRead(
            bus.read, clock, reset, reset_active_level, max_burst_len, **kwargs
        )

        Region.__init__(self, max(self.write_if.size, self.read_if.size), **kwargs)
