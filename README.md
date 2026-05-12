# Stock Intelligence Pipeline

Automated daily stock screening, technical analysis, portfolio monitoring, and AI-powered morning briefs.

## Architecture

```
EC2 (t2.micro, us-east-1)
├── 9:50 AM ET  →  Portfolio Analysis Bot
│   ├── fetch_portfolio.py     Pulls Robinhood holdings
│   └── analyze_portfolio.py   Claude Opus 4.6 analyzes: exit targets, stops, trim/hold/add
│
├── 10:00 AM ET →  Stock Screener Pipeline
│   ├── screener.py            Screens ~2700 US stocks (EMA, momentum, volume)
│   ├── wsb_sentiment.py       Scrapes WSB for top 5 trending tickers + sentiment
│   ├── news_agent.py          Fetches technicals + news, Claude generates morning brief
│   └── send_email.py          Sends HTML email + uploads to S3
│
Local Mac (launchd at 10:30 AM)
└── sync_results.sh            Syncs S3 → local for CSV viewing
```

## Morning Email Contains

1. **Screener table** — all stocks passing filters, sortable CSV
2. **Top 20 movers** — entry price → exit target with fib levels, thesis, support
3. **Claude's Top Picks** — 3-5 swing trade picks with upside/risk
4. **Avoid list** — overextended names to stay away from
5. **WSB Sentiment Check** — top 5 WSB tickers, Claude agrees/disagrees with reasoning
6. **Portfolio Analysis** (separate email) — per-position exit targets, trim/hold/add/exit calls, new buy suggestions

## Screener Filters

- Market cap > $1B
- Price above 50-day EMA
- Positive weekly gain
- Sorted by composite momentum score (MACD 35% | ROC 30% | Volume 25% | EMA 10%)

## Technical Analysis

Each stock gets:
- Fibonacci retracements (0.236, 0.382, 0.5, 0.618) for support
- Fibonacci extensions (1.272, 1.618) for exit targets
- 50-day EMA and SMA, 200-day SMA
- RSI (14-day), MACD histogram
- Volume ratio vs 20-day average
- 20-day high/low for immediate support/resistance

## Local File Structure

```
stock/
├── results/
│   └── 2026-05/
│       ├── 2026-05-11.csv          Sortable screener data
│       ├── 2026-05-11.txt          Full screener log
│       └── 2026-05-11_brief.md     News + picks + WSB sentiment
├── portfolio_analysis/
│   └── data/
│       └── 2026-05/
│           ├── 2026-05-11.json         Raw holdings
│           └── 2026-05-11_analysis.md  Portfolio exit analysis
├── screener.py
├── news_agent.py
├── wsb_sentiment.py
├── send_email.py
├── sync_results.sh
└── view.py                    Local CLI viewer with --sort flag
```

## Setup

### Prerequisites
- Python 3.11+
- AWS account with EC2, SES, S3, Bedrock access
- Robinhood account (for portfolio bot)

### Python Dependencies
```
yfinance pandas requests lxml boto3 robin_stocks python-dotenv pyotp
```

### AWS Resources
- EC2: t2.micro with IAM role (`stock-screener-ec2`) for SES + S3 + Bedrock
- S3: Private bucket for results storage
- SES: Verified sender email
- IAM user: `stock-sync-readonly` for local sync (permanent keys)

### Cron Jobs (EC2, UTC)
```
# Portfolio analysis — 9:50 AM ET (13:50 UTC)
50 13 * * 1-5  fetch_portfolio.py && analyze_portfolio.py

# Stock screener + news — 10:00 AM ET (14:00 UTC)
0 14 * * 1-5   screener.py && news_agent.py && send_email.py
```

### Local Sync (launchd)
```
# 10:30 AM weekdays — syncs S3 results + portfolio analysis locally
com.stock.sync.plist → sync_results.sh
```

## Configuration

### .env (screener — not needed, uses NASDAQ public API)

### portfolio_analysis/.env
```
RH_EMAIL=your_email
RH_PASSWORD=your_password
RH_TOTP_SECRET=optional_for_auto_2fa
```

