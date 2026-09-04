<!-- SPDX-License-Identifier: Apache-2.0 -->
# DV audit — `sep_sram_smoke_test` (test height) — 2026-09-04

**Verdict: `NO-EVIDENCE`.** No MUST-FIX. 1 GOOD-TO-HAVE, 3 OBSERVATION.
The proof is real: the deciding line is a live assertion over transactions the log
shows executing, with distinct value-specific readbacks.
What holds it below `CLEAN` is provenance, not the test: no log in this bucket
records a source revision (shared disposition **D6**), so the policy-1.7 freshness
judgment is **not evaluated** and cannot be converted into a clean result.
Absent D6 this test would be `WEAK` on the single GOOD-TO-HAVE below.

**Deciding line:** `cocotb/env/sep_scoreboard.py:93` —
`assert not self.errors, ...` in `SepScoreboard.check_phase`, backed by the
minimum-activity guard on the next effective line, `sep_scoreboard.py:98`
(`assert self.checks > 0`). Value mismatches are recorded at
`sep_scoreboard.py:84-87`; non-OKAY responses at `sep_scoreboard.py:67-78`.
The test file itself decides nothing — correctly; the verdict is in the scoreboard.

**Claim (ladder rung 1 — VPLAN entry `[[sep_sram_smoke_test]]`,
`docs/SEP_VPLAN.adoc:849-881`):**
> "Proves the SEP local fabric routes to the SRAM and that the SRAM stores."

with four checker contracts: CHK-RESET-READ (pre-write read returns zero with
`OKAY`, explicitly declared to be a decode/liveness anchor and *not* an SRAM reset
property), CHK-STORE (a 64-bit write stores and reads back exactly), CHK-LANE (a
genuine `AxSIZE=2` 4-byte beat to the upper half leaves the lower four bytes
intact), CHK-RESP (every read beat `OKAY`, no `DECERR`).

## Needs a decision

| Test | Mechanism |
|---|---|
| `sep_sram_smoke_test` | Nothing about the test's own proof needs a decision. The bucket-wide provenance gap (D6) does: until a run records a source revision, no test here can be signed off as clean. Owner: the run tooling, not this test. |

## Findings

**F1 — the zero-expecting read leg can be satisfied by an unresolved read.**
Tier: **GOOD-TO-HAVE** (policy 2.6, compare blind to X/Z).
`cocotb/seq_lib/sep_sram_smoke_seq.py:36` issues the pre-write read with
`expected=0`; the compare at `cocotb/env/sep_scoreboard.py:79-90` masks and tests
`got != exp`, so the *passing* branch for this leg is the value `0`. If `RDATA`
carried X in that window and the AXI layer resolved it to zero bytes, the leg would
pass without the SRAM having been read.
Escalation trigger (**not evaluated**): whether `RDATA` can be X in that window,
and whether `ocah_axi_vip` / `cocotbext-axi` resolves X to 0 rather than raising —
that needs the VIP's resolve behaviour plus a waveform, which this read-only audit
does not have.
Why it stays yellow: the response check at `sep_scoreboard.py:67` is fed by the
response channel, not by the data, so the "decode and liveness" half of
CHK-RESET-READ does not rest on the data value; and the two later legs read exact
non-zero patterns back over the same path, so the path demonstrably carries real
data in this run (log lines 294-295, 305-306).
Fix: assert on unresolved read data (or compare against a non-zero pre-fill) for
any leg whose passing value is zero.

**F2 — the zero the first leg compares against is deposited by the testbench.**
Tier: **OBSERVATION** (policy 1.6 considered and excluded; policy 3).
`dv/tb/tb_top.sv:990`, in the `backdoor_default_fill_zero` initial block, zeroes
`u_sep_sram...u_mem.mem` at time 0 (VCS only; Verilator zero-inits anyway). So the
value CHK-RESET-READ compares against is TB-supplied, not DUT-earned.
Not a 1.6 because the VPLAN entry pre-declares exactly this — "the macro has no
array reset, and the zero comes from simulator memory initialisation, so this leg
would not reproduce on silicon" — and scopes the checker to decode and liveness.
A time-0 memory image load is explicitly excluded by 1.6. The only inaccuracy is
wording: on VCS the zero comes from a TB backdoor deposit, not from simulator
initialisation. Route to the plan owner.

**F3 — the VPLAN entry's CHK-RESP cites a checker name that is not in the entry.**
Tier: **OBSERVATION** (policy 3; plan-side).
`docs/SEP_VPLAN.adoc:880` ends with "Write responses are enforced separately, by
the scoreboard line quoted under CHK-NONVAC", but the entry lists only
CHK-RESET-READ, CHK-STORE, CHK-LANE and CHK-RESP — there is no CHK-NONVAC, and no
"cited tally" is quoted anywhere in the entry. The substance is fine and in fact
*stricter* than described: `sep_scoreboard.py:67-78` fails any non-OKAY response on
reads **and** writes, so the caveat about write responses only being inspected for
`DECERR` understates the implemented check. Dangling cross-reference; route to the
plan owner.

