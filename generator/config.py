"""Configuration centrale du générateur Dobble.

Tous les paramètres modifiables du projet sont regroupés ici sous forme de
``dataclasses`` typées et gelées. Aucune variable globale mutable n'est
utilisée : les objets de configuration sont construits puis passés
explicitement aux différents composants (layout, renderer, export...).

Unités :
    * les dimensions physiques sont exprimées en millimètres (mm) ;
    * les dimensions écran sont converties en pixels via le DPI demandé.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Constantes mathématiques du jeu (plan projectif d'ordre 7)
# ---------------------------------------------------------------------------

#: Ordre du plan projectif fini utilisé (doit être premier).
PLANE_ORDER: int = 7

#: Nombre de symboles par carte : n + 1.
SYMBOLS_PER_CARD: int = PLANE_ORDER + 1

#: Nombre total de cartes et de symboles : n² + n + 1.
DECK_SIZE: int = PLANE_ORDER * PLANE_ORDER + PLANE_ORDER + 1

#: Conversion millimètres -> pouces.
MM_PER_INCH: float = 25.4


def mm_to_px(mm: float, dpi: int) -> int:
    """Convertit une longueur en millimètres vers des pixels entiers.

    Args:
        mm: longueur physique en millimètres.
        dpi: résolution en points par pouce.

    Returns:
        La longueur arrondie en pixels.
    """
    return int(round(mm / MM_PER_INCH * dpi))


# ---------------------------------------------------------------------------
# Thèmes graphiques
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Décrit un habillage graphique complet pour les cartes.

    Attributes:
        name: identifiant du thème.
        background_color: couleur de fond de la carte (RGBA).
        border_color: couleur du liseré (RGBA).
        border_width_mm: épaisseur du liseré en millimètres.
        outline_color: couleur du contour ajouté autour de chaque image.
        outline_width_mm: épaisseur de ce contour en millimètres.
        shadow_opacity: opacité de l'ombre portée (0.0 - 1.0).
        shadow_blur_mm: rayon de flou de l'ombre en millimètres.
        shadow_offset_mm: décalage (x, y) de l'ombre en millimètres.
        inner_ring: si vrai, dessine un second liseré fin décoratif.
        inner_ring_color: couleur du second liseré.
    """

    name: str
    background_color: Tuple[int, int, int, int] = (255, 255, 255, 255)
    border_color: Tuple[int, int, int, int] = (20, 20, 20, 255)
    border_width_mm: float = 1.2
    outline_color: Tuple[int, int, int, int] = (255, 255, 255, 255)
    outline_width_mm: float = 0.9
    shadow_opacity: float = 0.28
    shadow_blur_mm: float = 0.9
    shadow_offset_mm: Tuple[float, float] = (0.35, 0.55)
    inner_ring: bool = False
    inner_ring_color: Tuple[int, int, int, int] = (200, 200, 200, 255)


#: Bibliothèque des thèmes disponibles pour l'option ``--theme``.
THEMES: Dict[str, Theme] = {
    "classic": Theme(
        name="classic",
        background_color=(255, 255, 255, 255),
        border_color=(25, 25, 25, 255),
        border_width_mm=1.2,
        shadow_opacity=0.28,
    ),
    "pastel": Theme(
        name="pastel",
        background_color=(252, 246, 238, 255),
        border_color=(233, 168, 180, 255),
        border_width_mm=1.6,
        outline_color=(255, 253, 250, 255),
        shadow_opacity=0.18,
        shadow_blur_mm=1.2,
        inner_ring=True,
        inner_ring_color=(244, 214, 220, 255),
    ),
    "dark": Theme(
        name="dark",
        background_color=(28, 30, 38, 255),
        border_color=(240, 240, 240, 255),
        border_width_mm=1.0,
        outline_color=(245, 245, 245, 255),
        outline_width_mm=1.1,
        shadow_opacity=0.55,
        shadow_blur_mm=1.1,
        shadow_offset_mm=(0.4, 0.7),
    ),
    "kids": Theme(
        name="kids",
        background_color=(255, 250, 215, 255),
        border_color=(255, 122, 89, 255),
        border_width_mm=2.4,
        outline_color=(255, 255, 255, 255),
        outline_width_mm=1.3,
        shadow_opacity=0.22,
        inner_ring=True,
        inner_ring_color=(120, 196, 255, 255),
    ),
    "minimal": Theme(
        name="minimal",
        background_color=(255, 255, 255, 255),
        border_color=(0, 0, 0, 255),
        border_width_mm=0.4,
        outline_color=(255, 255, 255, 255),
        outline_width_mm=0.6,
        shadow_opacity=0.0,
        shadow_blur_mm=0.0,
        shadow_offset_mm=(0.0, 0.0),
    ),
}


