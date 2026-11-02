# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SW_RESET_N clears only its own domain, fabric gaps raise a bus-error NMI, and the WDT bites.

OCAH provenance: ``sep_reset_ctrl_csr_test`` checks reset-control CSRs and
domains, and ``wdt_sanity_test`` checks watchdog bark, pet, disable and bite.

The reset_wdt_sanity firmware:
  * checks SW_RESET_N default 0x7E, that pulsing each crypto/TRNG/ABR reset bit clears that
    domain's probe CSRs and leaves every probe outside that reset bit unchanged, and that each
    probe is writable again after release;
  * checks that a write and a read to an unmapped fabric gap each raise a D-bus-error NMI
    (count == 2);
  * stores to a target that answers DECERR (the reset-controller gap) and to one that answers
    SLVERR (the read-only entropy pool), and reports the NMI count, ``mcause`` and ``mdseac`` of
    each; then stores to an OKAY register (OTBN ``INTR_ENABLE``) and restores it, and reports
    the NMI count and the readback;
  * exercises WDT bark -> NMI, pet, disable-freeze and re-bark, then lets the WDT run to BITE.

fw/startup/crt0.s emits PASS/FAIL magic from main()'s return code. After PASS the test also
observes the BITE reset request on the ``sep`` output ``wdt_timer_rst_req_o``.

Store-response contract. The CPU LSU passes the AXI B response of a store to the core. The
VeeR EL2 Programmer's Reference Manual (linked from ``hw/sys/sep/doc/cpu.adoc``) states that a
store that ends with a bus error is reported as an imprecise non-maskable interrupt with
``mcause`` = 0xF000_0000 (store bus error), that ``mdseac`` captures the address of the store
and stays locked until software writes ``mdeau``. The B response of each store is read on the
PR-LSU-XBAR tap (``env/sep_fabric_tap.py``, the LSU demux port to the local crossbar): the
tap runs from the CPU release to the firmware verdict, and each B is paired with its AW by
AXI ID in issue order. A store is found by the 64-bit word of its address (the LSU aligns
AWADDR to 8 bytes outside side-effect regions). This test grades, from the firmware records and the tap:
  CHK-STORE-ERR-NMI  for each of DECERR and SLVERR: exactly one AW to the store word on
                     the tap, its B response equal to the kind (DECERR = 0b11, SLVERR =
                     0b10), exactly one NMI, ``mcause`` = 0xF000_0000, and ``mdseac`` = the
                     store address, which also equals the address the testbench derives
                     from the register map. A missing AW or B, a wrong BRESP, a store that
                     completes with no NMI (nmi=0), or a wrong ``mcause`` or ``mdseac``
                     fails. Targets: ``hw/sys/sep/regs/sep.rdl`` (reset-controller aperture:
                     DECERR write response past its one register) and
                     ``hw/sys/sep/doc/entropy_pool.adoc`` (a write to any offset ends with
                     BRESP=SLVERR).
  CHK-STORE-OK-QUIET the OKAY store and its restore (the two AWs to the OKAY word after
                     the SLVERR store) each end with BRESP = OKAY (0b00) on the tap and raise
                     no NMI in the same wait an error store gets, and the written value,
                     which differs from the reset value, reads back, so the store reached
                     the register. Control: the two error stores of CHK-STORE-ERR-NMI raise
                     their NMI in that wait.

