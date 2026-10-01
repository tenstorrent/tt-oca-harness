# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan SPI host transfer on the SEP, graded at the SMC LSIO pads.

Boots hw/sys/sep/dv/fw/tests/sep_smu_spi, which drives a command / address /
receive sequence on the SEP's OpenTitan SPI host and pops the received word out
of RXDATA. The image needs no external flash model and programs no pad path:
the OT SPI host reaches the pads only on the SMC LSIO primary plane (GPIO 0-10
and the DQS loopback pad 54), and no select steers it.

smu.sv drives the SEP SPI pad signals it passes to the SMC from
sep_io_pkg::ot_spi_pad_map (hw/sys/sep/rtl/sep_io_pkg.sv), and returns the data
lanes from the SMC as the SPI host response. This sequence grades that contract
at the deepest point the open tree carries: the SMC pad ports of smu.sv
(core2pad_o, core2pad_en_o, pad2core_en_o, lsio_interface_select_o, pad2core_i).
The host side is read on the ports of u_sep_ot_spi_wrap, upstream of smu.sv.

Every clk_smu cycle from the first sample with the SEP's ICCM-fetch latch set
to POST_IDLE_CYCLES after the firmware verdict is sampled, and:

* MAP: every field that ot_spi_pad_map produces equals, at the pads, the value
  the function defines for the host request of that cycle (``_pad_map_model``
  transcribes the function), and the host data inputs equal pad2core_i[3:0].
* SCK: the pad SCK rises exactly the number of times the firmware's byte counts
  give (FW_SEGMENTS), and the host's own SCK output rises the same number of
  times in the same window.
* FRAME: the pad CS# falls once per chip-select window of the firmware, each
  window holds that window's SCK rises, and no SCK rise occurs with CS# high.
* OE: at every SCK rise the SCK and CS# pads are driven, the receive lane and
  lanes 2-7 are not driven, and on every transmit bit the transmit lane is
  driven; while CS# is high no data lane is driven; before the host enables its
  outputs the SCK and CS# pads are not driven. In standard mode lane 0 is the
  host's output lane and the host may keep it driven into a receive segment, so
  on receive bits its enable is graded by MAP against the host, not here.
* MOSI: the bytes on the transmit pad at the SCK rises are the firmware's
  TXDATA bytes in the host's little-endian byte order.
* RSP: a bench SPI device drives a seeded pattern on the receive pad, shifting
  on the SCK falling edge; the host data input follows the pad at every receive
  SCK rise, and the one word popped from the host RX FIFO equals the pattern.
* IDLE: no pad net moves on a cycle where the host outputs do not move, the
  windows before and after the transfer have no pad change, and each pad net
  the transfer drives moves inside the transfer.

X/Z is not graded as a check: Verilator, the simulator this bench builds with,
is two-state. A sample the monitor cannot read as 0/1 still fails the run,
because the checks above cannot grade that cycle.

Every probe is resolved by its full path before the run starts; a path that
does not resolve fails the test. The image parks in one of eight per-stage fail
loops, so a firmware failure names the point in the transfer that stalled.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq
from seq_lib.smu_compose_helpers import hier

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SEEDED_RNG_PY = _REPO_ROOT / "hw" / "sys" / "sep" / "dv" / "cocotb" / "env" / "sep_seeded_rng.py"

SMU_PATH = "u_dut.u_smu"
HOST_PATH = "gen_sep.u_sep.u_sep_io.u_sep_ot_spi_wrap"
HOST_CORE_PATH = HOST_PATH + ".u_spi_host"

# SMC LSIO primary-plane SPI pins (hw/sys/smc/rtl/smc_peripherals/rtl/smc_padring.sv).
PAD_DQ = tuple(range(8))
PAD_CS = 8
PAD_SCK = 9
PAD_DQS = 10
PAD_DQS_LOOP = 54
SPI_PADS = (*PAD_DQ, PAD_CS, PAD_SCK, PAD_DQS, PAD_DQS_LOOP)
MOSI_LANE = 0
MISO_LANE = 1

