# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_fw_common_mk
ocah_fw_common_mk := 1

# A multi-command recipe (link, then objdump/nm/size/objcopy) that fails partway
# through must not leave the .elf behind: make would treat it as up to date on the
# next run and silently skip the remaining steps, so the .hex images would never be
# produced and the build would appear to pass.
.DELETE_ON_ERROR:

# Shared DV firmware build engine. A subsystem fw.mk sets the FW_* inputs below,
# includes its toolchain.mk, then includes this for the build rules + all/clean.
#
# Required inputs:
#   FW_NAME          - short subsystem name (e.g. key_manager, sep, smc)
#   FW_DIR           - absolute path to the subsystem dv/fw directory
#   FW_C_SRCS        - library C sources (no entry/main)
#   FW_ASM_SRCS      - library .s/.S startup/helper sources
#   FW_INCLUDES      - -I include flags
#   FW_CFLAGS        - C compile flags
#   FW_ASFLAGS       - assembler flags
#   FW_LDFLAGS       - link flags
# Optional, for a single linked image (FW_ELF):
#   FW_LINKER_SCRIPT - linker script path
#   FW_ENTRY_SRCS    - entry/main sources
# Optional, for per-test linked images via `dv-fw-tests`:
#   FW_LINK_MODES               - link modes; auto-discovered from link/modes/*.ld
#   FW_LINK_SCRIPT_<mode>       - linker script for <mode> (default: link/modes/<mode>.ld)
#   FW_DEFAULT_TEST_MODE        - mode used when a test has no override
#   FW_TEST_MODE_<name>         - per-test mode override
#   FW_TEST_LDFLAGS             - test link flags (default: FW_LDFLAGS)
#   FW_TEST_LDFLAGS_<mode>      - per-mode override (default: FW_TEST_LDFLAGS)
#   FW_TEST_INCLUDES            - extra test-only include flags
#   FW_TEST_EXTRA_CFLAGS        - extra test-only C flags
#   FW_TEST_EXTRA_ARCHIVES      - extra archives linked after lib<name>.a
#   FW_TEST_ARCHIVE_LINK        - how lib<name>.a is linked in (default: --whole-archive)
#   FW_TEST_ARCHIVE_LINK_<mode> - per-mode override (default: FW_TEST_ARCHIVE_LINK)
#   FW_TEST_POSTPROCESS         - macro called as $(call ...,elf_path,test_name,mode)
#   FW_TEST_POSTPROCESS_PRIMARY_SUFFIX - primary generated sidecar suffix; when
#                           set, postprocessing is a real target instead of an
#                           ELF recipe side effect (e.g. .ecc.hex)
#   FW_TEST_POSTPROCESS_DEPS - files that invalidate the primary sidecar target
# Test discovery (canonical tests/<name>/<name>.c, plus sibling .c/.S in the
# same dir); a subsystem declares only deltas, or opts out entirely by
# pre-setting FW_TEST_NAMES (+ FW_TEST_SRCS_<t>):
#   FW_TEST_EXCLUDE_NAMES  - test dir names to skip
#   FW_TEST_EXTRA_SRCS_<t> - extra .c/.S compiled into test <t>
#
# Each test links against exactly one mode. Output artifacts are named
# <test>/<test>.<mode>.{elf,map,dis,sym}.

# Parallelize object compiles / test links by default (same pattern as
# regen-regs). Explicit -j / --jobs on the command line wins.
OCAH_DV_FW_JOBS ?= 8
ifeq ($(filter -j% --jobs%,$(MAKEFLAGS)),)
MAKEFLAGS += -j$(OCAH_DV_FW_JOBS)
endif

# Toolchain resolution. RISCV_TOOLCHAIN = dir of riscv64-unknown-elf-* tools, or
# empty to use the toolchain on PATH (provisioned via Docker).
RISCV_TOOLCHAIN ?=
RISCV_PREFIX ?= riscv64-unknown-elf-

ifeq ($(strip $(RISCV_TOOLCHAIN)),)
OCAH_FW_TOOL_PREFIX := $(RISCV_PREFIX)
else
OCAH_FW_TOOL_PREFIX := $(patsubst %/,%,$(RISCV_TOOLCHAIN))/$(RISCV_PREFIX)
endif

