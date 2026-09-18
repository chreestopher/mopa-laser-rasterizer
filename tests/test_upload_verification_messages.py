"""Keep upload validation actionable without exposing private storage keys."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ClientError(Exception):
    pass


def load_upload_validator(name, head=None, error=None):
    source = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)

    def head_object(**_kwargs):
        if error:
            raise error
        return head

    namespace = {"s3": SimpleNamespace(head_object=head_object), "BUCKET": "test", "ClientError": ClientError}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "handler.py", "exec"), namespace)
    return namespace[name]


class UploadVerificationMessageTests(unittest.TestCase):
    def test_missing_object_does_not_disclose_storage_key(self):
        verify = load_upload_validator("verify_upload", error=ClientError("missing"))
        with self.assertRaisesRegex(ValueError, "^We couldn't access the uploaded file.*Select it again and retry") as raised:
            verify("jobs/private/inputs/artwork.png", "digest", 10 * 1024 * 1024)
        self.assertNotIn("jobs/", str(raised.exception))

    def test_empty_upload_has_specific_message(self):
        verify = load_upload_validator("verify_upload", head={"ContentLength": 0, "Metadata": {"upload-capability": "digest"}})
        with self.assertRaisesRegex(ValueError, "^The uploaded file is empty.*Choose a nonempty file"):
            verify("jobs/id/inputs/artwork.png", "digest", 10 * 1024 * 1024)

    def test_oversized_upload_includes_limit(self):
        verify = load_upload_validator("verify_upload", head={"ContentLength": 11 * 1024 * 1024, "Metadata": {"upload-capability": "digest"}})
        with self.assertRaisesRegex(ValueError, "^The uploaded file exceeds the 10 MB limit.*Choose a smaller file"):
            verify("jobs/id/inputs/artwork.png", "digest", 10 * 1024 * 1024)

    def test_upload_capability_mismatch_explains_recovery(self):
        verify = load_upload_validator("verify_upload", head={"ContentLength": 42, "Metadata": {"upload-capability": "older"}})
        with self.assertRaisesRegex(ValueError, "no longer matches this request.*retry to start a fresh upload"):
            verify("jobs/id/inputs/artwork.png", "digest", 100)

    def test_valid_upload_returns_metadata(self):
        head = {"ContentLength": 42, "Metadata": {"upload-capability": "digest"}}
        self.assertIs(load_upload_validator("verify_upload", head=head)("jobs/id/inputs/artwork.png", "digest", 100), head)

    def test_saved_material_library_size_messages(self):
        key = "users/owner/materials/library/file.clb"
        empty = load_upload_validator("verify_saved_material", head={"ContentLength": 0})
        with self.assertRaisesRegex(ValueError, "saved Material Library is empty"):
            empty(key, "owner", 10 * 1024 * 1024)

        oversized = load_upload_validator("verify_saved_material", head={"ContentLength": 11 * 1024 * 1024})
        with self.assertRaisesRegex(ValueError, "exceeds the 10 MB limit"):
            oversized(key, "owner", 10 * 1024 * 1024)

    def test_saved_material_library_account_message(self):
        verify = load_upload_validator("verify_saved_material", head={"ContentLength": 42})
        with self.assertRaisesRegex(ValueError, "Check that you're signed into the right account"):
            verify("users/another-account/materials/library/file.clb", "owner", 100)

    def test_saved_material_library_access_error_does_not_assume_file_is_missing(self):
        verify = load_upload_validator("verify_saved_material", error=ClientError("AccessDenied"))
        with self.assertRaisesRegex(ValueError, "We couldn't access the saved Material Library") as raised:
            verify("users/owner/materials/library/file.clb", "owner", 100)
        self.assertNotIn("missing", str(raised.exception))

    def test_saved_fauxlographic_palette_account_message(self):
        verify = load_upload_validator("verify_saved_recipe", head={"ContentLength": 42})
        with self.assertRaisesRegex(ValueError, "choose another palette"):
            verify("users/another-account/holographic-recipes/palette/file.json", "owner", 100)

    def test_saved_fauxlographic_palette_access_error_does_not_assume_file_is_missing(self):
        verify = load_upload_validator("verify_saved_recipe", error=ClientError("AccessDenied"))
        with self.assertRaisesRegex(ValueError, "We couldn't access the saved Fauxlographic Palette") as raised:
            verify("users/owner/holographic-recipes/palette/file.json", "owner", 100)
        self.assertNotIn("missing", str(raised.exception))

    def test_saved_fauxlographic_palette_size_messages(self):
        key = "users/owner/holographic-recipes/palette/file.json"
        empty = load_upload_validator("verify_saved_recipe", head={"ContentLength": 0})
        with self.assertRaisesRegex(ValueError, "saved Fauxlographic Palette is empty"):
            empty(key, "owner", 10 * 1024 * 1024)

        oversized = load_upload_validator("verify_saved_recipe", head={"ContentLength": 11 * 1024 * 1024})
        with self.assertRaisesRegex(ValueError, "exceeds the 10 MB limit"):
            oversized(key, "owner", 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
