#!/usr/bin/env python3
"""Generate English DV Skill Flow PPTX (visual flows only, no ASCII)."""

import re
from lxml import etree

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
OUT = "/proj_soc/user_dev/minshaoho/tryrun/os_aidv/hw/sys/smc/dv/docs/dv_skill_result/SMC_CLOCK_GATING_DV_Skill_Flow_EN.pptx"

# Layout constants (widescreen 16:9)
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGIN_L = Inches(0.5)
MARGIN_R = Inches(0.5)
CONTENT_W = SLIDE_W - MARGIN_L - MARGIN_R
TITLE_H = Inches(0.85)
CONTENT_TOP = Inches(1.1)
FOOTER_TOP = Inches(7.15)

C_TITLE = RGBColor(0x0B, 0x1F, 0x3A)
C_SKILL1 = RGBColor(0x1E, 0x40, 0xAF)
C_SKILL15 = RGBColor(0x0E, 0x74, 0x90)
C_SKILL2 = RGBColor(0xB4, 0x53, 0x09)
C_SKILL3 = RGBColor(0x9F, 0x12, 0x39)
C_OK = RGBColor(0x16, 0x65, 0x34)
C_WARN = RGBColor(0x9A, 0x34, 0x12)
C_LINE = RGBColor(0x33, 0x41, 0x55)
C_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
C_BLACK = RGBColor(0x0F, 0x17, 0x2A)
C_MUTED = RGBColor(0x47, 0x55, 0x69)
C_LIGHT = RGBColor(0xE2, 0xE8, 0xF0)
C_DES = RGBColor(0x4C, 0x1D, 0x95)
C_DV = RGBColor(0x0F, 0x76, 0x6E)
C_PEER = RGBColor(0x9F, 0x12, 0x39)
C_BG = RGBColor(0xF8, 0xFA, 0xFC)
C_BUG = RGBColor(0xB9, 0x1C, 0x1C)
# Cross-slide term highlights (distinct backgrounds)
HL_FEATURE = "C4B5FD"   # soft violet — feature_list
HL_CHECKBOX = "FDE68A"  # soft amber — checkbox
C_FEATURE = RGBColor(0x5B, 0x21, 0xB6)
C_CHECKBOX = RGBColor(0x92, 0x40, 0x0E)

prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H
blank = prs.slide_layouts[6]
slides_meta = []

