# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU/OCCP OSS-safe master-BFM VIP helpers."""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

from .smc_pad_table import pad_index

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    CPU_CTRL_RESET_CTRL_REG_DEFAULT,
    CPU_CTRL_RESET_VECTOR_REG_DEFAULT,
    SMC_CPU_CTRL_RESET_CTRL_REG_ADDR,
    SMC_CPU_CTRL_RESET_TIMEOUT_REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_1__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_2__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_3__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_3__REG_ADDR,
)

CPU_CTRL_RESET_VECTOR_0 = SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR
CPU_CTRL_RESET_VECTOR_1 = SMC_CPU_CTRL_RESET_VECTOR_1__REG_ADDR
CPU_CTRL_RESET_VECTOR_2 = SMC_CPU_CTRL_RESET_VECTOR_2__REG_ADDR
CPU_CTRL_RESET_VECTOR_3 = SMC_CPU_CTRL_RESET_VECTOR_3__REG_ADDR
CPU_CTRL_RESET_CTRL = SMC_CPU_CTRL_RESET_CTRL_REG_ADDR
CPU_CTRL_RESET_TIMEOUT = SMC_CPU_CTRL_RESET_TIMEOUT_REG_ADDR
CPU_CTRL_SCRATCH_0 = SMC_CPU_CTRL_SCRATCH_0__REG_ADDR
# SEED_REG in fw/include/smc_test.h, read by init_test() to seed its LFSR.
# Same register smc_occp_dual_defs.py calls SCRATCH_FW_SEED.
SCRATCH_FW_SEED = SMC_CPU_CTRL_SCRATCH_3__REG_ADDR

# Freedom-metal __metal_synchronize_harts uses CLINT MSIP as a barrier.
CLINT_MSIP_0 = 0xC800_0000
CLINT_MSIP_1 = 0xC800_0004
CLINT_MSIP_2 = 0xC800_0008
CLINT_MSIP_3 = 0xC800_000C

# Default RDL reset vector targets ROM window; hello_world links in scratch.
CPU_RESET_VECTOR_ROM = CPU_CTRL_RESET_VECTOR_REG_DEFAULT & 0xFFFF_FFFF
CPU_RESET_VECTOR_SCRATCH = 0xC006_0000

# Matches CPU_CTRL_RESET_CTRL_REG_DEFAULT (cores+uncore released).
CPU_RESET_CTRL_DEFAULT = CPU_CTRL_RESET_CTRL_REG_DEFAULT & 0xFFFF_FFFF
# Hold cores (reset_n=0) while keeping uncore out of reset (bit 8).
CPU_RESET_CTRL_HOLD_CORES = 0x0000_0100
# Pulse-start bits [7:4] for cores 0-3.
CPU_RESET_CTRL_PULSE_ALL = CPU_RESET_CTRL_DEFAULT | 0x0000_00F0  # 0x1FF
# debug_reset_n_n0_scan[24] defaults to 0 (DM held in reset). DMI/dmstatus
# needs this bit set.
CPU_RESET_CTRL_DEBUG_RELEASE = CPU_RESET_CTRL_DEFAULT | (1 << 24)  # 0x0100_010F

# RESET_TIMEOUT: timeout_value[15:0]=32, timeout_mode[16]=1 (force apply).
CPU_RESET_TIMEOUT_FORCE = 0x0001_0020

CPU_FW_SUCCESS_MAGIC = 0xACAF_ACA1
CPU_FW_FAIL_MASK = 0xFFFF_0000
CPU_FW_FAIL_VALUE = 0xBAD0_0000
# TEST_FAIL in fw/include/smc_test.h. test_fail() latches it over any
# 0xBAD0xxxx code the test wrote first, so it is the value most firmware
# failures actually leave behind.
CPU_FW_TEST_FAIL = 0xFFFF_FFFF

# The boot-stall pad, looked up by function in the Integrator Guide's GPIO
# table (doc/integrator/meta/ocah_gpio_table.csv): "Stall after fuse sensing
# ... boot will resume when this GPIO is released". `_release_boot_stall`
# proves the index by requiring the DUT's boot_stall_combined_o to drop when
# the pad is released.
BOOT_STALL_PAD = pad_index("Boot Stall")


