# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM crossbar decode table and the KM eFuse window against the host eFuse path.

no_cpu (``lsu_stub_all_live``), POKE image (``+km_rom_hex=km_rom_poke.parhex``),
real fuse sense of a per-leaf fuse image (no ``+skip_fuse_sense``). The image is
staged at t=0 by ``dv_sim_prestage.py`` from ``env/sep_km_fuse_plan.py``; the
test rebuilds the same plan from the same seed for its golden.

Contract (spec only):
``hw/ip/key_manager/regs/gen/adoc/memory_map.adoc`` (decode table and notes;
note [2]: the range 0x11600 to 0x11FFF is inside the eFuse window and answers
SLVERR with 0xBADCAB1E); ``hw/ip/key_manager/doc/index.adoc`` "Memory Map";
``hw/ip/key_manager/doc/architecture.adoc`` "OTP Inputs and Readout";
``hw/sys/sep/doc/otp_fuse_controller.adoc``; ``hw/ip/efuse/regs/gen/adoc/
efuse_interface_ctrl.adoc``; ``hw/ip/efuse/doc/architecture.adoc`` "Secure Test
Mode (secure_tm_i)"; ``hw/sys/sep/doc/test_mode.adoc`` "Protection While Active".

The KM CPU sees only the read data and IRQ_STATUS.AXI_SLVERR / AXI_DECERR. The
POKE image clears both bits before each access, reads them back (the clear
control) and ORs them over the settle reads after the access.

Checks (anchor):
  CHK-XBAR        hole and past-extent cells of the non-eFuse rows answer
                  SLVERR, data 0x0, by read and write (POKE result + IRQ_STATUS)
  CHK-XBAR-RSV    reserved rows outside the eFuse window answer DECERR, data
                  0xBADCAB1E, by read and write (POKE result + IRQ_STATUS)
  CHK-XBAR-EFUSE  eFuse window offsets outside its three maps answer SLVERR,
                  data 0xBADCAB1E, by read and write (POKE result + IRQ_STATUS)
  CHK-XBAR-SIZE   ROM top, SRAM base and top, the SRAM top store and the first
                  and last decoded word of each row answer clean (POKE result)
  CHK-EFW-RD      40 KM reads of the eFuse maps equal the host reads of the same
                  register (KM readback vs host readback, staged fuse model)
  CHK-EFW-RD-TM   the same with ``secure_tm_o`` = 1
  CHK-EFW-PROG    a KM program of an unlocked spare bit completes and lands;
                  program_done is graded on the first program after the boot
                  cold reset, the second program's done is logged (path
                  readback + host OTP readback)
  CHK-EFW-DENY    a KM program of a write-locked bit is refused, no bit lands
                  (``efuse_req_error`` readback + host OTP readback)
  CHK-EFW-TM      in secure test mode the KM and host program results, write
                  responses and efuse_addr echoes are equal, each KM eFuse write
                  leaves on efuse_req_o in order, a blocked OTP read returns 0
                  on both paths, and no bit lands (path readback, ``KM-BUS``
                  write handshakes, shadow frontdoor, ``efuse_shadow_probe_o``)
  CHK-REMAP-BUS   ``efuse_req_o`` after the remap keeps bits [11:0] of the KM
                  offset and holds one constant [31:12] (``KM-BUS`` tap)

Logged only (no verdict): ``OBS-XBAR-UNSTATED`` (the first word of the mailbox,
the DRBG sampler and the five key windows, which have no stated read response),
``CTL-XBAR`` (cells another open test grades: 0x4000, 0x13108 store, 0x11574,
0x1000_0000), ``CTL-EFW-PROG`` / ``CTL-EFW-DENY`` / ``CTL-EFW-TM`` (the host
path line of each program check), ``OBS-EFW-TM-TUPLE`` (the secure test program
status values), ``OBS-REMAP-BASE`` (the value of ``OTP_EFUSE_REMAP_BASE``),
``OBS-XBAR-SRAM-TOP`` (the SRAM top readback after the store).

Every drawn value is a pure function of the seed (``SepSeededRng``), and each
draw is logged on a ``DRAW`` line.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env import sep_km_poke as kp
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SHADOW_BASE, WORD_BITS, WORD_MASK, SepEfuseImage
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_km_fuse_plan import T_XBAR_EFUSE, FuseTarget, KmFusePlan, plan
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, EFUSE_MMR, ip_c_header
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_poke_seq import SepKmPoke

TEST = T_XBAR_EFUSE

# --- generated maps (RDL exports) -------------------------------------------


