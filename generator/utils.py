"""Utilitaires transverses : logging, barre de progression, bibliothèque d'images.

Aucune dépendance externe n'est utilisée pour la barre de progression afin de
respecter la liste de librairies imposée (Pillow, numpy, reportlab, svgwrite).
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import DECK_SIZE, ImportConfig

logger = logging.getLogger(__name__)


class ImageLibraryError(RuntimeError):
    """Levée si la bibliothèque d'images est invalide (nombre, format...)."""


def setup_logging(verbose: bool = False) -> None:
    """Configure le logging global (DEBUG si ``verbose``, sinon INFO)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


@dataclass
class ProgressBar:
    """Barre de progression minimaliste écrite sur ``stderr``.

    Attributes:
        total: nombre total d'étapes.
        label: libellé affiché à gauche de la barre.
        width: largeur de la barre en caractères.
    """

    total: int
    label: str = ""
    width: int = 32
    _current: int = 0

    def advance(self, step: int = 1) -> None:
        """Avance la barre de ``step`` étapes et rafraîchit l'affichage."""
        self._current = min(self.total, self._current + step)
        self._render()

    def finish(self) -> None:
        """Force la barre à 100 % et passe à la ligne."""
        self._current = self.total
        self._render()
        sys.stderr.write("\n")
        sys.stderr.flush()

    def _render(self) -> None:
        """Dessine la barre sur la ligne courante (retour chariot)."""
        ratio = self._current / self.total if self.total else 1.0
        filled = int(round(ratio * self.width))
        bar = "█" * filled + "░" * (self.width - filled)
        sys.stderr.write(
            f"\r{self.label:<24} |{bar}| {self._current}/{self.total} ({ratio * 100:5.1f}%)"
        )
        sys.stderr.flush()


@dataclass(frozen=True)
class SymbolImage:
    """Une image source de la bibliothèque.

    Attributes:
        symbol_id: identifiant du symbole (0 à 56) associé à l'image.
        path: chemin du fichier source.
        image: image Pillow chargée en RGBA et rognée sur son contenu.
    """

    symbol_id: int
    path: Path
    image: Image.Image


# ---------------------------------------------------------------------------
# Traitement de la transparence
# ---------------------------------------------------------------------------


def _trim_to_content(image: Image.Image) -> Image.Image:
    """Rogne l'image sur la boîte englobante de son canal alpha."""
    bbox = image.getchannel("A").getbbox()
    return image.crop(bbox) if bbox else image


def _has_useful_alpha(image: Image.Image, threshold: float) -> bool:
    """Indique si la proportion de pixels non opaques dépasse ``threshold``."""
    alpha = np.asarray(image.getchannel("A"))
    return float(np.mean(alpha < 250)) > threshold


def _border_uniformity(image: Image.Image) -> float:
    """Écart-type moyen des couleurs d'un anneau de 2 px le long des bords.

    Un fond uni donne ~0 ; une photo, un dégradé ou un drapeau une valeur élevée.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    ring = np.concatenate(
        [
            rgb[:2].reshape(-1, 3),
            rgb[-2:].reshape(-1, 3),
            rgb[:, :2].reshape(-1, 3),
            rgb[:, -2:].reshape(-1, 3),
        ]
    )
    return float(ring.std(axis=0).mean())


def _background_mask(image: Image.Image, tolerance: int) -> np.ndarray:
    """Masque booléen du fond uni connecté aux bords (flood fill vectorisé).

    La couleur de fond est estimée par la moyenne des quatre coins. Seuls les
    pixels proches de cette couleur **et connectés au bord** sont marqués :
    un aplat intérieur de même couleur (l'œil blanc d'un personnage sur fond
    blanc) est préservé, contrairement à un simple seuillage global.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]], dtype=np.float32)
    candidate = np.abs(rgb - corners.mean(axis=0)).mean(axis=2) <= tolerance

    mask = np.zeros(candidate.shape, dtype=bool)
    mask[0, :] = candidate[0, :]
    mask[-1, :] = candidate[-1, :]
    mask[:, 0] = candidate[:, 0]
    mask[:, -1] = candidate[:, -1]
    while True:
        grown = mask.copy()
        grown[1:, :] |= mask[:-1, :]
        grown[:-1, :] |= mask[1:, :]
        grown[:, 1:] |= mask[:, :-1]
        grown[:, :-1] |= mask[:, 1:]
        grown &= candidate
        if np.array_equal(grown, mask):
            return mask
        mask = grown


def _apply_background_mask(image: Image.Image, mask: np.ndarray) -> Image.Image:
    """Rend transparents les pixels du masque (alpha adouci sur ~1 px)."""
    result = image.convert("RGBA")
    alpha = np.asarray(result.getchannel("A"), dtype=np.uint8).copy()
    alpha[mask] = 0
    result.putalpha(Image.fromarray(alpha, mode="L").filter(ImageFilter.GaussianBlur(0.6)))
    return result


