# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI host pad output enables: no pad driven in reset or with OUTPUT_EN=0; data lanes only in a frame.

Contract (``doc/integrator/src/smu-sep.adoc``, "SEP SPI Host Pin Assignment",
the output-enable rules; ``spi_controller.adoc``, CONTROL.OUTPUT_EN, reset 0):

* no SPI pad is driven (``spi_cs_oe_o``, ``spi_sck_oe_o`` and ``spi_sd_oe_o[3:0]``
  all 0) from a cold reset until software sets CONTROL.OUTPUT_EN;
* with CONTROL.OUTPUT_EN = 0 no SPI pad is driven, also while SPIEN = 1 and the
  host runs a command;
* a data lane is driven only while chip select is asserted;
* with CONTROL.OUTPUT_EN = 1, ``spi_cs_oe_o`` and ``spi_sck_oe_o`` are 1 with
  chip select high or low:
  ``vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/data/spi_host.hjson:222-224``
  (CONTROL.OUTPUT_EN) "Enable the SPI host output buffers for the sck, csb, and
  sd lines." The pin-assignment text narrows only the data lanes.

A per-clock sampler reads ``rst_ni``, ``dbg_sep_reset_n_o``, ``spi_cs_n_o``
and the output-enable taps ``spi_cs_oe_o``, ``spi_sck_oe_o`` and
``spi_sd_oe_o`` of ``tb_top`` (docs/SEP_TB_ARCH.adoc) on every rising edge of
``clk_i``, in the read-only phase. It drives nothing. The leaf names the window
each sample belongs to; a sample outside every window is not graded.

Legs, in this order on every seed:

1. traffic A: OUTPUT_EN = 1, SPIEN = 1; frames TX x1, TX x2, TX x4, RX x1,
   RX x4 and a CSAAT chain (TX x1, dummy, RX x4), in a seeded order, with
   seeded lengths and TX data; the leaf waits for each command to end and
   reads the RX words. The last frame is a long TX x1 segment that the cold
   reset cuts.
2. cold reset: ``rst_ni`` asserts after a drawn number of sck rises of that
   segment (``sep_base_test.pulse_rst_ni``, real fuse sense). The window opens
   at the first sample with the SEP reset asserted (``dbg_sep_reset_n_o`` = 0)
   and closes before the first CONTROL write after the release and fuse sense.
3. OUTPUT_EN = 0: CONTROL = SPIEN only, a TXDATA word queued and a TX command
   issued; the window closes after STATUS shows ACTIVE=0 and CMDQD=0.
4. traffic B: as traffic A with its own seeded order, without the reset frame.

Checks:
  CHK-SPI-OE-OFF      every sample of the OUTPUT_EN = 0 window reads all output
                      enables 0. Control: a frontdoor STATUS read inside the
                      window shows ACTIVE=1 (the host runs the command, so only
                      the OUTPUT_EN gate keeps the pads undriven).
  CHK-SPI-OE-RESET    VCS only: every sample of the cold-reset window reads all
                      output enables 0, and an X or Z on an output enable fails.
                      On Verilator (2-state) the leaf logs ``OBS-SPI-OE-RESET``
                      with the same counts and grades nothing. Controls (both
                      simulators): the last sample before ``rst_ni`` falls reads
                      ``spi_cs_oe_o``, ``spi_sck_oe_o`` and ``spi_sd_oe_o[0]`` = 1
                      with chip select low (``CTL-SPI-OE-RESET`` line), and the
                      SEP reset asserts in the hold.
  CHK-SPI-OE-CS-HIGH  every traffic sample with chip select high, also the
                      clocks right after chip select rises and the gaps between
                      commands, reads ``spi_sd_oe_o`` = 0. Control: the count of
                      traffic samples with chip select low and ``spi_sd_oe_o[0]``
                      = 1 is above zero, and samples after a chip-select rise
                      exist. The same samples, from the end of the CONTROL write
                      that sets OUTPUT_EN (and the CSID and CONFIGOPTS writes
                      after it), read ``spi_cs_oe_o`` = 1 and ``spi_sck_oe_o`` = 1
                      (``spi_host.hjson:222-224``). Control: the
                      OUTPUT_EN = 0 window (CHK-SPI-OE-OFF) read both 0 on
                      every sample, and the graded count is above zero.
  CHK-SPI-OE-CS-LOW   every traffic sample with chip select low reads
                      ``spi_cs_oe_o`` = 1 and ``spi_sck_oe_o`` = 1. Control: the
                      chip-select-low sample count is above zero.

