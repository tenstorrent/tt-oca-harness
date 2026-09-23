# SPDX-License-Identifier: Apache-2.0

GCC_PREFIX ?= riscv64-unknown-elf
RISCV_CC ?= $(GCC_PREFIX)-gcc
RISCV_OBJCOPY ?= $(GCC_PREFIX)-objcopy
PYTHON ?= python3

OUT_DIR := ..
ROMS := km_rom km_rom_entropy km_rom_coexist km_rom_vault km_rom_crc \
        km_rom_kpv_scrambler km_rom_iso

# The KM PicoRV32 is built with ENABLE_REGS_16_31=0, so an image that runs on
# it must be assembled for RV32E and may use x0-x15 only. Images that only feed
# the tb keep the wider base ISA.
RV32E_ROMS := km_rom_vault km_rom_crc km_rom_kpv_scrambler km_rom_iso
ARCH_FLAGS = -march=rv32i -mabi=ilp32
$(addprefix $(OUT_DIR)/,$(addsuffix .parhex,$(RV32E_ROMS))): \
        ARCH_FLAGS := -march=rv32e -mabi=ilp32e
PARHEX := $(addprefix $(OUT_DIR)/,$(addsuffix .parhex,$(ROMS)))

.PHONY: all clean rom_main verify

all: $(PARHEX)

# verify: the committed .parhex blobs still match what their .S assembles to.
#
# These images are committed artifacts, and no run_dv stage rebuilds them --
# a test boots the blob through `+km_rom_hex=<name>.parhex`, not through a
# `firmware = {...}` build declaration. So an edit to a .S reaches no
# simulation until somebody runs `make`, and the run that follows quietly
# executes the OLD image while a reader sees the NEW source.
#
# NOTHING RUNS THIS AUTOMATICALLY. No stage, testlist or CI job invokes it, so
# it does not by itself prevent the drift above -- it only lets you detect it.
# Run it after editing any .S, and commit the regenerated blob with the source
# change. It needs the RISC-V toolchain on PATH; without it every image reports BUILD FAILED, which is why a failed
# build is a distinct token from a mismatch.
#
# It rebuilds into a scratch OUT_DIR and never writes the tracked blob: the
# recipe redirects gen_parhex.py output at its target, so building at the
# tracked path would truncate the committed artifact before python ran, and a
# reported mismatch would leave the rebuild in the tree -- self-clearing on the
# next run and booting an uncommitted image in the meantime.
verify:
	@rc=0; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	for r in $(ROMS); do \
	    if [ ! -f $(OUT_DIR)/$$r.parhex ]; then \
	        echo "MISSING  $$r.parhex is not committed" >&2; rc=1; continue; \
	    fi; \
	    if ! $(MAKE) --no-print-directory OUT_DIR=$$tmp $$tmp/$$r.parhex \
	            >$$tmp/$$r.log 2>&1; then \
	        echo "BUILD FAILED  $$r ($$(tail -n1 $$tmp/$$r.log))" >&2; rc=1; continue; \
	    fi; \
	    if cmp -s $$tmp/$$r.parhex $(OUT_DIR)/$$r.parhex; then \
	        echo "ok       $$r.parhex"; \
	    else \
	        echo "STALE    $$r.parhex does not match $$r.S -- rebuild with" \
	             "\`make $$r.parhex\` and commit it" >&2; \
	        rc=1; \
	    fi; \
	done; \
	if [ $$rc -ne 0 ]; then echo "verify: FAILED" >&2; else echo "verify: all $(words $(ROMS)) blobs match their source"; fi; \
	exit $$rc

# rom_main: the real KM production ROM, built from tracked KM firmware source.
# PROD_BOOT_WIPE=0 / PROD_UNREC_WIPE=0 disable the boot/unrecoverable-fault SRAM
# shred so rom_main's SRAM-scrambler cold-boot does not trip a parity fault --
# matching the OCAH subsystem tb. The output is gitignored (not a committed blob).
# SEP DV tests that boot this image declare
# `firmware = { name = "rom_main", mode = "km_rom_main" }` so run_dv.py
# c_compile drives this target. Requires the rv32emc/ilp32e toolchain on PATH.
#
# The firmware is in-tree at hw/ip/key_manager/dv/fw and builds through the shared
# DV firmware engine, the same one SEP's own firmware uses; the entry point is
# production/rom_main and the engine's parity step emits rom_main.rom.parhex.
OCH_ROOT ?= $(abspath $(CURDIR)/../../../../../../..)
KM_FW_DIR := $(OCH_ROOT)/hw/ip/key_manager/dv/fw
KM_ROM_BUILT := $(KM_FW_DIR)/build/tests/rom_main/rom_main.rom.parhex

# The wipe knobs are COMPILE-TIME DEFINES, not make variables. Upstream's KM tb
# Makefile maps PROD_BOOT_WIPE/PROD_UNREC_WIPE onto them, but the shared DV
# firmware engine has no such mapping -- passing PROD_* here is silently ignored
# and drivers/rom_boot.c falls back to its `#ifndef` defaults of 1 (wipe ENABLED).
# A rom_main built that way performs the production boot wipe and HALTS before
# posting RESP_KM_READY.
#
# rom_boot.c is a DRIVER, not a test source, so the define must ride
# FW_EXTRA_CFLAGS (compile.mk applies it to the driver rule);
# FW_TEST_EXTRA_CFLAGS is test-only and would not reach it.
ROM_MAIN_WIPE_DEFINES := -DROM_KM_BOOT_WIPE_DEFAULT=0 -DROM_KM_UNREC_WIPE_DEFAULT=0

