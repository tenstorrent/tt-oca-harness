# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI Debug Module activation and sbcs geometry on every bridge.

While dmcontrol.dmactive is 0 it is the one Debug Module bit a write changes:
the System Bus Access registers hold their reset values and start no access.
A write of 0 to dmactive returns them to those values, and the read-only
geometry fields of sbcs keep the bridge's widths through every write.
"""

from __future__ import annotations

import random

from env.dtp_types import JTAG2AXI_TARGETS, DtpDmReg, pack_sbcs, unpack_sbcs
from ocah_lib import OcahKnobs

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

DM_ACTIVE_CHECK_ID = "CHK-J2A-DM-ACTIVE"
DM_ACTIVE_NEGATIVE_KNOB = "DTP_J2A_DM_ACTIVE_NEGATIVE"
# The one dmcontrol bit besides dmactive that an active Debug Module stores.
DMCONTROL_NDMRESET = 0x2
# sbcs while dmactive is 0.
SBCS_RESET = pack_sbcs(sbaccess=2)
SBERROR_SIZE = 4
_SBCS_WRITABLE = ("sbreadonaddr", "sbaccess", "sbautoincrement", "sbreadondata")
_SBACCESS_BITS = (128, 64, 32, 16, 8)


class dtp_jtag2axi_dm_regs_test_seq(dtp_jtag2axi_base_test_seq):
    """dmactive gating and the sbcs geometry, on each bridge in a seeded order."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_dm_regs_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("Debug Module activation and sbcs geometry on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("dm_regs")
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            self._ledger_target = target
            self.open_bus_ledger()
            await self.deactivate_case(target, rng)
            await self.inactive_writes_case(target, rng)
            await self.reactivate_case(target, rng)
            self.close_bus_ledger()
            self._ledger_target = None
            self.log_summary(f"{target} Debug Module registers complete")

    def check_dm_register(
        self, target: str, register: DtpDmReg, observed: int, expected: int, *, context: str
    ) -> None:
        """``CHK-J2A-DM-ACTIVE`` on one Debug Module register read.

        ``DTP_J2A_DM_ACTIVE_NEGATIVE=1`` flips the expected bit 0, so the run
        must fail.
        """
        if OcahKnobs.is_set(DM_ACTIVE_NEGATIVE_KNOB):
            expected ^= 0x1
        self.check_equal(
            self.target_evidence(target),
            DM_ACTIVE_CHECK_ID,
            observed,
            expected,
            context=(
                f"{context} target={target} register={register.name}"
                f" observed=0x{observed:08x} expected=0x{expected:08x}"
            ),
        )

    async def expect_registers(
        self, target: str, expected: dict[DtpDmReg, int], *, context: str
    ) -> None:
        """Read each register of ``expected`` in order and judge it."""
        for register, value in expected.items():
            observed = await self.dmi_read(
                target, register, context=f"{context}.{register.name.lower()}"
            )
            self.check_dm_register(target, register, observed, value, context=context)

    def active_sbcs(self, target: str, written: int, *, sberror: int = 0) -> int:
        """``sbcs`` of an active, idle Debug Module after a write of ``written``."""
        cfg = self.target_cfg(target)
        fields = unpack_sbcs(written)
        return pack_sbcs(
            sbversion=1,
            sbasize=cfg.addr_width,
            sberror=sberror,
            **{f"sbaccess{bits}": int(cfg.data_width >= bits) for bits in _SBACCESS_BITS},
            **{name: fields[name] for name in _SBCS_WRITABLE},
        )

    def sba_registers(self, target: str) -> tuple[list[DtpDmReg], list[DtpDmReg]]:
        """The sbaddress and the sbdata registers ``target``'s widths use, the one whose write
        starts an access last."""
        cfg = self.target_cfg(target)
        addresses = [DtpDmReg.SBADDRESS1] if cfg.addr_width > 32 else []
        data = [DtpDmReg.SBDATA1] if cfg.data_width > 32 else []
        return addresses + [DtpDmReg.SBADDRESS0], data + [DtpDmReg.SBDATA0]

    def sba_words(
        self, target: str, registers: list[DtpDmReg], rng: random.Random, *, align: int = 0
    ) -> dict[DtpDmReg, int]:
        """A seeded nonzero word for each of ``registers`` that ``target`` holds whole,
        sbaddress0 aligned to a ``1 << align`` byte access."""
        addr_width = self.target_cfg(target).addr_width
        widths = {DtpDmReg.SBADDRESS0: min(addr_width, 32), DtpDmReg.SBADDRESS1: addr_width - 32}
        return {
            reg: random_word(
                rng, widths.get(reg, 32), align=align if reg == DtpDmReg.SBADDRESS0 else 0
            )
            for reg in registers
        }

    async def deactivate_case(self, target: str, rng: random.Random) -> None:
        """A write of 0 to dmactive returns dmcontrol and the SBA registers to their reset
        values, sberror among them."""
        ctx = f"{target}.deactivate"
        oversize = self.target_cfg(target).data_size + 1
        sbcs = pack_sbcs(sbaccess=oversize, sbautoincrement=1, sbreadondata=1)
        addresses, data = self.sba_registers(target)
        words = self.sba_words(target, addresses + data, rng, align=oversize)
        await self.dmi_write(
            target, DtpDmReg.DMCONTROL, DMCONTROL_NDMRESET | 1, context=f"{ctx}.dmcontrol"
        )
        await self.dmi_write(target, DtpDmReg.SBCS, sbcs, context=f"{ctx}.sbcs")
        # The sbdata0 write starts an access that sbaccess refuses with sberror 4.
        for register, word in words.items():
            await self.dmi_write(target, register, word, context=f"{ctx}.{register.name.lower()}")
        await self.expect_registers(
            target,
            {
                DtpDmReg.DMCONTROL: DMCONTROL_NDMRESET | 1,
                DtpDmReg.SBCS: self.active_sbcs(target, sbcs, sberror=SBERROR_SIZE),
                **words,
            },
            context=f"{ctx}.set",
        )
        await self.dmi_write(target, DtpDmReg.DMCONTROL, 0, context=f"{ctx}.dmcontrol")
        await self.expect_registers(
            target,
            {DtpDmReg.DMCONTROL: 0, DtpDmReg.SBCS: SBCS_RESET, **dict.fromkeys(words, 0)},
            context=f"{ctx}.reset",
        )
        self.expect_no_bus_request(target, context=ctx)

    async def inactive_writes_case(self, target: str, rng: random.Random) -> None:
        """While dmactive is 0 a write changes no Debug Module register and starts no
        access; each write would start a read or a write if it took effect."""
        ctx = f"{target}.inactive"
        size = rng.randint(0, self.target_cfg(target).data_size)
        addresses, data = self.sba_registers(target)
        words = self.sba_words(target, addresses, rng, align=size)
        sbdata = self.sba_words(target, data, rng)
        await self.dmi_write(
            target,
            DtpDmReg.DMCONTROL,
            (random_word(rng, 30) << 2) | DMCONTROL_NDMRESET,
            context=f"{ctx}.dmcontrol",
        )
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbreadonaddr=1, sbaccess=size, sbautoincrement=1, sbreadondata=1),
            context=f"{ctx}.sbcs",
        )
        # With sbreadonaddr, the sbaddress0 write starts a read; with sbreadondata, so does
        # the sbdata0 read.
        for register, word in words.items():
            await self.dmi_write(target, register, word, context=f"{ctx}.{register.name.lower()}")
        await self.expect_registers(
            target,
            {
                DtpDmReg.DMCONTROL: 0,
                DtpDmReg.SBCS: SBCS_RESET,
                **dict.fromkeys(words, 0),
                DtpDmReg.SBDATA0: 0,
            },
            context=f"{ctx}.read",
        )
        self.expect_no_bus_request(target, context=f"{ctx}.read")
        # The sbdata0 write starts a write.
        for register, word in sbdata.items():
            await self.dmi_write(target, register, word, context=f"{ctx}.{register.name.lower()}")
        await self.expect_registers(
            target,
            {DtpDmReg.SBCS: SBCS_RESET, **dict.fromkeys(sbdata, 0)},
            context=f"{ctx}.write",
        )
        self.expect_no_bus_request(target, context=f"{ctx}.write")

    async def reactivate_case(self, target: str, rng: random.Random) -> None:
        """A write of 1 to dmactive releases the SBA registers at their reset values, with
        sbcs giving the geometry. A write of sbcs sets its writable fields and leaves the
        geometry, and the bridge reaches the bus again."""
        ctx = f"{target}.reactivate"
        addresses, data = self.sba_registers(target)
        await self.activate_dm(target)
        await self.expect_registers(
            target,
            {
                DtpDmReg.DMCONTROL: 1,
                DtpDmReg.SBCS: self.active_sbcs(target, SBCS_RESET),
                **dict.fromkeys(addresses + data, 0),
            },
            context=f"{ctx}.released",
        )
        written = self.sbcs_over_geometry(target, rng)
        await self.dmi_write(target, DtpDmReg.SBCS, written, context=f"{ctx}.sbcs")
        sbcs = await self.dmi_read(target, DtpDmReg.SBCS, context=f"{ctx}.sbcs")
        self.check_sbcs_geometry(target, sbcs, context=f"{ctx}.sbcs")
        self.check_dm_register(
            target, DtpDmReg.SBCS, sbcs, self.active_sbcs(target, written), context=f"{ctx}.sbcs"
        )
        await self.write_neighbour_then_read(
            target, self.random_target_addr(target, rng), rng, context=f"{ctx}.access"
        )

    def sbcs_over_geometry(self, target: str, rng: random.Random) -> int:
        """An ``sbcs`` write with every read-only field the inverse of ``target``'s
        geometry and sbbusy 1, and seeded writable fields other than their reset values."""
        cfg = self.target_cfg(target)
        reset = {name: unpack_sbcs(SBCS_RESET)[name] for name in _SBCS_WRITABLE}
        while True:
            writable = {
                "sbreadonaddr": rng.getrandbits(1),
                "sbaccess": rng.getrandbits(3),
                "sbautoincrement": rng.getrandbits(1),
                "sbreadondata": rng.getrandbits(1),
            }
            if writable != reset:
                break
        return pack_sbcs(
            sbversion=~1,
            sbbusy=1,
            sbasize=~cfg.addr_width,
            **{f"sbaccess{bits}": int(cfg.data_width < bits) for bits in _SBACCESS_BITS},
            **writable,
        )


def random_word(rng: random.Random, bits: int, *, align: int = 0) -> int:
    """A seeded nonzero ``bits``-bit word whose low ``align`` bits are 0."""
    while True:
        word = rng.getrandbits(bits) & ~((1 << align) - 1)
        if word:
            return word
