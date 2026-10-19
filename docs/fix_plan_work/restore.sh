#!/bin/sh
# handoff_pkg: 新しいコンテナ（新しいセッション）で、確かめの道具（tools.tar.xz）を作業用の場所に戻し、道具が使うものを作り直す。
# 何度実行してもよい（あるものは作り直さない）。くわしくは README.md。
#
#   sh restore.sh [展開先] [--sed] [--skip-venv] [--skip-pdf] [--skip-fuzz] [--skip-golden]
#     展開先     : 道具を戻すフォルダ。新しいセッションの作業用の場所（scratchpad）を渡す。既定は OLD（下）と同じパス
#     --sed      : 展開先が OLD と違うとき、symlink を作らずに、道具の中の OLD を展開先に書き換える
#     --skip-*   : その段を飛ばす（venv310・出版版 PDF・fuzz の cases.json・golden の基準）
#
# 道具（.py・.sh）の中には、束を作ったセッションの作業用の場所の絶対パス OLD が書いてある。展開先が OLD と違うときは、
#   (1) OLD から展開先への symlink を作る（OLD がなく、親のフォルダを作れるとき。既定）。道具は OLD のまま動く
#   (2) それができない（OLD がすでにある）か --sed のときは、展開した .py・.sh・.md・.js の OLD を展開先に書き換える
#
# 段（順に）:
#   1. tools.tar.xz を展開先に展開する（道具・反例集・小さな入力・文書・ワークフローのスクリプト〈scripts/〉と、道具が書く空の出力フォルダ）。
#      この束の README・restore.sh・regen_fuzz.sh などを 展開先/handoff_pkg に写す
#   1c. OLD を使えるようにする（同じパス / symlink / 書き換え）
#   2. 道具が使うリンクと写しを作る（fixB2r4/base_src・fixB2r4/tools/docx、realpdf/check.py の写し）
#   3. コードの写しを git archive で作る: n10/judge/base_src（0.20.0 = 6ab1769）、b21/base021_src（0.21.0 = 45d8314）、
#      oracle/wt_head（0.19.0 = 1fe3bc7 の全体。反例集の make_fixtures の予備と fuzz8 の v019）、rvB_regress_mut/tests（1fe3bc7 の tests）
#   4. 本体を入れる（python に jasme_jats がなければ pip install -e ".[dev]"）。4b. Python 3.10 の venv（展開先/venv310。uv）
#   5. 本誌の出版版 PDF 5 本を tests/private/pdf/ に取る（J-STAGE。sha256 を束を作った時点のものと比べる）
#   6. 作り直せる入力の docx を作る（make_inputs.py: rvB2/docx の win1・num1、rvB_regress_exp_out）
#   7. fuzz の cases.json と docx を作り直す（regen_fuzz.sh --verify。89 組で 5 分ほど）
#   8. golden の基準（展開先/n10/golden_base）を 0.20.0 の src で作り、manifest を束を作った時点のものと比べる
#   9. Colab のテストデータ1〜3（tests/private/colab/td1〜3）があるかを確かめる（ないときは README の手順で Google ドライブから取る）
set -e
OLD=/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad
REPO=${REPO:-/home/user/jstgxmlcng_JASME}
H=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python}
DEST=$OLD; SKIP=""; SED=0
while [ $# -gt 0 ]; do
  case $1 in
    --dest) DEST=$2; shift 2 ;;
    --sed) SED=1; shift ;;
    --skip-*) SKIP="$SKIP ${1#--skip-}"; shift ;;
    -*) echo "知らない引数: $1" >&2; exit 2 ;;
    *) DEST=$1; shift ;;
  esac
done
skip() { case " $SKIP " in *" $1 "*) return 0 ;; esac; return 1; }
say() { printf '\n== %s\n' "$*"; }
mkdir -p "$DEST"; DEST=$(cd "$DEST" && pwd)

say "1. 展開: $H/tools.tar.xz → $DEST"
tar -xJf "$H/tools.tar.xz" -C "$DEST" --keep-newer-files 2>&1 | grep -v 'is newer or same age' || true
echo "  束のファイル: $(tar -tJf "$H/tools.tar.xz" | grep -cv '/$')"

