# 修正計画（2026-11 の別の AI による点検に基づく）

- 作成: 2026-11-06。対象: `main` の 0.29.0（コミット d81c378）。この計画の時点では、コードは変えていない。
- 2026-11-06 に、テンプレートのローカルのパスを取り除くため `git` の履歴を書き換えた（下の「履歴の書き換え」）。コミットのハッシュはすべて変わり、文書の中のハッシュは新しいものに直した。
- 付属:
  - 単位ごとの設計書: [fix_plan_2026-11/units/](fix_plan_2026-11/units/)（実装者はこれを読んで実装する。設計に点検の直しを入れたもの）
  - 計画づくりに使った試作・再現のスクリプト: [fix_plan_2026-11/protos/](fix_plan_2026-11/protos/)（手本として読むもの。scratchpad のパスを前提に書かれていて、出力・生成物は残していない。スクリプトは scratchpad が /tmp/scratchpad にある前提で書かれている）
- 文中の行番号は 0.29.0 のもの。

## この計画の作り方

1. 別の AI の点検の指摘 10 件を、コードを読んで確かめ、`docs/REVIEW_2026-11.md` の既存の項目と突き合わせた。指摘 7〜10 と 2 は既存の項目（K10・R6・A9・K1/K2・K7/K12）で、新しい指摘は 1・3・4・5・6 の 5 件。
2. 利用者から受け取った再現スクリプト（`tests/private/review-repros/reproduce.py`）を、この環境で 0.29.0 に対して動かし、10 件すべてが報告どおりに再現した。
3. 7 つの単位に分け、単位ごとに 1 人（Opus）が、再現・原因・直し方の設計・試作を行った。試作を当てて既存のテスト 1298 件が通ることも確かめた。
   実際の原稿（`tests/private` のテストデータ1〜5 とテンプレート。利用者の許可済み）で、各問題の件数と、直した後に出力が変わらないかを数えた。
4. 単位ごとに別の 1 人（Opus）が反証の立場で点検した（原則・回帰・利用者向けの観点）。7 単位とも「直せば実装してよい」で、そのまま実装すると原則違反・誤った出力・回帰になる指摘（blocker）は 0 件、直すべき指摘（major）は 20 件。
   さらに 1 人が、単位どうしの食い違い（同じファイル・同じ関数を触る順、知らせの並び、守りと中止の順序、版の分け方、計画の抜け）を点検した。
5. 計画者（Opus）がまとめ、単位ごとの設計書に点検の直しを入れた（設計と点検が食い違うところは点検を、単位の点検と単位どうしの点検が食い違うところは後者を採った）。

計画は公開リポジトリに載るので、実際の原稿については、テストデータの番号・件数・段落 ID だけを書き、本文の文字・ファイル名・著者名は書かない。

## 決めたこと

### 利用者の決定（2026-11-06）

1. 後付けの見出しが同じ種類で 2 つある原稿（K1）と、所属だけの段落・行が続く原稿（K2）は、**検出したら変換を中止する**（終了コード 2。XML・ZIP・レポートを作らない）。原因の段落と Word での直し方を示す。
2. Word でトリミングした画像は、**自動で切り取って出力し、要確認で知らせる**。
3. 理由が「位置づけが不明」の除外は**要確認**で知らせる。英文要旨が 1 段落もなく、英文の部分に除外があるときは**要対応**。
4. 注の節の中の表は、**XML に出す**（`<fn><p><table-wrap>`。DTD で妥当なことを確かめた）。
5. `tests/private` の実際の原稿（Google ドライブの「J-Stage変換開発用資料/テスト用ファイル」とテンプレート）は、テストで断りなく使ってよい。非公開のまま使う。

### 計画者の決定（変えたいときは、実装の前に言ってください）

| 単位 | 決めたこと | 理由 |
|---|---|---|
| u1 | AI の回答の `operations` を必須にする（操作がなくても `[]`）。最上位が一覧（`[ ]`）の回答は読まない | 4 つの API の構造化出力・手動の依頼文のどれもが `operations` を必ず書く形。推測で補わない原則と同じ |
| u1 | 子要素の足りない `w:lvlOverride/w:lvl` は、書かれた子要素だけを `abstractNum` の段の定義に重ねる | 既定値で置き換えると番号が空になり、知らせなしに消える（試作で確かめた）。Word の動きは未確認なので、安全な方を選んだ |
| u1 | テンプレートの fixture を新しい `sanitize_docx.py` で整え直し、fixture 15 件を作り直す | 公開リポジトリの fixture 15 件すべてに、Windows のユーザー名を含むローカルのパスが残っていた（2026-11-06 に履歴ごと取り除いた。下の「履歴の書き換え」）。u1 では、ほかの作成者情報（ヘッダー/フッター・customXml・文書のプロパティ）も新しい sanitize で取り除く |
| u2 | 入力が前回の変換から変わっていたら、「反映」「画像を入れる」「結果をダウンロード」（「このままダウンロード」でも）を断る。入力を戻せば続けられる | 別の論文の docx と前の書誌情報・前の論文の AI の回答が混ざっても、検証では見つからない |
| u2 | AI の回答と依頼文の結び付け（依頼文に印を入れて回答に返させる）は今回は入れず、REVIEW に新しい項目として記録する | 依頼文・回答の形・検証に触れる大きな変更になる。1 画面版の混ざりは、入力の写しと前の論文の回答の確かめで塞げる |
| u3-autonum | 題目・副題・著者名・所属の段落の Word の自動番号は XML に出さず、10 章の警告にする | J-STAGE の書誌に番号が入るのを避ける |
| u3-autonum | 付記・謝辞・注・引用文献・英文要旨の見出しの番号は、`<title>` の先頭の生成文字にする | これらの `<label>` を J-STAGE が表示するかを確かめていない |
| u3-autonum | 自動番号の出力漏れの守り（要対応）の文には、「XML に手で番号を補う」逃げ道を書かない | ほかの「変換ツールの不具合の可能性」の知らせと同じく、開発者に知らせるだけにする |
| u4 | 切り取れない画像（EMF/WMF、Exif の向きのある写真など）は ZIP に入れず、「用意が必要な画像」（要対応）にする。AI にも渡さない | Word で見せていない部分を外に出さない |
| u4 | 回転・反転・色の効果は反映せず、要確認で知らせる。負の `srcRect`（余白を足す指定）は 0 として知らせる | 実際の原稿に例がなく、Word の表示と同じにできる確かな方法がない |
| u5 | `jasme.toml` の styles に、英文要旨のスタイルの別名「英文要約見出し」「英文要約」を足す。誌名行（`front_lines`）を設定に足す | テンプレート（完成版）が英文要旨にこのスタイル名を使っていて、今は英文要旨が黙って落ちる |
| u5 | 注の節の表は、判断の一覧（4 章）に記録するだけで要確認は出さない。最初の注より前の表は、最初の注の 1 段落目の後ろに入れる | 注の番号を `<fn>` の先頭に保つ。J-STAGE の表示は試験登載で確かめる（利用者に聞くことの 3） |
| u6 | 英文要旨の見出しが 2 つある形も中止に含める。前か後ろの同じ種類の見出しが空白だけなら、中止せず空白の段落として除外に記録する | 英文要旨の見出しも K1 と同じ上書きの仕組みで落ちる。空白だけの見出しで止めると、テンプレートの空の見出しが残った原稿まで止まる |
| u6 | AI の `set_role` で K1・K2 の形ができたら、その範囲の `set_role` を不採用にして組み直し、なお残れば `set_role` をすべて不採用にする | docx 自体の衝突は AI の前に中止するので、AI の後の衝突は AI の指定が原因 |
| u6 | REVIEW の O7（ルート2 で中止しても補った docx が残る）も、中止の後始末と一緒に直す | 同じ場所で 1〜2 行で直せる |
| 共通 | `CLAUDE.md` は実装者が直さない。直す案の文を設計書に書き、利用者の承認を待つ（利用者に聞くことの 2） | `CLAUDE.md` は利用者の判断で変える文書 |