RAS port. ``sep_ras_probe_o`` (the DUT ``sep_ras_o``, bit map ``env/sep_ras_map.py``) is
watched on every ``clk_i`` edge from the CPU release (``env/sep_bit_watch.py``). The golden:
``hw/sys/sep/doc/port_table.adoc:130`` (row ``sep_ras_o``: the watchdog bark and the bite
synchronized from ``clk_wdt_i``, both levels); the bark is a level interrupt cleared by a
write of 1 to ``INTR_STATE.wdog_timer_bark``
(``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:77``), so ``wdt_bark`` is
held until INTR_STATE is cleared; ``wdt_rst_ni`` "resets the watchdog, which clears the
bite" (``hw/sys/sep/doc/watchdog.adoc:29``), so ``wdt_bite`` is held until ``wdt_rst_ni``.
Each check
below logs its own PASS or FAIL line, and the leaf fails once at its end if any failed:
  CHK-RAS-WDT_BARK-IDLE   0 on every clock from the CPU release to the console line of the
                          bad-address count (the watchdog is enabled after it).
  CHK-RAS-WDT_BARK-RISE   one line per bark: a rise after that line and before
                          ``CHK-WDT-NMI PASS`` (bark=1), and a rise after
                          ``CHK-WDT-PET PASS`` and before ``CHK-WDT-REBARK PASS`` (bark=2).
  CHK-RAS-WDT_BARK-SHAPE  after the first rise, no fall before the first CPU write to the
                          WDT ``INTR_STATE`` register on the PR-LSU-XBAR tap (AW address
                          word and W strobe lane).
  CHK-RAS-WDT_BARK-CLEAR  0 at ``CHK-WDT-CLEAR PASS``, which the firmware prints after it
                          reads the bark state cleared.
  CHK-RAS-WDT_BITE-IDLE   0 on every clock from the CPU release to ``CHK-WDT-REBARK PASS``.
  CHK-RAS-WDT_BITE-RISE   high within ``_BITE_POLL_CYCLES`` of ``wdt_timer_rst_req_o``
                          reading 1.
  CHK-RAS-WDT_BITE-SHAPE  no fall for ``_RAS_BITE_HOLD`` clocks after the rise.
