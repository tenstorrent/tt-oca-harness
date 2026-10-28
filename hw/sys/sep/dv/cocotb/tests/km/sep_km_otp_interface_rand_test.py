# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KMCSR OTP readout, read locks, secure test masking, change and integrity of the KM OTP input.

no_cpu (``lsu_stub_all_live``), POKE image (``+km_rom_hex=km_rom_poke.parhex``),
real fuse sense of a per-leaf fuse image (no ``+skip_fuse_sense``), VCS only. The
image is staged at t=0 by ``dv_sim_prestage.py`` from ``env/sep_km_fuse_plan.py``;
the test rebuilds the same plan from the same seed for its golden and checks
the sha256 of the staged file against it.

Contract (spec only): ``hw/ip/key_manager/doc/architecture.adoc`` "OTP Inputs
and Readout", "Errors and reset", "Scan and Scan-Dump Protection";
``hw/ip/key_manager/regs/gen/adoc/km_csr.adoc`` "OTP_LIFE_CYCLE" through
"OTP_READ_LOCK_COLD", "IRQ_STATUS", "IRQ_SET", "OTP_CHANGE_STATUS";
``hw/sys/sep/doc/otp_fuse_controller.adoc`` "Fuse Fields";
``hw/sys/sep/doc/lifecycle_controller.adoc`` "In-Field Debug Demotion";
``hw/sys/sep/doc/test_mode.adoc`` "Protection While Active".

The KM CPU reads and writes every KMCSR register through the POKE image, which
clears IRQ_STATUS.AXI_SLVERR / AXI_DECERR before each access and reports them
after it; a readback counts only with both bits 0. The host writes the LCC
DEMOTE registers, the eFuse shadow words and SW_RESET_N. ``HK-OTP``
(``km_otp_flip_en_i`` / ``km_otp_flip_mask_i``) flips bits of the KM OTP input
for the integrity and change legs; it is stimulus only and never a golden.

Checks (anchor):
  CHK-OTP-RD             boot-1 readout of the four secrets, the life cycle and
                         the demotion state (POKE readback vs staged image)
  CHK-OTP-LOCK           zero read of every field in m_w | m_c, staged read of
                         the rest, write-one-to-set lock registers (POKE readback)
  CHK-OTP-HANDOVER-MASK  control=1: OTP_READ_LOCK = 0x03C (POKE readback)
  CHK-OTP-TM             secure test boot: secrets 0 / all ones, public and
                         life-cycle words kept, OTP_SIGINT quiet (POKE readback,
                         ``secure_tm_o``)
  CHK-OTP-DEM            a DEMOTE write sets OTP_CHANGE_STATUS.demotion and
                         IRQ_STATUS.OTP_CHANGE and changes one group (POKE readback)
  CHK-OTP-SUPP           no change after a KM warm reset with a demotion held
  CHK-OTP-COLD           a SEP cold reset restores the first-boot demotion state
  CHK-OTP-NOTKM          shadow writes of REQUIRED_ALGS / REQUIRED_SIGNERS leave
                         the KM OTP words and status unchanged (POKE + host readback)
  CHK-OTP-NOTKM-CLASS    programmed bits of one field outside the KM interface
                         (BL1/BL2_VERSION, an RMA token digest or a public-key
                         hash), sensed by a SEP cold reset, leave every KM OTP
                         readout word equal to the boot before and to the staged
                         image (POKE readback; host program and shadow readback)
  CHK-OTP-SIG            a single-rail flip sets the sticky OTP_SIGINT (IRQ_STATUS)
  CHK-OTP-CHG            a two-rail flip sets the field change bit and
                         OTP_CHANGE, no OTP_SIGINT (POKE readback)

Logged only (no verdict): ``OBS-OTP-BOOT-SIGINT`` (IRQ_STATUS.OTP_SIGINT right
after each KM reset; the leaf clears it with a write of 1 before any graded
OTP_SIGINT read), ``OBS-OTP-SIG-CHANGE`` (OTP_CHANGE_STATUS after a single-rail
flip, not stated), ``OBS-OTP-DEM-GROUP`` (which group a DEMOTE register drives,
not stated), ``OBS-OTP-LOCK-RESP`` (the response of a locked-field read, not
stated; only its zero data is graded), ``OBS-OTP-RSVD`` (reserved bits of the read
registers).

Every drawn value is a pure function of the seed (``SepSeededRng``), and each
draw is logged on a ``DRAW`` line.

The fuse array changes in the simulation only through ``EFUSE_PROGRAM_CTRL``
(host writes, staged image unlocked); the golden of every later sense is the
staged image plus the programmed bits.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env import sep_km_poke as kp
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import WORD_MASK, SepEfuseImage
from env.sep_efuse_plan import PROGRAM_CTRL_ADDR, program_ctrl_word
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_km_fuse_plan import OTP_SHADOW_WRITE_FIELDS, T_OTP_IFACE, KmFusePlan, plan
from env.sep_seeded_rng import SepSeededRng
from km import sep_km_otp_interface_rand_model as m
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_poke_seq import SepKmPoke
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccDemoteSeq
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = T_OTP_IFACE

# --- test parameters ----------------------------------------------------------

SENSE_BOUND = 20_000  # clocks for sep_fuse_sense_done_o
RELEASE_BOUND = 20_000  # clocks for dbg_sep_reset_n_o after the sense
RESET_HOLD = 20  # clocks of rst_ni low, on each side of a strap change
QUIET = 256  # delay-op iterations of every "quiet window"
FLIP_CYCLES = 8  # clocks the HK-OTP enable stays 1
POLL_LOADS = 64  # KM loads of every bounded poll
LIST_TIMEOUT = 4_000_000
PROGRAM_POLLS = 1_000  # EFUSE_PROGRAM_CTRL reads of one program_done poll
PROGRAM_GAP = 16  # clocks between two program_done reads

_FN = m.FIELD_NAMES

_PG_DONE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_PG_BUSY = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_busy")
_PG_STATUS = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_status")

# Fuse fields that are not part of the Key Manager OTP interface, by class
# (hw/sys/sep/doc/otp_fuse_controller.adoc:443-445: "BL1_VERSION, BL2_VERSION,
# RMA token digests and public-key hashes are not part of that Key Manager
# interface"). The second item is the class value of
# sep_km_otp_readout_cg.cp_otp_notkm_class.
NOTKM_CLASSES: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("arbc", 0, ("BL1_VERSION", "BL2_VERSION")),
    ("rma_digest", 1, ("RMA_SIP_TOKEN_DIGEST", "RMA_CHIPLET_TOKEN_DIGEST")),
    (
        "pk_hash",
        3,
        (
            "SIP_PUBK_HASH0",
            "SIP_PUBK_HASH1",
            "SYS_PUBK_HASH",
            "CHIPLET_PUBK_HASH0",
            "CHIPLET_PUBK_HASH1",
            "CHIPLET_PUBK_PQC_HASH0",
            "CHIPLET_PUBK_PQC_HASH1",
            "SIP_PUBK_PQC_HASH0",
            "SIP_PUBK_PQC_HASH1",
            "SYS_PUBK_PQC_HASH",
        ),
    ),
)
NOTKM_MAX_BITS = 3  # programmed bits of the drawn class field: 1 to 3


def _h(v: int) -> str:
    return f"0x{v:08x}"


def _ok(res: kp.PokeResult, k: int = 0) -> bool:
    """A readback counts: known, the clear before it held, no SLVERR or DECERR."""
    f = res.flags[k]
    return res.known and f is not None and f.clean and f.slv == 0 and f.dec == 0


@dataclass
class Readout:
    """One readout: the 114 OTP words, the lock and status registers."""

    label: str
    words: dict[m.Slot, int]
    lock: int
    lock_cold: int
    change: int
    irq: int
    bad: list[str] = field(default_factory=list)
    reg_bad: list[str] = field(default_factory=list)
    slot_resp: dict[m.Slot, str] = field(default_factory=dict)
    slot_resp_only: set[m.Slot] = field(default_factory=set)


