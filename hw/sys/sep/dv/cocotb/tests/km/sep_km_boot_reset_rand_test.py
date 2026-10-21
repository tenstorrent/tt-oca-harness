# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM boot after warm and cold resets on the shipped ROM build: boot flush, scrambler keep, order.

no_cpu / lsu_stub_all_live / real fuse sense / +esrc_noise_force /
+km_rom_hex=rom_main_default.rom.parhex (vehicle HOST-DEFAULT: ``rom_main`` built
with the shipped defaults ``KM_BOOT_WIPE=1 KM_UNREC_WIPE=1``). RAND-REP:
``SepSeededRng`` from the run seed draws the reset points and their order, the
point parameters c, j and r, the stale word count w, the stale and partial words
and the spin image; every draw is logged as ``DRAW``. Contract: VPLAN 7.26,
``docs/test_contracts/key_manager.adoc``.

The testbench LSU master is the SEP host. It reaches the KM only through the
``km_mailbox_sep`` window. Every frame is built here (``CMD_SEQ_NUM`` from the
command model e, the CRC-8/ROHC and CRC-32C goldens of ``env/sep_crc_golden.py``)
and every response frame is read word by word after a bounded wait on
``SEP_STATUS.outbound_depth``. Spec constants, frame builders and draws are in
``sep_km_boot_reset_rand_plan.py``; the source of each value is
``hw/ip/key_manager/doc/firmware.adoc`` and ``km_mailbox_sep.adoc``.

Probes: ``HOST-MBX`` (``SEP_STATUS``, ``SEP_READ_DATA``, ``SEP_IRQ_STATUS``),
``KM-ISO`` (the three KM isolated probes), ``KM-COUNT`` (``km_rom_req_count_o``),
``dbg_sep_reset_n_o`` (in ``pulse_rst_ni``) and the read-only tap ``KM-CSR``
(``km_csr_cold_boot_done_o``, ``km_csr_scrambler_key_wr_count_o``,
``km_csr_scrambler_ctrl_o``), and ``KM-AXIV`` (``km_cpu_axi_valid_o``, the KM
CPU AXI master valids, and ``km_cpu_rst_n_o``, the KM CPU reset). Injects: none.
Every reset is a legal host stimulus: ``SW_RESET_N`` bit 0 for a warm reset,
``rst_ni`` for the cold resets.

Checks:
  CHK-WIPE-READY  every boot of the leaf (two cold, five warm) puts the
                  RESP_KM_READY header in the outbound FIFO within READY_BOUND_CLK
                  clocks of the release; a boot that misses the bound fails the
                  leaf at that boot
  CHK-BOOT-ORDER  at both cold boots COLD_BOOT_DONE reads 0 while the KM is held
                  and rises before the first host read that shows the READY word
  CHK-BOOT-FLUSH  at each warm reset of the warm-reset leg: the FIFOs keep their
                  words while the KM is held (every stale write OKAY, inbound depth
                  w, outbound depth as before the reset); after the release the
                  outbound depth reaches 1 with the READY header, the inbound depth
                  reads 0 and the next frame answers the first command
  CHK-SCR-KEEP    a cold boot writes SCRAMBLER_KEY at least once, a warm boot 0
                  times, and SCRAMBLER_CTRL enable and lock read 1 after every boot
  CHK-FWSIZE      CMD_SRAM_EXEC returns -7 with no argument after the cold reset
                  and after the next warm reset
  CHK-SRAM-VER    CMD_SRAM_VER returns -1 with no argument with an image stored
  CHK-RST-AXI-VALID
                  at each AXI reset point (rst_ni driven low in the half clock
                  of a pending KM CPU read, then of a pending write) the three
                  KM CPU AXI valids read 0 in the first sample with the KM CPU
                  reset at 0

Controls: CTRL-RST-AXI-PENDING (the point's valid reads 1 in the sample before
the KM CPU reset reads 0); CHK-SEQ0 (``control=1``: RESP_KM_READY at response sequence 0 and the
first command at sequence 0 answered with success at response sequence 1, after
the cold-boot reference and after each warm reset of the warm-reset leg); the
CMD_SRAM_EXEC success with the image stored (``control_warm_exec`` of
CHK-FWSIZE); the confirmation and the handover flush of the image load
(``stored`` of CHK-SRAM-VER); the SCRAMBLER_KEY writes of the cold-boot
reference (``control_n_cold`` of each warm CHK-SCR-KEEP line). COLD_BOOT_DONE at
a warm boot is logged as ``OBS-BOOT-ORDER-WARM`` with ``control=1``.