# Bound for the post-bring-up observability state this helper claims to observe.
# Every caller runs after reset release, so anything beyond this is a real
# failure of the powergood / reset-release contract rather than slow timing.
CPU_BFM_OBS_TIMEOUT_CYCLES = 2000
# Exact post-bring-up expectation: powergood stable and both observed resets
# released (active-low, so 1). Value-checked, not just logged.
CPU_BFM_OBS_EXPECTED = (
    ("powergood_stable_o", 1),
    ("rst_primary_smc_clk_no", 1),
    ("rst_wdt_smc_clk_no", 1),
)


async def check_cpu_bfm_observability() -> None:
    """Check the reset/powergood signals used by the CPU master-BFM substitute.

    Bounded poll until powergood is stable AND both observed resets are
    released, then assert that exact state. Expiry fails with the last observed
    values (X/Z reported as such, never resolved blindly).
    """
    dut = cocotb.top
    observed: dict[str, int | None] = {}
    for _ in range(CPU_BFM_OBS_TIMEOUT_CYCLES):
        for name, _want in CPU_BFM_OBS_EXPECTED:
            value = getattr(dut, name).value
            observed[name] = int(value) if value.is_resolvable else None
        if all(observed[name] == want for name, want in CPU_BFM_OBS_EXPECTED):
            cocotb.log.info(
                "CHK-CPU-BFM-OBSERVABILITY: powergood_stable_o=%d "
                "rst_primary_smc_clk_no=%d rst_wdt_smc_clk_no=%d "
                "(all resolvable and at their exact post-bring-up levels)",
                observed["powergood_stable_o"],
                observed["rst_primary_smc_clk_no"],
                observed["rst_wdt_smc_clk_no"],
            )
            return
        await ClockCycles(dut.clk_smc_i, 1)
    detail = ", ".join(
        f"{name}={'X/Z' if observed.get(name) is None else observed[name]} (expected {want})"
        for name, want in CPU_BFM_OBS_EXPECTED
    )
    raise AssertionError(
        "CPU BFM observability never reached the post-bring-up state within "
        f"{CPU_BFM_OBS_TIMEOUT_CYCLES} clk_smc_i cycles: {detail}"
    )


# Bound on the pad -> boot_stall_combined_o path after a release (pad shim,
# synchronizer and sticky flop); a release that has not reached the DUT's
# combined output by then means the pad driven was not the boot-stall pad.
BOOT_STALL_RELEASE_BOUND_CYCLES = 64


def _set_boot_stall(asserted: bool) -> None:
    """Drive the boot_stall pad (active-high) via the TB GPIO override."""
    dut = cocotb.top
    assert hasattr(dut, "tb_gpio_ext_drive_en"), (
        "tb_gpio_ext_drive_en is not exported by this bench, so the boot-stall pad cannot "
        "be driven and no boot release below can be believed"
    )
    en = int(dut.tb_gpio_ext_drive_en.value)
    val = int(dut.tb_gpio_ext_drive_value.value)
    mask = 1 << BOOT_STALL_PAD
    if asserted:
        en |= mask
        val |= mask
    else:
        # Explicitly drive 0 so +smc_hold_cpu_boot default cannot re-assert.
        en |= mask
        val &= ~mask
    dut.tb_gpio_ext_drive_en.value = en
    dut.tb_gpio_ext_drive_value.value = val


async def _release_boot_stall() -> None:
    """Release the held boot-stall pad and prove the release reached the DUT.

    Positive control for ``BOOT_STALL_PAD``: with ``+smc_hold_cpu_boot`` the pad
    has held ``boot_stall_combined_o`` high since t=0, and dropping the pad this
    helper names must drop it. A boot that proceeds without that transition was
    never stalled by this pad, and is failed rather than credited.
    """
    dut = cocotb.top
    combined = dut.tb_boot_stall_combined_o.value
    assert combined.is_resolvable and int(combined) == 1, (
        f"boot_stall_combined_o={combined} before the release; +smc_hold_cpu_boot should "
        f"have held it through GPIO_PAD[{BOOT_STALL_PAD}]"
    )
    _set_boot_stall(False)
    for cycle in range(BOOT_STALL_RELEASE_BOUND_CYCLES):
        await ClockCycles(dut.clk_smc_i, 1)
        combined = dut.tb_boot_stall_combined_o.value
        if combined.is_resolvable and int(combined) == 0:
            cocotb.log.info(
                "boot_stall_combined_o 1->0 %d cycle(s) after releasing GPIO_PAD[%d] (Boot Stall)",
                cycle + 1,
                BOOT_STALL_PAD,
            )
            return
    raise AssertionError(
        f"boot_stall_combined_o stayed {combined} for {BOOT_STALL_RELEASE_BOUND_CYCLES} cycles "
        f"after releasing GPIO_PAD[{BOOT_STALL_PAD}]; the released pad is not the boot-stall pad"
    )


