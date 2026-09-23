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

Checkers:
  CHK-WIDE-SPLIT   the 64-bit read equals the two 32-bit reads, at every aperture
  CHK-WIDE-NONVAC  every aperture in the table was presented and compared

Pass Criteria: every named checker PASSes. UVM_ERROR == 0.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

SIZE_4B = 2
SIZE_8B = 3

# One entry per axi_dw_downsizer instance inside sep_crypto, naming an 8-byte
# aligned pair of 32-bit registers whose reset values are NOT both zero.
#
# The register choice is the point. A pair that reads zero compares 0 against 0,
# which a converter that dropped the data entirely would also satisfy, so such a
# pair proves nothing about re-beating. Each address below is the low word of a
# pair the generated map gives a non-zero default, so a converter that returned
# zeros, duplicated a word, or swapped the halves fails the compare.
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
# vacuous however green it looks.
MIN_NONZERO_APERTURES = 3


@pyuvm.test()
class sep_crypto_csr_wide_access_test(sep_base_test):
    """64-bit CSR reads across the crypto width converters."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.compared: dict[str, int] = {}
        self.nonzero: list[str] = []
        self.unstable: list[str] = []

        for name, symbol in APERTURES:
            await self._check_aperture(name, sym(symbol))

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
        for note in self.unstable:
            self.logger.info("CHK-WIDE-NONVAC note: %s", note)
        self.logger.info(
            "CHK-WIDE-NONVAC PASS: %d of %d apertures compared a 64-bit read "
            "against its two 32-bit reads, %d of them against a non-zero value; "
            "%d held live state and were reported",
            len(self.compared),
            total,
            len(self.nonzero),
            len(self.unstable),
        )

    async def _rd(self, addr: int, size: int) -> int:
        seq = SepAxiAccessSeq(
            "wide_rd", op=SepAxiOp.READ, addr=addr, length=1 << size, size=size
        )
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
        self.logger.info(
            "CHK-WIDE-SPLIT PASS [%s]: 64-bit read 0x%016x matches its two 32-bit reads",
            name,
            wide,
        )
