"""Interface en ligne de commande du générateur Dobble.

Exemple ::

    python main.py \
        --images images \
        --output output \
        --dpi 300 \
        --theme classic

Pipeline :

1. génération mathématique des 57 cartes (plan projectif d'ordre 7) et
   validation exhaustive ;
2. chargement de la bibliothèque (PNG, WebP, JPG) avec détourage auto ;
3. placement sans chevauchement de chaque carte ;
4. rendu (contours, ombres, liseré) puis exports PNG, SVG, PDF et planches
   A4 — recto-verso si une illustration de dos est disponible.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Sequence

from PIL import Image

from generator.cards import generate_deck
from generator.config import THEMES, AppConfig, BackConfig, ImportConfig
from generator.export import Exporter, ExportPaths
from generator.layout import LayoutEngine, PlacedSymbol
from generator.renderer import CardRenderer, RenderedCard
from generator.utils import (
    ProgressBar,
    find_optional_back,
    find_optional_background,
    load_image_library,
    setup_logging,
)

logger = logging.getLogger("main")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Analyse les arguments de la ligne de commande."""
    defaults_import = ImportConfig()
    parser = argparse.ArgumentParser(
        prog="opendobble",
        description="Génère un jeu de type Dobble (57 cartes) prêt à imprimer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--images", type=Path, default=Path("images"),
                        help="Dossier contenant exactement 57 images (PNG, WebP, JPG).")
    parser.add_argument("--output", type=Path, default=Path("output"),
                        help="Dossier de sortie (créé si nécessaire).")
    parser.add_argument("--dpi", type=int, default=300,
                        help="Résolution des exports raster et du PDF.")
    parser.add_argument("--theme", choices=sorted(THEMES), default="classic",
                        help="Thème graphique appliqué aux cartes.")
    parser.add_argument("--seed", type=int, default=None,
                        help="Graine aléatoire pour un rendu reproductible.")
    parser.add_argument("--assets", type=Path, default=Path("assets"),
                        help="Dossier des ressources (background.png, back.png).")
    parser.add_argument("--back", type=Path, default=None,
                        help="Illustration du dos (défaut : assets/back.* si présent). "
                             "Active les planches recto-verso.")
    parser.add_argument("--back-mode", choices=["cover", "fit"], default=BackConfig().mode,
                        help="'cover' remplit tout le disque, 'fit' garde l'illustration entière.")
    parser.add_argument("--bg-removal", choices=["auto", "always", "never"],
                        default=defaults_import.background_mode,
                        help="Détourage des images sans transparence. Par image : "
                             "suffixes '.keep.' ou '.cut.' dans le nom de fichier.")
    parser.add_argument("--no-bg-removal", action="store_true",
                        help="Alias de --bg-removal never.")
    parser.add_argument("--bg-tolerance", type=int, default=defaults_import.background_tolerance,
                        help="Tolérance de couleur du détourage (0-255).")
    parser.add_argument("--corner-radius", type=float, default=defaults_import.corner_radius_ratio,
                        help="Arrondi des images conservées rectangulaires (0 = coins vifs).")
    parser.add_argument("--verbose", action="store_true", help="Active les logs de debug.")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> AppConfig:
    """Construit la configuration de l'application depuis les arguments CLI."""
    base = AppConfig(seed=args.seed).with_theme(args.theme).with_dpi(args.dpi)
    config = replace(
        base,
        imports=replace(
            base.imports,
            background_mode="never" if args.no_bg_removal else args.bg_removal,
            background_tolerance=args.bg_tolerance,
            corner_radius_ratio=args.corner_radius,
        ),
        back=replace(base.back, mode=args.back_mode),
    )
    logger.info(
        "Configuration : thème '%s', %d dpi, carte Ø %.0f mm, fond perdu %.1f mm.",
        config.theme.name, config.export.dpi, config.card.diameter_mm, config.card.bleed_mm,
    )
    return config


def _open_optional(path: Optional[Path], label: str) -> Optional[Image.Image]:
    """Ouvre une ressource image optionnelle, ou lève si un chemin explicite manque."""
    if path is None:
        return None
    if not path.is_file():
        raise FileNotFoundError(f"{label} introuvable : {path}")
    logger.info("%s : %s", label, path)
    with Image.open(path) as raw:
        return raw.convert("RGBA")


def run(args: argparse.Namespace) -> int:
    """Exécute le pipeline complet de génération ; retourne le code de sortie."""
    config = build_config(args)
    rng = random.Random(config.seed)

    deck = generate_deck()
    library = load_image_library(args.images, config=config.imports)
    background = _open_optional(find_optional_background(args.assets), "Fond de carte")
    back_image = _open_optional(args.back or find_optional_back(args.assets), "Dos de carte")

    # Placement.
    renderer = CardRenderer(config, background=background)
    engine = LayoutEngine(config.layout, rng)
    layouts: List[List[PlacedSymbol]] = []
    progress = ProgressBar(total=len(deck.cards), label="Placement")
    for card in deck.cards:
        layouts.append(engine.layout_card(card.symbols, renderer.usable_radius_px, renderer.padding_px))
        progress.advance()
    progress.finish()

    # Rendu + exports unitaires.
    paths = ExportPaths.create(args.output)
    exporter = Exporter(config, paths)
    bleed_px = config.card.bleed_px(config.export.dpi)
    rendered: List[RenderedCard] = []
    rendered_bleed: List[RenderedCard] = []
    progress = ProgressBar(total=len(deck.cards), label="Rendu & exports")
    for card, placements in zip(deck.cards, layouts):
        result = renderer.render_card(card.index, placements, library)
        rendered.append(result)
        if config.export.export_png:
            exporter.export_png(result)
        if config.export.export_svg:
            exporter.export_svg(result, library)
        if config.export.export_sheets:
            rendered_bleed.append(renderer.render_card(card.index, placements, library, bleed_px))
        progress.advance()
    progress.finish()

    # Dos de carte.
    back_bleed: Optional[Image.Image] = None
    if back_image is not None:
        back_bleed = renderer.render_back(back_image, bleed_px=bleed_px)
        logger.info("PNG du dos : %s", exporter.export_back_png(renderer.render_back(back_image)))

    # Documents regroupés.
    if config.export.export_pdf:
        logger.info("PDF du deck : %s", exporter.export_deck_pdf(rendered))
    if config.export.export_sheets:
        sheets = exporter.export_sheets(rendered_bleed, back_bleed)
        logger.info("%d planches A4%s : %s", len(sheets),
                    " recto-verso" if back_bleed is not None else "", paths.sheets_dir)

    logger.info("Terminé. Fichiers disponibles dans '%s'.", paths.root)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Point d'entrée du programme."""
    args = parse_args(argv)
    setup_logging(verbose=args.verbose)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - message propre pour la CLI
        logger.error("Échec de la génération : %s", exc)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
