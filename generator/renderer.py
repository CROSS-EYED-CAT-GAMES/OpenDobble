"""Rendu graphique des cartes avec Pillow.

Chaque symbole subit une chaîne de traitement :

1. mise à l'échelle pour tenir dans le cercle alloué par le moteur de
   placement ;
2. rotation (ré-échantillonnage bicubique, canevas étendu) ;
3. contour coloré par dilatation du canal alpha, qui améliore la lisibilité
   lorsque deux images sont proches ;
4. ombre portée discrète (alpha flouté, décalé et teinté).

Les disques et liserés sont dessinés en supersampling (×2) pour des bords
parfaitement lisses, puis réduits à la taille finale.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter

from .config import AppConfig, Theme, mm_to_px
from .layout import PlacedSymbol
from .utils import SymbolImage

logger = logging.getLogger(__name__)

#: Facteur de supersampling pour l'anticrénelage des cercles.
SUPERSAMPLE: int = 2


@dataclass(frozen=True)
class RenderedCard:
    """Résultat du rendu d'une carte.

    Attributes:
        index: numéro de la carte.
        image: image RGBA finale (transparente hors du disque).
        placements: placements utilisés (repris par l'export SVG).
    """

    index: int
    image: Image.Image
    placements: Tuple[PlacedSymbol, ...]


def _disc_mask(size: int) -> Image.Image:
    """Masque circulaire lisse (supersampling) de ``size × size`` pixels."""
    big = Image.new("L", (size * SUPERSAMPLE, size * SUPERSAMPLE), 0)
    ImageDraw.Draw(big).ellipse((0, 0, big.width - 1, big.height - 1), fill=255)
    return big.resize((size, size), Image.Resampling.LANCZOS)


class SymbolProcessor:
    """Applique mise à l'échelle, rotation, contour et ombre à un symbole.

    Args:
        theme: thème graphique actif (couleurs, épaisseurs, ombre).
        dpi: résolution cible, pour convertir les épaisseurs mm -> px.
    """

    def __init__(self, theme: Theme, dpi: int) -> None:
        self._theme = theme
        self._outline_px = max(1, mm_to_px(theme.outline_width_mm, dpi))
        self._shadow_blur_px = mm_to_px(theme.shadow_blur_mm, dpi)
        self._shadow_offset_px = (
            mm_to_px(theme.shadow_offset_mm[0], dpi),
            mm_to_px(theme.shadow_offset_mm[1], dpi),
        )

    def prepare(self, source: Image.Image, target_radius: float, rotation_deg: float) -> Image.Image:
        """Produit l'image finale d'un symbole, centrée, prête à être collée.

        Args:
            source: image RGBA rognée du symbole.
            target_radius: rayon du cercle englobant alloué, en pixels.
            rotation_deg: rotation à appliquer, en degrés.
        """
        scaled = self._scale_to_radius(source, target_radius)
        rotated = scaled.rotate(rotation_deg, resample=Image.Resampling.BICUBIC, expand=True)
        return self._add_shadow(self._add_outline(rotated))

    @staticmethod
    def _scale_to_radius(image: Image.Image, target_radius: float) -> Image.Image:
        """Redimensionne l'image pour que sa demi-diagonale ≈ ``target_radius``."""
        half_diagonal = 0.5 * math.hypot(image.width, image.height)
        scale = target_radius / half_diagonal if half_diagonal else 1.0
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        return image.resize(size, Image.Resampling.LANCZOS)

    def _add_outline(self, image: Image.Image) -> Image.Image:
        """Ajoute un contour coloré par dilatation morphologique du canal alpha.

        Des passes successives de ``MaxFilter(3)`` donnent une dilatation
        quasi circulaire ; la silhouette obtenue est glissée sous l'image.
        """
        pad = self._outline_px + 1
        canvas = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
        canvas.paste(image, (pad, pad), image)

        dilated = canvas.getchannel("A")
        for _ in range(self._outline_px):
            dilated = dilated.filter(ImageFilter.MaxFilter(3))
        dilated = dilated.filter(ImageFilter.GaussianBlur(0.5))

        result = Image.new("RGBA", canvas.size, self._theme.outline_color)
        result.putalpha(dilated)
        result.alpha_composite(canvas)
        return result

    def _add_shadow(self, image: Image.Image) -> Image.Image:
        """Ajoute une ombre portée douce sous l'image (si le thème l'active)."""
        opacity = self._theme.shadow_opacity
        if opacity <= 0.0:
            return image
        blur = self._shadow_blur_px
        ox, oy = self._shadow_offset_px
        pad = blur * 2 + max(abs(ox), abs(oy)) + 2
        size = (image.width + 2 * pad, image.height + 2 * pad)

        shadow_alpha = Image.new("L", size, 0)
        shadow_alpha.paste(image.getchannel("A"), (pad + ox, pad + oy))
        if blur > 0:
            shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(blur))
        shadow = Image.new("RGBA", size, (10, 10, 12, 255))
        shadow.putalpha(shadow_alpha.point(lambda v: int(v * opacity)))

        shadow.alpha_composite(image, (pad, pad))
        return shadow


