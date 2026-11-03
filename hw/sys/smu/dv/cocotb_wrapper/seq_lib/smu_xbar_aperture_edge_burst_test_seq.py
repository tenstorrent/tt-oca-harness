# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xbar_aperture_edge_burst_test (SMU_AXI_FAB_020).

DV-TESTCASE-CONTRACT: SMU_AXI_FAB_020 ANCHOR: smu_xbar_aperture_edge_burst_test
DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: d3d2b1b1138370575009ab91c9d20024f4bf86acac92fd6021a8d4394a3a5dc7
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_FAB_VPLAN_DETAIL.md @ artifact_revision 4 ENV: cocotb

The SMU crossbar decodes an inbound transaction on its first address: an
aperture covers [base, base + size) in a 57-bit sum, base included and
base + size excluded (``hw/sys/smu/doc/index.adoc``, "SMU aperture decode and
routing"). A burst is one transaction with one address and ARLEN + 1 beats
(IHI 0022 A3.4.1), so a burst whose later beats leave the window still goes
whole to the subordinate its first address selects.

S1:  sensing, SMC inbound filter entry 0 over the whole space over JTAG2AXI,
     the SEP debug module active; every crossbar subordinate counter sampled.
S2:  SEP aperture B=0x0400_0000, SEP_REGION_SIZE 0x1000_0840 (end E=0x1400_0840);
     readback; single write and read at E-8, single read and write at E.
S3:  SEP base 0x0400_1000: a write at base+0x1000_0000 over ext_in, then the
     SEP-local SRAM word at 0x1000_0000 over the system bus.
S4:  S2 placement: INCR read and write of 8 beats from E-16.
S5:  WRAP read ARLEN 15 from E-16; FIXED read and write ARLEN/AWLEN 3 at E-8.
S6:  SEP aperture at 0xFF_FFFF_FF00_0000 / 0x0100_0000 (end 2^56): INCR read and
     write of 8 beats from 0xFF_FFFF_FFFF_FFC0.
S7:  SEP aperture 0x1_0000_0000 / 0x8000_0000: reads at B+0x4000_0008 (ARID 0x5C)
     and B+0x4000_0000 (ARID 0x3A), a write at B+0x4000_0008 (AWID 0xA3).
S8:  SEP back to the S2 placement; SMC GLOBAL_BASE 0x4000_0400, then REGION_SIZE
     0x400 as the last BASE_CONFIG access JTAG2AXI can make.
S9:  SEP base 0x2FFF_FBC0 (SEP end = SMC base): singles at 0x4000_03F8 and
     0x4000_0400, the SMC word at 0x4000_0400 (CORE0 watchdog CTRL), its KEY
     written, 8-beat INCR read and write from 0x4000_03F0, the SMC word again;
     then KEY, a CTRL write of WDOGCOREAWAKE and its read-back.
S10: SEP base 0x4000_0800 (SMC end): reads at 0x4000_07F8 and 0x4000_0800, an
     8-beat INCR read from 0x4000_07F0.
S11: SEP base 0x0400_0000: singles at 0x4000_07F8 and 0x4000_0800, 8-beat INCR
     read and write from 0x4000_07F0; rst_cold_ni, then one ext_in read into
     each reset window.
S12: every wait has a finite bound and fails the test on expiry with the last
     channel state.

The per-beat response codes of a burst whose later beats leave the window, the
data words of a SEP DECERR and the legality of the unaligned SEP values are OBS
lines without a verdict (SF-005, SF-006, SF-007, SF-008, SF-029). Aperture
placements and probe addresses are stimulus stated by the contract; register
addresses come from the generated SEP and SMC headers. Every ext_in handshake is
sampled on the pins each clk_smu_i cycle; the crossbar subordinate counters,
the sep_in AR tap and the sep_in / smc_in channel levels on the AXI checker
instances are read passively from the bench top. No force or deposit.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_axi_vip import PROT_NONSECURE, RESP_DECERR, RESP_OKAY, clear_profile

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, c_header_u32, smc_addr, wdt_u32
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import DMI_OP_READ, DMI_OP_WRITE
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_64,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
)
from seq_lib.smu_dtp_sep_ic_reset_effect_test_seq import CAPTURE_POLL_CLK, CAPTURE_POLL_LIMIT
from seq_lib.smu_filter_helpers import SMC_APERTURE_LOCAL_BASE
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    WDT_KEY_MAGIC,
    pack_single_op,
    unpack_single_op,
)
from seq_lib.smu_tb_pins import smc_primary_reset
from seq_lib.smu_xbar_decerr_burst_response_test_seq import (
    _ExtInMonitor,
    _hx,
    _kv,
    _rn,
    _val,
)
from seq_lib.smu_xbar_reset_held_target_test_seq import smu_xbar_reset_held_target_test_seq

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"
SRAM_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_SRAM_BASE_ADDR")

SMC_GLOBAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
SMC_REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
SMC_GLOBAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
SMC_REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")

# Aperture placements and probe addresses stated by the contract.
SEP_B0 = 0x0400_0000
SEP_SIZE0 = 0x1000_0840
SEP_END0 = SEP_B0 + SEP_SIZE0
SEP_B_REBASE = 0x0400_1000
REBASE_PROBE = SEP_B_REBASE + 0x1000_0000
SEP_B_CARRY = 0xFF_FFFF_FF00_0000
SEP_SIZE_CARRY = 0x0100_0000
CARRY_ADDR = 0xFF_FFFF_FFFF_FFC0
SEP_B_WIDE = 0x1_0000_0000
SEP_SIZE_WIDE = 0x8000_0000
WIDE_PAST = SEP_B_WIDE + 0x4000_0008
WIDE_EDGE = SEP_B_WIDE + 0x4000_0000
SMC_B = 0x4000_0400
SMC_SIZE = 0x400
SMC_END = SMC_B + SMC_SIZE
# SMC_B is the SMC local base, the CORE0 watchdog CTRL. KEY unlocks the next write to CTRL, so
# with KEY written before the S9 write burst a beat leaking into the SMC changes CTRL.
SMC_WDT_CTRL = (
    SMC_B - SMC_APERTURE_LOCAL_BASE + smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
)
SMC_WDT_KEY = (
    SMC_B - SMC_APERTURE_LOCAL_BASE + smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
)
# A KEY-unlocked write of WDOGCOREAWAKE changes CTRL: the live control of the unchanged word.
# WDOGIP0 is status and is masked from the compare.
WDT_COREAWAKE = wdt_u32("WDT__CTRL__WDOGCOREAWAKE_bm")
WDT_CTRL_CFG_MASK = sum(
    wdt_u32(f"WDT__CTRL__{f}_bm")
    for f in ("WDOGSCALE", "WDOGRSTEN", "WDOGZEROCMP", "WDOGENALWAYS", "WDOGCOREAWAKE")
)
SEP_B_BELOW = SMC_B - SEP_SIZE0
SEP_B_ABOVE = SMC_END
ADDR_SPACE = 1 << 56

AXI_BURST_FIXED = 0
AXI_BURST_INCR = 1
AXI_BURST_WRAP = 2
BURST_NAMES = {AXI_BURST_FIXED: "FIXED", AXI_BURST_INCR: "INCR", AXI_BURST_WRAP: "WRAP"}
SIZE_8B = 3
SIZE_4B = 2
BEAT_BYTES = 8