## 項目の一覧

「指摘」は別の AI の点検の番号、「REVIEW」は `docs/REVIEW_2026-11.md` の番号。N は計画づくりで見つけたもの。

| ID | 内容 | 指摘・REVIEW | 単位 | 版 | 実際の原稿での件数 |
|---|---|---|---|---|---|
| 1 | `sanitize_docx.py` に入力と同じ出力先を渡すと、読む前に原稿を切り詰める | 指摘 1 | u1 | 0.30.0 | （開発用ツール） |
| 2a | 注の節の表の文字が、知らせなく除外される | 指摘 2・K7 | u5 | 0.31.0 | 0 |
| 2b | 見出しがなく標準スタイルの英文要旨が、知らせなく除外される | 指摘 2・K12 | u5 | 0.31.0 | テンプレート 1（N9） |
| 2c | 理由が「位置づけが不明」の除外に知らせがない | 指摘 2 | u5 | 0.31.0 | 0（テストデータ1〜5） |
| 3 | Word でトリミングした画像が、切り取り前のまま出力される | 指摘 3 | u4 | 0.30.0 | 4 枚（テストデータ3 の 3 件・テストデータ5） |
| 4 | 1 画面版で入力を変えて「反映」すると、別の論文に前の書誌情報・前の論文の AI の回答が当たる | 指摘 4・O3 | u2 | 0.30.0 | テストデータ1→2 で再現（段落 ID の 98% が重なり、AI の除外 3 件が別の論文に当たった） |
| 5 | すべて縦結合の継続の行が消え、`rowspan` が残って表の形が崩れる | 指摘 5 | u3-tables | 0.30.0 | 0 |
| 6 | 表のセルの段落の Word の自動番号が XML に出ない | 指摘 6 | u3-autonum | 0.30.0 | 27 段落（テストデータ1 の 5、テストデータ2 の 2 件で 11 ずつ） |
| 7 | 同じ著者・同じ年の引用文献の曖昧さを、候補の先頭と末尾だけで判定する | 指摘 7・K10 | u1 | 0.30.0 | 0（引用 750 件で変化なし） |
| 8 | `w:lvlOverride/w:lvl`（番号の書式の上書き）を無視する | 指摘 8・R6 | u1 | 0.30.0 | 0 |
| 9 | 最上位が一覧の AI の回答を、操作 0 件・知らせなしで通す | 指摘 9・A9 | u1 | 0.30.0 | — |
| 10 | 後付けの見出しの重複・連続する所属で、段落が落ちる（原因が利用者に伝わらない） | 指摘 10・K1・K2 | u6 | 0.31.0 | 0（92 回の変換で、検出と不変性チェックの不合格が完全に一致） |
| N1 | `sanitize_docx.py` がヘッダー/フッター・customXml・テンプレートのパス・題目（`dc:title`・`TitlesOfParts`）を取り除かない。公開の fixture 15 件にユーザー名を含むローカルのパス（パスは 2026-11-06 に履歴ごと取り除いた） | O5 | u1 | 0.30.0 | 原稿 10 件すべてに残る |
| N2 | 深い入れ子の AI の回答で `RecursionError` が捕まらず変換が止まる | A10 | u1 | 0.30.0 | — |
| N3 | `operations` の要素が `{ }` でない操作を黙って捨てる | — | u1 | 0.30.0 | — |
| N4 | 1 画面版: API キーを読めずに止まった後・`split_labels`/作り方を変えた後・回答の欄に残った前の論文の回答でも混ざる。docx の欄を空にすると「不具合」の案内が出る | — | u2 | 0.30.0 | — |
| N5 | 従来のノートブック: 途中で止まった手順の後ろの手順が、前の結果のまま進める | — | u2 | 0.30.0 | — |
| N6 | 表: `w:gridBefore`・`w:gridAfter` を読まない、幅の違う縦結合の継続、横に広いセルが結合元を覆う、見出し行から本文の行へ続く縦結合で、表の形が崩れる | — | u3-tables | 0.30.0 | 0 |
| N7 | Word の自動番号が、キャプション・引用・別行数式・英文要旨・注の 2 段落目以降・後付けの見出しでも XML に出ない | — | u3-autonum | 0.30.0 | 0 |
| N8 | 1 つの図形に画像が複数あると、画像の大きさが 0 になる（AI の依頼文の「0.0cm×0.0cm」） | — | u4 | 0.30.0 | 0 |
| N9 | テンプレート（完成版）の英文要旨のスタイル名が `jasme.toml` にないため、英文要旨が黙って落ちる | （K12 の実例） | u5 | 0.31.0 | テンプレート 1 |
| N10 | 英文要旨の見出しが 2 つあると、先の見出しが落ちる（K1 と同じ仕組み） | — | u6 | 0.31.0 | 0 |
| N11 | AI の `set_role` で K1・K2 の形ができ、今は原因の分からない不合格になる | — | u6 | 0.31.0 | — |
| N12 | ルート2 で中止しても、補った docx が出力フォルダに残る | O7 | u6 | 0.31.0 | — |
| N13 | 全角空白だけ・空の後付けの見出しが、本物の見出しの前か後ろにあると、不変性チェックが不合格になる（前の空白は missing、後ろの空白は前の本物の見出しが落ちる） | — | u6 | 0.31.0 | 0 |

直さずに REVIEW に記録するもの（単位の設計書の「新しく見つけた問題」）: AI の回答と依頼文の結び付け（コマンドラインの `--ai-response` を含む）、
英文の部分にスタイルがない原稿で英文の題目・著者・要旨が引用文献に入る、`numbering.py` が番号の段の隠し文字（`w:vanish`）を見ない、
コマンドラインで前の変換の出力が残ることがある、`attachedTemplate` 以外の外部ターゲットのローカルのパス（警告だけ）、ほか。

## 単位と担当

モデル・エフォートは、作る人（実装）と点検する人。点検は、CLAUDE.md の「原則・回帰・利用者向けの観点」で行い、修正と再点検は最大 3 回まで（収束しなければ反映せず、利用者に相談する）。