def _hold_cpu_boot_plusarg() -> bool:
    return "smc_hold_cpu_boot" in cocotb.plusargs


async def _program_reset_vectors(seq, reset_vector: int) -> None:
    for name, addr in (
        ("RESET_VECTOR_0", CPU_CTRL_RESET_VECTOR_0),
        ("RESET_VECTOR_1", CPU_CTRL_RESET_VECTOR_1),
        ("RESET_VECTOR_2", CPU_CTRL_RESET_VECTOR_2),
        ("RESET_VECTOR_3", CPU_CTRL_RESET_VECTOR_3),
    ):
        await seq.csr_write(f"CPU_BOOT_{name}", addr, reset_vector, length=8)


async def _release_held_cpu_boot(seq, reset_vector: int, *, settle_cycles: int = 64) -> None:
    """First-boot path when +smc_hold_cpu_boot kept tiles in fuse-reset from t=0.

    Cores have never fetched; program vectors, ensure RESET_CTRL is released,
    then drop boot_stall so fuse_reset / mem-init / tile reset release samples
    the scratch (or ROM) vector.

    Note: full Freedom-metal applications can barrier on cluster-local CLINT
    MSIP (0xC800_0000), which SEP-IN AXI cannot reach. The boot contract uses
    the sync-free hello_world C test built by the c_compile stage.
    """
    await seq.csr_write(
        "CPU_BOOT_RESET_TIMEOUT_FORCE",
        CPU_CTRL_RESET_TIMEOUT,
        CPU_RESET_TIMEOUT_FORCE,
        length=8,
    )
    await _program_reset_vectors(seq, reset_vector)
    # All cores must be released: holding any core keeps isolate_req high and
    # clamps MMIO (see smc_4core_cpu cluster_boundary_ready).
    await seq.csr_write(
        "CPU_BOOT_RESET_RELEASE",
        CPU_CTRL_RESET_CTRL,
        CPU_RESET_CTRL_DEFAULT,
        length=8,
    )
    await ClockCycles(cocotb.top.clk_smc_i, settle_cycles)

    await _release_boot_stall()
    await ClockCycles(cocotb.top.clk_smc_i, settle_cycles * 4)
    cocotb.log.info("CPU boot: released +smc_hold_cpu_boot with vector=0x%08x", reset_vector)


async def _pulse_core_reset(seq, reset_vector: int, *, settle_cycles: int = 32) -> None:
    """Re-vector cores with force-apply so drain-withhold cannot stick.

    Rocket Frontend latches RESET_VECTOR only on tile reset. Software HOLD/PULSE
    is gated by drained_i; enable RESET_TIMEOUT.timeout_mode=1 so the reset is
    forced if the cluster never drains.
    """
    await seq.csr_write(
        "CPU_BOOT_RESET_TIMEOUT_FORCE",
        CPU_CTRL_RESET_TIMEOUT,
        CPU_RESET_TIMEOUT_FORCE,
        length=8,
    )

    _set_boot_stall(True)
    await ClockCycles(cocotb.top.clk_smc_i, settle_cycles)

    await _program_reset_vectors(seq, reset_vector)

    await seq.csr_write(
        "CPU_BOOT_HOLD_CORES",
        CPU_CTRL_RESET_CTRL,
        CPU_RESET_CTRL_HOLD_CORES,
        length=8,
    )
    # Wait past timeout_value so force_apply can take the level hold.
    await ClockCycles(cocotb.top.clk_smc_i, 64)

    await seq.csr_write(
        "CPU_BOOT_RESET_PULSE",
        CPU_CTRL_RESET_CTRL,
        CPU_RESET_CTRL_PULSE_ALL,
        length=8,
    )
    await ClockCycles(cocotb.top.clk_smc_i, 64)

    _set_boot_stall(False)
    await ClockCycles(cocotb.top.clk_smc_i, settle_cycles)


