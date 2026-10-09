#!/usr/bin/env bash
# Removes everything the Classlop stack put in the AWS account. Run from the repo root in Git Bash.
set -euo pipefail

CDK="npx --yes aws-cdk@2.1145.0"
REGION=eu-central-1
export AWS_REGION=$REGION

echo "Destroying the Classlop stack..."
(cd infra && $CDK destroy Classlop --force)

# Secrets deleted by CloudFormation wait 30 days; force them out now.
for secret in classlop/app classlop/db; do
  aws secretsmanager delete-secret --secret-id "$secret" --force-delete-without-recovery \
    >/dev/null 2>&1 && echo "Deleted secret $secret" || true
done

# Log groups that Lambda-backed custom resources created at runtime, outside the stack.
for group in $(aws logs describe-log-groups --log-group-name-prefix /aws/lambda/Classlop- \
  --query 'logGroups[].logGroupName' --output text); do
  aws logs delete-log-group --log-group-name "$group" && echo "Deleted log group $group"
done

read -r -p "Also empty and delete the CDKToolkit bootstrap stack (needed for any later cdk deploy)? [y/N] " answer
if [[ $answer =~ ^[Yy]$ ]]; then
  bucket=$(aws cloudformation describe-stacks --stack-name CDKToolkit \
    --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)
  repo=$(aws cloudformation describe-stack-resources --stack-name CDKToolkit \
    --query "StackResources[?ResourceType=='AWS::ECR::Repository'].PhysicalResourceId" --output text)
  [[ -n $repo ]] && aws ecr delete-repository --repository-name "$repo" --force >/dev/null
  # The bootstrap bucket is versioned: delete every version and delete marker.
  while :; do
    batch=$(aws s3api list-object-versions --bucket "$bucket" --max-items 500 --output json \
      --query '{Objects: [Versions, DeleteMarkers][][].{Key: Key, VersionId: VersionId}}')
    [[ $batch == *'"Key"'* ]] || break
    aws s3api delete-objects --bucket "$bucket" --delete "$batch" >/dev/null
  done
  aws s3api delete-bucket --bucket "$bucket"
  aws cloudformation delete-stack --stack-name CDKToolkit
  aws cloudformation wait stack-delete-complete --stack-name CDKToolkit
  echo "Deleted CDKToolkit"
fi

echo "Done. Nothing from Classlop is left in $REGION."
