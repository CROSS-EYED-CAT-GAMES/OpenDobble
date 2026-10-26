"""Moteur de placement des symboles sur une carte.

Stratégie hybride en trois phases, inspirée des « force directed layouts »
et du recuit simulé :

1. **Initialisation** : chaque symbole reçoit une taille (grande / moyenne /
   petite selon la distribution configurée, avec bruit naturel) et une
   position initiale sur une spirale de tournesol, déjà quasi homogène.

2. **Relaxation par forces + recuit** : des forces de répulsion séparent les
   cercles qui se pénètrent, une force de confinement les garde dans la
   carte, et une agitation thermique décroissante permet d'échapper aux
   minima locaux. La meilleure configuration rencontrée est mémorisée.

3. **Croissance** : une fois une configuration valide obtenue, toutes les
   images sont agrandies progressivement tant que le placement reste valide,
   pour combler les vides et obtenir l'aspect dense des jeux commerciaux.

Si aucune configuration valide n'est trouvée, les tailles sont réduites
d'un facteur configurable et le processus recommence.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .config import LayoutConfig
from .geometry import (
    CirclePlacement,
    clamp_into_container,
    is_valid_layout,
    overlap_amount,
    spread_positions,
    sunflower_seeds,
    total_overlap_energy,
)

logger = logging.getLogger(__name__)


class LayoutError(RuntimeError):
    """Levée si le moteur ne parvient pas à placer les symboles."""


@dataclass(frozen=True)
class PlacedSymbol:
    """Résultat final du placement d'un symbole sur une carte.

    Attributes:
        symbol_id: identifiant du symbole (0 à 56).
        x: abscisse du centre (repère carte, origine au centre).
        y: ordonnée du centre.
        radius: rayon du cercle englobant alloué, en pixels.
        rotation_deg: rotation de l'image en degrés.
    """

    symbol_id: int
    x: float
    y: float
    radius: float
    rotation_deg: float


class LayoutEngine:
    """Place ``n`` symboles dans un disque sans chevauchement.

    Args:
        config: paramètres du moteur (tailles, itérations, marges...).
        rng: générateur pseudo-aléatoire dédié (reproductibilité).
    """

    def __init__(self, config: LayoutConfig, rng: random.Random) -> None:
        self._config = config
        self._rng = rng

    def layout_card(
        self, symbol_ids: Sequence[int], usable_radius: float, padding_px: float
    ) -> List[PlacedSymbol]:
        """Calcule le placement complet d'une carte.

        Args:
            symbol_ids: identifiants des symboles à placer (8 en général).
            usable_radius: rayon utile de la carte en pixels.
            padding_px: espace minimal entre deux images, en pixels.

        Returns:
            Les :class:`PlacedSymbol`, dans l'ordre de ``symbol_ids``.

        Raises:
            LayoutError: si aucun placement valide n'est trouvé.
        """
        count = len(symbol_ids)
        scale = 1.0
        for attempt in range(1, self._config.max_attempts + 1):
            circles = self._initial_circles(self._draw_radii(count, usable_radius, scale), usable_radius)
            self._relax(circles, usable_radius, padding_px)
            if is_valid_layout(circles, usable_radius, padding_px):
                self._grow(circles, usable_radius, padding_px)
                self._rng.shuffle(circles)  # casse la corrélation taille/ordre
                return [
                    PlacedSymbol(
                        symbol_id=symbol_id,
                        x=c.x,
                        y=c.y,
                        radius=c.radius,
                        rotation_deg=self._rng.uniform(0.0, self._config.max_rotation_deg),
                    )
                    for symbol_id, c in zip(symbol_ids, circles)
                ]
            scale *= self._config.shrink_on_fail
            logger.debug("Placement invalide (tentative %d) : échelle %.2f.", attempt, scale)
        raise LayoutError(
            f"Impossible de placer {count} symboles dans un rayon de "
            f"{usable_radius:.0f}px après {self._config.max_attempts} tentatives."
        )

    # ------------------------------------------------------------------
    # Phase 1 : tailles et positions initiales
    # ------------------------------------------------------------------

    def _draw_radii(self, count: int, usable_radius: float, scale: float) -> List[float]:
        """Tire les rayons selon la distribution grandes/moyennes/petites."""
        cfg = self._config
        counts = [int(round(f * count)) for f in cfg.size_fractions]
        while sum(counts) > count:
            counts[counts.index(max(counts))] -= 1
        while sum(counts) < count:
            counts[counts.index(min(counts))] += 1
        categories = [cat for cat, n in enumerate(counts) for _ in range(n)]
        self._rng.shuffle(categories)

        radii: List[float] = []
        for category in categories:
            low, high = cfg.size_ranges[category]
            jitter = 1.0 + self._rng.uniform(-cfg.size_jitter, cfg.size_jitter)
            radii.append(self._rng.uniform(low, high) * jitter * scale * usable_radius)
        return radii

    def _initial_circles(self, radii: Sequence[float], usable_radius: float) -> List[CirclePlacement]:
        """Positionne les cercles sur une spirale de tournesol."""
        seeds = list(sunflower_seeds(len(radii), usable_radius * 0.65))
        self._rng.shuffle(seeds)
        circles = [CirclePlacement(x=sx, y=sy, radius=r) for (sx, sy), r in zip(seeds, radii)]
        spread_positions(circles, usable_radius)
        return circles

    # ------------------------------------------------------------------
    # Phase 2 : relaxation par forces + recuit simulé
    # ------------------------------------------------------------------

    def _push_apart(self, circles: List[CirclePlacement], padding_px: float) -> bool:
        """Applique une passe de répulsion ; retourne vrai si un cercle a bougé."""
        moved = False
        for i, a in enumerate(circles):
            for b in circles[i + 1 :]:
                depth = overlap_amount(a, b, padding_px)
                if depth <= 0.0:
                    continue
                dx, dy = b.x - a.x, b.y - a.y
                dist = math.hypot(dx, dy)
                if dist < 1e-9:
                    angle = self._rng.uniform(0.0, math.tau)
                    dx, dy, dist = math.cos(angle), math.sin(angle), 1.0
                push = 0.5 * depth / dist
                a.x -= dx * push
                a.y -= dy * push
                b.x += dx * push
                b.y += dy * push
                moved = True
        return moved

    def _relax(self, circles: List[CirclePlacement], usable_radius: float, padding_px: float) -> None:
        """Fait converger les cercles vers une configuration sans collision."""
        cfg = self._config
        best_energy = math.inf
        best_state: List[Tuple[float, float]] = [(c.x, c.y) for c in circles]

        for iteration in range(cfg.iterations):
            temperature = max(0.0, 1.0 - iteration / (cfg.iterations * 0.75))
            self._push_apart(circles, padding_px)
            if temperature > 0.0:
                amplitude = temperature * usable_radius * 0.02
                for c in circles:
                    c.x += self._rng.uniform(-amplitude, amplitude)
                    c.y += self._rng.uniform(-amplitude, amplitude)
            for c in circles:
                clamp_into_container(c, usable_radius)

            energy = total_overlap_energy(circles, usable_radius, padding_px)
            if energy < best_energy:
                best_energy = energy
                best_state = [(c.x, c.y) for c in circles]
                if energy == 0.0 and temperature == 0.0:
                    break

        for c, (bx, by) in zip(circles, best_state):
            c.x, c.y = bx, by

    # ------------------------------------------------------------------
    # Phase 3 : croissance pour combler les vides
    # ------------------------------------------------------------------

    def _grow(self, circles: List[CirclePlacement], usable_radius: float, padding_px: float) -> None:
        """Agrandit les images tant que le placement reste valide.

        Chaque passe agrandit tous les cercles d'un petit facteur puis relance
        une courte relaxation déterministe ; si la configuration devient
        invalide, la passe est annulée et la croissance s'arrête.
        """
        cfg = self._config
        for _ in range(cfg.growth_passes):
            snapshot = [(c.x, c.y, c.radius) for c in circles]
            for c in circles:
                c.radius *= cfg.growth_factor
            for _step in range(60):
                moved = self._push_apart(circles, padding_px)
                for c in circles:
                    clamp_into_container(c, usable_radius)
                if not moved:
                    break
            if not is_valid_layout(circles, usable_radius, padding_px):
                for c, (x, y, r) in zip(circles, snapshot):
                    c.x, c.y, c.radius = x, y, r
                return
