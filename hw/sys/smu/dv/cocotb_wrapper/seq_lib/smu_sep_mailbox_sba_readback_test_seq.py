# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""WIRQT write-readback of the sixteen SEP mailbox ports from the SEP debug system bus.

Contract: SMU_MISC_COMPOSITION_010, anchor smu_sep_mailbox_sba_readback_test.
Spec: hw/sys/sep/doc/mailbox.adoc:28-30 (FIFOs of eight 64-bit entries), axil_mailbox.rdl
(WIRQT.wirqt[7:0] at 0x20, sw=rw, reset 0), axil_mailbox_sep_wrap.rdl, hw/sys/sep/regs/sep.rdl:127.

S1 is S0..S3 of ``smu_dtp_sep_dm_dmi_test`` (reused). S2: for each mailbox m in 0..7, WIRQT of
outbound_mailbox_m and inbound_mailbox_m reads 0 (reset value), takes V_m = 1 + (m % 7), a value
below the FIFO depth of eight, and reads V_m back over the system bus (RISC-V Debug
Specification 0.13) with sberror 0; WIRQT is then written back to 0. S3: every bounded wait
records its bound, the observed worst case and its last state.
"""

from __future__ import annotations

import time

from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_dtp_sep_dm_sba_test_seq import DMI_RETRIES, SBA_POLLS, SBCS_ADDR
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import smu_sep_sba_fabric_sweep_test_seq
from seq_lib.smu_sep_sba_peripheral_test_seq import (
    MBOX_WIRQT,
    NUM_MAILBOXES,
    _sep,
)

WIRQT_RESET = 0
SIZE_32 = 2
SITES = ("sba_sbbusy_poll", "dmi_busy_retry")
ORDER = ("S1", "S2", "S3", "PASS")


def _port(kind: str, mbox: int) -> str:
    return f"{kind}_mailbox_{mbox}"


def _wirqt_addr(kind: str, mbox: int) -> int:
    return _sep(f"AXIL_MAILBOX_{kind.upper()}_MAILBOX_{mbox}_BASE_ADDR") + MBOX_WIRQT


def _threshold(mbox: int) -> int:
    return 1 + (mbox % 7)


class smu_sep_mailbox_sba_readback_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """Write and read back WIRQT of every SEP mailbox port over the debug system bus."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.accesses = 0
        self.stamps: dict[str, float] = {}
        self.done = False
        self._scans = 0
        self._sbcs_reads = 0
        self.sites = {
            "sba_sbbusy_poll": {
                "bound": SBA_POLLS,
                "count": 0,
                "worst": 0,
                "last": "none",
                "expired": 0,
            },
            "dmi_busy_retry": {
                "bound": DMI_RETRIES,
                "count": 0,
                "worst": 0,
                "last": "none",
                "expired": 0,
            },
        }

    async def _dmi_scan(self, jtag, req: int) -> int:
        self._scans += 1
        return await super()._dmi_scan(jtag, req)

    async def _dmi(self, jtag, addr: int, data: int, op: int) -> int:
        site = self.sites["dmi_busy_retry"]
        before = self._scans
        if addr == SBCS_ADDR:
            self._sbcs_reads += 1
        try:
            value = await super()._dmi(jtag, addr, data, op)
        except AssertionError:
            site["expired"] += 1
            site["last"] = (
                f"addr=0x{addr:02x} op={op} still busy after {self._scans - before} scans"
            )
            raise
        retries = self._scans - before - 2
        site["count"] += 1
        site["worst"] = max(site["worst"], retries)
        site["last"] = f"addr=0x{addr:02x} op={op} retries={retries}"
        return value

    async def _sb(self, jtag, addr: int, size: int, data: int | None = None) -> tuple[int, int]:
        site = self.sites["sba_sbbusy_poll"]
        self.accesses += 1
        polls_before = self._sbcs_reads
        try:
            err, value = await super()._sb(jtag, addr, size, data)
        except AssertionError as exc:
            site["expired"] += 1
            site["last"] = f"0x{addr:08x} {exc}"
            raise
        polls = self._sbcs_reads - polls_before
        site["count"] += 1
        site["worst"] = max(site["worst"], polls)
        site["last"] = f"0x{addr:08x} sberror={err} sbcs_reads={polls}"
        return err, value

    async def _wirqt_read(self, jtag, addr: int) -> int:
        err, value = await self._sb(jtag, addr, SIZE_32)
        if err:
            raise AssertionError(f"system-bus read 0x{addr:08x}: sberror={err}")
        return value

    async def _readback(self, jtag, sb) -> None:
        observed, want = [], []
        ports = [(kind, m) for m in range(NUM_MAILBOXES) for kind in ("outbound", "inbound")]
        for kind, mbox in ports:
            addr = _wirqt_addr(kind, mbox)
            wrote = _threshold(mbox)
            reset = await self._wirqt_read(jtag, addr)
            await self._sb_ok(jtag, addr, SIZE_32, wrote)
            read = await self._wirqt_read(jtag, addr)
            self._log(
                f"CELL sep_wirqt_{kind}_{mbox} addr=0x{addr:08x} "
                f"reset={reset} wrote={wrote} read={read}"
            )
            observed.append((_port(kind, mbox), reset, wrote, read))
            want.append((_port(kind, mbox), WIRQT_RESET, wrote, wrote))
        for kind, mbox in ports:
            await self._sb_ok(jtag, _wirqt_addr(kind, mbox), SIZE_32, WIRQT_RESET)
        sb.expect_eq(
            "CHK-COMP-SEP-WIRQT-READBACK",
            observed,
            want,
            evidence="COMP_SEP_WIRQT_READBACK",
        )

    def _timeout_paths(self, sb) -> None:
        lines = []
        for name in SITES:
            rec = self.sites[name]
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{name}: bound={rec['bound']} worst={rec['worst']} {state} "
                f"count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"sba_accesses_counted={self.accesses} (counted at the call sites of this seq)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")

    def _stamp(self, step: str) -> None:
        self.stamps[step] = time.monotonic()
        self._log(f"STEP {step} t={self.stamps[step]:.3f}")

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        self._stamp("S1")
        await self._readback(jtag, sb)
        self._stamp("S2")
        self._timeout_paths(sb)
        self._stamp("S3")
        self._stamp("PASS")
        for a, b in zip(ORDER, ORDER[1:]):
            if self.stamps[a] >= self.stamps[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<PASS)")
        sb.expect_eq(
            "CHK-NONVAC ordered fence", list(self.stamps), list(ORDER), evidence="CHK-NONVAC"
        )
        self.done = True
