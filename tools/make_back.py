"""Génère l'illustration du dos « Édition Cross-Eyed Cat ».

Composition pensée comme un dos de jeu commercial :

* fond bleu nuit en dégradé radial avec vignettage ;
* rayons de soleil (sunburst) très discrets partant du centre ;
* motif régulier en treillis hexagonal (pattes, poissons, têtes de chat)
  qui s'estompe vers le centre — symétrique et uniforme, il pardonne le
  décalage recto/verso à l'impression ;
* anneau guilloché façon billet de banque autour du médaillon ;
* médaillon central cerclé d'or avec le portrait du chat qui louche
  (lynx point aux yeux bleu glacier) ;
* titre « ÉDITION » en arc au-dessus, et grande banderole
  « CROSS-EYED CAT » en travers du médaillon.

Toute l'information importante tient dans un rayon de 42 % de l'image :
elle reste visible une fois le dos rogné en disque (mode ``cover``).

Usage (depuis la racine du projet) ::

    python tools/make_back.py                 # -> assets/back.png
    python tools/make_back.py -o dos.png --size 3000
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

Color = Tuple[int, int, int, int]

#: Dossier des polices embarquées (Poppins, licence SIL OFL 1.1).
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

#: Facteur de supersampling (dessin à 2x puis réduction Lanczos).
SUPERSAMPLE = 2


@dataclass(frozen=True)
class Palette:
    """Couleurs de l'illustration (modifiables pour décliner le dos)."""

    night_center: Color = (40, 54, 104, 255)
    night_edge: Color = (12, 17, 40, 255)
    pattern: Color = (92, 116, 186, 255)
    gold: Color = (240, 194, 92, 255)
    gold_dark: Color = (186, 140, 52, 255)
    gold_shade: Color = (132, 96, 34, 255)
    medallion: Color = (20, 27, 58, 255)
    title_ink: Color = (22, 28, 56, 255)
    # Chat (lynx point d'après photo)
    fur: Color = (240, 228, 210, 255)
    fur_mask: Color = (170, 150, 126, 255)
    tabby: Color = (92, 80, 68, 255)
    white_fur: Color = (250, 247, 240, 255)
    iris: Color = (168, 205, 222, 255)
    iris_dark: Color = (104, 156, 186, 255)
    ear_pink: Color = (230, 176, 178, 255)
    nose: Color = (196, 118, 92, 255)
    ink: Color = (28, 28, 38, 255)


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Charge une police embarquée, avec repli sur DejaVu puis la police Pillow."""
    for candidate in (FONTS_DIR / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size)


def with_alpha(color: Color, alpha: int) -> Color:
    """Retourne ``color`` avec une autre opacité."""
    return (color[0], color[1], color[2], alpha)


def radial_ramp(size: int, center: Tuple[float, float], r0: float, r1: float) -> np.ndarray:
    """Rampe radiale 0→1 entre les rayons ``r0`` et ``r1`` (tableau float32)."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dist = np.hypot(xx - center[0], yy - center[1])
    return np.clip((dist - r0) / max(1e-6, r1 - r0), 0.0, 1.0)


def multiply_alpha(layer: Image.Image, factor: np.ndarray) -> Image.Image:
    """Multiplie le canal alpha d'un calque par ``factor`` (0..1)."""
    alpha = np.asarray(layer.getchannel("A"), dtype=np.float32) * factor
    layer.putalpha(Image.fromarray(alpha.clip(0, 255).astype(np.uint8), mode="L"))
    return layer


def paste_rotated(canvas: Image.Image, sprite: Image.Image, center: Tuple[float, float], angle: float) -> None:
    """Colle ``sprite`` tourné de ``angle`` degrés, centré sur ``center``."""
    rotated = sprite.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    canvas.alpha_composite(
        rotated, (int(round(center[0] - rotated.width / 2)), int(round(center[1] - rotated.height / 2)))
    )


