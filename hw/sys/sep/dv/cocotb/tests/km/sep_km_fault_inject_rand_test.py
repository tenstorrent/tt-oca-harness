# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM fatal faults: the fatal handler, the first-source rule, parity, key CRC, latency.

no_cpu (``lsu_stub_all_live``) / real fuse sense / ``+esrc_noise_force``. One
module, two testlist entries. The entry is the ``rom_main`` build that the
``+km_rom_hex`` plusarg preloads, so the legs follow the image that runs:

* HOST (``+km_rom_hex=rom_main.rom.parhex``, the bench build, wipe predicate
  off): the clean boot, the real-wipe point, the DRBG stall point and the
  key-path point.
* HOST-UNREC (``+km_rom_hex=rom_main_unrec.rom.parhex``, ``KM_BOOT_WIPE=0
  KM_UNREC_WIPE=1``): every leg except the DRBG stall and the key-path points,
  with the hooks HK-IRQSET, HK-CPUIRQ, HK-PAR, HK-KPV and HK-LAT.

The testbench LSU master is the SEP host. It reaches the KM only through
``km_mailbox_sep`` and writes ``SEP_CPU_CTRL.KM_WIPE_CTRL``,
``SEP_CPU_CTRL.EXT_TRNG_SRC_SEL`` and ``SW_RESET_N`` (legal host writes). The
frame model and every golden come from ``hw/ip/key_manager/doc/firmware.adoc``
("Error Recovery", "Interrupt Priority", the fault-code tables, "Key
Management", "Command Message Reference"), ``architecture.adoc`` ("Parameters",
"DRBG Sampler", "ROM and SRAM Error Detection", "Parity Error Protection"),
``km_csr.adoc`` (IRQ_STATUS) and the independent goldens
``env/sep_aes_golden.py`` and ``env/sep_hmac_golden.py``; never from the RTL.
The draws, the source table and the frame model are in
``sep_km_fault_inject_rand_plan.py``.

Witnesses. HMAC: keyed HMAC-SHA256 of a fixed message with a fixed software key
in the KEY registers; ``key`` when the digest equals the golden of the delivered
key, ``nokey`` when it equals the golden of the software key. AES: ECB-256 with
``sideload`` = 1; ``key`` when the output equals the golden of the delivered
key. Any other AES result is logged as ``OBS-AES-NOKEY`` and never grades the
absence of a key.

Probes and taps: ``HOST-MBX``, ``PIC-IRQ`` bit 30, ``KM-COUNT``, ``ENGINE-OUT``,
``KM-ENTROPY``, ``KM-ISO``, and the read-only taps ``KM-VALID``, ``KM-KPV``,
``KM-CSR``, ``KM-BUS``, ``KM-LAT`` and ``KM-OUTFIFO``. Each hook injection is
proven by its readback (``km_irqset_fired_o``, ``km_cpuirq_fired_o``,
``km_par_fired_o`` with ``km_par_rstrb_o``, ``km_kpv_flip_count_o``,
``km_sram_lat_delayed_count_o`` and ``KM-LAT``) before its check is graded.

Checks (HOST-UNREC unless marked):
  CHK-FATAL-WIPE     a KM_WIPE_CTRL write gives exactly one fault frame
                     0xFFFFFFFF and PIC bit 30 rises (HOST: control=1).
  CHK-FLUSH-FIRST    (both) the r unread responses are flushed: one frame after
                     the rise, no stale RESP_CMD.
  CHK-SRAM-SHRED     the SRAM write count rises by 8192 or more by the rise.
  CHK-SHRED-WITNESS  the HMAC witness shows no key after the report.
  CHK-NOSHRED-HOST   (HOST) the HMAC witness keeps the delivered key.
  CHK-TRAP-HELD      (both) bit 30 stays high and a CMD_STAT gets no answer.
  CHK-RESTORE        (both, control) a warm reset restores CMD_STAT and bit 30 = 0.
  CHK-PARITY-CLEAN   (both, control) a clean run and each no-flip twin raise no fault.
  CHK-FATAL-SET      HK-IRQSET sets report the code of the first source.
  CHK-SHRED-FIRST    no bank key_valid and no shared key at the first fault word.
  CHK-STATUS-HELD    (both) the IRQ_STATUS bits of the set stay set after the trap.
  CHK-KPV-TRAP       (control) the KPV words and CTRL read 0 after the trap.
  CHK-PARITY         a parity flip sets the memory's parity bit and reports -2 or -3.
  CHK-PARITY-VAC     a flip that the CPU did not check is redrawn, at most 4 times.
  CHK-KEYCRC         a corrupt key word gives 0xFE key_slot_crc, then failure.
  CHK-CRC-FIRST      the CRC fault precedes the policy refusal.
  CHK-NOFLUSH        the key fault keeps the sequence counters.
  CHK-GATE-AFTER     the fault repeats after CMD_RECOV_ACK; a sibling is gated.
  CHK-RESIDUE        a flip past the key end raises no fault.
  CHK-LAT            a fixed SRAM latency L in [2, 8] changes no response.
  CHK-LAT-VAR        a per-access SRAM latency in [1, 8] changes no response.
  CHK-CPU-TRAP       CPU lines 1 and 2 report -9 and -10 and rank above KMCSR.
  CHK-MAINCTX-FATAL  a bad image CRC sends one 0xFFFFFFF2 frame and holds bit 30.
  CHK-DRBG-STALL     (HOST) a stopped KM entropy stream reports -8.
  CHK-KEYPATH-FATAL  (HOST) a key write to a reset HMAC is fatal with -6 or -7.
  CHK-XFER-STOP      (HOST) the transfer writes no AES bank after the HMAC fault.

Logged only: OBS-AES-NOKEY, OBS-KEYPATH-CODE, the shared-key transfer after each
boot, the frames of the ML-KEM notify, the SRAM write count of the HOST fatal
path, the KPV and KM-VALID samples at the first fault word, the IRQ_STATUS bits
outside the graded set, and VACUOUS parity draws. CHK-MAINCTX-FATAL can fail on
this DUT (contract, "Known limitation"); the point runs after every other fatal
point of the leaf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_PROD
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_hmac_golden import hmac_sha256_words
from env.sep_reg_meta import SEP_CPU_CTRL
from env.sep_spec_tables import agg_from_pic
from km import sep_km_fault_inject_rand_plan as pl
from sep_base_test import sep_base_test
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_ENCAPS,
    KEM_CMD_KEYGEN,
    KEM_CTRL_ZEROIZE,
    KEM_EK_WORDS,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    KV_READ_EN,
    KV_WRITE_EN,
    MLKEM_CTRL,
    MLKEM_ENCAPS_KEY,
    MLKEM_KV_MSG_RD_CTRL,
    MLKEM_KV_SK_WR_CTRL,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_STATUS,
    SepAbrMlkem,
)
from seq_lib.sep_aes_seq import AES_STATUS, AES_STATUS_OUTPUT_VALID, SepAes
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_hmac_seq import SepHmac
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_ABR_SK_TRANSFER,
    KM_CMD_ENGINE_SHRED,
    KM_CMD_KEY_GENERATE,
    KM_CMD_KEY_LOAD,
    KM_CMD_KEY_REVOKE,
    KM_CMD_KEY_TRANSFER,
    KM_CMD_RECOV_ACK,
    KM_CMD_SRAM_LOAD_EXEC,
    KM_CMD_STAT,
    KM_MBOX_DEPTH,
    KM_RC_CMD_NOSEQ,
    KM_RC_FAILURE,
    KM_RC_SUCCESS,
    KM_RESP_ABR_SHARED_KEY_READY,
    KM_RESP_CMD,
    KM_RESP_KM_READY,
    KM_RESP_RECOVERABLE_FAULT,
    KM_RESP_UNRECOVERABLE_FAULT,
    KM_STATUS_INBOUND_DEPTH_LSB,
    KM_STATUS_INBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_DEPTH_LSB,
    KM_STATUS_OUTBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_EMPTY,
    KM_STATUS_OUTBOUND_SEPARATOR,
    RESP_OKAY,
    SepKmMailbox,
    crc8_rohc,
    crc32c,
)
from seq_lib.sep_kmac_seq import SepKmac
from seq_lib.sep_otbn_seq import SepOtbn
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

TEST = "sep_km_fault_inject_rand_test"
ENTRY_UNREC = TEST + "_unrec"
KM_UNREC_BIT = agg_from_pic("KM unrecoverable error")  # PIC vector bit 30

# The +km_rom_hex image of each entry (the HOST-UNREC build is the
# [c_build] profile km_rom_main_unrec, SEP_TB_ARCH.adoc).
IMAGE_HOST = "rom_main.rom.parhex"
IMAGE_UNREC = "rom_main_unrec.rom.parhex"

EVIDENCE_HOST = (
    "CHK-FATAL-WIPE",
    "CHK-FLUSH-FIRST",
    "CHK-NOSHRED-HOST",
    "CHK-TRAP-HELD",
    "CHK-STATUS-HELD",
    "CHK-RESTORE",
    "CHK-PARITY-CLEAN",
    "CHK-DRBG-STALL",
    "CHK-KEYPATH-FATAL",
    "CHK-XFER-STOP",
)
EVIDENCE_UNREC = (
    "CHK-FATAL-WIPE",
    "CHK-FLUSH-FIRST",
    "CHK-SRAM-SHRED",
    "CHK-SHRED-WITNESS",
    "CHK-TRAP-HELD",
    "CHK-RESTORE",
    "CHK-PARITY-CLEAN",
    "CHK-FATAL-SET",
    "CHK-SHRED-FIRST",
    "CHK-STATUS-HELD",
    "CHK-KPV-TRAP",
    "CHK-PARITY",
    "CHK-PARITY-VAC",
    "CHK-KEYCRC",
    "CHK-CRC-FIRST",
    "CHK-NOFLUSH",
    "CHK-GATE-AFTER",
    "CHK-RESIDUE",
    "CHK-LAT",
    "CHK-LAT-VAR",
    "CHK-CPU-TRAP",
    "CHK-MAINCTX-FATAL",
)

# Bounded waits. Each expiry fails the leaf with a named message, or fails the
# check of the step with timeout=1.
SEP_RESET_BOUND = 20_000  # clocks for dbg_sep_reset_n_o after the fuse sense
POLL = 20  # clocks between two mailbox status polls
FRAME_POLLS = 20_000  # polls for one response frame
READY_POLLS = 20_000  # polls for RESP_KM_READY after a release
INBOUND_POLLS = 20_000  # polls for inbound FIFO space while posting
RISE_BOUND = 4_000_000  # clocks from an injection to the PIC bit 30 rise
KEM_POLLS = 20_000
KEM_GAP = 200
QUIET_FACTOR = 10  # w_clk = 10 x ctrl_stat_clk
TRAP_SAMPLES = 20
SETTLE_STABLE = 4  # equal outbound depth reads before the quiet window
SETTLE_POLLS = 400
MAIN_HOLD_FACTOR = 8  # main-context window = 8 x the clocks from the trailer to the rise
PAR_REDRAWS = 4
PAR_STATS = 64  # CMD_STAT frames that drive reads after an HK-PAR arm
STAT_POLLS = 2_000  # polls for one CMD_STAT answer during the parity traffic
CLEAN_STATS = 128  # CMD_STAT frames of a clean run
TVALID_WINDOW = 4_000  # clocks of the KM-ENTROPY control window
ISO_BOUND = 20_000  # clocks for hmac_km_isolated_probe_o to read 1
W_FACTOR = 8  # AES window = 8 x the duration of the first AES output of the leaf
AES_FIRST_BOUND = 80_000
AES_POLL_GAP = 20
DRBG_REQ_WORDS = 128  # CMD_KEY_GENERATE size of the DRBG stall point
KPV_INDEX_MAX = pl.SLOT_WORDS * 64

