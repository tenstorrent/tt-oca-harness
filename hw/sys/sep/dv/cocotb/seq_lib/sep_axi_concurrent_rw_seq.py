# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Concurrent AW/W/AR arbitration on the DRBG AXI-Lite-64 lane adapters.

`sep_axi_order_sweep_seq` covers the two write channels against each other:
same-cycle, AW-first, W-first. AXI has a third independent channel, and a
master with a store and a load outstanding presents AR while AW and W are
still in flight. The adapter accepts each write half independently until that
half is pending, and accepts a read only when neither write half is pending.

`drbg_axil64_lane_adapter` is reached by every SEP-level CSRNG and EDN
register access (`drbg.sv` u_csrng_axil_adapter / u_edn_axil_adapter, fed from
`sep_crypto.sv` csrng_axil / edn_axil), so this is ordinary CSR traffic.

Three orderings. Only one of them is presentable through the SEP fabric:

* **aw-then-ar.** AW arrives, THEN AR while W is still outstanding.
  Presentable, and the one the leaves drive.
* **all-same-cycle.** AW, W and AR in one cycle. NOT presentable from a SEP
  AXI master: the crossbar between the master and the adapter delivers W one
  cycle after AW and re-serializes to that order whatever the master presents,
  and AxiTimingProfile can only delay a channel, never advance one, so the
  stagger cannot be closed from this side. CHK-CONCURRENT-CAL measures the
  AW-to-W gap at the master and at the port and reports which side introduced
  it, so the attribution is a logged measurement rather than an assumption.
  (`axi_to_axi_lite` is not the cause: it passes aw_valid and w_valid through
  combinationally.)
* **w-then-ar.** Needs W at the port before AW, which the fabric never
  produces for the same reason.

The two orderings the fabric cannot present are covered at the module's own
port by `sep_drbg_axil_adapter_port_arbitration_test`, which drives a
TB-instantiated instance of the same adapter directly.

Calibration also shows the overlap needs no timing manipulation: with plain
untimed traffic AW and AR land in the same cycle whenever a store and a load
are in flight together.

ONE ordering per lane per simulation so a wedge cannot contaminate a later
cell. Driving one scenario per leaf is what makes each verdict independent.

Delays are not guessed, they are CALIBRATED. The walk first issues a lone
write and a lone read and measures when AW, W and AR actually arrive at the
adapter port through the crossbar and axi_to_axi_lite. The target ordering is
then placed using those measured latencies, and fired once. A calibration
that cannot reach the ordering is reported as unreachable rather than fired
blind.

Channel delays come from a seeded source, so `--stage sim --seed N` replays a
failing alignment exactly.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_OKAY = 0

# Bit positions in drbg_{csrng,edn}_axil_chan_o.
AW_VALID, W_VALID, AR_VALID, AW_READY, W_READY, AR_READY = (1 << i for i in range(6))
VALID_BITS = AW_VALID | W_VALID | AR_VALID
READY_BITS = AW_READY | W_READY | AR_READY

# Bounded so a stalled adapter reports a timeout instead of hanging the leaf.
# Generous against the crossbar and the AXI-Lite-to-TLUL leg behind the
# adapter: a healthy CSRNG register access retires in well under this, and the
# failure this bounds is unbounded by construction.
CELL_TIMEOUT_NS = 20_000


# Each lane writes INTR_ENABLE and reads INTR_STATE in the same block, so the
# read is behind the same adapter as the write. INTR_ENABLE is the register
# sep_trng_reset_recovery_test already establishes as write-safe storage on
# both lanes; INTR_STATE is read-only, so the read cannot perturb the compare.
LANE_ADDRS: dict[str, tuple[int, int]] = {
    "csrng": (sym("CSRNG_INTR_ENABLE_REG_ADDR"), sym("CSRNG_INTR_STATE_REG_ADDR")),
    "edn": (sym("EDN_INTR_ENABLE_REG_ADDR"), sym("EDN_INTR_STATE_REG_ADDR")),
}

# The orderings, defined by what must be OBSERVED at the adapter port, not by
# a delay triple: the delays that reach each one are computed per build from
# the measured crossbar latency (see calibrate()).
#
# `gap` is the cycles left between the leading channel and AR. 0 means the
# same cycle. A non-zero gap must be enough for the leading channel to
# handshake first, which is what makes aw-then-ar a partially-committed state
# rather than a second all-same-cycle.
CONCURRENT_ORDERS: tuple[tuple[str, int], ...] = (
    ("all-same-cycle", 0),
    ("aw-then-ar", 2),
    ("w-then-ar", 2),
)
ORDER_NAMES = tuple(name for name, _gap in CONCURRENT_ORDERS)
ORDER_GAP = dict(CONCURRENT_ORDERS)

