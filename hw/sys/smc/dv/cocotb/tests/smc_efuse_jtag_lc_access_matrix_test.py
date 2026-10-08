# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle-gated eFuse JTAG access-control matrix.

Exercises the SMC-OTP JTAG access-control policy through product ports:

  * ``tb_lc_state`` drives ``lc_state_i`` = {diff_n, diff_p} directly, and
  * the ``ej_axi`` AXI-Lite master drives ``axil_smc_otp_jtag_req_i``.

For each lifecycle state the test checks whether a JTAG-side eFuse access is
routed to the access-control error slave (DECERR) or reaches the eFuse
controller and completes there (OKAY); the map content behind an allowed read
is ``smc_efuse_map_read_test``'s claim. Every access waits for fuse sense first,
because until sense completes the shadow window answers SLVERR / 0xBADCAB1E to
allowed and blocked requests alike.

The expected matrix follows ``hw/ip/efuse/doc/architecture.adoc``
§"Lifecycle State (LC_STATE) Effects":

  * lifecycle encodings, :265-282 --
    ``TEST_DEV 0x0 | PROD 0x1 | RMA_SOP 0x2, 0x3 | RMA_CHIPLET 0x6-0x7 |
    PROD_END 0x8 | INVALID all others``;
  * the restricted set, :286 -- "When lifecycle state is PROD (0x1) or RMA_SOP
    (0x2, 0x3), JTAG access to eFuse registers is restricted";
  * the access table, :289-295 -- JTAG Write *Blocked* / JTAG Read *Blocked*
    except Chiplet ID / JTAG Read Chiplet ID Allowed, in both columns;
  * the Chiplet ID exception, :301-305 -- "Even in PROD or RMA_SOP states, JTAG
    read access to the chiplet ID and package ID registers is permitted";
  * the blocked response, :297-299 -- "the error slave returns an error response
    with data value `0xbadcab1e`".

The differential encoding of the input is SPEC'd at
``hw/sys/smc/doc/port_table.adoc:64``: ``lc_state_i`` is
``[2*LC_STATE_WIDTH-1:0]`` (8 bits), "Lifecycle state input, differentially
encoded", "tie to 8'hf0 if unused (encoded TEST_DEV)" -- i.e. ``{~raw, raw}``,
which for ``raw = 0x0`` is exactly ``8'hf0``. Equal halves are therefore not a
legal encoding of any state; that is the differential-integrity (sigint) case,
which ``architecture.adoc:281`` classes as ``INVALID ... (error fallback)``; the
SIGINT row expects the access-control gate to block on that fallback.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, SimTimeoutError, with_timeout
from env.smc_protocol_vip_item import SmcProtocolVipKind
from env.smc_sys_axi_agent import idle_axil_master_inputs
from ocah_axi_vip import OcahAxiLiteMasterAgent
from seq_lib.smc_addr_map import smc_addr
from seq_lib.smc_base_test_seq import wait_fuse_sense_done
from smc_base_test import smc_base_test

# JTAG-side eFuse (full SMC-local) addresses (PeakRDL smc_addr.h).
EFUSE_MAP_NON_ID = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
EFUSE_MAP_JTAG_PUBLIC_IDENTITY = smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR")

# architecture.adoc:297-299 -- blocked request -> error slave -> 0xbadcab1e.
BLOCK_SIGNATURE = 0xBADCAB1E

# architecture.adoc:270-282 "Lifecycle State Encoding". LC_STATE_WIDTH = 4
# (port_table.adoc:64: lc_state_i is [2*LC_STATE_WIDTH-1:0] = 8 bits).
LC_TEST_DEV = 0x0
LC_PROD = 0x1
LC_RMA_SOP = 0x2
LC_RMA_SOP_ALT = 0x3
LC_RMA_CHIPLET = 0x6
LC_PROD_END = 0x8

# architecture.adoc:286 -- the restricted set is exactly PROD and RMA_SOP.
LC_JTAG_RESTRICTED = (LC_PROD, LC_RMA_SOP, LC_RMA_SOP_ALT)

