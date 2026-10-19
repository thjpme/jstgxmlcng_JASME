# 確かめの道具の束（handoff_pkg、2026-10-19 作成）

## これは何か

リポジトリ jstgxmlcng_JASME（論文の docx を J-STAGE 全文 XML にするツール。CLAUDE.md）の「ルート2」（docx の文字を出版版 PDF に
合わせて直してから XML を作る）の照合（`src/jasme_jats/pdfmatch.py` の `compare` と `pdfdocx.py` の `plan_fixes`）を確かめるために、
これまでのセッションが作業用の場所（Claude Code の scratchpad）に作ってきた道具（反例集・生成例・乱数の例・golden・本誌の出版版 PDF での
確認など。以下まとめて「物差し」）を、別のセッション・新しいコンテナで使えるようにまとめたもの。

- 物差しはどれも、**ある版のコード（src のフォルダ）を渡して流し、結果を別の版（ふつうは 0.20.0 か 0.21.0）と比べる**ためのもの。
  単体で合否が決まるものは少ない。比べ方と、これまで使った合格の目安は下の「物差し」の表。
- 守る原則（CLAUDE.md・docs/DEVELOPMENT.md の「守るべき原則」）: ルート2 は docx の文字を PDF に合わせて直すが、組版の文字（ページ番号・
  誌名の行・柱・投稿受付日）、docx にない図・表の中の文字、ほかの段落の文字を docx に**足してはいけない**。PDF の本文にある docx の文字を
  **消してはいけない**。決められない違いは docx のまま残し、変換レポートの **13 章に出す**。物差しの判定はこの原則から決めている。
- 束を作ったときの状態: main とブランチ claude/jstage-xml-converter-review-dw2f0u がどちらも 45d8314（0.21.0、単位 B2 まで）。
  単位 B2.1（0.21.1。docs/FIX_PLAN.md の「B2.1」、問題 N20）のワークフロー（スクリプト `scripts/jasme-unit-b21-wf_04aeb00a-7bf.js`）が
  動いている途中だった。束の `b21/` はその時点の写し（`b21/DESIGN_B21.md` はまだなかった）。
- **feature ブランチの控えにだけ置き、main には入れない**（realpdf の check.py は、出版版 PDF の中の位置を示す短い語を含む）。

はじめに読むもの: リポジトリの CLAUDE.md、docs/DEVELOPMENT.md・DESIGN.md（4.4 にルート2 の照合の限界）・HANDOFF.md（環境）・
FIX_PLAN.md（単位の計画。B2 の節の「確かめたこと」に、0.20.0 → 0.21.0 の物差しの値がすべてある）。束の中では、`session_notes.md`
（利用者の決めたこと・進め方）、`n10/DESIGN_N10.md`（B2 の設計。物差しの使い方の表がある）、`handoff/README.md`・`handoff/STATUS_2026-10-18.md`（前の引き継ぎ）。

## このフォルダのファイル

| ファイル | 中身 |
|---|---|
| `tools.tar.xz` | 道具の束（241 ファイル〈作業用の場所のもの 233・ワークフローのスクリプト 8〉と、道具が書く空の出力フォルダ。xz で 515,968 バイト。sha256 は `tools.tar.xz.sha256`）。中のパスは作業用の場所からの相対 |
| `restore.sh` | 新しいコンテナで、束を作業用の場所に展開し、道具が使うもの（コードの写し・venv・PDF・入力の docx・fuzz・golden の基準）を作り直す |
| `regen_fuzz.sh` | 乱数の例（fuzz4・fuzz8）の cases.json と docx を生成器で作り直す（`--verify` で sha256 を確かめる） |
| `make_inputs.py` | 束に入れない入力の docx（rvB2/docx の win1・num1、rvB_regress_exp_out の 8 個）を作る。restore.sh が呼ぶ |
| `fuzz_sha256.txt` | 束を作った時点の fuzz の cases.json 89 個の sha256 |
| `pdf_sha256.txt` / `td_sha256.txt` | 本誌の出版版 PDF 5 本と、Colab のテストデータ1〜3 の docx・PDF の sha256（取り直したものが同じかを見る） |
| `golden_base_manifest.json` | golden の基準（n10/golden_base、0.20.0）の manifest.json の写し（ハッシュだけ） |
| `build/trace.py` | 道具の中身（パスの文字・シェルの変数・Path の式・import）から、道具が読むファイルをたどって一覧にする |
| `build/leakcheck.py` | 一覧のファイルに、実際の論文（tests/private/ の PDF・docx）の文字と 12 文字以上一致する部分がないかを調べる |
| `build/pack.sh` | trace.py → leakcheck.py → tools.tar.xz を作る（束を作り直すとき。B2.1 が終わった後など） |
| `build/regen_check.sh` | 作り直した cases.json が元とハッシュまで同じかを、regen_check/ の下だけに作って確かめる（unshare で元と同じパスに見せる） |
| `build/restore_test.sh` | 束の展開の確かめ（3 通りのパスの扱いで、restore.sh と主な道具を名前空間の中で動かす） |

## 戻し方（新しいセッション・新しいコンテナで）

道具（`.py`・`.sh`）の中には、束を作ったセッションの作業用の場所の絶対パスが書いてある（以下 **OLD**）:

    OLD = /tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad

1. リポジトリ /home/user/jstgxmlcng_JASME に 1fe3bc7（0.19.0）・6ab1769（0.20.0）・45d8314（0.21.0）があること（main を取れば入っている。
   ないときは restore.sh が `git fetch origin <sha>` を試す）。
2. このフォルダ（tools.tar.xz と同じ場所）で、**展開先に新しいセッションの作業用の場所**を渡す:
   ```bash
   sh restore.sh <新しい作業用の場所>                 # 例: sh restore.sh /tmp/claude-0/-home-user-jstgxmlcng-JASME/<新しいID>/scratchpad
   sh restore.sh <新しい作業用の場所> --skip-fuzz     # fuzz を後で作る
   sh restore.sh                                     # 展開先を省くと OLD に戻す
   ```
   展開先が OLD と違うとき、restore.sh は次のどちらかで、道具の中の OLD を使えるようにする（restore.log の「1c」の行に出る）:
   - **symlink**（既定）: OLD がなければ、OLD → 展開先の symlink を作る。道具は OLD のパスのまま動く（cases.json の docx のパスも OLD）。
   - **書き換え**: OLD がすでにある（symlink を作れない）か `--sed` を付けたときは、展開した `.py`・`.sh`・`.md`・`.js` の中の OLD を
     展開先に書き換える（100 ファイルほど）。道具は展開先のパスで動く。
   symlink は新しいセッションの作業用の場所の外（/tmp/claude-0/ の下）に作るので、許可を求められることがある。避けるなら `--sed` を付ける。
   以下の説明の **S** は、symlink のときは OLD（または展開先）、書き換えのときは展開先のこと。
   何度実行してもよい（あるものは作り直さない。手で直した新しいファイルは上書きしない）。かかる時間は 1〜2 分（fuzz を含めると 6〜7 分）。段:
   1. tools.tar.xz を展開先に展開する（道具・反例集・小さな入力・文書・`scripts/` のワークフローのスクリプトと、空の出力フォルダ）。
      このフォルダのファイルを 展開先/handoff_pkg/ に写す（tools.tar.xz は写さない）
   2. リンク（fixB2r4/base_src → n10/judge/base_src、fixB2r4/tools/docx → n10/judge/tools/docx）と、realpdf/check.py の写し
      （fixB2r4/realpdf・b21/isolate/realpdf に n10/judge/realpdf/check.py を写す）
   3. コードの写しを `git archive` で作る（作業ツリーには触らない）: n10/judge/base_src（0.20.0）、b21/base021_src（0.21.0）、
      oracle/wt_head（0.19.0 の全体。反例集の make_fixtures の予備と run_all8.sh の v019。git worktree ではない）、rvB_regress_mut/tests（0.19.0 の tests）
   4. python に jasme_jats がなければ `pip install -e ".[dev]"`。4b. Python 3.10 の venv（S/venv310。`uv venv -p 3.10`・`uv pip install -e ".[dev]"`）
   5. 本誌の出版版 PDF 5 本を tests/private/pdf/ に取る（`https://www.jstage.jst.go.jp/article/jasme/<巻>/<号>/<巻>_<開始ページ>/_pdf/-char/ja`。
      24/1/24_25・25/1/25_77・27/1/27_47・29/2/29_79・30/2/30_59。ファイル名は 24_1_24_25.pdf の形）。sha256 を pdf_sha256.txt と比べる
   6. make_inputs.py で入力の docx を作る
   7. regen_fuzz.sh --verify（fuzz4 の 8 組・fuzz8 の 81 組）
   8. golden の基準 S/n10/golden_base を 0.20.0 の src で作り、manifest.json を golden_base_manifest.json と比べる
   9. Colab のテストデータ1〜3 があるかを確かめる（ないときは下の手順で取る）
3. 戻らないもの（試作の src・前の結果）は下の「戻らないもの」。比べる相手の結果は、0.20.0（S/n10/judge/base_src）と 0.21.0（S/b21/base021_src）で
   流し直して作る（下の「版を比べる流れ」）。

### Colab のテストデータ1〜3（Google ドライブ。読むだけ。コミットしない）

利用者の Colab での試験に使った実際の原稿（未公開）と出版版 PDF。tests/private/colab/tdN/ に tdN.docx・tdN.pdf の名前で置く
（tests/private/ は .gitignore 済み）。

| | docx の ID（元の名前） | PDF の ID |
|---|---|---|
| td1 | `16iCdOFaQa9f-B4p2zk69y6xkTrE_EZ4R`（51_…_テンプレート適用.docx。題目の部分は論文の文字なので省いた） | `1Ij6E-Gdqms8ZP_z-l6n4SSCg9LweIHjL` |
| td2 | `1fWLHTSQZNuKs0M0s-jzuXnVzJnJR9Kze`（56_オンライン_…_正解版.docx） | `1CDJC6NyJzU0NiusOi7yhYS4g5y3PdNBN` |
| td3 | `1LPPbDYLpDXhF4RxT7ws6dwrN2xmPH6Rz`（JASME251_template_A_注は規定どおり.docx） | `12LA_HE5cVC3vOYjbzvmfnUVq9s3U7eIX` |

Claude が Google ドライブのコネクタで取る手順:
1. `mcp__Google_Drive__download_file_content`（`fileId` に上の ID。exportMimeType は付けない。docx・PDF はそのまま取れる）を呼ぶ。
   結果は base64 の文字を含む JSON で、大きいとき（td1 の docx は 3 MB）は結果がファイルに保存され、そのパスが示される。