say "1b. handoff_pkg の写し（$DEST/handoff_pkg）"
if [ "$DEST/handoff_pkg" != "$H" ]; then
  mkdir -p "$DEST/handoff_pkg/build"
  for f in README.md restore.sh regen_fuzz.sh make_inputs.py fuzz_sha256.txt pdf_sha256.txt td_sha256.txt golden_base_manifest.json tools.tar.xz.sha256; do
    [ -f "$H/$f" ] && cp -p "$H/$f" "$DEST/handoff_pkg/$f"; done
  cp -p "$H"/build/*.py "$H"/build/*.sh "$DEST/handoff_pkg/build/" 2>/dev/null || true
  echo "  写した（tools.tar.xz は写さない）"
else echo "  ここから動かしている"; fi

say "1c. 道具の中の古いパス（$OLD）"
MODE=same
if [ "$DEST" != "$OLD" ]; then
  if [ $SED = 0 ] && [ -L "$OLD" ] && [ "$(readlink "$OLD")" = "$DEST" ]; then MODE=link
  elif [ $SED = 0 ] && [ ! -e "$OLD" ] && [ ! -L "$OLD" ] && mkdir -p "$(dirname "$OLD")" 2>/dev/null && ln -s "$DEST" "$OLD" 2>/dev/null; then MODE=link
  else MODE=sed; fi
fi
case $MODE in
  same) echo "  展開先が古いパスと同じ（そのまま動く）" ;;
  link) echo "  symlink: $OLD → $DEST（道具は古いパスのまま動く）" ;;
  sed)
    n=0
    for f in $(tar -tJf "$H/tools.tar.xz" | grep -E '\.(py|sh|md|js)$'); do
      p="$DEST/$f"
      if [ -f "$p" ] && grep -qF "$OLD" "$p"; then sed -i "s#$OLD#$DEST#g" "$p"; n=$((n + 1)); fi
    done
    echo "  書き換え: $n ファイルの $OLD を $DEST に（symlink を作れなかった、または --sed）" ;;
esac
# 道具の中のパスで見た S（cases.json の docx のパスなどに入る）
if [ $MODE = sed ]; then TS=$DEST; else TS=$OLD; fi

say "2. リンクと写し"
mkdir -p "$DEST/n10/judge/tools/docx" "$DEST/fixB2r4/realpdf" "$DEST/b21/isolate/realpdf"
[ -e "$DEST/fixB2r4/base_src" ] || ln -s "$TS/n10/judge/base_src" "$DEST/fixB2r4/base_src"
[ -e "$DEST/fixB2r4/tools/docx" ] || ln -s "$TS/n10/judge/tools/docx" "$DEST/fixB2r4/tools/docx"
for d in fixB2r4/realpdf b21/isolate/realpdf; do
  [ -f "$DEST/$d/check.py" ] || cp -p "$DEST/n10/judge/realpdf/check.py" "$DEST/$d/check.py"
done
echo "  fixB2r4/base_src → n10/judge/base_src、fixB2r4/tools/docx → n10/judge/tools/docx、realpdf/check.py の写し 2 つ"

say "3. コードの写し（git archive。リポジトリの作業ツリーには触らない）"
need_commit() {
  git -C "$REPO" cat-file -e "$1^{commit}" 2>/dev/null && return 0
  echo "  $1 がないので origin から取る"; git -C "$REPO" fetch -q origin "$1" 2>/dev/null || git -C "$REPO" fetch -q --unshallow origin 2>/dev/null || true
  git -C "$REPO" cat-file -e "$1^{commit}" || { echo "  $1 が取れない（git fetch origin main を試す）" >&2; return 1; }
}
put_src() {   # put_src コミット 置き場（その下に jasme_jats）
  if [ -f "$2/jasme_jats/__init__.py" ]; then echo "  ある: $2"; return; fi
  need_commit "$1"; mkdir -p "$2"
  git -C "$REPO" archive "$1" src/jasme_jats | tar -x -C "$2" --strip-components=1
  echo "  作った: $2（$1、版 $(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$2/jasme_jats/__init__.py")）"
}
put_src 6ab1769 "$DEST/n10/judge/base_src"
put_src 45d8314 "$DEST/b21/base021_src"
if [ -f "$DEST/oracle/wt_head/src/jasme_jats/__init__.py" ]; then echo "  ある: $DEST/oracle/wt_head"; else
  need_commit 1fe3bc7; mkdir -p "$DEST/oracle/wt_head"; git -C "$REPO" archive 1fe3bc7 | tar -x -C "$DEST/oracle/wt_head"
  echo "  作った: $DEST/oracle/wt_head（1fe3bc7 の全体。git worktree ではない）"; fi
if [ -f "$DEST/rvB_regress_mut/tests/make_fixtures.py" ]; then echo "  ある: $DEST/rvB_regress_mut/tests"; else
  need_commit 1fe3bc7; mkdir -p "$DEST/rvB_regress_mut"; git -C "$REPO" archive 1fe3bc7 tests | tar -x -C "$DEST/rvB_regress_mut"
  echo "  作った: $DEST/rvB_regress_mut/tests（1fe3bc7 の tests）"; fi

say "4. 本体（$PY）"
if $PY -c "import jasme_jats, pypdfium2, docx, lxml, PIL, pytest" 2>/dev/null; then echo "  $PY に jasme_jats がある"; else
  (cd "$REPO" && $PY -m pip install -q -e ".[dev]"); fi
if ! skip venv; then
  say "4b. Python 3.10 の venv（$DEST/venv310）"
  if [ -x "$DEST/venv310/bin/python" ]; then echo "  ある: $DEST/venv310"; else uv venv -q -p 3.10 "$DEST/venv310"; fi
  uv pip install -q --python "$DEST/venv310/bin/python" -e "$REPO[dev]"
  "$DEST/venv310/bin/python" -c "import sys, jasme_jats; print('  venv310:', sys.version.split()[0], jasme_jats.__file__)"
fi

if ! skip pdf; then
  say "5. 本誌の出版版 PDF（tests/private/pdf。コミットしない）"
  mkdir -p "$REPO/tests/private/pdf"
  for a in 24/1/24_25 25/1/25_77 27/1/27_47 29/2/29_79 30/2/30_59; do
    n=$(echo $a | tr / _); f="$REPO/tests/private/pdf/$n.pdf"
    if [ ! -s "$f" ]; then
      curl -sSfL --retry 3 -o "$f.part" "https://www.jstage.jst.go.jp/article/jasme/$a/_pdf/-char/ja" && mv "$f.part" "$f" || { rm -f "$f.part"; echo "  取れない: $n" >&2; continue; }
    fi
    want=$(grep " $n.pdf\$" "$H/pdf_sha256.txt" | cut -d' ' -f1 || true); got=$(sha256sum "$f" | cut -d' ' -f1)
    [ "$want" = "$got" ] && echo "  $n.pdf: sha256 一致" || echo "  $n.pdf: sha256 が束を作った時点と違う（J-STAGE が版を替えた？ 照合の結果が変わりうる）"
  done
fi

say "6. 作り直せる入力の docx"
(cd /tmp && $PY -I "$H/make_inputs.py" "$DEST")

if ! skip fuzz; then
  say "7. fuzz の cases.json と docx（regen_fuzz.sh）"
  JASME_S=$DEST sh "$H/regen_fuzz.sh" --root "$TS" --verify
fi

if ! skip golden; then
  say "8. golden の基準（n10/golden_base。0.20.0 の src で golden.py）"
  if [ -f "$DEST/n10/golden_base/manifest.json" ]; then echo "  ある: $DEST/n10/golden_base"; else
    (cd "$DEST/n10" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DEST/n10/judge/base_src" $PY "$DEST/golden/golden.py" "$DEST/n10/golden_base" > /dev/null); fi
  if cmp -s "$DEST/n10/golden_base/manifest.json" "$H/golden_base_manifest.json"; then echo "  manifest.json が束を作った時点のものと同じ"
  else echo "  manifest.json が束を作った時点のものと違う（tests/fixtures が変わった？ diff $H/golden_base_manifest.json $DEST/n10/golden_base/manifest.json）"; fi
fi

say "9. Colab のテストデータ1〜3（tests/private/colab/td1〜3。コミットしない）"
for n in 1 2 3; do
  for x in docx pdf; do
    f="$REPO/tests/private/colab/td$n/td$n.$x"
    if [ -s "$f" ]; then
      want=$(grep " td$n.$x\$" "$H/td_sha256.txt" | cut -d' ' -f1 || true); got=$(sha256sum "$f" | cut -d' ' -f1)
      [ "$want" = "$got" ] && echo "  td$n.$x: ある（sha256 一致）" || echo "  td$n.$x: ある（sha256 が違う）"
    else
      echo "  td$n.$x: ない → README.md の「Colab のテストデータ1〜3」の手順で Google ドライブから取る"
    fi
  done
done
echo
echo "終わり（パスの扱い: $MODE。道具の中の S は $TS）。作り直せないもの（試作の src など）は README.md の「戻らないもの」。"