# Longer phrases first so "checkbox sets" wins over "checkbox"
_TERM_RE = re.compile(
    r"(feature_list|feature list|checkbox sets|checkbox set|checkboxes|checkbox)",
    re.IGNORECASE,
)
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def set_run(run, size=16, bold=False, color=None, font="Calibri"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = font
    if color is not None:
        run.font.color.rgb = color


def apply_run_highlight(run, hex_rgb):
    """DrawingML text highlighter background on a run."""
    rPr = run._r.get_or_add_rPr()
    for child in list(rPr):
        if child.tag == f"{{{_A_NS}}}highlight":
            rPr.remove(child)
    hl = etree.SubElement(rPr, f"{{{_A_NS}}}highlight")
    srgb = etree.SubElement(hl, f"{{{_A_NS}}}srgbClr")
    srgb.set("val", hex_rgb)


def _term_highlight(term):
    t = term.lower()
    if t.startswith("feature"):
        return HL_FEATURE, C_FEATURE
    return HL_CHECKBOX, C_CHECKBOX


def add_runs_with_term_highlight(p, text, size, bold, color, font):
    """Split text and paint feature_list / checkbox with distinct backgrounds."""
    if not text:
        run = p.add_run()
        run.text = ""
        set_run(run, size, bold, color, font)
        return
    pos = 0
    for m in _TERM_RE.finditer(text):
        if m.start() > pos:
            run = p.add_run()
            run.text = text[pos:m.start()]
            set_run(run, size, bold, color, font)
        term = m.group(0)
        run = p.add_run()
        run.text = term
        hl, term_color = _term_highlight(term)
        # Keep term colors readable even on dark filled boxes
        set_run(run, size, True, term_color, font)
        apply_run_highlight(run, hl)
        pos = m.end()
    if pos < len(text) or pos == 0:
        run = p.add_run()
        run.text = text[pos:]
        set_run(run, size, bold, color, font)


def add_term_legend(slide, left, top, width=Inches(5.5)):
    """Small legend: feature_list vs checkbox highlight colors."""
    box = slide.shapes.add_textbox(left, top, width, Inches(0.35))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r0 = p.add_run()
    r0.text = "Color key:  "
    set_run(r0, 11, False, C_MUTED)
    r1 = p.add_run()
    r1.text = "feature_list"
    set_run(r1, 11, True, C_FEATURE)
    apply_run_highlight(r1, HL_FEATURE)
    r2 = p.add_run()
    r2.text = "   "
    set_run(r2, 11, False, C_MUTED)
    r3 = p.add_run()
    r3.text = "checkbox"
    set_run(r3, 11, True, C_CHECKBOX)
    apply_run_highlight(r3, HL_CHECKBOX)
    return box


def fill_text_frame(tf, lines, size=14, bold=False, color=None, align=PP_ALIGN.LEFT,
                    font="Calibri", line_spacing=1.15):
    """Write multi-line text with consistent spacing / wrapping."""
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(2)
        p.line_spacing = line_spacing
        if i == 0:
            p.text = ""
        add_runs_with_term_highlight(
            p, line if line is not None else "", size, bold, color, font
        )


def add_bg(slide, color=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color or C_BG
    shape.line.fill.background()
    spTree = slide.shapes._spTree
    sp = shape._element
    spTree.remove(sp)
    spTree.insert(2, sp)


def add_title_bar(slide, title, subtitle=None):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, TITLE_H)
    bar.fill.solid()
    bar.fill.fore_color.rgb = C_TITLE
    bar.line.fill.background()
    tf = bar.text_frame
    tf.margin_left = Pt(18)
    tf.margin_top = Pt(8)
    tf.margin_bottom = Pt(4)
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = title
    set_run(r, 22, True, C_WHITE)
    if subtitle:
        p2 = tf.add_paragraph()
        p2.space_before = Pt(2)
        r2 = p2.add_run()
        r2.text = subtitle
        set_run(r2, 12, False, RGBColor(0xCB, 0xD5, 0xE1))


def add_footer(slide, page, total):
    box = slide.shapes.add_textbox(MARGIN_L, FOOTER_TOP, CONTENT_W, Inches(0.28))
    tf = box.text_frame
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = f"DV AI Quality Layer  ·  SMC_CLOCK_GATING case  ·  {page} / {total}"
    set_run(r, 10, False, C_MUTED)


def add_text_box(slide, left, top, width, height, lines, size=14, bold=False,
                 color=None, align=PP_ALIGN.LEFT, font="Calibri"):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.margin_left = Pt(0)
    tf.margin_right = Pt(4)
    tf.margin_top = Pt(0)
    fill_text_frame(tf, lines if isinstance(lines, list) else [lines],
                    size=size, bold=bold, color=color, align=align, font=font)
    return box


def flow_box(slide, left, top, width, height, lines, fill, font_size=12):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = fill
    try:
        shape.adjustments[0] = 0.1
    except Exception:
        pass
    tf = shape.text_frame
    tf.margin_left = Pt(8)
    tf.margin_right = Pt(8)
    tf.margin_top = Pt(6)
    tf.margin_bottom = Pt(4)
    if isinstance(lines, str):
        lines = lines.split("\n")
    fill_text_frame(tf, lines, size=font_size, bold=True, color=C_WHITE,
                    align=PP_ALIGN.CENTER, line_spacing=1.1)
    return shape


def diamond(slide, left, top, width, height, lines, fill=C_WARN, font_size=11):
    shape = slide.shapes.add_shape(MSO_SHAPE.DIAMOND, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = fill
    tf = shape.text_frame
    tf.margin_left = Pt(10)
    tf.margin_right = Pt(10)
    tf.margin_top = Pt(10)
    if isinstance(lines, str):
        lines = lines.split("\n")
    fill_text_frame(tf, lines, size=font_size, bold=True, color=C_WHITE,
                    align=PP_ALIGN.CENTER, line_spacing=1.05)
    return shape


def arrow_right(slide, left, cy, length=0.28):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RIGHT_ARROW, left, cy - Inches(0.08), Inches(length), Inches(0.16)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = C_LINE
    shape.line.fill.background()
    return shape


def arrow_down(slide, cx, top, length=0.22):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.DOWN_ARROW, cx - Inches(0.1), top, Inches(0.2), Inches(length)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = C_LINE
    shape.line.fill.background()
    return shape


def card(slide, left, top, width, height, title, body_lines, title_color, body_size=12):
    hdr_h = Inches(0.4)
    hdr = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, hdr_h)
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = title_color
    hdr.line.fill.background()
    tf = hdr.text_frame
    tf.margin_left = Pt(8)
    tf.margin_top = Pt(6)
    fill_text_frame(tf, [title], size=13, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)

    body = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, left, top + hdr_h, width, height - hdr_h
    )
    body.fill.solid()
    body.fill.fore_color.rgb = C_WHITE
    body.line.color.rgb = C_LIGHT
    tf = body.text_frame
    tf.margin_left = Pt(12)
    tf.margin_right = Pt(10)
    tf.margin_top = Pt(10)
    tf.margin_bottom = Pt(8)
    if isinstance(body_lines, str):
        body_lines = body_lines.split("\n")
    fill_text_frame(tf, body_lines, size=body_size, bold=False, color=C_BLACK,
                    align=PP_ALIGN.LEFT, line_spacing=1.2)
    return hdr


