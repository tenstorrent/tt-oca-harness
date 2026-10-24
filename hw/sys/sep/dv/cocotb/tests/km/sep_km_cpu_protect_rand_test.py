# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM CPU trap kinds, the KPV wipe on a trap, the execute whitelist and the ROM lockout.

no_cpu (``lsu_stub_all_live``) / ``+skip_fuse_sense`` /
``+km_rom_hex=km_rom_poke.parhex``. The POKE image (``tests/km_fw/km_rom_poke.S``)
runs every KM access, trap and jump; it grades nothing. The host posts op lists
through the SEP-side mailbox and reads the results from KM SRAM words 0 to 97
(``KM-RESULT``). Every golden below comes from
``hw/ip/key_manager/doc/architecture.adoc`` (sections "Wipe State",
"Key Manager Control and Status Registers (KMCSR)", "ROM Lockout",
"Unrecoverable Faults", "CRC Accelerator", "Key Manager CPU Interrupt
Processing") and the generated register descriptions (``km_csr.adoc``,
``km_kpv.adoc``, ``hmac_wrapper_key.adoc``, ``memory_map.adoc``), never from the
RTL. The ROM word golden is the committed POKE image file (the stimulus).

Probes: ``KM-RESULT``, ``HOST-MBX`` (``SEP_STATUS``), ``PIC-IRQ`` bit 30
(``sep_ras_o.km_uncorrectable``), ``KM-COUNT`` (``km_rom_req_count_o``,
``km_cpu_fetch_count_o``), ``dbg_sep_reset_n_o``, and the read-only taps ``KM-VALID``
(``km_engine_key_valid_o``), ``KM-KPV`` (``km_kpv_words_o``, the plain-reset
control of CHK-TRAP-WIPE) and ``KM-CSR`` (``km_csr_irq_status_o``). No inject.

Plan (RAND-REP, ``SepSeededRng`` from the run seed). Every seed runs the six trap
kinds (a) to (f) in a drawn order, each in its own boot, and the cases C0 to C6.
The seed draws the misalignment of kind (c), the funct3 of kind (f), the major
opcode of the logged non-zero illegal word, the reset kind after each trap (at
least one warm and one cold among the six), the witnesses, the snippet regions,
the C5 window and the C5 and C6 enables.

Checks:
  CHK-TRAP           after each trap kind PIC bit 30 is 1, stays 1 over the
                     window, and km_rom_req_count_o stops moving.
  CHK-TRAP-WIPE      after the recovery reset all 1024 KPV words read 0; the
                     witnesses read non-zero before the trap.
  CHK-TRAP-SCOPE     the SRAM witness word and the mailbox witness word stay.
  CHK-TRAP-CLR       PIC bit 30 reads 0 after the warm or cold reset.
  CHK-TRAP-CTRL      control: one handler entry for a normal interrupt and the
                     three legal CRC encodings run with no trap.
  CHK-TRAP-ENGINE    a trap clears the HMAC key_valid (the trap is a wipe event);
                     the tap shows 0 and 1 after the two control writes.
  CHK-TRAP-STATUS    KM-CSR IRQ_STATUS.WIPE_STATE is 1 after a trap, 0 before.
  CHK-EXEC           C1, C3, C5, C6: EXEC_VIOLATION is 0 at the jump and rises
                     in the window; ROM_ACCESS_VIOLATION stays 0.
  CHK-EXEC-OK        C0 and C2: the permitted fetch lands its marker with no
                     violation; the ROM data read returns the image word.
  CHK-LOCKOUT        C2 after the lockout: ROM read 0 with ROM_ACCESS_VIOLATION;
                     ROM store clean with ROM_WRITE_ERR only; enable stays 1.
  CHK-LOCKOUT-FETCH  C4: a ROM fetch after the lockout traps and halts the CPU.
  CHK-LOCKOUT-ORDER  C4: ROM_ACCESS_VIOLATION rises in an earlier cycle than
                     PIC bit 30.
  CHK-REGION         region r locked runs (C2); region r + 1 is refused (C3).
  CHK-EXEC-RST       after a warm and a cold reset following C2 the enable reads
                     0 and the ROM word reads back.
  CHK-NONVAC         each "stays 0" check has a hit of the same signal elsewhere
                     in the leaf.

Logged only: ``OBS-TRAP-OPC`` (a non-zero word of a major opcode outside the base
set: the KM CPU ISA is not stated, so its outcome is not graded), the handler
result words of the refused fetches, the snippet marker of a refused fetch, the
CRC results of the legal encodings, the CTRL reads after the reset, and the
ROM store controls before the lockout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env import sep_km_poke as kp
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_reg_meta import CHeaderRegBlock, ip_c_header
from env.sep_rv32_asm import Asm, jalr, li, lui, sw
from env.sep_rv32_asm import lw as rv_lw
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import agg_from_pic
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import (
    KM_STATUS_INBOUND_DEPTH_LSB,
    KM_STATUS_INBOUND_DEPTH_MASK,
)
from seq_lib.sep_km_poke_seq import SepKmPoke
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SW_RESET_N_RESET_DEFAULT, SepSwReset

TEST_NAME = "sep_km_cpu_protect_rand_test"

# --- addresses and fields from the generated map ------------------------------
_ADDR_H = ip_c_header("key_manager").with_name("key_manager_addr.h")
_DEFINE = re.compile(r"^#define\s+(KEY_MANAGER_\w+)(\([^)]*\))?\s+(.+?)\s*$")


def _km_defines() -> tuple[dict[str, int], dict[str, tuple[int, ...]]]:
    """Plain addresses, and (base, stride, ...) of the indexed ones."""
    plain: dict[str, int] = {}
    arrays: dict[str, tuple[int, ...]] = {}
    for line in _ADDR_H.read_text(encoding="utf-8").splitlines():
        m = _DEFINE.match(line)
        if not m:
            continue
        name, params, body = m.groups()
        nums = tuple(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]+)", body))
        if params:
            arrays[name] = nums
        elif len(nums) == 1:
            plain[name] = nums[0]
    return plain, arrays


_PLAIN, _ARRAYS = _km_defines()


def _a(name: str) -> int:
    return _PLAIN[f"KEY_MANAGER_{name}"]


IRQ_STATUS_A = _a("KMCSR_IRQ_STATUS_BASE_ADDR")
IRQ_ENABLE_A = _a("KMCSR_IRQ_ENABLE_BASE_ADDR")
IRQ_SET_A = _a("KMCSR_IRQ_SET_BASE_ADDR")
SRAM_LOCK_A = _a("KMCSR_SRAM_LOCK_BASE_ADDR")
SRAM_EXEC_MODE_A = _a("KMCSR_SRAM_EXEC_MODE_BASE_ADDR")
HMAC_KEY_CTRL_A = _a("HMAC_WRAPPER_KEY_KEY_CTRL_BASE_ADDR")
SRAM_BASE = _a("SRAM_BASE_ADDR")
KPV_BASE = _a("KPV_BASE_ADDR")
_KPV_WORD = _ARRAYS["KEY_MANAGER_KPV_KEY_ENTRY_WORD_BASE_ADDR"]  # base, entry, word
_KPV_CTRL = _ARRAYS["KEY_MANAGER_KPV_CTRL_BASE_ADDR"]  # base, stride

# km_kpv.adoc: KEY_ENTRY[64].WORD[16] and CTRL[64].
KPV_SLOTS = 64
KPV_WORDS_PER_SLOT = 16
KPV_WORDS = KPV_SLOTS * KPV_WORDS_PER_SLOT

# architecture.adoc, "SRAM Write Locking": 32 regions of 1 KB, one per SRAM_LOCK bit.
SRAM_REGION_BYTES = 0x400
# Contract range of a drawn snippet region; region 0 holds the POKE context.
REGION_MIN, REGION_MAX = 1, 30

# architecture.adoc, executable regions table: the VROM window. A build without
# OCAH_KM_VROM treats it as unmapped, and a fetch pulses EXEC_VIOLATION.
VROM_BASE = 0x1000_0000
# Contract C5: the peripheral windows (mailbox, KPV, KMCSR, DRBG sampler).
PERIPH_WINDOWS = (
    _a("MAILBOX_KM_BASE_ADDR"),
    _a("KPV_BASE_ADDR"),
    _a("KMCSR_BASE_ADDR"),
    _a("DRBG_SAMPLER_BASE_ADDR"),
)

_KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
_IRQ = _KM_CSR.fields("IRQ_STATUS_REG")
_EN = _KM_CSR.fields("IRQ_ENABLE_REG")
_SET = _KM_CSR.fields("IRQ_SET_REG")
IRQ_ROM_WRITE_ERR = _IRQ["ROM_WRITE_ERR"]["bm"]
IRQ_AXI_SLVERR = _IRQ["AXI_SLVERR"]["bm"]
IRQ_AXI_DECERR = _IRQ["AXI_DECERR"]["bm"]
IRQ_WIPE_STATE = _IRQ["WIPE_STATE"]["bm"]
IRQ_OTP_CHANGE = _IRQ["OTP_CHANGE"]["bm"]
IRQ_EXEC_VIOL = _IRQ["EXEC_VIOLATION"]["bm"]
IRQ_ROM_ACC_VIOL = _IRQ["ROM_ACCESS_VIOLATION"]["bm"]
IRQ_DEFINED = sum(m["bm"] for n, m in _IRQ.items() if n != "RSVD")
EN_OTP_CHANGE = _EN["OTP_CHANGE_EN"]["bm"]
EN_EXEC_VIOL = _EN["EXEC_VIOLATION_EN"]["bm"]
SET_OTP_CHANGE = _SET["OTP_CHANGE_SET"]["bm"]
_EXEC = _KM_CSR.fields("SRAM_EXEC_MODE_REG")
EXEC_ENABLE = _EXEC["ENABLE"]["bm"]