2. その JSON から base64 の文字を取り出して戻し、置く。保存されたファイルが RESULT のときの例（JSON の項目の名前に頼らず、いちばん長い文字列を
   base64 とみなす）:
   ```bash
   mkdir -p /home/user/jstgxmlcng_JASME/tests/private/colab/td1
   python - RESULT /home/user/jstgxmlcng_JASME/tests/private/colab/td1/td1.docx <<'EOF'
   import base64, json, sys
   def strings(x):
       if isinstance(x, str):
           yield x
       elif isinstance(x, dict):
           for v in x.values():
               yield from strings(v)
       elif isinstance(x, list):
           for v in x:
               yield from strings(v)
   raw = open(sys.argv[1], encoding="utf-8").read()
   try:
       data = json.loads(raw)
   except ValueError:
       data = raw
   open(sys.argv[2], "wb").write(base64.b64decode(max(strings(data), key=len)))
   EOF
   ```
   結果がファイルに保存されず、その場に出たときは、その base64 の文字をファイルに書いてから同じように戻す。
3. `sha256sum` を td_sha256.txt と比べる（restore.sh を実行し直しても確かめられる）。td3.pdf は 25_1_25_77.pdf と同じファイル。

## 物差し（何を測るか・いつ使うか・合格の目安）

判定の言葉（どの物差しも同じ考え。段落ごとに、直した後の docx の文字を出版版の文字〈truth〉と比べる）:
- **OK**: 出版版と同じになった。
- **REPORTED / REP / MISS(13章)**: 同じにならなかったが、足し・消しはなく、その違いが 13 章に出ている（原則どおり。ただし利用者が手で直す箇所が増える）。
- **SILENT / MISS(黙って)**: 足し・消しはないが、違いが 13 章に出ていない（原則に反する。黙った違い）。
- **FAIL / VIOLATION**: docx にも PDF にもない文字を足した、または PDF にある docx の文字を消した（原則に反する）。

合格の目安（これまでの単位〈B・B2〉で反映の前に使ったもの。docs/FIX_PLAN.md の B2 の「確かめたこと」）: 新しい版を、いまの main（0.21.0）と
0.20.0 の両方と比べて、**FAIL・VIOLATION・SILENT が増えた例・段落がない**こと（増えたものは、1 つずつ原則に照らして説明できること）、
OK でなくなった例は 13 章に出ていること、golden が意図した節のほか同じこと、テストがすべて通ること（3.13 と 3.10）。

