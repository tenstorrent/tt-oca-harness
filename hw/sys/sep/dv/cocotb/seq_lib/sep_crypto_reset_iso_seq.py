# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-IP SW-reset control (sep_crypto_per_ip_reset_isolation_test).

Drives the SEP reset_ctrl SW_RESET_N register over the CPU-LSU master (no_cpu) to
pulse one crypto engine's per-IP reset while a sibling holds a live, golden-checked
crypto RESULT in its datapath output registers. The crypto operations themselves
(SHA-256 on HMAC, ECB-256 on AES) run on the SepHmac / SepAes drivers; this
module only owns the reset-control register so the held-result observation is a
real crypto-datapath state, not a poked status bit.

SW_RESET_N @ 0x1080_3000 (sep_reset_ctrl) is RW and ACTIVE-LOW: bit N high = IP N
released, low = held in reset. Reset default 0x3E (km[0] held; otbn[1]/aes[2]/
hmac[3]/kmac[4]/trng[5] released). A reset pulse for IP N clears that bit in the
generated default, then restores the default, preserving all unrelated domains.
The pulsed engine's whole wrapper rst_ni drops (sep_crypto.sv
hmac_wrapper.rst_ni/aes.rst_ni fed from sep_sw_rst_no.<ip>), clearing its held result;
a sibling's wrapper rst_ni is untouched, so its held result survives -- the isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import SEP_RESET_CTRL, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# sep_reset_ctrl SW_RESET_N (active-low per-IP resets).
SW_RESET_N = sym("SEP_RESET_CTRL_SW_RESET_N_REG_ADDR")
SW_RESET_N_DEFAULT = SEP_RESET_CTRL.reset32("SW_RESET_N")
# Field positions from the generated block, so an RDL move follows here rather
# than silently retargeting a reset request at the wrong domain.
RST_KM = SEP_RESET_CTRL.field_lsb("SW_RESET_N", "km_sw_rst_n")
RST_OTBN = SEP_RESET_CTRL.field_lsb("SW_RESET_N", "otbn_sw_rst_n")
RST_AES = SEP_RESET_CTRL.field_lsb("SW_RESET_N", "aes_sw_rst_n")
RST_HMAC = SEP_RESET_CTRL.field_lsb("SW_RESET_N", "hmac_sw_rst_n")
RST_KMAC = SEP_RESET_CTRL.field_lsb("SW_RESET_N", "kmac_sw_rst_n")
RST_TRNG = SEP_RESET_CTRL.field_lsb("SW_RESET_N", "trng_sw_rst_n")
KM_RST_MASK = SEP_RESET_CTRL.field_mask("SW_RESET_N", "km_sw_rst_n")
RESP_OKAY = 0
RESP_SLVERR = 2

# DIGEST_0 has no generated REG_DEFAULT; OpenTitan HMAC clears it to 0 on rst_ni.
HMAC_DIGEST_RESET = 0


@dataclass(frozen=True)
class CryptoEngine:
    """One crypto engine: display name + its SW_RESET_N bit."""

    name: str
    rst_bit: int


# Representative A/B pair: two independently-resettable crypto engines that each
# hold a live golden-checked result (HMAC DIGEST, AES DATA_OUT).
ENG_HMAC = CryptoEngine("hmac", RST_HMAC)
ENG_AES = CryptoEngine("aes", RST_AES)
ENG_KMAC = CryptoEngine("kmac", RST_KMAC)
ENG_OTBN = CryptoEngine("otbn", RST_OTBN)


class SepCryptoResetIso(SepAxiRegDriver):
    """Direct-AXI driver for the per-IP SW_RESET_N reset-control register."""

    _DRIVER_TAG = "RSTISO"

    async def assert_reset(self, rst_bit: int) -> None:
        """Hold IP ``rst_bit`` in reset (active-low), preserving km held + others released."""
        await self._wr(SW_RESET_N, SW_RESET_N_DEFAULT & ~(1 << rst_bit) & 0xFFFF_FFFF)

    async def release_resets(self) -> None:
        """Restore the reset default (all crypto released, km held)."""
        await self._wr(SW_RESET_N, SW_RESET_N_DEFAULT)

    async def read_back(self) -> int:
        """Read the live SW_RESET_N value (non-vacuity / evidence)."""
        return await self._rd(SW_RESET_N)

    async def probe(
        self,
        addr: int,
        *,
        write: bool = False,
        wdata: int = 0,
        expect_error: bool = False,
    ) -> SepAxiAccessSeq:
        """One 32-bit beat to a crypto CSR; caller asserts the exact resp_code."""
        seq = SepAxiAccessSeq(
            f"rstiso_{'wr' if write else 'rd'}_0x{addr:08x}",
            op=SepAxiOp.WRITE if write else SepAxiOp.READ,
            addr=addr,
            wdata=wdata,
            size=2,
            expect_error=expect_error,
        )
        await self.test.start_seq(seq)
        return seq
