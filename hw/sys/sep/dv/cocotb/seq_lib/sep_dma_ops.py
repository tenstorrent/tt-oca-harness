# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA register operations and SEP memory word access over the CPU-LSU splice.

Every SECURE_DMA address and field position comes from the generated register
export through ``sep_reg_meta``; no offset or mask is retyped.

Contents:

* ``control_word``: CONTROL encoder (OPCODE, HARDWARE_HANDSHAKE_ENABLE,
  DIGEST_SWAP, INITIAL_TRANSFER, ABORT, GO). ``DmaStatus``: a decoded STATUS
  read.
* ``SepDmaOps``: range (BASE, LIMIT, RANGE_VALID), ADDR_SPACE_ID, the transfer
  registers in a caller-given write order, GO and ABORT, the DMA clean state,
  bounded STATUS polls, the size-scaled wait for DONE with the re-GO rule, and
  the SHA2 digest words.
* ``SepMemWords``: frontdoor fill and read of 32-bit word arrays, in 64-bit
  INCR bursts that stay inside one 4 KiB page.

Definitions (shared rules of the DMA entries):

* DMA clean state: write 1 to STATUS.ERROR, STATUS.ABORTED, STATUS.DONE and
  STATUS.CHUNK_DONE.
* Re-GO rule: when a STATUS read shows CHUNK_DONE=1, DONE=0 and BUSY=0, write
  CONTROL with GO=1 and INITIAL_TRANSFER=0 (the other CONTROL fields as the
  transfer started), optionally after a write of 1 to STATUS.CHUNK_DONE, then
  wait (bounded) for a rise of ``dma_busy_probe_o`` after that write. The
  number of GO writes is returned as ``go_writes`` and is not graded here.
* A wait for DONE has a bound that scales with the transfer size. An expired
  bound logs and raises ``FAIL-DMA-TIMEOUT``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import RegBlock, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

SECURE_DMA = RegBlock("SECURE_DMA")
_D = SECURE_DMA

STATUS = _D.addr("STATUS")
CONTROL = _D.addr("CONTROL")
ERROR_CODE = _D.addr("ERROR_CODE")
INTR_STATE = _D.addr("INTR_STATE")
INTR_ENABLE = _D.addr("INTR_ENABLE")
SRC_ADDR_LO = _D.addr("SRC_ADDR_LO")
SRC_ADDR_HI = _D.addr("SRC_ADDR_HI")
DST_ADDR_LO = _D.addr("DST_ADDR_LO")
DST_ADDR_HI = _D.addr("DST_ADDR_HI")
ADDR_SPACE_ID = _D.addr("ADDR_SPACE_ID")
RANGE_BASE = _D.addr("ENABLED_MEMORY_RANGE_BASE")
RANGE_LIMIT = _D.addr("ENABLED_MEMORY_RANGE_LIMIT")
RANGE_VALID = _D.addr("RANGE_VALID")
RANGE_REGWEN = _D.addr("RANGE_REGWEN")
CFG_REGWEN = _D.addr("CFG_REGWEN")
TOTAL_DATA_SIZE = _D.addr("TOTAL_DATA_SIZE")
CHUNK_DATA_SIZE = _D.addr("CHUNK_DATA_SIZE")
TRANSFER_WIDTH = _D.addr("TRANSFER_WIDTH")
SRC_CONFIG = _D.addr("SRC_CONFIG")
DST_CONFIG = _D.addr("DST_CONFIG")
HANDSHAKE_INTR_ENABLE = _D.addr("HANDSHAKE_INTR_ENABLE")
DIGEST_BASE = sym("SECURE_DMA_SHA2_DIGEST_0_0__REG_ADDR")
DIGEST_WORDS = (sym("SECURE_DMA_SHA2_DIGEST_0_15__REG_ADDR") - DIGEST_BASE) // 4 + 1

ST_BUSY = _D.field_mask("STATUS", "busy")
ST_DONE = _D.field_mask("STATUS", "done")
ST_ABORTED = _D.field_mask("STATUS", "aborted")
ST_ERROR = _D.field_mask("STATUS", "error")
ST_DIGEST_VALID = _D.field_mask("STATUS", "sha2_digest_valid")
ST_CHUNK_DONE = _D.field_mask("STATUS", "chunk_done")
ST_CLEAN_W1C = ST_ERROR | ST_ABORTED | ST_DONE | ST_CHUNK_DONE