# Fixed witness stimulus. The second message differs from the first, so a
# stale digest cannot match the golden of the run after the report.
AES_PT = (0x03020100, 0x07060504, 0x0B0A0908, 0x0F0E0D0C)
HMAC_MSG = (0x61626364, 0x65666768, 0x696A6B6C, 0x6D6E6F70, 0x71727374, 0x75767778)
HMAC_MSG2 = (0x4D534732, 0x0A0B0C0D, 0x1E2F3A4B, 0x5C6D7E8F, 0x90A1B2C3, 0xD4E5F607)
WITNESS_WORDS = 8

# Directed ML-KEM seed of the register KEYGEN (test vectors, no zero word).
_KEM_D = (
    0x0BADC0DE,
    0x13572468,
    0xA5A5A5A5,
    0xFEEDFACE,
    0x2468ACE0,
    0x5A5A0F0F,
    0x97531ECA,
    0x600DF00D,
)
_KEM_Z = (
    0x1234ABCD,
    0x0F0F0F0F,
    0xC0FFEE00,
    0x5EED5EED,
    0x7E57CA5E,
    0x31415926,
    0x4B1D2C3E,
    0x8BADF00D,
)

AES_MASK = 1 << pl.AES
HMAC_AES_MASK = (1 << pl.HMAC) | (1 << pl.AES)
MSG_MASK = 1 << pl.MSG
PORT_AES, PORT_HMAC = 1, 2  # KM-BUS port index (bench isolate stage 8 + i)
N_PORTS = 5
KEYGEN_DEST = AES_MASK  # DEST_VALID 0x04 of the DRBG stall request


def _signed8(v: int) -> int:
    v &= 0xFF
    return v - 256 if v >= 128 else v


def _hx(v: int | None) -> str:
    return "none" if v is None else f"0x{v & 0xFFFF_FFFF:08x}"


def _h2(v: int) -> str:
    return f"0x{v:02x}"


def _bitstr(sig) -> str:
    """The per-bit string of a signal, MSB first, in cocotb 1.x and 2.x."""
    v = sig.value
    if isinstance(v, int):
        return format(int(v), f"0{len(sig)}b")
    s = getattr(v, "binstr", None)
    if s is None:
        s = str(v)
    return s.strip()


def _word_counts(bits: str, n: int, width: int) -> tuple[int, int]:
    """(non-zero, unknown) counts of the n words of ``width`` bits of ``bits``."""
    nz = unk = 0
    top = len(bits)
    for i in range(n):
        chunk = bits[top - width * (i + 1) : top - width * i]
        if any(c not in "01" for c in chunk):
            unk += 1
        elif "1" in chunk:
            nz += 1
    return nz, unk


class _Frame:
    """One response frame read from SEP_READ_DATA.

    ``bad`` is set when the words stop before the separator, the length does
    not match the header or a CRC does not match (firmware.adoc, frame format).
    """

    def __init__(self, words: list[int], bad: bool = False) -> None:
        self.words = words
        hdr = words[0]
        self.seq = hdr & 0xFF
        self.resp_id = (hdr >> 8) & 0xFF
        self.payload_len = (hdr >> 16) & 0xFF
        self.payload = words[1 : 1 + self.payload_len]
        self.bad = bad

    @property
    def fault_word(self) -> int | None:
        """The payload word of a one-word fault frame."""
        if self.bad or self.payload_len != 1 or len(self.payload) != 1:
            return None
        return self.payload[0]

    def is_fault(self, resp_id: int, code: int) -> bool:
        return self.resp_id == resp_id and self.fault_word == pl.fault_word(code)

    def resp_cmd(self, cmd_id: int, cmd_seq: int) -> tuple[int | None, int | None]:
        """(code, argument or None) of a RESP_CMD echo of this command; (None, None) otherwise."""
        p = self.payload
        if (
            self.bad
            or self.resp_id != KM_RESP_CMD
            or len(p) < 3
            or (p[0] & 0xFF) != (cmd_seq & 0xFF)
            or (p[1] & 0xFF) != (cmd_id & 0xFF)
        ):
            return None, None
        return _signed8(p[2]), (p[3] if len(p) >= 4 else None)

    def text(self) -> str:
        return "[" + ",".join(_hx(w) for w in self.words) + ("]!" if self.bad else "]")


def _ids(frames: list[_Frame]) -> str:
    return ",".join(_h2(f.resp_id) for f in frames) or "-"


class _FatalWatch:
    """Per-clock record of one fatal point.

    PIC bit 30: the rise clock, the SRAM write count at the rise, and the low
    and high clocks after it. KM-OUTFIFO: the first clock in which the outbound
    FIFO holds a word after it read empty, with the KM-VALID and KM-KPV sample
    of that clock. ``km_cpuirq_pending_o``: the OR of every sample.
    """

    def __init__(self, test: sep_base_test) -> None:
        top = cocotb.top
        self.test = test
        self.clk = top.clk_i
        self.cyc = 0
        self.rise: int | None = None
        self.wr_at_rise: int | None = None
        self.low_after_rise = 0
        self.high_after_rise = 0
        self.seen_zero = False
        self.first: dict | None = None
        self.pend_seen = 0
        self._on = False

    def start(self) -> None:
        self._on = True
        cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._on = False

    async def _run(self) -> None:
        t = self.test
        top = cocotb.top
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            self.cyc += 1
            b = t._b30()
            depth = t.rd_known(top.km_outfifo_depth_o)
            if depth == 0:
                self.seen_zero = True
            elif self.seen_zero and self.first is None:
                words_nz, words_unk = _word_counts(_bitstr(top.km_kpv_words_o), 1024, 32)
                ctrl_nz, ctrl_unk = _word_counts(_bitstr(top.km_kpv_ctrl_o), 64, 4)
                self.first = {
                    "cyc": self.cyc,
                    "keyvalid": t.rd(top.km_engine_key_valid_o, allow_unknown=True),
                    "kv_unknown": int(_bitstr(top.km_engine_key_valid_o).strip("01") != ""),
                    "shared": t.rd(top.km_abr_sk_valid_o, allow_unknown=True),
                    "kpv_words_nonzero": words_nz,
                    "kpv_words_unknown": words_unk,
                    "kpv_ctrl_nonzero": ctrl_nz + ctrl_unk,
                }
            self.pend_seen |= t.rd(top.km_cpuirq_pending_o, allow_unknown=True)
            if self.rise is None:
                if b:
                    self.rise = self.cyc
                    self.wr_at_rise = t.rd_known(top.km_sram_write_count_o)
            elif b:
                self.high_after_rise += 1
            else:
                self.low_after_rise += 1


class _KeyBus:
    """KM-BUS: per key-path port, the AW requests (valid rises) and handshakes."""

    def __init__(self, test: sep_base_test) -> None:
        top = cocotb.top
        self.test = test
        self.clk = top.clk_i
        self.valid = top.km_key_aw_valid_o
        self.ready = top.km_key_aw_ready_o
        self.req = [0] * N_PORTS
        self.hs = [0] * N_PORTS
        self.unknown = 0
        self._on = False

    def start(self) -> None:
        self.req = [0] * N_PORTS
        self.hs = [0] * N_PORTS
        self.unknown = 0
        self._on = True
        cocotb.start_soon(self._run())

    async def stop(self) -> None:
        self._on = False
        await ClockCycles(self.clk, 2)

    @property
    def writes(self) -> int:
        return sum(self.hs)

    async def _run(self) -> None:
        prev = 0
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            vbits = _bitstr(self.valid)
            rbits = _bitstr(self.ready)
            if any(c not in "01" for c in vbits) or any(
                c not in "01" for c, v in zip(rbits, vbits, strict=True) if v != "0"
            ):
                # An unknown request cannot count as "no write": it fails closed.
                self.unknown += 1
                continue
            v = int(vbits, 2)
            r = int("".join("1" if c == "1" else "0" for c in rbits), 2)
            for p in range(N_PORTS):
                if (v >> p) & 1 and not (prev >> p) & 1:
                    self.req[p] += 1
                if (v >> p) & 1 and (r >> p) & 1:
                    self.hs[p] += 1
            prev = v


class _LatWatch:
    """KM-LAT against the latency that HK-LAT sets for each SRAM read.

    The KM issues no new SRAM read while one is outstanding, and HK-LAT samples
    ``km_sram_lat_i`` when the macro answers, one clock after the accepted
    request. In the per-access mode the next value is written a quarter clock
    after the completion of a read, so it is in place before the next request
    can be sampled; the expected latency of each read is the value in place
    since the previous completion (1 for a value of 1).
    """

    def __init__(self, test: sep_base_test, mode: str, first: int, stream=None) -> None:
        self.test = test
        self.mode = mode
        self.cur = first
        self.stream = stream
        self.reads = 0
        self.skipped = 0
        self.mismatch = 0
        self.examples: list[str] = []
        self.observed: set[int] = set()
        self.expected: set[int] = set()
        self._on = False
        self.quarter_ps = test.period_ps // 4

    def start(self) -> None:
        self._on = True
        cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._on = False

    async def _run(self) -> None:
        top = cocotb.top
        t = self.test
        prev: int | None = None
        while True:
            await RisingEdge(top.clk_i)
            await ReadOnly()
            if not self._on:
                return
            done = t.rd_known(top.km_sram_rd_done_count_o)
            if prev is None:
                prev = done
                continue
            if done == prev:
                continue
            step = (done - prev) & 0xFFFF_FFFF
            prev = done
            lat = t.rd_known(top.km_sram_rd_lat_o)
            exp = max(1, self.cur)
            self.reads += 1
            self.skipped += step - 1
            self.observed.add(lat)
            self.expected.add(exp)
            if lat != exp:
                self.mismatch += 1
                if len(self.examples) < 8:
                    self.examples.append(f"read{self.reads}:{lat}!={exp}")
            if self.mode == "random":
                nxt = self.stream.next()
                await Timer(self.quarter_ps, "ps")
                top.km_sram_lat_i.value = nxt
                self.cur = nxt