| 物差し（道具） | 何を測るか | いつ使うか | 比べ方・合格の目安 | 0.20.0 → 0.21.0 の値（出どころ） |
|---|---|---|---|---|
| テスト（リポジトリの tests。`S/fixB2r4/tools/pytest_src.sh <src> <python>`） | 単体テストを指定した src で（`WHICH` の行に読んだ jasme_jats が出る） | 変更のたび | すべて通る（python と S/venv310/bin/python の両方） | 0.21.0 で 566 件（FIX_PLAN の B2） |
| 反例集（oracle の形。`S/fixB2r4/tools/run_oracle.sh SRC TAG [組...]`。仕組みは `S/oracle/runner.py` の docstring） | 原則だけから期待を決めた架空の論文。反例ごとに OK・REPORTED・FAIL。組: o34（原則 34）・n10（146）・n10g（139）・rv89（28）・judge（39）・judge2（10）・b2（66）・x（264）・xm（5）・r1（38）・y（128）・y2（24） | 照合を変えたとき（毎回） | `python S/fixB2r4/tools/cmp_or.py f4r_{w}_<TAG1> f4r_{w}_<TAG2>`（{w} は組の名前。judge は cj、judge2 は cj2） で反例ごとに比べ、悪くなった反例 0。o34 は 34/34 OK のまま | o34 34/34 → 34/34、n10 OK73・REP12・FAIL61 → OK132・REP14・FAIL0、n10g 72・17・50 → 137・2・0、rv89 1・16・11 → 7・18・3、judge 25・1・13 → 34・4・1、judge2 4・0・6 → 8・1・1、b2 30・1・35 → 51・11・4（OLD/n10/judge/logs/*_base.log、OLD/fixB2r4/logs/*_isov021.log。束にない）。0.21.0 の x 196・52・16、xm 1・1・3、r1 30・7・1、y 108・20・0、y2 24・0・0 |
| quick（点検の例。`S/fixB2r4/tools/run_suites.sh SRC TAG quick 4` → `python S/fixB2r4/tools/sum_q.py base TAG`） | 点検の担当が作った小さな論文（36 ファイル。cases_*.py と fz*.json・bound*.json）を、照合と直す箇所だけで流し、段落ごとに OK・MISS(13章)・MISS(黙って)・VIOLATION | 照合を変えたとき | sum_q.py の「base より悪い段落」が 0（あれば -v で 1 つずつ見る） | 126,057 段落で、足す・消す 171 → 21、黙った違い 176 → 34（FIX_PLAN の B2） |
| 生成例（h2.py の形。`sh S/fixB2r4/gen.sh SRC TAG [名前...]`、`sh S/b2_review/r5p/run_gen.sh SRC TAG 名前...` → `python S/fixB2r4/tools/agg_gen.py TAG`・`cmp_gen.py`） | 段落の端・図・ページの区切りなどの配置を機械的に組み合わせた例（29 種・数千件）を、照合の段階だけで流し、例ごとに OK・REP・SILENT・FAIL | 段落の端・図のまわりの照合を変えたとき | 前の版より悪くなった例 0。FAIL を増やさない | 18 種 4,484 件で足す・消す 1,149 → 67（FIX_PLAN の B2）。head は 0.20.0 OK70・REP53・SILENT24・FAIL105 → 0.21.0 OK163・REP77・SILENT12・FAIL0（OLD/fixB2r4/logs/gen_head_isov021.log） |
| 乱数の例 fuzz4（`run_suites.sh SRC TAG f4 4` → `python S/fixB2r4/tools/sum_fz.py f4 base TAG`） | 無作為の架空の論文 2,400 本（8 組 × 300）。段落ごとに OK・MISS・VIOLATION、13 章に出たか | 照合を変えたとき | base より悪い段落 0、VIOLATION を増やさない | 足す・消す 16 → 1、13 章に出ない違い 18 → 1（FIX_PLAN の B2） |
| 乱数の例 fuzz8（`run_suites.sh SRC TAG f8 4` → `sum_fz.py f8 base TAG`、`viol_kinds.py`・`cmp_fz.py`・`added_count.py`） | 24,300 本（81 組 × 300。組版の文字・図表の文字の入れ方を増やしたもの） | 照合を変えたとき（4 並列で数分） | 同上 | 足す・消す 5,821 → 2,047、docx にも PDF にもない文字を足した 3,728 → 189、13 章に出ない 10,262 → 468（FIX_PLAN の B2・session_notes.md） |
| 210 件（`python -I S/fixB/fixB_all.py SRC OUT.json`、比べるのは `fixB_all.py --compare A.json B.json`） | 単位 B の 1 回目の点検の例（rvB2 の 13 組と rvB_regress_exp の 8 個）の直す箇所 | 照合を変えたとき | 前の版と違う例を 1 つずつ見て、どれもよくなったこと | 0.20.0 と違う 24 件はどれもよくなった（FIX_PLAN の B2） |
| golden（`cd S/n10 && PYTHONPATH=SRC python S/golden/golden.py OUT`） | tests/fixtures の 19 件の出力（XML・AI 依頼文・レポート）のハッシュ | 変更のたび | OUT/manifest.json を S/n10/golden_base/manifest.json（0.20.0）と比べ、違うのは意図したもの（レポートの節など）だけ | 0.21.0 は 19 件とも 0.20.0 と同じ |
| 本誌の出版版 PDF（`cd S/fixB2r4/realpdf && python -I check.py --before-src S/n10/judge/base_src --after-src SRC --route1 --tag _TAG`） | 公開済みの PDF 5 本（7 通り）から確かめ用 docx を作り、わざと入れた違いが期待どおり直るか、組版の文字を足さないか（out/summary_TAG.txt） | 照合を変えたとき（2 分ほど） | 「組版の文字による挿入・削除」0、「それ以外の想定外」0、わざと入れた違い（M1・E1・E2・E3）が期待どおり、見つからない段落 0 | 0.21.0 ですべて満たす（OLD/b21/isolate/realpdf/out/summary_isov021.txt、束にない。0.20.0 は 29 巻 79・30 巻 59 の 3 通りで想定外 2・4・4） |
| Colab のテストデータ1〜3（`sh S/fixB2r4/tools/run_td.sh SRC TAG`。b21 は `S/b21/isolate/tools/run_td.sh`・`tdcmp.py`） | 実際の原稿 3 本をルート2・ルート1 で変換し、照合の違い・直す箇所を JSON に（段落 ID と数だけを比べる） | 照合を変えたとき | 前の版と違う段落を 1 つずつ見て、原則に沿うこと（実際の論文の文字なので、出力は作業用の場所にだけ置く） | 0.21.0 で XML が 0.20.0 と違うのは td1 の d71、td2 の 3 段落だけ（FIX_PLAN の B2） |
| 速さ（`python -I S/fixB2r4/tools/t_small.py SRC`、`t_patho.py`、`t_speed.py`） | 照合の時間（小さな論文 100 本・悪い形・本誌の PDF 7 通り） | 照合を変えたとき | 0.20.0 から大きく遅くならない | 本誌の PDF 7 通りで 20 秒ほど → 1.8 秒ほど、小さな論文 100 本で 0.20.0 の 1.15 倍ほど（FIX_PLAN の B2） |

### 版を比べる流れ（例）

```bash
S=<道具の場所>   # symlink のときは OLD、書き換えのときは展開先
sh $S/fixB2r4/snap.sh mine                                   # 作業ツリーの src を S/fixB2r4/mine_src に写す
for x in base:$S/n10/judge/base_src v021:$S/b21/base021_src mine:$S/fixB2r4/mine_src; do
  sh $S/fixB2r4/tools/master_r4.sh ${x#*:} ${x%%:*}           # 物差しをすべて（quick・反例集・fuzz4・golden・210 件・fuzz8・実 PDF。1 版 10 分ほど）
done
python $S/fixB2r4/tools/sum_q.py base v021 mine                 # quick
python $S/fixB2r4/tools/cmp_or.py f4r_{w}_v021 f4r_{w}_mine     # 反例集（反例ごと）
python $S/fixB2r4/tools/sum_fz.py f8 base v021 mine             # fuzz8（f4 も）
sh $S/fixB2r4/gen.sh $S/fixB2r4/mine_src mine && python $S/fixB2r4/tools/agg_gen.py mine   # 生成例（agg_gen は base・cur の結果も要る）
```
結果は S/fixB2r4/{v,logs,gen}/、S/oracle/results_f4r_<組>_<TAG>.json、S/fixB2r4/realpdf/out/summary_<TAG>.txt。master_r4.sh の golden の結果は
S/fixB2r4/v/golden_<TAG>/manifest.json（S/n10/golden_base/manifest.json と比べる）。並列で 4 つほど python を動かすので、ほかの重い処理と重ねない。

## ワークフローのスクリプト（束の `scripts/`）

これまでの単位を進めたワークフローのスクリプトの写し（元は ~/.claude/projects/-home-user-jstgxmlcng-JASME/<セッション>/workflows/scripts/）。
どれも `args.scratch`（作業用の場所。S を渡す）を受ける（jasme-pdf-heads は `args.files`、jasme-fix-plan は `args.clusters` も）。
新しい単位のワークフローを作るときのひな形として読む（そのまま再開はできない。journal〈途中の結果〉は新しいセッションに残らない）。

| スクリプト | 何をしたか |
|---|---|
| `jasme-fix-plan-wf_28e4e16c-786.js` | レビューの指摘ごとに修正方針を設計し、反証で詰め、順序と抜けを点検する（docs/FIX_PLAN.md を作った） |
| `jasme-pdf-heads-wf_5f3f357a-203.js` | 本誌の出版版 PDF のページの上下の行（ページ番号・柱など）を調べる |
| `jasme-unit-a-wf_94467c7a-c7c.js` | 単位 A（0.19.0）の実装・3 観点の反証レビュー・修正 |
| `jasme-pdfmatch-oracle-wf_6d59e6cd-0b4.js` | 実装を見ない担当が作る反例集の仕組み（S/oracle）を作る |
| `jasme-unit-b-round2-wf_d3eaf4ab-097.js` | 単位 B（0.20.0）の 2 回目（反例集の 3 件の修正と点検） |
| `jasme-n10-design-wf_2727320d-3a2.js` | N10 の直し方の 3 案（reanchor・guard・joint）の試作と比べ（n10/DESIGN_N10.md） |
| `jasme-unit-b2-wf_f63b8706-843.js` | 単位 B2（0.21.0）: 設計 C の実装・確かめ・仕上げ・点検と修正（4 回） |
| `jasme-unit-b21-wf_04aeb00a-7bf.js` | 単位 B2.1（0.21.1）: N20 を一般的な守りで止める（3 案の試作・反証・実装・確かめ・点検）。束を作ったとき作業中 |

単位 B（0.20.0）の 1 回目のスクリプト（jasme-unit-b-wf_1938bdf8-7dd.js）は、本誌の出版版 PDF の本文・図のキャプション・受付日をそのまま書いた
例を含むので入れていない（下の「実際の論文の文字の確認」）。

## regen_fuzz.sh（乱数の例を作り直す）

```bash
[JASME_S=<道具の場所>] sh regen_fuzz.sh [--root DIR] [--force] [--verify] [名前...]   # 名前を省くと 89 組すべて（1 組 300 本で 3〜4 秒）
```
cases.json の中には docx の絶対パスが入る。`--root` の既定は JASME_S（既定は OLD）。`--verify` は、DIR が OLD でなければパスの前置きを OLD に
戻してから、束を作った時点の sha256 と比べる。生成器は /home/user/jstgxmlcng_JASME の tests/make_fixtures.py と src を読む。

組の名前と生成器・引数（cases.json の件数〈どれも 300〉・柱の文字・フォルダの名前と、生成したときのコマンドから割り出した。89 組すべてで確かめた）:

| 組 | 生成器 | 引数（件数 種 …） | 備考 |
|---|---|---|---|
| fuzz4 `c1` | S/rvB4_regress/fuzz/gen.py | 300 7 | c1 だけ種は 7（名前と違う） |
| fuzz4 `c8`・`c9`・`c10` | gen.py | 300 8 / 9 / 10 | |
| fuzz4 `dense31`・`dense32` | gen_dense.py | 300 31 / 32 | 校正の直しと表・図の文字を多く |
| fuzz4 `h39` | gen_head.py | 300 21 架空の論文の柱の文字列です | 名前の数は柱の文字の UTF-8 のバイト数（sh の `${#h}`） |
| fuzz4 `h60` | gen_head.py | 300 21 架空の論文の題目を短くした柱の文字列です | 同上 |
| fuzz8 `mix_301`・`caption_302`・`long_303`・`refs_304`・`nopage_305`・`mix_306` | S/rvB8_regress/fuzz8/gen8.py | 300 <種> <形> | run_all8.sh |
| fuzz8 `m_<形>_<種>`（形 mix・caption・long・refs・nopage、種 311〜325。75 組） | gen8.py | 300 <種> <形> | run_more8.sh（形ごとに種は同じ） |

fuzz8 の `t1`（20 本）は gen8.py の今の版より前に作ったもので、どの道具も使わない（`*_3[0-9][0-9]` だけを読む）。作り直さない。

## 束の中身（tools.tar.xz）

道具の一覧（作業用の場所からの相対パス。同じ名前のものが n10/judge/tools と fixB2r4/tools にあるときは、fixB2r4 が新しい版〈出力先が fixB2r4〉）:

- 物差しをまとめて流す: `fixB2r4/tools/master_r4.sh`（1 つの版ですべての物差しを順に。B2 の 4 回目の修正のときの最新）。`master_one.sh`・`master_r1.sh`・
  `master_r3.sh`・`master.sh` と `n10/judge/tools/master_one.sh`・`master.sh` は前の版（流す反例集の組が違う。master.sh は試作 R・G・J を流すので動かない）。
  `fixB2r4/tools/run_suites.sh`（quick・f4・f8・b210 を流す）、`qfiles.sh`（quick のファイルの一覧）
- 反例集: `oracle/runner.py`・`oracle/run_all.py`（仕組み）、`fixB2r4/tools/run_oracle.sh`（組を並列に）、`cmp_or.py`・`cmp_oracle.py`・`sub_or.py`・`strict.py`
  （比べる・前置きで絞る・途中まで直した段落を数える）。反例のファイル: `oracle/cases_seed.py`・`cases_artifact.py`・`cases_layout.py`・`cases_b2.py`
  （と同じ中身の控え `cases_b2.saved.py`）、`rvB2_principle_cases.py`、`n10/cases_n10.py`・`cases_n10_guard.py`・`cases_judge.py`・`cases_judge2.py`、
  `rvB8p/cases_rvB8p.py`、`rvB9p/cases_rvB9p_e1〜e6.py`、`rvB2x_principle_cases.py`・`rvB2x_math_cases.py`、`fixB2r1/cases/cases_r1_*.py`（3）、
  `b2_review/r2p/cases_y.py`・`cases_y2.py`
- quick: `fixB2r4/tools/quick.py`（流す）・`sum_q.py`（数える）。反例のファイル: `rvB2p/cases_*.py`（10）と `fz11・21〜23・101〜104.json`、
  `fixB3/cases_b3_edge.py`、`rvB8p/cases_h1〜h4.py`（6）、`rvB9p/cases_e1・e5・e6.py`・`bound1・2.json`、`rvB9_regress/cases_t1〜t5.py`、`n10/joint/cases_island.py`
- 生成例: `b2_review/r4p/h2.py`（流して判定）、`fixB2r4/gen.sh`・`b2_review/r5p/run_gen.sh`（まとめて流す）、`fixB2r4/tools/agg_gen.py`・`cmp_gen.py`（数える・比べる）。
  生成器 `gen_*.py`（29）: `b2_review/r3p/exp/`（tail・head・figsim・figpre・figstop・pages・dup。gen_tail.py がほかの土台）、`b2_review/r4p/exp/`（capnext・capprev・
  figwidth・figwidth_head）、`b2_review/r4reg/exp/`（bfp・figw・figw2・figw3・widow）、`b2_review/r5p/exp/`（r5better・r5copytop・r5face・r5headfig・r5simtop・
  r5tabhead）、`b2_review/r5reg/exp/`（r5_bl・r5_cnq・r5_cpo・r5_fw・r5_rw）、`fixB2r4/exp/`（bpage・figtop）。何を作るかは各ファイルの docstring
- 乱数の例: `rvB4_regress/fuzz/gen.py`・`gen_dense.py`・`gen_head.py`（fuzz4 の生成器）・`run.py`・`judge.py`（前の版の照合と判定）、
  `rvB8_regress/fuzz8/gen8.py`（fuzz8 の生成器）・`run8.py`・`runw8.py`・`judge8.py`（judge8 は sum_fz.py などが読む判定）・`run_all8.sh`・`run_more8.sh`・
  `sum8.sh`・`tradeoff8.py`（前の版の流し方）、`fixB2r4/tools/run8_all.py`（照合）、`sum_fz.py`・`cmp_fz.py`・`viol_kinds.py`・`viol_samples.py`・`added_count.py`（数える）
- 210 件: `fixB/fixB_all.py`、`rvB2/rvB2_run.py`・`rvB2_mk.py`・`rvB2_mkdocx.py`・`rvB2_common.py`・`rvB2_cases_*.py`（13）、`rvB_regress_exp.py`
- golden: `golden/golden.py`
- 本誌の出版版 PDF: `n10/judge/realpdf/check.py`（今の版。restore.sh が fixB2r4/realpdf と b21/isolate/realpdf に写す）、`realpdf_B/check.py`（単位 B のときの版。
  --after-src・--tag がない）、`fixB2r4/tools/cmp_real.py`（結果を 2 つの版で比べる）・`run_real.sh`（試作を流す。前の版）
- Colab のテストデータ: `fixB2r4/tools/run_td.sh`・`td_cmp_compare.py`（変換して照合の結果を JSON に）、`td_c5.py`・`td_paras.py`・`cmp_fixed.py`・`chunks.py`・
  `pgrep.py`・`r12.py`（直し方の一貫性・段落の比べ・PDF の検索・13 章の段落 ID の突き合わせ。文字は端末にだけ出す。cmp_fixed.py は束にない出力を読む）
- 速さ・テスト: `fixB2r4/tools/t_small.py`・`t_small_min.py`・`t_patho.py`・`t_speed.py`（t_speed は fixB2r1 の realpdf/out/docx を読むので、先に check.py を流す）、
  `pytest_src.sh`・`pt/judge_which.py`（`n10/pytest_src.sh` も）、`fixB2r4/snap.sh`（作業ツリーの src を写す）
- 単位 B2.1 の写し（作業中）: `b21/isolate/`（tools・cases_iso*.py・exp。`tools/master_iso.sh` が物差しをまとめて流す）、`b21/ambiguity/`（tools・cases・exp）。
  `b2_review/r4p/cases_w_only.py`・`r5p/cases_v_only.py` はそこから読む
- 文書: `n10/DESIGN_N10.md`、`session_notes.md`、`handoff/README.md`・`handoff/STATUS_2026-10-18.md`
- ワークフローのスクリプト: `scripts/*.js`（8。上の表）
- 空の出力フォルダ（道具がそのまま書けるように）: fixB2r4/{logs,gen,v/{q,f4,f8},td,realpdf/out}、n10/judge/{logs,v/{q,f4,f8},tmp,tools/docx,realpdf/out}、
  oracle/_work、realpdf_B/out、rvB2/docx、rvB_regress_exp_out、b2_review/r5p/logs、b21/{isolate/{logs,gen,td},ambiguity/{logs,gen}}

## 外したもの

- 出力・結果: logs/・v/・gen/・out/・td/・tmp/・oracle/_work/・*.log・結果の json（oracle/results_*.json、fz_*_<TAG>.json、f4・f8・q の結果など）。
  比べる相手が要るときは流し直す。単位 B2 の点検の結果（OLD/b2_review/review_*・recheck*_*・fix*_result.json・workflow_final.json）も入れていない
  （workflow_final.json・review_user_result.json・finalize_result.json は実際の論文の文字を含む。残った指摘〈N20〉は docs/FIX_PLAN.md の B2.1 の節にある）。
- コードの写し: *_src（試作の版）・src・wt_*・*_snapshot、venv310、__pycache__、jasme_jats のモジュールの写し 2 つ（b21/ambiguity/exp/pdfmatch_p10.py・
  b21/isolate/exp/pdfmatch_src_switches.py）。0.19.0〜0.21.0 の src と tests の写しは restore.sh が git archive で作る。
- docx・pdf・xml・zip・png・jpg、*.patch・*.diff・*.txt。fuzz の cases.json と docx（regen_fuzz.sh で作り直す）。
- 文書以外の .md（変換のレポートなど。実際の論文の文字が入っている）。
- realpdf/check.py の写し（どれも n10/judge/realpdf/check.py と同じ中身。restore.sh が要るものを写す）。
- 実際の論文の文字のために外したもの: ワークフローのスクリプト jasme-unit-b-wf_1938bdf8-7dd.js（と、単位 B2 の点検の結果 3 つ）。

## 戻らないもの（作り直せないもの）

- 試作・途中の版の src: fixB2r4/prev_src（→ fixB2r3/vF_src。B2 の 3 回目の修正の版）・v10_src・v11_src、n10/judge の R・G・J・C_src（N10 の 3 案と組み合わせ C）、
  b21 の試作（isolate/src_*・ambiguity/p*_src など）、b2_review/*/cur_src・proto*_src、run_all8.sh・run_more8.sh の CUR（rvB8_regress/t_cur/src）・PRE（fixB2/before_src）。
