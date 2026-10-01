# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Requests that reach a register block while one of its external registers is busy.

Six SMC register blocks carry an external register: an access to it is handed
to logic outside the generated block, and until that logic acknowledges, the
block holds `external_pending` and stalls every further request. Serial traffic
never presents a second request during that window, so the stall has never
held anything back on any of them.

Each block here takes one outstanding group that opens with an access to its
external register and follows it at once with a read and a write of the block's
probe register -- the same side-effect-free register `smc_cpuif_handshake_test`
uses. The read and the write arrive while the external access is still
pending, so both the read-side and the write-side stall hold a request back.
A second external access closes the group. The claim is the one a stalled
manager is owed: every request the stall held back is answered once it lifts,
the probe read returns the value the block held, and the probe still holds it.

The external access is chosen so that it changes nothing:

* `AVS_CMD` (AVSBus) and `FDATA` (I2C) are write-only, so a read of either
  returns zero and pushes no command or format byte;
* `RESET_CTRL` (CPU_CTRL) holds the core resets and is only ever read here;
* `CREDIT_EXPIRED` (system timer) clears on a write, so it is only read;
* `RBR` (UART) pops the receiver on a read, but the receiver is empty at idle,
  so the read returns zero and `LSR.DR` stays clear;
* `SS_CONFIG` (reset unit) is plain read-write, so it is its own probe and its
  write carries back the value it held.

`uart_16550_main_wo` is left out: its only external register is `THR`, which
transmits whatever is written to it, so there is no access to it that leaves
the block as it was.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_cpuif_handshake_test_seq import _PROBES
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import LSR_DR, uart_reg
from .smc_rdl_regmap import rdl_contract

# (block, external register path, what its read must return). `None` means the
# value is not predicted and only the group's probe accesses are held to it.
_ZERO = 0
_RESET = "reset"
_EXTERNAL: tuple[tuple[str, str, object], ...] = (
    ("avsbus_controller", "smc_avsbus_controller/AVS_CMD", _ZERO),
    ("i2c", "smc_i2c_wrap/i2c/FDATA", _ZERO),
    ("cpu_ctrl", "smc_cpu_ctrl/RESET_CTRL", _RESET),
    ("system_timer_octs", "smc_system_timer_octs/CREDIT_EXPIRED", None),
    ("uart_16550_main", "smc_uart_wrap/uart_log_engine_wrap/uart/RBR", _ZERO),
    ("reset_unit", "smc_reset_unit/SS_CONFIG", None),
)


def _item(
    label: str,
    op: SmcSysAxiOp,
    addr: int,
    width: int,
    *,
    wdata: int = 0,
    expected: int | None = None,
) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"{op.value}_{label}")
    item.op = op
    item.addr = addr
    item.length = width
    item.wdata = wdata
    item.expected = expected
    return item


class smc_cpuif_external_stall_test_seq(SmcCsrSeq):
    """Present requests while each block's external register is pending."""

    def __init__(self, name: str = "smc_cpuif_external_stall_test_seq") -> None:
        super().__init__(name)
        self.blocks = 0

    async def _block(self, block: str, ext_path: str, expect: object, probe_path: str) -> None:
        ext = rdl_contract(ext_path)
        probe = rdl_contract(probe_path)
        if expect == _RESET:
            ext_expected: int | None = ext.reset_word & ((1 << (ext.width_bytes * 8)) - 1)
        else:
            ext_expected = expect  # type: ignore[assignment]

        held = await self.csr_read(f"{block}_PROBE_HELD", probe.addr, length=probe.width_bytes)
        members = [
            _item(
                f"{block}_ext0", SmcSysAxiOp.READ, ext.addr, ext.width_bytes, expected=ext_expected
            ),
            _item(
                f"{block}_probe_rd", SmcSysAxiOp.READ, probe.addr, probe.width_bytes, expected=held
            ),
            _item(
                f"{block}_probe_wr", SmcSysAxiOp.WRITE, probe.addr, probe.width_bytes, wdata=held
            ),
            _item(
                f"{block}_ext1", SmcSysAxiOp.READ, ext.addr, ext.width_bytes, expected=ext_expected
            ),
            _item(
                f"{block}_probe_rd2", SmcSysAxiOp.READ, probe.addr, probe.width_bytes, expected=held
            ),
        ]
        group = SmcSysAxiGroupItem(f"{block}_external_stall", members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)

        for member in members:
            assert member.resp_ok, (
                f"{block}: {member.get_name()} was not answered OKAY after the stall "
                f"that held it back lifted"
            )
            if member.expected is not None and member.op is SmcSysAxiOp.READ:
                got = member.rdata & ((1 << (member.length * 8)) - 1)
                assert got == member.expected, (
                    f"{block}: {member.get_name()} returned 0x{got:x}, 0x{member.expected:x} "
                    f"was expected"
                )

        after = await self.csr_read(
            f"{block}_PROBE_AFTER", probe.addr, length=probe.width_bytes, expected=held
        )
        assert after == held, (
            f"{block}: the probe read 0x{held:x} before the stalled group and 0x{after:x} "
            f"after it; its write carried back the value it held"
        )
        self.blocks += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        probes = dict(_PROBES)
        assert all(block in probes for block, _p, _e in _EXTERNAL), (
            "a block in the external-stall set has no probe"
        )

        for block, ext_path, expect in _EXTERNAL:
            await self._block(block, ext_path, expect, probes[block])

        # The UART reads popped nothing: the receiver was empty and still is.
        lsr = await self.csr_read("UART_LSR_AFTER_STALL", uart_reg(0, "LSR"))
        assert lsr & LSR_DR == 0, (
            f"LSR reads 0x{lsr:x} with DR set after RBR was read at idle; the receiver was "
            f"empty, so the reads could not have left data behind"
        )

        assert self.blocks == len(_EXTERNAL), f"{self.blocks} of {len(_EXTERNAL)} blocks driven"
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        cocotb.log.info(
            "CHK-CPUIF-EXTERNAL-STALL: on %d register blocks an access to the external "
            "register was followed at once by a read and a write of the block's probe, "
            "both presented while the external access was still pending; every request "
            "the stall held back was answered once it lifted, the probe read returned the "
            "value the block held, each external read returned what its contract gives "
            "it, and the probe held its value afterwards",
            self.blocks,
        )