def arc_text(
    canvas: Image.Image,
    text: str,
    center: Tuple[float, float],
    radius: float,
    font: ImageFont.FreeTypeFont,
    color: Color,
    tracking: float = 0.0,
    bottom: bool = False,
) -> None:
    """Écrit ``text`` sur un arc, avec chasse réelle des glyphes.

    Contrairement à un espacement angulaire uniforme, chaque lettre avance
    de sa largeur réelle (plus ``tracking``), ce qui donne un crénage
    régulier. Le texte est centré en haut du cercle (``bottom=False``,
    lettres vers l'extérieur) ou en bas (``bottom=True``, lisible de gauche
    à droite). La ligne de base suit le cercle de rayon ``radius``.
    """
    advances = [font.getlength(ch) + tracking for ch in text]
    total = sum(advances) - tracking
    span = total / radius
    middle = math.radians(90.0 if bottom else -90.0)
    cursor = 0.0
    box = int(font.size * 2.4)
    for ch, advance in zip(text, advances):
        offset = (cursor + (advance - tracking) / 2.0) / radius - span / 2.0
        angle = middle - offset if bottom else middle + offset
        glyph = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        # Ligne de base au centre du canevas : elle tombera sur le cercle.
        ImageDraw.Draw(glyph).text(
            (box / 2, box / 2 if not bottom else box / 2 + font.size * 0.70),
            ch, font=font, fill=color, anchor="ms",
        )
        rotation = 90.0 - math.degrees(angle) if bottom else -math.degrees(angle) - 90.0
        x = center[0] + radius * math.cos(angle)
        y = center[1] + radius * math.sin(angle)
        paste_rotated(canvas, glyph, (x, y), rotation)
        cursor += advance


# ---------------------------------------------------------------------------
# Icônes du motif
# ---------------------------------------------------------------------------


def icon_paw(size: int, color: Color) -> Image.Image:
    """Patte de chat pleine."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 100
    d.ellipse((27 * u, 44 * u, 73 * u, 88 * u), fill=color)
    for cx, cy, r in ((20, 34, 11), (40, 19, 12), (60, 19, 12), (80, 34, 11)):
        d.ellipse(((cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u), fill=color)
    return img


def icon_fish(size: int, color: Color) -> Image.Image:
    """Poisson au trait."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 100
    w = max(2, int(7 * u))
    d.ellipse((6 * u, 28 * u, 70 * u, 72 * u), outline=color, width=w)
    d.polygon([(64 * u, 50 * u), (94 * u, 28 * u), (94 * u, 72 * u)], fill=color)
    d.ellipse((20 * u, 42 * u, 30 * u, 52 * u), fill=color)
    return img


def icon_cat(size: int, color: Color) -> Image.Image:
    """Silhouette de tête de chat."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 100
    d.polygon([(14 * u, 46 * u), (20 * u, 8 * u), (44 * u, 30 * u)], fill=color)
    d.polygon([(86 * u, 46 * u), (80 * u, 8 * u), (56 * u, 30 * u)], fill=color)
    d.ellipse((12 * u, 24 * u, 88 * u, 92 * u), fill=color)
    return img


def icon_sparkle(size: int, color: Color) -> Image.Image:
    """Étincelle à quatre branches."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    c = size / 2
    pts = []
    for k in range(8):
        r = c * (1.0 if k % 2 == 0 else 0.30)
        a = k * math.pi / 4 - math.pi / 2
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    ImageDraw.Draw(img).polygon(pts, fill=color)
    return img


# ---------------------------------------------------------------------------
# Couches de fond
# ---------------------------------------------------------------------------


def draw_background(size: int, pal: Palette) -> Image.Image:
    """Dégradé radial bleu nuit avec vignettage."""
    c = size / 2
    t = radial_ramp(size, (c, c), 0.0, size * 0.72) ** 1.3
    inner = np.array(pal.night_center[:3], dtype=np.float32)
    outer = np.array(pal.night_edge[:3], dtype=np.float32)
    rgb = inner[None, None, :] * (1 - t[..., None]) + outer[None, None, :] * t[..., None]
    return Image.fromarray(rgb.astype(np.uint8), mode="RGB").convert("RGBA")


def draw_sunburst(size: int, rays: int = 48) -> Image.Image:
    """Rayons alternés très discrets partant du centre."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = size / 2
    far = size
    for k in range(0, rays, 2):
        a0 = 2 * math.pi * k / rays
        a1 = 2 * math.pi * (k + 1) / rays
        d.polygon(
            [(c, c), (c + far * math.cos(a0), c + far * math.sin(a0)), (c + far * math.cos(a1), c + far * math.sin(a1))],
            fill=(255, 255, 255, 11),
        )
    return layer


def draw_pattern(size: int, pal: Palette) -> Image.Image:
    """Treillis hexagonal régulier d'icônes, estompé vers le centre."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    step = size * 0.088
    icon = int(step * 0.46)
    makers = (icon_paw, icon_fish, icon_cat)
    color = with_alpha(pal.pattern, 120)
    sparkle_color = with_alpha(pal.gold, 70)
    rows = int(size / (step * 0.866)) + 3
    cols = int(size / step) + 3
    c = size / 2
    for j in range(-1, rows):
        y = j * step * 0.866
        for i in range(-1, cols):
            x = i * step + (step / 2 if j % 2 else 0.0)
            # Décalage pour que le treillis soit symétrique autour du centre.
            x += (c - round(c / step) * step)
            y_c = y + (c - round(c / (step * 0.866)) * step * 0.866)
            kind = (i + j * 2) % 4
            if kind == 3:
                sprite = icon_sparkle(int(icon * 0.6), sparkle_color)
                angle = 0.0
            else:
                sprite = makers[kind](icon, color)
                angle = 14.0 if j % 2 else -14.0
            paste_rotated(layer, sprite, (x, y_c), angle)
    fade = radial_ramp(size, (c, c), size * 0.36, size * 0.44)
    return multiply_alpha(layer, fade)