## Models

- **News Agent**: Claude Opus 4.6 (1M context) via AWS Bedrock
- **Portfolio Analysis**: Claude Opus 4.6 (1M context) via AWS Bedrock

## Getting Started (for others)

### 1. Clone and install dependencies

```bash
git clone https://github.com/kai-ion/stock-intelligence.git
cd stock-intelligence
pip install yfinance pandas requests lxml boto3 robin_stocks python-dotenv pyotp
```

### 2. Set up AWS infrastructure

```bash
# Create an S3 bucket
aws s3 mb s3://your-bucket-name

# Launch a t2.micro EC2 instance (free tier eligible)
aws ec2 run-instances --image-id ami-0xxx --instance-type t2.micro --key-name your-key

# Create an IAM role for the EC2 with these policies:
#   - SES: SendEmail, SendRawEmail
#   - S3: PutObject, GetObject, ListBucket (your bucket)
#   - Bedrock: InvokeModel

# Attach the role to your EC2 instance
aws ec2 associate-iam-instance-profile --instance-id i-xxx --iam-instance-profile Name=your-role

# Verify an email address in SES (sender + recipient if in sandbox)
aws ses verify-email-identity --email-address your_email@gmail.com
```

### 3. Configure environment variables

Create a `.env` file on your EC2 instance:

```bash
EMAIL_RECIPIENT=your_email@gmail.com
EMAIL_SENDER=your_email@gmail.com
S3_BUCKET=your-bucket-name
AWS_REGION=us-east-1
MODEL_ID=us.anthropic.claude-opus-4-6-v1
```

### 4. Deploy scripts to EC2

```bash
scp screener.py news_agent.py wsb_sentiment.py send_email.py ec2-user@YOUR_IP:/home/ec2-user/
scp portfolio_analysis/fetch_portfolio.py portfolio_analysis/analyze_portfolio.py ec2-user@YOUR_IP:/home/ec2-user/portfolio/
```

### 5. Set up cron jobs on EC2

```bash
# /etc/cron.d/stock-screener
SHELL=/bin/bash
0 14 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user && python3.11 screener.py > output.log 2>&1 && python3.11 news_agent.py >> news_run.log 2>&1 && python3.11 send_email.py >> email.log 2>&1

# /etc/cron.d/portfolio-analysis
SHELL=/bin/bash
50 13 * * 1-5 ec2-user . /home/ec2-user/.env && cd /home/ec2-user/portfolio && python3.11 fetch_portfolio.py > fetch.log 2>&1 && python3.11 analyze_portfolio.py >> analyze.log 2>&1
```

### 6. Set up local sync (macOS)

```bash
# Copy sync_results.sh.example to sync_results.sh and fill in your bucket/paths
cp sync_results.sh.example sync_results.sh
chmod +x sync_results.sh

# Create an IAM user with read-only S3 access for local sync
# Add permanent access keys to ~/.aws/credentials under a [stock-sync] profile

# Set up launchd to run sync at 10:30 AM weekdays (see sync_results.sh.example)
```

### 7. Portfolio bot (optional)

```bash
# Create portfolio_analysis/.env with your Robinhood credentials
RH_EMAIL=your_robinhood_email
RH_PASSWORD=your_password
RH_TOTP_SECRET=your_totp_secret  # optional, enables fully automated login

# Run once manually to establish a session (approve device in Robinhood app)
cd portfolio_analysis && python fetch_portfolio.py

# After initial login, the session persists and renews daily via cron
```

### Notes

- The screener uses Yahoo Finance which rate-limits aggressively. The script processes tickers in batches of 50 with pauses, and retries failures. Top daily movers are prioritized first.
- SES sandbox mode sends emails to spam — create a Gmail filter to fix this, or request SES production access.
- The Robinhood session pickle expires after 24 hours of inactivity. The daily cron keeps it alive on weekdays. After a weekend, you may need to re-approve on Monday.
- Adjust `MODEL_ID` in `.env` to use a different Claude model (e.g., `us.anthropic.claude-sonnet-4-6` for faster/cheaper runs).