E8_WORD = 0x5E0E_0838_A5E0_0838
REBASE_WORD = 0x5E0A_1000_C0DE_1000
WIDE_WORD = 0xA3A3_0008_A3A3_0008
# SEP SRAM read by the S4, S5 and S9 bursts, [E-64, E+64), is written first through a window
# that contains it, so no burst under test reads unwritten memory (X on a four-state simulator).
FILL_SIZE = 0x1000_1000
FILL_START = SEP_END0 - 64
FILL_BEATS = 16

# Cycle and poll bounds of the waits.
XFER_BOUND = 20_000
MON_BOUND = 8
PORT_BOUND = 200

COUNTS = (
    "sep_xbar_in_aw_count_o",
    "sep_xbar_in_ar_count_o",
    "smc_xbar_in_ar_count_o",
    "smc_xbar_in_aw_count_o",
    "smu_axi_out_write_count_o",
    "smu_axi_out_read_count_o",
)
SEP_AW, SEP_AR, SMC_AR, SMC_AW, OUT_W, OUT_R = COUNTS
# The crossbar subordinate ports alone. SEP-local addresses below SEP SRAM are external to
# the SEP (sep memory_map.adoc), so an access there may leave the SEP again on its outbound
# path and reach smu_axi_out as a second transaction.
INBOUND = (SEP_AW, SEP_AR, SMC_AR, SMC_AW)
MARKERS = (
    "SETUP_OK",
    "SEP_EDGES",
    "SEP_REBASE",
    "SEP_PAST_END",
    "WRAP_FIXED",
    "CARRY",
    "WIDE_SEP",
    "SMC_PHASE_SET",
    "SEP_BELOW",
    "SMC_BELOW",
    "SMC_PAST_END",
    "COLD_RESET_BASELINE",
)
STEPS = tuple(f"S{i}" for i in range(1, 12))

# Channels of the crossbar target ports, read from the ports of their AXI checker instances.
_PORT_CHANNELS = {
    "ar": ("arvalid", "arready", ("araddr", "arlen", "arburst", "arsize")),
    "aw": ("awvalid", "awready", ("awaddr", "awlen", "awburst", "awsize")),
    "w": ("wvalid", "wready", ("wlast",)),
    "r": ("rvalid", "rready", ("rlast", "rresp")),
    "b": ("bvalid", "bready", ("bresp",)),
}
_PORT_INSTANCES = {"sep_in": "u_xbar_sep_in_axi_sva", "smc_in": "u_xbar_smc_in_axi_sva"}


class _PortMonitor:
    """Handshakes on one crossbar target port, sampled at each clk_smu_i edge."""

    def __init__(self, dut, inst: str, ext: _ExtInMonitor) -> None:
        self.dut = dut
        self.ext = ext
        handle = getattr(dut, inst)
        self.events: dict[str, list[dict]] = {ch: [] for ch in _PORT_CHANNELS}
        self.levels: dict[str, tuple] = {}
        self.last_hs: dict[str, dict] = {}
        self._pins = {
            ch: (
                getattr(handle, valid),
                getattr(handle, ready),
                {f: getattr(handle, f) for f in fields},
            )
            for ch, (valid, ready, fields) in _PORT_CHANNELS.items()
        }
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        clk = self.dut.clk_smu_i
        while True:
            await RisingEdge(clk)
            levels = {}
            for ch, (valid, ready, fields) in self._pins.items():
                v, r = _val(valid), _val(ready)
                levels[ch] = (v, r)
                if v == 1 and r == 1:
                    event = {"cyc": self.ext.cyc}
                    event.update({f: _val(h) for f, h in fields.items()})
                    self.events[ch].append(event)
                    self.last_hs[ch] = event
            self.levels = levels

    def mark(self) -> dict[str, int]:
        return {ch: len(evs) for ch, evs in self.events.items()}

    def since(self, mark: dict[str, int], ch: str) -> list[dict]:
        return self.events[ch][mark[ch] :]

    def state(self) -> str:
        return f"valid_ready={self.levels} last_handshake={self.last_hs}"


def _ax(events: list[dict], pre: str) -> list[tuple]:
    """(address, len, burst, size) of each AR or AW handshake."""
    return [
        (
            _hx(e[f"{pre}addr"]),
            e[f"{pre}len"],
            BURST_NAMES.get(e[f"{pre}burst"], "X"),
            e[f"{pre}size"],
        )
        for e in events
    ]


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[1] != 0 and b[1] != 0 and a[0] < b[0] + b[1] and b[0] < a[0] + a[1]


