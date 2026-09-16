# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove whether SMC register windows alias unmapped offsets onto live CSRs.

Golden legality is PeakRDL ``SIZE`` / ``TOTAL_SIZE`` read by symbol from
``smc_addr.h`` (``_block_extent`` + ``DeadspaceProbe.__post_init__``), never
the xbar window and never a hand-copied literal.
A dead write that wraps onto a live register is the defect under test.

SCOPE -- OKAY-into-void: a write into unmapped space that returns OKAY and
leaves the live register alone is tallied as ACCEPTED and is OUT
OF SCOPE for eight of the nine probes; only ``i2c0_intr_enable`` carries
``expect_refuse`` and asserts on it, because the i2c_wrap SIZE range-check is a
decode contract this testcase can hold the DUT to. For the other eight no
authority establishes that the SMC xbar must DECERR an unmapped offset rather
than silently accept it, so ``accepted=N`` in the summary is a reported tally
and not a verdict. Deciding that contract for the whole map is not this
testcase's job.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
PAYLOAD = 0xA5A5A5A5
PAYLOAD_ZERO = 0x00000000
# Non-zero seed written into every live CSR before the dead access, so the
# read-alias compare is discriminating (a dead read of 0 cannot look
# like the live value) and so the wrap compare starts from a value the probe
# itself established. Chosen to differ from BOTH dead payloads, which is what
# makes the PAYLOAD/PAYLOAD_ZERO collision case impossible by construction.
SEED_SENTINEL = 0x5A5A5A5A
SEED_SENTINEL_ALT = 0x3C3C3C3C
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}


def _smc_def(symbol: str) -> int:
    """Plain ``#define`` value from the generated ``smc_addr.h``."""
    return smc_addr(symbol)


def _block_extent(prefix: str, *, indexed: bool) -> int:
    """Mapped extent of a generated block region, from smc_addr.h only.

    Prefers ``_TOTAL_SIZE``; for an indexed array without one, computes
    ``NUM * stride`` from the generated ``_NUM`` define and the stride encoded
    in the ``_BASE_ADDR(idx)`` macro; otherwise ``_SIZE``. Nothing here is
    hand-copied, so a PeakRDL regeneration that grows a block moves the
    deadness predicate with it instead of silently turning a "deadspace" probe
    into a probe of a mapped register.
    """
    try:
        return _smc_def(f"{prefix}_TOTAL_SIZE")
    except KeyError:
        pass
    if indexed:
        num = _smc_def(f"{prefix}_NUM")
        base0 = smc_indexed_addr(f"{prefix}_BASE_ADDR", 0)
        base1 = smc_indexed_addr(f"{prefix}_BASE_ADDR", 1)
        return num * (base1 - base0)
    return _smc_def(f"{prefix}_SIZE")


@dataclass(frozen=True)
class DeadspaceProbe:
    """One wrap candidate: ``dead_addr = live_addr + wrap_period``.

    ``block_base`` / ``block_extent`` come from the generated map and make the
    deadness predicate checkable: ``__post_init__`` asserts that ``live_addr``
    is inside the block and ``dead_addr`` is past its mapped extent, so a
    regenerated map that maps the offset fails the probe DEFINITION instead of
    silently changing what is being probed ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
    """

    name: str
    live_addr: int
    wrap_period: int
    block_base: int
    block_extent: int
    # I2C wrap range-checks SIZE; this probe should REFUSE if that decode holds.
    expect_refuse: bool = False

    def __post_init__(self) -> None:
        end = self.block_base + self.block_extent
        assert self.block_base <= self.live_addr < end, (
            f"{self.name}: live 0x{self.live_addr:08x} is not inside its "
            f"block [0x{self.block_base:08x}, 0x{end:08x}) from the generated "
            f"map -- the probe definition is wrong, not the DUT"
        )
        assert self.dead_addr >= end, (
            f"{self.name}: dead 0x{self.dead_addr:08x} = live + "
            f"0x{self.wrap_period:x} is INSIDE the block's mapped extent "
            f"[0x{self.block_base:08x}, 0x{end:08x}) from the generated map, "
            f"so it is not deadspace at all -- regenerate or re-pick the "
            f"wrap period"
        )

    @property
    def dead_addr(self) -> int:
        return self.live_addr + self.wrap_period


