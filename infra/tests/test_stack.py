import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from classlop_infra.stack import ClasslopStack


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    stack = ClasslopStack(
        app, "Classlop", env=cdk.Environment(account="123456789012", region="eu-central-1")
    )
    return Template.from_stack(stack)


def test_destroying_the_stack_retains_nothing(template):
    for logical_id, resource in template.to_json()["Resources"].items():
        assert resource.get("DeletionPolicy", "Delete") == "Delete", logical_id
        assert resource.get("UpdateReplacePolicy", "Delete") == "Delete", logical_id


def test_bucket_is_private_and_emptied_on_destroy(template):
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {"PublicAccessBlockConfiguration": Match.object_like({"BlockPublicPolicy": True})},
    )
    template.resource_count_is("Custom::S3AutoDeleteObjects", 1)


def test_network_has_no_nat_gateway(template):
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.has_resource_properties("AWS::EC2::Subnet", {"MapPublicIpOnLaunch": True})
    template.has_resource_properties("AWS::EC2::Subnet", {"MapPublicIpOnLaunch": False})


def test_database_is_a_small_postgres_without_deletion_protection(template):
    template.has_resource_properties(
        "AWS::RDS::DBInstance",
        {
            "Engine": "postgres",
            "DBInstanceClass": "db.t4g.micro",
            "MultiAZ": False,
            "DeletionProtection": False,
            "PubliclyAccessible": False,
        },
    )
    template.has_resource("AWS::RDS::DBInstance", {"DeletionPolicy": "Delete"})


def test_search_is_one_small_opensearch_node(template):
    template.has_resource_properties(
        "AWS::OpenSearchService::Domain",
        {
            "ClusterConfig": Match.object_like(
                {"InstanceType": "t3.small.search", "InstanceCount": 1}
            ),
            "VPCOptions": Match.any_value(),
        },
    )


def test_jobs_go_to_the_dead_letter_queue_after_three_receives(template):
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {"RedrivePolicy": Match.object_like({"maxReceiveCount": 3})},
    )
    template.resource_count_is("AWS::Scheduler::ScheduleGroup", 1)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": Match.object_like(
                {
                    "Statement": Match.array_with(
                        [Match.object_like({"Principal": {"Service": "scheduler.amazonaws.com"}})]
                    )
                }
            )
        },
    )


APP_SECRETS = [
    "M365_CLIENT_SECRET",
    "LLM_API_KEY",
    "LANGSMITH_API_KEY",
    "TYPESAFE_API_KEY",
    "SESSION_KEY",
    "LLM_BASE_URL",
    "M365_TENANT_ID",
    "M365_CLIENT_ID",
    "M365_TEACHER_OID",
]


def test_app_secret_is_generated_so_deploys_never_overwrite_hand_filled_values(template):
    secret = next(
        s["Properties"]
        for s in template.find_resources("AWS::SecretsManager::Secret").values()
        if s["Properties"].get("Name") == "classlop/app"
    )
    assert "SecretString" not in secret
    generated = secret["GenerateSecretString"]
    assert generated["GenerateStringKey"] == "SESSION_KEY"
    assert set(json.loads(generated["SecretStringTemplate"])) | {"SESSION_KEY"} == set(APP_SECRETS)


def task_definitions(template) -> list[dict]:
    return list(template.find_resources("AWS::ECS::TaskDefinition").values())


def containers(template) -> dict[str, dict]:
    return {
        c["Name"]: c
        for task in task_definitions(template)
        for c in task["Properties"]["ContainerDefinitions"]
    }


def test_web_and_worker_run_on_half_a_vcpu_and_a_gigabyte(template):
    sizes = {
        (t["Properties"]["Cpu"], t["Properties"]["Memory"]) for t in task_definitions(template)
    }
    assert sizes == {("512", "1024")}
    assert {"web", "worker", "migrate"} <= containers(template).keys()
    template.resource_count_is("AWS::ECS::Service", 2)


def test_web_starts_only_after_migrate_succeeds(template):
    c = containers(template)
    assert c["migrate"]["Essential"] is False
    assert c["migrate"]["Command"] == ["classlop", "migrate"]
    assert {"ContainerName": "migrate", "Condition": "SUCCESS"} in c["web"]["DependsOn"]


def test_app_secrets_reach_every_container_as_environment_variables(template):
    for name, container in containers(template).items():
        injected = {s["Name"] for s in container.get("Secrets", [])}
        assert set(APP_SECRETS) | {"DB_PASSWORD"} <= injected, name


def test_logs_are_kept_for_one_week(template):
    groups = template.find_resources("AWS::Logs::LogGroup")
    assert groups
    for group in groups.values():
        assert group["Properties"]["RetentionInDays"] == 7


def test_load_balancer_is_reachable_only_from_cloudfront(template):
    ingress = [
        rule
        for sg in template.find_resources("AWS::EC2::SecurityGroup").values()
        for rule in sg["Properties"].get("SecurityGroupIngress", [])
    ] + [
        r["Properties"] for r in template.find_resources("AWS::EC2::SecurityGroupIngress").values()
    ]
    assert not [r for r in ingress if r.get("CidrIp") == "0.0.0.0/0"]
    assert [r for r in ingress if "SourcePrefixListId" in r]
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "DefaultCacheBehavior": Match.object_like(
                        {"ViewerProtocolPolicy": "redirect-to-https"}
                    )
                }
            )
        },
    )


def test_stack_outputs_the_sign_in_callback_url(template):
    outputs = template.find_outputs("CallbackUrl")
    assert "/auth/callback" in str(outputs)


def test_database_password_fits_a_url_unescaped(template):
    template.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {
            "Name": "classlop/db",
            "GenerateSecretString": Match.object_like(
                {"ExcludePunctuation": True, "GenerateStringKey": "password"}
            ),
        },
    )
