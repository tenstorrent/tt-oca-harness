# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Key Manager POKE image: op encoding, result layout and the image itself.

``hw/sys/sep/dv/cocotb/env/sep_km_poke.py`` encodes POKE op lists and decodes
the KM SRAM result words; ``cocotb/tests/km_rom_poke.parhex`` is the KM image
that executes them. These tests run with no simulator:

* the encoding of every op and the list capacity limits;
* the signature of the committed image matches the host layout;
* the committed image, run on a small RV32E instruction model with a model of
  the KM mailbox and the KMCSR interrupt registers, boots, takes a list from the
  mailbox and writes the results the host decodes (data, slot order, the
  ``slv``/``dec`` nibbles, raw ops, jump and resume, the counting handler, sync
  and the list errors).

The instruction model checks the image against the host layout only. It is not
a model of the DUT and grades nothing about the Key Manager.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests -p 'test_sep_km_poke.py'
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = ROOT / "hw" / "sys" / "sep" / "dv" / "cocotb" / "env"
if str(ENV) not in sys.path:
    sys.path.insert(0, str(ENV))

import sep_km_poke as kp  # noqa: E402

M32 = 0xFFFF_FFFF
MBOX_STATUS = 0x1000C
MBOX_READ = 0x10008
IRQ_STATUS = 0x1400C
IRQ_ENABLE = 0x14010
IRQ_SET = 0x14020
SLVERR_ADDR = 0x13108  # the model answers SLVERR here
DECERR_ADDR = 0x0002_0000  # and DECERR here
SLVERR = 1 << 4
DECERR = 1 << 5


class Trap(Exception):
    pass


