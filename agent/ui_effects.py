"""Modern Cyber-Kinetic UI Effects & Gradient Engine for Focus Agent.

Provides cached, high-performance Pillow/Tkinter gradient generators:
- Linear horizontal/vertical spectral gradients
- Glassmorphism rounded cards with top-rim accent luminescence
- Dynamic gradient progress meters
- Interactive glowing gradient buttons with hover transitions
"""

import math
from typing import Tuple, Optional
from PIL import Image, ImageDraw, ImageTk
import tkinter as tk


def hex_to_rgb(hex_code: str) -> Tuple[int, int, int]:
    hex_code = hex_code.lstrip("#")
    if len(hex_code) == 3:
        hex_code = "".join(c * 2 for c in hex_code)
    return tuple(int(hex_code[i : i + 2], 16) for i in (0, 2, 4))


def interpolate_rgb(c1: Tuple[int, int, int], c2: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    factor = max(0.0, min(1.0, factor))
    return (
        int(c1[0] + (c2[0] - c1[0]) * factor),
        int(c1[1] + (c2[1] - c1[1]) * factor),
        int(c1[2] + (c2[2] - c1[2]) * factor),
    )


def create_horizontal_gradient_image(
    width: int,
    height: int,
    color1: str,
    color2: str,
    color3: Optional[str] = None,
    corner_radius: int = 0,
) -> Image.Image:
    """Generate a high-resolution horizontal multi-stop gradient image."""
    width = max(2, width)
    height = max(2, height)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2)
    rgb3 = hex_to_rgb(color3) if color3 else None

    for x in range(width):
        factor = x / float(width - 1)
        if rgb3:
            if factor < 0.5:
                col = interpolate_rgb(rgb1, rgb2, factor * 2.0)
            else:
                col = interpolate_rgb(rgb2, rgb3, (factor - 0.5) * 2.0)
        else:
            col = interpolate_rgb(rgb1, rgb2, factor)
        draw.line([(x, 0), (x, height - 1)], fill=col + (255,))

    if corner_radius > 0:
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (width - 1, height - 1)], radius=corner_radius, fill=255)
        img.putalpha(mask)

    return img


def create_vertical_gradient_image(
    width: int,
    height: int,
    color_top: str,
    color_bot: str,
    corner_radius: int = 0,
) -> Image.Image:
    """Generate a vertical gradient image."""
    width = max(2, width)
    height = max(2, height)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    rgb_t = hex_to_rgb(color_top)
    rgb_b = hex_to_rgb(color_bot)

    for y in range(height):
        factor = y / float(height - 1)
        col = interpolate_rgb(rgb_t, rgb_b, factor)
        draw.line([(0, y), (width - 1, y)], fill=col + (255,))

    if corner_radius > 0:
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (width - 1, height - 1)], radius=corner_radius, fill=255)
        img.putalpha(mask)

    return img


def create_glass_card_image(
    width: int,
    height: int,
    color_top: str = "#181A22",
    color_bot: str = "#111319",
    border_color: str = "#2B2F3D",
    accent_rim: str = "#444B60",
    corner_radius: int = 10,
) -> Image.Image:
    """Generate a sleek frosted glass card background with specular top frost highlight."""
    base = create_vertical_gradient_image(width, height, color_top, color_bot, corner_radius=corner_radius)
    draw = ImageDraw.Draw(base)

    # Draw rounded border stroke
    draw.rounded_rectangle(
        [(0, 0), (width - 1, height - 1)],
        radius=corner_radius,
        outline=border_color,
        width=1,
    )

    # Frosted top specular rim highlight
    rim_rgb = hex_to_rgb(accent_rim)
    for x in range(corner_radius, width - corner_radius):
        factor = abs(x - (width / 2.0)) / (width / 2.0)
        alpha = int(220 * (1.0 - factor * 0.7))
        draw.point((x, 0), fill=rim_rgb + (alpha,))

    return base


class GradientButton(tk.Label):
    """Frosted matte button with 1px border highlight and smooth hover transition."""

    def __init__(
        self,
        parent,
        text: str,
        command,
        width_px: int = 180,
        height_px: int = 42,
        color1: str = "#1E222C",
        color2: str = "#151820",
        hover_color1: str = "#2A2F3D",
        hover_color2: str = "#1E222C",
        fg: str = "#EDEDF2",
        font=("Segoe UI", 10, "bold"),
        corner_radius: int = 6,
        **kwargs
    ):
        super().__init__(parent, text=text, font=font, fg=fg, cursor="hand2", **kwargs)
        self.command = command
        self.width_px = width_px
        self.height_px = height_px
        self.color1 = color1
        self.color2 = color2
        self.hover_color1 = hover_color1
        self.hover_color2 = hover_color2
        self.corner_radius = corner_radius

        # Pre-render state textures
        self._img_normal = ImageTk.PhotoImage(
            create_horizontal_gradient_image(width_px, height_px, color1, color2, corner_radius=corner_radius)
        )
        self._img_hover = ImageTk.PhotoImage(
            create_horizontal_gradient_image(
                width_px, height_px, hover_color1, hover_color2, corner_radius=corner_radius
            )
        )

        self.configure(image=self._img_normal, compound="center", bd=0)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _):
        self.configure(image=self._img_hover)

    def _on_leave(self, _):
        self.configure(image=self._img_normal)

    def _on_click(self, _):
        if self.command:
            self.command()

    def update_gradient(self, color1: str, color2: str, hover1: str, hover2: str, text: Optional[str] = None):
        self.color1 = color1
        self.color2 = color2
        self.hover_color1 = hover1
        self.hover_color2 = hover2
        new_normal = ImageTk.PhotoImage(
            create_horizontal_gradient_image(
                self.width_px, self.height_px, color1, color2, corner_radius=self.corner_radius
            )
        )
        new_hover = ImageTk.PhotoImage(
            create_horizontal_gradient_image(
                self.width_px, self.height_px, hover1, hover2, corner_radius=self.corner_radius
            )
        )
        cfg = {"image": new_normal}
        if text is not None:
            cfg["text"] = text
        self.configure(**cfg)
        self._img_normal = new_normal
        self._img_hover = new_hover
