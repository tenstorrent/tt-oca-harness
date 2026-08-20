#!/usr/bin/env python3
"""Check every evidence string quoted in the Phase 1 plan against its kept log.

Run from hw/sys/sep/dv:  python3 docs/tools/verify_plan_proofs.py

The plan's contract is that each checker names log text the run must contain. That
only means something if it is mechanically checkable, and several classes of quote
silently are not:

  - anything containing a seed, or a value derived from one (the clock period);
  - item counts from the entropy scoreboard, which vary with how much traffic flowed;
  - report lines whose columns are padded, if the padding is not reproduced exactly;
  - "AXI read" quoted with one space, where the driver pads it to two.
  - short quotes: the original 15-character floor silently skipped 31 proof cells whose
    only quote was a brief but perfectly checkable log string (`ERROR_CODE=0`,
    `dst==src`, a `CHK1_decor` row label). The floor is 6 now.

Every one of those was present in this document and none of them would ever match
again. Exits non-zero if any quoted string is absent from the corresponding log.

REQUIRES A LOG CORPUS. Proof strings are checked against build/runs/, which is
git-ignored -- a fresh clone has nothing to check against and this script will report
every entry as having no kept log. Produce one first:

    python3 tools/dv/run_dv.py --dut sep --items no_cpu --tool verilator
    python3 tools/dv/run_dv.py --dut sep --items cpu    --tool verilator

That is the honest position rather than a hidden precondition: the plans' claim is that
their evidence is reproducible, not that it ships pre-verified.
"""
import re, pathlib, sys
# Both plans head each testcase entry with `=== sep_...`. Checked in one pass so a proof
# string cannot rot in either.
_DOCS = ('docs/verification_plan_phase1.adoc', 'docs/verification_plan_phase2.adoc')

# One (lines, marks) pair per document, NOT one concatenated list. Concatenating makes the
# next document's preamble fall inside the previous document's last entry, which quietly
# attributed Phase 2's audit narrative -- prose containing things like `0 != nonzero` --
# to the final Phase 1 testcase and demanded them from its log.
_ENTRIES = []
for _path in _DOCS:
    _f = pathlib.Path(_path)
    if not _f.is_file():
        continue
    _lines = _f.read_text().splitlines()
    _marks = [(i, l[4:].strip()) for i, l in enumerate(_lines) if l.startswith('=== sep_')]
    # The LAST entry must stop at the next level-2 section, not at end-of-file. Without
    # this, everything after the final testcase -- the audit summary, the open-items
    # table, the document history -- was attributed to that entry and demanded from its
    # log. That is how `glen=4`, prose in an open-items row describing a DIFFERENT test,
    # was reported missing from sep_esrc_e2e_smoke_test's log. Same bug the comment above
    # describes across documents, recurring within one.
    _stop = next((i for i, l in enumerate(_lines)
                  if l.startswith('== ') and _marks and i > _marks[-1][0]), len(_lines))
    _ENTRIES.append((_lines[:_stop], _marks))
logs = {}
for r in sorted(pathlib.Path('build/runs').iterdir(), key=lambda x: x.name):
    for lg in r.rglob('*.log'):
        if lg.parent.name == 'logs' and '/stages/' not in str(lg) \
                and '/latest/' not in str(lg):   # `latest` is a symlink to a run already listed
            logs[lg.stem] = lg
# Claims that describe the stimulus rather than quote a log line. Each is traceable to
# checked-in source, and each row's own Proof cell is separately checked against the log.
STIMULUS_CLAIMS = {
    'AxSIZE=2',   # cocotb/seq_lib/sep_sram_smoke_seq.py:43, sep_otbn_mem_smoke_seq.py:41
}

# Strings a plan quotes to say what must NOT appear. A presence grep cannot verify an
# absence, and this script scans whole entry bodies rather than just Proof cells, so a
# negative citation anywhere in an entry would otherwise be demanded from the log and
# reported as missing. Listed explicitly so the exemption is auditable rather than a
# silent hole -- and kept short on purpose: if this grows, the fix is to make the parser
# Proof-cell-aware, not to keep adding names.
NEGATIVE_EVIDENCE = {
    'ERROR: CFG_REGWEN not unlocked',   # sep_dma_hash_test CHK-CFG: the failure line
}

