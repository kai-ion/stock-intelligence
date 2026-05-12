#!/bin/bash
set -e

# ============================================================
# Stock Intelligence Pipeline — EC2 Deployment Script
# ============================================================
# Usage:
#   ./deploy.sh --ip <EC2_IP> --key <path/to/key.pem> --email <your@email.com> --bucket <s3-bucket-name>
#
# Prerequisites:
#   - EC2 instance running Amazon Linux 2023
#   - IAM role attached with SES, S3, Bedrock permissions
#   - SES email verified
# ============================================================

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --ip) EC2_IP="$2"; shift 2;;
        --key) KEY_PATH="$2"; shift 2;;
        --email) EMAIL="$2"; shift 2;;
        --bucket) BUCKET="$2"; shift 2;;
        --region) REGION="$2"; shift 2;;
        --model) MODEL="$2"; shift 2;;
        *) echo "Unknown option: $1"; exit 1;;
    esac
done

REGION="${REGION:-us-east-1}"
MODEL="${MODEL:-us.anthropic.claude-opus-4-6-v1}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

# Validate required args
if [[ -z "$EC2_IP" || -z "$KEY_PATH" || -z "$EMAIL" || -z "$BUCKET" ]]; then
    echo "Usage: ./deploy.sh --ip <EC2_IP> --key <key.pem> --email <email> --bucket <s3-bucket>"
    echo ""
    echo "Options:"
    echo "  --ip      EC2 public IP address"
    echo "  --key     Path to SSH key (.pem)"
    echo "  --email   Email for sending/receiving reports (must be SES-verified)"
    echo "  --bucket  S3 bucket name for storing results"
    echo "  --region  AWS region (default: us-east-1)"
    echo "  --model   Bedrock model ID (default: us.anthropic.claude-opus-4-6-v1)"
    exit 1
fi

echo "============================================"
echo "  Stock Intelligence Pipeline — Deploying"
echo "============================================"
echo "  EC2:    $EC2_IP"
echo "  Email:  $EMAIL"
echo "  Bucket: $BUCKET"
echo "  Region: $REGION"
echo "  Model:  $MODEL"
echo "============================================"
echo ""

# Step 1: Install dependencies on EC2
echo "[1/5] Installing Python dependencies on EC2..."
ssh $SSH_OPTS -i "$KEY_PATH" ec2-user@"$EC2_IP" "
    sudo yum install -y python3.11 python3.11-pip cronie -q
    sudo pip3.11 install yfinance pandas requests lxml boto3 robin_stocks python-dotenv pyotp --quiet
    sudo systemctl enable crond && sudo systemctl start crond
" 2>&1 | grep -v "WARNING"

# Step 2: Create directory structure
echo "[2/5] Creating directories..."
ssh $SSH_OPTS -i "$KEY_PATH" ec2-user@"$EC2_IP" "
    mkdir -p /home/ec2-user/portfolio/data
"

# Step 3: Upload scripts
echo "[3/5] Uploading scripts..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
scp $SSH_OPTS -i "$KEY_PATH" \
    "$SCRIPT_DIR/screener.py" \
    "$SCRIPT_DIR/news_agent.py" \
    "$SCRIPT_DIR/wsb_sentiment.py" \
    "$SCRIPT_DIR/send_email.py" \
    ec2-user@"$EC2_IP":/home/ec2-user/

scp $SSH_OPTS -i "$KEY_PATH" \
    "$SCRIPT_DIR/portfolio_analysis/fetch_portfolio.py" \
    "$SCRIPT_DIR/portfolio_analysis/analyze_portfolio.py" \
    ec2-user@"$EC2_IP":/home/ec2-user/portfolio/

# Step 4: Create .env on EC2
echo "[4/5] Configuring environment..."
ssh $SSH_OPTS -i "$KEY_PATH" ec2-user@"$EC2_IP" "
    cat > /home/ec2-user/.env << EOF
EMAIL_RECIPIENT=$EMAIL
EMAIL_SENDER=$EMAIL
S3_BUCKET=$BUCKET
AWS_REGION=$REGION
MODEL_ID=$MODEL
EOF
"

# Step 5: Set up cron jobs
echo "[5/5] Setting up cron jobs..."
ssh $SSH_OPTS -i "$KEY_PATH" ec2-user@"$EC2_IP" "
    echo 'SHELL=/bin/bash
0 14 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user && python3.11 screener.py > output.log 2>&1 && python3.11 news_agent.py >> news_run.log 2>&1 && python3.11 send_email.py >> email.log 2>&1' | sudo tee /etc/cron.d/stock-screener > /dev/null

    echo 'SHELL=/bin/bash
50 13 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/portfolio && python3.11 fetch_portfolio.py > fetch.log 2>&1 && python3.11 analyze_portfolio.py >> analyze.log 2>&1' | sudo tee /etc/cron.d/portfolio-analysis > /dev/null

    sudo chmod 644 /etc/cron.d/stock-screener /etc/cron.d/portfolio-analysis
"

echo ""
echo "============================================"
echo "  Deployment complete!"
echo "============================================"
echo ""
echo "  Screener runs at 10:00 AM ET weekdays"
echo "  Portfolio analysis runs at 9:50 AM ET weekdays"
echo ""
echo "  Next steps:"
echo "  1. Verify SES email: aws ses verify-email-identity --email-address $EMAIL"
echo "  2. For portfolio bot: create /home/ec2-user/portfolio/.env with RH credentials"
echo "     then run: ssh -i $KEY_PATH ec2-user@$EC2_IP 'cd portfolio && python3.11 fetch_portfolio.py'"
echo "     and approve the device in your Robinhood app"
echo "  3. Test screener: ssh -i $KEY_PATH ec2-user@$EC2_IP 'cd /home/ec2-user && python3.11 screener.py'"
echo ""