- 結果（比べる相手の base・cur など）: 流し直す。t_speed.py・cmp_fixed.py・td_paras.py が読む出力（realpdf/out/docx・colab_v20・fix_verify）も流し直す。
- ワークフローの journal（途中の結果。~/.claude/projects/.../workflows/wf_*.json）。fuzz8 の t1。

## 確かめたこと（2026-10-19 14:20〜15:10 UTC、Python 3.13.16）

- **作り直し（2026-10-19 21:30 UTC。単位 B2.1 を点検の途中で止めた後）**: pack.sh で束を作り直した（399 ファイル・27 フォルダ。B2.1 の各担当の道具・
  反例・`b21/DESIGN_B21.md`・`oracle/cases_b21.py`・`b21/judge/cases_judge21.py` が増えた）。leakcheck.py は 399 ファイルを調べ、一致のあるファイル 67。
  リポジトリにない一致のあるファイルは 24 個で、どれも下の (a)〜(c) の種類。B2.1 で増えたファイルにはない。restore_test.sh は 3 通りとも下と同じ結果
  （終了コード 0、反例集・生成例・quick・210 件の数も同じ）。B2.1 の担当の結果（journal の result）は、束ではなく `docs/fix_plan_work/b21/results/` に置いた。
  以下は 14:20〜15:10 UTC に確かめたこと（数はそのときのもの）。

