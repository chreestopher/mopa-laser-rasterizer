#!/bin/bash

# ==============================================================================
# CONFIGURATION - CHANGE THESE VALUES
# ==============================================================================
BUCKET_NAME="mopa-laser-rasterizer.com"
REGION="us-east-1"
POLICY_NAME="FlaskS3AccessPolicy"

# ==============================================================================
# VALIDATION
# ==============================================================================
if [ $# -eq 0 ]; then
    echo "❌ Error: Please provide a space-separated list of EC2 Instance IDs."
    echo "Usage: $0 i-1234567890abcdef0 i-abcdef1234567890"
    exit 1
fi

echo "🚀 Starting deployment workflow for S3 bucket storage initialization..."

# ==============================================================================
# STEP 1: CREATE THE S3 BUCKET
# ==============================================================================
echo "----------------------------------------"
echo "📦 Step 1: Provisioning Amazon S3 Bucket..."

# us-east-1 throws errors if CreateBucketConfiguration is explicitly passed
if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --region "$REGION"
else
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" \
        --create-bucket-configuration LocationConstraint="$REGION"
fi

if [ $? -eq 0 ]; then
    echo "✅ S3 Bucket s3://$BUCKET_NAME created successfully."
else
    echo "⚠️ S3 Bucket might already exist or creation failed. Attempting to proceed..."
fi

# ==============================================================================
# STEP 2: CREATE LOCAL IAM POLICY DOCUMENT AND DEPLOY TO AWS
# ==============================================================================
echo "----------------------------------------"
echo "📄 Step 2: Generating and Deploying IAM Policy Structure..."

POLICY_FILE="/tmp/s3_temporary_policy_doc.json"

cat <<EOF > "$POLICY_FILE"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::$BUCKET_NAME",
                "arn:aws:s3:::$BUCKET_NAME/*"
            ]
        }
    ]
}
EOF

# Create the managed policy in AWS IAM
POLICY_ARN=$(aws iam create-policy \
    --policy-name "$POLICY_NAME" \
    --policy-document file://"$POLICY_FILE" \
    --query "Policy.Arn" \
    --output text 2>/dev/null)

# Clean up local temporary file safely
rm -f "$POLICY_FILE"

# If policy already exists, fetch its existing ARN instead of failing
if [ -z "$POLICY_ARN" ]; then
    echo "ℹ️ IAM Policy '$POLICY_NAME' already exists. Fetching existing ARN..."
    # Grab your AWS Account ID dynamically to construct the ARN
    ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
    POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_NAME"
fi

echo "✅ Target Policy ARN: $POLICY_ARN"

# ==============================================================================
# STEP 3: ASSIGN NEW POLICY TO EXISTING ROLES DYNAMICALLY
# ==============================================================================
echo "----------------------------------------"
echo "🔒 Step 3: Checking Instance Profiles and Appending Permissions..."

declare -A PROCESSED_ROLES

for INSTANCE_ID in "$@"; do
    echo "  -> Analyzing EC2 target: $INSTANCE_ID"
    
    # Extract the active Instance Profile ARN assigned to this specific node
    INSTANCE_PROFILE_ARN=$(aws ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query "Reservations.Instances.IamInstanceProfile.Arn" \
        --output text 2>/dev/null)

    if [ "$INSTANCE_PROFILE_ARN" == "None" ] || [ -z "$INSTANCE_PROFILE_ARN" ]; then
        echo "  ❌ Warning: Instance $INSTANCE_ID does not have an IAM role attached. Skipping."
        continue
    fi

    # Isolate profile name from string structure
    PROFILE_NAME=$(basename "$INSTANCE_PROFILE_ARN")

    # Trace profile structural metadata down to the raw logical IAM Role Name
    ROLE_NAME=$(aws iam get-instance-profile \
        --instance-profile-name "$PROFILE_NAME" \
        --query "InstanceProfile.Roles[0].RoleName" \
        --output text 2>/dev/null)

    if [ "$ROLE_NAME" == "None" ] || [ -z "$ROLE_NAME" ]; then
        echo "  ❌ Warning: Could not locate a target active role for profile $PROFILE_NAME. Skipping."
        continue
    fi

    echo "     Found current live role: $ROLE_NAME"

    # Inject the policy attach instruction if we have not touched this role yet
    if [ -z "${PROCESSED_ROLES[$ROLE_NAME]}" ]; then
        echo "     Injecting new S3 access configurations into $ROLE_NAME..."
        aws iam attach-role-policy \
            --role-name "$ROLE_NAME" \
            --policy-arn "$POLICY_ARN"
        
        PROCESSED_ROLES[$ROLE_NAME]=1
        echo "     ✅ Appended permissions successfully without altering defaults."
    else
        echo "     ℹ️ Role $ROLE_NAME was already updated earlier during this deployment run."
    fi
done

echo "----------------------------------------"
echo "🎉 Complete! S3 backend integration infrastructure setup is finished."