def add_table(slide, left, top, width, rows, col_widths, font_size=11, row_h=0.42,
              header_fill=None, header_text=None):
    n_rows, n_cols = len(rows), len(rows[0])
    table_shape = slide.shapes.add_table(
        n_rows, n_cols, left, top, width, Inches(row_h * n_rows)
    )
    table = table_shape.table
    # Default: light header (readable; not near-black navy)
    hdr_fill = header_fill or RGBColor(0xDB, 0xEA, 0xFE)
    hdr_text = header_text or C_TITLE
    for i, w in enumerate(col_widths):
        table.columns[i].width = w
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = table.cell(r, c)
            cell.text = ""
            tf = cell.text_frame
            tf.word_wrap = True
            tf.margin_left = Pt(6)
            tf.margin_right = Pt(6)
            tf.margin_top = Pt(4)
            tf.margin_bottom = Pt(4)
            lines = val.split("\n") if isinstance(val, str) else [str(val)]
            is_h = r == 0
            fill_text_frame(
                tf, lines, size=font_size, bold=is_h,
                color=hdr_text if is_h else C_BLACK, align=PP_ALIGN.LEFT, line_spacing=1.1
            )
            cell.fill.solid()
            cell.fill.fore_color.rgb = (
                hdr_fill if is_h else (RGBColor(0xF1, 0xF5, 0xF9) if r % 2 == 0 else C_WHITE)
            )
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    return table_shape


def new_slide(title, subtitle=None):
    s = prs.slides.add_slide(blank)
    add_bg(s)
    add_title_bar(s, title, subtitle)
    slides_meta.append(s)
    return s


def evenly_spaced_boxes(n, box_w, gap=None, left=MARGIN_L, total_w=CONTENT_W):
    """Return list of left positions for n equal boxes aligned in content width."""
    if gap is None:
        gap = (total_w - n * box_w) / (n - 1) if n > 1 else 0
    return [left + i * (box_w + gap) for i in range(n)]



# ===================== SLIDES =====================
# Manager report: steps · key points · outcomes (no command / FESO detail)

# 1 Title
s = prs.slides.add_slide(blank)
add_bg(s, C_TITLE)
slides_meta.append(s)
add_text_box(s, MARGIN_L, Inches(2.2), CONTENT_W, Inches(0.7),
             ["AI-Assisted DV Quality Layer"], 36, True, C_WHITE)
add_text_box(s, MARGIN_L, Inches(3.2), CONTENT_W, Inches(1.2),
             ["What we added: Skill 1 → 1.5 → 2 → 3 quality loop",
              "What it delivers: clearer proof, earlier gaps, real RTL/sim bugs",
              "Case: SMC_CLOCK_GATING  (P0 / P1 / P2 Done)"],
             16, False, RGBColor(0xCB, 0xD5, 0xE1))
add_text_box(s, MARGIN_L, Inches(5.1), CONTENT_W, Inches(0.8),
             ["Does not replace FCOV, code coverage, regression, design review, or signoff"],
             13, False, RGBColor(0x94, 0xA3, 0xB8))

# 2 Agenda
s = new_slide("Agenda", "Steps · key points · outcomes")
agenda = [
    ("1", "Why this layer — the proof gap we close"),
    ("2", "What we build — intent vs evidence"),
    ("3", "Who signs what — Designer / DV / Peer / Signoff"),
    ("4", "How it runs — Skill 1 → 1.5 → 2 → 3"),
    ("5", "Shared policy — two audit scopes (Skill 2 vs Skill 3)"),
    ("6", "Case — SMC_CLOCK_GATING plan, tests, peer audit files"),
    ("7", "Outcome — bug found (#4413) and P1 loop result"),
]

