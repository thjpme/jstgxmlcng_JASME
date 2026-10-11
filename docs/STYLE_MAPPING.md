# テンプレートのスタイルと JATS 要素の対応

テンプレート: `tests/fixtures/JASME_template_20261009.docx`。対応表の実体は `src/jasme_jats/data/jasme.toml` の `[styles]`。
スタイルは「名前」で照合する（Word の内部 ID ではない）。テンプレートを元に作ったスタイル（基準スタイル）も、基準をたどって照合する。

| スタイル | 役割 | JATS |
|---|---|---|
| 題目（日） | title | `article-meta/title-group/article-title[@xml:lang="ja"]` |
| 副題（日） | subtitle | `title-group/subtitle[@xml:lang="ja"]` |
| 所属（日）/ 著者名（日） | aff_ja / author_ja | `contrib-group/contrib/name-alternatives/name[@name-style="eastern"]`, `aff-alternatives/aff[@xml:lang="ja"]` |
| 題目（英）/ 副題（英） | title_en / subtitle_en | `title-group/trans-title-group[@xml:lang="en"]/trans-title`, `trans-subtitle` |
| 著者名（英）/ 所属（英） | author_en / aff_en | `name[@name-style="western"]`, `aff[@xml:lang="en"]`（和文の著者・所属と順番で対応付け） |
| 英文要旨見出し / 英文要旨 | abstract_heading / abstract | `trans-abstract[@xml:lang="en"]/title`, `p`（英文の論文では `abstract[@xml:lang="en"]`） |
| 章見出し / 節見出し / 項見出し | sec1 / sec2 / sec3 | 入れ子の `sec/title` |
| 本文（Body Text） | p | `p` |
| 図キャプション | fig_caption | `fig/caption/p`（直前の画像段落と組にする。2 段落目以降は caption の中の追加の p） |
| 表キャプション | table_caption | `table-wrap/caption/p`（直後の表と組にする） |
| ブロック引用 | quote | `disp-quote/p`（連続する段落を 1 つにまとめる） |
| 付記見出し | notes_heading | `back/notes/title` |
| 謝辞見出し | ack_heading | `back/ack/title` |
| 注見出し | fn_heading | `back/fn-group/title`（以降の段落を 1 段落 1 件の `fn` に。「1)」で始まらない段落は前の注の続き。注の番号は `fn/p` の先頭に入れる。J-STAGE は `fn/label` を表示しないため） |
| 参考文献見出し / 参考文献 | ref_heading / ref | `back/ref-list/title`, `ref/mixed-citation` |
| 標準（Normal） | normal | 位置と内容から推定（下記） |

## 位置による扱い

- 冒頭（題目〜最初の章見出し）の「標準」スタイルの段落（誌名・装飾行など）は出力しない（レポートに全文）。
- 英文要旨の後に「資料」「付録」「Appendix」で始まる段落があれば、そこから `back/app-group/app`。
- 表（著者表を除く）は `table-wrap/table`。セルの複数段落は `<break/>` でつなぐ。横の結合は `colspan`、縦の結合は `rowspan`。
- 別行の数式（数式と式番号だけの段落）は `disp-formula`、式番号「(1)」は `<label>`。文中の数式は `inline-formula`。数式は MathML 2.0。
- キャプションのない画像段落は `fig`（キャプションなし）。横長の小さい画像は数式画像の可能性としてレポートに挙げる。
- テキストボックス・グループ図形に入った図表（画像・表・キャプションを含むもの）は、図の本体とキャプションを組にして、
  「図の左上の直上にある本文の文章を含む段落の直後」に置く。位置を機械的に決められるのは、図の左上がアンカー段落の左上にある場合だけで、
  それ以外は AI 補完で指定する（docs/DESIGN.md の 6.1）。表で組んだ図は `fig` の中の `table-wrap`。
- 図表の中身を持たないテキストボックス（文字だけ）の段落は、図の一部とみなして出力しない（レポートの 6 章に全文）。

## スタイルが想定外の段落の推定（機械的な規則）

| 条件 | 推定 |
|---|---|
| 「１．…」「1. …」で始まる短い 1 行（句点なし） | 章見出し |
| 「(1) …」で始まる短い 1 行 | 節見出し |
| 「① …」で始まる短い 1 行 | 項見出し |
| 本文スタイルでも、全体が太字で上の形式 | 見出し |
| 「表N …」で始まる短い段落で、隣が表 | 表キャプション |
| 「図N …」で始まる短い段落で、隣が画像 | 図キャプション |
| テキストボックス内の「図N …」「表N …」で始まる短い段落（「図1は…」のように番号の直後がひらがな・読点・範囲の記号のものを除く） | 図・表キャプション |
| 「引用文献」「参考文献」「謝辞」「付記」「注」だけの段落 | 後付けの見出し |

推定した箇所と、本文のスタイルでない（「標準」など）ため本文の段落として扱った段落は、すべてレポートの「機械処理による推定」に載る。AI 補完を使うと、AI がこれらを確認・修正する（`set_role`）。
