# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 64-bit CSR read must be split by the width converter without changing it.

Every crypto aperture reaches its IP through an `axi_dw_converter` whose
`gen_dw_downsize` arm elaborates: the fabric is 64-bit and the IP register
block is 32-bit. A 64-bit access is therefore not passed through -- the
converter has to turn one slave beat into two master beats and reassemble the
read data in order. That is a contract, and nothing in the suite has tested it:
every existing leaf issues 32-bit beats (`SepAxiRegDriver._AXI_SIZE = 2`), which
take the passthrough arm and never exercise the conversion.

`AxSIZE=3` is the whole stimulus. No burst is involved and none is possible:
`sep_crypto_axi_interconnect.sv:111-112` routes any `AxLEN != 0` to the crypto
error slave at `:175` / `:205`, and `hw/sys/sep/doc/crypto.adoc:117-123` states
that single-beat rule to software. A single 64-bit beat is legal and is what
software issues for a 64-bit load. In the converter that is `conv_ratio = 2`
with a converted length of `1*2-0-1 = 1`
(`vendor/pulp-platform/axi/upstream/src/axi_dw_downsizer.sv:419-426`), so the
`R_INCR_DOWNSIZE` arm runs and returns to `R_IDLE`.

Golden. The 64-bit read is compared against the two 32-bit reads of the same
two words, taken from the DUT's own single-beat path -- the path the rest of
the suite already exercises -- so the comparison is converter-vs-passthrough
and never a re-computation. Each word is read twice first; a word that does not
read the same twice is live state rather than a stable comparand and its
aperture is reported instead of compared.

Addresses come from the generated register map, and only the first two words of
each block are touched: an address past a block's populated extent is refused
by design, and a refusal on this master is a monitor failure, so the test does
not go looking for one.

Frontdoor only: ordinary AXI through the SEP fabric, no force, no backdoor.

Outstanding reads. A read issued after the previous one retired is answered
from a converter that is otherwise idle, so serial traffic exercises one path
however much of it there is. Concurrency is the only shape under which a
converted read can be answered with a DIFFERENT read's data, which is the
failure this phase grades. AXI permits it: several outstanding reads with
different ids, each answered with its own data (IHI 0022 A5.3).

The ids are distinct on purpose. A converter is entitled to steer a new read
whose id matches an in-flight one behind that one to keep responses ordered,
so equal ids would serialise the traffic and undo the concurrency.

The depth is DV-owned (`CRYPTO_CONCURRENT_READS`), not read from the RTL: the
claim is data integrity under concurrency, which holds at any depth. Nothing
here scores how many internal slots the converter has.

Checkers:
  CHK-WIDE-SPLIT   the 64-bit read equals the two 32-bit reads, at every aperture
  CHK-WIDE-NONVAC  every aperture in the table was presented and compared
  CHK-WIDE-OUTSTANDING  eight concurrent 64-bit reads at the entropy source,
                   distinct ids AND distinct addresses, each returning its own
                   data -- the shape that catches one slot answering with
                   another's
  CHK-WIDE-SLOTS   concurrent 64-bit reads at every aperture, distinct ids,
                   each returning the golden -- the same integrity claim as
                   CHK-WIDE-OUTSTANDING, carried to every converted aperture
                   rather than only the entropy source