async def _compare_image_in_memory(seq, boot_from_scratch: bool, reset_vector: int) -> str:
    """Compare what the DUT holds at the reset vector against the image file.

    Diagnostic, never a verdict: it runs on the failure path to separate "the
    firmware ran and did the wrong thing" from "the firmware that ran is not
    the firmware that was built".

    It reads the *linear* address over SEP_IN AXI and compares against the
    *linear* file at the same offset, so it does not re-implement the bank/entry
    decode internal to smc_cpu_mem_dv.

    A MISMATCH means the AXI view of scratch and the built image disagree, which
    points at the loader: `smc_dual_axi_sram_probe_test` requires the same
    decode to agree with AXI across both stripe bits, the wrap of the four-bank
    cycle and a group boundary, so a decode that is wrong in any of those fields
    fails there first. It stays a report rather than an assertion because it
    only ever runs on a path that is already failing for its own reason.

    The sidecar is `<name>.sram.bin`, staged by [c_build.default] beside the
    .ecc.hex. Returns a report string; any reason it cannot compare is reported
    rather than raised, because the caller is already failing for its own
    reason.
    """
    hex_arg = cocotb.plusargs.get("smc_scratch_ram_hex") or cocotb.plusargs.get("smc_rom_hex")
    if not boot_from_scratch or not hex_arg:
        return "image_check=skipped(not-a-scratch-boot)"
    sidecar = Path(str(hex_arg)).with_suffix("").with_suffix(".sram.bin")
    if not sidecar.is_file():
        return f"image_check=skipped(no-sidecar {sidecar.name})"
    blob = sidecar.read_bytes()

    # Offset 0 is the reset vector, which the CPU demonstrably fetched. The
    # others are the first instruction of _start and of main -- the two places
    # a mis-striped load would first change control flow.
    probes = [0x000, 0x040, 0x210, 0x700]
    parts: list[str] = []
    for off in probes:
        if off + 4 > len(blob):
            continue
        want = int.from_bytes(blob[off : off + 4], "little")
        got = await seq.csr_read(f"IMG_RB_{off:04x}", reset_vector + off, length=4)
        parts.append(
            f"+0x{off:03x}:{'ok' if got == want else f'want=0x{want:08x},got=0x{got:08x}'}"
        )
    verdict = "match" if all(p.endswith(":ok") for p in parts) else "AXI-VS-FILE-DIFFERS"
    return f"image_check={verdict}[" + " ".join(parts) + "]"