| 単位 | 版 | 内容 | 作る | Opus が自分で書く部分 | 点検 |
|---|---|---|---|---|---|
| [u1-small](fix_plan_2026-11/units/u1-small.md) | 0.30.0 | (1a) sanitize・(1b) AI の回答の形・(1c) 引用文献の曖昧さ・(1d) 自動番号の上書き | (1a)(1b)(1d) Sonnet・medium、(1c) Haiku・low | なし | Opus・medium |
| [u2-app](fix_plan_2026-11/units/u2-app.md) | 0.30.0 | 1 画面版の入力の写しと、ノートブックの手順の印 | Sonnet・medium | なし | Opus・medium |
| [u3-tables](fix_plan_2026-11/units/u3-tables.md) | 0.30.0 | 表の縦結合・飛ばしたグリッドと、表の形の確かめ | Sonnet・high | なし | Opus・medium |
| [u3-autonum](fix_plan_2026-11/units/u3-autonum.md) | 0.30.0 | 自動番号の出力漏れと、自動番号の出力の確かめ | Sonnet・medium | なし | Opus・medium |
| [u4-crop](fix_plan_2026-11/units/u4-crop.md) | 0.30.0 | トリミングした画像の切り取り | Sonnet・medium | なし（知らせの文は点検で Opus が確かめる） | Opus・medium |
| [u5-exclusions](fix_plan_2026-11/units/u5-exclusions.md) | 0.31.0 | 「位置づけが不明」の除外の知らせ・英文要旨・注の節の表 | Sonnet・high | `structure.Classifier.build_back` の注の表の枝と `builder.fn` の書き出し順 | Opus・high |
| [u6-k1k2](fix_plan_2026-11/units/u6-k1k2.md) | 0.31.0 | K1・K2 を検出して中止 | Sonnet・high | `pipeline.convert` の AI の後の衝突の組み直しと、`report.structure_conflict_text` の Word での直し方の文、案内どおりに直した docx が合格するテスト（`test_advice_fixed_docx_passes`） | Opus・high |
| 共通 | 各版 | 回帰の基準を取るスクリプトと比較 | Sonnet・low | 想定外の違いの判断 | — |
| 共通 | 各版 | 版上げ・ノートブックの作り直し | Haiku・low | — | — |
| 共通 | 各版 | 文書（DEVELOPMENT・ARCHITECTURE・DESIGN・STYLE_MAPPING・USAGE・USAGE_AI・JSTAGE_NOTES・GUI_PLAN・REVIEW）をまとめて直す | Opus・medium | すべて | — |
| 共通 | 各版 | 版全体の最後の点検（3 つの観点） | — | — | Opus・high |

各単位の要点（詳しくは単位の設計書）:

### [単位 u1-small（0.30.0）: 小さい独立の修正（sanitize・AI の回答の形・引用文献の曖昧さ・自動番号の上書き）](fix_plan_2026-11/units/u1-small.md)

- 目的: 互いに独立した 4 つの小さい不具合を直す。(1a) `tools/sanitize_docx.py` が入力と出力に同じファイルを指定すると原稿を壊す・個人情報を取り残す（O5）。
  (1b) `ai_assist.parse_response` が最上位が一覧（`[ ]`）の回答や `operations` のない回答を「操作 0 件」で黙って通し（A9）、深い入れ子の回答で変換が `RecursionError` で止まる（A10）。
  (1c) `refparse.match_citation` が同じ第一著者・同じ年の文献 3 件以上で曖昧さを取り違える（K10）。(1d) `numbering.py` が `w:lvlOverride/w:lvl` を無視する（R6）。
- 直し方: (1a) sanitize を lxml で作り直し、同じファイルを断り、一時ファイルに書いて本文の文字が同じことを確かめてから置き換える。変更履歴の作成者・ヘッダー/フッターの文字（ページ番号のフィールドは残す）・customXml・
  テンプレートのパス・文書のプロパティ（題目を含む）を取り除く。テンプレートの fixture を sanitize し直して fixture を作り直す（`sample_pdfcheck.pdf` は git で戻す）。
  (1b) 最上位の一覧を断り、`operations` を必須にし、`RecursionError` を読めない回答として扱う。`split_ops` の `{ }` でない操作は `outcome.rejected` に理由付きで記録する。
  (1c) 最大の当てはまりの候補の数で曖昧さを決める。(1d) 上書きの `w:lvl` に書かれた子要素だけを `abstractNum` の段の値に重ねる。
- 実際の原稿での影響: 出力（XML）の違いは 0 件。tests/private の docx 10 件（テストデータ1〜5 の 9 件とテンプレート）すべてに sanitize で取り除く個人情報があった。
  引用の照合 750 件で K10 の直しによる違いは 0 件、`w:lvlOverride` は 0 件。公開リポジトリのテンプレートと fixture 14 件にあったユーザー名を含むローカルのパスは、2026-11-06 に履歴ごと取り除いた（計画の「履歴の書き換え」）。
- 順: 0.30.0 の最初の commit は (1a)（sanitize と fixture の作り直し）だけにし、その直後に 0.29.0 のコードで回帰の基準を取る。(1b)(1c)(1d) は u2 と並行してよい。版は 0.30.0 の最後に 1 回だけ上げる。
- 担当: 作るのは (1a)(1b)(1d) が Sonnet（エフォート medium）、(1c)（4 行の直しとテスト）が Haiku（エフォート low）。点検は Opus（エフォート medium）。Opus が自分で書く部分はない。
  点検で見るのは (1a) ヘッダー/フッターのフィールドの判定と作り直した fixture の `git diff --stat`、(1b) `parse_cut_response` の一覧の判定と深い入れ子の期待（`None`）、(1d) `_levels` が `self.abstract` の共有の dict を書き換えていないこと。

### [単位 u2-app（0.30.0）: 1 画面版で入力を変えた後の結果の混ざり（と従来のノートブックの手順の印）](fix_plan_2026-11/units/u2-app.md)

- 目的: 1 画面版（`app.AppState`）で変換した後に入力（docx・PDF・ページ・日付・作り方など）を変えて「反映」「画像を入れる」「結果をダウンロード」を押すと、前回の変換の meta・回答・画像と今の docx・設定が 1 回の変換に混ざる。別の論文の段落が AI の除外として XML から消えても、不変性チェック・DTD は合格し、知らせも出ない。REVIEW の O3（変換の後に AI の方法のラジオを変えると画面が矛盾する）も同じ根で、あわせて直す。従来のノートブックで、途中で止まった手順の後も後ろの手順の「済み」（`DONE`）が残る穴も直す。
- 直し方: 変換したときの入力の写し `RunInputs`（ファイルは中身の sha256 で比べる）を `AppState.run` に持ち、`_run`・`apply_answer`・`add_images`・`download` はこの写しだけを使う。入力が写しと違えば、結果を残したまま理由の文で断る（「このままダウンロード」でも断る）。手動かどうかは写しで決める（O3）。`convert()` は確かめが済むまで前の結果を変えない。別の論文に変えて変換したら回答の欄を空にし、前に別の依頼文へ反映したのと同じ文字の回答は断る（依頼文の digest で結び付ける）。ノートブックは各手順の先頭で自分より後ろの `DONE` を消す（`unmark`）。
- 出力の形は変わらない（XML・レポート・ZIP の中身は同じ）。`report.actions()` に Action は足さない（画面の状態の表示）。
- 実際の原稿での影響: テストデータ1 → テストデータ2 の切り替えでは、本文の段落 ID が 135 件中 132 件重なり、前の論文用の set_role exclude 3 件がすべて採用されてテストデータ2 の段落が 3 つ消えた（fpage も前の値のまま）。テストデータ2 → テストデータ1 では 3 件とも不採用。どちらも混ざったことの知らせはなかった。修正後は、どちらの経路も「入力が前回の変換から変わっています」で断る。
- 担当: 作るのは Sonnet（エフォート medium）、点検は Opus（エフォート medium）。Opus が自分で書く部分はない。点検では `convert()` の手順の順、`on_convert` の 3 つの経路の戻り、crash の後の `view()` が例外を出さないこと、`CRASH_ADVICE` の各案内が新しい状態と合うことを見る。
- 触るファイル: `src/jasme_jats/app.py`、`tools/make_notebook.py`、`tests/test_app.py`、`tests/test_notebook.py`。文書（USAGE・ARCHITECTURE・DEVELOPMENT・REVIEW・GUI_PLAN）は版の最後にまとめて直す。

