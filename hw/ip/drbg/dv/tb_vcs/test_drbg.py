# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Cocotb tests and helpers for the DRBG wrapper."""

from typing import List, Tuple

import cocotb
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, RisingEdge

CSRNG_INTR_STATE_OFFSET = 0x00
CSRNG_INTR_ENABLE_OFFSET = 0x04
CSRNG_CTRL_OFFSET = 0x14
CSRNG_CMD_REQ_OFFSET = 0x18
CSRNG_SW_CMD_STS_OFFSET = 0x2C
CSRNG_GENBITS_VLD_OFFSET = 0x30
CSRNG_GENBITS_OFFSET = 0x34
EDN_INTR_ENABLE_OFFSET = 0x04
EDN_CTRL_OFFSET = 0x14
EDN_BOOT_INS_CMD_OFFSET = 0x18
EDN_BOOT_GEN_CMD_OFFSET = 0x1C

AXI_RESP_OKAY = 0b00
AXI_RESP_SLVERR = 0b10
CSRNG_CMD_STS_SUCCESS = 0
CSRNG_FILL_TIMEOUT_WORDS = 64
IDLE_CONTROL_PLANE_CYCLES = 8
E2E_AXIS_TIMEOUT_CYCLES = 128
MUBI4_TRUE = 0x6
CSRNG_ACMD_INS = 0x1
CSRNG_ACMD_GEN = 0x3


def _endpoint_slice(value: int, endpoint: int, width: int = 32) -> int:
    """Extract one endpoint lane from a packed cocotb vector."""
    return (value >> (endpoint * width)) & ((1 << width) - 1)


async def init_dut(dut) -> None:
    """Drive known-idle values on the cocotb-controlled harness signals."""
    dut.rst_ni.value = 0
    dut.entropy_stream_data_i.value = 0
    dut.entropy_stream_vld_i.value = 0
    dut.entropy_axis_tready_i.value = 0
    dut.edn_axis_tready_i.value = 0

    for prefix in ("csrng", "edn"):
        getattr(dut, f"{prefix}_axil_awvalid_i").value = 0
        getattr(dut, f"{prefix}_axil_awaddr_i").value = 0
        getattr(dut, f"{prefix}_axil_awprot_i").value = 0
        getattr(dut, f"{prefix}_axil_wvalid_i").value = 0
        getattr(dut, f"{prefix}_axil_wdata_i").value = 0
        getattr(dut, f"{prefix}_axil_wstrb_i").value = 0
        getattr(dut, f"{prefix}_axil_bready_i").value = 0
        getattr(dut, f"{prefix}_axil_arvalid_i").value = 0
        getattr(dut, f"{prefix}_axil_araddr_i").value = 0
        getattr(dut, f"{prefix}_axil_arprot_i").value = 0
        getattr(dut, f"{prefix}_axil_rready_i").value = 0


async def reset_dut(dut, cycles: int = 6) -> None:
    """Apply the wrapper reset for a fixed number of cycles."""
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_i, 2)


async def pulse_entropy_word(dut, word: int) -> None:
    """Emit one producer-driven entropy pulse."""
    dut.entropy_stream_data_i.value = word & 0xFFFFFFFF
    dut.entropy_stream_vld_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.entropy_stream_vld_i.value = 0
    dut.entropy_stream_data_i.value = 0
    await RisingEdge(dut.clk_i)


async def pulse_edn_endpoint_word(dut, endpoint: int, word: int, fips: int = 1) -> None:
    """Inject one EDN endpoint response word through the flattened harness surface."""
    dut.edn_endpoint_force_i.value = 1 << endpoint
    dut.edn_endpoint_bus_i.value = word << (32 * endpoint)
    dut.edn_endpoint_fips_i.value = fips << endpoint
    dut.edn_endpoint_ack_i.value = 1 << endpoint
    await RisingEdge(dut.clk_i)
    dut.edn_endpoint_ack_i.value = 0
    dut.edn_endpoint_bus_i.value = 0
    dut.edn_endpoint_fips_i.value = 0
    dut.edn_endpoint_force_i.value = 0