class CardRenderer:
    """Assemble le fond, le liseré et les symboles d'une carte.

    Args:
        config: configuration globale de l'application.
        background: texture optionnelle (``assets/background.png``) plaquée
            dans le disque sous les symboles.
    """

    def __init__(self, config: AppConfig, background: Optional[Image.Image] = None) -> None:
        self._config = config
        self._theme = config.theme
        self._dpi = config.export.dpi
        self._processor = SymbolProcessor(config.theme, config.export.dpi)
        self._background = background.convert("RGBA") if background else None

    # ------------------------------------------------------------------
    # Géométrie utile
    # ------------------------------------------------------------------

    @property
    def diameter_px(self) -> int:
        """Diamètre de coupe de la carte en pixels."""
        return self._config.card.diameter_px(self._dpi)

    @property
    def usable_radius_px(self) -> float:
        """Rayon disponible pour les symboles (coupe - liseré - marge)."""
        border = mm_to_px(self._theme.border_width_mm, self._dpi)
        margin = mm_to_px(self._config.card.margin_mm, self._dpi)
        return self.diameter_px / 2.0 - border - margin

    @property
    def padding_px(self) -> float:
        """Espace minimal entre deux images, en pixels."""
        return mm_to_px(self._config.layout.padding_mm, self._dpi)

    # ------------------------------------------------------------------
    # Recto
    # ------------------------------------------------------------------

    def render_card(
        self,
        card_index: int,
        placements: Sequence[PlacedSymbol],
        library: Sequence[SymbolImage],
        bleed_px: int = 0,
    ) -> RenderedCard:
        """Rend une carte complète.

        Args:
            card_index: numéro de la carte (0 à 56).
            placements: placements calculés par le :class:`LayoutEngine`.
            library: bibliothèque d'images indexée par identifiant de symbole.
            bleed_px: fond perdu autour de la ligne de coupe (0 pour les PNG
                unitaires, > 0 pour les planches d'impression).
        """
        size = self.diameter_px + 2 * bleed_px
        card = self._draw_base(size)
        center = size / 2.0
        for placement in placements:
            sprite = self._processor.prepare(
                library[placement.symbol_id].image, placement.radius, placement.rotation_deg
            )
            card.alpha_composite(
                sprite,
                (
                    int(round(center + placement.x - sprite.width / 2.0)),
                    int(round(center + placement.y - sprite.height / 2.0)),
                ),
            )
        return RenderedCard(
            index=card_index,
            image=self._clip_and_border(card, bleed_px),
            placements=tuple(placements),
        )

    # ------------------------------------------------------------------
    # Verso
    # ------------------------------------------------------------------

    def render_back(self, back_image: Image.Image, bleed_px: int = 0) -> Image.Image:
        """Rend le dos de carte (verso) avec l'illustration fournie.

        Args:
            back_image: illustration du dos (tout format Pillow).
            bleed_px: fond perdu autour de la ligne de coupe.

        Returns:
            Une image RGBA de même taille que les cartes recto rendues avec
            le même ``bleed_px``, transparente hors du disque.

        Raises:
            ValueError: si ``config.back.mode`` est inconnu.
        """
        back_cfg = self._config.back
        size = self.diameter_px + 2 * bleed_px
        artwork = back_image.convert("RGBA")
        color = back_cfg.background_color or self._theme.background_color
        card = Image.new("RGBA", (size, size), color)

        if back_cfg.mode == "cover":
            scale = size / min(artwork.width, artwork.height)
        elif back_cfg.mode == "fit":
            margin = mm_to_px(back_cfg.fit_margin_mm, self._dpi)
            border = mm_to_px(self._theme.border_width_mm, self._dpi)
            scale = (size - 2 * (bleed_px + border + margin)) / max(artwork.size)
        else:
            raise ValueError(f"Mode de dos inconnu '{back_cfg.mode}' (attendu 'cover' ou 'fit').")

        scaled = artwork.resize(
            (max(1, round(artwork.width * scale)), max(1, round(artwork.height * scale))),
            Image.Resampling.LANCZOS,
        )
        card.alpha_composite(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2))
        if back_cfg.draw_border:
            return self._clip_and_border(card, bleed_px)
        clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        clipped.paste(card, (0, 0), _disc_mask(size))
        return clipped

    # ------------------------------------------------------------------
    # Étapes internes
    # ------------------------------------------------------------------

    def _draw_base(self, size: int) -> Image.Image:
        """Prépare le fond carré de la carte (couleur + texture optionnelle).

        Le rognage circulaire est appliqué à la fin par
        :meth:`_clip_and_border` ; le fond couvre aussi le fond perdu.
        """
        base = Image.new("RGBA", (size, size), self._theme.background_color)
        if self._background is not None:
            texture = self._background.resize((size, size), Image.Resampling.LANCZOS)
            base.alpha_composite(texture)
        return base

    def _clip_and_border(self, card: Image.Image, bleed_px: int) -> Image.Image:
        """Rogne la carte au disque extérieur et trace le(s) liseré(s)."""
        size = card.width
        ss = SUPERSAMPLE
        border_px = mm_to_px(self._theme.border_width_mm, self._dpi)

        clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        clipped.paste(card, (0, 0), _disc_mask(size))

        ring = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
        draw = ImageDraw.Draw(ring)
        center = size * ss / 2.0
        cut_radius = (size / 2.0 - bleed_px) * ss
        r = cut_radius - border_px * ss / 2.0
        draw.ellipse(
            (center - r, center - r, center + r, center + r),
            outline=self._theme.border_color,
            width=max(1, border_px * ss),
        )
        if self._theme.inner_ring:
            r_in = cut_radius - border_px * ss * 2.2
            draw.ellipse(
                (center - r_in, center - r_in, center + r_in, center + r_in),
                outline=self._theme.inner_ring_color,
                width=max(1, int(border_px * ss * 0.45)),
            )
        clipped.alpha_composite(ring.resize((size, size), Image.Resampling.LANCZOS))
        return clipped