# architecture.adoc:301-305 -- the identity exception is JTAG_PUBLIC_IDENTITY.
LC_IDENTITY_ADDRS = (EFUSE_MAP_JTAG_PUBLIC_IDENTITY,)

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3

# Bound for one JTAG-side AXI-Lite access. Expiry is a FAILURE, never a pass.
JTAG_ACCESS_TIMEOUT_NS = 400


def pack_lc_state(raw: int, *, sigint: bool = False) -> int:
    """Pack product ``lc_state_i = {diff_n, diff_p}`` (WIDTH=4 each).

    SPEC (``hw/sys/smc/doc/port_table.adoc:64``): differentially encoded, and
    ``8'hf0`` encodes TEST_DEV (raw 0x0), i.e. ``diff_n = ~raw``. Equal halves
    are not a legal encoding of any state and are used here to inject the
    differential-integrity error.
    """
    raw4 = int(raw) & 0xF
    diff_n = raw4 if sigint else ((~raw4) & 0xF)
    return ((diff_n & 0xF) << 4) | raw4


def expect_read_blocked(raw: int, sigint: bool, addr: int) -> bool:
    """SPEC-derived expected block outcome for a JTAG-side eFuse read."""
    if sigint:
        # architecture.adoc:281 -- undecodable => INVALID (error fallback); the
        # fail-safe fallback of an access-control gate is to block everything,
        # identity exception included.
        return True
    if raw not in LC_JTAG_RESTRICTED:
        return False  # architecture.adoc:291-295, "Other States" column
    return addr not in LC_IDENTITY_ADDRS  # :293 + :301-305


def expect_write_blocked(raw: int, sigint: bool) -> bool:
    """SPEC-derived expected block outcome for a JTAG-side eFuse write.

    architecture.adoc:292 -- JTAG Write is *Blocked* in PROD/RMA_SOP and Allowed
    in other states; there is no write exception for the identity registers.
    """
    if sigint:
        return True
    return raw in LC_JTAG_RESTRICTED


# (raw, sigint, label) rows; expect_read_blocked / expect_write_blocked give
# each row's expectation.
LC_MATRIX = [
    (LC_TEST_DEV, False, "TEST_DEV"),
    (LC_PROD, False, "PROD"),
    (LC_RMA_SOP, False, "RMA_SOP"),
    (LC_RMA_CHIPLET, False, "RMA_CHIPLET"),
    (LC_PROD_END, False, "PROD_END"),
    (LC_TEST_DEV, True, "SIGINT"),
]

READ_CLASSES = (
    ("NON_ID", EFUSE_MAP_NON_ID),
    ("JTAG_PUBLIC_IDENTITY", EFUSE_MAP_JTAG_PUBLIC_IDENTITY),
)

# Hierarchical decode probe. `hw/sys/smc/dv/tb/smc_public_scope.vlt` publishes
# `lc_state_smc_raw` / `lc_sigint_err` / `is_prod_or_rma_sip` READ-ONLY
# (`public_flat_rd -module "smc_efuse_wrapper"`), which is what makes this path
# resolvable under Verilator.
_LC_PROBE_PATH = ("u_dut", "u_smc", "u_smc_peripherals", "u_smc_efuse_wrapper")
_LC_PROBE_VARS = ("lc_state_smc_raw", "lc_sigint_err", "is_prod_or_rma_sip")