async def collect_entropy_axis_words(dut, count: int) -> List[int]:
    """Drain `count` words from the entropy-distribution AXI-Stream."""
    words: List[int] = []
    dut.entropy_axis_tready_i.value = 1
    while len(words) < count:
        await RisingEdge(dut.clk_i)
        if dut.entropy_axis_tvalid_o.value.integer and dut.entropy_axis_tready_i.value.integer:
            words.append(int(dut.entropy_axis_tdata_o.value))
    dut.entropy_axis_tready_i.value = 0
    return words


async def axil64_write(dut, prefix: str, addr: int, data: int, strb: int) -> int:
    """Perform one external 64-bit AXI-Lite write and return `bresp`."""
    getattr(dut, f"{prefix}_axil_bready_i").value = 1

    aw_done = False
    w_done = False
    while not (aw_done and w_done):
        getattr(dut, f"{prefix}_axil_awvalid_i").value = 0 if aw_done else 1
        getattr(dut, f"{prefix}_axil_awaddr_i").value = addr
        getattr(dut, f"{prefix}_axil_awprot_i").value = 0
        getattr(dut, f"{prefix}_axil_wvalid_i").value = 0 if w_done else 1
        getattr(dut, f"{prefix}_axil_wdata_i").value = data
        getattr(dut, f"{prefix}_axil_wstrb_i").value = strb

        await RisingEdge(dut.clk_i)
        aw_done = aw_done or bool(getattr(dut, f"{prefix}_axil_awready_o").value)
        w_done = w_done or bool(getattr(dut, f"{prefix}_axil_wready_o").value)

    getattr(dut, f"{prefix}_axil_awvalid_i").value = 0
    getattr(dut, f"{prefix}_axil_wvalid_i").value = 0

    while True:
        await RisingEdge(dut.clk_i)
        if getattr(dut, f"{prefix}_axil_bvalid_o").value.integer:
            resp = int(getattr(dut, f"{prefix}_axil_bresp_o").value)
            getattr(dut, f"{prefix}_axil_bready_i").value = 0
            return resp


async def axil64_read(dut, prefix: str, addr: int) -> Tuple[int, int]:
    """Perform one external 64-bit AXI-Lite read and return `(rdata, rresp)`."""
    getattr(dut, f"{prefix}_axil_rready_i").value = 1

    while True:
        getattr(dut, f"{prefix}_axil_arvalid_i").value = 1
        getattr(dut, f"{prefix}_axil_araddr_i").value = addr
        getattr(dut, f"{prefix}_axil_arprot_i").value = 0
        await RisingEdge(dut.clk_i)
        if getattr(dut, f"{prefix}_axil_arready_o").value.integer:
            getattr(dut, f"{prefix}_axil_arvalid_i").value = 0
            break

    while True:
        await RisingEdge(dut.clk_i)
        if getattr(dut, f"{prefix}_axil_rvalid_o").value.integer:
            data = int(getattr(dut, f"{prefix}_axil_rdata_o").value)
            resp = int(getattr(dut, f"{prefix}_axil_rresp_o").value)
            getattr(dut, f"{prefix}_axil_rready_i").value = 0
            return data, resp


async def axil32_write(dut, prefix: str, offset: int, value: int) -> int:
    """Write one 32-bit register through the wrapper's 64-bit AXI-Lite surface."""
    lane_hi = bool(offset & 0x4)
    data = (value & 0xFFFF_FFFF) << (32 if lane_hi else 0)
    strb = 0xF0 if lane_hi else 0x0F
    return await axil64_write(dut, prefix, offset, data, strb)


async def axil32_read(dut, prefix: str, offset: int) -> Tuple[int, int]:
    """Read one 32-bit register through the wrapper's 64-bit AXI-Lite surface."""
    data, resp = await axil64_read(dut, prefix, offset)
    value = (data >> 32) & 0xFFFF_FFFF if (offset & 0x4) else data & 0xFFFF_FFFF
    return value, resp


def pack_csrng_cmd(acmd: int, glen: int = 0, clen: int = 0, flags: int = 0) -> int:
    """Pack one CSRNG/EDN command word using the native register layout."""
    return ((glen & 0xFFF) << 12) | ((flags & 0xF) << 8) | ((clen & 0xF) << 4) | (acmd & 0x7)


