# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The DMA register block refusing a sub-word write, at every writable register.

This block answers a sub-word write with an error response, so
`smc_periph_regblock_sweep_test` configures it with full-width writes. The
generated block says why:
`reg_error = (devmode_i & addrmiss) | wr_err`, and
`wr_err = reg_we & (addr_hit[N] & |(PERMIT[N] & ~reg_be))` -- a write errors
when it leaves out a byte lane that register's `PERMIT` mask requires, not
merely when it is narrow. Every register's update is gated on `!reg_error`, so
such a write is refused before it reaches the register.

That distinction decides where the sub-word write has to land. `PERMIT` covers
the lanes a register's fields occupy, and every register here has fields in its
low half, so a two-byte write at the register's own address can leave `PERMIT`
satisfied and be accepted. The write therefore goes to the upper half, which
omits the low lanes of all thirteen.

This leaf takes each of the thirteen writable registers -- the configuration
word and the twelve transfer-descriptor registers -- through four accesses:

1. a full-width read, which records what the register holds;
2. a full-width write of that same value, which has to be accepted. This is the
   live control: it shows the address is writable at all, so the refusal below
   is the byte enables and not a dead window;
3. a two-byte write at the upper half of the register, which omits lanes
   `PERMIT` requires and so has to be refused with an error response;
4. a full-width read, which has to return the value from step 1.

Step 4 is also why the leaf is safe to run against the transfer descriptors: a
refused write never reaches the register, so the descriptor state the sequence
found is the descriptor state it leaves. Step 2 writes back the value already
there, so it changes nothing either.

No transfer is started. In this frontend the launch is a read of a `NEXT_ID`
register, and `NEXT_ID` is read-only -- it is not in the writable set this leaf
touches, and the leaf reads nothing else.

The read-only registers are left alone. Their uncovered rows pair `addr_hit`
with `reg_re` and a set `reg_error`, and no stimulus can produce that: `reg_re`
and `reg_we` are `valid & ~write` and `valid & write`, so they are mutually
exclusive, `wr_err` is gated on `reg_we`, and `addrmiss` needs no address to
hit. A read that hits an address therefore cannot carry an error.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_register

#: Every `dma_ctrl` register the generated map gives a software-writable field.
_WRITABLE: tuple[str, ...] = (
    "dma_ctrl/CONFIG",
    "dma_ctrl/DST_ADDRESS_LO",
    "dma_ctrl/DST_ADDRESS_HI",
    "dma_ctrl/SRC_ADDRESS_LO",
    "dma_ctrl/SRC_ADDRESS_HI",
    "dma_ctrl/LENGTH_LO",
    "dma_ctrl/LENGTH_HI",
    "dma_ctrl/DST_STRIDE_LO",
    "dma_ctrl/DST_STRIDE_HI",
    "dma_ctrl/SRC_STRIDE_LO",
    "dma_ctrl/SRC_STRIDE_HI",
    "dma_ctrl/NUM_REPETITIONS_LO",
    "dma_ctrl/NUM_REPETITIONS_HI",
)

#: Bytes of the sub-word write, and the offset it lands at. The upper half of
#: the word, so the enabled lanes exclude the low half every one of these
#: registers has fields in.
_SUB_WORD_BYTES = 2
_SUB_WORD_OFFSET = 2
#: Payload of the refused write. Distinct from anything a descriptor holds, so
#: a write that did land would be unmistakable in the readback.
_REFUSED_PATTERN = 0xBEEF

_ACCESSES_PER_REGISTER = 4


class smc_dma_reg_byte_enable_error_test_seq(SmcCsrSeq):
    """Refuse a sub-word write at every writable DMA register."""

    def __init__(self, name: str = "smc_dma_reg_byte_enable_error_test_seq") -> None:
        super().__init__(name)
        self.registers_checked = 0
        #: Response code each refused write returned, in register order.
        self.refused_resps: list[int] = []

    async def _sub_word_write(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr + _SUB_WORD_OFFSET
        item.length = _SUB_WORD_BYTES
        item.wdata = _REFUSED_PATTERN
        item.allow_error = True
        item.expect_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{label} @ 0x{addr + _SUB_WORD_OFFSET:08x}: a {_SUB_WORD_BYTES}-byte write "
            f"over the upper half was answered with resp={item.resp_code}; it leaves out "
            f"lanes this register's PERMIT mask requires, and every register update is "
            f"gated on the byte-enable error that raises"
        )
        return item.resp_code

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        registers = [rdl_register(path) for path in _WRITABLE]
        assert len({reg.addr for reg in registers}) == len(registers), (
            "two of the writable DMA registers resolve to the same address"
        )
        for reg in registers:
            assert reg.rw_mask, (
                f"{reg.path} has no software-writable field, so a full-width write to it "
                f"would not be the live control this leaf needs"
            )

        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update(reg.addr + _SUB_WORD_OFFSET for reg in registers)

        for reg in registers:
            held = await self.csr_read(f"{reg.path}:held", reg.addr, length=reg.width_bytes)
            await self.csr_write(f"{reg.path}:full_width", reg.addr, held, length=reg.width_bytes)
            resp = await self._sub_word_write(f"{reg.path}:sub_word", reg.addr)
            self.refused_resps.append(resp)
            after = await self.csr_read(
                f"{reg.path}:after", reg.addr, expected=held, length=reg.width_bytes
            )
            assert after == held, (
                f"{reg.path} @ 0x{reg.addr:08x} read 0x{held:x} before the refused "
                f"{_SUB_WORD_BYTES}-byte write at 0x{reg.addr + _SUB_WORD_OFFSET:08x} and "
                f"0x{after:x} after it; the refusal has to come before the register update"
            )
            self.registers_checked += 1

        assert self.registers_checked == len(registers), (
            f"{self.registers_checked} of {len(registers)} writable DMA registers checked"
        )
        self.assert_all_reachable(
            len(registers) * _ACCESSES_PER_REGISTER, "DMA_REG_BYTE_ENABLE_ERROR"
        )
        cocotb.log.info(
            "CHK-DMA-REG-BYTE-ENABLE-ERROR: at each of %d writable DMA registers a "
            "full-width write of the word the register already held was accepted and a "
            "%d-byte write over the register's upper half was refused with an error "
            "response (code(s) %s), so the refusal is the missing byte lanes and not a "
            "dead window",
            self.registers_checked,
            _SUB_WORD_BYTES,
            ", ".join(str(r) for r in sorted(set(self.refused_resps))),
        )
        cocotb.log.info(
            "CHK-DMA-REG-REFUSED-WRITE-NO-EFFECT: every one of the %d registers read back "
            "the word it held before its refused write, so the byte-enable error gates the "
            "register update rather than being reported after it -- which is also why this "
            "leaf can run against the transfer descriptors without disturbing them",
            self.registers_checked,
        )
