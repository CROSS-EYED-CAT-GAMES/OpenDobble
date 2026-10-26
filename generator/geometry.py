"""Primitives géométriques du moteur de placement.

Toutes les positions sont exprimées dans le repère de la carte : origine au
centre, unités en pixels. Chaque symbole est approximé par son cercle
englobant, ce qui rend les tests de collision exacts, rapides et
indépendants de la rotation de l'image.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator, List, Sequence, Tuple

#: Angle d'or en radians, utilisé pour l'initialisation en spirale.
GOLDEN_ANGLE: float = math.pi * (3.0 - math.sqrt(5.0))


@dataclass
class CirclePlacement:
    """Position et taille d'un symbole approximé par un cercle.

    Attributes:
        x: abscisse du centre (repère carte).
        y: ordonnée du centre (repère carte).
        radius: rayon du cercle englobant du symbole.
        rotation_deg: rotation appliquée à l'image, en degrés.
    """

    x: float
    y: float
    radius: float
    rotation_deg: float = 0.0


def circles_overlap(a: CirclePlacement, b: CirclePlacement, padding: float = 0.0) -> bool:
    """Indique si deux cercles se chevauchent, marge ``padding`` comprise."""
    limit = a.radius + b.radius + padding
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2 < limit * limit


def overlap_amount(a: CirclePlacement, b: CirclePlacement, padding: float = 0.0) -> float:
    """Profondeur de pénétration entre deux cercles (0 si disjoints)."""
    return max(0.0, a.radius + b.radius + padding - math.hypot(a.x - b.x, a.y - b.y))


def containment_violation(circle: CirclePlacement, container_radius: float) -> float:
    """Dépassement du cercle hors de la zone utile de la carte (0 si inclus)."""
    return max(0.0, math.hypot(circle.x, circle.y) + circle.radius - container_radius)


def clamp_into_container(circle: CirclePlacement, container_radius: float) -> None:
    """Ramène (en place) un cercle strictement à l'intérieur du conteneur."""
    dist = math.hypot(circle.x, circle.y)
    max_dist = container_radius - circle.radius
    if max_dist <= 0.0:
        circle.x = circle.y = 0.0
    elif dist > max_dist:
        scale = max_dist / dist
        circle.x *= scale
        circle.y *= scale


def sunflower_seeds(count: int, radius: float) -> Iterator[Tuple[float, float]]:
    """Génère ``count`` points répartis en spirale de tournesol (Vogel).

    La spirale à angle d'or fournit une répartition initiale très homogène
    dans un disque, ce qui accélère la convergence de la relaxation.
    """
    for k in range(count):
        r = radius * math.sqrt((k + 0.5) / count)
        theta = k * GOLDEN_ANGLE
        yield r * math.cos(theta), r * math.sin(theta)


def total_overlap_energy(
    circles: Sequence[CirclePlacement], container_radius: float, padding: float
) -> float:
    """Énergie globale d'une configuration (0 = placement valide).

    Somme des carrés des pénétrations entre paires et des dépassements hors
    de la carte ; sert de score pour le recuit simulé.
    """
    energy = 0.0
    for i, a in enumerate(circles):
        energy += containment_violation(a, container_radius) ** 2
        for b in circles[i + 1 :]:
            energy += overlap_amount(a, b, padding) ** 2
    return energy


def is_valid_layout(
    circles: Sequence[CirclePlacement],
    container_radius: float,
    padding: float,
    tolerance: float = 1e-6,
) -> bool:
    """Vérifie qu'aucun chevauchement ni débordement n'existe."""
    for i, a in enumerate(circles):
        if containment_violation(a, container_radius) > tolerance:
            return False
        for b in circles[i + 1 :]:
            if overlap_amount(a, b, padding) > tolerance:
                return False
    return True


def spread_positions(circles: List[CirclePlacement], container_radius: float) -> None:
    """Écarte légèrement les cercles confondus pour éviter les divisions par 0."""
    for index, circle in enumerate(circles):
        for other in circles[index + 1 :]:
            if abs(circle.x - other.x) < 1e-9 and abs(circle.y - other.y) < 1e-9:
                other.x += container_radius * 0.01 * (index + 1)
                other.y -= container_radius * 0.01 * (index + 1)