async def wait_for_endpoint_axis_word(
    dut, endpoint: int = 0, cycles: int = E2E_AXIS_TIMEOUT_CYCLES
) -> int:
    """Wait for one endpoint AXI-Stream word to become visible without consuming it."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
        if _endpoint_slice(int(dut.edn_axis_tvalid_o.value), endpoint, 1):
            assert _endpoint_slice(int(dut.edn_axis_tstrb_o.value), endpoint, 4) == 0xF
            return _endpoint_slice(int(dut.edn_axis_tdata_o.value), endpoint, 32)
    raise AssertionError(f"Timed out waiting for endpoint {endpoint} AXI-Stream data")


async def wait_for_csrng_sw_cmd_ready(dut, cycles: int = E2E_AXIS_TIMEOUT_CYCLES) -> None:
    """Poll the CSRNG software-command ready bit until the SW path can accept a command."""
    for _ in range(cycles):
        sw_cmd_sts, resp = await axil32_read(dut, "csrng", CSRNG_SW_CMD_STS_OFFSET)
        assert resp == AXI_RESP_OKAY
        if (sw_cmd_sts >> 1) & 0x1:
            return
    raise AssertionError("Timed out waiting for CSRNG SW command ready")


async def wait_for_csrng_cmd_done(dut, cycles: int = E2E_AXIS_TIMEOUT_CYCLES) -> None:
    """Wait for one CSRNG software command to complete successfully, then clear the done bit."""
    for _ in range(cycles):
        intr_state, resp = await axil32_read(dut, "csrng", CSRNG_INTR_STATE_OFFSET)
        assert resp == AXI_RESP_OKAY
        if intr_state & 0x1:
            sw_cmd_sts, resp = await axil32_read(dut, "csrng", CSRNG_SW_CMD_STS_OFFSET)
            assert resp == AXI_RESP_OKAY
            assert ((sw_cmd_sts >> 3) & 0x7) == CSRNG_CMD_STS_SUCCESS
            resp = await axil32_write(dut, "csrng", CSRNG_INTR_STATE_OFFSET, 0x1)
            assert resp == AXI_RESP_OKAY
            return
    raise AssertionError("Timed out waiting for CSRNG command completion")


async def read_csrng_genbits_words(
    dut, words: int = 4, cycles: int = E2E_AXIS_TIMEOUT_CYCLES
) -> List[int]:
    """Wait for one software genbits block, then read out its 32-bit words."""
    for _ in range(cycles):
        genbits_vld, resp = await axil32_read(dut, "csrng", CSRNG_GENBITS_VLD_OFFSET)
        assert resp == AXI_RESP_OKAY
        if genbits_vld & 0x1:
            genbits_words: List[int] = []
            for _ in range(words):
                word, resp = await axil32_read(dut, "csrng", CSRNG_GENBITS_OFFSET)
                assert resp == AXI_RESP_OKAY
                genbits_words.append(word)
            return genbits_words
    raise AssertionError("Timed out waiting for CSRNG software genbits")


async def expect_pulse(clk, signal, cycles: int = 8) -> None:
    """Require a one-cycle pulse within a small timeout window."""
    for _ in range(cycles):
        await RisingEdge(clk)
        if signal.value.integer:
            return
    raise AssertionError(f"Timed out waiting for pulse on {signal._name}")


async def expect_idle_control_plane(dut, cycles: int = IDLE_CONTROL_PLANE_CYCLES) -> None:
    """Require both wrapper AXI-Lite control paths to stay idle for a short window."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
        assert int(dut.csrng_tl_a_valid_o.value) == 0
        assert int(dut.edn_tl_a_valid_o.value) == 0