def _probes() -> tuple[DeadspaceProbe, ...]:
    return (
        DeadspaceProbe(
            "system_timer_preset_lo",
            smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR"),
            0x40,
            _smc_def("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_SYSTEM_TIMER_OCTS", indexed=False),
        ),
        DeadspaceProbe(
            "reset_unit_sync",
            smc_addr("SMC_TOP_SMC_RESET_UNIT_SYNC_REG_BASE_ADDR"),
            0x100,
            _smc_def("SMC_TOP_SMC_RESET_UNIT_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_RESET_UNIT", indexed=False),
        ),
        DeadspaceProbe(
            "base_config_hang_det_timeout",
            smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"),
            0x80,
            _smc_def("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_BASE_CONFIG", indexed=False),
        ),
        DeadspaceProbe(
            "outbound_filter0_start",
            smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0),
            0x200,
            smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR", 0),
            _block_extent("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL", indexed=True),
        ),
        DeadspaceProbe(
            "alias_remap0_region_end",
            smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR", 0),
            0x100,
            smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_BASE_ADDR", 0),
            _block_extent("SMC_TOP_SMC_ALIAS_REMAP_REGION", indexed=True),
        ),
        DeadspaceProbe(
            "dfx_debug_ctrl",
            smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR"),
            0x20,
            _smc_def("SMC_TOP_DFX_CTRL_BASE_ADDR"),
            _block_extent("SMC_TOP_DFX_CTRL", indexed=False),
        ),
        DeadspaceProbe(
            "avsbus_cfg0",
            smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
            0x80,
            _smc_def("SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_AVSBUS_CONTROLLER", indexed=False),
        ),
        DeadspaceProbe(
            "zeroer_dest",
            smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR"),
            0x20,
            _smc_def("SMC_TOP_ZEROER_CTRL_BASE_ADDR"),
            _block_extent("SMC_TOP_ZEROER_CTRL", indexed=False),
        ),
        # PeakRDL I2C instance SIZE is 0x84, STRIDE is 0x200. live+0x100 lands
        # in the SIZE-to-stride hole (not I2C1 at +0x200), so the extent used
        # here is the INSTANCE `_SIZE`, not the array `_TOTAL_SIZE`.
        # expect_refuse is the decode-window contract: OKAY-into-void and
        # wrap onto INTR_ENABLE both fail this probe.
        DeadspaceProbe(
            "i2c0_intr_enable",
            smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
            0x100,
            smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR", 0),
            _smc_def("SMC_TOP_SMC_I2C_WRAP_I2C_SIZE"),
            expect_refuse=True,
        ),
    )