@pyuvm.test()
class smc_efuse_jtag_lc_access_matrix_test(smc_base_test):
    """Drive lc_state_i + JTAG eFuse accesses; assert the block/allow matrix."""

    required_evidence = (
        "CHK-EFUSE-JTAG-LC-PROD",
        "CHK-EFUSE-JTAG-LC-PROD_END",
        "CHK-EFUSE-JTAG-LC-RMA_CHIPLET",
        "CHK-EFUSE-JTAG-LC-RMA_SOP",
        "CHK-EFUSE-JTAG-LC-SIGINT",
        "CHK-EFUSE-JTAG-LC-TEST_DEV",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.errors: list[str] = []
        self.checks = 0
        self.chk_seen: set[str] = set()
        # Per-address-class outcome witness: {addr: set(blocked_bool)}. Filled
        # by every read, and required at the end to contain BOTH outcomes for at
        # least one address, so a build in which the demux never discriminates
        # cannot pass ([NO-ALWAYS-PASS-CHECKER]).
        self._read_outcomes: dict[int, set[bool]] = {}
        self._write_outcomes: set[bool] = set()

        # The wrapper decode probe must resolve before the first lifecycle step:
        # `hw/sys/smc/dv/tb/smc_public_scope.vlt` publishes the three signals
        # read-only, and an unresolvable handle means that publication or the
        # wrapper hierarchy changed.
        self._lc_probe = self._resolve_lc_probe()

        # Idle the JTAG-side eFuse master control and start at TEST_DEV.
        dut.tb_lc_state.value = pack_lc_state(LC_TEST_DEV)

        idle_axil_master_inputs(dut, "ej_axi")
        self.ejm = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "ej_axi",
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name="smc_ej_axil",
            reset_active_level=False,
        ).sequence
        await ClockCycles(dut.clk_smc_i, 5)
        await wait_fuse_sense_done()

        for raw, sigint, label in LC_MATRIX:
            await self._set_lc_state(raw, sigint, label)
            before = len(self.errors)
            observed: list[str] = []
            for cls, addr in READ_CLASSES:
                code = await self._check_read(
                    label, cls, addr, expect_read_blocked(raw, sigint, addr)
                )
                observed.append(f"{cls}:resp={code}")
            code = await self._check_write(
                label, EFUSE_MAP_NON_ID, expect_write_blocked(raw, sigint)
            )
            observed.append(f"WRITE:resp={code}")
            if len(self.errors) == before:
                token = f"CHK-EFUSE-JTAG-LC-{label}"
                cocotb.log.info(
                    "%s: lc_state_i=0x%02x (raw=0x%x sigint=%s) -- all three "
                    "SPEC-derived block/allow expectations held (%s)",
                    token,
                    pack_lc_state(raw, sigint=sigint),
                    raw,
                    sigint,
                    " ".join(observed),
                )
                self.chk_seen.add(token)

        # Restore a benign lifecycle state.
        await self._set_lc_state(LC_TEST_DEV, False, "RESTORE")

        assert not self.errors, "eFuse JTAG LC access-control matrix mismatch:\n" + "\n".join(
            self.errors
        )

        # Anti-vacuity gate. The AXI response code is the discriminator, and
        # this requires it to have taken BOTH values on the same address in the
        # same run. A build whose access-control demux is stuck (always routing
        # to the error slave, or never routing to it) fails here even though
        # every individual row's expectation could still be satisfied by one of
        # the two stuck behaviours.
        discriminating = [addr for addr, outs in self._read_outcomes.items() if len(outs) == 2]
        assert discriminating, (
            "no eFuse map address was both blocked and allowed across the six "
            "lifecycle states: the access-control demux never discriminated, so "
            "the matrix proves nothing "
            f"(per-address outcomes: { {hex(a): sorted(o) for a, o in self._read_outcomes.items()} })"
        )
        assert len(self._write_outcomes) == 2, (
            "JTAG eFuse writes were "
            f"{'always' if True in self._write_outcomes else 'never'} blocked "
            "across the six lifecycle states: the write half of the matrix "
            "never discriminated"
        )
        missing = [
            f"CHK-EFUSE-JTAG-LC-{label}"
            for _r, _s, label in LC_MATRIX
            if f"CHK-EFUSE-JTAG-LC-{label}" not in self.chk_seen
        ]
        assert not missing, f"missing CHK evidence tokens: {missing}"

        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            # Directed stimulus floor: the six LC_MATRIX rows, each two reads
            # (READ_CLASSES) and one write, is 18 lc_state-driven JTAG eFuse
            # access-control checks; a floor taken from `self.checks` would
            # shrink with a run that issued fewer.
            min_csr_accesses=18,
            csr_accesses=self.checks,
            proxy=False,
            details=(
                "lc_state_i-driven JTAG eFuse access-control ROUTING matrix "
                "(PROD/RMA_SOP block + JTAG_PUBLIC_IDENTITY exception + "
                "differential-integrity lockdown), expectations derived from "
                "hw/ip/efuse/doc/architecture.adoc:265-305; after fuse sense, "
                "blocked = DECERR + 0xBADCAB1E from the error slave, allowed = "
                "OKAY from the eFuse controller, both outcomes observed on the "
                "same address. No data claim is made on the allowed reads"
            ),
        )

    # --- lifecycle drive + optional white-box decode cross-check -------------

    def _resolve_lc_probe(self):
        """Resolve the wrapper decode handle once; an unresolvable path fails."""
        node = cocotb.top
        for part in _LC_PROBE_PATH:
            nxt = getattr(node, part, None)
            assert nxt is not None, (
                f"lc-decode cross-check handle {'.'.join(_LC_PROBE_PATH)} does "
                f"not resolve (stopped at '{part}'). "
                "hw/sys/smc/dv/tb/smc_public_scope.vlt must keep publishing "
                "lc_state_smc_raw / lc_sigint_err / is_prod_or_rma_sip on "
                "smc_efuse_wrapper for this leg to run; without them the "
                "decode comparison in _set_lc_state would never execute."
            )
            node = nxt
        for var in _LC_PROBE_VARS:
            assert getattr(node, var, None) is not None, (
                f"lc-decode cross-check signal '{var}' is not published on "
                f"{'.'.join(_LC_PROBE_PATH)}"
            )
        cocotb.log.info("lc-decode cross-check ENABLED on %s", ".".join(_LC_PROBE_PATH))
        return node

    async def _set_lc_state(self, raw: int, sigint: bool, label: str) -> None:
        dut = cocotb.top
        dut.tb_lc_state.value = pack_lc_state(raw, sigint=sigint)
        # Settle the diff decode + the access-control demux spill registers.
        await ClockCycles(dut.clk_smc_i, 20)

        # Expected decode: sigint forces raw 0 and prod 0; otherwise prod is set
        # for the architecture.adoc:286 restricted set (LC_JTAG_RESTRICTED).
        exp_sigint = 1 if sigint else 0
        exp_prod = 0 if sigint else (1 if raw in LC_JTAG_RESTRICTED else 0)
        exp_raw = 0 if sigint else raw

        efw = self._lc_probe
        got_raw = int(efw.lc_state_smc_raw.value)
        got_sigint = int(efw.lc_sigint_err.value)
        got_prod = int(efw.is_prod_or_rma_sip.value)
        cocotb.log.info(
            "lc decode [%s] raw=0x%x sigint=%d prod_or_rma=%d (exp raw=0x%x sigint=%d prod=%d)",
            label,
            got_raw,
            got_sigint,
            got_prod,
            exp_raw,
            exp_sigint,
            exp_prod,
        )
        if (got_raw, got_sigint, got_prod) != (exp_raw, exp_sigint, exp_prod):
            self.errors.append(
                f"[{label}] lc decode mismatch for raw=0x{raw:x} sigint={sigint}: "
                f"got (raw=0x{got_raw:x}, sigint={got_sigint}, prod={got_prod}) "
                f"exp (raw=0x{exp_raw:x}, sigint={exp_sigint}, prod={exp_prod})"
            )

    # --- bounded JTAG accesses; expiry is a failure --------------------------

    async def _read(self, addr: int):
        """Bounded JTAG eFuse read. Returns (rdata|None, resp_code|None)."""
        event = self.ejm.init_read(address=addr, length=4)
        try:
            await with_timeout(event.wait(), JTAG_ACCESS_TIMEOUT_NS, "ns")
        except SimTimeoutError:
            return None, None
        resp = event.data
        rdata = int.from_bytes(resp.data, "little")
        return rdata, _resp_code(resp)

    async def _write(self, addr: int, data: int):
        """Bounded JTAG eFuse write. Returns resp_code|None."""
        event = self.ejm.init_write(address=addr, data=data.to_bytes(4, "little"))
        try:
            await with_timeout(event.wait(), JTAG_ACCESS_TIMEOUT_NS, "ns")
        except SimTimeoutError:
            return None
        return _resp_code(event.data)

    def _bus_state(self) -> str:
        dut = cocotb.top
        bits = []
        for sig in (
            "ej_axi_arvalid",
            "ej_axi_arready",
            "ej_axi_rvalid",
            "ej_axi_awvalid",
            "ej_axi_awready",
            "ej_axi_wvalid",
            "ej_axi_bvalid",
            "rst_primary_smc_clk_no",
        ):
            handle = getattr(dut, sig, None)
            if handle is not None:
                bits.append(f"{sig}={handle.value}")
        return " ".join(bits) if bits else "<no ej_axi handles>"

    async def _check_read(self, label: str, cls: str, addr: int, expect_block: bool) -> int | None:
        self.checks += 1
        rdata, code = await self._read(addr)

        # A timed-out access (code None) must fail before the `blocked` compare:
        # `code == RESP_DECERR` is False for None, which is the ALLOW pass
        # condition.
        if code is None:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} got NO AXI response within "
                f"{JTAG_ACCESS_TIMEOUT_NS}ns (expected "
                f"{'BLOCK (DECERR)' if expect_block else 'ALLOW'}); "
                f"bus state: {self._bus_state()}"
            )
            return None

        # A blocked access is the err_slv DECERR. An allowed access reaches the
        # eFuse controller and, with fuse sense complete, completes OKAY; the
        # end-of-run gate requires both codes to have been seen on the same
        # address.
        blocked = code == RESP_DECERR
        self._read_outcomes.setdefault(addr, set()).add(blocked)
        cocotb.log.info(
            "JTAG eFuse read  [%s] %s @0x%08x -> rdata=0x%08x resp=%s blocked=%s (exp_block=%s)",
            label,
            cls,
            addr,
            rdata,
            code,
            blocked,
            expect_block,
        )
        if expect_block and not blocked:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} expected BLOCK (DECERR) but "
                f"got resp={code} rdata=0x{rdata:08x}"
            )
        elif not expect_block and blocked:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} expected ALLOW but was blocked (DECERR)"
            )
        elif not expect_block and code != RESP_OKAY:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} expected ALLOW (resp=OKAY at the eFuse "
                f"controller) but got resp={code} rdata=0x{rdata:08x}"
            )
        elif expect_block and rdata != BLOCK_SIGNATURE:
            # architecture.adoc:297-299: the error slave's blocked-read data.
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} blocked but data "
                f"0x{rdata:08x} != SPEC err-slv signature "
                f"0x{BLOCK_SIGNATURE:08x} (architecture.adoc:297-299)"
            )
        return code

    async def _check_write(self, label: str, addr: int, expect_block: bool) -> int | None:
        self.checks += 1
        # LOCKS is write-set-only: any bit this write sets locks a field for
        # the rest of the run, so the routing probe writes 0 and leaves the
        # map as sensed.
        code = await self._write(addr, 0)
        if code is None:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} got NO AXI response within "
                f"{JTAG_ACCESS_TIMEOUT_NS}ns (expected "
                f"{'BLOCK (DECERR)' if expect_block else 'ALLOW'}); "
                f"bus state: {self._bus_state()}"
            )
            return None
        # A blocked write is routed to the err_slv -> DECERR. An allowed write
        # reaches the eFuse controller and, with fuse sense complete, completes
        # OKAY.
        blocked = code == RESP_DECERR
        self._write_outcomes.add(blocked)
        cocotb.log.info(
            "JTAG eFuse write [%s] NON_ID @0x%08x -> resp=%s blocked=%s (exp_block=%s)",
            label,
            addr,
            code,
            blocked,
            expect_block,
        )
        if expect_block and not blocked:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} expected BLOCK (DECERR) but got resp={code}"
            )
        elif not expect_block and blocked:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} expected ALLOW but was blocked (DECERR)"
            )
        elif not expect_block and code != RESP_OKAY:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} expected ALLOW (resp=OKAY at the eFuse "
                f"controller) but got resp={code}"
            )
        return code


def _resp_code(resp):
    code = getattr(resp, "resp", None)
    if code is None:
        return None
    try:
        codes = code if isinstance(code, (list, tuple)) else [code]
        return int(codes[0]) if codes else None
    except Exception:
        return None