def _load_py(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_KM_GEN_PY = ip_c_header("key_manager").parents[1] / "py"
_KM_MAP = _load_py(_KM_GEN_PY / "key_manager_memory_map.py", "km_xbar_memory_map")
_KM_CSR = _load_py(_KM_GEN_PY / "km_csr_reg.py", "km_xbar_csr_reg")
_KM_MBX = _load_py(_KM_GEN_PY / "km_mailbox_km_reg.py", "km_xbar_mailbox_km_reg")
_KM_DRBG = _load_py(_KM_GEN_PY / "km_drbg_sampler_reg.py", "km_xbar_drbg_reg")
_KM_ABR = _load_py(_KM_GEN_PY / "abr_wrapper_key_reg.py", "km_xbar_abr_reg")

_ROWS: tuple[dict, ...] = tuple(_KM_MAP.VIEWS["km-cpu"]["rows"])
_ROW = {r["key"]: r for r in _ROWS}

# Register modules of the rows whose extent has a hole: the hole word is the
# lowest word inside the decoded extent that the register map assigns to no
# register.
_HOLE_REGS = {"main:kmcsr": _KM_CSR, "main:abr_wrapper_key": _KM_ABR}
# Decoded rows whose first word has no stated read response: the write-only
# mailbox word, the DRBG sampler DATA register (a read takes a stream word) and
# the key-share words of the five key windows.
_FIRST_UNSTATED = (
    "main:mailbox_km",
    "main:drbg_sampler",
    "main:otbn_wrapper_key",
    "main:aes_wrapper_key",
    "main:kmac_wrapper_key",
    "main:hmac_wrapper_key",
    "main:abr_wrapper_key",
)

KM_ROM_BASE = _ROW["main:rom"]["base"]
KM_ROM_TOP = _ROW["main:rom"]["end"] - 3
KM_SRAM_BASE = _ROW["main:sram"]["base"]
KM_SRAM_TOP = _ROW["main:sram"]["end"] - 3
KM_EFUSE_MAP = _ROW["main:otp_efuse_map"]["base"]
KM_EFUSE_CTRL = _ROW["main:otp_efuse_ctrl"]["base"]
KM_EFUSE_MMR = _ROW["main:otp_efuse_mmr"]["base"]
KM_EFUSE_WINDOW = 0x1000  # 4 KiB OTP/eFuse window (architecture.adoc, OTP Inputs and Readout)
KM_IRQ_ENABLE = _ROW["main:kmcsr"]["base"] + _KM_CSR.IRQ_ENABLE_REG_ADDR
KM_MBX_STATUS = _ROW["main:mailbox_km"]["base"] + _KM_MBX.KM_STATUS_REG_ADDR
KM_DRBG_STATUS = _ROW["main:drbg_sampler"]["base"] + _KM_DRBG.STATUS_REG_ADDR
KM_KPV_PAST = _ROW["main:kpv"]["base"] + _ROW["main:kpv"]["occupied_size"]
KM_RSV_ROM_GROWTH = _ROW["reserved_4000"]["base"]
KM_EFUSE_MMR_PAST = KM_EFUSE_MMR + _ROW["main:otp_efuse_mmr"]["occupied_size"]
# A KM address past the whole KM map (``index.adoc``, "Memory Map").
KM_VROM_PROBE = 0x1000_0000
BADCAB = 0xBADC_AB1E

# --- eFuse interface registers (efuse_interface_ctrl.adoc, efuse_mmr) ---------

R_STATUS = "EFUSE_INTERFACE_CTRL_STATUS"
R_PROG = "EFUSE_PROGRAM_CTRL"
R_READ = "EFUSE_READ_CTRL"
R_RDATA = "EFUSE_READ_INTERFACE_READ_DATA"
_CTRL_STATUS_REGS = (R_STATUS, R_PROG, R_READ, R_RDATA)
_TOKEN_STATUS_REGS = (
    "RMA_SIP_TOKEN_MATCH",
    "RMA_CHIPLET_TOKEN_MATCH",
    "SEC_DISABLE_TOKEN_MATCH",
    "TOKEN_MATCH_FAULT",
)


def _mmr_mask(reg: str) -> int:
    """RDL field mask of a token register.

    The three ``*_TOKEN_MATCH`` registers share one generated register type,
    ``EFUSE_MMR_TOKEN_MATCH_reg_t``, so their mask comes from that type.
    """
    try:
        return EFUSE_MMR.mask(reg)
    except KeyError:
        if reg.endswith("_TOKEN_MATCH"):
            return EFUSE_MMR.mask("TOKEN_MATCH")
        raise


def _f(reg: str, name: str) -> int:
    return EFUSE_INTERFACE_CTRL.field_mask(reg, name)


ST_REQ_ERR = _f(R_STATUS, "efuse_req_error")
ST_REQ_ERR_CLR = _f(R_STATUS, "efuse_req_error_clear")
PC_ENABLE = _f(R_PROG, "program_enable")
PC_STATUS = _f(R_PROG, "program_status")
PC_DONE = _f(R_PROG, "program_done")
PC_BUSY = _f(R_PROG, "program_busy")
PC_GO = _f(R_PROG, "efuse_program_go")
PC_DATA = _f(R_PROG, "efuse_data")
PC_ADDR_MASK = _f(R_PROG, "efuse_addr")
PC_ADDR_LSB = EFUSE_INTERFACE_CTRL.field_lsb(R_PROG, "efuse_addr")
RC_ENABLE = _f(R_READ, "read_enable")
RC_STATUS = _f(R_READ, "read_status")
RC_DONE = _f(R_READ, "read_done")
RC_BUSY = _f(R_READ, "read_busy")
RC_GO = _f(R_READ, "efuse_read_go")
RC_ADDR_MASK = _f(R_READ, "efuse_addr")
RC_ADDR_LSB = EFUSE_INTERFACE_CTRL.field_lsb(R_READ, "efuse_addr")

# --- test parameters ----------------------------------------------------------

N_RD_DRAWS = 40
SENSE_BOUND = 20_000
RELEASE_BOUND = 20_000
RESET_HOLD = 20
PROG_POLL_LOADS = 2_000  # KM loads of the bounded program / read waits
HOST_POLL_READS = 400  # host reads of the same waits
TM_POLL_READS = 32  # the secure-test status interval, the same on both paths
# KM loads that look for program_busy = 1 right after the go store. The go
# store and this poll are raw (no IRQ_STATUS settle reads), so the first load
# follows the store directly.
BUSY_RISE_LOADS = 64
LIST_TIMEOUT = 4_000_000
# Host OTP reads that wait for the bit of the second program of a pair to land.
OTP_LAND_READS = 16

_RESP_OF = {(0, 0): "OKAY", (1, 0): "SLVERR", (0, 1): "DECERR"}
_EXP_BITS = {"OKAY": (0, 0), "SLVERR": (1, 0), "DECERR": (0, 1)}


def _km_class(res: kp.PokeResult) -> str:
    return _RESP_OF.get((res.slv, res.dec), "BOTH")


def _bit(value: int, mask: int) -> int:
    return int(bool(value & mask))


def _place(addr: int, lsb: int, mask: int) -> int:
    placed = addr << lsb
    if addr < 0 or placed & ~mask:
        raise ValueError(f"eFuse bit address {addr:#x} does not fit efuse_addr")
    return placed


def _word_bit_addr(tgt: FuseTarget) -> int:
    """The bit address of the first bit of the OTP word that holds ``tgt``."""
    return (tgt.address // WORD_BITS) * WORD_BITS


# --- decode table -------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """One KM bus access of the decode walk and its table cell."""

    win: str
    addr: int
    kind: str
    chk: str  # CHK-XBAR, CHK-XBAR-RSV, CHK-XBAR-EFUSE, SIZE (clean read) or OBS
    d: str = "rd"  # "rd" or "wr"
    resp: str = "OKAY"
    rdata: int | None = None  # None: data not graded
    control: bool = False


def _short(key: str) -> str:
    return key.split(":", 1)[-1].lower()


def _in_efuse_window(addr: int) -> bool:
    return KM_EFUSE_MAP <= addr < KM_EFUSE_MAP + KM_EFUSE_WINDOW


def _hole_word(key: str, base: int, occupied: int) -> int:
    regs = _HOLE_REGS[key]
    assigned = {v for k, v in vars(regs).items() if k.endswith("_REG_ADDR")}
    for off in range(0, occupied, 4):
        if off not in assigned:
            return base + off
    raise AssertionError(f"{key}: the table shows a hole, the register map assigns every word")


def _resp_cell(resp: dict) -> tuple[str, int]:
    return resp["rresp"], int(resp["rdata"]) & WORD_MASK


def _is_control(addr: int, d: str) -> bool:
    """Cells that another open test grades: logged with control=1."""
    if addr in (KM_RSV_ROM_GROWTH, KM_EFUSE_MMR_PAST):
        return True
    return addr == KM_KPV_PAST and d == "wr"


def _both(win: str, addr: int, kind: str, chk: str, resp: str, rdata: int) -> list[Cell]:
    return [
        Cell(win, addr, kind, chk, d, resp, rdata, control=_is_control(addr, d))
        for d in ("rd", "wr")
    ]


def _row_cells(row: dict, rng: SepSeededRng, draws: dict[str, int]) -> list[Cell]:
    key, base, end = row["key"], row["base"], row["end"]
    win = _short(key)
    out: list[Cell] = []
    if row["kind"] == "reserved":
        if _in_efuse_window(base):
            # memory_map.adoc note [2]: the eFuse window answers every offset
            # outside its register maps with SLVERR and 0xBADCAB1E.
            chk, resp, rdata = "CHK-XBAR-EFUSE", "SLVERR", BADCAB
        else:
            resp, rdata = _resp_cell(row["hole_responses"][0][1])
            chk = "CHK-XBAR-RSV"
        drawn = base + 4 * rng.randrange(1, (end + 1 - base) // 4 - 1)
        draws[f"{win}.drawn"] = drawn
        for kind, addr in (("first", base), ("last", end - 3), ("drawn", drawn)):
            out += _both(win, addr, kind, chk, resp, rdata)
        return out
    occupied = row["occupied_size"]
    first_chk = "OBS" if key in _FIRST_UNSTATED else "SIZE"
    out.append(Cell(win, base, "first", first_chk))
    out.append(Cell(win, base + occupied - 4, "last_decoded", "SIZE"))
    holes = [h for _, h in row["hole_responses"] if h["rresp"] != "FORWARD"]
    if holes:
        resp, rdata = _resp_cell(holes[0])
        out += _both(win, _hole_word(key, base, occupied), "hole", "CHK-XBAR", resp, rdata)
    if row["past_response"] is not None and occupied < row["aperture_size"]:
        resp, rdata = _resp_cell(row["past_response"])
        chk = "CHK-XBAR-EFUSE" if _in_efuse_window(base) else "CHK-XBAR"
        past = base + occupied
        out += _both(win, past, "past_extent", chk, resp, rdata)
        if end - 3 != past:
            out += _both(win, end - 3, "span_last", chk, resp, rdata)
        if _in_efuse_window(base) and end - 3 - past >= 8:
            drawn = past + 4 * rng.randrange(1, (end + 1 - past) // 4 - 1)
            draws[f"{win}.gap_drawn"] = drawn
            out += _both(win, drawn, "gap_drawn", chk, resp, rdata)
    return out


# --- test -----------------------------------------------------------------------


@dataclass
class _Walk:
    """Results of the decode walk, graded after the in-map controls ran."""

    cells: list[tuple[Cell, kp.PokeResult]] = field(default_factory=list)


@pyuvm.test()
class sep_km_crossbar_efuse_window_rand_test(sep_base_test):
    """KM decode table cells, and the KM eFuse window equal to the host eFuse path."""

    required_evidence = (
        "CHK-XBAR",
        "CHK-XBAR-RSV",
        "CHK-XBAR-EFUSE",
        "CHK-XBAR-SIZE",
        "CHK-EFW-RD",
        "CHK-EFW-RD-TM",
        "CHK-EFW-PROG",
        "CHK-EFW-DENY",
        "CHK-EFW-TM",
        "CHK-REMAP-BUS",
    )

    # --- small helpers ------------------------------------------------------

    def _draw(self, name: str, value) -> None:
        if isinstance(value, int):
            self.logger.info("DRAW %s=0x%x", name, value)
        else:
            self.logger.info("DRAW %s=%s", name, value)

    def _fail(self, chk: str, problems: list[str]) -> None:
        if problems:
            for p in problems:
                self.logger.error("%s FAIL: %s", chk, p)
            raise AssertionError(f"{chk} FAIL: " + "; ".join(problems[:6]))

    async def _host(self, op: SepAxiOp, addr: int, data: int = 0) -> tuple[int, str]:
        """One host access; returns (read data, response class)."""
        if op is SepAxiOp.READ:
            seq = SepAxiAccessSeq(
                "km_xbar_host_rd",
                op=op,
                addr=addr,
                length=4,
                size=2,
                allow_ungraded_read_resp=True,
            )
        else:
            seq = SepAxiAccessSeq(
                "km_xbar_host_wr",
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
        cls = "OKAY" if seq.resp_ok else {2: "SLVERR", 3: "DECERR"}.get(seq.resp_code, "OTHER")
        return seq.rdata & WORD_MASK, cls

    async def _hr(self, reg: str) -> int:
        data, _ = await self._host(SepAxiOp.READ, EFUSE_INTERFACE_CTRL.addr(reg))
        return data

    async def _hw(self, reg: str, value: int) -> None:
        _, cls = await self._host(SepAxiOp.WRITE, EFUSE_INTERFACE_CTRL.addr(reg), value)
        trace = getattr(self, "_wr_trace", None)
        if trace is not None:
            trace["host"].append((reg, cls))

    @staticmethod
    def _km(reg: str) -> int:
        """KM address of an eFuse interface register (same bits [11:0] as the host)."""
        return KM_EFUSE_MAP + (EFUSE_INTERFACE_CTRL.addr(reg) - SHADOW_BASE)

    async def _run(self, ops: list[kp.PokeOp], **kw) -> list[kp.PokeResult]:
        res = await self.poke.run(ops, timeout_cycles=LIST_TIMEOUT, **kw)
        trace = getattr(self, "_wr_trace", None)
        if trace is not None:
            for r in res:
                addr = r.op.words[1] if r.op.code == kp.OP_WR else None
                if addr is not None and _in_efuse_window(addr):
                    trace["km"].append((addr, _km_class(r)))
        return res

    async def _run_chunked(self, ops: list[kp.PokeOp]) -> list[kp.PokeResult]:
        """Run ``ops`` in as few lists as the image buffer allows."""
        out: list[kp.PokeResult] = []
        chunk: list[kp.PokeOp] = []
        for op in ops:
            nxt = chunk + [op]
            if kp.list_words(nxt) > kp.BUF_WORDS or kp.list_slots(nxt) > kp.N_SLOTS:
                out.extend(await self._run(chunk, allow_unknown=True))
                chunk = [op]
            else:
                chunk = nxt
        if chunk:
            out.extend(await self._run(chunk, allow_unknown=True))
        return out

    async def _wait_sep_reset_release(self) -> int:
        dut = cocotb.top
        for cycle in range(1, RELEASE_BOUND + 1):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True):
                return cycle
        raise AssertionError(
            f"dbg_sep_reset_n_o did not read 1 within {RELEASE_BOUND} clocks after fuse sense"
        )

    def _shadow_probe_word(self, idx: int) -> int:
        mask = WORD_MASK << (WORD_BITS * idx)
        return (self.rd(cocotb.top.efuse_shadow_probe_o, mask) >> (WORD_BITS * idx)) & WORD_MASK

    def _check_staged_identity(self, fp: KmFusePlan) -> None:
        path = Path(os.getcwd()) / "out" / "sep_efuse.hex"
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
        self.logger.info("KM-FUSE-PLAN staged=%s staged_sha256=%s", path, digest)
        if digest != fp.identity():
            raise AssertionError(
                f"staged fuse image {path} sha256={digest} is not the plan image "
                f"{fp.identity()}; the prestage registry entry of {TEST} did not run"
            )

    async def _km_boot(self) -> None:
        """Release the KM with the POKE image; the image disables KM interrupts."""
        await self.poke.release()
        await self.poke.wait_boot()
        r = await self._run([kp.wr(KM_IRQ_ENABLE, 0)])
        self.logger.info("KM IRQ_ENABLE <- 0 (slv=%d dec=%d)", r[0].slv, r[0].dec)

    async def _cold_reset_strap1(self, golden: SepEfuseImage) -> int:
        """Cold reset with the secure test strap set while the reset is held."""
        dut = cocotb.top
        await self.poke.prepare_reset()
        self.write_efuse_image(golden)
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, RESET_HOLD)
        dut.test_en_strap_i.value = 1
        await ClockCycles(dut.clk_i, RESET_HOLD)
        dut.rst_ni.value = 1
        await self.wait_fuse_sense(max_cycles=SENSE_BOUND)
        rel = await self._wait_sep_reset_release()
        self.cfg.reset_done.set()
        await ReadOnly()
        tm = self.rd(dut.secure_tm_o)
        await RisingEdge(dut.clk_i)
        self.logger.info("cold reset strap=1: sep_reset_n release +%d clk, secure_tm_o=%d", rel, tm)
        return tm

    # --- scenario -------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        fp = plan(TEST, seed)
        self.fp = fp
        self.logger.info("DRAW fuse_plan %s", fp.summary())
        for key, tgt in fp.targets.items():
            staged = fp.words[tgt.address // WORD_BITS]
            assert not (staged >> tgt.bit) & 1, f"plan target {key} bit is 1 in the staged word"
            assert staged != 0, f"plan target {key} word is 0 in the staged image"
        # The walk stream is a second pure function of the seed, apart from the plan stream.
        rng = SepSeededRng(seed ^ (732 << 48))
        self._check_staged_identity(fp)
        model = fp.image()
        self.write_efuse_image(model)

        # Boot one: strap 0, real sense.
        dut = cocotb.top
        await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        rel = await self._wait_sep_reset_release()
        tm0 = self.rd(dut.secure_tm_o)
        self.logger.info("boot 1 strap=0: sep_reset_n release +%d clk, secure_tm_o=%d", rel, tm0)
        self.poke = SepKmPoke(self)
        await self._km_boot()

        open_graded_window(TEST, self.logger)
        walk = await self._decode_walk(rng)
        size = await self._size_boundaries(rng)
        vrom = (await self._run([kp.rd(KM_VROM_PROBE)], allow_unknown=True))[0]
        clean = await self._run(
            [kp.rd(KM_MBX_STATUS), kp.rd(KM_DRBG_STATUS), kp.rd(KM_ROM_BASE), kp.rd(KM_SRAM_BASE)]
        )
        rd1 = await self._efw_reads(rng, model, tm=0, bus=True)
        self._grade_walk(seed, walk, size, vrom, clean, rd1)
        self._grade_efw_rd(seed, rd1, tm=0, tm_seen=tm0)
        self._grade_remap(rd1)

        prog = await self._program_pair(rng, fp)
        model.words[fp.targets["km_spare"].address // WORD_BITS] |= 1 << fp.targets["km_spare"].bit
        model.words[fp.targets["host_spare"].address // WORD_BITS] |= (
            1 << fp.targets["host_spare"].bit
        )
        await self._deny_pair(rng, fp, prog)
        close_graded_window(self.logger)

        # Boot two: secure test strap set before the cold reset and held.
        tm1 = await self._cold_reset_strap1(model)
        await self._km_boot()
        open_graded_window(TEST, self.logger)
        rd2 = await self._efw_reads(rng, model, tm=1, bus=False)
        self._grade_efw_rd(seed, rd2, tm=1, tm_seen=tm1, tm_first_boot=tm0)
        tm_res = await self._tm_program_pair(rng, fp)
        close_graded_window(self.logger)

        # Boot three: strap held, fresh sense, read the shadow of every target.
        tm2 = await self._cold_reset_strap1(model)
        await self._grade_tm_shadow(fp, tm_res, prog, tm2)
        await self._km_boot()
        self.result_pass(TEST, seed, len(self.required_evidence))

    # --- steps 4 to 7: decode walk ------------------------------------------

    async def _decode_walk(self, rng: SepSeededRng) -> _Walk:
        rows = list(_ROWS)
        rng.shuffle(rows)
        self._draw("walk.row_order", ",".join(_short(r["key"]) for r in rows))
        draws: dict[str, int] = {}
        cells: list[Cell] = []
        for row in rows:
            cells.extend(_row_cells(row, rng, draws))
        for name, value in draws.items():
            self._draw(f"walk.{name}", value)
        ops: list[kp.PokeOp] = []
        for cell in cells:
            if cell.d == "rd":
                ops.append(kp.rd(cell.addr))
            else:
                data = rng.randrange(1, 1 << WORD_BITS)
                self._draw(f"walk.wdata.0x{cell.addr:05x}", data)
                ops.append(kp.wr(cell.addr, data))
        results = await self._run_chunked(ops)
        return _Walk(list(zip(cells, results, strict=True)))

    async def _size_boundaries(self, rng: SepSeededRng) -> list[kp.PokeResult]:
        data = rng.randrange(1, 1 << WORD_BITS)
        self._draw("size.sram_top_wdata", data)
        res = await self._run(
            [
                kp.rd(KM_ROM_TOP),
                kp.rd(KM_RSV_ROM_GROWTH),
                kp.wr(KM_SRAM_TOP, data),
                kp.rd(KM_SRAM_BASE),
                kp.rd(KM_SRAM_TOP),
            ],
            allow_unknown=True,
        )
        self.logger.info(
            "OBS-XBAR-SRAM-TOP stored=0x%08x read=0x%08x equal=%d",
            data,
            res[4].value,
            int(res[4].value == data),
        )
        return res

    def _grade_walk(
        self,
        seed: int,
        walk: _Walk,
        size: list[kp.PokeResult],
        vrom: kp.PokeResult,
        clean: list[kp.PokeResult],
        rd1: list[dict],
    ) -> None:
        # Controls: the clean in-map reads show both bits at 0, and the in-map
        # eFuse reads answer OKAY, so a 0 bit and an OKAY can be seen.
        ctl_clean = [r for r in clean if not (r.known and r.clean and (r.slv, r.dec) == (0, 0))]
        self._fail(
            "CHK-XBAR",
            [
                f"clean in-map control op {r.index} slv={r.slv} dec={r.dec} clean={int(r.clean)}"
                for r in ctl_clean
            ],
        )
        self.logger.info(
            "CTL-XBAR-CLEAN mbx_status=%s drbg_status=%s rom0=%s sram0=%s (slv=0 dec=0)",
            *(f"0x{r.value:08x}" for r in clean),
        )
        efw_ok = [d for d in rd1 if d["km_cls"] == "OKAY"]
        if not efw_ok:
            self._fail("CHK-XBAR-EFUSE", ["no in-map eFuse read answered OKAY (control)"])

        problems: dict[str, list[str]] = {
            "CHK-XBAR": [],
            "CHK-XBAR-RSV": [],
            "CHK-XBAR-EFUSE": [],
            "CHK-XBAR-SIZE": [],
        }
        passes: dict[str, list[str]] = {k: [] for k in problems}
        first_last_clean = 0
        first_last_logged = 0
        for cell, res in walk.cells:
            d = cell.d
            rd_txt = f"0x{res.value:08x}" if res.known else "X"
            tag = f"win={cell.win} off=0x{cell.addr:05x} kind={cell.kind} dir={d}"
            if cell.chk == "OBS":
                first_last_logged += 1
                self.logger.info(
                    "OBS-XBAR-UNSTATED %s rd=%s slv=%d dec=%d", tag, rd_txt, res.slv, res.dec
                )
                continue
            want = _EXP_BITS[cell.resp]
            got_ok = res.known and res.clean and (res.slv, res.dec) == want
            if d == "rd" and cell.rdata is not None:
                got_ok = got_ok and res.value == cell.rdata
            line = f"{tag} rd={rd_txt} slv={res.slv} dec={res.dec} pre_clean={int(res.clean)}"
            if cell.control:
                self.logger.info("CTL-XBAR %s control=1 match=%d", line, int(got_ok))
                continue
            chk = "CHK-XBAR-SIZE" if cell.chk == "SIZE" else cell.chk
            exp = f"expected {cell.resp}" + (
                f" data=0x{cell.rdata:08x}" if d == "rd" and cell.rdata is not None else ""
            )
            if got_ok:
                if chk == "CHK-XBAR-SIZE":
                    first_last_clean += 1
                passes[chk].append(f"seed={seed} {line}")
            else:
                problems[chk].append(f"{line} ({exp})")

        # Size boundaries: 0x3FFC, 0x8000, 0xFFFC reads and the 0xFFFC store
        # are clean; the 0x4000 read next to them shows an error bit (control).
        rom_top, rom_next, sram_st, sram_lo, sram_hi = size
        for name, r in (
            ("rom_top", rom_top),
            ("sram_hi_store", sram_st),
            ("sram_lo", sram_lo),
            ("sram_hi", sram_hi),
        ):
            if not (r.known and r.clean and (r.slv, r.dec) == (0, 0)):
                problems["CHK-XBAR-SIZE"].append(
                    f"{name} slv={r.slv} dec={r.dec} pre_clean={int(r.clean)} (expected clean)"
                )
        if not (rom_next.clean and rom_next.dec == 1):
            problems["CHK-XBAR-SIZE"].append(
                f"control: the read at 0x{KM_RSV_ROM_GROWTH:x} showed slv={rom_next.slv} "
                f"dec={rom_next.dec}; the leaf cannot show an error bit next to the ROM top"
            )
        self.logger.info(
            "CTL-XBAR win=reserved_4000 off=0x%05x kind=first dir=rd rd=0x%08x slv=%d dec=%d "
            "control=1",
            KM_RSV_ROM_GROWTH,
            rom_next.value,
            rom_next.slv,
            rom_next.dec,
        )
        self.logger.info(
            "CTL-XBAR off=0x%08x dir=rd rd=%s slv=%d dec=%d control=1",
            KM_VROM_PROBE,
            f"0x{vrom.value:08x}" if vrom.known else "X",
            vrom.slv,
            vrom.dec,
        )
        for chk in ("CHK-XBAR", "CHK-XBAR-RSV", "CHK-XBAR-EFUSE", "CHK-XBAR-SIZE"):
            self._fail(chk, problems[chk])
            if not passes[chk]:
                self._fail(chk, ["no graded cell"])
            if chk == "CHK-XBAR-SIZE":
                self.logger.info(
                    "CHK-XBAR-SIZE PASS rom_top=clean rom_next=dec(control) sram_lo=clean "
                    "sram_hi=clean sram_hi_store=clean first_last_clean=%d first_last_logged=%d",
                    first_last_clean,
                    first_last_logged,
                )
                continue
            for p in passes[chk]:
                self.logger.info("%s PASS %s", chk, p)

    # --- steps 8 and 11: KM read against host read ---------------------------

    def _rd_draws(self, rng: SepSeededRng, tm: int) -> list[tuple[str, int, int, int]]:
        """(map, KM address, SEP address, field mask) of the read draws."""
        fp = self.fp
        rl = SepEfuseImage.field(fp.read_locked)
        wl = SepEfuseImage.field(fp.write_locked)
        shadow = [0, 255, rl.word + rng.randrange(rl.n_words), wl.word + rng.randrange(wl.n_words)]
        shadow += [rng.randrange(256) for _ in range(N_RD_DRAWS - 12)]
        out = [("map", KM_EFUSE_MAP + 4 * w, SHADOW_BASE + 4 * w, WORD_MASK) for w in shadow]
        for reg in _CTRL_STATUS_REGS:
            sep = EFUSE_INTERFACE_CTRL.addr(reg)
            out.append(
                ("ctrl", KM_EFUSE_MAP + sep - SHADOW_BASE, sep, EFUSE_INTERFACE_CTRL.mask(reg))
            )
        for reg in _TOKEN_STATUS_REGS:
            sep = EFUSE_MMR.addr(reg)
            out.append(("token", KM_EFUSE_MAP + sep - SHADOW_BASE, sep, _mmr_mask(reg)))
        rng.shuffle(out)
        for k, (m, km, sep, mask) in enumerate(out):
            self._draw(
                f"efw_rd.tm{tm}.{k}", f"map={m} km=0x{km:05x} host=0x{sep:08x} mask=0x{mask:08x}"
            )
        return out

    async def _efw_reads(
        self, rng: SepSeededRng, model: SepEfuseImage, *, tm: int, bus: bool
    ) -> list[dict]:
        draws = self._rd_draws(rng, tm)
        host1: list[tuple[int, str]] = []
        host2: list[tuple[int, str]] = []
        marks: list[int] = []
        seen: list[int] = []
        mon = cocotb.start_soon(self._efuse_ar_monitor(seen)) if bus else None

        async def on_sync(k: int) -> None:
            if k > 0:
                host2.append(await self._host(SepAxiOp.READ, draws[k - 1][2]))
            host1.append(await self._host(SepAxiOp.READ, draws[k][2]))
            marks.append(len(seen))
            return None

        ops: list[kp.PokeOp] = []
        for _m, km, _sep, _mask in draws:
            ops += [kp.sync(), kp.rd(km)]
        res = await self._run(ops, on_sync=on_sync, allow_unknown=True)
        host2.append(await self._host(SepAxiOp.READ, draws[-1][2]))
        if mon is not None:
            await ClockCycles(cocotb.top.clk_i, 4)
            if hasattr(mon, "cancel"):
                mon.cancel()
            else:
                mon.kill()
        marks.append(len(seen))
        out = []
        for k, (m, km, sep, mask) in enumerate(draws):
            r = res[2 * k + 1]
            out.append(
                {
                    "k": k,
                    "map": m,
                    "km": km,
                    "sep": sep,
                    "mask": mask,
                    "km_data": r.value,
                    "km_known": r.known,
                    "km_clean": r.clean,
                    "km_cls": _km_class(r),
                    "h1": host1[k],
                    "h2": host2[k],
                    "staged": model.words[(km - KM_EFUSE_MAP) // 4] if m == "map" else None,
                    "model": model.shadow_word((km - KM_EFUSE_MAP) // 4) if m == "map" else None,
                    "bus": seen[marks[k] : marks[k + 1]] if bus else None,
                }
            )
        return out

    async def _efuse_ar_monitor(self, sink: list[int], ch: str = "ar") -> None:
        """Addresses of the handshakes on channel ``ch`` of ``efuse_req_o`` (KM-BUS)."""
        dut = cocotb.top
        valid = getattr(dut, f"km_efuse_{ch}_valid_o")
        ready = getattr(dut, f"km_efuse_{ch}_ready_o")
        addr = getattr(dut, f"km_efuse_{ch}_addr_o")
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(valid, allow_unknown=True) and self.rd(ready, allow_unknown=True):
                sink.append(self.rd(addr))

    def _grade_efw_rd(
        self,
        seed: int,
        draws: list[dict],
        *,
        tm: int,
        tm_seen: int,
        tm_first_boot: int | None = None,
    ) -> None:
        chk = "CHK-EFW-RD-TM" if tm else "CHK-EFW-RD"
        fp = self.fp
        rl = SepEfuseImage.field(fp.read_locked)
        locked_words = set(range(rl.word, rl.word + rl.n_words))
        problems: list[str] = []
        if tm_seen != tm:
            problems.append(f"secure_tm_o={tm_seen} in this boot, expected {tm}")
        if tm and tm_first_boot != 0:
            problems.append(f"control: secure_tm_o={tm_first_boot} in the first boot, expected 0")
        equal = stable = eq_staged = locked_staged = 0
        maps = set()
        for d in draws:
            mask = d["mask"]
            kd, (h1d, h1c), (h2d, h2c) = d["km_data"], d["h1"], d["h2"]
            maps.add(d["map"])
            line = (
                f"k={d['k']} map={d['map']} km=0x{d['km']:05x} km_rd=0x{kd:08x} "
                f"km_cls={d['km_cls']} host_rd=0x{h1d:08x}/0x{h2d:08x} host_cls={h1c}/{h2c} "
                f"mask=0x{mask:08x}"
            )
            self.logger.info("%s draw %s", "LOG-EFW-RD-TM" if tm else "LOG-EFW-RD", line)
            if (h1d & mask, h1c) != (h2d & mask, h2c):
                problems.append(f"control: the two host reads differ: {line}")
            else:
                stable += 1
            if not (d["km_known"] and d["km_clean"]) or d["km_cls"] == "BOTH":
                problems.append(f"KM result unknown, not cleared or both bits: {line}")
            elif (kd & mask, d["km_cls"]) == (h1d & mask, h1c):
                equal += 1
            else:
                problems.append(f"KM read differs from the host read: {line}")
            if d["map"] != "map":
                continue
            word = (d["km"] - KM_EFUSE_MAP) // 4
            if word in locked_words:
                if d["staged"] in (kd, h1d, h2d):
                    locked_staged += 1
                    problems.append(f"the read-locked word {word} returned its staged word: {line}")
            elif tm == 0:
                if h1d == d["model"]:
                    eq_staged += 1
                else:
                    problems.append(
                        f"host read of shadow word {word} is not the staged model "
                        f"0x{d['model']:08x}: {line}"
                    )
        if len(maps) != 3:
            problems.append(f"draws cover maps {sorted(maps)}, not all three")
        if tm == 0 and eq_staged == 0:
            problems.append("no shadow draw returned its staged word; the lock check cannot fail")
        self._fail(chk, problems)
        if tm:
            self.logger.info(
                "CHK-EFW-RD-TM PASS draws=%d equal=%d host_stable=%d locked_field=%s "
                "locked_words_staged_seen=%d tm=1",
                len(draws),
                equal,
                stable,
                fp.read_locked,
                locked_staged,
            )
        else:
            self.logger.info(
                "CHK-EFW-RD PASS seed=%d draws=%d equal=%d maps=%d host_stable=%d "
                "host_eq_staged=%d locked_field=%s locked_words_staged_seen=%d tm=0",
                seed,
                len(draws),
                equal,
                len(maps),
                stable,
                eq_staged,
                fp.read_locked,
                locked_staged,
            )

    def _grade_remap(self, draws: list[dict]) -> None:
        problems: list[str] = []
        uppers: set[int] = set()
        for d in draws:
            bus = d["bus"]
            if len(bus) != 1:
                problems.append(
                    f"k={d['k']} km=0x{d['km']:05x}: {len(bus)} efuse_req_o read handshakes, "
                    "expected 1"
                )
                continue
            addr = bus[0]
            if addr & 0xFFF != d["km"] & 0xFFF:
                problems.append(
                    f"k={d['k']} km=0x{d['km']:05x}: efuse_req_o addr 0x{addr:08x} low12 "
                    f"0x{addr & 0xFFF:03x} != 0x{d['km'] & 0xFFF:03x}"
                )
            uppers.add(addr >> 12)
        if len(uppers) > 1:
            problems.append(f"efuse_req_o bits [31:12] take {len(uppers)} values: {sorted(uppers)}")
        self._fail("CHK-REMAP-BUS", problems)
        base = next(iter(uppers)) << 12
        self.logger.info("OBS-REMAP-BASE base=0x%08x", base)
        self.logger.info(
            "CHK-REMAP-BUS PASS draws=%d low12=ok base_constant=1 base=0x%08x", len(draws), base
        )

    # --- steps 9, 10 and 12: programs -----------------------------------------

    @staticmethod
    def _prog_word(tgt: FuseTarget) -> int:
        return PC_ENABLE | PC_DATA | _place(tgt.address, PC_ADDR_LSB, PC_ADDR_MASK)

    @staticmethod
    def _read_word(tgt: FuseTarget) -> int:
        return RC_ENABLE | _place(_word_bit_addr(tgt), RC_ADDR_LSB, RC_ADDR_MASK)

    def _km_prog_ops(self, tgt: FuseTarget, mode: str) -> list[kp.PokeOp]:
        """KM program ops. ``mode``: "allow", "deny" or "tm"."""
        km = self._km
        pw = self._prog_word(tgt)
        ops = [
            kp.wr(km(R_STATUS), ST_REQ_ERR_CLR),
            kp.rd(km(R_STATUS)),
            kp.wr(km(R_READ), 0),
            kp.rd(km(R_PROG)),
            kp.wr(km(R_PROG), pw),
        ]
        if mode == "tm":
            # Read back efuse_addr (RW) before the other path touches the register.
            ops.append(kp.rd(km(R_PROG)))
        ops += [
            kp.wr(km(R_PROG), pw | PC_GO, raw=mode == "allow"),
        ]
        if mode == "allow":
            # Looks for program_busy = 1 after the go; busy_seen is logged only.
            ops.append(kp.poll(km(R_PROG), PC_BUSY, PC_BUSY, BUSY_RISE_LOADS, raw=True))
            ops.append(kp.poll(km(R_PROG), PC_BUSY | PC_DONE, PC_DONE, PROG_POLL_LOADS))
        elif mode == "deny":
            ops.append(kp.poll(km(R_STATUS), ST_REQ_ERR, ST_REQ_ERR, PROG_POLL_LOADS))
            ops.append(kp.poll(km(R_PROG), PC_BUSY, 0, PROG_POLL_LOADS))
        else:
            # A fixed interval: the condition never holds, so the poll makes
            # exactly TM_POLL_READS loads.
            ops.append(kp.poll(km(R_PROG), 0, 1, TM_POLL_READS))
        ops += [kp.rd(km(R_PROG)), kp.rd(km(R_STATUS))]
        if mode != "allow":
            # A refused or blocked program leaves the sticky efuse_req_error set;
            # clear it so a later command is not blocked. An allowed program
            # keeps it for the read after the OTP readback.
            ops.append(kp.wr(km(R_STATUS), ST_REQ_ERR_CLR))
        return ops

    async def _km_program(self, tgt: FuseTarget, mode: str) -> dict:
        res = await self._run(self._km_prog_ops(tgt, mode))
        polls = [r for r in res if r.op.code == kp.OP_POLL]
        tail = res[-2:] if mode == "allow" else res[-3:-1]
        pc, st = tail[0].value, tail[1].value
        busy_seen = 0
        if mode == "allow":
            busy_seen = _bit(polls[0].data[0], PC_BUSY)
            waited = (polls[1].data[0] & (PC_BUSY | PC_DONE)) == PC_DONE
        elif mode == "deny":
            waited = bool(polls[0].data[0] & ST_REQ_ERR) and not polls[1].data[0] & PC_BUSY
        else:
            waited = polls[0].data[1] == TM_POLL_READS
        echo = res[5].value if mode == "tm" else None
        return {
            "path": "km",
            "echo": echo,
            "req_err_before": _bit(res[1].value, ST_REQ_ERR),
            "done_before": _bit(res[3].value, PC_DONE),
            "done": _bit(pc, PC_DONE),
            "status": _bit(pc, PC_STATUS),
            "busy": _bit(pc, PC_BUSY),
            "busy_seen": busy_seen,
            "req_err": _bit(st, ST_REQ_ERR),
            "waited": waited,
        }

    async def _host_program(self, tgt: FuseTarget, mode: str) -> dict:
        pw = self._prog_word(tgt)
        await self._hw(R_STATUS, ST_REQ_ERR_CLR)
        req_before = _bit(await self._hr(R_STATUS), ST_REQ_ERR)
        await self._hw(R_READ, 0)
        done_before = _bit(await self._hr(R_PROG), PC_DONE)
        await self._hw(R_PROG, pw)
        echo = await self._hr(R_PROG) if mode == "tm" else None
        await self._hw(R_PROG, pw | PC_GO)
        waited = False
        busy_seen = 0
        if mode == "tm":
            for _ in range(TM_POLL_READS):
                await self._hr(R_PROG)
            waited = True
        else:
            for _ in range(HOST_POLL_READS):
                pc = await self._hr(R_PROG)
                st = await self._hr(R_STATUS)
                busy, done, err = _bit(pc, PC_BUSY), _bit(pc, PC_DONE), _bit(st, ST_REQ_ERR)
                busy_seen |= busy
                if mode == "allow" and not busy and done:
                    waited = True
                    break
                if mode == "deny" and not busy and err:
                    waited = True
                    break
        pc = await self._hr(R_PROG)
        st = await self._hr(R_STATUS)
        if mode != "allow":
            await self._hw(R_STATUS, ST_REQ_ERR_CLR)
        return {
            "path": "host",
            "echo": echo,
            "busy_seen": busy_seen,
            "req_err_before": req_before,
            "done_before": done_before,
            "done": _bit(pc, PC_DONE),
            "status": _bit(pc, PC_STATUS),
            "busy": _bit(pc, PC_BUSY),
            "req_err": _bit(st, ST_REQ_ERR),
            "waited": waited,
        }

    async def _host_otp_read(self, tgt: FuseTarget, *, need_done: bool = True) -> dict:
        """Host OTP read of the word that holds ``tgt``.

        The bounded wait ends at read_busy = 0 and, with ``need_done``, read_done = 1.
        """
        rw = self._read_word(tgt)
        await self._hw(R_PROG, 0)
        await self._hw(R_READ, rw)
        await self._hw(R_READ, rw | RC_GO)
        rc = 0
        waited = False
        for _ in range(HOST_POLL_READS):
            rc = await self._hr(R_READ)
            if not rc & RC_BUSY and (rc & RC_DONE or not need_done):
                waited = True
                break
        data = await self._hr(R_RDATA)
        await self._hw(R_READ, 0)
        return {
            "word": data,
            "done": _bit(rc, RC_DONE),
            "status": _bit(rc, RC_STATUS),
            "waited": waited,
        }

    async def _km_otp_read(self, tgt: FuseTarget) -> dict:
        km = self._km
        rw = self._read_word(tgt)
        res = await self._run(
            [
                kp.wr(km(R_PROG), 0),
                kp.wr(km(R_READ), rw),
                kp.wr(km(R_READ), rw | RC_GO),
                kp.poll(km(R_READ), RC_BUSY, 0, PROG_POLL_LOADS),
                kp.rd(km(R_READ)),
                kp.rd(km(R_RDATA)),
                kp.wr(km(R_READ), 0),
            ]
        )
        rc = res[4].value
        return {
            "word": res[5].value,
            "done": _bit(rc, RC_DONE),
            "status": _bit(rc, RC_STATUS),
            "waited": not res[3].data[0] & RC_BUSY,
        }

    def _order(self, rng: SepSeededRng, name: str) -> tuple[str, str]:
        order = ("km", "host") if rng.getrandbits(1) == 0 else ("host", "km")
        self._draw(name, ",".join(order))
        return order

    async def _path_status(self, path: str) -> tuple[int, int]:
        """EFUSE_PROGRAM_CTRL and EFUSE_INTERFACE_CTRL_STATUS read through ``path``."""
        if path == "km":
            res = await self._run([kp.rd(self._km(R_PROG)), kp.rd(self._km(R_STATUS))])
            return res[0].value, res[1].value
        return await self._hr(R_PROG), await self._hr(R_STATUS)

    async def _program_pair(self, rng: SepSeededRng, fp: KmFusePlan) -> dict:
        km_t, host_t = fp.targets["km_spare"], fp.targets["host_spare"]
        out: dict = {}
        order = self._order(rng, "prog.order")
        for path in order:
            tgt = km_t if path == "km" else host_t
            r = await (
                self._km_program(tgt, "allow") if path == "km" else self._host_program(tgt, "allow")
            )
            r["otp"] = await self._host_otp_read(tgt)
            r["land_reads"] = 1
            if path == order[1]:
                # The second program starts with program_done already 1, so done
                # cannot show its end. The target bit set in OTP shows that it
                # completed; program_status and efuse_req_error are then read
                # again through the same path, and they belong to this program.
                while not (r["otp"]["word"] >> tgt.bit) & 1 and r["land_reads"] < OTP_LAND_READS:
                    r["otp"] = await self._host_otp_read(tgt)
                    r["land_reads"] += 1
                pc, st = await self._path_status(path)
                r["done_first_read"] = r["done"]
                r["status"], r["req_err"] = _bit(pc, PC_STATUS), _bit(st, ST_REQ_ERR)
                r["done"] = _bit(pc, PC_DONE)
            out[path] = r
        problems: list[str] = []
        for path, tgt in (("km", km_t), ("host", host_t)):
            r = out[path]
            staged = fp.words[tgt.address // WORD_BITS]
            want = staged | (1 << tgt.bit)
            otp = r["otp"]
            r["otp_bit"] = (otp["word"] >> tgt.bit) & 1
            r["otp_word_eq"] = int(otp["word"] == want)
            # program_done resets to 0x0 (efuse_interface_ctrl.adoc,
            # EFUSE_PROGRAM_CTRL) at the cold reset that starts this boot
            # (otp_fuse_controller.adoc: SEP released from chiplet_cold_reset),
            # and no program runs between that reset and this pair. The first
            # program of the pair therefore starts at done = 0, and its done
            # belongs to it. The second program follows a program that set done,
            # so its done is logged, not graded; its status and efuse_req_error
            # are read after its bit landed in OTP and are graded.
            r["fresh"] = int(path == order[0])
            line = (
                f"path={path} spare={tgt.field} word={tgt.word} bit={tgt.bit} "
                f"done_before={r['done_before']} done={r['done']} status={r['status']} "
                f"req_err_before={r['req_err_before']} req_err={r['req_err']} "
                f"otp_word=0x{otp['word']:08x} staged=0x{staged:08x} otp_bit={r['otp_bit']} "
                f"otp_word_eq={r['otp_word_eq']} busy_seen={r['busy_seen']} "
                f"land_reads={r['land_reads']} done_graded={r['fresh']}"
                + ("" if r["fresh"] else " reason=prior_program")
            )
            r["line"] = line
            bad = []
            if r["req_err_before"]:
                bad.append("efuse_req_error read 1 after its clear (control)")
            if not r["waited"] or not otp["waited"]:
                bad.append("the bounded wait ran out")
            if r["fresh"] and r["done_before"] != 0:
                bad.append("program_done read 1 before the first program since the reset")
            if r["fresh"] and r["done"] != 1:
                bad.append("program_done != 1")
            if r["status"] != 0:
                bad.append("program_status is 1")
            if r["req_err"] != 0:
                bad.append("efuse_req_error is 1")
            if not r["otp_word_eq"]:
                bad.append(f"OTP word != staged + target bit 0x{want:08x}")
            if path == "km":
                problems += [f"{b}: {line}" for b in bad]
            else:
                self.logger.info("CTL-EFW-PROG %s control=1 match=%d", line, int(not bad))
        # program_status and efuse_req_error belong to each program (see
        # above); program_done only to the first one.
        keys = ("status", "req_err")
        second = out[order[1]]
        tgt2 = km_t if order[1] == "km" else host_t
        if not (second["otp"]["word"] >> tgt2.bit) & 1:
            # The status of the second program is read only after its bit
            # landed; a bit that never lands leaves nothing to compare.
            problems.append(
                f"the bounded wait for the {order[1]} program bit ran out after "
                f"{second['land_reads']} OTP reads: {second['line']}"
            )
        km_tuple = tuple(out["km"][k] for k in keys)
        host_tuple = tuple(out["host"][k] for k in keys)
        if km_tuple != host_tuple:
            problems.append(f"KM tuple {km_tuple} != host tuple {host_tuple}")
        self._fail("CHK-EFW-PROG", problems)
        self.logger.info(
            "CHK-EFW-PROG PASS %s host_tuple_equal=1 tuple_fields=%s done_graded_path=%s",
            out["km"]["line"],
            ",".join(keys),
            order[0],
        )
        return out

    async def _deny_pair(self, rng: SepSeededRng, fp: KmFusePlan, prog: dict) -> None:
        tgt = fp.targets["denied"]
        out: dict = {}
        for path in self._order(rng, "deny.order"):
            r = await (
                self._km_program(tgt, "deny") if path == "km" else self._host_program(tgt, "deny")
            )
            r["otp"] = await self._host_otp_read(tgt)
            out[path] = r
        spare = {}
        for key in ("km_spare", "host_spare"):
            s = fp.targets[key]
            spare[key] = await self._host_otp_read(s)
            spare[key]["bit"] = (spare[key]["word"] >> s.bit) & 1
        staged = fp.words[tgt.address // WORD_BITS]
        problems: list[str] = []
        for path in ("km", "host"):
            r = out[path]
            r["bit"] = (r["otp"]["word"] >> tgt.bit) & 1
            line = (
                f"path={path} field={tgt.field} word={tgt.word} bit={tgt.bit} "
                f"req_err_before={r['req_err_before']} req_err={r['req_err']} "
                f"done={r['done']} status={r['status']} otp_word=0x{r['otp']['word']:08x} "
                f"staged=0x{staged:08x} bit_unchanged={int(r['bit'] == 0)}"
            )
            r["line"] = line
            bad = []
            if r["req_err_before"]:
                bad.append("efuse_req_error read 1 after its clear (control)")
            if not r["waited"] or not r["otp"]["waited"]:
                bad.append("the bounded wait ran out")
            if r["req_err"] != 1:
                bad.append("efuse_req_error != 1")
            if r["bit"] != 0:
                bad.append("the write-locked target bit reads 1 in OTP")
            if path == "km":
                problems += [f"{b}: {line}" for b in bad]
            else:
                self.logger.info("CTL-EFW-DENY %s control=1 match=%d", line, int(not bad))
        if any(v["bit"] != 1 or not v["waited"] for v in spare.values()):
            problems.append(
                "control: a spare bit of the unlocked programs does not read 1 in OTP: "
                + ", ".join(f"{k}=0x{v['word']:08x}" for k, v in spare.items())
            )
        km_r = (out["km"]["req_err"], out["km"]["bit"])
        host_r = (out["host"]["req_err"], out["host"]["bit"])
        if km_r != host_r:
            problems.append(f"KM result {km_r} != host result {host_r}")
        self._fail("CHK-EFW-DENY", problems)
        self.logger.info("CHK-EFW-DENY PASS %s spare_bit_control=1 host_equal=1", out["km"]["line"])

    async def _tm_program_pair(self, rng: SepSeededRng, fp: KmFusePlan) -> dict:
        out: dict = {}
        aw: list[int] = []
        mon = cocotb.start_soon(self._efuse_ar_monitor(aw, "aw"))
        self._wr_trace = {"km": [], "host": []}
        for path in self._order(rng, "tm.order"):
            tgt = fp.targets["tm_km_spare" if path == "km" else "tm_host_spare"]
            r = await (
                self._km_program(tgt, "tm") if path == "km" else self._host_program(tgt, "tm")
            )
            out[path] = r
        for path in self._order(rng, "tm.read_order"):
            tgt = fp.targets["tm_km_spare" if path == "km" else "tm_host_spare"]
            out[path]["otp"] = await (
                self._km_otp_read(tgt)
                if path == "km"
                else self._host_otp_read(tgt, need_done=False)
            )
        await ClockCycles(cocotb.top.clk_i, 4)
        if hasattr(mon, "cancel"):
            mon.cancel()
        else:
            mon.kill()
        out["trace"] = self._wr_trace
        out["aw"] = aw
        self._wr_trace = None
        for path in ("km", "host"):
            r = out[path]
            self.logger.info(
                "OBS-EFW-TM-TUPLE path=%s done_before=%d done=%d status=%d req_err=%d busy=%d "
                "read_done=%d read_status=%d read_word=0x%08x",
                path,
                r["done_before"],
                r["done"],
                r["status"],
                r["req_err"],
                r["busy"],
                r["otp"]["done"],
                r["otp"]["status"],
                r["otp"]["word"],
            )
        return out

    async def _grade_tm_shadow(self, fp: KmFusePlan, tm_res: dict, prog: dict, tm: int) -> None:
        problems: list[str] = []
        if tm != 1:
            problems.append(f"secure_tm_o={tm} after the strap-held cold reset")
        trace, aw = tm_res["trace"], tm_res["aw"]
        # Every KM write of this boot leaves the KM on efuse_req_o with bits
        # [11:0] of its KM offset (architecture.adoc, OTP Inputs and Readout;
        # memory_map.adoc: the three maps are Forwarded), in order.
        km_low = [a & 0xFFF for a, _ in trace["km"]]
        aw_low = [a & 0xFFF for a in aw]
        if km_low != aw_low:
            problems.append(
                f"KM eFuse writes {[hex(a) for a in km_low]} != efuse_req_o write handshakes "
                f"{[hex(a) for a in aw_low]}"
            )
        # The window applies the same access filtering as a SEP host access, so
        # each KM write answers as the same host write.
        km_cls = [c for _, c in trace["km"]]
        host_cls = [c for _, c in trace["host"]]
        if km_cls != host_cls:
            problems.append(f"KM write responses {km_cls} != host write responses {host_cls}")
        echo = {}
        for path in ("km", "host"):
            tgt = fp.targets["tm_km_spare" if path == "km" else "tm_host_spare"]
            word = tm_res[path]["echo"]
            echo[path] = int((word & PC_ADDR_MASK) >> PC_ADDR_LSB == tgt.address)
            self.logger.info(
                "LOG-EFW-TM echo path=%s program_ctrl=0x%08x efuse_addr_echo=%d",
                path,
                word,
                echo[path],
            )
        if echo["km"] != echo["host"]:
            problems.append(
                f"efuse_addr read back after the write: km echo={echo['km']} host echo={echo['host']}"
            )
        for path in ("km", "host"):
            r = tm_res[path]
            if not r["otp"]["waited"]:
                problems.append(f"path={path}: the bounded wait for read_busy=0 ran out")
            if r["req_err_before"]:
                problems.append(f"path={path}: efuse_req_error read 1 after its clear (control)")
        km_tuple = tuple(tm_res["km"][k] for k in ("done", "status", "req_err"))
        host_tuple = tuple(tm_res["host"][k] for k in ("done", "status", "req_err"))
        if km_tuple != host_tuple:
            problems.append(f"KM tuple {km_tuple} != host tuple {host_tuple}")
        read_zero = 0
        for path in ("km", "host"):
            tgt = fp.targets["tm_km_spare" if path == "km" else "tm_host_spare"]
            staged = fp.words[tgt.address // WORD_BITS]
            word = tm_res[path]["otp"]["word"]
            if word == 0 and staged != 0:
                read_zero += 1
            else:
                problems.append(
                    f"path={path}: blocked OTP read returned 0x{word:08x} (staged 0x{staged:08x}), "
                    "expected the default all-zero response"
                )
        landed: dict[str, tuple[int, int]] = {}
        for key in ("tm_km_spare", "tm_host_spare", "km_spare", "host_spare"):
            tgt = fp.targets[key]
            idx = tgt.address // WORD_BITS
            front, _ = await self._host(SepAxiOp.READ, SHADOW_BASE + 4 * idx)
            probe = self._shadow_probe_word(idx)
            landed[key] = ((front >> tgt.bit) & 1, (probe >> tgt.bit) & 1)
            self.logger.info(
                "LOG-EFW-TM shadow %s %s[%d].%d frontdoor=0x%08x probe=0x%08x",
                key,
                tgt.field,
                tgt.word,
                tgt.bit,
                front,
                probe,
            )
        if landed["tm_km_spare"] != (0, 0):
            problems.append(f"KM target bit reads {landed['tm_km_spare']} (frontdoor, probe)")
        control_landed = sum(1 for k in ("km_spare", "host_spare") if landed[k] == (1, 1))
        if control_landed != 2:
            problems.append(
                "control: a boot-one program bit does not read 1 in the shadow: "
                f"km_spare={landed['km_spare']} host_spare={landed['host_spare']}"
            )
        if not all(prog[p]["otp"]["word"] != 0 for p in ("km", "host")):
            problems.append("control: a boot-one OTP word of a spare read 0")
        host_ok = landed["tm_host_spare"] == (0, 0)
        self.logger.info("CTL-EFW-TM path=host bit_unchanged=%d control=1", int(host_ok))
        self._fail("CHK-EFW-TM", problems)
        self.logger.info(
            "CHK-EFW-TM PASS km_host_equal=1 tuple=%d,%d,%d read_zero=%d km_bit_unchanged=1 "
            "host_bit_unchanged=%d(control) control_landed=%d secure_tm=%d km_writes=%d "
            "efuse_req_aw=%d km_wr_resp_eq_host=1 efuse_addr_echo=%d,%d",
            *km_tuple,
            read_zero,
            int(host_ok),
            control_landed,
            tm,
            len(km_low),
            len(aw_low),
            echo["km"],
            echo["host"],
        )
