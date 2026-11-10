"""Shoot plan as a PDF: the script first, then one page per setup in shoot order.

Pure: `render_plan_pdf(title, plan, beats) -> bytes`. Printable and readable on a phone.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from stylecut.schemas.shoot_plan import PlannedShot, ShootPlan

_base = getSampleStyleSheet()
TITLE = ParagraphStyle("title", parent=_base["Title"], fontSize=20, leading=24, alignment=0)
H2 = ParagraphStyle("h2", parent=_base["Heading2"], fontSize=14, leading=18, spaceBefore=8)
BODY = ParagraphStyle("body", parent=_base["BodyText"], fontSize=10.5, leading=15)
MUTED = ParagraphStyle("muted", parent=BODY, textColor=colors.HexColor("#6b6560"), fontSize=9.5)
SHOT = ParagraphStyle("shot", parent=BODY, leftIndent=8 * mm, spaceBefore=2)
HEAD = ParagraphStyle("head", parent=BODY)
TICK_COLUMN = 8 * mm


class TickBox(Flowable):
    """An empty square to tick with a pen. Drawn, not typed: fonts lack a reliable glyph."""

    def __init__(self, size: float = 3.6 * mm) -> None:
        super().__init__()
        self.width = self.height = size

    def draw(self) -> None:
        self.canv.setLineWidth(0.9)
        self.canv.rect(0, 0, self.width, self.height, stroke=1, fill=0)


def _p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def _shot_block(shot: PlannedShot, lines: dict[str, str], width: float) -> list[object]:
    takes = f"{shot.takes} take{'s' if shot.takes != 1 else ''}"
    must = ", must-have" if shot.priority == "must" else ""
    head = Paragraph(
        f"<b>{escape(shot.id)}</b> &nbsp;{escape(shot.description)} "
        f"<font color='#6b6560'>({shot.framing}, {shot.camera_motion.replace('_', ' ')}, "
        f"record {shot.record_s:g}s, {takes}{must})</font>",
        HEAD,
    )
    row = Table([[TickBox(), head]], colWidths=[TICK_COLUMN, width - TICK_COLUMN])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    block: list[object] = [row]
    spoken = " ".join(lines[i] for i in shot.line_ids if i in lines)
    if spoken:
        block.append(Paragraph(f"<i>Say:</i> “{escape(spoken)}”", SHOT))
    block.append(Paragraph(escape(shot.direction), SHOT))
    if shot.alternatives:
        block.append(
            Paragraph("If you can't get it: " + escape("; ".join(shot.alternatives)), SHOT)
        )
    return block


def render_plan_pdf(title: str, plan: ShootPlan, beat_labels: dict[str, str]) -> bytes:
    """`beat_labels` maps beat id -> label for the script section headings."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=title, author="StyleCut",
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
    )  # fmt: skip
    story: list[object] = [
        _p(escape(title), TITLE),
        _p(
            f"{plan.target_duration_s:g}s video · {len(plan.shots)} shots · "
            f"{len(plan.setups)} setup{'s' if len(plan.setups) != 1 else ''} · "
            f"{plan.word_budget} word budget",
            MUTED,
        ),
    ]
    if plan.title_options:
        story += [_p("On-screen title options", H2)]
        story += [_p(f"• {escape(option)}") for option in plan.title_options]

    story.append(_p("Script", H2))
    if not plan.script:
        story.append(_p("No spoken script: this style has no speech.", MUTED))
    current_beat = None
    for line in plan.script:
        if line.beat_id != current_beat:
            current_beat = line.beat_id
            story.append(_p(f"<b>{escape(beat_labels.get(line.beat_id, line.beat_id))}</b>", MUTED))
        note = (
            f" <font color='#6b6560'>({escape(line.delivery_note)})</font>"
            if line.delivery_note
            else ""
        )
        story.append(_p(f"{escape(line.text)}{note}"))

    if plan.checklist_notes:
        story.append(_p("Before you start", H2))
        story += [_p(f"• {escape(note)}") for note in plan.checklist_notes]
    if plan.music_brief:
        story += [_p("Music", H2), _p(escape(plan.music_brief))]
    if plan.warnings:
        story.append(_p("Worth a second look", H2))
        story += [_p(f"• {escape(warning)}") for warning in plan.warnings]

    lines = {line.id: line.text for line in plan.script}
    shots = {shot.id: shot for shot in plan.shots}
    setups = {setup.id: setup for setup in plan.setups}
    setup_order = list(dict.fromkeys(shots[i].setup_id for i in plan.shoot_order if i in shots))
    for number, setup_id in enumerate(setup_order, start=1):
        story.append(PageBreak())
        setup = setups.get(setup_id)
        heading = f"Setup {number} of {len(setup_order)}"
        if setup is not None:
            heading += f": {escape(setup.location)}"
        story.append(_p(heading, H2))
        if setup is not None:
            story.append(_p(f"<b>Framing:</b> {escape(setup.framing_summary)}"))
            story.append(_p(f"<b>Light:</b> {escape(setup.lighting)}"))
            story.append(_p(f"<b>Sound:</b> {escape(setup.audio)}"))
            if setup.props:
                story.append(_p(f"<b>Props:</b> {escape(', '.join(setup.props))}"))
        story.append(Spacer(1, 4 * mm))
        for shot_id in plan.shoot_order:
            shot = shots.get(shot_id)
            if shot is not None and shot.setup_id == setup_id:
                story += _shot_block(shot, lines, doc.width)

    doc.build(story)
    return buffer.getvalue()