An X or Z on a graded sample is a violation. Each check logs its sample count
and its violation count.

Run mode: no_cpu (``lsu_stub_all_live``) with real fuse sense of the committed
default image; Verilator and VCS. RAND-REP: frame orders, lengths, TX data,
CONFIGOPTS timing, the reset point and the post-release wait come from
``SepSeededRng`` and the run seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_efuse_image import SepEfuseImage
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_lane_responder import spi_lane_fcov
from sep_base_test import _DEFAULT_EFUSE_PRELOAD, sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    CONTROL,
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
    CTRL_SPIEN,
)
from seq_lib.sep_spi_host_ops import (
    DIR_DUMMY,
    DIR_RX,
    DIR_TX,
    SPEED_DUAL,
    SPEED_QUAD,
    SPEED_STD,
    SepSpiHostOps,
    command_word,
    configopts_word,
)

TEST = "sep_spi_pad_oe_rules_test"

# Expected output-enable levels of each rule; the step-14 MUTATION hooks edit
# one of these:
#   OUTPUT_EN = 0 window: EXP_OFF = (1, 1, 0xF)   -> CHK-SPI-OE-OFF fails
#   cold-reset window:    EXP_RESET = (1, 1, 0xF) -> CHK-SPI-OE-RESET fails (VCS)
#   chip select high:     EXP_CS_HIGH_SD = 0x1    -> CHK-SPI-OE-CS-HIGH fails
#   chip select low:      EXP_CS_LOW = (0, 0)     -> CHK-SPI-OE-CS-LOW fails
#   chip select high:     EXP_CS_HIGH_CS_SCK = (0, 0) -> CHK-SPI-OE-CS-HIGH fails
EXP_OFF = (0, 0, 0x0)  # (cs_oe, sck_oe, sd_oe[3:0])
EXP_RESET = (0, 0, 0x0)
EXP_CS_HIGH_SD = 0x0  # sd_oe[3:0] while chip select is high
EXP_CS_LOW = (1, 1)  # (cs_oe, sck_oe) while chip select is low
EXP_CS_HIGH_CS_SCK = (1, 1)  # (cs_oe, sck_oe) while chip select is high, OUTPUT_EN = 1

SPEED = {1: SPEED_STD, 2: SPEED_DUAL, 4: SPEED_QUAD}
FRAME_KINDS = ("tx1", "tx2", "tx4", "rx1", "rx4", "chain")
AFTER_RISE_CLKS = 8  # chip-select-high samples this close to a rise are logged apart
FIRST_VIOLATIONS = 4

# Bounds, in STATUS reads or clk_i cycles; each fails the leg it feeds.
POLL_READS = 4_000
ACTIVE_READS = 16
SCK_RISE_BOUND = 200_000
TAIL_CLKS = 64


def _val(sig) -> int | None:
    v = sig.value
    return int(v) if v.is_resolvable else None


@dataclass
class _Win:
    """Counters of one graded window."""

    name: str
    samples: int = 0
    violations: int = 0
    xz: int = 0
    first: list[str] = field(default_factory=list)
    cs_low: int = 0
    cs_high: int = 0
    cs_high_after_rise: int = 0
    cs_rises: int = 0
    sd0_high_cs_low: int = 0
    cs_low_violations: int = 0
    cs_high_violations: int = 0
    cs_high_cs_sck: int = 0
    cs_high_cs_sck_violations: int = 0

    def violate(self, clk: int, text: str) -> None:
        self.violations += 1
        if len(self.first) < FIRST_VIOLATIONS:
            self.first.append(f"clk{clk}:{text}")


