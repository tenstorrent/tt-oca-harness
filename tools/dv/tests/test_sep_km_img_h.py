# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Key Manager SRAM images: IMG-H report decode and the spin image.

``hw/sys/sep/dv/cocotb/env/sep_km_img_h.py`` decodes the report of the IMG-H
image (``cocotb/tests/km_img_h.parhex``) and builds the spin image and the
CMD_SRAM_LOAD_EXEC image frame. These tests run with no simulator:

* the committed IMG-H fits SRAM write-lock region 0 and its parity nibbles
  match the KM ``.parhex`` format;
* the committed IMG-H, run at 0x8000 on the RV32E instruction model of
  ``test_sep_km_poke.py`` with a model of the KM mailbox, KMCSR, KPV and key
  banks, sends one message that :func:`decode_report` maps back to the values
  the model held (each register, each slot, the free-slot probe, the stores);
* the spin image spins at word 0, its other words are a pure function of the
  seed, and the frame trailer is the CRC-32C of the image words.

The model checks the image against the host layout only. It is not a model of
the DUT and grades nothing about the Key Manager.

Run from the repository root:

    python3 -m pytest tools/dv/tests/test_sep_km_img_h.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = ROOT / "hw" / "sys" / "sep" / "dv" / "cocotb" / "env"
