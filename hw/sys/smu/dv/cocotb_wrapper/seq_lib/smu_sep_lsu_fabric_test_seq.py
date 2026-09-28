# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP load/store unit traffic on the paths that leave the SEP, run under the debug module.

The SEP ICCM holds ``sep_lsu_probe.itcm.hex`` (``assets/gen_sep_lsu_probe_itcm.py``):
ten stores of every width into a 64-byte window at ``a0``, six word loads back
from it, their sum in ``t0``, then ``ebreak``. The debug module (RISC-V Debug
Specification 0.13) halts the hart, sets ``a0``, ``a1``, ``dpc`` and the trap
vector through abstract register writes, and resumes it; with ``dcsr.ebreakm``
set the ``ebreak`` returns the hart to debug mode, where ``t0`` is read back.

The VeeR EL2 load/store unit issues a bus access with AxCACHE 0b1111 and a
doubleword AxSIZE in a region whose ``mrac`` side-effect bit is clear, and with
AxCACHE 0b0000 and the access size when it is set; its AXI ID is the index of
the bus-buffer entry, of which there are four, and stores are posted
(``el2_lsu_bus_buffer.sv``).

S0..S3 are ``smu_dtp_sep_dm_dmi_test``.
S4: a halt request halts the hart, and ``dcsr.ebreakm``, ``mtvec`` and the
    outbound filter are set.
S5: the SMU aperture with the bench responder stalling every AW, W and AR
    handshake: the probe completes, ``t0`` is six times the store word, the
    responder holds every byte stored, and each address phase leaves with
    AxCACHE 0b1111.
S6: the same with the region's side-effect bit set: each address phase leaves
    with AxCACHE 0b0000 and every byte store and half-word store keeps its size.
S7: the SEP view of the SMC SPM: the probe completes and ``t0`` is six times
    the store word.
S8: the external aperture, whose DECERR slave (``sep_ip_integration.sv``) fails
    every access: a run entered at the loads, with the side-effect bit clear,
    takes the first bus error as an NMI to the vector's ``ebreak``, and no run,
    that one or the full probe with the bit set and clear, reads the stored
    word back.
S9: before the first probe run and after the last, a system-bus write and read
    on the SMU aperture and the SMC SPM view complete and on the external
    aperture return a bus error, so both initiators take each path in turn.
