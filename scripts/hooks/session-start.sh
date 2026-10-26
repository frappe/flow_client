#!/usr/bin/env bash
# SessionStart — stamp today's daily note and surface the active loop and branch rules.
DAY=$(date +%Y-%m-%d)
NOTE="brain/80-daily/$DAY.md"
mkdir -p brain/80-daily
if [ ! -f "$NOTE" ]; then
  printf -- "---\ntype: daily\ndate: %s\n---\n# %s\n\n## Sessions\n" "$DAY" "$DAY" > "$NOTE"
fi
BRANCH=$(git branch --show-current 2>/dev/null || echo "")
echo "- session started $(date +%H:%M) on branch \`${BRANCH:-n/a}\`" >> "$NOTE"
case "$BRANCH" in
  loop/*)          echo "Active loop: ${BRANCH#loop/}. Read brain/10-specs/${BRANCH#loop/}.md before changing anything." ;;
  develop)         echo "On develop — the upstream mirror. Do not change anything here. Run /loops." ;;
  veyqon)          echo "On veyqon — the integration branch. Work happens on loop/<slug>. Run /loops." ;;
  *)               echo "No active loop. Run /loops." ;;
esac
exit 0