# The transfer run_spi_txrx_sequence() in sep_smu_spi.c issues, in order:
# (bytes, COMMAND.CSAAT, direction). Every segment is standard speed
# (COMMAND.SPEED=0), so a byte is 8 SCK periods on one lane, and with
# CONFIGOPTS.CPOL=0 each period has one SCK rising edge.
TX = "tx"
RX = "rx"
FW_SEGMENTS = ((1, 0, TX), (4, 1, TX), (4, 0, RX))
# The TXDATA word the firmware writes for each TX segment, in order.
FW_TXDATA_WORDS = (0x0000_009F, 0x0010_0003)
BITS_PER_BYTE = 8

#: Clock cycles sampled after the firmware verdict; the host is idle there.
POST_IDLE_CYCLES = 2000
#: Least number of cycles the window before the first host change must hold.
MIN_PRE_IDLE_CYCLES = 200
#: Salt for the receive pattern, so it does not track other seeded draws.
RSP_SALT = 0x5E9_5B1


def _edge_plan() -> tuple[list[str], list[int]]:
    """Direction of each SCK rise, and the rises in each chip-select window."""
    directions: list[str] = []
    windows: list[int] = []
    in_window = 0
    for nbytes, csaat, direction in FW_SEGMENTS:
        directions += [direction] * (nbytes * BITS_PER_BYTE)
        in_window += nbytes * BITS_PER_BYTE
        if not csaat:
            windows.append(in_window)
            in_window = 0
    if in_window:
        raise AssertionError("FW_SEGMENTS ends with CSAAT=1; the last window never closes")
    return directions, windows


EDGE_DIRECTIONS, CS_WINDOW_RISES = _edge_plan()
EXPECTED_SCK_RISES = len(EDGE_DIRECTIONS)
TX_BYTES = sum(n for n, _, d in FW_SEGMENTS if d == TX)
RX_BYTES = sum(n for n, _, d in FW_SEGMENTS if d == RX)
# STATUS.BYTEORDER=1 (OpenTitan spi_host ByteOrder): the host sends byte 0 of
# each TXDATA word first and puts the first received byte in RXDATA[7:0]; bits
# go MSB first inside a byte. A TX segment sends the first bytes of its own
# word; the host drops the bytes a segment leaves unsent in its last word.
EXPECTED_MOSI = [
    (word >> (8 * i)) & 0xFF
    for word, nbytes in zip(FW_TXDATA_WORDS, (n for n, _, d in FW_SEGMENTS if d == TX), strict=True)
    for i in range(nbytes)
]

# Host fields that must take both values inside the window, so the MAP check
# grades both polarities of each pad field that follows them.
HOST_TOGGLE_FIELDS = ("sck", "sck_oe", "cs_n", "cs_oe", "sd0", "sd_oe0")