def _round_corners(image: Image.Image, ratio: float) -> Image.Image:
    """Arrondit les coins d'une image opaque (aspect « tuile photo »)."""
    radius = int(min(image.size) * ratio)
    if radius <= 0:
        return image
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1), radius=radius, fill=255
    )
    result = image.convert("RGBA")
    combined = np.minimum(np.asarray(result.getchannel("A")), np.asarray(mask)).astype(np.uint8)
    result.putalpha(Image.fromarray(combined, mode="L"))
    return result


def _process_opacity(image: Image.Image, path: Path, cfg: ImportConfig) -> Tuple[Image.Image, bool]:
    """Décide et applique (ou non) le détourage d'une image sans alpha utile.

    Politique : suffixes ``.keep.`` / ``.cut.`` prioritaires ; mode ``never``
    ou ``always`` ; en mode ``auto``, détourage seulement si la bordure est
    homogène et si la proportion retirée reste dans les bornes configurées.
    Les images conservées rectangulaires reçoivent des coins arrondis.

    Returns:
        ``(image transformée, détourée ?)``.
    """
    name = path.name.lower()
    force_cut = ".cut." in name
    force_keep = (".keep." in name or cfg.background_mode == "never") and not force_cut
    kept = (_round_corners(image, cfg.corner_radius_ratio), False)

    if force_keep:
        return kept

    auto = cfg.background_mode == "auto" and not force_cut
    if auto:
        uniformity = _border_uniformity(image)
        if uniformity > cfg.border_uniformity_max:
            logger.debug("%s : bordure non uniforme (%.1f), conservée.", path.name, uniformity)
            return kept

    mask = _background_mask(image, cfg.background_tolerance)
    removed = float(mask.mean())
    if auto and not (cfg.min_removed_ratio <= removed <= cfg.max_removed_ratio):
        logger.debug("%s : %.0f%% de fond, hors bornes : conservée.", path.name, removed * 100)
        return kept
    return _apply_background_mask(image, mask), True


# ---------------------------------------------------------------------------
# Chargement de la bibliothèque
# ---------------------------------------------------------------------------


def load_image_library(
    directory: Path,
    config: ImportConfig | None = None,
    expected_count: int = DECK_SIZE,
) -> List[SymbolImage]:
    """Charge et valide la bibliothèque des images sources.

    Formats acceptés : PNG, WebP, JPG/JPEG. Les images sans transparence
    utile suivent la politique ``config.background_mode`` (voir
    :class:`ImportConfig`).

    Args:
        directory: dossier contenant les images sources.
        config: paramètres d'import (``None`` = valeurs par défaut).
        expected_count: nombre d'images attendu (57 par défaut).

    Returns:
        Les :class:`SymbolImage` triées par nom de fichier ; l'identifiant de
        symbole correspond au rang alphabétique.

    Raises:
        ImageLibraryError: dossier absent, nombre d'images incorrect ou
            fichier illisible.
    """
    cfg = config or ImportConfig()
    if not directory.is_dir():
        raise ImageLibraryError(f"Le dossier d'images '{directory}' est introuvable.")

    paths = sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in cfg.extensions
    )
    if len(paths) != expected_count:
        raise ImageLibraryError(
            f"{len(paths)} images ({', '.join(cfg.extensions)}) trouvées dans "
            f"'{directory}' au lieu de {expected_count}."
        )

    detoured = 0
    library: List[SymbolImage] = []
    for symbol_id, path in enumerate(paths):
        try:
            with Image.open(path) as raw:
                image = raw.convert("RGBA")
        except OSError as exc:
            raise ImageLibraryError(f"Impossible d'ouvrir '{path}' : {exc}") from exc

        if not _has_useful_alpha(image, cfg.alpha_threshold):
            image, was_cut = _process_opacity(image, path, cfg)
            detoured += int(was_cut)

        image = _trim_to_content(image)
        if image.width < 8 or image.height < 8:
            raise ImageLibraryError(
                f"L'image '{path}' est vide ou trop petite après rognage "
                "(essayez une tolérance plus faible avec --bg-tolerance)."
            )
        library.append(SymbolImage(symbol_id=symbol_id, path=path, image=image))

    logger.info(
        "Bibliothèque chargée : %d images depuis '%s' (%d fond(s) détouré(s)).",
        len(library),
        directory,
        detoured,
    )
    return library


def find_optional_background(assets_dir: Path) -> Optional[Path]:
    """Retourne le chemin de ``assets/background.png`` s'il existe."""
    candidate = assets_dir / "background.png"
    return candidate if candidate.is_file() else None


def find_optional_back(assets_dir: Path) -> Optional[Path]:
    """Retourne l'illustration de dos par défaut (``assets/back.*``) si présente."""
    for name in ("back.png", "back.webp", "back.jpg", "back.jpeg"):
        candidate = assets_dir / name
        if candidate.is_file():
            return candidate
    return None