# ':=' because CC/AR are Make built-ins ('?=' wouldn't take); cmdline still wins.
# AR/RANLIB use gcc-* wrappers so the LTO plugin indexes -flto archives.
CC      := $(OCAH_FW_TOOL_PREFIX)gcc
AR      := $(OCAH_FW_TOOL_PREFIX)gcc-ar
RANLIB  := $(OCAH_FW_TOOL_PREFIX)gcc-ranlib
OBJCOPY := $(OCAH_FW_TOOL_PREFIX)objcopy
# Disassembly uses -d (code sections) rather than -D (every section): the RISC-V
# disassembler aborts on some non-code byte patterns, e.g. the sha3 round
# constants in sep_smu_sanity's .data. -s still hexdumps the data sections.
OBJDUMP := $(OCAH_FW_TOOL_PREFIX)objdump
NM      := $(OCAH_FW_TOOL_PREFIX)nm
SIZE    := $(OCAH_FW_TOOL_PREFIX)size

# picolibc spec file shared by every subsystem toolchain; default here so the
# per-subsystem toolchain.mk files do not repeat it.
FW_PICOLIBC_SPECS ?= picolibc.specs

# A sys sets FW_REG_SYS to pull in its register headers; leaf IP subsystems
# leave it unset.
include $(OCAH_ROOT)/hw/common/dv/fw/reg_includes.mk
FW_INCLUDES += $(if $(strip $(FW_REG_SYS)),$(call ocah_fw_reg_includes,$(FW_REG_SYS)))

# Derived build variables.
FW_BUILD_DIR ?= $(FW_DIR)/build

FW_C_OBJS   := $(addprefix $(FW_BUILD_DIR)/,$(notdir $(FW_C_SRCS:.c=.o)))
FW_ASM_OBJS := $(addprefix $(FW_BUILD_DIR)/,$(patsubst %.S,%.o,$(patsubst %.s,%.o,$(notdir $(FW_ASM_SRCS)))))
FW_LIB_OBJS := $(FW_C_OBJS) $(FW_ASM_OBJS)

FW_ENTRY_OBJS := $(addprefix $(FW_BUILD_DIR)/,$(patsubst %.S,%.o,$(patsubst %.s,%.o,$(notdir $(FW_ENTRY_SRCS:.c=.o)))))

FW_ARCHIVE := $(FW_BUILD_DIR)/lib$(FW_NAME).a
FW_ELF     := $(FW_BUILD_DIR)/$(FW_NAME).elf

FW_TEST_BUILD_DIR ?= $(FW_BUILD_DIR)/tests
FW_TEST_LDFLAGS ?= $(FW_LDFLAGS)
FW_TEST_INCLUDES ?=
FW_TEST_EXTRA_CFLAGS ?=
FW_TEST_EXTRA_ARCHIVES ?=
FW_TEST_COMMON_SRCS ?=
FW_TEST_ARCHIVE_LINK ?= -Wl,--whole-archive "$(FW_ARCHIVE)" $(FW_TEST_EXTRA_ARCHIVES) -Wl,--no-whole-archive

