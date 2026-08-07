# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# key_manager DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw TARGET=key_manager
FW_NAME := key_manager
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FW_DIR)/../../../../common/dv/fw/preamble.mk

# Runtime driver/startup sources: the library holds no entry point. Each image
# supplies its own main() and links against libkey_manager.a — a DV test from
# tests/, or the production entry from production/rom_main.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)

# Register headers: KM uses only its own generated headers (no umbrella), so
# FW_REG_SYS is left unset.
FW_REGS_GEN := $(OCAH_ROOT)/hw/ip/key_manager/regs/gen/c
# tests/common carries DV-only helper headers (test_common.h, vuart.h, vectors).
FW_INCLUDES := \
  -I$(FW_DIR)/include -I$(FW_REGS_GEN) -I$(FW_DIR)/tests/common

# Test discovery is unified in compile.mk; declare only the KM deltas.
# The eFuse controller sits in the KM address map, so tests that check its status
# fields take those from the eFuse IP's own collateral: KM's umbrella header also
# carries them, but it redeclares the per-block types the drivers already include.
FW_TEST_INCLUDES := -I$(FW_DIR)/tests/common -I$(OCAH_ROOT)/hw/ip/efuse/regs/gen/c

# Images built beside the cocotb tests but never run by them. Both are separate
# roots rather than tests/ entries because the regression enumerates
# dv/fw/tests/test_* directly, and neither ends on its own: production/ is the
# real ROM entry (rom_main), which loops forever serving the mailbox, and
# sep_images/ holds KM ROM images that need a live SEP host to drive or drain
# them. The SEP UVM testbench loads all of them via +KM_ROM_HEX_FILE.
FW_TEST_ROOTS := $(FW_DIR)/tests $(FW_DIR)/sep_images $(FW_DIR)/production
KM_ROM_IMAGES := $(sort $(notdir $(patsubst %/,%,$(dir \
  $(wildcard $(FW_DIR)/sep_images/*/*.c $(FW_DIR)/production/*/*.c)))))

# Link modes are auto-discovered from link/modes/*.ld. vrom is the default; the
# SEP UVM loads only the physical KM ROM with no VROM behind it, and the
# production image has none by definition, so both link all-in-ROM instead.
FW_DEFAULT_TEST_MODE := vrom
$(foreach t,$(KM_ROM_IMAGES),$(eval FW_TEST_MODE_$(t) := rom))

FW_TEST_LDFLAGS = \
  $(FW_LDFLAGS) -Wl,--defsym=__rom_max_stack=0x600
# ROM-linked images may relax: the long-jump relaxations -mno-relax guards
# against apply to the VROM split, where .text sits 256 MB from the vectors.
FW_TEST_LDFLAGS_rom = $(filter-out -mno-relax,$(FW_TEST_LDFLAGS))
FW_TEST_ARCHIVE_LINK = "$(FW_ARCHIVE)"

# rom_isr.c is named per test instead of coming from the archive: nothing calls
# its rom_irq(), which overrides the weak stub in crt0.s, so the on-demand link
# above would extract it only incidentally and otherwise leave faults unserviced
# without a build error. The tests below install their own rom_irq() and must not
# link it.
KM_ISR_SRC := $(FW_DIR)/drivers/rom_isr.c
KM_OWN_ISR_TESTS := \
  test_abr_sharedkey_irq \
  test_cpu_interrupts \
  test_irq_entry_default \
  test_irq_entry_program \
  test_kmcsr_irq \
  test_rom_write_irq

FW_C_SRCS := $(filter-out $(KM_ISR_SRC),$(FW_C_SRCS))
KM_TEST_NAMES := $(filter-out common, \
  $(sort $(notdir $(patsubst %/,%,$(dir $(foreach r,$(FW_TEST_ROOTS),$(wildcard $(r)/*/*.c)))))))
$(foreach t,$(filter-out $(KM_OWN_ISR_TESTS),$(KM_TEST_NAMES)), \
  $(eval FW_TEST_EXTRA_SRCS_$(t) += $(KM_ISR_SRC)))

# ROM hex contents follow the link mode ($(3)): a vrom image boots from ROM and
# runs from side-loaded VROM, so ROM carries only the vectors; a rom image has no
# VROM behind it and must ship whole.
KM_ROM_HEX_SECTIONS_vrom := \
  --only-section=.text.reset --only-section=.text.irq_vec --only-section=.text.irq_handler
KM_ROM_HEX_SECTIONS_rom := $(KM_ROM_HEX_SECTIONS_vrom) \
  --only-section=.text --only-section=.rodata --only-section=.data

# The SEP UVM resolves firmware symbols (e.g. the payload buffer it checks for
# key residue) from "<name>.sym" beside the hex it was given, so a rom image also
# emits the mode-free name the engine's "<name>.<mode>.sym" does not cover.
define FW_TEST_POSTPROCESS
	$(OBJCOPY) -O verilog $(1) $(KM_ROM_HEX_SECTIONS_$(3)) \
	  --change-addresses "-0x00000000" "$(4).rom.hex"
	python3 "$(FW_DIR)/scripts/add_rom_parity.py" "$(4).rom.hex" "$(4).rom.parhex"
	$(if $(filter rom,$(3)),$(NM) -B -n $(1) > "$(4).sym")
	$(if $(filter-out rom,$(3)),$(OBJCOPY) -O verilog $(1) \
	  --only-section=.text --only-section=.text.alt_irq --only-section=.rodata --only-section=.data \
	  --change-addresses "-0x10000000" "$(4).vrom.hex")
endef

# Default artifact: libkey_manager.a. A linked ELF/hex additionally requires
# FW_LINKER_SCRIPT and FW_ENTRY_SRCS (a DV/production entry providing main()).

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
