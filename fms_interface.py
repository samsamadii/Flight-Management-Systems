"""Shared presentation tokens and interactions for the FMS desktop UI."""

from dataclasses import fields

import flet as ft


GAP = 12
CARD_RADIUS = 10
CONTROL_RADIUS = 7
NAV_HEIGHT = 52
CONTEXT_HEIGHT = 48
SHELL_HEIGHT = NAV_HEIGHT + CONTEXT_HEIGHT
UI_FONT = "Jost"
UI_FONT_ASSET = "fonts/Jost.ttf"
SURFACE_OPACITY = 0.50
NAV_OPACITY = 0.60
AIRLINE_GRADIENT_END = "#949494"
AIRLINE_GRADIENT_STARTS = {
    "Cathay Pacific": "#043800",
}


def surface_fill(color):
    if not color or color == ft.Colors.TRANSPARENT:
        return color
    return ft.Colors.with_opacity(SURFACE_OPACITY, str(color).split(",", 1)[0])


def airline_background(airline, accents):
    if not airline:
        return None
    brand = AIRLINE_GRADIENT_STARTS.get(airline) or accents.get(airline, accents["Generic"])
    return ft.LinearGradient(
        begin=ft.Alignment(-1, -1),
        end=ft.Alignment(1, 1),
        # Hold the brand color so the midpoint of the fade is 70% down the diagonal.
        colors=[brand, brand, AIRLINE_GRADIENT_END],
        stops=[0, 0.40, 1],
    )

LIGHT = {
    "bg": "#D9DFE2",
    "panel": "#FAFBFC",
    "subpanel": "#EDF0F2",
    "input_bg": "#E6E1DA",
    "pressed": "#DCE2E6",
    "text": "#171B20",
    "muted": "#505C66",
    "card_border": "#C8D0D6",
    "accent": "#4E47BC",
    "shell_topbar": "#E4E9EC",
    "primary": "#131619",
    "on_primary": "#FFFFFF",
    "primary_hover": "#292E33",
}

DARK = {
    "bg": "#1C2127",
    "panel": "#292F36",
    "subpanel": "#323A43",
    "input_bg": "#22282F",
    "pressed": "#3E4852",
    "text": "#F1F4F6",
    "muted": "#C1C9D0",
    "card_border": "#48525B",
    "accent": "#AAA4FF",
    "shell_topbar": "#242A30",
    "primary": "#F2F4F5",
    "on_primary": "#171B20",
    "primary_hover": "#DCE2E6",
}


def button_style(tokens, *, primary=False, circular=False, translucent=False):
    fill = surface_fill if translucent else lambda color: color
    return ft.ButtonStyle(
        color={
            ft.ControlState.DEFAULT: tokens["on_primary"] if primary else tokens["text"],
            ft.ControlState.DISABLED: tokens["muted"],
        },
        bgcolor={
            ft.ControlState.HOVERED: fill(tokens["primary_hover"] if primary else tokens["subpanel"]),
            ft.ControlState.PRESSED: fill(tokens["primary_hover"] if primary else tokens["pressed"]),
            ft.ControlState.DEFAULT: fill(tokens["primary"] if primary else tokens["panel"]),
            ft.ControlState.DISABLED: fill(tokens["subpanel"]),
        },
        elevation=0,
        icon_size=17,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        shape=ft.CircleBorder() if circular else ft.RoundedRectangleBorder(radius=CONTROL_RADIUS),
        side={
            ft.ControlState.FOCUSED: ft.BorderSide(2, tokens["accent"]),
            ft.ControlState.DEFAULT: ft.BorderSide(1, tokens["card_border"]),
        },
    )


def _set_hover_scale(control, hovered):
    scale = 1.035 if hovered and not control.disabled else 1
    if control.scale != scale:
        control.scale = scale
        control.update()


def _hover_scale(event):
    _set_hover_scale(event.control, event.data == "true")


def with_hover(control):
    return ft.Container(
        content=control,
        animate_scale=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
        on_hover=_hover_scale,
    )


def prepare_controls(*roots):
    """Give clickable controls hover feedback without replacing their actions."""
    buttons = (ft.Button, ft.FilledButton, ft.OutlinedButton, ft.TextButton, ft.IconButton)
    pending = list(roots)
    seen = set()
    while pending:
        control = pending.pop()
        if not isinstance(control, ft.BaseControl) or id(control) in seen:
            continue
        seen.add(id(control))
        if (
            isinstance(control, ft.GestureDetector)
            and control.mouse_cursor == ft.MouseCursor.CLICK
            and (control.on_tap is not None or control.on_tap_down is not None)
            and control.on_enter is None and control.on_exit is None and control.scale is None
        ):
            control.animate_scale = ft.Animation(120, ft.AnimationCurve.EASE_OUT)
            control.on_enter = lambda e: _set_hover_scale(e.control, True)
            control.on_exit = lambda e: _set_hover_scale(e.control, False)
        elif (
            (isinstance(control, buttons) or isinstance(control, ft.Container) and control.on_click is not None)
            and control.on_hover is None and control.scale is None
        ):
            control.animate_scale = ft.Animation(120, ft.AnimationCurve.EASE_OUT)
            control.on_hover = _hover_scale
        for item in fields(control):
            if item.name.startswith("_"):
                continue
            value = getattr(control, item.name)
            if isinstance(value, ft.BaseControl):
                pending.append(value)
            elif isinstance(value, (list, tuple)):
                pending.extend(child for child in value if isinstance(child, ft.BaseControl))