@cocotb.test()
async def test_entropy_to_csrng_software_path(dut):
    """Use CSRNG software commands while the wrapper still provides the entropy seed material."""
    await init_dut(dut)
    await reset_dut(dut)

    ingress_depth = int(dut.u_dut.INGRESS_FIFO_DEPTH.value)
    dist_words = [0x7100 + i for i in range(ingress_depth)]
    seed_words = [0xB500_0000 + i for i in range(12)]
    csrng_ctrl = (MUBI4_TRUE << 4) | MUBI4_TRUE

    resp = await axil32_write(dut, "csrng", CSRNG_CTRL_OFFSET, csrng_ctrl)
    assert resp == AXI_RESP_OKAY
    readback, resp = await axil32_read(dut, "csrng", CSRNG_CTRL_OFFSET)
    assert resp == AXI_RESP_OKAY
    assert readback & 0xFF == csrng_ctrl

    seed_push_task = cocotb.start_soon(expect_pulse(dut.clk_i, dut.seed_push_pulse_o, cycles=64))

    for word in dist_words:
        await pulse_entropy_word(dut, word)

    for word in seed_words:
        await pulse_entropy_word(dut, word)

    await seed_push_task

    await wait_for_csrng_sw_cmd_ready(dut)
    resp = await axil32_write(dut, "csrng", CSRNG_CMD_REQ_OFFSET, pack_csrng_cmd(CSRNG_ACMD_INS))
    assert resp == AXI_RESP_OKAY
    await wait_for_csrng_cmd_done(dut)

    await wait_for_csrng_sw_cmd_ready(dut)
    resp = await axil32_write(
        dut, "csrng", CSRNG_CMD_REQ_OFFSET, pack_csrng_cmd(CSRNG_ACMD_GEN, glen=1)
    )
    assert resp == AXI_RESP_OKAY
    genbits_words = await read_csrng_genbits_words(dut)
    await wait_for_csrng_cmd_done(dut)

    assert len(genbits_words) == 4
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        assert int(dut.edn_axis_tvalid_o.value) == 0

    drained = await collect_entropy_axis_words(dut, ingress_depth)
    assert drained == dist_words


@cocotb.test()
async def test_entropy_to_edn_end_to_end(dut):
    """Configure CSRNG and EDN, feed wrapper entropy, and observe real endpoint output."""
    await init_dut(dut)
    await reset_dut(dut)

    ingress_depth = int(dut.u_dut.INGRESS_FIFO_DEPTH.value)
    dist_words = [0x7000 + i for i in range(ingress_depth)]
    seed_words = [0xA500_0000 + i for i in range(12)]

    csrng_ctrl = (MUBI4_TRUE << 4) | MUBI4_TRUE
    edn_ctrl = (MUBI4_TRUE << 4) | MUBI4_TRUE

    resp = await axil32_write(dut, "csrng", CSRNG_CTRL_OFFSET, csrng_ctrl)
    assert resp == AXI_RESP_OKAY
    readback, resp = await axil32_read(dut, "csrng", CSRNG_CTRL_OFFSET)
    assert resp == AXI_RESP_OKAY
    assert readback & 0xFF == csrng_ctrl

    resp = await axil32_write(dut, "edn", EDN_BOOT_INS_CMD_OFFSET, pack_csrng_cmd(CSRNG_ACMD_INS))
    assert resp == AXI_RESP_OKAY
    resp = await axil32_write(
        dut, "edn", EDN_BOOT_GEN_CMD_OFFSET, pack_csrng_cmd(CSRNG_ACMD_GEN, glen=1)
    )
    assert resp == AXI_RESP_OKAY
    resp = await axil32_write(dut, "edn", EDN_CTRL_OFFSET, edn_ctrl)
    assert resp == AXI_RESP_OKAY
    readback, resp = await axil32_read(dut, "edn", EDN_CTRL_OFFSET)
    assert resp == AXI_RESP_OKAY
    assert readback & 0xFF == edn_ctrl

    seed_push_task = cocotb.start_soon(expect_pulse(dut.clk_i, dut.seed_push_pulse_o, cycles=64))

    for word in dist_words:
        await pulse_entropy_word(dut, word)

    for word in seed_words:
        await pulse_entropy_word(dut, word)

    await seed_push_task

    assert int(dut.edn_endpoint_force_i.value) == 0
    endpoint_word = await wait_for_endpoint_axis_word(dut, endpoint=0)
    endpoint_count = int(dut.u_dut.EDN_ENDPOINT_COUNT.value)
    endpoint_depth_width = len(dut.endpoint_fifo_depth_o.value) // endpoint_count
    assert _endpoint_slice(int(dut.endpoint_fifo_depth_o.value), 0, endpoint_depth_width) > 0

    drained = await collect_entropy_axis_words(dut, ingress_depth)
    assert drained == dist_words


