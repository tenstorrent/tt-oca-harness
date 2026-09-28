# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove that SMC register windows refuse offsets past their decoded extent.

Golden legality is PeakRDL ``SIZE`` / ``TOTAL_SIZE`` read by symbol from
``smc_addr.h`` (``_block_extent`` + ``DeadspaceProbe.__post_init__``), never
the xbar window and never a hand-copied literal. The crossbars are sized from
the same generated parameters, so a regenerated map moves the decode and the
probe definitions together.

CONTRACT -- ``hw/sys/smc/doc/memmap.adoc``: the fabric refuses an address that
falls between unit apertures or past a unit's decoded extent; such an access
never reaches a unit. Every probe here therefore expects the dead read and both
dead writes to come back non-OKAY with the live register untouched. The three
ways the DUT fails this testcase are ranked by what they mean:

* WRAP-TO-LIVE -- a dead write changed the live register (the aliasing defect);
* READ-ALIAS -- a dead read returned the live register's seeded value with OKAY;
* ACCEPTED -- a dead access answered OKAY without reaching a register
  (OKAY-into-void), which the memmap contract forbids past the decoded extent.

The i2c probe lands in the SIZE-to-stride hole between two I2C instances, which
is inside the I2C_WRAP aperture the fabric decodes; there the refusal is the
i2c_wrap's own SIZE range-check, and this probe holds it to the same verdict.

Each live register is seeded with a value the generated field model says it
can hold before its dead offsets are touched, so "the live register did not
change" is drawn only after the change detector was shown to be sensitive.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL field model (hw/sys/smc/regs/gen/py/smc_reg.py): the
# per-register field layout the seed mask is read from.
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

import smc_reg  # noqa: E402

AXI_RESP_OKAY = 0
WORD_MASK = 0xFFFFFFFF
PAYLOAD = 0xA5A5A5A5
PAYLOAD_ZERO = 0x00000000
# Seed candidates, tried in order against the live register's field mask. A
# seed must raise at least one field bit the live register currently holds at
# 0: the PAYLOAD_ZERO dead write lowers every writable bit, so a wrap onto a
# register seeded that way is visible whatever PAYLOAD looks like under the
# mask. The two sentinels differ from both dead payloads on every bit position
# they share; `_pick_seed` falls back to the complement and the whole mask for
# registers too narrow to take either (a 1-bit field at bit 0 sees 0 from both).
SEED_CANDIDATES = (0x5A5A5A5A, 0x3C3C3C3C)
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


def _field_mask(reg_type: str) -> int:
    """Bits of a register's low word that the generated model declares as fields.

    ``smc_reg.py`` lays every register out as a ctypes bit-field struct from
    bit 0 upward, with ``rsvd*`` fillers for the gaps, so the implemented
    footprint of the register is the union of its named fields. Read from the
    model rather than guessed, so a seed never targets a bit the RDL does not
    implement.
    """
    struct = getattr(smc_reg, f"{reg_type}_reg_t")
    mask = 0
    lsb = 0
    for name, _ctype, width in struct._fields_:
        if not name.startswith("rsvd"):
            mask |= ((1 << width) - 1) << lsb
        lsb += width
    mask &= WORD_MASK
    assert mask, f"{reg_type}: the generated model declares no field in the low 32 bits"
    return mask


@dataclass(frozen=True)
class DeadspaceProbe:
    """One wrap candidate: ``dead_addr = live_addr + wrap_period``.

    ``block_base`` / ``block_extent`` come from the generated map and make the
    deadness predicate checkable: ``__post_init__`` asserts that ``live_addr``
    is inside the block and ``dead_addr`` is past its mapped extent, so a
    regenerated map that maps the offset fails the probe DEFINITION instead of
    silently changing what is being probed ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
    ``reg_type`` names the live register's type in the generated Python model;
    its field layout is the seed mask.
    """

    name: str
    live_addr: int
    wrap_period: int
    block_base: int
    block_extent: int
    reg_type: str

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
        _field_mask(self.reg_type)

    @property
    def dead_addr(self) -> int:
        return self.live_addr + self.wrap_period

    @property
    def field_mask(self) -> int:
        return _field_mask(self.reg_type)