- **fuzz の作り直し**: fuzz4 の 8 組と fuzz8 の 81 組の **89 組すべて**で、regen_fuzz.sh で作り直した cases.json の sha256 が束を作った時点のもの
  （fuzz_sha256.txt）と一致した。作り直しは regen_check/ の下にだけ作り、`unshare -m` の名前空間で regen_check の組を元の組のフォルダの上に bind mount して、
  元と同じパスで作った（ほかのプロセスからは元のフォルダのまま。元の cases.json 89 個が変わっていないことも確かめた）。各組の case0000.docx もバイトまで同じ
  （make_fixtures の docx は毎回同じバイト）。`--root` で別の場所に作った c8・m_refs_312 も、パスの前置きを戻すと一致した。
- **golden の基準**: restore.sh で 0.20.0 の src から作り直した n10/golden_base が、全ファイル（manifest と 19 件の XML・レポート・AI 依頼文）でバイトまで同じだった。
- **入力の docx**: make_inputs.py で作った 10 個と、210 件を流したときに作られる rvB2/docx の 54 個の数が元と同じ（make_inputs の 10 個はバイトまで同じ）。
- **展開の確かめ**（build/restore_test.sh）: このプロセスだけの mount 名前空間で 3 通りを試した。どれも restore.sh（venv310 と fuzz の全体を除く）が最後まで通り、
  PDF 5 本・td1〜3 の sha256 一致、golden の manifest 一致、fuzz 2 組（c1・caption_302）の sha256 一致。主な道具を 0.20.0（n10/judge/base_src）で流した結果が、
  元の作業用の場所にある 0.20.0 の結果と同じだった（run_oracle.sh の o34 34 件・b2 66 件の判定が反例ごとに同じ〈元: OLD/oracle/results_judge_o34_base.json・
  results_b2r2_b2_base.json〉、gen.sh head の結果の JSON が同じ〈OLD/b2_review/r3p/exp/fz_head_base.json〉、quick の rvB2p/cases_bound が同じ
  〈OLD/fixB2r4/v/q/rvB2p_cases_bound_base.json〉、fixB_all.py の 210 件が同じ〈OLD/fixB2r4/v/fixB210_base.json〉）。
  - same: 展開先 = OLD（restore_test を OLD の上に bind mount。OLD には束から戻したものしかない）
  - link: 展開先 = /media（restore_test を bind mount）、OLD を含むフォルダを空の tmpfs で隠した形（新しいコンテナの形）。restore.sh が OLD → /media の symlink を作り、
    道具は OLD のパスで動いた
  - sed: link と同じ形で OLD に空のフォルダを置いた形（symlink を作れない形）。restore.sh が 100 ファイルの OLD を /media に書き換え、道具は /media のパスで動いた
    （OLD は空なので、書き換え漏れがあれば失敗する。展開先の .py・.sh に OLD は残っていなかった）
  venv310 は作らなかった（`uv pip install -e` がリポジトリの src/jasme_jats.egg-info を書き換えるため。手順は docs/HANDOFF.md と同じ）。
  確かめた後、restore_test と regen_check は消した。記録は build/regen_all.log（89 組）・build/regen_root.log・build/restore_test.out（3 通り）。