"""

from __future__ import annotations

from cocotb.triggers import ClockCycles

from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    DMI_OP_WRITE,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
)
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import (
    ADDR_MASK,
    SB_BUS_ERROR,
    SEP_EXTERNAL_BASE,
    SMC_SPM_BASE,
    SMU_BASE,
    _CacheTap,
    smu_sep_sba_fabric_sweep_test_seq,
)

ICCM_BASE = 0xC000_0000
TRAP_VECTOR = ICCM_BASE + 0x100
# Instruction index of the probe's ebreak (gen_sep_lsu_probe_itcm.program()).
PROBE_EBREAK = ICCM_BASE + 4 * 22
# Instruction index of the probe's first load: a run entered here issues the
# loads without the stores before them.
PROBE_LOADS_ENTRY = ICCM_BASE + 4 * 10
PROBE_STORES = [(4, 8 * i) for i in range(8)] + [(2, 66), (1, 73)]
PROBE_LOADS = 6

# RISC-V Debug Specification 0.13 debug module registers and fields.
DATA0 = 0x04
DMCONTROL = 0x10
DMSTATUS = 0x11
ABSTRACTCS = 0x16
COMMAND = 0x17
DMACTIVE = 1 << 0
HALTREQ = 1 << 31
RESUMEREQ = 1 << 30
ALLHALTED = 1 << 9
ALLRESUMEACK = 1 << 17
ABSTRACTCS_BUSY = 1 << 12
CMDERR_SHIFT = 8
CMDERR_MASK = 0x7
AARSIZE_32 = 2 << 20
TRANSFER = 1 << 17
WRITE = 1 << 16
GPR = 0x1000
A0, A1, T0 = GPR + 10, GPR + 11, GPR + 5
CSR_MTVEC = 0x305
CSR_MCAUSE = 0x342
# VeeR EL2 mcause for an imprecise store and load bus-error NMI.
NMI_BUS_ERROR_CAUSES = (0xF000_0000, 0xF000_0001)
CSR_DCSR = 0x7B0
CSR_DPC = 0x7B1
# VeeR EL2 memory region access control: bit 2r+1 is region r's side effect.
CSR_MRAC = 0x7C0
DCSR_EBREAKM = 1 << 15
DCSR_CAUSE_SHIFT = 6
DCSR_CAUSE_EBREAK = 1

HALT_POLLS = 64
RUN_POLLS = 400
BACKPRESSURE_STALL = 12
STORE_WORD = 0x5A0F_C3E1


def _side_effect(addr: int) -> int:
    return 1 << (2 * (addr >> 28) + 1)


class smu_sep_lsu_fabric_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """Run the ICCM probe against the SMU, SMC and external apertures."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"s4": False, "s5": False, "s6": False, "s7": False, "s8": False}

    async def _abstract(self, jtag, command: int) -> None:
        await self._dmi(jtag, COMMAND, command, DMI_OP_WRITE)
        for _ in range(HALT_POLLS):
            status = await self._dmi(jtag, ABSTRACTCS, 0, DMI_OP_READ)
            if not status & ABSTRACTCS_BUSY:
                break
        else:
            raise AssertionError(f"abstract command 0x{command:08x} stayed busy")
        cmderr = (status >> CMDERR_SHIFT) & CMDERR_MASK
        if cmderr:
            await self._dmi(jtag, ABSTRACTCS, CMDERR_MASK << CMDERR_SHIFT, DMI_OP_WRITE)
            raise AssertionError(f"abstract command 0x{command:08x} cmderr={cmderr}")

    async def _reg_write(self, jtag, regno: int, value: int) -> None:
        await self._dmi(jtag, DATA0, value & 0xFFFF_FFFF, DMI_OP_WRITE)
        await self._abstract(jtag, AARSIZE_32 | TRANSFER | WRITE | regno)

    async def _reg_read(self, jtag, regno: int) -> int:
        await self._abstract(jtag, AARSIZE_32 | TRANSFER | regno)
        return await self._dmi(jtag, DATA0, 0, DMI_OP_READ)

    async def _wait_status(self, jtag, bit: int, polls: int) -> bool:
        for _ in range(polls):
            if await self._dmi(jtag, DMSTATUS, 0, DMI_OP_READ) & bit:
                return True
            await ClockCycles(self.dut.clk_smu_i, 32)
        return False

    async def _halt(self, jtag, sb) -> None:
        await self._dmi(jtag, DMCONTROL, DMACTIVE | HALTREQ, DMI_OP_WRITE)
        halted = await self._wait_status(jtag, ALLHALTED, HALT_POLLS)
        await self._dmi(jtag, DMCONTROL, DMACTIVE, DMI_OP_WRITE)
        sb.expect_true("CHK-SEP-LSU-HALT", halted, evidence="CHK-SEP-LSU-HALT")
        dcsr = await self._reg_read(jtag, CSR_DCSR)
        await self._reg_write(jtag, CSR_DCSR, dcsr | DCSR_EBREAKM)
        await self._reg_write(jtag, CSR_MTVEC, TRAP_VECTOR)
        await self._sb_ok(jtag, OUTBOUND_START_ADDR, 3, 0)
        await self._sb_ok(jtag, OUTBOUND_END_ADDR, 3, ADDR_MASK)
        await self._sb_ok(jtag, OUTBOUND_FILTER_CONFIG, 2, OUTBOUND_CFG_OPEN)
        self.steps["s4"] = True

    async def _run_probe(self, jtag, base: int, mrac: int, entry: int = ICCM_BASE) -> dict:
        """Resume at the probe with a0=base; return what the hart reports on halting."""
        await self._reg_write(jtag, CSR_MRAC, mrac)
        await self._reg_write(jtag, A0, base)
        await self._reg_write(jtag, A1, STORE_WORD)
        await self._reg_write(jtag, T0, 0)
        await self._reg_write(jtag, CSR_DPC, entry)
        await self._dmi(jtag, DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE)
        resumed = await self._wait_status(jtag, ALLRESUMEACK, HALT_POLLS)
        await self._dmi(jtag, DMCONTROL, DMACTIVE, DMI_OP_WRITE)
        halted = await self._wait_status(jtag, ALLHALTED, RUN_POLLS)
        if not halted:
            await self._dmi(jtag, DMCONTROL, DMACTIVE | HALTREQ, DMI_OP_WRITE)
            await self._wait_status(jtag, ALLHALTED, HALT_POLLS)
            await self._dmi(jtag, DMCONTROL, DMACTIVE, DMI_OP_WRITE)
        dcsr = await self._reg_read(jtag, CSR_DCSR)
        return {
            "resumed": resumed,
            "halted": halted,
            "cause": (dcsr >> DCSR_CAUSE_SHIFT) & 0x7,
            "dpc": await self._reg_read(jtag, CSR_DPC),
            "t0": await self._reg_read(jtag, T0),
        }

    @staticmethod
    def _completed(t0: int) -> dict:
        return {
            "resumed": True,
            "halted": True,
            "cause": DCSR_CAUSE_EBREAK,
            "dpc": PROBE_EBREAK,
            "t0": t0,
        }

    def _held(self, base: int) -> tuple[dict, dict]:
        held, want = {}, {}
        for width, off in PROBE_STORES:
            held[off] = self.mem.read_int(base + off, width)
            want[off] = STORE_WORD & ((1 << (8 * width)) - 1)
        return held, want

    async def _smu_aperture(self, jtag, sb, tap: _CacheTap) -> None:
        sum6 = (PROBE_LOADS * STORE_WORD) & 0xFFFF_FFFF
        for step, label, base, mrac, cache in (
            ("s5", "CHK-SEP-LSU-OUT", SMU_BASE + 0x1000_2000, 0, 0b1111),
            (
                "s6",
                "CHK-SEP-LSU-OUT-SIDE-EFFECT",
                SMU_BASE + 0x1000_3000,
                _side_effect(SMU_BASE + 0x1000_3000),
                0b0000,
            ),
        ):
            aw0, ar0 = len(tap.aw), len(tap.ar)
            self.mem.enable_backpressure(
                channels=("aw", "w", "ar"), stall_cycles=BACKPRESSURE_STALL
            )
            try:
                report = await self._run_probe(jtag, base, mrac)
            finally:
                self.mem.disable_backpressure()
            held, want_held = self._held(base)
            phases = [p for p in tap.aw[aw0:] + tap.ar[ar0:] if base <= p[0] < base + 0x80]
            caches = sorted({c for _, c in phases})
            self._log(f"{label} report={report} held={held} phases={phases}")
            sb.expect_eq(
                label,
                (report, held, caches),
                (self._completed(sum6), want_held, [cache]),
                evidence=label,
            )
            if step == "s6":
                sizes = sorted(a - base for a, _ in tap.aw[aw0:] if base <= a < base + 0x80)
                sb.expect_eq(
                    f"{label} every store leaves at its own address",
                    sizes,
                    sorted(off for _, off in PROBE_STORES),
                )
            self.steps[step] = True

    async def _smc_spm(self, jtag, sb) -> None:
        self.smc_base = int(self.dut.smc_global_base_o.value)
        base = self._smc_view(SMC_SPM_BASE) + 0x3000
        report = await self._run_probe(jtag, base, 0)
        self._log(f"CHK-SEP-LSU-SMC report={report}")
        sb.expect_eq(
            "CHK-SEP-LSU-SMC",
            report,
            self._completed((PROBE_LOADS * STORE_WORD) & 0xFFFF_FFFF),
            evidence="CHK-SEP-LSU-SMC",
        )
        self.steps["s7"] = True

    async def _external(self, jtag, sb) -> None:
        base = SEP_EXTERNAL_BASE + 0x1000
        sum6 = (PROBE_LOADS * STORE_WORD) & 0xFFFF_FFFF
        observed = {}
        for label, mrac, entry in (
            ("loads", 0, PROBE_LOADS_ENTRY),
            ("side effect", _side_effect(base), ICCM_BASE),
            ("plain", 0, ICCM_BASE),
        ):
            report = await self._run_probe(jtag, base, mrac, entry)
            mcause = await self._reg_read(jtag, CSR_MCAUSE)
            observed[label] = (report, mcause)
        self._log(f"CHK-SEP-LSU-EXTERNAL {observed}")
        # The first bus error is an imprecise-error NMI to the vector
        # (mcause 0xF000_0000 store, 0xF000_0001 load). With that NMI not
        # returned from, a later run completes the probe instead, and its
        # loads return the DECERR slave's zero data, never the stored word.
        first, cause = observed["loads"]
        verdict = {
            "first run traps": (
                first["halted"],
                first["cause"],
                first["dpc"],
                cause in NMI_BUS_ERROR_CAUSES,
            ),
            "no run reads the stored word back": [
                (r["halted"], r["cause"], r["dpc"] in (TRAP_VECTOR, PROBE_EBREAK), r["t0"] != sum6)
                for r, _ in observed.values()
            ],
        }
        sb.expect_eq(
            "CHK-SEP-LSU-EXTERNAL",
            verdict,
            {
                "first run traps": (True, DCSR_CAUSE_EBREAK, TRAP_VECTOR, True),
                "no run reads the stored word back": [(True, DCSR_CAUSE_EBREAK, True, True)]
                * len(observed),
            },
            evidence="CHK-SEP-LSU-EXTERNAL",
        )
        self.steps["s8"] = True

    async def _system_bus_mix(self, jtag, sb, label: str) -> None:
        """A system-bus write and read on each path the probe uses, between probe runs."""
        self.smc_base = int(self.dut.smc_global_base_o.value)
        cells = (
            (SMU_BASE + 0x1000_4000, (0, 0)),
            (self._smc_view(SMC_SPM_BASE) + 0x5000, (0, 0)),
            (SEP_EXTERNAL_BASE + 0x2000, (SB_BUS_ERROR, SB_BUS_ERROR)),
        )
        observed, want = {}, {}
        for addr, expect in cells:
            werr, _ = await self._sb(jtag, addr, 3, STORE_WORD)
            rerr, _ = await self._sb(jtag, addr, 3)
            observed[hex(addr)] = (werr, rerr)
            want[hex(addr)] = expect
        self._log(f"CHK-SEP-LSU-SBA-MIX {label} {observed}")
        sb.expect_eq(f"CHK-SEP-LSU-SBA-MIX {label}", observed, want, evidence="CHK-SEP-LSU-SBA-MIX")

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        tap = _CacheTap(self.dut)
        try:
            await self._halt(jtag, sb)
            await self._system_bus_mix(jtag, sb, "before")
            await self._smu_aperture(jtag, sb, tap)
            await self._smc_spm(jtag, sb)
            await self._external(jtag, sb)
            await self._system_bus_mix(jtag, sb, "after")
        finally:
            tap.stop()
