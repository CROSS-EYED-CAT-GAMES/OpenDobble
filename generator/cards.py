"""Construction mathématique du jeu de cartes.

Un jeu de type Dobble est un plan projectif fini d'ordre ``n`` (avec ``n``
premier) : les *symboles* sont les points du plan et les *cartes* en sont les
droites. Deux droites distinctes d'un plan projectif se coupent toujours en
exactement un point, ce qui garantit la règle du jeu :

    « Deux cartes quelconques possèdent exactement une image en commun. »

Pour ``n = 7`` on obtient ``n² + n + 1 = 57`` symboles, ``57`` cartes et
``n + 1 = 8`` symboles par carte.

Construction utilisée :

* ``n²`` points affines ``(x, y)`` avec ``x, y ∈ GF(n)`` ;
* ``n`` points à l'infini, un par pente ``m ∈ GF(n)`` ;
* ``1`` point à l'infini pour la direction verticale.

Les droites sont :

* ``y = m·x + b (mod n)`` complétées du point à l'infini de pente ``m`` ;
* les droites verticales ``x = c`` complétées du point à l'infini vertical ;
* la droite à l'infini, formée de tous les points à l'infini.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import combinations
from typing import List, Tuple

from .config import PLANE_ORDER

logger = logging.getLogger(__name__)


class DeckValidationError(RuntimeError):
    """Levée lorsque le deck généré viole une règle du plan projectif."""


@dataclass(frozen=True)
class Card:
    """Une carte du jeu : un ensemble ordonné d'identifiants de symboles.

    Attributes:
        index: numéro de la carte (0 à 56).
        symbols: identifiants des 8 symboles présents sur la carte.
    """

    index: int
    symbols: Tuple[int, ...]

    def __post_init__(self) -> None:
        """Refuse une carte portant deux fois le même symbole."""
        if len(self.symbols) != len(set(self.symbols)):
            raise DeckValidationError(
                f"La carte {self.index} contient un symbole en double : {self.symbols}"
            )


@dataclass(frozen=True)
class Deck:
    """Le jeu complet construit mathématiquement.

    Attributes:
        order: ordre du plan projectif (7).
        cards: les ``n² + n + 1`` cartes.
    """

    order: int
    cards: Tuple[Card, ...] = field(default_factory=tuple)

    @property
    def symbol_count(self) -> int:
        """Nombre total de symboles distincts du deck."""
        return self.order * self.order + self.order + 1


def _is_prime(n: int) -> bool:
    """Teste la primalité de ``n`` (division par essais, suffisant ici)."""
    if n < 2:
        return False
    return all(n % d for d in range(2, int(n**0.5) + 1))


def generate_deck(order: int = PLANE_ORDER) -> Deck:
    """Génère le deck complet via la construction du plan projectif.

    Args:
        order: ordre ``n`` du plan projectif. Doit être premier (la
            construction par arithmétique modulaire n'est valable que dans un
            corps ; une puissance de premier nécessiterait GF(p^k)).

    Returns:
        Un :class:`Deck` validé contenant ``n² + n + 1`` cartes.

    Raises:
        ValueError: si ``order`` n'est pas premier.
        DeckValidationError: si le deck généré est invalide.
    """
    if not _is_prime(order):
        raise ValueError(f"L'ordre {order} n'est pas premier : construction impossible.")

    n = order

    def affine(x: int, y: int) -> int:
        """Identifiant du point affine (x, y) : indices 0 .. n²-1."""
        return y * n + x

    def infinity_slope(m: int) -> int:
        """Identifiant du point à l'infini de pente m : n² .. n²+n-1."""
        return n * n + m

    infinity_vertical = n * n + n
    raw_cards: List[Tuple[int, ...]] = []

    # 1) Droites de pente m : y = m·x + b (mod n)  ->  n² cartes.
    for m in range(n):
        for b in range(n):
            symbols = tuple(affine(x, (m * x + b) % n) for x in range(n))
            raw_cards.append(symbols + (infinity_slope(m),))

    # 2) Droites verticales x = c  ->  n cartes.
    for c in range(n):
        raw_cards.append(tuple(affine(c, y) for y in range(n)) + (infinity_vertical,))

    # 3) Droite à l'infini  ->  1 carte.
    raw_cards.append(tuple(infinity_slope(m) for m in range(n)) + (infinity_vertical,))

    deck = Deck(order=n, cards=tuple(Card(i, s) for i, s in enumerate(raw_cards)))
    validate_deck(deck)
    logger.info(
        "Deck généré : %d cartes, %d symboles, %d symboles/carte.",
        len(deck.cards),
        deck.symbol_count,
        n + 1,
    )
    return deck


def validate_deck(deck: Deck) -> None:
    """Vérifie exhaustivement les propriétés du plan projectif.

    Contrôles : nombre de cartes, nombre et plage des symboles, nombre de
    symboles par carte, intersection d'exactement un symbole pour chaque
    paire de cartes, et propriété duale (chaque symbole sur ``n + 1`` cartes).

    Raises:
        DeckValidationError: dès qu'une règle est violée.
    """
    n = deck.order
    expected = n * n + n + 1
    per_card = n + 1

    if len(deck.cards) != expected:
        raise DeckValidationError(f"{len(deck.cards)} cartes au lieu de {expected}.")

    all_symbols = {s for card in deck.cards for s in card.symbols}
    if all_symbols != set(range(expected)):
        raise DeckValidationError(
            f"{len(all_symbols)} symboles utilisés au lieu de {expected} "
            f"(identifiants attendus : 0 à {expected - 1})."
        )

    for card in deck.cards:
        if len(set(card.symbols)) != per_card:
            raise DeckValidationError(
                f"La carte {card.index} porte {len(set(card.symbols))} symboles "
                f"au lieu de {per_card}."
            )

    for a, b in combinations(deck.cards, 2):
        common = set(a.symbols) & set(b.symbols)
        if len(common) != 1:
            raise DeckValidationError(
                f"Les cartes {a.index} et {b.index} partagent {len(common)} "
                f"symbole(s) au lieu de 1 : {sorted(common)}."
            )

    occurrences = [0] * expected
    for card in deck.cards:
        for symbol in card.symbols:
            occurrences[symbol] += 1
    bad = [s for s, count in enumerate(occurrences) if count != per_card]
    if bad:
        raise DeckValidationError(
            f"Les symboles {bad} n'apparaissent pas sur exactement {per_card} cartes."
        )
    logger.debug("Validation du deck : OK (%d cartes).", expected)
