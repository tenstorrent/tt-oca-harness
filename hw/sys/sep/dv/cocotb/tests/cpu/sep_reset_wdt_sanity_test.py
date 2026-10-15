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
from cocotb.triggers import RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_fabric_tap import SepFabricTap, TapBeat
from sep_base_test import sep_base_test
from sep_reg_meta import sym
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

        async def _bite_idle() -> None:
            assert self.rd_known(cocotb.top.wdt_timer_rst_req_o) == 0, (
                "CHK-BITE FAIL: wdt_timer_rst_req_o asserted before firmware "
                "enabled the WDT, so a later 1 cannot be attributed to BITE"
            )
            # The CPU is released; the tap records every LSU access of the firmware.
            lsu_tap.start()

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
            f"readback=wrote restored!=wrote control_err_store_nmis="
            + ",".join(f"{k}:{v}" for k, v in sorted(err_nmis.items()))
        )
        ok = (
            addr == _OKAY_ADDR
            and ok_bresp == [_BRESP["OKAY"]] * 2
            and nmi == 0
            and rb == wrote
            and restored != wrote
        )
        if not ok:
            self.logger.error("CHK-STORE-OK-QUIET FAIL: %s", line)
            raise AssertionError(f"CHK-STORE-OK-QUIET FAIL: {line}")
        self.logger.info("CHK-STORE-OK-QUIET PASS: %s", line)