def _probes() -> tuple[DeadspaceProbe, ...]:
    return (
        DeadspaceProbe(
            "system_timer_preset_lo",
            smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR"),
            0x40,
            _smc_def("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_SYSTEM_TIMER_OCTS", indexed=False),
            "SYSTEM_TIMER_OCTS_TIMER_PRESET_LO",
        ),
        DeadspaceProbe(
            "reset_unit_sync",
            smc_addr("SMC_TOP_SMC_RESET_UNIT_SYNC_REG_BASE_ADDR"),
            0x100,
            _smc_def("SMC_TOP_SMC_RESET_UNIT_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_RESET_UNIT", indexed=False),
            "RESET_UNIT_SYNC_REG",
        ),
        DeadspaceProbe(
            "base_config_hang_det_timeout",
            smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"),
            0x80,
            _smc_def("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_BASE_CONFIG", indexed=False),
            "SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD",
        ),
        DeadspaceProbe(
            "outbound_filter0_start",
            smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0),
            0x200,
            smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR", 0),
            _block_extent("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL", indexed=True),
            "FILTER_CTRL_START_ADDR",
        ),
        DeadspaceProbe(
            "alias_remap0_region_end",
            smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR", 0),
            0x100,
            smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_BASE_ADDR", 0),
            _block_extent("SMC_TOP_SMC_ALIAS_REMAP_REGION", indexed=True),
            "REMAP_REGION_REGION_END",
        ),
        DeadspaceProbe(
            "dfx_debug_ctrl",
            smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR"),
            0x20,
            _smc_def("SMC_TOP_DFX_CTRL_BASE_ADDR"),
            _block_extent("SMC_TOP_DFX_CTRL", indexed=False),
            "DFX_CTRL_STATUS_DEBUG_CTRL",
        ),
        DeadspaceProbe(
            "avsbus_cfg0",
            smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
            0x80,
            _smc_def("SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR"),
            _block_extent("SMC_TOP_SMC_AVSBUS_CONTROLLER", indexed=False),
            "AVSBUS_CONTROLLER_AVS_CFG_0",
        ),
        DeadspaceProbe(
            "zeroer_dest",
            smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR"),
            0x20,
            _smc_def("SMC_TOP_ZEROER_CTRL_BASE_ADDR"),
            _block_extent("SMC_TOP_ZEROER_CTRL", indexed=False),
            "ZEROER_CTRL_DEST_ADDR",
        ),
        # PeakRDL I2C instance SIZE is 0x84, STRIDE is 0x200. live+0x100 lands
        # in the SIZE-to-stride hole (not I2C1 at +0x200), so the extent used
        # here is the INSTANCE `_SIZE`, not the array `_TOTAL_SIZE`.
        DeadspaceProbe(
            "i2c0_intr_enable",
            smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
            0x100,
            smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR", 0),
            _smc_def("SMC_TOP_SMC_I2C_WRAP_I2C_SIZE"),
            "I2C_INTR_ENABLE",
        ),
    )