INTR_DONE = _D.field_mask("INTR_STATE", "dma_done")
INTR_CHUNK_DONE = _D.field_mask("INTR_STATE", "dma_chunk_done")
INTR_ERROR = _D.field_mask("INTR_STATE", "dma_error")

CFG_INCREMENT = _D.field_mask("SRC_CONFIG", "increment")
CFG_WRAP = _D.field_mask("SRC_CONFIG", "wrap")

ERROR_CODE_MASK = _D.mask32("ERROR_CODE")

# OPCODE encodings (sep-programming.adoc, DMA; dma.hjson, OPCODE).
OP_COPY, OP_SHA256, OP_SHA384, OP_SHA512 = 0, 1, 2, 3

# Transfer-register names in the default write order.
XFER_REGS = (
    "SRC_ADDR_LO",
    "SRC_ADDR_HI",
    "DST_ADDR_LO",
    "DST_ADDR_HI",
    "TOTAL_DATA_SIZE",
    "CHUNK_DATA_SIZE",
    "TRANSFER_WIDTH",
    "SRC_CONFIG",
    "DST_CONFIG",
)


def _put(reg: str, fld: str, value: int) -> int:
    mask = _D.field_mask(reg, fld)
    lsb = _D.field_lsb(reg, fld)
    if value < 0 or (value << lsb) & ~mask:
        raise ValueError(f"{reg}.{fld}={value} does not fit the field (mask 0x{mask:x})")
    return int(value << lsb)


def control_word(
    *,
    opcode: int = OP_COPY,
    hs: int = 0,
    digest_swap: int = 0,
    initial: int = 0,
    go: int = 0,
    abort: int = 0,
) -> int:
    """CONTROL value from its fields."""
    return (
        _put("CONTROL", "opcode", opcode)
        | _put("CONTROL", "hardware_handshake_enable", hs)
        | _put("CONTROL", "digest_swap", digest_swap)
        | _put("CONTROL", "initial_transfer", initial)
        | _put("CONTROL", "go", go)
        | _put("CONTROL", "abort", abort)
    )


def addr_cfg(inc: bool, wrap: bool) -> int:
    """SRC_CONFIG / DST_CONFIG value."""
    return (CFG_INCREMENT if inc else 0) | (CFG_WRAP if wrap else 0)


def asid_word(src_asid: int, dst_asid: int) -> int:
    return _put("ADDR_SPACE_ID", "src_asid", src_asid) | _put("ADDR_SPACE_ID", "dst_asid", dst_asid)


@dataclass(frozen=True)
class DmaStatus:
    raw: int

    busy = property(lambda s: int(bool(s.raw & ST_BUSY)))
    done = property(lambda s: int(bool(s.raw & ST_DONE)))
    aborted = property(lambda s: int(bool(s.raw & ST_ABORTED)))
    error = property(lambda s: int(bool(s.raw & ST_ERROR)))
    digest_valid = property(lambda s: int(bool(s.raw & ST_DIGEST_VALID)))
    chunk_done = property(lambda s: int(bool(s.raw & ST_CHUNK_DONE)))

    def fmt(self) -> str:
        return (
            f"STATUS=0x{self.raw:08x} busy={self.busy} done={self.done} "
            f"aborted={self.aborted} error={self.error} digest_valid={self.digest_valid} "
            f"chunk_done={self.chunk_done}"
        )


class DmaTimeout(AssertionError):
    """A size-scaled wait for DONE expired (``FAIL-DMA-TIMEOUT``)."""


@dataclass
class DmaRunResult:
    status: DmaStatus
    go_writes: int
    polls: int
    statuses: list[DmaStatus] = field(default_factory=list)


