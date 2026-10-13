# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-IP JTAG reset overrides, their priority, and the ``sep_reset_n`` override.

What the test proves. For OTBN, AES, HMAC, KMAC, TRNG and Adams Bridge the
per-IP JTAG override pair forces the domain reset (value 0) or forces it
released (value 1), whatever ``SW_RESET_N`` holds, and does not run the
isolation sequence. The domain returns when the override releases. With
``rst_ni`` high, the override that forces ``sep_reset_n`` low resets every
``sep_reset_n``-domain block and every sequenced engine domain, and leaves the
``rst_ni``-domain blocks intact (``sep_fuse_sense_done_o``, ``aon_rst_n``).

Sources: ``hw/sys/sep/doc/reset_controller.adoc`` (SEP Reset Controller,
Isolation and Reset Sequencing); ``hw/sys/sep/doc/clk_rst.adoc`` (Reset
Architecture); ``hw/ip/jtag/jtag_ptap/doc/architecture.adoc`` (IC_RESET
Support: port n at TDR bits 2n+1 ``reset_enable``, active low, and 2n+2
``reset_control``); ``doc/integrator/src/smu-composition.adoc`` (SEP slice,
TDI to TDO order).

Stimulus. Every override is shifted through the IC_RESET TDR driver
(``env/sep_ic_reset_tdr.py``). Pass 1 applies the walking-one and
walking-zero enable vectors E, each with V all 0 and V all 1, and 8 drawn
(E, V) pairs with every software bit at 1. Pass 2 applies the same pairs with
``SW_RESET_N`` = 0x00. A pulse leg drives ``wdt_rst_ni_i`` under two overrides,
a priority leg releases the software bit and the override in both orders on
OTBN, AES, HMAC and KMAC, and a ``sep_reset_n`` leg forces the SEP reset low
with ``rst_ni`` high. A last ``rst_ni`` pulse is the control of the
``sep_fuse_sense_done_o`` and ``aon_rst_n`` checks.

Probes. Approved: ``ip_rst_n[6:1]`` (``*_gated_rst_n_probe_o``),
``dbg_sep_reset_n_o``, ``sep_cpu_reset_n_o``, ``sep_fuse_sense_done_o``.
Observation taps: the isolate-complete vector ``crypto_isolated_probe_o`` (the
host-path bits of every domain, read through ``env/sep_reset_taps.py``) and
``aon_rst_n_probe_o``. Engine probe registers:
``seq_lib/sep_reset_mid_transfer_seq.PROBES`` (OTBN ``LOAD_CHECKSUM``, AES
``CTRL_AUX_SHADOWED``, HMAC ``INTR_ENABLE``, KMAC ``ENTROPY_PERIOD``, CSRNG
``INTR_ENABLE`` for TRNG, Adams Bridge ``notif_cmd_done_intr_count_r``) and SPI
``CONFIGOPTS``, DMA ``SRC_ADDR_LO``. Every expected register value is its RDL
reset value or the value the leaf wrote.

Checkers (log shape ``CHK-<ID> PASS|FAIL: ...``):
  CHK-OVR-IP        each pass, pair and domain: after the settle the tap is 0
                    for E=1 V=0, 1 for E=1 V=1, and the software bit for E=0;
                    the tap holds that value to the end of the hold. The
                    E=1 V=0 cells of Adams Bridge and TRNG log ``CTL-OVR-IP``.
  CHK-OVR-SKIP-ISO  per domain: the host-path isolate-complete bits stay 0 over
                    every pass 1 override of the domain. Control: the software
                    assert of the same domain raises them.
  CHK-OVR-RETURN    pass 1: after the override is removed a domain held with
                    V=0 reads its probe at the RDL default, the others keep
                    their armed value.
  CHK-OVR-PULSE     the V=0 tap is low and the V=1 tap high on every cycle of a
                    ``wdt_rst_ni`` pulse; both move after the overrides go.
  CHK-OVR-PRIO      with the software bit and the override both active the tap
                    stays low until both are released, in either order.
  CHK-OVR-AND       during the ``sep_reset_n`` override ``ip_rst_n[6:1]`` are low
                    on every cycle after the settle and ``aon_rst_n`` stays high.
  CHK-OVR-DOMAIN    after the ``sep_reset_n`` override SPI ``CONFIGOPTS``, DMA
                    ``SRC_ADDR_LO`` and the engine probes read their RDL default.
  CHK-OVR-SENSE     ``sep_fuse_sense_done_o`` is high on every cycle of the
                    ``sep_reset_n`` override. Control: the ``rst_ni`` pulse drops it.

