# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
example_load_elf.py — OcahMemoryImage usage examples.

Demonstrates:
  1. Load a SEP firmware ELF and obtain the plusarg list for the runner.
  2. Load individual banks from OCAH hex files.
  3. Load a raw binary into a specific bank.
  4. Load a bank from an Intel HEX (.ihex) file.
  5. Patch a word before writing plusargs (pre-simulation backdoor).
  6. Runtime backdoor via cocotb hierarchical handle.
  7. Override the memory layout from a custom YAML file.

These snippets are not stand-alone cocotb tests; they illustrate the API
patterns that real tests would follow.  Adapt the paths, bank names, and
handle names for your specific testbench.

Prerequisites
-------------
- pyelftools (for ELF loading): ``pip install pyelftools``
- pyyaml    (for YAML layout):  ``pip install pyyaml``  [optional]
"""

import os
import cocotb
from cocotb.clock import Clock

# Primary import — all three public names are available from the package root.
from ocah_memory_image import (
    OcahMemoryImage,
    SepMemoryLayout,
    MemoryBank,
    backdoor_sim_write,
)


# ---------------------------------------------------------------------------
# Example 1 — Load a SEP firmware ELF and pass plusargs to the runner
# ---------------------------------------------------------------------------

def example_elf_to_plusargs():
    """Show how to convert a firmware ELF into simulator plusargs.

    This is the most common use case: the test receives a path to a compiled
    ELF, loads it, and passes the resulting plusargs to the cocotb runner or
    simulator invocation.

    The loader routes each PT_LOAD segment to the bank whose address window
    covers the segment's physical address.  Typically:
      - .text in boot ROM window  -> +sep_boot_rom_preload=...
      - .data/.bss in SRAM window -> +sep_sram_preload=...
    """
    # Use a run-specific output directory so parallel tests do not clobber
    # each other's hex files.
    run_dir = os.environ.get("SIM_RUN_DIR", "/tmp/sep_sim_run")

    img = OcahMemoryImage(run_dir=run_dir)

    # load_elf() requires pyelftools.
    elf_path = "fw/sep/tests/hello_world/hello_world.elf"
    img.load_elf(elf_path)

    # write_plusargs() writes one hex file per loaded bank and returns the
    # plusarg strings ready for the simulator command line.
    plusargs = img.write_plusargs()

    print("Simulator plusargs:")
    for arg in plusargs:
        print(f"  {arg}")

    # Typical output:
    #   +sep_boot_rom_preload=/tmp/sep_sim_run/sep_boot_rom.hex
    #   +sep_sram_preload=/tmp/sep_sim_run/sep_sram.hex

    return plusargs


# ---------------------------------------------------------------------------
# Example 2 — Load individual banks from OCAH hex files
# ---------------------------------------------------------------------------

def example_load_hex_files():
    """Load banks explicitly from pre-built OCAH hex files.

    Use this when the firmware build system already produces per-bank hex
    files in the Task #9 format (one word per line, MSN first).
    """
    run_dir = "/tmp/sep_sim_run"
    img = OcahMemoryImage(run_dir=run_dir)

    # Load the boot ROM image.
    img.load_hex("sep_boot_rom", "fw/sep/build/sep_boot_rom.hex")

    # Load the SRAM image (optional if firmware executes from boot ROM).
    img.load_hex("sep_sram", "fw/sep/tests/hello_world/hello_world.hex")

    # Load the KM ROM constant tables.
    img.load_hex("km_rom", "hw/comp/key_manager/data/km_rom.hex")

    # Emit plusargs.
    plusargs = img.write_plusargs()
    return plusargs


# ---------------------------------------------------------------------------
# Example 3 — Load a raw binary into a specific bank
# ---------------------------------------------------------------------------

def example_load_bin():
    """Load a raw binary blob into the SRAM bank.

    Useful when the firmware build produces a flat .bin (e.g., from
    ``objcopy -O binary``).  The binary is packed into 64-bit words
    (little-endian) starting at word 0 of the bank.
    """
    run_dir = "/tmp/sep_sim_run"
    img = OcahMemoryImage(run_dir=run_dir)

    # Load a raw binary starting at the beginning of the SRAM bank.
    img.load_bin("sep_sram", "fw/sep/tests/hello_world/hello_world.bin")

    # Load a raw binary with a byte offset into the bank.
    # Here we place it at byte offset 0x1000 within the SRAM bank.
    # img.load_bin("sep_sram", "fw/sep/tests/hello_world/patch.bin", base_offset=0x1000)

    return img.write_plusargs()


# ---------------------------------------------------------------------------
# Example 4 — Load a bank from an Intel HEX (.ihex) file
# ---------------------------------------------------------------------------

def example_load_ihex():
    """Load a bank from an Intel HEX file produced by objcopy.

    ``load_ihex()`` resolves each Intel HEX record's absolute address
    against the bank's base address.  Use this when your toolchain emits
    ``-O ihex`` output.
    """
    run_dir = "/tmp/sep_sim_run"
    img = OcahMemoryImage(run_dir=run_dir)

    # Intel HEX output from: riscv64-unknown-elf-objcopy -O ihex firmware.elf firmware.hex
    img.load_ihex("sep_sram", "fw/sep/tests/hello_world/hello_world_sram.hex")
    img.load_ihex("sep_boot_rom", "fw/sep/build/sep_boot_rom.hex")

    return img.write_plusargs()


# ---------------------------------------------------------------------------
# Example 5 — Patch a word before writing plusargs (pre-simulation backdoor)
# ---------------------------------------------------------------------------

def example_backdoor_patch():
    """Override a single word in the image before emitting plusargs.

    This is the *pre-simulation* backdoor — it modifies the Python-side image
    store before the hex files are written.  Use it to inject test-specific
    configuration values without rebuilding firmware.
    """
    run_dir = "/tmp/sep_sim_run"
    img = OcahMemoryImage(run_dir=run_dir)
    img.load_elf("fw/sep/tests/crypto_test/crypto_test.elf")

    # Patch word 0x100 of the SRAM bank with a test vector.
    # Word address 0x100 == byte address 0x2000_0800 in the default layout.
    img.backdoor_write("sep_sram", addr=0x100, data=0xDEAD_BEEF_CAFE_BABE)

    # The patched value will appear in the emitted sep_sram.hex file.
    return img.write_plusargs()


# ---------------------------------------------------------------------------
# Example 6 — Runtime backdoor via cocotb hierarchical handle
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_runtime_backdoor(dut):
    """Patch a live simulation memory word via a cocotb hierarchical handle.

    ``backdoor_sim_write`` navigates the hierarchical path registered in
    ``_BACKDOOR_HANDLE_MAP`` inside ``ocah_memory_image.py`` and pokes the
    word directly.

    Requirements:
    - The TB must expose the memory backing array under the registered path.
    - Verilator: compile with ``--public-flat-rw``.
    - VCS / Questa: hierarchical force / deposit is typically available by
      default.

    This test assumes the DUT is already in a running state (clock + reset
    have been applied).
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    # Patch word address 5 of the SRAM bank while the simulation is running.
    await backdoor_sim_write(
        dut_handle=dut,
        bank="sep_sram",
        word_addr=5,
        word_data=0xCAFE_BABE_1234_5678,
    )

    cocotb.log.info("example_runtime_backdoor: patched sep_sram[5]")