label_w = Inches(1.2)
for i, (k, v) in enumerate(agenda):
    y = CONTENT_TOP + Inches(0.15) + i * Inches(0.78)
    flow_box(s, MARGIN_L, y, label_w, Inches(0.6), [k], C_TITLE, 16)
    add_text_box(s, MARGIN_L + label_w + Inches(0.35), y + Inches(0.1),
                 CONTENT_W - label_w - Inches(0.35), Inches(0.5), [v], 16, False, C_BLACK)

# 3 Why
s = new_slide("Why — the proof gap", "Coverage shows a test ran; it does not prove the right thing was checked")
ow = Inches(4.0)
xs = evenly_spaced_boxes(3, ow)
card(s, xs[0], CONTENT_TOP, ow, Inches(4.8),
     "Problem",
     ["AI / fast DV can produce tests that",
      "compile, PASS, and look complete —",
      "while proving little or nothing.",
      "",
      "Existing metrics (FCOV, CodeCov,",
      "regression) confirm existence and",
      "execution — not intent quality."],
     C_WARN, 14)
card(s, xs[1], CONTENT_TOP, ow, Inches(4.8),
     "Approach",
     ["Add an AI quality layer on top",
      "of the current DV flow.",
      "",
      "Three skills, one per phase:",
      "• Skill 1 — define the contract",
      "• Skill 2 — prove each test",
      "• Skill 3 — close the IP"],
     C_SKILL1, 14)
card(s, xs[2], CONTENT_TOP, ow, Inches(4.8),
     "Principle",
     ["AI drafts at volume.",
      "Humans own judgment.",
      "",
      "Skills never self-approve.",
      "Existing signoff still owns Done.",
      "",
      "Nothing in FCOV / regression",
      "/ design review is replaced."],
     C_OK, 14)

# 4 Two layers
s = new_slide("Key point — two layers kept separate",
              "Intent (what SPEC requires)  ≠  Evidence (what the test proved)")
add_table(s, MARGIN_L, CONTENT_TOP, CONTENT_W, [
    ["", "feature_list (intent)", "Checkbox sets (evidence)"],
    ["Answers", "What must be verified?", "Did each step execute correctly?"],
    ["Scope", "IP-wide requirements", "Per-testcase proof steps"],
    ["Built by", "Skill 1", "Skill 1"],
    ["Checked by", "Skill 3 (coverage closure)", "Skill 2 (self-audit)"],
    ["Owner gate", "Designer sign-off", "DV Owner sign-off"],
], [Inches(2.2), Inches(5.15), Inches(5.15)], 14, row_h=0.58)
add_text_box(s, MARGIN_L, Inches(5.45), CONTENT_W, Inches(0.95),
             ["Milestone closes only when:",
              "1) checkbox sets cover every required feature_list item, and",
              "2) every mapped checkbox is proven by retained log evidence."],
             14, False, C_MUTED)
add_term_legend(s, MARGIN_L, Inches(6.55), CONTENT_W)

# 5 Roles
s = new_slide("Who does what", "Clear ownership — AI never owns Done")
rw = Inches(3.0)
xs = evenly_spaced_boxes(4, rw)
roles = [
    (C_DES, "Designer / Architect",
     ["Owns intended behavior",
      "",
      "Signs off feature meaning",
      "and SPEC answers",
      "",
      "Gate after Skill 1"]),
    (C_DV, "DV Owner",
     ["Owns implementation",
      "and evidence",
      "",
      "Skill 1.5: from each checkbox,",
      "implement the matching checker",
      "",
      "Then Skill 2 audit + sign closure"]),
    (C_PEER, "Peer Reviewer",
     ["Owns quality findings",
      "(advisory only)",
      "",
      "Did not implement the IP",
      "",
      "Runs Skill 3"]),
    (C_OK, "Signoff Authority",
     ["Owns waivers and",
      "final Done",
      "",
      "Existing process retains",
      "milestone signoff",
      "",
      "AI never self-approves"]),
]
for x, (c, t, b) in zip(xs, roles):
    card(s, x, CONTENT_TOP, rw, Inches(5.4), t, b, c, 13)