@dataclass
class Leg:
    """Results of one inject or DEMOTE leg."""

    label: str
    pts: list[m.FlipPoint]
    exp: int = 0
    pre_irq: int = 0
    pre_change: int = 0
    pre_dem: int = 0
    poll: int = 0
    poll_irq: int = 0
    irq: int = 0
    change: int = 0
    dem: int = 0
    w1c_irq: int = 0
    w1c_change: int = 0
    bad: list[str] = field(default_factory=list)
    active: int = 0


# One fuse bit to program: (eFuse field name, word in the field, bit in the word).
FuseBit = tuple[str, int, int]


@dataclass
class ClassLeg:
    """Draws of the fuse-class leg and its public-identity sensitivity twin."""

    cls: str
    cls_value: int
    fuse_field: str
    bits: list[FuseBit]
    pub: FuseBit
    pub_f: int
    pub_word: int
    pub_bit: int


def _zero_bit(rng, words: list[int], name: str, taken: set[tuple[int, int]]) -> FuseBit:
    """A bit of field ``name`` that reads 0 in ``words`` and is not in ``taken``."""
    fld = SepEfuseImage.field(name)
    order = list(range(fld.n_words))
    rng.shuffle(order)
    for w in order:
        word = words[fld.word + w]
        zeros = [b for b in range(32) if not (word >> b) & 1 and (w, b) not in taken]
        if zeros:
            return (name, w, int(rng.choice(zeros)))
    raise AssertionError(f"{name} has no 0 bit left in the staged image")


def draw_class_leg(rng, words: list[int]) -> ClassLeg:
    """The class, field and bits to program, and the public-identity twin bit."""
    cls, value, names = NOTKM_CLASSES[rng.randrange(len(NOTKM_CLASSES))]
    name = str(rng.choice(names))
    taken: set[tuple[int, int]] = set()
    bits: list[FuseBit] = []
    for _ in range(1 + rng.randrange(NOTKM_MAX_BITS)):
        bit = _zero_bit(rng, words, name, taken)
        taken.add((bit[1], bit[2]))
        bits.append(bit)
    pub_f = int(rng.choice(m.PUBLIC))
    pub = _zero_bit(rng, words, m.efuse_name(pub_f), set())
    return ClassLeg(cls, value, name, bits, pub, pub_f, pub[1], pub[2])


class _Ops:
    """A POKE list whose result slots are looked up by name."""

    def __init__(self) -> None:
        self.ops: list[kp.PokeOp] = []
        self.at: dict[str, int] = {}

    def add(self, op: kp.PokeOp, name: str | None = None) -> None:
        if name is not None:
            self.at[name] = len(self.ops)
        self.ops.append(op)

    def values(self, res: list[kp.PokeResult]) -> dict[str, int]:
        return {name: res[i].value for name, i in self.at.items()}