### [単位 u3-tables（0.30.0）: 表の縦結合・飛ばしたグリッドと、表の形の確かめ](fix_plan_2026-11/units/u3-tables.md)

- 目的: 表の組み立て（`builder.Builder.table`）が、縦結合（`w:vMerge`）と行の前後で飛ばしたグリッド（`w:gridBefore`・`w:gridAfter`）で表の形を崩す不具合を直す（指摘 5・N6）。
  すべてのセルが結合の継続の行を消しても `rowspan` が元の行数のまま残る、見出し行（thead）から本文の行（tbody）へ `rowspan` がはみ出す、幅の違う継続を結合する、横に広いセルが結合元の列を覆っても結合が続く、`gridBefore`・`gridAfter` を読まずに行が左に詰まる、の 5 つ。
  どれも不変性チェック（文字だけを見る）と DTD 検証（要素の並びだけを見る）を通り、利用者に知らされない。あわせて、出力した表の形を変換の後に確かめる守り `pipeline.table_problems` を足し、崩れていれば要対応 `table_shape`（変換ツールの不具合の可能性）で知らせる。
- 直し方: 読み取りで `Row.grid_before`・`grid_after`・`number` を読み、`gridSpan` の不正な値（0・負・数でない）を 1 にそろえる。`Builder.table` は、結合元を「開始列 → (セル, 幅)」で覚えて行ごとに作り直し、幅が同じ継続だけを結合し、本文の 1 行目で結合を止め、`rowspan` は出力する行だけで数え、飛ばしたグリッドは空のセルで埋める。
  `table_problems(root, info)` は builder の結合の判断に頼らず、docx の行ごとの列の数と HTML の表の割り当て（行ごとの列の数・セルの重なり・節の外へのはみ出し・セルのない行）だけで判定する。
  見出し行をまたぐ結合を止めたとき・幅の違う継続を結合しなかったときは 10 章の警告（Action にしない）。文字を書き換える箇所はない（足すのは空のセルだけ）。
- 実際の原稿での影響: 0 件。tests/private の docx 10 件（出力の表 59 個）と fixtures 15 件（計 101 個）に、崩れる形（gridBefore・gridAfter・幅の違う継続・見出し行をまたぐ結合・すべて継続の行など）は 1 つもない。
  試作では 25 件の出力 XML が 0.29.0 とバイト単位で同じで、表の形の確かめは 0 件も鳴らなかった（全テストの 653 回の変換の表 468 個でも 0 件）。基準との比較で想定する違いは 0。
- 順: 0.30.0 の中で u1 の (1a) と基準取りの後、**u3-tables → u3-autonum → u4** の最初に実装する（builder.py・model.py・pipeline.py・report.py・docx_reader.py・structure.py・make_fixtures.py をこの単位が最初に触る）。
- 担当: 作るのは Sonnet（エフォート high）。点検は Opus（エフォート medium）。Opus が自分で書く部分はない。
  点検で Opus が確かめるのは、(1) `Builder.table` の結合の規則が試作（`docs/fix_plan_2026-11/protos/u3-tables/proto.py`）に点検の直しを加えた答えと同じになるか（テストの場合と点検の edge・edge2 の場合）、(2) `table_problems` が builder の判断に頼らず docx の行の列数と HTML の割り当てだけで判定しているか、(3) fixtures と tests/private の出力が基準とバイト単位で同じか。

### [単位 u3-autonum（0.30.0）: Word の自動番号の出力漏れ（表のセルほか）と、自動番号の出力の確かめ](fix_plan_2026-11/units/u3-autonum.md)

- 目的: Word の自動番号（`Para.autonum`）が、表のセル・キャプション・引用・別行数式・英文要旨・注の 2 段落目以降・後付けの見出しなどで
  XML に出ず、知らせもない不具合を直す。番号は docx の文字ではなく生成文字（`jx:gen`）なので、不変性チェックも 8 章も気づけない。
- 直し方: 番号を書く処理を `Builder.autonum_mark`（段落の先頭に生成文字で補う）・`Builder.caption`（キャプションの番号は `<label>`）・
  `Builder.heading_title`（後付け・英文要旨の見出しは `<title>` の先頭）にまとめ、`Emitter.gen` に段落 ID（`src`）を持たせる。
  題目・副題・著者名・所属の番号は出さず（J-STAGE の書誌に番号が入らないように）、`BuildInfo.unshown_numbers` に記録して 10 章の警告にする。
  組み立ての後に、文字を出したのに番号の `jx:gen` がない段落を `pipeline.lost_autonums()` が数え、要対応 `autonum_lost` で知らせる（終了コード 1）。
- 実際の原稿での影響: 今のコードで番号が落ちているのは表のセルだけで、テストデータ1 が 5 段落、テストデータ2 の 2 つの docx が各 11 段落
  （ルート1・ルート2 とも同じ）。直すと自動番号の生成文字はテストデータ1 で 4→9、テストデータ2 で 6→17 になる。fixture 15 件の XML は変わらない。
  試作では、実際の原稿 16 回・fixture・監査の docx のすべてで不変性チェック・最終出力の再チェック・DTD・補完の確かめが合格し、守りの誤報は 0。
- ルート2: セルの段落は PDF と照合しない（`pdfmatch.target_paragraphs` の外）ので、セルの番号は Word の形のまま。照合・直しのコードは変えない。
- 順: builder.py・model.py・pipeline.py・report.py を u3-tables の後、u4 の前に直す（同じ作業の枝で単位ごとに commit。版は 0.30.0 の最後に 1 回）。
- 担当: 作るのは Sonnet（エフォート medium）。点検は Opus（エフォート medium）。Opus が自分で書く部分はない。
  点検で見るのは、`fn` の 1 段落目の番号（二重に出さないことと区切りの空白）、`caption` の分岐と u3-tables の `table_wrap` との合わせ方、
  `unshown_number` を呼ぶ 4 か所、`lost_autonums` が最後の組み立ての `root`・`info`・`plan` を使っていること。

### [単位 u4-crop（0.30.0）: Word でトリミングした画像の切り取り](fix_plan_2026-11/units/u4-crop.md)

- 目的: Word でトリミングした画像が、切り取る前のまま `Graphics/` と ZIP に入り（Word で隠した部分が J-STAGE で公開される）、知らせもない不具合を直す。
  Word のトリミングは画像ファイルを変えず、表示のときに `a:srcRect`（VML は `v:imagedata` の `crop*`）の割合で切り取るだけなので、docx の画像は常に切り取る前のもの。