- **実際の論文の文字の確認**（build/leakcheck.py）: 束の 241 ファイルを、本誌の出版版 PDF 5 本と td1〜3 の PDF・docx（docx は XML のすべての段落の文字）と比べた
  （空白を除き、12 文字の窓。NFKC で寄せた形でも。.py は文字列リテラルをつないだ形とコメント、.json はすべての文字列も見る）。
  - 12 文字以上一致した部分のあるファイルは 66。多くはリポジトリにも入っている文字（誌名の行、受付日の行の形、URL の頭など）だけ。
  - リポジトリにない一致は次の 3 種類だけで、論文の本文を書き写したものではない（だから外していない）:
    (a) 一般的な言い回しや英単語の 12〜16 文字（研究の目的を述べる文末の定型、「〜と考えられる。」の形、英語のよくある 2 語の並び、
    文の終わりのすぐ後に引用文献の見出しが続く形など。n10/cases_judge*.py・cases_n10.py・oracle/cases_layout.py・cases_b2.py・rvB2x_principle_cases.py・
    rvB2p/fz*.json・rvB9p/bound*.json・rvB4_regress/fuzz/gen.py・rvB8_regress/fuzz8/gen8.py）、
    (b) 本誌の書式（組版の文字）をまねた行: 24 巻 1 号の誌名の行（巻・号・年・ページ）と受理日の形（oracle/runner.py の journal_line の既定値、
    cases_seed.py・cases_artifact.py の received_old、scripts/jasme-pdfmatch-oracle-wf_6d59e6cd-0b4.js）。どれも J-STAGE で公開されている書誌の文字、
    (c) 引用文献の書式の断片（『…研究』，第 N 巻，第 N 号，pp. の並び。rvB2p/cases_refs2.py・fz*.json）。
  - n10/judge/realpdf/check.py と realpdf_B/check.py は、出版版 PDF の中の位置を示す短い語（わざと入れる違いの語）を含むが、8 文字以上の一致は
    リポジトリにもある文字だけだった。
  - 外したもの: scripts の jasme-unit-b-wf_1938bdf8-7dd.js（出版版 PDF 2 本の本文の文〈受付日の行とつながった形〉・図のキャプションを 16〜57 文字そのまま含む）。
  - この README と handoff_pkg のほかのファイルも同じように確かめた（リポジトリにもある文字だけ）。
  - 一致した文字そのものは端末にだけ出す（`python -I build/leakcheck.py build/filelist.txt --show`。filelist は pack.sh が作る）。

## 束を作り直す

```bash
sh <S>/handoff_pkg/build/pack.sh     # trace.py で一覧 → leakcheck.py → tools.tar.xz・tools.tar.xz.sha256
```
新しいファイルを道具に足したら、build/trace.py の SEEDS（出発点）に足すか、道具から参照する。leak_summary.txt の一致は毎回見て、論文の本文があれば
そのファイルを外す（pack.sh の stage や trace.py の RESTORED・exclude）。作り直した後は build/restore_test.sh で 3 通りを確かめる。