class smu_xbar_aperture_edge_burst_test_seq(smu_xbar_reset_held_target_test_seq):
    """ext_in bursts and singles at SEP and SMC aperture edges, adjacent apertures and the carry."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.pmon: dict[str, _PortMonitor] = {}
        self.obs: dict[str, dict] = {}

    # ------------------------------------------------------------------ helpers

    def _state(self) -> str:
        ports = " ".join(f"{n}:{m.state()}" for n, m in self.pmon.items())
        return f"{self.mon.state()} nets={self._nets()} {ports}"

    def _pre(self, name: str, observed: dict, expected: dict) -> None:
        """A precondition compare; a failure is recorded and the run goes on."""
        try:
            self.sb.expect_eq(name, _kv(observed), _kv(expected))
        except AssertionError as exc:
            self.failures.append(str(exc))

    async def _sba_read64(self, addr: int, label: str) -> int:
        await self._dmi_op(
            SBCS_ADDR,
            SBCS_SBACCESS_64 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
            f"{label}_sbcs",
        )
        await self._dmi_op(SBADDRESS0_ADDR, addr, DMI_OP_WRITE, f"{label}_addr")
        await self._sba_wait(label)
        high = await self._dmi_op(SBDATA1_ADDR, 0, DMI_OP_READ, f"{label}_d1")
        low = await self._dmi_op(SBDATA0_ADDR, 0, DMI_OP_READ, f"{label}_d0")
        return (high << 32) | low

    async def _place_sep(
        self, tag: str, base: int, size: int, *, size_first: bool, readback: bool = True
    ) -> dict:
        """Move the SEP aperture, one CSR at a time, never overlapping the SMC window.

        Returns the ports and the system-bus readback of both CSRs.
        """
        dut = self.dut
        cur = self._ports()
        window = [cur["sep_base"], cur["sep_size"]]
        order = [("size", SEP_REGION_SIZE_ADDR, size, 1), ("base", SEP_GLOBAL_BASE_ADDR, base, 0)]
        if not size_first:
            order.reverse()
        for name, addr, value, idx in order:
            if window[idx] == value:
                continue
            window[idx] = value
            smc = (cur["smc_base"], cur["smc_size"])
            if _overlap(tuple(window), smc) or window[0] + window[1] > ADDR_SPACE:
                raise AssertionError(
                    f"{tag}: SEP window (0x{window[0]:x}, 0x{window[1]:x}) after the {name} write "
                    f"overlaps the SMC window (0x{smc[0]:x}, 0x{smc[1]:x}) or leaves the space"
                )
            await self._sba_write64(addr, value, f"{tag}_sep_{name}")
        await self._until(
            f"{tag}_sep_base_port",
            lambda: _val(dut.sep_xbar_global_base_o) == base,
            PORT_BOUND,
            fatal=False,
        )
        await self._until(
            f"{tag}_sep_size_port",
            lambda: _val(dut.sep_xbar_region_size_o) == size,
            PORT_BOUND,
            fatal=False,
        )
        ports = self._ports()
        if not readback:
            return {"port": (_hx(ports["sep_base"]), _hx(ports["sep_size"]))}
        rb_base = await self._sba_read64(SEP_GLOBAL_BASE_ADDR, f"{tag}_rb_base")
        rb_size = await self._sba_read64(SEP_REGION_SIZE_ADDR, f"{tag}_rb_size")
        placed = {
            "port": (_hx(ports["sep_base"]), _hx(ports["sep_size"])),
            "readback": (_hx(rb_base), _hx(rb_size)),
        }
        self._info(f"{tag} SEP aperture base=0x{base:x} size=0x{size:x} placed={placed}")
        return placed

    @staticmethod
    def _placed_want(base: int, size: int) -> dict:
        return {"port": (_hx(base), _hx(size)), "readback": (_hx(base), _hx(size))}

    async def _fabric_sized(self, addr: int, data: int, size: int, wstrb: int, label: str) -> int:
        """One JTAG2AXI SINGLE_OP write; captures until it leaves busy, bounded."""
        raw = pack_single_op(J2A_OP_WRITE, addr, data, wstrb=wstrb, size=size)
        await self._dr(DTP_IR_SMC_AXI_SINGLE_OP, raw, SMC_DBG_SINGLE_OP_LEN, f"{label}_issue")
        used = 0
        while True:
            captured, _ = await self._dr(
                DTP_IR_SMC_AXI_SINGLE_OP,
                0,
                SMC_DBG_SINGLE_OP_LEN,
                f"{label}_c{used}",
                counted=used == 0,
            )
            status, _ = unpack_single_op(captured)
            used += 1
            if status != J2A_STATUS_BUSY:
                break
            if used >= CAPTURE_POLL_LIMIT:
                self._site(
                    "op_capture", label, CAPTURE_POLL_LIMIT, "captures", used, f"op={status}", True
                )
            await ClockCycles(self.dut.clk_smu_i, CAPTURE_POLL_CLK)
        self._site("op_capture", label, CAPTURE_POLL_LIMIT, "captures", used, f"op={status}", False)
        return status

    async def _txn(
        self,
        label: str,
        *,
        write: bool,
        addr: int,
        beats: int,
        xid: int,
        burst: int = AXI_BURST_INCR,
        size: int = SIZE_8B,
        payload: bytes | None = None,
    ) -> dict:
        """One ext_in transaction; every handshake it caused on ext_in, sep_in and smc_in."""
        mon = self.mon
        c0 = self._counts()
        mk = mon.mark()
        pmk = {name: m.mark() for name, m in self.pmon.items()}
        if write:
            if payload is None:
                payload = bytes((xid + i) & 0xFF for i in range(beats * (1 << size)))
            event = self.master.init_write(
                addr, payload, size=size, prot=PROT_NONSECURE, burst=burst, awid=xid
            )
        else:
            event = self.master.init_read(
                addr, beats * (1 << size), size=size, prot=PROT_NONSECURE, burst=burst, arid=xid
            )
        await self._until(label, event.is_set, XFER_BOUND)
        if write:
            seen = lambda: any(e["bid"] == xid for e in mon.since(mk, "b"))  # noqa: E731
        else:
            seen = lambda: any(  # noqa: E731
                e["rid"] == xid and e["rlast"] == 1 for e in mon.since(mk, "r")
            )
        await self._until(f"{label}_monitor", seen, MON_BOUND)
        c1 = self._counts()
        t = {
            "label": label,
            "addr": addr,
            "xid": xid,
            "burst": burst,
            "len": beats - 1,
            "aw": mon.since(mk, "aw"),
            "w": mon.since(mk, "w"),
            "b": [e for e in mon.since(mk, "b") if e["bid"] == xid],
            "ar": mon.since(mk, "ar"),
            "r": [e for e in mon.since(mk, "r") if e["rid"] == xid],
            "d": {n: self._delta(c0, c1, n) for n in COUNTS},
            "tap_addr": _val(self.dut.sep_xbar_in_ar_addr_o),
            "aw_addr": _val(self.dut.sep_xbar_in_aw_addr_o),
        }
        for name, m in self.pmon.items():
            t[f"{name}_ar"] = _ax(m.since(pmk[name], "ar"), "ar")
            t[f"{name}_aw"] = _ax(m.since(pmk[name], "aw"), "aw")
            t[f"{name}_w"] = len(m.since(pmk[name], "w"))
        self._info(
            f"TXN {label} {'write' if write else 'read'} addr=0x{addr:014x} id=0x{xid:x} "
            f"burst={BURST_NAMES[burst]} len={beats - 1} deltas={t['d']} "
            f"sep_in_ar={t['sep_in_ar']} sep_in_aw={t['sep_in_aw']} smc_in_ar={t['smc_in_ar']} "
            f"smc_in_aw={t['smc_in_aw']} r={[(_rn(e['rresp']), _hx(e['rlast'])) for e in t['r']]} "
            f"b={[_rn(e['bresp']) for e in t['b']]} tap_addr={_hx(t['tap_addr'])} "
            f"aw_addr={_hx(t['aw_addr'])}"
        )
        return t

    @staticmethod
    def _moved(t: dict, *names: str, watch: tuple[str, ...] = COUNTS) -> dict:
        """The deltas of ``names`` and the sum of the other ``watch`` counter deltas."""
        rest = [v for n, v in t["d"].items() if n in watch and n not in names]
        others = "X" if "X" in rest else sum(abs(v) for v in rest)
        return {**{n: t["d"][n] for n in names}, "others": others}

    @staticmethod
    def _moved_want(**deltas: int) -> dict:
        return {**deltas, "others": 0}

    @staticmethod
    def _rd_shape(t: dict) -> dict:
        r = t["r"]
        return {
            "beats": len(r),
            "rlast_at": [i for i, e in enumerate(r) if e["rlast"] != 0],
            "x_beats": sum(1 for e in r if None in (e["rresp"], e["rlast"], e["rid"])),
            "ext_ar": len(t["ar"]),
        }

    @staticmethod
    def _rd_want(arlen: int) -> dict:
        return {"beats": arlen + 1, "rlast_at": [arlen], "x_beats": 0, "ext_ar": 1}

    @staticmethod
    def _wr_shape(t: dict) -> dict:
        w, b = t["w"], t["b"]
        wlast_cyc = w[-1]["cyc"] if w else None
        return {
            "w_hs": len(w),
            "wlast_at": [i for i, e in enumerate(w) if e["wlast"] != 0],
            "b_hs": len(b),
            "b_before_wlast": sum(1 for e in b if wlast_cyc is None or e["cyc"] <= wlast_cyc),
            "x_b": sum(1 for e in b if e["bresp"] is None),
        }

    @staticmethod
    def _wr_want(awlen: int) -> dict:
        return {"w_hs": awlen + 1, "wlast_at": [awlen], "b_hs": 1, "b_before_wlast": 0, "x_b": 0}

    @staticmethod
    def _codes(t: dict) -> str:
        if t["r"]:
            return ",".join(_rn(e["rresp"]) for e in t["r"])
        return ",".join(_rn(e["bresp"]) for e in t["b"]) or "none"

    @staticmethod
    def _resp(t: dict) -> list[str]:
        return [_rn(e["rresp"]) for e in t["r"]] if t["r"] else [_rn(e["bresp"]) for e in t["b"]]

    def _word(self, t: dict) -> int | None:
        if not t["r"] or t["r"][0]["rdata"] is None:
            return None
        return (t["r"][0]["rdata"] >> (8 * (t["addr"] % BEAT_BYTES))) & 0xFFFF_FFFF

    def _resp_line(self, tag: str, t: dict) -> str:
        return f"{tag}:{BURST_NAMES[t['burst']]}/len{t['len']}=[{self._codes(t)}]"

    # ------------------------------------------------------------------ steps

    async def _s1_setup(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        self.mon = _ExtInMonitor(dut)
        self.pmon = {
            name: _PortMonitor(dut, inst, self.mon) for name, inst in _PORT_INSTANCES.items()
        }
        await RisingEdge(dut.clk_smu_i)
        self._step("S1", "sensing, SMC inbound filter entry 0, SEP debug module, counters")
        self._info(f"SEED: RANDOM_SEED={self.seed} (every value of this leaf is directed)")
        sb.expect_eq("S1 SEP=1 build with the crossbar elaborated", _val(dut.sep_enabled_o), 1)
        idcode = await self._jtag_bringup("s1")
        lc, dbg = await self._posture("s1")
        security = _val(dut.tb_smc_jtag2axi_security_disable)
        statuses = await self._program_inbound0("s1")
        dmactive = await self._activate_debug_module("s1")
        self.ports = self._ports()
        setup = {
            "idcode": _hx(idcode),
            "dbg_disable": dbg,
            "j2a_security_disable": security,
            "inbound0_status": statuses,
            "dmactive": dmactive,
            "ports": tuple(_hx(v) for v in self.ports.values()),
        }
        self._info(f"S1 setup {_kv(setup)} lc_state={_hx(lc)} counters={self._counts()}")
        self._pre(
            "S1 setup access path open, apertures at their RDL reset",
            setup,
            {
                "idcode": _hx(DTP_DEFAULT_IDCODE),
                "dbg_disable": 0,
                "j2a_security_disable": 0,
                "inbound0_status": [J2A_STATUS_SUCCESS] * 3,
                "dmactive": 1,
                "ports": tuple(
                    _hx(v)
                    for v in (
                        SEP_GLOBAL_BASE_RESET,
                        SEP_REGION_SIZE_RESET,
                        SMC_GLOBAL_BASE_RESET,
                        SMC_REGION_SIZE_RESET,
                    )
                ),
            },
        )
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        clear_profile(self.master.driver)
        self._ctrl("SETUP_OK")
        self.steps["S1"] = True

    async def _s2_sep_edges(self) -> None:
        self._step("S2", "SEP aperture 0x0400_0000 / 0x1000_0840; singles at E-8 and E")
        fill = await self._place_sep("S2_fill", SEP_B0, FILL_SIZE, size_first=False, readback=False)
        fill_wr = await self._txn(
            "S2_fill_sram", write=True, addr=FILL_START, beats=FILL_BEATS, xid=0x1F
        )
        self._info(
            f"S2 fill window {fill} [0x{FILL_START:x}, 0x{FILL_START + 8 * FILL_BEATS:x}) "
            f"bresp={self._resp(fill_wr)} counters={fill_wr['d']}"
        )
        self._pre(
            "S2 fill write lands inside the fill window",
            {"port": fill["port"], "bresp": self._resp(fill_wr), "w": len(fill_wr["w"])},
            {"port": (_hx(SEP_B0), _hx(FILL_SIZE)), "bresp": [_rn(RESP_OKAY)], "w": FILL_BEATS},
        )
        placed = await self._place_sep("S2", SEP_B0, SEP_SIZE0, size_first=False)
        self.log.info(
            "OBS-SEP-NOALIGN-LEGAL: base=0x%x size=0x%x size_power_of_two=%s "
            "base_aligned_to_size=%s end=0x%x end_4k_aligned=%s port=%s readback=%s "
            "(no constraint stated in sep_cpu_ctrl.adoc; SF-029 open)",
            SEP_B0,
            SEP_SIZE0,
            SEP_SIZE0 & (SEP_SIZE0 - 1) == 0,
            SEP_B0 % SEP_SIZE0 == 0,
            SEP_END0,
            SEP_END0 % 0x1000 == 0,
            placed["port"],
            placed["readback"],
        )
        e8 = SEP_END0 - 8
        wr_e8 = await self._txn(
            "S2_write_e8",
            write=True,
            addr=e8,
            beats=1,
            xid=0x20,
            payload=E8_WORD.to_bytes(8, "little"),
        )
        rd_e8 = await self._txn("S2_read_e8", write=False, addr=e8, beats=1, xid=0x21)
        rd_e = await self._txn("S2_read_e", write=False, addr=SEP_END0, beats=1, xid=0x22)
        wr_e = await self._txn("S2_write_e", write=True, addr=SEP_END0, beats=1, xid=0x23)
        self._info(
            f"S2 E-8 write bresp={self._resp(wr_e8)} read rresp={self._resp(rd_e8)} "
            f"rdata={[_hx(e['rdata']) for e in rd_e8['r']]}"
        )
        self.obs["s2"] = {
            "placed": placed,
            "e8_write": (self._moved(wr_e8, SEP_AW), _hx(wr_e8["aw_addr"])),
            "e8_read": (
                self._moved(rd_e8, SEP_AR),
                self._resp(rd_e8),
                [_hx(e["rdata"]) for e in rd_e8["r"]],
            ),
            "e_read": (self._moved(rd_e), self._resp(rd_e)),
            "e_write": (self._moved(wr_e), self._resp(wr_e)),
        }
        self._ctrl("SEP_EDGES")
        self.steps["S2"] = True

    async def _s3_rebase(self) -> None:
        self._step("S3", "SEP base 0x0400_1000; write at base+0x1000_0000, SEP-local SRAM read")
        placed = await self._place_sep("S3", SEP_B_REBASE, SEP_SIZE0, size_first=False)
        wr = await self._txn(
            "S3_write_rebase",
            write=True,
            addr=REBASE_PROBE,
            beats=1,
            xid=0x30,
            payload=REBASE_WORD.to_bytes(8, "little"),
        )
        local = await self._sba_read64(SRAM_LOCAL, "S3_sram_local")
        self._info(
            f"S3 write at 0x{REBASE_PROBE:x} bresp={self._resp(wr)}; SEP-local SRAM "
            f"0x{SRAM_LOCAL:x} reads 0x{local:016x}, written 0x{REBASE_WORD:016x}"
        )
        s2 = self.obs["s2"]
        self._grade(
            "CHK-SEP-NOALIGN",
            {
                "s2_placed": s2["placed"],
                "s2_e8_counted_at_sep": s2["e8_write"][0][SEP_AW],
                "s2_e_counted": s2["e_read"][0]["others"] + s2["e_write"][0]["others"],
                "s3_placed": placed,
                "s3_write": (self._moved(wr, SEP_AW), _hx(wr["aw_addr"])),
                "s3_sram_local": _hx(local),
            },
            {
                "s2_placed": self._placed_want(SEP_B0, SEP_SIZE0),
                "s2_e8_counted_at_sep": 1,
                "s2_e_counted": 0,
                "s3_placed": self._placed_want(SEP_B_REBASE, SEP_SIZE0),
                "s3_write": (self._moved_want(**{SEP_AW: 1}), _hx(REBASE_PROBE)),
                "s3_sram_local": _hx(REBASE_WORD),
            },
            "SEP_REGION_SIZE and sep_xbar_region_size_o read 0x1000_0840, E-8 routes and E does "
            "not, and with base 0x0400_1000 the word written at base+0x1000_0000 is at SEP-local "
            "SRAM 0x1000_0000; OBS-SEP-NOALIGN-LEGAL logged",
        )
        self._ctrl("SEP_REBASE")
        self.steps["S3"] = True

    async def _s4_sep_past_end(self) -> None:
        self._step("S4", "S2 placement; INCR read and write of 8 beats from E-16")
        placed = await self._place_sep("S4", SEP_B0, SEP_SIZE0, size_first=False)
        start = SEP_END0 - 16
        rd = await self._txn("S4_incr_read", write=False, addr=start, beats=8, xid=0x40)
        wr = await self._txn("S4_incr_write", write=True, addr=start, beats=8, xid=0x41)
        self.log.info(
            "OBS-PAST-END-SEP-RESP: %s %s (beats past E: %d of 8; SF-005 open)",
            self._resp_line("read", rd),
            self._resp_line("write", wr),
            sum(1 for k in range(8) if start + 8 * k >= SEP_END0),
        )
        self._grade(
            "CHK-SEP-PAST-END",
            {
                "placed": placed,
                "rd_counters": self._moved(rd, SEP_AR),
                "rd_tap_addr": _hx(rd["tap_addr"]),
                "rd_sep_in_ar": rd["sep_in_ar"],
                "rd_shape": self._rd_shape(rd),
                "wr_counters": self._moved(wr, SEP_AW),
                "wr_aw_addr": _hx(wr["aw_addr"]),
                "wr_sep_in_aw": wr["sep_in_aw"],
                "wr_sep_in_w": wr["sep_in_w"],
                "wr_shape": self._wr_shape(wr),
                "bid": [_hx(e["bid"]) for e in wr["b"]],
            },
            {
                "placed": self._placed_want(SEP_B0, SEP_SIZE0),
                "rd_counters": self._moved_want(**{SEP_AR: 1}),
                "rd_tap_addr": _hx(start),
                "rd_sep_in_ar": [(_hx(start), 7, "INCR", SIZE_8B)],
                "rd_shape": self._rd_want(7),
                "wr_counters": self._moved_want(**{SEP_AW: 1}),
                "wr_aw_addr": _hx(start),
                "wr_sep_in_aw": [(_hx(start), 7, "INCR", SIZE_8B)],
                "wr_sep_in_w": 8,
                "wr_shape": self._wr_want(7),
                "bid": [_hx(0x41)],
            },
            "INCR ARLEN/AWLEN 7 from E-16: one AR and one AW at sep_in with the first address, 8 R "
            "beats with RLAST on the last only and RID=ARID, 8 W beats and one B with BID=AWID, no "
            "other counter",
        )
        self._ctrl("SEP_PAST_END")
        self.steps["S4"] = True

    async def _s5_wrap_fixed(self) -> None:
        self._step("S5", "WRAP read ARLEN 15 from E-16; FIXED read and write of 4 beats at E-8")
        e16, e8 = SEP_END0 - 16, SEP_END0 - 8
        wrap = await self._txn(
            "S5_wrap_read", write=False, addr=e16, beats=16, xid=0x50, burst=AXI_BURST_WRAP
        )
        frd = await self._txn(
            "S5_fixed_read", write=False, addr=e8, beats=4, xid=0x51, burst=AXI_BURST_FIXED
        )
        fwr = await self._txn(
            "S5_fixed_write", write=True, addr=e8, beats=4, xid=0x52, burst=AXI_BURST_FIXED
        )
        self.log.info(
            "OBS-WRAP-FIXED-RESP: %s %s %s (WRAP container [0x%x, 0x%x) straddles E=0x%x; "
            "SF-005 open)",
            self._resp_line("wrap_read", wrap),
            self._resp_line("fixed_read", frd),
            self._resp_line("fixed_write", fwr),
            SEP_END0 - 64,
            SEP_END0 + 64,
            SEP_END0,
        )
        self._grade(
            "CHK-WRAP-FIXED",
            {
                "wrap_counters": self._moved(wrap, SEP_AR),
                "wrap_sep_in_ar": wrap["sep_in_ar"],
                "wrap_shape": self._rd_shape(wrap),
                "fixed_rd_counters": self._moved(frd, SEP_AR),
                "fixed_rd_sep_in_ar": frd["sep_in_ar"],
                "fixed_rd_shape": self._rd_shape(frd),
                "fixed_wr_counters": self._moved(fwr, SEP_AW),
                "fixed_wr_sep_in_aw": fwr["sep_in_aw"],
                "fixed_wr_shape": self._wr_shape(fwr),
                "fixed_wr_bid": [_hx(e["bid"]) for e in fwr["b"]],
            },
            {
                "wrap_counters": self._moved_want(**{SEP_AR: 1}),
                "wrap_sep_in_ar": [(_hx(e16), 15, "WRAP", SIZE_8B)],
                "wrap_shape": self._rd_want(15),
                "fixed_rd_counters": self._moved_want(**{SEP_AR: 1}),
                "fixed_rd_sep_in_ar": [(_hx(e8), 3, "FIXED", SIZE_8B)],
                "fixed_rd_shape": self._rd_want(3),
                "fixed_wr_counters": self._moved_want(**{SEP_AW: 1}),
                "fixed_wr_sep_in_aw": [(_hx(e8), 3, "FIXED", SIZE_8B)],
                "fixed_wr_shape": self._wr_want(3),
                "fixed_wr_bid": [_hx(0x52)],
            },
            "WRAP ARLEN 15: one AR at sep_in, 16 beats with RLAST on the last only; FIXED read 4 "
            "beats, FIXED write 4 W beats and one B; no other counter",
        )
        self._ctrl("WRAP_FIXED")
        self.steps["S5"] = True

    async def _s6_carry(self) -> None:
        self._step("S6", "SEP aperture 0xFF_FFFF_FF00_0000 / 0x0100_0000; 8 beats to 2^56")
        placed = await self._place_sep("S6", SEP_B_CARRY, SEP_SIZE_CARRY, size_first=True)
        rd = await self._txn("S6_carry_read", write=False, addr=CARRY_ADDR, beats=8, xid=0x60)
        wr = await self._txn("S6_carry_write", write=True, addr=CARRY_ADDR, beats=8, xid=0x61)
        self.log.info(
            "OBS-CARRY-RESP: %s %s (base+size=0x%x; SEP-local 0x%x is external to the SEP) "
            "smu_axi_out_deltas read=(%s,%s) write=(%s,%s)",
            self._resp_line("read", rd),
            self._resp_line("write", wr),
            SEP_B_CARRY + SEP_SIZE_CARRY,
            CARRY_ADDR - SEP_B_CARRY,
            rd["d"][OUT_R],
            rd["d"][OUT_W],
            wr["d"][OUT_R],
            wr["d"][OUT_W],
        )
        self._grade(
            "CHK-CARRY-BURST",
            {
                "placed": placed,
                "rd_counters": self._moved(rd, SEP_AR, watch=INBOUND),
                "rd_tap_addr": _hx(rd["tap_addr"]),
                "rd_sep_in_ar": rd["sep_in_ar"],
                "rd_shape": self._rd_shape(rd),
                "wr_counters": self._moved(wr, SEP_AW, watch=INBOUND),
                "wr_aw_addr": _hx(wr["aw_addr"]),
                "wr_shape": self._wr_shape(wr),
            },
            {
                "placed": self._placed_want(SEP_B_CARRY, SEP_SIZE_CARRY),
                "rd_counters": self._moved_want(**{SEP_AR: 1}),
                "rd_tap_addr": _hx(CARRY_ADDR),
                "rd_sep_in_ar": [(_hx(CARRY_ADDR), 7, "INCR", SIZE_8B)],
                "rd_shape": self._rd_want(7),
                "wr_counters": self._moved_want(**{SEP_AW: 1}),
                "wr_aw_addr": _hx(CARRY_ADDR),
                "wr_shape": self._wr_want(7),
            },
            "with base+size = 2^56 the INCR read and write from 0xFF_FFFF_FFFF_FFC0 reach sep_in "
            "(not answered by the crossbar), 8 beats with RLAST on the last only, one B",
        )
        self._ctrl("CARRY")
        self.steps["S6"] = True

    async def _s7_wide_sep(self) -> None:
        self._step("S7", "SEP aperture 0x1_0000_0000 / 0x8000_0000; probes at +0x4000_0008/0000")
        placed = await self._place_sep("S7", SEP_B_WIDE, SEP_SIZE_WIDE, size_first=False)
        rd = await self._txn("S7_read_past", write=False, addr=WIDE_PAST, beats=1, xid=0x5C)
        wr = await self._txn(
            "S7_write_past",
            write=True,
            addr=WIDE_PAST,
            beats=1,
            xid=0xA3,
            payload=WIDE_WORD.to_bytes(8, "little"),
        )
        edge = await self._txn("S7_read_edge", write=False, addr=WIDE_EDGE, beats=1, xid=0x3A)
        self.log.info(
            "OBS-WIDE-SEP-RDATA: read_0x%x rdata=%s read_0x%x rdata=%s (SF-007, SF-008 open)",
            WIDE_PAST,
            [_hx(e["rdata"]) for e in rd["r"]],
            WIDE_EDGE,
            [_hx(e["rdata"]) for e in edge["r"]],
        )
        self._grade(
            "CHK-WIDE-SEP",
            {
                "placed": placed,
                "past_rd": (
                    self._moved(rd, SEP_AR),
                    self._resp(rd),
                    [_hx(e["rid"]) for e in rd["r"]],
                ),
                "past_wr": (
                    self._moved(wr, SEP_AW),
                    self._resp(wr),
                    [_hx(e["bid"]) for e in wr["b"]],
                ),
                "edge_rd": (
                    self._moved(edge, SEP_AR),
                    self._resp(edge),
                    [_hx(e["rid"]) for e in edge["r"]],
                ),
            },
            {
                "placed": self._placed_want(SEP_B_WIDE, SEP_SIZE_WIDE),
                "past_rd": (self._moved_want(**{SEP_AR: 1}), [_rn(RESP_DECERR)], [_hx(0x5C)]),
                "past_wr": (self._moved_want(**{SEP_AW: 1}), [_rn(RESP_DECERR)], [_hx(0xA3)]),
                "edge_rd": (self._moved_want(**{SEP_AR: 1}), [_rn(RESP_DECERR)], [_hx(0x3A)]),
            },
            "an aperture wider than the SEP inbound space routes B+0x4000_0008 and B+0x4000_0000 "
            "to sep_in, and the SEP answers each DECERR with the ID echoed",
        )
        self._ctrl("WIDE_SEP")
        self.steps["S7"] = True

    async def _s8_smc_phase(self) -> None:
        dut = self.dut
        self._step("S8", "SEP back to 0x0400_0000 / 0x1000_0840; SMC 0x4000_0400 / 0x400")
        sep = await self._place_sep("S8", SEP_B0, SEP_SIZE0, size_first=True)
        base_status = await self._fabric_sized(
            SMC_GLOBAL_BASE_REG, SMC_B, SMC_DBG_AXSIZE_8B, 0xFF, "s8_smc_global_base"
        )
        size_status = await self._fabric_sized(
            SMC_REGION_SIZE_REG, SMC_SIZE, SMC_DBG_AXSIZE_4B, 0x0F, "s8_smc_region_size"
        )
        await self._until(
            "S8_smc_base_port",
            lambda: _val(dut.smc_global_base_o) == SMC_B,
            PORT_BOUND,
            fatal=False,
        )
        await self._until(
            "S8_smc_size_port",
            lambda: _val(dut.smc_region_size_o) == SMC_SIZE,
            PORT_BOUND,
            fatal=False,
        )
        self.ports = self._ports()
        self.obs["s8"] = {
            "sep_placed": sep,
            "j2a_status": (base_status, size_status),
            "smc_ports": (_hx(self.ports["smc_base"]), _hx(self.ports["smc_size"])),
        }
        self._info(
            f"S8 {_kv(self.obs['s8'])}; REGION_SIZE 0x400 leaves BASE_CONFIG outside the window "
            "JTAG2AXI reaches, so it is not read back and the leg ends with rst_cold_ni"
        )
        self._pre(
            "S8 SEP aperture back and the SMC aperture at 0x4000_0400 / 0x400",
            self.obs["s8"],
            {
                "sep_placed": self._placed_want(SEP_B0, SEP_SIZE0),
                "j2a_status": (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS),
                "smc_ports": (_hx(SMC_B), _hx(SMC_SIZE)),
            },
        )
        self._ctrl("SMC_PHASE_SET")
        self.steps["S8"] = True

    async def _s9_sep_below(self) -> None:
        self._step("S9", "SEP base 0x2FFF_FBC0 so the SEP end is the SMC base 0x4000_0400")
        placed = await self._place_sep("S9", SEP_B_BELOW, SEP_SIZE0, size_first=False)
        w3f8 = await self._txn("S9_write_3f8", write=True, addr=SMC_B - 8, beats=1, xid=0x90)
        r3f8 = await self._txn("S9_read_3f8", write=False, addr=SMC_B - 8, beats=1, xid=0x91)
        r400 = await self._txn("S9_read_400", write=False, addr=SMC_B, beats=1, xid=0x92)
        word0 = await self._txn(
            "S9_smc_word_before", write=False, addr=SMC_WDT_CTRL, beats=1, xid=0x93, size=SIZE_4B
        )
        key = await self._txn(
            "S9_smc_wdt_key",
            write=True,
            addr=SMC_WDT_KEY,
            beats=1,
            xid=0x97,
            size=SIZE_4B,
            payload=WDT_KEY_MAGIC.to_bytes(4, "little"),
        )
        start = SMC_B - 16
        brd = await self._txn("S9_incr_read", write=False, addr=start, beats=8, xid=0x94)
        bwr = await self._txn("S9_incr_write", write=True, addr=start, beats=8, xid=0x95)
        word1 = await self._txn(
            "S9_smc_word_after", write=False, addr=SMC_WDT_CTRL, beats=1, xid=0x96, size=SIZE_4B
        )
        live_key = await self._txn(
            "S9_smc_live_key",
            write=True,
            addr=SMC_WDT_KEY,
            beats=1,
            xid=0x98,
            size=SIZE_4B,
            payload=WDT_KEY_MAGIC.to_bytes(4, "little"),
        )
        live_wr = await self._txn(
            "S9_smc_live_ctrl",
            write=True,
            addr=SMC_WDT_CTRL,
            beats=1,
            xid=0x99,
            size=SIZE_4B,
            payload=WDT_COREAWAKE.to_bytes(4, "little"),
        )
        live_rd = await self._txn(
            "S9_smc_live_readback", write=False, addr=SMC_WDT_CTRL, beats=1, xid=0x9A, size=SIZE_4B
        )
        live_word = self._word(live_rd)
        self.obs["s9"] = {
            "placed": placed,
            "w3f8": self._moved(w3f8, SEP_AW),
            "r3f8": self._moved(r3f8, SEP_AR),
            "r400": self._moved(r400, SMC_AR),
            "brd": brd,
            "bwr": bwr,
            "words": (self._word(word0), self._word(word1)),
            "word_resp": (self._resp(word0), self._resp(word1)),
            "key_resp": self._resp(key),
            "live": (
                self._resp(live_key),
                self._resp(live_wr),
                self._resp(live_rd),
                None if live_word is None else _hx(live_word & WDT_CTRL_CFG_MASK),
            ),
            "single_resp": (self._resp(w3f8), self._resp(r3f8), self._resp(r400)),
        }
        self._info(
            f"S9 SMC word at 0x{SMC_WDT_CTRL:x} before={_hx(self._word(word0))} "
            f"after={_hx(self._word(word1))} resp={self.obs['s9']['word_resp']} "
            f"key resp={self.obs['s9']['key_resp']}; live control KEY, CTRL=0x{WDT_COREAWAKE:x} "
            f"write and read-back (resp, resp, resp, configuration bits)={self.obs['s9']['live']}"
        )
        self._ctrl("SEP_BELOW")
        self.steps["S9"] = True

    async def _s10_smc_below(self) -> None:
        self._step("S10", "SEP base 0x4000_0800, the SMC end")
        placed = await self._place_sep("S10", SEP_B_ABOVE, SEP_SIZE0, size_first=False)
        r7f8 = await self._txn("S10_read_7f8", write=False, addr=SMC_END - 8, beats=1, xid=0xA0)
        r800 = await self._txn("S10_read_800", write=False, addr=SMC_END, beats=1, xid=0xA1)
        start = SMC_END - 16
        brd = await self._txn("S10_incr_read", write=False, addr=start, beats=8, xid=0xA2)
        s9 = self.obs["s9"]
        self.log.info(
            "OBS-ADJ-RESP: S9 %s %s write_0x%x=[%s] read_0x%x=[%s] read_0x%x=[%s] "
            "smc_word=[%s]; S10 %s read_0x%x=[%s] read_0x%x=[%s] (SF-005 open)",
            self._resp_line("sep_below_read", s9["brd"]),
            self._resp_line("sep_below_write", s9["bwr"]),
            SMC_B - 8,
            ",".join(s9["single_resp"][0]),
            SMC_B - 8,
            ",".join(s9["single_resp"][1]),
            SMC_B,
            ",".join(s9["single_resp"][2]),
            ";".join(",".join(r) for r in s9["word_resp"]),
            self._resp_line("smc_below_read", brd),
            SMC_END - 8,
            ",".join(self._resp(r7f8)),
            SMC_END,
            ",".join(self._resp(r800)),
        )
        self._grade(
            "CHK-ADJACENT-SINGLES",
            {
                "sep_below_placed": s9["placed"],
                "sep_below_write_0x400003f8": s9["w3f8"],
                "sep_below_read_0x400003f8": s9["r3f8"],
                "sep_below_read_0x40000400": s9["r400"],
                "smc_below_placed": placed,
                "smc_below_read_0x400007f8": self._moved(r7f8, SMC_AR),
                "smc_below_read_0x40000800": self._moved(r800, SEP_AR, watch=INBOUND),
            },
            {
                "sep_below_placed": self._placed_want(SEP_B_BELOW, SEP_SIZE0),
                "sep_below_write_0x400003f8": self._moved_want(**{SEP_AW: 1}),
                "sep_below_read_0x400003f8": self._moved_want(**{SEP_AR: 1}),
                "sep_below_read_0x40000400": self._moved_want(**{SMC_AR: 1}),
                "smc_below_placed": self._placed_want(SEP_B_ABOVE, SEP_SIZE0),
                "smc_below_read_0x400007f8": self._moved_want(**{SMC_AR: 1}),
                "smc_below_read_0x40000800": self._moved_want(**{SEP_AR: 1}),
            },
            "with adjacent apertures each edge access is counted at exactly the port the "
            "arithmetic selects",
        )
        brd9, bwr9 = s9["brd"], s9["bwr"]
        words = s9["words"]
        self._grade(
            "CHK-ADJACENT-BURST",
            {
                "sep_below_rd_counters": self._moved(brd9, SEP_AR),
                "sep_below_rd_sep_in_ar": brd9["sep_in_ar"],
                "sep_below_rd_shape": self._rd_shape(brd9),
                "sep_below_wr_counters": self._moved(bwr9, SEP_AW),
                "sep_below_wr_shape": self._wr_shape(bwr9),
                "smc_wdt_key_resp": s9["key_resp"],
                "smc_word_same": words[0] is not None and words[0] == words[1],
                "smc_word_resp": s9["word_resp"],
                "smc_ctrl_live_control": s9["live"],
                "smc_below_rd_counters": self._moved(brd, SMC_AR),
                "smc_below_rd_smc_in_ar_len": [a[1] for a in brd["smc_in_ar"]],
                "smc_below_rd_shape": self._rd_shape(brd),
            },
            {
                "sep_below_rd_counters": self._moved_want(**{SEP_AR: 1}),
                "sep_below_rd_sep_in_ar": [(_hx(SMC_B - 16), 7, "INCR", SIZE_8B)],
                "sep_below_rd_shape": self._rd_want(7),
                "sep_below_wr_counters": self._moved_want(**{SEP_AW: 1}),
                "sep_below_wr_shape": self._wr_want(7),
                "smc_wdt_key_resp": [_rn(RESP_OKAY)],
                "smc_word_same": True,
                "smc_word_resp": ([_rn(RESP_OKAY)], [_rn(RESP_OKAY)]),
                "smc_ctrl_live_control": (
                    [_rn(RESP_OKAY)],
                    [_rn(RESP_OKAY)],
                    [_rn(RESP_OKAY)],
                    _hx(WDT_COREAWAKE),
                ),
                "smc_below_rd_counters": self._moved_want(**{SMC_AR: 1}),
                "smc_below_rd_smc_in_ar_len": [7],
                "smc_below_rd_shape": self._rd_want(7),
            },
            "a burst running into the adjacent aperture is counted only at the port of its first "
            "address with ARLEN+1 beats and RLAST last; with the CORE0 watchdog KEY written OKAY "
            "before the write burst, its CTRL word at 0x4000_0400 reads OKAY and unchanged, and a "
            "KEY-unlocked CTRL write of WDOGCOREAWAKE then reads back changed",
        )
        self._ctrl("SMC_BELOW")
        self.steps["S10"] = True

    async def _s11_smc_past_end(self) -> None:
        dut = self.dut
        self._step("S11", "SEP back at 0x0400_0000; SMC edge singles and bursts, rst_cold_ni")
        placed = await self._place_sep("S11", SEP_B0, SEP_SIZE0, size_first=False)
        r7f8 = await self._txn("S11_read_7f8", write=False, addr=SMC_END - 8, beats=1, xid=0xB0)
        w7f8 = await self._txn(
            "S11_write_7f8", write=True, addr=SMC_END - 8, beats=1, xid=0xB1, payload=bytes(8)
        )
        r800 = await self._txn("S11_read_800", write=False, addr=SMC_END, beats=1, xid=0xB2)
        w800 = await self._txn(
            "S11_write_800", write=True, addr=SMC_END, beats=1, xid=0xB3, payload=bytes(8)
        )
        start = SMC_END - 16
        brd = await self._txn("S11_incr_read", write=False, addr=start, beats=8, xid=0xB4)
        # A zero payload: the beats past the SMC end land on SMC registers if the burst is
        # forwarded whole, and zero leaves them disabled.
        bwr = await self._txn(
            "S11_incr_write", write=True, addr=start, beats=8, xid=0xB5, payload=bytes(64)
        )
        self.log.info(
            "OBS-PAST-END-SMC-RESP: %s %s singles read_0x%x=[%s] write_0x%x=[%s] "
            "(SF-005, SF-006 open)",
            self._resp_line("read", brd),
            self._resp_line("write", bwr),
            SMC_END - 8,
            ",".join(self._resp(r7f8)),
            SMC_END - 8,
            ",".join(self._resp(w7f8)),
        )
        self._grade(
            "CHK-SMC-PAST-END",
            {
                "placed": placed,
                "rd_counters": self._moved(brd, SMC_AR),
                "rd_smc_in_ar_len": [(a[1], a[2]) for a in brd["smc_in_ar"]],
                "rd_shape": self._rd_shape(brd),
                "wr_counters": self._moved(bwr, SMC_AW),
                "wr_smc_in_aw_len": [(a[1], a[2]) for a in bwr["smc_in_aw"]],
                "wr_smc_in_w": bwr["smc_in_w"],
                "wr_shape": self._wr_shape(bwr),
                "bid": [_hx(e["bid"]) for e in bwr["b"]],
            },
            {
                "placed": self._placed_want(SEP_B0, SEP_SIZE0),
                "rd_counters": self._moved_want(**{SMC_AR: 1}),
                "rd_smc_in_ar_len": [(7, "INCR")],
                "rd_shape": self._rd_want(7),
                "wr_counters": self._moved_want(**{SMC_AW: 1}),
                "wr_smc_in_aw_len": [(7, "INCR")],
                "wr_smc_in_w": 8,
                "wr_shape": self._wr_want(7),
                "bid": [_hx(0xB5)],
            },
            "INCR ARLEN/AWLEN 7 from 0x4000_07F0 past the SMC end: one AR and one AW at smc_in, 8 "
            "beats with RLAST on the last only and RID=ARID, 8 W beats and one B with BID=AWID, "
            "no other counter",
        )
        s2 = self.obs["s2"]
        self._grade(
            "CHK-END-EXCL",
            {
                "sep_e8_write": s2["e8_write"],
                "sep_e8_read": s2["e8_read"],
                "sep_e_read": s2["e_read"],
                "sep_e_write": s2["e_write"],
                "smc_7f8_read": self._moved(r7f8, SMC_AR),
                "smc_7f8_write": self._moved(w7f8, SMC_AW),
                "smc_800_read": (self._moved(r800), self._resp(r800)),
                "smc_800_write": (self._moved(w800), self._resp(w800)),
            },
            {
                "sep_e8_write": (self._moved_want(**{SEP_AW: 1}), _hx(SEP_END0 - 8)),
                "sep_e8_read": (
                    self._moved_want(**{SEP_AR: 1}),
                    [_rn(RESP_OKAY)],
                    [_hx(E8_WORD)],
                ),
                "sep_e_read": (self._moved_want(), [_rn(RESP_DECERR)]),
                "sep_e_write": (self._moved_want(), [_rn(RESP_DECERR)]),
                "smc_7f8_read": self._moved_want(**{SMC_AR: 1}),
                "smc_7f8_write": self._moved_want(**{SMC_AW: 1}),
                "smc_800_read": (self._moved_want(), [_rn(RESP_DECERR)]),
                "smc_800_write": (self._moved_want(), [_rn(RESP_DECERR)]),
            },
            "base included, base+size excluded: E-8 and 0x4000_07F8 are counted once at their "
            "port, E-8 reads back OKAY, and E and 0x4000_0800 answer DECERR with no counter moving",
        )
        self._ctrl("SMC_PAST_END")

        await self._cold_reset()
        reset_ports = self._ports()
        sep_rd = await self._txn(
            "S11_cold_sep_read", write=False, addr=SEP_GLOBAL_BASE_RESET + 8, beats=1, xid=0xB6
        )
        smc_addr_reset = SMC_GLOBAL_BASE_RESET + (
            SMC_CHIP_CONFIG_VERSION_LO - SMC_APERTURE_LOCAL_BASE
        )
        smc_rd = await self._txn(
            "S11_cold_smc_read", write=False, addr=smc_addr_reset, beats=1, xid=0xB7, size=SIZE_4B
        )
        self._info(
            f"S11 after rst_cold_ni ports={reset_ports} sep_read={self._resp(sep_rd)} "
            f"smc_read={self._resp(smc_rd)} xbar_rst={_hx(_val(dut.obs_xbar_rst_n_o))}"
        )
        self._pre(
            "S11 rst_cold_ni restores both apertures and one ext_in read reaches each window",
            {
                "ports": tuple(_hx(v) for v in reset_ports.values()),
                "sep_read": self._moved(sep_rd, SEP_AR, watch=INBOUND),
                "smc_read": self._moved(smc_rd, SMC_AR),
            },
            {
                "ports": tuple(
                    _hx(v)
                    for v in (
                        SEP_GLOBAL_BASE_RESET,
                        SEP_REGION_SIZE_RESET,
                        SMC_GLOBAL_BASE_RESET,
                        SMC_REGION_SIZE_RESET,
                    )
                ),
                "sep_read": self._moved_want(**{SEP_AR: 1}),
                "smc_read": self._moved_want(**{SMC_AR: 1}),
            },
        )
        self._ctrl("COLD_RESET_BASELINE")
        self.steps["S11"] = True

    def _fences(self) -> None:
        names = [n for n, _ in self.markers]
        cycles = [c for _, c in self.markers]
        increasing = all(a < b for a, b in zip(cycles, cycles[1:]))
        self._info(f"NONVAC markers={self.markers}")
        self._grade(
            "CHK-NONVAC",
            {"order": names, "strictly_increasing": increasing, "steps": sorted(self.steps)},
            {"order": list(MARKERS), "strictly_increasing": True, "steps": sorted(STEPS)},
            "ordered markers " + " < ".join(f"{n}@{c}" for n, c in self.markers),
        )
        for rec in self.sites:
            self._info(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {'EXPIRED' if rec['expired'] else 'ok'} on_expiry=fail "
                f"last={rec['last']}"
            )
        expired = [s["label"] for s in self.sites if s["expired"]]
        unbounded = [s["label"] for s in self.sites if not s["bound"]]
        no_last = [s["label"] for s in self.sites if not s["last"]]
        self._grade(
            "CHK-TIMEOUT-PATHS",
            {
                "expired": expired,
                "unbounded": unbounded,
                "without_last_state": no_last,
            },
            {
                "expired": [],
                "unbounded": [],
                "without_last_state": [],
            },
            f"every handshake, system-bus, JTAG2AXI, port and reset wait ({len(self.sites)}) has "
            "a finite bound, a fail-on-expiry path and a last state, and none expired",
        )

    async def run(self) -> None:
        await self._s1_setup()
        await self._s2_sep_edges()
        await self._s3_rebase()
        await self._s4_sep_past_end()
        await self._s5_wrap_fixed()
        await self._s6_carry()
        await self._s7_wide_sep()
        await self._s8_smc_phase()
        await self._s9_sep_below()
        await self._s10_smc_below()
        await self._s11_smc_past_end()
        self._step("S12", f"{len(self.sites)} bounded waits recorded")
        self._fences()
        if self.failures:
            raise AssertionError(f"{len(self.failures)} checker compare(s) failed: {self.failures}")
