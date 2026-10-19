#!/bin/sh
# handoff_pkg: 確かめの道具の束（tools.tar.xz）を作る。何度実行してもよい（B2.1 が終わった後などに作り直す）。
#   sh pack.sh            # trace.py で一覧を作り、leakcheck.py で実際の論文の文字との一致を確かめ、束を作る
# 束の中のパスは S からの相対（restore.sh が S に展開する）。中身は一覧（filelist.txt）と、道具が書く空の出力フォルダ（OUTDIRS）。
set -e
S=/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad
H=$S/handoff_pkg; B=$H/build
cd $B
python -I trace.py > filelist.txt 2> excluded.txt
echo "一覧: $(wc -l < filelist.txt) ファイル（外したものは excluded.txt）"
# ワークフローのスクリプトの写し（束の scripts/ の下。新しいセッションには ~/.claude/projects の下が残らないため）
W=$HOME/.claude/projects/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/workflows/scripts
rm -rf $B/stage; mkdir -p $B/stage/scripts
cp -p $W/*.js $B/stage/scripts/
# 単位 B のスクリプトは、本誌の出版版 PDF の本文・図のキャプション・受付日をそのまま書いた例を含むので入れない（leakcheck.py で見つけた）
rm -f $B/stage/scripts/jasme-unit-b-wf_1938bdf8-7dd.js
echo "ワークフローのスクリプト: $(ls $B/stage/scripts | wc -l) 個"
# 道具が書く出力のフォルダ（空で入れる。restore 後に道具がそのまま書けるように）
OUTDIRS="b21/ambiguity/gen b21/ambiguity/logs b21/isolate/gen b21/isolate/logs b21/isolate/td b2_review/r5p/logs
fixB2r4/gen fixB2r4/logs fixB2r4/td fixB2r4/v fixB2r4/v/q fixB2r4/v/f4 fixB2r4/v/f8 fixB2r4/realpdf/out n10/judge/logs
n10/judge/realpdf/out n10/judge/tmp n10/judge/tools/docx n10/judge/v n10/judge/v/q n10/judge/v/f4 n10/judge/v/f8 oracle/_work realpdf_B/out rvB2/docx rvB_regress_exp_out"
{ cut -f1 filelist.txt; ls -d $B/stage/scripts/*.js; } > leaklist.txt
python -I leakcheck.py leaklist.txt > leak_summary.txt
head -2 leak_summary.txt
{ cat filelist.txt; for d in $OUTDIRS; do echo "$d"; done; } | cut -f1 | sort -u > tarlist.txt
( cd $S && for d in $OUTDIRS; do [ -d $d ] || { echo "ない出力フォルダ: $d" >&2; exit 1; }; done )
tar -C $S --no-recursion --sort=name --owner=0 --group=0 --numeric-owner -cf $B/tools.tar -T tarlist.txt
tar -C $B/stage --sort=name --owner=0 --group=0 --numeric-owner -rf $B/tools.tar scripts
xz -9e -T1 -c $B/tools.tar > $H/tools.tar.xz.part; rm -f $B/tools.tar
mv $H/tools.tar.xz.part $H/tools.tar.xz
echo "束: $H/tools.tar.xz $(stat -c %s $H/tools.tar.xz) バイト、$(tar -tJf $H/tools.tar.xz | grep -vc '/$') ファイル・$(tar -tJf $H/tools.tar.xz | grep -c '/$') フォルダ"
sha256sum $H/tools.tar.xz | sed "s#$H/##" > $H/tools.tar.xz.sha256
