# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold reset with an access outstanding, and with fuse sensing in progress.

``rst_ni`` is the one SEP reset that may assert on any cycle:
``doc/integrator/src/smu-sep.adoc`` (Clock and Reset Requirements) gives it
asynchronous assertion, and ``hw/sys/sep/doc/clk_rst.adoc`` (Reset
Architecture) makes it the reset of the whole subsystem. Every ``SW_RESET_N``
domain isolates and drains its paths before its reset asserts
(``hw/sys/sep/doc/reset_controller.adoc``), so no software reset is used here,
and no software reset can reach the in-flight cases this test grades.

Phase A walks one read-write probe register on each converted register port
the CPU-LSU master reaches (``seq_lib/sep_reset_mid_transfer_seq.PROBES``). For
each probe and each of read and write it first runs the probe access with no
reset to measure the response window W: the cycles from the last request
handshake to the response handshake on ``s_axi``. It then lands ``rst_ni`` at
each offset ``reset_offsets(W)`` inside that window and grades the recovery.

Phase B lands ``rst_ni`` while fuse sensing runs, at every early cycle and at
points across the measured sense time. It grades that each ``rst_ni`` returns
the shadow registers to their reset value, and that the next sense completes
and fills them with the staged image.

Checks:
  CHK-PROBE-LIVE   with no reset, the probe access completes OKAY: a read
                   returns the value written before it, a write reads back.
                   So each probe is a real access, and its window is measured.
  CHK-ARM          before each landing the probe holds a written value that is
                   not its RDL reset, so CHK-RESET-VALUE can fail.
  CHK-MIDFLIGHT    at every landing the request handshake has completed; at
                   least one landing per probe and op comes before the response
                   is accepted, and for each such landing the master abandons
                   the access (its completion carries no response). A landing
                   the response beat is logged and grades recovery only.
  CHK-RESET-VALUE  the first read after the reset returns OKAY and the RDL
                   reset value of the probe, within half the AXI timeout.
  CHK-RECOVER      a write after the reset reads back exactly, OKAY.
  CHK-NO-STALE     no R or B beat with the abandoned access's ID appears after
                   the reset.
  CHK-SHADOW-CLEAR  with ``rst_ni`` low, every shadow word reads its RDL reset
                   value (``efuse_shadow_probe_o``), both after a completed sense
                   and with sense-done low. The LC_STATE word reads the INVALID
                   hold that ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (Fuse
                   Sensing and Boot Sequencing) gives before sensing completes,
                   ``{~4'b1111, 4'b1111}``. The staged image differs from the
                   reset value in at least one word, so a shadow that keeps its
                   value through the reset fails this check.
  CHK-SENSE-RESTART  a reset that lands with sense-done low is followed by a
                   sense that completes, and the sensed shadow matches the
                   staged image (the base-class compare after sense-done). The
                   shadow read its reset value before that sense, so the match
                   comes from words the restarted sense wrote.

no_cpu, real fuse sense with the committed default preload
(``+sep_efuse_preload``). Randomization: the armed, in-flight and post-reset
data values come from the run seed (``SepSeededRng``); the probes, ops and
offsets are walked on every seed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, SimTimeoutError, with_timeout
from env.sep_efuse_image import (
    LC_FIELD_MASK,
    LC_WORD_IDX,
    NUM_FUSE_WORDS,
    SHADOW_BASE,
    WORD_BITS,
    WORD_MASK,
    lc_encode,
)
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from sep_reg_meta import word_reset
from seq_lib.sep_reset_mid_transfer_seq import (
    PROBE_ID,
    PROBES,
    SepResetProbeDriver,
    other_value,
    reset_offsets,
    watch_stale,
)

