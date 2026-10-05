# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Register -I flags for a sys subsystem (umbrella + generated headers + shim/ip
# trees). Separate from compile.mk because the SEP boot ROM drives its own build
# but has to see exactly the same headers.

ifndef ocah_fw_reg_includes_mk
ocah_fw_reg_includes_mk := 1

# The overlay dirs come first so that a header of the same name placed there
# shadows the open copy.
ocah_fw_reg_includes = $(OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_$(1)) \
  -I$(OCAH_ROOT)/hw/common/dv/fw \
  -I$(OCAH_ROOT)/hw/sys/$(1)/regs/gen/c -I$(OCAH_ROOT)/hw/sys/$(1)/regs/gen/c/blocks \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/sys/$(1)/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/*/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/*/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/rdl/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/regs/*/regs/gen/c))

endif
