# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A cold ``rst_ni`` returns every readable SPI host register to its reset value.

Proves that an ``rst_ni`` pulse returns INTR_STATE, INTR_ENABLE, CONTROL,
CONFIGOPTS, CSID, ERROR_ENABLE, ERROR_STATUS and EVENT_ENABLE of the OpenTitan
SPI host to the reset values of
``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc``,
with the host idle and with ``rst_ni`` asserted inside a Tx segment
(``hw/sys/sep/doc/reset_controller.adoc``, SEP Reset Controller). The reset
values are 0 for INTR_STATE, INTR_ENABLE, CONFIGOPTS, CSID, ERROR_STATUS and
EVENT_ENABLE, 0x7F for CONTROL (RX_WATERMARK) and 0x1F for ERROR_ENABLE; every
expected value comes from the generated register export.

Trials, both on every seed:

* idle: CMDINVAL is injected (COMMAND with SPEED=3), so ERROR_STATUS and
  INTR_STATE.ERROR are set, and drawn non-reset values are armed in the other
  six registers. All eight read a non-reset value before the reset.
* midseg: INTR_STATE.ERROR is set by INTR_TEST and drawn values are armed in
  INTR_ENABLE, CONTROL, CONFIGOPTS, ERROR_ENABLE and EVENT_ENABLE. CSID stays
  0 (the only valid chip select) and ERROR_STATUS stays 0. The TX FIFO holds
  the segment words plus 1 to 4 extra words, a Tx segment starts, and
  ``rst_ni`` asserts after a drawn number of sck cycles with chip select low.

After each reset the leaf waits for ``dbg_sep_reset_n_o`` (inside
``sep_base_test.pulse_rst_ni``), reads the eight registers, then runs one clean
dummy command and grades its sck cycle count and ERROR_STATUS.

Checks:
  CHK-SPI-COLDRST  per trial: every register equals its reset value on its RDL
                   field bits, and the clean command runs LEN+1 sck cycles with
                   ERROR_STATUS 0. Controls: each armed register held a
                   non-reset value (``nonreset``), and in the midseg trial
                   ``spi_cs_n_o`` is low when ``rst_ni`` asserts; a control
                   that does not hold logs CTRL-MISSING and fails.

Probes: register frontdoor over ``s_axi``; pads ``spi_cs_n_o`` and
``spi_sck_o`` (``env/sep_spi_pad_sampler.py``); ``dbg_sep_reset_n_o``.

Run mode: no_cpu (``lsu_stub_all_live``) with real fuse sense of the committed
default image; VCS only, because the leaf reads state after reset. The graded
window is open across both graded ``rst_ni`` pulses. RAND-REP: the ``rst_ni``
point, the armed values, the segment length and the extra TX words come from
``SepSeededRng`` and the run seed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_efuse_image import SepEfuseImage
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_reg_meta import SPI_CONTROLLER
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_pad_sampler import SepSpiPadSampler
from sep_base_test import _DEFAULT_EFUSE_PRELOAD, sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    CONTROL,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
    CTRL_SPIEN,
    ERR_CMDINVAL,
    ERROR_STATUS,
    INTR_ERROR,
    INTR_STATE,
    INTR_TEST,
    RESET_VALUES,
    TXDATA,
)
from seq_lib.sep_spi_host_ops import (
    DIR_DUMMY,
    DIR_TX,
    SepSpiHostOps,
    command_word,
    configopts_word,
)

TEST = "sep_spi_cold_reset_values_rand_test"
_R = SPI_CONTROLLER

# Register name -> (address, reset value, RDL field mask).
_REGS = {name: (addr, rst, _R.mask32(name)) for name, (addr, rst) in RESET_VALUES.items()}
_MIDSEG_ARMED = (
    "INTR_STATE",
    "INTR_ENABLE",
    "CONTROL",
    "CONFIGOPTS",
    "ERROR_ENABLE",
    "EVENT_ENABLE",
)

