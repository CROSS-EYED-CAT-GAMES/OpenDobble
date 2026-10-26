"""Génère 57 images d'exemple pour tester le générateur sans bibliothèque.

Formes géométriques colorées numérotées, sur fond transparent (PNG).
Remplacez ensuite le contenu de ``images/`` par vos propres illustrations.

Usage (depuis la racine du projet) ::

    python tools/make_sample_images.py            # -> images/001.png ... 057.png
    python tools/make_sample_images.py -o demo --seed 3
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw


def make_shape(index: int, rng: random.Random) -> Image.Image:
    """Dessine une forme (disque, carré, étoile, triangle) numérotée."""
    size = rng.randint(200, 320)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = tuple(rng.randint(40, 220) for _ in range(3)) + (255,)
    m = size // 8
    kind = index % 4
    if kind == 0:
        draw.ellipse((m, m, size - m, size - m), fill=color)
    elif kind == 1:
        draw.rounded_rectangle((m, m, size - m, size - m), radius=size // 12, fill=color)
    elif kind == 2:
        points = [
            (size / 2 + (size / 2.3 if k % 2 == 0 else size / 5) * math.cos(k * math.pi / 5 - math.pi / 2),
             size / 2 + (size / 2.3 if k % 2 == 0 else size / 5) * math.sin(k * math.pi / 5 - math.pi / 2))
            for k in range(10)
        ]
        draw.polygon(points, fill=color)
    else:
        draw.polygon([(size / 2, m), (size - m, size - m), (m, size - m)], fill=color)
    draw.text((size / 2, size / 2), f"{index + 1:02d}", fill=(255, 255, 255, 255), anchor="mm",
              font_size=size // 6)
    return img


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée : écrit 57 PNG d'exemple."""
    parser = argparse.ArgumentParser(description="Génère 57 images d'exemple.")
    parser.add_argument("-o", "--output", type=Path, default=Path("images"))
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    for i in range(57):
        make_shape(i, rng).save(args.output / f"{i + 1:03d}.png")
    print(f"57 images d'exemple écrites dans {args.output}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