_RESP_OKAY = 0
# Dense part of the sense sweep: every cycle from the rst_ni release edge.
_SENSE_DENSE = 32
_SENSE_SPREAD = 8
_MAX_SENSE_CYCLES = 20_000
# rst_ni low time for every reset this test lands, in clk_i cycles.
_HOLD = 20
# clk_wdt_i period in clk_i periods. A watchdog threshold write returns on
# clk_i, then prim_reg_cdc holds the register busy until the pulse
# synchronizer finishes on clk_wdt_i, and the next access waits for that. At
# the 200 kHz default one probe access outlasts the AXI timeout; eight core
# periods keeps it inside, as in sep_reg_bit_bash_rand_test.
_WDT_CLK_RATIO = 8
# Logical LC_STATE before sensing completes: hw/sys/sep/doc/otp_fuse_controller.adoc
# (Fuse Sensing and Boot Sequencing) holds the output at 4'b1111 until then.
_LC_PRESENSE_RAW = 0xF


def _shadow_reset_words() -> list[int]:
    """Reset value of each shadow word: the RDL reset, and the pre-sense LC hold."""
    words = [word_reset(SHADOW_BASE + 4 * i) for i in range(NUM_FUSE_WORDS)]
    keep = words[LC_WORD_IDX] & WORD_MASK & ~LC_FIELD_MASK
    words[LC_WORD_IDX] = keep | lc_encode(_LC_PRESENSE_RAW)
    return words


def _shadow_words() -> list[int | None]:
    """Each word of ``efuse_shadow_probe_o``; None for a word with an X or Z bit."""
    value = cocotb.top.efuse_shadow_probe_o.value
    if value.is_resolvable:
        flat = int(value)
        return [(flat >> (WORD_BITS * i)) & 0xFFFF_FFFF for i in range(NUM_FUSE_WORDS)]
    bits = str(value)
    n = len(bits)
    out: list[int | None] = []
    for i in range(NUM_FUSE_WORDS):
        chunk = bits[n - WORD_BITS * (i + 1) : n - WORD_BITS * i]
        out.append(int(chunk, 2) if set(chunk) <= {"0", "1"} else None)
    return out


