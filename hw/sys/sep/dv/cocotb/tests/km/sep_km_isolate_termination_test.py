# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A Key Manager store to an isolated key path ends with SLVERR; the KM reset waits for all six paths.

no_cpu host-AXI test with a KM-CPU firmware image
(``+km_rom_hex=km_rom_iso.parhex``). Every other isolation check in this
package drives the SEP host port, so it reaches the ``host_*`` AXI-Lite paths
and never the ``km_*`` ones -- the Key Manager masters those, so only code
running on the KM CPU can present a transaction to them.

Contract (hw/sys/sep/doc/crypto.adoc:94-95, hw/sys/sep/doc/reset_controller.adoc):

  * :139-140 new transactions on an isolated path complete with SLVERR;
  * :143 a domain's reset asserts once all of its paths report isolated;
  * :144 the release reopens the paths;
  * :154 the Key Manager domain isolates all five key paths and the eFuse path.

The ROM is a store server: per inbound mailbox word it stores 0 to the KM bus
address in the word and publishes the IRQ_STATUS AXI error bits read before
and after the store (``km_fw/km_rom_iso.S``). The host draws the destination
order from the seed and, per destination (AES, KMAC, OTBN, HMAC, ABR key
aperture), runs four legs on the same address:

  * CHK-KM-PATH-LIVE-<DEST>   engine released: one B handshake on the key
                              isolate stage, OKAY, path not isolated;
                              IRQ_STATUS error bits 0.
  * CHK-KM-ISO-TERM-<DEST>    engine held in reset, key path isolated (tap 1
                              for the whole leg): one B handshake on the stage
                              with SLVERR while the stage reports isolated;
                              IRQ_STATUS AXI_SLVERR = 1 and AXI_DECERR = 0.
                              Run twice: the second run is the graded FCOV
                              instance and starts only after the first passed.
  * CHK-KM-ISO-REOPEN-<DEST>  engine released again: as the live leg.

Every leg first requires both error bits clear after the ROM's W1C, so the
bits a leg reports belong to that leg's store. The live and reopen legs are
the controls that make the isolated leg discriminating: same instruction, same
address, same image, differing only in whether the host holds the engine in
reset.

Last leg, CHK-KM-RST-ORDER: with every engine released and the ROM parked on a
jump loop, the host writes the Key Manager SW_RESET_N bit to 0. The KM gated
reset must fall, and on the clock it falls the isolate-complete vector of the
six Key Manager paths must be all ones. The request vector of those six paths
must have risen (the request reached the sequencer).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import RESP_NAME
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_km_img_h import AXI_DECERR, AXI_SLVERR
from env.sep_reset_taps import ISO_BENCH
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import ip_c_header
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_crypto_reset_iso_seq import (
    RESP_OKAY,
    RESP_SLVERR,
    RST_ABR,
    RST_AES,
    RST_HMAC,
    RST_KM,
    RST_KMAC,
    RST_OTBN,
    SW_RESET_N,
    SepCryptoResetIso,
)
from seq_lib.sep_km_mailbox_seq import (
    KM_MBOX_BASE,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
)
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

TEST = "sep_km_isolate_termination_test"

# km_rom_iso.S result word layout.
RESULT_MAGIC = 0xB1
PARK_MARK = 0xFF
PARK_WORD = 0
AXI_ERR_BITS = AXI_SLVERR | AXI_DECERR

_MAX_KM_CYCLES = 60_000
_MAX_ISO_CYCLES = 2_000

# Bench isolate stages of the Key Manager domain (reset_controller.adoc:154,
# "All five key paths and the eFuse path").
KM_DOMAIN_PATHS = ("km_otbn", "km_aes", "km_hmac", "km_kmac", "km_abr", "km_efuse")
KM_DOMAIN_MASK = sum(1 << ISO_BENCH.index(p) for p in KM_DOMAIN_PATHS)
KM_STAGES = tuple(ISO_BENCH.index(p) for p in KM_DOMAIN_PATHS)


def _km_addr_map() -> dict[str, int]:
    out: dict[str, int] = {}
    text = ip_c_header("key_manager").with_name("key_manager_addr.h").read_text(encoding="utf-8")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "#define" and parts[1].startswith("KEY_MANAGER_"):
            out[parts[1]] = int(parts[2], 0)
    return out