**F4 — `+skip_fuse_sense` is on the bring-up path and the VPLAN entry does not
name it.** Tier: **OBSERVATION** (policy 2.9 considered; the shortcut is declared
where it is configured, so it is not undeclared).
`testlists/memory.toml:29` enrols the test with `args = ["+skip_fuse_sense"]`, and
the run applied it (log line 7; "Skipping fuse sense" at log line 197, and
`_wait_fuse_sense` reporting "fuse sense done at cycle 0" at log line 277 —
`cocotb/tests/sep_base_test.py:229-248`). The VPLAN row at
`docs/SEP_VPLAN.adoc:126-129` lists the run mode as plain `no_cpu`, while sibling
rows do declare the plusarg (`sep_otbn_mem_smoke_test`, line 135).
Not a 1.6: the skip supplies the fabric-release gate, not any state the checked
mechanism (routing and storage) was itself supposed to produce, and the SRAM data
comes from a real AXI transaction against the design's own array. 2.9's escalation
trigger — "the stub is what answers the checker" — was **evaluated and does not
hold**. Fix is one word in the VPLAN row, for consistency with its neighbours.

## The seven MUST-FIX classes

| Class | Result |
|---|---|
| 1.1 fabricated verdict | **excluded.** The verdict is `assert not self.errors` at `sep_scoreboard.py:93` over items the driver filled from the bus (`sep_axi_agent.py:159-187`). No pass token is emitted off a compare; the two `pass_claim` hits in the log are cocotb's own regression summary. Nothing in the closure assigns `rdata` or `expected` from the other. |
| 1.2 a check that cannot fail | **excluded.** `expected` is a literal pattern in the sequence (`sep_sram_smoke_seq.py:36,38,42`); `rdata` comes from `read_bytes_result`. The two are independent, and the log shows three different compared values (0x0, 0x0123456789abcdef, 0xfeedface89abcdef), so the compare discriminates. `resp_ok` defaults **False** (`sep_axi_agent.py:88`), so a missing response fails closed. |
| 1.3 a mismatch that does not fail | **excluded.** `_fail` appends to `self.errors` (`sep_scoreboard.py:31-33`) and `check_phase` asserts the list is empty. Shared disposition **D1** (`sep_base_test.py:1029-1031`) confirms no `try`/`except` swallows an `AssertionError` on this path. No bounded wait in the closure treats expiry as success: `allow_timeout` is left False for every item, so a wedge raises in the VIP. `log_facts` reports 12 completed waits and no expiry. |
| 1.4 nothing was observed | **excluded.** `sep_scoreboard.py:98` is a real minimum-activity guard, and the run reports "5 checks (3 value-verified, 0 expected-error), 0 errors" (log line 307) against the 5 items the sequence issues — stimulus and observation reconcile exactly. Caveat recorded, not filed: the guard is `checks > 0`, not a count derived from the stimulus, so it would not catch a *partially* drained sequence; in this closure every `finish_item` is awaited before the next, and an early exception would propagate per D1, so no path reaches `check_phase` with items missing. |
| 1.5 the wrong thing was proven | **excluded.** Step-by-step against the claim: bring-up in `no_cpu` (`sep_sram_smoke_test.py:17`) · read-and-require-zero (`seq:36`) = CHK-RESET-READ · 64-bit write then readback (`seq:37-38`) = CHK-STORE · 4-byte `size=2` beat to the upper half then a full 64-bit readback expecting `0xFEED_FACE_89AB_CDEF` (`seq:41-42`) = CHK-LANE, which genuinely proves the lower four bytes survived · every access response checked = CHK-RESP. The address is symbolic — `sym("SEP_SRAM_MEM_BASE_ADDR")` at `seq:11`, which raises rather than returning a stale value (`cocotb/env/sep_reg_meta.py:330-349`) — so the unmapped-space-reads-zero trap does not apply; the resolved address `0x10000100` decoded and returned written data (log 289-295). The five bare literals in the fact row are data patterns and a `0x100` offset within the window, not register addresses: no 2.3. |
| 1.6 the testbench supplied the answer | **excluded**, with F2 and F4 recorded. Bring-up is `bring_up_no_cpu` with `park=()` (`sep_base_test.py:354-373`), which forces nothing. The `backdoor` hits in the log are the time-0 ROM/SRAM/TCM fills and image loads in `tb_top.sv:973-1035` — time-0 image loads, explicitly excluded by 1.6. No force target in the closure intersects any checked signal; the fact row reports 0 forces. |
| 1.7 evidence not from this test at this commit | **not evaluated** (freshness), enrollment **excluded**. Enrollment is real and scheduled: `testlists/memory.toml:22-29` plus group membership in `testlists/all.toml:68` (`all`) and `:181` (`no_cpu`), and the log is from the `..._vcs__all` run directory, so the test was declared, present, and executed. Freshness cannot be judged: per **D6** no log here names a git revision (`result.json` carries only build fingerprint `c07fb8d96992` and the seed), and the skill's stated method forbids settling this with file timestamps. No `ifdef`-selected DUT datapath on the proof path; the one guard in the closure region, `ifndef VERILATOR` at `tb_top.sv:988`, gates a TB memory pre-fill, not design logic. |