The procedure steps that serve only planned checkers do not run: the witnesses
and the resident state (steps 3 to 6), the witness reads and
CMD_ABR_SK_TRANSFER of step 12, the ``KM-VALID``, ``KM-KPV`` and ``KM-BUS``
parts of step 13, the KPV reads of step 2, and the CMD_OTP_READ_LOCK_COLD
commands of steps 14, 16, 19 and 20.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, Timer
from env import sep_km_img_h as imgh
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_PROD
from env.sep_fcov_gate import close_graded_window, open_graded_window
from km import sep_km_boot_reset_rand_plan as pl
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import (
    KM_IRQ_FLUSHED_BY_KM,
    KM_MBOX_BASE,
    KM_MBOX_DEPTH,
    KM_MBOX_IRQ_STATUS,
    KM_MBOX_READ_DATA,
    KM_MBOX_STATUS,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
    KM_STATUS_INBOUND_DEPTH_LSB,
    KM_STATUS_INBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_DEPTH_LSB,
    KM_STATUS_OUTBOUND_DEPTH_MASK,
    RESP_OKAY,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_RESET_DEFAULT, SepSwReset

TEST = pl.TEST
ROM_HEX = "rom_main_default.rom.parhex"

# CHK-WIPE-READY bound: clocks from the completed release write to the host read
# that shows the READY word. A test parameter; the leaf logs it with the boot
# clocks of every boot.
READY_BOUND_CLK = 4_000_000

# Other bounded waits. Each expiry fails the leaf with a named message.
SEP_RESET_BOUND = 20_000  # clocks for dbg_sep_reset_n_o to read 1
HELD_BOUND_CLK = 20_000  # clocks for the KM to read held after the park
HELD_GAP = 32  # clocks between two km_rom_req_count_o samples
POLL = 20  # clocks between two status polls
RESP_POLLS = 50_000  # polls for one response word
INBOUND_POLLS = 20_000  # polls for inbound FIFO room
DEPTH_POLLS = 50_000  # polls for a point depth (inbound 0, outbound min(6r, 16))
FLUSH_POLLS = 50_000  # polls for FLUSHED_BY_KM after the image stream
POP_MAX_WORDS = 64  # words one pop reads at most
FRAME_MAX_PLEN = 8  # payload words of the longest frame this leaf reads
AXI_ARM_BOUND = 200_000  # clocks from the KM release to a pending request of the point
AXI_RST_BOUND = 16  # clocks from the rst_ni drive to the KM CPU reset reading 0

# KM-AXIV bits of km_cpu_axi_valid_o: 2 ar_valid, 1 aw_valid, 0 w_valid. The AXI
# reset points: the read point arms on ar_valid, the write point on aw_valid or
# w_valid.
AXI_POINTS = (("read", 0b100), ("write", 0b011))

# The boots of one leaf: the cold-boot reference, three warm resets of the
# warm-reset leg, and the warm, cold and warm boots of the cold-domain leg.
N_BOOTS = 1 + 3 + 3


def _a(value: int | None) -> str:
    return "none" if value is None else f"0x{value & 0xFFFF_FFFF:08x}"


class _Stop(Exception):
    """A boot or a frame left the protocol state unknown; the failing check is recorded."""


@dataclass(frozen=True)
class _Frame:
    seq: int
    rid: int
    plen: int
    payload: tuple[int, ...]
    crc_ok: bool
    words: tuple[int, ...]


@dataclass
class _Boot:
    tag: str
    kind: str
    word: int
    ready_ok: bool
    depth: int
    in_after: int
    boot_clk: int
    ready_cycle: int
    rise_cycle: int | None
    scr_count0: int


class _Watch:
    """Clock counter and the COLD_BOOT_DONE rise (KM-CSR), sampled in ReadOnly every clock."""

    def __init__(self, test: sep_base_test) -> None:
        self.test = test
        self.clk = cocotb.top.clk_i
        self.cbd = cocotb.top.km_csr_cold_boot_done_o
        self.cyc = 0
        self.rise: int | None = None
        self._armed = False

    def start(self) -> None:
        cocotb.start_soon(self._run())

    def arm(self) -> None:
        self.rise = None
        self._armed = True

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            self.cyc += 1
            # An unknown flag reads 0, so a missing rise fails CHK-BOOT-ORDER.
            if self._armed and self.test.rd(self.cbd, allow_unknown=True):
                self.rise = self.cyc
                self._armed = False


@pyuvm.test()
class sep_km_boot_reset_rand_test(sep_base_test):
    """Boot flush, scrambler keep, boot order and stored-image size across KM resets."""

    required_evidence = (
        "CHK-WIPE-READY",
        "CHK-BOOT-ORDER",
        "CHK-BOOT-FLUSH",
        "CHK-SCR-KEEP",
        "CHK-FWSIZE",
        "CHK-SRAM-VER",
        "CHK-RST-AXI-VALID",
        "CHK-SEQ0",
    )

    # ------------------------------------------------------------------ main

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.plan = pl.BootResetPlan(seed)
        for line in self.plan.draw_lines():
            self.logger.info(line)
        self.chk = SepChkLog(self, TEST, seed)
        self.dut = cocotb.top
        self.clk = self.dut.clk_i
        assert pl.FIFO_DEPTH == KM_MBOX_DEPTH, "plan FIFO depth differs from the mailbox depth"
        self.e = 0  # next command sequence number
        self.r = 0  # next expected response sequence number
        self.boot_clks: list[int] = []
        self.boot_tries = 0
        self.n_cold_ref: int | None = None

        # Step 1: the preload, a PROD fuse image sensed for real, every engine out
        # of reset (SW_RESET_N reset value 0x7E, KM held), entropy with noise forced.
        hexname = cocotb.plusargs.get("km_rom_hex")
        if not isinstance(hexname, str) or Path(hexname).name != ROM_HEX:
            raise AssertionError(f"+km_rom_hex={hexname}; this leaf needs +km_rom_hex={ROM_HEX}")
        self.logger.info("ROM-BUILD km_boot_wipe=1 km_unrec_wipe=1 image=%s", hexname)
        image = self.select_efuse_image(lc_raw=LC_PROD, fixed={"SIP_DIS": 0, "SYS_DIS": 0})
        self.write_efuse_image(image)
        await self.bring_up_no_cpu()
        self.swrst = SepSwReset(self)
        self.suppress_host_axi_transaction_info()
        await self._wait_sep_reset_release()
        for point, mask in AXI_POINTS:
            await self._axi_point(point, mask)
        await self._entropy_up()
        self.watch = _Watch(self)
        self.watch.start()

        try:
            await self._wait_sep_reset_release()
            await self._graded(True)
            await self._cold_reference()
            for k, d in enumerate(self.plan.resets):
                await self._warm_leg(k, d)
            await self._cold_domain_leg()
            self.chk.ok(
                "WIPE-READY",
                self.boot_tries == N_BOOTS and len(self.boot_clks) == N_BOOTS,
                build="default",
                boots=self.boot_tries,
                ready=len(self.boot_clks),
                max_boot_clk=max(self.boot_clks, default=0),
                bound_clk=READY_BOUND_CLK,
                boot_clks=self.boot_clks,
            )
        except _Stop as exc:
            self.logger.error("leaf stopped: %s", exc)
            await self._graded(False)
            await self.stop_fifo_drain()
            if not self.chk.failures:
                raise AssertionError(f"leaf stopped without a recorded failure: {exc}") from exc
            self.chk.finish()  # raises: a failure is recorded
            return

        await self._graded(False)
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.chk.finish()

    # ------------------------------------------------------------- bring-up

    async def _entropy_up(self) -> None:
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain(log_batches=False)

    async def _wait_sep_reset_release(self) -> None:
        for _ in range(SEP_RESET_BOUND):
            await RisingEdge(self.clk)
            await ReadOnly()
            if self.rd(self.dut.dbg_sep_reset_n_o, allow_unknown=True):
                await RisingEdge(self.clk)
                return
        raise AssertionError(
            f"dbg_sep_reset_n_o did not read 1 within {SEP_RESET_BOUND} clocks; "
            "a SW_RESET_N write before it is lost"
        )

    async def _graded(self, on: bool) -> None:
        # The gate is a signal write, which cocotb refuses in the ReadOnly phase.
        await RisingEdge(self.clk)
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    # ------------------------------------------------------------- taps

    async def _sample(self, sig) -> int:
        await RisingEdge(self.clk)
        await ReadOnly()
        v = self.rd_known(sig)
        await RisingEdge(self.clk)
        return v

    async def _cbd(self) -> int:
        return await self._sample(self.dut.km_csr_cold_boot_done_o)

    async def _scr(self) -> tuple[int, int]:
        """KM-CSR: (SCRAMBLER_KEY write count, SCRAMBLER_CTRL {lock, enable})."""
        await RisingEdge(self.clk)
        await ReadOnly()
        n = self.rd_known(self.dut.km_csr_scrambler_key_wr_count_o)
        ctrl = self.rd_known(self.dut.km_csr_scrambler_ctrl_o)
        await RisingEdge(self.clk)
        return n, ctrl

    async def _wait_held(self, tag: str) -> None:
        """Bounded wait: the three KM-ISO probes read isolated and the ROM count is stable."""
        prev: int | None = None
        for _ in range(0, HELD_BOUND_CLK, HELD_GAP):
            await RisingEdge(self.clk)
            await ReadOnly()
            iso = (
                self.rd(self.dut.hmac_km_isolated_probe_o, allow_unknown=True),
                self.rd(self.dut.kmac_km_isolated_probe_o, allow_unknown=True),
                self.rd(self.dut.abr_km_isolated_probe_o, allow_unknown=True),
            )
            cnt = self.rd(self.dut.km_rom_req_count_o, allow_unknown=True)
            if iso == (1, 1, 1) and prev is not None and cnt == prev:
                await RisingEdge(self.clk)
                return
            prev = cnt if iso == (1, 1, 1) else None
            await ClockCycles(self.clk, HELD_GAP)
        raise AssertionError(
            f"[{tag}] the KM did not read held within {HELD_BOUND_CLK} clocks of the park "
            f"(KM-ISO {iso}, km_rom_req_count_o {cnt})"
        )

    # ------------------------------------------------------------- bus access

    async def _rd(self, offset: int) -> int:
        seq = SepAxiAccessSeq("kmbr_rd", op=SepAxiOp.READ, addr=KM_MBOX_BASE + offset, size=2)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox read @0x{KM_MBOX_BASE + offset:08x} not OKAY")
        return seq.rdata

    async def _wr(self, offset: int, data: int) -> None:
        if await self._wr_resp(offset, data) != RESP_OKAY:
            raise AssertionError(f"KM mailbox write @0x{KM_MBOX_BASE + offset:08x} not OKAY")

    async def _wr_resp(self, offset: int, data: int) -> int:
        seq = SepAxiAccessSeq(
            "kmbr_wr", op=SepAxiOp.WRITE, addr=KM_MBOX_BASE + offset, wdata=data, size=2
        )
        await self.start_seq(seq)
        return seq.resp_code

    async def _depths(self) -> tuple[int, int]:
        """SEP_STATUS: (inbound_depth, outbound_depth)."""
        st = await self._rd(KM_MBOX_STATUS)
        return (
            (st >> KM_STATUS_INBOUND_DEPTH_LSB) & KM_STATUS_INBOUND_DEPTH_MASK,
            (st >> KM_STATUS_OUTBOUND_DEPTH_LSB) & KM_STATUS_OUTBOUND_DEPTH_MASK,
        )

    async def _write_words(self, words, *, separator: bool, tag: str) -> None:
        """Write ``words`` while the inbound FIFO has room; the separator goes on the last word."""
        n = len(words)
        i = 0
        while i < n:
            for _ in range(INBOUND_POLLS):
                in_d, _ = await self._depths()
                if in_d < KM_MBOX_DEPTH:
                    break
                await ClockCycles(self.clk, POLL)
            else:
                raise AssertionError(
                    f"[{tag}] the inbound FIFO stayed full for {INBOUND_POLLS} polls at word {i}"
                )
            for _ in range(KM_MBOX_DEPTH - in_d):
                if separator and i == n - 1:
                    await self._wr(KM_MBOX_WRITE_SEPARATOR, 1)
                await self._wr(KM_MBOX_WRITE_DATA, words[i] & pl.WORD_MASK)
                i += 1
                if i == n:
                    break

    async def _wait_depth(self, *, inbound: int | None, outbound: int | None, tag: str) -> None:
        for _ in range(DEPTH_POLLS):
            in_d, out_d = await self._depths()
            if (inbound is None or in_d == inbound) and (outbound is None or out_d == outbound):
                return
            await ClockCycles(self.clk, POLL)
        raise AssertionError(
            f"[{tag}] SEP_STATUS depths ({in_d}, {out_d}) did not reach "
            f"({inbound}, {outbound}) within {DEPTH_POLLS} polls"
        )

    async def _pop_all(self, tag: str) -> list[int]:
        """Pop every word that SEP_STATUS.outbound_depth shows."""
        words: list[int] = []
        while len(words) < POP_MAX_WORDS:
            _, out_d = await self._depths()
            if not out_d:
                break
            for _ in range(out_d):
                words.append(await self._rd(KM_MBOX_READ_DATA))
        if words:
            self.logger.info("LOG %s popped=%d words=%s", tag, len(words), [_a(w) for w in words])
        return words

    # ---------------------------------------------------------- frame reader

    async def _read_word(self, tag: str) -> int:
        for _ in range(RESP_POLLS):
            _, out_d = await self._depths()
            if out_d:
                return await self._rd(KM_MBOX_READ_DATA)
            await ClockCycles(self.clk, POLL)
        raise AssertionError(f"[{tag}] no outbound word within {RESP_POLLS} polls")

    async def _read_frame(self, tag: str) -> _Frame:
        """One response frame; ``crc_ok`` reports the header CRC-8 and the payload CRC-32C."""
        hdr = await self._read_word(tag)
        seq, rid, plen = hdr & 0xFF, (hdr >> 8) & 0xFF, (hdr >> 16) & 0xFF
        crc_ok = hdr >> 24 == pl.header_crc(seq, rid, plen)
        if not crc_ok or plen > FRAME_MAX_PLEN:
            return _Frame(seq, rid, plen, (), False, (hdr,))
        payload = tuple([await self._read_word(tag) for _ in range(plen)])
        words = [hdr, *payload]
        if plen:
            crc = await self._read_word(tag)
            words.append(crc)
            crc_ok = crc == pl.payload_crc(payload)
        return _Frame(seq, rid, plen, payload, crc_ok, tuple(words))

    @staticmethod
    def _echo(f: _Frame, cmd: int, seq: int) -> tuple[int, int | None] | None:
        """(code, argument) of the RESP_CMD of (``cmd``, ``seq``), or None for another frame."""
        if not f.crc_ok or f.rid != pl.RESP_CMD or f.plen not in (3, 4):
            return None
        if f.payload[0] != (seq & 0xFF) or f.payload[1] != (cmd & 0xFF) or f.payload[2] >> 8:
            return None
        return pl.signed8(f.payload[2]), (f.payload[3] if f.plen == 4 else None)

    async def _cmd(self, cmd: int, payload=(), tag: str = "") -> tuple[int, int | None]:
        """Send a well-formed frame at e; read its RESP_CMD at response sequence r."""
        tag = tag or f"cmd 0x{cmd:02x}"
        seq = self.e
        await self._write_words(pl.cmd_frame(cmd, seq, list(payload)), separator=True, tag=tag)
        self.e = (self.e + 1) & 0xFF
        f = await self._read_frame(tag)
        res = self._echo(f, cmd, seq)
        if res is None or f.seq != self.r:
            raise AssertionError(
                f"[{tag}] expected the RESP_CMD of cmd 0x{cmd:02x} seq {seq} at response "
                f"sequence {self.r}; got {[_a(w) for w in f.words]} (crc_ok={int(f.crc_ok)})"
            )
        self.r = (self.r + 1) & 0xFF
        return res

    async def _first_stat(self, tag: str) -> tuple[bool, int | None, int, _Frame]:
        """CMD_STAT at sequence 0 after a boot; (is the next frame its echo, code, resp seq)."""
        await self._write_words(pl.cmd_frame(pl.CMD_STAT, 0, []), separator=True, tag=tag)
        self.e = 1
        f = await self._read_frame(tag)
        res = self._echo(f, pl.CMD_STAT, 0)
        self.r = (f.seq + 1) & 0xFF
        return res is not None and f.plen == 4, (res[0] if res else None), f.seq, f

    # ------------------------------------------------------------- boots

    async def _boot(self, tag: str, kind: str, parked_out: int) -> _Boot:
        """Release the KM and pop the first outbound word of its boot.

        SEP_STATUS is read back to back until the outbound depth reads a value
        other than 0 and other than the depth held over the reset. A boot that
        reaches no such read within READY_BOUND_CLK clocks fails CHK-WIPE-READY.
        """
        scr0, _ = await self._scr()
        self.boot_tries += 1
        self.watch.arm()
        await self.swrst.release("km")
        t_rel = self.watch.cyc
        while True:
            _, out_d = await self._depths()
            if out_d not in (0, parked_out):
                ready_cycle = self.watch.cyc
                rise = self.watch.rise
                break
            if self.watch.cyc - t_rel > READY_BOUND_CLK:
                self.chk.ok(
                    "WIPE-READY",
                    False,
                    build="default",
                    boot=tag,
                    kind=kind,
                    boots=self.boot_tries,
                    ready=len(self.boot_clks),
                    boot_clk="timeout",
                    bound_clk=READY_BOUND_CLK,
                    out_depth=out_d,
                    km_rom_req_count=self.rd(self.dut.km_rom_req_count_o, allow_unknown=True),
                    km_cpu_fetch_count=self.rd(self.dut.km_cpu_fetch_count_o, allow_unknown=True),
                )
                raise _Stop(
                    f"[{tag}] no RESP_KM_READY: the outbound depth stayed in "
                    f"{{0, {parked_out}}} for {READY_BOUND_CLK} clocks after the release"
                )
        word = await self._rd(KM_MBOX_READ_DATA)
        in_after, _ = await self._depths()
        b = _Boot(
            tag=tag,
            kind=kind,
            word=word,
            ready_ok=word == pl.READY_WORD,
            depth=out_d,
            in_after=in_after,
            boot_clk=ready_cycle - t_rel,
            ready_cycle=ready_cycle,
            rise_cycle=rise,
            scr_count0=scr0,
        )
        self.logger.info(
            "LOG boot=%s kind=%s boot_clk=%d bound_clk=%d ready_depth=%d word=%s ready=%d",
            tag,
            kind,
            b.boot_clk,
            READY_BOUND_CLK,
            b.depth,
            _a(word),
            int(b.ready_ok),
        )
        # A boot restarts both sequence counters: RESP_KM_READY is response 0.
        self.r, self.e = 1, 0
        return b

    def _ready_or_stop(self, b: _Boot) -> None:
        """CHK-WIPE-READY of one boot: the first word is the RESP_KM_READY header."""
        if b.ready_ok and b.depth == 1:
            self.boot_clks.append(b.boot_clk)
            return
        self.chk.ok(
            "WIPE-READY",
            False,
            build="default",
            boot=b.tag,
            kind=b.kind,
            boots=self.boot_tries,
            ready=len(self.boot_clks),
            ready_depth=b.depth,
            word=_a(b.word),
            golden=_a(pl.READY_WORD),
            boot_clk=b.boot_clk,
            bound_clk=READY_BOUND_CLK,
        )
        raise _Stop(f"[{b.tag}] the first word after the release is not RESP_KM_READY")

    def _boot_order(self, b: _Boot, held: int) -> None:
        """CHK-BOOT-ORDER at a cold boot."""
        # The flag reads 0 while the KM is held, so a rise after the arm is this
        # boot setting it; a flag already 1 while held fails the check.
        self.chk.ok(
            "BOOT-ORDER",
            held == 0 and b.rise_cycle is not None and b.rise_cycle < b.ready_cycle,
            boot="cold",
            tag=b.tag,
            held=held,
            cold_boot_done_cycle=b.rise_cycle if b.rise_cycle is not None else "none",
            ready_visible_cycle=b.ready_cycle,
        )

    async def _scr_keep(self, b: _Boot) -> None:
        """CHK-SCR-KEEP of one boot, sampled after its first command."""
        n_now, ctrl = await self._scr()
        n = n_now - b.scr_count0
        sram_scr = int(ctrl == 0b11)
        if b.kind == "cold":
            if self.n_cold_ref is None:
                self.n_cold_ref = n
            self.chk.ok("SCR-KEEP", n >= 1 and sram_scr, boot=b.tag, n_cold=n, sram_scr=sram_scr)
            return
        # Control: the cold-boot reference wrote the key, so the tap counts writes.
        ctrl_n = self.n_cold_ref if self.n_cold_ref is not None else 0
        self.chk.ok(
            "SCR-KEEP",
            n == 0 and sram_scr and ctrl_n >= 1,
            boot=b.tag,
            n_warm=n,
            sram_scr=sram_scr,
            control_n_cold=ctrl_n,
        )

    async def _park(self, tag: str) -> int:
        """Warm reset, first half: SW_RESET_N bit 0 low, wait until the KM reads held."""
        await self.swrst.park("km")
        await self._wait_held(tag)
        cbd = await self._cbd()
        return cbd

    async def _warm_boot(self, tag: str) -> _Boot:
        """A warm reset with no stale words; the boot must give RESP_KM_READY."""
        await self._pop_all(f"{tag} before the reset")
        cbd_held = await self._park(tag)
        _, out_held = await self._depths()
        b = await self._boot(tag, "warm", out_held)
        cbd_ready = await self._cbd()
        self.chk.obs("BOOT-ORDER-WARM", control=1, boot=tag, cbd_held=cbd_held, cbd_ready=cbd_ready)
        self._ready_or_stop(b)
        return b

    # ------------------------------------------------------------- legs

    async def _cold_reference(self) -> None:
        """Step 2: the cold-boot reference."""
        tag = "cold-ref"
        held = await self._cbd()
        b = await self._boot(tag, "cold", 0)
        self._boot_order(b, held)
        self._ready_or_stop(b)
        ok, code, rseq, f = await self._first_stat(tag)
        self.chk.ok(
            "SEQ0",
            ok and code == pl.RC_SUCCESS and rseq == 1,
            control=1,
            boot=tag,
            ready_seq=b.word & 0xFF,
            first_cmd_seq=0,
            resp_seq=rseq,
            code=code if code is not None else "none",
        )
        if not ok:
            raise _Stop(
                f"[{tag}] the first frame after RESP_KM_READY is {[_a(w) for w in f.words]}"
            )
        self.logger.info("LOG %s cold_boot_done_after=%d control=1", tag, await self._cbd())
        await self._scr_keep(b)

    async def _warm_leg(self, k: int, d: pl.PointDraw) -> None:
        """Steps 7 to 11 and the KM-CSR part of step 13 at one reset point."""
        tag = f"reset{k} point={d.point}"
        # Step 7: reach the reset point.
        if d.point == pl.POINT_CMDS:
            for i in range(d.c):
                code, _ = await self._cmd(pl.CMD_STAT, (), f"{tag} stat{i}")
                if code != pl.RC_SUCCESS:
                    raise AssertionError(f"[{tag}] CMD_STAT {i} returned {code}")
        elif d.point == pl.POINT_PARTIAL:
            await self._write_words(d.partial, separator=False, tag=f"{tag} partial")
            await self._wait_depth(inbound=0, outbound=None, tag=f"{tag} partial consumed")
        elif d.point == pl.POINT_UNREAD:
            for _ in range(d.r):
                await self._write_words(
                    pl.cmd_frame(pl.CMD_STAT, self.e, []), separator=True, tag=f"{tag} unread"
                )
                self.e = (self.e + 1) & 0xFF
            await self._wait_depth(
                inbound=None, outbound=pl.unread_depth(d.r), tag=f"{tag} unread responses"
            )
        if d.point != pl.POINT_UNREAD:
            await self._pop_all(f"{tag} before the reset")
        _, d_out = await self._depths()

        # Step 8: warm reset, held.
        cbd_held = await self._park(tag)

        # Step 9: stale words while the KM is held.
        resps = []
        for i, w in enumerate(d.stale):
            if i == len(d.stale) - 1:
                await self._wr(KM_MBOX_WRITE_SEPARATOR, 1)
            resps.append(await self._wr_resp(KM_MBOX_WRITE_DATA, w))
        in_held, out_held = await self._depths()

        # Step 10: release; the first word is RESP_KM_READY.
        b = await self._boot(tag, "warm", out_held)
        cbd_ready = await self._cbd()
        self.chk.obs("BOOT-ORDER-WARM", control=1, boot=tag, cbd_held=cbd_held, cbd_ready=cbd_ready)

        # Step 11: CMD_STAT at sequence 0; its response must be the next frame.
        echo, code, rseq, f = False, None, -1, None
        if b.ready_ok:
            echo, code, rseq, f = await self._first_stat(tag)
        writes_okay = all(r == RESP_OKAY for r in resps)
        self.chk.ok(
            "BOOT-FLUSH",
            writes_okay
            and in_held == len(d.stale)
            and out_held == d_out
            and b.depth == 1
            and b.ready_ok
            and b.in_after == 0
            and echo,
            point=d.point,
            w=len(d.stale),
            writes_okay=int(writes_okay),
            parked_depth_in=in_held,
            d_out=d_out,
            parked_depth_out=out_held,
            ready_depth=b.depth,
            ready_word=_a(b.word),
            inbound_after=b.in_after,
            stale=0 if echo else 1,
            next_frame=[_a(w) for w in f.words] if f is not None and not echo else "echo",
        )
        self._ready_or_stop(b)
        self.chk.ok(
            "SEQ0",
            echo and code == pl.RC_SUCCESS and rseq == 1,
            control=1,
            boot=tag,
            ready_seq=b.word & 0xFF,
            first_cmd_seq=0,
            resp_seq=rseq,
            code=code if code is not None else "none",
        )
        if not echo:
            raise _Stop(f"[{tag}] a stale frame answered before the first command")
        # Step 13, KM-CSR part.
        await self._scr_keep(b)

    async def _load_image(self, tag: str) -> bool:
        """Step 15: CMD_SRAM_LOAD_EXEC of the spin image; True when the image is stored."""
        n = self.plan.image_n
        code, arg = await self._cmd(pl.CMD_SRAM_LOAD_EXEC, (n,), f"{tag} load")
        confirm = code == pl.RC_SUCCESS and arg is None
        # The boot flush left FLUSHED_BY_KM set; clear it so that only the
        # handover flush sets it again. That flush follows the store of the image
        # size ("SRAM Firmware Handover"), so the warm reset of step 16 waits for it.
        await self._wr(KM_MBOX_IRQ_STATUS, 1 << KM_IRQ_FLUSHED_BY_KM)
        irq = await self._rd(KM_MBOX_IRQ_STATUS)
        if irq & (1 << KM_IRQ_FLUSHED_BY_KM):
            raise AssertionError(f"[{tag}] FLUSHED_BY_KM still set after its W1C ({_a(irq)})")
        await self._write_words(imgh.stream_words(self.plan.image), separator=True, tag=tag)
        flushed = 0
        for _ in range(FLUSH_POLLS):
            if (await self._rd(KM_MBOX_IRQ_STATUS) >> KM_IRQ_FLUSHED_BY_KM) & 1:
                flushed = 1
                break
            await ClockCycles(self.clk, POLL)
        else:
            raise AssertionError(
                f"[{tag}] the handover flush (FLUSHED_BY_KM) never followed the stream of {n} words"
            )
        # Step 16: the image sends nothing; a word here is a fault frame of the load.
        popped = await self._pop_all(f"{tag} after the handover")
        stored = confirm and flushed == 1 and not popped
        self.logger.info(
            "LOG %s n=%d confirm_code=%d confirm_arg=%s flushed=%d popped=%d stored=%d control=1",
            tag,
            n,
            code,
            _a(arg),
            flushed,
            len(popped),
            int(stored),
        )
        return stored

    async def _cold_reset(self, tag: str) -> int:
        """Step 18, first half: rst_ni pulse, fuse sense, entropy; the KM stays held."""
        await self._graded(False)
        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        self.drbg_sb.stop()
        rec = await self.pulse_rst_ni(release_bound=SEP_RESET_BOUND)
        self.swrst.value = SW_RESET_N_RESET_DEFAULT
        self.logger.info("LOG %s release_clks=%d", tag, rec["release_clks"])
        await self._entropy_up()
        await self._graded(True)
        return await self._cbd()

    async def _axi_point(self, point: str, mask: int) -> None:
        """Step 1, one AXI reset point: rst_ni low in the half clock of a pending request.

        Runs before the entropy source comes up. The KM boots from the release;
        at the first falling edge with a valid of ``mask`` at 1 the leaf drives
        rst_ni low. CHK-RST-AXI-VALID grades the three valids in the first sample
        with the KM CPU reset at 0; the sample before it must show the request
        pending. The cold reset then completes with the KM held.
        """
        tag = f"axi-{point}"
        await self.swrst.release("km")
        for _ in range(AXI_ARM_BOUND):
            await FallingEdge(self.clk)
            await ReadOnly()
            pending = self.rd_known(self.dut.km_cpu_axi_valid_o)
            if pending & mask:
                break
        else:
            raise AssertionError(
                f"[{tag}] no KM CPU request on valid mask 0b{mask:03b} within "
                f"{AXI_ARM_BOUND} clocks of the release"
            )
        await Timer(1, "step")
        self.dut.rst_ni.value = 0
        clks = 0
        while True:
            await ReadOnly()
            valid = self.rd_known(self.dut.km_cpu_axi_valid_o)
            rst_n = self.rd_known(self.dut.km_cpu_rst_n_o)
            if rst_n == 0:
                break
            if clks == AXI_RST_BOUND:
                raise AssertionError(
                    f"[{tag}] the KM CPU reset did not read 0 within {AXI_RST_BOUND} clocks "
                    "of the rst_ni drive"
                )
            pending = valid
            clks += 1
            await FallingEdge(self.clk)
        self.chk.ctrl(
            "RST-AXI-PENDING", bool(pending & mask), point=point, pending=f"0b{pending:03b}"
        )
        self.chk.ok(
            "RST-AXI-VALID",
            valid == 0,
            point=point,
            valid=f"0b{valid:03b}",
            rst_n=rst_n,
            pending=f"0b{pending:03b}",
            clks=clks,
        )
        rec = await self.pulse_rst_ni(release_bound=SEP_RESET_BOUND)
        self.swrst.value = SW_RESET_N_RESET_DEFAULT
        self.logger.info("LOG %s release_clks=%d", tag, rec["release_clks"])

    async def _cold_domain_leg(self) -> None:
        """Steps 15 to 20 without the CMD_OTP_READ_LOCK_COLD commands."""
        tag = "stored"
        stored = await self._load_image(tag)

        # Step 16: warm reset with the image stored.
        b = await self._warm_boot(f"{tag} warm")
        # Step 17.
        ver_code, ver_arg = await self._cmd(pl.CMD_SRAM_VER, (), f"{tag} CMD_SRAM_VER")
        await self._scr_keep(b)
        # Control of CHK-SRAM-VER: the image is stored (confirmation, handover flush,
        # no fault frame).
        self.chk.ok(
            "SRAM-VER",
            ver_code == pl.RC_FAILURE and ver_arg is None and stored,
            code=ver_code,
            arg=_a(ver_arg),
            stored=int(stored),
        )
        warm_exec, warm_arg = await self._cmd(pl.CMD_SRAM_EXEC, (), f"{tag} CMD_SRAM_EXEC")
        self.logger.info("LOG %s warm_exec=%d arg=%s control=1", tag, warm_exec, _a(warm_arg))
        await self._pop_all(f"{tag} after CMD_SRAM_EXEC")

        # Step 18: cold reset.
        ctag = "cold"
        held = await self._cold_reset(ctag)
        b = await self._boot(ctag, "cold", 0)
        self._boot_order(b, held)
        self._ready_or_stop(b)
        self.logger.info("LOG %s cold_boot_done_after=%d control=1", ctag, await self._cbd())

        # Step 19.
        cold_exec, cold_arg = await self._cmd(pl.CMD_SRAM_EXEC, (), f"{ctag} CMD_SRAM_EXEC")
        await self._scr_keep(b)

        # Step 20: warm reset after the cold reset.
        b = await self._warm_boot("cold warm")
        after_exec, after_arg = await self._cmd(pl.CMD_SRAM_EXEC, (), "cold warm CMD_SRAM_EXEC")
        await self._scr_keep(b)

        # Control: the same command succeeds with the image stored before the cold reset.
        self.chk.ok(
            "FWSIZE",
            cold_exec == pl.RC_INVALID_ARG
            and cold_arg is None
            and after_exec == pl.RC_INVALID_ARG
            and after_arg is None
            and warm_exec == pl.RC_SUCCESS,
            cold_exec=cold_exec,
            arg=_a(cold_arg),
            control_warm_exec=warm_exec,
            warm_after_cold_exec=after_exec,
            warm_after_cold_arg=_a(after_arg),
        )