_KM_MAP = _km_addr_map()


@dataclass(frozen=True)
class KmDest:
    """One Key Manager key destination: its key aperture, reset bit and taps."""

    name: str
    rst_bit: int
    key_addr: int
    stage: int
    gated_rst_port: str
    km_iso_port: str


def _dest(name: str, rst_bit: int) -> KmDest:
    return KmDest(
        name=name,
        rst_bit=rst_bit,
        key_addr=_KM_MAP[f"KEY_MANAGER_{name.upper()}_WRAPPER_KEY_BASE_ADDR"],
        stage=ISO_BENCH.index(f"km_{name}"),
        gated_rst_port=f"{name}_gated_rst_n_probe_o",
        km_iso_port=f"{name}_km_isolated_probe_o",
    )


DESTS = (
    _dest("aes", RST_AES),
    _dest("kmac", RST_KMAC),
    _dest("otbn", RST_OTBN),
    _dest("hmac", RST_HMAC),
    _dest("abr", RST_ABR),
)


def _resp_name(code: int) -> str:
    return RESP_NAME.get(code, f"0x{code:x}")


class _KmBusTap:
    """Per-clock read of the Key Manager isolate stage taps (read only).

    Records each B handshake on a Key Manager stage with its response code and
    the stage's isolate-complete bit on that clock, and counts per stage the
    clocks the isolate-complete bit is 0 and the clocks any tap is unknown.
    """

    def __init__(self, test: sep_base_test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cycle = 0
        self.b_events: list[tuple[int, int, int, int]] = []  # cycle, stage, bresp, iso
        self.iso_low = {st: 0 for st in KM_STAGES}
        self.xz = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None

    def mark(self) -> tuple[int, int, dict[int, int], int]:
        return self.cycle, len(self.b_events), dict(self.iso_low), self.xz

    async def _run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_i)
            self.cycle += 1
            try:
                hs = self.test.rd(dut.iso_slv_b_hs_probe_o)
                bresp = self.test.rd(dut.iso_slv_bresp_probe_o)
                iso = self.test.rd(dut.crypto_isolated_probe_o)
            except AssertionError:
                self.xz += 1
                continue
            for st in KM_STAGES:
                if not (iso >> st) & 1:
                    self.iso_low[st] += 1
                if (hs >> st) & 1:
                    self.b_events.append((self.cycle, st, (bresp >> (2 * st)) & 3, (iso >> st) & 1))