@cocotb.test()
async def test_parameterized_smoke(dut):
    """Sanity-check the elaborated wrapper parameters and basic idle behavior."""
    await init_dut(dut)
    await reset_dut(dut)

    assert int(dut.u_dut.INGRESS_FIFO_DEPTH.value) > 0
    assert int(dut.u_dut.SEED_FIFO_DEPTH.value) > 0
    assert int(dut.u_dut.EDN_ENDPOINT_COUNT.value) > 0
    assert int(dut.u_dut.ENDPOINT_FIFO_DEPTH.value) > 0
    assert int(dut.entropy_axis_tvalid_o.value) == 0
    assert int(dut.seed_queue_valid_o.value) == 0


@cocotb.test()
async def test_entropy_routing_priority(dut):
    """Verify distribution-first routing, CSRNG fallback, drop-on-full, and output ordering."""
    await init_dut(dut)
    await reset_dut(dut)

    ingress_depth = int(dut.u_dut.INGRESS_FIFO_DEPTH.value)
    dut.entropy_axis_tready_i.value = 0

    dist_words = [0x1000 + i for i in range(ingress_depth)]
    for word in dist_words:
        pulse_task = cocotb.start_soon(pulse_entropy_word(dut, word))
        await expect_pulse(dut.clk_i, dut.route_distribution_pulse_o)
        await pulse_task

    assert int(dut.distribution_fifo_full_o.value) == 1

    csrng_words = []
    while not dut.csrng_fifo_full_o.value.integer:
        word = 0x2000 + len(csrng_words)
        pulse_task = cocotb.start_soon(pulse_entropy_word(dut, word))
        await expect_pulse(dut.clk_i, dut.route_csrng_pulse_o)
        await pulse_task
        csrng_words.append(word)

        if len(csrng_words) > CSRNG_FILL_TIMEOUT_WORDS:
            raise AssertionError("Timed out waiting for the CSRNG ingress FIFO to fill")

    assert int(dut.csrng_fifo_full_o.value) == 1

    pulse_task = cocotb.start_soon(pulse_entropy_word(dut, 0xDEAD_BEEF))
    await expect_pulse(dut.clk_i, dut.route_drop_pulse_o)
    await pulse_task

    drained = await collect_entropy_axis_words(dut, ingress_depth)
    assert drained == dist_words


@cocotb.test()
async def test_seed_packing_and_fips(dut):
    """Verify 12-word packing order, provisional `es_fips=1`, and queue pop behavior."""
    await init_dut(dut)
    await reset_dut(dut)

    ingress_depth = int(dut.u_dut.INGRESS_FIFO_DEPTH.value)
    dut.entropy_axis_tready_i.value = 0

    for i in range(ingress_depth):
        await pulse_entropy_word(dut, 0x3000 + i)

    seed_words = [0xA500_0000 + i for i in range(12)]
    for word in seed_words:
        await pulse_entropy_word(dut, word)

    for _ in range(8):
        await RisingEdge(dut.clk_i)
        if dut.seed_queue_valid_o.value.integer:
            break

    assert int(dut.seed_queue_valid_o.value) == 1
    assert int(dut.seed_queue_fips_o.value) == 1

    seed_bits = int(dut.seed_queue_bits_o.value)
    unpacked = [(seed_bits >> (32 * i)) & 0xFFFF_FFFF for i in range(12)]
    assert unpacked == seed_words

    dut.u_dut.csrng_entropy_req.es_req.value = Force(1)
    await RisingEdge(dut.clk_i)
    dut.u_dut.csrng_entropy_req.es_req.value = Release()
    await RisingEdge(dut.clk_i)

    assert int(dut.seed_queue_valid_o.value) == 0


