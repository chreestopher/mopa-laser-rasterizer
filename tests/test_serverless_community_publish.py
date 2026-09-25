import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerlessCommunityPublishTests(unittest.TestCase):
    def setUp(self):
        self.handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.services = (ROOT / "services.py").read_text(encoding="utf-8")
        self.copy_script = (ROOT / "dev_setup" / "copy_user_data_to_serverless_staging.py").read_text(encoding="utf-8")
        self.page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        self.client = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
        self.infrastructure = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")

    def test_api_and_browser_sources_parse(self):
        ast.parse(self.handler)
        self.assertIn('RouteKey: POST /account/community-set', self.infrastructure)
        self.assertIn('path == "/account/community-set"', self.handler)
        self.assertIn('api("/account/community-set"', self.client)

    def test_modal_requires_machine_and_lens_and_selects_swatches(self):
        self.assertIn('id="communityPublishPanel"', self.page)
        self.assertIn('id="communityLaser" maxlength="160" required', self.page)
        self.assertIn('id="communityLens" maxlength="160" required', self.page)
        self.assertIn('id="communityNotes" maxlength="1000"', self.page)
        self.assertIn('data-community-index=', self.client)
        self.assertIn('input:not(:disabled)', self.client)
        self.assertIn('selected_indexes:selectedIndexes', self.client)
        self.assertIn('Laser Model / Source is required', self.handler)
        self.assertIn('Lens is required', self.handler)

    def test_existing_palette_metadata_prefills_but_remains_editable(self):
        for field in ('"laser_source": str(item.get("laser_source")',
                      '"lens_field_of_view": str(item.get("lens_field_of_view")',
                      '"notes": str(item.get("notes")'):
            self.assertIn(field, self.handler)
        self.assertIn('#communityLaser").value=item.laser_source', self.client)
        self.assertIn('#communityLens").value=item.lens_field_of_view', self.client)
        self.assertIn('#communityNotes").value=item.notes', self.client)
        self.assertIn('UpdateExpression="SET laser_source=:laser, lens_field_of_view=:lens, notes=:notes', self.handler)

    def test_publication_is_anonymous_and_does_not_copy_private_identifiers(self):
        function = self.handler[
            self.handler.index("def publish_community_palette(event):"):
            self.handler.index("def community_settings(event):")
        ]
        public_write = function[function.index('table.put_item(Item={'):function.index('private_key = {')]
        self.assertIn('publication_id = str(uuid.uuid4())', function)
        self.assertNotIn('f"{owner}', public_write)
        self.assertNotIn('source_id', public_write)
        self.assertNotIn('palette_name', public_write)
        self.assertNotIn('s3_key', public_write)
        self.assertNotIn('user_id', public_write)

    def test_only_checked_public_columns_are_written(self):
        self.assertIn('COMMUNITY_PUBLIC_SETTING_FIELDS = (', self.handler)
        for field in ("speed", "minPower", "maxPower", "frequency", "QPulseWidth",
                      "interval", "angle", "numPasses", "crossHatch", "type"):
            self.assertIn(f'"{field}"', self.handler)
        definition = self.handler[
            self.handler.index("COMMUNITY_PUBLIC_SETTING_FIELDS = ("):
            self.handler.index("def community_public_settings")
        ]
        for private_field in ("overscan", "priority", "tabsEnabled", "hide", "LinkPath"):
            self.assertNotIn(f'"{private_field}"', definition)

    def test_every_community_storage_path_strips_private_lightburn_metadata(self):
        ast.parse(self.services)
        ast.parse(self.copy_script)
        self.assertIn("def _community_public_settings(settings):", self.services)
        self.assertIn('"settings": _community_public_settings(entry.get("settings"))', self.services)
        community_writer = self.services[
            self.services.index("def _write_laser_community_record"):
            self.services.index("def rename_user_material_library")
        ]
        self.assertNotIn("LASER_COMMUNITY_SETTINGS", community_writer)
        self.assertNotIn("LASER_COMMUNITY_COLOR_INDEX", community_writer)
        self.assertIn("def compact_community_item(item):", self.copy_script)
        self.assertIn("compact_community_item(item)", self.copy_script)

    def test_new_publications_skip_existing_cut_parameter_duplicates(self):
        self.assertIn("def community_setting_identity", self.handler)
        self.assertIn("def existing_community_setting_identities", self.handler)
        self.assertIn("identity in existing_identities or identity in submitted_identities", self.handler)
        self.assertIn('"duplicate_count": duplicate_count', self.handler)

    def test_only_color_palette_cards_expose_community_action(self):
        self.assertIn('data-community-kind="material"', self.client)
        self.assertIn('communityButton=hatch||processing?"":', self.client)
        self.assertNotIn('data-community-kind="recipe"', self.client)
        self.assertNotIn('data-community-kind="depth"', self.client)
        self.assertIn('if source_kind != "material":', self.handler)
        self.assertIn('if material_library_intent(source.get("library_intent")) != "color_palette":', self.handler)
        self.assertGreaterEqual(self.handler.count('Only Color Palettes can be added to Community Set'), 2)


if __name__ == "__main__":
    unittest.main()
