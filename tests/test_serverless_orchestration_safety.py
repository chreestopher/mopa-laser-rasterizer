from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]


def test_orchestration_marks_unlaunchable_jobs_failed_before_dead_lettering():
    template = (ROOT / "ecs" / "rasterizer-orchestration.yaml").read_text(
        encoding="utf-8"
    )

    assert "RuntimeTableName:" in template
    assert "Action: dynamodb:UpdateItem" in template
    assert "MarkJobFailed:" in template
    assert 'ConditionExpression: "#status = :pending"' in template
    assert 'UpdateExpression: "SET #status = :failed, error_message = :error"' in template
    assert "Next: MarkJobFailed" in template
    assert template.index("MarkJobFailed:") < template.index("SendToDlq:")


def test_staging_deployment_pauses_dispatch_across_task_revision_change():
    deploy = (ROOT / "dev_setup" / "deploy_serverless_staging.sh").read_text(
        encoding="utf-8"
    )

    stop = deploy.index("aws pipes stop-pipe")
    worker = deploy.index('aws cloudformation deploy --region "$REGION" --stack-name "$WORKER_STACK"')
    orchestration = deploy.index(
        'aws cloudformation deploy --region "$REGION" --stack-name "$ORCHESTRATION_STACK"'
    )
    start = deploy.index("aws pipes start-pipe")

    assert stop < worker < orchestration < start
    assert "aws pipes describe-pipe" in deploy
    assert '"RuntimeTableName=$RUNTIME_TABLE"' in deploy
    assert "The pipe remains STOPPED so queued jobs are preserved." in deploy


def test_staging_network_discovery_does_not_depend_on_retired_worker_stack():
    deploy = (ROOT / "dev_setup" / "deploy_serverless_staging.sh").read_text(
        encoding="utf-8"
    )

    assert 'SOURCE_WORKER_STACK="${SERVERLESS_SOURCE_WORKER_STACK:-$WORKER_STACK}"' in deploy
    assert "mopa-rasterizer-serverless-production-worker" in deploy
    assert 'FARGATE_STACK_NAME:-mopa-rasterizer-worker' not in deploy


def test_deployment_queue_acceptance_script_coordinates_pause_deploy_and_resume():
    acceptance = (
        ROOT / "dev_setup" / "test_serverless_staging_deployment_queue.sh"
    ).read_text(encoding="utf-8")

    stop = acceptance.index("aws pipes stop-pipe")
    submit = acceptance.index('bash "$SCRIPT_DIR/test_serverless_staging_job.sh"')
    assert_pending = acceptance.index('queued_status" = "pending"')
    deploy = acceptance.index('bash "$SCRIPT_DIR/deploy_serverless_staging.sh"')
    start = acceptance.index("aws pipes start-pipe", deploy)
    complete = acceptance.index('wait "$smoke_pid"', start)

    assert stop < submit < assert_pending < deploy < start < complete
    assert "SERVERLESS_STAGING_QUEUE_TEST_REQUIRE_REVISION_CHANGE" in acceptance
    assert "staging dispatch remains STOPPED so the queued job is preserved" in acceptance


def test_staging_smoke_fixture_is_self_contained_and_multicolor():
    fixture = ElementTree.parse(ROOT / "dev_setup" / "serverless-staging-smoke.clb")
    material = fixture.getroot().find("Material")

    assert material is not None
    assert material.get("name") == "staging-smoke"
    assert [entry.get("Desc") for entry in material.findall("Entry")] == [
        "Black",
        "Red",
    ]


def test_direct_dispatch_uses_six_state_happy_path_and_requeues_paused_jobs():
    template = (ROOT / "ecs" / "rasterizer-orchestration.yaml").read_text(
        encoding="utf-8"
    )
    assert "DetectMessageShape:" not in template
    assert "SetDirectTaskId:" not in template
    assert "SplitDispatchKey:" not in template
    assert "SetTaskId:" not in template
    assert "message.$: States.StringToJson($[0].body)" in template
    assert "RequeuePausedJob:" in template
    assert "SqsQueueUrl:" in template
    assert "Resource: [!Ref SqsQueueArn, !Ref SqsDlqArn]" in template
    assert "JobDeferred:" in template


def test_production_deployment_retires_legacy_s3_dispatch_notification():
    legacy_deploy = (ROOT / "dev_setup" / "deploy_fargate_worker_production.sh").read_text(
        encoding="utf-8"
    )
    serverless_deploy = (ROOT / "dev_setup" / "deploy_serverless_production.sh").read_text(
        encoding="utf-8"
    )
    removal = (ROOT / "dev_setup" / "remove-s3-fargate-dispatch.sh").read_text(
        encoding="utf-8"
    )
    assert 'remove-s3-fargate-dispatch.sh' in legacy_deploy
    assert 'ensure-s3-fargate-dispatch.sh' not in legacy_deploy
    assert 'remove-s3-fargate-dispatch.sh' in serverless_deploy
    assert 'mopa-raster-fargate-dispatch' in removal
    assert 'item for item in queues if item.get("Id") !=' in removal