_CTRL_TX_WM_LSB = _R.field_lsb("CONTROL", "tx_watermark")
_CTRL_RX_WM_LSB = _R.field_lsb("CONTROL", "rx_watermark")
_CTRL_RX_WM_RESET = (RESET_VALUES["CONTROL"][1] & _R.field_mask("CONTROL", "rx_watermark")) >> (
    _CTRL_RX_WM_LSB
)
_ERR_EN_RESET = RESET_VALUES["ERROR_ENABLE"][1]
_CMD_SPEED_RESERVED = 3

# Bounds, in clk_i cycles or STATUS reads; each fails the check it feeds.
_SEG_BOUND_CLKS = 200_000
_POLL_READS = 64
_RELEASE_BOUND = 20_000


@pyuvm.test()
class sep_spi_cold_reset_values_rand_test(sep_base_test):
    """Every readable SPI host register returns to reset after rst_ni, idle and mid-segment."""

    required_evidence = ("CHK-SPI-COLDRST",)

    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.checks = 0
        rng = SepSeededRng(self.seed)
        draw = self._draw(rng)
        self.logger.info(
            "PLAN %s seed=%d trials=idle,midseg regs=%d tool=vcs fuse=real",
            TEST,
            self.seed,
            len(_REGS),
        )
        self.logger.info(
            "DRAW seed=%d idle_arm={%s} midseg_arm={%s} m=%d extra=%d t=%d "
            "clean_len={idle:%d,midseg:%d}",
            self.seed,
            " ".join(f"{k}=0x{v:08x}" for k, v in draw["idle"].items()),
            " ".join(f"{k}=0x{v:08x}" for k, v in draw["midseg"].items()),
            draw["m"],
            draw["extra"],
            draw["t"],
            draw["clean_len"][0],
            draw["clean_len"][1],
        )

        self.write_efuse_image(SepEfuseImage().load(_DEFAULT_EFUSE_PRELOAD))
        await self.bring_up_no_cpu()
        self.pads = SepSpiPadSampler().start()
        self.ops = SepSpiHostOps(self, clock=self.pads.now)
        try:
            await self._run(draw)
        finally:
            close_graded_window(self.logger)
            await self.pads.stop()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, self.checks)

    # ---- draws ------------------------------------------------------------
    @staticmethod
    def _configopts(rng: SepSeededRng) -> int:
        """A non-reset CONFIGOPTS: CLKDIV 1 to 3 keeps a segment short; FULLCYC stays 0."""
        return configopts_word(
            clkdiv=rng.randrange(1, 4),
            csnidle=rng.randrange(16),
            csntrail=rng.randrange(16),
            csnlead=rng.randrange(16),
            fullcyc=0,
            cpha=rng.randrange(2),
            cpol=rng.randrange(2),
        )

    @staticmethod
    def _control(rng: SepSeededRng) -> int:
        rx_wm = rng.choice([v for v in range(256) if v != _CTRL_RX_WM_RESET])
        return (
            CTRL_SPIEN
            | CTRL_OUTPUT_EN
            | (rng.randrange(1, 256) << _CTRL_TX_WM_LSB)
            | (rx_wm << _CTRL_RX_WM_LSB)
        )

    def _draw(self, rng: SepSeededRng) -> dict:
        idle = {
            "INTR_ENABLE": rng.randrange(1, 4),
            "CONTROL": self._control(rng),
            "CONFIGOPTS": self._configopts(rng),
            "CSID": rng.randrange(1, 1 << 32),
            "ERROR_ENABLE": rng.randrange(0, _ERR_EN_RESET),
            "EVENT_ENABLE": rng.randrange(1, 64),
        }
        midseg = {
            "INTR_ENABLE": rng.randrange(1, 4),
            "CONTROL": self._control(rng),
            "CONFIGOPTS": self._configopts(rng),
            "ERROR_ENABLE": rng.randrange(0, _ERR_EN_RESET),
            "EVENT_ENABLE": rng.randrange(1, 64),
        }
        m = rng.randrange(1, 5)
        return {
            "idle": idle,
            "midseg": midseg,
            "m": m,
            "extra": rng.randrange(1, 5),
            # The segment runs 8 sck cycles per byte, 4 bytes per word.
            "t": rng.randrange(1, (32 * m) // 2 + 1),
            "clean_len": (rng.randrange(0, 32), rng.randrange(0, 32)),
        }

    # ---- helpers ----------------------------------------------------------
    def _fail(self, chk: str, msg: str) -> None:
        line = f"{chk} FAIL seed={self.seed} {msg}"
        self.logger.error(line)
        raise AssertionError(line)

    def _ctrl_missing(self, msg: str) -> None:
        line = f"CTRL-MISSING seed={self.seed} {msg}"
        self.logger.error(line)
        raise AssertionError(line)

    async def _poll_reg(self, addr: int, mask: int, what: str) -> int:
        """Read ``addr`` until the ``mask`` bits are all set, at most _POLL_READS reads."""
        got = 0
        for _ in range(_POLL_READS):
            got = await self.ops.rd(addr)
            if got & mask == mask:
                return got
        self._fail("CHK-SPI-COLDRST", f"wait '{what}' expired: last=0x{got:08x}")
        return got

    async def _read_regs(self) -> dict[str, int]:
        return {name: await self.ops.rd(addr) for name, (addr, _, _) in _REGS.items()}

    async def _arm(self, values: dict[str, int]) -> None:
        for name, value in values.items():
            await self.ops.wr(_REGS[name][0], value)

    async def _wait_release(self) -> None:
        dut = cocotb.top
        for _ in range(_RELEASE_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True):
                return
        self._fail("CHK-SPI-COLDRST", "dbg_sep_reset_n_o did not read 1 after bring-up")

    async def _clean_command(self, len_field: int) -> tuple[int, int]:
        """CONTROL SPIEN=1 OUTPUT_EN=1, one dummy command; returns (sck cycles, ERROR_STATUS)."""
        await self.ops.wr(CONTROL, CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
        self.pads.set_idle_level(0)
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(len_field, direction=DIR_DUMMY))
        wins = await self.ops.wait_segment_done(self.pads, mark, bound_clks=_SEG_BOUND_CLKS)
        return wins[0].leading_edges, await self.ops.rd(ERROR_STATUS)

    def _grade(
        self,
        trial: str,
        before: dict[str, int],
        armed: tuple[str, ...],
        after: dict[str, int],
        cs_low: int,
        clean: tuple[int, int],
        clean_len: int,
    ) -> None:
        nonreset = [n for n in armed if (before[n] ^ _REGS[n][1]) & _REGS[n][2]]
        for name, (_, rst, mask) in _REGS.items():
            fc = field_compare(after[name], rst, mask)
            self.logger.info(
                "COLDRST-REG LOG seed=%d trial=%s reg=%s armed=0x%08x %s",
                self.seed,
                trial,
                name,
                before[name],
                fc.fields(),
            )
        mismatch = [n for n in _REGS if not field_compare(after[n], _REGS[n][1], _REGS[n][2]).ok]
        cycles, err = clean
        exp_cycles = clean_len + 1
        line = (
            f"trial={trial} cs_low_at_reset={cs_low} regs={len(_REGS)} "
            f"nonreset={len(nonreset)} mismatch={len(mismatch)} "
            f"clean_cmd={int(cycles == exp_cycles and err == 0)} "
            f"clean_cycles={cycles}/{exp_cycles} clean_err_status=0x{err:02x}"
        )
        if mismatch or cycles != exp_cycles or err != 0:
            self._fail("CHK-SPI-COLDRST", f"{line} regs_not_reset={','.join(mismatch) or '-'}")
        self.checks += 1
        self.logger.info("CHK-SPI-COLDRST PASS seed=%d %s", self.seed, line)

    # ---- scenario ---------------------------------------------------------
    async def _run(self, draw: dict) -> None:
        await self._wait_release()
        es = await self.ops.rd(ERROR_STATUS)
        ist = await self.ops.rd(INTR_STATE)
        if es != 0 or ist != 0:
            self._ctrl_missing(f"bring-up ERROR_STATUS=0x{es:08x} INTR_STATE=0x{ist:08x}")

        open_graded_window(TEST, self.logger)

        # Trial 1, idle: CMDINVAL sets ERROR_STATUS and INTR_STATE.ERROR, then the
        # other six registers are armed.
        await self.ops.wr(CONTROL, CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
        await self.ops.issue_command(command_word(0, speed=_CMD_SPEED_RESERVED))
        await self._poll_reg(ERROR_STATUS, ERR_CMDINVAL, "ERROR_STATUS.CMDINVAL=1")
        await self._poll_reg(INTR_STATE, INTR_ERROR, "INTR_STATE.ERROR=1")
        await self._arm(draw["idle"])
        before = await self._read_regs()
        armed = tuple(_REGS)
        not_armed = [n for n in armed if not (before[n] ^ _REGS[n][1]) & _REGS[n][2]]
        if not_armed:
            self._ctrl_missing(f"trial=idle registers at reset before rst_ni: {not_armed}")
        rst = await self.pulse_rst_ni(release_bound=_RELEASE_BOUND)
        after = await self._read_regs()
        self.logger.info("COLDRST-RST LOG seed=%d trial=idle %s", self.seed, rst)
        clean = await self._clean_command(draw["clean_len"][0])
        self._grade("idle", before, armed, after, 0, clean, draw["clean_len"][0])

        # Trial 2, midseg: six registers armed, rst_ni inside a Tx segment.
        await self.ops.wr(INTR_TEST, INTR_ERROR)
        await self._poll_reg(INTR_STATE, INTR_ERROR, "INTR_STATE.ERROR=1 after INTR_TEST")
        await self._arm(draw["midseg"])
        before = await self._read_regs()
        not_armed = [n for n in _MIDSEG_ARMED if not (before[n] ^ _REGS[n][1]) & _REGS[n][2]]
        if not_armed:
            self._ctrl_missing(f"trial=midseg registers at reset before rst_ni: {not_armed}")
        if before["CSID"] != 0 or before["ERROR_STATUS"] != 0:
            self._ctrl_missing(
                f"trial=midseg CSID=0x{before['CSID']:08x} "
                f"ERROR_STATUS=0x{before['ERROR_STATUS']:08x} before the segment"
            )
        m, extra = draw["m"], draw["extra"]
        for i in range(m + extra):
            st = await self.ops.read_status()
            if st.txfull:
                self._ctrl_missing(f"trial=midseg TXFULL=1 before word {i} of {m + extra}")
            await self.ops.wr(TXDATA, 0xC0DE_0000 | i)
        cpol = (draw["midseg"]["CONFIGOPTS"] >> _R.field_lsb("CONFIGOPTS", "cpol")) & 1
        self.pads.set_idle_level(cpol)
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(4 * m - 1, direction=DIR_TX))
        edges = await self.pads.wait_leading_edges(draw["t"], mark, _SEG_BOUND_CLKS)
        cs_low = int(self.pads.cs_low())
        self.logger.info(
            "COLDRST-POINT LOG seed=%d t=%d edges=%d cs_low=%d clk=%d",
            self.seed,
            draw["t"],
            edges,
            cs_low,
            self.pads.now(),
        )
        if not cs_low:
            self._ctrl_missing(f"trial=midseg spi_cs_n_o high at the rst_ni point t={draw['t']}")
        rst = await self.pulse_rst_ni(release_bound=_RELEASE_BOUND)
        after = await self._read_regs()
        self.logger.info("COLDRST-RST LOG seed=%d trial=midseg %s", self.seed, rst)
        clean = await self._clean_command(draw["clean_len"][1])
        self._grade("midseg", before, _MIDSEG_ARMED, after, cs_low, clean, draw["clean_len"][1])