# 6 Artifacts — role sign-off (no file names)
s = new_slide("Artifacts by role — who signs what",
              "Designer owns intent; DV owns proof mechanics")

col_w = Inches(6.05)
card(s, MARGIN_L, CONTENT_TOP, col_w, Inches(5.5),
     "Designer signs",
     ["Must sign:",
      "",
      "• feature_list",
      "  (what the SPEC requires)",
      "",
      "Also confirms:",
      "• SPEC open questions answered / waived",
      "• Feature ↔ proof mapping is correct",
      "",
      "Why it matters:",
      "If intent is wrong, every later PASS",
      "can prove the wrong thing.",
      "",
      "Gate: before any test is written."],
     C_DES, 14)
card(s, MARGIN_L + Inches(6.3), CONTENT_TOP, Inches(6.0), Inches(5.5),
     "DV Owner reviews / signs",
     ["Must review / sign:",
      "",
      "• checkbox sets (per-test proof steps)",
      "• Testcase set and ownership split",
      "• Deferred / out-of-milestone gaps",
      "",
      "Later also signs:",
      "• Skill 2 audit grades",
      "  (evidence-closed)",
      "",
      "Why it matters:",
      "Proof mechanics must be implementable",
      "and able to fail when wrong.",
      "",
      "Gate: before / during implementation."],
     C_DV, 14)

# 7 Three skills steps overview
s = new_slide("How it runs — four steps", "One chain from SPEC to milestone Done")
steps = [
    (C_SKILL1, "1. Plan", "Skill 1",
     ["Turn SPEC into an",
      "approvable contract",
      "",
      "feature_list:",
      "Designer approved",
      "",
      "checkbox sets:",
      "DV reviewed"]),
    (C_SKILL15, "2. Implement", "Skill 1.5",
     ["From each checkbox,",
      "implement its checker",
      "",
      "Run test; emit kept-log",
      "evidence tokens"]),
    (C_SKILL2, "3. Audit", "Skill 2",
     ["Is each checker",
      "correct + matches",
      "its checkbox?",
      "",
      "Re-audit if needed"]),
    (C_SKILL3, "4. Peer close", "Skill 3",
     ["IP-wide coverage",
      "+ intent review",
      "",
      "Then human signoff"]),
]
sw = Inches(2.85)
xs = evenly_spaced_boxes(4, sw)
for i, ((c, h, sk, lines), x) in enumerate(zip(steps, xs)):
    flow_box(s, x, CONTENT_TOP, sw, Inches(0.5), [h], c, 15)
    flow_box(s, x, CONTENT_TOP + Inches(0.58), sw, Inches(0.4), [sk], C_TITLE, 12)
    card(s, x, CONTENT_TOP + Inches(1.1), sw, Inches(3.4), "Focus", lines, c, 13)
    if i < 3:
        arrow_right(s, x + sw, CONTENT_TOP + Inches(0.18), 0.22)

add_text_box(s, MARGIN_L, Inches(5.8), CONTENT_W, Inches(0.8),
             ["Loops are expected:  NOT-READY → rework → re-audit  ·  gap → amend plan → re-prove  ·  peer FAIL → fix → re-review"],
             12, False, C_MUTED)

# 8 Skill 1 flow (manager)
s = new_slide("Step 1 — Skill 1  (Plan)", "Build the verification contract before coding")
nw = Inches(2.2)
xs = evenly_spaced_boxes(5, nw)
nodes = [
    ("Pinned SPEC\n+ scope", C_MUTED),
    ("Draft\nfeature_list", C_SKILL1),
    ("Plan +\ncards", C_SKILL1),
    ("Review\npackets", C_SKILL1),
    ("Human\napprove", C_WARN),
]
for i, ((lab, col), x) in enumerate(zip(nodes, xs)):
    flow_box(s, x, CONTENT_TOP, nw, Inches(1.15), lab, col, 13)
    if i < 4:
        arrow_right(s, x + nw, CONTENT_TOP + Inches(0.5), 0.2)

ow = Inches(6.05)
card(s, MARGIN_L, Inches(2.7), ow, Inches(3.5),
     "Key points",
     ["• Turns SPEC into atomic features + per-test checkboxes",
      "• Designer signs intent; DV signs test set / cards",
      "• Quality ceiling is set here — a bad plan makes later",
      "  audits prove the wrong thing",
      "• Amend later if a card is unobservable or incomplete"],
     C_SKILL1, 14)