_KPV = CHeaderRegBlock("KM_KPV", ip_c_header("key_manager").with_name("km_kpv.h"))
_CTRL = _KPV.fields("CTRL_REG")
KPV_LOCKS = {
    "lock_write": _CTRL["LOCK_WRITE"]["bm"],
    "lock_use": _CTRL["LOCK_USE"]["bm"],
    "seal": _CTRL["SEAL"]["bm"],
}
_HMAC = CHeaderRegBlock(
    "HMAC_WRAPPER_KEY", ip_c_header("key_manager").with_name("hmac_wrapper_key.h")
)
HMAC_KEY_VALID = _HMAC.fields("KEY_CTRL_REG")["KEY_VALID"]["bm"]
# KM-VALID tap bit order (tb/sep_tb_signal_list.svh): bit 0 is the HMAC bank.
KM_VALID_HMAC_BIT = 0

# PIC-IRQ: aggregator bit of PIC source "KM unrecoverable error" (bit 30).
KM_UNREC_BIT = agg_from_pic("KM unrecoverable error")

# --- test parameters ----------------------------------------------------------
WINDOW_CLKS = 5000  # observation window (contract test parameter)
SETTLE_CLKS = 4  # clocks after the PIC bit 30 rise before the fetch-count baseline
TRAP_RISE_BOUND = 400_000  # bounded wait for the trap after the trap list starts
JUMP_BOUND = 400_000  # bounded wait for the image to reach its jump
MARKER_BOUND = 200_000  # bounded wait for a snippet or spin-loop result word
SEP_RESET_BOUND = 20_000  # bounded wait for dbg_sep_reset_n_o
WITNESS_DELAY = 1000  # idle POKE iterations between the witness push and the trap
RDLOOP_TIMEOUT = 4_000_000  # the 1024-word KPV read loop

# Result words of the snippets (region 0, inside the KM-RESULT probe). The
# lists of a snippet boot use fewer than 72 slots, so no slot reaches them.
W_P = 90  # P: +0 start marker, +1 IRQ_STATUS at entry, +2 ROM read data,
#            +3 IRQ_STATUS after the ROM read, +4 IRQ_STATUS after the ROM
#            store, +5 SRAM_EXEC_MODE after the 0 write, +6 end marker
W_S_MARK = 97  # S: marker word
SENTINEL_WORDS = 8  # words 90..97
MAX_SNIPPET_SLOTS = W_P - kp.W_DATA

# Host-chosen stimulus markers: what the snippets store, never a DUT result.
MARK_S = 0x5EC5_0001
MARK_S_UNLOCKED = 0x5EC5_0003  # C1 boot B: a snippet that differs from boot A's
MARK_P_START = 0x5EC5_0002
MARK_P_END = 0x5EC5_00FF
MARKERS = (MARK_S, MARK_S_UNLOCKED, MARK_P_START, MARK_P_END)

TRAP_KINDS = ("a", "b", "c", "d", "e", "f")
TRAP_TEXT = {
    "a": "EBREAK with the interrupts masked",
    "b": "the all-zero word with the interrupts masked",
    "c": "a misaligned word access with the interrupts masked",
    "d": "EBREAK inside the handler",
    "e": "the all-zero word inside the handler",
    "f": "custom0 funct7 0101100 with an undefined funct3",
}
MISALIGNED = {
    ("lw", 1): kp.EX_LW_PLUS1,
    ("lw", 2): kp.EX_LW_PLUS2,
    ("sw", 1): kp.EX_SW_PLUS1,
    ("sw", 2): kp.EX_SW_PLUS2,
}


def kpv_word_addr(slot: int, word: int) -> int:
    base, entry_stride, word_stride = _KPV_WORD
    return base + slot * entry_stride + word * word_stride


def kpv_ctrl_addr(slot: int) -> int:
    base, stride = _KPV_CTRL
    return base + slot * stride


def region_base(r: int) -> int:
    return SRAM_BASE + r * SRAM_REGION_BYTES


def irq_text(v: int) -> str:
    names = [n for n, m in _IRQ.items() if n != "RSVD" and v & m["bm"]]
    return "|".join(names) or "none"


def _bits(v: int) -> list[int]:
    return [b for b in range(v.bit_length()) if (v >> b) & 1]


def _nz(rng: SepSeededRng, avoid: tuple[int, ...] = ()) -> int:
    while True:
        v = rng.getrandbits(32)
        if v and v not in avoid:
            return v


def _split(addr: int) -> tuple[int, int]:
    """(lui immediate, signed 12-bit offset) of ``addr``."""
    hi = ((addr + 0x800) >> 12) & 0xFFFFF
    lo = addr - (hi << 12)
    return hi, lo


def snippet_s(marker: int) -> list[int]:
    """Five instructions: store ``marker`` to the S marker word, jump to the ROM spin loop."""
    hi, lo = _split(kp.sram_addr(W_S_MARK))
    words = [*li(7, marker), lui(8, hi), sw(7, 8, lo), jalr(0, 0, kp.ENTRY_SPIN)]
    assert len(words) == 5
    return words


def snippet_p(base: int, rom_addr: int, rom_store: int) -> list[int]:
    """SRAM-resident snippet P; it never fetches from ROM (contract, BFM)."""
    a = Asm(base)
    a.li(8, kp.sram_addr(W_P))
    a.li(7, MARK_P_START).op(sw(7, 8, 0))
    a.li(9, IRQ_STATUS_A)
    a.op(rv_lw(7, 9, 0), sw(7, 8, 4))
    a.li(7, IRQ_DEFINED).op(sw(7, 9, 0))
    a.li(6, rom_addr).op(rv_lw(7, 6, 0), sw(7, 8, 8))
    a.op(rv_lw(7, 9, 0), sw(7, 8, 12))
    a.li(7, IRQ_DEFINED).op(sw(7, 9, 0))
    a.li(5, rom_store).op(sw(5, 6, 0))
    a.op(rv_lw(7, 9, 0), sw(7, 8, 16))
    a.li(6, SRAM_EXEC_MODE_A).op(sw(0, 6, 0), rv_lw(7, 6, 0), sw(7, 8, 20))
    a.li(7, MARK_P_END).op(sw(7, 8, 24))
    a.label("spin").j("spin")
    return a.words()


def kpv_reset_control_fault(
    kind: str,
    slots: list[int],
    locks: dict[int, str],
    words: dict[int, tuple[int, ...]],
    tap_after: dict[int, tuple[int, ...]],
    port_after: dict[int, kp.PokeResult],
    ctrl_after: list[int],
) -> str | None:
    """None when every locked slot kept its words over a plain reset, else the failure.

    The stored words are graded on KM-KPV for every slot. A slot whose CTRL reads
    0 after the reset (locks cleared) is also graded on the KM port, with every
    read free of slv and dec. A slot still locked after the reset is not read on
    the port, because lock_use or seal refuses that read.
    """
    for i, s in enumerate(slots):
        if tap_after[s] != words[s]:
            return (
                f"CHK-TRAP-WIPE FAIL: control: KM-KPV slot {s} ({locks[s]}) holds "
                f"{[hex(v) for v in tap_after[s]]} after a plain {kind} reset, wrote "
                f"{[hex(v) for v in words[s]]}; a reset alone overwrote a locked slot"
            )
        if ctrl_after[i]:
            continue
        r = port_after[s]
        bad = [k for k, f in enumerate(r.flags) if f is None or f.slv or f.dec]
        if bad:
            return (
                f"CHK-TRAP-WIPE FAIL: control: slot {s} ({locks[s]}) port reads {bad} reported "
                f"slv or dec after a plain {kind} reset with CTRL 0"
            )
        if tuple(r.data) != words[s]:
            return (
                f"CHK-TRAP-WIPE FAIL: control: slot {s} ({locks[s]}) reads "
                f"{[hex(v) for v in r.data]} on the port after a plain {kind} reset, wrote "
                f"{[hex(v) for v in words[s]]}"
            )
    return None


# --- plan -----------------------------------------------------------------------


@dataclass
class Witness:
    slots: tuple[int, ...]
    words: dict[int, tuple[int, ...]]
    locks: dict[int, str]
    sram: int
    mbox: int


