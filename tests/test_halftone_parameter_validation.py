import json
import os

import pytest


# Importing services constructs boto clients. Inert credentials keep this unit
# test isolated from a developer's AWS profile and make no network requests.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-2")

from services import parse_abstract_filter_parameters


def test_halftone_checkbox_booleans_are_normalized_to_numeric_flags():
    assert parse_abstract_filter_parameters(
        json.dumps({"square_dots": False, "invert": True, "black_only": True})
    ) == {"square_dots": 0, "invert": 1, "black_only": 1}


def test_cached_textual_halftone_checkbox_values_are_also_accepted():
    assert parse_abstract_filter_parameters(
        json.dumps({"square_dots": "true", "invert": "false", "black_only": "true"})
    ) == {"square_dots": 1, "invert": 0, "black_only": 1}


def test_krasnow_preserve_black_checkbox_is_normalized_to_a_numeric_flag():
    assert parse_abstract_filter_parameters(
        json.dumps({"preserve_black": True})
    ) == {"preserve_black": 1}


def test_tight_pack_checkbox_is_normalized_for_filter_settings():
    assert parse_abstract_filter_parameters(
        json.dumps({"tight_pack_geometry": True})
    ) == {"tight_pack_geometry": 1}


def test_krasnow_cell_shape_accepts_only_supported_tessellations():
    for cell_shape in (
        "square", "hexagon", "triangle", "diamond", "skull", "heart",
        "space_invader", "ghost", "bat", "alien_head", "paw_print",
        "fish_scale", "puzzle_piece",
    ):
        assert parse_abstract_filter_parameters(
            json.dumps({"cell_shape": cell_shape})
        ) == {"cell_shape": cell_shape}

    with pytest.raises(ValueError, match="cell_shape.*number"):
        parse_abstract_filter_parameters(json.dumps({"cell_shape": "circle"}))


def test_krasnow_render_mode_accepts_only_line_or_fill():
    for render_mode in ("line", "fill"):
        assert parse_abstract_filter_parameters(
            json.dumps({"grating_render_mode": render_mode})
        ) == {"grating_render_mode": render_mode}

    with pytest.raises(ValueError, match="grating_render_mode.*number"):
        parse_abstract_filter_parameters(
            json.dumps({"grating_render_mode": "offset_fill"})
        )
