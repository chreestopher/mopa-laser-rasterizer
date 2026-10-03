from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_all_job_history_writers_attach_seven_day_expiry():
    services = read("services.py")
    handler = read("serverless_api/handler.py")

    service_writer = services[services.index("def record_user_job("):services.index("def get_job_record(")]
    assert service_writer.count('"expires_at": created_at + HISTORY_TTL_SECONDS') == 2

    holographic_writer = handler[handler.index("def submit_holographic_job("):handler.index("def dynamo_value(")]
    assert holographic_writer.count('"expires_at": now + TTL_SECONDS') >= 2

    raster_writer = handler[handler.index("history = {", handler.index("def submit_job(")):handler.index("sqs.send_message", handler.index("def submit_job("))]
    assert '"expires_at": now + TTL_SECONDS' in raster_writer


def test_saved_asset_writers_do_not_attach_ttl():
    services = read("services.py")
    handler = read("serverless_api/handler.py")

    durable_service_section = services[services.index("def save_user_material_library("):services.index("def record_user_job(")]
    durable_handler_section = handler[handler.index("def edit_material_entry("):handler.index("def holographic_svg_grid(")]
    durable_handler_section += handler[handler.index("def save_measured_holographic_recipe("):handler.index("def holographic_recipe_detail(")]

    assert "expires_at" not in durable_service_section
    assert "expires_at" not in durable_handler_section


def test_signed_in_color_discovery_grids_are_durable():
    handler = read("serverless_api/handler.py")
    writer = handler[handler.index("elif guest:", handler.index("def create_color_discovery_grid(")):handler.index("downloads={", handler.index("def create_color_discovery_grid("))]

    assert '"sk":f"COLORDISCOVERY#{grid_id}"' in writer
    assert '"expires_at":now+TTL_SECONDS' not in writer
    assert 'UpdateExpression="REMOVE expires_at"' in handler


def test_backfill_targets_jobs_not_saved_assets():
    backfill = read("dev_setup/backfill_dynamodb_job_ttl.py")

    assert 'pk.startswith("JOB#")' in backfill
    assert 'pk.startswith("USER#") and sk.startswith("JOB#")' in backfill
    assert 'pk == "ADMIN#JOBS"' in backfill
    assert "MATERIAL#" not in backfill
    assert "DEPTHPALETTE#" not in backfill
    assert "HOLORECIPE#" not in backfill
    assert "COLORDISCOVERY#" not in backfill


def test_production_migrates_legacy_color_grids_before_durable_ttl_guard():
    deploy = read("dev_setup/deploy_serverless_production.sh")
    migration = read("dev_setup/make_color_discovery_grids_durable.py")

    assert deploy.index("make_color_discovery_grids_durable.py") < deploy.index("ensure_dynamodb_job_ttl.sh")
    assert 'begins_with(#pk,:user) AND begins_with(#sk,:grid)' in migration
    assert '"COLORDISCOVERY#"' in migration
    assert '"REMOVE expires_at"' in migration


def test_staging_web_deploy_migrates_legacy_color_grids_before_serving_the_feature():
    deploy = read("dev_setup/deploy_serverless_staging_web.sh")

    assert deploy.index("make_color_discovery_grids_durable.py") < deploy.index('cp "$REPO_ROOT/serverless_api/handler.py"')
    assert '--table "$TABLE" --region "$REGION" --apply' in deploy