class SepDmaOps:
    """Secure DMA register operations for a no_cpu leaf."""

    # Poll-count bound of a wait for DONE: base plus polls per KiB of data.
    POLL_BASE = 400
    POLL_PER_KIB = 400

    def __init__(self, test, *, logger=None) -> None:
        self.test = test
        self.log = logger if logger is not None else test.logger
        # The CONTROL value of the last GO write, reused by the re-GO rule.
        self.last_control = 0

    # ---- raw access --------------------------------------------------------
    async def access(
        self, op: SepAxiOp, addr: int, data: int = 0, *, ungraded: bool = False
    ) -> SepAxiAccessSeq:
        """One 32-bit access; the caller reads ``resp_code`` and ``rdata``.

        ``ungraded=True`` hands the response grade to the caller: the
        scoreboard then does not fail a non-OKAY response of this access.
        """
        seq = SepAxiAccessSeq(
            f"dma_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=data & 0xFFFF_FFFF,
            size=2,
            allow_unverified_write_resp=ungraded and op is SepAxiOp.WRITE,
            allow_ungraded_read_resp=ungraded and op is SepAxiOp.READ,
        )
        await self.test.start_seq(seq)
        return seq

    async def wr(self, addr: int, data: int) -> None:
        seq = await self.access(SepAxiOp.WRITE, addr, data)
        if not seq.resp_ok:
            raise AssertionError(f"DMA write @0x{addr:08x} resp={seq.resp_code}, not OKAY")

    async def rd(self, addr: int) -> int:
        seq = await self.access(SepAxiOp.READ, addr)
        if not seq.resp_ok:
            raise AssertionError(f"DMA read @0x{addr:08x} resp={seq.resp_code}, not OKAY")
        return int(seq.rdata) & 0xFFFF_FFFF

    # ---- configuration -----------------------------------------------------
    async def program_range(self, base: int, limit: int, *, valid: bool = True) -> None:
        await self.wr(RANGE_BASE, base)
        await self.wr(RANGE_LIMIT, limit)
        await self.wr(RANGE_VALID, 1 if valid else 0)

    async def set_asid(self, src_asid: int, dst_asid: int) -> None:
        await self.wr(ADDR_SPACE_ID, asid_word(src_asid, dst_asid))

    async def program_transfer(
        self,
        *,
        src: int,
        dst: int,
        total: int,
        chunk: int,
        width_enc: int = 2,
        src_inc: bool = True,
        src_wrap: bool = False,
        dst_inc: bool = True,
        dst_wrap: bool = False,
        src_hi: int = 0,
        dst_hi: int = 0,
        order: Sequence[str] = XFER_REGS,
    ) -> dict[str, int]:
        """Write the transfer registers named in ``order``; returns name -> value written."""
        values = {
            "SRC_ADDR_LO": src,
            "SRC_ADDR_HI": src_hi,
            "DST_ADDR_LO": dst,
            "DST_ADDR_HI": dst_hi,
            "TOTAL_DATA_SIZE": total,
            "CHUNK_DATA_SIZE": chunk,
            "TRANSFER_WIDTH": width_enc,
            "SRC_CONFIG": addr_cfg(src_inc, src_wrap),
            "DST_CONFIG": addr_cfg(dst_inc, dst_wrap),
        }
        unknown = [n for n in order if n not in values]
        if unknown:
            raise KeyError(f"unknown transfer registers {unknown}; known: {list(values)}")
        written = {}
        for name in order:
            await self.wr(_D.addr(name), values[name])
            written[name] = values[name]
        return written

    async def go(
        self, *, opcode: int = OP_COPY, hs: int = 0, digest_swap: int = 0, initial: int = 1
    ) -> int:
        """Write CONTROL with GO=1; returns the value written."""
        value = control_word(opcode=opcode, hs=hs, digest_swap=digest_swap, initial=initial, go=1)
        await self.wr(CONTROL, value)
        self.last_control = value
        return value

    async def abort(self) -> None:
        await self.wr(CONTROL, control_word(abort=1))

    async def clean_state(self) -> None:
        """DMA clean state: W1C STATUS.ERROR, ABORTED, DONE and CHUNK_DONE."""
        await self.wr(STATUS, ST_CLEAN_W1C)

    # ---- STATUS ------------------------------------------------------------
    async def read_status(self) -> DmaStatus:
        return DmaStatus(await self.rd(STATUS))

    async def poll_status(
        self, pred: Callable[[DmaStatus], bool], bound: int, what: str
    ) -> DmaStatus:
        st = None
        for _ in range(bound):
            st = await self.read_status()
            if pred(st):
                return st
        raise AssertionError(
            f"DMA wait '{what}' expired after {bound} STATUS reads "
            f"(last {st.fmt() if st else 'none'})"
        )

    def done_bound(self, total_bytes: int) -> int:
        """Poll bound of a wait for DONE, scaled with the transfer size."""
        return self.POLL_BASE + self.POLL_PER_KIB * (-(-total_bytes // 1024))

    async def run_to_done(
        self,
        total_bytes: int,
        *,
        busy=None,
        w1c_chunk_done: bool = False,
        busy_bound: int = 2_000,
        max_go: int | None = None,
        stop_on: Callable[[DmaStatus], bool] = lambda s: bool(s.error or s.aborted),
        tag: str = "",
    ) -> DmaRunResult:
        """Wait for DONE with the re-GO rule; bounded by ``done_bound(total_bytes)`` reads.

        ``busy`` is a ``env.sep_bit_watch.SepBitWatch`` on ``dma_busy_probe_o``;
        with it, each re-GO waits up to ``busy_bound`` clocks for a BUSY rise
        after the write. Returns at DONE=1, or at a read for which ``stop_on``
        holds (ERROR or ABORTED by default). ``max_go`` caps the GO writes.
        """
        bound = self.done_bound(total_bytes)
        go_writes = 1
        statuses: list[DmaStatus] = []
        for poll in range(1, bound + 1):
            st = await self.read_status()
            statuses.append(st)
            if st.done or stop_on(st):
                return DmaRunResult(st, go_writes, poll, statuses)
            if st.chunk_done and not st.busy:
                if max_go is not None and go_writes >= max_go:
                    raise AssertionError(
                        f"DMA{tag}: CHUNK_DONE=1 DONE=0 BUSY=0 after {go_writes} GO writes "
                        f"(cap {max_go}); {st.fmt()}"
                    )
                if w1c_chunk_done:
                    await self.wr(STATUS, ST_CHUNK_DONE)
                mark = busy.mark() if busy is not None else None
                value = (self.last_control & ~control_word(initial=1)) | control_word(go=1)
                await self.wr(CONTROL, value)
                go_writes += 1
                if busy is not None:
                    await busy.wait_rise(mark, busy_bound)
        last = statuses[-1] if statuses else None
        msg = (
            f"FAIL-DMA-TIMEOUT{tag}: DONE not seen in {bound} STATUS reads "
            f"(total={total_bytes} bytes, go_writes={go_writes}, "
            f"last {last.fmt() if last else 'none'})"
        )
        self.log.error(msg)
        raise DmaTimeout(msg)

    async def read_digest(self, n_words: int = DIGEST_WORDS) -> list[int]:
        if not 0 < n_words <= DIGEST_WORDS:
            raise ValueError(f"digest has {DIGEST_WORDS} words; asked {n_words}")
        return [await self.rd(DIGEST_BASE + 4 * i) for i in range(n_words)]


class SepMemWords:
    """Frontdoor fill and read of 32-bit word arrays in SEP memory (e.g. SRAM).

    Uses 64-bit INCR bursts of at most ``max_beats`` beats that never cross a
    4 KiB page, with a single 32-bit access for a leading or trailing half
    beat. Every access must return OKAY.
    """

    PAGE = 4096

    def __init__(self, test, *, max_beats: int = 64) -> None:
        self.test = test
        self.max_beats = max_beats

    def _spans(self, addr: int, n_bytes: int) -> list[tuple[int, int]]:
        if addr % 4 or n_bytes % 4:
            raise ValueError("word access needs a 4-aligned address and size")
        out = []
        end = addr + n_bytes
        a = addr
        while a < end:
            if a % 8 or end - a < 8:
                out.append((a, 4))
                a += 4
                continue
            page_end = (a // self.PAGE + 1) * self.PAGE
            n = min(end - a, page_end - a, 8 * self.max_beats)
            n -= n % 8
            out.append((a, n))
            a += n
        return out

    async def _acc(self, op: SepAxiOp, addr: int, n: int, data: int = 0) -> int:
        seq = SepAxiAccessSeq(
            f"mem_{op.value}_0x{addr:08x}_{n}",
            op=op,
            addr=addr,
            wdata=data,
            length=n,
            size=2 if n == 4 else 3,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(
                f"memory {op.value} @0x{addr:08x} len={n} resp={seq.resp_code}, not OKAY"
            )
        return int(seq.rdata)

    async def fill(self, addr: int, words: Sequence[int]) -> None:
        raw = b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)
        for a, n in self._spans(addr, len(raw)):
            off = a - addr
            await self._acc(SepAxiOp.WRITE, a, n, int.from_bytes(raw[off : off + n], "little"))

    async def read(self, addr: int, n_words: int) -> list[int]:
        raw = bytearray()
        for a, n in self._spans(addr, 4 * n_words):
            raw += (await self._acc(SepAxiOp.READ, a, n)).to_bytes(n, "little")
        return [int.from_bytes(raw[4 * i : 4 * i + 4], "little") for i in range(n_words)]
