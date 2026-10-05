import ast
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDLER = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
HISTORY_JS = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
HISTORY_HTML = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")


def test_history_exposes_two_distinct_rerun_actions():
    assert "data-rerun-exact" in HISTORY_JS
    assert "data-rerun-current" in HISTORY_JS
    assert 'rerunJob("exact")' in HISTORY_JS
    assert 'rerunJob("current_palette")' in HISTORY_JS
    assert "Rerun exact snapshot" in HISTORY_JS
    assert "Rerun with current palette" in HISTORY_JS


def test_rerun_payload_retargets_nested_assets_and_task_identity():
    tree = ast.parse(HANDLER)
    wanted = {"safe_name", "rerun_input_destination", "replace_job_asset_keys"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {"os": os}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "handler.py", "exec"), namespace)

    old_task = "11111111-1111-1111-1111-111111111111"
    new_task = "22222222-2222-2222-2222-222222222222"
    old_key = f"jobs/{old_task}/inputs/artwork-source.png"
    new_key = namespace["rerun_input_destination"](old_key, old_task, new_task, 1)
    payload = {
        "task_id": old_task,
        "image_key": old_key,
        "nested": [{"output_name": f"output_{old_task}_source.png"}],
    }
    result = namespace["replace_job_asset_keys"](payload, {old_key: new_key}, old_task, new_task)

    assert result["task_id"] == new_task
    assert result["image_key"] == f"jobs/{new_task}/inputs/artwork-source.png"
    assert result["nested"][0]["output_name"] == f"output_{new_task}_source.png"
    assert payload["task_id"] == old_task


def test_rerun_api_is_authenticated_and_creates_a_new_task():
    assert "def rerun_account_job(event, source_task_id):" in HANDLER
    assert 'mode not in {"exact", "current_palette"}' in HANDLER
    assert 'new_task_id, now = str(uuid.uuid4()), int(time.time())' in HANDLER
    assert '"rerun_of": source_task_id' in HANDLER
    assert 'RouteKey: POST /account/jobs/{task_id}/rerun' in TEMPLATE
    assert 'parts[3] == "rerun"' in HANDLER


def test_current_palette_rerun_requires_a_durable_vault_identity():
    assert 'source_live.get("saved_material_library_id")' in HANDLER
    assert 'source_live.get("generated_recipe_id")' in HANDLER
    assert 'source_live.get("saved_holographic_recipe_id")' in HANDLER
    assert "one-off uploaded palette" in HANDLER
    assert "current_palette_available" in HANDLER


def test_saved_palettes_are_snapshotted_for_future_exact_reruns():
    assert "def snapshot_saved_input(" in HANDLER
    assert 'saved_material_key = snapshot_saved_input(' in HANDLER
    assert 'recipe_key = snapshot_saved_input(' in HANDLER
    assert 'MetadataDirective="REPLACE"' in HANDLER


def test_history_uses_new_asset_version_for_rerun_ui():
    assert '/history.js?v=11' in HISTORY_HTML
