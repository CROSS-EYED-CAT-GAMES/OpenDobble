"""Tests pytest du générateur Dobble.

Lancer depuis la racine du projet ::

    python -m pytest tests/ -v
"""

from __future__ import annotations

import random
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from generator.cards import Card, Deck, DeckValidationError, generate_deck, validate_deck
from generator.config import THEMES, AppConfig, BackConfig, ImportConfig, LayoutConfig
from generator.export import Exporter, ExportPaths
from generator.geometry import (
    CirclePlacement,
    circles_overlap,
    containment_violation,
    is_valid_layout,
    overlap_amount,
)
from generator.layout import LayoutEngine
from generator.renderer import CardRenderer, RenderedCard
from generator.utils import ImageLibraryError, load_image_library


# ---------------------------------------------------------------------------
# Deck mathématique
# ---------------------------------------------------------------------------


class TestDeck:
    """Propriétés du plan projectif d'ordre 7."""

    def test_deck_has_57_cards(self) -> None:
        assert len(generate_deck().cards) == 57

    def test_deck_uses_57_symbols(self) -> None:
        deck = generate_deck()
        assert {s for c in deck.cards for s in c.symbols} == set(range(57))

    def test_each_card_has_8_symbols(self) -> None:
        assert all(len(set(c.symbols)) == 8 for c in generate_deck().cards)

    def test_every_pair_shares_exactly_one_symbol(self) -> None:
        for a, b in combinations(generate_deck().cards, 2):
            assert len(set(a.symbols) & set(b.symbols)) == 1

    def test_each_symbol_appears_on_8_cards(self) -> None:
        counts = [0] * 57
        for card in generate_deck().cards:
            for symbol in card.symbols:
                counts[symbol] += 1
        assert all(count == 8 for count in counts)

    def test_non_prime_order_rejected(self) -> None:
        with pytest.raises(ValueError):
            generate_deck(order=6)

    def test_validation_detects_corruption(self) -> None:
        cards = list(generate_deck().cards)
        cards[0] = Card(index=0, symbols=cards[0].symbols[:-1] + (99,))
        with pytest.raises(DeckValidationError):
            validate_deck(Deck(order=7, cards=tuple(cards)))

    def test_duplicate_symbol_on_card_rejected(self) -> None:
        with pytest.raises(DeckValidationError):
            Card(index=0, symbols=(1, 1, 2, 3, 4, 5, 6, 7))


# ---------------------------------------------------------------------------
# Géométrie
# ---------------------------------------------------------------------------


class TestGeometry:
    """Primitives cercle / conteneur."""

    def test_overlap_detection(self) -> None:
        a, b = CirclePlacement(0, 0, 10), CirclePlacement(15, 0, 10)
        assert circles_overlap(a, b)
        assert overlap_amount(a, b) == pytest.approx(5.0)

    def test_disjoint_circles(self) -> None:
        a, b = CirclePlacement(0, 0, 10), CirclePlacement(25, 0, 10)
        assert not circles_overlap(a, b)
        assert overlap_amount(a, b) == 0.0

    def test_padding_taken_into_account(self) -> None:
        a, b = CirclePlacement(0, 0, 10), CirclePlacement(22, 0, 10)
        assert not circles_overlap(a, b, padding=0.0)
        assert circles_overlap(a, b, padding=5.0)

    def test_containment_violation(self) -> None:
        assert containment_violation(CirclePlacement(0, 0, 10), 100.0) == 0.0
        assert containment_violation(CirclePlacement(95, 0, 10), 100.0) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Moteur de placement
# ---------------------------------------------------------------------------