@pyuvm.test()
class sep_km_otp_interface_rand_test(sep_base_test):
    """KM OTP readout, locks, secure test mode, demotion change and HK-OTP integrity legs."""

    required_evidence = (
        "CHK-OTP-RD",
        "CHK-OTP-LOCK",
        "CHK-OTP-HANDOVER-MASK",
        "CHK-OTP-TM",
        "CHK-OTP-DEM",
        "CHK-OTP-SUPP",
        "CHK-OTP-COLD",
        "CHK-OTP-NOTKM",
        "CHK-OTP-NOTKM-CLASS",
        "CHK-OTP-SIG",
        "CHK-OTP-CHG",
    )

    # --- small helpers ------------------------------------------------------

    def _draw(self, name: str, value) -> None:
        if isinstance(value, int):
            self.logger.info("DRAW %s=0x%x", name, value)
        else:
            self.logger.info("DRAW %s=%s", name, value)

    async def _run(self, ops: list[kp.PokeOp], **kw) -> list[kp.PokeResult]:
        return await self.poke.run(ops, timeout_cycles=LIST_TIMEOUT, allow_unknown=True, **kw)

    async def _host(self, op: SepAxiOp, addr: int, data: int = 0) -> tuple[int, bool]:
        """One host access; returns (read data, OKAY)."""
        if op is SepAxiOp.READ:
            seq = SepAxiAccessSeq(
                "km_otp_host_rd", op=op, addr=addr, length=4, size=2, allow_ungraded_read_resp=True
            )
        else:
            seq = SepAxiAccessSeq(
                "km_otp_host_wr",
                op=op,
                addr=addr,
                wdata=data,
                length=4,
                size=2,
                allow_unverified_write_resp=True,
            )
        await self.start_seq(seq)
        if seq.timed_out:
            raise AssertionError(f"host {op.value} 0x{addr:08x} did not complete")
        return seq.rdata & WORD_MASK, bool(seq.resp_ok)

    async def _wait_sep_reset_release(self) -> int:
        dut = cocotb.top
        for cycle in range(1, RELEASE_BOUND + 1):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True):
                return cycle
        raise AssertionError(
            f"dbg_sep_reset_n_o did not read 1 within {RELEASE_BOUND} clocks after fuse sense"
        )

    def _check_staged_identity(self, fp: KmFusePlan) -> None:
        path = Path(os.getcwd()) / "out" / "sep_efuse.hex"
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
        self.logger.info("KM-FUSE-PLAN staged=%s staged_sha256=%s", path, digest)
        if digest != fp.identity():
            raise AssertionError(
                f"staged fuse image {path} sha256={digest} is not the plan image "
                f"{fp.identity()}; the prestage registry entry of {TEST} did not run"
            )

    def _rsvd(self, reg: str, value: int, fields: int) -> None:
        if value & ~fields & WORD_MASK:
            self.chk.obs("OTP-RSVD", reg=reg, value=_h(value), mask=_h(~fields & WORD_MASK))

    # --- boots and resets ---------------------------------------------------------

    async def _km_boot(self, boot: str) -> None:
        """Release the KM, wait for the POKE start marker, then clear OTP_SIGINT.

        A KM reset can leave IRQ_STATUS.OTP_SIGINT at 1 before any inject. The
        leaf logs that value and writes 1 to OTP_SIGINT only, so every graded
        OTP_SIGINT read starts from a cleared bit, and OTP_CHANGE stays as the
        reset left it (CHK-OTP-SUPP and CHK-OTP-COLD read it).
        """
        await self.poke.release()
        await self.poke.wait_boot()
        await self._sigint_clear(boot)

    async def _sigint_clear(self, boot: str) -> None:
        r = await self._run(
            [kp.rd(m.A_IRQ_STATUS), kp.wr(m.A_IRQ_STATUS, m.IRQ_OTP_SIGINT), kp.rd(m.A_IRQ_STATUS)]
        )
        pre, post = r[0].value, r[2].value
        self.chk.obs(
            "OTP-BOOT-SIGINT",
            boot=boot,
            irq_pre=_h(pre),
            sigint_pre=int(bool(pre & m.IRQ_OTP_SIGINT)),
            irq_post=_h(post),
        )
        self.chk.ctrl(
            "OTP-BOOT-SIGINT-CLEAR",
            _ok(r[2]) and not post & m.IRQ_OTP_SIGINT,
            boot=boot,
            irq_post=_h(post),
        )

    async def _cold_reset(self, strap: int, boot: str) -> int:
        """SEP cold reset with ``test_en_strap_i`` set while the reset is held."""
        dut = cocotb.top
        await self.poke.prepare_reset()
        self.write_efuse_image(self.model)
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, RESET_HOLD)
        dut.test_en_strap_i.value = strap
        await ClockCycles(dut.clk_i, RESET_HOLD)
        dut.rst_ni.value = 1
        await self.wait_fuse_sense(max_cycles=SENSE_BOUND)
        rel = await self._wait_sep_reset_release()
        self.cfg.reset_done.set()
        await ReadOnly()
        tm = self.rd(dut.secure_tm_o)
        await RisingEdge(dut.clk_i)
        self.logger.info(
            "LOG %s cold reset strap=%d: sep_reset_n release +%d clk, secure_tm_o=%d",
            boot,
            strap,
            rel,
            tm,
        )
        self.swrst = SepSwReset(self)
        await self._km_boot(boot)
        return tm

    async def _park(self) -> None:
        """KM warm reset: SW_RESET_N bit 0 low then high, the other bits at 1."""
        await self.poke.prepare_reset()
        await self.poke.mbox.flush()
        await self.swrst.park("km")
        await self.swrst.release("km")
        await self.poke.wait_boot()
        await self._sigint_clear("park")

    # --- readout ------------------------------------------------------------------

    async def _readout(self, label: str) -> Readout:
        (b0, s0), (b1, s1), (b2, s2) = m.READOUT_BLOCKS
        r1 = await self._run([kp.rdblk(b0, len(s0)), kp.rdblk(b1, len(s1))])
        r2 = await self._run(
            [
                kp.rdblk(b2, len(s2)),
                kp.rd(m.A_READ_LOCK),
                kp.rd(m.A_READ_LOCK_COLD),
                kp.rd(m.A_CHANGE),
                kp.rd(m.A_IRQ_STATUS),
            ]
        )
        words: dict[m.Slot, int] = {}
        bad: list[str] = []
        slot_resp: dict[m.Slot, str] = {}
        resp_only: set[m.Slot] = set()
        for res, slots in ((r1[0], s0), (r1[1], s1), (r2[0], s2)):
            for k, slot in enumerate(slots):
                words[slot] = res.data[k]
                if not _ok(res, k):
                    bad.append(f"{label} {_FN[slot[0]]}.{slot[1]}{slot[2]} not a clean OKAY read")
                    fl = res.flags[k]
                    if res.known and fl is not None and fl.clean:
                        resp_only.add(slot)
                    slot_resp[slot] = (
                        f"known={int(res.known)} slv={fl.slv} dec={fl.dec} "
                        f"pre_clean={int(fl.clean)}"
                        if fl is not None
                        else "no_flags"
                    )
        reg_bad: list[str] = []
        regs = r2[1:]
        for name, res in zip(
            ("OTP_READ_LOCK", "OTP_READ_LOCK_COLD", "OTP_CHANGE_STATUS", "IRQ_STATUS"),
            regs,
            strict=True,
        ):
            if not _ok(res):
                reg_bad.append(f"{label} {name} not a clean OKAY read")
        ro = Readout(
            label,
            words,
            regs[0].value,
            regs[1].value,
            regs[2].value,
            regs[3].value,
            bad + reg_bad,
            reg_bad,
            slot_resp,
            resp_only,
        )
        self._rsvd("OTP_LIFE_CYCLE", words[(m.F_LC, "reg", 0)], m.LC_FIELDS)
        self._rsvd("OTP_DEMOTION_STATE", words[(m.F_DEM, "reg", 0)], m.DEM_FIELDS)
        self._rsvd("OTP_READ_LOCK", ro.lock, m.LOCK_FIELDS)
        self._rsvd("OTP_READ_LOCK_COLD", ro.lock_cold, m.LOCK_FIELDS)
        self._rsvd("OTP_CHANGE_STATUS", ro.change, m.CHANGE_FIELDS)
        self._rsvd("IRQ_STATUS", ro.irq, m.IRQ_FIELDS)
        return ro

    def _bad_under(self, ro: Readout, eff: int) -> list[str]:
        """Response problems of a readout under the effective lock ``eff``.

        The RDL states only that a locked field reads zero, not the response,
        so a locked read is graded on its data and its SLVERR / DECERR bits are
        logged. A locked read with an unknown bit or a failed clear before it
        fails: an unknown word would otherwise compare equal to 0. Every
        unlocked read and every register read counts only as a clean OKAY.
        """
        out = list(ro.reg_bad)
        locked: list[str] = []
        for slot, resp in ro.slot_resp.items():
            name = f"{_FN[slot[0]]}.{slot[1]}{slot[2]}"
            if (eff >> slot[0]) & 1 and slot in ro.slot_resp_only:
                locked.append(f"{name}:{resp}")
            else:
                out.append(f"{ro.label} {name} not a clean OKAY read")
        if locked:
            self.chk.obs("OTP-LOCK-RESP", readout=ro.label, reads=len(locked), first=locked[0])
        return out

    @staticmethod
    def _field_bits(slot: m.Slot, value: int) -> int:
        f = slot[0]
        if f == m.F_LC:
            return value & m.LC_FIELDS
        if f == m.F_DEM:
            return value & m.DEM_FIELDS
        return value & WORD_MASK

    def _diff(self, ro: Readout, exp: dict[m.Slot, int]) -> dict[int, list[str]]:
        """Per field, the words that differ from ``exp`` (RDL field bits)."""
        out: dict[int, list[str]] = {f: [] for f in range(m.N_FIELDS)}
        for slot, want in exp.items():
            got = self._field_bits(slot, ro.words[slot])
            if got != want:
                out[slot[0]].append(f"{slot[1]}{slot[2]}={_h(got)}!={_h(want)}")
        return out

    def _expected(self, eff: int, tm: int = 0) -> dict[m.Slot, int]:
        return m.expected_readout(self.otp_fields, self.fp.lc_raw, self.dem_record, eff, tm)

    # --- scenario -------------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        fp = plan(TEST, seed)
        self.fp = fp
        # The KM OTP field values of the current fuse array: the staged plan
        # plus every bit this leaf programs.
        self.otp_fields = dict(fp.otp_fields)
        self.logger.info("DRAW fuse_plan %s", fp.summary())
        lc_name = {0x0: "TEST_DEV", 0x1: "PROD"}.get(fp.lc_raw, f"0x{fp.lc_raw:x}")
        self.logger.info("LC lc=%s", lc_name)
        self.masks = m.lock_rounds(fp.lock_mask_a)
        self._draw("lock.a", self.masks["a"])
        self._draw("lock.not_a", self.masks["not_a"])
        # The RAND-REP stream is a second pure function of the seed, apart from the plan stream.
        self.rep = m.draw_rep(SepSeededRng(seed ^ (735 << 48)))
        for name, value in self.rep.draws:
            self._draw(name, value)
        # The fuse-class leg draws from a third stream of the seed.
        self.class_leg = draw_class_leg(SepSeededRng(seed ^ (735 << 48) ^ (1 << 32)), fp.words)
        self._draw("notkm.class", f"{self.class_leg.cls}({self.class_leg.cls_value})")
        self._draw("notkm.field", self.class_leg.fuse_field)
        self._draw("notkm.bits", [f"w{w}.b{b}" for _, w, b in self.class_leg.bits])
        self._draw(
            "notkm.twin",
            f"{self.class_leg.pub[0]}.w{self.class_leg.pub_word}.b{self.class_leg.pub_bit}",
        )
        self._draw("quiet_window", QUIET)
        self._draw("flip_cycles", FLIP_CYCLES)
        for name in OTP_SHADOW_WRITE_FIELDS + ("LOCKS", "LOCKS_SPARE"):
            fld = SepEfuseImage.field(name)
            staged = fp.words[fld.word : fld.word + fld.n_words]
            if any(staged):
                raise AssertionError(f"plan stages {name}={staged}; the leaf needs it at 0")
        self.chk = SepChkLog(self, TEST, seed)
        self._check_staged_identity(fp)
        self.model = fp.image()
        self.write_efuse_image(self.model)

        dut = cocotb.top
        if len(dut.km_otp_flip_mask_i) != m.OTP_WIDTH:
            raise AssertionError(
                f"km_otp_flip_mask_i is {len(dut.km_otp_flip_mask_i)} bits, "
                f"km_otp_data_t is {m.OTP_WIDTH}"
            )
        # Step 1-2: boot 1, strap 0, real sense.
        dut.test_en_strap_i.value = 0
        await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        dut.test_en_strap_i.value = 0
        rel = await self._wait_sep_reset_release()
        self.tm0 = self.rd(dut.secure_tm_o)
        self.logger.info(
            "LOG boot1 strap=0: sep_reset_n release +%d clk, secure_tm_o=%d", rel, self.tm0
        )
        self.swrst = SepSwReset(self)
        self.poke = SepKmPoke(self)
        open_graded_window(TEST, self.logger)
        await self._km_boot("boot1")

        await self._step_first_read()
        await self._step_round1()
        await self._cold_reset(0, "boot2")
        await self._step_round2()
        await self._cold_reset(0, "boot3")
        await self._step_handover_mask()
        await self._cold_reset(0, "boot4")
        await self._step_quiet()
        await self._step_single_rail()
        await self._step_two_rail()
        self._grade_sig_chg()
        await self._step_demote_park()
        await self._cold_reset(0, "boot5")
        await self._step_cold()
        await self._step_notkm()
        b = await self._step_notkm_class()
        await self._step_notkm_twin(b)
        await self._step_tm()
        close_graded_window(self.logger)
        self.chk.finish()

    # --- step 3: boot-1 readout ------------------------------------------------------------

    async def _step_first_read(self) -> None:
        ro = await self._readout("boot1")
        self.r0 = ro
        self.dem_record = ro.words[(m.F_DEM, "reg", 0)] & m.DEM_FIELDS
        self._draw("record.demotion", self.dem_record)
        exp = self._expected(0)
        diff = self._diff(ro, exp)
        graded = (m.F_LC, m.F_DEM, *m.SECRET)
        n_val = sum(
            1
            for f in m.SECRET
            for w in range(m.N_WORDS)
            if ro.words[(f, "val", w)] == exp[(f, "val", w)]
        )
        # A complement word is the bitwise inverse of the value word the DUT returned.
        n_cpl = sum(
            1
            for f in m.SECRET
            for w in range(m.N_WORDS)
            if ro.words[(f, "cpl", w)] == (~ro.words[(f, "val", w)] & WORD_MASK)
            and ro.words[(f, "cpl", w)] == exp[(f, "cpl", w)]
        )
        lc = ro.words[(m.F_LC, "reg", 0)] & m.LC_FIELDS
        dem_cpl = m.dem_groups_cpl(self.dem_record)
        ok = (
            not ro.bad
            and n_val == 32
            and n_cpl == 32
            and lc == m.lc_encode(self.fp.lc_raw)
            and dem_cpl == 2
            and all(not diff[f] for f in graded if f != m.F_DEM)
        )
        self.chk.ok(
            "OTP-RD",
            ok,
            graded_val=n_val,
            graded_cpl=n_cpl,
            lc=_h(lc),
            lc_exp=_h(m.lc_encode(self.fp.lc_raw)),
            dem=_h(self.dem_record),
            dem_groups_cpl=dem_cpl,
            bad=len(ro.bad),
            first=(ro.bad + [f"{_FN[f]}:{d[0]}" for f, d in diff.items() if d])[:4],
        )
        pub_val = sum(
            1
            for f in m.PUBLIC
            for w in range(m.N_WORDS)
            if not ro.bad and ro.words[(f, "val", w)] == exp[(f, "val", w)]
        )
        pub_cpl = sum(
            1
            for f in m.PUBLIC
            for w in range(m.N_WORDS)
            if not ro.bad and ro.words[(f, "cpl", w)] == exp[(f, "cpl", w)]
        )
        self.chk.ctrl(
            "OTP-RD-PUBLIC",
            pub_val == 24 and pub_cpl == 24,
            control=1,
            control_public_val=pub_val,
            control_public_cpl=pub_cpl,
        )
        # Controls of later checks: no lock at boot, every field staged, strap 0.
        self.base_ok = not ro.bad and not any(diff.values())
        self.chk.ctrl(
            "OTP-LOCK-BASE",
            self.base_ok and ro.lock == 0 and ro.lock_cold == 0,
            fields_staged=sum(1 for d in diff.values() if not d),
            lock=_h(ro.lock),
            lock_cold=_h(ro.lock_cold),
        )
        self.logger.info(
            "LOG boot1 status: change=%s irq=%s secure_tm_o=%d", _h(ro.change), _h(ro.irq), self.tm0
        )

    # --- steps 4 to 6: lock rounds ------------------------------------------------------

    async def _triple(self, reg: int, value: int) -> list[kp.PokeResult]:
        ops: list[kp.PokeOp] = []
        for _ in range(3):
            ops += [kp.wr(reg, value), kp.rd(reg)]
        return await self._run(ops)

    async def _pair(self, value: int) -> list[kp.PokeResult]:
        return await self._run(
            [
                kp.wr(m.A_READ_LOCK, value),
                kp.wr(m.A_READ_LOCK_COLD, value),
                kp.rd(m.A_READ_LOCK),
                kp.rd(m.A_READ_LOCK_COLD),
            ]
        )

    def _grade_lock(
        self,
        rnd: str,
        ro: Readout,
        m_w: int,
        m_c: int,
        writes: list[kp.PokeResult],
        triple_reads: list[int],
        w0_kept: int = 1,
    ) -> None:
        eff = m_w | m_c
        diff = self._diff(ro, self._expected(eff))
        problems = self._bad_under(ro, eff)
        problems += [f"write op {r.index} slv={r.slv} dec={r.dec}" for r in writes if not _ok(r)]
        locked = [f for f in range(m.N_FIELDS) if (eff >> f) & 1]
        unlocked = [f for f in range(m.N_FIELDS) if not (eff >> f) & 1]
        # The warm-lock zero read of a public identity belongs to the open owner.
        ctl = [f for f in locked if f in m.PUBLIC and (m_w >> f) & 1 and not (m_c >> f) & 1]
        graded_zero = sum(1 for f in locked if f not in ctl and not diff[f])
        ctl_zero = sum(1 for f in ctl if not diff[f])
        unlocked_ok = sum(1 for f in unlocked if not diff[f])
        problems += [f"{_FN[f]}: {d[0]}" for f, d in diff.items() if d and f not in ctl]
        if (ro.lock & m.LOCK_FIELDS) != m_w or (ro.lock_cold & m.LOCK_FIELDS) != m_c:
            problems.append(f"lock regs {_h(ro.lock)},{_h(ro.lock_cold)} != {_h(m_w)},{_h(m_c)}")
        if not w0_kept:
            problems.append("a write of 0 cleared a lock bit")
        if any(v != triple_reads[0] for v in triple_reads):
            problems.append(f"triple-write reads differ: {[_h(v) for v in triple_reads]}")
        self.chk.ok(
            "OTP-LOCK",
            not problems,
            round=rnd,
            m_w=f"0x{m_w:03x}",
            m_c=f"0x{m_c:03x}",
            eff=f"0x{eff:03x}",
            locked_zero=graded_zero,
            unlocked_ok=unlocked_ok,
            w0_kept=w0_kept,
            triple_write_reads=",".join(f"0x{v:03x}" for v in triple_reads),
            first=problems[:4],
        )
        if ctl:
            self.chk.ctrl(
                "OTP-LOCK-PUBLIC-WARM",
                ctl_zero == len(ctl),
                control=1,
                round=rnd,
                fields=[_FN[f] for f in ctl],
            )
        if rnd in ("warm_only", "cold_only"):
            # Each register alone is graded on a field outside its mask.
            self.chk.ctrl("OTP-LOCK-OUTSIDE", unlocked_ok >= 1, round=rnd, outside=len(unlocked))

    def _triple_vals(
        self, res: list[kp.PokeResult], reg_mask: int = m.LOCK_FIELDS
    ) -> tuple[list[int], list[kp.PokeResult]]:
        reads = [r.value & reg_mask for r in res[1::2]]
        bad = [r for r in res if not _ok(r)]
        return reads, bad

    async def _step_round1(self) -> None:
        a, na = self.masks["a"], self.masks["not_a"]
        t = await self._triple(m.A_READ_LOCK, a)
        reads, bad = self._triple_vals(t)
        ro = await self._readout("r1_warm_only")
        self._grade_lock("warm_only", ro, a, 0, bad, reads)
        t = await self._triple(m.A_READ_LOCK_COLD, na)
        reads, bad = self._triple_vals(t)
        ro = await self._readout("r1_disjoint")
        self._grade_lock("disjoint", ro, a, na, bad, reads)
        z = await self._pair(0)
        kept = int((z[2].value & m.LOCK_FIELDS, z[3].value & m.LOCK_FIELDS) == (a, na))
        ro = await self._readout("r1_w0")
        self._grade_lock(
            "w0", ro, a, na, [r for r in z if not _ok(r)], [z[2].value & m.LOCK_FIELDS], kept
        )

    async def _step_round2(self) -> None:
        a, na = self.masks["a"], self.masks["not_a"]
        r = await self._run([kp.rd(m.A_READ_LOCK), kp.rd(m.A_READ_LOCK_COLD)])
        self.chk.ctrl(
            "OTP-LOCK-COLD-CLEAR",
            all(_ok(x) for x in r) and not (r[0].value | r[1].value) & m.LOCK_FIELDS,
            lock=_h(r[0].value),
            lock_cold=_h(r[1].value),
        )
        t = await self._triple(m.A_READ_LOCK_COLD, a)
        reads, bad = self._triple_vals(t)
        ro = await self._readout("r2_cold_only")
        self._grade_lock("cold_only", ro, 0, a, bad, reads)
        t = await self._triple(m.A_READ_LOCK, na)
        reads, bad = self._triple_vals(t)
        ro = await self._readout("r2_swap")
        self._grade_lock("swap", ro, na, a, bad, reads)
        z = await self._pair(0)
        kept = int((z[2].value & m.LOCK_FIELDS, z[3].value & m.LOCK_FIELDS) == (na, a))
        ro = await self._readout("r2_w0")
        self._grade_lock(
            "w0", ro, na, a, [x for x in z if not _ok(x)], [z[2].value & m.LOCK_FIELDS], kept
        )
        z = await self._pair(m.LOCK_ALL)
        ro = await self._readout("r2_all")
        self._grade_lock(
            "all",
            ro,
            m.LOCK_ALL,
            m.LOCK_ALL,
            [x for x in z if not _ok(x)],
            [z[2].value & m.LOCK_FIELDS],
        )

    async def _step_handover_mask(self) -> None:
        mask = m.SECRET_MASK
        t = await self._triple(m.A_READ_LOCK, mask)
        reads, bad = self._triple_vals(t)
        ro = await self._readout("boot3_handover_mask")
        diff = self._diff(ro, self._expected(mask))
        resp_bad = self._bad_under(ro, mask)
        secret_zero = sum(1 for f in m.SECRET if not diff[f])
        public_ok = sum(1 for f in m.PUBLIC if not diff[f])
        ok = (
            not resp_bad
            and not bad
            and secret_zero == 4
            and public_ok == 3
            and not diff[m.F_LC]
            and not diff[m.F_DEM]
            and reads == [mask] * 3
        )
        self.chk.ok(
            "OTP-HANDOVER-MASK",
            ok,
            control=1,
            m=f"0x{mask:03x}",
            secret_zero=secret_zero,
            control_public_ok=public_ok,
            reads=",".join(f"0x{v:03x}" for v in reads),
        )

    # --- steps 7 to 9: quiet window and HK-OTP legs ------------------------------------------

    async def _step_quiet(self) -> None:
        r = await self._run(
            [
                kp.rd(m.A_CHANGE),
                kp.rd(m.A_IRQ_STATUS),
                kp.delay(QUIET),
                kp.rd(m.A_CHANGE),
                kp.rd(m.A_IRQ_STATUS),
            ]
        )
        reads = [x for x in r if x.op.reports]
        vals = [x.value for x in reads]
        self.quiet_ok = all(_ok(x) for x in reads) and not (
            (vals[0] | vals[2]) & m.CHANGE_FIELDS or (vals[1] | vals[3]) & m.IRQ_OTP
        )
        self.chk.ctrl(
            "OTP-QUIET",
            self.quiet_ok,
            boot="boot4",
            change=[_h(vals[0]), _h(vals[2])],
            irq=[_h(vals[1]), _h(vals[3])],
        )

    async def _flip(self, mask: int) -> int:
        """Hold ``mask`` XORed into the KM OTP input for FLIP_CYCLES clocks (HK-OTP)."""
        dut = cocotb.top
        dut.km_otp_flip_mask_i.value = mask
        await RisingEdge(dut.clk_i)
        dut.km_otp_flip_en_i.value = 1
        active = 0
        held = 0
        for _ in range(FLIP_CYCLES):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            active += self.rd(dut.km_otp_flip_active_o)
            held += 1 - self.rd_known(dut.km_otp_input_live_o)
        await RisingEdge(dut.clk_i)
        dut.km_otp_flip_en_i.value = 0
        await ClockCycles(dut.clk_i, 4)
        await ReadOnly()
        still = self.rd(dut.km_otp_flip_active_o)
        live = self.rd_known(dut.km_otp_input_live_o)
        await RisingEdge(dut.clk_i)
        dut.km_otp_flip_mask_i.value = 0
        # The KM input differs from the live OTP word while the flip holds it
        # and equals it again after the release.
        if active == 0 or held == 0 or still or not live:
            raise AssertionError(
                f"HK-OTP hold did not follow the enable: active clocks={active}, "
                f"input off the live value for {held} clocks, after release active={still} "
                f"input live={live}"
            )
        return active

    async def _leg(self, label: str, pts: list[m.FlipPoint], *, single: bool) -> Leg:
        """Control reads, one HK-OTP flip at the sync, bounded poll, readback, W1C."""
        leg = Leg(label, pts)
        leg.exp = 0 if single else sum(1 << p.f for p in pts)
        mask = m.flip_mask([p.tup() for p in pts])
        o = _Ops()
        o.add(kp.rd(m.A_DEMOTION), "pre_dem")
        o.add(kp.rd(m.A_IRQ_STATUS), "pre_irq")
        o.add(kp.rd(m.A_CHANGE), "pre_change")
        o.add(kp.sync())
        if single:
            o.add(kp.poll(m.A_IRQ_STATUS, m.IRQ_OTP_SIGINT, m.IRQ_OTP_SIGINT, POLL_LOADS), "poll")
        else:
            o.add(kp.poll(m.A_CHANGE, leg.exp, leg.exp, POLL_LOADS), "poll")
            o.add(
                kp.poll(m.A_IRQ_STATUS, m.IRQ_OTP_CHANGE, m.IRQ_OTP_CHANGE, POLL_LOADS), "poll_irq"
            )
        o.add(kp.rd(m.A_IRQ_STATUS), "irq")
        o.add(kp.rd(m.A_CHANGE), "change")
        if single:
            o.add(kp.wr(m.A_IRQ_STATUS, m.IRQ_OTP_SIGINT))
            o.add(kp.rd(m.A_IRQ_STATUS), "w1c_sig")
        o.add(kp.wr(m.A_IRQ_STATUS, m.IRQ_OTP_CHANGE))
        o.add(kp.wr(m.A_CHANGE, m.CHANGE_FIELDS if single else leg.exp))
        o.add(kp.rd(m.A_IRQ_STATUS), "w1c_irq")
        o.add(kp.rd(m.A_CHANGE), "w1c_change")

        async def on_sync(_k: int) -> None:
            leg.active = await self._flip(mask)
            return None

        r = await self._run(o.ops, on_sync=on_sync)
        leg.bad = [
            f"{label} op {x.index} ({x.op.name}) not a clean OKAY"
            for x in r
            if x.op.reports and not _ok(x)
        ]
        v = o.values(r)
        leg.pre_dem, leg.pre_irq, leg.pre_change = v["pre_dem"], v["pre_irq"], v["pre_change"]
        leg.poll, leg.poll_irq = v["poll"], v.get("poll_irq", 0)
        leg.irq, leg.change = v["irq"], v["change"]
        leg.w1c_change = v["w1c_change"]
        leg.w1c_irq = v["w1c_sig"] if single else v["w1c_irq"]
        if single:
            self.chk.obs(
                "OTP-SIG-CHANGE",
                leg=label,
                change=_h(leg.change),
                irq_change=int(bool(leg.irq & m.IRQ_OTP_CHANGE)),
            )
        self.logger.info(
            "LOG HK-OTP %s points=%s mask_bits=%d active_clocks=%d",
            label,
            ",".join(p.text() for p in pts),
            bin(mask).count("1"),
            leg.active,
        )
        return leg

    async def _step_single_rail(self) -> None:
        self.sig_legs = [
            await self._leg(f"sig.{p.text()}", [p], single=True) for p in self.rep.single
        ]

    async def _step_two_rail(self) -> None:
        self.chg_legs = [
            await self._leg(f"chg.{p.text()}", [p], single=False) for p in self.rep.double
        ]
        self.multi_leg = await self._leg("chg.multi", list(self.rep.multi), single=False)

    def _pre_zero(self, leg: Leg) -> bool:
        return not (leg.pre_irq & m.IRQ_OTP) and not (leg.pre_change & m.CHANGE_FIELDS)

    def _chg_ok(self, leg: Leg) -> tuple[bool, dict]:
        change = leg.change & m.CHANGE_FIELDS
        sig = bool((leg.irq | leg.poll_irq) & m.IRQ_OTP_SIGINT)
        ok = (
            not leg.bad
            and (leg.poll & leg.exp) == leg.exp
            and change == leg.exp
            and bool(leg.irq & m.IRQ_OTP_CHANGE)
            and not sig
            and not (leg.w1c_change & m.CHANGE_FIELDS)
            and not (leg.w1c_irq & m.IRQ_OTP_CHANGE)
        )
        info = {
            "sigint": int(sig),
            "change_bits": f"0x{change:03x}",
            "exp_bits": f"0x{leg.exp:03x}",
            "irq": int(bool(leg.irq & m.IRQ_OTP_CHANGE)),
            "w1c_after": f"{leg.w1c_change & m.CHANGE_FIELDS},{int(bool(leg.w1c_irq & m.IRQ_OTP_CHANGE))}",
        }
        return ok, info

    def _grade_sig_chg(self) -> None:
        chg_by_f = {leg.pts[0].f: leg for leg in self.chg_legs}
        sig_by_f: dict[int, list[Leg]] = {}
        for leg in self.sig_legs:
            sig_by_f.setdefault(leg.pts[0].f, []).append(leg)
        for leg in self.sig_legs:
            p = leg.pts[0]
            self.chk.ctrl(
                "OTP-SIG-PRE",
                self._pre_zero(leg),
                leg=leg.label,
                irq=_h(leg.pre_irq),
                change=_h(leg.pre_change),
            )
            twin = chg_by_f[p.f]
            self.chk.ctrl(
                "OTP-SIG-TWIN",
                not ((twin.irq | twin.poll_irq) & m.IRQ_OTP_SIGINT),
                field=_FN[p.f],
                twin_sigint=int(bool(twin.irq & m.IRQ_OTP_SIGINT)),
            )
            sig = bool(leg.poll & m.IRQ_OTP_SIGINT)
            held = bool(leg.irq & m.IRQ_OTP_SIGINT)
            w1c = int(bool(leg.w1c_irq & m.IRQ_OTP_SIGINT))
            self.chk.ok(
                "OTP-SIG",
                not leg.bad and sig and held and not w1c,
                field=_FN[p.f],
                word=p.word,
                bit=p.bit,
                rail=p.rail,
                sigint=int(sig),
                w1c=w1c,
                held=int(held),
                quiet_ctrl=int(self.quiet_ok),
            )
        for leg in [*self.chg_legs, self.multi_leg]:
            self.chk.ctrl(
                "OTP-CHG-PRE",
                self._pre_zero(leg),
                leg=leg.label,
                irq=_h(leg.pre_irq),
                change=_h(leg.pre_change),
            )
            ok, info = self._chg_ok(leg)
            if leg is self.multi_leg:
                self.chk.ok(
                    "OTP-CHG",
                    ok,
                    fields=[_FN[p.f] for p in leg.pts],
                    both_rail=1,
                    multi_k=len(leg.pts),
                    multi_bits_set=bin(leg.change & leg.exp).count("1"),
                    **info,
                )
                continue
            f = leg.pts[0].f
            self.chk.ctrl(
                "OTP-CHG-TWIN",
                all(bool(s.poll & m.IRQ_OTP_SIGINT) for s in sig_by_f[f]),
                field=_FN[f],
            )
            self.chk.ok(
                "OTP-CHG",
                ok,
                field=_FN[f],
                both_rail=1,
                word=leg.pts[0].word,
                bit=leg.pts[0].bit,
                **info,
            )

    # --- steps 10 to 13: demotion, PARK, change with both demotions held ---------------------------

    async def _demote(self, group: int) -> Leg:
        leg = Leg(f"DEMOTE_{group}", [])
        dem_bit = 1 << m.F_DEM
        leg.exp = dem_bit
        o = _Ops()
        o.add(kp.delay(QUIET))
        o.add(kp.rd(m.A_DEMOTION), "pre_dem")
        o.add(kp.rd(m.A_CHANGE), "pre_change")
        o.add(kp.rd(m.A_IRQ_STATUS), "pre_irq")
        o.add(kp.sync())
        o.add(kp.poll(m.A_CHANGE, dem_bit, dem_bit, POLL_LOADS), "poll")
        o.add(kp.poll(m.A_IRQ_STATUS, m.IRQ_OTP_CHANGE, m.IRQ_OTP_CHANGE, POLL_LOADS), "poll_irq")
        o.add(kp.rd(m.A_CHANGE), "change")
        o.add(kp.rd(m.A_IRQ_STATUS), "irq")
        o.add(kp.rd(m.A_DEMOTION), "dem")
        o.add(kp.wr(m.A_CHANGE, dem_bit))
        o.add(kp.wr(m.A_IRQ_STATUS, m.IRQ_OTP_CHANGE))
        o.add(kp.rd(m.A_CHANGE), "w1c_change")
        o.add(kp.rd(m.A_IRQ_STATUS), "w1c_irq")

        async def on_sync(_k: int) -> None:
            seq = SepLccDemoteSeq(group)
            await self.start_seq(seq)
            self.logger.info(
                "LOG DEMOTE_%d host readback demote=%s lock=%s", group, seq.demote, seq.lock
            )
            return None

        r = await self._run(o.ops, on_sync=on_sync)
        leg.bad = [
            f"op {x.index} ({x.op.name}) not a clean OKAY" for x in r if x.op.reports and not _ok(x)
        ]
        v = o.values(r)
        leg.pre_dem, leg.pre_change, leg.pre_irq = v["pre_dem"], v["pre_change"], v["pre_irq"]
        leg.poll, leg.poll_irq = v["poll"], v["poll_irq"]
        leg.change, leg.irq, leg.dem = v["change"], v["irq"], v["dem"]
        leg.w1c_change, leg.w1c_irq = v["w1c_change"], v["w1c_irq"]
        return leg

    def _grade_dem(self, leg: Leg, other_group: int | None) -> int | None:
        pre = leg.pre_dem & m.DEM_FIELDS
        post = leg.dem & m.DEM_FIELDS
        changed = m.dem_groups_changed(pre, post)
        before0 = self._pre_zero(leg)
        self.chk.ctrl(
            "OTP-DEM-PRE", before0, reg=leg.label, change=_h(leg.pre_change), irq=_h(leg.pre_irq)
        )
        group = changed[0] if len(changed) == 1 else None
        ok = (
            not leg.bad
            and (leg.change & m.CHANGE_FIELDS) == leg.exp
            and bool(leg.irq & m.IRQ_OTP_CHANGE)
            and len(changed) == 1
            and m.dem_groups_cpl(post) == 2
            and not (leg.w1c_change & m.CHANGE_FIELDS)
            and not (leg.w1c_irq & m.IRQ_OTP_CHANGE)
            and (other_group is None or group != other_group)
        )
        self.chk.ok(
            "OTP-DEM",
            ok,
            reg=leg.label,
            change_before=int(not before0),
            group=group if group is not None else "none",
            change_bit=f"0x{leg.change & m.CHANGE_FIELDS:03x}",
            irq=int(bool(leg.irq & m.IRQ_OTP_CHANGE)),
            group_changed=len(changed),
            group_cpl=m.dem_groups_cpl(post),
            dem=f"{_h(pre)}->{_h(post)}",
            w1c_after=f"{leg.w1c_change & m.CHANGE_FIELDS},{int(bool(leg.w1c_irq & m.IRQ_OTP_CHANGE))}",
        )
        self.chk.obs(
            "OTP-DEM-GROUP", reg=leg.label, group_index=group if group is not None else "none"
        )
        return group

    async def _step_demote_park(self) -> None:
        da = self.rep.demote_first
        db = 3 - da
        self.dem_a = await self._demote(da)
        g_a = self._grade_dem(self.dem_a, None)
        await self._park()
        r = await self._run(
            [kp.delay(QUIET), kp.rd(m.A_CHANGE), kp.rd(m.A_IRQ_STATUS), kp.rd(m.A_DEMOTION)]
        )
        supp_change, supp_irq, supp_dem = r[1].value, r[2].value, r[3].value
        supp_bad = [x for x in r if x.op.reports and not _ok(x)]
        self.dem_b = await self._demote(db)
        self._grade_dem(self.dem_b, g_a)
        held = (supp_dem & m.DEM_FIELDS) == (self.dem_a.dem & m.DEM_FIELDS)
        twin = bool(self.dem_b.change & (1 << m.F_DEM)) and bool(self.dem_b.irq & m.IRQ_OTP_CHANGE)
        self.chk.ctrl(
            "OTP-SUPP-HELD", held, dem_after_reboot=_h(supp_dem), dem_written=_h(self.dem_a.dem)
        )
        self.chk.ctrl("OTP-SUPP-TWIN", twin, twin_change=int(twin))
        self.chk.ok(
            "OTP-SUPP",
            not supp_bad
            and not (supp_change & m.CHANGE_FIELDS)
            and not (supp_irq & m.IRQ_OTP_CHANGE),
            demote_held=int(held),
            after_reboot_change=_h(supp_change & m.CHANGE_FIELDS),
            after_reboot_irq=int(bool(supp_irq & m.IRQ_OTP_CHANGE)),
            twin_change=int(twin),
        )
        # Step 13: a two-rail flip well after the reboot with both demotions held.
        await self._run([kp.delay(QUIET)])
        leg = await self._leg(f"chg.held.{self.rep.held.text()}", [self.rep.held], single=False)
        both = (leg.pre_dem & m.DEM_FIELDS) == (self.dem_b.dem & m.DEM_FIELDS)
        self.chk.ctrl(
            "OTP-CHG-PRE",
            self._pre_zero(leg),
            leg=leg.label,
            irq=_h(leg.pre_irq),
            change=_h(leg.pre_change),
        )
        self.chk.ctrl("OTP-CHG-HELD", both, dem=_h(leg.pre_dem))
        ok, info = self._chg_ok(leg)
        self.chk.ok("OTP-CHG", ok, field=_FN[self.rep.held.f], both_rail=1, held=1, **info)
        self.dem_last = self.dem_b.dem & m.DEM_FIELDS

    # --- step 14: SEP cold reset ---------------------------------------------------------

    async def _step_cold(self) -> None:
        r = await self._run(
            [kp.delay(QUIET), kp.rd(m.A_DEMOTION), kp.rd(m.A_CHANGE), kp.rd(m.A_IRQ_STATUS)]
        )
        dem, change, irq = r[1].value & m.DEM_FIELDS, r[2].value, r[3].value
        self.chk.ctrl(
            "OTP-COLD-CHANGED", self.dem_last != self.dem_record, dem_before_reset=_h(self.dem_last)
        )
        self.chk.ok(
            "OTP-COLD",
            all(_ok(x) for x in r if x.op.reports)
            and dem == self.dem_record
            and not (change & m.CHANGE_FIELDS)
            and not (irq & m.IRQ_OTP_CHANGE),
            dem_equals_first_boot=int(dem == self.dem_record),
            dem=_h(dem),
            change=_h(change & m.CHANGE_FIELDS),
            irq_change=int(bool(irq & m.IRQ_OTP_CHANGE)),
        )

    # --- steps 15 and 16: other fuse fields, secure test mode -------------------------------

    async def _irq_set_ctrl(self, boot: str) -> bool:
        r = await self._run(
            [
                kp.wr(m.A_IRQ_SET, m.SET_OTP_SIGINT),
                kp.rd(m.A_IRQ_STATUS),
                kp.wr(m.A_IRQ_STATUS, m.IRQ_OTP_SIGINT),
                kp.rd(m.A_IRQ_STATUS),
            ]
        )
        ok = (
            all(_ok(x) for x in r)
            and bool(r[1].value & m.IRQ_OTP_SIGINT)
            and not r[3].value & m.IRQ_OTP_SIGINT
        )
        self.chk.ctrl(
            "OTP-IRQSET-SIGINT", ok, boot=boot, set_read=_h(r[1].value), clear_read=_h(r[3].value)
        )
        return ok

    async def _step_notkm(self) -> None:
        sig_ctrl = await self._irq_set_ctrl("boot5")
        pre = await self._readout("boot5_pre_shadow")
        landed = 0
        host: list[str] = []
        for name, bit in (
            ("REQUIRED_ALGS", self.rep.algs_bit),
            ("REQUIRED_SIGNERS", self.rep.signers_bit),
        ):
            fld = SepEfuseImage.field(name)
            staged = self.fp.words[fld.word]
            want = staged | (1 << bit)
            _, wr_ok = await self._host(SepAxiOp.WRITE, fld.shadow_addr, want)
            got, rd_ok = await self._host(SepAxiOp.READ, fld.shadow_addr)
            landed += int(rd_ok and got == want)
            host.append(f"{name}:{_h(staged)}->{_h(got)} wr_ok={int(wr_ok)} rd_ok={int(rd_ok)}")
        self.logger.info("LOG shadow writes %s", " ".join(host))
        self.notkm_a = pre
        await self._run([kp.delay(QUIET)])
        post = await self._readout("boot5_post_shadow")
        same = sum(1 for s in m.READOUT_SLOTS if pre.words[s] == post.words[s])
        model_eq = sum(1 for d in self._diff(post, self._expected(0)).values() if not d)
        irq_same = (pre.irq & m.IRQ_FIELDS) == (post.irq & m.IRQ_FIELDS)
        dem_raised = bool(self.dem_a.change & (1 << m.F_DEM)) and bool(
            self.dem_b.change & (1 << m.F_DEM)
        )
        self.chk.ctrl(
            "OTP-NOTKM-DEM-RAISED",
            dem_raised,
            demote_a=_h(self.dem_a.change),
            demote_b=_h(self.dem_b.change),
        )
        self.chk.ok(
            "OTP-NOTKM",
            not pre.bad
            and not post.bad
            and landed == 2
            and same == len(m.READOUT_SLOTS)
            and not (post.change & m.CHANGE_FIELDS)
            and not (post.irq & m.IRQ_OTP_SIGINT)
            and irq_same
            and sig_ctrl,
            fuses="required_algs,required_signers",
            landed=landed,
            change=_h(post.change & m.CHANGE_FIELDS),
            sigint_ctrl=int(sig_ctrl),
            sigint=int(bool(post.irq & m.IRQ_OTP_SIGINT)),
            words_same=same,
            fields_model=model_eq,
            irq_same=int(irq_same),
        )

    # --- fuse fields outside the KM interface, programmed and sensed ----------------------

    async def _program(self, bit_addr: int) -> tuple[bool, int]:
        """Program one fuse bit through ``EFUSE_PROGRAM_CTRL``; (done and clean, last read)."""
        dut = cocotb.top
        _, wr_ok = await self._host(SepAxiOp.WRITE, PROGRAM_CTRL_ADDR, program_ctrl_word(bit_addr))
        pg, rd_ok = 0, False
        for _ in range(PROGRAM_POLLS):
            pg, rd_ok = await self._host(SepAxiOp.READ, PROGRAM_CTRL_ADDR)
            if rd_ok and pg & _PG_DONE:
                break
            await ClockCycles(dut.clk_i, PROGRAM_GAP)
        _, clr_ok = await self._host(SepAxiOp.WRITE, PROGRAM_CTRL_ADDR, 0)
        ok = wr_ok and rd_ok and clr_ok and bool(pg & _PG_DONE) and not pg & (_PG_BUSY | _PG_STATUS)
        return ok, pg

    async def _program_bits(self, bits: list[FuseBit]) -> tuple[int, list[str]]:
        """Program ``bits``; each clean program joins the golden of the next sense.

        Returns the number of clean programs and one log entry per bit.
        """
        done = 0
        info: list[str] = []
        for name, w, b in bits:
            fld = SepEfuseImage.field(name)
            addr = 32 * (fld.word + w) + b
            ok, pg = await self._program(addr)
            info.append(f"{name}.w{w}.b{b}@{addr}:ok={int(ok)}:pg={_h(pg)}")
            if not ok:
                continue
            done += 1
            self.model.words[fld.word + w] |= 1 << b
            if name in self.otp_fields:
                self.otp_fields[name] |= 1 << (32 * w + b)
        self.logger.info("LOG fuse program %s", " ".join(info))
        return done, info

    async def _shadow_bits(self, bits: list[FuseBit]) -> tuple[bool, list[str]]:
        """Host shadow readback of each programmed word against the golden image."""
        ok = True
        info: list[str] = []
        for name, w, b in bits:
            fld = SepEfuseImage.field(name)
            want = self.model.words[fld.word + w]
            got, rd_ok = await self._host(SepAxiOp.READ, fld.shadow_addr + 4 * w)
            ok = ok and rd_ok and got == want and bool((got >> b) & 1)
            info.append(f"{name}.w{w}={_h(got)}/{_h(want)}")
        return ok, info

    async def _step_notkm_class(self) -> Readout:
        """Boot B: the drawn class field gains programmed bits; the KM readout is unchanged.

        Boot A is the boot-5 readout before the shadow writes. The SEP cold reset
        between A and B senses the array again, so the shadow writes of
        CHK-OTP-NOTKM are gone and the class bits are the only shadow difference.
        Both readouts are taken before any KM read-lock write.
        """
        leg = self.class_leg
        a = self.notkm_a
        done, prog = await self._program_bits(leg.bits)
        await self._cold_reset(0, "boot6")
        b = await self._readout("boot6_notkm_class")
        shadow_ok, shadow = await self._shadow_bits(leg.bits)
        self.chk.ctrl(
            "OTP-NOTKM-CLASS-PROG",
            done == len(leg.bits) and shadow_ok,
            cls=leg.cls,
            field=leg.fuse_field,
            programmed=f"{done}/{len(leg.bits)}",
            shadow=shadow,
        )
        unlocked = a.lock == 0 and a.lock_cold == 0 and b.lock == 0 and b.lock_cold == 0
        self.chk.ctrl(
            "OTP-NOTKM-CLASS-UNLOCKED",
            unlocked,
            lock_a=_h(a.lock),
            lock_cold_a=_h(a.lock_cold),
            lock_b=_h(b.lock),
            lock_cold_b=_h(b.lock_cold),
        )
        ref = dict(a.words)
        exp = self._expected(0)
        diff = self._diff(b, exp)
        moved = [
            f"{_FN[s[0]]}.{s[1]}{s[2]}={_h(b.words[s])}!={_h(ref[s])}"
            for s in m.READOUT_SLOTS
            if b.words[s] != ref[s]
        ]
        self.chk.ok(
            "OTP-NOTKM-CLASS",
            not a.bad and not b.bad and not moved and not any(diff.values()),
            cls=leg.cls,
            field=leg.fuse_field,
            bits=[f"w{w}.b{bb}" for _, w, bb in leg.bits],
            words=len(m.READOUT_SLOTS),
            words_same=len(m.READOUT_SLOTS) - len(moved),
            fields_model=sum(1 for d in diff.values() if not d),
            bad=len(a.bad) + len(b.bad),
            first=(a.bad + b.bad + moved + [f"{_FN[f]}:{d[0]}" for f, d in diff.items() if d])[:4],
        )
        return b

    async def _step_notkm_twin(self, b: Readout) -> None:
        """Sensitivity twin: one programmed public-identity bit moves its readout words."""
        leg = self.class_leg
        done, _prog = await self._program_bits([leg.pub])
        await self._cold_reset(0, "boot7")
        c = await self._readout("boot7_public_twin")
        val = (leg.pub_f, "val", leg.pub_word)
        cpl = (leg.pub_f, "cpl", leg.pub_word)
        mask = 1 << leg.pub_bit
        others = [s for s in m.READOUT_SLOTS if s not in (val, cpl) and c.words[s] != b.words[s]]
        model = sum(1 for d in self._diff(c, self._expected(0)).values() if not d)
        self.chk.ctrl(
            "OTP-NOTKM-CLASS-SENS",
            done == 1
            and not c.bad
            and c.words[val] == b.words[val] | mask
            and c.words[cpl] == b.words[cpl] & ~mask & WORD_MASK
            and not others
            and model == m.N_FIELDS,
            field=_FN[leg.pub_f],
            word=leg.pub_word,
            bit=leg.pub_bit,
            val=f"{_h(b.words[val])}->{_h(c.words[val])}",
            cpl=f"{_h(b.words[cpl])}->{_h(c.words[cpl])}",
            others_moved=len(others),
            fields_model=model,
        )

    async def _step_tm(self) -> None:
        tm = await self._cold_reset(1, "boot8")
        sig_ctrl = await self._irq_set_ctrl("boot8")
        ro = await self._readout("boot8_secure_tm")
        r = await self._run([kp.delay(QUIET), kp.rd(m.A_IRQ_STATUS), kp.rd(m.A_CHANGE)])
        exp = self._expected(0, tm=1)
        diff = self._diff(ro, exp)
        secret_val = [ro.words[(f, "val", w)] for f in m.SECRET for w in range(m.N_WORDS)]
        secret_cpl = [ro.words[(f, "cpl", w)] for f in m.SECRET for w in range(m.N_WORDS)]
        public_ok = sum(1 for f in m.PUBLIC if not diff[f])
        lc_dem_ok = not diff[m.F_LC] and not diff[m.F_DEM]
        sig = bool((ro.irq | r[1].value) & m.IRQ_OTP_SIGINT)
        twin = sum(1 for f in m.SECRET if not self._diff(self.r0, self._expected(0))[f])
        self.chk.ctrl(
            "OTP-TM-TWIN", twin == 4 and self.tm0 == 0, twin_secret_staged=twin, tm_boot1=self.tm0
        )
        self.chk.ok(
            "OTP-TM",
            tm == 1
            and not ro.bad
            and all(_ok(x) for x in r if x.op.reports)
            and all(v == 0 for v in secret_val)
            and all(v == WORD_MASK for v in secret_cpl)
            and public_ok == 3
            and lc_dem_ok
            and not sig
            and sig_ctrl,
            tm=tm,
            secret_val=_h(max(secret_val)),
            secret_cpl=_h(min(secret_cpl)),
            sigint_ctrl=int(sig_ctrl),
            sigint=int(sig),
            public_ok=public_ok,
            lc_dem_ok=int(lc_dem_ok),
            twin_secret_staged=twin,
            change=_h(r[2].value & m.CHANGE_FIELDS),
        )
