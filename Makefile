# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

OCAH_ROOT := $(abspath .)

include $(OCAH_ROOT)/ocah.mk

# Local convenience aliases: `make regen-regs` forwards to `make ocah-regen-regs`.
define ocah_phony_forward_rule
$(patsubst ocah-%,%,$(1)): $(1)
endef

$(foreach phony,$(filter ocah-%,$(OCAH_PHONY)),$(eval $(call ocah_phony_forward_rule,$(phony))))

.DEFAULT_GOAL := help