- 直し方: 読み取り（`docx_reader._graphic`）で切り取りの割合と「反映しない Word の加工」（回転・反転・色の変更など）を `ImageRef.crop`・`ImageRef.edits` に記録し、
  書き出し（`images.export_images`）で Pillow で切り取る（`images.crop_image`）。出力ファイル名・拡張子・XML の `xlink:href` は変えない。
  切り取って出力した画像は要確認 `image_crop`、加工を反映していない画像は要確認 `image_edits`。切り取れない画像（EMF/WMF、Exif の向きのある写真、
  動く GIF、保存できない形式など）は ZIP に入れず、切り取る前の画像を `要変換/` に置いて「用意が必要な画像」（既存の要対応 `images`）にする。
  AI にも Word の表示どおりに切り取った画像を渡し、切り取れない画像は渡さない（AI には依頼文の文字だけ）。文字には触れないので、不変性チェック・ルート2 に影響しない。
- 一緒に直す: 1 つの `w:drawing` に `pic` が複数あるとき、`a:blip` の `a:extLst/a:ext` を拾って画像の大きさが 0 になる不具合（グループの縮尺も掛ける）。
  `images_action` の文の「画像（PNG）」と「docx に画像ファイルがない」を、切り取れなかった JPEG にも合う文に直す。
- 実際の原稿での影響: 切り取りのある画像はテストデータ3 の 3 つの docx（各 1 枚）とテストデータ5（1 枚）。今は 590×438・1636×556 のまま出力しているものが、
  Word の表示どおり 534×401・1308×556 になり、状態が ok → converted、要確認 `image_crop` が 1 件ずつ増える（終了コードは変わらない）。ほかの 30 枚（4 辺とも 0 の空の指定 21 枚を含む）は今と同じバイト列。
  回転・反転・色の効果・負の値・VML の切り取り・Exif の向きは実際の原稿に 0 件。fixture 15 件の XML と画像は変わらない。
- 順: model.py・docx_reader.py・report.py は u3-tables・u3-autonum の後に、ai_assist.py は u1 の後に直す（同じ作業の枝で単位ごとに commit。版は 0.30.0 の最後に 1 回）。
- 担当: 作るのは Sonnet（エフォート medium）。点検は Opus（エフォート medium）。Opus が自分で書く部分はない（文はこの設計書のものをそのまま使う）。
  点検で Opus が見るのは、`image_crop`・`image_edits`・`images_action` の文（top・checklist・box_detail・cli の書き分けと目印 `step()`）、
  切り取れないときに failed へ進む経路（`crop_image` の例外の扱い、`要変換/` の置き方、ZIP に入らないこと）、AI に切り取れない画像を渡さないこと。

### [単位 u5-exclusions（0.31.0）: 「位置づけが不明」の除外の知らせ・英文要旨が見つからないとき・注の節の表](fix_plan_2026-11/units/u5-exclusions.md)

- 目的: 構造の組み立てで役割を決められずに除いた段落（後付けの表・英文の部分の段落など）が、6 章に載るだけで知らせがない不具合を直す（K7・K12）。
  不変性チェックは除外に記録した段落を正しいものとして数えるので、今は合格し、要対応にも要確認にもならない。
- 直し方: 除外の理由を structure.py の定数にし、「位置を決められない」理由の集合 `UNPLACED_EXCLUSIONS` で要確認 `excluded_unsure` を出す。
  英文要旨が 1 段落もなく英文の部分に除外があるときは要対応 `abstract_missing`（終了コード 1）。冒頭部の装飾（誌名行・記号だけの行）は
  `front_decoration` と jasme.toml の `front_lines` で見分け、知らせない。注の節の中の表は `FnNode.tables` に入れて `<fn><p><table-wrap>` で出し、
  判断の一覧（4 章）に記録する（最初の注より前の表は最初の注の 1 段落目の後ろ）。jasme.toml の styles に「英文要約見出し」「英文要約」を別名で足す。
- docx の文字は 1 文字も変えない。段落の役割と入れ先を変えるだけで、表のセルは今までどおり `builder.table_wrap` → `Emitter.span` で書く。
- 実際の原稿での影響: テストデータ1〜5 の 9 件と fixture 15 件は、XML・除外・知らせとも変わらない（「位置づけが不明」の除外は 0 件。冒頭部の 3 件はすべて装飾と判定）。
  tests/private のテンプレートだけが変わり、別名で英文要旨（見出し d87・段落 d88）と資料 2 つ（d90 と表 T2、d186 と表 T3）ができ、英文の部分の除外（段落 4・セル 121）は 0 になる。
  注の節の中の表・本文と後付けの間の段落は、実際の原稿にはない。
- 順: u3-tables → u3-autonum（0.30.0）の後、u6 の前に実装する（同じ作業の枝で単位ごとに commit。版は 0.31.0 の最後に 1 回）。
- 担当: 作るのは Sonnet（エフォート high）、点検は Opus（エフォート high）。Opus が自分で書くのは `structure.Classifier.build_back` の注の表の枝
  （`pending`・`fn_role`・`flush`・キャプションだけの注を作らない条件・各表の `plan.decide`）と、`builder.fn` の表の書き出し順（直し方 4.6）。点検では、不変性チェック（出力した段落を除外に記録しない）・
  DTD・注の数・注の番号が `<fn>` の先頭に来ることを、直し方 4.8 の 6 つの形で確かめる。

### [単位 u6-k1k2（0.31.0）: 後付けの見出しの重複・連続する所属を検出して変換を中止する](fix_plan_2026-11/units/u6-k1k2.md)

- 目的: 後付けの見出し（付記・謝辞・注・引用文献）が同じ種類で 2 つあるとき（K1）や、著者名の付かない所属の段落・行があるとき（K2）は、構造の組み立てが前の値を上書きして捨て、その段落の文字が XML にも除外の記録にも入らない。今は最後の不変性チェック（`fidelity.missing`）でしか見つからず、利用者には「変換ツールの不具合の可能性」としか伝わらない。英文要旨の見出しが 2 つある形も同じ仕組みで落ちるので、一緒に扱う。
- 直し方: 上書きが起きる 5 か所（`build_back` の 4 か所と `build_front_en` の英文要旨の見出し）と所属の 2 経路（段落・著者表）で、「その段落が出力も除外もされなくなる」ときだけ `ArticlePlan.structure_conflicts` に記録する。`pipeline.convert` は `_mechanical` の直後に新しい例外 `StructureConflictError` で中止する（終了コード 2、XML・ZIP・レポートを作らない）。文には箇所ごとの段落 ID・抜粋・Word での直し方を書く。前か後ろの見出しが空白だけなら中止せず、空白の除外にする。
- ルート2 は補った docx を作る前に元の docx で確かめる。同じ場所で O7（`AIRequiredError` で中止しても補った docx が残る）も直す。
- AI の `set_role` で衝突ができたら、衝突の範囲（前付けの中にとどめる）の `set_role` を不採用（2 章）にして組み直し、なお残れば `set_role` をすべて不採用にして組み直す。その先は守りの raise だけ。
- `report.actions()` には何も足さない（中止は `AIRequiredError` と同じ例外の表示）。
- 実際の原稿での影響: tests/private の docx 9 件とテンプレート（ルート1 10 回、ルート2 6 回）で検出 0 件・missing 0 件。止まる原稿はない。試作で 92 回の変換を走らせ、検出した 31 件はすべて今の不変性チェックが不合格の形で、落ちる段落 ID の集合が一致した（不一致 0）。止まるのは今も要対応 fidelity で止まっている原稿だけ。
- 担当: 作るのは Sonnet（エフォート high）、点検は Opus（エフォート high）。Opus が自分で書く（または最終の文を決める）部分は、`pipeline.convert` の AI の後の 2 段の組み直し、`report.structure_conflict_text` の種類ごとの直し方の文、案内どおりに直した docx が合格することを確かめるテスト。
- 順: 0.31.0 の中で u5 の後に実装する（`build_back` の同じ枝・`app.py`・`article.py`・`report.py` を u5 の後に触る）。