class smc_deadspace_decode_test_seq(SmcCsrSeq):
    """Sweep wrap-period offsets past PeakRDL SIZE and watch live CSRs."""

    def __init__(self, name: str = "smc_deadspace_decode_test_seq") -> None:
        super().__init__(name)
        self.wrap_to_live: list[str] = []
        self.accepted_dead: list[str] = []
        self.refused: list[str] = []
        self.read_alias: list[str] = []
        # Probes whose live CSR did not accept the seed. Their NEGATIVE
        # conclusions ("no alias", "no live change") carry no proof, so they
        # are tracked separately instead of being counted as clean results.
        self.alias_not_checkable: list[str] = []
        self.change_not_proven: list[str] = []

    async def _xfer(
        self,
        name: str,
        op: SmcSysAxiOp,
        addr: int,
        data: int = 0,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(name)
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        item.allow_timeout = False
        item.timeout_ns = 2000
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        # Guard for a caller that sets `allow_timeout=True`. With
        # `allow_timeout = False` the driver raises from `_timed_event`
        # (env/smc_sys_axi_agent.py) before `item_done()`, so the sequence
        # never regains control with `timed_out` set and this path is not taken.
        assert not item.timed_out, (
            f"{name} @ 0x{addr:08x}: timed out (deadspace probe must complete)"
        )
        return item

    def _arm_monitor(self, probes: tuple[DeadspaceProbe, ...]) -> None:
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is None:
            return
        monitor.expected_decerr_addrs.update(p.dead_addr for p in probes)

    def _log_proof(self, kind: str, probe: DeadspaceProbe, **fields: object) -> None:
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        cocotb.log.info(
            "DEADSPACE %s: %s live=0x%08x dead=0x%08x period=0x%x %s",
            kind,
            probe.name,
            probe.live_addr,
            probe.dead_addr,
            probe.wrap_period,
            extra,
        )

    async def _seed_live(self, probe: DeadspaceProbe) -> tuple[int, int]:
        """Seed a known non-zero value into the live CSR and prove it took.

        Seeding serves two purposes:

        * the read-alias leg is gated on ``before != 0`` and an unseeded live
          CSR that happens to read 0 makes the compare non-discriminating -- a
          perfect read alias returns 0 exactly like a dead read
          ([NO-ALWAYS-PASS-CHECKER]);
        * the wrap verdict is ``after != before``, and without a same-run write
          to ``live_addr`` "the dead write did not change the live register" is
          indistinguishable from a register that cannot change at all
          ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).

        Writing a sentinel and reading it back establishes both at once: the
        seeded value is non-zero, differs from the original, and differs from
        both dead payloads, so the change detector is demonstrably sensitive
        before any negative conclusion is drawn.

        A live CSR that does NOT accept the seed is not silently tolerated and
        does not abort the sweep either: the probe keeps running (a POSITIVE
        wrap detection is self-proving -- the change WAS observed), but its
        negative conclusions are booked into ``alias_not_checkable`` /
        ``change_not_proven`` so the summary and the final assert distinguish
        "no alias found" from "alias not checkable".

        Returns ``(original, seeded, seed_ok)``. The caller restores
        ``original``.
        """
        live_rd = await self._xfer(f"{probe.name}_live_rd", SmcSysAxiOp.READ, probe.live_addr)
        assert live_rd.resp_code == AXI_RESP_OKAY, (
            f"{probe.name}: live CSR 0x{probe.live_addr:08x} resp="
            f"{_RESP_NAME.get(live_rd.resp_code)} (block is not awake)"
        )
        original = live_rd.rdata & 0xFFFFFFFF

        seed = SEED_SENTINEL if original != SEED_SENTINEL else SEED_SENTINEL_ALT
        seed_wr = await self._xfer(
            f"{probe.name}_seed_wr", SmcSysAxiOp.WRITE, probe.live_addr, seed
        )
        assert seed_wr.resp_code == AXI_RESP_OKAY, (
            f"{probe.name}: seeding live CSR 0x{probe.live_addr:08x} with "
            f"0x{seed:08x} returned {_RESP_NAME.get(seed_wr.resp_code)}"
        )
        seed_rd = await self._xfer(f"{probe.name}_seed_rd", SmcSysAxiOp.READ, probe.live_addr)
        assert seed_rd.resp_code == AXI_RESP_OKAY, (
            f"{probe.name}: seeded readback of 0x{probe.live_addr:08x} resp="
            f"{_RESP_NAME.get(seed_rd.resp_code)}"
        )
        seeded = seed_rd.rdata & 0xFFFFFFFF

        seed_ok = seeded != original and seeded != 0
        # A seed that landed must not collide with a dead payload, or a wrap
        # that wrote that payload would look like "no change".
        assert not (seed_ok and seeded in (PAYLOAD, PAYLOAD_ZERO)), (
            f"{probe.name}: seeded value 0x{seeded:08x} collides with a dead "
            f"payload, so a wrap that wrote it would look like 'no change'"
        )
        if seed_ok:
            self._log_proof(
                "SEEDED",
                probe,
                original=f"0x{original:08x}",
                wrote=f"0x{seed:08x}",
                seeded=f"0x{seeded:08x}",
            )
        else:
            cocotb.log.error(
                "DEADSPACE SEED-REFUSED: %s live=0x%08x wrote=0x%08x readback "
                "0x%08x (unchanged from 0x%08x). The change detector this "
                "probe relies on was NOT shown to be sensitive, so any "
                "negative conclusion from it is unproven; the probe needs a "
                "writable observable in this block.",
                probe.name,
                probe.live_addr,
                seed,
                seeded,
                original,
            )
        return original, seeded, seed_ok

    async def _restore_live(self, probe: DeadspaceProbe, original: int) -> None:
        restore = await self._xfer(
            f"{probe.name}_restore", SmcSysAxiOp.WRITE, probe.live_addr, original
        )
        assert restore.resp_code == AXI_RESP_OKAY, (
            f"{probe.name}: failed to restore live CSR 0x{probe.live_addr:08x} "
            f"to 0x{original:08x} (resp {_RESP_NAME.get(restore.resp_code)})"
        )

    async def _probe_one(self, probe: DeadspaceProbe) -> None:
        original, before, seed_ok = await self._seed_live(probe)
        try:
            await self._probe_after_seed(probe, before, seed_ok)
        finally:
            await self._restore_live(probe, original)

    async def _probe_after_seed(self, probe: DeadspaceProbe, before: int, seed_ok: bool) -> None:
        dead_rd = await self._xfer(f"{probe.name}_dead_rd", SmcSysAxiOp.READ, probe.dead_addr)
        if (
            dead_rd.resp_code == AXI_RESP_OKAY
            and (dead_rd.rdata & 0xFFFFFFFF) == before
            and before != 0
        ):
            proof = (
                f"{probe.name} dead 0x{probe.dead_addr:08x} read 0x{before:08x} "
                f"matching live 0x{probe.live_addr:08x} (resp OKAY)"
            )
            self.read_alias.append(proof)
            self._log_proof("READ-ALIAS", probe, rdata=f"0x{before:08x}")
        elif before == 0:
            # The alias compare is gated on `before != 0` (unmapped
            # reads commonly return 0, so dead == live == 0 is not evidence).
            # Seeding is what normally makes `before` non-zero; when the live
            # CSR refused the seed and still reads 0, a perfect read alias
            # would return 0 exactly like a dead read, so this probe's "no
            # alias" is not a result -- it is an unchecked leg, and it is
            # booked as one rather than counted clean.
            self.alias_not_checkable.append(
                f"{probe.name} dead 0x{probe.dead_addr:08x}: live "
                f"0x{probe.live_addr:08x} still reads 0 (seed_ok={seed_ok}), "
                f"so the alias compare had no discriminating value"
            )
            self._log_proof("ALIAS-NOT-CHECKABLE", probe, before=f"0x{before:08x}")

        # The second payload exists for the collision case: if the live CSR
        # already held the first payload, `after == before` even though the
        # dead write wrapped through. `_seed_live` requires the seeded `before`
        # to equal neither payload, so that collision is impossible by
        # construction and the OKAY path's early return cannot hide it.
        # PAYLOAD_ZERO is therefore only the second attempt on the refused
        # path.
        for payload in (PAYLOAD, PAYLOAD_ZERO):
            dead_wr = await self._xfer(
                f"{probe.name}_dead_wr_{payload:08x}",
                SmcSysAxiOp.WRITE,
                probe.dead_addr,
                payload,
            )
            wr_resp = _RESP_NAME.get(dead_wr.resp_code)
            after_rd = await self._xfer(
                f"{probe.name}_live_after_{payload:08x}",
                SmcSysAxiOp.READ,
                probe.live_addr,
            )
            after = after_rd.rdata & 0xFFFFFFFF
            if after != before:
                proof = (
                    f"{probe.name} dead 0x{probe.dead_addr:08x} wrote "
                    f"0x{payload:08x} resp={wr_resp} and CHANGED live "
                    f"0x{probe.live_addr:08x}: 0x{before:08x} -> 0x{after:08x}"
                )
                self.wrap_to_live.append(proof)
                self._log_proof(
                    "WRAP-TO-LIVE",
                    probe,
                    payload=f"0x{payload:08x}",
                    wr_resp=wr_resp,
                    before=f"0x{before:08x}",
                    after=f"0x{after:08x}",
                )
                # `_probe_one` restores the pre-seed value in its `finally`.
                return
            if dead_wr.resp_code == AXI_RESP_OKAY:
                proof = (
                    f"{probe.name} dead 0x{probe.dead_addr:08x} wrote "
                    f"0x{payload:08x} resp=OKAY (no live change)"
                )
                self.accepted_dead.append(proof)
                self._log_proof("ACCEPTED", probe, payload=f"0x{payload:08x}", wr_resp=wr_resp)
                self._book_unproven_negative(probe, "ACCEPTED", seed_ok)
                return
            if payload == PAYLOAD_ZERO:
                proof = f"{probe.name} dead 0x{probe.dead_addr:08x} resp={wr_resp} (no live change)"
                self.refused.append(proof)
                self._log_proof("REFUSED", probe, wr_resp=wr_resp)
                self._book_unproven_negative(probe, "REFUSED", seed_ok)

    def _book_unproven_negative(self, probe: DeadspaceProbe, kind: str, seed_ok: bool) -> None:
        """Record a "no live change" verdict taken without a positive control.

        ACCEPTED and REFUSED both rest on ``after == before``. That negative is
        only meaningful once the same run has shown a write to ``live_addr``
        does change what the checker watches; when the seed was refused it has
        not ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        """
        if seed_ok:
            return
        self.change_not_proven.append(
            f"{probe.name} classified {kind} from 'live 0x{probe.live_addr:08x} "
            f"did not change', but that live CSR refused this run's seed, so "
            f"the change detector was never shown to detect a change"
        )
        self._log_proof("CHANGE-NOT-PROVEN", probe, verdict=kind)

    async def body(self) -> None:
        probes = _probes()
        self._arm_monitor(probes)
        await self.wait_fuse_sense_done()

        # Bystander check: a CSR none of the probes touches must be byte-identical
        # after a sweep that writes 0xA5A5A5A5 into nine unmapped
        # windows. The baseline is captured and passed as `expected=` to the
        # recovery read, so the scoreboard's exact compare FAILS on collateral
        # damage instead of the pair being two discarded reads.
        sentinel = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
        sentinel_baseline = await self.csr_read("ALIVE_SENTINEL_BASELINE", sentinel)

        for probe in probes:
            await self._probe_one(probe)

        sentinel_recovery = await self.csr_read(
            "ALIVE_SENTINEL_RECOVERY", sentinel, expected=sentinel_baseline
        )
        assert sentinel_recovery == sentinel_baseline, (
            f"bystander CLOCK_GATE_CONTROL@0x{sentinel:08x} changed across the "
            f"deadspace sweep: 0x{sentinel_baseline:08x} -> "
            f"0x{sentinel_recovery:08x}"
        )
        cocotb.log.info(
            "DEADSPACE BYSTANDER: CLOCK_GATE_CONTROL@0x%08x unchanged across "
            "the sweep (0x%08x == 0x%08x)",
            sentinel,
            sentinel_baseline,
            sentinel_recovery,
        )

        # The summary distinguishes "no alias found" from "alias not
        # checkable": `alias_checked` is the denominator the read_alias count
        # is a numerator of, so `read_alias=0` cannot read as "0 of 9
        # alias" when some probes were never testable.
        alias_checked = len(probes) - len(self.alias_not_checkable)
        cocotb.log.info(
            "DEADSPACE SUMMARY: wrap_to_live=%d read_alias=%d of %d checkable "
            "probe(s) accepted=%d refused=%d alias_not_checkable=%d "
            "change_not_proven=%d",
            len(self.wrap_to_live),
            len(self.read_alias),
            alias_checked,
            len(self.accepted_dead),
            len(self.refused),
            len(self.alias_not_checkable),
            len(self.change_not_proven),
        )
        for line in self.wrap_to_live:
            cocotb.log.error("DEADSPACE PROOF WRAP-TO-LIVE: %s", line)
        for line in self.read_alias:
            cocotb.log.error("DEADSPACE PROOF READ-ALIAS: %s", line)
        for line in self.alias_not_checkable:
            cocotb.log.error("DEADSPACE ALIAS-NOT-CHECKABLE: %s", line)
        for line in self.change_not_proven:
            cocotb.log.error("DEADSPACE CHANGE-NOT-PROVEN: %s", line)

        i2c = next(p for p in probes if p.expect_refuse)
        i2c_refused = any(i2c.name in row for row in self.refused)
        i2c_wrapped = any(i2c.name in row for row in self.wrap_to_live)
        i2c_accepted = any(i2c.name in row for row in self.accepted_dead)
        if i2c_wrapped:
            cocotb.log.error("DEADSPACE I2C wrap still aliases; i2c_wrap SIZE check did not hold")
        elif i2c_refused:
            cocotb.log.info(
                "DEADSPACE I2C: 0x%08x refused (i2c_wrap range-check held)",
                i2c.dead_addr,
            )

        # Two ways for this testcase to fail, in one gate so the leading cause
        # stays the aliasing evidence:
        #   1. aliasing was FOUND (the defect under test), or
        #   2. a probe reached a NEGATIVE conclusion its own run could not
        #      support, because the live CSR refused this run's seed -- a
        #      "clean" result there would be an unchecked leg presented as a
        #      pass.
        assert (
            not self.wrap_to_live
            and not self.read_alias
            and not self.alias_not_checkable
            and not self.change_not_proven
        ), (
            "SMC deadspace aliased live registers "
            f"(wrap_to_live={len(self.wrap_to_live)} "
            f"read_alias={len(self.read_alias)}) "
            f"or could not check for aliasing "
            f"(alias_not_checkable={len(self.alias_not_checkable)} "
            f"change_not_proven={len(self.change_not_proven)}): "
            + " | ".join(
                self.wrap_to_live
                + self.read_alias
                + self.alias_not_checkable
                + self.change_not_proven
            )
        )
        assert i2c_refused and not i2c_accepted and not i2c_wrapped, (
            "SMC deadspace expect_refuse probe did not refuse "
            f"(refused={i2c_refused} accepted={i2c_accepted} wrapped={i2c_wrapped})"
        )
