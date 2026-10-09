from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, SecretValue, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_opensearchservice as opensearch
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct

APP_SECRETS = [
    "M365_CLIENT_SECRET",
    "LLM_API_KEY",
    "LANGSMITH_API_KEY",
    "TYPESAFE_API_KEY",
    "SESSION_KEY",
]


class ClasslopStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Tasks get public IPs instead of a NAT gateway; RDS and OpenSearch stay isolated.
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC),
                ec2.SubnetConfiguration(
                    name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
                ),
            ],
        )

        isolated = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        self.tasks_sg = ec2.SecurityGroup(self, "Tasks", vpc=vpc)
        data_sg = ec2.SecurityGroup(self, "Data", vpc=vpc, allow_all_outbound=False)
        data_sg.add_ingress_rule(self.tasks_sg, ec2.Port.tcp(5432), "Postgres from tasks")
        data_sg.add_ingress_rule(self.tasks_sg, ec2.Port.tcp(443), "OpenSearch from tasks")

        self.bucket = s3.Bucket(
            self,
            "Files",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Letters and digits only, so the password drops into DATABASE_URL unescaped.
        db_secret = secretsmanager.Secret(
            self,
            "DatabaseSecret",
            secret_name="classlop/db",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "classlop"}',
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=32,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.database = rds.DatabaseInstance(
            self,
            "Database",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_17),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=isolated,
            security_groups=[data_sg],
            database_name="classlop",
            credentials=rds.Credentials.from_secret(db_secret),
            allocated_storage=20,
            multi_az=False,
            deletion_protection=False,
            storage_encrypted=True,
            delete_automated_backups=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.search = opensearch.Domain(
            self,
            "Search",
            version=opensearch.EngineVersion.OPENSEARCH_2_19,
            capacity=opensearch.CapacityConfig(
                data_nodes=1,
                data_node_instance_type="t3.small.search",
                multi_az_with_standby_enabled=False,
            ),
            ebs=opensearch.EbsOptions(volume_size=10, volume_type=ec2.EbsDeviceVolumeType.GP3),
            vpc=vpc,
            vpc_subnets=[ec2.SubnetSelection(subnets=[vpc.isolated_subnets[0]])],
            security_groups=[data_sg],
            zone_awareness=opensearch.ZoneAwarenessConfig(enabled=False),
            enforce_https=True,
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Reachable only inside the VPC through data_sg, so requests need no signing.
        self.search.add_access_policies(
            iam.PolicyStatement(
                principals=[iam.AnyPrincipal()],
                actions=["es:ESHttp*"],
                resources=[f"{self.search.domain_arn}/*"],
            )
        )

        dlq = sqs.Queue(
            self, "JobsDlq", queue_name="classlop-jobs-dlq", removal_policy=RemovalPolicy.DESTROY
        )
        self.queue = sqs.Queue(
            self,
            "Jobs",
            queue_name="classlop-jobs",
            visibility_timeout=Duration.seconds(60),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3),
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Deleting the group deletes the schedules the app created in it at runtime.
        self.schedule_group = scheduler.ScheduleGroup(
            self, "Schedules", schedule_group_name="classlop", removal_policy=RemovalPolicy.DESTROY
        )
        self.schedule_role = iam.Role(
            self, "ScheduleRole", assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com")
        )
        self.queue.grant_send_messages(self.schedule_role)

        # Filled by hand with `aws secretsmanager put-secret-value`; the keys exist from the
        # start so the tasks can boot before that.
        app_secret = secretsmanager.Secret(
            self,
            "AppSecret",
            secret_name="classlop/app",
            secret_object_value={k: SecretValue.unsafe_plain_text("") for k in APP_SECRETS},
            removal_policy=RemovalPolicy.DESTROY,
        )

        # The edge comes before the tasks so they can be told their public URL.
        alb_sg = ec2.SecurityGroup(self, "LoadBalancerSg", vpc=vpc)
        cloudfront_ips = ec2.PrefixList.from_lookup(
            self,
            "CloudFrontOrigins",
            prefix_list_name="com.amazonaws.global.cloudfront.origin-facing",
        )
        alb_sg.add_ingress_rule(
            ec2.Peer.prefix_list(cloudfront_ips.prefix_list_id), ec2.Port.tcp(80), "CloudFront only"
        )
        alb = elbv2.ApplicationLoadBalancer(
            self, "LoadBalancer", vpc=vpc, internet_facing=True, security_group=alb_sg
        )
        listener = alb.add_listener("Http", port=80, open=False)
        distribution = cloudfront.Distribution(
            self,
            "Cdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    alb, protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
            ),
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
        )
        public_url = f"https://{distribution.distribution_domain_name}"

        repo_root = Path(__file__).resolve().parents[2]
        image = ecs.ContainerImage.from_asset(
            str(repo_root),
            platform=ecr_assets.Platform.LINUX_AMD64,
            exclude=["infra", ".claude", "docs", "prototypes", "scripts", ".github"],
        )
        logs_group = logs.LogGroup(
            self,
            "Logs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        db_host = self.database.db_instance_endpoint_address
        # The password arrives as its own secret; the app reads one DATABASE_URL.
        entry_point = [
            "sh",
            "-c",
            'export DATABASE_URL="postgresql+psycopg://classlop:$DB_PASSWORD@'
            + db_host
            + ':5432/classlop" && exec "$@"',
            "sh",
        ]
        environment = {
            "AWS_REGION": self.region,
            "OPENSEARCH_URL": f"https://{self.search.domain_endpoint}",
            "S3_BUCKET": self.bucket.bucket_name,
            "JOBS_QUEUE": self.queue.queue_name,
            "JOBS_DLQ": dlq.queue_name,
            "JOBS_QUEUE_ARN": self.queue.queue_arn,
            "SCHEDULE_GROUP": "classlop",
            "SCHEDULE_ROLE_ARN": self.schedule_role.role_arn,
            "PUBLIC_URL": public_url,
        }
        secrets = {
            "DB_PASSWORD": ecs.Secret.from_secrets_manager(self.database.secret, "password"),
            **{k: ecs.Secret.from_secrets_manager(app_secret, k) for k in APP_SECRETS},
        }

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        def task(name: str) -> ecs.FargateTaskDefinition:
            definition = ecs.FargateTaskDefinition(
                self, f"{name.title()}Task", cpu=512, memory_limit_mib=1024
            )
            self.bucket.grant_read_write(definition.task_role)
            self.queue.grant_send_messages(definition.task_role)
            self.queue.grant_consume_messages(definition.task_role)
            dlq.grant_consume_messages(definition.task_role)
            self.schedule_role.grant_pass_role(definition.task_role)
            definition.task_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=[
                        "scheduler:CreateSchedule",
                        "scheduler:UpdateSchedule",
                        "scheduler:DeleteSchedule",
                        "scheduler:GetSchedule",
                    ],
                    resources=[
                        self.format_arn(
                            service="scheduler", resource="schedule", resource_name="classlop/*"
                        )
                    ],
                )
            )
            return definition

        def container(definition: ecs.FargateTaskDefinition, name: str, **kwargs):
            return definition.add_container(
                name,
                container_name=name,
                image=image,
                entry_point=entry_point,
                command=["classlop", name],
                environment=environment,
                secrets=secrets,
                logging=ecs.LogDrivers.aws_logs(stream_prefix=name, log_group=logs_group),
                **kwargs,
            )

        web_task = task("web")
        migrate = container(web_task, "migrate", essential=False)
        web = container(web_task, "web", port_mappings=[ecs.PortMapping(container_port=8000)])
        web.add_container_dependencies(
            ecs.ContainerDependency(
                container=migrate, condition=ecs.ContainerDependencyCondition.SUCCESS
            )
        )
        worker_task = task("worker")
        container(worker_task, "worker")
        self.worker_task = worker_task

        public = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        web_service = ecs.FargateService(
            self,
            "Web",
            cluster=cluster,
            task_definition=web_task,
            assign_public_ip=True,
            vpc_subnets=public,
            security_groups=[self.tasks_sg],
            health_check_grace_period=Duration.minutes(3),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=100,
        )
        ecs.FargateService(
            self,
            "Worker",
            cluster=cluster,
            task_definition=worker_task,
            assign_public_ip=True,
            vpc_subnets=public,
            security_groups=[self.tasks_sg],
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=0,
        )
        listener.add_targets(
            "Web",
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[web_service],
            health_check=elbv2.HealthCheck(path="/healthz"),
            deregistration_delay=Duration.seconds(10),
        )

        CfnOutput(self, "Url", value=public_url)
        CfnOutput(
            self,
            "CallbackUrl",
            value=f"{public_url}/auth/callback",
            description="Add once as a Web redirect URI of the app registration in Entra",
        )
        CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        CfnOutput(self, "WorkerTaskDefinition", value=worker_task.task_definition_arn)
        CfnOutput(
            self,
            "PublicSubnets",
            value=",".join(s.subnet_id for s in vpc.public_subnets),
        )
        CfnOutput(self, "TasksSecurityGroup", value=self.tasks_sg.security_group_id)