@dataclass
class _Pre:
    """The pre-state of a fatal point with keys (steps 3 and 4)."""

    keyvalid: int
    shared: int
    kpv_words_nonzero: int
    stat_clk: int
    stat_ok: bool
    hmac: str | None = None
    aes: str | None = None
    w_clk: int = 0
    quiet_high: int = 0
    wr_start: int = 0
    wr_end: int = 0
    depth: int = 0


@dataclass
class _Trap:
    """What the host sees after a fatal point."""

    rose: bool
    frames: list[_Frame] = field(default_factory=list)
    samples_high: int = 0
    stat_answered: int = 0
    window_frames: list[_Frame] = field(default_factory=list)


@pyuvm.test()
class sep_km_fault_inject_rand_test(sep_base_test):
    """KM fatal handler, first-source rule, parity, key CRC, latency and stall faults."""

    required_evidence: tuple[str, ...] = ()

    # ================================================================ scenario
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.unrec = self._entry() == "unrec"
        entry = ENTRY_UNREC if self.unrec else TEST
        self.required_evidence = EVIDENCE_UNREC if self.unrec else EVIDENCE_HOST
        self.chk = SepChkLog(self, entry, seed)
        self.plan = pl.draw_plan(seed)
        pl.check_plan(self.plan)
        for line in pl.draw_lines(self.plan):
            self.logger.info(line)
        self.logger.info("ROM-BUILD km_boot_wipe=0 km_unrec_wipe=%d", int(self.unrec))
        self.logger.info(
            "LOG entry=%s legs selected by +km_rom_hex (%s)",
            "HOST-UNREC" if self.unrec else "HOST",
            IMAGE_UNREC if self.unrec else IMAGE_HOST,
        )

        self.period_ps = self._whole_ps(self.cfg.sys_clk_period_ns, "clk_i period")
        self.aes_first_clk: int | None = None
        self.aes_w_clk: int | None = None
        self.ek: list[int] | None = None
        self.sk_pending = False
        self.fresh = False
        self.lat_on = False
        self.resp_next = 0
        self.w_ref = 0

        await self._bring_up()
        await self._clean_run(self.plan.max_parity_n, None, "clean_boot")  # step 2
        await self._real_wipe_point()  # steps 3 to 9
        if self.unrec:
            for name in self.plan.singles:  # step 10
                await self._irqset_point((name,))
            for names in self.plan.multis:  # step 11
                await self._irqset_point(names)
            for mem, lane, n in self.plan.parity:  # step 12
                await self._parity_point(mem, lane, n)
            await self._keycrc_leg()  # steps 13 to 18
            await self._cpu_point(2, None)  # step 19
            await self._cpu_point(1, None)
            await self._cpu_point(2, self.plan.cpu_src)
            await self._lat_leg()  # step 23
            await self._mainctx_point()  # step 20, after every other fatal point
        else:
            await self._drbg_stall_point()  # step 21
            await self._keypath_point()  # step 22
        await self._fresh("end of leaf")  # step 24: km_sw_rst_n ends high
        await self._graded(False)
        await self.stop_fifo_drain()
        self.chk.finish()

    def _entry(self) -> str:
        arg = cocotb.plusargs.get("km_rom_hex")
        name = Path(arg).name if isinstance(arg, str) else None
        if name == IMAGE_UNREC:
            return "unrec"
        if name == IMAGE_HOST:
            return "host"
        raise AssertionError(
            f"{TEST}: +km_rom_hex={arg!r}; the entry needs {IMAGE_HOST} (HOST) or "
            f"{IMAGE_UNREC} (HOST-UNREC)"
        )

    async def _bring_up(self) -> None:
        """Step 1: PROD image, real sense, entropy, engines idle, KM release."""
        image = self.select_efuse_image(lc_raw=LC_PROD)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))
        if getattr(self, "swrst", None) is None:
            self.swrst = SepSwReset(self)
        self.suppress_host_axi_transaction_info()
        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)
        self.hmac = SepHmac(self)
        self.kem = SepAbrMlkem(self)
        self.bus = _KeyBus(self)
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain(log_batches=False)
        # A key write to an engine held in its SW_RESET_N reset ends in SLVERR,
        # which the KM reports as fatal, so every engine is out of reset first.
        await self.swrst.release("aes", "hmac", "kmac", "otbn")
        await self.aes.wait_idle("post-release")
        await self.hmac.wait_idle("post-release")
        await SepKmac(self).wait_idle("post-release")
        await SepOtbn(self).wait_idle("post-release")
        held = [
            n
            for n in SW_RESET_N_BIT
            if n != "km" and not (self.swrst.value >> SW_RESET_N_BIT[n]) & 1
        ]
        assert not held, f"precondition: engines held in SW_RESET_N reset: {held}"
        await self._wait_sep_reset_release()
        await self.swrst.release("km")
        await self._wait_ready("cold reset")
        await self._graded(True)

    # ================================================================ probes
    def _cyc(self) -> int:
        return int(get_sim_time("ps")) // self.period_ps

    def _b30(self) -> int:
        vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << KM_UNREC_BIT)
        return (vec >> KM_UNREC_BIT) & 1

    def _kv(self) -> int:
        return self.rd_known(cocotb.top.km_engine_key_valid_o)

    def _sk(self) -> int:
        return self.rd_known(cocotb.top.km_abr_sk_valid_o)

    def _wr_count(self) -> int:
        return self.rd_known(cocotb.top.km_sram_write_count_o)

    def _reads(self) -> tuple[int, int]:
        """(ROM reads, SRAM reads) since the bench reset (KM-COUNT)."""
        top = cocotb.top
        rom = self.rd_known(top.km_rom_req_count_o)
        sram = self.rd_known(top.km_sram_req_count_o) - self.rd_known(top.km_sram_write_count_o)
        return rom, sram

    def _csr_status(self) -> int:
        return self.rd(cocotb.top.km_csr_irq_status_o, allow_unknown=True)

    def _kpv(self) -> tuple[int, int, int]:
        """KM-KPV: (non-zero words, unknown words, non-zero or unknown CTRL)."""
        top = cocotb.top
        nz, unk = _word_counts(_bitstr(top.km_kpv_words_o), 1024, 32)
        cnz, cunk = _word_counts(_bitstr(top.km_kpv_ctrl_o), 64, 4)
        return nz, unk, cnz + cunk

    def _ctrl_slots(self) -> list[int]:
        v = self.rd_known(cocotb.top.km_kpv_ctrl_o)
        return [(v >> (4 * s)) & 0xF for s in range(64)]

    async def _graded(self, on: bool) -> None:
        # The gate is a signal write, which cocotb refuses in the ReadOnly phase.
        await RisingEdge(cocotb.top.clk_i)
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    # ================================================================ transport
    async def _status(self) -> int:
        return await self.km.read_status()

    async def _out_depth(self) -> int:
        return (
            await self._status() >> KM_STATUS_OUTBOUND_DEPTH_LSB
        ) & KM_STATUS_OUTBOUND_DEPTH_MASK

    async def _post(self, words: list[int]) -> None:
        """Write ``words`` to SEP_WRITE_DATA, the separator on the last word.

        The writer waits for space in the 16-word inbound FIFO, so a frame or an
        image longer than the FIFO never overflows it.
        """
        i = 0
        while i < len(words):
            for _ in range(INBOUND_POLLS):
                depth = (
                    await self._status() >> KM_STATUS_INBOUND_DEPTH_LSB
                ) & KM_STATUS_INBOUND_DEPTH_MASK
                if depth < KM_MBOX_DEPTH:
                    break
                await ClockCycles(cocotb.top.clk_i, POLL)
            else:
                raise AssertionError(
                    f"the inbound FIFO stayed full for {INBOUND_POLLS} polls at word {i} "
                    f"of {len(words)}"
                )
            for _ in range(KM_MBOX_DEPTH - depth):
                if i == len(words) - 1:
                    await self.km.post_raw_words([words[i]])
                else:
                    resp = await self.km.write_data_raw(words[i])
                    if resp != RESP_OKAY:
                        raise AssertionError(f"SEP_WRITE_DATA write {i} answered resp={resp}")
                i += 1
                if i == len(words):
                    break

    async def _send(self, cmd_id: int, payload: list[int], *, seq: int | None = None) -> int:
        """Post one well-formed command frame. A given ``seq`` leaves the host counter."""
        use = self.km.seq_num if seq is None else seq & 0xFF
        await self._post(self.km.build_frame(cmd_id, use, payload))
        if seq is None:
            self.km.seq_num = (self.km.seq_num + 1) & 0xFF
        return use

    async def _read_word(self, polls: int) -> int | None:
        for _ in range(polls):
            if not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                resp, data = await self.km.read_data_raw()
                if resp != RESP_OKAY:
                    raise AssertionError(f"SEP_READ_DATA read answered resp={resp}")
                return data
            await ClockCycles(cocotb.top.clk_i, POLL)
        return None

    async def _read_frame(self, polls: int = FRAME_POLLS) -> _Frame | None:
        """One response frame, or None if no word arrives within ``polls`` polls."""
        first = await self._read_word(polls)
        if first is None:
            return None
        words = [first]
        while not (await self._status() & (1 << KM_STATUS_OUTBOUND_SEPARATOR)):
            if len(words) >= 32:
                return _Frame(words, bad=True)
            w = await self._read_word(FRAME_POLLS)
            if w is None:
                return _Frame(words, bad=True)
            words.append(w)
        fr = _Frame(words)
        exp_crc = crc8_rohc(bytes([fr.seq, fr.resp_id, fr.payload_len]))
        exp_len = 1 + fr.payload_len + (1 if fr.payload_len else 0)
        bad = ((first >> 24) & 0xFF) != exp_crc or len(words) != exp_len
        if not bad and fr.payload_len:
            body = b"".join(w.to_bytes(4, "little") for w in fr.payload)
            bad = words[-1] != crc32c(body)
        fr.bad = bad
        return fr

    async def _drain(self) -> list[_Frame]:
        """Every frame in the outbound FIFO now."""
        out: list[_Frame] = []
        while not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
            fr = await self._read_frame(1)
            if fr is None:
                break
            out.append(fr)
            if len(out) > 32:
                raise AssertionError("more than 32 frames in the outbound FIFO")
        return out

    async def _cmd_frames(
        self, cmd_id: int, payload: list[int], *, seq: int | None = None, track: bool = True
    ) -> tuple[int, list[_Frame]]:
        """Send one command; return its sequence and the frames up to its RESP_CMD.

        RESP_ABR_SHARED_KEY_READY frames are logged and skipped. With ``track``
        the response sequence numbers must follow the frames read since the
        boot (firmware.adoc, "Command Message Reference").
        """
        sent = await self._send(cmd_id, payload, seq=seq)
        frames: list[_Frame] = []
        while True:
            fr = await self._read_frame(FRAME_POLLS)
            if fr is None:
                raise AssertionError(
                    f"no response frame to command 0x{cmd_id:02x} seq {sent} within "
                    f"{FRAME_POLLS} polls (frames so far {_ids(frames)})"
                )
            if fr.bad:
                raise AssertionError(f"malformed response frame {fr.text()}")
            if track and fr.seq != self.resp_next:
                raise AssertionError(
                    f"response sequence {fr.seq}, expected {self.resp_next} ({fr.text()})"
                )
            self.resp_next = (fr.seq + 1) & 0xFF
            if fr.resp_id == KM_RESP_ABR_SHARED_KEY_READY:
                self.chk.obs("SK-NOTIFY", cmd=_h2(cmd_id), frame=fr.text())
                continue
            frames.append(fr)
            code, _arg = fr.resp_cmd(cmd_id, sent)
            if code is not None:
                return sent, frames
            if len(frames) >= 4:
                raise AssertionError(
                    f"command 0x{cmd_id:02x}: no RESP_CMD echo in {[f.text() for f in frames]}"
                )

    async def _cmd(self, cmd_id: int, payload: list[int]) -> tuple[int, int | None, _Frame]:
        """One command whose only frame is its RESP_CMD; (code, argument, frame)."""
        sent, frames = await self._cmd_frames(cmd_id, payload)
        if len(frames) != 1:
            raise AssertionError(
                f"command 0x{cmd_id:02x}: frames {[f.text() for f in frames]} before its RESP_CMD"
            )
        code, arg = frames[0].resp_cmd(cmd_id, sent)
        return code, arg, frames[0]

    async def _load(self, words, dest: int) -> int:
        code, arg, _ = await self._cmd(KM_CMD_KEY_LOAD, [len(words) - 1, dest, *words])
        if code != KM_RC_SUCCESS or arg is None or not arg & 0xFF:
            raise AssertionError(
                f"precondition: CMD_KEY_LOAD of {len(words)} words dest={_h2(dest)} "
                f"code={code} arg={_hx(arg)}"
            )
        return arg & 0xFF

    async def _transfer_pre(self, handle: int, dest: int) -> None:
        code, arg, _ = await self._cmd(KM_CMD_KEY_TRANSFER, [handle, dest])
        if code != KM_RC_SUCCESS or arg is None or (arg & 0xFFFF) != (handle | (dest << 8)):
            raise AssertionError(
                f"precondition: CMD_KEY_TRANSFER handle={_h2(handle)} dest={_h2(dest)} "
                f"code={code} arg={_hx(arg)}"
            )

    # ================================================================ resets
    async def _wait_sep_reset_release(self) -> None:
        for _ in range(SEP_RESET_BOUND):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd(cocotb.top.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(
            f"dbg_sep_reset_n_o did not read 1 within {SEP_RESET_BOUND} clocks; the KM "
            "release would be lost"
        )

    async def _wait_ready(self, after: str) -> _Frame:
        fr = await self._read_frame(READY_POLLS)
        if fr is None:
            raise AssertionError(
                f"KM never announced RESP_KM_READY after {after} within {READY_POLLS} polls. "
                f"{self.km._km_boot_evidence()}"
            )
        if fr.bad or fr.resp_id != KM_RESP_KM_READY or fr.seq != 0:
            raise AssertionError(f"after {after}: expected RESP_KM_READY seq 0, got {fr.text()}")
        self.resp_next = 1
        self.fresh = True
        return fr

    async def _boot(self, after: str, *, restore: bool = True, parked=None) -> _Frame:
        """Warm reset: SW_RESET_N bit 0 low, then high, the other bits at 1."""
        await self._graded(False)
        others = [n for n in SW_RESET_N_BIT if n != "km"]
        held = [n for n in others if not (self.swrst.value >> SW_RESET_N_BIT[n]) & 1]
        assert not held, f"precondition: SW_RESET_N holds {held} at a KM warm reset"
        await self.swrst.park("km")
        if self.lat_on:
            await RisingEdge(cocotb.top.clk_i)
            cocotb.top.km_sram_lat_en_i.value = 0
            cocotb.top.km_sram_lat_i.value = 0
            self.lat_on = False
        if parked is not None:
            await parked()
        await self.swrst.release("km")
        self.km.reset_host_seq()
        ready = await self._wait_ready(after)
        if self.sk_pending:
            await self._sk_flush(after)
        await self._graded(True)
        if restore:
            await self._restore(after)
        return ready

    async def _fresh(self, why: str) -> None:
        """A warm boot unless the KM booted since the last point."""
        if not self.fresh:
            await self._boot(why)
        self.fresh = False

    async def _sk_flush(self, after: str) -> None:
        """The pending ABR shared key: CMD_ABR_SK_TRANSFER with DEST_VALID bit 7, logged."""
        code, arg, _ = await self._cmd(KM_CMD_ABR_SK_TRANSFER, [MSG_MASK])
        self.chk.obs("SK-AFTER-BOOT", after=after, code=code, arg=_hx(arg))
        self.sk_pending = False

    async def _restore(self, after: str) -> None:
        """CHK-RESTORE (control): CMD_STAT succeeds with status 0 and bit 30 reads 0."""
        code, arg, _ = await self._cmd(KM_CMD_STAT, [])
        b = self._b30()
        ok = code == KM_RC_SUCCESS and arg is not None and (arg & 1) == 0 and b == 0
        self.chk.ok("RESTORE", ok, control=1, after=after, stat=_hx(arg), err_o=b)

    # ================================================================ witnesses
    async def _aes_reset(self) -> None:
        await self.swrst.park("aes")
        await self.swrst.release("aes")
        await self.aes.wait_idle("post-witness-reset")

    async def _aes_read(self, key, step: str) -> str:
        """AES witness: ``key`` or ``other``. Resets the AES after ``other``."""
        golden = aes256_ecb_encrypt_words(list(key[:WITNESS_WORDS]), list(AES_PT))
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        await self.aes.start_block_no_wait(list(AES_PT))
        t0 = self._cyc()
        first = self.aes_first_clk is None
        dur = None
        while True:
            st = await self.aes._rd(AES_STATUS)
            el = self._cyc() - t0
            if st & (1 << AES_STATUS_OUTPUT_VALID):
                dur = el
                break
            if first and el > AES_FIRST_BOUND:
                raise AssertionError(
                    f"AES witness ({step}): the first AES read of the leaf gave no output "
                    f"within {AES_FIRST_BOUND} clocks"
                )
            if not first and el > self.aes_w_clk:
                break
            await ClockCycles(cocotb.top.clk_i, AES_POLL_GAP)
        out = await self.aes.read_data_out() if dur is not None else None
        if first:
            self.aes_first_clk = dur
            self.aes_w_clk = W_FACTOR * dur
            self.logger.info("LOG aes_first_clk=%d aes_w_clk=%d (%s)", dur, self.aes_w_clk, step)
        state = "key" if out == golden else "other"
        if state == "other":
            self.chk.obs(
                "AES-NOKEY",
                step=step,
                output="none" if out is None else "0x" + "".join(f"{w:08x}" for w in out),
                aes_w_clk=self.aes_w_clk,
            )
            await self._aes_reset()
        return state

    async def _hmac_read(self, key, msg) -> str:
        """HMAC witness: ``key``, ``nokey`` or ``other``."""
        await self.hmac.write_key(list(pl.HMAC_SW_KEY))
        await self.hmac.configure_keyed_256()
        digest = await self.hmac.run_keyed_mac(list(msg))
        g_sw = hmac_sha256_words(list(pl.HMAC_SW_KEY), list(msg), key_word_rev=False, key_be=True)
        g_key = hmac_sha256_words(list(key[:WITNESS_WORDS]), list(msg))
        if g_key == g_sw:
            raise AssertionError("test construction error: key golden equals the SW-key golden")
        if digest == g_key:
            return "key"
        if digest == g_sw:
            return "nokey"
        self.logger.info("LOG hmac digest=%s (neither golden)", [_hx(w) for w in digest])
        return "other"

    # ================================================================ ML-KEM
    async def _kem_wait(self, mask: int, expect: int, what: str) -> int:
        for _ in range(KEM_POLLS):
            st = await self.kem.rd32(MLKEM_STATUS)
            if st & KEM_ST_ERROR:
                raise AssertionError(f"precondition: {what}: ML-KEM STATUS.ERROR (0x{st:08x})")
            if (st & mask) == expect:
                return st
            await ClockCycles(cocotb.top.clk_i, KEM_GAP)
        raise AssertionError(f"precondition: {what}: ML-KEM STATUS never 0x{expect:x}")

    async def _kem_keygen(self) -> list[int]:
        """Register KEYGEN of the directed seed; returns the encapsulation key."""
        await self._kem_wait(KEM_ST_READY, KEM_ST_READY, "keygen READY")
        await self.kem.write_words(MLKEM_SEED_D, list(_KEM_D))
        await self.kem.write_words(MLKEM_SEED_Z, list(_KEM_Z))
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN)
        await self._kem_wait(KEM_ST_VALID, KEM_ST_VALID, "keygen VALID")
        ek = await self.kem.read_words(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
        if not any(ek):
            raise AssertionError("precondition: the ML-KEM encapsulation key reads all zero")
        await self.kem.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self._kem_wait(KEM_ST_VALID, 0, "zeroize VALID clear")
        return ek

    async def _kem_encaps_pending(self, ek: list[int]) -> None:
        """ENCAPS with the message from the KM message bank and the shared key
        written back to the KM; then read RESP_ABR_SHARED_KEY_READY.

        The VALID of an earlier operation is cleared first, so the VALID wait
        below belongs to this encapsulation.
        """
        if await self.kem.rd32(MLKEM_STATUS) & KEM_ST_VALID:
            await self.kem.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
            await self._kem_wait(KEM_ST_VALID, 0, "zeroize VALID clear")
        await self._kem_wait(KEM_ST_READY, KEM_ST_READY, "encaps READY")
        await self.kem.wr32(MLKEM_KV_MSG_RD_CTRL, KV_READ_EN)
        await self.kem.wr32(MLKEM_KV_SK_WR_CTRL, KV_WRITE_EN)
        await self.kem.write_words(MLKEM_ENCAPS_KEY, list(ek))
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_ENCAPS)
        await self._kem_wait(KEM_ST_VALID, KEM_ST_VALID, "encaps VALID")
        fr = await self._read_frame(FRAME_POLLS)
        if fr is None or fr.bad or fr.resp_id != KM_RESP_ABR_SHARED_KEY_READY:
            raise AssertionError(
                "precondition: no RESP_ABR_SHARED_KEY_READY after the encapsulation "
                f"({'none' if fr is None else fr.text()})"
            )
        if fr.seq != self.resp_next:
            raise AssertionError(f"response sequence {fr.seq}, expected {self.resp_next}")
        self.resp_next = (fr.seq + 1) & 0xFF
        self.sk_pending = True
        self.logger.info("LOG RESP_ABR_SHARED_KEY_READY frame=%s", fr.text())

    # ================================================================ fatal plumbing
    async def _wipe_write(self, value: int) -> None:
        mask = SEP_CPU_CTRL.field_mask("KM_WIPE_CTRL", "wipe_state")
        await self._cpu_ctrl_wr("KM_WIPE_CTRL", mask if value else 0)

    async def _cpu_ctrl_wr(self, reg: str, value: int) -> None:
        addr = SEP_CPU_CTRL.addr(reg)
        seq = SepAxiAccessSeq(f"wr_{reg}", op=SepAxiOp.WRITE, addr=addr, wdata=value, size=2)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"{reg} write @0x{addr:08x} not OKAY")

    async def _cpu_ctrl_rd(self, reg: str) -> int:
        addr = SEP_CPU_CTRL.addr(reg)
        seq = SepAxiAccessSeq(f"rd_{reg}", op=SepAxiOp.READ, addr=addr, size=2)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"{reg} read @0x{addr:08x} not OKAY")
        return seq.rdata & 0xFFFF_FFFF

    async def _wait_rise(self, watch: _FatalWatch, what: str) -> bool:
        for _ in range(RISE_BOUND // 64):
            if watch.rise is not None:
                return True
            await ClockCycles(cocotb.top.clk_i, 64)
        if watch.rise is None:
            self.logger.error(
                "%s: PIC bit 30 did not rise within %d clocks of the injection", what, RISE_BOUND
            )
            return False
        return True

    async def _trap_window(self, w_clk: int) -> tuple[int, int, list[_Frame]]:
        """Send CMD_STAT, then sample bit 30 20 times over ``w_clk`` clocks and
        read every frame that arrives. Returns (high samples, RESP_CMD frames, frames)."""
        await self._send(KM_CMD_STAT, [])
        step = max(1, w_clk // TRAP_SAMPLES)
        high = 0
        frames: list[_Frame] = []
        for _ in range(TRAP_SAMPLES):
            await ClockCycles(cocotb.top.clk_i, step)
            await ReadOnly()
            high += self._b30()
            await RisingEdge(cocotb.top.clk_i)
            frames += await self._drain()
        answered = sum(1 for f in frames if f.resp_id == KM_RESP_CMD)
        return high, answered, frames

    async def _settle(self, stat_clk: int) -> None:
        """Wait until the outbound depth stops changing (the KM queued its responses)."""
        prev, stable = -1, 0
        for _ in range(SETTLE_POLLS):
            d = await self._out_depth()
            stable = stable + 1 if d == prev else 0
            if stable >= SETTLE_STABLE:
                return
            prev = d
            await ClockCycles(cocotb.top.clk_i, max(64, stat_clk // 2))
        self.logger.info("LOG outbound depth did not settle; the quiet control decides")

    # ================================================================ precondition
    async def _precondition(self, witness: bool) -> _Pre:
        """Steps 3 and 4: keys in V, a pending shared key, r unread responses, quiet."""
        p = self.plan
        for key in p.transfer_order():
            handle = await self._load(key.words, key.dest)
            await self._transfer_pre(handle, key.dest)
        if self.ek is None:
            self.ek = await self._kem_keygen()
        await self._kem_encaps_pending(self.ek)
        hmac = aes = None
        if witness:
            hmac = await self._hmac_read(p.keys[0].words, HMAC_MSG)
            aes = await self._aes_read(p.keys[0].words, "pre_wipe")
        t0 = self._cyc()
        code, arg, _ = await self._cmd(KM_CMD_STAT, [])
        stat_clk = self._cyc() - t0
        for _ in range(p.r):
            await self._send(KM_CMD_STAT, [])
        pre = _Pre(
            keyvalid=self._kv(),
            shared=self._sk(),
            kpv_words_nonzero=self._kpv()[0],
            stat_clk=stat_clk,
            stat_ok=code == KM_RC_SUCCESS,
            hmac=hmac,
            aes=aes,
        )
        self.logger.info(
            "LOG pre-state keyvalid=%s v=%s shared=%d kpv_words_nonzero=%d ctrl_stat_clk=%d "
            "stat=%s r=%d",
            _h2(pre.keyvalid),
            _h2(p.v),
            pre.shared,
            pre.kpv_words_nonzero,
            stat_clk,
            _hx(arg),
            p.r,
        )
        # Step 4: the quiet window, w_clk = 10 x ctrl_stat_clk of this point.
        await self._settle(stat_clk)
        pre.w_clk = QUIET_FACTOR * stat_clk
        self.w_ref = pre.w_clk
        pre.wr_start = self._wr_count()
        for _ in range(pre.w_clk):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            pre.quiet_high += self._b30()
        await RisingEdge(cocotb.top.clk_i)
        pre.wr_end = self._wr_count()
        pre.depth = await self._out_depth()
        self.logger.info(
            "LOG quiet window w_clk=%d ctrl_stat_clk=%d pic30_high=%d sram_writes=%d->%d "
            "out_depth=%d",
            pre.w_clk,
            stat_clk,
            pre.quiet_high,
            pre.wr_start,
            pre.wr_end,
            pre.depth,
        )
        return pre

    def _shred_first(self, pre: _Pre, watch: _FatalWatch, point: str) -> None:
        f = watch.first
        kv_at = None if f is None else f["keyvalid"]
        sk_at = None if f is None else f["shared"]
        fields = dict(
            point=point,
            keyvalid_before=_h2(pre.keyvalid),
            shared_before=pre.shared,
            keyvalid_at_report="none" if kv_at is None else _h2(kv_at),
            shared_zero=int(sk_at == 0),
            kv_unknown="none" if f is None else f["kv_unknown"],
            kpv_words_nonzero_logged="none" if f is None else f["kpv_words_nonzero"],
            kpv_ctrl_nonzero_logged="none" if f is None else f["kpv_ctrl_nonzero"],
        )
        if self.unrec:
            # Control: the pre-state record holds keys and a pending shared key,
            # so a clear sample at the fault word is a change.
            ok = (
                pre.keyvalid != 0
                and pre.shared == 1
                and f is not None
                and kv_at == 0
                and not f["kv_unknown"]
                and sk_at == 0
            )
            self.chk.ok("SHRED-FIRST", ok, **fields)
        else:
            self.chk.obs("SHRED-FIRST-HOST", km_unrec_wipe=0, **fields)

    # ================================================================ step 2 and twins
    async def _clean_run(self, n: int, mem: int | None, label: str) -> None:
        """CHK-PARITY-CLEAN: CMD_STAT traffic to ``n`` reads with no fault.

        The run follows the first CMD_STAT of the boot. ``mem`` None runs both
        memories to ``n`` reads; otherwise the memory of a parity point.
        """
        if label == "clean_boot":
            code, arg, _ = await self._cmd(KM_CMD_STAT, [])
            if code != KM_RC_SUCCESS or arg is None or arg & 1:
                raise AssertionError(f"clean boot: CMD_STAT code={code} arg={_hx(arg)}")
        rom0, sram0 = self._reads()
        faults = 0
        stats = 0
        rom_d = sram_d = 0
        while stats < CLEAN_STATS:
            rom1, sram1 = self._reads()
            rom_d, sram_d = rom1 - rom0, sram1 - sram0
            need = (rom_d < n or sram_d < n) if mem is None else ((rom_d, sram_d)[mem] < n)
            if not need:
                break
            sent = await self._send(KM_CMD_STAT, [])
            stats += 1
            got = False
            for _ in range(4):
                fr = await self._read_frame(FRAME_POLLS)
                if fr is None:
                    break
                self.resp_next = (fr.seq + 1) & 0xFF
                if fr.resp_id in (KM_RESP_RECOVERABLE_FAULT, KM_RESP_UNRECOVERABLE_FAULT):
                    faults += 1
                    continue
                if fr.resp_cmd(KM_CMD_STAT, sent)[0] is not None:
                    got = True
                    break
            if not got:
                break
        rom1, sram1 = self._reads()
        rom_d, sram_d = rom1 - rom0, sram1 - sram0
        b = self._b30()
        reached = (rom_d >= n and sram_d >= n) if mem is None else ((rom_d, sram_d)[mem] >= n)
        self.chk.ok(
            "PARITY-CLEAN",
            reached and b == 0 and faults == 0,
            run=label,
            reads=n,
            mem="both" if mem is None else pl.MEM_NAME[mem],
            rom_reads=rom_d,
            sram_reads=sram_d,
            stats=stats,
            err_o=b,
            frames=faults,
        )

    # ================================================================ steps 3 to 9
    async def _real_wipe_point(self) -> None:
        p = self.plan
        self.fresh = False
        pre = await self._precondition(witness=True)
        wr_base = self._wr_count()  # step 5
        depth_before = pre.depth
        watch = _FatalWatch(self)
        watch.start()
        await self._wipe_write(1)
        await ClockCycles(cocotb.top.clk_i, p.wipe_w)
        await self._wipe_write(0)
        rose = await self._wait_rise(watch, "real wipe")  # step 6
        frames = await self._drain()
        high, answered, wframes = await self._trap_window(pre.w_clk)
        delta = None if watch.wr_at_rise is None else watch.wr_at_rise - wr_base  # step 7
        hmac_after = await self._hmac_read(p.keys[0].words, HMAC_MSG2)
        aes_after = await self._aes_read(p.keys[0].words, "post_wipe")
        status = self._csr_status()  # step 8
        watch.stop()
        b_end = self._b30()

        one = len(frames) == 1 and not frames[0].bad
        code = frames[0].fault_word if one else None
        is_wipe = one and frames[0].is_fault(KM_RESP_UNRECOVERABLE_FAULT, pl.CODE["wipe_state"])
        fault_frames = sum(1 for f in frames if f.resp_id == KM_RESP_UNRECOVERABLE_FAULT)
        if self.unrec:
            self.chk.ok(
                "FATAL-WIPE",
                pre.quiet_high == 0 and rose and is_wipe,
                code=_hx(code),
                frames=len(frames),
                err_o=int(rose),
                control_quiet=pre.quiet_high,
                frame_ids=_ids(frames),
            )
        else:
            # The code on the wipe-off build is graded by the open wipe test; the
            # line shows that the point reached the fatal state.
            self.chk.ok(
                "FATAL-WIPE",
                pre.quiet_high == 0 and rose and fault_frames >= 1,
                control=1,
                code=_hx(code),
                frames=len(frames),
                err_o=int(rose),
            )
        stale = sum(1 for f in frames if f.resp_id == KM_RESP_CMD)
        # Control: r responses sat unread in the outbound FIFO before the write.
        self.chk.ok(
            "FLUSH-FIRST",
            depth_before > 0 and len(frames) == 1 and stale == 0 and rose,
            out_depth_before=depth_before,
            out_frames_after=len(frames),
            stale_resp=stale,
            r=p.r,
        )
        self.chk.ok(
            "TRAP-HELD",
            pre.quiet_high == 0
            and pre.stat_ok
            and rose
            and high == TRAP_SAMPLES
            and watch.low_after_rise == 0
            and answered == 0,
            control_quiet=pre.quiet_high,
            control_stat="answered" if pre.stat_ok else "none",
            ctrl_stat_clk=pre.stat_clk,
            w_clk=pre.w_clk,
            err_o=int(rose),
            samples=TRAP_SAMPLES,
            high=high,
            low_after_rise=watch.low_after_rise,
            stat_answered=answered,
            window_frames=_ids(wframes),
        )
        wipe_bit = 1 << pl.IRQ_BIT["wipe_state"]
        self.chk.ok(
            "STATUS-HELD",
            rose and (status & wipe_bit) == wipe_bit,
            point="real_wipe",
            set=f"0x{wipe_bit:03x}",
            status=f"0x{status:03x}",
        )
        if self.unrec:
            # Control: the count does not move in the quiet window before the write.
            self.chk.ok(
                "SRAM-SHRED",
                rose
                and pre.wr_start == pre.wr_end
                and delta is not None
                and delta >= pl.SRAM_WORDS,
                writes_delta="none" if delta is None else delta,
                min=pl.SRAM_WORDS,
                full_extent_logged=pl.SRAM_FULL_EXTENT,
                control_quiet_writes=pre.wr_end - pre.wr_start,
            )
            self.chk.ok(
                "SHRED-WITNESS",
                pre.hmac == "key"
                and pre.aes == "key"
                and hmac_after == "nokey"
                and aes_after != "key",
                hmac_before="golden" if pre.hmac == "key" else pre.hmac,
                hmac_after=hmac_after,
                aes_before="golden" if pre.aes == "key" else pre.aes,
                aes_key_after=int(aes_after == "key"),
            )
        else:
            assert HMAC_MSG2 != HMAC_MSG
            self.chk.ok(
                "NOSHRED-HOST",
                pre.hmac == "key" and rose and fault_frames >= 1 and hmac_after == "key",
                km_unrec_wipe=0,
                hmac_before="golden" if pre.hmac == "key" else pre.hmac,
                hmac_after="golden" if hmac_after == "key" else hmac_after,
                msg_changed=1,
                writes_delta_logged="none" if delta is None else delta,
            )
            self.chk.obs("NOSHRED-HOST-AES", control=1, aes_before=pre.aes, aes_after=aes_after)
        self._shred_first(pre, watch, "real_wipe")
        self.logger.info(
            "LOG real wipe: W=%d status=0x%03x err_o_end=%d rise_cyc=%s",
            p.wipe_w,
            status,
            b_end,
            watch.rise,
        )
        await self._boot("real wipe")  # step 9

    # ================================================================ steps 10 and 11
    async def _irqset_point(self, names: tuple[str, ...]) -> None:
        top = cocotb.top
        await self._fresh(f"before {'+'.join(names)}")
        mask = pl.set_mask(names)
        pre = await self._precondition(witness=False)
        watch = _FatalWatch(self)
        watch.start()
        await RisingEdge(top.clk_i)
        top.km_irqset_mask_i.value = mask
        top.km_irqset_arm_i.value = 1
        rose = await self._wait_rise(watch, f"HK-IRQSET {names}")
        fired = self.rd(top.km_irqset_fired_o, allow_unknown=True)
        frames = await self._drain()
        high, answered, _wf = await self._trap_window(pre.w_clk)
        status = self._csr_status()
        words_nz, words_unk, ctrl_nz = self._kpv()
        watch.stop()
        await RisingEdge(top.clk_i)
        top.km_irqset_arm_i.value = 0
        top.km_irqset_mask_i.value = 0

        exp = pl.expected_code(names)
        first = pl.first_source(names)
        one = len(frames) == 1
        code = frames[0].fault_word if one else None
        control_err = int(rose and high == TRAP_SAMPLES and answered == 0)
        fields = dict(
            set=f"0x{mask:03x}",
            names="+".join(names),
            order_first=first,
            code=_hx(code),
            frames=len(frames),
            control_err_o=control_err,
            fired=fired,
        )
        if tuple(names) == pl.FORCED_DRBG_SET:
            # CHK-DRBG-STALL grades drbg_err over axi_slverr on the organic stall.
            faults = sum(1 for f in frames if f.resp_id == KM_RESP_UNRECOVERABLE_FAULT)
            self.chk.ok("FATAL-SET", fired == 1 and rose and faults >= 1, control=1, **fields)
        else:
            ok = (
                fired == 1
                and pre.quiet_high == 0
                and one
                and frames[0].is_fault(KM_RESP_UNRECOVERABLE_FAULT, exp)
                and control_err == 1
            )
            self.chk.ok("FATAL-SET", ok, expected=_hx(pl.fault_word(exp)), **fields)
        self.chk.ok(
            "STATUS-HELD",
            fired == 1 and rose and (status & mask) == mask,
            point="irqset",
            set=f"0x{mask:03x}",
            status=f"0x{status:03x}",
        )
        self._shred_first(pre, watch, "irqset_" + "+".join(names))
        # Control: the vault holds keys before the injection.
        self.chk.ok(
            "KPV-TRAP",
            rose
            and pre.kpv_words_nonzero > 0
            and words_nz == 0
            and words_unk == 0
            and ctrl_nz == 0,
            control=1,
            set=f"0x{mask:03x}",
            words_nonzero_before=pre.kpv_words_nonzero,
            words_nonzero=words_nz + words_unk,
            ctrl_nonzero=ctrl_nz,
        )
        await self._boot("+".join(names))

    # ================================================================ step 12
    async def _par_traffic(self, lane: int) -> tuple[bool, bool]:
        """CMD_STAT frames until HK-PAR fires; (fired, flipped lane checked by the KM)."""
        top = cocotb.top
        for _ in range(PAR_STATS):
            sent = await self._send(KM_CMD_STAT, [])
            for _ in range(STAT_POLLS):
                await ClockCycles(top.clk_i, POLL)
                if self.rd(top.km_par_fired_o, allow_unknown=True):
                    rstrb = self.rd(top.km_par_rstrb_o, allow_unknown=True)
                    if (rstrb >> lane) & 1:
                        return True, True
                    await self._finish_stat(sent)
                    return True, False
                if not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                    await self._finish_stat(sent)
                    break
            else:
                raise AssertionError(f"parity traffic: no answer to CMD_STAT seq {sent}")
        return False, False

    async def _finish_stat(self, sent: int) -> None:
        fr = await self._read_frame(FRAME_POLLS)
        if fr is None or fr.resp_cmd(KM_CMD_STAT, sent)[0] != KM_RC_SUCCESS:
            raise AssertionError(
                f"parity traffic: CMD_STAT seq {sent} got {'none' if fr is None else fr.text()}"
            )
        self.resp_next = (fr.seq + 1) & 0xFF

    async def _parity_point(self, mem: int, lane: int, n0: int) -> None:
        top = cocotb.top
        await self._fresh(f"before parity {pl.MEM_NAME[mem]} lane {lane}")
        watch = _FatalWatch(self)
        watch.start()
        consumed = fired = False
        n = n0
        redraws = 0
        for redraws in range(PAR_REDRAWS + 1):
            n = min(n0 + redraws, 255)
            await RisingEdge(top.clk_i)
            top.km_par_mem_i.value = mem
            top.km_par_lane_i.value = lane
            top.km_par_n_i.value = n
            top.km_par_arm_i.value = 1
            fired, consumed = await self._par_traffic(lane)
            if consumed:
                break
            self.logger.info(
                "VACUOUS mem=%s lane=%d n=%d fired=%d rstrb=0x%x seed=%d",
                pl.MEM_NAME[mem],
                lane,
                n,
                int(fired),
                self.rd(top.km_par_rstrb_o, allow_unknown=True),
                self.plan.seed,
            )
            await RisingEdge(top.clk_i)
            top.km_par_arm_i.value = 0
        self.chk.ok(
            "PARITY-VAC",
            consumed,
            mem=pl.MEM_NAME[mem],
            lane=lane,
            n_drawn=n0,
            redraws=redraws,
        )
        status = 0
        frames: list[_Frame] = []
        rose = False
        resp_count = self.rd(top.km_par_resp_count_o, allow_unknown=True)
        if consumed:
            rose = await self._wait_rise(watch, f"parity {pl.MEM_NAME[mem]}")
            frames = await self._drain()
            status = self._csr_status()
            src = pl.MEM_SOURCE[mem]
            other = pl.MEM_SOURCE[1 - mem]
            par_bit = (status >> pl.IRQ_BIT[src]) & 1
            other_bit = (status >> pl.IRQ_BIT[other]) & 1
            code = frames[0].fault_word if len(frames) == 1 else None
            self.chk.ok(
                "PARITY",
                rose
                and par_bit == 1
                and other_bit == 0
                and len(frames) == 1
                and frames[0].is_fault(KM_RESP_UNRECOVERABLE_FAULT, pl.CODE[src]),
                mem=pl.MEM_NAME[mem],
                lane=lane,
                n=n,
                par_bit=par_bit,
                other_par_bit=other_bit,
                status_logged=f"0x{status:03x}",
                code=_hx(code),
                err_o=int(rose),
                frames=_ids(frames),
            )
        watch.stop()
        await RisingEdge(top.clk_i)
        top.km_par_arm_i.value = 0
        top.km_par_n_i.value = 0
        # The no-flip twin runs to the same read count with HK-PAR idle.
        await self._boot(f"parity {pl.MEM_NAME[mem]} lane {lane}")
        self.fresh = False
        await self._clean_run(max(n, resp_count), mem, f"twin_{pl.MEM_NAME[mem]}{lane}")
        await self._boot(f"parity twin {pl.MEM_NAME[mem]} lane {lane}")

    # ================================================================ steps 13 to 18
    async def _set_kpv_flip(self, en: int, index: int = 0, bit: int = 0) -> None:
        top = cocotb.top
        await RisingEdge(top.clk_i)
        if en:
            if not 0 <= index < KPV_INDEX_MAX:
                raise AssertionError(f"HK-KPV index {index} outside the KPV")
            top.km_kpv_flip_index_i.value = index
            top.km_kpv_flip_bit_i.value = bit
        top.km_kpv_flip_en_i.value = en
        await ClockCycles(top.clk_i, 2)

    def _run_of(self, before: list[int], after: list[int], words: int, what: str) -> list[int]:
        run = [s for s in range(64) if before[s] != after[s]]
        want = pl.slots_of(words)
        if not run or run != list(range(run[0], run[0] + want)):
            raise AssertionError(
                f"precondition: the CTRL change of the load of {what} ({words} words) is "
                f"slots {run}, not {want} consecutive slots"
            )
        return run

    async def _keycrc_leg(self) -> None:
        p = self.plan
        top = cocotb.top
        await self._fresh("key CRC leg")
        # Step 13.
        hb = await self._load(p.key_b, AES_MASK)
        c0 = self._ctrl_slots()
        ha = await self._load(p.key_a, p.dest_a)
        c1 = self._ctrl_slots()
        run_a = self._run_of(c0, c1, len(p.key_a), "key A")
        s_a = run_a[0]
        self.bus.start()
        code_c, arg_c, _ = await self._cmd(KM_CMD_KEY_TRANSFER, [ha, AES_MASK])
        await self.bus.stop()
        ctrl_aes_writes = self.bus.hs[PORT_AES]
        ctrl_xfer_ok = code_c == KM_RC_SUCCESS
        code_s, _arg_s, _ = await self._cmd(KM_CMD_ENGINE_SHRED, [AES_MASK])
        if code_s != KM_RC_SUCCESS:
            raise AssertionError(f"precondition: CMD_ENGINE_SHRED AES code={code_s}")
        assert p.outside_a & ~p.dest_a, "the outside destination is in the policy of key A"
        sent, pol = await self._cmd_frames(KM_CMD_KEY_TRANSFER, [ha, p.outside_a])
        control_first = pol[0].resp_id
        pol_code, pol_arg = pol[-1].resp_cmd(KM_CMD_KEY_TRANSFER, sent)
        pol_ok = len(pol) == 1 and pol_code == KM_RC_FAILURE and pol_arg is None
        self.logger.info(
            "LOG key A run=%d-%d handle=%s control xfer code=%d arg=%s aes_writes=%d "
            "policy code=%s arg=%s",
            run_a[0],
            run_a[-1],
            _h2(ha),
            code_c,
            _hx(arg_c),
            ctrl_aes_writes,
            pol_code,
            _hx(pol_arg),
        )

        # Step 14: HK-KPV on the logical index of a used word of key A.
        index = s_a * pl.SLOT_WORDS + p.flip_word
        await self._set_kpv_flip(1, index, p.flip_bit)
        ctrl_a = [self._ctrl_slots()[s] for s in run_a]
        resp_expected = self.resp_next
        self.bus.start()
        sent14, f14 = await self._cmd_frames(KM_CMD_KEY_TRANSFER, [ha, p.outside_a], track=False)
        await self.bus.stop()
        flips14 = self.rd(top.km_kpv_flip_count_o, allow_unknown=True)
        bus14 = self.bus.writes
        ctrl14 = [self._ctrl_slots()[s] for s in run_a]
        self.logger.info(
            "LOG key CRC transfer outside policy frames=%s flips=%d kv=%s recov_err=%d "
            "bus_writes_logged=%d",
            [f.text() for f in f14],
            flips14,
            _h2(self._kv()),
            self.rd(top.km_csr_recov_err_o, allow_unknown=True),
            bus14,
        )
        fa = f14[0]
        fb = f14[1] if len(f14) > 1 else None
        first_ok = fa.is_fault(KM_RESP_RECOVERABLE_FAULT, pl.CODE_KEY_SLOT_CRC)
        b_code, b_arg = (None, None) if fb is None else fb.resp_cmd(KM_CMD_KEY_TRANSFER, sent14)

        # Step 15.
        code15, arg15, _ = await self._cmd(KM_CMD_STAT, [])
        next_cmd_ok = code15 == KM_RC_SUCCESS and arg15 is not None and (arg15 & 1) == 1
        expected_next = self.km.seq_num
        assert expected_next != 0, "the sequence-0 frame equals the expected sequence"
        sent0, f0 = await self._cmd_frames(KM_CMD_STAT, [], seq=0)
        seq0_code, seq0_arg = f0[-1].resp_cmd(KM_CMD_STAT, sent0)

        # Step 16.
        ack1, _a, _ = await self._cmd(KM_CMD_RECOV_ACK, [])
        self.bus.start()
        sent16, f16 = await self._cmd_frames(KM_CMD_KEY_TRANSFER, [ha, AES_MASK], track=False)
        await self.bus.stop()
        bus16 = self.bus.writes
        bus16_unknown = self.bus.unknown
        flips16 = self.rd(top.km_kpv_flip_count_o, allow_unknown=True)
        ctrl16 = [self._ctrl_slots()[s] for s in run_a]
        kv16 = self._kv()
        a16 = (
            len(f16) == 2
            and f16[0].is_fault(KM_RESP_RECOVERABLE_FAULT, pl.CODE_KEY_SLOT_CRC)
            and f16[1].resp_cmd(KM_CMD_KEY_TRANSFER, sent16) == (KM_RC_FAILURE, None)
        )

        # Step 17.
        g_sent, g_frames = await self._cmd_frames(KM_CMD_KEY_TRANSFER, [hb, AES_MASK])
        g_code, g_arg = g_frames[-1].resp_cmd(KM_CMD_KEY_TRANSFER, g_sent)
        g_one = len(g_frames) == 1
        ack2, _a2, _ = await self._cmd(KM_CMD_RECOV_ACK, [])
        b_ok, b_ok_arg, _ = await self._cmd(KM_CMD_KEY_TRANSFER, [hb, AES_MASK])
        kv17 = self._kv()

        # Step 18: residue word of key C.
        c2 = self._ctrl_slots()
        hc = await self._load(p.key_c, AES_MASK)
        c3 = self._ctrl_slots()
        await self._set_kpv_flip(0)
        run_c = self._run_of(c2, c3, len(p.key_c), "key C")
        flip_index = run_c[-1] * pl.SLOT_WORDS + p.residue_j
        assert p.residue_j >= len(p.key_c) % pl.SLOT_WORDS, "the residue flip is a key word"
        await self._set_kpv_flip(1, flip_index, p.residue_bit)
        sent18, f18 = await self._cmd_frames(KM_CMD_KEY_TRANSFER, [hc, AES_MASK])
        flips18 = self.rd(top.km_kpv_flip_count_o, allow_unknown=True)
        await self._set_kpv_flip(0)
        r_code, r_arg = f18[-1].resp_cmd(KM_CMD_KEY_TRANSFER, sent18)

        # Grades.
        ctrl_same = ctrl14 == ctrl_a and ctrl16 == ctrl_a
        self.chk.ok(
            "KEYCRC",
            flips14 > 0
            and ctrl_xfer_ok
            and ctrl_aes_writes > 0
            and len(f14) == 2
            and first_ok
            and b_code == KM_RC_FAILURE
            and b_arg is None
            and next_cmd_ok
            and ctrl_same
            and a16
            and bus16 == 0
            and bus16_unknown == 0,
            size=len(p.key_a),
            word=p.flip_word,
            word_class=p.word_class,
            bit=p.flip_bit,
            index=index,
            first=_h2(fa.resp_id),
            code=_signed8(fa.fault_word) if fa.fault_word is not None else "none",
            second_code="none" if b_code is None else b_code,
            arg="none" if b_arg is None else _hx(b_arg),
            stat=_hx(arg15),
            ctrl_same=int(ctrl_same),
            bus_bank_writes=bus16,
            bus_unknown=bus16_unknown,
            control_bus_aes_writes=ctrl_aes_writes,
            flips=flips14,
            flips_after_ack=flips16,
            kv_after=_h2(kv16),
        )
        self.chk.ok(
            "CRC-FIRST",
            flips14 > 0 and first_ok and pol_ok and control_first == KM_RESP_CMD,
            policy_dest=_h2(p.outside_a),
            first=_h2(fa.resp_id),
            control_first=_h2(control_first),
            control_code="none" if pol_code is None else pol_code,
        )
        seq_a = fa.seq
        seq_b = None if fb is None else fb.seq
        self.chk.ok(
            "NOFLUSH",
            flips14 > 0
            and seq_a == resp_expected
            and seq_b == ((seq_a + 1) & 0xFF)
            and next_cmd_ok
            and seq0_code == KM_RC_CMD_NOSEQ
            and seq0_arg == expected_next,
            resp_seq_a=seq_a,
            resp_seq_b="none" if seq_b is None else seq_b,
            resp_seq_expected=resp_expected,
            next_cmd_ok=int(next_cmd_ok),
            seq0_code="none" if seq0_code is None else seq0_code,
            seq0_arg="none" if seq0_arg is None else seq0_arg,
            next_expected=expected_next,
        )
        self.chk.ok(
            "GATE-AFTER",
            flips16 > 0
            and a16
            and g_one
            and g_code == KM_RC_FAILURE
            and g_arg is None
            and ack1 == KM_RC_SUCCESS
            and ack2 == KM_RC_SUCCESS
            and b_ok == KM_RC_SUCCESS
            and (kv17 & AES_MASK) == AES_MASK,
            b_gated="none" if g_code is None else g_code,
            b_gated_arg=_hx(g_arg),
            b_gated_frames=_ids(g_frames),
            ack=ack2,
            b_ok=b_ok,
            b_ok_arg=_hx(b_ok_arg),
            a_again="fault" if a16 else "none",
            aes_key_valid=(kv17 >> pl.AES) & 1,
        )
        self.chk.ok(
            "RESIDUE",
            len(f18) == 1 and r_code == KM_RC_SUCCESS,
            size=len(p.key_c),
            flip_index=flip_index,
            j=p.residue_j,
            bit=p.residue_bit,
            code="none" if r_code is None else r_code,
            frames=_ids(f18),
            flips_logged=flips18,
        )
        await self._boot("key CRC leg")

    # ================================================================ step 19
    async def _cpu_point(self, line: int, csr_src: str | None) -> None:
        top = cocotb.top
        await self._fresh(f"before CPU line {line}")
        b0 = self._b30()
        lines = pl.CPU_LINE_MASK[line]
        watch = _FatalWatch(self)
        watch.start()
        await RisingEdge(top.clk_i)
        top.km_cpuirq_lines_i.value = lines
        if csr_src is not None:
            top.km_irqset_mask_i.value = pl.set_mask((csr_src,))
            top.km_irqset_arm_i.value = 1
        top.km_cpuirq_arm_i.value = 1
        rose = await self._wait_rise(watch, f"HK-CPUIRQ line {line}")
        fired = self.rd(top.km_cpuirq_fired_o, allow_unknown=True)
        csr_fired = self.rd(top.km_irqset_fired_o, allow_unknown=True) if csr_src else 1
        frames = await self._drain()
        await ClockCycles(top.clk_i, 16)
        await ReadOnly()
        b1 = self._b30()
        await RisingEdge(top.clk_i)
        watch.stop()
        top.km_cpuirq_arm_i.value = 0
        top.km_cpuirq_lines_i.value = 0
        top.km_irqset_arm_i.value = 0
        top.km_irqset_mask_i.value = 0
        exp = pl.CPU_LINE_CODE[line] if csr_src is None else pl.CODE_BUS_ERROR
        one = len(frames) == 1
        code = frames[0].fault_word if one else None
        # Control: the core took the pulsed line.
        self.chk.ctrl(
            "CPU-TRAP-TAKEN",
            fired == 1 and (watch.pend_seen & lines) == lines,
            line=line,
            fired=fired,
            pending_seen=f"0x{watch.pend_seen:x}",
        )
        self.chk.ok(
            "CPU-TRAP",
            b0 == 0
            and fired == 1
            and csr_fired == 1
            and rose
            and b1 == 1
            and one
            and frames[0].is_fault(KM_RESP_UNRECOVERABLE_FAULT, exp),
            line=line,
            with_csr="none" if csr_src is None else csr_src,
            code=_hx(code),
            expected=_hx(pl.fault_word(exp)),
            frames=len(frames),
            err_o=int(rose and b1 == 1),
            fired=fired,
        )
        await self._boot(f"CPU line {line}")

    # ================================================================ step 20
    async def _mainctx_point(self) -> None:
        p = self.plan
        await self._fresh("before the main-context point")
        b0 = self._b30()
        n = len(p.main_image)
        code, arg, _ = await self._cmd(KM_CMD_SRAM_LOAD_EXEC, [n])
        confirm = code == KM_RC_SUCCESS
        frame, orig, flipped = p.main_stream()
        assert flipped != orig, "the flipped stream word equals the original word"
        self.logger.info(
            "LOG main-context stream n=%d w=%d bit=%d original=%s flipped=%s confirm=%d",
            n,
            p.main_w,
            p.main_bit,
            _hx(orig),
            _hx(flipped),
            code,
        )
        watch = _FatalWatch(self)
        watch.start()
        await self._post(frame[:-1])
        await self._post(frame[-1:])
        trailer = watch.cyc
        rose = await self._wait_rise(watch, "main-context fatal")
        frames: list[_Frame] = []
        window = 0
        if rose:
            window = MAIN_HOLD_FACTOR * max(1, watch.rise - trailer)
            end = watch.rise + window
            while watch.cyc < end:
                await ClockCycles(cocotb.top.clk_i, 64)
                frames += await self._drain()
        frames += await self._drain()
        watch.stop()
        held = rose and watch.low_after_rise == 0 and watch.high_after_rise > 0
        m11 = sum(1 for f in frames if f.fault_word == pl.fault_word(pl.CODE_EBREAK))
        one = len(frames) == 1
        self.chk.ok(
            "MAINCTX-FATAL",
            b0 == 0
            and confirm
            and rose
            and one
            and frames[0].is_fault(KM_RESP_UNRECOVERABLE_FAULT, pl.CODE_FW_CRC)
            and m11 == 0
            and held,
            n=n,
            pos="trailer" if p.main_w == n else p.main_w,
            bit=p.main_bit,
            frames=len(frames),
            code=_hx(frames[0].fault_word if one else None),
            code_m11=m11,
            err_o=int(rose),
            held=int(held),
            control_quiet=b0,
            confirm=code,
            confirm_arg=_hx(arg),
            window_clk=window,
            low_in_window=watch.low_after_rise,
            frame_list=[f.text() for f in frames] or "-",
        )
        await self._boot("main-context point")

    # ================================================================ step 21 (HOST)
    async def _drbg_stall_point(self) -> None:
        top = cocotb.top
        await self._fresh("before the DRBG stall point")
        sel = await self._cpu_ctrl_rd("EXT_TRNG_SRC_SEL")
        stop = sel | 1  # sel bit 0: the KM stream takes the external input
        await self._cpu_ctrl_wr("EXT_TRNG_SRC_SEL", stop)
        self.chk.obs(
            "DRBG-STALL-STOP",
            control="EXT_TRNG_SRC_SEL.sel_bit0",
            sel_before=_hx(sel),
            sel_stop=_hx(stop),
            ext_stream="idle",
        )
        seen = 0
        for _ in range(TVALID_WINDOW):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            seen |= self.rd_known(top.km_entropy_tvalid_o)
        await RisingEdge(top.clk_i)
        watch = _FatalWatch(self)
        watch.start()
        await self._send(KM_CMD_KEY_GENERATE, [DRBG_REQ_WORDS - 1, KEYGEN_DEST])
        rose = await self._wait_rise(watch, "DRBG stall")
        frames = await self._drain()
        high, answered, _wf = await self._trap_window(self.w_ref)
        watch.stop()
        one = len(frames) == 1
        code = frames[0].fault_word if one else None
        self.chk.ok(
            "DRBG-STALL",
            seen == 0
            and rose
            and one
            and frames[0].is_fault(KM_RESP_UNRECOVERABLE_FAULT, pl.CODE["drbg_err"])
            and high == TRAP_SAMPLES,
            req_words=DRBG_REQ_WORDS,
            tvalid_seen=seen,
            code=_hx(code),
            frames=len(frames),
            err_o=int(rose),
            samples_high=high,
            stat_answered_logged=answered,
        )
        await self._cpu_ctrl_wr("EXT_TRNG_SRC_SEL", sel)
        await self._boot("DRBG stall")

    # ================================================================ step 22 (HOST)
    async def _keypath_point(self) -> None:
        top = cocotb.top
        await self._fresh("before the key-path point")
        handle = await self._load(self.plan.keys[0].words, HMAC_AES_MASK)
        await self.swrst.park("hmac")
        iso = 0
        for _ in range(ISO_BOUND):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            iso = self.rd(top.hmac_km_isolated_probe_o, allow_unknown=True)
            if iso:
                break
        await RisingEdge(top.clk_i)
        if not iso:
            self.logger.error("hmac_km_isolated_probe_o did not read 1 within %d clocks", ISO_BOUND)
        b0 = self._b30()
        watch = _FatalWatch(self)
        watch.start()
        self.bus.start()
        await self._send(KM_CMD_KEY_TRANSFER, [handle, HMAC_AES_MASK])
        rose = await self._wait_rise(watch, "key path")
        await self.bus.stop()
        frames = await self._drain()
        high, answered, _wf = await self._trap_window(self.w_ref)
        watch.stop()
        one = len(frames) == 1
        code = frames[0].fault_word if one else None
        axi = code in (pl.fault_word(pl.CODE["axi_decerr"]), pl.fault_word(pl.CODE["axi_slverr"]))
        self.chk.ok(
            "KEYPATH-FATAL",
            iso == 1
            and b0 == 0
            and rose
            and one
            and frames[0].resp_id == KM_RESP_UNRECOVERABLE_FAULT
            and axi
            and high == TRAP_SAMPLES,
            iso=iso,
            frames=len(frames),
            code_class="axi" if axi else "other",
            err_o=int(rose),
            samples_high=high,
            control_quiet=b0,
            frame_ids=_ids(frames),
        )
        self.chk.obs("KEYPATH-CODE", code=_hx(code))
        hmac_req = self.bus.req[PORT_HMAC]
        aes_writes = self.bus.req[PORT_AES]  # every AES key write starts with a request
        # Control: the tap sees the request on the HMAC port, so the transfer started.
        self.chk.ctrl("XFER-STOP-HMAC-REQ", hmac_req > 0, hmac_req=hmac_req)
        self.chk.ok(
            "XFER-STOP",
            rose and hmac_req > 0 and aes_writes == 0 and self.bus.unknown == 0,
            hmac_req=hmac_req,
            aes_writes=aes_writes,
            bus_unknown=self.bus.unknown,
            answered_logged=answered,
        )
        await self.swrst.release("hmac")
        await self.hmac.wait_idle("post-keypath")
        await self._boot("key path")

    # ================================================================ step 23
    async def _lat_run(self, mode: str, first: int, stream) -> dict:
        top = cocotb.top
        lat = _LatWatch(self, mode, first, stream)
        base_delayed = self.rd_known(top.km_sram_lat_delayed_count_o)

        async def parked() -> None:
            await RisingEdge(top.clk_i)
            top.km_sram_lat_i.value = first
            top.km_sram_lat_en_i.value = 1
            self.lat_on = True
            lat.start()

        watch = _FatalWatch(self)
        watch.start()
        err = ""
        frames: list[list[int]] = []
        aes = "none"
        try:
            ready = await self._boot(f"latency {mode}", restore=False, parked=parked)
            frames.append(ready.words)
            key = self.plan.keys[0].words
            for cmd, payload in ((KM_CMD_STAT, []), (KM_CMD_KEY_LOAD, [7, AES_MASK, *key])):
                _c, _a, fr = await self._cmd(cmd, payload)
                frames.append(fr.words)
            _c, _a, fr = await self._cmd(KM_CMD_KEY_TRANSFER, [pl.LAT_FIRST_HANDLE, AES_MASK])
            frames.append(fr.words)
            aes = await self._aes_read(key, f"latency_{mode}")
            for cmd, payload in (
                (KM_CMD_KEY_REVOKE, [pl.LAT_FIRST_HANDLE]),
                (KM_CMD_ENGINE_SHRED, [AES_MASK]),
            ):
                _c, _a, fr = await self._cmd(cmd, payload)
                frames.append(fr.words)
        except AssertionError as exc:
            err = str(exc)[:200]
        lat.stop()
        watch.stop()
        self.fresh = False
        delayed = self.rd_known(top.km_sram_lat_delayed_count_o) - base_delayed
        model_ok = len(frames) == 6 and all(pl.lat_frame_ok(i, w) for i, w in enumerate(frames))
        return {
            "frames": frames,
            "model_ok": model_ok,
            "aes": aes,
            "err_o": int(watch.rise is not None),
            "error": err,
            "lat": lat,
            "delayed": delayed,
        }

    async def _lat_leg(self) -> None:
        p = self.plan
        await self._graded(True)
        base = await self._lat_run("base", 1, None)
        bl = base["lat"]
        # Control: the L = 1 twin matches the frame model with the macro latency.
        self.chk.ctrl(
            "LAT-BASE",
            base["model_ok"]
            and base["aes"] == "key"
            and base["err_o"] == 0
            and bl.reads > 0
            and bl.observed == {1},
            model_ok=int(base["model_ok"]),
            aes=base["aes"],
            err_o=base["err_o"],
            reads=bl.reads,
            observed=sorted(bl.observed),
            error=base["error"] or "-",
        )
        fixed = await self._lat_run("fixed", p.lat_fixed, None)
        stream = pl.LatStream(p.lat_seed)
        rnd = await self._lat_run("random", stream.next(), stream)
        for name, run in (("LAT", fixed), ("LAT-VAR", rnd)):
            lw = run["lat"]
            equal = sum(1 for a, b in zip(run["frames"], base["frames"], strict=False) if a == b)
            common = (
                run["model_ok"]
                and equal == 6
                and run["aes"] == "key"
                and run["err_o"] == 0
                and not run["error"]
                and lw.reads > 0
                and lw.mismatch == 0
                and lw.skipped == 0
                and run["delayed"] > 0
            )
            if name == "LAT":
                self.chk.ok(
                    name,
                    common and lw.observed == {p.lat_fixed},
                    mode="fixed",
                    L=p.lat_fixed,
                    observed=sorted(lw.observed),
                    resp_equal=equal,
                    aes_ok=int(run["aes"] == "key"),
                    err_o=run["err_o"],
                    reads=lw.reads,
                    mismatch=lw.mismatch,
                    delayed=run["delayed"],
                    error=run["error"] or "-",
                )
            else:
                self.chk.ok(
                    name,
                    common and lw.expected == set(range(1, 9)),
                    mode="random",
                    L="1..8",
                    values=sorted(lw.expected),
                    resp_equal=equal,
                    aes_ok=int(run["aes"] == "key"),
                    err_o=run["err_o"],
                    reads=lw.reads,
                    mismatch=lw.mismatch,
                    examples=lw.examples or "-",
                    delayed=run["delayed"],
                    error=run["error"] or "-",
                )