card(s, MARGIN_L + Inches(6.3), Inches(2.7), Inches(6.0), Inches(3.5),
     "Outcome of this step",
     ["Approved feature_list",
      "Approved Testcase Plan",
      "Approved checkbox cards",
      "",
      "→ ready for Skill 1.5 implementation"],
     C_OK, 14)

# 9 Skill 1.5
s = new_slide("Step 2 — Skill 1.5  (Implement)",
              "From each approved checkbox → implement its checker (+ evidence token)")
bw = Inches(3.9)
xs = evenly_spaced_boxes(3, bw)
for (lab, col), x in zip([
    ("Approved\ncheckbox card", C_OK),
    ("Implement checker\nper checkbox", C_SKILL15),
    ("Kept log has\nall evidence tokens?", C_WARN),
], xs):
    flow_box(s, x, CONTENT_TOP, bw, Inches(1.1), lab, col, 13)
arrow_right(s, xs[0] + bw, CONTENT_TOP + Inches(0.45), 0.35)
arrow_right(s, xs[1] + bw, CONTENT_TOP + Inches(0.45), 0.35)

card(s, MARGIN_L, Inches(2.7), Inches(6.05), Inches(3.5),
     "Principle",
     ["• Implement checkers from the approved checkbox set",
      "  — one checkbox → one real checker (not a free-form test)",
      "• Does not grade and does not claim PROVEN",
      "• Strongest claim: run finished and evidence tokens appeared",
      "• No DUT force / deposit on the proof path",
      "• If a checkbox is unobservable → back to Skill 1"],
     C_SKILL15, 13)
card(s, MARGIN_L + Inches(6.3), Inches(2.7), Inches(6.0), Inches(3.5),
     "Outcome of this step",
     ["Checkers wired to checkboxes",
      "Runnable test enrolled",
      "Kept log with evidence tokens",
      "",
      "→ handoff to Skill 2 audit"],
     C_OK, 13)

# 10 Skill 2
s = new_slide("Step 3 — Skill 2  (Audit)",
              "Is each checker correct — and does it match its checkbox?")
bw = Inches(3.9)
xs = evenly_spaced_boxes(3, bw)
for (lab, col), x in zip([
    ("Fresh audit", C_SKILL2),
    ("Checker correct\n+ matches checkbox", C_SKILL2),
    ("CLOSED or\nNOT-READY", C_WARN),
], xs):
    flow_box(s, x, CONTENT_TOP, bw, Inches(1.1), lab, col, 13)
arrow_right(s, xs[0] + bw, CONTENT_TOP + Inches(0.45), 0.35)
arrow_right(s, xs[1] + bw, CONTENT_TOP + Inches(0.45), 0.35)

card(s, MARGIN_L, Inches(2.6), Inches(6.05), Inches(3.6),
     "Principle",
     ["• Audit: is each checker correct?",
      "  (can fail when RTL / behavior is wrong)",
      "• Audit: does each checker match its checkbox?",
      "  (checkbox ↔ logged-proof evidence token)",
      "• Also scored against DV_QUALITY_POLICY",
      "• Simulation PASS starts the audit — not the finish",
      "• NOT-READY → rework → re-audit; DV signs closed"],
     C_SKILL2, 13)
card(s, MARGIN_L + Inches(6.3), Inches(2.6), Inches(6.0), Inches(3.6),
     "Outcome of this step",
     ["Per-checker grade report",
      "Checker ↔ checkbox alignment proven",
      "Rework / re-audit loop closed",
      "Card evidence-closed",
      "",
      "→ when all cards closed: Skill 3"],
     C_OK, 13)

# 11 Skill 3
s = new_slide("Step 4 — Skill 3  (Peer close)",
              "Checked by peer — independent of the implementer / Skill 2 auditor")
bw = Inches(3.9)
xs = evenly_spaced_boxes(3, bw)
for (lab, col), x in zip([
    ("All cards\nCLOSED", C_OK),
    ("Checked by peer\n(independent)", C_SKILL3),
    ("Pass / Fail /\nInsufficient", C_WARN),
], xs):
    flow_box(s, x, CONTENT_TOP, bw, Inches(1.1), lab, col, 13)
arrow_right(s, xs[0] + bw, CONTENT_TOP + Inches(0.45), 0.35)
arrow_right(s, xs[1] + bw, CONTENT_TOP + Inches(0.45), 0.35)

