# Stock Intelligence Pipeline — Full Setup Guide

This document contains everything needed to rebuild the entire pipeline from scratch. Give this to Claude Code and it can set everything up on a new EC2 instance.

## Infrastructure Required

- **AWS Account** with EC2, SES, S3, Bedrock access
- **EC2**: t2.micro (or larger), Amazon Linux 2023, us-east-1
- **S3 Bucket**: for results storage
- **IAM Role** on EC2: SES SendEmail, S3 read/write, Bedrock InvokeModel
- **IAM User** (for local sync): permanent access keys, S3 read + PutObject on wsb/ prefix
- **SES**: verified sender email
- **Robinhood account**: for portfolio bot (optional)

## EC2 Setup Steps

### 1. Launch and configure EC2

```bash
# Launch t2.micro with Amazon Linux 2023
# Attach IAM role with: ses:SendEmail, s3:*, bedrock:InvokeModel
# Security group: allow SSH (port 22)
# Create key pair for SSH access
```

### 2. Install dependencies

```bash
sudo yum install -y python3.11 python3.11-pip cronie git
sudo pip3.11 install yfinance pandas requests lxml boto3 robin_stocks python-dotenv pyotp beautifulsoup4
sudo systemctl enable crond && sudo systemctl start crond
```

### 3. Create .env file

```bash
cat > /home/ec2-user/.env << 'EOF'
export EMAIL_RECIPIENT=your_email@gmail.com
export EMAIL_SENDER=your_email@gmail.com
export S3_BUCKET=your-bucket-name
export AWS_REGION=us-east-1
export MODEL_ID=us.anthropic.claude-opus-4-6-v1
EOF
```

### 4. Deploy scripts

Upload these files to `/home/ec2-user/`:
- `screener.py` — stock screener (2700 US stocks, momentum/EMA/volume)
- `news_agent.py` — fetches technicals, news, WSB, earnings reactions, comps → Claude brief
- `wsb_sentiment.py` — ApeWisdom API for WSB trending tickers
- `financial_skills.py` — peer comps and valuation data
- `send_email.py` — HTML email + S3 upload

Upload to `/home/ec2-user/portfolio/`:
- `fetch_portfolio.py` — Robinhood holdings via robin_stocks
- `analyze_portfolio.py` — Claude analyzes positions with fib levels

Upload to `/home/ec2-user/trump_alert/`:
- `monitor.py` — polls Telegram + White House for market-moving statements

Upload to `/home/ec2-user/paper_trading/`:
- `simulator.py` — buys Claude's picks, auto-exits at targets/stops
- `generate_chart.py` — SVG equity curve

Upload to `/home/ec2-user/events/`:
- `weekly_report.py` — Monday earnings/economic/IPO preview

### 5. Create directories

```bash
mkdir -p /home/ec2-user/portfolio/data
mkdir -p /home/ec2-user/trump_alert/data
mkdir -p /home/ec2-user/paper_trading/data
mkdir -p /home/ec2-user/events/data
```

### 6. Set up cron jobs

```bash
# Stock Screener — 9:45 AM ET (13:45 UTC)
echo 'SHELL=/bin/bash
45 13 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user && python3.11 screener.py > /home/ec2-user/output.log 2>&1 && python3.11 news_agent.py >> /home/ec2-user/news_run.log 2>&1 && python3.11 send_email.py >> /home/ec2-user/email.log 2>&1' | sudo tee /etc/cron.d/stock-screener

# Portfolio Analysis — 9:50 AM ET (13:50 UTC) + 5 PM EOD (21:00 UTC) + weekend keep-alive
echo 'SHELL=/bin/bash
50 13 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/portfolio && python3.11 fetch_portfolio.py > /home/ec2-user/portfolio/fetch.log 2>&1 && python3.11 analyze_portfolio.py >> /home/ec2-user/portfolio/analyze.log 2>&1
0 21 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/portfolio && python3.11 fetch_portfolio.py > /home/ec2-user/portfolio/fetch_eod.log 2>&1
0 14 * * 0,6 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/portfolio && python3.11 fetch_portfolio.py > /home/ec2-user/portfolio/fetch.log 2>&1' | sudo tee /etc/cron.d/portfolio-analysis

# Paper Trading — 10:02 AM + 3:55 PM ET
echo 'SHELL=/bin/bash
2 14 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/paper_trading && python3.11 simulator.py >> /home/ec2-user/paper_trading/simulator.log 2>&1
55 19 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/paper_trading && python3.11 simulator.py >> /home/ec2-user/paper_trading/simulator.log 2>&1' | sudo tee /etc/cron.d/paper-trading

# GitHub Push — 10:05 AM ET (14:05 UTC)
echo 'SHELL=/bin/bash
5 14 * * 1-5 ec2-user . /home/ec2-user/.env && /home/ec2-user/push_results.sh >> /home/ec2-user/push.log 2>&1' | sudo tee /etc/cron.d/push-results

# Trump Monitor — every 10 min during market hours (9:30-4 PM ET)
echo 'SHELL=/bin/bash
*/10 13-20 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/trump_alert && python3.11 monitor.py >> /home/ec2-user/trump_alert/monitor.log 2>&1' | sudo tee /etc/cron.d/trump-alert

# Weekly Events — Monday 8 AM ET (12:00 UTC)
echo 'SHELL=/bin/bash
0 12 * * 1 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/events && python3.11 weekly_report.py >> /home/ec2-user/events/report.log 2>&1' | sudo tee /etc/cron.d/weekly-events

sudo chmod 644 /etc/cron.d/*
```

### 7. Set up GitHub push (optional)

