# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""INCR bursts from the external AXI input into the SEP extension port and the eFuse SHIM.

Spec: hw/sys/sep/doc/memory_map.adoc:90-95, hw/sys/sep/doc/fabric.adoc:38,
doc/integrator/src/smu-sep.adoc:141-143, hw/sys/smu/doc/port_table.adoc:201-202,
doc/programmer/src/sep-smc-common.adoc:82,118-200.

S0..S3 are ``smu_dtp_sep_dm_dmi_test``: the TEST_DEV posture leaves SEP debug open and the SEP
debug module's system bus is reachable. S1 programs SEP inbound filter entry 1 over SEP-local
0x2000_0000..0x2000_FFFF for secure bursts in the programmer-guide order and widens
SEP_REGION_SIZE to 0x4000_0000 with SEP_GLOBAL_BASE_ADDR at its reset value, so SEP-local
addresses below 0x4000_0000 are the global addresses.
S2: a four-beat INCR burst of 8-byte beats at SEP-local 0x2000_1000, written and read, is routed
    on its first address to the extension port: one AW (or AR) with that address, AxLEN 3 and
    AxSIZE 3, four W beats on the write, and nothing on the eFuse bank-control port. The
    response code the extension port's tie-off returns is logged and not compared.
S3: the same burst shape from the SHIM base 0x2000_0000 carries every beat to the eFuse bank
    control port as AXI-Lite transfers in ascending address order whose 4-byte spans cover the
    burst, and none to the extension port.
