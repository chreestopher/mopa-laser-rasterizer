import tempfile
import unittest
import zipfile
from pathlib import Path
from dev_setup.package_lightburn_extension import build_archive

class ExtensionDownloadTests(unittest.TestCase):
    def test_archive_contains_loadable_extension_without_local_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'extension.zip'
            build_archive(archive)
            with zipfile.ZipFile(archive) as package:
                names=package.namelist()
                self.assertIn('mopa-lightburn-extension-beta/manifest.json',names)
                self.assertIn('mopa-lightburn-extension-beta/background.js',names)
                self.assertIn('mopa-lightburn-extension-beta/console.html',names)
                self.assertFalse(any('..' in name or '.env' in name or 'node_modules' in name for name in names))
                self.assertEqual(package.testzip(),None)
    def test_guide_is_linked_and_deployment_publishes_archive(self):
        root=Path(__file__).resolve().parents[1]
        page=(root/'serverless_web/lightburn-extension.html').read_text(encoding="utf-8")
        self.assertIn('/downloads/mopa-lightburn-extension-beta.zip',page)
        for phrase in ['chrome://extensions','edge://extensions','Load unpacked','Developer mode','Pair with LightBurn','staging','Processing','100 MiB']:
            self.assertIn(phrase,page)
        self.assertIn('/lightburn-extension.html',(root/'serverless_web/index.html').read_text(encoding="utf-8"))
        script=(root/'dev_setup/deploy_serverless_staging_web.sh').read_text(encoding="utf-8")
        self.assertIn('package_lightburn_extension.py',script)
        self.assertIn('web/downloads/mopa-lightburn-extension-beta.zip',script)

    def test_environment_packages_restrict_all_runtime_origins(self):
        import json
        for environment, origin in [('staging', 'https://serverless-staging.mopa-laser-rasterizer.com'), ('production', 'https://mopa-laser-rasterizer.com')]:
            with tempfile.TemporaryDirectory() as directory:
                archive = build_archive(Path(directory)/'extension.zip', origin, environment)
                with zipfile.ZipFile(archive) as package:
                    prefix = 'mopa-lightburn-extension-beta/'
                    manifest = json.loads(package.read(prefix+'manifest.json'))
                    self.assertEqual(manifest['externally_connectable']['matches'], [origin+'/*'])
                    self.assertTrue(all(match.startswith(origin+'/') for item in manifest['content_scripts'] for match in item['matches']))
                    self.assertEqual('Development' in manifest['name'], environment == 'staging')
                    for filename in ['bridge-protocol.js', 'background.js']:
                        source = package.read(prefix+filename).decode()
                        self.assertIn(origin, source)
                        if environment == 'production':
                            self.assertNotIn('serverless-staging.mopa-laser-rasterizer.com', source)
                from dev_setup.package_lightburn_extension import build_guide
                guide = build_guide(origin, environment)
                self.assertIn(origin+'/vault.html', guide)
                self.assertIn(manifest['name'], guide)
                if environment == 'production':
                    self.assertNotIn('staging Rasterizer', guide)
                    self.assertNotIn('on staging', guide)

    def test_invalid_target_is_rejected(self):
        for origin in ['http://example.com', 'https://example.com/path', 'https://example.com?x=1']:
            with self.assertRaises(ValueError):
                build_archive('unused.zip', origin, 'production')