class TestLayoutEngine:
    """Le moteur doit produire des placements valides et reproductibles."""

    @pytest.fixture()
    def engine(self) -> LayoutEngine:
        return LayoutEngine(LayoutConfig(), random.Random(42))

    def test_layout_is_collision_free(self, engine: LayoutEngine) -> None:
        placements = engine.layout_card(list(range(8)), 480.0, 8.0)
        circles = [CirclePlacement(p.x, p.y, p.radius) for p in placements]
        assert is_valid_layout(circles, 480.0, 8.0)

    def test_layout_keeps_symbol_order(self, engine: LayoutEngine) -> None:
        ids = [10, 20, 30, 40, 50, 51, 52, 53]
        assert [p.symbol_id for p in engine.layout_card(ids, 480.0, 8.0)] == ids

    def test_rotations_within_bounds(self, engine: LayoutEngine) -> None:
        assert all(0.0 <= p.rotation_deg <= 360.0 for p in engine.layout_card(list(range(8)), 480.0, 8.0))

    def test_reproducible_with_seed(self) -> None:
        a = LayoutEngine(LayoutConfig(), random.Random(7)).layout_card(list(range(8)), 480.0, 8.0)
        b = LayoutEngine(LayoutConfig(), random.Random(7)).layout_card(list(range(8)), 480.0, 8.0)
        assert a == b

    def test_size_distribution_covers_categories(self, engine: LayoutEngine) -> None:
        radii = sorted(p.radius for p in engine.layout_card(list(range(8)), 480.0, 8.0))
        assert radii[-1] / radii[0] > 1.3


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfig:
    """Comportement de la configuration immuable."""

    def test_all_expected_themes_exist(self) -> None:
        assert {"classic", "pastel", "dark", "kids", "minimal"} <= set(THEMES)

    def test_with_theme_returns_new_config(self) -> None:
        config = AppConfig()
        assert config.with_theme("dark").theme.name == "dark"
        assert config.theme.name == "classic"

    def test_unknown_theme_rejected(self) -> None:
        with pytest.raises(KeyError):
            AppConfig().with_theme("does-not-exist")

    def test_invalid_dpi_rejected(self) -> None:
        with pytest.raises(ValueError):
            AppConfig().with_dpi(10)

    def test_size_fractions_sum_to_one(self) -> None:
        assert sum(LayoutConfig().size_fractions) == pytest.approx(1.0)

    def test_config_is_frozen(self) -> None:
        with pytest.raises(Exception):
            AppConfig().seed = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Import des images (formats multiples, détourage)
# ---------------------------------------------------------------------------


def _disc_on_flat(path: Path, fmt: str, background=(255, 255, 255)) -> None:
    """Écrit un disque rouge sur fond uni."""
    img = Image.new("RGB", (120, 120), background)
    ImageDraw.Draw(img).ellipse((20, 20, 100, 100), fill=(200, 40, 40))
    img.save(path, format=fmt)


def _alpha(library, index: int = 0) -> np.ndarray:
    """Canal alpha de l'image ``index`` de la bibliothèque."""
    return np.asarray(library[index].image.getchannel("A"))


NO_CORNERS = ImportConfig(corner_radius_ratio=0.0)


