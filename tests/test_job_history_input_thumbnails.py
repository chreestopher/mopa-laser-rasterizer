from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDLER = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
RASTERIZER = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
HISTORY_SCRIPT = (ROOT / "serverless_web" / "history.js").read_text(encoding="utf-8")
HISTORY_PAGE = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")


def test_browser_generates_and_uploads_a_bounded_job_thumbnail():
    assert "async function createJobThumbnail(file)" in RASTERIZER
    assert "const maximum=256" in RASTERIZER
    assert "canvas.toBlob(resolve,'image/webp',.8)" in RASTERIZER
    assert "thumbnail_content_type:thumbnail?.type||''" in RASTERIZER
    assert "await upload(thumbnail,grant.thumbnail);thumbnailUploaded=true" in RASTERIZER
    assert "Optional Job History thumbnail upload failed" in RASTERIZER
    assert "thumbnail_key:thumbnailUploaded?grant.thumbnail.key:''" in RASTERIZER


def test_thumbnail_upload_is_job_scoped_size_limited_and_verified():
    assert "MAX_THUMBNAIL_BYTES = 512 * 1024" in HANDLER
    assert 'task_id, "thumbnail", f"input-thumbnail.{extension}"' in HANDLER
    assert 'runtime_item["expected_thumbnail_key"] = thumbnail["key"]' in HANDLER
    assert 'thumbnail_key != str(item.get("expected_thumbnail_key") or "")' in HANDLER
    assert 'verify_upload(thumbnail_key, item["upload_capability"], MAX_THUMBNAIL_BYTES)' in HANDLER
    assert HANDLER.count('"thumbnail_key": thumbnail_key') >= 4


def test_owned_job_details_receive_only_a_short_lived_inline_thumbnail_url():
    assert 'key.startswith(f"jobs/{task_id}/inputs/thumbnail-")' in HANDLER
    assert '"ResponseContentDisposition": "inline"' in HANDLER
    assert '"thumbnail_url": input_thumbnail_url(task_id, record, history)' in HANDLER
    assert "ExpiresIn=900" in HANDLER


def test_job_history_renders_thumbnail_only_inside_expanded_details():
    assert "data-job-input-preview" in HISTORY_SCRIPT
    assert 'loading="lazy"' in HISTORY_SCRIPT
    assert "renderInputPreview(job)" in HISTORY_SCRIPT
    assert ".job-input-preview img" in HISTORY_PAGE
    assert "repeating-conic-gradient" in HISTORY_PAGE
    assert '/history.js?v=10' in HISTORY_PAGE
