"""Offline contract tests; no cloud or laser connection."""
import ast
import io
import json
import math
import time
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET


class PresetExportTests(unittest.TestCase):
    def setUp(self):
        source = Path('serverless_api/handler.py').read_text(encoding='utf-8')
        names = {'color_lbmt_layout', 'color_lbmt_axis', 'color_lbmt_cut',
                 'color_grid_layout', 'color_axis_values', 'create_color_discovery_grid',
                 'lightburn_setting_snapshot'}
        nodes = [n for n in ast.parse(source).body if
                 isinstance(n, ast.FunctionDef) and n.name in names or
                 isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                 t.id in {'COLOR_DISCOVERY_PARAMETERS', 'COLOR_LBMT_CELL_GAP_MM', 'COLOR_LBMT_MATRIX_SCALE'} for t in n.targets)]
        self.ns = dict(math=math, ET=ET, json=json, time=time, uuid=uuid, deepcopy=deepcopy)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'handler.py', 'exec'), self.ns)

    def test_dimensions_and_limits(self):
        layout = self.ns['color_lbmt_layout']
        self.assertEqual(layout({}, 100, 100), (10, 10, 8.1, 8.1))
        self.assertEqual(layout(dict(rows=4, columns=6), 50, 100/4.5), (4, 6, 40/6, 17/4))
        for data in ({'rows': 1}, {'columns': 2.5}, {'rows': 100, 'columns': 100},
                     {'rows': float('nan')}):
            with self.assertRaises(ValueError):
                layout(data, 100, 100)
        for width, length in ((float('nan'), 100), (100, 0)):
            with self.assertRaises(ValueError):
                layout({}, width, length)

    def test_axis_validation_and_interpolation(self):
        axis = self.ns['color_lbmt_axis']
        field, values, enum = axis('frequency', 150000, 450000, 6)
        self.assertEqual((field, enum), ('frequency', 4))
        self.assertEqual(values, [150000, 210000, 270000, 330000, 390000, 450000])
        for param, low, high in [('angle', 0, 90), ('speed', float('nan'), 100), ('interval', .01, .001)]:
            with self.assertRaises(ValueError):
                axis(param, low, high, 10)

    def test_cut_serialization_rejects_nested_data(self):
        convert = self.ns['color_lbmt_cut']
        cut = ET.fromstring('<CutSetting type="Scan"><LinkPath Value="private"/><index Value="9"/><autoRotate Value="True"/><frequency Value="300000"/></CutSetting>')
        self.assertEqual(convert(cut), dict(type='Scan', autoRotate=True, frequency=300000))
        ET.SubElement(cut, 'SubLayer')
        with self.assertRaisesRegex(ValueError, 'single-layer'):
            convert(cut)

    def test_cut_mode_override_flattens_offset_fill_sublayers(self):
        convert = self.ns['color_lbmt_cut']
        cut = ET.fromstring('<CutSetting type="Offset"><speed Value="400"/><interval Value="0.255"/><SubLayer type="Offset" index="1"><interval Value="0.205"/></SubLayer></CutSetting>')
        self.assertEqual(convert(cut, 'fill'), dict(type='Scan', speed=400, interval=.255))
        self.assertEqual(convert(cut, 'line')['type'], 'Cut')
        self.assertEqual(convert(cut, 'offset_fill')['type'], 'Offset')
        with self.assertRaisesRegex(ValueError, 'Choose Fill'):
            convert(cut, 'image')

    def generate(self, **overrides):
        data = dict(library_id='example', entry_id=0, output_format='lbmt',
                    x_parameter='frequency', x_low=150000, x_high=450000,
                    y_parameter='interval', y_low=.001, y_high=.01,
                    columns=6, rows=4, grid_width_mm=60, grid_length_mm=48,
                    cut_mode='fill',
                    label_entry_id=1)
        data.update(overrides)
        library = b'<LightBurnLibrary><Material Name="Example"><Entry Desc="Red"><CutSetting type="Scan"><speed Value="1000"/><maxPower Value="15"/><minPower Value="12"/><frequency Value="300000"/><interval Value="0.002"/></CutSetting></Entry><Entry Desc="Labels"><CutSetting type="Scan"><speed Value="3500"/><maxPower Value="50"/></CutSetting></Entry></Material></LightBurnLibrary>'
        writes = []
        records = []
        self.ns.update(body_json=lambda event: data, user_id=lambda event: 'test',
                       owned_material=lambda *args: {'s3_key': 'library'},
                       material_label_choice=lambda entries, material, cut, selected:
                           (entries[int(selected)][1].find('./CutSetting'), int(selected), []),
                       MAX_MATERIAL_BYTES=100000, MATERIAL_LIMIT_MB=1, BUCKET='test', TTL_SECONDS=1000,
                       add_lightburn_safe_optimization_prefs=lambda project: None,
                       dynamo_value=lambda v: v, response=lambda status, value: value,
                       s3=SimpleNamespace(get_object=lambda **kwargs: {'Body': io.BytesIO(library)},
                                          put_object=lambda **kwargs: writes.append(kwargs),
                                          generate_presigned_url=lambda *args, **kwargs: 'test-download'),
                       table=SimpleNamespace(put_item=lambda **kwargs: records.append(kwargs)))
        result = self.ns['create_color_discovery_grid']({})
        return result, writes

    def test_rectangular_preset_metadata_and_labels(self):
        result, writes = self.generate()
        self.assertTrue(writes[0]['Key'].endswith('.lbmt'))
        preset = next(iter(json.loads(writes[0]['Body']).values()))
        self.assertEqual([preset[k] for k in ('XCount','YCount')], [6,4])
        self.assertAlmostEqual(preset['XSize'], 49/6)
        self.assertAlmostEqual(preset['YSize'], 40.2/4)
        self.assertEqual((preset['XCenter'], preset['YCenter']), (30,24))
        self.assertEqual((preset['XMin'], preset['XMax']), (150,450))
        self.assertEqual(preset['MaterialCut']['frequency'], 300000)
        self.assertEqual(preset['MaterialCut']['type'], 'Scan')
        self.assertEqual(preset['TextCut']['speed'], 3500)
        self.assertEqual(preset['BorderCut']['maxPower'], 50)
        self.assertIs(preset['BorderCut']['doOutput'], False)
        cells = result['metadata']['cells']
        self.assertEqual(len(cells), 24)
        self.assertEqual(cells[0]['overrides'], {'frequency':150000, 'interval':.01})
        self.assertEqual(cells[-1]['overrides'], {'frequency':450000, 'interval':.001})
        self.assertEqual(result['metadata']['cut_mode'], 'fill')
        self.assertEqual(result['metadata']['cell_gap_mm'], 1)
        self.assertEqual(result['metadata']['matrix_scale'], .9)
        self.assertEqual((result['metadata']['grid_width_mm'], result['metadata']['grid_height_mm']), (54,43.2))

    def test_default_100_cells_and_existing_project(self):
        result, _ = self.generate(rows=10, columns=10)
        self.assertEqual(len(result['metadata']['cells']), 100)
        result, writes = self.generate(output_format='lbrn2')
        self.assertTrue(writes[0]['Key'].endswith('.lbrn2'))
        project = ET.fromstring(writes[0]['Body'])
        self.assertLessEqual(len(project.findall('./CutSetting')), 30)
        self.assertLess(result['metadata']['y_values'][0], result['metadata']['y_values'][-1])


if __name__ == '__main__':
    unittest.main()