def _load_seeded_rng():
    spec = importlib.util.spec_from_file_location("sep_seeded_rng", _SEEDED_RNG_PY)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load the seeded RNG from {_SEEDED_RNG_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SepSeededRng


def _rsp_pattern(seed: int) -> int:
    """A receive word with four distinct bytes, none 0x00 or 0xFF."""
    rng = _load_seeded_rng()(seed ^ RSP_SALT)
    while True:
        word = rng.getrandbits(8 * RX_BYTES)
        lanes = [(word >> (8 * i)) & 0xFF for i in range(RX_BYTES)]
        if len(set(lanes)) == RX_BYTES and not {0x00, 0xFF} & set(lanes):
            return word


def _wire_bits(word: int) -> list[int]:
    """The bits of ``word`` in the order the host receives them."""
    return [(word >> (8 * byte + bit)) & 1 for byte in range(RX_BYTES) for bit in range(7, -1, -1)]


def _pad_map_model(req: dict[str, int]) -> dict[str, int]:
    """sep_io_pkg::ot_spi_pad_map, transcribed field by field."""
    return {
        "enable": 1,
        "clk": req["sck"],
        "txd": req["sd"] & 0xF,
        "cs_n": req["cs_n"],
        "cs_oe_n": req["cs_oe"] ^ 1,
        "cs_ie_n": req["cs_oe"],
        "clk_oe_n": req["sck_oe"] ^ 1,
        "clk_ie_n": req["sck_oe"],
        "dqs_oe_n": 1,
        "dqs_ie_n": 1,
        "dq_oe_n": 0xF0 | (~req["sd_oe"] & 0xF),
        "dq_ie_n": 0xF0 | (req["sd_oe"] & 0xF),
        "mem_rebar_oepad": 0,
        "mem_rebar_opad": 0,
        "mem_rebar_iepad": 0,
    }


def _bits(value: str, pads) -> int:
    """Gather the given bit positions of an MSB-first binary string, LSB first."""
    return sum(int(value[-1 - pad]) << i for i, pad in enumerate(pads))


def _inv(value: int, width: int) -> int:
    return ~value & ((1 << width) - 1)


def _pads_as_fields(pad: dict[str, str]) -> dict[str, int]:
    """Read each ot_spi_pad_map field back off the SMC pads.

    The SMC LSIO pin select hands each pad the LSIO data and the inverse of the
    active-low LSIO enables (hw/ip/gpio/rtl/gpio.sv), so an active-low field
    reads as the inverse of its pad enable.
    """
    c2p, oe, ie, sel = pad["core2pad"], pad["core2pad_en"], pad["pad2core_en"], pad["select"]
    selects = _bits(sel, SPI_PADS)
    every = (1 << len(SPI_PADS)) - 1
    return {
        # 1 or 0 when every SPI pad agrees; otherwise the per-pad select mask.
        "enable": 1 if selects == every else (0 if selects == 0 else selects << 1),
        "clk": _bits(c2p, (PAD_SCK,)),
        "txd": _bits(c2p, PAD_DQ),
        "cs_n": _bits(c2p, (PAD_CS,)),
        "cs_oe_n": _inv(_bits(oe, (PAD_CS,)), 1),
        "cs_ie_n": _inv(_bits(ie, (PAD_CS,)), 1),
        "clk_oe_n": _inv(_bits(oe, (PAD_SCK,)), 1),
        "clk_ie_n": _inv(_bits(ie, (PAD_SCK,)), 1),
        "dqs_oe_n": _inv(_bits(oe, (PAD_DQS,)), 1),
        "dqs_ie_n": _inv(_bits(ie, (PAD_DQS,)), 1),
        "dq_oe_n": _inv(_bits(oe, PAD_DQ), 8),
        "dq_ie_n": _inv(_bits(ie, PAD_DQ), 8),
        "mem_rebar_oepad": _bits(oe, (PAD_DQS_LOOP,)),
        "mem_rebar_opad": _bits(c2p, (PAD_DQS_LOOP,)),
        "mem_rebar_iepad": _bits(ie, (PAD_DQS_LOOP,)),
    }


class SmuSepSpiSeq(SepTerminalLoopSeq):
    NAME = "sep_spi"
    PASS_SYM = "smu_sep_spi_pass_loop"
    # Labels mirror the firmware's SPI_ERR_* codes, in transfer order.
    FAIL_SYMS = {
        "wait_ready_cmd": "smu_sep_spi_fail_wait_ready_cmd_loop",
        "wait_idle_cmd": "smu_sep_spi_fail_wait_idle_cmd_loop",
        "wait_ready_addr": "smu_sep_spi_fail_wait_ready_addr_loop",
        "wait_ready_rx": "smu_sep_spi_fail_wait_ready_rx_loop",
        "wait_idle_rx": "smu_sep_spi_fail_wait_idle_rx_loop",
        "error_status": "smu_sep_spi_fail_error_status_loop",
        "rx_depth": "smu_sep_spi_fail_rx_depth_loop",
        "rx_drain": "smu_sep_spi_fail_rx_drain_loop",
        # Catch-all for an rc outside the enumerated codes. The compiler can
        # prove it unreachable and drop it; the base sequence then reports it as
        # a path this image does not cover, rather than assuming it passed.
        "unclassified": "smu_sep_spi_fail_loop",
    }
    SYM_DEFAULT = "sep_smu_spi.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_SPI_OK", "SEP_SPI_CONTROLLER_TXRX_OK")
    #: Emitted only after every pad check below holds.
    PAD_EVIDENCE = (
        "SEP_SPI_PAD_MAP_OK",
        "SEP_SPI_PAD_SCK_COUNT_OK",
        "SEP_SPI_PAD_FRAMING_OK",
        "SEP_SPI_PAD_OE_OK",
        "SEP_SPI_PAD_MOSI_OK",
        "SEP_SPI_PAD_RSP_OK",
        "SEP_SPI_PAD_IDLE_OK",
    )

    def __init__(self, test) -> None:
        super().__init__(test)
        test.declare_evidence(*self.PAD_EVIDENCE)
        self._stop_cycle: int | None = None
        self._cycle = 0

    # ------------------------------------------------------------------ probes
    def _resolve_probes(self) -> None:
        dut = self.dut
        smu = hier(dut, SMU_PATH)
        host = hier(smu, HOST_PATH)
        core = hier(smu, HOST_CORE_PATH)
        self._pad_h = {
            "core2pad": hier(smu, "core2pad_o"),
            "core2pad_en": hier(smu, "core2pad_en_o"),
            "pad2core_en": hier(smu, "pad2core_en_o"),
            "select": hier(smu, "lsio_interface_select_o"),
            "pad2core": hier(smu, "pad2core_i"),
        }
        self._host_h = {
            "sck": hier(host, "spi_sck_o"),
            "sck_oe": hier(host, "spi_sck_oe_o"),
            "cs_n": hier(host, "spi_cs_no"),
            "cs_oe": hier(host, "spi_cs_oe_o"),
            "sd": hier(host, "spi_sd_o"),
            "sd_oe": hier(host, "spi_sd_oe_o"),
            "sd_i": hier(host, "spi_sd_i"),
        }
        self._rx_h = {
            "rx_valid": hier(core, "rx_valid"),
            "rx_ready": hier(core, "rx_ready"),
            "rx_data": hier(core, "rx_data"),
        }
        self._drive_en = hier(dut, "tb_gpio_drive_en")
        self._drive_val = hier(dut, "tb_gpio_drive_val")
        self._iccm_seen = hier(dut, "sep_iccm_fetch_seen_o")
        widths = {name: len(h) for name, h in self._pad_h.items()}
        widths["tb_gpio_drive_en"] = len(self._drive_en)
        short = {name: w for name, w in widths.items() if w <= max(SPI_PADS)}
        assert not short, f"{self.NAME}: pad vectors too narrow for pad {max(SPI_PADS)}: {short}"

    def _drive_miso(self, enable: int, value: int) -> None:
        self._drive_en.value = enable << MISO_LANE
        self._drive_val.value = (value & enable) << MISO_LANE

    # ---------------------------------------------------------------- monitor
    async def _monitor(self, rx_bits: list[int]) -> dict:
        st: dict = {
            "start": None,
            "end": None,
            "xz": [],
            "map_bad": {},
            "toggles": {f: set() for f in HOST_TOGGLE_FIELDS},
            "host_rises": 0,
            "pad_rises": 0,
            "host_cs_falls": 0,
            "pad_cs_falls": 0,
            "cs_windows": [],
            "rises_cs_high": [],
            "edges": [],
            "cs_high_data_oe": [],
            "pre_enable_cycles": 0,
            "host_changes": [],
            "pad_changes": [],
            "pad_moves": {},
            "unmatched_pad_changes": [],
            "pops": [],
            "first_cs": None,
            "last_cs": None,
        }
        first_rx = EDGE_DIRECTIONS.index(RX) + 1
        sck_bit = SPI_PADS.index(PAD_SCK)
        cs_bit = SPI_PADS.index(PAD_CS)
        prev_host = prev_pad = prev_sig = None
        driving = 0
        clk = self.dut.clk_smu_i
        while True:
            await RisingEdge(clk)
            self._cycle += 1
            cycle = self._cycle
            if self._stop_cycle is not None and cycle > self._stop_cycle:
                break
            if st["start"] is None:
                if not self._rd(self._iccm_seen, "sep_iccm_fetch_seen_o"):
                    continue
                st["start"] = cycle
            st["end"] = cycle

            raw_pad = {k: str(h.value) for k, h in self._pad_h.items()}
            raw_host = {k: str(h.value) for k, h in self._host_h.items()}
            raw_rx = {k: str(self._rx_h[k].value) for k in ("rx_valid", "rx_ready")}
            bad = [
                (f"{k}[{p}]", v[-1 - p])
                for k, v in raw_pad.items()
                for p in SPI_PADS
                if v[-1 - p] not in "01"
            ]
            bad += [(k, v) for k, v in {**raw_host, **raw_rx}.items() if set(v) - set("01")]
            if raw_rx == {"rx_valid": "1", "rx_ready": "1"}:
                data = str(self._rx_h["rx_data"].value)
                if set(data) - set("01"):
                    bad.append(("rx_data", data))
                else:
                    st["pops"].append((cycle, int(data, 2)))
            if bad:
                st["xz"].append((cycle, bad))
                prev_host = prev_pad = prev_sig = None
                continue

            host = {k: int(v, 2) for k, v in raw_host.items()}
            host["sd0"] = (host["sd"] >> MOSI_LANE) & 1
            host["sd_oe0"] = (host["sd_oe"] >> MOSI_LANE) & 1
            for f in HOST_TOGGLE_FIELDS:
                st["toggles"][f].add(host[f])

            want = _pad_map_model(host)
            seen = _pads_as_fields(raw_pad)
            # Response: smu.sv returns the SMC data lanes 3:0 as the host input.
            want["rxd"] = _bits(raw_pad["pad2core"], range(4))
            seen["rxd"] = host["sd_i"] & 0xF
            for field, value in want.items():
                if seen[field] != value:
                    rec = st["map_bad"].setdefault(field, [0, cycle, value, seen[field]])
                    rec[0] += 1

            sck = _bits(raw_pad["core2pad"], (PAD_SCK,))
            cs_n = _bits(raw_pad["core2pad"], (PAD_CS,))
            oe = _bits(raw_pad["core2pad_en"], range(max(SPI_PADS) + 1))
            if not (oe >> PAD_SCK) & 1 and not (oe >> PAD_CS) & 1:
                st["pre_enable_cycles"] += 1
            if cs_n and _bits(raw_pad["core2pad_en"], PAD_DQ):
                st["cs_high_data_oe"].append((cycle, _bits(raw_pad["core2pad_en"], PAD_DQ)))

            host_sig = tuple(host[k] for k in ("sck", "sck_oe", "cs_n", "cs_oe", "sd", "sd_oe"))
            pad_sig = {
                k: _bits(raw_pad[k], SPI_PADS)
                for k in ("core2pad", "core2pad_en", "pad2core_en", "select")
            }
            if prev_host is not None:
                if host["sck"] and not prev_host["sck"]:
                    st["host_rises"] += 1
                if not host["cs_n"] and prev_host["cs_n"]:
                    st["host_cs_falls"] += 1
                host_moved = host_sig != prev_sig
                pad_moved = pad_sig != prev_pad
                if host_moved:
                    st["host_changes"].append(cycle)
                if pad_moved:
                    st["pad_changes"].append(cycle)
                    for k, v in pad_sig.items():
                        diff = v ^ prev_pad[k]
                        for i, p in enumerate(SPI_PADS):
                            if (diff >> i) & 1:
                                key = f"{k}[{p}]"
                                st["pad_moves"][key] = st["pad_moves"].get(key, 0) + 1
                    if not host_moved:
                        st["unmatched_pad_changes"].append(cycle)

                prev_sck = (prev_pad["core2pad"] >> sck_bit) & 1
                prev_cs = (prev_pad["core2pad"] >> cs_bit) & 1
                if not cs_n and prev_cs:
                    st["pad_cs_falls"] += 1
                    st["cs_windows"].append([st["pad_rises"], None])
                    st["first_cs"] = st["first_cs"] or cycle
                if cs_n and not prev_cs:
                    if st["cs_windows"]:
                        st["cs_windows"][-1][1] = st["pad_rises"]
                    st["last_cs"] = cycle
                    if driving:
                        driving = 0
                        self._drive_miso(0, 0)
                if sck and not prev_sck:
                    st["pad_rises"] += 1
                    n = st["pad_rises"]
                    if cs_n:
                        st["rises_cs_high"].append((n, cycle))
                    st["edges"].append(
                        {
                            "n": n,
                            "cycle": cycle,
                            "dir": EDGE_DIRECTIONS[n - 1] if n <= EXPECTED_SCK_RISES else None,
                            "oe": oe,
                            "mosi": _bits(raw_pad["core2pad"], (MOSI_LANE,)),
                            "host_miso": (host["sd_i"] >> MISO_LANE) & 1,
                            "driven": driving,
                        }
                    )
                # Bench SPI device, mode 0: present the next receive bit on the
                # SCK falling edge, so it is stable at the rising edge the host
                # samples on, and release the pad after the last receive bit.
                if prev_sck and not sck and not cs_n:
                    k = st["pad_rises"] + 1 - first_rx
                    if 0 <= k < len(rx_bits):
                        driving = 1
                        self._drive_miso(1, rx_bits[k])
                    elif driving:
                        driving = 0
                        self._drive_miso(0, 0)

            prev_host, prev_pad, prev_sig = host, pad_sig, host_sig
        return st

    # ------------------------------------------------------------------ grade
    def _grade(self, st: dict, pattern: int) -> list[str]:
        errors: list[str] = []
        log = self.log.info
        if st["start"] is None:
            return ["the SEP never fetched from ICCM, so no window is graded"]
        span = f"cycles {st['start']}..{st['end']}"

        # Unreadable samples: the checks below cannot grade those cycles.
        if st["xz"]:
            c, bad = st["xz"][0]
            errors.append(
                f"SAMPLE: {len(st['xz'])} sampled cycles carry X/Z on a probed net, so "
                f"the checks cannot grade them; first at cycle {c}: {bad[:6]}"
            )
        log("%s: four-state X/Z check not run: Verilator is two-state", self.NAME)

        # MAP
        untoggled = [f for f, vals in st["toggles"].items() if vals != {0, 1}]
        if untoggled:
            errors.append(
                f"MAP: host field(s) {untoggled} took one value only in the window, "
                "so their pad mapping is graded at one polarity"
            )
        for field, (count, c, want, seen) in sorted(st["map_bad"].items()):
            errors.append(
                f"MAP: pad field {field} differs from ot_spi_pad_map on {count} cycles; "
                f"first at cycle {c}: expected 0x{want:x}, pads 0x{seen:x}"
            )
        if not untoggled and not st["map_bad"]:
            log(
                "CHK-SEP-SPI-PAD-MAP: PASS (the 15 ot_spi_pad_map fields and rxd match the "
                "host request on every cycle, %s; host fields with both values: %s)",
                span,
                ", ".join(HOST_TOGGLE_FIELDS),
            )

        # SCK
        pad, hst = st["pad_rises"], st["host_rises"]
        if (pad, hst) != (EXPECTED_SCK_RISES, EXPECTED_SCK_RISES):
            errors.append(
                f"SCK: pad SCK rises={pad}, host SCK rises={hst}, "
                f"firmware byte counts give {EXPECTED_SCK_RISES}"
            )
        else:
            log(
                "CHK-SEP-SPI-PAD-SCK: PASS (pad SCK rises=%d == host SCK rises=%d == %d "
                "from the firmware segment bytes %s)",
                pad,
                hst,
                EXPECTED_SCK_RISES,
                [n for n, _, _ in FW_SEGMENTS],
            )

        # FRAME
        per_window = [
            (end if end is not None else st["pad_rises"]) - begin for begin, end in st["cs_windows"]
        ]
        frame_bad = []
        if (st["pad_cs_falls"], st["host_cs_falls"]) != (len(CS_WINDOW_RISES),) * 2:
            frame_bad.append(
                f"CS# falls pad={st['pad_cs_falls']} host={st['host_cs_falls']}, "
                f"expected {len(CS_WINDOW_RISES)}"
            )
        if per_window != CS_WINDOW_RISES:
            frame_bad.append(f"SCK rises per CS# window {per_window}, expected {CS_WINDOW_RISES}")
        if any(end is None for _, end in st["cs_windows"]):
            frame_bad.append("CS# still low at the end of the window")
        if st["rises_cs_high"]:
            frame_bad.append(f"SCK rose with CS# high at (rise, cycle) {st['rises_cs_high'][:4]}")
        errors.extend(f"FRAME: {msg}" for msg in frame_bad)
        if not frame_bad:
            log(
                "CHK-SEP-SPI-PAD-FRAME: PASS (CS# windows=%d, SCK rises per window=%s, "
                "every SCK rise with CS# low, CS# first low at cycle %s, last high at %s)",
                st["pad_cs_falls"],
                per_window,
                st["first_cs"],
                st["last_cs"],
            )

        # OE
        oe_bad = []
        for e in st["edges"]:
            oe = e["oe"]
            got = {
                "sck_oe": (oe >> PAD_SCK) & 1,
                "cs_oe": (oe >> PAD_CS) & 1,
                "mosi_oe": (oe >> MOSI_LANE) & 1,
                "miso_oe": (oe >> MISO_LANE) & 1,
                "dq7_2_oe": (oe >> 2) & 0x3F,
                "dqs_oe": (oe >> PAD_DQS) & 1,
            }
            want = {
                "sck_oe": 1,
                "cs_oe": 1,
                "mosi_oe": 1 if e["dir"] == TX else got["mosi_oe"],
                "miso_oe": 0,
                "dq7_2_oe": 0,
                "dqs_oe": 0,
            }
            if got != want:
                oe_bad.append((e["n"], e["dir"], got))
        if oe_bad:
            errors.append(
                f"OE: pad output enables wrong at {len(oe_bad)} SCK rises; first "
                f"(rise, dir, enables) {oe_bad[0]}; expected SCK and CS# driven, the receive "
                "lane and lanes 2-7 released, the transmit lane driven on transmit bits"
            )
        if st["cs_high_data_oe"]:
            errors.append(
                f"OE: a data pad is driven while CS# is high on {len(st['cs_high_data_oe'])} "
                f"cycles; first (cycle, lane enables) {st['cs_high_data_oe'][0]}"
            )
        if len(st["edges"]) != EXPECTED_SCK_RISES:
            errors.append(
                f"OE: graded at {len(st['edges'])} pad SCK rises, expected "
                f"{EXPECTED_SCK_RISES}, so the enables of some bits are not graded"
            )
        if st["pre_enable_cycles"] == 0:
            errors.append(
                "OE: no cycle had the SCK and CS# pads released, so the window did not "
                "start before the host enabled its outputs"
            )
        if (
            not oe_bad
            and not st["cs_high_data_oe"]
            and st["pre_enable_cycles"]
            and len(st["edges"]) == EXPECTED_SCK_RISES
        ):
            log(
                "CHK-SEP-SPI-PAD-OE: PASS (%d SCK rises: SCK and CS# driven, receive lane "
                "and lanes 2-7 released, transmit lane driven on all %d transmit bits; no "
                "data pad driven with CS# high; %d cycles with SCK and CS# released before "
                "the host enabled its outputs)",
                len(st["edges"]),
                EDGE_DIRECTIONS.count(TX),
                st["pre_enable_cycles"],
            )

        # MOSI
        tx_bits = [e["mosi"] for e in st["edges"] if e["dir"] == TX]
        mosi = [
            int("".join(map(str, tx_bits[i : i + 8])), 2) for i in range(0, len(tx_bits) - 7, 8)
        ]
        if mosi != EXPECTED_MOSI:
            errors.append(
                f"MOSI: transmit pad bytes {[hex(b) for b in mosi]}, expected the TXDATA "
                f"bytes {[hex(b) for b in EXPECTED_MOSI]}"
            )
        else:
            log(
                "CHK-SEP-SPI-PAD-MOSI: PASS (transmit pad bytes %s == TXDATA bytes)",
                [hex(b) for b in mosi],
            )

        # RSP
        rx_edges = [e for e in st["edges"] if e["dir"] == RX]
        wire = _wire_bits(pattern)
        rsp_bad = [
            (e["n"], wire[i], e["host_miso"], e["driven"])
            for i, e in enumerate(rx_edges)
            if e["host_miso"] != wire[i] or not e["driven"]
        ]
        pops = st["pops"]
        rsp_ok = len(rx_edges) == len(wire) and not rsp_bad
        pop_ok = len(pops) == 1 and pops[0][1] == pattern
        if len(rx_edges) != len(wire):
            errors.append(f"RSP: {len(rx_edges)} receive SCK rises, expected {len(wire)}")
        if rsp_bad:
            errors.append(
                f"RSP: host receive input differs from the driven pad bit at {len(rsp_bad)} "
                f"receive rises; first (rise, driven bit, host bit, device driving) {rsp_bad[0]}"
            )
        if not pop_ok:
            errors.append(
                f"RSP: RX FIFO pops {[(c, hex(v)) for c, v in pops]}, expected one pop of "
                f"the driven pattern 0x{pattern:08x}"
            )
        if rsp_ok and pop_ok:
            log(
                "CHK-SEP-SPI-PAD-RSP: PASS (receive pad pattern 0x%08x reached the host input "
                "on all %d receive rises; RXDATA pop at cycle %d = 0x%08x)",
                pattern,
                len(rx_edges),
                pops[0][0],
                pops[0][1],
            )

        # IDLE
        idle_bad = []
        hc, pc = st["host_changes"], st["pad_changes"]
        if not hc:
            idle_bad.append("the host outputs never moved")
        else:
            pre = hc[0] - st["start"]
            post = st["end"] - hc[-1]
            pre_moves = [c for c in pc if c < hc[0]]
            post_moves = [c for c in pc if c > hc[-1]]
            if pre < MIN_PRE_IDLE_CYCLES:
                idle_bad.append(f"pre-transfer window {pre} cycles < {MIN_PRE_IDLE_CYCLES}")
            if post < POST_IDLE_CYCLES:
                idle_bad.append(f"post-transfer window {post} cycles < {POST_IDLE_CYCLES}")
            if pre_moves or post_moves:
                idle_bad.append(
                    f"pad change with the host idle: before={pre_moves[:4]} after={post_moves[:4]}"
                )
        if st["unmatched_pad_changes"]:
            idle_bad.append(
                f"{len(st['unmatched_pad_changes'])} pad changes on cycles the host did not "
                f"move; first {st['unmatched_pad_changes'][:4]}"
            )
        must_move = tuple(
            f"{vec}[{p}]"
            for vec in ("core2pad", "core2pad_en", "pad2core_en")
            for p in (PAD_SCK, PAD_CS, MOSI_LANE)
        )
        still = [k for k in must_move if not st["pad_moves"].get(k)]
        if still:
            idle_bad.append(f"pad nets the transfer drives never moved: {still}")
        errors.extend(f"IDLE: {msg}" for msg in idle_bad)
        if not idle_bad:
            log(
                "CHK-SEP-SPI-PAD-IDLE: PASS (pre-transfer %d cycles and post-transfer %d "
                "cycles with no pad change; %d pad changes, each on a cycle the host moved; "
                "moves in the transfer: %s)",
                hc[0] - st["start"],
                st["end"] - hc[-1],
                len(pc),
                {k: st["pad_moves"][k] for k in must_move},
            )
        return errors

    # -------------------------------------------------------------------- run
    async def run(self) -> None:
        self._resolve_probes()
        seed = self.test.random_seed()
        pattern = _rsp_pattern(seed)
        self.log.info(
            "%s: receive pattern 0x%08x (RANDOM_SEED=%d); expected SCK rises=%d, "
            "rises per CS# window=%s, TXDATA bytes=%s",
            self.NAME,
            pattern,
            seed,
            EXPECTED_SCK_RISES,
            CS_WINDOW_RISES,
            [hex(b) for b in EXPECTED_MOSI],
        )
        self._drive_miso(0, 0)
        monitor = cocotb.start_soon(self._monitor(_wire_bits(pattern)))
        try:
            await super().run()
        except BaseException:
            monitor.cancel()
            raise
        self._stop_cycle = self._cycle + POST_IDLE_CYCLES
        st = await monitor
        self._drive_miso(0, 0)
        errors = self._grade(st, pattern)
        assert not errors, f"{self.NAME}: " + "; ".join(errors)
        for token in self.PAD_EVIDENCE:
            self._log_evidence(token)