@dataclass
class Plan:
    seed: int
    kind_order: list[str]
    reset_after: dict[str, str]
    mis_access: str
    mis_offset: int
    mis_scratch: int
    mis_data: int
    f3: int
    obs_opcode: str
    rom_addr: int
    rom_word: int
    rom_store: int
    c1_regions: dict[str, int]
    c2_region: int
    c4_region: int
    c5_window: int
    c5_enable: int
    c6_enable: int
    crc_operands: tuple[int, int]
    rng: SepSeededRng = field(repr=False)

    @classmethod
    def draw(cls, seed: int) -> Plan:
        rng = SepSeededRng(seed)
        order = list(TRAP_KINDS)
        rng.shuffle(order)
        resets = [rng.choice(("warm", "cold")) for _ in order]
        if len(set(resets)) == 1:
            flip = rng.randrange(len(resets))
            resets[flip] = "cold" if resets[flip] == "warm" else "warm"
        image = kp.read_parhex()
        rom_addrs = [
            a
            for a in range(kp.EXEC_BASE, kp.EXEC_BASE + kp.EXEC_COUNT * kp.EXEC_ENTRY_BYTES, 4)
            if image.get(a, 0)
        ]
        rom_addr = rng.choice(rom_addrs)
        rom_word = image[rom_addr]
        mis_access, mis_offset = rng.choice(sorted(MISALIGNED))
        scratch = region_base(rng.randrange(REGION_MIN, REGION_MAX + 1)) + 4 * rng.randrange(256)
        return cls(
            seed=seed,
            kind_order=order,
            reset_after=dict(zip(order, resets, strict=True)),
            mis_access=mis_access,
            mis_offset=mis_offset,
            mis_scratch=scratch,
            mis_data=_nz(rng),
            f3=rng.randrange(3, 8),
            obs_opcode=rng.choice(sorted(kp.EX_MAJOR_OPCODE)),
            rom_addr=rom_addr,
            rom_word=rom_word,
            rom_store=_nz(rng, (rom_word,)),
            c1_regions=dict(
                zip(
                    ("locked", "unlocked"),
                    rng.sample(range(REGION_MIN, REGION_MAX + 1), 2),
                    strict=True,
                )
            ),
            c2_region=rng.randrange(REGION_MIN, REGION_MAX + 1),
            c4_region=rng.randrange(REGION_MIN, REGION_MAX + 1),
            c5_window=rng.choice(PERIPH_WINDOWS),
            c5_enable=rng.randrange(2),
            c6_enable=rng.randrange(2),
            crc_operands=(_nz(rng), _nz(rng)),
            rng=rng,
        )

    def draw_lines(self) -> list[str]:
        return [
            "DRAW kind_order=" + ",".join(self.kind_order),
            "DRAW reset_after=" + ",".join(f"{k}:{self.reset_after[k]}" for k in self.kind_order),
            f"DRAW kind_c access={self.mis_access} offset=+{self.mis_offset} "
            f"base=0x{self.mis_scratch:08x} data=0x{self.mis_data:08x}",
            f"DRAW kind_f funct3={self.f3}",
            f"DRAW obs_opcode={self.obs_opcode}",
            f"DRAW rom_addr=0x{self.rom_addr:05x} rom_word=0x{self.rom_word:08x} "
            f"rom_store=0x{self.rom_store:08x}",
            f"DRAW c1_region_locked={self.c1_regions['locked']} "
            f"c1_region_unlocked={self.c1_regions['unlocked']}",
            f"DRAW c2_region={self.c2_region} c3_region={self.c2_region + 1}",
            f"DRAW c4_region={self.c4_region}",
            f"DRAW c5_window=0x{self.c5_window:05x} c5_enable={self.c5_enable}",
            f"DRAW c6_enable={self.c6_enable}",
            "DRAW crc_operands=" + ",".join(f"0x{v:08x}" for v in self.crc_operands),
        ]

    def witness(self) -> Witness:
        slots = tuple(self.rng.sample(range(KPV_SLOTS), 4))
        words = {s: tuple(_nz(self.rng) for _ in range(KPV_WORDS_PER_SLOT)) for s in slots}
        locks = {s: self.rng.choice(sorted(KPV_LOCKS)) for s in slots}
        return Witness(slots, words, locks, _nz(self.rng), _nz(self.rng))

    def sentinel(self) -> int:
        # Bit 31 set: IRQ_STATUS bits [31:12] are reserved, so no IRQ_STATUS
        # copy of the image can equal the sentinel.
        while True:
            v = self.rng.getrandbits(32) | 0x8000_0000
            if v not in MARKERS:
                return v


@dataclass
class JumpWindow:
    """KM-CSR IRQ_STATUS and PIC bit 30 from the jump to the end of the window."""

    tag: int
    jump_cycle: int
    irq_at_jump: int
    err_at_jump: int
    rise: dict[int, int]
    err_rise: int | None
    irq_or: int