## 反映の順序

作業の枝で単位ごとに commit し、版を上げるのは版の最後に 1 回だけにする。`main` への反映（利用者の Colab にすぐ届く）は、版の最後に利用者の確認を得てから行う。

### 0.30.0

1. **u1 の (1a) だけを最初の commit にする**（`tools/sanitize_docx.py`、テンプレートの整え直し、`python tests/make_fixtures.py` での fixture の作り直し。LibreOffice が作り直す `sample_pdfcheck.pdf` は `git checkout` で戻す）。
2. **回帰の基準を取る**: 0.29.0 のコードのまま、変換の設定は AI は manual・回答なし、`convert_metafiles=False` にして、作り直した fixture 15 件と `tests/private` の docx 10 件（ルート1。PDF のあるテストデータ1・2・3 の 6 件はルート2 も）を変換し、
   XML のハッシュ・`actions()` の key と level・除外の理由ごとの件数・警告の件数・ZIP の一覧と画像のハッシュ・終了コードを scratchpad に保存する（原稿の本文は保存しない）。
3. 並行してよい（触るファイルが重ならない）: u1 の (1b)(1c)(1d)、u2。
4. 続けて実装する（`builder.py`・`model.py`・`pipeline.py`・`report.py` を順に直すため）: **u3-tables → u3-autonum → u4**。
5. 単位ごとに、全テストと、1 つ前の commit の出力との比較で、想定した違いだけであることを確かめる（下の「想定した違い」）。
6. 版を 0.30.0 に上げる → `python tools/make_notebook.py` → 全テスト → 文書をまとめて直す → 版全体の点検 → 利用者の確認 → `main` に反映。

### 0.31.0（0.30.0 を反映した後の `main` から）

7. 0.31.0 の基準は、0.30.0 を反映した `main` で取り直す。
8. **u5 → u6** の順（どちらも `structure.Classifier.build_back` の見出しの枝を直す。見出しの枝の並び: 分岐の前は今のまま（文字から推定したときの decide → `state = BACK_HEADINGS[heading]` → `plan.region[b.src] = state`）→ 種類ごとの分岐で `if self.replace_back(kind, old, b, role): plan.X = b`（u6）と `plan.locations[b.src] = …`・注の節が引用文献の後ろのときの decide（今のまま）→ `self._heading_by_text[b.src] = role not in BACK_HEADINGS`（u6）→ `flush()`（u5）→ `current_fn = None` → `continue`。）
9. 両方を入れた状態で、u6 の検出の sweep（fixtures と `tests/private`、ルート1・ルート2。検出 0・不合格 0）と u5 の除外の件数をもう一度取る。
10. 版を 0.31.0 に上げる → ノートブックの作り直し → 全テスト・基準との比較 → 文書 → 版全体の点検 → 利用者の確認 → `main` に反映。

### 同じファイルを触る順

| ファイル | 順 |
|---|---|
| `builder.py` | u3-tables → u3-autonum → u5 |
| `model.py` | u3-tables → u3-autonum → u4 |
| `docx_reader.py` | u3-tables → u4 |
| `pipeline.py` | u3-tables → u3-autonum → u6 |
| `report.py` | u3-tables → u3-autonum → u4 → u5 → u6 |
| `ai_assist.py` | u1 → u4 → u5 |
| `structure.py` | u3-tables → u5 → u6 |
| `article.py` | u5 → u6 |
| `app.py` | u2 → u5 → u6 |
| `tools/make_notebook.py` | u2 → u6 |
| `tests/make_fixtures.py` | u1（作り直しだけ）→ u3-tables（`table_row`）→ u4（`drawing` の引数・`vml_image`・`pic_group`・`two_tone`）→ u6（`front_ja_rows`・`front_en_rows`）（どれも既定の出力を変えない。新しい docx は `tmp_path` に作る） |

### 想定した違い（基準との比較）

| 単位 | 出力が変わる原稿 |
|---|---|
| u1 | なし（実際の原稿・fixture に `lvlOverride` も、同じ著者・同じ年の文献の 3 件以上もない） |
| u2 | なし（画面の状態だけ） |
| u3-tables | なし（25 件の出力 XML がバイト単位で同じことを試作で確かめた） |
| u3-autonum | テストデータ1・2 の表のセルの自動番号（生成した文字）だけ |
| u4 | テストデータ3（3 件）・テストデータ5 の切り取った画像と、要確認 `image_crop` だけ |
| u5 | tests/private のテンプレート（完成版）だけ: 別名で英文要旨（見出しと段落）と資料 2 つ（表 2 個）ができ、英文の部分の除外が 0 になる。知らせは増えない（fixture のテンプレートは変わらない） |
| u6 | なし |

## 決めた並び・順序

### `pipeline.convert` の中の順序

1. ルート2: 元の docx を `_mechanical` する → 衝突があれば `StructureConflictError` → 図表の位置が決まらず AI を使わないなら `AIRequiredError`（O7: 補った docx を作る前に止める）→ `make_fixed_docx`。
2. `_mechanical` → 衝突があれば（補った docx を作っていれば消してから）`StructureConflictError` → `AIRequiredError`（同じく補った docx を消してから）。
3. `build`。
4. AI: 回答を読む → `split_ops` → 上書き → `_mechanical` → 衝突の組み直し（範囲の `set_role` の不採用 → `set_role` をすべて不採用 → 守りの `raise`）→ `retarget_ops` → 図表の位置の採用の記録 → `apply_ops` → `build`。
5. PDF との照合と、`pdf_numbers` での `build`。
6. 不変性チェック・`finalize`・DTD 検証と取り消し（`build` のやり直し）。
7. 補完の確かめ（ルート2）。
8. 守り: `lost_images` → `table_problems` → `lost_autonums`（この 3 つは並べて書き、最後の木と `BuildInfo` を使う）。
9. `export_images`（u4 の切り取り）→ `write_package` → `Result` → レポート。

`Result`・`BuildInfo` に足す欄は、どれも既定値つきにする（模擬の `Result` を作る既存のテストを壊さない）。

### `report.actions()` の並び

fidelity, supplement, dtd, **table_shape**（u3-tables）, upload, ai_error, ai_pending, partial, forced, figbody, textbox_undecided, textbox_place, textbox_figure_text,
**excluded_unsure**（u5）, images, lost, **autonum_lost**（u3-autonum）, **abstract_missing**（u5）, **image_crop**, **image_edits**（u4）, style_hidden, abstract_ja,
app_after_refs, note_overlap, float_ref, fn_guess, newline、その後ろに pdf_actions（今のまま）。