for p in (str(ENV), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sep_km_img_h as ih  # noqa: E402
from sep_crc_golden import crc32c  # noqa: E402
from sep_seeded_rng import SepSeededRng  # noqa: E402
from test_sep_km_poke import PokeModel  # noqa: E402

M32 = 0xFFFF_FFFF
SRAM = 0x8000
MB_WDATA = 0x10000
MB_WSEP = 0x10004
MB_STATUS = 0x1000C
OUT_FULL = 1 << 3
IRQ_STATUS = 0x1400C
VIOL = 0x14024
KPV_WORD = 0x12000
KPV_CTRL = 0x13000
SRAM_WRITE_LOCK_ERR = 1 << 3
KMAC_KEY_CTRL = 0x1A040
TABLE_REGS = {  # report word -> KM address of the register the image reads
    ih.W_IRQ_ENABLE: 0x14010,
    ih.W_KM_IRQ_ENABLE: 0x10014,
    ih.W_IRQ_ENTRY_ADDR: 0x140B8,
    ih.W_IRQ_ENTRY_LOCK: 0x140BC,
    ih.W_SRAM_EXEC_MODE: 0x14038,
    ih.W_OTP_READ_LOCK: 0x14300,
    ih.W_SECRET_VAL0 + 0: 0x14200,
    ih.W_SECRET_VAL0 + 1: 0x14240,
    ih.W_SECRET_VAL0 + 2: 0x14280,
    ih.W_SECRET_VAL0 + 3: 0x142C0,
    ih.W_PUBLIC_VAL0 + 0: 0x14400,
    ih.W_PUBLIC_VAL0 + 1: 0x14440,
    ih.W_PUBLIC_VAL0 + 2: 0x14480,
    ih.W_SRAM_LOCK: 0x1401C,
}
KEY_CTRL_ADDRS = (
    0x1B040,
    KMAC_KEY_CTRL,
    0x19040,
    0x18060,
    0x1C040,
    0x1C140,
    0x1C240,
    0x1C340,
    0x1C420,
)


class ImgHModel(PokeModel):
    """PokeModel CPU with IMG-H at SRAM 0x8000 and models of the KM mailbox
    outbound side, IRQ_STATUS, SRAM write locks, the KPV and the KEY_CTRL
    registers. KM_STATUS reports outbound_full on every third read."""

    def __init__(self, image: list[int], ctrl: list[int], sram_lock: int = 0x8000_0001) -> None:
        super().__init__(rom={})
        self.sram = {SRAM + 4 * i: w for i, w in enumerate(image)}
        self.pc = SRAM
        self.x = [0] * 16
        self.x[5] = SRAM
        for r in range(1, 16):
            if r != 5:
                self.x[r] = 0x5100_0000 | r
        self.mask = M32
        self.lock = sram_lock
        self.viol = 0x0000_0004  # stale, so the clear is visible
        self.irq_status = SRAM_WRITE_LOCK_ERR | (1 << 4)
        self.ctrl = list(ctrl)
        self.kpv: dict[int, int] = {
            KPV_WORD + 4 * i: 0x6B00_0000 | i for i in range(ih.KPV_SLOTS * ih.KPV_SLOT_WORDS)
        }
        self.regs = {a: 0xA000_0000 | w for w, a in TABLE_REGS.items()}
        self.regs.update({a: 0 for a in KEY_CTRL_ADDRS})
        self.sram[0xFFFC] = 0x1234_5678
        self.inbound_empty = 1
        self.status_reads = 0
        self.sep = 0
        self.out: list[tuple[int, int]] = []
        self.other_stores: list[tuple[int, int]] = []

    def load(self, addr: int) -> int:
        if addr % 4:
            raise AssertionError(f"misaligned load 0x{addr:x}")
        if SRAM <= addr < 0x10000:
            return self.sram.get(addr, 0)
        if addr == MB_STATUS:
            self.status_reads += 1
            return self.inbound_empty | (OUT_FULL if self.status_reads % 3 == 1 else 0)
        if addr == IRQ_STATUS:
            return self.irq_status
        if addr == VIOL:
            return self.viol
        if KPV_CTRL <= addr < KPV_CTRL + 4 * ih.KPV_SLOTS:
            return self.ctrl[(addr - KPV_CTRL) // 4]
        if KPV_WORD <= addr < KPV_CTRL:
            if self.ctrl[(addr - KPV_WORD) // 64] & ih.LOCK_USE:
                self.irq_status |= ih.AXI_SLVERR
                return 0
            return self.kpv[addr]
        return self.regs.get(addr, 0x1000_0000 | addr)

    def store(self, addr: int, value: int) -> None:
        value &= M32
        if addr % 4:
            raise AssertionError(f"misaligned store 0x{addr:x}")
        if SRAM <= addr < 0x10000:
            region = (addr - SRAM) // 1024
            if self.lock >> region & 1:
                self.viol |= 1 << region
                self.irq_status |= SRAM_WRITE_LOCK_ERR
            else:
                self.sram[addr] = value
        elif addr == MB_WSEP:
            self.sep = value & 1
        elif addr == MB_WDATA:
            self.out.append((value, self.sep))
            self.sep = 0
        elif addr == IRQ_STATUS:
            self.irq_status &= ~value
        elif addr == VIOL:
            self.viol &= ~value
        elif KPV_WORD <= addr < KPV_CTRL and not self.ctrl[(addr - KPV_WORD) // 64] & ih.LOCK_USE:
            self.kpv[addr] = value
        elif addr in KEY_CTRL_ADDRS:
            self.regs[addr] = value & 1
        else:
            self.other_stores.append((addr, value))

    def run_report(self) -> list[int]:
        self.run_until(lambda: bool(self.out) and self.out[-1][1] == 1, limit=200_000)
        pc = self.pc
        for _ in range(8):
            self.step()
        assert self.pc == pc, "IMG-H does not spin after the message"
        return [w for w, _ in self.out]


def _ctrl(free: int | None) -> list[int]:
    ctrl = [ih.LOCK_USE | 0x1] * 4 + [0x1] * (ih.KPV_SLOTS - 4)
    if free is not None:
        ctrl[free] = 0
        ctrl[free + 3] = 0  # a later free slot: the image takes the lowest
    return ctrl


class ImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.image = ih.read_image()

    def test_fits_region_0_and_parity(self) -> None:
        self.assertLessEqual(len(self.image) * 4, ih.SRAM_REGION_BYTES)
        for line in ih.IMAGE_PATH.read_text().splitlines():
            if line.startswith(("//", "@")) or not line.strip():
                continue
            word = int(line, 16) & M32
            par = 0
            for i in range(4):
                par |= (1 ^ (bin(word >> 8 * i & 0xFF).count("1") & 1)) << i
            self.assertEqual(int(line, 16) >> 32, par)

    def test_report_round_trip(self) -> None:
        m = ImgHModel(self.image, _ctrl(free=6))
        entry = list(m.x)
        irq0 = m.irq_status
        words = m.run_report()
        self.assertEqual([s for _, s in m.out].count(1), 1)
        self.assertEqual(m.other_stores, [])
        rep = ih.decode_report(words)
        self.assertEqual(rep.gpr, {r: entry[r] for r in ih.GPR_ORDER})
        self.assertEqual(rep.gpr[5], SRAM)
        self.assertEqual(rep.irq_status, irq0)
        for w, addr in TABLE_REGS.items():
            self.assertEqual(words[w], 0xA000_0000 | w, hex(addr))
        self.assertEqual(rep.cpu_irq_mask, M32)
        self.assertEqual(rep.inbound_empty, 1)
        self.assertEqual(rep.secret_val0["chiplet_uid"], 0xA000_0000 | ih.W_SECRET_VAL0)
        self.assertEqual(rep.public_val0["sep_sys_id"], 0xA000_0000 | (ih.W_PUBLIC_VAL0 + 2))
        for s, slot in enumerate(rep.slots):
            self.assertEqual(slot.ctrl, m.ctrl[s])
            if slot.lock_use:
                self.assertEqual((slot.word0, slot.slv, slot.dec), (0, 1, 0))
            else:
                self.assertEqual((slot.word0, slot.slv), (0x6B00_0000 | (16 * s), 0))
        self.assertEqual(rep.free_slot, 6)
        self.assertEqual(rep.free_words, tuple(0x6B00_0000 | (16 * 6 + i) for i in range(16)))
        self.assertEqual(rep.free_probe_readback, ih.CTRL_PROBE)
        self.assertEqual(m.kpv[KPV_WORD + 64 * 6], ih.CTRL_PROBE)
        self.assertEqual(tuple(rep.key_ctrl.values()), (0,) * 9)
        self.assertEqual((rep.kmac_readback_set, rep.kmac_readback_clear), (1, 0))
        self.assertEqual(rep.viol_after_clear, 0)
        self.assertEqual((rep.r31_old, rep.r31_readback), (0x1234_5678, 0x1234_5678))
        self.assertEqual(rep.r31_viol, 1 << 31)
        self.assertEqual(rep.r31_region, 31)
        self.assertEqual(rep.own_old, rep.own_readback)
        self.assertEqual(rep.own_viol, 1 << 0)
        self.assertEqual(rep.own_region, 0)
        self.assertEqual(rep.own_old, m.sram[rep.own_addr])

    def test_unlocked_stores_land(self) -> None:
        """With no lock the two stores land: the report shows a dropped store
        only when the DUT drops it."""
        m = ImgHModel(self.image, _ctrl(free=0), sram_lock=0)
        rep = ih.decode_report(m.run_report())
        self.assertEqual(rep.r31_readback, rep.r31_old ^ M32)
        self.assertEqual(rep.own_readback, rep.own_old ^ M32)
        self.assertEqual((rep.r31_viol, rep.own_viol), (0, 0))
        self.assertEqual(rep.free_slot, 0)

    def test_no_free_slot(self) -> None:
        m = ImgHModel(self.image, _ctrl(free=None))
        words = m.run_report()
        rep = ih.decode_report(words)
        self.assertIsNone(rep.free_slot)
        self.assertEqual(rep.free_words, (0,) * 16)
        self.assertEqual(rep.free_probe_readback, 0)
        self.assertNotIn(ih.CTRL_PROBE, m.kpv.values())


class DecodeTest(unittest.TestCase):
    def _words(self) -> list[int]:
        w = [0] * ih.REPORT_WORDS
        w[ih.W_MAGIC], w[ih.W_LAYOUT], w[ih.W_END] = ih.MAGIC, ih.LAYOUT, ih.END_MAGIC
        w[ih.W_FREE_SLOT] = ih.NO_FREE_SLOT
        return w

    def test_rejects_bad_frames(self) -> None:
        ih.decode_report(self._words())
        with self.assertRaises(ih.ImgHReportError):
            ih.decode_report(self._words()[:-1])
        for idx in (ih.W_MAGIC, ih.W_LAYOUT, ih.W_END):
            w = self._words()
            w[idx] ^= 1
            with self.assertRaises(ih.ImgHReportError):
                ih.decode_report(w)
        w = self._words()
        w[ih.W_FREE_SLOT] = ih.KPV_SLOTS
        with self.assertRaises(ih.ImgHReportError):
            ih.decode_report(w)

    def test_magic_is_no_response_header(self) -> None:
        # Response IDs (firmware.adoc, "Response Message Reference").
        self.assertNotIn((ih.MAGIC >> 8) & 0xFF, (0x00, 0x55, 0x56, 0xFE, 0xFF))


class SpinTest(unittest.TestCase):
    def test_word0_spins(self) -> None:
        words = ih.spin_image(8, SepSeededRng(1))
        m = PokeModel(rom={})
        m.load = lambda a: words[(a - SRAM) // 4]  # type: ignore[method-assign]
        m.pc = SRAM
        for _ in range(16):
            m.step()
            self.assertEqual(m.pc, SRAM)
        self.assertEqual(m.x, [0] * 16)

    def test_seeded_and_sized(self) -> None:
        a = ih.spin_image(200, SepSeededRng(7))
        self.assertEqual(a, ih.spin_image(200, SepSeededRng(7)))
        self.assertNotEqual(a[1:], ih.spin_image(200, SepSeededRng(8))[1:])
        self.assertEqual((len(a), a[0]), (200, ih.SPIN_WORD))
        self.assertEqual(ih.spin_image(1, SepSeededRng(7)), [ih.SPIN_WORD])
        for n in (0, ih.FW_WORDS_MAX + 1):
            with self.assertRaises(ValueError):
                ih.spin_image(n, SepSeededRng(7))

    def test_stream_trailer(self) -> None:
        words = ih.spin_image(9, SepSeededRng(3))
        frame = ih.stream_words(words)
        self.assertEqual(frame[:-1], words)
        self.assertEqual(frame[-1], crc32c(b"".join(w.to_bytes(4, "little") for w in words)))
        self.assertEqual(ih.image_crc([0x3433_3231, 0x3837_3635]), crc32c(b"12345678"))
        with self.assertRaises(ValueError):
            ih.stream_words([])


if __name__ == "__main__":
    unittest.main()
