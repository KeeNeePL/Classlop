import os

import aws_cdk as cdk

from classlop_infra.stack import ClasslopStack

app = cdk.App()
ClasslopStack(
    app,
    "Classlop",
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="eu-central-1"),
)
app.synth()