# The defines above are COMPILE flags, and compile.mk's dependency tracking
# (-MMD -MP) records HEADER dependencies only -- it cannot see a CFLAGS change.
# So an object left over from a build that did not pass them would be silently
# reused, re-enabling the boot wipe and leaving the KM CPU dead.
#
# The object that carries these defines is NOT under build/tests/. rom_boot.c is
# a DRIVER, and compile.mk:118 places driver objects FLAT in $(FW_BUILD_DIR)
# via $(addprefix $(FW_BUILD_DIR)/,$(notdir ...)), while tests go to
# $(FW_BUILD_DIR)/tests (compile.mk:127). So the stale artifacts are
#     $(KM_FW_DIR)/build/rom_boot.o
#     $(KM_FW_DIR)/build/libkey_manager.a
# which are SIBLINGS of build/tests/rom_main -- wiping only the test directory
# leaves them untouched and they get re-linked verbatim. Wipe the whole build
# tree instead; it only happens when the defines actually change.
# The stamp lives outside $(KM_FW_DIR)/build: the guard below wipes that whole
# tree and would delete a stamp stored there.
ROM_MAIN_STAMP := $(OUT_DIR)/.km_rom_wipe_defines
.PHONY: rom_main_stamp
rom_main_stamp:
	@mkdir -p $(dir $(ROM_MAIN_STAMP))
	@if [ "$$(cat $(ROM_MAIN_STAMP) 2>/dev/null)" != "$(ROM_MAIN_WIPE_DEFINES)" ]; then \
	    echo "[km_fw] wipe defines changed -> rebuilding KM firmware from scratch"; \
	    rm -rf $(KM_FW_DIR)/build; \
	fi

rom_main: rom_main_stamp
	$(MAKE) -C $(KM_FW_DIR) -f fw.mk dv-fw-tests TEST=rom_main \
	    OCAH_ROOT=$(OCH_ROOT) FW_EXTRA_CFLAGS="$(ROM_MAIN_WIPE_DEFINES)"
	@mkdir -p $(dir $(ROM_MAIN_STAMP))
	@printf '%s' "$(ROM_MAIN_WIPE_DEFINES)" > $(ROM_MAIN_STAMP)
	cp $(KM_ROM_BUILT) $(OUT_DIR)/rom_main.rom.parhex
	@echo "[km_fw] staged rom_main.rom.parhex -> $(OUT_DIR)/rom_main.rom.parhex"

# The images take their KM register addresses from the generated map rather
# than hand-typed literals: .S files run through the C preprocessor, so the
# PeakRDL raw-header is includable directly and a moved register becomes a
# build error instead of a silently stale constant.
KM_REG_INC := $(OCH_ROOT)/hw/ip/key_manager/regs/gen/c

# Field MASKS live in km_csr.h / km_kpv.h, C headers of structs and
# static_asserts an .S cannot include. This target lifts the plain #define
# lines an image needs into an assembler-safe include, so a field that moves
# at the next RDL regeneration changes the mask instead of leaving a
# hand-typed literal behind. The grep is the trace: if a name disappears,
# the build fails here.
KM_CSR_H := $(KM_REG_INC)/km_csr.h
KM_KPV_H := $(KM_REG_INC)/km_kpv.h
KM_FIELD_INC := km_fields.inc
KM_CSR_DEFS := KM_CSR__IRQ_STATUS_REG__(AXI_SLVERR|AXI_DECERR|SRAM_WRITE_LOCK_ERR|DRBG_ERR|ROM_PARITY_ERR|SRAM_PARITY_ERR|ROM_WRITE_ERR)_bm
KM_KPV_DEFS := KM_KPV__CTRL_REG__(LOCK_WRITE|LOCK_USE|ERASE|SEAL)_bm

$(KM_FIELD_INC): $(KM_CSR_H) $(KM_KPV_H) Makefile
	@printf '/* Generated from km_csr.h / km_kpv.h by km_fw/Makefile. Do not edit. */\n' > $@
	@grep -E '^#define ($(KM_CSR_DEFS)) ' $(KM_CSR_H) >> $@ || { \
	    echo "$(KM_CSR_H): expected field-mask defines matching $(KM_CSR_DEFS)" >&2; \
	    rm -f $@; exit 1; }
	@grep -E '^#define ($(KM_KPV_DEFS)) ' $(KM_KPV_H) >> $@ || { \
	    echo "$(KM_KPV_H): expected field-mask defines matching $(KM_KPV_DEFS)" >&2; \
	    rm -f $@; exit 1; }

$(OUT_DIR)/%.parhex: %.S gen_parhex.py $(KM_REG_INC)/key_manager_addr.h $(KM_FIELD_INC)
	$(RISCV_CC) -nostdlib $(ARCH_FLAGS) -I$(KM_REG_INC) -I. -Ttext=0 -o $*.elf $<
	$(RISCV_OBJCOPY) -O binary $*.elf $*.bin
	$(PYTHON) gen_parhex.py $*.bin > $@

clean:
	rm -f *.elf *.bin $(KM_FIELD_INC) $(PARHEX) $(OUT_DIR)/rom_main.rom.parhex
	# Whole build tree, not just build/tests/rom_main: the driver objects that
	# carry the wipe defines (rom_boot.o, libkey_manager.a) live flat in build/.
	rm -rf $(KM_FW_DIR)/build
