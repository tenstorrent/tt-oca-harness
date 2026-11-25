# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI transfers under responder back-pressure on every bridge.

Each bridge's responder stalls AWREADY, WREADY and ARREADY and delays B and R,
every channel from its own seeded stream. Each channel takes every timing mode,
no stall, short stalls, stalls of one to two sbcs polls and a seeded mix of
short and long, in a seeded order of its own, so a long stall on one channel
meets a short or no stall on another. W takes the mode paired with AW's, so the
AW and W handshakes land in every order. Under each timing the bridge writes two
neighbouring beats, reads the first back, then writes and reads back seeded
lanes of it at a seeded size. Every access is judged on the bus
(``CHK-J2A-BUS-REQ``, ``CHK-J2A-AXI-ATTR``), in the subordinate memory and on
the data the debugger fetches, and every sbcs poll against the bridge model;
the port raises no request while one is open (``CHK-J2A-ONE-XFER``). With a
write and then a read held open, the access a second sbdata0 or sbaddress0
write would start is refused with sbbusyerror and reaches no port.
"""

from __future__ import annotations

import math
import random

from cocotb.utils import get_sim_time
from env.dtp_types import JTAG2AXI_TARGETS, DtpDmiOp, DtpDmiStatus, DtpDmReg, pack_sbcs, unpack_sbcs
from ocah_axi_vip import OcahAxiDelays

from .dtp_jtag2axi_base_test_seq import FAULT_STATUS_CHECK_ID, dtp_jtag2axi_base_test_seq

# Every responder channel with a seeded stream: the READY stalls of AW, W and
# AR, and the B and R response delays.
TIMING_CHANNELS = ("aw", "w", "ar", "b", "r")
TIMING_MODES = ("none", "short", "long", "mixed")
# The W mode under each AW mode: no stall on both puts the SMC fabric bridge's
# AW and W handshakes in one cycle, and a long stall against a short one puts
# the short channel's handshake first.
W_MODE_WITH_AW = {"none": "none", "short": "long", "long": "short", "mixed": "mixed"}
SHORT_CYCLES = (1, 8)
# Percentages of long draws in the mixed mode.
MIXED_LONG_PERCENT = (10, 40)
# Long draws, in sbcs polls; three channels of one write at the top of the range
# end within SBA_POLLS polls.
LONG_POLLS = (1, 2)
# Write-and-read rounds under each timing.
ROUNDS = 2


class dtp_jtag2axi_backpressure_test_seq(dtp_jtag2axi_base_test_seq):
    """Writes and reads on each bridge in a seeded order, each bridge under seeded READY
    stalls and response delays, with one transfer at a time on the port."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_backpressure_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("Transfers under responder back-pressure on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("backpressure")
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            self._ledger_target = target
            self.open_bus_ledger()
            await self.backpressure_case(target, rng)
            self.close_bus_ledger()
            self._ledger_target = None
            self.log_summary(f"{target} transfers under back-pressure complete")

    async def backpressure_case(self, target: str, rng: random.Random) -> None:
        """Every timing mode on every channel of ``target``, each channel but W in its own
        seeded order, with ``ROUNDS`` write-and-read rounds under each timing, then the busy
        attempts."""
        poll = await self.poll_cycles(target)
        since = self.open_request_count(target)
        schedule = {
            channel: rng.sample(TIMING_MODES, len(TIMING_MODES))
            for channel in ("aw", "ar", "b", "r")
        }
        schedule["w"] = [W_MODE_WITH_AW[mode] for mode in schedule["aw"]]
        for step in range(len(TIMING_MODES)):
            modes = {channel: schedule[channel][step] for channel in TIMING_CHANNELS}
            ctx = f"{target}.timing{step}"
            self.log.info("%s poll=%d cycles modes=%s", ctx, poll, modes)
            self.apply_responder_timing(
                target, **{channel: self.delays(rng, mode, poll) for channel, mode in modes.items()}
            )
            for index in range(ROUNDS):
                await self.write_and_read_round(target, rng, context=f"{ctx}.round{index}")
        self.clear_responder_timing(target)
        await self.busy_attempt_case(target, rng)
        self.check_one_transfer(target, since, context=f"{target}.backpressure")

    async def busy_attempt_case(self, target: str, rng: random.Random) -> None:
        """A second access requested while one is open: under a held write, an sbdata0 write
        that would start the next write, and under a held read, an sbaddress0 write that would
        start the next read. The held write lands with its own data and the held read returns
        it."""
        ctx = f"{target}.busy_attempt"
        size = self.target_cfg(target).data_size
        addr = self.random_target_addr(target, rng)
        data = self.random_distinct_word(rng, target)
        wstrb = self.full_wstrb(size)
        tb_if = self.cfg.tb_if
        self.scoreboard_arm_strobes(target, wstrb, addr, context=f"{ctx}.write")
        await self.sba_setup(target, addr, size, read=False, context=f"{ctx}.write")
        tb_if.hold_responses(target, b=True, r=False)
        if size == 3:
            await self.dmi_write(
                target, DtpDmReg.SBDATA1, data >> 32, context=f"{ctx}.write.sbdata1"
            )
        await self.dmi_write(
            target, DtpDmReg.SBDATA0, data & 0xFFFF_FFFF, context=f"{ctx}.write.sbdata0"
        )
        await self.refuse_while_open(target, DtpDmReg.SBDATA0, rng, context=f"{ctx}.write")
        tb_if.hold_responses(target, b=False, r=False)
        await self.expect_bus_request(
            target, read=False, addr=addr, size=size, data=data, wstrb=wstrb, context=f"{ctx}.write"
        )
        await self.wait_sba_idle(target, sbbusyerror=1, context=f"{ctx}.write.released")
        self.check_target_word(target, addr, data, size=size, context=f"{ctx}.write.mem")
        await self.clear_sbbusyerror(target, size, context=f"{ctx}.write")
        tb_if.hold_responses(target, b=False, r=True)
        await self.sba_setup(target, addr, size, read=True, context=f"{ctx}.read")
        await self.refuse_while_open(target, DtpDmReg.SBADDRESS0, rng, context=f"{ctx}.read")
        tb_if.hold_responses(target, b=False, r=False)
        await self.expect_bus_request(
            target, read=True, addr=addr, size=size, context=f"{ctx}.read"
        )
        await self.wait_sba_idle(target, sbbusyerror=1, context=f"{ctx}.read.released")
        await self.clear_sbbusyerror(target, size, context=f"{ctx}.read")
        rdata = await self.dmi_read(target, DtpDmReg.SBDATA0, context=f"{ctx}.read.sbdata0")
        if size == 3:
            rdata |= (
                await self.dmi_read(target, DtpDmReg.SBDATA1, context=f"{ctx}.read.sbdata1")
            ) << 32
        self.check_bridge_rdata(target, rdata, data, context=f"{ctx}.read")

    async def refuse_while_open(
        self, target: str, address: DtpDmReg, rng: random.Random, *, context: str
    ) -> None:
        """With the access just started held open, a seeded write to ``address`` takes a busy
        DMI status, which the next scan clears; sbcs then reads sbbusy and sbbusyerror 1, and
        the port raised no request for it."""
        refused = rng.getrandbits(32)
        since = self.open_request_count(target)
        await self.dmi_write(target, address, refused, context=f"{context}.refused")
        await self.select_dmi(target)
        await self.dmi_raw(
            target,
            0,
            0,
            DtpDmiOp.CLEAR,
            status=DtpDmiStatus.BUSY,
            expect=(int(address), refused),
            context=f"{context}.refused_clear",
        )
        sbcs = unpack_sbcs(
            await self.dmi_read(target, DtpDmReg.SBCS, context=f"{context}.held_sbcs")
        )
        self.check_equal(
            self.target_evidence(target),
            FAULT_STATUS_CHECK_ID,
            (sbcs["sbbusy"], sbcs["sbbusyerror"]),
            (1, 1),
            context=f"{context} target={target} held (sbbusy, sbbusyerror)",
        )
        self.check_one_transfer(target, since, context=f"{context}.refused")

    async def clear_sbbusyerror(self, target: str, size: int, *, context: str) -> None:
        """Clear sbbusyerror, keeping sbaccess ``size``, and require sbcs idle with no error."""
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbbusyerror=1, sbaccess=size),
            context=f"{context}.sbbusyerror_w1",
        )
        await self.wait_sba_idle(target, context=f"{context}.cleared")

    async def poll_cycles(self, target: str) -> int:
        """System clock cycles of one sbcs poll: the DMI read and the scan that fetches it."""
        start_ns = get_sim_time("ns")
        await self.dmi_read(target, DtpDmReg.SBCS, context=f"{target}.poll_length")
        return math.ceil((get_sim_time("ns") - start_ns) / self.cfg.sys_clk_period_ns)

    @staticmethod
    def delays(rng: random.Random, mode: str, poll: int) -> OcahAxiDelays:
        """A seeded stream of ``mode`` cycle counts, long ones in ``LONG_POLLS`` polls."""
        seed = rng.getrandbits(32)
        long_min, long_max = (polls * poll for polls in LONG_POLLS)
        if mode == "none":
            return OcahAxiDelays(seed)
        if mode == "short":
            return OcahAxiDelays(seed, short_min=SHORT_CYCLES[0], short_max=SHORT_CYCLES[1])
        if mode == "long":
            return OcahAxiDelays(seed, long_percent=100, long_min=long_min, long_max=long_max)
        return OcahAxiDelays(
            seed,
            short_max=SHORT_CYCLES[1],
            long_percent=rng.randint(*MIXED_LONG_PERCENT),
            long_min=long_min,
            long_max=long_max,
        )

    async def write_and_read_round(self, target: str, rng: random.Random, *, context: str) -> None:
        """Two neighbouring beats written and the first read back, then seeded lanes of that
        beat written at a seeded size and read back."""
        cfg = self.target_cfg(target)
        addr = self.random_target_addr(target, rng)
        _, beat = await self.write_neighbour_then_read(target, addr, rng, context=context)
        size = rng.randint(0, cfg.data_size)
        offset = rng.randrange(0, cfg.beat_bytes, 1 << size)
        mask = self.data_mask(size) << (8 * offset)
        while True:
            lanes = (rng.getrandbits(8 << size) << (8 * offset)) & mask
            if lanes != beat & mask:
                break
        access = f"{context}.lanes.size{size}.offset{offset}"
        await self.sba_write(
            target, addr + offset, lanes >> (8 * offset), size=size, context=f"{access}.write"
        )
        beat = (beat & ~mask) | lanes
        self.check_target_word(target, addr, beat, size=cfg.data_size, context=f"{access}.mem")
        rdata = await self.sba_read(target, addr + offset, size=size, context=f"{access}.read")
        self.check_bridge_rdata(
            target, rdata & self.data_mask(size), lanes >> (8 * offset), context=f"{access}.read"
        )
