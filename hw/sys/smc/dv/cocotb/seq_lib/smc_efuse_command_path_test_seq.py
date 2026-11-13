# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The eFuse command path under `program_enable`, and a lock set while a program is in flight.

`hw/ip/efuse/doc/architecture.adoc` (Command-path ownership): after fuse sense, software
program and read requests share one command path to the OTP bank; `program_enable` takes that
path in preference to `read_enable`, so the two enables must be asserted exclusively, and a
read issued while `program_enable` is set does not reach the bank. (Hardware vs. Software
Locks): the guard checks the target of a program or read when it is started; a lock set after
a command has been issued does not affect that command.

`tb_efuse_shim_cmd_valid` is the command valid the interface controller presents to the SHIM,
sampled on every `clk_smc_i` rise; a read that reaches the bank raises it once. The eFuse
bank is the DV model, whose write response the bench can stall (`tb_efuse_bank_stall_wr`), so a
program stays in flight long enough for a `HARNESS_LOCKS` write to land during it.

`efuse_interface_ctrl.rdl` states `read_status` is set when `read_go` is asserted while the
read is not enabled or when the read request times out; `read_done` is set when the read has
completed. The leaf grades those words and reports what else the interface returned.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, with_timeout

from .smc_addr_map import smc_efuse_map_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_guard_target_test_seq import _bit_addr
from .smc_efuse_read_program_timeout_test_seq import (
    LOCKS_ADDR,
    PROG_BUSY,
    PROG_DATA,
    PROG_DONE,
    PROG_EN,
    PROG_ERR,
    PROG_GO,
    PROG_RB,
    PROGRAM_ADDR,
    PROGRAM_CTRL,
    READ_ADDR,
    READ_BUSY,
    READ_CTRL,
    READ_DATA,
    READ_DONE,
    READ_EN,
    READ_ERR,
    READ_GO,
    READ_TMO,
    REQ_ERR,
    REQ_ERR_CLR,
    STATUS,
    TMO_CYC_RST_R,
    TMO_EN_R,
)
from .smc_efuse_vip_utils import efuse_preload_word_at

#: The fuse word every read of this leaf targets: word 0 of the map, which the default image
#: holds non-zero and the guard never locks.
WORD0_BIT = 0
WORD0 = efuse_preload_word_at(LOCKS_ADDR)
#: The SPARE field programmed under a late write lock; no other leaf of a run touches it.
LOCK_FIELD = 2
LOCK_WORD_ADDR = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", LOCK_FIELD)
LOCK_WRITE = smc_efuse_map_u32(f"SMC_EFUSE_MAP__HARNESS_LOCKS__SPARE{LOCK_FIELD}_WRITE_LOCK_bm")
LOCK_BIT_IN_FLIGHT = 0
LOCK_BIT_REFUSED = 1
LOCKS_BYTES = 8
#: Read timeout for the read issued with both enables set, in cycles.
READ_TIMEOUT_CYCLES = 64
#: Bank write stall that keeps a program in flight across a HARNESS_LOCKS write.
PROGRAM_STALL_CYCLES = 512
#: Rises a watch of the SHIM command valid or a busy flag may take.
WATCH_BOUND = 4 * PROGRAM_STALL_CYCLES
#: Rises the read with both enables set is watched for before program_enable is cleared.
DEFERRED_WINDOW = 256
#: Register polls one operation may take to complete.
POLL_BOUND = 4096


def _read_cmd(enable: bool) -> int:
    return READ_GO | (READ_EN if enable else 0)