@pyuvm.test()
class sep_km_isolate_termination_test(sep_base_test):
    """A KM master store to an isolated key path ends with SLVERR; KM reset waits for six paths."""

    required_evidence = (
        "CHK-KM-PATH-LIVE-AES",
        "CHK-KM-ISO-TERM-AES",
        "CHK-KM-ISO-REOPEN-AES",
        "CHK-KM-PATH-LIVE-KMAC",
        "CHK-KM-ISO-TERM-KMAC",
        "CHK-KM-ISO-REOPEN-KMAC",
        "CHK-KM-PATH-LIVE-OTBN",
        "CHK-KM-ISO-TERM-OTBN",
        "CHK-KM-ISO-REOPEN-OTBN",
        "CHK-KM-PATH-LIVE-HMAC",
        "CHK-KM-ISO-TERM-HMAC",
        "CHK-KM-ISO-REOPEN-HMAC",
        "CHK-KM-PATH-LIVE-ABR",
        "CHK-KM-ISO-TERM-ABR",
        "CHK-KM-ISO-REOPEN-ABR",
        "CHK-KM-RST-ORDER",
    )

    def _grade(self, ok: bool, chk: str, detail: str) -> None:
        """Log one PASS/FAIL line; on FAIL log it, close the graded window, then raise."""
        if ok:
            self.logger.info("%s PASS: %s", chk, detail)
            return
        self.logger.error("%s FAIL: %s", chk, detail)
        close_graded_window(self.logger)
        raise AssertionError(f"{chk} FAIL: {detail}")

    async def _post_mbox(self, tag: str, word: int) -> None:
        """One inbound mailbox word: separator then data, as the KM images expect."""
        for name, offset, data in (
            ("sep", KM_MBOX_WRITE_SEPARATOR, 1),
            ("data", KM_MBOX_WRITE_DATA, word),
        ):
            seq = SepAxiAccessSeq(
                f"km_iso_{tag}_{name}",
                op=SepAxiOp.WRITE,
                addr=KM_MBOX_BASE + offset,
                wdata=data,
                size=2,
            )
            await self.start_seq(seq)
            assert seq.resp_ok, f"KM mailbox {name} write not OKAY for leg {tag}"

    async def _set_reset(self, rst_bit: int, held: bool, tag: str) -> int:
        """Hold or release one domain by read-modify-write of SW_RESET_N.

        Not ``SepCryptoResetIso.assert_reset``: that writes the register's
        reset default with one bit cleared, and the default holds the Key
        Manager. Here the KM is running firmware, so clobbering its bit would
        reset the CPU whose transaction is the subject. Every other bit must
        read back unchanged.
        """
        live = await self.rst.read_back()
        bit = 1 << rst_bit
        want = ((live & ~bit) if held else (live | bit)) & 0xFFFF_FFFF
        seq = SepAxiAccessSeq(
            f"km_iso_rst_{tag}",
            op=SepAxiOp.WRITE,
            addr=SW_RESET_N,
            wdata=want,
            size=2,
        )
        await self.start_seq(seq)
        assert seq.resp_ok, f"SW_RESET_N write not OKAY ({tag})"
        got = await self.rst.read_back()
        assert got == want, (
            f"SW_RESET_N readback 0x{got:08x} != requested 0x{want:08x} ({tag}); "
            f"before the write 0x{live:08x}"
        )
        return got

    async def _await_word(self, seq_no: int, what: str) -> int:
        """Poll KM SRAM word0 until the ROM publishes leg ``seq_no``."""
        dut = cocotb.top
        word = 0
        for polled in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            # The word can be unknown before the ROM's first store; the poll
            # tolerates that, and the returned word is re-read as fully known.
            word = self.rd(dut.km_sram_word0_o, allow_unknown=True)
            if (word >> 24) == RESULT_MAGIC and ((word >> 16) & 0xFF) == seq_no:
                return self.rd(dut.km_sram_word0_o)
        raise AssertionError(
            f"KM image liveness FAIL: KM SRAM word0=0x{word:08x} after {polled} cycles "
            f"(leg {seq_no} [{what}] never published; the KM image did not reach that leg)"
        )

    async def _await_bit(self, sig, want: int, what: str) -> int:
        """Wait up to _MAX_ISO_CYCLES clocks for a 1-bit tap to read ``want``."""
        for waited in range(_MAX_ISO_CYCLES + 1):
            if self.rd(sig, allow_unknown=True) == want and self.rd(sig) == want:
                return waited
            await ClockCycles(cocotb.top.clk_i, 1)
        raise AssertionError(f"{what}: tap did not read {want} within {_MAX_ISO_CYCLES} clocks")

    async def _store_leg(self, dest: KmDest, tag: str) -> tuple[int, int, list, int, int]:
        """Release the ROM into one store to the destination key aperture.

        Returns (pre bits, post bits, B events on the stage, isolated-0 clocks
        on the stage, unknown-tap clocks) for this leg only.
        """
        self.leg_no = (self.leg_no + 1) & 0xFF
        _, n0, low0, xz0 = self.tap.mark()
        await self._post_mbox(f"{dest.name}_{tag}", dest.key_addr)
        word = await self._await_word(self.leg_no, f"{dest.name} {tag}")
        _, n1, low1, xz1 = self.tap.mark()
        events = [e for e in self.tap.b_events[n0:n1] if e[1] == dest.stage]
        pre = (word >> 8) & 0xFF
        post = word & 0xFF
        self.logger.info(
            "INFO-KM-ISO-LEG: dest=%s leg=%s seq=%d word0=0x%08x pre=0x%02x post=0x%02x b_events=%s",
            dest.name,
            tag,
            self.leg_no,
            word,
            pre,
            post,
            [(c, _resp_name(r), i) for c, _, r, i in events],
        )
        return pre, post, events, low1[dest.stage] - low0[dest.stage], xz1 - xz0

    def _grade_open(self, chk: str, dest: KmDest, leg) -> None:
        """One B handshake, OKAY, stage not isolated; IRQ_STATUS error bits 0."""
        pre, post, events, _, xz = leg
        resp = [(_resp_name(r), i) for _, _, r, i in events]
        ok = (
            pre == 0
            and post == 0
            and xz == 0
            and len(events) == 1
            and events[0][2] == RESP_OKAY
            and events[0][3] == 0
        )
        self._grade(
            ok,
            f"{chk}-{dest.name.upper()}",
            f"addr=0x{dest.key_addr:08x} stage={dest.stage} pre=0x{pre:02x} post=0x{post:02x} "
            f"(want 0x00, 0x00) b_hs={len(events)} (want 1) resp,iso={resp} "
            f"(want [('OKAY', 0)]) unknown_clocks={xz}",
        )

    def _grade_iso(self, dest: KmDest, leg, expect: int) -> None:
        """One B handshake, SLVERR, stage isolated for the whole leg; AXI_SLVERR only."""
        pre, post, events, low, xz = leg
        want_resp = RESP_SLVERR
        resp = [(_resp_name(r), i) for _, _, r, i in events]
        ok = (
            pre == 0
            and post == expect
            and xz == 0
            and low == 0
            and len(events) == 1
            and events[0][2] == want_resp
            and events[0][3] == 1
        )
        self._grade(
            ok,
            f"CHK-KM-ISO-TERM-{dest.name.upper()}",
            f"addr=0x{dest.key_addr:08x} stage={dest.stage} pre=0x{pre:02x} post=0x{post:02x} "
            f"AXI_SLVERR={int(bool(post & AXI_SLVERR))} AXI_DECERR={int(bool(post & AXI_DECERR))} "
            f"(want post=0x{expect:02x}) b_hs={len(events)} (want 1) resp,iso={resp} "
            f"(want [('{_resp_name(want_resp)}', 1)]) isolated_low_clocks={low} (want 0) "
            f"unknown_clocks={xz}",
        )

    async def _dest_legs(self, dest: KmDest) -> None:
        dut = cocotb.top
        gated = getattr(dut, dest.gated_rst_port)
        km_iso = getattr(dut, dest.km_iso_port)
        assert self.rd(gated) == 1 and self.rd(km_iso) == 0, (
            f"{dest.name}: engine reset {self.rd(gated)} / km path isolated {self.rd(km_iso)} "
            "before the live leg, want released (1) and open (0)"
        )

        live = await self._store_leg(dest, "live")
        self._grade_open("CHK-KM-PATH-LIVE", dest, live)

        # Park, then wait for the key path to report isolated before the store,
        # so a pass cannot come from a store that raced the coordinator.
        await self._set_reset(dest.rst_bit, held=True, tag=f"{dest.name}_park")
        waited = await self._await_bit(km_iso, 1, f"{dest.name} km path isolated")
        self.logger.info(
            "OBS-KM-ISO-PARK: dest=%s km path isolated %d clocks after the SW_RESET_N readback",
            dest.name,
            waited,
        )

        # First isolated store: graded with the window closed.
        self._grade_iso(dest, await self._store_leg(dest, "isolated"), AXI_SLVERR)

        # Second isolated store: the graded FCOV instance, after the first passed.
        open_graded_window(TEST, self.logger)
        self._grade_iso(dest, await self._store_leg(dest, "isolated_fcov"), AXI_SLVERR)
        close_graded_window(self.logger)

        await self._set_reset(dest.rst_bit, held=False, tag=f"{dest.name}_release")
        await self._await_bit(gated, 1, f"{dest.name} engine reset released")
        await self._await_bit(km_iso, 0, f"{dest.name} km path reopened")
        reopen = await self._store_leg(dest, "reopen")
        self._grade_open("CHK-KM-ISO-REOPEN", dest, reopen)

    async def _km_reset_leg(self) -> None:
        """CHK-KM-RST-ORDER: the KM gated reset falls only with all six KM paths isolated."""
        dut = cocotb.top
        # Park the ROM on its jump loop, so no KM data access is in flight at
        # the reset.
        self.leg_no = (self.leg_no + 1) & 0xFF
        await self._post_mbox("park", PARK_WORD)
        word = await self._await_word(self.leg_no, "park")
        assert word & 0xFF == PARK_MARK, f"KM image park marker FAIL: word0=0x{word:08x}"

        engines = {d.name: self.rd(getattr(dut, d.gated_rst_port)) for d in DESTS}
        km_rst0 = self.rd(dut.km_gated_rst_n_probe_o)
        iso0 = self.rd(dut.crypto_isolated_probe_o) & KM_DOMAIN_MASK
        assert km_rst0 == 1 and iso0 == 0 and all(engines.values()), (
            f"CHK-KM-RST-ORDER FAIL (precondition): km_gated_rst_n={km_rst0} "
            f"KM paths isolated=0x{iso0:04x} engines released={engines}"
        )

        trace: dict[str, int | None] = {"fall": None, "iso_at_fall": None, "req_seen": 0}
        trace["all_isolated"] = None
        done = {"stop": False}

        async def _watch() -> None:
            cyc = 0
            while not done["stop"]:
                await RisingEdge(dut.clk_i)
                cyc += 1
                rst = self.rd(dut.km_gated_rst_n_probe_o)
                iso = self.rd(dut.crypto_isolated_probe_o) & KM_DOMAIN_MASK
                req = self.rd(dut.crypto_isolate_req_probe_o) & KM_DOMAIN_MASK
                trace["req_seen"] |= req
                if trace["all_isolated"] is None and iso == KM_DOMAIN_MASK:
                    trace["all_isolated"] = cyc
                if rst == 0:
                    trace["fall"] = cyc
                    trace["iso_at_fall"] = iso
                    return

        open_graded_window(TEST, self.logger)
        watcher = cocotb.start_soon(_watch())
        await self._set_reset(RST_KM, held=True, tag="km_park")
        for _ in range(_MAX_ISO_CYCLES):
            if trace["fall"] is not None:
                break
            await ClockCycles(dut.clk_i, 1)
        done["stop"] = True
        if trace["fall"] is None:
            watcher.kill()
            self._grade(
                False,
                "CHK-KM-RST-ORDER",
                f"km_gated_rst_n never fell within {_MAX_ISO_CYCLES} clocks of the KM "
                f"SW_RESET_N write; KM isolate requests seen=0x{trace['req_seen']:04x} "
                f"(want 0x{KM_DOMAIN_MASK:04x})",
            )
        ok = trace["iso_at_fall"] == KM_DOMAIN_MASK and trace["req_seen"] == KM_DOMAIN_MASK
        self._grade(
            ok,
            "CHK-KM-RST-ORDER",
            f"km_gated_rst_n fell at clock {trace['fall']} with KM paths isolated="
            f"0x{trace['iso_at_fall']:04x} (want 0x{KM_DOMAIN_MASK:04x}, stages "
            f"{', '.join(KM_DOMAIN_PATHS)}); all six isolated from clock "
            f"{trace['all_isolated']}; KM isolate requests seen=0x{trace['req_seen']:04x} "
            f"(want 0x{KM_DOMAIN_MASK:04x})",
        )
        close_graded_window(self.logger)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await self.start_seq(sep_km_release_seq("km_iso_release"))
        self.rst = SepCryptoResetIso(self)
        self.leg_no = 0

        order = list(DESTS)
        SepSeededRng(self.random_seed()).shuffle(order)
        self.logger.info(
            "INFO-KM-ISO-ORDER: seed=%d order=%s",
            self.random_seed(),
            [d.name for d in order],
        )

        self.tap = _KmBusTap(self)
        self.tap.start()
        failed = True
        try:
            for dest in order:
                await self._dest_legs(dest)
            await self._km_reset_leg()
            failed = False
        finally:
            if failed:
                # A failure may resume from ReadOnly, where no value can be written.
                await NextTimeStep()
            self.tap.stop()
            close_graded_window(self.logger)