card(s, MARGIN_L, Inches(2.6), Inches(6.05), Inches(3.6),
     "Principle",
     ["• Checked by peer — not the same person / model",
      "  who implemented or ran Skill 2",
      "• Defining job: do all checkboxes cover the feature_list?",
      "• Also catches wrong-target / never-wired intent gaps",
      "• Advisory only — no tracker / Done authority",
      "• FAIL / Insufficient → fix → peer re-check"],
     C_SKILL3, 13)
card(s, MARGIN_L + Inches(6.3), Inches(2.6), Inches(6.0), Inches(3.6),
     "Outcome of this step",
     ["Peer-checked findings + one result",
      "Coverage holes surfaced",
      "Feeds existing signoff",
      "",
      "→ Milestone Done (human)"],
     C_OK, 13)

# 12 Shared policy — Skill 2 vs Skill 3 scopes
s = new_slide("Shared policy — two audit scopes",
              "Same guideline file; different compare targets and methods")

flow_box(s, MARGIN_L, CONTENT_TOP, CONTENT_W, Inches(0.95),
         ["Pinned quality guideline (both Skill 2 and Skill 3 read it)",
          "DV_QUALITY_POLICY.md  —  forbidden patterns, PASS definition, severity / sampling rules"],
         C_TITLE, 13)

cw = Inches(6.05)
card(s, MARGIN_L, Inches(2.45), cw, Inches(2.85),
     "Skill 2 — one test, deep",
     ["Compares:",
      "checkbox set  ↔  logged-proof",
      "+  DV_QUALITY_POLICY rules",
      "",
      "Asks: is each checker correct,",
      "does it match its checkbox,",
      "and does it break any policy pattern?"],
     C_SKILL2, 13)
card(s, MARGIN_L + Inches(6.3), Inches(2.45), Inches(6.0), Inches(2.85),
     "Skill 3 — whole IP, wide",
     ["Compares:",
      "feature_list  ↔  checkbox union",
      "(from all CLOSED / green cards)",
      "+  same DV_QUALITY_POLICY",
      "",
      "Asks: do all green cards cover the SPEC,",
      "and do intent / sampling findings still",
      "break policy at IP scope?"],
     C_SKILL3, 13)

flow_box(s, MARGIN_L, Inches(5.5), CONTENT_W, Inches(1.1),
         ["Why two scopes help the workflow",
          "Skill 2 stops a hollow PASS before peer time is spent.  "
          "Skill 3 stops “every test looks green” while the feature_list still has holes.  "
          "One policy keeps both audits scoring the same quality bar."],
         C_OK, 13)

# 13 Case artifacts — how Skills 1/2/3 planned & implemented SMC clock gating
s = new_slide("Case — SMC_CLOCK_GATING plan & implementation",
              "Skill 1 / 2 / 3 outputs with example file names under hw/sys/smc/dv/tb/")

# Three columns
cw = Inches(4.0)
xs = evenly_spaced_boxes(3, cw)
card(s, xs[0], CONTENT_TOP, cw, Inches(5.5),
     "Skill 1 — Plan",
     ["Build feature_list + testplan + cards",
      "",
      "Reviewed files (sign-off):",
      "• SMC_CLOCK_GATING_FEATURE_REVIEW.md",
      "• SMC_CLOCK_GATING_SPEC_REVIEW.md",
      "• SMC_CLOCK_GATING_TESTCASE_REVIEW.md",
      "• SMC_CLOCK_GATING_CARD_REVIEW.md",
      "",
      "Contract / testplan:",
      "• SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md",
      "• SMC_CLOCK_GATING_TESTCASE_PLAN.md",
      "• SMC_CLOCK_GATING_VPLAN_DETAIL.md"],
     C_SKILL1, 11)
card(s, xs[1], CONTENT_TOP, cw, Inches(5.5),
     "Skill 1.5 + 2 — Implement & audit",
     ["Implement one approved card → audit",
      "",
      "Testcase example:",
      "• smc_dma_cg_activity_test.py",
      "• smc_dma_cg_activity_test_seq.py",
      "",
      "Also implemented:",
      "• smc_cg_test_mode_bypass_test",
      "  (DFT / test_en → #4413)",
      "",
      "Skill 2 grade example:",
      "• smc_dma_cg_activity_test_GRADE.md",
      "",
      "Status board:",
      "• audit_status_smc_clock_gating.md"],
     C_SKILL2, 11)