class _CmdWatch:
    """Count `tb_efuse_shim_cmd_valid` rises and busy-high samples every `clk_smc_i` rise."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.cmd_rises = 0
        self.read_busy_high = 0
        self.program_busy_high = 0

    def mark(self) -> tuple[int, int, int]:
        return self.cmd_rises, self.read_busy_high, self.program_busy_high

    def since(self, mark: tuple[int, int, int]) -> tuple[int, int, int]:
        return tuple(now - then for now, then in zip(self.mark(), mark))

    async def run(self) -> None:
        clk = self.dut.clk_smc_i
        prev = 0
        while not self.stop:
            await RisingEdge(clk)
            await ReadOnly()
            cmd = self.dut.tb_efuse_shim_cmd_valid.value
            rd = self.dut.tb_efuse_read_busy.value
            pr = self.dut.tb_efuse_program_busy.value
            assert cmd.is_resolvable and rd.is_resolvable and pr.is_resolvable, (
                f"eFuse taps unresolvable: cmd={cmd} read_busy={rd} program_busy={pr}"
            )
            if int(cmd) and not prev:
                self.cmd_rises += 1
            prev = int(cmd)
            self.read_busy_high += int(rd)
            self.program_busy_high += int(pr)


class smc_efuse_command_path_test_seq(SmcCsrSeq):
    """Grade a read under program_enable and a program locked after it was issued."""

    def __init__(self, name: str = "smc_efuse_command_path_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self.waits: list[str] = []

    def _chk(self, token: str, text: str) -> None:
        cocotb.log.info("%s: %s", token, text)
        self.chk_seen.add(token)

    async def _poll(self, label: str, addr: int, mask: int) -> tuple[int, int]:
        """Read `addr` until `mask` is set; returns (final word, polls taken)."""
        value = 0
        for polls in range(1, POLL_BOUND + 1):
            value = await self.csr_read(f"{label}_{polls}", addr)
            if value & mask:
                self.waits.append(f"{label}: 0x{mask:x} set after {polls} polls")
                return value, polls
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: 0x{mask:x} never set in {POLL_BOUND} polls (0x{value:08x})")

    async def _watch_until(self, label: str, watch: _CmdWatch, mark, want) -> int:
        """Advance until `want(watch.since(mark))` holds; returns the rises taken."""
        clk = cocotb.top.clk_smc_i
        for rises in range(1, WATCH_BOUND + 1):
            await RisingEdge(clk)
            if want(watch.since(mark)):
                self.waits.append(f"{label}: after {rises} rises")
                return rises
        raise AssertionError(
            f"{label}: not seen in {WATCH_BOUND} rises; since mark {watch.since(mark)}"
        )

    @staticmethod
    def _stall(wr: int) -> None:
        dut = cocotb.top
        dut.tb_efuse_bank_stall_rd.value = 0
        dut.tb_efuse_bank_stall_wr.value = wr
        dut.tb_efuse_bank_stall_en.value = int(wr != 0)

    async def _control_read(self, label: str, watch: _CmdWatch) -> tuple[int, int]:
        """A read with the path free: one SHIM command, no error, the preload word."""
        mark = watch.mark()
        await self.csr_write(f"{label}_ADDR", READ_ADDR, WORD0_BIT)
        await self.csr_write(f"{label}_GO", READ_CTRL, _read_cmd(True))
        ctrl, _ = await self._poll(f"{label}_DONE", READ_CTRL, READ_DONE)
        data = await self.csr_read(f"{label}_DATA", READ_DATA)
        await self.csr_write(f"{label}_IDLE", READ_CTRL, 0)
        cmds, _, _ = watch.since(mark)
        assert cmds == 1 and not ctrl & READ_ERR and data == WORD0, (
            f"{label}: read of word 0 with program_enable clear raised {cmds} SHIM commands, "
            f"READ_CTRL=0x{ctrl:08x}, READ_DATA=0x{data:08x} (preload 0x{WORD0:08x})"
        )
        return ctrl, data

    async def _read_under_program_enable(self, watch: _CmdWatch) -> None:
        await self._control_read("CONTROL_READ", watch)
        await self.csr_write("PROGRAM_ENABLE_ONLY", PROGRAM_CTRL, PROG_EN)
        await self.csr_read("PROGRAM_ENABLE_ONLY_RB", PROGRAM_CTRL, expected=PROG_EN)

        mark = watch.mark()
        await self.csr_write("EXCL_ADDR", READ_ADDR, WORD0_BIT)
        await self.csr_write("EXCL_GO", READ_CTRL, _read_cmd(False))
        excl = await self.csr_read("EXCL_FIRST", READ_CTRL)
        excl_data = await self.csr_read("EXCL_DATA", READ_DATA)
        await self.csr_write("EXCL_IDLE", READ_CTRL, 0)
        excl_cmds, excl_busy, _ = watch.since(mark)
        assert excl_cmds == 0 and excl_busy == 0, (
            f"read_go with program_enable set and read_enable clear: {excl_cmds} SHIM commands, "
            f"read_busy high on {excl_busy} samples"
        )
        assert excl & READ_DONE and excl & READ_ERR and excl_data == WORD0, (
            f"read_go with read_enable clear: first READ_CTRL read 0x{excl:08x} (done "
            f"{excl >> 25 & 1}, status {excl >> 26 & 1}), READ_DATA 0x{excl_data:08x} (was "
            f"0x{WORD0:08x})"
        )

        await self.csr_write("READ_TMO_SHORT", READ_TMO, TMO_EN_R | READ_TIMEOUT_CYCLES)
        mark = watch.mark()
        await self.csr_write("BOTH_ADDR", READ_ADDR, WORD0_BIT)
        await self.csr_write("BOTH_GO", READ_CTRL, _read_cmd(True))
        both_first = await self.csr_read("BOTH_FIRST", READ_CTRL)
        both, both_polls = await self._poll("BOTH_DONE", READ_CTRL, READ_DONE)
        both_data = await self.csr_read("BOTH_DATA", READ_DATA)
        await self.csr_write("BOTH_IDLE", READ_CTRL, 0)
        both_cmds, both_busy, _ = watch.since(mark)
        assert both_cmds == 0, (
            f"read_go with program_enable and read_enable set raised {both_cmds} SHIM commands"
        )
        assert both_first & READ_BUSY and both_busy >= 1, (
            f"the read with both enables set was not accepted: first READ_CTRL 0x{both_first:08x}, "
            f"read_busy high on {both_busy} samples"
        )
        assert both & READ_DONE and both & READ_ERR, (
            f"the read with both enables set ended with READ_CTRL=0x{both:08x} after "
            f"{both_polls} polls; the timeout of {READ_TIMEOUT_CYCLES} cycles sets read_status"
        )
        await self.csr_write("READ_TMO_RESTORE", READ_TMO, TMO_CYC_RST_R)

        mark = watch.mark()
        await self.csr_write("DEFER_ADDR", READ_ADDR, WORD0_BIT)
        await self.csr_write("DEFER_GO", READ_CTRL, _read_cmd(True))
        defer_first = await self.csr_read("DEFER_FIRST", READ_CTRL)
        await self._watch_until("DEFER_WINDOW", watch, mark, lambda d: d[1] >= DEFERRED_WINDOW)
        defer_cmds, defer_busy, _ = watch.since(mark)
        assert defer_cmds == 0 and defer_first & READ_BUSY, (
            f"read with both enables and no timeout: {defer_cmds} SHIM commands while "
            f"program_enable stayed set over {defer_busy} busy samples, first READ_CTRL "
            f"0x{defer_first:08x}"
        )
        mark2 = watch.mark()
        await self.csr_write("PROGRAM_ENABLE_CLR", PROGRAM_CTRL, 0)
        await self._watch_until("DEFER_ISSUE", watch, mark2, lambda d: d[0] >= 1)
        defer, _ = await self._poll("DEFER_DONE", READ_CTRL, READ_DONE)
        defer_data = await self.csr_read("DEFER_DATA", READ_DATA)
        await self.csr_write("DEFER_IDLE", READ_CTRL, 0)
        issued, _, _ = watch.since(mark2)
        assert issued == 1 and not defer & READ_ERR and defer_data == WORD0, (
            f"after program_enable cleared the held read issued {issued} SHIM commands, "
            f"READ_CTRL=0x{defer:08x}, READ_DATA=0x{defer_data:08x}"
        )
        self._chk(
            "CHK-EFUSE-READ-UNDER-PROGRAM-ENABLE",
            f"program_enable=1, no program go: read_go with read_enable=0 -> 0 SHIM commands, "
            f"0 busy samples, first READ_CTRL 0x{excl:08x} (done 1, status 1 at once), READ_DATA "
            f"unchanged 0x{excl_data:08x}; read_go with read_enable=1 and a "
            f"{READ_TIMEOUT_CYCLES}-cycle timeout -> 0 SHIM commands, accepted (first READ_CTRL "
            f"0x{both_first:08x}, busy {both_busy} samples), READ_CTRL 0x{both:08x} after "
            f"{both_polls} polls (done 1, status 1 by timeout), READ_DATA 0x{both_data:08x}; "
            f"read_go with read_enable=1 and no timeout -> 0 SHIM commands over {defer_busy} "
            f"busy samples, then {issued} command once program_enable cleared, READ_CTRL "
            f"0x{defer:08x}, READ_DATA 0x{defer_data:08x}; control read with the path free: 1 "
            f"command, 0x{WORD0:08x}",
        )

    async def _lock_after_issue(self, watch: _CmdWatch) -> None:
        locks = await self.csr_read("HARNESS_LOCKS_ENTRY", LOCKS_ADDR, length=LOCKS_BYTES)
        assert not locks & LOCK_WRITE, f"SPARE{LOCK_FIELD} write lock already set: 0x{locks:016x}"
        bit = _bit_addr(LOCK_WORD_ADDR, LOCK_BIT_IN_FLIGHT)
        self._stall(PROGRAM_STALL_CYCLES)
        mark = watch.mark()
        await self.csr_write("INFLIGHT_ADDR", PROGRAM_ADDR, bit)
        await self.csr_write("INFLIGHT_GO", PROGRAM_CTRL, PROG_DATA | PROG_GO | PROG_RB | PROG_EN)
        busy = await self.csr_read("INFLIGHT_BUSY", PROGRAM_CTRL)
        issued_before_lock = watch.since(mark)[0]
        assert busy & PROG_BUSY and issued_before_lock == 1, (
            f"the stalled program is not in flight before the lock: PROGRAM_CTRL=0x{busy:08x}, "
            f"{issued_before_lock} SHIM commands issued"
        )
        await self.csr_write("LOCK_LATE", LOCKS_ADDR, LOCK_WRITE, length=LOCKS_BYTES)
        locks = await self.csr_read("LOCK_LATE_RB", LOCKS_ADDR, length=LOCKS_BYTES)
        still_busy = await self.csr_read("INFLIGHT_STILL_BUSY", PROGRAM_CTRL)
        assert locks & LOCK_WRITE and still_busy & PROG_BUSY, (
            f"the lock did not land while the program was in flight: HARNESS_LOCKS=0x{locks:016x}, "
            f"PROGRAM_CTRL=0x{still_busy:08x}"
        )
        done, polls = await self._poll("INFLIGHT_DONE", PROGRAM_CTRL, PROG_DONE)
        status = await self.csr_read("INFLIGHT_STATUS", STATUS)
        await self.csr_write("INFLIGHT_IDLE", PROGRAM_CTRL, 0)
        self._stall(0)
        cmds, _, busy_high = watch.since(mark)
        assert cmds == 1 and not done & PROG_ERR and not status & REQ_ERR, (
            f"program issued before its write lock: {cmds} SHIM commands, PROGRAM_CTRL="
            f"0x{done:08x} after {polls} polls, STATUS=0x{status:08x}"
        )
        mark = watch.mark()
        await self.csr_write("BURNT_ADDR", READ_ADDR, bit)
        await self.csr_write("BURNT_GO", READ_CTRL, READ_GO | READ_EN)
        await self._poll("BURNT_DONE", READ_CTRL, READ_DONE)
        burnt = await self.csr_read("BURNT_DATA", READ_DATA)
        await self.csr_write("BURNT_IDLE", READ_CTRL, 0)
        read_cmds, _, _ = watch.since(mark)
        assert read_cmds == 1 and burnt >> LOCK_BIT_IN_FLIGHT & 1, (
            f"SPARE{LOCK_FIELD} reads 0x{burnt:08x} after the program; bit {LOCK_BIT_IN_FLIGHT} "
            f"is not burnt ({read_cmds} read commands)"
        )

        refused_bit = _bit_addr(LOCK_WORD_ADDR, LOCK_BIT_REFUSED)
        mark = watch.mark()
        await self.csr_write("REFUSED_ADDR", PROGRAM_ADDR, refused_bit)
        await self.csr_write("REFUSED_GO", PROGRAM_CTRL, PROG_DATA | PROG_GO | PROG_RB | PROG_EN)
        refused, _ = await self._poll("REFUSED_DONE", PROGRAM_CTRL, PROG_DONE)
        refused_status = await self.csr_read("REFUSED_STATUS", STATUS)
        await self.csr_write("REFUSED_IDLE", PROGRAM_CTRL, 0)
        await self.csr_write("REQ_ERR_CLR", STATUS, REQ_ERR_CLR)
        await self.csr_write("REQ_ERR_CLR0", STATUS, 0)
        refused_cmds, _, _ = watch.since(mark)
        assert refused_cmds == 0 and refused & PROG_ERR and refused_status & REQ_ERR, (
            f"a program started after the lock: {refused_cmds} SHIM commands, PROGRAM_CTRL="
            f"0x{refused:08x}, STATUS=0x{refused_status:08x}"
        )
        self._chk(
            "CHK-EFUSE-LOCK-AFTER-ISSUE",
            f"SPARE{LOCK_FIELD} bit {LOCK_BIT_IN_FLIGHT} read-back program with the bank write "
            f"stalled {PROGRAM_STALL_CYCLES} cycles: busy with its SHIM command issued (PROGRAM_CTRL "
            f"0x{busy:08x}), HARNESS_LOCKS write lock 0x{LOCK_WRITE:x} landed while busy "
            f"(0x{still_busy:08x}), program completed "
            f"after {polls} polls with PROGRAM_CTRL 0x{done:08x} (status 0), STATUS 0x{status:08x} "
            f"(no req_error), 1 SHIM command, program_busy high on {busy_high} samples, the word "
            f"reads 0x{burnt:08x}; a program of bit {LOCK_BIT_REFUSED} started after the lock: "
            f"0 SHIM commands, PROGRAM_CTRL 0x{refused:08x}, STATUS 0x{refused_status:08x}",
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        watch = _CmdWatch(dut)
        task = cocotb.start_soon(watch.run())
        try:
            await self._read_under_program_enable(watch)
            await self._lock_after_issue(watch)
        finally:
            self._stall(0)
            watch.stop = True
            await with_timeout(task, 1_000, "ns")
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{self.accesses} SEP_IN accesses bounded by the AXI driver timeout; polls bounded "
            f"by {POLL_BOUND} reads and watches by {WATCH_BOUND} rises: " + "; ".join(self.waits),
        )