def draw_guilloche(size: int, pal: Palette, r_mid: float, amplitude: float) -> Image.Image:
    """Anneau guilloché : rosaces sinusoïdales entrelacées (façon billet)."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = size / 2
    width = max(2, int(size * 0.0011))
    lobes = 40
    steps = 4000
    for phase_index in range(4):
        phase = phase_index * math.pi / 4
        pts = []
        for k in range(steps + 1):
            t = 2 * math.pi * k / steps
            r = r_mid + amplitude * math.sin(lobes * t + phase)
            pts.append((c + r * math.cos(t), c + r * math.sin(t)))
        d.line(pts, fill=with_alpha(pal.gold, 120), width=width, joint="curve")
    # Deux cercles fins bornant l'anneau
    for r in (r_mid - amplitude * 1.35, r_mid + amplitude * 1.35):
        d.ellipse((c - r, c - r, c + r, c + r), outline=with_alpha(pal.gold, 150), width=width)
    return layer


# ---------------------------------------------------------------------------
# Médaillon, chat, titres
# ---------------------------------------------------------------------------


def draw_medallion(canvas: Image.Image, pal: Palette, cx: float, cy: float, r: float) -> None:
    """Médaillon central : disque nuit, double cerclage or, ombre portée."""
    size = canvas.width
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((cx - r, cy - r + size * 0.008, cx + r, cy + r + size * 0.008), fill=(0, 0, 0, 150))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(size * 0.012)))
    d = ImageDraw.Draw(canvas)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=pal.medallion)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=pal.gold, width=int(size * 0.011))
    ri = r - size * 0.021
    d.ellipse((cx - ri, cy - ri, cx + ri, cy + ri), outline=pal.gold_dark, width=int(size * 0.0035))
    # Points décoratifs entre les deux cerclages.
    rd = r - size * 0.0105
    for k in range(72):
        a = 2 * math.pi * k / 72
        px, py = cx + rd * math.cos(a), cy + rd * math.sin(a)
        dot = size * 0.0024
        d.ellipse((px - dot, py - dot, px + dot, py + dot), fill=pal.gold_shade)


def draw_cat(layer: Image.Image, pal: Palette, cx: float, cy: float, R: float) -> None:
    """Portrait stylisé du chat qui louche (lynx point, yeux bleu glacier).

    Tête crème, masque taupe, « M » tabby sur le front, museau blanc, nez
    brique, moustaches blanches, poitrail clair ; pupilles convergentes.
    """
    d = ImageDraw.Draw(layer)
    lw = max(3, int(R * 0.040))

    # Poitrail / épaules (sous la tête ; la banderole en cache le bas).
    d.ellipse((cx - R * 1.05, cy + R * 0.45, cx + R * 1.05, cy + R * 2.3), fill=pal.fur, outline=pal.tabby, width=lw)
    d.ellipse((cx - R * 0.55, cy + R * 0.55, cx + R * 0.55, cy + R * 2.1), fill=pal.white_fur)

    # Oreilles
    for side in (-1, 1):
        base_in = (cx + side * R * 0.20, cy - R * 0.70)
        base_out = (cx + side * R * 0.98, cy - R * 0.28)
        tip = (cx + side * R * 0.90, cy - R * 1.24)
        d.polygon([base_in, tip, base_out], fill=pal.fur, outline=pal.tabby, width=int(lw * 1.2))
        inner = [
            (cx + side * R * 0.38, cy - R * 0.66),
            (cx + side * R * 0.86, cy - R * 1.04),
            (cx + side * R * 0.86, cy - R * 0.44),
        ]
        d.polygon(inner, fill=pal.ear_pink)

    # Tête
    d.ellipse((cx - R, cy - R * 0.92, cx + R, cy + R * 0.92), fill=pal.fur, outline=pal.tabby, width=lw)

    # Masque taupe autour des yeux + chanfrein crème
    for side in (-1, 1):
        mx = cx + side * R * 0.46
        d.ellipse((mx - R * 0.36, cy - R * 0.48, mx + R * 0.36, cy + R * 0.18), fill=pal.fur_mask)
    d.polygon(
        [(cx - R * 0.11, cy - R * 0.46), (cx + R * 0.11, cy - R * 0.46),
         (cx + R * 0.20, cy + R * 0.22), (cx - R * 0.20, cy + R * 0.22)],
        fill=pal.fur,
    )

    # « M » tabby : rayures sombres sur le front
    top = cy - R * 0.88
    for dx, length, w in ((0.0, 0.36, 1.5), (-0.14, 0.31, 1.3), (0.14, 0.31, 1.3),
                          (-0.28, 0.26, 1.1), (0.28, 0.26, 1.1), (-0.42, 0.19, 1.0), (0.42, 0.19, 1.0)):
        x = cx + dx * R
        y0 = top + abs(dx) * R * 0.18
        d.line((x, y0, x, y0 + length * R), fill=pal.tabby, width=int(lw * w))

    # Rayures de joues
    for side in (-1, 1):
        for j, yy in enumerate((-0.04, 0.08, 0.20)):
            d.line((cx + side * R * 0.97, cy + yy * R, cx + side * R * (0.80 - j * 0.03), cy + (yy + 0.02) * R),
                   fill=pal.tabby, width=int(lw * 0.9))

    # Museau blanc
    d.ellipse((cx - R * 0.34, cy + R * 0.10, cx + R * 0.34, cy + R * 0.60), fill=pal.white_fur)

    # Yeux bleu glacier, pupilles convergentes (le strabisme !)
    eye_r = R * 0.29
    for side in (-1, 1):
        ex, ey = cx + side * R * 0.42, cy - R * 0.11
        d.ellipse((ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r), fill=pal.iris, outline=pal.ink, width=lw)
        d.arc((ex - eye_r * 0.82, ey - eye_r * 0.82, ex + eye_r * 0.82, ey + eye_r * 0.82),
              200, 340, fill=pal.iris_dark, width=int(eye_r * 0.26))
        px, py = ex - side * eye_r * 0.46, ey + eye_r * 0.20
        pr = eye_r * 0.40
        d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=pal.ink)
        hr = pr * 0.34
        d.ellipse((px - pr * 0.35 - hr, py - pr * 0.40 - hr, px - pr * 0.35 + hr, py - pr * 0.40 + hr),
                  fill=(255, 255, 255, 255))

    # Nez + bouche
    nw, ny = R * 0.12, cy + R * 0.25
    thin = max(2, lw // 2)
    d.polygon([(cx - nw, ny), (cx + nw, ny), (cx, ny + nw * 1.15)], fill=pal.nose, outline=pal.ink, width=thin)
    d.arc((cx - R * 0.20, ny + nw * 0.4, cx, ny + R * 0.24), 0, 130, fill=pal.ink, width=thin)
    d.arc((cx, ny + nw * 0.4, cx + R * 0.20, ny + R * 0.24), 50, 180, fill=pal.ink, width=thin)

    # Moustaches blanches
    for side in (-1, 1):
        for dy, ang in ((-0.02, 10), (0.08, 0), (0.18, -10)):
            x0, y0 = cx + side * R * 0.60, ny + dy * R
            length = R * 0.62
            d.line((x0, y0, x0 + side * length * math.cos(math.radians(ang)), y0 - length * math.sin(math.radians(ang))),
                   fill=(245, 243, 238, 255), width=max(2, int(lw * 0.55)))


def draw_ribbon(canvas: Image.Image, pal: Palette, cx: float, cy: float, width: float, height: float,
                text: str) -> None:
    """Banderole or « à queues » avec le titre en grandes capitales."""
    size = canvas.width
    d = ImageDraw.Draw(canvas)
    half_w, half_h = width / 2, height / 2
    tail_w = height * 1.15
    drop = height * 0.38

    # Ombre portée de l'ensemble
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle(
        (cx - half_w - tail_w * 0.6, cy - half_h + drop * 0.5, cx + half_w + tail_w * 0.6, cy + half_h + drop * 1.4),
        fill=(0, 0, 0, 120),
    )
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(size * 0.01)))
    d = ImageDraw.Draw(canvas)

    for side in (-1, 1):
        inner_x = cx + side * (half_w - height * 0.55)
        outer_x = cx + side * (half_w + tail_w)
        top, bottom = cy - half_h + drop, cy + half_h + drop
        notch_x = outer_x - side * height * 0.42
        d.polygon([(inner_x, top), (outer_x, top), (notch_x, (top + bottom) / 2), (outer_x, bottom), (inner_x, bottom)],
                  fill=pal.gold_dark)
        # Pli : petit triangle sombre entre la queue et la bande principale
        edge_x = cx + side * half_w
        d.polygon([(edge_x, cy + half_h), (edge_x - side * height * 0.55, cy + half_h + drop * 0.02),
                   (edge_x - side * height * 0.55, cy + half_h + drop)], fill=pal.gold_shade)

    d.rectangle((cx - half_w, cy - half_h, cx + half_w, cy + half_h), fill=pal.gold)
    # Filets de finition en haut et en bas de la bande
    inset = height * 0.10
    line_w = max(2, int(size * 0.0016))
    for y in (cy - half_h + inset, cy + half_h - inset):
        d.line((cx - half_w + inset, y, cx + half_w - inset, y), fill=pal.gold_dark, width=line_w)

    # Titre : taille ajustée à la largeur disponible
    target = width * 0.86
    font_size = int(height * 0.62)
    font = load_font("Poppins-Bold.ttf", font_size)
    tracking = font_size * 0.04
    while sum(font.getlength(ch) + tracking for ch in text) - tracking > target and font_size > 10:
        font_size -= 2
        font = load_font("Poppins-Bold.ttf", font_size)
        tracking = font_size * 0.04
    total = sum(font.getlength(ch) + tracking for ch in text) - tracking
    x = cx - total / 2
    for ch in text:
        d.text((x, cy + font_size * 0.36), ch, font=font, fill=pal.title_ink, anchor="ls")
        x += font.getlength(ch) + tracking


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def compose(final_size: int, pal: Palette) -> Image.Image:
    """Assemble toutes les couches et retourne l'illustration RGBA finale."""
    S = final_size * SUPERSAMPLE
    c = S / 2

    img = draw_background(S, pal)
    img.alpha_composite(draw_sunburst(S))
    img.alpha_composite(draw_pattern(S, pal))

    med_cx, med_cy, med_r = c, c - S * 0.015, S * 0.235
    img.alpha_composite(draw_guilloche(S, pal, r_mid=med_r + S * 0.034, amplitude=S * 0.014))
    draw_medallion(img, pal, med_cx, med_cy, med_r)

    # Chat, rogné à l'intérieur du médaillon
    cat_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw_cat(cat_layer, pal, med_cx, med_cy - S * 0.045, S * 0.098)
    clip = Image.new("L", (S, S), 0)
    inner = med_r - S * 0.026
    ImageDraw.Draw(clip).ellipse((med_cx - inner, med_cy - inner, med_cx + inner, med_cy + inner), fill=255)
    cat_alpha = np.minimum(np.asarray(cat_layer.getchannel("A")), np.asarray(clip)).astype(np.uint8)
    cat_layer.putalpha(Image.fromarray(cat_alpha, mode="L"))
    img.alpha_composite(cat_layer)

    # Titre « ÉDITION » en arc au-dessus du médaillon, encadré d'étincelles
    arc_r = med_r + S * 0.085
    edition_font = load_font("Poppins-Bold.ttf", int(S * 0.050))
    arc_text(img, "ÉDITION", (med_cx, med_cy), arc_r, edition_font, pal.gold, tracking=S * 0.014)
    for ang in (-124, -56):
        a = math.radians(ang)
        paste_rotated(img, icon_sparkle(int(S * 0.030), pal.gold),
                      (med_cx + (arc_r + S * 0.012) * math.cos(a), med_cy + (arc_r + S * 0.012) * math.sin(a)), 0)

    # Banderole « CROSS-EYED CAT » en travers du bas du médaillon
    draw_ribbon(img, pal, c, med_cy + med_r * 0.66, width=S * 0.56, height=S * 0.092, text="CROSS-EYED CAT")

    # Trois étincelles sous la banderole
    for dx, scale in ((-0.05, 0.020), (0.0, 0.030), (0.05, 0.020)):
        paste_rotated(img, icon_sparkle(int(S * scale), pal.gold), (c + dx * S, med_cy + med_r + S * 0.075), 0)

    return img.resize((final_size, final_size), Image.Resampling.LANCZOS)


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée : génère l'illustration et l'écrit sur disque."""
    parser = argparse.ArgumentParser(description="Génère le dos « Édition Cross-Eyed Cat ».")
    parser.add_argument("-o", "--output", type=Path, default=Path("assets/back.png"))
    parser.add_argument("--size", type=int, default=2400, help="Côté de l'image en pixels.")
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    compose(args.size, Palette()).save(args.output)
    print(f"Illustration écrite : {args.output} ({args.size}×{args.size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
