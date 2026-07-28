#!/bin/bash
# Publish the sports-betting blog: copy daily reports into the repo, regenerate
# Jekyll posts, commit, and push. GitHub Pages then auto-deploys.
# Mirrors push_results.sh (stock pipeline). Runs daily after the picks cron.
set -e

REPO=/home/ec2-user/sports-repo
SPORTS=/home/ec2-user/sports
# Dedicated write-enabled deploy key for sports-betting (github_deploy is read-only there)
export GIT_SSH_COMMAND="ssh -i /home/ec2-user/.ssh/sports_deploy -o StrictHostKeyChecking=no"

# Clone once, then reuse
if [ ! -d "$REPO/.git" ]; then
    git clone git@github.com:kai-ion/sports-betting.git "$REPO"
fi

cd "$REPO"
git pull --rebase origin main

# Copy the latest reports + data from the standalone sports tree into the repo
for sport in nba wnba mlb; do
    mkdir -p "$REPO/$sport/reports" "$REPO/$sport/data"
    cp "$SPORTS/$sport/reports/"*.md "$REPO/$sport/reports/" 2>/dev/null || true
    cp "$SPORTS/$sport/data/"*.json "$REPO/$sport/data/" 2>/dev/null || true
done

# Regenerate Jekyll posts from the reports
python3.11 "$REPO/blog/generate_posts.py" || echo 'Sports blog generation failed'

# Stage, commit, push only if something changed
git add nba/ wnba/ mlb/ blog/ 2>/dev/null
if git diff --cached --quiet; then
    echo 'No new sports results to push'
    exit 0
fi

DATE=$(date +%Y-%m-%d)
git -c user.name='Sports Bot' -c user.email='bot@sports-betting' commit -m "Sports results — $DATE"
git push origin main
echo "Pushed sports results for $DATE"
