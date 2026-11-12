# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DEMOTE_1 is written only after the fuse-secret locks are set.

rom.adoc, Demotion Handling, ROM Behavior ([S25]):

    [SEP-ROM-DEM-035] The `DEMOTE_1` write shall be ordered after the fuse-secret read-locks
    of [S25]/[S26]: the demotion register is the last fuse state BL0 changes, so a fault
    while writing it cannot leave the secret fuses readable. Consequently anything that must
    *read* a secret shall run before the lock, not between the lock and the demotion write.

rom.adoc, Fuse-Secret Locking ([S25]/[S26]), which names the fuse-secret read-locks:

    [SEP-ROM-HOFF-030] Before hand-off the ROM shall set the SET-only read-locks in
    `SEP_EFUSE_MAP_LOCKS` for all six protected fuse fields — `CLASS_KEY`,
    `RMA_SIP_TOKEN_DIGEST`, `RMA_CHIPLET_TOKEN_DIGEST`, `CHIPLET_UID`, `SIP_UID` and
    `SYS_UID` — so no post-ROM software can read them, and shall then *independently
    re-read* the LOCKS register and confirm every lock bit is set ([S26]).

CHK-DEMOTE1-AFTER-LOCK grades the first clause of DEM-035 at the registers: the first clk
edge where the LOCKS shadow word holds all six read-lock bits is strictly earlier than the
first clk edge where DEMOTE_1 leaves its reset value. It does not grade "the last fuse state
BL0 changes" (logged as OBS-FUSE-SHADOW-AFTER-DEMOTE) nor the second sentence (no secret
read between the lock and the DEMOTE_1 write), and it does not order the write against the
[S26] re-read. HOFF-030 is graded by the fuse-lock leaves; here it only supplies the mask.

The leaf runs the O5 demotion member (DEMOTE_1 written (0, 1)) and keeps all of its checks.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import Edge, ReadOnly
from cocotb.utils import get_sim_time
from env.sep_chk_log import SepChkLog
from env.sep_rom_observer import SepRomObserver
from rom_fw.sep_firmware_demotion_decision_auth_flag_0_prod_test import (
    sep_firmware_demotion_decision_auth_flag_0_prod_test as _Base,
)
from sep_reg_meta import RegBlock, sym

_SHADOW = "efuse_shadow_probe_o"
# The probe holds OTP shadow word i at bits [32*i +: 32].
_LOCKS_SHIFT = 32 * (sym("SEP_EFUSE_MAP_LOCKS_REG_OFFSET") // 4)
_SECRET_FIELDS = (
    "CLASS_KEY",
    "RMA_SIP_TOKEN_DIGEST",
    "RMA_CHIPLET_TOKEN_DIGEST",
    "CHIPLET_UID",
    "SIP_UID",
    "SYS_UID",
)
_LOCKS_MASK = 0
for _name in _SECRET_FIELDS:
    _LOCKS_MASK |= 1 << RegBlock("SEP_EFUSE_MAP").field_lsb("LOCKS", f"{_name.lower()}_read_lock")
# DEMOTE_1 probes and their reset values: demote 0 on the {~d, d} rails, lock clear.
_DEMOTE_RESET = {"lcc_demote_state_1_probe_o": 0b10, "lcc_demote_lock_1_probe_o": 0}


def _first_leave(records: list[tuple[int, int]], reset: int) -> int | None:
    """Time of the first change away from reset, once the record has shown reset."""
    seen = False
    for t, v in records:
        if v == reset:
            seen = True
        elif seen:
            return t
    return None


@pyuvm.test()
class sep_rom_demote_after_lock_order_test(_Base):
    required_evidence = ("CHK-DEMOTE1-AFTER-LOCK",)

    async def _shadow_monitor(self) -> None:
        # A per-cycle read of the 8192-bit shadow costs too much wall time; it changes rarely.
        sig = getattr(cocotb.top, _SHADOW)
        self._shadow.append((int(get_sim_time("ps")), self.rd(sig, allow_unknown=True)))
        while True:
            await Edge(sig)
            await ReadOnly()
            v = self.rd(sig, allow_unknown=True)
            if v != self._shadow[-1][1]:
                self._shadow.append((int(get_sim_time("ps")), v))

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self._shadow: list[tuple[int, int]] = []
        shadow = cocotb.start_soon(self._shadow_monitor())
        obs = SepRomObserver(
            self, keep=lambda _insn: False, watch=tuple(_DEMOTE_RESET), tracker=False
        ).start()
        await super().run_scenario()
        await obs.stop()
        shadow.cancel()
        self._grade(obs)
        self.chk.finish()

    def _grade(self, obs: SepRomObserver) -> None:
        dut = cocotb.top
        chk = self.chk
        locks = [(t, (v >> _LOCKS_SHIFT) & _LOCKS_MASK) for t, v in self._shadow]
        cleared_t = next((t for t, w in locks if w == 0), None)
        locked_t = next(
            (
                t
                for t, w in locks
                if _LOCKS_MASK and cleared_t is not None and t > cleared_t and w == _LOCKS_MASK
            ),
            None,
        )
        locks_end = self.rd(getattr(dut, _SHADOW), _LOCKS_MASK << _LOCKS_SHIFT) >> _LOCKS_SHIFT
        chk.ctrl(
            "LOCKS-LIVE",
            bool(_LOCKS_MASK) and cleared_t is not None and locks_end == _LOCKS_MASK,
            mask=f"0x{_LOCKS_MASK:08x}",
            cleared_ps=cleared_t if cleared_t is not None else -1,
            locks_end=f"0x{locks_end:08x}",
            shadow_changes=len(self._shadow),
        )

        writes = {n: _first_leave(obs.watched[n], r) for n, r in _DEMOTE_RESET.items()}
        times = [t for t in writes.values() if t is not None]
        demote_t = min(times) if times else None
        end = tuple(self.rd(getattr(dut, n)) for n in _DEMOTE_RESET)
        chk.ctrl(
            "DEMOTE1-WRITTEN",
            demote_t is not None and end != tuple(_DEMOTE_RESET.values()),
            state_ps=writes["lcc_demote_state_1_probe_o"] or -1,
            lock_ps=writes["lcc_demote_lock_1_probe_o"] or -1,
            end_state=f"0b{end[0]:02b}",
            end_lock=end[1],
        )

        # A DEMOTE_1 change on the same clk edge as the lock is not "after" it.
        chk.ok(
            "DEMOTE1-AFTER-LOCK",
            locked_t is not None and demote_t is not None and locked_t < demote_t,
            locked_ps=locked_t if locked_t is not None else -1,
            demote_ps=demote_t if demote_t is not None else -1,
        )

        mret_t = obs.pre_mret[-1].t_ps if obs.pre_mret else None
        after = (
            [t for t, _ in self._shadow if demote_t < t <= mret_t]
            if demote_t is not None and mret_t is not None
            else []
        )
        chk.obs(
            "FUSE-SHADOW-AFTER-DEMOTE",
            changes=len(after),
            demote_ps=demote_t if demote_t is not None else -1,
            mret_ps=mret_t if mret_t is not None else -1,
        )
        chk.obs(
            "CONSOLE-ORDER",
            fuse_secrets_locked_ps=obs.line_t("FUSE_SECRETS_LOCKED") or -1,
            demote_locked_ps=obs.line_t("DEMOTE_LOCKED") or -1,
        )
