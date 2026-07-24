// SPDX-License-Identifier: Apache-2.0
//
// SEP OSS hello-world boot firmware: open the outbound filter, print a banner
// over the testbench mailbox, and return PASS. Fully self-contained — uses only
// the OSS drivers (no libc, no internal headers).

#include "sep_mailbox.h"
#include "sep_outbound_filter.h"

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("Hello from SEP OSS firmware!\n");
    return 0; // start.S writes the PASS completion magic on a 0 return
}