| key | 重さ | 章 | 単位 |
|---|---|---|---|
| `table_shape` | 要対応 | 12 章（見出しの文字は変えず「表の形の確かめ」の節を足す） | u3-tables |
| `autonum_lost` | 要対応 | 8 章 | u3-autonum |
| `image_crop` | 要確認 | 9 章 | u4 |
| `image_edits` | 要確認 | 9 章 | u4 |
| `excluded_unsure` | 要確認 | 6 章 | u5 |
| `abstract_missing` | 要対応 | 6 章 | u5 |

Action にしないもの: 10 章の警告（見出し行をまたぐ結合を止めた・幅の違う継続を結合しなかった〈u3-tables〉、題目・著者名・所属の自動番号を出さなかった〈u3-autonum〉）、
4 章の判断の一覧（注の表〈u5〉）、2 章の不採用（`{ }` でない操作〈u1〉、衝突の範囲の `set_role`〈u6〉）、中止（`StructureConflictError`・`AIRequiredError`。例外の表示）。
`app.AppState.REPASTE_KEYS` に足すのは `abstract_missing` だけ。新しい目印（`report.step`）は足さない。

## 共通の作業

- **`tests/private` の用意**（クラウドのセッションは毎回新しい環境なので、実装を始めるときに取り込み直す）: Google ドライブの「J-Stage変換開発用資料/テスト用ファイル」の 5 つのフォルダ
  （テストデータ1〜5）を `tests/private/テストデータN/` に、親フォルダのテンプレート 2 件を `tests/private/テンプレート/` に、
  「J-Stage変換開発用資料/レビュー再現_2026-11/jasme-review-repros/reproduce.py」を `tests/private/review-repros/reproduce.py` に置く（取り込んだ写しの `ROOT` だけを `Path(__file__).resolve().parents[3]` に直す。ドライブの元のファイルは変えない。項目を消すかは利用者に聞くことの 4）。
  ドライブのコネクタの `download_file_content` は、大きいファイルを JSON（`content` が base64）でファイルに保存するので、Python で読んで書き出す。
- **テスト**: 単位ごとに `python -m pytest -q` をすべて通す（今は 1298 件）。新しい Action が fixture で鳴らないこと（並びを確かめる既存のテストで分かる）と、`tests/test_syntax.py`（Python 3.10 で読める書き方）も確かめる。
- **回帰の比較**: 上の「回帰の基準」と、1 つ前の commit の出力を比べ、想定した違いだけであることを報告する。
- **知らせの文の決まり**: 画面の操作は目印 `report.step()` で書く（使うのは既存の `docx`・`ai_choose`・`answer_apply`・`convert_again`・`prompt`・`apply_button`・`pdf`）。レポートの本文（冒頭・14 章）は目印を使わず両方の画面の言い方で書く。生のタグは `report.md_tag()`。f 文字列の式の中にバックスラッシュと外側と同じ引用符を書かない。
- **AI の回答のテスト**: 0.30.0 から `operations` が必須になるので、テストの回答は必ず `{"placements": […], "operations": […], "notes": []}` の形にする。
- **版上げ**: 版の最後に 1 回だけ、`src/jasme_jats/__init__.py` と `pyproject.toml` の両方。
- **ノートブック**: 版の最後に `python tools/make_notebook.py`（ipynb を直接直さない）。
- **文書**: 版の最後に 1 人（Opus）がまとめて直す。`ARCHITECTURE.md`（行数の表・`Result` の欄・`actions()` の並び・`convert` の段階）、`DEVELOPMENT.md`（守るべき原則 3 に表の形・自動番号の守りと除外の理由、原則 8 の注に中止、原則 8 の `app.AppState.REPASTE_KEYS` の一覧に `abstract_missing`〈0.31.0〉）、`DESIGN.md`、`STYLE_MAPPING.md`、
  `USAGE.md`（0.30.0 で `table_shape`・`autonum_lost`・`image_crop`・`image_edits`、0.31.0 で `excluded_unsure`・`abstract_missing` と K1・K2 の中止）、`USAGE_AI.md`（u1）、`JSTAGE_NOTES.md`（u5）、`GUI_PLAN.md`（u2）。
- **REVIEW の記録**: 直したもの（0.30.0: O5・A9・A10・K10・R6・O3・指摘 1・3・4・5・6、0.31.0: K7・K12・K1・K2・O7）と、新しく見つけて直さないもの（上の「直さずに REVIEW に記録するもの」）を `docs/REVIEW_2026-11.md` に書く。
- **再現スクリプト**: 架空の docx で作れる項目（ai-array・sanitize-same-path・reference・app-input-change・merge・cell-number・crop・note-table・abstract-plain・number-override・repeated-headings・consecutive-affiliations）は、単位ごとに `tests/` の正式なテストにする。`tests/private/review-repros/reproduce.py` はそのまま残す（0.31.0 からは repeated-headings・consecutive-affiliations で `StructureConflictError` になる）。
- **最後の報告**: 見つけた文書とコードの食い違いを、直したものも直さなかったものもすべて挙げる（単位の設計書の「文書とコードの食い違い」を集める）。

## 確かめていないこと

- J-STAGE が `<fn><p><table-wrap>`（注の中の表）と、`<title>` の先頭に置いた後付けの見出しの番号を表示するか（試験登載で確かめる）。
- Word が、子要素の足りない `w:lvlOverride/w:lvl`、結合元のない縦結合の継続、JPEG の Exif の向きを、どう表示するか。
- 新しい `sanitize_docx.py` で整えた docx を、Word で開けるか（利用者が一度開いて確かめる）。
- Pillow の新しい版での 16 ビットの PNG などの保存（新しい環境のテストで確かめる）。

## 利用者に聞くこと

1. ~~公開リポジトリの fixture に残っているローカルのパスを、`git` の履歴からも消すか。~~ → **済み**（2026-11-06。利用者の回答「履歴も書き換えて、今後のファイルも消す」。下の「履歴の書き換え」）。
2. **`CLAUDE.md` を次のように直してよいか**（実装者は直さず、承認を得てから版の最後に直す）。
   (1)「不変性チェックは文字しか見ない」の行に、表の形の崩れ（`pipeline.table_problems`）と Word の自動番号の出力漏れ（`pipeline.lost_autonums`）も要対応として知らせることを足す。
   (2) ルート2 で「Word が付ける番号を PDF に合わせる」のは、PDF と照合する段落だけ（表のセル・囲み・別行数式の段落と、後付けと英文要旨の見出しの番号は Word の形のまま）と書く（今のコードの動きに合わせる）。
   (3) 終了コード 2（中止）に、原稿の構造（同じ種類の後付けの見出しが 2 つ・著者の付かない所属。K1・K2）による中止を加える。
   (4)（0.30.0。u4）「アップロード用 ZIP に入れるものは…」の項の後ろに、「Word でトリミングした画像は、Word で表示される範囲に切り取って入れ（要確認）、切り取れないもの（EMF/WMF など）は入れずに「用意が必要な画像」（要対応）にする（`images.crop_image`）。Word で隠した部分は ZIP にも AI にも渡さない。」を足す。
   (5)（0.31.0。u5）最優先の原則の 2 つ目の箇条の後ろに、「論文の中の位置を決められずに除く段落は、`structure.UNPLACED_EXCLUSIONS` の理由で記録し、要確認（`excluded_unsure`）で知らせる。英文要旨が 1 段落もなく英文の部分を除いたときは要対応（`abstract_missing`）。」を足す。
   (1)(2)(4) は 0.30.0、(3)(5) は 0.31.0 の最後に聞く。