# Link modes: auto-discovered from link/modes/*.ld, each overridable by name.
FW_LINK_MODES ?= $(sort $(patsubst $(FW_DIR)/link/modes/%.ld,%,$(wildcard $(FW_DIR)/link/modes/*.ld)))
$(foreach m,$(FW_LINK_MODES),$(eval FW_LINK_SCRIPT_$(m) ?= $(FW_DIR)/link/modes/$(m).ld))
# Per-mode overrides default to the subsystem-wide settings.
$(foreach m,$(FW_LINK_MODES),$(eval FW_TEST_LDFLAGS_$(m) ?= $(FW_TEST_LDFLAGS)))
$(foreach m,$(FW_LINK_MODES),$(eval FW_TEST_ARCHIVE_LINK_$(m) ?= $(FW_TEST_ARCHIVE_LINK)))

# Per-test mode resolution: an explicit FW_TEST_MODE_<name> override wins,
# otherwise the subsystem's FW_DEFAULT_TEST_MODE applies.
ocah_fw_test_mode = $(if $(strip $(FW_TEST_MODE_$(1))),$(strip $(FW_TEST_MODE_$(1))),$(FW_DEFAULT_TEST_MODE))

# Unified DV test discovery: one testcase per tests/<name>/ (plus sibling .c),
# tests/common/ reserved for shared helpers. Opt out by pre-setting FW_TEST_NAMES.
ifndef FW_TEST_NAMES
FW_TEST_SRCS := $(filter-out \
  $(FW_DIR)/tests/common/% \
  $(foreach t,$(FW_TEST_EXCLUDE_NAMES),$(FW_DIR)/tests/$(t)/%), \
  $(wildcard $(FW_DIR)/tests/*/*.c))
FW_TEST_NAMES := $(sort $(notdir $(patsubst %/,%,$(dir $(FW_TEST_SRCS)))))
$(foreach t,$(FW_TEST_NAMES),$(eval FW_TEST_SRC_$(t) := $(firstword $(wildcard $(FW_DIR)/tests/$(t)/*.c))))
$(foreach t,$(FW_TEST_NAMES),$(eval FW_TEST_SRCS_$(t) := $(wildcard $(FW_DIR)/tests/$(t)/*.c $(FW_DIR)/tests/$(t)/*.S) $(FW_TEST_EXTRA_SRCS_$(t))))
endif

FW_TEST_SELECTED := $(if $(strip $(TEST)),$(strip $(TEST)),$(FW_TEST_NAMES))
FW_TEST_ELFS := $(foreach t,$(FW_TEST_SELECTED),$(FW_TEST_BUILD_DIR)/$(t)/$(t).$(call ocah_fw_test_mode,$(t)).elf)
FW_TEST_POSTPROCESS_TARGETS := $(if $(strip $(FW_TEST_POSTPROCESS_PRIMARY_SUFFIX)), \
  $(foreach t,$(FW_TEST_SELECTED),$(FW_TEST_BUILD_DIR)/$(t)/$(t)$(FW_TEST_POSTPROCESS_PRIMARY_SUFFIX)))
FW_TEST_TARGETS := $(if $(strip $(FW_TEST_POSTPROCESS_TARGETS)),$(FW_TEST_POSTPROCESS_TARGETS),$(FW_TEST_ELFS))

# Let the pattern rules below find sources regardless of subdirectory.
vpath %.c $(sort $(dir $(FW_C_SRCS) $(FW_ENTRY_SRCS)))
vpath %.S $(sort $(dir $(FW_ASM_SRCS) $(FW_ENTRY_SRCS)))
vpath %.s $(sort $(dir $(FW_ASM_SRCS) $(FW_ENTRY_SRCS)))

DEPFLAGS := -MMD -MP

# Optional extra compile flags from the make command line (e.g. a register stub).
FW_EXTRA_CFLAGS ?=

$(FW_BUILD_DIR):
	@mkdir -p "$@"

$(FW_BUILD_DIR)/%.o: %.c | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_CFLAGS) $(FW_INCLUDES) $(FW_EXTRA_CFLAGS) $(DEPFLAGS) -c "$<" -o "$@"

$(FW_BUILD_DIR)/%.o: %.S | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_ASFLAGS) $(FW_INCLUDES) $(FW_EXTRA_CFLAGS) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

$(FW_BUILD_DIR)/%.o: %.s | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_ASFLAGS) $(FW_INCLUDES) $(FW_EXTRA_CFLAGS) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

# Runtime library archive; DV tests / production entries link against it.
$(FW_ARCHIVE): $(FW_LIB_OBJS)
	@rm -f "$@"
	$(AR) rcs "$@" $(FW_LIB_OBJS)
	$(SIZE) -t $(FW_LIB_OBJS) | tail -n 1

.PHONY: ocah-fw-lib
ocah-fw-lib: $(FW_ARCHIVE)

$(FW_TEST_BUILD_DIR)/%/.dir:
	@mkdir -p "$(@D)"
	@touch "$@"

ifndef FW_TEST_POSTPROCESS
define FW_TEST_POSTPROCESS
endef
endif

define ocah_fw_test_obj_rule
$(FW_TEST_BUILD_DIR)/$(1)/$(notdir $(basename $(2)).o): $(2) | $(FW_TEST_BUILD_DIR)/$(1)/.dir ocah-fw-check-toolchain
	$$(CC) $(if $(filter %.S %.s,$(2)),$$(FW_ASFLAGS) $$(FW_INCLUDES) $$(FW_EXTRA_CFLAGS) $$(DEPFLAGS) -x assembler-with-cpp,$$(FW_CFLAGS) $$(FW_INCLUDES) $$(FW_TEST_INCLUDES) $$(FW_EXTRA_CFLAGS) $$(FW_TEST_EXTRA_CFLAGS) $$(DEPFLAGS)) -c "$$<" -o "$$@"
endef

define ocah_fw_test_rules
FW_TEST_SRCS_FOR_$(1) := $$(if $$(strip $$(FW_TEST_SRCS_$(1))),$$(FW_TEST_SRCS_$(1)),$$(FW_TEST_SRC_$(1))) $$(FW_TEST_COMMON_SRCS)
FW_TEST_OBJS_$(1) := $$(addprefix $(FW_TEST_BUILD_DIR)/$(1)/,$$(addsuffix .o,$$(basename $$(notdir $$(FW_TEST_SRCS_FOR_$(1))))))
$$(foreach src,$$(FW_TEST_SRCS_FOR_$(1)),$$(eval $$(call ocah_fw_test_obj_rule,$(1),$$(src))))

FW_TEST_MODE_FOR_$(1) := $$(call ocah_fw_test_mode,$(1))
FW_TEST_LINK_SCRIPT_FOR_$(1) := $$(FW_LINK_SCRIPT_$$(FW_TEST_MODE_FOR_$(1)))
FW_TEST_LDFLAGS_FOR_$(1) := $$(FW_TEST_LDFLAGS_$$(FW_TEST_MODE_FOR_$(1)))
FW_TEST_ARCHIVE_LINK_FOR_$(1) := $$(FW_TEST_ARCHIVE_LINK_$$(FW_TEST_MODE_FOR_$(1)))

# Search both link/ and link/modes/ so an INCLUDEd fragment resolves
# regardless of which one it lives in.
$(FW_TEST_BUILD_DIR)/$(1)/$(1).$$(FW_TEST_MODE_FOR_$(1)).elf: $$(FW_TEST_OBJS_$(1)) $$(FW_ARCHIVE) $$(FW_TEST_EXTRA_ARCHIVES) $$(FW_TEST_LINK_SCRIPT_FOR_$(1)) | $(FW_TEST_BUILD_DIR)/$(1)/.dir ocah-fw-check-toolchain
	$$(CC) $$(FW_TEST_LDFLAGS_FOR_$(1)) -L"$(FW_DIR)/link" -L"$(FW_DIR)/link/modes" -Wl,-Map="$(FW_TEST_BUILD_DIR)/$(1)/$(1).$$(FW_TEST_MODE_FOR_$(1)).map" -T "$$(FW_TEST_LINK_SCRIPT_FOR_$(1))" $$(FW_TEST_OBJS_$(1)) $$(FW_TEST_ARCHIVE_LINK_FOR_$(1)) -o "$$@"
	$$(OBJDUMP) -dCSsx "$$@" > "$(FW_TEST_BUILD_DIR)/$(1)/$(1).$$(FW_TEST_MODE_FOR_$(1)).dis"
	$$(NM) -B -n "$$@" > "$(FW_TEST_BUILD_DIR)/$(1)/$(1).$$(FW_TEST_MODE_FOR_$(1)).sym"
	$$(SIZE) "$$@"
	$$(if $$(strip $$(FW_TEST_POSTPROCESS_PRIMARY_SUFFIX)),,$$(call FW_TEST_POSTPROCESS,$$@,$(1),$$(FW_TEST_MODE_FOR_$(1))))
endef

$(foreach test,$(FW_TEST_NAMES),$(eval $(call ocah_fw_test_rules,$(test))))

define ocah_fw_test_postprocess_rule
$(FW_TEST_BUILD_DIR)/$(1)/$(1)$(FW_TEST_POSTPROCESS_PRIMARY_SUFFIX): $(FW_TEST_BUILD_DIR)/$(1)/$(1).$$(FW_TEST_MODE_FOR_$(1)).elf $(FW_TEST_POSTPROCESS_DEPS)
	$$(call FW_TEST_POSTPROCESS,$$<,$(1),$$(FW_TEST_MODE_FOR_$(1)))
endef

ifneq ($(strip $(FW_TEST_POSTPROCESS_PRIMARY_SUFFIX)),)
$(foreach test,$(FW_TEST_NAMES),$(eval $(call ocah_fw_test_postprocess_rule,$(test))))
endif

# Validate the test selection at parse time, but only for dv-fw-tests (TEST may
# be set for other goals and must not break all/clean).
ifneq ($(filter dv-fw-tests,$(MAKECMDGOALS)),)
ifeq ($(strip $(FW_TEST_NAMES)),)
$(error no FW C tests configured for $(FW_NAME))
endif
ifneq ($(strip $(TEST)),)
ifeq ($(strip $(FW_TEST_SRC_$(strip $(TEST)))$(FW_TEST_SRCS_$(strip $(TEST)))),)
$(error unknown $(FW_NAME) FW C test '$(strip $(TEST))'; known tests: $(FW_TEST_NAMES))
endif
endif
$(foreach t,$(FW_TEST_SELECTED),$(if $(filter $(call ocah_fw_test_mode,$(t)),$(FW_LINK_MODES)),,$(error $(FW_NAME) test '$(t)' resolved to unknown link mode '$(call ocah_fw_test_mode,$(t))'; known modes: $(FW_LINK_MODES))))
endif

.PHONY: dv-fw-tests
dv-fw-tests: $(FW_TEST_TARGETS)

.PHONY: dv-fw-test-list
dv-fw-test-list:
	@printf '%s\n' $(FW_TEST_NAMES)

# Linked image: only when the subsystem provides a linker script + entry.
ifneq ($(strip $(FW_LINKER_SCRIPT)),)
ifneq ($(strip $(FW_ENTRY_SRCS)),)
$(FW_ELF): $(FW_ENTRY_OBJS) $(FW_ARCHIVE) $(FW_LINKER_SCRIPT)
	$(CC) $(FW_LDFLAGS) -T "$(FW_LINKER_SCRIPT)" $(FW_ENTRY_OBJS) $(FW_ARCHIVE) -o "$@"
	$(OBJCOPY) -O verilog --verilog-data-width 8 "$@" "$(FW_BUILD_DIR)/$(FW_NAME).hex"
	$(OBJDUMP) -dCSsx "$@" > "$(FW_BUILD_DIR)/$(FW_NAME).dis"
	$(SIZE) "$@"

.PHONY: ocah-fw-elf
ocah-fw-elf: $(FW_ELF)
FW_DEFAULT_GOAL := ocah-fw-elf
endif
endif

FW_DEFAULT_GOAL ?= ocah-fw-lib

.PHONY: all
all: $(FW_DEFAULT_GOAL)

.PHONY: clean
clean:
	@rm -rf "$(FW_BUILD_DIR)"

# Verify the cross compiler resolves; emit an actionable error otherwise.
# A bare gcc on PATH is not enough: hosts often carry a distro riscv64-unknown-elf-gcc
# built without picolibc, which only fails ~100 objects later with a spec-file error.
.PHONY: ocah-fw-check-toolchain
ocah-fw-check-toolchain:
	@command -v "$(CC)" >/dev/null 2>&1 || { \
		echo "error: RISC-V toolchain not found (looking for '$(CC)')."; \
		echo "set RISCV_TOOLCHAIN=/path/to/bin (a directory with $(RISCV_PREFIX)* tools),"; \
		echo "put the toolchain on PATH, or run via the toolchain container:"; \
		echo "  ./scripts/docker-run.sh run make dv-fw-libs TARGET=<subsystem>"; \
		exit 1; \
	}
	@specs=$$("$(CC)" --print-file-name=$(FW_PICOLIBC_SPECS) 2>/dev/null); \
	if [ "$$specs" = "$(FW_PICOLIBC_SPECS)" ] || [ ! -f "$$specs" ]; then \
		echo "error: '$(CC)' cannot find $(FW_PICOLIBC_SPECS); this toolchain has no picolibc."; \
		echo "point RISCV_TOOLCHAIN at a picolibc-enabled toolchain, or run via the"; \
		echo "toolchain container, which carries one:"; \
		echo "  ./scripts/docker-run.sh run make dv-fw-libs TARGET=<subsystem>"; \
		exit 1; \
	fi

FW_TEST_DEPFILES := $(foreach t,$(FW_TEST_NAMES),$(FW_TEST_OBJS_$(t):.o=.d))

-include $(FW_LIB_OBJS:.o=.d) $(FW_ENTRY_OBJS:.o=.d) $(FW_TEST_DEPFILES)

endif
