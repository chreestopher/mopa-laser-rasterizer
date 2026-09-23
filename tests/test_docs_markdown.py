from lib.docs_markdown import _render_blocks


def test_wrapped_ordered_list_items_remain_single_list_items():
    blocks = _render_blocks(
        [
            "1. Choose the format and overall dimensions,",
            "   then select the settings and sweep axes.",
            "2. Download the preset and keep its metadata.",
        ]
    )

    assert blocks == [
        {
            "html": (
                "<ol><li>Choose the format and overall dimensions, then select the "
                "settings and sweep axes.</li><li>Download the preset and keep its "
                "metadata.</li></ol>"
            )
        }
    ]


def test_wrapped_unordered_list_items_remain_single_list_items():
    blocks = _render_blocks(
        [
            "- The native preset supports independently selected",
            "  row and column counts.",
            "- The project format uses separate LightBurn layers.",
        ]
    )

    assert blocks == [
        {
            "html": (
                "<ul><li>The native preset supports independently selected row and "
                "column counts.</li><li>The project format uses separate LightBurn "
                "layers.</li></ul>"
            )
        }
    ]
