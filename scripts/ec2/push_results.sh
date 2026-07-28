#!/bin/bash
cd /home/ec2-user/repo

# Pull latest
git pull --rebase origin main

# Sync all public data into the repo
mkdir -p screener_output/ events/ paper_trading/snapshots/ trading_agents/

aws s3 sync s3://$S3_BUCKET/results/ screener_output/ --region $AWS_REGION
aws s3 sync s3://$S3_BUCKET/events/ events/ --region $AWS_REGION
aws s3 sync s3://$S3_BUCKET/paper_trading/snapshots/ paper_trading/snapshots/ --region $AWS_REGION
aws s3 cp s3://$S3_BUCKET/paper_trading/portfolio.json paper_trading/portfolio.json --region $AWS_REGION 2>/dev/null
# The chart reads paper_trading/snapshots + portfolio.json, but generate_posts.py reads
# paper_trading/data/{snapshots,portfolio.json} FIRST. Keep both in sync so the portfolio
# table shows live prices (otherwise it reads a stale snapshot and shows $0.00 P&L).
mkdir -p paper_trading/data && cp paper_trading/portfolio.json paper_trading/data/portfolio.json 2>/dev/null
mkdir -p paper_trading/data/snapshots && cp -r paper_trading/snapshots/* paper_trading/data/snapshots/ 2>/dev/null

# Copy TradingAgents data
cp /home/ec2-user/trading_agents/data/portfolio.json trading_agents/portfolio.json 2>/dev/null
mkdir -p trading_agents/snapshots && cp -r /home/ec2-user/trading_agents/data/snapshots/* trading_agents/snapshots/ 2>/dev/null
mkdir -p paper_trading/history/2026/05 && cp /home/ec2-user/paper_trading/data/history/2026/05/*.json paper_trading/history/2026/05/ 2>/dev/null
mkdir -p paper_trading/history/2026/06 && cp /home/ec2-user/paper_trading/data/history/2026/06/*.json paper_trading/history/2026/06/ 2>/dev/null
mkdir -p trading_agents/decisions && cp /home/ec2-user/trading_agents/data/decisions/*.json trading_agents/decisions/ 2>/dev/null
mkdir -p trading_agents/reports && cp /home/ec2-user/trading_agents/data/reports/*.md trading_agents/reports/ 2>/dev/null

# Generate paper trading chart
python3.11 -c "
import sys
from pathlib import Path
sys.path.insert(0, '/home/ec2-user/paper_trading')
from generate_chart import load_snapshots, load_all_trades, generate_svg
import generate_chart
generate_chart.DATA_DIR = Path('/home/ec2-user/repo/paper_trading')
generate_chart.OUTPUT_FILE = Path('/home/ec2-user/repo/paper_trading/chart.svg')
snapshots = load_snapshots()
trades = load_all_trades()
generate_svg(snapshots, trades)
" 2>/dev/null || echo 'Paper trading chart failed'

# Generate TradingAgents comparison chart
python3.11 -c "
import sys
from pathlib import Path
sys.path.insert(0, '/home/ec2-user/trading_agents')
import generate_chart
generate_chart.DATA_DIR = Path('/home/ec2-user/trading_agents/data')
generate_chart.PAPER_TRADING_DIR = Path('/home/ec2-user/repo/paper_trading/data')
generate_chart.OUTPUT_FILE = Path('/home/ec2-user/repo/trading_agents/chart.svg')
generate_chart.main()
" 2>/dev/null || echo 'TradingAgents chart failed'

# Regenerate the blog posts + home-page includes (portfolio tables, market overview,
# AI agent) from the freshly synced data. Without this the home page shows stale
# holdings even though the underlying data updated.
python3.11 /home/ec2-user/repo/blog/generate_posts.py || echo 'Blog generation failed'

# Stage everything
git add screener_output/ events/ paper_trading/ trading_agents/ blog/ 2>/dev/null

# Check if there are changes to commit
if git diff --cached --quiet; then
    echo 'No new results to push'
    exit 0
fi

DATE=$(date +%Y-%m-%d)
git commit -m "Daily results — $DATE"
git push origin main
echo "Pushed results for $DATE"
