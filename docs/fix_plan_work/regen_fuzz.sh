#!/bin/sh
# handoff_pkg: 乱数の例（fuzz4 = rvB4_regress/fuzz の 8 組、fuzz8 = rvB8_regress/fuzz8 の *_3[0-9][0-9] の 81 組）の
# cases.json と docx を、生成器（gen.py・gen_dense.py・gen_head.py・gen8.py）で作り直す。どれも架空の文字（作業用の場所だけ）。
#
#   [JASME_S=道具の場所] sh regen_fuzz.sh [--root DIR] [--force] [--verify] [名前...]
#     名前    : 組の名前（c1・dense31・h39・caption_302・m_mix_311 など）。省くとすべて（89 組。1 組 300 本で 3〜4 秒）
#     --root  : DIR/rvB4_regress/fuzz/<名前>/ などに作る（既定は JASME_S。cases.json の docx のパスも DIR の下になる）
#     --force : cases.json があっても作り直す（既定は、ある組を飛ばす。何度実行してもよい）
#     --verify: 作った（またはある）cases.json の sha256 を fuzz_sha256.txt（束を作った時点のもの）と比べる。
#               cases.json には docx の絶対パスが入るので、DIR が OLD（束を作ったセッションの作業用の場所）でなければ、
#               パスの前置きを OLD に戻してから比べる
#     JASME_S : 束を戻した場所（生成器を探す場所。既定は OLD）。restore.sh が渡す
# 生成器は /home/user/jstgxmlcng_JASME の tests/make_fixtures.py と src を読む。Python は ${PYTHON:-python}
# （束を作ったときは 3.13.16。--verify で同じ列になったかが分かる）。
OLD=/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad
S=${JASME_S:-$OLD}
H=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python}
ROOT=$S; FORCE=0; VERIFY=0; NAMES=""
while [ $# -gt 0 ]; do
  case $1 in
    --root) ROOT=$2; shift 2 ;;
    --force) FORCE=1; shift ;;
    --verify) VERIFY=1; shift ;;
    *) NAMES="$NAMES $1"; shift ;;
  esac
done
F4="c1 c8 c9 c10 dense31 dense32 h39 h60"
F8="mix_301 caption_302 long_303 refs_304 nopage_305 mix_306"
for seed in 311 312 313 314 315 316 317 318 319 320 321 322 323 324 325; do
  for shape in mix caption long refs nopage; do F8="$F8 m_${shape}_$seed"; done
done
[ -z "$NAMES" ] && NAMES="$F4 $F8"

# 組の名前 → 生成器と引数（cases.json の件数・柱の文字と、生成したときのコマンドから割り出したもの。README の表）
#   fuzz4: c<種>（gen.py。c1 だけ種 7）、dense<種>（gen_dense.py）、h<柱の文字のバイト数>（gen_head.py、種 21）
#   fuzz8: <形>_<種>（gen8.py。run_all8.sh）、m_<形>_<種>（gen8.py。run_more8.sh。形ごとに種は同じ）
run_one() {
  name=$1
  case $name in
    c1)            dir=rvB4_regress/fuzz; set -- gen.py 300 7 ;;
    c8|c9|c10)     dir=rvB4_regress/fuzz; set -- gen.py 300 ${name#c} ;;
    dense31|dense32) dir=rvB4_regress/fuzz; set -- gen_dense.py 300 ${name#dense} ;;
    h39)           dir=rvB4_regress/fuzz; set -- gen_head.py 300 21 架空の論文の柱の文字列です ;;
    h60)           dir=rvB4_regress/fuzz; set -- gen_head.py 300 21 架空の論文の題目を短くした柱の文字列です ;;
    mix_30[16]|caption_302|long_303|refs_304|nopage_305)
                   dir=rvB8_regress/fuzz8; set -- gen8.py 300 ${name##*_} ${name%_*} ;;
    m_*_3[12][0-9]) x=${name#m_}; dir=rvB8_regress/fuzz8; set -- gen8.py 300 ${x##*_} ${x%_*} ;;
    *) echo "知らない組: $name" >&2; return 1 ;;
  esac
  gen=$1; shift
  out=$ROOT/$dir/$name
  if [ -f $out/cases.json ] && [ $FORCE = 0 ]; then
    msg="ある"
  else
    mkdir -p $out
    g=$ROOT/$dir/$gen; [ -f $g ] || g=$S/$dir/$gen
    (cd /tmp && $PY -I $g $out "$@" > /dev/null) || { echo "$name: 生成に失敗" >&2; return 1; }
    msg="作った（$gen $*）"
  fi
  if [ $VERIFY = 1 ]; then
    want=$(grep " $dir/$name/cases.json\$" $H/fuzz_sha256.txt | cut -d' ' -f1)
    if [ "$ROOT" = "$OLD" ]; then got=$(sha256sum $out/cases.json | cut -d' ' -f1)
    else got=$(sed "s#$ROOT/#$OLD/#g" $out/cases.json | sha256sum | cut -d' ' -f1); fi
    if [ "$want" = "$got" ]; then msg="$msg  sha256 一致"; else msg="$msg  sha256 不一致（$got / $want）"; fi
  fi
  echo "$name: $msg"
}
for n in $NAMES; do run_one $n; done