card(s, xs[2], CONTENT_TOP, cw, Inches(5.5),
     "Skill 3 — Peer close",
     ["IP-wide coverage + intent review",
      "",
      "Peer audit report:",
      "• SMC_CLOCK_GATING_PEER_AUDIT.md",
      "",
      "Reverse inventory:",
      "• SMC_CLOCK_GATING_REVERSE_",
      "  FEATURE_INVENTORY.md",
      "",
      "Pin + shared policy:",
      "• SMC_CLOCK_GATING_PIN.yaml",
      "• DV_QUALITY_POLICY.md",
      "",
      "Result path:",
      "INSUFF → FAIL → amend →",
      "PASS 19/19 CLEAN"],
     C_SKILL3, 11)

# 14 Bug page — clean layout for managers
s = new_slide("Outcome — real bug found (#4413)",
              "Skill 1 extracted the feature_list from SPEC — the gap was a SPEC claim, not an RTL leftover")

# Top: context + bug (short)
flow_box(s, MARGIN_L, CONTENT_TOP, CONTENT_W, Inches(1.55),
         ["Key message",
          "Skill 1 extracted the feature_list from SPEC (not from existing RTL / tests).",
          "DFT / test_en bypass was a SPEC requirement that prior RTL-facing tests never forced,",
          "so implementing that claim exposed a silent sim / model hole (#4413)."],
         C_BUG, 13)

# Bottom two equal cards: Skill1 vs Skill2 catch path
cw = Inches(6.05)
card(s, MARGIN_L, Inches(2.95), cw, Inches(3.5),
     "How Skill 1 raised the bar to SPEC",
     ["Skill 1 extracts the feature_list from SPEC",
      "— requirements RTL-facing tests may miss.",
      "",
      "Before: tests covered RTL that was already",
      "implemented and wired.",
      "",
      "From SPEC: DFT / test-mode bypass was a",
      "required feature_list item and checkbox:",
      "when test_en is on, gated clocks must run."],
     C_SKILL1, 13)
card(s, MARGIN_L + Inches(6.3), Inches(2.95), Inches(6.0), Inches(3.5),
     "How Skill 1.5 + Skill 2 caught it",
     ["Skill 1.5 implemented the SPEC checkbox",
      "and ran gating-on + test_en asserted.",
      "",
      "Observed: gated clocks stayed off",
      "(SPEC expects free-run).",
      "",
      "Skill 2 graded against the audit principle",
      "— checker could not be PROVEN.",
      "",
      "Result: filed as #4413."],
     C_SKILL2, 13)

# 15 Timeline — cleaner layout / colors
s = new_slide("Outcome — P1 loop at a glance",
              "Rework and re-review are part of the value")

# Phase bands
phases = [
    ("Implement", C_SKILL15, ["Write tests", "Emit evidence"]),
    ("Audit", C_SKILL2, ["NOT-READY first", "Then CLOSED"]),
    ("Peer", C_SKILL3, ["INSUFF → FAIL", "Then PASS"]),
    ("Close", C_OK, ["Amend + re-prove", "Owner signoff"]),
]
pw = Inches(2.95)
px = evenly_spaced_boxes(4, pw)
for (title, color, lines), x in zip(phases, px):
    flow_box(s, x, CONTENT_TOP, pw, Inches(0.55), [title], color, 16)
    card(s, x, CONTENT_TOP + Inches(0.65), pw, Inches(1.7), "Result", lines, color, 14)
for i in range(3):
    arrow_right(s, px[i] + pw, CONTENT_TOP + Inches(0.2), 0.22)

# Takeaway cards — color coded
tw = Inches(6.05)
card(s, MARGIN_L, Inches(3.8), tw, Inches(2.6),
     "What improved",
     ["• Hollow checks did not get a free PASS",
      "• Missing SPEC interaction was found and amended",
      "• DFT / test_en gap became a filed bug (#4413)"],
     C_OK, 14)
card(s, MARGIN_L + Inches(6.3), Inches(3.8), Inches(6.0), Inches(2.6),
     "What stayed the same",
     ["• Designer / DV re-approve contract changes",
      "• Peer remains advisory only",
      "• Final Done stays with human signoff"],
     C_TITLE, 14)

total = len(slides_meta)
for i, slide in enumerate(slides_meta):
    if i == 0:
        continue
    add_footer(slide, i + 1, total)

prs.save(OUT)
print(f"Wrote {OUT}")
print(f"Slides: {total}")