Environment choices (logged): the settle of 4 ``clk_i`` cycles after each
Update-DR (the override passes a two-flop synchronizer), and the bounds of
every wait.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense of the committed
default image (``+sep_efuse_preload``), ``+sep_edn_jtag_reset_waive``. Four
seeds, Verilator and VCS.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import SepBitWatch
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_ic_reset_tdr import IC_RESET_IDLE, SepIcResetTdr, tdr_word
from env.sep_reset_taps import SepResetTaps, iso_name
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_RESET_CTRL
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_reset_mid_transfer_seq import PROBES, SepResetProbeDriver, other_value
from seq_lib.sep_sw_reset_seq import SEP_RESET_CTRL_SW_RESET_N, SW_RESET_N_BIT

TEST = "sep_ip_reset_override_matrix_test"

# Engine domains in SW_RESET_N bit order; ip_rst_n index = SW_RESET_N bit.
DOMS = ("otbn", "aes", "hmac", "kmac", "trng", "abr")
IPRST = {d: SW_RESET_N_BIT[d] for d in DOMS}
TDR_PORT = {d: f"{d}_jtag_rst_n" for d in DOMS}
SEP_RESET_PORT = "sep_reset_n"
# Host-path isolate stages of each domain (bench index of env/sep_reset_taps.py).
HOST_ISO = {"otbn": (0,), "aes": (1,), "hmac": (2,), "kmac": (3,), "abr": (4,), "trng": (5, 6, 7)}
_BY_NAME = {p.name: p for p in PROBES}
# Engine probe of each domain; TRNG uses the CSRNG register.
PROBE = {d: _BY_NAME["csrng" if d == "trng" else d] for d in DOMS}
SEPRST_REGS = (_BY_NAME["spi"], _BY_NAME["dma"])
# Cells the open owners grade: E=1, V=0 of Adams Bridge and TRNG.
CTL_CELLS = ("abr", "trng")
PRIO_DOMS = ("otbn", "aes", "hmac", "kmac")

SW_MASK = SEP_RESET_CTRL.mask32("SW_RESET_N")
SW_DEFAULT = SEP_RESET_CTRL.reset32("SW_RESET_N")
ENGINE_BITS = sum(1 << IPRST[d] for d in DOMS)

# Environment choices.
SETTLE = 4  # clk_i cycles after an Update-DR (two-flop synchronizer + margin)
TAP_BOUND = 2_000  # clk_i cycles for a tap to reach a level
ISO_BOUND = 2_000  # clk_i cycles for the isolate-complete bits of a domain
SEPRST_BOUND = 2_000  # clk_i cycles for sep_reset_n to read 1 after the override
RST_NI_HOLD = 16  # rst_ni control pulse, clk_i cycles (at least 8)
# aon_rst_n release after rst_ni: 16 clk_wdt_i periods of 5000 ns, plus one, in
# clk_i cycles of 1.25 ns.
AON_BOUND = 17 * 4_000
N_RANDOM_PAIRS = 8
N_PROBE_VALUES = 4


@dataclass(frozen=True)
class Pair:
    idx: int
    kind: str
    e: int  # bit i = DOMS[i]
    v: int
    hold: int

    def en(self, d: str) -> int:
        return (self.e >> DOMS.index(d)) & 1

    def val(self, d: str) -> int:
        return (self.v >> DOMS.index(d)) & 1

    def word(self) -> int:
        apply = tuple(TDR_PORT[d] for d in DOMS if self.en(d))
        hold = tuple(TDR_PORT[d] for d in DOMS if self.en(d) and not self.val(d))
        return tdr_word(apply=apply, hold=hold)