# The writable width of INTR_ENABLE is NOT assumed. The two blocks implement
# different numbers of interrupts, so a hardcoded mask is wrong for one of them
# and a bit that does not exist reads back 0 -- which looks exactly like a
# dropped write and would be reported as a DUT defect. `probe_mask()` measures
# it per lane instead. This upper bound only bounds the probe.
INTR_ENABLE_PROBE = 0xFFFF_FFFF


class SepAxiConcurrentRwCfg:
    """The single cell this leaf will drive, fixed by the leaf and the seed.

    One cell, not a walk: see the module docstring on why a wedge cannot be
    followed by a second measurement. The seed picks the register value only;
    the channel placement comes from calibration, so a seed replays the cell
    without pinning it to a latency the build may have changed.
    """

    def __init__(self, seed: int, *, lane: str, order: str, bus: str = "s_axi") -> None:
        if lane not in LANE_ADDRS:
            raise ValueError(f"unknown lane {lane!r}; expected one of {sorted(LANE_ADDRS)}")
        if order not in ORDER_GAP:
            raise ValueError(f"unknown ordering {order!r}; expected one of {list(ORDER_NAMES)}")
        self.bus = bus
        self.lane = lane
        self.order = order
        self.gap = ORDER_GAP[order]
        rng = SepSeededRng(seed)
        self.wr_addr, self.rd_addr = LANE_ADDRS[lane]
        # A candidate pattern only. run_cell narrows it to the bits the
        # register is measured to actually implement, so the seed cannot pick
        # a value whose set bits do not exist on this lane.
        self.value = rng.randrange(1, 8)

    @property
    def key(self) -> tuple[str, str]:
        return (self.lane, self.order)

    def summary(self) -> str:
        return (
            f"{self.lane} {self.order} (gap={self.gap}cyc) "
            f"wr=0x{self.wr_addr:08x} rd=0x{self.rd_addr:08x} "
            f"value=0x{self.value:x} on {self.bus}"
        )


class AdapterPortObserver:
    """Samples one lane adapter's AXI-Lite-64 port while a cell is in flight.

    Records the first cycle each valid is presented, the first cycle each
    channel handshakes, and the longest run of cycles in which valids were
    held with every ready low. That run IS the stall signature: a stable legal
    `1'b0` on the ready signals, which no X-check or protocol assertion sees.
    """

    def __init__(self, lane: str) -> None:
        self.lane = lane
        self.signal = getattr(cocotb.top, f"drbg_{lane}_axil_chan_o")
        self.reset()
        self._task: cocotb.Task | None = None

    def reset(self) -> None:
        self.cycles = 0
        self.valid_cycle: dict[str, int | None] = {"aw": None, "w": None, "ar": None}
        self.hs_cycle: dict[str, int | None] = {"aw": None, "w": None, "ar": None}
        self.overlap_cycles = 0  # cycles with 2+ valids up, one of them AR
        self.stall_run = 0
        self.max_stall_run = 0

    def start(self) -> None:
        self.reset()
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None

    async def _run(self) -> None:
        pairs = (("aw", AW_VALID, AW_READY), ("w", W_VALID, W_READY), ("ar", AR_VALID, AR_READY))
        while True:
            await RisingEdge(cocotb.top.clk_i)
            self.cycles += 1
            try:
                chan = int(self.signal.value)
            except ValueError:
                # An X on the port during this window is not a stall verdict;
                # skip the cycle rather than score it either way.
                continue
            for name, vbit, rbit in pairs:
                if chan & vbit and self.valid_cycle[name] is None:
                    self.valid_cycle[name] = self.cycles
                if chan & vbit and chan & rbit and self.hs_cycle[name] is None:
                    self.hs_cycle[name] = self.cycles
            up = chan & VALID_BITS
            n_up = bin(up).count("1")
            if n_up >= 2 and up & AR_VALID:
                self.overlap_cycles += 1
            if up and not (chan & READY_BITS):
                self.stall_run += 1
                self.max_stall_run = max(self.max_stall_run, self.stall_run)
            else:
                self.stall_run = 0

    def presented(self) -> str | None:
        """What the port presented, judged on handshakes and not just valids.

        Valid-arrival order alone cannot name a partially committed state.
        `aw_pending_q` is set by the AW HANDSHAKE, so a cell where AW and AR
        merely asserted in the same cycle never entered that state: it hit the
        StIdle interlock, where nothing was accepted at all. Classifying the
        second as the first would claim a scenario the cell never reached, and
        on this fabric plain traffic arrives with aw == ar, so that is the
        common case rather than a corner. The two get different names.
        """
        aw, w, ar = (self.valid_cycle[k] for k in ("aw", "w", "ar"))
        if aw is None or w is None or ar is None:
            return None
        aw_hs, w_hs = self.hs_cycle["aw"], self.hs_cycle["w"]
        # Partially committed: the leading write channel was ACCEPTED strictly
        # before AR was presented.
        if aw_hs is not None and aw_hs < ar:
            return "aw-then-ar"
        if w_hs is not None and w_hs < ar:
            return "w-then-ar"
        # Nothing accepted. An AR that overlapped the write at all means the
        # StIdle interlock, every ready gated by the other side's valid.
        if self.overlap_cycles:
            return "interlock"
        return f"other(aw={aw},w={w},ar={ar})"

    def summary(self) -> str:
        return (
            f"valid(aw={self.valid_cycle['aw']},w={self.valid_cycle['w']},"
            f"ar={self.valid_cycle['ar']}) "
            f"hs(aw={self.hs_cycle['aw']},w={self.hs_cycle['w']},ar={self.hs_cycle['ar']}) "
            f"overlap={self.overlap_cycles}cyc max_all_ready_low={self.max_stall_run}cyc"
        )