# ---------------------------------------------------------------------------
# Configuration de la carte
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardConfig:
    """Paramètres géométriques d'une carte ronde.

    Attributes:
        diameter_mm: diamètre de coupe de la carte.
        margin_mm: marge de sécurité entre le liseré et les images.
        bleed_mm: fond perdu (le fond déborde de la ligne de coupe).
    """

    diameter_mm: float = 88.0
    margin_mm: float = 4.0
    bleed_mm: float = 3.0

    def diameter_px(self, dpi: int) -> int:
        """Diamètre de coupe en pixels pour un DPI donné."""
        return mm_to_px(self.diameter_mm, dpi)

    def bleed_px(self, dpi: int) -> int:
        """Fond perdu en pixels pour un DPI donné."""
        return mm_to_px(self.bleed_mm, dpi)


# ---------------------------------------------------------------------------
# Configuration du moteur de placement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutConfig:
    """Paramètres du moteur de placement (force-directed + recuit simulé).

    Les tailles sont exprimées en fraction du rayon utile de la carte.

    Attributes:
        size_fractions: répartition (grande, moyenne, petite) des symboles.
        size_ranges: intervalles de rayon relatif pour chaque catégorie.
        size_jitter: bruit relatif appliqué à chaque taille (naturel).
        max_rotation_deg: rotation aléatoire maximale des images.
        padding_mm: espace minimal garanti entre deux images.
        iterations: nombre d'itérations de relaxation par tentative.
        growth_passes: nombre de passes de « croissance » pour combler les vides.
        growth_factor: facteur d'agrandissement testé à chaque passe.
        max_attempts: nombre de tentatives avant abandon.
        shrink_on_fail: facteur de réduction appliqué si le placement échoue.
    """

    size_fractions: Tuple[float, float, float] = (0.30, 0.40, 0.30)
    size_ranges: Tuple[Tuple[float, float], ...] = (
        (0.30, 0.36),  # grandes
        (0.23, 0.28),  # moyennes
        (0.16, 0.21),  # petites
    )
    size_jitter: float = 0.05
    max_rotation_deg: float = 360.0
    padding_mm: float = 1.0
    iterations: int = 420
    growth_passes: int = 10
    growth_factor: float = 1.035
    max_attempts: int = 6
    shrink_on_fail: float = 0.94


# ---------------------------------------------------------------------------
# Configuration de l'import des images sources
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportConfig:
    """Paramètres de chargement de la bibliothèque d'images.

    Attributes:
        extensions: extensions de fichiers acceptées (minuscules).
        background_mode: politique de détourage des images sans transparence :

            * ``"auto"`` (défaut) — détoure uniquement si l'image ressemble
              vraiment à un sujet sur fond uni : bordure de couleur homogène
              et proportion de fond retirée dans des limites raisonnables.
              Les photos, affiches, drapeaux et visuels pleine page sont
              conservés tels quels (rectangulaires) ;
            * ``"always"`` — détoure toute image sans transparence utile ;
            * ``"never"`` — ne détoure jamais.

            Contrôle par image : un fichier dont le nom contient ``.keep.``
            (ex. ``014.keep.jpg``) n'est jamais détouré ; ``.cut.``
            (ex. ``046.cut.jpg``) est toujours détouré.
        background_tolerance: tolérance de couleur du détourage (0-255).
        alpha_threshold: proportion de pixels non opaques en dessous de
            laquelle une image est jugée sans transparence utile.
        border_uniformity_max: (mode auto) écart-type maximal des couleurs de
            la bordure pour que le fond soit jugé uni.
        min_removed_ratio: (mode auto) en dessous de cette proportion de fond
            retiré, le détourage est jugé inutile et annulé.
        max_removed_ratio: (mode auto) au-dessus, l'image est probablement un
            logo ou un texte sur aplat : elle est conservée telle quelle.
        corner_radius_ratio: arrondi des coins des images conservées
            rectangulaires, en fraction du plus petit côté (0 = coins vifs).
    """

    extensions: Tuple[str, ...] = (".png", ".webp", ".jpg", ".jpeg")
    background_mode: str = "auto"
    background_tolerance: int = 40
    alpha_threshold: float = 0.005
    border_uniformity_max: float = 12.0
    min_removed_ratio: float = 0.04
    max_removed_ratio: float = 0.75
    corner_radius_ratio: float = 0.08