@pyuvm.test()
class sep_reset_mid_transfer_recovery_test(sep_base_test):
    """A cold reset mid-access or mid-sense leaves every path usable."""

    required_evidence = (
        "CHK-PROBE-LIVE",
        "CHK-ARM",
        "CHK-MIDFLIGHT",
        "CHK-RESET-VALUE",
        "CHK-RECOVER",
        "CHK-NO-STALE",
        "CHK-SHADOW-CLEAR",
        "CHK-SENSE-RESTART",
    )

    async def run_scenario(self) -> None:
        self.rng = SepSeededRng(self.random_seed())
        self.cfg.wdt_clk_period_ns = _WDT_CLK_RATIO * self.cfg.sys_clk_period_ns
        self.logger.info(
            "WDT sim-timing knob: clk_wdt=%s ns (%dx core)",
            self.cfg.wdt_clk_period_ns,
            _WDT_CLK_RATIO,
        )
        self.write_efuse_image(self.select_efuse_image())
        await self.bring_up_no_cpu(max_cycles=_MAX_SENSE_CYCLES)
        self.drv = SepResetProbeDriver(self)
        total = 0
        for probe in PROBES:
            for op in ("read", "write"):
                total += await self._walk(probe, op)
        self.logger.info(
            "Phase A PASS: %d resets landed mid-access over %d probes x 2 ops",
            total,
            len(PROBES),
        )
        await self._sense_restart()

    async def _calibrate(self, probe, op: str) -> int:
        """Run the probe access with no reset; return its response window."""
        arm = other_value(self.rng, probe.mask, (probe.reset,))
        await self.drv.write(probe, arm)
        value = other_value(self.rng, probe.mask, (probe.reset, arm))
        ev, watch = await self.drv.run_probe(probe, op, value, land_at=None)
        await with_timeout(ev.wait(), 10_000, "ns")
        code = worst_resp(getattr(ev.data, "resp", None))
        assert code == _RESP_OKAY and watch.resp_code == _RESP_OKAY, (
            f"CHK-PROBE-LIVE FAIL: {probe.name} {op} @0x{probe.addr:08x} resp={code} "
            f"(pins {watch.resp_code}) with no reset, expected OKAY"
        )
        if op == "write":
            await self.drv.commit(probe, value)
        if op == "read":
            raw = bytes(getattr(ev.data, "data", b""))
            got = int.from_bytes(raw[:4], "little") & probe.mask
            want = arm
        else:
            got = await self.drv.read(probe)
            want = value
        assert got == want, (
            f"CHK-PROBE-LIVE FAIL: {probe.name} {op} @0x{probe.addr:08x} returned "
            f"0x{got:08x}, expected 0x{want:08x}"
        )
        window = watch.resp - watch.anchor
        self.logger.info(
            "CHK-PROBE-LIVE PASS: %s %s @0x%08x OKAY value=0x%08x; request handshake "
            "at cycle %d, response at cycle %d, window %d cycles",
            probe.name,
            op,
            probe.addr,
            got,
            watch.anchor,
            watch.resp,
            window,
        )
        return window

    async def _walk(self, probe, op: str) -> int:
        """Land rst_ni at every offset inside this probe's response window."""
        window = await self._calibrate(probe, op)
        offsets = reset_offsets(window)
        arms: list[int] = []
        resets: list[int] = []
        posts: list[int] = []
        late: list[int] = []
        for d in offsets:
            arm, rv, post, outstanding = await self._land(probe, op, d)
            arms.append(arm)
            resets.append(rv)
            posts.append(post)
            if not outstanding:
                late.append(d)
        n = len(offsets)
        mid = [d for d in offsets if d not in late]
        assert mid, (
            f"CHK-MIDFLIGHT FAIL: {probe.name} {op}: the response beat the reset at "
            f"every offset {offsets}; no reset landed with the access outstanding"
        )
        self.logger.info(
            "CHK-ARM PASS: %s %s: %d landings armed with a non-reset value "
            "(first 0x%08x, last 0x%08x; RDL reset 0x%08x)",
            probe.name,
            op,
            n,
            arms[0],
            arms[-1],
            probe.reset & probe.mask,
        )
        self.logger.info(
            "CHK-MIDFLIGHT PASS: %s %s: rst_ni asserted at offsets %s of the "
            "%d-cycle calibrated window after the request handshake and before the "
            "response; the master abandoned all %d of those accesses. Offsets %s "
            "came after the response (the window varies run to run) and grade "
            "recovery only",
            probe.name,
            op,
            mid,
            window,
            len(mid),
            late,
        )
        self.logger.info(
            "CHK-RESET-VALUE PASS: %s %s: %d post-reset reads OKAY, all 0x%08x == RDL reset 0x%08x",
            probe.name,
            op,
            n,
            resets[0],
            probe.reset & probe.mask,
        )
        self.logger.info(
            "CHK-RECOVER PASS: %s %s: %d post-reset writes read back OKAY "
            "(first 0x%08x, last 0x%08x)",
            probe.name,
            op,
            n,
            posts[0],
            posts[-1],
        )
        self.logger.info(
            "CHK-NO-STALE PASS: %s %s: no R/B beat with ID %d after any of %d resets",
            probe.name,
            op,
            PROBE_ID,
            n,
        )
        return len(mid)

    async def _land(self, probe, op: str, d: int) -> tuple[int, int, int, bool]:
        """Arm, start the probe access, land rst_ni ``d`` cycles in, grade recovery.

        The last value is True when the reset landed with the access outstanding.
        A probe whose latency crosses a clock-domain synchronizer can answer
        earlier than its calibrated window; the reset then lands just after
        the response, and the landing grades recovery only.
        """
        top = cocotb.top
        tag = f"{probe.name} {op} offset {d}"
        expect_reset = probe.reset & probe.mask
        arm = other_value(self.rng, probe.mask, (probe.reset,))
        await self.drv.write(probe, arm)
        armed = await self.drv.read(probe)
        assert armed == arm, (
            f"CHK-ARM FAIL: {tag}: probe read 0x{armed:08x} after writing 0x{arm:08x}"
        )
        value = other_value(self.rng, probe.mask, (probe.reset, arm))
        ev, watch = await self.drv.run_probe(probe, op, value, land_at=d)
        assert watch.anchor is not None, (
            f"CHK-MIDFLIGHT FAIL: {tag}: no request handshake before the reset"
        )
        outstanding = watch.resp is None
        top.rst_ni.value = 0
        stop = [False]
        stale: list[tuple[str, int]] = []
        stale_task = cocotb.start_soon(watch_stale(stop, stale))
        await self.resense(hold_cycles=_HOLD, max_cycles=_MAX_SENSE_CYCLES)
        self.env.axi_monitor.forget_pending_reads(PROBE_ID)
        if outstanding:
            assert ev.is_set() and ev.data is None, (
                f"CHK-MIDFLIGHT FAIL: {tag}: the master holds a response "
                f"({getattr(ev.data, 'resp', None)}) for an access the reset abandoned"
            )
        else:
            # The pins carry the verdict: the reset one half-cycle after the
            # response edge can flush the master's record of it.
            assert watch.resp_code == _RESP_OKAY, (
                f"CHK-PROBE-LIVE FAIL: {tag}: the access answered before the reset "
                f"with resp={watch.resp_code} on s_axi, expected OKAY"
            )
        rv = await self._first_read(probe, tag)
        assert rv == expect_reset, (
            f"CHK-RESET-VALUE FAIL: {tag}: post-reset read 0x{rv:08x}, RDL reset "
            f"0x{expect_reset:08x}"
        )
        post = other_value(self.rng, probe.mask, (probe.reset,))
        await self.drv.write(probe, post)
        rb = await self.drv.read(probe)
        assert rb == post, (
            f"CHK-RECOVER FAIL: {tag}: post-reset write 0x{post:08x} read back 0x{rb:08x}"
        )
        stop[0] = True
        await stale_task
        await FallingEdge(top.clk_i)
        assert not stale, (
            f"CHK-NO-STALE FAIL: {tag}: beat(s) {stale} with the abandoned ID "
            f"{PROBE_ID} appeared after the reset"
        )
        return arm, rv, post, outstanding

    async def _first_read(self, probe, tag: str) -> int:
        """First probe read after the reset, bounded inside the driver's AXI timeout.

        A path the reset left waiting for a lost response never answers. The
        bound is half the per-access AXI timeout, so that wedge fails here by
        name before the driver times out.
        """
        bound_ns = self.cfg.axi_timeout_ns // 2
        try:
            return await with_timeout(cocotb.start_soon(self.drv.read(probe)), bound_ns, "ns")
        except SimTimeoutError:
            raise AssertionError(
                f"CHK-RESET-VALUE FAIL: {tag}: post-reset read @0x{probe.addr:08x} got "
                f"no response within {bound_ns} ns"
            ) from None
        except AssertionError as exc:
            raise AssertionError(f"CHK-RESET-VALUE FAIL: {tag}: post-reset read: {exc}") from exc

    async def _sense_cycles(self) -> int:
        """Pulse rst_ni and count clk_i edges from release to sense-done."""
        top = cocotb.top
        top.rst_ni.value = 0
        await ClockCycles(top.clk_i, _HOLD)
        top.rst_ni.value = 1
        for cycle in range(1, _MAX_SENSE_CYCLES + 1):
            await RisingEdge(top.clk_i)
            if self.rd_known(top.sep_fuse_sense_done_o):
                return cycle
        raise AssertionError("CHK-SENSE-RESTART FAIL: sense-done never asserted")

    async def _reset_and_check_clear(self, tag: str) -> int:
        """Assert rst_ni, hold it, and grade every shadow word against its reset value.

        Leaves rst_ni low. Returns the number of shadow words the reset changed.
        """
        top = cocotb.top
        before = _shadow_words()
        top.rst_ni.value = 0
        await ClockCycles(top.clk_i, _HOLD)
        await FallingEdge(top.clk_i)
        got = _shadow_words()
        bad = [i for i in range(NUM_FUSE_WORDS) if got[i] != self._shadow_reset[i]]
        if bad:
            i = bad[0]
            seen = "X/Z" if got[i] is None else f"0x{got[i]:08x}"
            raise AssertionError(
                f"CHK-SHADOW-CLEAR FAIL: {tag}: {len(bad)} shadow word(s) not at reset "
                f"with rst_ni low; first word {i} reads {seen}, reset "
                f"0x{self._shadow_reset[i]:08x}"
            )
        return sum(1 for i in range(NUM_FUSE_WORDS) if before[i] != got[i])

    async def _restarted_sense(self, tag: str) -> None:
        """Release rst_ni (low on entry) and let the next sense complete and compare."""
        try:
            await self.resense(hold_cycles=1, max_cycles=_MAX_SENSE_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"CHK-SENSE-RESTART FAIL: {tag}: {exc}") from exc

    async def _sense_restart(self) -> None:
        """Land rst_ni while fuse sensing runs; the next sense must complete."""
        top = cocotb.top
        self._shadow_reset = _shadow_reset_words()
        image = self._efuse_compare_image
        differ = [i for i in range(NUM_FUSE_WORDS) if image.shadow_word(i) != self._shadow_reset[i]]
        assert differ, (
            "CHK-SHADOW-CLEAR FAIL: the staged image equals the shadow reset value in "
            "every word, so no reset can be seen to clear the shadow"
        )
        sense = await self._sense_cycles()
        await self._restarted_sense("sense after the timing pulse")
        offsets = sorted(
            set(range(min(_SENSE_DENSE, sense - 1)))
            | {sense * j // _SENSE_SPREAD for j in range(1, _SENSE_SPREAD)}
            | {sense - 2}
        )
        full: list[int] = []
        mid: list[int] = []
        for k in offsets:
            full.append(await self._reset_and_check_clear(f"offset {k}, after a completed sense"))
            top.rst_ni.value = 1
            if k:
                await ClockCycles(top.clk_i, k)
            await FallingEdge(top.clk_i)
            assert not self.rd_known(top.sep_fuse_sense_done_o), (
                f"CHK-SENSE-RESTART FAIL: sense-done already high {k} cycles after "
                f"release; the sense takes {sense} cycles"
            )
            mid.append(await self._reset_and_check_clear(f"offset {k}, sense-done low"))
            await self._restarted_sense(f"sense after the reset at offset {k}")
        self.logger.info(
            "CHK-SHADOW-CLEAR PASS: at %d resets after a completed sense and %d with "
            "sense-done low, all %d shadow words read their reset value with rst_ni "
            "low (LC_STATE word 0x%08x); the staged image differs from reset in %d "
            "words; the reset after a completed sense changed %d..%d words, the reset "
            "with sense-done low changed %d..%d (most at offset %d)",
            len(full),
            len(mid),
            NUM_FUSE_WORDS,
            self._shadow_reset[LC_WORD_IDX],
            len(differ),
            min(full),
            max(full),
            min(mid),
            max(mid),
            offsets[mid.index(max(mid))],
        )
        self.logger.info(
            "CHK-SENSE-RESTART PASS: sense takes %d cycles from rst_ni release; rst_ni "
            "landed with sense-done low at %d offsets %s, and every following sense "
            "started from the reset shadow and completed with all %d words matching "
            "the staged image",
            sense,
            len(offsets),
            offsets,
            NUM_FUSE_WORDS,
        )