@pyuvm.test()
class sep_km_cpu_protect_rand_test(sep_base_test):
    """KM CPU traps, KPV wipe on a trap, execute whitelist and ROM lockout (POKE)."""

    required_evidence = (
        "CHK-TRAP",
        "CHK-TRAP-WIPE",
        "CHK-TRAP-SCOPE",
        "CHK-TRAP-CLR",
        "CHK-TRAP-CTRL",
        "CHK-TRAP-ENGINE",
        "CHK-TRAP-STATUS",
        "CHK-EXEC",
        "CHK-EXEC-OK",
        "CHK-LOCKOUT",
        "CHK-LOCKOUT-FETCH",
        "CHK-LOCKOUT-ORDER",
        "CHK-REGION",
        "CHK-EXEC-RST",
        "CHK-NONVAC",
    )

    # --- probes -----------------------------------------------------------------
    def _err(self) -> int:
        vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << KM_UNREC_BIT)
        return (vec >> KM_UNREC_BIT) & 1

    def _irq(self) -> int:
        return self.rd_known(cocotb.top.km_csr_irq_status_o, mask=IRQ_DEFINED)

    def _rom_count(self) -> int:
        return self.rd_known(cocotb.top.km_rom_req_count_o)

    def _fetch_count(self) -> int:
        return self.rd_known(cocotb.top.km_cpu_fetch_count_o)

    def _hmac_valid(self) -> int:
        vec = self.rd_known(cocotb.top.km_engine_key_valid_o, mask=1 << KM_VALID_HMAC_BIT)
        return (vec >> KM_VALID_HMAC_BIT) & 1

    async def _mbox_depth(self) -> int:
        status = await self.poke.mbox.read_status()
        return (status >> KM_STATUS_INBOUND_DEPTH_LSB) & KM_STATUS_INBOUND_DEPTH_MASK

    async def _graded(self, on: bool) -> None:
        # The gate is a signal write, which cocotb refuses in the ReadOnly phase.
        await RisingEdge(cocotb.top.clk_i)
        if on:
            open_graded_window(TEST_NAME, self.logger)
        else:
            close_graded_window(self.logger)

    @staticmethod
    def _field(value: int, mask: int, what: str, log) -> int:
        """The RDL field bits of ``value``; the reserved bits are logged with their mask."""
        rsvd_mask = 0xFFFF_FFFF & ~mask
        if value & rsvd_mask:
            log.info(
                "LOG %s reserved bits 0x%08x (mask 0x%08x) not graded",
                what,
                value & rsvd_mask,
                rsvd_mask,
            )
        return value & mask

    # --- resets -------------------------------------------------------------------
    async def _wait_sep_reset_release(self) -> int:
        for cycle in range(1, SEP_RESET_BOUND + 1):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd(cocotb.top.dbg_sep_reset_n_o, allow_unknown=True):
                return cycle
        raise AssertionError(
            f"dbg_sep_reset_n_o did not read 1 within {SEP_RESET_BOUND} clocks; the KM "
            "release would be lost"
        )

    async def _reset(self, kind: str) -> None:
        """Warm: SW_RESET_N bit 0 low, then high. Cold: an rst_ni pulse, then 0x7F."""
        await self.poke.prepare_reset()
        if kind == "warm":
            await self.swrst.park("km")
            await self.swrst.release("km")
        else:
            info = await self.pulse_rst_ni(release_bound=SEP_RESET_BOUND)
            self.swrst.value = SW_RESET_N_RESET_DEFAULT
            after = await self.swrst.read_back()
            self.logger.info(
                "LOG cold reset: release_clks=%d SW_RESET_N=0x%08x after rst_ni",
                info["release_clks"],
                after,
            )
            await self.swrst.release("km")
        waited = await self.poke.wait_boot()
        self.logger.info("POKE boot after a %s reset (%d clocks)", kind, waited)

    # --- windows --------------------------------------------------------------------
    async def _hold_window(self) -> tuple[int, int, int]:
        """(clocks with bit 30 high, fetch count after the settle, fetch count at the end)."""
        high = 0
        rom0 = None
        for i in range(WINDOW_CLKS):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            high += self._err()
            if i == SETTLE_CLKS - 1:
                rom0 = self._rom_count()
        return high, rom0, self._rom_count()

    async def _fetch_hold_window(self) -> tuple[int, int, int, int]:
        """(clocks with bit 30 high, CPU fetch count at the start, after the settle, at the end)."""
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        f_start = self._fetch_count()
        high = 0
        f_settle = None
        for i in range(WINDOW_CLKS):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            high += self._err()
            if i == SETTLE_CLKS - 1:
                f_settle = self._fetch_count()
        return high, f_start, f_settle, self._fetch_count()

    async def _quiet_window(self) -> tuple[int, int, int]:
        """(clocks with bit 30 high, fetch count at the start, fetch count at the end)."""
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        rom0 = self._rom_count()
        high = 0
        for _ in range(WINDOW_CLKS):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            high += self._err()
        return high, rom0, self._rom_count()

    async def _wait_ops_done(self, n: int, what: str) -> int:
        """Bounded wait until PROG shows at least ``n`` ops completed in the running list."""
        for cycle in range(0, MARKER_BOUND, 16):
            if self.poke.progress()[0] >= n:
                return cycle
            await ClockCycles(cocotb.top.clk_i, 16)
        raise AssertionError(
            f"{what}: PROG shows {self.poke.progress()[0]} ops completed after "
            f"{MARKER_BOUND} clocks, expected {n}"
        )

    async def _wait_err_rise(self, what: str) -> int:
        for cycle in range(1, TRAP_RISE_BOUND + 1):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self._err():
                return cycle
        raise AssertionError(
            f"CHK-TRAP FAIL: {what}: PIC bit 30 (sep_ras_o.km_uncorrectable) did not rise within "
            f"{TRAP_RISE_BOUND} clocks"
        )

    async def _watch_jump(self) -> JumpWindow:
        """From the first clock that STATE reads JUMP, sample WINDOW_CLKS clocks."""
        top = cocotb.top
        n = 0
        while True:
            await RisingEdge(top.clk_i)
            await ReadOnly()
            n += 1
            st = kp.state_of(self.rd(top.km_sram_word0_o, allow_unknown=True))
            if st is not None and st[0] == kp.ST_JUMP:
                break
            if n > JUMP_BOUND:
                raise AssertionError(f"POKE never reached its jump within {JUMP_BOUND} clocks")
        jw = JumpWindow(st[1], n, self._irq(), self._err(), {}, None, 0)
        prev_irq, prev_err = jw.irq_at_jump, jw.err_at_jump
        for k in range(1, WINDOW_CLKS + 1):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            irq, err = self._irq(), self._err()
            for b in _bits(irq & ~prev_irq):
                jw.rise.setdefault(b, k)
            if err and not prev_err and jw.err_rise is None:
                jw.err_rise = k
            jw.irq_or |= irq
            prev_irq, prev_err = irq, err
        return jw

    async def _post_jump(self, ops: list[kp.PokeOp]) -> tuple[kp.PokeHandle, JumpWindow]:
        task = cocotb.start_soon(self._watch_jump())
        handle = await self.poke.post(ops)
        jw = await task
        assert jw.tag == handle.tag, (
            f"POKE reached JUMP with tag {jw.tag}, the posted list has tag {handle.tag}"
        )
        return handle, jw

    @staticmethod
    def _rise(jw: JumpWindow, mask: int) -> int | None:
        b = mask.bit_length() - 1
        return jw.rise.get(b)

    # --- witness writes --------------------------------------------------------------
    def _require_clean(self, results: list[kp.PokeResult], what: str) -> None:
        for r in results:
            if r.op.reports and (r.slv or r.dec):
                raise AssertionError(
                    f"{what}: op {r.index} ({r.op.name}) reported slv={r.slv} dec={r.dec}; the "
                    "witness setup did not complete, so no trap check can be graded"
                )

    async def _write_witnesses(self, w: Witness) -> dict[str, int]:
        ops = [kp.wr(IRQ_STATUS_A, IRQ_DEFINED)]
        ops += [kp.wrblk(kpv_word_addr(s, 0), w.words[s]) for s in w.slots]
        ops += [kp.rdloop(kpv_word_addr(s, 0), KPV_WORDS_PER_SLOT) for s in w.slots]
        res = await self.poke.run(ops)
        self._require_clean(res, "KPV witness write")
        nonzero = [res[1 + len(w.slots) + i].data[0] for i in range(len(w.slots))]
        ops = [kp.wr(kpv_ctrl_addr(s), KPV_LOCKS[w.locks[s]]) for s in w.slots]
        ops += [kp.rd(kpv_ctrl_addr(s)) for s in w.slots]
        ops += [
            kp.wr(HMAC_KEY_CTRL_A, 0),
            kp.sync(),
            kp.wr(HMAC_KEY_CTRL_A, HMAC_KEY_VALID),
            kp.sync(),
        ]
        seen: list[int] = []

        async def _on_sync(k: int) -> None:
            seen.append(self._hmac_valid())

        res = await self.poke.run(ops, on_sync=_on_sync)
        self._require_clean(res, "CTRL lock / HMAC KEY_CTRL write")
        ctrl = [res[len(w.slots) + i].value for i in range(len(w.slots))]
        self.logger.info(
            "LOG witnesses: slots=%s locks=%s kpv_nonzero_per_slot=%s ctrl=%s "
            "hmac_key_valid_after_w0=%d after_w1=%d",
            ",".join(str(s) for s in w.slots),
            ",".join(w.locks[s] for s in w.slots),
            ",".join(str(v) for v in nonzero),
            ",".join(f"0x{v:x}" for v in ctrl),
            seen[0],
            seen[1],
        )
        return {
            "kpv_nonzero_before": int(all(v == KPV_WORDS_PER_SLOT for v in nonzero)),
            "control_w0": seen[0],
            "control_w1": seen[1],
        }

    # --- trap legs ----------------------------------------------------------------------
    def _trap_ops(self, kind: str) -> tuple[list[kp.PokeOp], str]:
        p = self.plan
        if kind == "a":
            return [kp.exec_(kp.EX_EBREAK)], "ebreak"
        if kind == "b":
            return [kp.exec_(kp.EX_ZERO_WORD)], "word=0x00000000"
        if kind == "c":
            entry = MISALIGNED[(p.mis_access, p.mis_offset)]
            return (
                [kp.exec_(entry, p.mis_scratch, p.mis_data)],
                f"{p.mis_access}+{p.mis_offset}@0x{p.mis_scratch + p.mis_offset:08x}",
            )
        if kind == "f":
            return (
                [kp.exec_(kp.EX_CRC_FUNCT3[p.f3], *p.crc_operands)],
                f"custom0_funct7=0101100_funct3={p.f3}",
            )
        entry = kp.EX_EBREAK if kind == "d" else kp.EX_ZERO_WORD
        return (
            [
                kp.arm([kp.IRQ_LINE_KMCSR], kp.ACT_EXEC, entry),
                kp.wr(IRQ_ENABLE_A, EN_OTP_CHANGE),
                kp.wr(IRQ_SET_A, SET_OTP_CHANGE),
                kp.nop(),
            ],
            "ebreak_in_isr" if kind == "d" else "zero_word_in_isr",
        )

    async def _trap_leg(self, kind: str) -> None:
        p = self.plan
        reset = p.reset_after[kind]
        w = p.witness()
        self.logger.info(
            "DRAW trap=%s slots=%s locks=%s sram_witness=0x%08x mbox_witness=0x%08x",
            kind,
            ",".join(str(s) for s in w.slots),
            ",".join(w.locks[s] for s in w.slots),
            w.sram,
            w.mbox,
        )
        await self._graded(True)
        ctl = await self._write_witnesses(w)

        # Quiet window before the trap: the control of CHK-TRAP.
        q_high, _, _ = await self._quiet_window()
        wipe_before = self._irq() & IRQ_WIPE_STATE

        trap_ops, detail = self._trap_ops(kind)
        ops = [kp.mark(w.sram), kp.delay(WITNESS_DELAY), *trap_ops]
        handle = await self.poke.post(ops)
        await self.poke.wait(handle, (kp.ST_RUN,))
        # STATE reads RUN before the first op runs; wait until the mark op
        # (op 0) has stored the SRAM witness, so the witness read below sees it.
        await self._wait_ops_done(1, f"trap {kind} SRAM witness mark")
        await self.poke.mbox.post_raw_words([w.mbox])
        depth_before = await self._mbox_depth()
        await ReadOnly()
        head_before = self.rd_known(cocotb.top.km_infifo_head_o)
        err_at_push = self._err()
        wipe_at_push = self._irq() & IRQ_WIPE_STATE
        sram_before = self.poke.word(kp.W_DATA)
        assert err_at_push == 0 and wipe_at_push == 0, (
            f"trap {kind}: PIC bit 30={err_at_push} IRQ_STATUS.WIPE_STATE={int(bool(wipe_at_push))} "
            f"when the mailbox witness was pushed; the trap ran before the witness window, "
            f"raise WITNESS_DELAY ({WITNESS_DELAY})"
        )

        rise = await self._wait_err_rise(f"trap {kind} ({TRAP_TEXT[kind]})")
        high, rom0, rom1 = await self._hold_window()
        sram_after = self.poke.word(kp.W_DATA)
        depth_after = await self._mbox_depth()
        await ReadOnly()
        head_after = self.rd_known(cocotb.top.km_infifo_head_o)
        valid_after = self._hmac_valid()
        irq_after = self._irq()

        assert q_high == 0, (
            f"CHK-TRAP FAIL: kind={kind}: PIC bit 30 was high on {q_high} of {WINDOW_CLKS} "
            "clocks of the quiet window before the trap"
        )
        assert high == WINDOW_CLKS, (
            f"CHK-TRAP FAIL: kind={kind} detail={detail}: PIC bit 30 high on {high} of "
            f"{WINDOW_CLKS} clocks after the rise; the output dropped before a reset"
        )
        assert rom0 == rom1, (
            f"CHK-TRAP FAIL: kind={kind} detail={detail}: km_rom_req_count_o moved "
            f"{rom0} -> {rom1} over the window after the trap; the KM CPU kept fetching"
        )
        self.logger.info(
            "CHK-TRAP PASS: kind=%s detail=%s err_o=1 halted=1 held=1 quiet_high=0 "
            "rise_clks=%d rom_req=%d",
            kind,
            detail,
            rise,
            rom1,
        )

        assert wipe_before == 0, (
            f"CHK-TRAP-STATUS FAIL: kind={kind}: IRQ_STATUS.WIPE_STATE read 1 before the trap "
            "after the witness list cleared it; the control is not met"
        )
        assert irq_after & IRQ_WIPE_STATE, (
            f"CHK-TRAP-STATUS FAIL: kind={kind}: KM-CSR IRQ_STATUS=0x{irq_after:03x} "
            f"({irq_text(irq_after)}) after the trap; WIPE_STATE is clear"
        )
        self.logger.info(
            "CHK-TRAP-STATUS PASS: kind=%s status_wipe=1 status_wipe_before=0 irq_status=0x%03x",
            kind,
            irq_after,
        )

        mbox_word = (1 << 32) | w.mbox  # the separator is on the one pushed word
        assert sram_before == w.sram and depth_before == 1 and head_before == mbox_word, (
            f"CHK-TRAP-SCOPE FAIL: kind={kind}: witnesses before the trap: SRAM word "
            f"0x{sram_before:08x} (expected 0x{w.sram:08x}), mailbox depth {depth_before} "
            f"(expected 1), inbound head 0x{head_before:09x} (expected 0x{mbox_word:09x}); "
            "the control is not met"
        )
        assert sram_after == w.sram, (
            f"CHK-TRAP-SCOPE FAIL: kind={kind}: SRAM result word 0x{sram_after:08x} after the "
            f"trap, expected the witness 0x{w.sram:08x}"
        )
        assert depth_after == 1 and head_after == mbox_word, (
            f"CHK-TRAP-SCOPE FAIL: kind={kind}: SEP_STATUS inbound depth {depth_after} and "
            f"inbound head 0x{head_after:09x} after the trap, expected the 1 pushed word "
            f"0x{mbox_word:09x}"
        )
        self.logger.info(
            "CHK-TRAP-SCOPE PASS: kind=%s sram_same=1 mbox_depth=1 mbox_word=0x%09x",
            kind,
            head_after,
        )

        assert ctl["control_w0"] == 0 and ctl["control_w1"] == 1, (
            f"CHK-TRAP-ENGINE FAIL: kind={kind}: KM-VALID HMAC showed {ctl['control_w0']} after "
            f"KEY_CTRL=0 and {ctl['control_w1']} after KEY_CTRL=1; the tap control is not met"
        )
        assert valid_after == 0, (
            f"CHK-TRAP-ENGINE FAIL: kind={kind}: HMAC key_valid {valid_after} after the trap; "
            "the wipe event of the trap did not clear the accelerator sideload register"
        )
        self.logger.info(
            "CHK-TRAP-ENGINE PASS: kind=%s control_w0=0 control_w1=1 keyvalid_hmac=0", kind
        )

        # The image never reads the mailbox again in this boot, and the FIFO
        # keeps its words across a warm reset (architecture.adoc, "Reset
        # Conditioning"), so flush it before the next boot reads a list.
        await self.poke.mbox.flush()

        await self._reset(reset)
        await ReadOnly()
        err_after_reset = self._err()
        assert err_after_reset == 0, (
            f"CHK-TRAP-CLR FAIL: kind={kind} reset={reset}: PIC bit 30 reads 1 after the reset"
        )
        self.logger.info("CHK-TRAP-CLR PASS: kind=%s reset=%s err_o=0 err_o_before=1", kind, reset)

        res = await self.poke.run([kp.rdloop(KPV_BASE, KPV_WORDS)], timeout_cycles=RDLOOP_TIMEOUT)
        kpv_nonzero, kpv_or = res[0].data
        kpv_slv, kpv_dec = res[0].slv, res[0].dec
        ctrl = await self.poke.run([kp.rdblk(kpv_ctrl_addr(0), KPV_SLOTS)])
        ctrl_nonzero = sum(1 for v in ctrl[0].data if v)
        ctrl_err = sum(1 for f in ctrl[0].flags if f is not None and (f.slv or f.dec))
        self.logger.info(
            "LOG ctrl_nonzero_after_reset=%d ctrl_reads_with_slv_or_dec=%d kind=%s reset=%s",
            ctrl_nonzero,
            ctrl_err,
            kind,
            reset,
        )
        assert self.kpv_kept.get(reset), (
            f"CHK-TRAP-WIPE FAIL: kind={kind}: no plain {reset} reset control showed the KPV "
            "words kept, so a zero read cannot be credited to the trap"
        )
        assert kpv_slv == 0 and kpv_dec == 0, (
            f"CHK-TRAP-WIPE FAIL: kind={kind} reset={reset}: the KPV read loop reported "
            f"slv={kpv_slv} dec={kpv_dec}; a refused read is not a wiped word"
        )
        assert ctl["kpv_nonzero_before"] == 1, (
            f"CHK-TRAP-WIPE FAIL: kind={kind}: a witness slot read back fewer than "
            f"{KPV_WORDS_PER_SLOT} non-zero words before the trap; the control is not met"
        )
        assert kpv_nonzero == 0, (
            f"CHK-TRAP-WIPE FAIL: kind={kind} reset={reset}: {kpv_nonzero} of {KPV_WORDS} KPV "
            f"words read non-zero after the reset (OR 0x{kpv_or:08x}); the trap did not wipe "
            "the KPV"
        )
        self.logger.info(
            "CHK-TRAP-WIPE PASS: kind=%s reset=%s kpv_nonzero_before=1 kpv_nonzero_after_reset=0 "
            "slv=0 dec=0 plain_reset_kept=1",
            kind,
            reset,
        )
        self.err_hits += 1
        await self._graded(False)

    def _kpv_tap_words(self, slot: int) -> tuple[int, ...]:
        """KM-KPV: the 16 stored words of ``slot``. The KPV scrambler stays off
        (reset 0, never enabled here), so stored word i is logical word i."""
        lo = 32 * slot * KPV_WORDS_PER_SLOT
        mask = ((1 << (32 * KPV_WORDS_PER_SLOT)) - 1) << lo
        v = self.rd_known(cocotb.top.km_kpv_words_o, mask=mask) >> lo
        return tuple((v >> (32 * i)) & kp.WORD_MASK for i in range(KPV_WORDS_PER_SLOT))

    async def _plain_reset_kpv_control(self, kind: str) -> None:
        """Control of CHK-TRAP-WIPE: a reset with no trap keeps the KPV words.

        architecture.adoc:466 ("Key and Policy Vault (KPV)"): cold or warm reset
        alone does not overwrite their contents. One slot per lock kind of the
        trap witnesses (lock_write, lock_use, seal) is written, read back,
        locked, and reset with no trap. A zero after a trap and the same kind of
        reset therefore comes from the trap wipe, also for a locked slot.
        """
        kinds = sorted(KPV_LOCKS)
        slots = self.plan.rng.sample(range(KPV_SLOTS), len(kinds))
        words = {s: tuple(_nz(self.plan.rng) for _ in range(KPV_WORDS_PER_SLOT)) for s in slots}
        locks = dict(zip(slots, kinds, strict=True))
        for s in slots:
            self.logger.info(
                "DRAW kpv_reset_control reset=%s slot=%d lock=%s words=%s",
                kind,
                s,
                locks[s],
                ",".join(f"0x{v:08x}" for v in words[s]),
            )
        for s in slots:
            base = kpv_word_addr(s, 0)
            res = await self.poke.run(
                [kp.wrblk(base, words[s]), kp.rdblk(base, KPV_WORDS_PER_SLOT)]
            )
            self._require_clean(res, f"KPV {kind} reset control write")
            assert tuple(res[1].data) == words[s], (
                f"KPV {kind} reset control: slot {s} read back "
                f"{[hex(v) for v in res[1].data]} before the reset; the control write failed"
            )
        res = await self.poke.run(
            [kp.wr(kpv_ctrl_addr(s), KPV_LOCKS[locks[s]]) for s in slots]
            + [kp.rd(kpv_ctrl_addr(s)) for s in slots]
        )
        self._require_clean(res, f"KPV {kind} reset control lock")
        ctrl_before = [res[len(slots) + i].value for i in range(len(slots))]
        for s, c in zip(slots, ctrl_before, strict=True):
            assert c & KPV_LOCKS[locks[s]], (
                f"KPV {kind} reset control: slot {s} CTRL=0x{c:x} after the {locks[s]} write; "
                "the lock did not set, so the control does not cover a locked slot"
            )
        await ReadOnly()
        tap_before = {s: self._kpv_tap_words(s) for s in slots}
        for s in slots:
            assert tap_before[s] == words[s], (
                f"KPV {kind} reset control: KM-KPV slot {s} shows "
                f"{[hex(v) for v in tap_before[s]]} with the port readback "
                f"{[hex(v) for v in words[s]]}; the tap does not show the stored words"
            )
        await self._reset(kind)
        await ReadOnly()
        tap_after = {s: self._kpv_tap_words(s) for s in slots}
        res = await self.poke.run(
            [kp.rd(kpv_ctrl_addr(s)) for s in slots]
            + [kp.rdblk(kpv_word_addr(s, 0), KPV_WORDS_PER_SLOT) for s in slots]
        )
        ctrl_after = [r.value for r in res[: len(slots)]]
        port_after = {s: res[len(slots) + i] for i, s in enumerate(slots)}
        msg = kpv_reset_control_fault(kind, slots, locks, words, tap_after, port_after, ctrl_after)
        assert msg is None, msg
        self.kpv_kept[kind] = True
        self.logger.info(
            "LOG kpv_reset_control control=1 reset=%s slots=%s locks=%s ctrl_before=%s "
            "ctrl_after=%s tap_words_kept=%d port_words_kept=%d slv=0 dec=0",
            kind,
            ",".join(str(s) for s in slots),
            ",".join(locks[s] for s in slots),
            ",".join(f"0x{c:x}" for c in ctrl_before),
            ",".join(f"0x{c:x}" for c in ctrl_after),
            KPV_WORDS_PER_SLOT * len(slots),
            sum(KPV_WORDS_PER_SLOT for s in slots if ctrl_after[slots.index(s)] == 0),
        )

    async def _normal_irq_control(self) -> None:
        a0, a1 = self.plan.crc_operands
        ops = [
            kp.wr(IRQ_STATUS_A, IRQ_DEFINED),
            kp.arm([kp.IRQ_LINE_KMCSR], kp.ACT_CLEAR),
            kp.wr(IRQ_ENABLE_A, EN_OTP_CHANGE),
            kp.wr(IRQ_SET_A, SET_OTP_CHANGE),
            kp.delay(4),
            kp.cnt(kp.IRQ_LINE_KMCSR),
            kp.rd(IRQ_STATUS_A),
            kp.disarm(),
            kp.wr(IRQ_ENABLE_A, 0),
            kp.exec_(kp.EX_CRC32C_WORD, a0, a1),
            kp.exec_(kp.EX_CRC32C_BYTE, a0, a1),
            kp.exec_(kp.EX_CRC8_ROHC, a0, a1),
        ]
        res = await self.poke.run(ops)
        entries = res[5].value
        status = self._field(res[6].value, IRQ_DEFINED, "IRQ_STATUS after the handler", self.logger)
        crc = [r.value for r in res[9:12]]
        high, rom0, rom1 = await self._quiet_window()
        self.logger.info(
            "LOG crc_results word=0x%08x byte=0x%08x rohc=0x%08x (graded by the open CRC test)",
            *crc,
        )
        assert entries == 1, (
            f"CHK-TRAP-CTRL FAIL: {entries} handler entries for one IRQ_SET of OTP_CHANGE with "
            "the clearing handler, expected 1"
        )
        assert status & IRQ_OTP_CHANGE == 0, (
            f"CHK-TRAP-CTRL FAIL: IRQ_STATUS=0x{status:03x} ({irq_text(status)}) after the "
            "handler wrote OTP_CHANGE back; the status did not clear"
        )
        assert high == 0, (
            f"CHK-TRAP-CTRL FAIL: PIC bit 30 high on {high} of {WINDOW_CLKS} clocks after a "
            "normal interrupt and three legal CRC encodings"
        )
        assert rom1 > rom0, (
            f"CHK-TRAP-CTRL FAIL: km_rom_req_count_o did not move ({rom0} -> {rom1}) while the "
            "image waits for a list; the KM CPU stopped"
        )
        self.logger.info(
            "CHK-TRAP-CTRL PASS: control=1 irq_entries=1 legal_crc=3 err_o=0 rom_req_delta=%d",
            rom1 - rom0,
        )

    async def _obs_opcode(self) -> None:
        """A non-zero word of a major opcode outside the base set: logged, not graded."""
        name = self.plan.obs_opcode
        entry = kp.EX_MAJOR_OPCODE[name]
        word = kp.rom_word(kp.exec_entry_addr(entry))
        handle = await self.poke.post([kp.exec_(entry, self.plan.mis_scratch, 0)])
        err = 0
        done = 0
        for _ in range(WINDOW_CLKS):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            err |= self._err()
            st = self.poke.state()
            done |= int(st == (kp.ST_DONE, handle.tag))
        self.logger.info(
            "OBS-TRAP-OPC LOG opcode=%s word=0x%08x err_o=%d list_done=%d (the KM CPU ISA is "
            "not stated; not graded)",
            name,
            word,
            err,
            done,
        )
        await self._reset("warm")

    # --- whitelist cases --------------------------------------------------------------
    async def _copy_snippet(self, base: int, words: list[int], what: str) -> None:
        res = await self.poke.run([kp.wrblk(base, words), kp.rdblk(base, len(words))])
        self._require_clean(res[:1], f"{what} copy")
        back = list(res[1].data)
        assert back == words, (
            f"{what}: snippet read back {[hex(x) for x in back]}, wrote {[hex(x) for x in words]}; "
            "the copy failed, so the fetch case cannot be graded"
        )

    def _sentinel_ops(self, sentinel: int) -> list[kp.PokeOp]:
        return [
            kp.fill(kp.sram_addr(W_P), sentinel, SENTINEL_WORDS),
            kp.reseth(sentinel),
            kp.rd(kp.sram_addr(W_P)),
            kp.rd(kp.sram_addr(W_S_MARK)),
            kp.rd(kp.ADDR_HWORD),
            kp.rd(kp.ADDR_SPIN),
        ]

    @staticmethod
    def _sentinel_ok(res: list[kp.PokeResult], first: int, sentinel: int) -> bool:
        return all(res[first + 2 + i].value == sentinel for i in range(4))

    async def _wait_word(self, index: int, sentinel: int, what: str) -> int:
        """Bounded wait until result word ``index`` no longer holds ``sentinel``."""
        for _ in range(0, MARKER_BOUND, 16):
            if self.poke.word(index, allow_unknown=True) != sentinel:
                return self.poke.word(index)
            await ClockCycles(cocotb.top.clk_i, 16)
        raise AssertionError(
            f"{what}: result word {index} still holds the sentinel after {MARKER_BOUND} clocks"
        )

    async def _plain_reset(self) -> None:
        """A warm reset between two case boots; not a graded stimulus."""
        await self._graded(False)
        await self._reset("warm")
        await self._graded(True)

    async def _refused_case(
        self, case: str, target: int, *, enable: int, region: str, locked: int
    ) -> None:
        """Arm the exec_violation handler, write the enable, jump to ``target``."""
        sentinel = self.plan.sentinel()
        self.logger.info("DRAW %s sentinel=0x%08x", case, sentinel)
        ops = [kp.wr(IRQ_STATUS_A, IRQ_DEFINED), *self._sentinel_ops(sentinel)]
        if enable:
            ops.append(kp.wr(SRAM_EXEC_MODE_A, EXEC_ENABLE))
        ops += [
            kp.wr(IRQ_ENABLE_A, EN_EXEC_VIOL),
            kp.arm([kp.IRQ_LINE_KMCSR], kp.ACT_SPIN),
            kp.jump(target),
        ]
        handle, jw = await self._post_jump(ops)
        res = self.poke.results(handle, partial=True)
        pre_ok = self._sentinel_ok(res, 1, sentinel)
        hword = self.poke.word(kp.W_HWORD)
        s_mark = self.poke.word(W_S_MARK)
        exec_rise = self._rise(jw, IRQ_EXEC_VIOL)
        acc_rise = self._rise(jw, IRQ_ROM_ACC_VIOL)
        self.logger.info(
            "LOG %s handler_word=0x%08x (%s) snippet_marker=0x%08x err_o_rise=%s",
            case,
            hword,
            "sentinel" if hword == sentinel else irq_text(hword),
            s_mark,
            jw.err_rise,
        )
        assert pre_ok, f"CHK-EXEC FAIL: {case}: a result word did not hold the sentinel"
        assert jw.irq_at_jump & IRQ_EXEC_VIOL == 0, (
            f"CHK-EXEC FAIL: {case}: EXEC_VIOLATION already 1 at the jump "
            f"(IRQ_STATUS=0x{jw.irq_at_jump:03x})"
        )
        assert exec_rise is not None, (
            f"CHK-EXEC FAIL: {case} mode={enable} target=0x{target:08x}: EXEC_VIOLATION did not "
            f"rise within {WINDOW_CLKS} clocks of the jump (IRQ_STATUS OR "
            f"0x{jw.irq_or:03x} {irq_text(jw.irq_or)})"
        )
        assert jw.irq_or & IRQ_ROM_ACC_VIOL == 0, (
            f"CHK-EXEC FAIL: {case}: ROM_ACCESS_VIOLATION set in the window (rise at clock "
            f"{acc_rise}) for a fetch outside the whitelist"
        )
        self.exec_hits += 1
        self.logger.info(
            "CHK-EXEC PASS: case=%s mode=%d region=%s locked=%d exec_viol_at_jump=0 exec_viol=1 "
            "rom_acc_viol=0 handler_word_logged=0x%08x rise_clk=%d",
            case,
            enable,
            region,
            locked,
            hword,
            exec_rise,
        )
        await self._plain_reset()

    async def _case_c0(self) -> None:
        p = self.plan
        sentinel = p.sentinel()
        self.logger.info("DRAW C0 sentinel=0x%08x", sentinel)
        ops = [
            kp.wr(IRQ_STATUS_A, IRQ_DEFINED),
            *self._sentinel_ops(sentinel),
            kp.rd(p.rom_addr),
            kp.rd(IRQ_STATUS_A),
            kp.wr(p.rom_addr, p.rom_store),
            kp.rd(IRQ_STATUS_A),
            kp.wr(IRQ_STATUS_A, IRQ_DEFINED),
            kp.disarm(),
            kp.jump(kp.ENTRY_SPIN),
        ]
        handle, jw = await self._post_jump(ops)
        res = self.poke.results(handle, partial=True)
        n = 7
        rom_rd = res[n].value
        irq_rd = self._field(res[n + 1].value, IRQ_DEFINED, "C0 IRQ_STATUS", self.logger)
        st = res[n + 2]
        irq_wr = self._field(res[n + 3].value, IRQ_DEFINED, "C0 IRQ_STATUS", self.logger)
        spin = await self._wait_word(kp.W_SPIN, sentinel, "C0 ROM spin loop")
        self.logger.info(
            "LOG C0 ROM store before the lockout: slv=%d dec=%d rom_write_err=%d control=1",
            st.slv,
            st.dec,
            int(bool(irq_wr & IRQ_ROM_WRITE_ERR)),
        )
        spin_f = self._field(spin, IRQ_DEFINED, "C0 spin IRQ_STATUS", self.logger)
        assert self._sentinel_ok(res, 1, sentinel), "CHK-EXEC-OK FAIL: C0: sentinel not in place"
        assert rom_rd == p.rom_word, (
            f"CHK-EXEC-OK FAIL: C0: ROM read at 0x{p.rom_addr:05x} returned 0x{rom_rd:08x}, the "
            f"image word is 0x{p.rom_word:08x}"
        )
        assert irq_rd & IRQ_ROM_ACC_VIOL == 0, (
            f"CHK-EXEC-OK FAIL: C0: ROM_ACCESS_VIOLATION after a ROM read with enable 0 "
            f"(IRQ_STATUS=0x{irq_rd:03x})"
        )
        assert spin_f & (IRQ_EXEC_VIOL | IRQ_ROM_ACC_VIOL) == 0, (
            f"CHK-EXEC-OK FAIL: C0: the ROM spin loop stored IRQ_STATUS=0x{spin_f:03x} "
            f"({irq_text(spin_f)})"
        )
        assert jw.irq_or & (IRQ_EXEC_VIOL | IRQ_ROM_ACC_VIOL) == 0, (
            f"CHK-EXEC-OK FAIL: C0: KM-CSR showed {irq_text(jw.irq_or)} after the jump into ROM"
        )
        self.logger.info(
            "CHK-EXEC-OK PASS: case=C0 mode=0 region=rom locked=0 pre=sentinel marker=1 viol=0 "
            "rom_rd_ok=1 spin_irq=0x%03x",
            spin_f,
        )
        await self._plain_reset()

    async def _case_c2(self, leg: str) -> None:
        """C2 in its own boot; ``leg`` names the reset that follows it."""
        p = self.plan
        r = p.c2_region
        base = region_base(r)
        sentinel = p.sentinel()
        self.logger.info("DRAW C2 leg=%s sentinel=0x%08x", leg, sentinel)
        words = snippet_p(base, p.rom_addr, p.rom_store)
        await self._copy_snippet(base, words, "C2 snippet P")
        ops = [
            kp.wr(SRAM_LOCK_A, 1 << r),
            kp.wr(IRQ_STATUS_A, IRQ_DEFINED),
            kp.wr(SRAM_EXEC_MODE_A, EXEC_ENABLE),
            kp.rd(p.rom_addr),
            kp.rd(IRQ_STATUS_A),
            kp.wr(SRAM_EXEC_MODE_A, 0),
            kp.rd(SRAM_EXEC_MODE_A),
            kp.wr(p.rom_addr, p.rom_store),
            kp.rd(IRQ_STATUS_A),
            kp.wr(IRQ_STATUS_A, IRQ_DEFINED),
            *self._sentinel_ops(sentinel),
            kp.rd(kp.sram_addr(W_P + 6)),
            kp.disarm(),
            kp.jump(base),
        ]
        handle, jw = await self._post_jump(ops)
        res = self.poke.results(handle, partial=True)
        rom_pre = res[3].value
        irq_pre = self._field(res[4].value, IRQ_DEFINED, "C2 IRQ_STATUS", self.logger)
        en_pre = self._field(res[6].value, EXEC_ENABLE, "C2 SRAM_EXEC_MODE", self.logger)
        st_pre = res[7]
        irq_st = self._field(res[8].value, IRQ_DEFINED, "C2 IRQ_STATUS", self.logger)
        pre_ok = self._sentinel_ok(res, 10, sentinel) and res[16].value == sentinel
        self.logger.info(
            "LOG C2 before the lockout: enable_after_w0=%d store slv=%d dec=%d rom_write_err=%d "
            "control=1",
            en_pre,
            st_pre.slv,
            st_pre.dec,
            int(bool(irq_st & IRQ_ROM_WRITE_ERR)),
        )
        end = await self._wait_word(W_P + 6, sentinel, "C2 snippet P end marker")
        pw = [self.poke.word(W_P + i) for i in range(7)]
        irq_entry = self._field(pw[1], IRQ_DEFINED, "P IRQ_STATUS at entry", self.logger)
        irq_rd = self._field(pw[3], IRQ_DEFINED, "P IRQ_STATUS after the ROM read", self.logger)
        irq_wr = self._field(pw[4], IRQ_DEFINED, "P IRQ_STATUS after the ROM store", self.logger)
        en_post = self._field(pw[5], EXEC_ENABLE, "P SRAM_EXEC_MODE", self.logger)

        # CHK-EXEC-OK: ROM before the lockout, then the locked region r.
        assert pre_ok, "CHK-EXEC-OK FAIL: C2: a P result word did not hold the sentinel"
        assert rom_pre == p.rom_word and irq_pre & IRQ_ROM_ACC_VIOL == 0, (
            f"CHK-EXEC-OK FAIL: C2: ROM read with enable 1 before the lockout returned "
            f"0x{rom_pre:08x} (image 0x{p.rom_word:08x}), IRQ_STATUS=0x{irq_pre:03x}"
        )
        assert jw.irq_at_jump & (IRQ_EXEC_VIOL | IRQ_ROM_ACC_VIOL) == 0, (
            f"CHK-EXEC-OK FAIL: C2: KM-CSR IRQ_STATUS=0x{jw.irq_at_jump:03x} at the jump; a "
            "ROM fetch with enable 1 before the lockout raised a violation"
        )
        assert pw[0] == MARK_P_START and end == MARK_P_END, (
            f"CHK-EXEC-OK FAIL: C2 region={r}: P markers 0x{pw[0]:08x}/0x{end:08x}, expected "
            f"0x{MARK_P_START:08x}/0x{MARK_P_END:08x}; the locked-region fetch did not run"
        )
        assert irq_entry & (IRQ_EXEC_VIOL | IRQ_ROM_ACC_VIOL) == 0, (
            f"CHK-EXEC-OK FAIL: C2 region={r}: IRQ_STATUS at P entry 0x{irq_entry:03x} "
            f"({irq_text(irq_entry)})"
        )
        assert jw.irq_or & IRQ_EXEC_VIOL == 0, (
            f"CHK-EXEC-OK FAIL: C2 region={r}: EXEC_VIOLATION rose in the window (clock "
            f"{self._rise(jw, IRQ_EXEC_VIOL)})"
        )
        self.logger.info(
            "CHK-EXEC-OK PASS: case=C2 mode=1 region=%d locked=1 pre=sentinel marker=1 viol=0 "
            "rom_rd_ok=1 leg=%s",
            r,
            leg,
        )

        # CHK-LOCKOUT: P's accesses after the first locked-SRAM fetch.
        rom_post = pw[2]
        slv = int(bool(irq_wr & IRQ_AXI_SLVERR))
        dec = int(bool(irq_wr & IRQ_AXI_DECERR))
        assert rom_post == 0, (
            f"CHK-LOCKOUT FAIL: C2: ROM read after the lockout returned 0x{rom_post:08x}, "
            "expected 0"
        )
        assert irq_rd & IRQ_ROM_ACC_VIOL, (
            f"CHK-LOCKOUT FAIL: C2: IRQ_STATUS=0x{irq_rd:03x} ({irq_text(irq_rd)}) after a ROM "
            "read after the lockout; ROM_ACCESS_VIOLATION is clear"
        )
        assert irq_wr & IRQ_ROM_WRITE_ERR and not irq_wr & IRQ_ROM_ACC_VIOL, (
            f"CHK-LOCKOUT FAIL: C2: IRQ_STATUS=0x{irq_wr:03x} ({irq_text(irq_wr)}) after a ROM "
            "store after the lockout; expected ROM_WRITE_ERR and no ROM_ACCESS_VIOLATION"
        )
        assert slv == 0 and dec == 0, (
            f"CHK-LOCKOUT FAIL: C2: ROM store after the lockout set AXI_SLVERR={slv} "
            f"AXI_DECERR={dec}"
        )
        assert en_post == EXEC_ENABLE, (
            f"CHK-LOCKOUT FAIL: C2: SRAM_EXEC_MODE.enable reads {en_post} after a write of 0 "
            "after the lockout"
        )
        self.logger.info(
            "CHK-LOCKOUT PASS: rom_rd=0 rom_acc_viol=1 rom_wr_err=1 slv=0 dec=0 enable=1 leg=%s",
            leg,
        )
        self.c2_rom_pre = rom_pre
        self.c2_ok = True

    async def _exec_rst(self, kind: str) -> None:
        p = self.plan
        await self._reset(kind)
        res = await self.poke.run([kp.rd(SRAM_EXEC_MODE_A), kp.rd(p.rom_addr)])
        en = self._field(res[0].value, EXEC_ENABLE, "SRAM_EXEC_MODE after reset", self.logger)
        rom = res[1].value
        assert en == 0, f"CHK-EXEC-RST FAIL: reset={kind}: SRAM_EXEC_MODE.enable reads 1"
        assert rom == p.rom_word, (
            f"CHK-EXEC-RST FAIL: reset={kind}: ROM read at 0x{p.rom_addr:05x} returned "
            f"0x{rom:08x}, the image word is 0x{p.rom_word:08x}"
        )
        assert self.c2_rom_pre == p.rom_word, "CHK-EXEC-RST FAIL: the C2 control was not met"
        self.logger.info(
            "CHK-EXEC-RST PASS: reset=%s enable=0 rom_word_ok=1 control_pre=0x%08x "
            "control_post_lockout=0",
            kind,
            self.c2_rom_pre,
        )

    async def _case_c4(self) -> None:
        r = self.plan.c4_region
        base = region_base(r)
        sentinel = self.plan.sentinel()
        self.logger.info("DRAW C4 sentinel=0x%08x", sentinel)
        await self._copy_snippet(base, snippet_s(MARK_S), "C4 snippet")
        ops = [
            kp.wr(SRAM_LOCK_A, 1 << r),
            kp.wr(IRQ_STATUS_A, IRQ_DEFINED),
            *self._sentinel_ops(sentinel),
            kp.wr(SRAM_EXEC_MODE_A, EXEC_ENABLE),
            kp.disarm(),
            kp.jump(base),
        ]
        f_pre = self._fetch_count()
        _, jw = await self._post_jump(ops)
        high, f_start, f_settle, f_end = await self._fetch_hold_window()
        acc = self._rise(jw, IRQ_ROM_ACC_VIOL)
        self.logger.info(
            "LOG C4 region=%d snippet_marker=0x%08x rom_acc_viol_rise=%s err_rise=%s",
            r,
            self.poke.word(W_S_MARK),
            acc,
            jw.err_rise,
        )
        assert jw.err_at_jump == 0 and jw.err_rise is not None, (
            f"CHK-LOCKOUT-FETCH FAIL: C4 region={r}: PIC bit 30 did not rise within "
            f"{WINDOW_CLKS} clocks of the jump (at jump {jw.err_at_jump}); the ROM code ran "
            "with no trap"
        )
        assert f_start > f_pre, (
            f"CHK-LOCKOUT-FETCH FAIL: C4: km_cpu_fetch_count_o did not move from before the "
            f"jump ({f_pre}) to the window start ({f_start}); the halt check has no control"
        )
        assert high == WINDOW_CLKS and f_settle == f_end, (
            f"CHK-LOCKOUT-FETCH FAIL: C4: after the trap bit 30 high on {high} of {WINDOW_CLKS} "
            f"clocks, km_cpu_fetch_count_o {f_settle} -> {f_end}; the KM CPU kept fetching"
        )
        self.logger.info(
            "CHK-LOCKOUT-FETCH PASS: trap=1 halted=1 region=%d fetch_pre=%d fetch_start=%d "
            "fetch_end=%d",
            r,
            f_pre,
            f_start,
            f_end,
        )
        assert jw.irq_at_jump & IRQ_ROM_ACC_VIOL == 0 and acc is not None, (
            f"CHK-LOCKOUT-ORDER FAIL: C4: ROM_ACCESS_VIOLATION at jump "
            f"{int(bool(jw.irq_at_jump & IRQ_ROM_ACC_VIOL))}, rise {acc}; no rise to order"
        )
        assert acc < jw.err_rise, (
            f"CHK-LOCKOUT-ORDER FAIL: C4: ROM_ACCESS_VIOLATION rose at clock {acc}, PIC bit 30 "
            f"at clock {jw.err_rise}; the trap came first"
        )
        self.logger.info(
            "CHK-LOCKOUT-ORDER PASS: viol_cycle=%d trap_cycle=%d (clocks after the jump)",
            acc,
            jw.err_rise,
        )
        self.acc_hits += 1
        self.err_hits += 1
        await self._plain_reset()

    # --- scenario ------------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.plan = Plan.draw(seed)
        for line in self.plan.draw_lines():
            self.logger.info(line)
        self.exec_hits = 0
        self.acc_hits = 0
        self.err_hits = 0
        self.c2_rom_pre = None
        self.c2_ok = False

        await self.bring_up_no_cpu()
        self.swrst = SepSwReset(self)
        self.poke = SepKmPoke(self)
        await self._wait_sep_reset_release()
        await self.swrst.release("km")
        await self.poke.wait_boot()

        # Normal interrupt and legal CRC encodings: the control of the trap kinds.
        await self._graded(False)
        await self._normal_irq_control()
        self.kpv_kept: dict[str, bool] = {}
        for reset_kind in ("warm", "cold"):
            await self._plain_reset_kpv_control(reset_kind)

        for kind in self.plan.kind_order:
            await self._trap_leg(kind)

        await self._graded(False)
        await self._obs_opcode()

        await self._graded(True)
        await self._case_c0()

        for region_kind, locked, marker in (
            ("locked", 1, MARK_S),
            ("unlocked", 0, MARK_S_UNLOCKED),
        ):
            r = self.plan.c1_regions[region_kind]
            base = region_base(r)
            await self._copy_snippet(base, snippet_s(marker), f"C1 {region_kind} snippet")
            ops = [kp.wr(SRAM_LOCK_A, 1 << r)] if locked else []
            res = await self.poke.run([*ops, kp.rd(SRAM_LOCK_A)])
            lock_rd = res[-1].value
            assert (lock_rd >> r) & 1 == locked, (
                f"CHK-EXEC FAIL: C1 {region_kind} region={r}: SRAM_LOCK reads 0x{lock_rd:08x} "
                f"before the jump, expected lock bit {r} = {locked}"
            )
            self.logger.info(
                "LOG C1 %s region=%d SRAM_LOCK=0x%08x lock_bit=%d", region_kind, r, lock_rd, locked
            )
            await self._refused_case("C1", base, enable=0, region=str(r), locked=locked)

        await self._case_c2("warm")
        await self._exec_rst("warm")
        await self._case_c2("cold")
        await self._exec_rst("cold")

        r = self.plan.c2_region
        base3 = region_base(r + 1)
        await self._copy_snippet(base3, snippet_s(MARK_S), "C3 snippet")
        await self.poke.run([kp.wr(SRAM_LOCK_A, 1 << r)])
        await self._refused_case("C3", base3, enable=1, region=str(r + 1), locked=0)
        assert self.c2_ok, "CHK-REGION FAIL: the C2 boot of region r did not complete"
        self.logger.info("CHK-REGION PASS: r=%d in_r=allowed in_r1=refused", r)

        await self._case_c4()

        p = self.plan
        await self._refused_case(
            "C5", p.c5_window, enable=p.c5_enable, region=f"0x{p.c5_window:05x}", locked=0
        )
        await self._refused_case(
            "C6", VROM_BASE, enable=p.c6_enable, region=f"0x{VROM_BASE:08x}", locked=0
        )
        await self._graded(False)

        # Each "stays 0" check above has a hit of the same signal in this leaf:
        # EXEC_VIOLATION (CHK-EXEC-OK) rose in C1, C3, C5, C6; ROM_ACCESS_VIOLATION
        # (CHK-EXEC) rose in C2 and C4; PIC bit 30 (quiet windows) rose on every trap.
        assert self.exec_hits >= 1 and self.acc_hits >= 1 and self.err_hits >= 1, (
            f"CHK-NONVAC FAIL: exec_viol_hits={self.exec_hits} rom_acc_viol_hits="
            f"{self.acc_hits} err_o_hits={self.err_hits}"
        )
        self.logger.info(
            "CHK-NONVAC PASS: exec_viol_hits=%d rom_acc_viol_hits=%d err_o_hits=%d",
            self.exec_hits,
            self.acc_hits,
            self.err_hits,
        )

        if not (self.swrst.value >> SW_RESET_N_BIT["km"]) & 1:
            await self.swrst.release("km")
        final = await self.swrst.read_back()
        assert (final >> SW_RESET_N_BIT["km"]) & 1, f"SW_RESET_N=0x{final:08x} at the end"
        self.result_pass(TEST_NAME, seed, len(self.required_evidence))