async def check_cpu_firmware_boot_contract(
    seq,
    *,
    require_image: bool = False,
    arm_value: int | None = None,
    on_armed: Callable[[], Awaitable[None]] | None = None,
    poll_iterations: int = 2000,
) -> dict[str, int | bool | str]:
    """Check CPU firmware boot when a ROM or scratch image was preloaded.

    ``poll_iterations`` bounds the verdict poll at 100 clk_smc_i cycles each.
    The default suits an image that goes straight to its verdict; raise it for
    one that does real setup first, and put the measured figure in the caller
    rather than picking a round number.

    ``arm_value`` is for images that report twice: once to say "I have set
    myself up and am now waiting for the testbench", then again with the
    verdict. Give it the first word and the poll requires it to appear before
    the pass magic -- an image that jumps straight to PASS has skipped its own
    setup and is failed rather than believed. ``on_armed`` is awaited once, at
    that point, and is where the stimulus the image is waiting for belongs.

    Plusargs:
      * ``+smc_rom_hex=<path>`` — ROM window preload (vector 0xC004_0000)
      * ``+smc_scratch_ram_hex=<path>`` — scratch ECC hex, scattered across the
        32 banks by smc_scratch_map_pkg (vector 0xC006_0000)
      * ``+smc_hold_cpu_boot`` — assert boot_stall from time-0 (preferred for
        scratch)

    Paths must be absolute (or resolvable from the simulator cwd under
    ``attempt_*/make``). If both plusargs are present, scratch wins.
    """
    dut = cocotb.top
    rom_image = cocotb.plusargs.get("smc_rom_hex")
    scratch_image = cocotb.plusargs.get("smc_scratch_ram_hex")
    image_path = scratch_image or rom_image
    boot_from_scratch = scratch_image is not None

    if image_path is None:
        if require_image:
            raise AssertionError(
                "CPU firmware boot requires +smc_rom_hex=<path> or +smc_scratch_ram_hex=<path>"
            )
        return {
            "boot_checked": False,
            "reason": "missing +smc_rom_hex / +smc_scratch_ram_hex preload",
            "rom_reads": int(dut.tb_cpu_rom_read_count.value),
            "scratch_writes": int(dut.tb_cpu_scratch_write_count.value),
        }

    reset_vector = CPU_RESET_VECTOR_SCRATCH if boot_from_scratch else CPU_RESET_VECTOR_ROM
    cocotb.log.info(
        "CPU firmware boot start image=%s source=%s reset_vector=0x%08x expected_magic=0x%08x",
        image_path,
        "scratch" if boot_from_scratch else "rom",
        reset_vector,
        CPU_FW_SUCCESS_MAGIC,
    )

    # CPU_CTRL is decoded off the front port ahead of the cluster, so SEP_IN
    # reaches it whatever the cluster is doing.
    #
    # The verdict is read from CPU_CTRL SCRATCH_0 over SEP_IN, which is where
    # `test_pass()` / `test_fail()` in fw/include/smc_test.h put it:
    # write_scratch() is an MMIO store to SMC_TOP_SMC_CPU_CTRL_SCRATCH, not to
    # the scratch RAM.
    #
    # Clear it and read the clear back. SCRATCH_0 is plain storage that no reset
    # in this sequence touches, so without the read-back a residual value from
    # an earlier test -- TEST_ROM_PASS 0x77777777, or a stale TEST_PASS -- would
    # be indistinguishable from one this run's firmware wrote.
    await seq.csr_write("CPU_BOOT_SCRATCH0_CLEAR", CPU_CTRL_SCRATCH_0, 0)
    await seq.csr_read("CPU_BOOT_SCRATCH0_CLEAR_RB", CPU_CTRL_SCRATCH_0, expected=0)

    # init_test() in fw/include/smc_test.h seeds its LFSR from SCRATCH_3
    # (SEED_REG). Nothing else publishes it, so a firmware test that randomises
    # runs off whatever was left in that register. Publish this run's seed --
    # the same RANDOM_SEED the environment randomisation uses -- so firmware
    # randomisation is reproducible from the testlist seed rather than from
    # residue.
    fw_seed = int(os.environ.get("RANDOM_SEED", "1"), 0) & 0xFFFF_FFFF
    await seq.csr_write("CPU_BOOT_SEED_PUBLISH", SCRATCH_FW_SEED, fw_seed, length=8)
    await seq.csr_read("CPU_BOOT_SEED_RB", SCRATCH_FW_SEED, expected=fw_seed)

    # Capture fetch baselines BEFORE release: the I$ fill can complete
    # during the post-release settle window, so a post-release baseline would
    # make "scratch_reads > baseline" spuriously fail after PASS.
    baseline_rom_reads = int(dut.tb_cpu_rom_read_count.value)
    baseline_scratch_reads = int(dut.tb_cpu_scratch_read_count.value)
    baseline_scratch_writes = int(dut.tb_cpu_scratch_write_count.value)
    cocotb.log.info(
        "CPU boot baselines (pre-release) rom_reads=%d scratch_reads=%d scratch_writes=%d",
        baseline_rom_reads,
        baseline_scratch_reads,
        baseline_scratch_writes,
    )

    if _hold_cpu_boot_plusarg():
        await _release_held_cpu_boot(seq, reset_vector)
    else:
        await _pulse_core_reset(seq, reset_vector)

    last_csr = 0
    armed = arm_value is None
    # The boot image is short; poll the CSR the firmware actually writes.
    #
    # tb_cpu_fw_mailbox is not part of the verdict. It is driven by
    # the FW_MAGIC snoop in models/smc_cpu_mem_dv.sv, which watches the scratch
    # RAM and L1 D-cache *write ports* -- not the CPU_CTRL SCRATCH CSR that
    # test_pass() stores to. So for any image that reports through smc_test.h it
    # never fires, and the dcache half matches any 32-bit window of written data
    # (the snoop steps bit_base across the 144-bit beat), which would grant PASS
    # to a run whose firmware never reported one. It stays wired as
    # observability and is logged below, but it cannot decide the outcome.
    for _ in range(poll_iterations):
        await ClockCycles(dut.clk_smc_i, 100)
        last_csr = await seq.csr_read("CPU_BOOT_SCRATCH0_POLL", CPU_CTRL_SCRATCH_0)
        # Sampled and reported, never used to decide -- see the note above.
        fw_valid = int(dut.tb_cpu_fw_mailbox_valid.value)
        fw_mbox = int(dut.tb_cpu_fw_mailbox.value) if fw_valid else 0
        last_pass = last_csr
        # TEST_FAIL from fw/include/smc_test.h. Without this the fail path is
        # invisible and every firmware failure presents as a poll-bound
        # expiry with no diagnosis.
        if arm_value is not None and not armed and last_pass == arm_value:
            armed = True
            cocotb.log.info(
                "CPU firmware armed: SCRATCH_0=0x%08x. Applying the stimulus it is waiting for.",
                last_pass,
            )
            if on_armed is not None:
                await on_armed()
            continue
        if last_pass == CPU_FW_TEST_FAIL:
            raise AssertionError(
                f"CPU firmware reported TEST_FAIL (SCRATCH_0=0x{last_pass:08x}); "
                f"see the [ERROR] lines and SCRATCH_2 error status in this log "
                f"for the failing check"
            )
        if (last_pass & CPU_FW_FAIL_MASK) == CPU_FW_FAIL_VALUE:
            raise AssertionError(f"CPU firmware reported failure code 0x{last_pass:08x}")
        if last_pass == CPU_FW_SUCCESS_MAGIC:
            # PASS without the arm word having been seen means the image
            # reached its verdict without passing through the state it was
            # supposed to wait in, so the stimulus proved nothing.
            assert armed, (
                f"CPU firmware reached PASS without ever publishing its arm "
                f"word 0x{arm_value:08x}. The verdict did not depend on the "
                f"stimulus this testcase applies."
            )
            rom_reads = int(dut.tb_cpu_rom_read_count.value)
            scratch_reads = int(dut.tb_cpu_scratch_read_count.value)
            scratch_writes = int(dut.tb_cpu_scratch_write_count.value)
            if boot_from_scratch:
                assert scratch_reads > baseline_scratch_reads, (
                    "CPU PASS without scratch fetch evidence: "
                    f"baseline={baseline_scratch_reads} observed={scratch_reads}"
                )
            else:
                assert rom_reads > baseline_rom_reads, (
                    "CPU PASS without ROM fetch evidence: "
                    f"baseline={baseline_rom_reads} observed={rom_reads}"
                )
            return {
                "boot_checked": True,
                "reason": (
                    "firmware pass magic observed (scratch boot)"
                    if boot_from_scratch
                    else "firmware pass magic observed (rom boot)"
                ),
                "rom_reads": rom_reads,
                "scratch_reads": scratch_reads,
                "scratch_writes": scratch_writes,
                "mailbox_csr": last_csr,
                "mailbox_tb": fw_mbox,
                "image": str(image_path),
            }

    rom_reads = int(dut.tb_cpu_rom_read_count.value)
    scratch_reads = int(dut.tb_cpu_scratch_read_count.value)
    scratch_writes = int(dut.tb_cpu_scratch_write_count.value)
    fw_valid = int(dut.tb_cpu_fw_mailbox_valid.value)
    fw_mbox = int(dut.tb_cpu_fw_mailbox.value) if fw_valid else 0
    dc_writes = int(dut.tb_cpu_dcache_write_count.value)
    isolate = int(dut.tb_cpu_cluster_isolate.value)
    # All four harts, because crt0 calls __metal_synchronize_harts before
    # main() on every sram image: hart 0 waiting in that barrier and hart 0
    # never being released are indistinguishable from hart 0's PC alone. A hart
    # still at its reset vector never started; harts stopped at different PCs
    # inside the barrier are a barrier that never completed.
    wb_pcs = [int(getattr(dut, f"tb_cpu_wb_pc{i}").value) for i in range(4)]
    # mcause / mepc separate a trap from a stall. mcause == 0 with mepc == 0 is
    # a core that never trapped; anything else names the cause and the
    # instruction that took it. Read-only probes: see smc_public_scope.vlt.
    causes = [int(getattr(dut, f"tb_cpu_mcause{i}").value) for i in range(4)]
    mepcs = [int(getattr(dut, f"tb_cpu_mepc{i}").value) for i in range(4)]
    trap_report = " ".join(
        f"hart{i}[mcause=0x{c:x} mepc=0x{e:x}]" for i, (c, e) in enumerate(zip(causes, mepcs))
    )
    image_report = await _compare_image_in_memory(seq, boot_from_scratch, reset_vector)
    armed_report = "" if arm_value is None else f" armed={armed}"
    raise AssertionError(
        "CPU firmware boot did not reach PASS magic: "
        f"expected=0x{CPU_FW_SUCCESS_MAGIC:08x} last_csr=0x{last_csr:08x} "
        f"tb_mbox=0x{fw_mbox:08x} "
        f"rom_reads={rom_reads} scratch_reads={scratch_reads} "
        f"scratch_writes={scratch_writes} dcache_writes={dc_writes} "
        + " ".join(f"wb_pc{i}=0x{pc:x}" for i, pc in enumerate(wb_pcs))
        + f" {trap_report}"
        + f" {image_report}"
        + f" isolate={isolate}{armed_report} image={image_path}"
    )
