"""Génère les visuels web du dépôt GitHub (dossier ``docs/images``).

Produit trois images optimisées pour le web :

* ``back.png`` — le dos de carte rendu en disque (600 px, fond transparent),
  affiché en tête du README ;
* ``cards.png`` — un bandeau « dos + 3 faces » (fond transparent, lisible en
  thème clair comme en thème sombre de GitHub) ;
* ``social-preview.png`` — l'aperçu social du dépôt au format recommandé par
  GitHub (1280 × 640, opaque, moins de 1 Mo), à téléverser dans
  *Settings → General → Social preview*.

Les faces utilisent les images d'exemple de ``images/`` : aucun visuel tiers
n'est publié. À lancer après une génération, depuis la racine du projet ::

    python main.py --images images --output output --dpi 150 --seed 7
    python tools/make_docs_images.py --cards output/png
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Charge une police embarquée."""
    return ImageFont.truetype(str(FONTS / name), size)


def with_shadow(card: Image.Image, blur: int, offset: int, opacity: int = 90) -> Image.Image:
    """Ajoute une ombre douce sous une carte ronde (canevas élargi)."""
    pad = blur * 3 + offset
    out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("L", out.size, 0)
    shadow.paste(card.getchannel("A").point(lambda v: v * opacity // 255), (pad, pad + offset))
    shadow_layer = Image.new("RGBA", out.size, (0, 0, 0, 255))
    shadow_layer.putalpha(shadow.filter(ImageFilter.GaussianBlur(blur)))
    out.alpha_composite(shadow_layer)
    out.alpha_composite(card, (pad, pad))
    return out


def save_png(image: Image.Image, path: Path) -> None:
    """Enregistre un PNG compressé et affiche son poids."""
    image.save(path, optimize=True)
    print(f"{path.relative_to(ROOT)} : {image.width}×{image.height}, {path.stat().st_size // 1024} Ko")


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée : écrit les trois visuels dans ``docs/images``."""
    parser = argparse.ArgumentParser(description="Génère les visuels du README GitHub.")
    parser.add_argument("--cards", type=Path, default=ROOT / "output" / "png",
                        help="Dossier contenant card_XX.png et back.png.")
    parser.add_argument("--faces", type=int, nargs=3, default=(1, 12, 30),
                        help="Numéros des trois faces à montrer.")
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "docs" / "images")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)

    back = Image.open(args.cards / "back.png").convert("RGBA")
    faces = [Image.open(args.cards / f"card_{n:02d}.png").convert("RGBA") for n in args.faces]

    # 1) Dos seul, 600 px, transparent.
    save_png(with_shadow(back.resize((560, 560), Image.Resampling.LANCZOS), 12, 6), args.output / "back.png")

    # 2) Bandeau dos + 3 faces, transparent.
    size, gap = 380, 30
    banner = Image.new("RGBA", (4 * size + 3 * gap + 80, size + 80), (0, 0, 0, 0))
    for k, card in enumerate([back, *faces]):
        sprite = with_shadow(card.resize((size, size), Image.Resampling.LANCZOS), 10, 5)
        x = 40 + k * (size + gap) - (sprite.width - size) // 2
        banner.alpha_composite(sprite, (x, 40 - (sprite.height - size) // 2))
    save_png(banner, args.output / "cards.png")

    # 3) Aperçu social 1280 × 640, opaque.
    W, H = 1280, 640
    social = Image.new("RGBA", (W, H), (14, 20, 44, 255))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((-200, -160, 760, 800), fill=120)
    social.paste((40, 54, 104, 255), (0, 0), glow.filter(ImageFilter.GaussianBlur(160)))
    card = with_shadow(back.resize((500, 500), Image.Resampling.LANCZOS), 16, 8, opacity=160)
    social.alpha_composite(card, (70 - (card.width - 500) // 2, (H - card.height) // 2))
    d = ImageDraw.Draw(social)
    gold, cream = (240, 194, 92, 255), (244, 238, 226, 255)
    x = 640
    d.text((x, 175), "OPENDOBBLE", font=font("Poppins-Bold.ttf", 54), fill=cream)
    d.text((x, 252), "Édition Cross-Eyed Cat", font=font("Poppins-Medium.ttf", 36), fill=gold)
    d.line((x, 318, x + 120, 318), fill=gold, width=4)
    lines = ["57 cartes · plan projectif d'ordre 7", "PNG 300 dpi · SVG · PDF",
             "Planches A4 recto-verso prêtes à imprimer"]
    for i, line in enumerate(lines):
        d.text((x, 350 + i * 46), line, font=font("Poppins-Regular.ttf", 28), fill=(196, 204, 228, 255))
    save_png(social.convert("RGB"), args.output / "social-preview.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