Pass Criteria: every named checker PASSes. UVM_ERROR == 0.
"""

from __future__ import annotations

import pyuvm
from cocotb.triggers import with_timeout
from env.sep_axi_agent import SepAxiOp
from env.sep_spec_tables import CRYPTO_CONCURRENT_READS
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

SIZE_4B = 2
SIZE_8B = 3

# AXI read-response encoding (IHI 0022 A3.4.4).
RESP_OKAY = 0

# One entry per axi_dw_downsizer instance inside sep_crypto, naming an 8-byte
# aligned pair of 32-bit registers whose reset values are NOT both zero.
#
# The register choice is the point. A pair that reads zero compares 0 against 0,
# which a converter that dropped the data entirely would also satisfy. Every
# pair below has a non-zero 64-bit value. KMAC and ESRC additionally have two
# distinct non-zero halves, so the representative floor can detect zeroing,
# duplication and swapping. Pairs with one zero or equal halves still grade
# exact re-beating at their own converter instance, but do not claim every
# mutation class locally.
#
# The TRNG aperture is absent: a plain 32-bit read of TRNG_REG_MAP_BASE_ADDR
# answers DECERR, so the block is not reachable from this test's quiescent
# state and a wide access there would measure that instead of the converter.
APERTURES = (
    ("aes", "AES_CTRL_AUX_SHADOWED_REG_ADDR"),
    ("hmac", "HMAC_CFG_REG_ADDR"),
    ("kmac", "KMAC_CFG_REGWEN_REG_ADDR"),
    ("otbn", "OTBN_STATUS_REG_ADDR"),
    ("esrc", "ENTROPY_SOURCE_COMPONENT_ID_REG_ADDR"),
)

# At least this many apertures must compare a non-zero golden, or the run is
# vacuous however green it looks. A separate floor requires both halves to be
# non-zero and distinct, which makes zero/duplicate/swap mutations observable.
MIN_NONZERO_APERTURES = 3
MIN_FULL_SENSITIVE_APERTURES = 2

# Concurrent-outstanding phase. Serial reads are answered by an otherwise idle
# converter, so they exercise one path however many are issued; only reads held
# in flight together can be answered with each other's data. The ids are
# distinct because a converter may legitimately order same-id reads behind one
# another, which would serialise the traffic and undo the concurrency.
#
# Eight-byte aligned entropy-source pairs, each with a different non-zero
# reset value in the generated map. Different values are what makes a
# cross-wired slot visible: if the converter returned another slot's data the
# compare fails, where eight identical goldens would hide it.
OUTSTANDING_REGS = (
    "ENTROPY_SOURCE_COMPONENT_ID_REG_ADDR",
    "ENTROPY_SOURCE_FIFO_CTRL_REG_ADDR",
    "ENTROPY_SOURCE_HEALTH_TEST_CTRL_REG_ADDR",
    "ENTROPY_SOURCE_RING_OSC_ENABLE_REG_ADDR",
    "ENTROPY_SOURCE_DECORRELATOR_CTRL_REG_ADDR",
    "ENTROPY_SOURCE_GENERATOR_2_SAMPLE_CLK_CONFIG_REG_ADDR",
    "ENTROPY_SOURCE_GENERATOR_4_SAMPLE_CLK_CONFIG_REG_ADDR",
    "ENTROPY_SOURCE_ALERT_THRESHOLD_REG_ADDR",
)

# How many reads are held in flight. DV-owned (sep_spec_tables), deliberately
# NOT the converter's AxiMaxReads: the graded claim is that concurrent reads
# each return their own data, which holds at any depth. Scoring "every read
# slot was occupied" against the RTL's own slot count would be the DUT
# agreeing with itself.
OUTSTANDING_DEPTH = CRYPTO_CONCURRENT_READS

# A response must arrive within this window. Eight converted reads on a 32-bit
# register bus settle in far fewer cycles; the cap stops a lost response
# spending the run timeout in one wait.
OUTSTANDING_TIMEOUT_NS = 20_000


@pyuvm.test()
class sep_crypto_csr_wide_access_test(sep_base_test):
    """64-bit CSR reads across the crypto width converters."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.compared: dict[str, int] = {}
        self.nonzero: list[str] = []
        self.full_sensitive: list[str] = []
        self.unstable: list[str] = []
        self.slots_spread: list[str] = []

        for name, symbol in APERTURES:
            await self._check_aperture(name, sym(symbol))

        await self._check_outstanding()

        # The same integrity claim at every other aperture, so concurrency is
        # graded at each converted instance rather than only at the entropy
        # source. One address per aperture -- the one the phase above already
        # proved readable -- because concurrency is a property of the reads in
        # flight, not of which address they target, and probing further
        # registers risks a refusal that this master's monitor treats as a
        # failure.
        for name, symbol in APERTURES:
            await self._spread_slots(name, sym(symbol))

        assert self.compared, "CHK-WIDE-NONVAC FAIL: no aperture was compared"
        total = len(APERTURES)
        assert len(self.compared) + len(self.unstable) == total, (
            f"CHK-WIDE-NONVAC FAIL: {len(self.compared)} compared + "
            f"{len(self.unstable)} unstable != {total} apertures in the table"
        )
        assert len(self.nonzero) >= MIN_NONZERO_APERTURES, (
            "CHK-WIDE-NONVAC FAIL: only "
            f"{len(self.nonzero)} aperture(s) compared a non-zero value "
            f"({', '.join(self.nonzero) or 'none'}), below the floor of "
            f"{MIN_NONZERO_APERTURES}. A compare of zero against zero passes "
            "even if the converter returned nothing, so this run would be green "
            "without having tested re-beating."
        )
        assert len(self.full_sensitive) >= MIN_FULL_SENSITIVE_APERTURES, (
            "CHK-WIDE-NONVAC FAIL: only "
            f"{len(self.full_sensitive)} aperture(s) had distinct non-zero halves "
            f"({', '.join(self.full_sensitive) or 'none'}), below the floor of "
            f"{MIN_FULL_SENSITIVE_APERTURES}; zeroing, duplicating or swapping a "
            "half would not be observable across the required representative set"
        )
        assert len(self.slots_spread) == total, (
            f"CHK-WIDE-NONVAC FAIL: the slot spread ran at "
            f"{len(self.slots_spread)} aperture(s), not all {total}, so the "
            "concurrency is ungraded at the rest"
        )
        for note in self.unstable:
            self.logger.info("CHK-WIDE-NONVAC note: %s", note)
        self.logger.info(
            "CHK-WIDE-NONVAC PASS: %d of %d apertures compared a 64-bit read "
            "against its two 32-bit reads, %d of them against a non-zero value; "
            "%d with distinct non-zero halves; %d held live state and were reported",
            len(self.compared),
            total,
            len(self.nonzero),
            len(self.full_sensitive),
            len(self.unstable),
        )

    async def _check_outstanding(self) -> None:
        """Eight concurrent 64-bit reads, distinct ids, distinct addresses.

        Serial reads are answered by an otherwise idle converter, so this is
        the only shape that can show one read being answered with another
        read's data.
        """
        addrs = [sym(n) for n in OUTSTANDING_REGS]
        golden = [await self._rd(a, SIZE_4B) & 0xFFFF_FFFF for a in addrs]
        golden_hi = [await self._rd(a + 4, SIZE_4B) & 0xFFFF_FFFF for a in addrs]
        want = [(h << 32) | lo for lo, h in zip(golden, golden_hi)]

        distinct = len(set(want))
        assert distinct >= 2, (
            "CHK-WIDE-OUTSTANDING FAIL: the eight pairs produced only "
            f"{distinct} distinct value(s), so a slot returning another slot's "
            "data would compare equal and go unseen"
        )

        # Non-blocking: every AR is presented before any R is consumed, which is
        # what holds the low slots busy. Awaiting each read in turn would retire
        # it before the next is issued, leaving nothing concurrent.
        axi = self.env.axi_agent.driver.axi
        events = [
            axi.init_read(address=a, length=8, size=SIZE_8B, arid=i) for i, a in enumerate(addrs)
        ]

        for i, (ev, addr, exp) in enumerate(zip(events, addrs, want)):
            await with_timeout(ev.wait(), OUTSTANDING_TIMEOUT_NS, "ns")
            # worst_resp, not int(resp or 0): an unreadable response must not
            # coerce to OKAY and let the check pass on a measurement that was
            # never taken. It returns RESP_TIMEOUT when nothing is readable.
            code = worst_resp(getattr(ev.data, "resp", None))
            assert code == RESP_OKAY, (
                f"CHK-WIDE-OUTSTANDING FAIL: outstanding read id={i} "
                f"@0x{addr:08x} returned resp={code}, expected OKAY"
            )
            raw = getattr(ev.data, "data", None)
            got = (
                int.from_bytes(bytes(raw), "little")
                if isinstance(raw, (bytes, bytearray))
                else int(raw)
            ) & 0xFFFF_FFFF_FFFF_FFFF
            assert got == exp, (
                f"CHK-WIDE-OUTSTANDING FAIL: outstanding read id={i} "
                f"@0x{addr:08x} returned 0x{got:016x}, but the same words read "
                f"32 bits at a time are 0x{exp:016x}. With eight reads in flight "
                "the converter returned data that is not this transaction's."
            )

        self.logger.info(
            "CHK-WIDE-OUTSTANDING PASS: 8 concurrent 64-bit reads, distinct ids, "
            "each returned its own data (%d distinct values across the set)",
            distinct,
        )

    async def _spread_slots(self, name: str, addr: int) -> None:
        """Hold several 64-bit reads of one address in flight, distinct ids.

        Integrity under concurrency, carried to every converted aperture: each
        read must return the golden, so an aperture answering a concurrent read
        with zeros or stale data fails. A cross-wire between concurrent reads
        is NOT visible here, because every id reads the same word -- the
        entropy-source phase owns that case with distinct addresses. Nothing
        here scores the converter's internal slot count.
        """
        lo = await self._rd(addr, SIZE_4B) & 0xFFFF_FFFF
        hi = await self._rd(addr + 4, SIZE_4B) & 0xFFFF_FFFF
        want = (hi << 32) | lo

        axi = self.env.axi_agent.driver.axi
        events = [
            axi.init_read(address=addr, length=8, size=SIZE_8B, arid=i)
            for i in range(OUTSTANDING_DEPTH)
        ]
        for i, ev in enumerate(events):
            await with_timeout(ev.wait(), OUTSTANDING_TIMEOUT_NS, "ns")
            # worst_resp, not int(resp or 0): an unreadable response must not
            # coerce to OKAY and let the check pass on a measurement that was
            # never taken. It returns RESP_TIMEOUT when nothing is readable.
            code = worst_resp(getattr(ev.data, "resp", None))
            assert code == RESP_OKAY, (
                f"CHK-WIDE-SLOTS FAIL [{name}]: outstanding read id={i} "
                f"@0x{addr:08x} returned resp={code}, expected OKAY"
            )
            raw = getattr(ev.data, "data", None)
            got = (
                int.from_bytes(bytes(raw), "little")
                if isinstance(raw, (bytes, bytearray))
                else int(raw)
            ) & 0xFFFF_FFFF_FFFF_FFFF
            assert got == want, (
                f"CHK-WIDE-SLOTS FAIL [{name}]: outstanding read id={i} "
                f"@0x{addr:08x} returned 0x{got:016x}, expected 0x{want:016x} "
                "from the single-beat golden"
            )
        self.slots_spread.append(name)
        self.logger.info(
            "CHK-WIDE-SLOTS PASS [%s]: %d concurrent 64-bit reads, distinct ids, "
            "each returned its own golden",
            name,
            OUTSTANDING_DEPTH,
        )

    async def _rd(self, addr: int, size: int) -> int:
        seq = SepAxiAccessSeq("wide_rd", op=SepAxiOp.READ, addr=addr, length=1 << size, size=size)
        await self.start_seq(seq)
        assert seq.resp_ok, (
            f"read @0x{addr:08x} size={size} returned resp={seq.resp_code}, expected OKAY"
        )
        return seq.rdata

    async def _check_aperture(self, name: str, base: int) -> None:
        lo_a = await self._rd(base, SIZE_4B) & 0xFFFF_FFFF
        hi_a = await self._rd(base + 4, SIZE_4B) & 0xFFFF_FFFF
        lo_b = await self._rd(base, SIZE_4B) & 0xFFFF_FFFF
        hi_b = await self._rd(base + 4, SIZE_4B) & 0xFFFF_FFFF

        if lo_a != lo_b or hi_a != hi_b:
            self.unstable.append(
                f"{name}: words at 0x{base:08x} changed between two single-beat "
                "reads, so they are live state and cannot serve as a comparand"
            )
            return

        wide = await self._rd(base, SIZE_8B) & 0xFFFF_FFFF_FFFF_FFFF
        golden = (hi_b << 32) | lo_b
        assert wide == golden, (
            f"CHK-WIDE-SPLIT FAIL [{name}] @0x{base:08x}: the 64-bit read returned "
            f"0x{wide:016x}, but the same two words read 32 bits at a time are "
            f"0x{golden:016x} (low=0x{lo_b:08x} high=0x{hi_b:08x}). The width "
            "converter changed the data it was asked only to re-beat."
        )
        self.compared[name] = 2
        if golden:
            self.nonzero.append(name)
        if lo_b and hi_b and lo_b != hi_b:
            self.full_sensitive.append(name)
        self.logger.info(
            "CHK-WIDE-SPLIT PASS [%s]: 64-bit read 0x%016x matches its two "
            "32-bit reads (low=0x%08x high=0x%08x full-sensitive=%d)",
            name,
            wide,
            lo_b,
            hi_b,
            int(bool(lo_b and hi_b and lo_b != hi_b)),
        )
