#!/bin/sh
# handoff_pkg: regen_fuzz.sh で作り直した cases.json が、今の S のものとハッシュまで同じかを確かめる（作るのは regen_check の下だけ）。
#   sh regen_check.sh same 名前...   # 元と同じパスで作る: このプロセスだけの mount 名前空間（unshare -m、propagation private）で、
#                                     # regen_check/<組> を S/<組> の上に bind mount して regen_fuzz.sh を動かす。ほかのプロセス（動いている
#                                     # ワークフロー）からは元のフォルダのまま見える。cases.json の sha256 を fuzz_sha256.txt と比べる
#   sh regen_check.sh root 名前...   # --root で regen_check2 の下に作り、cases.json の docx のパスの前置きを S に戻してから比べる
# 組ごとに、比べた後で作った docx を消す（cases.json は残す）。
S=/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad
H=$S/handoff_pkg
mode=$1; shift
for name in "$@"; do
  case $name in c[0-9]*|dense[0-9]*|h[0-9]*) dir=rvB4_regress/fuzz ;; *) dir=rvB8_regress/fuzz8 ;; esac
  want=$(grep " $dir/$name/cases.json\$" $H/fuzz_sha256.txt | cut -d' ' -f1)
  if [ $mode = same ]; then
    rc=$H/regen_check/$dir/$name
    rm -rf $rc; mkdir -p $rc
    # bind mount に失敗したら何もしない（&&）。mount の後、元の cases.json が見えないこと（空のフォルダ）を確かめてから作る。
    # regen_fuzz.sh は --force なしなので、元の cases.json が見えていれば作らない（二重の守り）
    unshare -m --propagation private sh -c "mount --bind $rc $S/$dir/$name && [ ! -e $S/$dir/$name/cases.json ] && \
      sh $H/regen_fuzz.sh $name" > $rc.log 2>&1
    got=$( [ -f $rc/cases.json ] && sha256sum $rc/cases.json | cut -d' ' -f1)
    n=$(ls $rc | grep -c '\.docx$')
    d0=$(cmp -s $rc/case0000.docx $S/$dir/$name/case0000.docx && echo "case0000.docx もバイトまで同じ" || echo "case0000.docx はバイトが違う")
    rm -f $rc/*.docx
  else
    rc=$H/regen_check2
    rm -rf $rc/$dir/$name
    sh $H/regen_fuzz.sh --root $rc $name > $rc.$name.log 2>&1
    n=$(ls $rc/$dir/$name | grep -c '\.docx$')
    got=$(sed "s#$rc/#$S/#g" $rc/$dir/$name/cases.json | sha256sum | cut -d' ' -f1)
    d0=""
    rm -f $rc/$dir/$name/*.docx
  fi
  if [ -n "$got" ] && [ "$got" = "$want" ]; then r="一致"; else r="不一致（got=$got）"; fi
  echo "$mode $dir/$name: sha256 $r（docx $n 本） $d0"
done
