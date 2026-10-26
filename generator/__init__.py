"""Générateur de jeu de type Dobble (plan projectif d'ordre 7).

Sous-modules :

* :mod:`generator.config`   — configuration et thèmes ;
* :mod:`generator.cards`    — construction mathématique et validation du deck ;
* :mod:`generator.geometry` — primitives géométriques ;
* :mod:`generator.layout`   — moteur de placement (forces + recuit + croissance) ;
* :mod:`generator.renderer` — rendu Pillow (contours, ombres, liserés, dos) ;
* :mod:`generator.export`   — exports PNG / SVG / PDF / planches A4 ;
* :mod:`generator.utils`    — logging, progression, bibliothèque d'images.
"""

from .cards import Card, Deck, DeckValidationError, generate_deck, validate_deck
from .config import (
    THEMES,
    AppConfig,
    BackConfig,
    CardConfig,
    ExportConfig,
    ImportConfig,
    LayoutConfig,
    Theme,
)

__all__ = [
    "AppConfig",
    "BackConfig",
    "Card",
    "CardConfig",
    "Deck",
    "DeckValidationError",
    "ExportConfig",
    "ImportConfig",
    "LayoutConfig",
    "THEMES",
    "Theme",
    "generate_deck",
    "validate_deck",
]

__version__ = "1.2.0"