# ---------------------------------------------------------------------------
# Configuration du dos de carte
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackConfig:
    """Paramètres du dos de carte (verso).

    Attributes:
        mode: mise à l'échelle de l'illustration dans le disque :
            ``"cover"`` remplit tout le disque (et le fond perdu) ;
            ``"fit"`` garde l'illustration entière, centrée, avec une marge.
        fit_margin_mm: marge entre l'illustration et le liseré en mode fit.
        draw_border: dessiner le même liseré qu'au recto.
        background_color: couleur derrière l'illustration ; ``None`` reprend
            la couleur de fond du thème actif.
    """

    mode: str = "cover"
    fit_margin_mm: float = 8.0
    draw_border: bool = True
    background_color: Tuple[int, int, int, int] | None = None


# ---------------------------------------------------------------------------
# Configuration des exports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportConfig:
    """Paramètres des fichiers produits.

    Attributes:
        dpi: résolution des PNG et du PDF.
        export_png: activer l'export des 57 PNG HD.
        export_svg: activer l'export des 57 SVG.
        export_pdf: activer le PDF regroupant toutes les cartes.
        export_sheets: activer les planches A4 prêtes à imprimer.
        cards_per_sheet: nombre de cartes par planche A4 (colonnes, lignes).
        sheet_margin_mm: marge extérieure minimale des planches.
        crop_mark_length_mm: longueur des traits de coupe.
        crop_mark_gap_mm: distance entre le trait et la zone de coupe.
    """

    dpi: int = 300
    export_png: bool = True
    export_svg: bool = True
    export_pdf: bool = True
    export_sheets: bool = True
    cards_per_sheet: Tuple[int, int] = (2, 3)
    sheet_margin_mm: float = 6.0
    crop_mark_length_mm: float = 4.0
    crop_mark_gap_mm: float = 1.5


# ---------------------------------------------------------------------------
# Configuration globale de l'application
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppConfig:
    """Agrège l'ensemble des configurations du projet.

    Attributes:
        card: paramètres de la carte.
        layout: paramètres du moteur de placement.
        export: paramètres des exports.
        imports: paramètres de chargement des images sources.
        back: paramètres du dos de carte.
        theme: thème graphique actif.
        seed: graine aléatoire (reproductibilité) ; ``None`` = aléatoire.
    """

    card: CardConfig = field(default_factory=CardConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    imports: ImportConfig = field(default_factory=ImportConfig)
    back: BackConfig = field(default_factory=BackConfig)
    theme: Theme = field(default_factory=lambda: THEMES["classic"])
    seed: int | None = None

    def with_theme(self, theme_name: str) -> "AppConfig":
        """Retourne une copie de la configuration avec un autre thème.

        Raises:
            KeyError: si le thème demandé n'existe pas.
        """
        if theme_name not in THEMES:
            valid = ", ".join(sorted(THEMES))
            raise KeyError(f"Thème inconnu '{theme_name}'. Thèmes valides : {valid}")
        return replace(self, theme=THEMES[theme_name])

    def with_dpi(self, dpi: int) -> "AppConfig":
        """Retourne une copie de la configuration avec un autre DPI.

        Raises:
            ValueError: si le DPI est inférieur à 72.
        """
        if dpi < 72:
            raise ValueError("Le DPI doit être supérieur ou égal à 72.")
        return replace(self, export=replace(self.export, dpi=dpi))
