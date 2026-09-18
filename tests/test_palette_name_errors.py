"""User-facing validation for Material Library swatch-name overrides."""

import os

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-2")

from services import (
    parse_abstract_filter_parameters,
    parse_color_name_overrides,
    parse_geometry_style_parameters,
)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{", "couldn't read the selected swatch names.*Reload Rasterizer"),
        ('{"wrong":"Red"}', "Swatch color 'wrong' is invalid.*select the swatch again"),
        ('{"#FF0000":""}', "name for swatch #FF0000 must be 1–80 characters"),
        ('{"#FF0000":"Red","#00FF00":"Red"}', "More than one swatch uses the Material Library name 'Red'"),
    ],
)
def test_palette_name_error_identifies_recovery(payload, message):
    with pytest.raises(ValueError, match=message):
        parse_color_name_overrides(payload)


def test_invalid_style_settings_explain_how_to_retry():
    with pytest.raises(ValueError, match="couldn't read the Image Style settings.*choose the style again"):
        parse_abstract_filter_parameters("{")
    with pytest.raises(ValueError, match="couldn't read the Geometry Style settings.*choose the geometry again"):
        parse_geometry_style_parameters("{")
