# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register blocks accessed in the direction their contract does not define.

Each SMC register block decodes an address together with a direction. For a
read-only register the decode term is the address *and* a read; for a
write-only one it is the address *and* a write. The half of each term that
pairs the address with the other direction -- a write at a read-only register,
a read at a write-only one -- has never been driven, and neither has a read of
the few registers nobody reads at all.

This leaf drives those accesses, and holds each to the generated block's
contract. A write to a read-only register is answered OKAY and takes no effect;
a read of a write-only register is answered OKAY and returns zero, because the
register has no readable field to contribute. Both follow from the regblock
the RDL compiles to, and both are checked here rather than assumed:

* every write at a read-only register must be answered, and where the register
  holds still at idle and reading it has no side effect, it must read the same
  value before and after a write of the complement of that value, so a write
  that reached any field would show in every bit;
* every read of a write-only register must return zero;
* around each block's accesses the block's probe register -- the same plain or
  read-only register `smc_cpuif_handshake_test` uses -- must read the same
  value, so no wrong-direction write aliased onto something writable.

Some registers need care, and the card records each choice:

* `RDATA`, `ACQDATA` (I2C) and `AVS_READBACK` pop a FIFO when read, so they are
  written but not read back; the FIFO level registers of the same block are
  read either side instead and must not move.
* `TIMER_COUNT_LO` and `TIMER_COUNT_HI` run freely, so equality before and after
  would not mean anything; they rely on the probe guard.
* `LSR` and `MSR` clear their error bits and deltas on any read, so each is read
  once to settle those before the baseline the write is held against.
* `TARGET_NACK_COUNT` clears when read. At idle it holds zero, so the read that
  reaches its decode clears nothing, and it must read zero.
* `TARGET_ACK_CTRL` takes a write of zero at idle: its `NBYTES` write enable is
  held off by hardware and a zero on the write-only `NACK` is no NACK. The
  write carries nothing the register could take, so it is answered and read
  around but not counted among the writes shown to take no effect.

