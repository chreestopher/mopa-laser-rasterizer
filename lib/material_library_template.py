"""Safe, unconfigured LightBurn Material Library palette templates."""

from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree as ET


DEFAULT_RASTERIZER_PALETTE = (
    ("Light-Gray", 8), ("Black", 0), ("Blue", 1), ("Red", 2),
    ("Green", 3), ("Yellow", 4), ("Orange", 5), ("Cyan", 6),
    ("Magenta", 7), ("Dark-Blue", 9), ("Dark-Red", 10),
    ("Dark-Green", 11), ("Dark-Yellow", 12), ("Dark-Orange", 13),
    ("Light-Blue", 14), ("Dark-Magenta", 15), ("Medium-Gray", 16),
    ("Slate-Blue", 17), ("Rose", 18), ("Periwinkle-Blue", 19),
    ("Raspberry", 20), ("Sage-Green", 21), ("Peach", 22),
    ("Light-Pink", 23), ("Orchid-Pink", 24), ("Deep-Purple", 25),
    ("Rust-Brown", 26), ("Teal", 27), ("Bright-Mint-Green", 28),
    ("Light-Gold", 29),
)


def build_blank_palette_library(material_name):
    """Return a valid, deliberately non-runnable 30-swatch .clb document."""
    material_name = str(material_name or "").strip()
    if not material_name or len(material_name) > 160:
        raise ValueError("Material name must be between 1 and 160 characters.")
    if any(ord(character) < 32 for character in material_name):
        raise ValueError("Material name cannot contain control characters.")

    root = ET.Element("LightBurnLibrary", {
        "RasterizerTemplate": "UNCONFIGURED",
        "Warning": "PLACEHOLDERS_ONLY_DO_NOT_RUN",
    })
    material = ET.SubElement(root, "Material", {"name": material_name})
    for swatch_name, _layer_index in DEFAULT_RASTERIZER_PALETTE:
        entry = ET.SubElement(material, "Entry", {
            "Thickness": "-1.0000",
            "Desc": f"UNCONFIGURED {swatch_name}",
        })
        cut = ET.SubElement(entry, "CutSetting", {"type": "Scan"})
        values = {
            "index": 0, "name": "",
            "LinkPath": f"{material_name}/-1.0000/UNCONFIGURED {swatch_name}",
            "minPower": 0, "maxPower": 0, "maxPower2": 0, "speed": 0,
            "frequency": 0, "QPulseWidth": 0, "interval": 0, "angle": 0,
            "anglePerPass": 0, "crossHatch": 0, "doOutput": 0,
            "hide": 1, "numPasses": 1,
        }
        for field, value in values.items():
            ET.SubElement(cut, field, {"Value": str(value)})

    output = BytesIO()
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    output.seek(0)
    return output


def build_hatch_palette_library(material_name, interval_mm=0.1, base_entry=None,
                                base_settings=None, base_type="Scan"):
    """Return a safe 30-layer Fill library with evenly distributed hatch angles."""
    material_name = str(material_name or "").strip()
    if not material_name or len(material_name) > 160:
        raise ValueError("Material name must be between 1 and 160 characters.")
    if any(ord(character) < 32 for character in material_name):
        raise ValueError("Material name cannot contain control characters.")
    try:
        interval_mm = float(interval_mm)
    except (TypeError, ValueError) as error:
        raise ValueError("Line interval must be a positive number.") from error
    if interval_mm <= 0:
        raise ValueError("Line interval must be a positive number.")

    if base_entry is not None:
        base_cut = base_entry.find("CutSetting")
        if base_cut is None or base_cut.attrib.get("type") not in {"Scan", "Offset"}:
            raise ValueError("A Hatch Palette base setting must use Fill or Offset Fill mode.")
    else:
        base_settings = dict(base_settings or {})
        if base_type not in {"Scan", "Offset"}:
            raise ValueError("A Hatch Palette base setting must use Fill or Offset Fill mode.")

    root = ET.Element("LightBurnLibrary", {"RasterizerPalette": "HATCH"})
    material = ET.SubElement(root, "Material", {"name": material_name})
    for swatch_name, layer_index in DEFAULT_RASTERIZER_PALETTE:
        angle = layer_index * (180 / len(DEFAULT_RASTERIZER_PALETTE))
        if base_entry is not None:
            entry = deepcopy(base_entry)
            entry.attrib["Desc"] = swatch_name
            entry.attrib.setdefault("Thickness", "-1.0000")
            material.append(entry)
            cut = entry.find("CutSetting")
        else:
            entry = ET.SubElement(material, "Entry", {
                "Thickness": "-1.0000",
                "Desc": swatch_name,
            })
            cut = ET.SubElement(entry, "CutSetting", {"type": base_type})
            defaults = {
                "minPower": 0, "maxPower": 0, "maxPower2": 0, "speed": 0,
                "frequency": 0, "QPulseWidth": 0, "anglePerPass": 0,
                "crossHatch": 0, "autoRotate": 0, "doOutput": 0,
                "hide": 1, "numPasses": 1,
            }
            defaults.update(base_settings)
            for field, value in defaults.items():
                ET.SubElement(cut, field, {"Value": str(value)})

        replacements = {
            "index": layer_index,
            "name": swatch_name,
            "LinkPath": f"{material_name}/-1.0000/{swatch_name}",
            "interval": f"{interval_mm:.6f}".rstrip("0").rstrip("."),
            "angle": f"{angle:.6f}".rstrip("0").rstrip("."),
        }
        for field, value in replacements.items():
            element = cut.find(field)
            if element is None:
                element = ET.SubElement(cut, field)
            element.attrib["Value"] = str(value)
        # Offset Fill can store its concrete pass values in SubLayer nodes.
        # Keep every cloned laser parameter intact while applying only the
        # planned hatch angle and interval to those concrete passes as well.
        for sublayer in cut.findall(".//SubLayer"):
            for field in ("interval", "angle"):
                element = sublayer.find(field)
                if element is None:
                    element = ET.SubElement(sublayer, field)
                element.attrib["Value"] = replacements[field]

    output = BytesIO()
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    output.seek(0)
    return output
