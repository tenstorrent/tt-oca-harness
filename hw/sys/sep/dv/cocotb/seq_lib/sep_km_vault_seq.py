# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM key/policy vault: slot extent, SRAM write-lock, and the KPV seal.

RANDCFG. The KM CPU owns KPV CTRL and SRAM_LOCK, so a dedicated ROM
(``km_rom_vault.S``) is the vehicle — not ``rom_main``. The seal walk is
here rather than on the mailbox command set because no command seals a
slot: over that surface an erase always frees. The host mailbox word
selects the legal slot, the SRAM lock region and the seal/free slot
pair; extent endpoints 0 and 63 are always walked, then a store past
``KM_KPV_SIZE`` must raise AXI SLVERR. Result flags land in KM SRAM
word0, with the slot the ROM received echoed back alongside them.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import KM_MBOX_WRITE_DATA, KM_MBOX_WRITE_SEPARATOR
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

N_SLOTS = 64
# Region 0 holds the result word; region 15 hangs in the KM IP SRAM-lock test.
LEGAL_REGIONS = tuple(r for r in range(1, 31) if r != 15)
RESULT_MAGIC = 0xA11A0000
FLAG_SLOT = 0x1
FLAG_EXTENT = 0x2
FLAG_DROP = 0x4
FLAG_VIOL = 0x8
FLAG_IRQ = 0x10
FLAG_W1C = 0x20
SLOT_ECHO_SHIFT = 10
FLAG_SEAL = 0x40
FLAG_RETIRE = 0x80
FLAG_FREE = 0x100
FLAG_ALL = (
    FLAG_SLOT
    | FLAG_EXTENT
    | FLAG_DROP
    | FLAG_VIOL
    | FLAG_IRQ
    | FLAG_W1C
    | FLAG_SEAL
    | FLAG_RETIRE
    | FLAG_FREE
)
KM_MBOX_BASE = sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR")


class SepKmVaultCfg:
    """Single source of truth: the seeded slots and SRAM lock region.

    ``seal_slot`` and ``free_slot`` are the two halves of the seal contrast --
    the same erase, run once on a sealed slot and once on an unsealed one, must
    retire the first and free the second. They are drawn distinct from each
    other and from every slot the extent walk write-locks (0, ``slot``, 63), so
    neither outcome can be attributed to a lock the walk left behind.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.slot = rng.randrange(N_SLOTS)
        self.region = rng.choice(LEGAL_REGIONS)
        taken = {0, N_SLOTS - 1, self.slot}
        self.seal_slot = self._pick_free(rng, taken)
        taken.add(self.seal_slot)
        self.free_slot = self._pick_free(rng, taken)
        self.cfg_word = (
            (self.slot & 0x3F)
            | ((self.region & 0x1F) << 8)
            | ((self.seal_slot & 0x3F) << 16)
            | ((self.free_slot & 0x3F) << 24)
        )
        # The ROM echoes the slot it received into bits [15:10]. Without it the
        # expected word would be the same constant for every seed, and a config
        # word that never arrived could not be told from one that did.
        self.expect = RESULT_MAGIC | FLAG_ALL | ((self.slot & 0x3F) << SLOT_ECHO_SHIFT)

    @staticmethod
    def _pick_free(rng, taken: set[int]) -> int:
        while True:
            cand = rng.randrange(N_SLOTS)
            if cand not in taken:
                return cand

    def summary(self) -> str:
        return (
            f"seed={self.seed} slot={self.slot} region={self.region} "
            f"seal_slot={self.seal_slot} free_slot={self.free_slot} "
            f"cfg=0x{self.cfg_word:08x} expect=0x{self.expect:08x}"
        )


class SepKmVault:
    """Host: post the config word on the SEP-side KM mailbox."""

    def __init__(self, test) -> None:
        self.test = test

    async def post_cfg(self, cfg: SepKmVaultCfg) -> None:
        sep = KM_MBOX_WRITE_SEPARATOR
        data = KM_MBOX_WRITE_DATA
        wr_sep = SepAxiAccessSeq(
            "km_vault_sep", op=SepAxiOp.WRITE, addr=KM_MBOX_BASE + sep, wdata=1, size=2
        )
        await self.test.start_seq(wr_sep)
        if not wr_sep.resp_ok:
            raise AssertionError("KM mailbox WRITE_SEPARATOR not OKAY")
        wr_data = SepAxiAccessSeq(
            "km_vault_cfg", op=SepAxiOp.WRITE, addr=KM_MBOX_BASE + data, wdata=cfg.cfg_word, size=2
        )
        await self.test.start_seq(wr_data)
        if not wr_data.resp_ok:
            raise AssertionError("KM mailbox WRITE_DATA not OKAY")


async def km_vault_release(test) -> None:
    await test.start_seq(sep_km_release_seq("km_vault_release"))