Log only: ``OBS-RAS-WDT_BARK-DELAY`` (clocks from the ``WDOG_CTRL`` enable write to each
rise), ``OBS-RAS-WDT_BARK-FALL`` (clocks from the ``INTR_STATE`` write to the fall),
``OBS-RAS-WDT_BARK-BARK2`` (the field after the second bark, whose clear the leaf does not
grade: the watchdog stays enabled toward the bite), ``OBS-RAS-WDT_BITE-DELAY`` (clocks from
``wdt_timer_rst_req_o`` to the rise) and ``OBS-RAS-WDT_BITE-CLEAR`` (the leaf drives no
``wdt_rst_ni``, so the field is held to the end of the window). The leaf opens its FCOV
graded window from the CPU release to the end of the bite hold.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``. OTBN/AES/HMAC/KMAC are
JTAG-held across ``rst_ni`` release and fuse sense so they raise no crypto ``edn_req`` while the
fabric opens. The hold must end with sense: a held engine's registers are unreachable, so the
firmware's reset-wire probe write would trap.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_bit_watch import BitMark, BitWatchTimeout, SepBitWatch
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_fabric_tap import SepFabricTap, TapBeat
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_ras_map import RasChkLines, check_tap_width, ras_bit
from sep_base_test import sep_base_test
from sep_reg_meta import OTBN, sym
from seq_lib.sep_sw_reset_seq import SEP_RESET_CTRL_SW_RESET_N

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "reset_wdt_sanity_test")
_ITCM_HEX = os.path.join(_FW_DIR, "reset_wdt_sanity_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "reset_wdt_sanity_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
# Console anchors. Each names a leg the firmware scores separately, so a stale image
# that dropped one is visible here rather than hiding behind the PASS magic.
_BADADDR_LINE = "reset_ctrl bad-address NMI count == 2 OK"
_SWRST_DEFAULT_NEEDLE = "PASS: SW_RESET_N default"
_RESET_WIRE_IPS = ("otbn", "aes", "hmac", "kmac", "abr", "esrc", "csrng", "edn")
# Reset bit of each probe's domain: esrc, csrng and edn share the TRNG bit.
_RESET_DOMAIN = {ip: ("trng" if ip in ("esrc", "csrng", "edn") else ip) for ip in _RESET_WIRE_IPS}
# Each reset-wire line ends with the count of other-domain probes the firmware
# found unchanged after the pulse.
_WIRE_LINE_RE = re.compile(
    r"(\w+) reset wire OK, writable after release, other-domain probes unchanged 0x([0-9a-f]{8})"
)
# The firmware prints this after "<ip>" only once the probe, rewritten after the
# release, reads back its non-reset value.
_WRITABLE_SUFFIX = " reset wire OK, writable after release"
_BANNER = "SEP reset+WDT sanity test"

# Store-response legs. VeeR EL2 Programmer's Reference Manual (linked from
# hw/sys/sep/doc/cpu.adoc), non-maskable interrupt mcause values: 0xF000_0000 is
# a store bus error.
_MCAUSE_STORE_BUS_ERR = 0xF000_0000
# Store address of each error-response leg, from the register map: the word past
# the reset-controller register (its aperture answers DECERR past the register,
# hw/sys/sep/regs/sep.rdl) and the entropy pool STATUS register (any write is
# SLVERR, hw/sys/sep/doc/entropy_pool.adoc).
_RESET_CTRL_END = sym("SEP_RESET_CTRL_REG_MAP_BASE_ADDR") + sym("SEP_RESET_CTRL_REG_MAP_SIZE")
_STORE_ERR_ADDR = {
    "DECERR": SEP_RESET_CTRL_SW_RESET_N + 0x8,
    "SLVERR": sym("ENTROPY_POOL_STATUS_REG_ADDR"),
}
if _STORE_ERR_ADDR["DECERR"] < _RESET_CTRL_END:
    raise RuntimeError("the DECERR store address is inside the reset-controller register map")
_OKAY_ADDR = sym("OTBN_INTR_ENABLE_REG_ADDR")
# The value the restore store writes: the RDL reset of OTBN INTR_ENABLE.
_OKAY_RESET = OTBN.reset("INTR_ENABLE")
# AXI BRESP codes (AMBA AXI, BRESP encoding).
_BRESP = {"OKAY": 0b00, "SLVERR": 0b10, "DECERR": 0b11}
_STORE_ERR_RE = re.compile(
    r"CHK-STORE-ERR-NMI REC resp=(\w+) addr=0x([0-9a-f]{8}) nmi=0x([0-9a-f]{8}) "
    r"mcause=0x([0-9a-f]{8}) mdseac=0x([0-9a-f]{8})"
)
_STORE_OK_RE = re.compile(
    r"CHK-STORE-OK-QUIET REC addr=0x([0-9a-f]{8}) wrote=0x([0-9a-f]{8}) "
    r"readback=0x([0-9a-f]{8}) restored=0x([0-9a-f]{8}) nmi=0x([0-9a-f]{8})"
)
# After the firmware PASSes (2nd bark), the WDT runs on to BITE. At ~5 us/tick and
# a few ticks of bark->bite margin, give generous headroom for the reset request.
_BITE_POLL_CYCLES = 40_000

TEST = "sep_reset_wdt_sanity_test"
# Console lines that bound the RAS windows (fw/tests/reset_wdt_sanity_test).
_WDT_NMI_LINE = "CHK-WDT-NMI PASS"
_WDT_CLEAR_LINE = "CHK-WDT-CLEAR PASS"
_WDT_PET_LINE = "CHK-WDT-PET PASS"
_WDT_REBARK_LINE = "CHK-WDT-REBARK PASS"
_RAS_LINES = (_BADADDR_LINE, _WDT_NMI_LINE, _WDT_CLEAR_LINE, _WDT_PET_LINE, _WDT_REBARK_LINE)
# WDT registers whose CPU writes bound the bark windows, from the register map.
_WDT_REGS = {
    "intr_state": sym("WDT_TIMER_INTR_STATE_REG_ADDR"),
    "wdog_ctrl": sym("WDT_TIMER_WDOG_CTRL_REG_ADDR"),
}
_LSU_BYTES = 8  # data bytes of the 64-bit LSU AXI port
# Clocks the leaf watches the bite field after its rise (environment choice: two
# watchdog ticks at the bench clocks).
_RAS_BITE_HOLD = 8_000


@pyuvm.test()
class sep_reset_wdt_sanity_test(sep_base_test):
    """reset_ctrl CSR, WDT bark/pet/disable legs pass, and the BITE raises wdt_timer_rst_req_o."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER

        lsu_tap = SepFabricTap("PR-LSU-XBAR")
        check_tap_width(cocotb.top.sep_ras_probe_o)
        self.ras = SepBitWatch(
            cocotb.top.sep_ras_probe_o,
            {f: ras_bit(f) for f in ("wdt_bark", "wdt_bite")},
            name="sep_ras_probe_o",
        )
        self.ras_chk = RasChkLines(self.logger, self.random_seed())
        self.ras_lines: dict[str, BitMark] = {}
        self.ras_writes: list[tuple[str, BitMark]] = []
        follow = None

        async def _bite_idle() -> None:
            nonlocal follow
            assert self.rd_known(cocotb.top.wdt_timer_rst_req_o) == 0, (
                "CHK-BITE FAIL: wdt_timer_rst_req_o asserted before firmware "
                "enabled the WDT, so a later 1 cannot be attributed to BITE"
            )
            # The CPU is released; the tap records every LSU access of the firmware.
            lsu_tap.start()
            self.ras.start()
            self.ras_rel = self.ras.mark()
            follow = cocotb.start_soon(self._ras_follow(lsu_tap))

        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
            park=("otbn", "aes", "hmac", "kmac"),
            release_park=True,
            after_bring_up_hook=_bite_idle,
        )
        await lsu_tap.stop()
        self._grade_bark()

        # The firmware scores the reset_ctrl legs into its own error count, and the
        # PASS magic alone cannot say which of them ran: an image without a leg
        # reaches PASS with that contract never exercised. Gate on the line each
        # leg prints, and emit the record the VPLAN row names for it.
        console = self.sb.console_text()
        assert _BADADDR_LINE in console, (
            f"firmware console has no {_BADADDR_LINE!r} line, so the unmapped-gap "
            f"bus-error count was not checked. Console was:\n{console}"
        )
        self.logger.info("CHK-BADADDR PASS: firmware reported the bad-address NMI count == 2")
        self._grade_store_responses(console, lsu_tap)
        wired = [ip for ip in _RESET_WIRE_IPS if f"{ip} reset wire OK" in console]
        assert len(wired) == len(_RESET_WIRE_IPS), (
            f"firmware console reports a reset wire for {sorted(wired)}, expected all "
            f"{sorted(_RESET_WIRE_IPS)}; a missing domain is an unexercised reset bit. "
            f"Console was:\n{console}"
        )
        unchanged = {m.group(1): int(m.group(2), 16) for m in _WIRE_LINE_RE.finditer(console)}
        want_unchanged = {
            ip: sum(1 for nb in _RESET_WIRE_IPS if _RESET_DOMAIN[nb] != _RESET_DOMAIN[ip])
            for ip in _RESET_WIRE_IPS
        }
        assert unchanged == want_unchanged, (
            f"CHK-SWRST-WIRE FAIL: other-domain probes found unchanged per pulse "
            f"{unchanged}, expected {want_unchanged}; a pulse that checked fewer "
            f"domains leaves a cross-wired reset bit unseen. Console was:\n{console}"
        )
        self.logger.info(
            "CHK-SWRST-WIRE PASS: %d reset bits each returned their probe and left every "
            "probe outside that bit unchanged (per pulse: %s)",
            len(wired),
            ", ".join(f"{ip}={unchanged[ip]}" for ip in _RESET_WIRE_IPS),
        )
        writable = [ip for ip in _RESET_WIRE_IPS if f"{ip}{_WRITABLE_SUFFIX}" in console]
        assert len(writable) == len(_RESET_WIRE_IPS), (
            f"firmware console reports a post-release write/readback for "
            f"{sorted(writable)}, expected all {sorted(_RESET_WIRE_IPS)}; a missing "
            f"domain was never shown writable after its reset release. "
            f"Console was:\n{console}"
        )
        self.logger.info(
            "CHK-SWRST-WRITABLE PASS: %d reset domains each read back a non-reset "
            "probe value written after the release",
            len(writable),
        )
        assert _SWRST_DEFAULT_NEEDLE in console, (
            f"firmware console has no {_SWRST_DEFAULT_NEEDLE!r} in its verdict line, so "
            f"the SW_RESET_N default was not checked. Console was:\n{console}"
        )
        self.logger.info("CHK-SWRST-DEFAULT PASS: firmware reported the SW_RESET_N default")

        # Now observe the BITE: the still-enabled WDT reaches BITE_THOLD
        # and asserts the real wdt_timer_rst_req_o output.
        dut = cocotb.top
        bite_seen = self.rd_known(dut.wdt_timer_rst_req_o) == 1
        for _ in range(_BITE_POLL_CYCLES):
            if bite_seen:
                break
            await RisingEdge(dut.clk_i)
            if self.rd_known(dut.wdt_timer_rst_req_o):
                bite_seen = True
                break
        assert bite_seen, (
            "CHK-BITE: wdt_timer_rst_req_o never asserted after re-bark "
            "(BITE reset request not observed)"
        )
        self.logger.info(
            "CHK-BITE PASS: wdt_timer_rst_req_o asserted -> WDT BITE reset request observed"
        )
        await self._grade_bite(self.ras.mark())
        follow.cancel()
        await RisingEdge(dut.clk_i)
        close_graded_window(self.logger)
        await self.ras.stop()
        if self.ras_chk.fails:
            raise AssertionError(
                f"{len(self.ras_chk.fails)} RAS check(s) failed: " + "; ".join(self.ras_chk.fails)
            )

    # ---- sep_ras_o watchdog fields ----
    def _ras(self, fld: str, half: str, ok: bool, **fields) -> None:
        """Log CHK-RAS-<FIELD>-<HALF> and record a FAIL for the end of the leaf."""
        self.ras_chk.ok(f"RAS-{fld.upper()}-{half}", ok, **fields)

    @staticmethod
    def _wdt_reg(aw: TapBeat, w: TapBeat) -> str | None:
        """The WDT register of ``_WDT_REGS`` that a write's address word and strobe hit."""
        addr, strb = aw.fields.get("addr"), w.fields.get("strb")
        if addr is None or strb is None:
            return None
        for reg, a in _WDT_REGS.items():
            lane = a % _LSU_BYTES
            if addr // _LSU_BYTES == a // _LSU_BYTES and (strb >> lane) & 0xF:
                return reg
        return None

    async def _ras_follow(self, tap: SepFabricTap) -> None:
        """Open the graded window, then mark the watcher at each bounding console line
        and each CPU write to a WDT register.

        A mark is taken on the clock that shows the line or the write, or one clock later.
        """
        dut = cocotb.top
        seen_len = 0
        seen_beats = 0
        aws: list[TapBeat] = []
        ws: list[TapBeat] = []
        burst: list[TapBeat] = []
        await RisingEdge(dut.clk_i)
        open_graded_window(TEST, self.logger)
        while True:
            await ReadOnly()
            if len(self.sb.console) != seen_len:
                seen_len = len(self.sb.console)
                text = self.sb.console_text()
                for line in _RAS_LINES:
                    if line not in self.ras_lines and line in text:
                        self.ras_lines[line] = self.ras.mark()
            while seen_beats < len(tap.beats):
                beat = tap.beats[seen_beats]
                seen_beats += 1
                if beat.ch == "aw":
                    aws.append(beat)
                elif beat.ch == "w":
                    burst.append(beat)
                    if beat.fields.get("last") != 0:
                        ws.append(burst[0])
                        burst = []
                while aws and ws:
                    # W bursts follow the AW order; the first beat carries the strobe
                    # of the AW address.
                    reg = self._wdt_reg(aws.pop(0), ws.pop(0))
                    if reg is not None:
                        self.ras_writes.append((reg, self.ras.mark()))
            await RisingEdge(dut.clk_i)

    def _span(self, fld: str, kind: str, lo: int, hi: int) -> list[int]:
        """Rise or fall clocks of ``fld`` in the clocks (lo, hi]."""
        clks = (
            self.ras.rise_clks_since(self.ras_rel, fld)
            if kind == "rise"
            else self.ras.fall_clks_since(self.ras_rel, fld)
        )
        return [c for c in clks if lo < c <= hi]

    def _write_after(self, reg: str, lo: int, hi: int) -> BitMark | None:
        """The mark of the first write to ``reg`` in the clocks (lo, hi]."""
        return next((m for r, m in self.ras_writes if r == reg and lo < m.clk <= hi), None)

    def _grade_bark(self) -> None:
        """CHK-RAS-WDT_BARK-*: idle window, both rises, hold to the clear write, clear."""
        fld = "wdt_bark"
        rel = self.ras_rel
        mk = {line: self.ras_lines.get(line) for line in _RAS_LINES}
        missing = [line for line, m in mk.items() if m is None]
        if missing:
            for half in ("IDLE", "RISE", "SHAPE", "CLEAR"):
                self._ras(fld, half, False, console_lines_not_seen=missing)
            return
        bad, nmi, clr = mk[_BADADDR_LINE], mk[_WDT_NMI_LINE], mk[_WDT_CLEAR_LINE]
        pet, rebark = mk[_WDT_PET_LINE], mk[_WDT_REBARK_LINE]
        hi = bad.high[fld] - rel.high[fld]
        self._ras(
            fld,
            "IDLE",
            hi == 0 and bad.clk > rel.clk,
            window="release..bad-address_line",
            clocks=bad.clk - rel.clk,
            high_clocks=hi,
            exp=0,
        )
        r1 = self._span(fld, "rise", bad.clk, nmi.clk)
        self._ras(
            fld,
            "RISE",
            bool(r1),
            bark=1,
            window="bad-address_line..CHK-WDT-NMI",
            rises=len(r1),
            exp=">=1",
        )
        r2 = self._span(fld, "rise", pet.clk, rebark.clk)
        self._ras(
            fld,
            "RISE",
            bool(r2),
            bark=2,
            window="CHK-WDT-PET..CHK-WDT-REBARK",
            rises=len(r2),
            exp=">=1",
        )
        for bark, rises, lo in ((1, r1, bad.clk), (2, r2, pet.clk)):
            en = self._write_after("wdog_ctrl", lo, rises[0]) if rises else None
            self.ras_chk.obs(
                "RAS-WDT_BARK-DELAY",
                bark=bark,
                clocks_from_wdog_ctrl_write_to_rise=rises[0] - en.clk if en is not None else "none",
            )
        if not r1:
            self._ras(fld, "SHAPE", False, rise_clk="none")
        else:
            wr = self._write_after("intr_state", r1[0], clr.clk)
            f1 = self._span(fld, "fall", r1[0], self.ras.clk)
            first_fall = f1[0] if f1 else None
            if wr is None:
                self._ras(
                    fld,
                    "SHAPE",
                    False,
                    rise_clk=r1[0],
                    intr_state_write_clk="none",
                    exp="write_before_CHK-WDT-CLEAR",
                )
            else:
                self._ras(
                    fld,
                    "SHAPE",
                    first_fall is None or first_fall >= wr.clk,
                    rise_clk=r1[0],
                    intr_state_write_clk=wr.clk,
                    first_fall_clk=first_fall if first_fall is not None else "none",
                    exp="no_fall_before_write",
                )
                self.ras_chk.obs(
                    "RAS-WDT_BARK-FALL",
                    clocks_from_intr_state_write_to_fall=(
                        first_fall - wr.clk if first_fall is not None else "none"
                    ),
                )
        nr = len(self._span(fld, "rise", bad.clk, clr.clk))
        nf = len(self._span(fld, "fall", bad.clk, clr.clk))
        self._ras(
            fld,
            "CLEAR",
            nr >= 1 and nr == nf,
            at="CHK-WDT-CLEAR",
            level=nr - nf,
            rises=nr,
            falls=nf,
            exp=0,
        )
        w2 = self._write_after("intr_state", r2[0], self.ras.clk) if r2 else None
        self.ras_chk.obs(
            "RAS-WDT_BARK-BARK2",
            level_at_rebark_line=len(self._span(fld, "rise", bad.clk, rebark.clk))
            - len(self._span(fld, "fall", bad.clk, rebark.clk)),
            intr_state_write_clk=w2.clk if w2 is not None else "none",
            falls_after_rise=self._span(fld, "fall", r2[0], self.ras.clk)[:4] if r2 else "none",
        )

    async def _grade_bite(self, req: BitMark) -> None:
        """CHK-RAS-WDT_BITE-*: idle window, rise near the bite request, hold."""
        fld = "wdt_bite"
        rel = self.ras_rel
        rebark = self.ras_lines.get(_WDT_REBARK_LINE)
        if rebark is None:
            for half in ("IDLE", "RISE", "SHAPE"):
                self._ras(fld, half, False, console_lines_not_seen=[_WDT_REBARK_LINE])
            return
        hi = rebark.high[fld] - rel.high[fld]
        self._ras(
            fld,
            "IDLE",
            hi == 0 and rebark.clk > rel.clk,
            window="release..CHK-WDT-REBARK",
            clocks=rebark.clk - rel.clk,
            high_clocks=hi,
            exp=0,
        )
        rises = self._span(fld, "rise", rebark.clk, self.ras.clk)
        if not rises:
            try:
                rises = [await self.ras.wait_rise(req, _BITE_POLL_CYCLES, fld)]
            except BitWatchTimeout:
                rises = []
        self._ras(
            fld,
            "RISE",
            bool(rises),
            rise_clk=rises[0] if rises else "none",
            wdt_timer_rst_req_o_clk=req.clk,
            bound=_BITE_POLL_CYCLES,
        )
        if not rises:
            self._ras(fld, "SHAPE", False, rise_clk="none")
            return
        self.ras_chk.obs(
            "RAS-WDT_BITE-DELAY", clocks_from_wdt_timer_rst_req_o_to_rise=rises[0] - req.clk
        )
        for _ in range(_RAS_BITE_HOLD + 2):
            if self.ras.clk >= rises[0] + _RAS_BITE_HOLD:
                break
            await RisingEdge(cocotb.top.clk_i)
        falls = self._span(fld, "fall", rises[0], self.ras.clk)
        held = self.ras.clk - rises[0]
        self._ras(
            fld,
            "SHAPE",
            not falls and held >= _RAS_BITE_HOLD,
            rise_clk=rises[0],
            held_clocks=held,
            falls=falls[:4] or "none",
            exp_hold=_RAS_BITE_HOLD,
        )
        self.ras_chk.obs(
            "RAS-WDT_BITE-CLEAR",
            wdt_rst_ni="not_driven",
            level=self.ras.level(fld),
            clk=self.ras.clk,
        )

    @staticmethod
    def _write_pairs(tap: SepFabricTap) -> list[tuple[TapBeat, TapBeat | None]]:
        """Every AW of the tap with its B (None when no B came), paired by AXI ID in order."""
        open_aw: dict[int | None, list[int]] = {}
        pairs: list[list] = []
        for beat in tap.since(0):
            if beat.ch == "aw":
                open_aw.setdefault(beat.id, []).append(len(pairs))
                pairs.append([beat, None])
            elif beat.ch == "b":
                queue = open_aw.get(beat.id)
                if not queue:
                    raise AssertionError(
                        f"PR-LSU-XBAR B with id={beat.id} at {beat.t_ps} ps has no open AW"
                    )
                pairs[queue.pop(0)][1] = beat
        return [(aw, b) for aw, b in pairs]

    @staticmethod
    def _to(pairs: list[tuple[TapBeat, TapBeat | None]], addr: int) -> list:
        """The pairs whose AW is in the 64-bit word of ``addr``.

        The LSU AXI port is 64 bits wide, so the match is on the 64-bit
        word of ``addr``, not on its exact byte address.
        """
        return [p for p in pairs if p[0].addr is not None and (p[0].addr & ~7) == (addr & ~7)]

    @staticmethod
    def _bresp_text(pairs: list[tuple[TapBeat, TapBeat | None]]) -> str:
        """``awaddr/bresp`` of each pair; ``none`` for a missing B, ``X`` for an unknown one."""
        return ",".join(
            f"0x{aw.addr:08x}/"
            + ("none" if b is None else ("X" if b.resp is None else f"0b{b.resp:02b}"))
            for aw, b in pairs
        )

    def _grade_store_responses(self, console: str, tap: SepFabricTap) -> None:
        """Grade the firmware store-response records and the bus B responses."""
        pairs = self._write_pairs(tap)
        recs = [m.groups() for m in _STORE_ERR_RE.finditer(console)]
        kinds = sorted(r[0] for r in recs)
        assert kinds == sorted(_STORE_ERR_ADDR), (
            f"CHK-STORE-ERR-NMI FAIL: firmware store records {kinds}, expected one each of "
            f"{sorted(_STORE_ERR_ADDR)}. Console was:\n{console}"
        )
        err_nmis = {}
        for kind, addr_s, nmi_s, mcause_s, mdseac_s in recs:
            addr, nmi = int(addr_s, 16), int(nmi_s, 16)
            mcause, mdseac = int(mcause_s, 16), int(mdseac_s, 16)
            want = _STORE_ERR_ADDR[kind]
            err_nmis[kind] = nmi
            hits = self._to(pairs, want)
            bresp = hits[0][1].resp if len(hits) == 1 and hits[0][1] is not None else None
            line = (
                f"resp={kind} addr=0x{addr:08x} aw_count={len(hits)} "
                f"aw/bresp={self._bresp_text(hits) or 'none'} nmi={nmi} mcause=0x{mcause:08x} "
                f"mdseac=0x{mdseac:08x} expected addr=0x{want:08x} aw_count=1 "
                f"bresp=0b{_BRESP[kind]:02b} nmi=1 mcause=0x{_MCAUSE_STORE_BUS_ERR:08x} "
                f"mdseac=0x{want:08x}"
            )
            ok = (
                addr == want
                and bresp == _BRESP[kind]
                and nmi == 1
                and mcause == _MCAUSE_STORE_BUS_ERR
                and mdseac == want
            )
            if not ok:
                self.logger.error("CHK-STORE-ERR-NMI FAIL: %s", line)
                raise AssertionError(f"CHK-STORE-ERR-NMI FAIL: {line}")
            self.logger.info("CHK-STORE-ERR-NMI PASS: %s", line)

        oks = [m.groups() for m in _STORE_OK_RE.finditer(console)]
        assert len(oks) == 1, (
            f"CHK-STORE-OK-QUIET FAIL: {len(oks)} OKAY-store records, expected 1. "
            f"Console was:\n{console}"
        )
        addr, wrote, rb, restored, nmi = (int(x, 16) for x in oks[0])
        # The OKAY leg runs after the SLVERR store; earlier writes to the same
        # register belong to the reset-wire legs.
        slv = [p[0].seq for p in self._to(pairs, _STORE_ERR_ADDR["SLVERR"])]
        ok_hits = [p for p in self._to(pairs, _OKAY_ADDR) if slv and p[0].seq > slv[-1]]
        ok_bresp = [None if b is None else b.resp for _, b in ok_hits]
        line = (
            f"addr=0x{addr:08x} wrote=0x{wrote:08x} readback=0x{rb:08x} "
            f"restored=0x{restored:08x} aw_count={len(ok_hits)} "
            f"aw/bresp={self._bresp_text(ok_hits) or 'none'} nmi={nmi} expected "
            f"addr=0x{_OKAY_ADDR:08x} aw_count=2 bresp=0b00,0b00 nmi=0 "
            f"readback=wrote restored=0x{_OKAY_RESET:08x} (RDL reset, differs from wrote) "
            f"control_err_store_nmis=" + ",".join(f"{k}:{v}" for k, v in sorted(err_nmis.items()))
        )
        ok = (
            addr == _OKAY_ADDR
            and ok_bresp == [_BRESP["OKAY"]] * 2
            and nmi == 0
            and rb == wrote
            and restored == _OKAY_RESET
            and wrote != _OKAY_RESET
        )
        if not ok:
            self.logger.error("CHK-STORE-OK-QUIET FAIL: %s", line)
            raise AssertionError(f"CHK-STORE-OK-QUIET FAIL: {line}")
        self.logger.info("CHK-STORE-OK-QUIET PASS: %s", line)
