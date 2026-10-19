#!/bin/sh
# handoff_pkg: 束の展開の確かめ。このプロセスだけの mount 名前空間（unshare -m、propagation private）で、restore.sh と主な道具を動かす。
# ほかのプロセス（動いているワークフロー）からは、元の作業用の場所のまま見える。
#   sh restore_test.sh [same] [link] [sed]      # 省くと 3 通りすべて。結果は restore_test/<形>/ の下（*.log・new_files.txt）
#   same: restore_test/same を OLD（束を作ったセッションの作業用の場所）の上に bind mount し、既定の展開先（OLD）に戻す
#   link: restore_test/link を /media に bind mount し、OLD を含むセッションのフォルダを空の tmpfs で隠して（OLD がない新しい
#         コンテナの形）、展開先 /media に戻す。restore.sh が OLD → /media の symlink を作り、道具は OLD のパスのまま動く
#   sed : link と同じ形で、OLD に空のフォルダを置いてから戻す（symlink を作れない形）。restore.sh が道具の中の OLD を /media に
#         書き換え、道具は /media のパスで動く。OLD は空なので、書き換え漏れがあればその道具は失敗する
# どの形でも venv310 は作らない（uv pip install -e がリポジトリの src/jasme_jats.egg-info を書き換えるため。手順は HANDOFF.md と同じ）。
# fuzz は c1・caption_302 だけ作る（89 組は build/regen_check.sh で確かめた）。
S=/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad
SD=$(dirname $S)
H=$S/handoff_pkg
MODES=${*:-"same link sed"}
for m in $MODES; do
  RT=$H/restore_test/$m
  rm -rf $RT; mkdir -p $RT/pkg/build $RT/bin
  cp -p $H/tools.tar.xz $H/tools.tar.xz.sha256 $H/restore.sh $H/regen_fuzz.sh $H/make_inputs.py $H/fuzz_sha256.txt $H/pdf_sha256.txt \
    $H/td_sha256.txt $H/golden_base_manifest.json $H/README.md $RT/pkg/
  cp -p $H/build/*.py $H/build/*.sh $RT/pkg/build/
  # python の __pycache__ をリポジトリの tests/ などに書かない（-B）
  printf '#!/bin/sh\nexec /usr/bin/python -B "$@"\n' > $RT/bin/python; chmod +x $RT/bin/python
  case $m in
    same) D=$S; T=$S; ARG="" ;;
    link) D=/media; T=$S; ARG=/media ;;
    sed)  D=/media; T=/media; ARG=/media ;;
  esac
  cat > $RT/pkg/inner.sh <<EOF
D=$D; T=$T
export PATH=\$D/bin:\$PATH
cd /tmp
echo "[$m] 展開先 \$D の中: \$(ls \$D | tr '\n' ' ')／OLD: \$(ls -ld $S 2>&1 | sed 's/.* $SD/…/')"
sh \$D/pkg/restore.sh $ARG --skip-venv --skip-fuzz > \$D/restore.log 2>&1; echo "[$m] restore.sh: 終了コード \$?（\$(tail -1 \$D/restore.log)）"
JASME_S=\$D sh \$D/handoff_pkg/regen_fuzz.sh --root \$T --verify c1 caption_302 > \$D/regen.log 2>&1; echo "[$m] regen_fuzz.sh: 終了コード \$?（\$(grep -c 'sha256 一致' \$D/regen.log)/2 一致）"
SRC=\$T/n10/judge/base_src
sh \$T/fixB2r4/tools/run_oracle.sh \$SRC rt o34 b2 > \$D/t_oracle.log 2>&1; echo "[$m] run_oracle.sh o34 b2: 終了コード \$?（\$(tr '\n' ' ' < \$D/t_oracle.log)）"
sh \$T/fixB2r4/gen.sh \$SRC rt head > \$D/t_gen.log 2>&1; echo "[$m] gen.sh head: 終了コード \$?（\$(cat \$D/t_gen.log)）"
python -I \$T/fixB2r4/tools/quick.py run \$SRC \$T/rvB2p/cases_bound.py \$T/fixB2r4/v/q/rvB2p_cases_bound_rt.json > \$D/t_quick.log 2>&1; echo "[$m] quick.py: 終了コード \$?"
python -I \$T/fixB/fixB_all.py \$SRC \$T/fixB2r4/v/fixB210_rt.json > \$D/t_b210.log 2>&1; echo "[$m] fixB_all.py: 終了コード \$?（\$(tail -1 \$D/t_b210.log | sed 's/ ->.*//')）"
echo "[$m] 展開先の .py・.sh に残る OLD: \$(grep -rlF '$S' --include='*.py' --include='*.sh' \$D 2>/dev/null | grep -v '/handoff_pkg/\|/pkg/' | wc -l) ファイル"
find \$D -newer \$D/pkg/inner.sh -type f | grep -v '/_work/\|/docx/\|/rvB4_regress/\|/rvB8_regress/\|/golden_base/\|/oracle/wt_head/\|/base_src/\|/base021_src/\|/rvB_regress_mut/\|/handoff_pkg/\|__pycache__' | sed "s#\$D/##" | sort > \$D/new_files.txt
EOF
  case $m in
    same) unshare -m --propagation private sh -c "mount --bind $RT $S && [ -f $S/pkg/inner.sh ] && sh $S/pkg/inner.sh" ;;
    link) unshare -m --propagation private sh -c "mount --bind $RT /media && mount -t tmpfs none $SD && [ ! -e $S ] && sh /media/pkg/inner.sh" ;;
    sed)  unshare -m --propagation private sh -c "mount --bind $RT /media && mount -t tmpfs none $SD && mkdir -p $S && sh /media/pkg/inner.sh" ;;
  esac
done
