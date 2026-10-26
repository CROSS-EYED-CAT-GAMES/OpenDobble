"""Exports du jeu : PNG HD, SVG vectoriels, PDF et planches A4.

Formats produits :

* ``output/png/card_XX.png`` — 57 PNG à la résolution demandée (300 dpi par
  défaut), fond transparent hors du disque, DPI embarqué ;
* ``output/svg/card_XX.svg`` — 57 SVG aux dimensions physiques exactes :
  fond, liserés et positions vectoriels ; chaque symbole (contour et ombre
  inclus) est embarqué en base64 avec sa rotation SVG ;
* ``output/deck.pdf`` — les 57 cartes, une par page ;
* ``output/sheets/sheet_XX.pdf`` — planches A4 (6 cartes par défaut) avec
  fonds perdus, traits de coupe, et verso en miroir si un dos est fourni.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import svgwrite
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from .config import AppConfig, mm_to_px
from .renderer import RenderedCard, SymbolProcessor
from .utils import SymbolImage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportPaths:
    """Chemins de sortie créés par :class:`Exporter`.

    Attributes:
        root: dossier de sortie racine.
        png_dir: dossier des PNG unitaires.
        svg_dir: dossier des SVG unitaires.
        sheets_dir: dossier des planches A4.
        deck_pdf: chemin du PDF regroupant toutes les cartes.
    """

    root: Path
    png_dir: Path
    svg_dir: Path
    sheets_dir: Path
    deck_pdf: Path

    @classmethod
    def create(cls, root: Path) -> "ExportPaths":
        """Crée l'arborescence de sortie et retourne les chemins."""
        paths = cls(root, root / "png", root / "svg", root / "sheets", root / "deck.pdf")
        for directory in (paths.root, paths.png_dir, paths.svg_dir, paths.sheets_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return paths


class Exporter:
    """Réalise l'ensemble des exports d'un jeu rendu.

    Args:
        config: configuration globale.
        paths: arborescence de sortie (voir :meth:`ExportPaths.create`).
    """

    def __init__(self, config: AppConfig, paths: ExportPaths) -> None:
        self._config = config
        self._paths = paths
        self._dpi = config.export.dpi

    # ------------------------------------------------------------------
    # PNG
    # ------------------------------------------------------------------

    def export_png(self, card: RenderedCard) -> Path:
        """Écrit le PNG HD d'une carte (fond transparent, DPI embarqué)."""
        path = self._paths.png_dir / f"card_{card.index + 1:02d}.png"
        card.image.save(path, format="PNG", dpi=(self._dpi, self._dpi))
        return path

    def export_back_png(self, back: Image.Image) -> Path:
        """Écrit le PNG HD du dos de carte."""
        path = self._paths.png_dir / "back.png"
        back.save(path, format="PNG", dpi=(self._dpi, self._dpi))
        return path

    # ------------------------------------------------------------------
    # SVG
    # ------------------------------------------------------------------

    def export_svg(self, card: RenderedCard, library: Sequence[SymbolImage]) -> Path:
        """Écrit le SVG d'une carte.

        Le document est dimensionné en millimètres, avec un ``viewBox`` en
        pixels de rendu : cercles et positions sont vectoriels, les symboles
        sont embarqués (contour et ombre pré-calculés) et tournés en SVG.
        """
        cfg = self._config
        theme = cfg.theme
        diameter_px = cfg.card.diameter_px(self._dpi)
        center = diameter_px / 2.0
        border_px = mm_to_px(theme.border_width_mm, self._dpi)

        path = self._paths.svg_dir / f"card_{card.index + 1:02d}.svg"
        drawing = svgwrite.Drawing(
            filename=str(path),
            size=(f"{cfg.card.diameter_mm}mm", f"{cfg.card.diameter_mm}mm"),
            viewBox=f"0 0 {diameter_px} {diameter_px}",
        )
        clip = drawing.defs.add(drawing.clipPath(id="cardClip"))
        clip.add(drawing.circle(center=(center, center), r=center))
        group = drawing.add(drawing.g(clip_path="url(#cardClip)"))
        group.add(drawing.circle(center=(center, center), r=center, fill=_svg_color(theme.background_color)))

        processor = SymbolProcessor(theme, self._dpi)
        for placement in card.placements:
            sprite = processor.prepare(library[placement.symbol_id].image, placement.radius, 0.0)
            cx, cy = center + placement.x, center + placement.y
            image = drawing.image(
                href=_data_uri(sprite),
                insert=(cx - sprite.width / 2.0, cy - sprite.height / 2.0),
                size=(sprite.width, sprite.height),
            )
            # SVG tourne en sens horaire ; Pillow en sens trigonométrique.
            image.rotate(-placement.rotation_deg, center=(cx, cy))
            group.add(image)

        drawing.add(
            drawing.circle(
                center=(center, center),
                r=center - border_px / 2.0,
                fill="none",
                stroke=_svg_color(theme.border_color),
                stroke_width=border_px,
            )
        )
        if theme.inner_ring:
            drawing.add(
                drawing.circle(
                    center=(center, center),
                    r=center - border_px * 2.2,
                    fill="none",
                    stroke=_svg_color(theme.inner_ring_color),
                    stroke_width=max(1.0, border_px * 0.45),
                )
            )
        drawing.save(pretty=False)
        return path

    # ------------------------------------------------------------------
    # PDF : une carte par page
    # ------------------------------------------------------------------

    def export_deck_pdf(self, cards: Sequence[RenderedCard]) -> Path:
        """Écrit un PDF regroupant toutes les cartes (une par page)."""
        diameter_pt = self._config.card.diameter_mm * mm
        page = (diameter_pt + 20 * mm, diameter_pt + 20 * mm)
        pdf = pdf_canvas.Canvas(str(self._paths.deck_pdf), pagesize=page)
        pdf.setTitle("OpenDobble — Deck complet")
        for card in cards:
            offset = (page[0] - diameter_pt) / 2.0
            pdf.drawImage(
                ImageReader(card.image), offset, offset,
                width=diameter_pt, height=diameter_pt, mask="auto",
            )
            pdf.setFont("Helvetica", 8)
            pdf.setFillColorRGB(0.45, 0.45, 0.45)
            pdf.drawCentredString(page[0] / 2.0, 6 * mm, f"Carte {card.index + 1:02d} / {len(cards)}")
            pdf.showPage()
        pdf.save()
        return self._paths.deck_pdf

    # ------------------------------------------------------------------
    # Planches A4 avec fonds perdus, traits de coupe, verso miroir
    # ------------------------------------------------------------------

    def export_sheets(
        self,
        cards_with_bleed: Sequence[RenderedCard],
        back_with_bleed: Optional[Image.Image] = None,
    ) -> List[Path]:
        """Écrit les planches A4 prêtes pour l'imprimeur.

        Si ``back_with_bleed`` est fourni, chaque planche contient deux
        pages : recto puis verso. Les positions du verso sont le **miroir
        horizontal** du recto, afin qu'une impression recto-verso en
        retournement sur le bord long fasse coïncider chaque dos avec sa face
        (indispensable sur la dernière planche, incomplète).

        Args:
            cards_with_bleed: cartes rendues **avec** fond perdu.
            back_with_bleed: dos rendu **avec** fond perdu, ou ``None``.

        Returns:
            Les chemins des planches produites.

        Raises:
            ValueError: si la grille ne tient pas sur une page A4.
        """
        cfg = self._config
        cols, rows = cfg.export.cards_per_sheet
        per_sheet = cols * rows
        page_w, page_h = A4
        cut_pt = cfg.card.diameter_mm * mm
        bleed_pt = cfg.card.bleed_mm * mm
        cell_pt = cut_pt + 2 * bleed_pt
        margin_pt = cfg.export.sheet_margin_mm * mm

        if cols * cell_pt > page_w - 2 * margin_pt or rows * cell_pt > page_h - 2 * margin_pt:
            raise ValueError(
                "La grille de cartes ne tient pas sur une page A4 : réduisez le "
                "diamètre, le fond perdu ou le nombre de cartes par planche."
            )
        origin_x = (page_w - cols * cell_pt) / 2.0
        origin_y = (page_h - rows * cell_pt) / 2.0

        def cell_origin(col: int, row: int) -> Tuple[float, float]:
            """Coin bas-gauche (points) de la cellule ; rangées de haut en bas."""
            return origin_x + col * cell_pt, origin_y + (rows - 1 - row) * cell_pt

        back_reader = ImageReader(back_with_bleed) if back_with_bleed is not None else None
        chunks = [cards_with_bleed[i : i + per_sheet] for i in range(0, len(cards_with_bleed), per_sheet)]
        sheet_paths: List[Path] = []

        for sheet_index, chunk in enumerate(chunks, start=1):
            path = self._paths.sheets_dir / f"sheet_{sheet_index:02d}.pdf"
            pdf = pdf_canvas.Canvas(str(path), pagesize=A4)
            pdf.setTitle(f"OpenDobble — Planche {sheet_index}")

            for slot, card in enumerate(chunk):
                x, y = cell_origin(slot % cols, slot // cols)
                pdf.drawImage(ImageReader(card.image), x, y, width=cell_pt, height=cell_pt, mask="auto")
                self._draw_crop_marks(pdf, x + bleed_pt, y + bleed_pt, cut_pt)
            self._draw_footer(pdf, margin_pt, sheet_index, len(chunks), "recto" if back_reader else None)
            pdf.showPage()

            if back_reader is not None:
                for slot in range(len(chunk)):
                    x, y = cell_origin(cols - 1 - slot % cols, slot // cols)
                    pdf.drawImage(back_reader, x, y, width=cell_pt, height=cell_pt, mask="auto")
                    self._draw_crop_marks(pdf, x + bleed_pt, y + bleed_pt, cut_pt)
                self._draw_footer(pdf, margin_pt, sheet_index, len(chunks), "verso")
                pdf.showPage()

            pdf.save()
            sheet_paths.append(path)
        return sheet_paths

    def _draw_footer(
        self, pdf: pdf_canvas.Canvas, margin_pt: float, index: int, count: int, side: Optional[str]
    ) -> None:
        """Écrit la ligne d'information technique en pied de planche."""
        cfg = self._config
        side_label = f" — {side} — imprimer recto-verso, retournement bord long" if side else ""
        pdf.setFont("Helvetica", 7)
        pdf.setFillColorRGB(0.55, 0.55, 0.55)
        pdf.drawString(
            margin_pt,
            5 * mm,
            f"Planche {index}/{count}{side_label} — coupe Ø {cfg.card.diameter_mm:g} mm — "
            f"fond perdu {cfg.card.bleed_mm:g} mm — {cfg.export.dpi} dpi",
        )

    def _draw_crop_marks(self, pdf: pdf_canvas.Canvas, cut_x: float, cut_y: float, cut_size: float) -> None:
        """Trace les traits de coupe aux coins du carré de coupe d'une carte.

        Args:
            pdf: canevas reportlab de la page en cours.
            cut_x: abscisse (points) du coin bas-gauche de la zone de coupe.
            cut_y: ordonnée (points) du coin bas-gauche de la zone de coupe.
            cut_size: côté (points) du carré de coupe (= diamètre de la carte).
        """
        cfg = self._config.export
        length = cfg.crop_mark_length_mm * mm
        gap = cfg.crop_mark_gap_mm * mm
        pdf.setLineWidth(0.3)
        pdf.setStrokeColorRGB(0.1, 0.1, 0.1)
        x0, y0, x1, y1 = cut_x, cut_y, cut_x + cut_size, cut_y + cut_size
        for cx, cy, dx, dy in ((x0, y0, -1, -1), (x1, y0, 1, -1), (x0, y1, -1, 1), (x1, y1, 1, 1)):
            pdf.line(cx + dx * gap, cy, cx + dx * (gap + length), cy)
            pdf.line(cx, cy + dy * gap, cx, cy + dy * (gap + length))

        # Cercle de coupe indicatif, très fin (aide à la découpe ronde).
        pdf.setLineWidth(0.2)
        pdf.setStrokeColorRGB(0.6, 0.6, 0.6)
        pdf.setDash(2, 3)
        pdf.circle(cut_x + cut_size / 2.0, cut_y + cut_size / 2.0, cut_size / 2.0)
        pdf.setDash()


def _svg_color(color: Sequence[int]) -> str:
    """Convertit un tuple RGBA en couleur SVG ``rgb(r,g,b)``."""
    return f"rgb({color[0]},{color[1]},{color[2]})"


def _data_uri(image: Image.Image) -> str:
    """Encode une image Pillow en data-URI PNG base64 pour SVG."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
