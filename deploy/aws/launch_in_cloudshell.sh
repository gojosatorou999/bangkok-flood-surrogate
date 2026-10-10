#!/usr/bin/env bash
# Launches the whole backend on one GPU instance. Run it in AWS CloudShell (the >_ icon in the AWS console's top bar):
#
#   curl -fsSL https://raw.githubusercontent.com/gojosatorou999/bangkok-flood-surrogate/main/deploy/aws/launch_in_cloudshell.sh | bash
#
# Optional: INSTANCE_TYPE=g5.xlarge (faster, dearer). Needs the "Running On-Demand G and VT instances" vCPU quota to be >= 4
# (Service Quotas > EC2); new accounts start at 0, so request it first or the launch is refused.
set -euo pipefail

TYPE="${INSTANCE_TYPE:-g4dn.xlarge}"
AMI_PARAM="/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id"
USERDATA_URL="https://raw.githubusercontent.com/gojosatorou999/bangkok-flood-surrogate/main/deploy/aws/userdata_single_gpu.sh"

echo "region: $(aws configure get region 2>/dev/null || echo "${AWS_REGION:-?}")  type: $TYPE"
VPC="$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
[ "$VPC" != "None" ] || { echo "no default VPC in this region: create one (VPC console > Actions > Create default VPC) and retry"; exit 1; }

SG="$(aws ec2 create-security-group --group-name "flood-api-$RANDOM" --description "flood api: https only" --vpc-id "$VPC" --query GroupId --output text)"
aws ec2 authorize-security-group-ingress --group-id "$SG" \
  --ip-permissions 'IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]' \
                   'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]' >/dev/null

curl -fsSL "$USERDATA_URL" -o /tmp/userdata.sh

IID="$(aws ec2 run-instances \
  --image-id "resolve:ssm:$AMI_PARAM" --instance-type "$TYPE" --security-group-ids "$SG" \
  --user-data file:///tmp/userdata.sh \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=flood-api}]' \
  --query 'Instances[0].InstanceId' --output text)"
echo "instance: $IID (waiting for it to run)"
aws ec2 wait instance-running --instance-ids "$IID"

ALLOC="$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)"
aws ec2 associate-address --instance-id "$IID" --allocation-id "$ALLOC" >/dev/null
IP="$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)"

cat <<EOF

================================================================
 Backend launched.  Instance $IID   IP $IP
 API address (use this in Vercel as FD_API_BASE):

     https://${IP//./-}.nip.io

 First boot installs everything: allow about 10-15 minutes, then the
 first NOAA forecast needs another ~2 minutes. Check:

     curl https://${IP//./-}.nip.io/api/dash/health

 (until it answers, the page just shows the loading message)
================================================================
EOF
