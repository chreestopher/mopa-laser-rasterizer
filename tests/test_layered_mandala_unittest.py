import unittest

from lib.mandala import generate_mandala


def _config(layer):
    return {
        "project_name": "Mandala unittest",
        "diameter_mm": 120,
        "workbed_width_mm": 140,
        "workbed_height_mm": 140,
        "processing_palette_name": "Review",
        "material": "Review",
        "cut_entry_ref": "review",
        "cut_setting": {"description": "Cut", "type": "Cut", "settings": {}},
        "layers": [layer],
    }


def _layer(**overrides):
    layer = {
        "name": "Review layer",
        "motif": "petal",
        "construction": "positive",
        "support_mode": "automatic_bridges",
        "repetitions": 12,
        "rings": 3,
        "inner_radius_ratio": 0.18,
        "motif_scale": 0.72,
        "radial_stretch": 1,
        "tangent_stretch": 1,
        "twist_degrees": 18,
        "rotation_degrees": 0,
        "alternate_rotation": True,
        "mirror_alternating": False,
        "rim_width_mm": 4,
        "bridge_width_mm": 2,
        "seed": 1,
    }
    layer.update(overrides)
    return layer


class LayeredMandalaUnittestTests(unittest.TestCase):
    def test_connected_modes_make_every_builtin_motif_one_piece(self):
        for motif in ("petal", "leaf", "diamond", "circle", "triangle", "star", "heart"):
            for support_mode in ("automatic_bridges", "fully_connected"):
                with self.subTest(motif=motif, support_mode=support_mode):
                    _, geometries = generate_mandala(_config(_layer(
                        motif=motif,
                        support_mode=support_mode,
                        twist_degrees=23,
                    )))
                    self.assertEqual(geometries[0].geom_type, "Polygon")

    def test_extreme_solid_and_sparse_layers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "almost completely solid"):
            generate_mandala(_config(_layer(
                construction="cutout",
                support_mode="loose",
                motif="circle",
                repetitions=4,
                rings=1,
                motif_scale=0.2,
                radial_stretch=0.4,
                tangent_stretch=0.4,
            )))

        with self.assertRaisesRegex(ValueError, "too little material"):
            generate_mandala(_config(_layer(
                support_mode="loose",
                motif="circle",
                repetitions=4,
                rings=1,
                motif_scale=0.2,
                radial_stretch=0.4,
                tangent_stretch=0.4,
            )))

    def test_diagonal_sine_supports_remain_one_piece(self):
        _, geometries = generate_mandala(_config(_layer(
            motif="heart",
            support_mode="fully_connected",
            support_sweep_degrees=-55,
            bridge_wave_amount=1,
            bridge_wave_amplitude_mm=8,
            bridge_wave_position=0.7,
        )))
        self.assertEqual(geometries[0].geom_type, "Polygon")


if __name__ == "__main__":
    unittest.main()
