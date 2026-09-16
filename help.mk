# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_help_mk
ocah_help_mk := 1

.PHONY: help
help:
ifdef HELP_TITLE
	@echo $(HELP_TITLE)
endif
ifdef HELP_DESCRIPTION
	@echo $(HELP_DESCRIPTION)
endif
	@echo ""
	@MAKEFILES="$(MAKEFILE_LIST)" bash "$(OCAH_ROOT)/scripts/generate-makefile-help.sh"

endif
