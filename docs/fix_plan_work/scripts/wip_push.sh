#!/bin/sh
# 作業中の控えを、一時的な index で作ってブランチに push する（作業ツリーは変えない）。 sh wip_push.sh "<件名>" "<本文>"
# 新しいセッションでは、下の S= を自分の作業用の場所（docs/fix_plan_work を写した場所の親）に書き換える。親は b21/review/wip_commit.txt の控え。
set -e
S=/tmp/claude-0/-home-user-jstgxmlcng-JASME/d6c16a4c-c8c0-592a-be84-ec12faff29b8/scratchpad
cd /home/user/jstgxmlcng_JASME
P=$(cat "$S/b21/review/wip_commit.txt")
export GIT_INDEX_FILE=$S/wip.index; rm -f "$GIT_INDEX_FILE"
git read-tree HEAD && git add -A
# 引き継ぎのフォルダ（作業用の場所の写し）を丸ごと docs/fix_plan_work/ に入れる
(cd "$S/fix_plan_work" && find . -type f ! -name '*.pyc' | sort) | while read -r f; do
  f=${f#./}; git update-index --add --cacheinfo 100644,$(git hash-object -w "$S/fix_plan_work/$f"),"docs/fix_plan_work/$f"
done
python3 - "$S/claude_wip.md" <<'PY'
import sys
s=open('CLAUDE.md',encoding='utf-8').read()
line='> **作業中の控え（このブランチだけ。main には入れない）: 最初に `docs/fix_plan_work/README.md` を読むこと。**\n\n'
if '作業中の控え' not in s: s=s.replace('# CLAUDE.md\n\n','# CLAUDE.md\n\n'+line,1)
open(sys.argv[1],'w',encoding='utf-8').write(s)
PY
git update-index --add --cacheinfo 100644,$(git hash-object -w "$S/claude_wip.md"),CLAUDE.md
T=$(git write-tree)
C=$(printf '%s\n\n%s\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_011VDa8Hv9YqnGw8AXp7iZKb\n' "$1" "$2" | git commit-tree "$T" -p "$P")
unset GIT_INDEX_FILE
git push origin "$C:refs/heads/claude/jstage-xml-converter-review-dw2f0u" 2>&1 | tail -1
echo "$C" > "$S/b21/review/wip_commit.txt"; echo "wip $C"