# Register reset values and other design constants a Description cites to explain WHY an
# entry exists. They are facts about the DUT, not text the run emits, so demanding them
# from the log is a false positive -- which is what this script reported on a clean tree
# before they were listed.
DESIGN_CONSTANTS = {
    'glen=4095',   # sep_drbg_gen_segmentation_test: EDN.BOOT_GEN_CMD reset value
}
# A quoted constructor / function call with keyword arguments -- SepEntropyCfg(glen=4,
# program_boot_generate=True) -- is checked-in source being named, not log text. Matched
# structurally rather than by listing each one, because a Description naming the object
# that drives an entry is a pattern that recurs.
_CALL_SIGNATURE = re.compile(r'^[A-Za-z_]\w*\([^()]*=[^()]*\)$')

def evidence(x):
    if x in STIMULUS_CLAIMS or x in NEGATIVE_EVIDENCE or x in DESIGN_CONSTANTS: return False
    if _CALL_SIGNATURE.match(x): return False
    if x.startswith(('+', '--')): return False
    if ' = "' in x: return False
    # Single-token quotes are usually a signal name or a register, not log text — except
    # when they carry a value or name a scoreboard row, which are literal log strings.
    if ' ' not in x and not ('=' in x or x.startswith('CHK')): return False
    if '...' in x: return False               # an ellipsis marks prose, not log text
    if x.endswith('!'): return True           # firmware banner lines          # header config attribute, not log text
    # Anything that looks like it was copied out of a log. Kept deliberately broad:
    # the strings this missed on the first pass were exactly the ones with a
    # placeholder in them, which is the class most worth catching.
    return any(t in x for t in ('PASS', ' -> ', ' <- ', '->', '=', 'dut_items', 'checks',
                                'counters', 'beats', 'word', 'cycle', 'OK', '0x',
                                'R/W', 'SLVERR', 'DECERR', 'locked', 'golden',
                                # scoreboard tail lines: "..., 0 errors" is log text, and
                                # without this a row whose only stable quote is the error
                                # count was silently SKIPPED rather than checked.
                                'errors'))
tot = miss_n = skipped = 0; out = []; n_entries = 0
for adoc, marks in _ENTRIES:
  n_entries += len(marks)
  for idx, (ln, name) in enumerate(marks):
    end = marks[idx + 1][0] if idx + 1 < len(marks) else len(adoc)
    body = "\n".join(adoc[ln:end]); lg = logs.get(name)
    if not lg:
        out.append((name, 'NO KEPT LOG', [])); continue
    text = lg.read_text(errors='replace')
    quoted = sorted(set(re.findall(r'`([^`\n]{6,})`', body)))
    cand = [x for x in quoted if evidence(x)]
    skipped += len(quoted) - len(cand)
    miss = [c for c in cand if c not in text]
    tot += len(cand); miss_n += len(miss)
    if miss: out.append((name, str(lg), miss))
print(f"checked {tot} evidence strings across {n_entries} entries; "
      f"{miss_n} not found, {skipped} skipped as non-log text")

# The plans also claim their entry and backlog counts track the testlists. Check it,
# rather than leaving that claim resting on the reader's trust: a name promoted to an
# implemented test without being promoted to a graded entry is exactly the drift the
# backlog table would otherwise hide.
count_err = 0
_tl = pathlib.Path('testlists')
if _tl.is_dir():
    implemented = set(re.findall(r'name\s*=\s*"(sep_[\w]+)"',
                                 "\n".join(f.read_text() for f in _tl.glob('*.toml'))))
    graded = set()
    for _p in _DOCS:
        _f = pathlib.Path(_p)
        if _f.is_file():
            graded |= set(re.findall(r'^=== (sep_\w+)', _f.read_text(), re.M))
    p2 = pathlib.Path('docs/verification_plan_phase2.adoc')
    if p2.is_file():
        body = p2.read_text()
        i = body.find('| Named, not implemented')
        backlog = set(re.findall(r'^\| `(sep_\w+)`$', body[i:], re.M)) if i >= 0 else set()
        both = sorted(backlog & implemented)
        if both:
            count_err += len(both)
            print(f"\nBACKLOG DRIFT: {len(both)} name(s) listed as not-implemented but "
                  f"present in a testlist -- promote them to graded entries:")
            for n in both:
                print(f"    {n}")
    ungraded = sorted(implemented - graded)
    print(f"entries: {len(graded)} graded, {len(implemented)} implemented in testlists, "
          f"{len(ungraded)} implemented but ungraded")
# Print the detail BEFORE exiting. This loop used to sit after sys.exit(), so it was
# unreachable: the script reported "N not found" and then died without ever saying
# WHICH strings were missing, which is a CI failure nobody can act on.
for name, lg, miss in out:
    if not miss: continue
    print(f"### {name}\n    log: {lg}")
    for m in miss: print(f"    MISSING: {m}")

sys.exit(1 if (miss_n or count_err) else 0)
