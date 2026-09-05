import ast
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class ServerlessColorDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.api = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.page = (ROOT / "serverless_web" / "color-lab.html").read_text(encoding="utf-8")
        self.client = (ROOT / "serverless_web" / "color-lab.js").read_text(encoding="utf-8")
        self.docs = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")

    def test_api_source_parses_and_routes_grid_creation(self):
        ast.parse(self.api)
        self.assertIn('path == "/color-discovery/grids"', self.api)
        self.assertIn("def create_color_discovery_grid(event, guest=False, upload_task_id=\"\"):", self.api)
        infrastructure = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
        self.assertIn("RouteKey: POST /color-discovery/grids", infrastructure)
        self.assertIn("ColorDiscoveryGridRoute:", infrastructure)
        self.assertIn("GetColorDiscoveryGridRoute:", infrastructure)
        self.assertIn("RouteKey: \"GET /color-discovery/grids/{grid_id}\"", infrastructure)
        self.assertIn("ListColorDiscoveryGridsRoute:", infrastructure)
        self.assertIn("RouteKey: \"GET /color-discovery/grids\"", infrastructure)
        self.assertIn("users/*/color-discovery/*", infrastructure)

    def test_grid_is_gapless_automatic_and_capped(self):
        self.assertIn("rows, columns, cell_mm = color_grid_layout(width_mm, length_mm)", self.api)
        self.assertIn("rows * columns <= maximum_cells", self.api)
        self.assertIn('grid_label=f"COLOR GRID {grid_id[:8]}"', self.api)
        self.assertNotIn('id="gridColumns"', self.page)
        self.assertNotIn('id="gridRows"', self.page)
        self.assertIn('for link_path in layer.findall("./LinkPath")', self.api)
        self.assertIn('layer.remove(link_path)', self.api)
        self.assertIn('label_layer.set("type","Scan")', self.api)
        self.assertIn("label_height=2.1", self.api)
        self.assertIn('"H":f"{label_height:g}"', self.api)

    def test_color_and_holographic_grids_prefer_explicit_labels_setting(self):
        tree = ast.parse(self.api)
        helper = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "material_label_cut_setting"
        )
        namespace = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "handler.py", "exec"), namespace)
        material = ET.fromstring('''<Material name="steel">
          <Entry Desc="First"><CutSetting type="Scan"><maxPower Value="10"/></CutSetting></Entry>
          <Entry Desc="Labels"><CutSetting type="Scan"><maxPower Value="20"/></CutSetting></Entry>
        </Material>''')
        fallback = material.findall("./Entry")[0].find("./CutSetting")

        selected = namespace["material_label_cut_setting"](material, fallback)

        self.assertEqual("20", selected.find("./maxPower").get("Value"))
        self.assertIn("label_cut, label_entry_id, label_options = material_label_choice(", self.api)
        self.assertIn("label_cut,label_entry_id,label_options=material_label_choice(", self.api)
        self.assertIn('"label_laser_settings":lightburn_setting_snapshot(label_layer)', self.api)
        self.assertIn('or refinement_metadata.get("label_laser_settings")', self.api)
        self.assertIn('id="labelEntry"', self.page)
        self.assertIn("payload.label_entry_id=Number($('#labelEntry').value)", self.client)

        color_route = (ROOT / "routes" / "color_discovery.py").read_text(encoding="utf-8")
        holographic_route = (ROOT / "routes" / "holographic.py").read_text(encoding="utf-8")
        self.assertIn('"baseline": baseline, "label_baseline": label_baseline', color_route)
        self.assertIn('session.get("label_baseline") or baseline', color_route)
        self.assertIn("def _grid_label_setting(", holographic_route)
        self.assertIn("_grid_label_setting(lightburn, library_path, material, base_setting)", holographic_route)

    def test_grid_label_setting_falls_back_when_labels_is_absent(self):
        tree = ast.parse(self.api)
        helper = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "material_label_cut_setting"
        )
        namespace = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "handler.py", "exec"), namespace)
        material = ET.fromstring(
            '<Material name="steel"><Entry Desc="First"><CutSetting type="Scan"/></Entry></Material>'
        )
        fallback = material.find("./Entry/CutSetting")

        self.assertIs(namespace["material_label_cut_setting"](material, fallback), fallback)

    def test_color_lab_exposes_generation_and_local_measurement(self):
        for expected in ('id="gridWidth"', 'id="gridLength"', 'id="gridPhoto"', 'id="measure"'):
            self.assertIn(expected, self.page)
        self.assertIn('id="cellSize" type="text" readonly', self.page)
        self.assertIn("$('#cellSize').value=size.toFixed(2)", self.client)
        self.assertIn('input[readonly]{border-color:#4f604b;color:#e4e3cf', self.page)
        self.assertIn("/color-discovery/grids", self.client)
        self.assertIn("Measured ${measurements.length} cells locally.", self.client)

    def test_color_lab_downloads_use_shared_theme_aware_buttons(self):
        shared_styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        self.assertEqual(self.client.count('class="staging-action-button color-lab-download-button"'), 4)
        self.assertIn('class="color-lab-downloads"', self.client)
        self.assertIn(".color-lab-download-button{display:flex!important", self.page)
        self.assertIn("width:100%;height:60px", self.page)
        self.assertIn("a:not(.staging-action-button)", self.page)
        self.assertIn(".staging-action-button{border:2px solid #9ba89f!important", shared_styles)
        self.assertIn("body.light-machine .staging-action-button{color:#171815!important", shared_styles)

    def test_previously_created_grid_can_be_loaded_by_short_or_full_id(self):
        self.assertIn('id="measurementGridId"', self.page)
        self.assertIn('id="recentGridSelect"', self.page)
        self.assertNotIn('<datalist id="measurementGridIds">', self.page)
        self.assertNotIn('id="loadGridForm"', self.page)
        self.assertIn("def get_color_discovery_grid(event, grid_reference, guest=False):", self.api)
        self.assertIn("def list_color_discovery_grids(event):", self.api)
        self.assertIn('user_items(owner, "COLORDISCOVERY#", limit=50)', self.api)
        self.assertIn('re.fullmatch(r"[0-9a-f]{8}", reference)', self.api)
        self.assertIn('f"COLORDISCOVERY#{reference}"', self.api)
        self.assertIn("async function loadSelectedGrid()", self.client)
        self.assertIn("/color-discovery/grids/${encodeURIComponent(reference)}", self.client)
        self.assertIn("function activateGrid(loaded)", self.client)
        self.assertIn("async function populateGridChoices()", self.client)
        self.assertIn("new Option(`${item.short_id}", self.client)
        self.assertIn("$('#recentGridSelect').onchange=()=>", self.client)
        self.assertIn("$('#measurementGridId').value=$('#recentGridSelect').value", self.client)
        start_handler = self.client[self.client.index("async function start()") :]
        self.assertIn("$('#recentGridSelect').value=''", start_handler)
        self.assertIn("$('#measurementGridId').value=''", start_handler)
        self.assertIn("$('#gridPhoto').onchange=async", self.client)
        self.assertIn("const loaded=await loadSelectedGrid()", self.client)

    def test_selected_setting_initializes_both_sweep_axes(self):
        self.assertIn("function baselineValue(parameter)", self.client)
        self.assertIn("if(!spec)return null", self.client)
        self.assertIn("if(value===null)return", self.client)
        self.assertIn("function populateAxis(axis)", self.client)
        self.assertIn("function applyStartingSetting()", self.client)
        self.assertIn("$('#entry').onchange=applyStartingSetting", self.client)
        self.assertIn("if(selectedId==='')return null", self.client)
        self.assertIn('id="entryPickerButton"', self.page)
        self.assertIn('.staging-color-lab .stage .setting-picker-button{', self.page)
        self.assertIn('background:#131812!important', self.page)
        self.assertIn('text-transform:none!important', self.page)
        self.assertIn('.light-machine.staging-color-lab .stage .setting-picker-button{', self.page)
        self.assertIn('.light-machine.staging-color-lab .stage .downloads a', self.page)
        self.assertIn('text-decoration-color:#245f1d!important', self.page)
        self.assertIn('id="entryPickerMenu"', self.page)
        self.assertIn("function entryColor(entry)", self.client)
        self.assertIn("function chooseEntry(entryId)", self.client)
        self.assertIn('class="mini-swatch"', self.client)
        self.assertIn("option.dataset.entryId", self.client)
        self.assertIn(".staging-color-lab .stage .setting-picker-option", self.page)
        self.assertIn("border:1px solid #465248!important", self.page)
        self.assertIn("background:#111710!important", self.page)
        self.assertIn("box-shadow:none!important", self.page)
        self.assertIn("<strong>${esc(entry.description", self.client)
        self.assertIn("$('#xParameter').onchange=()=>populateAxis('x')", self.client)
        self.assertIn("$('#yParameter').onchange=()=>populateAxis('y')", self.client)

    def test_grid_truncates_every_parameter_except_line_interval(self):
        self.assertIn('"interval": ("interval", "Fill interval", .001, 10, False)', self.api)
        for parameter in ("speed", "max_power", "min_power", "frequency", "pulse_width", "passes", "angle"):
            definition = next(line for line in self.api.splitlines() if f'"{parameter}": (' in line)
            fragment = definition.split(f'"{parameter}": (', 1)[1].split(")", 1)[0]
            self.assertTrue(fragment.rstrip().endswith("True"), parameter)
        self.assertIn("math.floor(value) if integer else value", self.api)

    def test_speed_and_frequency_bounds_are_floored_in_the_display(self):
        self.assertIn("const integerDisplayParameters=new Set(['speed','frequency'])", self.client)
        self.assertIn("Math.floor(numeric)", self.client)
        self.assertIn("function setAxisBounds(parameter,lowInput,highInput,low,high)", self.client)
        self.assertIn("lowInput.step=integer?'1':'any'", self.client)
        self.assertIn("function normalizeAxisInputs(axis)", self.client)
        self.assertIn("[xLow,xHigh]=normalizeAxisInputs('x')", self.client)
        self.assertIn("normalizeAxisInputs('x');normalizeAxisInputs('y')", self.client)
        self.assertIn("setAxisBounds(x,$('#refineXLow'),$('#refineXHigh')", self.client)
        self.assertIn("setAxisBounds(y,$('#refineYLow'),$('#refineYHigh')", self.client)
        self.assertIn("for(const axis of ['X','Y'])", self.client)
        self.assertIn('src="/color-lab.js?v=6"', self.page)

    def test_deploy_script_uploads_color_lab_client(self):
        deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")
        self.assertIn('serverless_web/color-lab.js', deploy)

    def test_shared_styles_override_prototype_gold_on_color_lab(self):
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")
        self.assertIn('body.staging-color-lab .stage h2{color:#e4e3cf!important', styles)
        self.assertIn('body.staging-color-lab .stage label{color:#8ee474!important', styles)
        self.assertIn('body.light-machine.staging-color-lab .stage h2{color:#20221e!important', styles)
        self.assertIn('body.light-machine.staging-prototype .staging-page-hero a:visited', styles)
        self.assertIn('color:#245f1d!important', styles)

    def test_analysis_swatches_toggle_and_save_unique_official_matches(self):
        self.assertIn('id="savePalette"', self.page)
        self.assertIn("function nearestOfficial(hex)", self.client)
        self.assertIn("function rgbLab(rgb)", self.client)
        self.assertIn("function labDistance(left,right)", self.client)
        self.assertIn("function labHue(lab)", self.client)
        self.assertIn("function hueDistance(left,right)", self.client)
        self.assertIn("function rgbHsv(rgb)", self.client)
        self.assertIn("chromatic=sampleChroma>=8&&sampleHsv.saturation>=.12", self.client)
        self.assertIn("ranked.filter(item=>labChroma(item.lab)>=8&&item.hsv.saturation>=.12)", self.client)
        self.assertIn("closestHue+6", self.client)
        self.assertIn("distance+hsv_hue_difference*.2", self.client)
        self.assertNotIn("item.hue_difference<=72", self.client)
        self.assertIn("function toggleCell(card,force)", self.client)
        self.assertIn("/account/color-palettes/discovered", self.client)
        self.assertIn("both use ${cell.official.name}", self.client)
        self.assertIn("def save_color_discovery_palette(event):", self.api)
        self.assertIn("both use the official", self.api)
        infrastructure = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
        self.assertIn("RouteKey: POST /account/color-palettes/discovered", infrastructure)
        self.assertNotIn('class="cell-hex official-hex"', self.client)
        self.assertIn('class="cell-square detected-picker" type="color"', self.client)
        self.assertIn('class="cell-hex detected-hex"', self.client)
        self.assertIn("rasterizer_hex:c.official.hex", self.client)
        self.assertIn('str(swatch.get("rasterizer_hex")', self.api)
        self.assertIn("function sortMeasurements()", self.client)
        self.assertIn("item.official=nearestOfficial(hex)", self.client)
        self.assertIn("selected.sort(key=lambda item:item[2])", self.api)
        self.assertIn("function measurementCard(c,m)", self.client)
        self.assertIn('class="official-group"', self.client)
        self.assertIn("resources.palette.map(official=>", self.client)

    def test_one_enabled_swatch_can_generate_a_finer_refinement_grid(self):
        self.assertIn('id="refineGrid"', self.page)
        self.assertIn('id="reviewAction"', self.page)
        self.assertIn("$('#reviewAction').onchange=", self.client)
        self.assertIn("measurements.forEach(cell=>cell.enabled=false)", self.client)
        self.assertIn("if($('#reviewAction').value==='refine')", self.client)
        self.assertIn('id="refineBounds"', self.page)
        self.assertIn('#refineBounds[hidden]{display:none!important}', self.page)
        self.assertIn('id="refineXParameter"', self.page)
        self.assertIn('id="refineYParameter"', self.page)
        self.assertIn("To sweep only one parameter", self.page)
        self.assertIn("function populateRefineBounds(item)", self.client)
        self.assertIn("function populateRefineAxis(item,axis)", self.client)
        self.assertIn("function refinementCenter(item,parameter)", self.client)
        self.assertIn("refine_x_parameter:x", self.client)
        self.assertIn("refine_y_parameter:y", self.client)
        self.assertIn("if(x===y)", self.client)
        self.assertIn("function originalAxisStep(values)", self.client)
        self.assertIn("refine_x_low:bounds[0]", self.client)
        self.assertIn("enabled.length!==1", self.client)
        self.assertIn("refine_from_grid_id:grid.grid_id", self.client)
        self.assertIn("refine_cell_index:enabled[0].index", self.client)
        self.assertIn('refinement_grid_id = str(data.get("refine_from_grid_id")', self.api)
        self.assertIn('request_data.get("refine_x_parameter")', self.api)
        self.assertIn('request_data.get("refine_y_parameter")', self.api)
        self.assertIn("def color_refinement_center(cell, parameter):", self.api)
        self.assertIn("def color_refinement_step(metadata, parameter):", self.api)
        self.assertIn('"pulse_width": 10', self.api)
        self.assertIn('"x_low":x_center-x_step, "x_high":x_center+x_step', self.api)
        self.assertIn('"y_low":y_center-y_step, "y_high":y_center+y_step', self.api)
        self.assertIn('"refinement":refinement', self.api)
        self.assertIn('source_cut = lightburn_snapshot_element(refinement_cell.get("laser_settings"))', self.api)
        self.assertIn("if not library and contents is None and not refinement", self.api)
        self.assertIn('("refine_x_low","x_low")', self.api)
        self.assertIn('"requested_x_range":[data["x_low"],data["x_high"]]', self.api)
        self.assertIn('"source_x_parameter":source_x_parameter', self.api)
        self.assertIn("independently choose a different supported parameter", self.docs)
        self.assertIn("set the minimum and maximum of the other axis to the same value", self.docs)

    def test_grid_and_refinement_axes_use_matching_responsive_rows(self):
        self.assertIn(".form-grid,.axis-controls{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}", self.page)
        self.assertIn("@media(max-width:760px){.form-grid,.axis-controls{grid-template-columns:1fr}", self.page)
        self.assertGreaterEqual(self.page.count('class="axis-controls'), 2)
        initial_axes = self.page.split('<div class="axis-controls full">', 1)[1].split('</div>', 1)[0]
        self.assertLess(initial_axes.index('id="xParameter"'), initial_axes.index('id="xLow"'))
        self.assertLess(initial_axes.index('id="xLow"'), initial_axes.index('id="xHigh"'))
        self.assertLess(initial_axes.index('id="xHigh"'), initial_axes.index('id="yParameter"'))
        self.assertLess(initial_axes.index('id="yParameter"'), initial_axes.index('id="yLow"'))
        self.assertLess(initial_axes.index('id="yLow"'), initial_axes.index('id="yHigh"'))
        refinement_axes = self.page.split('<div id="refineBounds" class="full" hidden><div class="axis-controls">', 1)[1].split('</div>', 1)[0]
        self.assertLess(refinement_axes.index('id="refineXParameter"'), refinement_axes.index('id="refineXLowLabel"'))
        self.assertLess(refinement_axes.index('id="refineXLowLabel"'), refinement_axes.index('id="refineXHighLabel"'))
        self.assertLess(refinement_axes.index('id="refineXHighLabel"'), refinement_axes.index('id="refineYParameter"'))
        self.assertLess(refinement_axes.index('id="refineYParameter"'), refinement_axes.index('id="refineYLowLabel"'))
        self.assertLess(refinement_axes.index('id="refineYLowLabel"'), refinement_axes.index('id="refineYHighLabel"'))

    def test_reconstructed_lightburn_settings_use_canonical_field_order(self):
        self.assertIn("LIGHTBURN_SETTING_FIELD_ORDER = (", self.api)
        self.assertIn('"index", "name", "LinkPath", "minPower", "maxPower"', self.api)
        self.assertIn("sorted(settings.items(), key=lambda item:(order.get", self.api)

    def test_photo_overlay_identifies_perspective_grid_cells(self):
        self.assertIn("function overlayGrid()", self.client)
        self.assertIn("point(column/columns,0)", self.client)
        self.assertIn("point(0,row/rows)", self.client)
        self.assertIn("ctx.fillText(String(index),x,y)", self.client)
        self.assertIn("numbered overlay", self.page)

    def test_photo_attempts_auto_alignment_but_keeps_manual_corners(self):
        self.assertIn('id="autoAlign"', self.page)
        self.assertIn("function autoAlignGrid()", self.client)
        self.assertIn("const aligned=autoAlignGrid()", self.client)
        self.assertIn("corners=proposed;draw();return true", self.client)
        self.assertIn("canvas.onpointermove", self.client)
        self.assertIn("drag any corner to correct it", self.client)

    def test_analysis_samples_clean_photo_before_redrawing_overlay(self):
        handler = self.client[self.client.index("$('#measure').onclick="):]
        self.assertLess(handler.index("ctx.drawImage(image"), handler.index("measurements=m.cells.map"))
        self.assertLess(handler.index("measurements=m.cells.map"), handler.index(";draw();renderMeasurements()"))

    def test_optional_white_background_calibrates_from_outside_grid(self):
        self.assertIn('<strong>White Background</strong>', self.page)
        self.assertIn("function insideGrid(x,y)", self.client)
        self.assertIn("function whiteBalanceGains()", self.client)
        self.assertIn("if(insideGrid(x,y))continue", self.client)
        self.assertIn("function balancedRgb(value,gains)", self.client)
        self.assertIn("displayGains=[1,1,1]", self.client)
        self.assertIn("function drawPhoto()", self.client)
        self.assertIn("pixels[offset+channel]*displayGains[channel]", self.client)
        self.assertIn("displayGains=balance.gains", self.client)
        self.assertIn("preview now shows the same correction used for measurement", self.client)

    def test_guests_upload_measure_refine_and_export_without_vault_access(self):
        infrastructure = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
        self.assertIn('id="librarySource"', self.page)
        self.assertIn('id="libraryFile"', self.page)
        self.assertIn('value="export">Export selected settings (.clb)', self.page)
        self.assertIn("function usingSavedLibrary()", self.client)
        self.assertIn("function exportColorPalette(enabled)", self.client)
        self.assertIn("function snapshotElement(documentNode,snapshot", self.client)
        self.assertIn("guestMode?'/guest/color-discovery/uploads':'/color-discovery/uploads'", self.client)
        self.assertIn("if(guestMode)throw new Error('Sign in to save palettes to Swatch Palette Vault')", self.client)
        self.assertIn("def create_color_discovery_upload(event, guest=False):", self.api)
        self.assertIn('POST /guest/color-discovery/uploads', infrastructure)
        self.assertIn('POST /guest/color-discovery/grids/{task_id}', infrastructure)
        self.assertIn('GET /guest/color-discovery/grids/{task_id}', infrastructure)
        self.assertIn('POST /guest/color-discovery/grids/{task_id}/refine', infrastructure)


if __name__ == "__main__":
    unittest.main()