class SepAxiConcurrentRw:
    """Drives each concurrent-channel cell and checks both signatures."""

    def __init__(self, test, *, bus: str = "s_axi") -> None:
        self.test = test
        self.bus = bus
        env = test.env
        self._agent_name = "env.axi_agent" if bus == "s_axi" else "env.ext_axi_agent"
        self._agent = env.axi_agent if bus == "s_axi" else env.ext_axi_agent
        # The TB-master-side view. Comparing it against the adapter-port view
        # is what attributes a channel stagger to the master or to the fabric
        # between them, instead of inferring one from the other.
        self._mon = env.axi_monitor if bus == "s_axi" else env.ext_axi_monitor
        self._start = test.start_seq if bus == "s_axi" else test.start_ext_seq
        # One cell per leaf, so these are scalars, not tallies.
        self.cal: dict[str, int] | None = None
        self.presented: str | None = None
        self.observation: str = "not driven"
        self.covered: int = 0
        # First handshake cycle of each channel at the adapter port, per cell.
        self.hs: dict[str, int | None] = {"aw": None, "w": None, "ar": None}
        self.unreachable: str | None = None
        # Set once a lane adapter has stalled. It cannot be cleared without a
        # reset, so the walk stops rather than reporting later cells as
        # independent failures of the same wedge.
        self.wedged = False

    def _master(self):
        """The VIP master sequence, bypassing the one-item-at-a-time sequencer.

        The SEP AXI driver awaits each item to completion, so a read and a
        write can never be in flight together through it. The VIP drives each
        channel from its own queue, so two coroutines on the master sequence
        do overlap. Raises rather than returning None: without the master
        there is no concurrency and the walk would report cells it never drove.
        """
        seq = getattr(getattr(self._agent, "driver", None), "axi", None)
        if seq is None or not hasattr(seq, "write_bytes_result"):
            raise RuntimeError(
                f"no VIP master sequence behind {self._agent_name}.driver.axi on "
                f"{self.bus}; the concurrent-channel walk cannot overlap a read "
                f"with a write and would report cells it never drove"
            )
        return seq

    def _driver(self):
        drv = getattr(self._master(), "driver", None)
        if drv is None or not hasattr(drv, "set_timing"):
            raise RuntimeError(
                f"no VIP master driver with set_timing() on {self.bus}; the "
                f"concurrent-channel walk cannot place AR inside the AW/W window"
            )
        return drv

    async def _wr(self, addr: int, data: int, *, allow_timeout: bool = False) -> int | None:
        """One write through the SEP AXI sequencer; returns its response.

        `allow_timeout` is accepted and ignored -- see the note below on why
        this path cannot meet a wedged adapter.

        The sequencer path rather than the VIP master directly:
        the scoreboard is fed from the agent's analysis port, and a test whose
        every access bypassed it would finish with no positive evidence and
        could never report a pass, whatever the DUT did. Only the OVERLAPPING
        pair bypasses the sequencer, because concurrency is the one thing the
        sequencer cannot express.
        """
        seq = SepAxiAccessSeq(
            f"conc_wr_0x{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data & 0xFFFF_FFFF,
            length=4,
            size=2,
        )
        # No allow_timeout on this path: every sequencer
        # access this walk makes -- calibration, prime, readback -- happens
        # BEFORE the overlapping pair, so none of them can meet a wedged
        # adapter. A hang here would mean the lane was already stuck on
        # arrival, which is a hard error and should surface as one rather than
        # be folded into an arbitration verdict.
        await self._start(seq)
        return seq.resp_code

    async def _rd(self, addr: int, *, allow_timeout: bool = False) -> tuple[int | None, int]:
        """One read through the SEP AXI sequencer; returns (response, data).

        `allow_timeout` is accepted and ignored, as for `_wr`.
        """
        seq = SepAxiAccessSeq(
            f"conc_rd_0x{addr:08x}",
            op=SepAxiOp.READ,
            addr=addr,
            length=4,
            size=2,
        )
        await self._start(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def probe_read(self, addr: int) -> int:
        """Plain read used to confirm a lane is reachable from this bus.

        A closed gate would fail the cell on its prime write and read as an
        arbitration defect, so the caller checks the path before driving.
        """
        resp, _data = await self._rd(addr, allow_timeout=True)
        return -1 if resp is None else resp

    async def probe_mask(self, addr: int) -> int:
        """The writable bits of `addr`, measured rather than assumed.

        Writes all-ones and reads back: what sticks is writable. The two
        blocks implement different interrupt counts, so a hardcoded width is
        wrong for one of them, and a non-existent bit reads back 0 -- which is
        indistinguishable from a dropped write and would be reported as a DUT
        defect. Measuring removes that whole failure mode.
        """
        resp = await self._wr(addr, INTR_ENABLE_PROBE)
        if resp != RESP_OKAY:
            return 0
        resp, mask = await self._rd(addr)
        if resp != RESP_OKAY:
            return 0
        return mask

    async def calibrate(self, cfg: SepAxiConcurrentRwCfg) -> dict[str, int] | None:
        """Measure when AW, W and AR reach the adapter port, in issue cycles.

        A lone write and a lone read, with only one side outstanding. Both
        are driven at default timing, so what comes back is the crossbar +
        axi_to_axi_lite latency this build has, which is what the placement
        has to work around. Returns None when a channel never arrived, so a
        missing measurement cannot be silently read as zero.
        """
        obs = AdapterPortObserver(cfg.lane)

        obs.start()
        self._mon.arm_write_order()
        resp = await self._wr(cfg.wr_addr, cfg.value, allow_timeout=True)
        mst_aw, mst_w = self._mon.write_order_cycles[0], self._mon.write_order_cycles[1]
        obs.stop()
        if resp is None or resp != RESP_OKAY:
            self.test.logger.error(
                "CHK-CONCURRENT-CAL FAIL: calibration write to 0x%08x resp=%s",
                cfg.wr_addr,
                resp,
            )
            return None
        aw_at, w_at = obs.valid_cycle["aw"], obs.valid_cycle["w"]

        obs.start()
        resp, _data = await self._rd(cfg.rd_addr, allow_timeout=True)
        obs.stop()
        if resp is None or resp != RESP_OKAY:
            self.test.logger.error(
                "CHK-CONCURRENT-CAL FAIL: calibration read of 0x%08x resp=%s",
                cfg.rd_addr,
                resp,
            )
            return None
        ar_at = obs.valid_cycle["ar"]

        if aw_at is None or w_at is None or ar_at is None:
            self.test.logger.error(
                "CHK-CONCURRENT-CAL FAIL: %s port never presented aw=%s w=%s ar=%s "
                "during a lone write and a lone read; the probe is not watching "
                "the adapter this lane's registers are behind",
                cfg.lane,
                aw_at,
                w_at,
                ar_at,
            )
            return None

        self.cal = {"aw": aw_at, "w": w_at, "ar": ar_at}
        # Where a stagger comes from, stated rather than inferred: the master
        # presented AW and W this far apart, the port saw them this far apart.
        # A stagger present at the port but not at the master belongs to the
        # fabric in between and cannot be closed by a master-side profile.
        mst_gap = None if mst_aw is None or mst_w is None else mst_w - mst_aw
        port_gap = w_at - aw_at
        self.test.logger.info(
            "CHK-CONCURRENT-CAL PASS: %s port latency aw=%d w=%d ar=%d issue "
            "cycles; AW->W gap master=%s port=%d (%s)",
            cfg.lane,
            aw_at,
            w_at,
            ar_at,
            mst_gap,
            port_gap,
            "fabric-introduced"
            if mst_gap is not None and port_gap > mst_gap
            else "master-introduced"
            if mst_gap == port_gap
            else "unattributed",
        )
        return self.cal

    def place(self, cfg: SepAxiConcurrentRwCfg, cal: dict[str, int]) -> AxiTimingProfile | None:
        """The delay profile that puts the ordering on the port, or None.

        Each channel is held back by (target arrival - measured arrival), so a
        channel the fabric already delivers late is not delayed again. A
        negative hold is unreachable: the profile can only ever delay a
        channel, never advance one.
        """
        gap = cfg.gap
        if cfg.order == "all-same-cycle":
            at = {k: max(cal.values()) for k in ("aw", "w", "ar")}
        elif cfg.order == "aw-then-ar":
            # AW must handshake before AR arrives, and W must arrive last, so
            # the adapter is in aw_pending_q=1 / w_pending_q=0 when AR lands.
            base = cal["aw"]
            at = {"aw": base, "ar": base + gap, "w": base + 2 * gap}
        else:  # w-then-ar
            base = cal["w"]
            at = {"w": base, "ar": base + gap, "aw": base + 2 * gap}

        holds = {k: at[k] - cal[k] for k in ("aw", "w", "ar")}
        if min(holds.values()) < 0:
            self.test.logger.error(
                "CHK-CONCURRENT-CAL FAIL: %s %s needs a negative hold %s against "
                "measured latency %s; the profile can only delay a channel, so "
                "this ordering is not reachable from this master on this build",
                cfg.lane,
                cfg.order,
                holds,
                cal,
            )
            return None
        # AxiTimingProfile holds the trailing write channel until the leading
        # one asserts, so at most one of aw/w may carry a hold. A placement
        # needing both is the same unreachability, reported the same way.
        if holds["aw"] and holds["w"]:
            self.test.logger.error(
                "CHK-CONCURRENT-CAL FAIL: %s %s needs both aw and w held (%s); "
                "AxiTimingProfile releases the trailing write channel off the "
                "leading one, so this placement is not expressible",
                cfg.lane,
                cfg.order,
                holds,
            )
            return None
        self.test.logger.info(
            "CHK-CONCURRENT-CAL: %s %s placing aw+%d w+%d ar+%d to reach port "
            "arrivals %s from measured %s",
            cfg.lane,
            cfg.order,
            holds["aw"],
            holds["w"],
            holds["ar"],
            at,
            cal,
        )
        return AxiTimingProfile(aw_delay=holds["aw"], w_delay=holds["w"], ar_delay=holds["ar"])

    async def run_cell(self, cfg: SepAxiConcurrentRwCfg) -> str | None:
        """Drive the one calibrated cell. None when it passed.

        Single shot: one overlap per leaf so a wedge cannot contaminate a
        later cell.
        """
        drv = self._driver()
        tag = f"[{cfg.order} {cfg.lane}]"

        mask = await self.probe_mask(cfg.wr_addr)
        if mask == 0:
            return (
                f"{tag} no writable bit found at 0x{cfg.wr_addr:08x}; the data "
                f"compare would be vacuous, so the cell cannot distinguish a "
                f"dropped concurrent write from a register that stores nothing"
            )
        self.mask = mask
        # Narrow the seed's pattern to bits that exist here, and keep it
        # non-zero and different from its complement, or the compare proves
        # nothing.
        value = cfg.value & mask
        if value == 0 or value == mask:
            value = mask & ~(mask >> 1) if mask else 0
        if value == 0:
            return (
                f"{tag} measured mask 0x{mask:x} leaves no value that differs "
                f"from its complement; the data compare would be vacuous"
            )
        self.test.logger.info(
            "CHK-CONCURRENT-CAL: %s writable mask at 0x%08x measured as 0x%x",
            cfg.lane,
            cfg.wr_addr,
            mask,
        )

        cal = await self.calibrate(cfg)
        if cal is None:
            return f"{tag} calibration failed; the cell was not driven"
        profile = self.place(cfg, cal)
        if profile is None:
            self.unreachable = f"{cfg.order} not placeable from measured latency {cal}"
            return None

        drv.set_timing(AxiTimingProfile())  # prime at default timing
        # Prime the complement so the concurrent write always changes the
        # field. A prime of the reset value would leave the register at zero,
        # which a dropped write also produces.
        prime = (~value) & mask
        prime_resp = await self._wr(cfg.wr_addr, prime, allow_timeout=True)
        if prime_resp is None:
            return f"{tag} prime write to 0x{cfg.wr_addr:08x} did not retire"
        if prime_resp != RESP_OKAY:
            return f"{tag} prime write to 0x{cfg.wr_addr:08x} refused"
        resp, staged = await self._rd(cfg.wr_addr, allow_timeout=True)
        if resp != RESP_OKAY or (staged & mask) != prime:
            return (
                f"{tag} prime readback 0x{staged:08x} != 0x{prime:08x} under "
                f"mask 0x{mask:x}; the cell cannot tell a dropped "
                f"concurrent write from a register that never took the prime"
            )

        obs = AdapterPortObserver(cfg.lane)
        obs.start()
        drv.set_timing(profile)
        try:
            wr = cocotb.start_soon(
                self._master().write_bytes_result(
                    cfg.wr_addr,
                    (value & mask).to_bytes(4, "little"),
                    size=2,
                    check_response=False,
                    timeout_ns=CELL_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            rd = cocotb.start_soon(
                self._master().read_bytes_result(
                    cfg.rd_addr,
                    4,
                    size=2,
                    check_response=False,
                    timeout_ns=CELL_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            wres = await wr
            rres = await rd
        finally:
            drv.set_timing(AxiTimingProfile())
            obs.stop()

        self.presented = obs.presented()
        self.observation = obs.summary()
        self.hs = dict(obs.hs_cycle)
        self.test.logger.info(
            "CHK-CONCURRENT-STIM %s: requested=%s presented=%s %s.INTR_ENABLE %s",
            "OK " if self.presented == cfg.order else "DIFF",
            cfg.order,
            self.presented,
            cfg.lane,
            self.observation,
        )

        # A stall is the reported failure whether or not the placement matched:
        # the accesses did not retire, which is a defect under every ordering.
        if wres.timed_out or rres.timed_out:
            which = [w for w, r in (("write", wres), ("read", rres)) if r.timed_out]
            self.wedged = True
            return (
                f"{tag} {' and '.join(which)} did not retire within "
                f"{CELL_TIMEOUT_NS} ns with AW/W/AR presented as "
                f"{self.presented} at the {cfg.lane} lane adapter port -- the "
                f"port held its valids for {obs.max_stall_run} consecutive "
                f"cycles with aw_ready, w_ready and ar_ready ALL low, so no "
                f"channel could retire and neither side may deassert VALID "
                f"(AMBA IHI 0022 A3.2.1). {self.observation}"
            )

        # The named leaf is covered only when THIS ordering is what the port
        # presented. A different overlap after an RTL fix would pass the
        # arbitration contract on a different cell than the leaf name claims.
        if self.presented != cfg.order or obs.overlap_cycles == 0:
            self.unreachable = (
                f"requested {cfg.order}, port presented {self.presented}, "
                f"{obs.overlap_cycles} overlap cycles"
            )
            return None

        if wres.resp != RESP_OKAY:
            return (
                f"{tag} concurrent write resp={wres.resp}, expected OKAY -- "
                f"an AR overlapping a write is legal AXI"
            )
        if rres.resp != RESP_OKAY:
            return (
                f"{tag} concurrent read resp={rres.resp}, expected OKAY -- "
                f"a write overlapping this AR is legal AXI"
            )

        resp, after = await self._rd(cfg.wr_addr, allow_timeout=True)
        if resp != RESP_OKAY:
            return f"{tag} readback resp={resp}"
        if (after & mask) != (value & mask):
            hint = ""
            if (after & mask) == prime:
                hint = (
                    " -- the write did not land; an adapter whose pending-write "
                    "state is consumed or cleared by the overlapping read fails "
                    "exactly here"
                )
            return (
                f"{tag} 0x{cfg.wr_addr:08x}: wrote 0x{value:08x} over "
                f"0x{prime:08x}, read 0x{after:08x} under mask "
                f"0x{mask:x} with AR overlapping{hint}"
            )

        self.covered = obs.overlap_cycles
        return None