## Yellow triggers evaluated

- 2.1 deny without a live control — not applicable; no deny leg. Every access expects `OKAY`.
- 2.2 golden derived from the RTL — not applicable. The expected values are arbitrary literal patterns chosen by the test (`0x0123456789ABCDEF`, `0xFEEDFACE`); nothing was transcribed from the design.
- 2.3 hand-copied addressing — excluded; symbolic base, see 1.5.
- 2.4 fixed delay for a handshake — excluded. No `Timer`/settling delay in the closure; every access completes through `start_item`/`finish_item` and the VIP's response handshake.
- 2.5 seed — excluded. The test is deterministic (no randomisation in the closure) and the seed is recorded in the run path and `result.json`.
- 2.6 X/Z-blind compare — **filed as F1**, trigger not evaluated (stated there).
- 2.7 depends on another test — excluded. Self-contained: it brings the DUT up itself and writes the value it later reads.
- 2.8 expectation looser than the claim — excluded. Exact full-width value compares, and the response check (any non-OKAY fails) is stricter than the entry's own wording.
- 2.9 undeclared model/stub/shortcut — evaluated, see F4; also checked that the storage element is design RTL, not a TB model: `u_sep_ip_integration.u_km_sram`-style `prim`-based array `u_sep_sram.gen_ram_inst[0].u_mem` inside the DUT hierarchy (`tb_top.sv:990` addresses it through the DUT path), so the "OSS behavioral SRAM responder" in the test docstring is the design's own generic RAM, not a testbench responder.

## What I did not check

- **Log freshness / provenance.** Deliberately unevaluated per D6; no revision is recorded anywhere in the artifact set, and this cannot be retrofitted.
- **F1's trigger:** the X-resolution behaviour of `ocah_axi_vip` / `cocotbext-axi` on `RDATA`, and whether `RDATA` is ever X in the pre-write read window. Needs the VIP internals plus a waveform.
- **Whether `AxSIZE=2` actually appeared on the bus.** CHK-LANE's premise is a genuine narrow beat; I confirmed the sequence requests `size=2` (`seq:41`) and that the driver passes it through (`sep_axi_agent.py:149-158`), and the byte-level result is consistent with it, but I did not confirm the beat encoding on the wire — that needs a waveform or a monitor trace.
- **The `DECERR` tally CHK-RESP alludes to.** I did not chase whether `cocotb/env/sep_axi_monitor.py` / `sep_axi_decode_map.py` are active for this test; the OKAY-on-every-access substance of CHK-RESP is enforced by the scoreboard regardless, so nothing in the verdict depended on it.
- **`results.xml`.** I read `result.json` (exit 0, no failure buckets) and the log facts; I did not open `results/results.xml`.
- **Shared infrastructure**, by instruction: `sep_base_test.py`, `sep_axi_reg_driver.py`, `sep_boot_scoreboard.py` — cited as dispositions D1-D7, not re-opened. The 1-hit `assert_fail` lead in the log facts is D7's known false positive (cocotb's "pytest not found" line).

## Appendix — inputs

- **Policy:** `/home/yenhenglai/.claude-ai/skills/dv_audit/references/dv_policy.md`, no git; SHA-256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210`. (The `../dv_policy.md` location does not exist here; `references/` was used.)
- **Claim:** `hw/sys/sep/dv/docs/SEP_VPLAN.adoc:849-881` (detail entry), summary row at `:126-129`.
- **Closure read:** `cocotb/tests/sram/sep_sram_smoke_test.py` (19 lines, whole) · `cocotb/seq_lib/sep_sram_smoke_seq.py` (42 lines, whole) · `cocotb/env/sep_axi_agent.py` (whole) · `cocotb/env/sep_scoreboard.py` (whole — the deciding file) · narrow reads of `cocotb/tests/sep_base_test.py` (`bring_up_no_cpu`, `_wait_fuse_sense`), `cocotb/env/sep_reg_meta.py` (`sym`), `tb/tb_top.sv:955-1035`, `hw/sys/sep/rtl/sep_sram_interface_shim.sv`, `sep_sram.sv`. `cocotb/seq_lib/sep_axi_access_seq.py` is **not** on this proof path — the sequence drives `SepAxiItem` directly.
- **Enrollment:** `testlists/memory.toml:22-29`; groups `testlists/all.toml:68`, `:181`.
- **Log:** `build/runs/20260904_065716__vcs__all/sep_sram_smoke_test/seed_723424069/attempt_0/logs/sep_sram_smoke_test.log` (374 lines, PASS), read only via `scripts/log_facts.py` plus four targeted `grep`/`sed` windows (lines 1-12, 197-198, 277, 283-307). `result.json` at the sibling path: `exit_code 0`, `failure_buckets []`, build fingerprint `c07fb8d96992`.
- **Dispositions cited:** D1, D6, D7 (D2-D5 not on this proof path).