Three UART rows are not driven, because the UART's own address demux never
presents those accesses to the block the rows belong to. `uart_16550.sv`
routes every write at the THR and FCR addresses to the write-only block, so the
main block never sees a write at `RBR` or `IIR`, and it routes no read to the
write-only block at all, so that block never sees a read at `FCR`.
"""

from __future__ import annotations

import cocotb

from .smc_cpuif_handshake_test_seq import _PROBES
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_contract

_WRITE_RO = "write_ro"
_READ_WO = "read_wo"
_READ = "read"
_WRITE_ZERO = "write_zero"

# Checks after the access: the register read the same before and after; the
# register is not read back because reading it changes state; the register runs
# freely so equality means nothing.
_STABLE = "stable"
_SETTLE = "settle"
_NO_READ = "no_read"
_FREE = "free"

_TELEMETRY = "smc_telemetry_receiver_wrap/telemetry_receiver"
_I2C = "smc_i2c_wrap/i2c"
_AVS = "smc_avsbus_controller"

# (block, register path, action, check). Grouped by block so the probe guard
# brackets every block's accesses.
_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    ("telemetry_receiver", f"{_TELEMETRY}/STATUS", _WRITE_RO, _STABLE),
    ("telemetry_receiver", f"{_TELEMETRY}/TELEMETRY_PROBE_ID", _WRITE_RO, _STABLE),
    ("telemetry_receiver", f"{_TELEMETRY}/TELEMETRY_COUNTER_VLDS", _WRITE_RO, _STABLE),
    ("ndm_reset", "smc_misc_wrap/ndm_reset/NDMRESET_REQUEST", _WRITE_RO, _STABLE),
    ("chip_config", "smc_misc_wrap/chip_config/VERSION_LO", _WRITE_RO, _STABLE),
    ("chip_config", "smc_misc_wrap/chip_config/VERSION_HI", _WRITE_RO, _STABLE),
    ("chip_config", "smc_misc_wrap/chip_config/LC_STATE", _WRITE_RO, _STABLE),
    ("log_engine", "smc_uart_wrap/uart_log_engine_wrap/log_engine/INTR_TEST", _READ_WO, _STABLE),
    ("reset_unit", "smc_reset_unit/SS_RESET_COMPLETE", _WRITE_RO, _STABLE),
    ("reset_unit", "smc_reset_unit/ISOLATE_REQ_VIS", _WRITE_RO, _STABLE),
    ("system_timer_octs", "smc_system_timer_octs/STATUS", _WRITE_RO, _STABLE),
    ("system_timer_octs", "smc_system_timer_octs/TIMER_COUNT_LO", _WRITE_RO, _FREE),
    ("system_timer_octs", "smc_system_timer_octs/TIMER_COUNT_HI", _WRITE_RO, _FREE),
    ("avsbus_controller", f"{_AVS}/AVS_CMD", _READ_WO, _STABLE),
    ("avsbus_controller", f"{_AVS}/AVS_READBACK", _WRITE_RO, _NO_READ),
    ("avsbus_controller", f"{_AVS}/AVS_DEBUG_READBACK", _WRITE_RO, _STABLE),
    ("avsbus_controller", f"{_AVS}/AVS_LATEST_SLAVE_SUBFRAME", _WRITE_RO, _STABLE),
    ("avsbus_controller", f"{_AVS}/AVS_NORMAL_STATUS", _WRITE_RO, _STABLE),
    ("avsbus_controller", f"{_AVS}/AVS_SLAVE_STATUS", _WRITE_RO, _STABLE),
    ("avsbus_controller", f"{_AVS}/AVS_FIFOS_STATUS", _WRITE_RO, _STABLE),
    ("avsbus_controller", f"{_AVS}/AVS_INTERRUPT", _WRITE_RO, _STABLE),
    ("avsbus_controller", f"{_AVS}/AVS_INTERRUPT_CLEAR", _READ_WO, _STABLE),
    (
        "efuse_interface_ctrl",
        "efuse_interface_ctrl/EFUSE_PROGRAM_INTERFACE_READ_DATA",
        _WRITE_RO,
        _STABLE,
    ),
    (
        "efuse_interface_ctrl",
        "efuse_interface_ctrl/EFUSE_READ_INTERFACE_READ_DATA",
        _WRITE_RO,
        _STABLE,
    ),
    ("dfx_ctrl_status", "dfx_ctrl/STATUS_SMU", _WRITE_RO, _STABLE),
    ("i2c", f"{_I2C}/STATUS", _WRITE_RO, _STABLE),
    ("i2c", f"{_I2C}/RDATA", _WRITE_RO, _NO_READ),
    ("i2c", f"{_I2C}/FDATA", _READ_WO, _STABLE),
    ("i2c", f"{_I2C}/HOST_FIFO_STATUS", _WRITE_RO, _STABLE),
    ("i2c", f"{_I2C}/TARGET_FIFO_STATUS", _WRITE_RO, _STABLE),
    ("i2c", f"{_I2C}/VAL", _WRITE_RO, _STABLE),
    ("i2c", f"{_I2C}/ACQDATA", _WRITE_RO, _NO_READ),
    ("i2c", f"{_I2C}/TXDATA", _READ_WO, _STABLE),
    ("i2c", f"{_I2C}/ACQ_FIFO_NEXT_DATA", _WRITE_RO, _STABLE),
    ("i2c", f"{_I2C}/SMBUS_STATUS", _WRITE_RO, _STABLE),
    ("i2c", f"{_I2C}/TARGET_NACK_COUNT", _READ, _STABLE),
    ("i2c", f"{_I2C}/TARGET_ACK_CTRL", _WRITE_ZERO, _STABLE),
    ("i2c_ctrl", "smc_i2c_wrap/i2c_ctrl_regs/I2C_CTRL[2]", _READ, _STABLE),
    ("uart_16550_main", "smc_uart_wrap/uart_log_engine_wrap/uart/LSR", _WRITE_RO, _SETTLE),
    ("uart_16550_main", "smc_uart_wrap/uart_log_engine_wrap/uart/MSR", _WRITE_RO, _SETTLE),
)

# The FIFO level registers read either side of a write at a register whose read
# pops its FIFO.
_LEVEL_REGS = {
    f"{_I2C}/RDATA": f"{_I2C}/HOST_FIFO_STATUS",
    f"{_I2C}/ACQDATA": f"{_I2C}/TARGET_FIFO_STATUS",
    f"{_AVS}/AVS_READBACK": f"{_AVS}/AVS_FIFOS_STATUS",
}

# Word written where the register itself is not read back: a FIFO pop or a
# free-running count. A register that is read back takes the complement of
# what it held instead.
_WRITE_PATTERN = 0xFFFF_FFFF_FFFF_FFFF


class smc_cpuif_wrong_direction_test_seq(SmcCsrSeq):
    """Write read-only registers, read write-only ones, and read the unread."""

    def __init__(self, name: str = "smc_cpuif_wrong_direction_test_seq") -> None:
        super().__init__(name)
        self.writes_ignored = 0
        self.zero_writes = 0
        self.reads_zero = 0
        self.plain_reads = 0
        self.blocks_guarded = 0

    async def _read(self, label: str, path: str) -> int:
        reg = rdl_contract(path)
        return await self.csr_read(label, reg.addr, length=reg.width_bytes)

    async def _access(self, block: str, path: str, action: str, check: str) -> None:
        reg = rdl_contract(path)
        name = path.split("/")[-1]
        width = reg.width_bytes
        mask = (1 << (width * 8)) - 1

        if action == _READ_WO:
            assert all(f.access == "write-only" for f in reg.fields), (
                f"{block}: {name} is expected to be write-only in the contract"
            )
            got = await self.csr_read(f"{block}_{name}_RD_WO", reg.addr, length=width, expected=0)
            assert got == 0, (
                f"{block}: a read of the write-only {name} returned 0x{got:x}; it has no "
                f"readable field, so the read has to return zero"
            )
            self.reads_zero += 1
            return

        if action == _READ:
            got = await self.csr_read(f"{block}_{name}_RD", reg.addr, length=width)
            want = reg.reset_word & mask
            assert got == want, (
                f"{block}: {name} read 0x{got:x} at idle; its RDL reset is 0x{want:x}"
            )
            self.plain_reads += 1
            return

        level = _LEVEL_REGS.get(path)
        before = None
        if check == _SETTLE:
            # uart_16550_main.rdl clears the MSR deltas and the LSR error bits on
            # any read of their register, so the first read settles them and the
            # second is the baseline the write is held against.
            await self.csr_read(f"{block}_{name}_SETTLE", reg.addr, length=width)
        if check in (_STABLE, _SETTLE):
            before = await self.csr_read(f"{block}_{name}_BEFORE", reg.addr, length=width)
        elif check == _NO_READ:
            assert level is not None, f"{block}: {name} has no level register to watch"
            before = await self._read(f"{block}_{name}_LEVEL_BEFORE", level)

        if action == _WRITE_ZERO:
            data = 0
        elif check in (_STABLE, _SETTLE):
            data = ~before & mask
        else:
            data = _WRITE_PATTERN & mask
        await self.csr_write(f"{block}_{name}_WR", reg.addr, data, length=width)

        if check in (_STABLE, _SETTLE):
            after = await self.csr_read(f"{block}_{name}_AFTER", reg.addr, length=width)
            assert after == before, (
                f"{block}: {name} read 0x{before:x} before a write of 0x{data:x} and "
                f"0x{after:x} after it; the write reached no writable field, so the "
                f"register had to hold its value"
            )
        elif check == _NO_READ:
            after = await self._read(f"{block}_{name}_LEVEL_AFTER", level)
            assert after == before, (
                f"{block}: the FIFO level register read 0x{before:x} before a write at "
                f"{name} and 0x{after:x} after it; a write there reaches no writable "
                f"field, so the FIFO had to stay where it was"
            )
        if action == _WRITE_ZERO:
            self.zero_writes += 1
        else:
            self.writes_ignored += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        probes = dict(_PROBES)

        blocks: list[str] = []
        for block, *_rest in _TARGETS:
            if block not in blocks:
                blocks.append(block)
        assert all(block in probes for block in blocks), (
            f"these blocks have no probe to guard them: "
            f"{sorted(b for b in blocks if b not in probes)}"
        )

        for block in blocks:
            probe = probes[block]
            held = await self._read(f"{block}_PROBE_BEFORE", probe)
            for tgt_block, path, action, check in _TARGETS:
                if tgt_block == block:
                    await self._access(block, path, action, check)
            after = await self._read(f"{block}_PROBE_AFTER", probe)
            assert after == held, (
                f"{block}: the probe {probe.split('/')[-1]} read 0x{held:x} before the "
                f"block's wrong-direction accesses and 0x{after:x} after; one of them "
                f"reached a writable register"
            )
            self.blocks_guarded += 1

        total = self.writes_ignored + self.zero_writes + self.reads_zero + self.plain_reads
        assert total == len(_TARGETS), f"{total} of {len(_TARGETS)} accesses completed"
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        cocotb.log.info(
            "CHK-CPUIF-WRITE-READ-ONLY: %d writes at read-only registers across %d "
            "register blocks were answered and took no effect -- each register that holds "
            "still at idle read the same before and after a write of the complement of what "
            "it held, each FIFO whose data register pops on read kept its level -- and no "
            "block's probe register moved; the %d write of zero at TARGET_ACK_CTRL, which "
            "carries nothing its fields could take, was answered and is not among them",
            self.writes_ignored,
            self.blocks_guarded,
            self.zero_writes,
        )
        cocotb.log.info(
            "CHK-CPUIF-READ-WRITE-ONLY: %d reads of write-only registers were answered and "
            "returned zero, which is all a register with no readable field can return, and "
            "%d registers no leaf had read returned their RDL reset at idle",
            self.reads_zero,
            self.plain_reads,
        )