@cocotb.test()
async def test_nondefault_seed_queue_depth(dut):
    """Verify multi-seed queueing when the elaborated seed FIFO depth exceeds one."""
    await init_dut(dut)
    await reset_dut(dut)

    if int(dut.u_dut.SEED_FIFO_DEPTH.value) <= 1:
        return

    ingress_depth = int(dut.u_dut.INGRESS_FIFO_DEPTH.value)
    for i in range(ingress_depth):
        await pulse_entropy_word(dut, 0x4000 + i)

    for i in range(24):
        await pulse_entropy_word(dut, 0x5000 + i)

    for _ in range(16):
        await RisingEdge(dut.clk_i)
        if int(dut.seed_queue_depth_o.value) == 2:
            break

    assert int(dut.seed_queue_depth_o.value) == 2
    assert int(dut.seed_queue_valid_o.value) == 1

    dut.u_dut.csrng_entropy_req.es_req.value = Force(1)
    await RisingEdge(dut.clk_i)
    dut.u_dut.csrng_entropy_req.es_req.value = Release()
    await RisingEdge(dut.clk_i)

    assert int(dut.seed_queue_depth_o.value) == 1


@cocotb.test()
async def test_edn_axis_endpoint_buffering(dut):
    """Verify endpoint buffering, `tstrb=4'hF`, and that EDN FIPS does not affect the stream."""
    await init_dut(dut)
    await reset_dut(dut)

    dut.edn_axis_tready_i.value = 0
    await pulse_edn_endpoint_word(dut, endpoint=0, word=0xCAFEBABE, fips=0)

    for _ in range(4):
        await RisingEdge(dut.clk_i)
        if dut.edn_axis_tvalid_o.value.integer:
            break

    assert _endpoint_slice(int(dut.edn_axis_tvalid_o.value), 0, 1) == 1
    assert _endpoint_slice(int(dut.edn_axis_tdata_o.value), 0, 32) == 0xCAFEBABE
    assert _endpoint_slice(int(dut.edn_axis_tstrb_o.value), 0, 4) == 0xF


@cocotb.test()
async def test_multi_endpoint_backpressure_isolation(dut):
    """Verify multi-endpoint isolation and per-endpoint FIFO depth under non-default elaboration."""
    await init_dut(dut)
    await reset_dut(dut)

    endpoint_count = int(dut.u_dut.EDN_ENDPOINT_COUNT.value)
    if endpoint_count < 2:
        return

    endpoint_fifo_depth = int(dut.u_dut.ENDPOINT_FIFO_DEPTH.value)
    endpoint_depth_width = len(dut.endpoint_fifo_depth_o.value) // endpoint_count

    dut.edn_axis_tready_i.value = 0b10

    for i in range(endpoint_fifo_depth):
        await pulse_edn_endpoint_word(dut, endpoint=0, word=0x6000 + i)

    assert _endpoint_slice(int(dut.endpoint_fifo_full_o.value), 0, 1) == 1
    assert _endpoint_slice(int(dut.endpoint_fifo_depth_o.value), 0, endpoint_depth_width) == (
        endpoint_fifo_depth
    )
    assert _endpoint_slice(int(dut.edn_req_valid_o.value), 0, 1) == 0
    assert _endpoint_slice(int(dut.edn_req_valid_o.value), 1, 1) == 1

    await pulse_edn_endpoint_word(dut, endpoint=1, word=0xDEADBEEF)

    for _ in range(4):
        await RisingEdge(dut.clk_i)
        if _endpoint_slice(int(dut.edn_axis_tvalid_o.value), 1, 1):
            break

    assert _endpoint_slice(int(dut.edn_axis_tdata_o.value), 1, 32) == 0xDEADBEEF
    assert _endpoint_slice(int(dut.edn_axis_tstrb_o.value), 1, 4) == 0xF
    assert _endpoint_slice(int(dut.endpoint_fifo_full_o.value), 0, 1) == 1


