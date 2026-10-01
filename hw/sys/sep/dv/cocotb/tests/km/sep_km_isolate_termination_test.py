# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""What a Key Manager master transaction receives when its path is isolated.

no_cpu host-AXI test with a KM-CPU firmware image
(``+km_rom_hex=km_rom_iso.parhex``). Every other isolation check in this
package drives the SEP host port, so it reaches the ``host_*`` AXI-Lite paths
and never the ``km_*`` ones -- the Key Manager masters those, so only code
running on the KM CPU can present a transaction to them. This entry is that
vehicle for one path, ``km_hmac``.

The ROM stores to the same HMAC wrapper key address three times, each leg
preceded by a W1C of the two AXI error bits and a readback requiring them
clear, so the bit a leg reports belongs to that leg:

  * CHK-KM-PATH-LIVE    HMAC released: the store completes with neither error
                        bit set.
  * CHK-KM-ISO-TERM     HMAC held in reset, both its paths isolated: the same
                        store raises AXI_SLVERR or AXI_DECERR rather than
                        completing or hanging.
  * CHK-KM-ISO-REOPEN   HMAC released again: the same store is clean.
  * CHK-KM-ISO-PRECOND  every leg began with both error bits clear.

The two clean legs cannot fail by themselves -- "no error" is also what a dead
poll loop reports -- and they are not offered as evidence on their own. They
are the controls that make CHK-KM-ISO-TERM discriminating: same instruction,
same address, same image, differing only in whether the host holds HMAC in
reset. Without them the error leg would be satisfied by an address that always
errors.

The host does not guess when isolation is complete. It parks HMAC and then
waits on ``hmac_km_isolated_probe_o`` -- the ``km_hmac`` bit of the
interconnect's isolate-completion vector -- before releasing the ROM into the
isolated leg, so a pass cannot come from a store that raced the coordinator.

Handshake: the ROM publishes a phase marker in KM SRAM word0 (the
``km_sram_word0_o`` probe) and blocks on an inbound mailbox word between legs.

Coverage note: this claims the ``km_hmac`` path only. The other five KM
destination paths share the mechanism but are not demonstrated here.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_crypto_reset_iso_seq import ENG_HMAC, KM_RST_MASK, SW_RESET_N, SepCryptoResetIso
from seq_lib.sep_km_mailbox_seq import (
    KM_MBOX_BASE,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
)
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

RESULT_MAGIC = 0xB1

FLAG_LIVE = 0x10
FLAG_ISO_TERM = 0x20
FLAG_REOPEN = 0x40
FLAG_PRECOND = 0x80

_MAX_KM_CYCLES = 60_000
_MAX_ISO_CYCLES = 2_000