class Plan:
    """Every draw of the leaf, in the order of the contract, logged as DRAW lines."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.lines: list[str] = []
        all1 = (1 << len(DOMS)) - 1
        ev: list[tuple[str, int, int]] = []
        for i in range(len(DOMS)):
            for v in (0, all1):
                ev.append(("walk1", 1 << i, v))
        for i in range(len(DOMS)):
            for v in (0, all1):
                ev.append(("walk0", all1 & ~(1 << i), v))
        for _ in range(N_RANDOM_PAIRS):
            ev.append(("rand", rng.getrandbits(len(DOMS)), rng.getrandbits(len(DOMS))))
        self.pairs: list[Pair] = []
        for n, (kind, e, v) in enumerate(ev):
            hold = rng.randrange(SETTLE, 65)
            self.pairs.append(Pair(n, kind, e, v, hold))
            self.lines.append(f"DRAW pair={n} kind={kind} E=0b{e:06b} V=0b{v:06b} hold={hold}")
        runs = [(d, o) for d in PRIO_DOMS for o in ("sw_first", "ovr_first")]
        rng.shuffle(runs)
        self.prio = [(d, o, rng.randrange(SETTLE, 65)) for d, o in runs]
        self.lines.append(
            "DRAW prio_order=" + ",".join(f"{d}:{o}:hold={h}" for d, o, h in self.prio)
        )
        self.seprst_width = rng.randrange(8, 65)
        self.lines.append(f"DRAW sep_reset_n_override_width={self.seprst_width}")
        self.events = rng.randrange(1, 4)
        self.lines.append(f"DRAW sep_reset_n_events={self.events}")
        # Armed values: an entry n differs from the RDL reset and from entry n-1, so
        # consecutive arms of one register write different values.
        self.values: dict[str, list[int]] = {}
        for p in PROBES:
            vals: list[int] = []
            for _ in range(N_PROBE_VALUES):
                # Non-default, and different from the value before it.
                vals.append(other_value(rng, p.mask, (p.reset, *vals[-1:])))
            self.values[p.name] = vals
            self.lines.append(
                f"DRAW armed {p.name} @0x{p.addr:08x} = "
                + ",".join(f"0x{x:08x}" for x in vals)
                + f" (RDL reset 0x{p.reset:08x})"
            )
        d0, d1 = rng.sample(list(DOMS), 2)
        self.pulse_d0, self.pulse_d1 = d0, d1
        self.wdt_width = rng.randrange(2, 33)
        self.lines.append(f"DRAW pulse_leg v0_dom={d0} v1_dom={d1} wdt_width={self.wdt_width}")


@pyuvm.test()
class sep_ip_reset_override_matrix_test(sep_base_test):
    """Per-IP JTAG overrides force or release engine domains without isolation."""

    required_evidence = (
        "CHK-OVR-IP",
        "CHK-OVR-SKIP-ISO",
        "CHK-OVR-RETURN",
        "CHK-OVR-PULSE",
        "CHK-OVR-PRIO",
        "CHK-OVR-AND",
        "CHK-OVR-DOMAIN",
        "CHK-OVR-SENSE",
    )

    # ---- log helpers --------------------------------------------------------
    def _chk(self, chk: str, ok: bool, values: str) -> None:
        line = f"{chk} {'PASS' if ok else 'FAIL'}: {values}"
        if not ok:
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)
        self.k += 1

    def _ctl(self, ctl: str, ok: bool, values: str) -> None:
        line = f"{ctl}: {values}"
        if not ok:
            self.logger.error(f"{ctl} FAIL (control not met): {values}")
            raise AssertionError(f"{ctl} control not met: {values}")
        self.logger.info(line)

    # ---- pins and taps ------------------------------------------------------
    async def _cycles(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_i)

    def _ip(self) -> int:
        v = self.taps.ip_rst_n_now()
        if v is None:
            raise AssertionError("ip_rst_n taps are not 0/1")
        return v

    def _tap(self, d: str) -> int:
        return (self._ip() >> IPRST[d]) & 1

    async def _ip_ro(self) -> int:
        """``ip_rst_n[6:0]`` in the read-only phase of the next clock edge.

        Returns at the falling edge after the sample, so the caller may drive.
        """
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        v = self._ip()
        await FallingEdge(cocotb.top.clk_i)
        return v

    async def _wait_tap(self, d: str, level: int, what: str) -> int:
        try:
            return await self.taps.ip_rst[IPRST[d]].wait_level(level, TAP_BOUND)
        except AssertionError as exc:
            raise AssertionError(f"{what}: ip_rst_n[{IPRST[d]}] ({d}) {exc}") from exc

    async def _wait_host_iso(self, d: str, what: str) -> None:
        for x in HOST_ISO[d]:
            try:
                await self.taps.iso_ack.wait_level(1, ISO_BOUND, bit=iso_name(x))
            except AssertionError as exc:
                raise AssertionError(f"{what}: host isolate-complete of {d}: {exc}") from exc

    def _host_iso_now(self, d: str) -> int:
        return min(self.taps.iso_ack.level(iso_name(x)) or 0 for x in HOST_ISO[d])

    def _host_iso_any(self, d: str) -> int:
        return max(self.taps.iso_ack.level(iso_name(x)) or 0 for x in HOST_ISO[d])

    async def _shift(self, word: int, what: str) -> None:
        self.logger.info("TDR %s word=0x%05x", what, word)
        await self.tdr.capture_shift_update(word)

    # ---- register access ----------------------------------------------------
    async def _sw_write(self, value: int) -> None:
        seq = SepAxiAccessSeq(
            "sw_reset_n_wr", op=SepAxiOp.WRITE, addr=SEP_RESET_CTRL_SW_RESET_N, wdata=value
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SW_RESET_N write 0x{value:02x} not OKAY")
        self.sw = value
        self.logger.info("SW_RESET_N <- 0x%02x", value)

    async def _sw_read(self) -> int:
        seq = SepAxiAccessSeq("sw_reset_n_rd", op=SepAxiOp.READ, addr=SEP_RESET_CTRL_SW_RESET_N)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError("SW_RESET_N read not OKAY")
        return int(seq.rdata) & 0xFFFF_FFFF

    async def _arm(self, d_or_probe, idx: int = 0) -> None:
        p = PROBE[d_or_probe] if isinstance(d_or_probe, str) else d_or_probe
        val = self.plan.values[p.name][idx % N_PROBE_VALUES]
        await self.pd.write(p, val)
        got = await self.pd.read(p)
        fc = field_compare(got, val, p.mask)
        if not fc.ok or (val & p.mask) == (p.reset & p.mask):
            raise AssertionError(f"arm {p.name}: {fc.fields()} RDL reset 0x{p.reset:08x}")
        self.armed[p.name] = val

    async def _read_probe(self, p):
        return await self.pd.read(p)

    # ---- scenario -----------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.k = 0
        self.plan = Plan(self.seed)
        self.logger.info("SEED %s seed=%d", TEST, self.seed)
        for line in self.plan.lines:
            self.logger.info(line)
        self.logger.info(
            "ENV settle=%d tap_bound=%d iso_bound=%d seprst_bound=%d rst_ni_hold=%d "
            "aon_bound=%d (clk_i cycles)",
            SETTLE,
            TAP_BOUND,
            ISO_BOUND,
            SEPRST_BOUND,
            RST_NI_HOLD,
            AON_BOUND,
        )

        # Step 1: real fuse sense of the staged image.
        self.write_efuse_image(self.select_efuse_image())
        await self.bring_up_no_cpu()
        dut = cocotb.top
        self.taps = SepResetTaps(dut).start()
        self.taps.log_map(self.logger)
        self.sense = SepBitWatch(dut.sep_fuse_sense_done_o, name="sep_fuse_sense_done_o").start()
        self.pd = SepResetProbeDriver(self)
        self.tdr = SepIcResetTdr(self.rd_known)
        self.armed: dict[str, int] = {}
        self.sense_ovr: list[tuple[int, int, int]] = []
        try:
            await self._cycles(2)
            for name in ("sep_reset_n", "sep_cpu_reset_n"):
                await self.taps.resets[name].wait_level(1, TAP_BOUND)
            sw0 = await self._sw_read()
            self._ctl(
                "CTL-BOOT",
                (sw0 & SW_MASK) == SW_DEFAULT,
                f"SW_RESET_N=0x{sw0:02x} expect=0x{SW_DEFAULT:02x} reset_taps=1,1",
            )
            self.sw = sw0 & SW_MASK
            await self.tdr.reset_and_select()
            await self._shift(IC_RESET_IDLE, "idle")
            await self._cycles(SETTLE)

            # Step 2: arm the six engine probes.
            for d in DOMS:
                await self._arm(d)

            open_graded_window(TEST, self.logger)
            skip_iso = await self._pass(1)
            close_graded_window(self.logger)
            ctl_iso = await self._sw_assert_control()
            self._grade_skip_iso(skip_iso, ctl_iso)
            await self._pulse_leg()
            await self._priority_leg()
            await self._pass(2)
            await self._seprst_leg()
            close_graded_window(self.logger)
            await self._rst_ni_control()
        finally:
            close_graded_window(self.logger)
            await self.taps.stop()
            await self.sense.stop()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, self.k)

    # ---- steps 3 and 7: the (E, V) passes -----------------------------------
    async def _pass(self, n: int) -> dict[str, list[int]]:
        """Pass 1 (software bits at 1) or pass 2 (SW_RESET_N = 0x00).

        Returns, for pass 1, per domain the [cycles, high cycles] of its
        host-path isolate-complete bits over every override of the domain.
        """
        skip_iso = {d: [0, 0] for d in DOMS}
        if n == 2:
            await self._sw_write(self.sw & ~ENGINE_BITS)
            for d in DOMS:
                await self._wait_tap(d, 0, "pass 2 SW_RESET_N=0x00")
        for pair in self.plan.pairs:
            sw_bits = {d: (self.sw >> IPRST[d]) & 1 for d in DOMS}
            marks = self.taps.mark()
            await self._shift(pair.word(), f"pass{n} pair={pair.idx} apply")
            await self._cycles(SETTLE)
            settled = await self._ip_ro()
            await self._cycles(pair.hold - SETTLE)
            held = await self._ip_ro()
            moved = {
                d: self.taps.ip_rst[IPRST[d]].rises_since(marks[f"ip_rst_{IPRST[d]}"])
                + len(self.taps.ip_rst[IPRST[d]].fall_clks_since(marks[f"ip_rst_{IPRST[d]}"]))
                for d in DOMS
            }
            for d in DOMS:
                exp = pair.val(d) if pair.en(d) else sw_bits[d]
                got_s = (settled >> IPRST[d]) & 1
                got_h = (held >> IPRST[d]) & 1
                ok = got_s == exp and got_h == exp
                vals = (
                    f"pass={n} pair={pair.idx} dom={d} E={pair.en(d)} V={pair.val(d)} "
                    f"sw_bit={sw_bits[d]} ip_rst_n={got_s} held={got_h} expected={exp} "
                    f"edges_from_apply={moved[d]}"
                )
                if pair.en(d) and not pair.val(d) and d in CTL_CELLS:
                    self._ctl("CTL-OVR-IP", ok, vals)
                else:
                    self._chk("CHK-OVR-IP", ok, vals)
            await self._shift(IC_RESET_IDLE, f"pass{n} pair={pair.idx} remove")
            await self._cycles(SETTLE)
            if n == 1:
                cyc = self.taps.iso_ack.clk - marks["iso_ack"].clk
                for d in DOMS:
                    if not pair.en(d):
                        continue
                    hi = max(
                        self.taps.iso_ack.high_clocks_since(marks["iso_ack"], iso_name(x))
                        for x in HOST_ISO[d]
                    )
                    skip_iso[d][0] += cyc
                    skip_iso[d][1] += hi
                    if hi:
                        self.logger.error(
                            "CHK-OVR-SKIP-ISO FAIL: dom=%s pair=%d host isolate-complete "
                            "high %d of %d cycles under the override with sw_bit=1",
                            d,
                            pair.idx,
                            hi,
                            cyc,
                        )
                        raise AssertionError(f"CHK-OVR-SKIP-ISO FAIL: dom={d} pair={pair.idx}")
                await self._pass1_return(pair)
        if n == 2:
            await self._sw_write(self.sw | ENGINE_BITS)
            for d in DOMS:
                await self._wait_tap(d, 1, "pass 2 SW_RESET_N=0x7e")
            for d in DOMS:
                await self._arm(d)
        return skip_iso

    async def _pass1_return(self, pair: Pair) -> None:
        held0 = [d for d in DOMS if pair.en(d) and not pair.val(d)]
        for d in held0:
            await self._wait_tap(d, 1, f"pair={pair.idx} override removed")
        for d in DOMS:
            p = PROBE[d]
            got = await self._read_probe(p)
            if d in held0:
                exp, kind = p.reset, "default"
            else:
                exp, kind = self.armed[p.name], "retained"
            fc = field_compare(got, exp, p.mask)
            self._chk(
                "CHK-OVR-RETURN",
                fc.ok,
                f"pair={pair.idx} dom={d} probe={kind} reg={p.name} {fc.fields()}",
            )
        for d in held0:
            await self._arm(d)

    # ---- step 4: software-assert control ------------------------------------
    async def _sw_assert_control(self) -> dict[str, int]:
        """Step 4: a software assert of each domain raises its host-path bits."""
        cycles: dict[str, int] = {}
        for d in DOMS:
            m = self.taps.mark()
            await self._sw_write(self.sw & ~(1 << IPRST[d]))
            rise = -1
            try:
                await self._wait_host_iso(d, f"control sw assert {d}")
                rises = [
                    self.taps.iso_ack.rise_clks_since(m["iso_ack"], iso_name(x))
                    for x in HOST_ISO[d]
                ]
                if all(rises):
                    rise = max(r[0] for r in rises) - m["iso_ack"].clk
            except AssertionError as exc:
                self.logger.info("OBS-OVR-SKIP-ISO: dom=%s control not met (%s)", d, exc)
            await self._wait_tap(d, 0, f"control sw assert {d}")
            await self._sw_write(self.sw | (1 << IPRST[d]))
            await self._wait_tap(d, 1, f"control sw release {d}")
            await self._arm(d)
            cycles[d] = rise
            self.logger.info(
                "CTL-SW-ASSERT: dom=%s host_iso_ack_rise_cycle=%d (from the write issue)",
                d,
                rise,
            )
        return cycles

    def _grade_skip_iso(self, skip: dict[str, list[int]], ctl: dict[str, int]) -> None:
        for d in DOMS:
            n, hi = skip[d]
            if ctl[d] < 0:
                self.logger.info("OBS-OVR-SKIP-ISO: dom=%s control not met", d)
                continue
            self._chk(
                "CHK-OVR-SKIP-ISO",
                hi == 0 and n > 0,
                f"dom={d} sw_bit=1 iso_ack_max={1 if hi else 0} over {n} cycles "
                f"control_sw_assert_iso_ack_cycle={ctl[d]}",
            )

    # ---- step 5: pulse leg --------------------------------------------------
    async def _pulse_leg(self) -> None:
        d0, d1, w = self.plan.pulse_d0, self.plan.pulse_d1, self.plan.wdt_width
        dut = cocotb.top
        # Set-up write, window closed.
        await self._sw_write(self.sw & ~(1 << IPRST[d1]))
        await self._wait_tap(d1, 0, "pulse leg set-up")
        open_graded_window(TEST, self.logger)
        word = tdr_word(
            apply=(TDR_PORT[d0], TDR_PORT[d1]),
            hold=(TDR_PORT[d0],),
        )
        await self._shift(word, f"pulse leg v0={d0} v1={d1}")
        await self._cycles(SETTLE)
        v0_low = v1_high = cpu_low = 0
        await FallingEdge(dut.clk_i)
        dut.wdt_rst_ni_i.value = 0
        for _ in range(w):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            ip = self._ip()
            v0_low += 1 - ((ip >> IPRST[d0]) & 1)
            v1_high += (ip >> IPRST[d1]) & 1
            cpu_low += 1 - self.rd_known(dut.sep_cpu_reset_n_o)
        await FallingEdge(dut.clk_i)
        dut.wdt_rst_ni_i.value = 1
        await self.taps.resets["sep_cpu_reset_n"].wait_level(1, TAP_BOUND)
        await self._shift(IC_RESET_IDLE, "pulse leg remove")
        await self._wait_tap(d0, 1, "pulse leg v0 tap after removal")
        await self._cycles(SETTLE)
        await ReadOnly()
        d1_after = self._tap(d1)
        moved = int(d1_after == 0)
        self._chk(
            "CHK-OVR-PULSE",
            v0_low == w and v1_high == w and cpu_low == w and moved,
            f"pulse=WDT v0_dom={d0} v0_tap_low_cycles={v0_low}/{w} v1_dom={d1} v1_sw_bit=0 "
            f"v1_tap_high_cycles={v1_high}/{w} cpu_rst_low_on_wdt={int(cpu_low == w)} "
            f"moved_after_removal={moved}",
        )
        await RisingEdge(dut.clk_i)
        await self._sw_write(self.sw | (1 << IPRST[d1]))
        await self._wait_tap(d1, 1, "pulse leg v1 release")
        for d in (d0, d1):
            await self._arm(d)

    # ---- step 6: priority leg -----------------------------------------------
    async def _priority_leg(self) -> None:
        for d, order, hold in self.plan.prio:
            await self._sw_write(self.sw & ~(1 << IPRST[d]))
            await self._wait_tap(d, 0, f"priority {d} assert")
            await self._wait_host_iso(d, f"priority {d} assert")
            await self._shift(
                tdr_word(apply=(TDR_PORT[d],), hold=(TDR_PORT[d],)), f"priority {d} force"
            )
            await self._cycles(SETTLE)
            await ReadOnly()
            iso_before = self._host_iso_now(d)
            await RisingEdge(cocotb.top.clk_i)
            m = self.taps.mark()
            key = f"ip_rst_{IPRST[d]}"
            if order == "sw_first":
                await self._sw_write(self.sw | (1 << IPRST[d]))
            else:
                await self._shift(IC_RESET_IDLE, f"priority {d} release override")
            await self._cycles(SETTLE + hold)
            await ReadOnly()
            rose = self.taps.ip_rst[IPRST[d]].rises_since(m[key])
            high = self.taps.ip_rst[IPRST[d]].high_clocks_since(m[key])
            first_ok = rose == 0 and high == 0 and self._tap(d) == 0
            iso_at_second = self._host_iso_now(d)
            await RisingEdge(cocotb.top.clk_i)
            if order == "sw_first":
                await self._shift(IC_RESET_IDLE, f"priority {d} release override")
            else:
                # The software bit is written to 1 only with every host-path
                # isolate-complete bit of the domain high.
                iso_before = min(iso_before, iso_at_second)
                await self._sw_write(self.sw | (1 << IPRST[d]))
            await self._wait_tap(d, 1, f"priority {d} second release")
            p = PROBE[d]
            got = await self._read_probe(p)
            fc = field_compare(got, p.reset, p.mask)
            self._chk(
                "CHK-OVR-PRIO",
                iso_before == 1 and first_ok and fc.ok,
                f"dom={d} order={order} iso_ack_high_before_sw_release={iso_before} "
                f"tap_after_first_release={0 if first_ok else 1} (rises={rose} "
                f"high_cycles={high} over {SETTLE + hold}) tap_after_second=1 "
                f"probe_default: {fc.fields()}",
            )
            await self._arm(d)

    # ---- step 8: sep_reset_n override ---------------------------------------
    async def _seprst_leg(self) -> None:
        dut = cocotb.top
        # aon_rst_n leaves reset through a 16-stage synchronizer on clk_wdt_i, so it
        # reads 1 only some 16 watchdog periods after the rst_ni release. The leg
        # starts once it reads 1, so a fall during the override can show.
        aon = self.taps.resets["aon_rst_n"]
        at = await aon.wait_level(1, AON_BOUND)
        self.logger.info("CTL-AON-UP: aon_rst_n=1 at tap clock %d (bound %d)", at, AON_BOUND)
        for ev in range(self.plan.events):
            for p in SEPRST_REGS:
                await self._arm(p, ev + 1)
            for d in DOMS:
                await self._arm(d, ev + 1)
            sw_before = await self._sw_read()
            if (sw_before & SW_MASK) != SW_DEFAULT:
                raise AssertionError(f"SW_RESET_N before the override reads 0x{sw_before:02x}")
            for p in (*SEPRST_REGS, *(PROBE[d] for d in DOMS)):
                got = await self._read_probe(p)
                fc = field_compare(got, self.armed[p.name], p.mask)
                if not fc.ok:
                    raise AssertionError(f"armed {p.name} before the override: {fc.fields()}")
            samples: list[tuple[int, int, int, int]] = []
            stop = [False]

            async def sampler() -> None:
                while not stop[0]:
                    await RisingEdge(dut.clk_i)
                    await ReadOnly()
                    samples.append(
                        (
                            self.rd_known(dut.dbg_sep_reset_n_o),
                            self._ip() & ENGINE_BITS,
                            self.rd_known(dut.sep_fuse_sense_done_o),
                            self.rd_known(dut.aon_rst_n_probe_o),
                        )
                    )

            await RisingEdge(dut.clk_i)
            task = cocotb.start_soon(sampler())
            await self._shift(
                tdr_word(apply=(SEP_RESET_PORT,), hold=(SEP_RESET_PORT,)),
                f"sep_reset_n override event={ev}",
            )
            start = len(samples)
            await self._cycles(self.plan.seprst_width)
            # The graded window ends where the shift of the idle word starts; its
            # Update-DR removes the override before the shift returns.
            removal = len(samples)
            await self._shift(IC_RESET_IDLE, f"sep_reset_n override remove event={ev}")
            await self.taps.resets["sep_reset_n"].wait_level(1, SEPRST_BOUND)
            await self._cycles(2)
            stop[0] = True
            await task
            win = samples[start + SETTLE : removal]
            if len(win) < self.plan.seprst_width - SETTLE:
                raise AssertionError("sep_reset_n override window shorter than drawn")
            seprst_low = sum(1 for s in win if s[0] == 0)
            ip_high = sum(1 for s in win if s[1] != 0)
            aon_low = sum(1 for s in samples if s[3] == 0)
            taps_or = 0
            for smp in win:
                taps_or |= smp[1]
            sense_low = sum(1 for s in samples if s[2] == 0)
            self._chk(
                "CHK-OVR-AND",
                seprst_low == len(win) and ip_high == 0 and aon_low == 0,
                f"event={ev} width={self.plan.seprst_width} graded_cycles={len(win)} "
                f"sep_reset_n_low={seprst_low} ip_rst_n[6:1]=0b{taps_or >> 1:06b} "
                f"(OR over the graded cycles, cycles_with_a_high_tap={ip_high}) "
                f"aon_rst_n={int(aon_low == 0)} (low_cycles={aon_low} of {len(samples)}) "
                f"SW_RESET_N_before=0x{sw_before & SW_MASK:02x}",
            )
            self.sense_ovr.append((ev, sense_low, len(samples)))
            for d in DOMS:
                await self._wait_tap(d, 1, f"sep_reset_n override event={ev} release")
            n_ok = 0
            regs = (*SEPRST_REGS, *(PROBE[d] for d in DOMS))
            for p in regs:
                got = await self._read_probe(p)
                fc = field_compare(got, p.reset, p.mask)
                self.logger.info(
                    "OVR-DOMAIN event=%d reg=%s %s %s",
                    ev,
                    p.name,
                    fc.fields(),
                    "default" if fc.ok else "NOT-RESET",
                )
                n_ok += int(fc.ok)
            sw_after = await self._sw_read()
            self._ctl(
                "CTL-OVR-SWRST",
                (sw_after & SW_MASK) == SW_DEFAULT,
                f"SW_RESET_N=0x{sw_after & SW_MASK:02x}",
            )
            self._chk(
                "CHK-OVR-DOMAIN",
                n_ok == len(regs),
                f"event={ev} sep_reset_n_domain_reset={n_ok}/{len(regs)}",
            )

    # ---- step 9: rst_ni control ---------------------------------------------
    async def _rst_ni_control(self) -> None:
        m_sense = self.sense.mark()
        m_aon = self.taps.resets["aon_rst_n"].mark()
        res = await self.pulse_rst_ni(hold_cycles=RST_NI_HOLD)
        await self.taps.resets["sep_cpu_reset_n"].wait_level(1, TAP_BOUND)
        cyc = self.sense.clk - m_sense.clk
        sense_low = cyc - self.sense.high_clocks_since(m_sense)
        acyc = self.taps.resets["aon_rst_n"].clk - m_aon.clk
        aon_low = acyc - self.taps.resets["aon_rst_n"].high_clocks_since(m_aon)
        self._ctl(
            "CTL-RST-NI",
            sense_low > 0 and aon_low > 0,
            f"hold={RST_NI_HOLD} sep_fuse_sense_done_o_low_cycles={sense_low} "
            f"aon_rst_n_low_cycles={aon_low} release_clks={res['release_clks']}",
        )
        for ev, low, n in self.sense_ovr:
            self._chk(
                "CHK-OVR-SENSE",
                low == 0 and n > 0,
                f"event={ev} sep_fuse_sense_done_o high every cycle ({n - low}/{n}) "
                f"control_rst_ni_sense_done_low=1 control_rst_ni_aon_rst_n_low=1",
            )