class _OeSampler:
    """Per-clock sampler of the SPI output enables; grades each sample of the open window."""

    def __init__(self) -> None:
        dut = cocotb.top
        self.dut = dut
        self.clk = 0
        self.mode: str | None = None  # "traffic", "reset", "off" or None
        self.reset_armed = False  # traffic: watch for rst_ni falling
        # traffic: grade cs_oe and sck_oe with chip select high (OUTPUT_EN = 1 written)
        self.cs_sck_high = False
        self.lag_samples = 0  # rst_ni low, SEP reset not yet asserted
        self.lag_oe: list[str] = []
        self.pre_reset: tuple | None = None  # last traffic sample before rst_ni fell
        self.wins = {name: _Win(name) for name in ("traffic", "reset", "off")}
        self.sck_rises_cs_low = 0
        self._last: tuple | None = None
        self._cs_prev: int | None = None
        self._sck_prev: int | None = None
        self._since_rise = 1 << 30
        self._task = None

    def start(self) -> _OeSampler:
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.clk += 1
            rst = _val(dut.rst_ni)
            sep_rst_n = _val(dut.dbg_sep_reset_n_o)
            cs = _val(dut.spi_cs_n_o)
            sck = _val(dut.spi_sck_o)
            cs_oe = _val(dut.spi_cs_oe_o)
            sck_oe = _val(dut.spi_sck_oe_o)
            sd_oe = _val(dut.spi_sd_oe_o)
            sample = (rst, sep_rst_n, cs, cs_oe, sck_oe, sd_oe)
            if cs == 0 and sck == 1 and self._sck_prev == 0:
                self.sck_rises_cs_low += 1
            if cs == 1 and self._cs_prev == 0:
                self._since_rise = 0
            elif cs == 1:
                self._since_rise += 1
            self._sck_prev = sck
            self._cs_prev = cs
            if self.mode == "traffic" and self.reset_armed and rst == 0:
                self.pre_reset = self._last
                self.reset_armed = False
                self.mode = "reset_lag"
            if self.mode == "reset_lag":
                if sep_rst_n == 0:
                    self.mode = "reset"
                else:
                    self.lag_samples += 1
                    if len(self.lag_oe) < FIRST_VIOLATIONS:
                        self.lag_oe.append(f"cs_oe={cs_oe} sck_oe={sck_oe} sd_oe={sd_oe}")
            if self.mode == "traffic":
                self._grade_traffic(sample)
            elif self.mode in ("reset", "off"):
                exp = EXP_RESET if self.mode == "reset" else EXP_OFF
                self._all_off(self.wins[self.mode], sample, exp)
            self._last = sample

    def _all_off(self, win: _Win, sample: tuple, exp: tuple[int, int, int]) -> None:
        _, _, _, cs_oe, sck_oe, sd_oe = sample
        win.samples += 1
        if None in (cs_oe, sck_oe, sd_oe):
            win.xz += 1
        if (cs_oe, sck_oe, sd_oe) != exp:
            win.violate(self.clk, f"cs_oe={cs_oe} sck_oe={sck_oe} sd_oe={sd_oe}")

    def _grade_traffic(self, sample: tuple) -> None:
        _, _, cs, cs_oe, sck_oe, sd_oe = sample
        win = self.wins["traffic"]
        win.samples += 1
        if cs is None:
            win.xz += 1
            win.violate(self.clk, "spi_cs_n_o=X")
            return
        if cs == 1:
            win.cs_high += 1
            if self._since_rise == 0:
                win.cs_rises += 1
            if self._since_rise < AFTER_RISE_CLKS:
                win.cs_high_after_rise += 1
            if sd_oe is None:
                win.xz += 1
            if sd_oe != EXP_CS_HIGH_SD:
                win.cs_high_violations += 1
                win.violate(self.clk, f"cs_n=1 sd_oe={sd_oe}")
            if self.cs_sck_high:
                win.cs_high_cs_sck += 1
                if cs_oe is None or sck_oe is None:
                    win.xz += 1
                if (cs_oe, sck_oe) != EXP_CS_HIGH_CS_SCK:
                    win.cs_high_cs_sck_violations += 1
                    win.violate(self.clk, f"cs_n=1 cs_oe={cs_oe} sck_oe={sck_oe}")
        else:
            win.cs_low += 1
            if sd_oe is not None and sd_oe & 1:
                win.sd0_high_cs_low += 1
            if cs_oe is None or sck_oe is None:
                win.xz += 1
            if (cs_oe, sck_oe) != EXP_CS_LOW:
                win.cs_low_violations += 1
                win.violate(self.clk, f"cs_n=0 cs_oe={cs_oe} sck_oe={sck_oe}")