@pyuvm.test()
class sep_km_isolate_termination_test(sep_base_test):
    """A KM master store to an isolated destination path terminates with an error."""

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
            assert seq.resp_ok, f"KM mailbox {name} write not OKAY for phase {tag}"

    async def _set_hmac_reset(self, held: bool) -> int:
        """Park or release HMAC by read-modify-write of SW_RESET_N.

        Not ``SepCryptoResetIso.assert_reset``: that writes the register's
        reset default with one bit cleared, and the default holds the Key
        Manager. Here the KM is running firmware, so clobbering its bit would
        reset the CPU whose transaction is the subject -- with a read already
        outstanding, which the KM AXI-Lite protocol checker reports as valid
        asserted during reset.
        """
        live = await self.rst.read_back()
        bit = 1 << ENG_HMAC.rst_bit
        want = (live & ~bit) if held else (live | bit)
        seq = SepAxiAccessSeq(
            f"km_iso_rst_{'park' if held else 'release'}",
            op=SepAxiOp.WRITE,
            addr=SW_RESET_N,
            wdata=want & 0xFFFF_FFFF,
            size=2,
        )
        await self.start_seq(seq)
        assert seq.resp_ok, "SW_RESET_N write not OKAY"
        got = await self.rst.read_back()
        assert got == want, f"SW_RESET_N readback 0x{got:08x} != requested 0x{want:08x}"
        km_bit = got & KM_RST_MASK
        assert km_bit == (live & KM_RST_MASK), (
            f"the HMAC reset write disturbed the Key Manager reset bit: 0x{live:08x} -> 0x{got:08x}"
        )
        return got

    async def _await_phase(self, phase: int) -> int:
        """Poll KM SRAM word0 until the ROM publishes this phase marker."""
        dut = cocotb.top
        word = 0
        for polled in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            # The word can be unknown before the ROM's first store; the poll
            # tolerates that, and the returned word is re-read as fully known.
            word = self.rd(dut.km_sram_word0_o, allow_unknown=True)
            if (word >> 24) == RESULT_MAGIC and (word & 0xF) == phase:
                return self.rd(dut.km_sram_word0_o)
        raise AssertionError(
            f"KM image liveness FAIL: KM SRAM word0=0x{word:08x} after {polled} cycles "
            f"(phase {phase} never published; the KM image did not reach that leg)"
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await self.start_seq(sep_km_release_seq("km_iso_release"))
        self.rst = SepCryptoResetIso(self)

        dut = cocotb.top

        # Leg A runs with HMAC released. Prove that here rather than assuming
        # the reset default: a leg A that ran against an already-parked HMAC
        # would report an error and the test would fail for the wrong reason.
        assert int(dut.hmac_gated_rst_n_probe_o.value) == 1, (
            "HMAC is already held in reset before the live leg"
        )
        await self._post_mbox("go", 1)
        await self._await_phase(1)

        # Park HMAC, then WAIT for the km_hmac path to report isolated before
        # releasing the ROM. Without this the isolated leg could race the
        # coordinator and store into a still-open path.
        await self._set_hmac_reset(held=True)
        for _ in range(_MAX_ISO_CYCLES):
            if int(dut.hmac_km_isolated_probe_o.value) == 1:
                break
            await ClockCycles(dut.clk_i, 1)
        else:
            raise AssertionError(
                "km_hmac never reported isolated after the HMAC reset request, so "
                "the isolated leg would not have been run against an isolated path"
            )
        self.logger.info("km_hmac reported isolated; releasing the KM image into the isolated leg")
        await self._post_mbox("parked", 2)
        await self._await_phase(2)

        await self._set_hmac_reset(held=False)
        await ClockCycles(dut.clk_i, 40)
        assert int(dut.hmac_gated_rst_n_probe_o.value) == 1, (
            "HMAC reset did not release before the reopen leg"
        )
        await self._post_mbox("released", 3)
        word = await self._await_phase(3)

        def _bit(flag: int, name: str) -> None:
            assert word & flag, f"{name} FAIL: KM SRAM word0=0x{word:08x} missing 0x{flag:02x}"

        _bit(FLAG_PRECOND, "CHK-KM-ISO-PRECOND")
        self.logger.info(
            "CHK-KM-ISO-PRECOND PASS: every leg began with both AXI error bits clear, "
            "so each reported bit belongs to that leg's store"
        )
        _bit(FLAG_LIVE, "CHK-KM-PATH-LIVE")
        self.logger.info(
            "CHK-KM-PATH-LIVE PASS: KM store to the HMAC key aperture completed with "
            "no AXI error while the path was open"
        )
        _bit(FLAG_ISO_TERM, "CHK-KM-ISO-TERM")
        self.logger.info(
            "CHK-KM-ISO-TERM PASS: the same KM store raised an AXI error while "
            "km_hmac was isolated -- it neither completed nor hung"
        )
        _bit(FLAG_REOPEN, "CHK-KM-ISO-REOPEN")
        self.logger.info(
            "CHK-KM-ISO-REOPEN PASS: the same KM store is clean again after release, "
            "so isolation did not leave the KM path wedged"
        )