@cocotb.test()
async def test_csrng_axil_lane_filtering(dut):
    """Verify supported single-lane CSRNG accesses and SLVERR on unsupported ones."""
    await init_dut(dut)
    await reset_dut(dut)

    resp = await axil64_write(dut, "csrng", CSRNG_INTR_ENABLE_OFFSET, 0x0000_0001 << 32, 0xF0)
    assert resp == AXI_RESP_OKAY

    rdata, resp = await axil64_read(dut, "csrng", CSRNG_INTR_ENABLE_OFFSET)
    assert resp == AXI_RESP_OKAY
    assert (rdata >> 32) & 0xFFFF_FFFF == 0x0000_0001

    write_task = cocotb.start_soon(
        axil64_write(dut, "csrng", CSRNG_INTR_ENABLE_OFFSET, 0xFFFF_FFFF_FFFF_FFFF, 0xFF)
    )
    await expect_pulse(dut.clk_i, dut.csrng_unsupported_access_pulse_o)
    resp = await write_task
    assert resp == AXI_RESP_SLVERR

    _, resp = await axil64_read(dut, "csrng", CSRNG_INTR_ENABLE_OFFSET + 2)
    assert resp == AXI_RESP_SLVERR


@cocotb.test()
async def test_control_plane_idle_and_passthrough(dut):
    """Verify idle control behavior plus OTP, lifecycle, interrupt, and alert passthrough."""
    await init_dut(dut)
    await reset_dut(dut)

    await expect_idle_control_plane(dut)

    dut.otp_en_csrng_sw_app_read_i.value = 0x69
    dut.lc_hw_debug_en_i.value = 0x5
    await RisingEdge(dut.clk_i)

    assert int(dut.u_dut.u_csrng.otp_en_csrng_sw_app_read_i.value) == 0x69
    assert int(dut.u_dut.u_csrng.lc_hw_debug_en_i.value) == 0x5

    for _ in range(4):
        await RisingEdge(dut.clk_i)
        assert int(dut.intr_cs_cmd_req_done_o.value) == int(
            dut.u_dut.u_csrng.intr_cs_cmd_req_done_o.value
        )
        assert int(dut.intr_cs_entropy_req_o.value) == int(
            dut.u_dut.u_csrng.intr_cs_entropy_req_o.value
        )
        assert int(dut.intr_cs_hw_inst_exc_o.value) == int(
            dut.u_dut.u_csrng.intr_cs_hw_inst_exc_o.value
        )
        assert int(dut.intr_cs_fatal_err_o.value) == int(
            dut.u_dut.u_csrng.intr_cs_fatal_err_o.value
        )
        assert int(dut.intr_edn_cmd_req_done_o.value) == int(
            dut.u_dut.u_edn.intr_edn_cmd_req_done_o.value
        )
        assert int(dut.intr_edn_fatal_err_o.value) == int(
            dut.u_dut.u_edn.intr_edn_fatal_err_o.value
        )
        assert int(dut.csrng_alert_p_o.value) == int(dut.csrng_inner_alert_p_o.value)
        assert int(dut.csrng_alert_n_o.value) == int(dut.csrng_inner_alert_n_o.value)
        assert int(dut.edn_alert_p_o.value) == int(dut.edn_inner_alert_p_o.value)
        assert int(dut.edn_alert_n_o.value) == int(dut.edn_inner_alert_n_o.value)


@cocotb.test()
async def test_edn_axil_lane_filtering(dut):
    """Verify supported single-lane EDN accesses and SLVERR on unsupported ones."""
    await init_dut(dut)
    await reset_dut(dut)

    resp = await axil64_write(dut, "edn", EDN_INTR_ENABLE_OFFSET, 0x0000_0001 << 32, 0xF0)
    assert resp == AXI_RESP_OKAY

    rdata, resp = await axil64_read(dut, "edn", EDN_INTR_ENABLE_OFFSET)
    assert resp == AXI_RESP_OKAY
    assert (rdata >> 32) & 0xFFFF_FFFF == 0x0000_0001

    write_task = cocotb.start_soon(
        axil64_write(dut, "edn", EDN_INTR_ENABLE_OFFSET, 0xFFFF_FFFF_FFFF_FFFF, 0xFF)
    )
    await expect_pulse(dut.clk_i, dut.edn_unsupported_access_pulse_o)
    resp = await write_task
    assert resp == AXI_RESP_SLVERR

    _, resp = await axil64_read(dut, "edn", EDN_INTR_ENABLE_OFFSET + 2)
    assert resp == AXI_RESP_SLVERR