# ---------------------------------------------------------------------------
# Example 7 — Override the layout from a custom YAML file
# ---------------------------------------------------------------------------

def example_custom_layout():
    """Use a project-specific address map instead of the default SEP layout.

    If your chip uses different memory base addresses or bank depths, create
    a YAML file from the ``example_layout.yaml`` template and load it here.

    Requires PyYAML: ``pip install pyyaml``.
    """
    run_dir = "/tmp/sep_sim_run"

    # Load a custom layout — see examples/example_layout.yaml for the format.
    layout = SepMemoryLayout.from_yaml(
        "hw/common/dv/vip/ocah_memory_image/examples/example_layout.yaml"
    )

    img = OcahMemoryImage(layout=layout, run_dir=run_dir)
    img.load_elf("fw/sep/tests/hello_world/hello_world.elf")
    return img.write_plusargs()


# ---------------------------------------------------------------------------
# Example 8 — Check which banks were populated
# ---------------------------------------------------------------------------

def example_check_loaded_banks():
    """Inspect which banks were populated after loading an ELF."""
    img = OcahMemoryImage(run_dir="/tmp/sep_sim_run")
    img.load_elf("fw/sep/tests/hello_world/hello_world.elf")

    for name in img._layout.banks:
        if img.is_bank_loaded(name):
            content = img.get_bank_content(name)
            non_zero = sum(1 for w in content if w != 0)
            print(f"  {name}: {non_zero} non-zero words loaded")
        else:
            print(f"  {name}: (empty)")