def sx(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class PokeModel:
    """RV32E subset with PicoRV32 q-register IRQs, the KM ROM, SRAM, inbound
    mailbox and KMCSR IRQ_STATUS / IRQ_ENABLE / IRQ_SET."""

    def __init__(self, rom: dict[int, int]) -> None:
        self.rom = rom
        self.sram: dict[int, int] = {}
        self.inbound: deque[int] = deque()
        self.x = [0] * 16
        self.q = [0] * 4
        self.pc = 0
        self.mask = M32
        self.irq_active = False
        self.irq_status = 0
        self.irq_enable = 0
        self.ext_lines = 0  # CPU IRQ bits 4 and 5, driven by the test
        self.steps = 0

    # --- bus -----------------------------------------------------------------
    def load(self, addr: int) -> int:
        if addr % 4:
            raise Trap(f"misaligned load 0x{addr:x}")
        if addr < 0x4000:
            return self.rom.get(addr, 0)
        if 0x8000 <= addr < 0x10000:
            return self.sram.get(addr, 0)
        if addr == MBOX_STATUS:
            return 0 if self.inbound else 1
        if addr == MBOX_READ:
            return self.inbound.popleft() if self.inbound else 0
        if addr == IRQ_STATUS:
            return self.irq_status
        if addr == IRQ_ENABLE:
            return self.irq_enable
        if addr == SLVERR_ADDR:
            self.irq_status |= SLVERR
            return 0
        if addr == DECERR_ADDR:
            self.irq_status |= DECERR
            return 0
        return 0x1000_0000 | addr  # any other peripheral word

    def store(self, addr: int, value: int) -> None:
        if addr % 4:
            raise Trap(f"misaligned store 0x{addr:x}")
        if 0x8000 <= addr < 0x10000:
            self.sram[addr] = value & M32
        elif addr == IRQ_STATUS:
            self.irq_status &= ~value
        elif addr == IRQ_ENABLE:
            self.irq_enable = value & 0xFFF
        elif addr == IRQ_SET:
            self.irq_status |= value & 0xFFF
        elif addr == SLVERR_ADDR:
            self.irq_status |= SLVERR
        elif addr == DECERR_ADDR:
            self.irq_status |= DECERR

    def word(self, i: int) -> int:
        return self.sram.get(0x8000 + 4 * i, 0)

    def words(self) -> list[int]:
        return [self.word(i) for i in range(kp.RESULT_WORDS)]

    # --- CPU -----------------------------------------------------------------
    def pending(self) -> int:
        lines = self.ext_lines
        if self.irq_status & self.irq_enable:
            lines |= 1 << 3
        return lines & ~self.mask & 0x38

    def step(self) -> None:
        self.steps += 1
        if not self.irq_active and self.pending():
            self.q[0] = self.pc
            self.q[1] = self.pending()
            self.irq_active = True
            self.pc = 0x10
        insn = self.load(self.pc)
        nxt = (self.pc + 4) & M32
        op = insn & 0x7F
        rd = (insn >> 7) & 0x1F
        f3 = (insn >> 12) & 7
        rs1 = (insn >> 15) & 0x1F
        rs2 = (insn >> 20) & 0x1F
        f7 = insn >> 25
        if op in (0x37, 0x17, 0x6F):
            used = [rd]
        elif op in (0x23, 0x63):
            used = [rs1, rs2]
        elif op == 0x33 or (op == 0x0B and f7 == 0x2C):
            used = [rd, rs1, rs2]
        else:
            used = [rd, rs1]
        if op == 0x0B and f7 in (0, 1):  # getq/setq name a q register in one field
            used = [rd] if f7 == 0 else [rs1]
        if any(r > 15 for r in used):
            raise Trap(f"RV32E register above x15 at pc 0x{self.pc:x}")
        a = self.x[rs1 & 15]
        b = self.x[rs2 & 15]
        val = None
        if insn == 0:
            raise Trap("all-zero word")
        if op == 0x37:
            val = insn & 0xFFFFF000
        elif op == 0x17:
            val = (self.pc + (insn & 0xFFFFF000)) & M32
        elif op == 0x6F:
            imm = (
                (((insn >> 31) & 1) << 20)
                | (((insn >> 12) & 0xFF) << 12)
                | (((insn >> 20) & 1) << 11)
                | (((insn >> 21) & 0x3FF) << 1)
            )
            val = nxt
            nxt = (self.pc + sx(imm, 21)) & M32
        elif op == 0x67:
            val = nxt
            nxt = (a + sx(insn >> 20, 12)) & ~1 & M32
        elif op == 0x63:
            imm = (
                (((insn >> 31) & 1) << 12)
                | (((insn >> 7) & 1) << 11)
                | (((insn >> 25) & 0x3F) << 5)
                | (((insn >> 8) & 0xF) << 1)
            )
            take = {
                0: a == b,
                1: a != b,
                4: sx(a, 32) < sx(b, 32),
                5: sx(a, 32) >= sx(b, 32),
                6: a < b,
                7: a >= b,
            }[f3]
            if take:
                nxt = (self.pc + sx(imm, 13)) & M32
        elif op == 0x03 and f3 == 2:
            val = self.load((a + sx(insn >> 20, 12)) & M32)
        elif op == 0x23 and f3 == 2:
            imm = ((insn >> 25) << 5) | ((insn >> 7) & 0x1F)
            self.store((a + sx(imm, 12)) & M32, b)
        elif op == 0x13:
            imm = sx(insn >> 20, 12) & M32
            sh = (insn >> 20) & 0x1F
            val = {
                0: (a + imm) & M32,
                1: (a << sh) & M32,
                4: a ^ imm,
                5: a >> sh,
                6: a | imm,
                7: a & imm,
            }[f3]
        elif op == 0x33:
            if f7 == 0x20 and f3 == 0:
                val = (a - b) & M32
            else:
                val = {
                    0: (a + b) & M32,
                    1: (a << (b & 31)) & M32,
                    4: a ^ b,
                    5: a >> (b & 31),
                    6: a | b,
                    7: a & b,
                }[f3]
        elif op == 0x0B:
            if f7 == 3:  # maskirq
                val = self.mask
                self.mask = a | 0x7
            elif f7 == 0:  # getq
                val = self.q[rs1 & 3]
            elif f7 == 1:  # setq
                self.q[rd & 3] = a
                rd = 0
            elif f7 == 2:  # retirq
                self.irq_active = False
                nxt = self.q[0]
            elif f7 == 0x2C and f3 in (0, 1, 2):
                val = (a ^ b ^ (f3 << 28)) & M32  # not a CRC; distinct per encoding
            else:
                raise Trap(f"custom0 0x{insn:08x}")
        elif insn == 0x0010_0073:
            raise Trap("ebreak")
        else:
            raise Trap(f"illegal 0x{insn:08x} at pc 0x{self.pc:x}")
        if val is not None and rd:
            self.x[rd] = val & M32
        self.pc = nxt

    def run_until(self, cond, limit: int = 2_000_000) -> None:
        for _ in range(limit):
            if cond():
                return
            self.step()
        raise AssertionError(
            f"model did not reach the condition in {limit} steps; pc=0x{self.pc:x}"
        )

    def state(self):
        return kp.state_of(self.word(kp.W_STATE))

    def boot(self) -> None:
        self.run_until(lambda: self.state() == (kp.ST_BOOT, 0))

    def run_list(self, ops, tag: int = 1, on_sync=None):
        self.inbound.extend(kp.encode_list(ops, tag))
        k = 0
        while True:
            self.run_until(
                lambda: self.state() in ((kp.ST_DONE, tag), (kp.ST_SYNC, tag), (kp.ST_ERROR, tag))
            )
            st = self.state()
            if st[0] != kp.ST_SYNC:
                break
            self.inbound.append(on_sync(k))
            k += 1
            self.run_until(lambda: self.state() != (kp.ST_SYNC, tag))
        return st


def model() -> PokeModel:
    m = PokeModel(kp.read_parhex())
    m.boot()
    return m


class EncodingTest(unittest.TestCase):
    def test_header_and_words(self) -> None:
        op = kp.rdblk(0x12000, 5, 8, raw=True)
        self.assertEqual(op.words, (kp.OP_RDBLK | kp.F_RAW | (5 << 16), 0x12000, 8))
        self.assertEqual(op.slots, 5)
        self.assertFalse(op.reports)
        self.assertEqual(kp.wr2(1, 2, 3, 4, readback=True).words[0], kp.OP_WR2 | kp.F_OPT)
        self.assertEqual(kp.poll(1, 2, 3, 4, ne=True).words[0], kp.OP_POLL | kp.F_OPT)
        self.assertEqual(kp.arm([3, 5], kp.ACT_EXEC, 7).words, (kp.OP_ARM, 0x28, 3 | 7 << 8))
        self.assertEqual(kp.cnt(4).words, (kp.OP_CNT | 4 << 16,))
        words = kp.encode_list([kp.nop(), kp.mark(9)], 7)
        self.assertEqual(words[0], 0x5007_0003)

    def test_limits(self) -> None:
        self.assertEqual(len(kp.encode_list([kp.wrblk(0x8400, [0] * 126)], 1)), 1 + kp.BUF_WORDS)
        with self.assertRaises(ValueError):
            kp.encode_list([kp.wrblk(0x8400, [0] * 127)], 1)
        with self.assertRaises(ValueError):
            kp.encode_list([kp.rdblk(0x8400, kp.N_SLOTS + 1)], 1)
        with self.assertRaises(ValueError):
            kp.encode_list([], 0)
        with self.assertRaises(ValueError):
            kp.arm([2])
        with self.assertRaises(ValueError):
            kp.exec_(kp.EXEC_COUNT)
        with self.assertRaises(ValueError):
            kp.poll(0, 0, 0, 0)

    def test_signature(self) -> None:
        kp.check_image()
        rom = kp.read_parhex()
        self.assertEqual(rom[kp.SIG_ADDR], kp.SIG_MAGIC)
        text = kp.IMAGE_PATH.read_text().splitlines()
        sig_line = 3 + kp.SIG_ADDR // 4 + 6  # W_FLAGS entry of the signature
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.parhex"
            lines = list(text)
            lines[sig_line] = "000000009"
            bad.write_text("\n".join(lines) + "\n")
            with self.assertRaises(AssertionError):
                kp.check_image(bad)


class ImageTest(unittest.TestCase):
    def test_boot_clears_results(self) -> None:
        m = model()
        self.assertTrue(all(m.word(i) == 0 for i in range(1, kp.RESULT_WORDS)))

    def test_reads_writes_and_flags(self) -> None:
        m = model()
        m.sram[0x8400] = 0x1111_2222
        ops = [
            kp.rd(0x8400),
            kp.wr(0x8404, 0xCAFE_F00D),
            kp.rd(0x8404),
            kp.rd(SLVERR_ADDR),
            kp.wr(DECERR_ADDR, 1),
            kp.rd(SLVERR_ADDR, raw=True),
            kp.rd(IRQ_STATUS, raw=True),
            kp.mark(0xA5A5_0001),
            kp.wr2(0x8408, 1, 0x840C, 2, readback=True),
            kp.fill(0x8500, 0x77, 3),
            kp.wrblk(0x8600, [5, 0, 6]),
            kp.copy(0x8600, 0x8700, 3),
            kp.rdblk(0x8700, 3),
            kp.rdblk(SLVERR_ADDR, 2, 0),
            kp.rdloop(0x8500, 4),
            kp.poll(0x8408, 0xFF, 1, 5),
            kp.poll(0x8408, 0xFF, 9, 5),
            kp.poll(0x8408, 0xFF, 1, 5, ne=True),
            kp.nop(),
        ]
        self.assertEqual(m.run_list(ops), (kp.ST_DONE, 1))
        done, slots = kp.progress_of(m.word(kp.W_PROG))
        self.assertEqual((done, slots), (len(ops), kp.list_slots(ops)))
        r = kp.decode(ops, m.words())
        self.assertEqual((r[0].value, r[0].slv, r[0].dec, r[0].clean), (0x1111_2222, 0, 0, True))
        self.assertEqual(r[2].value, 0xCAFE_F00D)
        self.assertEqual((r[3].slv, r[3].dec), (1, 0))
        self.assertEqual((r[4].slv, r[4].dec), (0, 1))
        self.assertEqual(r[5].flags, (None,))
        self.assertEqual(r[6].value & (SLVERR | DECERR), SLVERR | DECERR)  # raw: no clear
        self.assertEqual(r[7].value, 0xA5A5_0001)
        self.assertEqual(r[8].value, 2)
        self.assertEqual([m.sram[0x8500 + 4 * i] for i in range(3)], [0x77] * 3)
        self.assertEqual(r[12].data, (5, 0, 6))
        self.assertTrue(all(f is not None and f.slv == 0 for f in r[12].flags))
        self.assertEqual([f.slv for f in r[13].flags], [1, 1])
        self.assertEqual(r[14].data, (3, 0x77))  # 3 non-zero words, OR
        self.assertEqual(r[15].data, (1, 1))
        self.assertEqual(r[16].data, (1, 5))
        self.assertEqual(r[17].data, (1, 5))

    def test_jump_resume_and_exec(self) -> None:
        m = model()
        # addi x12, x0, 0x55; jalr x0, 0(x1)
        snippet = [0x0550_0613, 0x0000_8067]
        ops = [
            kp.wrblk(0x8800, snippet),
            kp.jump(0x8800),
            kp.exec_(kp.EX_CRC32C_WORD, 3, 5),
            kp.mark(1),
        ]
        self.assertEqual(m.run_list(ops), (kp.ST_DONE, 1))
        r = kp.decode(ops, m.words())
        self.assertEqual(r[1].value, 0x55)
        self.assertEqual(r[2].value, 3 ^ 5)
        self.assertEqual(r[3].value, 1)
        m2 = model()
        m2.inbound.extend(kp.encode_list([kp.mark(7), kp.exec_(kp.EX_EBREAK)], 2))
        with self.assertRaises(Trap):
            m2.run_until(lambda: False, 200_000)
        self.assertEqual(kp.progress_of(m2.word(kp.W_PROG))[0], 1)

    def test_spin_and_handler(self) -> None:
        m = model()
        ops = [
            kp.reseth(0x5E57),
            kp.arm([3], kp.ACT_CLEAR),
            kp.wr(IRQ_ENABLE, 1 << 8),
            kp.wr(IRQ_SET, 1 << 8, raw=True),
            kp.nop(),
            kp.cnt(3),
            kp.rd(IRQ_STATUS, raw=True),
            kp.wr(IRQ_ENABLE, 0),
            kp.wr(IRQ_SET, 1 << 2, raw=True),
            kp.delay(4),
            kp.cnt(3),
            kp.disarm(),
        ]
        self.assertEqual(m.run_list(ops), (kp.ST_DONE, 1))
        r = kp.decode(ops, m.words())
        self.assertEqual(r[5].value, 1)
        self.assertEqual(r[6].value & (1 << 8), 0)
        self.assertEqual(r[10].value, 1)  # enable 0: no entry
        # Line 5 is level: one entry for each re-arm point while it is high, so
        # the points before delay, its 3 iterations and the point before cnt
        # give 5; the point before disarm gives one more, and none after it.
        m.ext_lines = 1 << 5
        ops = [kp.arm([5]), kp.delay(3), kp.cnt(5), kp.disarm(), kp.delay(3), kp.cnt(5)]
        self.assertEqual(m.run_list(ops, tag=2), (kp.ST_DONE, 2))
        r = kp.decode(ops, m.words())
        self.assertEqual((r[2].value, r[5].value), (5, 6))
        # ACT_SPIN: the handler stores IRQ_STATUS and the CPU stays in the spin loop.
        m.ext_lines = 0
        ops = [kp.arm([3], kp.ACT_SPIN), kp.wr(IRQ_ENABLE, 1), kp.wr(IRQ_SET, 1, raw=True)]
        m.inbound.extend(kp.encode_list(ops, 3))
        m.run_until(lambda: m.word(kp.W_HWORD) != 0x5E57)
        self.assertEqual(m.word(kp.W_HWORD) & 1, 1)
        m.run_until(lambda: kp.ENTRY_SPIN <= m.pc < kp.ENTRY_SPIN + 0x18)

    def test_sync_and_errors(self) -> None:
        m = model()
        ops = [kp.sync(), kp.mark(3), kp.sync()]
        self.assertEqual(m.run_list(ops, on_sync=lambda k: 0x100 + k), (kp.ST_DONE, 1))
        r = kp.decode(ops, m.words())
        self.assertEqual([x.value for x in r], [0x100, 3, 0x101])
        m.inbound.append(0x4100_0000)
        m.run_until(lambda: m.state() is not None and m.state()[0] == kp.ST_ERROR)
        self.assertEqual(m.word(kp.W_ERR) >> 24, 1)
        m.inbound.extend([0x5009_0001, 0x0000_00FF])
        m.run_until(lambda: m.state() == (kp.ST_ERROR, 9))
        self.assertEqual(m.word(kp.W_ERR) >> 24, 3)
        self.assertEqual(m.run_list([kp.mark(1)], tag=10), (kp.ST_DONE, 10))

    def test_header_posted_ahead(self) -> None:
        """A header posted while a delay op runs starts the next list."""
        m = model()
        ops_b = [kp.mark(0x77), kp.rd(kp.ADDR_HWORD)]
        tag_b = 5
        header = kp.list_header(ops_b, tag_b)
        self.assertEqual(header, kp.encode_list(ops_b, tag_b)[0])
        m.inbound.extend(kp.encode_list([kp.delay(50)], 4))
        m.run_until(lambda: m.state() == (kp.ST_RUN, 4))
        m.inbound.append(header)
        m.run_until(lambda: m.state() == (kp.ST_DONE, 4))
        self.assertEqual(len(m.inbound), 1, "the image took the header during the delay op")
        m.run_until(lambda: len(m.inbound) == 0)
        self.assertNotEqual(m.state(), (kp.ST_ERROR, tag_b))
        m.inbound.extend(kp.encode_list(ops_b, tag_b)[1:])
        m.run_until(lambda: m.state() == (kp.ST_DONE, tag_b))
        self.assertEqual(kp.decode(ops_b, m.words())[0].value, 0x77)


if __name__ == "__main__":
    unittest.main()