```bash
# Generate deploy key
ssh-keygen -t ed25519 -f /home/ec2-user/.ssh/github_deploy -N ''

# Add to GitHub repo as deploy key with write access
# Configure SSH
cat > /home/ec2-user/.ssh/config << 'EOF'
Host github.com
    HostName github.com
    User git
    IdentityFile /home/ec2-user/.ssh/github_deploy
    StrictHostKeyChecking no
EOF

git config --global user.email 'bot@stock-intelligence'
git config --global user.name 'Stock Intelligence Bot'
git clone git@github.com:YOUR_USER/stock-intelligence.git /home/ec2-user/repo
```

### 8. Robinhood setup (one-time)

```bash
# Create portfolio .env
cat > /home/ec2-user/portfolio/.env << 'EOF'
RH_EMAIL=your_robinhood_email
RH_PASSWORD=your_password
RH_TOTP_SECRET=optional_totp_secret
EOF

# Run once and approve device in Robinhood app
cd /home/ec2-user/portfolio && python3.11 fetch_portfolio.py
```

## Local Mac Setup

### 1. S3 sync credentials

Create IAM user `stock-sync-readonly` with policy:
```json
{
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": ["arn:aws:s3:::BUCKET", "arn:aws:s3:::BUCKET/*"]},
    {"Effect": "Allow", "Action": ["s3:PutObject"], "Resource": ["arn:aws:s3:::BUCKET/wsb/*"]}
  ]
}
```

Add to `~/.aws/credentials`:
```
[stock-sync]
aws_access_key_id=AKIA...
aws_secret_access_key=...
region=us-east-1
```

### 2. Launchd sync (10:30 AM weekdays)

Create `~/Library/LaunchAgents/com.stock.sync.plist` pointing to `sync_results.sh`.

The sync script:
- Syncs S3 results/, portfolio/, paper_trading/, events/ locally
- Scrapes WSB via ApeWisdom and uploads to S3 (for EC2 fallback)
- Regenerates paper trading chart SVG

### 3. GitHub Pages

The repo has a `docs/` directory with Jekyll config. GitHub Actions auto-deploys on push.
- `.github/workflows/deploy-blog.yml` builds the site
- `docs/generate_posts.py` converts daily briefs to blog posts

## Key Architecture Decisions

- **Screener sorts tickers by daily gain** before processing (top movers get fetched first before Yahoo rate-limits)
- **Batches of 50 tickers** with 1-second pauses to avoid rate-limiting
- **WSB uses ApeWisdom API** (Reddit blocks EC2 IPs)
- **Earnings scorecard** parses the weekly report to find which day each ticker was scheduled
- **Portfolio analysis** falls back to previous day's data if morning fetch fails
- **Paper trading** sells weakest position to fund new picks when capital is low
- **Trump monitor** classifies posts as IMMEDIATE/DIGEST/IGNORE via Claude
- **TradingAgents** uses custom `bedrock_client.py` adapter (langchain-aws) to connect the framework to Bedrock
- **Bedrock model**: us.anthropic.claude-opus-4-6-v1 (inference profile)

## TradingAgents Setup

```bash
# Clone TradingAgents into the experiment directory
# The tradingagents/ package is copied to /home/ec2-user/trading_agents_experiment/tradingagents/

# Install additional deps
sudo pip3.11 install langchain-aws langchain-core langgraph langgraph-checkpoint-sqlite stockstats

# The custom bedrock_client.py lives at:
# trading_agents_experiment/tradingagents/llm_clients/bedrock_client.py

# Config: provider=bedrock, deep_think=claude-sonnet-4-6, quick_think=claude-haiku-4-5
# Features: 4 analysts, 2 debate rounds, 2 risk rounds, checkpoint enabled, weekly reflection

# Cron at 10:10 AM ET (14:10 UTC):
echo '10 14 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/trading_agents_experiment && python3.11 run.py >> run.log 2>&1' | sudo tee /etc/cron.d/trading-agents-experiment
```

## Daily Schedule (all times ET)

```
Mon  8:00 AM  →  Weekly Events (next week's earnings, fed, IPOs)
     9:45 AM  →  Screener + News Agent + Email
     9:50 AM  →  Portfolio Fetch + Analysis + Email
    10:02 AM  →  Paper Trading (buy + exit check)
    10:05 AM  →  GitHub Push
    10:10 AM  →  TradingAgents Experiment (multi-agent debate on top 5)
    10:30 AM  →  Local sync (launchd)
     3:55 PM  →  Paper Trading exit check
     5:00 PM  →  Portfolio EOD fetch (backup)
  9:30-4 PM  →  Trump Monitor (every 10 min)

Tue-Fri same as Mon minus the weekly report
Sat-Sun 10:00 AM → Portfolio session keep-alive only
```

## S3 Bucket Structure

```
s3://BUCKET/
├── results/YYYY-MM/          Daily screener (csv, txt, brief.md)
├── portfolio/YYYY-MM/        Portfolio analysis (json, analysis.md)
├── paper_trading/
│   ├── portfolio.json        Current paper portfolio
│   ├── history/YYYY/MM/DD.json  Daily trade log
│   └── snapshots/YYYY-MM/    Daily equity values
├── events/YYYY-MM/           Weekly reports
└── wsb/latest.json           WSB data (uploaded from local)
```

## Disaster Recovery

1. Launch new EC2, run `deploy.sh`
2. Copy `.env` and portfolio `.env` with credentials
3. For Robinhood: run `fetch_portfolio.py` once and approve device
4. For GitHub push: generate new deploy key, add to repo
5. Paper trading state: restore `portfolio.json` and `trade_history.json` from S3
6. Trump monitor: `seen_posts.json` from S3 (or start fresh — will re-process recent posts once)