S4: SEP_REGION_SIZE returns to its reset value and entry 1 is disabled.
S5: every bounded wait is a runtime site record.
"""

from __future__ import annotations

import math
from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from ocah_axi_vip import resp_name, worst_resp

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    LC_STATE_PRESENSE,
    POSTURE_SETTLE_POLLS,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    _FILTER_CTRL_H,
    _SEP_ADDR_H,
    PORT_POLL_CYCLES,
    SBA_POLLS,
    SBCS_ADDR,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
    _indexed_addr,
    smu_dtp_sep_dm_sba_test_seq,
)
from seq_lib.smu_tb_pins import smc_primary_reset

INBOUND_ENTRY = 1
INBOUND_CONFIG = _indexed_addr("SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", INBOUND_ENTRY)
INBOUND_START = _indexed_addr("SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", INBOUND_ENTRY)
INBOUND_END = _indexed_addr("SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", INBOUND_ENTRY)
# Secure read and write, enabled, bursts allowed; ALLOW_NS stays clear.
INBOUND_CFG_BURST = (
    c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
    | c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
    | c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
    | c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
)
INBOUND_ENABLED_BM = c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")

SHIM_BASE = 0x2000_0000
SHIM_BASE_HEADER = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR")
EXT_LOCAL = 0x2000_1000
FILTER_RANGE_END = 0x2000_FFFF
WIDE_REGION_SIZE = 0x4000_0000

BURST_BEATS = 4
BURST_SIZE = 3
BURST_LEN = BURST_BEATS - 1
BEAT_BYTES = 1 << BURST_SIZE
LITE_TRANSFER_BYTES = 4

BEAT_GAP_CLK = 256
RESP_CLK = 512
DRAIN_CLK = 64
SAMPLER_CAP_CLK = BEAT_GAP_CLK * BURST_BEATS

# Test steps: S1 writes entry 1 (clear, start, end, enable) and the region size, reads both
# back; S4 writes the region size and the entry config, reads both back. S2 and S3 each issue a
# write and a read burst.
SETUP_SBA_ACCESSES = 4 + 1 + 2
RESTORE_SBA_ACCESSES = 1 + 1 + 2
EXPECTED_SBA_ACCESSES = SETUP_SBA_ACCESSES + RESTORE_SBA_ACCESSES
EXPECTED_BURSTS = 4
EXPECTED_PORT_WAITS = 2
EXPECTED_POSTURE_WAITS = 1

# Bit positions in the pulp AXI4 request/response structs of the 32-bit address, 64-bit data,
# 6-bit ID, 12-bit user extension port (vendor/pulp-platform/axi include/axi/typedef.svh).
EXT_REQ_BITS = 254
EXT_RESP_BITS = 110
EXT_REQ = {
    "ar_valid": 1,
    "ar_addr": 43,
    "ar_len": 35,
    "ar_size": 32,
    "w_valid": 82,
    "aw_valid": 168,
    "aw_addr": 216,
    "aw_len": 208,
    "aw_size": 205,
}
EXT_RESP = {"aw_ready": 109, "ar_ready": 108, "w_ready": 107}
EXT_ADDR_BITS = 32
# Bit positions in the pulp AXI-Lite structs with a 32-bit data bus; the request width is
# 47 + 2 * address bits.
LITE_RESP_BITS = 41
LITE_RESP = {"aw_ready": 40, "w_ready": 39, "ar_ready": 35}
LITE_REQ_FIXED_BITS = 47


def _field(bits: str, lsb: int, width: int, name: str) -> int:
    text = bits[len(bits) - lsb - width : len(bits) - lsb]
    if set(text) - {"0", "1"}:
        raise AssertionError(f"X/Z on {name}: {text}")
    return int(text, 2)


class _PortTap:
    """Decodes accepted AW, W and AR handshakes of one request/response net pair."""

    def __init__(self, name: str, req, resp, lite: bool) -> None:
        self.name = name
        self.req = req
        self.resp = resp
        self.lite = lite
        if lite:
            if len(resp) != LITE_RESP_BITS or (len(req) - LITE_REQ_FIXED_BITS) % 2:
                raise AssertionError(f"{name} is {len(req)}/{len(resp)} bits, not AXI-Lite 32-bit")
            abits = (len(req) - LITE_REQ_FIXED_BITS) // 2
            self.abits = abits
            self.rq = {
                "ar_valid": 1,
                "ar_addr": 5,
                "w_valid": 6 + abits,
                "aw_valid": 43 + abits,
                "aw_addr": 47 + abits,
            }
            self.rp = LITE_RESP
        else:
            if (len(req), len(resp)) != (EXT_REQ_BITS, EXT_RESP_BITS):
                raise AssertionError(
                    f"{name} is {len(req)}/{len(resp)} bits, the tap decodes "
                    f"{EXT_REQ_BITS}/{EXT_RESP_BITS}"
                )
            self.abits = EXT_ADDR_BITS
            self.rq = EXT_REQ
            self.rp = EXT_RESP
        self.events: list[tuple[int, str, tuple]] = []
        self.cycles = 0
        self.capped = False

    def _decode(self, cycle: int) -> None:
        q = str(self.req.value)
        r = str(self.resp.value)
        rq, rp, n = self.rq, self.rp, self.name
        if _field(q, rq["aw_valid"], 1, f"{n}.aw_valid") and _field(
            r, rp["aw_ready"], 1, f"{n}.aw_ready"
        ):
            addr = _field(q, rq["aw_addr"], self.abits, f"{n}.aw_addr")
            if self.lite:
                payload = (addr,)
            else:
                payload = (
                    addr,
                    _field(q, rq["aw_len"], 8, f"{n}.aw_len"),
                    _field(q, rq["aw_size"], 3, f"{n}.aw_size"),
                )
            self.events.append((cycle, "aw", payload))
        if _field(q, rq["w_valid"], 1, f"{n}.w_valid") and _field(
            r, rp["w_ready"], 1, f"{n}.w_ready"
        ):
            self.events.append((cycle, "w", ()))
        if _field(q, rq["ar_valid"], 1, f"{n}.ar_valid") and _field(
            r, rp["ar_ready"], 1, f"{n}.ar_ready"
        ):
            addr = _field(q, rq["ar_addr"], self.abits, f"{n}.ar_addr")
            if self.lite:
                payload = (addr,)
            else:
                payload = (
                    addr,
                    _field(q, rq["ar_len"], 8, f"{n}.ar_len"),
                    _field(q, rq["ar_size"], 3, f"{n}.ar_size"),
                )
            self.events.append((cycle, "ar", payload))

    async def sample(self, clk, cap: int, flag: dict) -> None:
        while not flag["stop"]:
            if self.cycles >= cap:
                self.capped = True
                return
            await RisingEdge(clk)
            self.cycles += 1
            self._decode(self.cycles)

    def of(self, chan: str) -> list[tuple]:
        return [payload for _, c, payload in self.events if c == chan]

    def max_gap(self) -> int:
        gap, last = 0, 0
        for cycle, _, _ in self.events:
            gap = max(gap, cycle - last)
            last = cycle
        return gap


class smu_sep_inbound_burst_extension_test_seq(smu_dtp_sep_dm_sba_test_seq):
    """External-input INCR bursts into the SEP extension port and the eFuse SHIM window."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.sites: list[dict] = []
        self.step_ns: dict[str, float] = {}
        self.bursts = 0
        self.period_ps = 0.0
        self.done = False

    def _site(self, kind, label, bound, unit, used, state, expired) -> None:
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": unit,
                "used": used,
                "state": state,
                "expired": bool(expired),
            }
        )

    def _stamp(self, step: str, text: str) -> None:
        self.step_ns[step] = float(get_sim_time("ns"))
        self._log(f"STEP {step}: {text} t={self.step_ns[step]:.1f}ns")

    def _global(self, local: int) -> int:
        return SEP_GLOBAL_BASE_RESET + local

    async def _require_debug_open(self, sb) -> None:
        polls, lc_state = 0, LC_STATE_PRESENSE
        for polls in range(1, POSTURE_SETTLE_POLLS + 1):
            lc_state = sample(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
            if lc_state != LC_STATE_PRESENSE:
                break
            await ClockCycles(self.dut.clk_smu_i, 10)
        expired = lc_state == LC_STATE_PRESENSE
        self._site(
            "posture",
            "lc_state leaves pre-sense",
            POSTURE_SETTLE_POLLS,
            "polls of 10 clk_smu_i",
            polls,
            f"lc_state=0x{lc_state:02x}",
            expired,
        )
        if expired:
            raise AssertionError(f"posture wait expired after {polls} polls lc_state={lc_state}")
        await super()._require_debug_open(sb)

    async def _sba_wait(self, jtag, what: str) -> None:
        sbcs = SBCS_SBBUSY
        polls = 0
        for polls in range(1, SBA_POLLS + 1):
            sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if not sbcs & SBCS_SBBUSY:
                break
        expired = bool(sbcs & SBCS_SBBUSY)
        sberror = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        self._site(
            "sba",
            what,
            SBA_POLLS,
            "sbcs polls",
            polls,
            f"sbcs=0x{sbcs:08x} sberror={sberror}",
            expired,
        )
        if expired:
            raise AssertionError(f"system-bus {what}: sbbusy never cleared sbcs=0x{sbcs:08x}")
        if sberror or (sbcs & SBCS_SBBUSYERROR):
            raise AssertionError(f"system-bus {what}: sbcs=0x{sbcs:08x} sberror={sberror}")

    async def _port_poll(self, name: str, want: int) -> int:
        observed = sample(getattr(self.dut, name), name)
        used = 0
        while observed != want and used < PORT_POLL_CYCLES:
            await RisingEdge(self.dut.clk_smu_i)
            used += 1
            observed = sample(getattr(self.dut, name), name)
        expired = observed != want
        self._site(
            "port",
            f"{name} reaches 0x{want:x}",
            PORT_POLL_CYCLES,
            "clk_smu_i",
            used,
            f"{name}=0x{observed:x}",
            expired,
        )
        if expired:
            raise AssertionError(f"{name} stayed 0x{observed:x}, want 0x{want:x}")
        return observed

    async def _measure_period(self) -> None:
        clk = self.dut.clk_smu_i
        await RisingEdge(clk)
        first = float(get_sim_time("ps"))
        await RisingEdge(clk)
        self.period_ps = float(get_sim_time("ps")) - first

    async def _set_region(self, jtag, size: int) -> int:
        await self._sba_write64(jtag, SEP_REGION_SIZE_ADDR, size)
        await self._port_poll("sep_region_size_o", size)
        return await self._sba_read64(jtag, SEP_REGION_SIZE_ADDR)

    async def _setup(self, jtag, sb) -> None:
        sb.expect_eq("SHIM base from sep_addr.h", SHIM_BASE_HEADER, SHIM_BASE)
        for addr, value in (
            (INBOUND_CONFIG, 0),
            (INBOUND_START, SHIM_BASE),
            (INBOUND_END, FILTER_RANGE_END),
            (INBOUND_CONFIG, INBOUND_CFG_BURST),
        ):
            await self._sba_write(jtag, addr, value)
        config = await self._sba_read(jtag, INBOUND_CONFIG)
        region = await self._set_region(jtag, WIDE_REGION_SIZE)
        self._log(f"CELL setup entry1_config=0x{config:08x} region_size=0x{region:x}")
        sb.expect_eq(
            "entry 1 config readback",
            config & INBOUND_CFG_BURST,
            INBOUND_CFG_BURST,
        )
        sb.expect_eq("SEP_REGION_SIZE readback", region, WIDE_REGION_SIZE)

    async def _burst(self, master, *, write: bool, local: int, ext_want: int, shim_want: int):
        """One INCR burst; returns the ext tap, the SHIM tap and the response code."""
        dut = self.dut
        smu_dut = hier(dut, "u_dut")
        ext = _PortTap(
            "sep_external",
            hier(smu_dut, "sep_external_req"),
            hier(smu_dut, "sep_external_resp"),
            lite=False,
        )
        shim = _PortTap(
            "sep_efuse_bank_ctrl",
            hier(smu_dut, "sep_efuse_bank_ctrl_req"),
            hier(smu_dut, "sep_efuse_bank_ctrl_resp"),
            lite=True,
        )
        flag = {"stop": False}
        label = f"{'write' if write else 'read'} burst @0x{local:08x}"
        addr = self._global(local)
        samplers = [
            cocotb.start_soon(tap.sample(dut.clk_smu_i, SAMPLER_CAP_CLK, flag))
            for tap in (ext, shim)
        ]
        t0 = float(get_sim_time("ps"))
        if write:
            payload = bytes((0xA0 + i) & 0xFF for i in range(BURST_BEATS * BEAT_BYTES))
            event = master.init_write(addr, payload, size=BURST_SIZE)
        else:
            event = master.init_read(addr, BURST_BEATS * BEAT_BYTES, size=BURST_SIZE)
        resp_ps = round(RESP_CLK * self.period_ps)
        try:
            await with_timeout(event.wait(), resp_ps, "ps")
        except Exception as exc:  # noqa: BLE001 - recorded, then raised
            flag["stop"] = True
            self._site("burst_resp", label, RESP_CLK, "clk_smu_i", RESP_CLK, f"timeout {exc}", True)
            raise AssertionError(f"TIMEOUT {label}: no response in {RESP_CLK} clk: {exc}") from exc
        resp_cycles = math.ceil((float(get_sim_time("ps")) - t0) / self.period_ps)
        raw = event.data
        resp = worst_resp(getattr(raw, "resp", None))
        self._site(
            "burst_resp",
            label,
            RESP_CLK,
            "clk_smu_i",
            resp_cycles,
            f"resp={resp_name(resp)}",
            resp_cycles > RESP_CLK,
        )
        drain = 0
        while (len(ext.events) < ext_want or len(shim.events) < shim_want) and drain < DRAIN_CLK:
            await RisingEdge(dut.clk_smu_i)
            drain += 1
        flag["stop"] = True
        for task in samplers:
            await task
        total_cycles = ext.cycles
        for tap, want in ((ext, ext_want), (shim, shim_want)):
            if want:
                self._site(
                    "beat_wait",
                    f"{label} on {tap.name}",
                    BEAT_GAP_CLK,
                    "clk_smu_i between events",
                    tap.max_gap(),
                    f"events={len(tap.events)}/{want}",
                    tap.capped or tap.max_gap() > BEAT_GAP_CLK or len(tap.events) < want,
                )
            else:
                self._site(
                    "hold",
                    f"{label} on {tap.name}",
                    SAMPLER_CAP_CLK,
                    "clk_smu_i window",
                    tap.cycles,
                    f"events={len(tap.events)}",
                    tap.capped,
                )
        self._site(
            "drain",
            label,
            DRAIN_CLK,
            "clk_smu_i",
            drain,
            f"events ext={len(ext.events)} shim={len(shim.events)} window={total_cycles}",
            drain >= DRAIN_CLK and (len(ext.events) < ext_want or len(shim.events) < shim_want),
        )
        self.bursts += 1
        return ext, shim, resp

    def _summary(self, tap: _PortTap) -> tuple:
        return (tap.of("aw"), len(tap.of("w")), tap.of("ar"))

    async def _ext_bursts(self, master, sb) -> None:
        want_aw = (EXT_LOCAL, BURST_LEN, BURST_SIZE)
        results = {}
        for write in (True, False):
            ext, shim, resp = await self._burst(
                master,
                write=write,
                local=EXT_LOCAL,
                ext_want=1 + (BURST_BEATS if write else 0),
                shim_want=0,
            )
            leg = "write" if write else "read"
            self._log(
                f"CHK-DBG-EXT-BURST: resp={resp_name(resp)} (measured, not compared) leg={leg}"
            )
            results[leg] = (self._summary(ext), self._summary(shim))
            first = (ext.of("aw") or ext.of("ar") or [(0, 0, 0)])[0]
            self._log(
                f"CELL incr_burst addr=0x{first[0]:08x} len={first[1]} size={first[2]} "
                f"w_beats={len(ext.of('w'))} leg={leg}"
            )
            self._log(
                f"CELL burst_first_addr_decode ext_hits={len(ext.events)} "
                f"shim_hits={len(shim.events)} leg={leg}"
            )
        want = {
            "write": (([want_aw], BURST_BEATS, []), ([], 0, [])),
            "read": (([], 0, [want_aw]), ([], 0, [])),
        }
        self._log(f"CHK-DBG-EXT-BURST: observed={results}")
        sb.expect_eq("CHK-DBG-EXT-BURST", results, want, evidence="DBG_EXT_BURST")

    async def _shim_bursts(self, master, sb) -> None:
        burst_bytes = BURST_BEATS * BEAT_BYTES
        burst_range = list(range(SHIM_BASE, SHIM_BASE + burst_bytes))
        results = {}
        for write in (True, False):
            ext, shim, resp = await self._burst(
                master,
                write=write,
                local=SHIM_BASE,
                ext_want=0,
                shim_want=BURST_BEATS * (2 if write else 1),
            )
            leg = "write" if write else "read"
            addrs = [p[0] for p in (shim.of("aw") if write else shim.of("ar"))]
            w_beats = len(shim.of("w"))
            self._log(
                f"CELL burst_from_base shim_beats={len(addrs)} addrs={[hex(a) for a in addrs]} "
                f"ext_hits={len(ext.events)} leg={leg}"
            )
            self._log(f"CHK-DBG-SHIM-BURST: resp={resp_name(resp)} leg={leg}")
            step = addrs[1] - addrs[0] if len(addrs) > 1 else 0
            self._log(
                f"CHK-DBG-SHIM-BURST: shim_transfers={len(addrs)} step_bytes={step} "
                f"beat_bytes={BEAT_BYTES} leg={leg}"
            )
            covered = sorted(a + i for a in addrs for i in range(LITE_TRANSFER_BYTES))
            results[leg] = (
                addrs == sorted(addrs),
                covered,
                (w_beats == len(addrs)) if write else True,
                len(ext.events),
            )
        want = {leg: (True, burst_range, True, 0) for leg in ("write", "read")}
        self._log(
            "CHK-DBG-SHIM-BURST: observed="
            + str({leg: (r[0], len(r[1]), r[2], r[3]) for leg, r in results.items()})
        )
        sb.expect_eq("CHK-DBG-SHIM-BURST", results, want, evidence="DBG_SHIM_BURST")

    async def _restore(self, jtag, sb) -> None:
        region = await self._set_region(jtag, SEP_REGION_SIZE_RESET)
        await self._sba_write(jtag, INBOUND_CONFIG, 0)
        config = await self._sba_read(jtag, INBOUND_CONFIG)
        self._log(f"CELL restore entry1_config=0x{config:08x} region_size=0x{region:x}")
        sb.expect_eq("SEP_REGION_SIZE restored", region, SEP_REGION_SIZE_RESET)
        sb.expect_eq("entry 1 disabled", config & INBOUND_ENABLED_BM, 0)

    def _timeout_proof(self, sb) -> None:
        for rec in self.sites:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['state']}"
            )
        expired = sum(1 for rec in self.sites if rec["expired"])
        finite = all(
            isinstance(rec["bound"], int) and 0 < rec["bound"] < math.inf and rec["state"]
            for rec in self.sites
        )
        kinds = Counter(rec["kind"] for rec in self.sites)
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expired={expired} "
            f"finite_and_stated={finite} "
            f"kinds={dict(kinds)}"
        )
        sb.expect_eq("every site finite with a last state", finite, True)
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq(
            "wait sites per kind against the test steps",
            dict(kinds),
            {
                "posture": EXPECTED_POSTURE_WAITS,
                "sba": EXPECTED_SBA_ACCESSES,
                "port": EXPECTED_PORT_WAITS,
                "burst_resp": EXPECTED_BURSTS,
                "beat_wait": EXPECTED_BURSTS,
                "hold": EXPECTED_BURSTS,
                "drain": EXPECTED_BURSTS,
            },
        )

    def _fence_proof(self, sb, final_region: int) -> None:
        order = ["S1", "S2", "S3", "S4", "S5", "PASS"]
        stamps = [self.step_ns[s] for s in order]
        positive = [b > a for a, b in zip(stamps, stamps[1:])]
        sba = sum(1 for rec in self.sites if rec["kind"] == "sba")
        self._log(
            "CHK-NONVAC: ordered sim-time fence "
            + "<".join(f"{s}@{t:.1f}ns" for s, t in zip(order, stamps))
            + f" sba_accesses={sba} bursts={self.bursts} final_region_size=0x{final_region:x}"
        )
        sb.expect_eq(
            "CHK-NONVAC fence and access counts",
            (positive, sba, self.bursts, final_region),
            (
                [True] * (len(order) - 1),
                EXPECTED_SBA_ACCESSES,
                EXPECTED_BURSTS,
                SEP_REGION_SIZE_RESET,
            ),
            evidence="CHK-NONVAC",
        )

    async def run(self) -> None:
        self._stamp("S1", "SETUP bring-up, entry 1 and SEP_REGION_SIZE")
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        await self._setup(jtag, sb)
        master = await make_smu_axi_master(
            cocotb.top, self.dut.clk_smu_i, smc_primary_reset(self.dut)
        )
        await self._measure_period()
        self._stamp("S2", "bursts at the extension window")
        await self._ext_bursts(master, sb)
        self._stamp("S3", "bursts from the SHIM base")
        await self._shim_bursts(master, sb)
        self._stamp("S4", "restore SEP_REGION_SIZE and disable entry 1")
        await self._restore(jtag, sb)
        self._stamp("S5", "TIMEOUT site records")
        self._timeout_proof(sb)
        await RisingEdge(self.dut.clk_smu_i)
        final_region = sample(self.dut.sep_region_size_o, "sep_region_size_o")
        self.step_ns["PASS"] = float(get_sim_time("ns"))
        self._fence_proof(sb, final_region)
        self.done = True