class smc_deadspace_decode_test_seq(SmcCsrSeq):
    """Sweep wrap-period offsets past PeakRDL SIZE and watch live CSRs."""

    def __init__(self, name: str = "smc_deadspace_decode_test_seq") -> None:
        super().__init__(name)
        self.wrap_to_live: list[str] = []
        self.accepted_dead: list[str] = []
        self.refused: list[str] = []
        self.read_refused: list[str] = []
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

    @staticmethod
    def _pick_seed(probe: DeadspaceProbe, original: int) -> int:
        """First candidate that raises a field bit the live register holds at 0.

        The sentinels come first; the complement of the current value and the
        whole field mask follow for registers too narrow to take either (a
        1-bit field at bit 0 sees 0 from both sentinels). Only field bits are
        written, so the seed never targets a bit the RDL does not implement.
        """
        mask = probe.field_mask
        for candidate in (*SEED_CANDIDATES, ~original, WORD_MASK):
            seed = candidate & mask
            if seed & ~original & mask:
                return seed
        raise AssertionError(
            f"{probe.name}: live 0x{probe.live_addr:08x} holds 0x{original:08x}, every "
            f"field bit of mask 0x{mask:08x} is already 1, so no seed can raise one"
        )

    async def _seed_live(self, probe: DeadspaceProbe) -> tuple[int, int, bool]:
        """Seed a known value into the live CSR and prove it took.

        Seeding serves two purposes:

        * the read-alias leg is gated on ``before != 0`` and an unseeded live
          CSR that happens to read 0 makes the compare non-discriminating -- a
          perfect read alias returns 0 exactly like a dead read
          ([NO-ALWAYS-PASS-CHECKER]);
        * the wrap verdict is ``after != before``, and without a same-run write
          to ``live_addr`` "the dead write did not change the live register" is
          indistinguishable from a register that cannot change at all
          ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).

        The seed is chosen from the register's generated field mask so that it
        raises at least one field bit currently at 0 (``_pick_seed``); the
        readback then proves the change detector is sensitive: a bit the seed
        raised is a bit the PAYLOAD_ZERO dead write would lower, so a wrap is
        visible on that leg whatever PAYLOAD looks like under the mask.

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
        original = live_rd.rdata & WORD_MASK

        seed = self._pick_seed(probe, original)
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
        seeded = seed_rd.rdata & WORD_MASK

        # The seed took if at least one bit rose. That implies `seeded` is
        # non-zero and differs from `original`, which is what the alias and
        # wrap compares below need.
        raised = seeded & ~original & WORD_MASK
        seed_ok = raised != 0
        if seed_ok:
            cocotb.log.info(
                "CHK-DEADSPACE-SEED: %s live=0x%08x original=0x%08x wrote=0x%08x "
                "seeded=0x%08x raised=0x%08x field_mask=0x%08x",
                probe.name,
                probe.live_addr,
                original,
                seed,
                seeded,
                raised,
                probe.field_mask,
            )
        else:
            cocotb.log.error(
                "DEADSPACE SEED-REFUSED: %s live=0x%08x wrote=0x%08x readback "
                "0x%08x (from 0x%08x, field_mask=0x%08x) raised no bit. The "
                "change detector this probe relies on was NOT shown to be "
                "sensitive, so any negative conclusion from it is unproven; the "
                "probe needs a writable observable in this block.",
                probe.name,
                probe.live_addr,
                seed,
                seeded,
                original,
                probe.field_mask,
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
        rd_resp = _RESP_NAME.get(dead_rd.resp_code)
        rdata = dead_rd.rdata & WORD_MASK
        if dead_rd.resp_code == AXI_RESP_OKAY and rdata == before and before != 0:
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
        elif dead_rd.resp_code == AXI_RESP_OKAY:
            # OKAY with a value other than the live one: the fabric answered an
            # address past the decoded extent, which the memmap contract
            # forbids. Not an alias, but not a refusal either.
            proof = (
                f"{probe.name} dead 0x{probe.dead_addr:08x} read resp=OKAY "
                f"rdata=0x{rdata:08x} (into void)"
            )
            self.accepted_dead.append(proof)
            self._log_proof("READ-ACCEPTED", probe, rdata=f"0x{rdata:08x}")
        else:
            self.read_refused.append(
                f"{probe.name} dead 0x{probe.dead_addr:08x} read resp={rd_resp}"
            )
            cocotb.log.info(
                "CHK-DEADSPACE-READ-REFUSED: %s dead=0x%08x resp=%s (live 0x%08x seeded "
                "0x%08x was not returned)",
                probe.name,
                probe.dead_addr,
                rd_resp,
                probe.live_addr,
                before,
            )

        # PAYLOAD first, PAYLOAD_ZERO second. `_pick_seed` made the seed raise
        # a field bit, so even a live register whose masked PAYLOAD equals the
        # seeded value cannot hide a wrap: the zero write lowers that bit.
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
            after = after_rd.rdata & WORD_MASK
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
                if seed_ok:
                    cocotb.log.info(
                        "CHK-DEADSPACE-WRITE-REFUSED: %s dead=0x%08x payloads=0x%08x,0x%08x "
                        "resp=%s live 0x%08x held 0x%08x",
                        probe.name,
                        probe.dead_addr,
                        PAYLOAD,
                        PAYLOAD_ZERO,
                        wr_resp,
                        probe.live_addr,
                        before,
                    )

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
            "CHK-DEADSPACE-BYSTANDER: CLOCK_GATE_CONTROL@0x%08x unchanged across "
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
            "probe(s) accepted=%d refused=%d read_refused=%d alias_not_checkable=%d "
            "change_not_proven=%d",
            len(self.wrap_to_live),
            len(self.read_alias),
            alias_checked,
            len(self.accepted_dead),
            len(self.refused),
            len(self.read_refused),
            len(self.alias_not_checkable),
            len(self.change_not_proven),
        )
        for line in self.wrap_to_live:
            cocotb.log.error("DEADSPACE PROOF WRAP-TO-LIVE: %s", line)
        for line in self.read_alias:
            cocotb.log.error("DEADSPACE PROOF READ-ALIAS: %s", line)
        for line in self.accepted_dead:
            cocotb.log.error("DEADSPACE PROOF ACCEPTED: %s", line)
        for line in self.alias_not_checkable:
            cocotb.log.error("DEADSPACE ALIAS-NOT-CHECKABLE: %s", line)
        for line in self.change_not_proven:
            cocotb.log.error("DEADSPACE CHANGE-NOT-PROVEN: %s", line)

        # Three ways for this testcase to fail, in one gate so the leading
        # cause stays the aliasing evidence:
        #   1. aliasing was FOUND (a dead write reached a live register, or a
        #      dead read returned one),
        #   2. a dead access was ACCEPTED with OKAY past the decoded extent,
        #      which memmap.adoc says the fabric must refuse, or
        #   3. a probe reached a NEGATIVE conclusion its own run could not
        #      support, because the live CSR refused this run's seed -- a
        #      "clean" result there would be an unchecked leg presented as a
        #      pass.
        assert (
            not self.wrap_to_live
            and not self.read_alias
            and not self.accepted_dead
            and not self.alias_not_checkable
            and not self.change_not_proven
        ), (
            "SMC deadspace aliased live registers "
            f"(wrap_to_live={len(self.wrap_to_live)} "
            f"read_alias={len(self.read_alias)}) "
            f"or accepted a dead access (accepted={len(self.accepted_dead)}) "
            f"or could not check for aliasing "
            f"(alias_not_checkable={len(self.alias_not_checkable)} "
            f"change_not_proven={len(self.change_not_proven)}): "
            + " | ".join(
                self.wrap_to_live
                + self.read_alias
                + self.accepted_dead
                + self.alias_not_checkable
                + self.change_not_proven
            )
        )
        # Every probe's dead read and both of its dead writes were refused.
        assert len(self.refused) == len(probes) and len(self.read_refused) == len(probes), (
            f"SMC deadspace refusal count short of the {len(probes)} probes "
            f"(write refused={len(self.refused)} read refused={len(self.read_refused)})"
        )
        cocotb.log.info(
            "CHK-DEADSPACE-SWEEP: %d probes, each dead read and both dead writes refused "
            "with the seeded live register unchanged; wrap_to_live=0 read_alias=0 accepted=0",
            len(probes),
        )