3. **試験登載で確かめてもらえるか**: 注の中の表（`<fn><p><table-wrap>`）と、付記・謝辞・注・引用文献の見出しの自動番号（見出しの先頭の文字）が、J-STAGE の画面に表示されるか。確かめられるまでは、判断の一覧（4 章）に記録するだけにする。
4. ~~再現スクリプト（tests/private/review-repros/reproduce.py）のうち、tests/ の正式なテストに移した項目を、利用者が reproduce.py から消す形でよいか。~~ → （済み。2026-11-08 の利用者の回答: ドライブの元の reproduce.py は点検の記録として残す。項目は消さない。tests/private の写しは実装する側で扱う）

## 履歴の書き換え（2026-11-06）

利用者の回答（「履歴も書き換えて、今後のファイルも消す」）に従い、テンプレートのローカルのパス（Windows のユーザー名を含む）を、
`git` の履歴と今のファイルの両方から取り除いた。

- 取り除いたもの: docx の `word/_rels/settings.xml.rels` の `attachedTemplate` の外部の関係（テンプレートの場所）と、
  それを指す `word/settings.xml` の `w:attachedTemplate`。ほかの部品は中身を変えていない（本文の文字・画像・スタイルなどは同じ）。
  対象は、全ブランチの全コミットの docx（`tests/fixtures/` の 15 件とその過去の版、過去の作業用フォルダ `docs/fix_plan_work/` の docx。計 106 のパス）。
- やり方: `git filter-repo --blob-callback`（docx の ZIP を開いて上の 2 つの部品だけを直す）。12 のブランチすべてを `--force-with-lease` で置き換えた。
- 確かめたこと: 書き換えの前と後で、154 のコミットのどれでも、違うのは docx の 2 つの部品だけ（ほかのファイル・部品・コミットの作成者と日時は同じ）。
  書き換えた `main` で全テスト 1298 件が合格。GitHub から取り直した全ブランチの blob 1607 個に、ユーザー名・パスは 0 件。
- 変わったこと: すべてのコミットのハッシュ（例: `main` の 0.29.0 は 5c55945 → d81c378）。文書（FIX_PLAN.md・GUI_PLAN.md・REVIEW_2026-11.md・この計画）と
  `colab.py`・`test_colab.py` のコメントにある古いハッシュは、新しいものに直した（この枝の commit。`main` には 0.30.0 と一緒に入る）。
  手元にクローンがあれば、取り直す（`git fetch` の後に `git reset --hard origin/main`）。Colab は実行のたびに `main` から入れるので影響しない。
- **残っているもの**: 統合済みの PR 1（`refs/pull/1/head`）は GitHub が読み取り専用で持つ参照で、書き換え前のコミット（e4222ed）を指したまま。
  PR 1 の画面や古いコミットのハッシュの URL からは、書き換え前の docx をまだ取り出せる。これを消すには、リポジトリの持ち主が GitHub Support に
  「Removing sensitive data」として依頼する（リポジトリ名、PR 1、書き換え前のコミット e4222ed などを伝える）。フォークがあれば、そちらにも残る。
- `tools/sanitize_docx.py` はまだ `attachedTemplate` を取り除かない（u1 で直す）。それまでに docx をリポジトリに加えるときは、`word/_rels/settings.xml.rels` を確かめる。
  → 0.30.0 の u1 で直した（`attachedTemplate` とその関係を取り除く）。

## 0.30.0 の実装で設計書と違えたところ（2026-11-08）

単位の設計書（`fix_plan_2026-11/units/`）は計画の記録として直さずに残し、実装（作業の枝の 0.30.0）と違うところをここに挙げる。
文書（docs/）は実装に合わせて直した（`docs/REVIEW_2026-11.md` の「0.30.0 での直し方」）。

実装が設計書と違うもの:

| 単位 | 設計書の記述 | 実装 |
|---|---|---|
| u3-tables | 「直し方 5.2」と「利用者向けの文」: 12 章の「表の形の確かめ」で、表がなければ「出力した表はありません。」 | 「形を確かめた表はありません（表がないか、変更履歴ですべての行が削除された表だけです）。」（すべての行が削除された表は数えないので、表があってもこの文になる） |
| u1-small | テスト `test_same_author_year_ambiguity_uses_all_best_candidates`（K10） | `tests/test_refparse.py` の `test_same_year_ties_ignore_lower_candidates`・`test_same_year_low_high_low_is_exact`・`test_same_year_two_tied_top_candidates_ambiguous`・`test_same_year_coauthored_citation_picks_coauthored_among_three`・`test_same_year_two_candidates_unchanged` に分けた |
| u3-autonum | テスト `test_guard_uses_final_tree`（最後の組み立ての木を使うこと） | `tests/test_lost_autonums.py` の `test_guard_uses_final_tree_after_dtd_retraction`（DTD に合わない数式の取り消しの後）と `test_guard_uses_final_tree_after_route2_numbers`（ルート2 で番号を PDF に合わせた後）に分けた |

文書の更新の案と違えたもの（コードの書き方に合わせた）:

| 単位 | 設計書の「文書の更新」の案 | 直した形 |
|---|---|---|
| u3-autonum | `docs/DESIGN.md` 3 章の処理の流れに「自動番号の出力漏れの検出」を 10. として足し、後ろの番号を送る | `pipeline.py` の docstring が 9. に `lost_images`・`table_problems`・`lost_autonums` をまとめているので、DESIGN.md も 9. にまとめた（番号は送らない） |
| u3-autonum | 「`docs/DEVELOPMENT.md` の 43 行目の『ルート2 で Word の番号…を PDF に合わせるときは』を絞る」 | この文は `docs/DESIGN.md` の 43 行目（3 章）にあった。DESIGN.md の側を直した |
| u2-app | `docs/REVIEW_2026-11.md` に、直したもの（入力の混ざり・前の回答・ノートブックの「済み」）を O 系の続きの番号（O15〜）で足す | 点検の一覧（2026-11-03 の点検の分類）に後から番号を足さず、この計画の番号（指摘 4・N4・N5）で「0.30.0 での直し方」に書いた |
| u1-small・u2-app | `docs/REVIEW_2026-11.md` の A10 の場所「ai_assist.py 1033」と O3 の場所「app.py 225〜228」は 0.29.0 の行と合わないので直す | REVIEW の行番号は点検の対象の 0.28.1 のもので、0.28.1 では合っている（1033 は `parse_cut_response` の捕まえていない `json.loads`、226 は `waiting_for_answer`）。直さなかった |
| u2-app | `docs/USAGE.md` に、従来のノートブックのフォームの値は ▶ を押すまで変数にならないことを書くか、版の最後に決める | 確かめていないので書かなかった |
