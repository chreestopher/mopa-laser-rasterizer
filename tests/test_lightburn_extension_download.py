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
