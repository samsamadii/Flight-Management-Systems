"""Vector cabin diagrams built from FMS's existing aircraft rows."""

from itertools import groupby

import flet as ft


CANVAS_WIDTH = 456
FLOOR_WIDTH = 388
FLOOR = "#424E5A"
SEAT_BLUE = "#1A609C"
SEAT_YELLOW = "#E6B510"
SEAT_RED = "#B83930"

# Width, height, and longitudinal pitch. The deck width and endcaps stay fixed.
SEAT_GEOMETRY = {
    "First": (48, 96, 112),
    "Business": (38, 56, 91),
    "Premium Economy": (32, 38, 65),
    "Economy": (28, 25, 54),
}


def seat_artwork(label, cabin, width, height, color, text_color, tooltip, on_click):
    """Return the clickable seat and the two controls updated by occupancy."""
    suite = cabin == "First"
    tall = cabin in ("First", "Business")
    top = 38 if suite else 2
    back = ft.Container(
        left=4, right=4, top=top, bottom=4,
        bgcolor=color, border_radius=5 if tall else 3,
        border=ft.Border.all(0.7, "#95A6B4"),
        animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
    )
    label_size = 9 if tall else (8 if len(label) <= 3 else 7)
    text = ft.Text(label, size=label_size, weight=ft.FontWeight.W_600, color=text_color, no_wrap=True)
    components = [
        ft.Container(left=3, right=3, top=top + 1, bottom=0, bgcolor="#85929D", border_radius=6),
        back,
        ft.Container(left=3, right=3, top=top + (7 if tall else 3), alignment=ft.Alignment(0, 0), content=text),
        ft.Container(
            left=width * 0.24, right=width * 0.24, bottom=7 if tall else 5,
            height=7 if tall else 3, bgcolor="#F8FAFC", border_radius=4,
        ),
        ft.Container(left=1, width=3, top=top + 5, bottom=7, bgcolor="#C1CAD2", border_radius=2),
        ft.Container(right=1, width=3, top=top + 5, bottom=7, bgcolor="#C1CAD2", border_radius=2),
    ]
    if suite:
        components[:0] = [
            ft.Container(left=0, right=0, top=0, bottom=0, bgcolor="#AAB6C0", border_radius=3),
            ft.Container(left=2, right=2, top=4, bottom=4, bgcolor="#5C6874", border_radius=3),
            ft.Container(
                left=4, right=4, top=2, height=24, bgcolor=SEAT_BLUE,
                border_radius=ft.BorderRadius(0, 0, 9, 9),
            ),
            ft.Container(left=0, right=0, top=0, height=3, bgcolor="#DFE7EC"),
            ft.Container(left=0, right=0, bottom=0, height=2, bgcolor="#DFE7EC"),
        ]
    return ft.Container(
        width=width, height=height, tooltip=tooltip, on_click=on_click, ink=True,
        content=ft.Stack(components, width=width, height=height, clip_behavior=ft.ClipBehavior.NONE),
    ), back, text


def _seat_row(row, make_seat, highlight, *, single_aisle=False):
    seat_width, height, pitch = SEAT_GEOMETRY[row["cabin"]]
    groups = row["groups"]
    if single_aisle:
        aisle_width = 36 if len(groups) == 2 else 0
        seat_width = min(seat_width * 2, (FLOOR_WIDTH - 10 - aisle_width) / sum(map(len, groups)))
        height *= 2
        pitch *= 2
    existing = set(row["existing_seats"])
    seats = []
    for index, group in enumerate(groups):
        block_width = len(group) * seat_width
        if len(groups) == 1:
            start = (FLOOR_WIDTH - block_width) / 2
        elif index == 0:
            start = 5
        elif index == len(groups) - 1:
            start = FLOOR_WIDTH - block_width - 5
        else:
            start = (FLOOR_WIDTH - block_width) / 2
        for offset, letter in enumerate(group):
            if letter in existing:
                window_seat = (index == 0 and offset == 0) or (
                    index == len(groups) - 1 and offset == len(group) - 1
                )
                highlighted = highlight and (row["cabin"] in ("Premium Economy", "Economy") or window_seat)
                seats.append(ft.Container(
                    left=start + offset * seat_width, top=(pitch - height) / 2,
                    content=make_seat(row, letter, seat_width - 1, height, highlighted),
                ))
    return ft.Stack(seats, width=FLOOR_WIDTH, height=pitch, clip_behavior=ft.ClipBehavior.NONE)


def _service_bay():
    def fixture(width, symbol, label):
        return ft.Container(
            width=width, height=37, bgcolor="#9CADBE",
            border_radius=4, tooltip=label,
            border=ft.Border(bottom=ft.BorderSide(9, "#B8C6D3")),
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(symbol, size=18, color="#394D5E"),
        )

    return ft.Container(
        height=74, padding=ft.Padding.symmetric(horizontal=4),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                fixture(68, ft.Icons.WC, "Lavatory"),
                fixture(112, ft.Icons.RESTAURANT, "Galley"),
                fixture(68, ft.Icons.WC, "Lavatory"),
            ],
        ),
    )


def cabin_diagram(rows, make_seat, *, single_aisle=False):
    body = []
    for cabin, row_group in groupby(rows, key=lambda row: row["cabin"]):
        if body and not single_aisle:
            body.append(_service_bay())
        body.append(ft.Container(
            height=28, padding=ft.Padding.symmetric(horizontal=8),
            alignment=ft.Alignment(0, 0), bgcolor="#3A4651",
            content=ft.Text(cabin.upper(), size=10, color="#E0E8EF", weight=ft.FontWeight.W_700),
        ))
        for index, row in enumerate(row_group):
            after_exit = index > 0 and index % 12 == 0
            if after_exit and not single_aisle:
                body.append(_service_bay())
            body.append(_seat_row(row, make_seat, highlight=(index == 0 and cabin != "First") or after_exit,
                                  single_aisle=single_aisle))

    if not body:
        body.append(ft.Container(
            height=48, alignment=ft.Alignment(0, 0),
            content=ft.Text("No seats on this deck", size=12, color="#E0E8EF"),
        ))
    walls = ft.Container(
        width=420, bgcolor="#C9D4DE",
        border=ft.Border(left=ft.BorderSide(8, "#E8EDF1"), right=ft.BorderSide(8, "#E8EDF1")),
        padding=ft.Padding.symmetric(horizontal=8),
        content=ft.Container(bgcolor=FLOOR, content=ft.Column(body, spacing=0)),
    )
    return ft.Container(
        width=CANVAS_WIDTH, bgcolor=ft.Colors.TRANSPARENT,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        content=ft.Column(
            spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Image(src="cabin/nose.svg", width=CANVAS_WIDTH, height=448),
                walls,
                ft.Image(src="cabin/tail.svg", width=CANVAS_WIDTH, height=522),
            ],
        ),
    )