class TestImageImport:
    """Chargement PNG/WebP/JPG et détourage automatique."""

    def test_jpg_background_removed(self, tmp_path: Path) -> None:
        for i in range(57):
            _disc_on_flat(tmp_path / f"{i + 1:03d}.jpg", "JPEG")
        alpha = _alpha(load_image_library(tmp_path))
        assert float(np.mean(alpha < 10)) > 0.10
        assert alpha[alpha.shape[0] // 2, alpha.shape[1] // 2] > 200

    def test_webp_accepted(self, tmp_path: Path) -> None:
        for i in range(57):
            _disc_on_flat(tmp_path / f"{i + 1:03d}.webp", "WEBP")
        assert len(load_image_library(tmp_path)) == 57

    def test_interior_flat_area_preserved(self, tmp_path: Path) -> None:
        for i in range(57):
            img = Image.new("RGB", (120, 120), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            draw.ellipse((10, 10, 110, 110), fill=(30, 30, 200))
            draw.ellipse((45, 45, 75, 75), fill=(255, 255, 255))
            img.save(tmp_path / f"{i + 1:03d}.jpg", format="JPEG")
        alpha = _alpha(load_image_library(tmp_path))
        assert alpha[alpha.shape[0] // 2, alpha.shape[1] // 2] > 200

    def test_removal_can_be_disabled(self, tmp_path: Path) -> None:
        for i in range(57):
            _disc_on_flat(tmp_path / f"{i + 1:03d}.jpg", "JPEG")
        config = replace(NO_CORNERS, background_mode="never")
        assert float(np.mean(_alpha(load_image_library(tmp_path, config)) < 10)) == 0.0

    def test_photo_like_image_kept_intact(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(0)
        for i in range(57):
            Image.fromarray(rng.integers(0, 255, (120, 120, 3), dtype=np.uint8)).save(tmp_path / f"{i + 1:03d}.jpg")
        assert float(np.mean(_alpha(load_image_library(tmp_path, NO_CORNERS)) < 250)) < 0.01

    def test_logo_on_flat_color_kept_intact(self, tmp_path: Path) -> None:
        for i in range(57):
            img = Image.new("RGB", (200, 200), (40, 44, 52))
            ImageDraw.Draw(img).rectangle((85, 85, 115, 115), fill=(240, 235, 220))
            img.save(tmp_path / f"{i + 1:03d}.jpg", quality=95)
        assert float(np.mean(_alpha(load_image_library(tmp_path, NO_CORNERS)) < 10)) < 0.01

    def test_keep_and_cut_filename_overrides(self, tmp_path: Path) -> None:
        _disc_on_flat(tmp_path / "001.keep.jpg", "JPEG")
        for i in range(1, 57):
            _disc_on_flat(tmp_path / f"{i + 1:03d}.cut.jpg", "JPEG")
        library = load_image_library(tmp_path, NO_CORNERS)
        assert float(np.mean(_alpha(library, 0) < 10)) < 0.01
        assert float(np.mean(_alpha(library, 1) < 10)) > 0.10

    def test_rounded_corners_applied(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(1)
        for i in range(57):
            Image.fromarray(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)).save(tmp_path / f"{i + 1:03d}.jpg")
        alpha = _alpha(load_image_library(tmp_path, ImportConfig(corner_radius_ratio=0.1)))
        assert alpha[0, 0] < 50
        assert alpha[alpha.shape[0] // 2, 5] > 200

    def test_wrong_count_rejected(self, tmp_path: Path) -> None:
        _disc_on_flat(tmp_path / "001.jpg", "JPEG")
        with pytest.raises(ImageLibraryError):
            load_image_library(tmp_path)


# ---------------------------------------------------------------------------
# Dos de carte et planches recto-verso
# ---------------------------------------------------------------------------


class TestCardBack:
    """Rendu du dos et planches recto-verso."""

    ARTWORK = Image.new("RGBA", (300, 200), (30, 60, 120, 255))

    def test_back_same_size_as_front(self) -> None:
        config = AppConfig().with_dpi(100)
        renderer = CardRenderer(config)
        bleed = config.card.bleed_px(100)
        back = renderer.render_back(self.ARTWORK, bleed_px=bleed)
        assert back.size == (renderer.diameter_px + 2 * bleed,) * 2

    def test_back_transparent_outside_disc(self) -> None:
        alpha = np.asarray(CardRenderer(AppConfig().with_dpi(100)).render_back(self.ARTWORK).getchannel("A"))
        assert alpha[0, 0] == 0
        assert alpha[alpha.shape[0] // 2, alpha.shape[1] // 2] > 200

    def test_back_cover_fills_disc(self) -> None:
        config = replace(AppConfig().with_dpi(100), back=BackConfig(mode="cover"))
        rgb = np.asarray(CardRenderer(config).render_back(self.ARTWORK).convert("RGB"))
        c = rgb.shape[0] // 2
        assert tuple(rgb[c, c]) == (30, 60, 120)
        assert tuple(rgb[c, rgb.shape[1] // 5]) == (30, 60, 120)

    def test_back_invalid_mode_rejected(self) -> None:
        config = replace(AppConfig().with_dpi(100), back=BackConfig(mode="stretch"))
        with pytest.raises(ValueError):
            CardRenderer(config).render_back(self.ARTWORK)

    def test_sheets_recto_verso_has_two_pages(self, tmp_path: Path) -> None:
        config = AppConfig().with_dpi(80)
        renderer = CardRenderer(config)
        bleed = config.card.bleed_px(80)
        size = renderer.diameter_px + 2 * bleed
        blank = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        cards = [RenderedCard(index=i, image=blank, placements=()) for i in range(3)]
        back = renderer.render_back(self.ARTWORK, bleed_px=bleed)
        paths = Exporter(config, ExportPaths.create(tmp_path)).export_sheets(cards, back)
        assert len(paths) == 1
        assert paths[0].read_bytes().count(b"/Type /Page\n") + paths[0].read_bytes().count(b"/Type /Page ") >= 2


# ---------------------------------------------------------------------------
# Illustration du dos (tools/make_back.py)
# ---------------------------------------------------------------------------


class TestBackArtwork:
    """Le script d'illustration du dos produit une image exploitable."""

    def test_compose_returns_square_opaque_image(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        from make_back import Palette, compose

        image = compose(240, Palette())
        assert image.size == (240, 240)
        alpha = np.asarray(image.getchannel("A"))
        assert alpha.min() == 255  # aucun trou transparent dans le visuel
