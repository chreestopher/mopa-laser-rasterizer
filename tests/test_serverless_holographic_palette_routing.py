import ast
import unittest
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class ServerlessHolographicPaletteRoutingTests(unittest.TestCase):
    def test_serverless_rasterizer_supports_explicit_svg_only_jobs(self):
        page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        worker = (ROOT / "worker.py").read_text(encoding="utf-8")

        self.assertIn('<option value="svg">SVG-Only (no laser settings)</option>', page)
        self.assertIn("function svgOnlySelected(){return selectedAsset().kind==='svg'}", page)
        self.assertIn("material_key:grant.material?.key||''", page)
        self.assertIn("svg_only:svgOnly", page)
        self.assertIn('result["material"] = (None if svg_only else', handler)
        self.assertIn('data["svg_only"] = "true" if svg_only else "false"', handler)
        self.assertIn('key for key in (artwork_key, material_key, recipe_input_key) if key', handler)
        self.assertIn('if not svg_only:', worker)
        self.assertIn('None if svg_only else material_path', worker)

    def test_test_grid_and_coupon_labels_are_enlarged_without_resizing_geometry(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")

        self.assertIn('"Str":holographic_grid_label,"H":"3.5"', handler)
        self.assertIn('f"HOLO GRID {calibration_id[:8]}"', handler)
        self.assertIn('"font-size":"1.575"', handler)
        self.assertIn('"H":"5.25"', handler)
        self.assertIn('"H":"3.5"', handler)
        self.assertIn("cell, gap, label_space = 10.0, 2.0, 6.0", handler)
        self.assertIn("top_label = max(4.0, min(8.0, cell_mm * .45))", handler)
        self.assertIn("label_baseline = max(.8, top_label * .24)", handler)
        self.assertIn("label_center_y = max(.5, (top_label - 3.0) / 2)", handler)

    def test_raster_preset_controls_align_values_above_full_width_sliders(self):
        page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

        self.assertIn(".filter-control{display:grid;grid-template-columns:minmax(0,1fr)", page)
        self.assertIn(".filter-control label{display:grid;grid-template-columns:minmax(0,1fr) 88px", page)
        self.assertIn(".filter-control input[type=number]{width:88px;justify-self:end;text-align:right}", page)
        self.assertIn(".filter-control input[type=range]{display:block;width:100%", page)
        self.assertIn("row.setAttribute('role','group')", page)
        self.assertIn("row.setAttribute('aria-label',settingLabel)", page)

        shared_styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")
        self.assertIn("body.staging-home fieldset>label", shared_styles)
        self.assertIn("body.staging-home .filter-control label", shared_styles)
        self.assertIn("color:#8ee474!important", shared_styles)
        self.assertIn("body.staging-home input:not([type=checkbox]):not([type=range])", shared_styles)
        self.assertIn('id="statusHeading"', page)
        self.assertIn("body.staging-home #statusHeading{color:#e4e3cf!important", shared_styles)
        self.assertIn("body.staging-home #materialUpload>label", shared_styles)
        self.assertIn("body.light-machine.staging-home fieldset>legend,body.light-machine.staging-home #statusHeading", shared_styles)

    def test_material_import_normalizes_duplicate_and_missing_descriptions(self):
        handler_path = ROOT / "serverless_api" / "handler.py"
        tree = ast.parse(handler_path.read_text(encoding="utf-8"))
        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in {
                "effective_lightburn_settings", "material_summary",
                "normalize_imported_material_descriptions",
            }
        ]
        namespace = {"ET": ET}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(handler_path), "exec"), namespace)
        library = b'''<LightBurnLibrary><Material name="Steel">
            <Entry Desc="white"><CutSetting><name Value="white"/></CutSetting></Entry>
            <Entry Desc="white-2"><CutSetting><name Value="white-2"/></CutSetting></Entry>
            <Entry Desc="White"><CutSetting><name Value="White"/></CutSetting></Entry>
            <Entry><CutSetting><name Value="Custom"/></CutSetting></Entry>
            <Entry><CutSetting><name Value=""/></CutSetting></Entry>
        </Material></LightBurnLibrary>'''

        normalized, adjustments = namespace["normalize_imported_material_descriptions"](library)
        root = ET.fromstring(normalized)
        entries = root.findall("./Material/Entry")

        self.assertEqual([entry.get("Desc") for entry in entries], [
            "white", "white-2", "White-3", "Unnamed setting", "Unnamed setting-2",
        ])
        self.assertEqual(entries[2].find("./CutSetting/name").get("Value"), "White-3")
        self.assertEqual(entries[3].find("./CutSetting/name").get("Value"), "Custom")
        self.assertEqual(len(adjustments), 3)
        summary = namespace["material_summary"](normalized)
        self.assertEqual(summary["entry_count"], 5)
        self.assertIn(
            "contents, import_adjustments = normalize_imported_material_descriptions(contents)",
            handler_path.read_text(encoding="utf-8"),
        )

    def test_material_import_retains_only_the_selected_material(self):
        handler_path = ROOT / "serverless_api" / "handler.py"
        tree = ast.parse(handler_path.read_text(encoding="utf-8"))
        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in {
                "effective_lightburn_settings", "material_summary", "retain_selected_material"
            }
        ]
        namespace = {"ET": ET}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(handler_path), "exec"), namespace)
        library = b'<LightBurnLibrary><Material name="Steel"><Entry Desc="Hatch"><CutSetting type="Scan"/></Entry></Material><Material name="Brass"><Entry Desc="Hatch"><CutSetting type="Scan"/></Entry></Material></LightBurnLibrary>'

        selected = namespace["retain_selected_material"](library, "Steel")
        summary = namespace["material_summary"](selected)

        self.assertEqual(summary["material_names"], ["Steel"])
        self.assertEqual([entry["description"] for entry in summary["entries"]], ["Hatch"])
        with self.assertRaisesRegex(ValueError, "selected material needs at least one laser setting entry"):
            namespace["material_summary"](b'<LightBurnLibrary><Material name="Empty"/></LightBurnLibrary>')
        with self.assertRaisesRegex(ValueError, "Available materials: Steel, Brass.*Choose a material name present in the library"):
            namespace["retain_selected_material"](library, "Titanium")

        duplicate_names = b'<LightBurnLibrary><Material name="Steel"/><Material name="Steel"/></LightBurnLibrary>'
        with self.assertRaisesRegex(ValueError, "Give the materials distinct names in LightBurn"):
            namespace["retain_selected_material"](duplicate_names, "Steel")
        with self.assertRaisesRegex(ValueError, "LightBurn's Material Library.*setting descriptions.*start the import again"):
            namespace["retain_selected_material"](b"<NotALightBurnLibrary/>", "Steel")

    def test_palette_vault_populates_material_names_from_selected_file(self):
        page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")

        self.assertIn('id="materialSelectionField"', page)
        self.assertIn('id="materialImportMaterial"', page)
        self.assertIn("async function populateMaterialChoices()", script)
        self.assertIn('payload.material_name=materialName', script)
        self.assertIn('file.text()', script)

    def test_all_palette_inline_editors_use_shared_field_typography(self):
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        self.assertIn("body.staging-vault .entry-editor label,body.staging-vault .depth-entry-editor label,body.staging-vault .recipe-entry-editor label", styles)
        self.assertIn("body.staging-vault .entry-editor input:not([type=checkbox]):not([type=range]):not([type=color])", styles)
        self.assertIn("body.staging-vault .depth-entry-editor output{color:#e4e3cf!important", styles)
        self.assertIn("body.light-machine.staging-vault .entry-editor label", styles)

    def test_coupon_uses_private_presigned_s3_download_instead_of_blob_url(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")

        coupon_branch = handler[handler.index('if action == "coupon":'):handler.index('if action == "copy_new":')]
        self.assertIn('Tagging="mopa-retention=job"', coupon_branch)
        self.assertIn('"download_url":download_url', coupon_branch)
        self.assertIn('ResponseContentDisposition', coupon_branch)
        template = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
        self.assertIn("s3:PutObjectTagging", template)
        self.assertIn("users/*/exports/*", template)
        self.assertIn('projectDownload=action==="coupon"||action==="blank_project"', script)
        self.assertIn('if(projectDownload){const download=await response.json()', script)
        self.assertIn('link.href=download.download_url', script)
        self.assertNotIn('if(action==="export"||action==="coupon"){const blob=', script)

    def test_hatch_planner_builds_full_planned_palette(self):
        handler_path = ROOT / "serverless_api" / "handler.py"
        tree = ast.parse(handler_path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "hatch_palette_contents")
        palette = [(f"Color-{index}", f"#{index:06X}") for index in range(30)]
        namespace = {"ET": ET, "deepcopy": deepcopy, "PALETTE": palette}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(handler_path), "exec"), namespace)

        contents = namespace["hatch_palette_contents"](
            "Steel", base_settings={"speed": 500}, start_angle=10,
            angular_span=180, first_interval=.05, last_interval=.1,
        )
        entries = ET.fromstring(contents).findall("./Material/Entry")

        self.assertEqual(len(entries), 30)
        self.assertEqual(entries[0].find("./CutSetting/angle").get("Value"), "10")
        self.assertEqual(entries[-1].find("./CutSetting/interval").get("Value"), "0.1")
        self.assertEqual(entries[0].find("./CutSetting/speed").get("Value"), "500")

    def test_hatch_planner_is_available_through_unified_palette_workflow(self):
        page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        template = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")

        self.assertIn('value="hatch_palette"', page)
        self.assertIn('id="hatchImportBaseSetting"', page)
        self.assertIn('id="hatchImportOperation"', page)
        self.assertIn('id="hatchPlannerFields"', page)
        self.assertIn("async function populateHatchImportBaseSettings()", script)
        self.assertIn("payload.base_setting_id=Number(baseSetting)", script)
        self.assertIn("payload.hatch_operation=", script)
        self.assertIn("contents = hatch_palette_contents(", handler)
        self.assertNotIn("def create_hatch_palette(event):", handler)
        self.assertNotIn('POST /account/hatch-palettes', template)

    def test_mobile_nav_uses_wrapped_height_before_first_visible_paint(self):
        shell = (ROOT / "serverless_web" / "staging-shell.js").read_text(encoding="utf-8")
        styles = (ROOT / "serverless_web" / "staging-shell.css").read_text(encoding="utf-8")
        self.assertIn('matchMedia("(max-width: 700px)")', shell)
        self.assertIn('machineNav.classList.add("nav-wrap-all")', shell)
        self.assertIn(".staging-shell .machine-nav-item>a,.staging-shell .machine-nav.nav-wrap-all", styles)

    def test_holographic_lab_uses_shared_title_and_field_typography(self):
        page = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        for step in range(1, 5):
            self.assertIn(f'<span class="stage-number">Step {step:02d}</span>', page)
        self.assertIn("For best results, sweep your most iridescent laser setting", page)
        self.assertIn("body.staging-holographic .stage h2{color:#e4e3cf!important", styles)
        self.assertIn("body.staging-holographic .stage .stage-number{display:block;width:auto;height:auto", styles)
        self.assertIn("color:#8ee474;background:none;font:inherit", styles)
        self.assertIn("body.staging-holographic .stage label{color:#8ee474!important", styles)
        self.assertIn("body.staging-holographic .stage input:not([type=checkbox]):not([type=range])", styles)
        self.assertIn("body.light-machine.staging-holographic .stage h2", styles)

    def test_holographic_lab_supports_guest_uploads_and_account_palette_sources(self):
        page = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "holographic.js").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        template = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")

        self.assertIn('id="calibrationSource"', page)
        self.assertIn('id="calibrationFile"', page)
        self.assertIn('id="calibrationLibraryRow" class="full" hidden', page)
        self.assertIn('const saved=!guestMode&&$("#calibrationSource").value==="saved"', script)
        self.assertIn('guestMode?"/guest/holographic/calibration-uploads":"/holographic/calibration-uploads"', script)
        self.assertIn('downloadGuestPalette(profile)', script)
        self.assertIn('resources=guestMode?{material_libraries:[]}:await api("/account/resources")', script)
        self.assertIn('def create_holographic_calibration_upload(event, guest=False):', handler)
        self.assertIn('return create_holographic_calibration(event, guest=True, upload_task_id=guest_parts[3])', handler)
        self.assertIn('return create_holographic_calibration(event, upload_task_id=holographic_parts[2])', handler)
        self.assertIn('POST /guest/holographic/calibration-uploads', template)
        self.assertIn('POST /guest/holographic/calibrations/{task_id}', template)
        self.assertIn('POST /holographic/calibration-uploads', template)
        self.assertIn('POST /holographic/calibrations/{task_id}', template)

    def test_experimental_lab_cards_use_cream_display_titles(self):
        page = (ROOT / "templates" / "experimental_laboratories.html").read_text(encoding="utf-8")
        builder = (ROOT / "dev_setup" / "build_serverless_experimental.py").read_text(encoding="utf-8")
        deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")
        shell = (ROOT / "serverless_web" / "staging-shell.js").read_text(encoding="utf-8")
        color_lab = (ROOT / "serverless_web" / "color-lab.html").read_text(encoding="utf-8")
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        self.assertEqual(page.count('class="lab-card"'), 3)
        self.assertIn("<h2>Color Lab</h2>", page)
        self.assertLess(page.index("<h2>Color Lab</h2>"), page.index("<h2>Fauxlographic Etching Lab</h2>"))
        self.assertLess(page.index("<h2>Color Lab</h2>"), page.index("<h2>Depthmap/Relief Engraving Lab</h2>"))
        self.assertIn('href="/color-discovery">Open Color Lab</a>', page)
        self.assertIn("'href=\"/color-discovery\"', 'href=\"/color-lab.html\"'", builder)
        self.assertIn('$BUILD_DIR/seo/color-lab.html', deploy)
        self.assertIn('"/color-lab.html"', shell)
        self.assertIn("Color Discovery Workflow", color_lab)
        self.assertIn("body.staging-experimental .lab-card h2{color:#e4e3cf!important", styles)
        self.assertIn("body.staging-experimental .staging-page-shell{width:100%;max-width:none}", styles)
        self.assertIn("body.light-machine.staging-experimental .lab-card h2{color:#20221e!important", styles)

    def test_depthmap_lab_uses_cream_display_titles(self):
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        self.assertIn("body.staging-depthmap main h2{color:#e4e3cf!important", styles)
        self.assertIn("body.staging-depthmap main h3{color:#e4e3cf!important", styles)
        self.assertIn("body.staging-depthmap main label{color:#8ee474!important", styles)
        self.assertIn("body.staging-depthmap main input:not([type=checkbox]):not([type=range])", styles)
        self.assertIn("body.staging-depthmap main output{color:#e4e3cf", styles)
        self.assertIn("body.light-machine.staging-depthmap main h2,body.light-machine.staging-depthmap main h3", styles)

    def test_job_history_uses_shared_title_and_detail_typography(self):
        page = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        self.assertIn('<section class="recent-jobs-section"><h2>Recent jobs</h2>', page)
        self.assertNotIn('<section class="panel"><h2>Recent jobs</h2>', page)
        self.assertIn("body.staging-history .recent-jobs-section>h2,body.staging-history .job-details h3{color:#e4e3cf!important", styles)
        self.assertIn("body.staging-history .job-details dt,body.staging-history .job-details p>strong{color:#8ee474!important", styles)
        self.assertIn("body.staging-history .job-details dd,body.staging-history .job-details p", styles)
        self.assertIn("body.staging-history .job-delete-actions [data-delete-job]{display:block;width:100%", styles)
        self.assertIn("background:linear-gradient(#a8464e,#67242a)!important", styles)
        self.assertIn("body.light-machine.staging-history .recent-jobs-section>h2,body.light-machine.staging-history .job-details h3", styles)
        self.assertIn('if(status.includes("fail")||status.includes("error"))return "status-failed"', script)
        self.assertIn('return "status-active"', script)
        self.assertIn("body.light-machine.staging-history .job-record.status-completed>.job", styles)
        self.assertIn("body.light-machine.staging-history .job-record.status-pending>.job,body.light-machine.staging-history .job-record.status-active>.job", styles)
        self.assertIn("@keyframes active-job-pulse-light", styles)
        self.assertIn("body.light-machine.staging-history .job-record.status-failed>.job", styles)
        self.assertIn("body.light-machine.staging-history .job-details{border-top", styles)
        self.assertIn("body.light-machine.staging-history .job-log-list", styles)

    def test_community_set_uses_shared_typography_without_an_inner_panel(self):
        page = (ROOT / "templates" / "community_set.html").read_text(encoding="utf-8")
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        self.assertIn("const crossHatchIndex = discoveredParameters.findIndex", page)
        self.assertIn("const parametersThroughCrossHatch = crossHatchIndex >= 0 ? discoveredParameters.slice(0,crossHatchIndex + 1)", page)
        self.assertIn("const typeParameter = discoveredParameters.find", page)
        self.assertIn("[...parametersThroughCrossHatch,typeParameter]", page)
        self.assertNotIn("...parameters.map(labelFor),'Notes'", page)
        self.assertNotIn("notes.className='notes-cell'", page)
        self.assertIn("body.staging-community .community-panel{padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important}", styles)
        self.assertIn("body.staging-community .community-panel h2,body.staging-community .community-panel h3{color:#e4e3cf!important", styles)
        self.assertIn("body.staging-community .community-search label,body.staging-community .privacy-note strong,body.staging-community th{color:#8ee474!important", styles)
        self.assertIn("body.staging-community .community-search input{min-height:42px;color:#e4e3cf!important", styles)
        self.assertIn("body.light-machine.staging-community .community-panel{border:0!important;background:transparent!important;box-shadow:none!important}", styles)

    def test_job_history_details_have_curated_parameter_and_vault_order(self):
        script = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")

        self.assertIn('function parametersHtml(parameters)', script)
        self.assertIn('["Pixel square mm",values.pixel_square_mm]', script)
        self.assertIn('["New width",values.new_width]', script)
        self.assertIn('["New height",values.new_height]', script)
        self.assertIn('["Image preset",values.image_preset]', script)
        self.assertIn('["Abstract filter",values.abstract_filter]', script)
        self.assertIn('["Abstract filter parameters",values.abstract_filter_parameters]', script)
        self.assertIn('["Geometry style",values.geometry_style]', script)
        self.assertIn('["Geometry style parameters",geometryParameters]', script)
        self.assertIn('function formattedValue(value,depth=0)', script)
        self.assertIn('formattedValue(item,depth+1)', script)
        self.assertIn('function effectiveGeometryParameters(style,value)', script)
        self.assertIn('if(used.has("glyphs")&&parsed.glyphs)', script)
        self.assertIn('if(used.has("krasnow_grating")&&parsed.krasnow_grating)', script)
        self.assertIn('<h3>Swatch Settings</h3>', script)
        self.assertIn('class="job-details-grid"', script)
        self.assertIn('job-details-column job-swatch-settings', script)
        self.assertIn('Object.entries(parsedOverrides)', script)
        self.assertIn('job-mini-swatch-grid', script)

        self.assertIn('function displayedLogs(logs)', script)
        self.assertIn('"palette_names","material_library_layers","lightburn_layers","requested_limit_colors","effective_limit_colors"', script)
        self.assertIn("Material layer '.*' assigned to LightBurn layer", script)
        self.assertIn('@media(min-width:800px){.job-log-list{gap:0}', (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8"))
        self.assertIn('material=materialName||values.material', script)
        self.assertIn('["Color name overrides",values.color_name_overrides]', script)
        self.assertNotIn('data-job-material', script)
        self.assertNotIn('<h3>Downloads</h3>', script)
        self.assertIn('job-primary-downloads', script)
        self.assertIn('<strong>Job type:</strong> <span data-job-type></span>', script)
        self.assertIn('holographic_artwork:"Fauxlographic Etching Lab"', script)
        self.assertIn('font-size:clamp(1.15rem,3vw,1.65rem)!important', styles)

    def test_job_history_renders_compact_masks_as_thumbnails(self):
        script = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        page = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")
        self.assertIn('function compactMaskThumbnailHtml(mask)', script)
        self.assertIn('if(pixels.length!==width*height)', script)
        self.assertIn('return compactMaskThumbnailHtml(parsed)', script)
        self.assertIn('canvas.toDataURL("image/png")', script)
        self.assertIn('class="job-mask-thumbnail"', script)
        self.assertIn('.job-mask-thumbnail{', page)

    def test_rasterizer_pixel_size_accepts_four_decimals_down_to_point_zero_one(self):
        staging = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        production = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        jobs = (ROOT / "routes" / "jobs.py").read_text(encoding="utf-8")

        self.assertIn('id="pixel" type="number" min="0.01" step="0.0001"', staging)
        self.assertIn('id="pixel_square_mm" name="pixel_square_mm" value="1" min="0.01" step="0.0001"', production)
        self.assertIn('return response(400, {"message": "Pixel size must be at least 0.01 mm"})', handler)
        self.assertIn('"message": "Pixel size must be at least 0.01 mm"', jobs)
        self.assertIn("if not .01 <= pixel_mm <= 5:", handler)

    def test_job_history_stores_and_infers_explicit_job_types(self):
        handler_path = ROOT / "serverless_api" / "handler.py"
        source = handler_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "history_job_type")
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(handler_path), "exec"), namespace)

        classify = namespace["history_job_type"]
        self.assertEqual(classify({"job_type": "rasterizer"}), "rasterizer")
        self.assertEqual(classify({"run_parameters": {"job_type": "holographic_artwork"}}), "holographic_artwork")
        self.assertEqual(classify({"image_preset": "holographic_artwork"}), "holographic_artwork")
        self.assertEqual(classify({}), "rasterizer")
        self.assertIn('"job_type": "holographic_artwork"', source)
        self.assertIn('job_type = "holographic_artwork" if generated_recipe_id else "rasterizer"', source)

    def test_rasterizer_holographic_jobs_derive_missing_max_dimension_from_source(self):
        route_path = ROOT / "routes" / "holographic.py"
        route_source = route_path.read_text(encoding="utf-8")
        tree = ast.parse(route_source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_resolved_holographic_dimension")
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(route_path), "exec"), namespace)
        resolve = namespace["_resolved_holographic_dimension"]

        self.assertEqual(resolve(0, (1200, 800)), 1200)
        self.assertEqual(resolve(None, (800, 1200)), 1200)
        self.assertEqual(resolve(400, (1200, 800)), 400)
        self.assertEqual(resolve(0, (4000, 3000)), 1600)
        with self.assertRaises(ValueError):
            resolve(7, (1200, 800))

        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.assertIn("max_dimension = max(explicit_dimensions) if explicit_dimensions else 0", handler)
        self.assertIn("max_dimension = _resolved_holographic_dimension(max_dimension, image.size)", route_source)

    def test_rasterizer_holographic_palette_replaces_image_controls_with_lab_settings(self):
        page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        worker = (ROOT / "worker.py").read_text(encoding="utf-8")
        holographic = (ROOT / "routes" / "holographic.py").read_text(encoding="utf-8")

        self.assertIn('id="holographicRasterSettings"', page)
        self.assertIn('id="rasterHoloCutMode"', page)
        self.assertIn('id="rasterHoloBlack"', page)
        self.assertIn("holographicSettings.classList.toggle('hidden',!selectedRecipe)", page)
        self.assertIn("cut_mode:recipe?document.querySelector('#rasterHoloCutMode').value:'setting'", page)
        self.assertIn("preserve_black_outlines:recipe&&document.querySelector('#rasterHoloBlack').checked", page)
        self.assertIn('embedded_black_name = "Rasterizer Preserved Black"', handler)
        self.assertIn('"cut_mode": cut_mode', handler)
        self.assertIn('"preserve_black_outlines": preserve_black_outlines', handler)
        self.assertIn('embedded_black_setting_name=payload.get("embedded_black_setting_name")', worker)
        self.assertIn("if not embedded_black_setting_name:", holographic)

    def test_holographic_artwork_exports_only_svg_and_lightburn_outputs(self):
        worker = (ROOT / "worker.py").read_text(encoding="utf-8")
        holographic = (ROOT / "routes" / "holographic.py").read_text(encoding="utf-8")

        self.assertNotIn('"kind": "holographic_art_export"', holographic)
        self.assertNotIn('metadata_name = f"{stem}.json"', holographic)
        self.assertNotIn('"metadata_url"', worker)
        self.assertIn("output_names = (svg_name, lbrn_name)", worker)
        self.assertIn("registering 2/2 outputs with job history", worker)
        self.assertIn("prepared 2/2 Fauxlographic Artwork artifacts", holographic)

    def test_all_rasterizer_downloads_are_svg_first_and_uniform_filename_buttons(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        rasterizer = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        history = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        history_page = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")

        self.assertIn('if key.endswith(".svg"):\n        return (0, key)', handler)
        self.assertIn('if key.endswith(".lbrn2"):\n        return (1, key)', handler)
        self.assertEqual(handler.count("ordered_output_descriptors(task_id, source_name,"), 3)
        self.assertIn('class="staging-action-button output-download-button"', rasterizer)
        self.assertIn('const label=`Download ${outputBasename(output)}`', rasterizer)
        self.assertIn("renderRasterOutputs(job.outputs)", rasterizer)
        self.assertIn('name.endsWith(".svg")?0:name.endsWith(".lbrn2")?1:2', history)
        self.assertIn('const label=`Download ${outputBasename(output)}`', history)
        self.assertIn('class="staging-action-button"', history)
        self.assertIn(".job-primary-downloads a{display:flex!important", history_page)
        shared_styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")
        self.assertIn(".staging-action-button{border:2px solid #9ba89f!important", shared_styles)
        self.assertIn("body.light-machine .staging-action-button{color:#171815!important", shared_styles)
        self.assertIn("width:100%;height:60px", rasterizer)
        self.assertIn("width:100%;height:60px", history_page)

    def test_holographic_calibration_downloads_are_svg_first_filename_buttons(self):
        page = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "holographic.js").read_text(encoding="utf-8")

        self.assertIn('src="/holographic.js?v=6"', page)
        self.assertIn('.holographic-downloads{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px', page)
        self.assertIn('.holographic-download-button{display:flex!important;box-sizing:border-box;width:100%;height:60px', page)
        self.assertEqual(script.count('class="staging-action-button holographic-download-button"'), 2)
        svg = script.index('download="${stem}.svg">Download ${stem}.svg</a>')
        lightburn = script.index('download="${stem}.lbrn2">Download ${stem}.lbrn2</a>')
        self.assertLess(svg, lightburn)
        self.assertNotIn('download="${stem}.json">Download ${stem}.json</a>', script)

    def test_holographic_photo_uses_numbered_perspective_overlay_without_sampling_it(self):
        page = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "holographic.js").read_text(encoding="utf-8")

        self.assertIn('src="/holographic.js?v=6"', page)
        self.assertIn("numbered perspective overlay", page)
        self.assertIn("function overlayGrid()", script)
        self.assertIn("bilinear(column/columns,0)", script)
        self.assertIn("bilinear(0,row/rows)", script)
        self.assertIn("context.fillText(String(index),x,y)", script)
        self.assertIn("context.closePath();context.stroke();overlayGrid();corners.forEach", script)
        analyze = script.split('$("#analyzePhoto").onclick=', 1)[1].split("function guestPalette", 1)[0]
        self.assertLess(analyze.index("context.drawImage(photoImage,0,0,canvas.width,canvas.height)"), analyze.index("measurements=cells.map"))
        self.assertLess(analyze.index("measurements=cells.map"), analyze.index("drawPhoto();renderMeasurements()"))

    def test_holographic_lab_finishes_by_linking_saved_recipe_to_rasterizer(self):
        page = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "holographic.js").read_text(encoding="utf-8")
        rasterizer = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="runRecipeInRasterizer"', page)
        self.assertIn('Run Rasterizer with This Fauxlographic Palette', page)
        self.assertNotIn('id="artworkForm"', page)
        self.assertNotIn('id="holoArtwork"', page)
        self.assertNotIn('$("#artworkForm").onsubmit', script)
        self.assertIn('sessionStorage.setItem("last_holographic_recipe_id",saved.recipe_id)', script)
        self.assertIn('`/?recipe=${encodeURIComponent(recipeId)}`', script)
        self.assertIn("const requestedRecipe=new URLSearchParams(location.search).get('recipe')", rasterizer)
        self.assertIn("choice.value=requestedValue", rasterizer)
        self.assertIn("recipeRasterEntries().forEach(item=>selectedPaletteHexes.add(item.selection_key))", rasterizer)

    def test_job_history_rows_have_live_status_tones(self):
        page = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        for tone in ("status-completed", "status-pending", "status-active", "status-failed"):
            self.assertIn(tone, page)
            self.assertIn(tone, script)
        self.assertIn('button.closest(".job-record").className', script)
        self.assertIn(".job-record.status-pending>.job,.job-record.status-active>.job{animation:active-job-pulse", page)
        self.assertIn("@keyframes active-job-pulse", page)
        self.assertIn("prefers-reduced-motion:reduce", page)

    def test_job_log_polling_is_toggleable_and_closes_after_thirty_minutes(self):
        script = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")

        self.assertIn("const LOG_POLL_LIMIT_MS=30*60*1000", script)
        self.assertIn("function stopLogPolling()", script)
        self.assertIn('button.textContent="Load logs"', script)
        self.assertIn('?"Stop polling"', script)
        self.assertIn("if(logsRequested){stopLogPolling();return}", script)
        self.assertIn("pollLimitTimer=setTimeout", script)
        self.assertIn("if(activeTask===taskId&&logsRequested)closeActive()", script)
        self.assertIn("clearTimeout(pollLimitTimer)", script)

    def test_job_history_supports_owned_job_and_asset_deletion(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        page = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        template = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
        self.assertIn("def delete_account_job(event, task_id):", handler)
        self.assertIn('f"users/{owner}/jobs/{task_id}/"', handler)
        self.assertIn('f"jobs/{task_id}/"', handler)
        self.assertIn('method in {"GET", "DELETE"}', handler)
        self.assertIn('data-delete-job', page)
        self.assertIn('{method:"DELETE"}', page)
        self.assertIn("Seven-day retention:", page)
        self.assertIn("Saved Material Libraries and palettes in the Swatch Palette Vault are not removed.", page)
        self.assertIn("RouteKey: DELETE /account/jobs/{task_id}", template)

    def test_job_history_shows_start_and_terminal_end_times(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        page = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")

        self.assertIn('"ended_at": ended_at', handler)
        self.assertIn('terminal_status = str(status).lower() in {"completed", "failed"}', handler)
        self.assertIn("Start Time:", script)
        self.assertIn("End Time:", script)
        self.assertIn('setText("[data-job-start-time]",formatTime(job.created_at))', script)
        self.assertIn('setText("[data-job-end-time]",formatEndTime(job))', script)
        self.assertIn('<strong>Job Duration:</strong> <span data-job-duration></span>', script)
        self.assertIn('setText("[data-job-duration]",formatDuration(job))', script)
        self.assertIn('active?" (in progress)":""', script)
        self.assertIn('src="/history.js?v=9"', page)

    def test_serverless_docs_rewrite_production_only_routes(self):
        builder = (ROOT / "dev_setup" / "build_serverless_docs.py").read_text(encoding="utf-8")
        docs = (ROOT / "templates" / "docs.html").read_text(encoding="utf-8")
        docs_catalog = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")

        self.assertNotIn("'href=\"/laser-engraving-tool\"': 'href=\"/\"'", builder)
        self.assertNotIn("'href=\"/color-laser-engraving-tool\"'", builder)
        self.assertIn("'href=\"/color-discovery\"': 'href=\"/color-lab.html\"'", builder)
        self.assertIn("return rewrite_staging_routes(template.render(", builder)
        self.assertIn('<a href="/color-discovery">Color Lab</a>', docs)
        self.assertIn("select SVG-Only (no laser settings)", docs_catalog)
        self.assertNotIn("Choose Continue with SVG only", docs_catalog)
        self.assertNotIn("Depthmap Generator landing page", docs_catalog)
        self.assertIn("Adding surface texture with color guidance", docs_catalog)
        self.assertIn("a portrait of a woman with a sleeve tattoo containing red diamonds", docs_catalog)
        self.assertIn("blue stars on a black background", docs_catalog)
        self.assertIn("making raised areas resemble rounded mounds", docs_catalog)

    def test_rasterizer_material_name_immediately_follows_upload_control(self):
        page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        upload_position = page.index('id="materialUpload"')
        material_position = page.index('id="materialNameField"')
        swatches_position = page.index("Raster palette swatches")

        self.assertLess(upload_position, material_position)
        self.assertLess(material_position, swatches_position)
        self.assertNotIn("colorMatchingSection", page[upload_position:material_position])
        self.assertIn('<select id="materialName" required>', page)
        self.assertIn("function setMaterialOptions(names,preferred='',placeholder='Choose a material')", page)
        self.assertIn("new DOMParser().parseFromString(await file.text(),'application/xml')", page)
        self.assertIn("setMaterialOptions(materials)", page)

    def test_cognito_managed_branding_is_reproducible(self):
        css = (ROOT / "ecs" / "cognito-staging-classic.css").read_text(encoding="utf-8")
        settings = (ROOT / "ecs" / "cognito-managed-login-settings.json").read_text(encoding="utf-8")
        branding = (ROOT / "dev_setup" / "apply_cognito_managed_branding.sh").read_text(encoding="utf-8")
        deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")

        # Retain the compact classic style as the version-1 rollback asset.
        self.assertLessEqual(len(css.encode("utf-8")), 3072)
        self.assertIn('"pageBackground"', settings)
        self.assertIn('"color": "c8c9c3ff"', settings)
        self.assertIn('"colorSchemeMode": "DYNAMIC"', settings)
        self.assertIn('"backgroundColor": "46584eff"', settings)
        self.assertIn('"textColor": "efb94fff"', settings)
        self.assertIn("--managed-login-version 2", branding)
        self.assertIn("describe-managed-login-branding-by-client", branding)
        self.assertIn("update-managed-login-branding", branding)
        self.assertIn("PRODUCTION_CLIENT_ID", branding)
        self.assertIn("apply_cognito_managed_branding.sh", deploy)
        self.assertIn('apply_cognito_managed_branding.sh" "$CLIENT_ID"', deploy)

    def test_rasterizer_ui_selects_holographic_recipes_by_index(self):
        page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        staging_css = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")
        self.assertIn("body.light-machine.staging-prototype button.color-square", page)
        self.assertIn("background:var(--swatch-color)!important", page)
        self.assertIn("body.light-machine.staging-home .filter-control", staging_css)
        self.assertIn("body.light-machine.staging-home #imageStyleSection .filter-description", staging_css)
        self.assertIn("body.light-machine.staging-vault .library-entry", staging_css)
        self.assertIn("body.light-machine.staging-vault .depth-palette-entry", staging_css)
        self.assertIn("body.light-machine.staging-vault{color-scheme:light}", staging_css)
        self.assertIn("body.light-machine.staging-color-lab .stage", staging_css)
        self.assertIn("body.light-machine.staging-color-lab button.cell-square", staging_css)
        self.assertIn("body.light-machine.staging-holographic .stage", staging_css)
        self.assertIn("body.light-machine.staging-holographic .recipe-card", staging_css)
        self.assertIn("body.light-machine.staging-depthmap .status-label", staging_css)
        self.assertIn("body.staging-depthmap button.color-square", staging_css)
        self.assertIn("body.light-machine.staging-depthmap.staging-prototype button.color-square", staging_css)
        self.assertIn("background:var(--depth-swatch-color)!important", staging_css)
        depth_js = (ROOT / "static" / "depthmap_generator.js").read_text(encoding="utf-8")
        self.assertIn('--depth-swatch-color", swatch.hex', depth_js)
        self.assertIn("selection_key:String(index)", page)
        self.assertIn("selected_holographic_recipe_indexes:selectedRecipeIndexes", page)
        self.assertIn("imageStyleSection').classList.toggle('hidden',Boolean(selectedRecipe)", page)
        self.assertNotIn("function nearestOfficialSwatch", page)

    def test_saved_palette_unassigned_swatches_cannot_leak_into_jobs(self):
        page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.assertIn("function explicitLibraryAssignments()", page)
        self.assertIn("Unassigned in the selected Swatch Palette", page)
        self.assertIn("explicitAssignments===null||Object.prototype.hasOwnProperty.call", page)
        self.assertIn('runtime_item["saved_material_library_id"] = saved_library_id', handler)
        self.assertIn("The selected Swatch Palette no longer assigns", handler)

    def test_job_history_only_displays_swatches_selected_for_the_job(self):
        history = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
        self.assertIn("parsedValue(values.selected_color_hexes)", history)
        self.assertIn("selectedHexes.has(String(color).toUpperCase())", history)

    def test_members_can_download_the_complete_saved_holographic_palette_json(self):
        script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
        self.assertIn('class="downloadRecipeJson"', script)
        self.assertIn('event.target.matches(".downloadRecipeJson")', script)
        self.assertIn('api(`/account/holographic-recipes/${recipeId}`)', script)
        self.assertIn('JSON.stringify(profile,null,2)', script)
        self.assertIn('{type:"application/json"}', script)
        self.assertIn('link.download=`${base.replace(/\\.json$/i,"")}.json`', script)
        self.assertIn("function recipeDraft(card,profile)", script)
        self.assertIn('let profile=recipeProfiles.get(recipeId)', script)
        self.assertIn("const draft=recipeDraft(card,profile);downloadJson(draft,draft.profile_name)", script)
        self.assertIn('draft.profile_name=draftName', script)
        self.assertIn('editor.querySelector(".editRecipeName")', script)
        self.assertIn('editor.querySelectorAll("[data-recipe-setting]")', script)
        self.assertIn("Fauxlographic Palette JSON downloaded with current edits.", script)

    def test_api_routes_saved_holographic_palette_to_holographic_worker(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.assertIn('"job_type": "holographic_artwork"', handler)
        self.assertIn('"artwork_key": artwork_key', handler)
        self.assertIn('"artwork_name": payload["image_name"]', handler)
        self.assertIn('"selected_recipe_indexes": selected_recipe_indexes', handler)
        self.assertIn('runtime_item["saved_recipe_key"]', handler)

    def test_worker_uses_embedded_recipe_layers_and_selected_subset(self):
        worker = (ROOT / "worker.py").read_text(encoding="utf-8")
        exporter = (ROOT / "routes" / "holographic.py").read_text(encoding="utf-8")
        self.assertIn('selected_recipe_indexes=payload.get("selected_recipe_indexes")', worker)
        self.assertIn('embedded_material_name=payload.get("embedded_material_name")', worker)
        self.assertIn("selected_recipe_indexes=None", exporter)
        self.assertIn("embedded_material_name=None", exporter)
        self.assertIn('embedded_material_name, recipe["name"]', exporter)


if __name__ == "__main__":
    unittest.main()