@dataclass(frozen=True)
class _Seg:
    """One command segment: ``length`` is bytes, or clocks for a dummy segment."""

    lanes: int
    direction: int
    length: int
    data: bytes = b""


class _Draw:
    """Every draw of the leaf, from the run seed."""

    def __init__(self, seed: int) -> None:
        r = SepSeededRng(seed)
        self.seed = seed
        self.configopts = configopts_word(
            clkdiv=r.randrange(1, 4),
            csnidle=r.randrange(0, 4),
            csntrail=r.randrange(0, 4),
            csnlead=r.randrange(0, 4),
        )
        self.order_a = list(FRAME_KINDS)
        r.shuffle(self.order_a)
        self.order_b = list(FRAME_KINDS)
        r.shuffle(self.order_b)
        self.frames = {
            leg: {kind: self._frame(r, kind) for kind in FRAME_KINDS} for leg in ("a", "b")
        }
        self.reset_tx = bytes(r.getrandbits(8) for _ in range(r.randrange(16, 33)))
        self.reset_t = r.randrange(1, (len(self.reset_tx) * 8) // 2 + 1)
        self.reset_tail = r.randrange(0, 64)
        self.off_tx = bytes(r.getrandbits(8) for _ in range(r.randrange(8, 33)))

    @staticmethod
    def _frame(r: SepSeededRng, kind: str) -> list[_Seg]:
        """The segments of one frame of ``kind``."""
        if kind.startswith("tx"):
            data = bytes(r.getrandbits(8) for _ in range(r.randrange(1, 9)))
            return [_Seg(int(kind[2:]), DIR_TX, len(data), data)]
        if kind.startswith("rx"):
            return [_Seg(int(kind[2:]), DIR_RX, r.randrange(1, 9))]
        return [
            _Seg(1, DIR_TX, 1, bytes([r.getrandbits(8)])),
            _Seg(4, DIR_DUMMY, r.randrange(2, 7)),
            _Seg(4, DIR_RX, 4),
        ]


@pyuvm.test()
class sep_spi_pad_oe_rules_test(sep_base_test):
    """SPI pad output enables in reset, with OUTPUT_EN = 0, and around chip select."""

    required_evidence: tuple[str, ...] = (
        "CHK-SPI-OE-OFF",
        "CHK-SPI-OE-CS-HIGH",
        "CHK-SPI-OE-CS-LOW",
    )

    # ---- helpers ----------------------------------------------------------
    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, chk: str, line: str) -> None:
        msg = f"CTRL-MISSING {chk} seed={self.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.seed, line)
        self.checks += 1

    @staticmethod
    def _win_line(win: _Win) -> str:
        return (
            f"window={win.name} samples={win.samples} violations={win.violations} "
            f"xz={win.xz} first={';'.join(win.first) or '-'}"
        )

    async def _done(self, what: str) -> None:
        await self.ops.poll_status(
            lambda s: s.active == 0 and s.cmdqd == 0, POLL_READS, f"{what}: ACTIVE=0 and CMDQD=0"
        )

    async def _push_tx(self, data: bytes) -> None:
        """One TX segment's bytes in its own TXDATA words (ByteOrder = 1, last word padded)."""
        padded = data + b"\0" * (-len(data) % 4)
        for j in range(0, len(padded), 4):
            await self.ops.push_tx(int.from_bytes(padded[j : j + 4], "little"))

    async def _frame(self, segments: list[_Seg], what: str) -> None:
        """Issue one frame (CSAAT on every segment but the last), wait for it, read RX words."""
        for seg in segments:
            if seg.direction == DIR_TX:
                await self._push_tx(seg.data)
        for i, seg in enumerate(segments):
            csaat = int(i < len(segments) - 1)
            await self.ops.issue_command(
                command_word(
                    seg.length - 1, speed=SPEED[seg.lanes], direction=seg.direction, csaat=csaat
                )
            )
        await self._done(what)
        if any(seg.direction == DIR_RX for seg in segments):
            await self.ops.drain_rx()

    async def _traffic(self, leg: str, order: list[str]) -> None:
        for kind in order:
            await self._frame(self.draw.frames[leg][kind], f"traffic {leg} {kind}")

    async def _enable(self, ctrl: int) -> None:
        await self.ops.wr(CONTROL, CTRL_RESET | ctrl)
        await self.ops.wr(CSID, 0)
        await self.ops.write_configopts(self.draw.configopts)

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.checks = 0
        sim = str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        self.four_state = "vcs" in sim
        if self.four_state:
            self.required_evidence = (*type(self).required_evidence, "CHK-SPI-OE-RESET")
        self.draw = d = _Draw(self.seed)
        self.logger.info(
            "PLAN %s seed=%d legs=traffic_a,reset,output_en_off,traffic_b sim=%s "
            "reset_window=%s fuse=real",
            TEST,
            self.seed,
            sim or "-",
            "graded" if self.four_state else "observed",
        )
        self.logger.info(
            "DRAW seed=%d configopts=0x%08x order_a=%s order_b=%s reset_tx_bytes=%d "
            "reset_t=%d reset_tail=%d off_tx_bytes=%d",
            self.seed,
            d.configopts,
            ",".join(d.order_a),
            ",".join(d.order_b),
            len(d.reset_tx),
            d.reset_t,
            d.reset_tail,
            len(d.off_tx),
        )

        self.write_efuse_image(SepEfuseImage().load(_DEFAULT_EFUSE_PRELOAD))
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.ops = SepSpiHostOps(self)
        self.oe = _OeSampler().start()
        try:
            await self._run()
        finally:
            close_graded_window(self.logger)
            await self.oe.stop()
        self.result_pass(TEST, self.seed, self.checks)

    async def _run(self) -> None:
        d = self.draw
        oe = self.oe
        clk = cocotb.top.clk_i
        open_graded_window(TEST, self.logger)

        # Leg 1: traffic A, then the long TX x1 segment that the cold reset cuts.
        oe.mode = "traffic"
        await self._enable(CTRL_SPIEN | CTRL_OUTPUT_EN)
        oe.cs_sck_high = True
        await self._traffic("a", d.order_a)
        await self._push_tx(d.reset_tx)
        rises0 = oe.sck_rises_cs_low
        await self.ops.issue_command(
            command_word(len(d.reset_tx) - 1, speed=SPEED_STD, direction=DIR_TX)
        )
        for _ in range(SCK_RISE_BOUND):
            if oe.sck_rises_cs_low - rises0 >= d.reset_t:
                break
            await RisingEdge(clk)
        else:
            self._ctrl_missing("CHK-SPI-OE-RESET", f"{d.reset_t} sck rises not seen")

        # Leg 2: cold reset inside the segment.
        oe.reset_armed = True
        rst = await self.pulse_rst_ni()
        await ClockCycles(clk, d.reset_tail)
        oe.mode = None
        oe.cs_sck_high = False
        pre = oe.pre_reset
        win = oe.wins["reset"]
        ctl = (
            f"pre_reset_cs_n={pre[2] if pre else '-'} cs_oe={pre[3] if pre else '-'} "
            f"sck_oe={pre[4] if pre else '-'} sd_oe={pre[5] if pre else '-'} "
            f"sck_rises={oe.sck_rises_cs_low - rises0} "
            f"sep_reset_n_at_hold_end={rst['sep_reset_n_at_hold_end']} "
            f"rst_lag_samples={oe.lag_samples} rst_lag_oe={'|'.join(oe.lag_oe) or '-'}"
        )
        self.logger.info("CTL-SPI-OE-RESET LOG seed=%d %s", self.seed, ctl)
        live = pre is not None and pre[2] == 0 and pre[3] == 1 and pre[4] == 1 and (pre[5] or 0) & 1
        if not live or rst["sep_reset_n_at_hold_end"] != 0 or win.samples == 0:
            self._ctrl_missing("CHK-SPI-OE-RESET", f"{ctl} {self._win_line(win)}")
        line = f"{self._win_line(win)} sim={'vcs' if self.four_state else 'verilator'}"
        if self.four_state:
            if win.violations or win.xz:
                self._fail("CHK-SPI-OE-RESET", line)
            self._pass("CHK-SPI-OE-RESET", line)
            await spi_lane_fcov(TEST, "oe", oe_win=0)
        else:
            self.logger.info("OBS-SPI-OE-RESET LOG seed=%d %s", self.seed, line)

        # Leg 3: OUTPUT_EN = 0 with SPIEN = 1, a TXDATA word and a TX command.
        oe.mode = "off"
        await self._enable(CTRL_SPIEN)
        await self._push_tx(d.off_tx)
        await self.ops.issue_command(
            command_word(len(d.off_tx) - 1, speed=SPEED_STD, direction=DIR_TX)
        )
        active = 0
        for _ in range(ACTIVE_READS):
            st = await self.ops.read_status()
            if st.active:
                active = 1
                break
        await self._done("OUTPUT_EN=0 command")
        await ClockCycles(clk, TAIL_CLKS)
        oe.mode = None
        win = oe.wins["off"]
        line = f"{self._win_line(win)} status_active_in_window={active} tx_bytes={len(d.off_tx)}"
        if not active or win.samples == 0:
            self._ctrl_missing("CHK-SPI-OE-OFF", line)
        if win.violations or (self.four_state and win.xz):
            self._fail("CHK-SPI-OE-OFF", line)
        self._pass("CHK-SPI-OE-OFF", line)
        await spi_lane_fcov(TEST, "oe", oe_win=1)

        # Leg 4: traffic B.
        oe.mode = "traffic"
        await self._enable(CTRL_SPIEN | CTRL_OUTPUT_EN)
        oe.cs_sck_high = True
        await self._traffic("b", d.order_b)
        await ClockCycles(clk, TAIL_CLKS)
        oe.mode = None
        oe.cs_sck_high = False
        close_graded_window(self.logger)

        win = oe.wins["traffic"]
        off = oe.wins["off"]
        line = (
            f"cs_high_samples={win.cs_high} cs_high_after_rise={win.cs_high_after_rise} "
            f"cs_rises={win.cs_rises} sd_oe_violations={win.cs_high_violations} "
            f"cs_sck_samples={win.cs_high_cs_sck} "
            f"expect_cs_sck_oe={EXP_CS_HIGH_CS_SCK} "
            f"cs_sck_oe_violations={win.cs_high_cs_sck_violations} "
            f"control_sd0_high_cs_low={win.sd0_high_cs_low} "
            f"control_off_samples={off.samples} control_off_violations={off.violations} "
            f"xz={win.xz} first={';'.join(win.first) or '-'}"
        )
        if (
            win.sd0_high_cs_low == 0
            or win.cs_high_after_rise == 0
            or win.cs_high_cs_sck == 0
            or off.samples == 0
            or off.violations
        ):
            self._ctrl_missing("CHK-SPI-OE-CS-HIGH", line)
        if win.cs_high_violations or win.cs_high_cs_sck_violations or (self.four_state and win.xz):
            self._fail("CHK-SPI-OE-CS-HIGH", line)
        self._pass("CHK-SPI-OE-CS-HIGH", line)
        await spi_lane_fcov(TEST, "oe", oe_win=2)

        line = (
            f"cs_low_samples={win.cs_low} cs_sck_oe_violations={win.cs_low_violations} "
            f"xz={win.xz} first={';'.join(win.first) or '-'}"
        )
        if win.cs_low == 0:
            self._ctrl_missing("CHK-SPI-OE-CS-LOW", line)
        if win.cs_low_violations or (self.four_state and win.xz):
            self._fail("CHK-SPI-OE-CS-LOW", line)
        self._pass("CHK-SPI-OE-CS-LOW", line)
        await spi_lane_fcov(TEST, "oe", oe_win=3)
