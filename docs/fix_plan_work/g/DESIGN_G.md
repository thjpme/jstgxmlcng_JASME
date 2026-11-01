# 単位 G（0.26.0）の設計: 読み取りの文字ポリシー（D5・U8・U3・N8）

- 対象: main の c35defd（0.25.0）。正本は docs/FIX_PLAN.md の「G」の節。この設計書は、その節を関数ごとの変更点まで具体化したもの。
- 作成: 設計の担当（2026-11-01）。コードは変えていない。試作は `scratchpad/g/design/proto_src`（0.25.0 の src の写しに D5・U8・U3・N8 の
  読み取り・検証・ルート2・emit の部分だけを入れたもの。レポート・Decision・Action は入れていない）。
- 実験のスクリプトと結果（どれも `scratchpad/g/design/` の下。文字は架空）:
  `gen_cases.py`（D5 の 16 通り）・`gen_u8.py`（U8 の 21 通り＋docDefaults）・`gen_n8.py`（削除された行・セル）・`gen_u3.py`（セルの改行）・
  `lo_dump.py`（LibreOffice の UNO で「すべての変更を承諾」した後の段落・スタイル・番号・表示される文字を出す）・`lo/*.json`（その結果）・
  `run_proto.py`（試作で変換）・`route2_split.py`（ルート2 で段落記号の削除をまたぐ段落を直す）・`dtd_break.py`（DTD で `<break/>` の置き場所）・
  `count_td.py`・`td_counts.json`・`td_br.py`・`realpdf_counts.json`（実際の原稿の件数。数だけ）・`jstage/a1.txt`（J-STAGE の修飾タグ処理仕様の文字）。
- **暫定**（まとめ役の判断。利用者にはまだ確かめていない）: FIX_PLAN の G の「前提」の利用者の確認（Word で sample_reader.docx の段落の
  つながりとスタイルを見る〈D5〉、スタイルの隠し文字の表示を Word で見る〈U8〉、セルの改行に `<break/>` を補うか〈U3〉）は利用者が後で行う。
  G は FIX_PLAN の G の規則（LibreOffice で確かめたもの）を実装し、利用者の確認で違いが出たら直す。画面（Colab・CLI）の文言・見え方は
  利用者が後でまとめて直す方針なので、既存の形（赤い枠・手順 8・標準エラー）に `Action` を足すだけにし、表示の仕組みは変えない。
  実装の担当は、FIX_PLAN の G の節の冒頭（「前提」の後）に、この段落と同じ趣旨の「暫定」の注記を足す。

---

## 1. 文字ポリシーの今の形（0.25.0）と、G でそろえる形

### 1.1 今の扱い（コードを読んだ結果）

| 項目 | ooxml.canonical_text（検証） | docx_reader（読み取り） | pdfdocx.paragraph_units（ルート2） |
|---|---|---|---|
| 段落の単位 | w:p 1 つ（中の w:p・txbxContent・w:rt は飛ばす） | `read_block` の w:p 1 つ（`read_paragraph`）。テキストボックスの段落は `_textboxes`→`_read_nested_paragraph` | w:p 1 つ |
| 段落の ID | `paragraph_ids(root, prefix)`: 前処理（mc:Choice に置き換え）後の `root.iter(w:p)` の出現順。本文 d・脚注 f・文末脚注 e | 同じ（`self.pids`。注は `read_notes` で部品ごとに作り直す） | `raw_paragraph_ids`: 前処理しない XML で、mc:Fallback の中を飛ばして数える（同じ番号） |
| 削除（w:del・w:moveFrom） | 中を deleted として歩き、文字を出さない | 同じ（`_walk`）。脚注の参照は `deleted_note_refs` に記録 | 同じ |
| 挿入（w:ins・w:moveTo） | 中を歩く（ふつうの文字） | 同じ | 同じ |
| 段落記号の削除（w:pPr/w:rPr/w:del・w:moveFrom） | **扱わない**（w:pPr ごと飛ばす。2 段落のまま） | **扱わない** | **扱わない** |
| 表の行の削除（w:trPr/w:del）・セルの削除（w:tcPr/w:cellDel） | 扱わない（行の w:p はそれぞれの段落。削除された文字は出さない） | `read_table` は行・セルをすべて読む（空の行・セルとして出力） | 扱わない |
| 隠し文字 | `run_hidden(r)`: ランの直接の w:vanish か w:specVanish（`on_off`）だけ。スタイル・既定の書式は見ない | 同じ `run_hidden`。隠した文字は `self.hidden` に (src, 文字) で記録（`_plain_of_run_child` は w:t とタブだけ）。隠しランの中の画像は `ImageRef.hidden` | 同じ `run_hidden` |
| 改行 w:br（type なし・textWrapping）・w:cr | "\n" | "\n"（アトムの文字） | ("\n", None)（直せない文字） |
| フィールドの状態 | w:p ごとに初期化 | w:p ごとに初期化（`read_paragraph` で `self._fields = []`） | w:p ごとに初期化 |
| 書式・番号・セクション | 見ない | `read_paragraph` が w:p の pPr から style・numPr・jc・sectPr を読み、番号付きなら `Numbering.label` を 1 回呼ぶ | 見ない |

emit.py・builder.py: セルの段落は `Builder.cell_content` が `E.CELL`（今は `Ctx()` で `BODY` と同じ値）で `Emitter.span` に書き、セルの中の
段落と段落の間に `<break/>` を入れる。段落の中の "\n" はどの文脈でも文字のまま（`_append_text`）。

### 1.2 G でそろえる形（3 か所で共有する規則と、独立に保つ実装）

- **規則（1 か所に置き、3 か所が呼ぶ）**: `ooxml` に、段落記号の削除（`paragraph_mark_deleted`・`joined_paragraphs`・`unjoined_deleted_marks`）と
  隠し文字の判定（`HiddenRule`）を置く。読み取り・検証・ルート2 は、同じ関数で「どの w:p をつなぐか」「どのランが隠れているか」を決める
  （FIX_PLAN の計画全体の作業の「CLAUDE.md の更新 G」と同じ）。
- **文字の取り出し（独立に保つ）**: 検証の `canonical_text`、読み取りの `_walk`/`_run`、ルート2 の `paragraph_units` は今までどおり別々の実装のまま
  （ooxml.py の冒頭の「別の実装で取り出すことで、変換処理の誤りを検出できる」を守る）。規則を共有するので、規則そのものの誤りは不変性チェックでは
  見つからない。規則は単体テスト（7 章）と LibreOffice との比較（3・4 章）で確かめる。
- **段落の ID**: 3 か所とも今の番号（すべての w:p の出現順）のまま。つないだ段落は最初の w:p の ID にし、後ろの w:p の ID は欠番（読み取りの段落が
  ない。検証の文字の辞書にもない。ルート2 も直さない）。
- **隠し文字の規則の元**: 3 か所とも、その docx の word/styles.xml から `HiddenRule` を作る（読み取りと検証は `DocxPackage.xml`、ルート2 は
  `parse_xml(zin.read("word/styles.xml"))`。styles.xml に mc:AlternateContent はないので、前処理の有無で違わない）。
- **削除された行（N8）**: 読み取りだけで読み飛ばす。行の段落の docx の文字はすべて空（条件）なので、検証（`verify` は文字が空の段落を数えない）と
  ルート2（直す箇所がない）は今のままで同じ結果になる（5 章）。

---

## 2. D5: 段落記号の削除を承諾した状態として、次の段落とつなぐ

### 2.1 ooxml に足す関数

```python
def paragraph_mark_deleted(p) -> bool
```
- w:p の w:pPr/w:rPr に w:del か w:moveFrom があれば真。w:pPr/w:rPr の w:vanish（段落記号の隠し文字。スタイル区切り）・w:ins は見ない（つながない）。

```python
JOIN_SKIP = {bookmarkStart, bookmarkEnd, proofErr, permStart, permEnd, commentRangeStart, commentRangeEnd,
             moveFromRangeStart, moveFromRangeEnd, moveToRangeStart, moveToRangeEnd,
             customXmlInsRangeStart/End, customXmlDelRangeStart/End, customXmlMoveFromRangeStart/End, customXmlMoveToRangeStart/End}
def _join_target(p) -> (w:p | None, 理由)
```
- p の次の兄弟を、JOIN_SKIP（中身のない目印）とコメント・処理命令を飛ばしてたどる。
  - 次が w:p → それにつなぐ（理由は空）。
  - 次がない、または w:sectPr（本文の最後のセクションの設定）→ つながない。理由は親で決める: w:body「本文の最後の段落」、w:tc「表のセルの最後の段落」、
    w:txbxContent「テキストボックスの最後の段落」、w:footnote・w:endnote「注の最後の段落」、w:sdtContent「コンテンツコントロールの最後の段落」、
    w:customXml「カスタム XML の最後の段落」、ほか「段落の並びの最後の段落」。
  - 次が w:tbl「次が表」、w:sdt「次がコンテンツコントロール」、w:customXml「次がカスタム XML」、そのほか（ブロックの w:ins・w:del・
    mc:AlternateContent・w:altChunk など）「次が段落でない」→ つながない。
- 同じ親の中だけを見る（親を越えて、sdt の中から外へ、セルの最後から次のセルへ、などはつながない）。

```python
def joined_paragraphs(root) -> dict   # {最初の w:p: [w:p, w:p, ...]}（2 段落以上の連鎖だけ）
```
- `root.iter(w:p)` のすべての w:p（テキストボックス・表・注の中も）で、`paragraph_mark_deleted(p)` かつ `_join_target(p)` が w:p のものを
  p → 次 とつなぎ、連鎖にまとめる（3 段落以上も。連鎖の最初は「ほかの段落からつながれていない」段落）。
- 前処理した木（mc:Choice に置き換えたもの）に対して呼ぶ。前処理しない木に呼ぶと mc:Fallback の中の写しもつなぐので、ルート2 は前処理した写しで
  呼ぶ（2.7）。

```python
def unjoined_deleted_marks(root) -> list   # [(w:p, 理由)]
```
- 段落記号が削除されているのに、つなぐ先がない段落と、その理由（上の `_join_target` の理由）。

```python
def canonical_texts(root, prefix, hidden=None) -> dict   # {段落 ID: 文字}
```
- `paragraph_ids(root, prefix)` の順に、連鎖の後ろの w:p を除き、連鎖の最初の w:p の ID に、連鎖の w:p ごとの `canonical_text(q, hidden)` を
  順に連結した文字を入れる。連鎖でない w:p は今までどおり `canonical_text(p, hidden)`。フィールドの状態は w:p ごとに初期化（今と同じ。段落を
  またぐフィールドは今も扱っていない）。
- `fidelity.source_texts` はこれを使う（3 部品とも。`hidden` は `HiddenRule(pkg.xml("word/styles.xml"))`）。

### 2.2 つなぐ・つながない境界（決めたこと）

| 場所 | 扱い | LibreOffice（24.2、UNO で承諾した後） |
|---|---|---|
| 同じ親の中で、次の兄弟が w:p（間の bookmark などは飛ばす） | つなぐ | つなぐ（本文・セルの中・テキストボックスの中・脚注の中、3 段落の連鎖、bookmark をはさむもの） |
| 段落記号の w:vanish（スタイル区切り。w:specVanish つき） | つながない（警告もしない。削除ではない） | つながない |
| 次が表 | つながない＋10 章の警告 | つながない |
| セル・テキストボックス・注・コンテンツコントロール・カスタム XML の最後、本文の最後 | つながない＋10 章の警告（2.6 の条件） | セル・テキストボックスの最後はつながない |
| 次が w:sdt・w:customXml（境界） | つながない＋10 章の警告（FIX_PLAN どおり。Word では未確認） | **つなぐ**（sdt の中の段落と、customXml の中の段落と） |
| 段落記号の w:moveFrom | つなぐ（w:del と同じ。中身の w:moveFrom は今も削除と同じに扱っている） | **つながない**（今回の例は中身が移動でない段落。LibreOffice は段落記号の moveFrom を承諾の対象にしないとみられる） |
| 脚注の参照のある段落の段落記号の削除 | つなぐ | **つながない**（LibreOffice の承諾の不具合とみられる） |

LibreOffice と違う 3 つ（sdt・customXml の境界、段落記号の moveFrom、脚注の参照のある段落）は、Word での確かめ（9 章）に入れる。
sdt・customXml の境界は、つながないと文字は失われない（2 段落になるだけ）ので、つながない側を採る（FIX_PLAN どおり）。

### 2.3 つないだ段落の中身（読み取り）

- **ID**: 連鎖の最初の w:p の ID（`self.pids[chain[0]]`）。後ろの w:p の ID は欠番。
- **文字・アトム**: 連鎖の w:p を順に `_walk` して、同じ `Para` にアトムを足す（w:p ごとに `self._fields = []` と `self._pstate`〈4 章〉を設定し直す）。
  `_add_text` は同じ書式の文字アトムを今までどおりまとめる（段落の境目でもまとめてよい。文字は変えない）。
- **書式の元の段落（`fp`）**: 連鎖の中で、`canonical_text(q, self.hidden_rule)` が空でない最初の w:p。すべて空なら連鎖の最後の w:p。
  （「前の段落が空なら後の段落のもの、そうでなければ前の段落のもの」を連鎖の先頭からたたみ込んだ結果と同じ。LibreOffice の B・C・D・P の例と一致）。
  「空」は docx の文字（canonical_text）で決める。画像だけの段落は「空」とみなす（決めたこと。画像だけの段落の段落記号の削除はまれ。Word で
  違えば直す）。読み取りが canonical_text を呼ぶのは書式の元を選ぶためだけで、文字は今までどおり `_walk` で取り出す。
- **fp から取るもの**: pStyle（なければ既定の段落スタイル）・style_name・numPr（なければスタイルの番号）・jc（align）。
- **最後の w:p から取るもの**: `section_break`（w:pPr/w:sectPr の有無）。前の段落の sectPr は、段落記号の削除でセクションの区切りも消えるので見ない。
- **最初の w:p から取るもの**: in_textbox・float_id・textbox_id（同じ親なので、どの w:p でも同じ）。
- **自動番号**: fp に番号があれば、その (numId, ilvl) で `Numbering.label` を連鎖ごとに 1 回だけ呼ぶ。呼ぶのは連鎖を読むとき（連鎖の最初の w:p に
  来たとき）で、今の 1 段落と同じく `_walk` の前。連鎖の後ろの w:p は `read_paragraph` を通らないので label を呼ばない（「連鎖の途中かどうかは
  集合で判定する」= `self.later` の集合）。FIX_PLAN の「連鎖の最後で 1 回」とは、連鎖の中のテキストボックスに同じ番号の段落があるときの
  数える順だけが違う（連鎖を読む前に数える。1 段落の今の順と同じにするため。決めたこと）。LibreOffice の H の例（「1.」の次の、文字ごと削除した
  番号付きの段落の段落記号を削除 → 次の段落が「2.」）と一致。
- **図形・テキストボックス**: 連鎖の後ろの w:p の中の図形は、読む中の `para`（最初の ID）に結び付く（`Float.anchor_src`・`TextBox.anchor_src` は
  最初の段落の ID）。`_extra`（テキストボックスの段落）は連鎖の順に並ぶ。
- **隠し文字の段落の状態**: w:p ごとに、その w:p 自身の段落スタイルで `para_state` を決める（承諾した後は fp のスタイルになるが、そこまでは
  まねない。暫定。段落スタイルで隠した段落の段落記号の削除はまれ。限界として DESIGN.md 7 章に書く）。

### 2.4 docx_reader の変更点（関数ごと）

- `Reader.__init__`: `self.hidden_rule = HiddenRule(self.pkg.xml("word/styles.xml"))`、`self._pstate = False`、`self.chains = {}`（w:p → 連鎖）、
  `self.later = set()`（連鎖の後ろの w:p）、`self.joins = []`（2.5）、`self.deleted_rows = []`（5 章）。
- 新しい `Reader._set_joins(root)`: `self.chains = joined_paragraphs(root)`、`self.later = {q for c in chains.values() for q in c[1:]}`。
  `unjoined_deleted_marks(root)` のうち、`canonical_text(p, self.hidden_rule) != ""` の段落だけを 10 章の警告にする（2.6）。
- `Reader.read`: `self.pids = paragraph_ids(root, "d")` の直後に `self._set_joins(root)`。`Document(...)` に `joins=self.joins`、
  `deleted_rows=self.deleted_rows` を渡す（model.Document に 2 つのフィールドを足す）。
- `Reader.read_notes`: 退避（`saved`）に `self.chains, self.later` を加え、部品の `paragraph_ids` の後に `self._set_joins(root)`、最後に戻す。
- `Reader.read_block`: w:p が `self.later` にあれば `[]`（前の段落と一緒に読んだ）。
- `Reader.read_paragraph(p, in_textbox=False)`: `chain = self.chains.get(p, [p])`。2.3 の fp・最後の w:p・label。`self._extra = []` の後、
  `for q in chain: self._fields = []; self._pstate = self.hidden_rule.para_state(q); self._walk(q, para, ...)`。連鎖が 2 段落以上で、w:p ごとの
  実際のスタイル（pStyle がなければ既定の段落スタイル）が 1 種類でなければ、`self.joins` に `JoinInfo`（2.5）を足す。
  連鎖が 1 段落のときは、今と同じ順・同じ処理になるようにする（golden が変わらないこと）。
- `Reader._textboxes`: `_children(tx, (w:p, w:tbl))` の w:p が `self.later` にあれば飛ばす（F の TextBox の段落は、つないだ後に残った段落だけになる。
  `TextBox` 自体には段落の一覧がなく、structure の `box_members`・`plan.textboxes[x].paras` は読み取った段落から作るので、ここで飛ばせば足りる）。
- `Reader._read_nested_paragraph`・`_read_nested_table`: 退避と復元に `self._pstate` を加える（テキストボックスの段落を読んでも、外側の段落の
  隠し文字の状態が変わらないように。FIX_PLAN の「U8 で段落の隠し文字の状態を退避して戻す」）。
- `Reader._walk`: `self._run(ch, para, fmt, href, hidden or self.hidden_rule.run_hidden(ch, self._pstate), deleted)`（4 章）。

### 2.5 スタイルの違う段落をつないだときの Decision（4 章）

- model.py に `JoinInfo(src: str, srcs: list, style_ids: list, used: str)` を足し（`Document.joins: list`）、読み取りが、連鎖の w:p のスタイルが
  1 種類でないときだけ記録する。
- structure.py: `Classifier.run` の最後（`assign_ids` の後。今の判断の番号を変えないため、最後に足す）で、`doc.joins` ごとに
  `plan.decide("mechanical", "style", j.src, msg)`。文言（例）:
  「変更履歴で段落記号が削除された d12・d13 を、1 つの段落につないだ（Word で変更をすべて承諾した状態）。段落のスタイルが違う（「節見出し」「本文」）ので、
  文字のある最初の段落のスタイル「本文」にした（Word で承諾した後のスタイルと同じかは確かめていない）」。スタイル名は `doc.styles[sid].name`。
  N7 の 2 回の組み立てでも、返す方の plan にだけ残る（各回の run が足す）。
- 6 章（出力しなかった docx の文字）の「ほかの注記」に、つないだ段落の一覧を 1 行足す（Result に `joined` を渡す。2.8）:
  「変更履歴で段落記号が削除された段落を、次の段落とつないで 1 段落として出力しました（N か所: d12＋d13、d20＋d21＋d22 …）。」
  今の「変更履歴が N 箇所あります。…」の文は変えない（つないだ段落がないレポートは 0.25.0 と同じ文字にするため。FIX_PLAN の「report.py:424 の文言も直す」は、
  この 1 行を足すことで果たす）。

### 2.6 つなげないときの 10 章の警告

- 読み取りの `doc.warnings`（10 章にそのまま出る）に、段落ごとに 1 行:
  「d20: 変更履歴で段落記号（段落の区切り）が削除されていますが、次が表なので、次の段落とつながずに 2 段落のまま出力しました。Word で変更履歴を
  承諾してから変換し直すと、Word と同じ 1 段落になります。」（「次が表なので」の部分は 2.1 の理由に「なので」を付ける）
- 出すのは、その段落の docx の文字（canonical_text）が空でないときだけ（決めたこと）。空の段落はつながなくても見える違いがなく、変更履歴で
  削除された表の行の中の段落など、Word がセルの最後の段落の段落記号にも削除の印を付ける形で警告が並ぶのを避ける。
- Action にはしない（FIX_PLAN どおり 10 章だけ。文字は失われない）。

### 2.7 ルート2（pdfdocx）での扱い

- **段落の対応**: `write_fixed_docx` は、部品ごとに前処理しない木（`roots[part]`）に加えて、その写しを前処理した木で `joined_paragraphs` を呼び、
  `paragraph_ids` で ID の連鎖 `{最初の ID: [ID, …]}` にする（新しい `pdfdocx._chains(root, prefix)`。前処理した写しは ID を決めるためだけに使い、
  書き込みは前処理しない木の w:p に行う。`raw_paragraph_ids` と ID の番号は同じ）。部品の中に段落記号の削除がひとつもなければ（前処理しない木の
  `root.iter(w:p)` で `paragraph_mark_deleted` を見る）写しを作らず `{}`（速さのため。今の docx のほとんど）。
- `raw_paragraph_ids` は変えない（ID → w:p。欠番の ID も w:p を返す）。
- 連鎖の後ろの ID は直さない（`by_src` に直す箇所がないので、今のコードでも素通りする。`plan.paras[src]` を引く前に飛ばす）。
- 連鎖の最初の ID の段落は、`units = [u for q in chain for u in paragraph_units(raw[q], rule)]`（w:p ごとの単位を連結）。どれかの w:p が `_Complex`
  なら連鎖ごと直さない（今の 1 段落と同じ理由）。`"".join(units)` が `plan.paras[src].plain()`（読み取りでつないだ文字）と同じことを確かめる今の
  検査はそのまま。
- **どちらの w:p に差し込むか**: `_apply_paragraph` は単位の w:t ごとに直すので、削除・置き換えは、その文字のある w:p の w:t に入る（段落記号の
  削除をまたぐ直しは、前の w:p の最後の w:t と後ろの w:p の最初の w:t の両方に分かれて入る）。足す文字は今の規則（直前の文字の後ろ。なければ直後の
  文字の前）のまま。つないだ段落の境目に足す文字は、前の w:p の最後の w:t の後ろに入る（前の w:p に文字がなければ、後ろの w:p の最初の文字の前）。
  前の w:p の段落記号の削除（w:pPr/w:rPr/w:del）には触らないので、直した docx を Word で承諾しても、読み取りでも、同じ 1 段落になる。
- `paragraph_units(p, hidden=None)`: 4 章の規則を渡す。`rule = hidden or NO_RULE`、`ps = rule.para_state(p)`、ランは
  `run(ch, deleted, hidden or rule.run_hidden(ch, ps))`。`write_fixed_docx` は `HiddenRule(parse_xml(zin.read("word/styles.xml")))` を作って渡す
  （styles.xml がなければ `NO_RULE`）。
- `make_fixed_docx` の読み直しの確かめ（`_verify`・`_structure`・`_lost`）は外さない。つないだ段落も 1 つの段落 ID として比べる。
- 試作の結果（`route2_split.py`）: sample_pdfcheck.docx の本文の段落「詳しくは資料の…。授業は2回行った。」を段落記号の削除で 2 つに分けた docx を、
  今の sample_pdfcheck.pdf でルート2 にすると、0.25.0 は 2 段落のまま「資料→付録」と「2→２」を別の段落で直し XML も 2 つの `<p>`、試作は 1 段落として
  同じ 2 つを直し XML は 1 つの `<p>`（不変性・最終・DTD とも合格）。

### 2.8 pipeline・report の変更点（D5）

- pipeline.Result に `joined: list`（`doc.joins` ではなく、すべての連鎖の (最初の ID, [ID…])）を足す。読み取りは、スタイルの違いに関係なく
  すべての連鎖を `Document.joined`（[(src, [srcs])]）に入れ、スタイルの違うものだけ `Document.joins`（JoinInfo）にも入れる。
- report.render の 6 章「other」に 2.5 の 1 行（`r.joined` があるときだけ）。

---

## 3. （実験）LibreOffice と試作で確かめた D5 の結果

`gen_cases.py` の docx（`lo/d5.docx`）を LibreOffice で開き、`.uno:AcceptAllTrackedChanges` の後の段落（`lo/d5_acc.json`）と、試作の読み取り
（`run_proto.py`）を比べた。

| 例 | LibreOffice | 試作 |
|---|---|---|
| A 本文＋本文 | 1 段落・本文 | 同じ |
| B 文字ごと削除した節見出し＋本文 | 1 段落・本文（後の書式） | 同じ（Decision の対象） |
| C 節見出し＋本文 | 1 段落・節見出し（前の書式） | 同じ（Decision） |
| D 本文＋節見出し | 1 段落・本文 | 同じ（Decision） |
| E 表の直前 | つながない | 同じ（警告） |
| F セルの 1 段落目／セルの最後 | つなぐ／つながない | 同じ（最後は警告） |
| G 3 段落の連鎖 | 1 段落 | 同じ |
| H 番号「1.」、文字ごと削除した番号付きの段落＋次の番号付きの段落、その次 | 1. / 2. / 3. | 同じ |
| I 段落記号の moveFrom | つながない | つなぐ（2.2） |
| J 次が sdt／O 次が customXml | つなぐ | つながない（警告） |
| K 間に bookmark | つなぐ | 同じ |
| L 段落記号の vanish（スタイル区切り） | つながない | 同じ |
| M 脚注の参照のある段落 | つながない | つなぐ（2.2） |
| N テキストボックスの中の連鎖・最後 | つなぐ・つながない | 同じ（最後は警告） |
| P 空でない＋文字ごと削除した節見出し＋項見出し | 1 段落・本文 | 同じ |
| 脚注の 1 段落目の段落記号の削除 | 1 段落「注の前半と注の後半。」 | 同じ |

試作で、不変性チェック・最終チェック・DTD はすべて合格（`d5.docx`）。sectPr の規則は LibreOffice では確かめていない（FIX_PLAN の規則のまま）。

---

## 4. U8: スタイル・既定の書式の隠し文字

### 4.1 HiddenRule の仕様

```python
class HiddenRule:
    def __init__(self, styles_root=None)   # word/styles.xml の根（None なら、直接の指定だけを見る規則）
    def style_value(self, sid) -> bool | None
    def para_state(self, p) -> bool
    def run_hidden(self, r, ps) -> bool
NO_RULE = HiddenRule(None)
```

- `style_value(sid)`: スタイル sid から w:basedOn をたどり、w:rPr/w:vanish を最初に指定しているスタイル（いちばん派生した側）の `on_off` の値。
  どれも指定していなければ None。循環は打ち切る。結果はスタイルごとにためておく。FIX_PLAN どおり（派生の連鎖の中で反転させない）。
- 既定の段落スタイル: styles の中の `w:type="paragraph"` で `w:default="1"`（または true）のもの。docDefaults の値 `dd`:
  w:docDefaults/w:rPrDefault/w:rPr/w:vanish の `on_off`（なければ False）。
- `para_state(p)`: 段落スタイル（w:pPr/w:pStyle。なければ既定の段落スタイル）の `style_value` が None でなければその値、None なら `dd`。
- `run_hidden(r, ps)`（上から順に、最初に当たったもの）:
  1. ランの直接の w:rPr/w:vanish があれば、その `on_off`（val="0" なら表示）。
  2. 直接の w:specVanish が on なら隠す。
  3. w:rStyle があり、その `style_value` が True なら `not ps`（段落の状態を反転）、False なら表示（False）、None なら `ps`。
  4. どれもなければ `ps`。
- `NO_RULE`（styles なし）は、直接の vanish・specVanish だけを見る（今の `run_hidden` とほぼ同じ。違いは「直接の vanish="0" と specVanish が
  両方あるラン」で、今は隠し、新しい規則は表示する）。

### 4.2 FIX_PLAN の規則から変えた 2 か所（LibreOffice に合わせた。暫定）

`gen_u8.py` の 21 通り（`lo/u8.docx`）と、docDefaults に vanish を足した同じ 21 通り（`lo/u8dd.docx`）を、LibreOffice の UNO の `CharHidden`
（LibreOffice が計算した、ランが隠れているか）と、PDF に書き出した文字（`pdftotext`）で比べた（docDefaults なしでは、UNO と PDF は 21 通りすべて一致）。
FIX_PLAN の規則とは 2 か所で食い違ったので、LibreOffice に合わせる。

1. **文字スタイルの vanish が「いちばん派生した側で val="0"」（u15: 隠す段落スタイル＋「基のスタイルは vanish、派生は vanish val=0」の文字スタイル）**:
   FIX_PLAN の `ps XOR style_value` は `1 XOR 0 = 1`（隠す）。LibreOffice は表示。→ 文字スタイルの値が False なら表示にする（3. の「False なら表示」）。
   隠すほうに倒すと、Word で表示される文字が XML から消える（6 章には載る）。表示するほうに倒すと、Word で隠れた文字が XML に入る。迷う形では
   文字を落とさないほう（表示）を採る、という理由もある。
2. **docDefaults と段落スタイルの両方に vanish（u05・u06・u08 の dd 版）**: FIX_PLAN の `dd XOR 段落スタイル` は表示。LibreOffice は UNO・PDF とも隠す。
   → 段落スタイルの値があればその値（docDefaults を上書き）にする。

そのほか（u01〜u14・u16〜u18・u21: 文字スタイル・派生の文字スタイル・段落スタイル・派生の段落スタイル・val=0 の打ち消し・段落と文字の両方〈反転で表示〉・
直接の vanish）は、FIX_PLAN の規則・新しい規則・LibreOffice の 3 つが一致した。

LibreOffice と合わないまま残すもの（Word で確かめる。9 章）:
- **specVanish だけのラン（u19）**: LibreOffice は表示（specVanish を見ない）。ECMA-376 では「常に隠れているようにふるまう」なので、隠す（今と同じ）。
- **docDefaults の vanish だけの段落（dd 版の plain）**: UNO は隠す、PDF は表示（LibreOffice の中で食い違う）。規則どおり隠す。
  docDefaults に vanish を置いた docx は、すべての文字が隠れる極端な形で、実際の原稿にはない（6 章）。

試作の読み取り（`run_proto.py lo/u8.docx`）は、docDefaults なしの 21 通りのうち u19 の 1 つを除いて LibreOffice と一致し、不変性・最終・DTD は合格。

### 4.3 3 か所への渡し方

- `canonical_text(p, hidden=None)`: `rule = hidden or NO_RULE`、`ps = rule.para_state(p)`、ランは `walk(ch, hidden_flag or rule.run_hidden(ch, ps), deleted)`
  （内側の関数の引数 `hidden` と名前が重なるので、実装では内側を `hid` などに変える）。
- `canonical_texts(root, prefix, hidden)` が w:p ごとに `canonical_text(q, hidden)` を呼ぶ。`fidelity.source_texts` は styles.xml から規則を作って渡す。
- `docx_reader._walk`: `self._pstate`（w:p ごとに `read_paragraph` が設定。2.4）と `self.hidden_rule` で `run_hidden`。
- `pdfdocx.paragraph_units(p, hidden=None)`（2.7）。
- `ooxml.run_hidden(r)` は、ほかに使うところがなくなる（3 か所とも `HiddenRule` に置き換える）ので消す。

### 4.4 扱わないもの（文字ポリシーに明記する）

- 数式の中のラン（m:r の w:rPr の vanish）: 今までどおり見ない（数式は全体を出す）。
- 表スタイル（w:tblStylePr・表スタイルの w:rPr）の vanish、番号の書式（w:lvl/w:rPr）の vanish、段落記号の vanish（w:pPr/w:rPr/w:vanish。
  スタイル区切りで、Word では前後の段落が 1 行に並ぶ）、文字スタイルの w:rStyle と段落スタイルの w:link の組（リンクスタイル）の特別な扱い、
  テーマ・互換性の設定。
- 連鎖（D5）の後ろの段落の隠し文字は、その段落自身の段落スタイルで決める（2.3）。

### 4.5 隠し文字のレポート（6 章）の範囲

- `docx_reader._plain_of_run_child` を広げる（「広げる」を採る）: w:t、w:tab・w:ptab（タブ）、w:br（type なし・textWrapping）・w:cr（"\n"）、
  w:noBreakHyphen（U+2011）、w:softHyphen（U+00AD）、w:sym（`sym_char`）。6 章の文字は `esc()` で表示するので、改行もそのまま一覧に入る。
- 6 章の見出しの文「隠し文字（Word で非表示に設定された文字）」は変えない（スタイルで非表示にしたものもこの定義に入る。0.25.0 のレポートを変えないため）。
- 隠し文字だけの段落（段落スタイルで隠した段落など）は、読み取りの段落が空になり、structure が「空白のみの段落」として `exclude_blank` で除外する
  （検証は文字が空なので合格。6 章の隠し文字の一覧に文字が載る）。理由の文が「空白のみ」になるのは限界として DESIGN.md 7 章に書く。

---

## 5. N8: 変更履歴で削除された表の行

### 5.1 削除された行（w:trPr/w:del）

- `Reader.read_table` の行ごとの処理で、行を読む前に `n_img, n_float, n_tb = len(self.images), len(self.floats), len(self.textboxes)` を覚え、
  行を今までどおり読んだ後、次をすべて満たす行だけを `t.rows` に入れない（読み飛ばす）:
  1. w:trPr に w:del がある。
  2. 行のすべてのセルの段落（入れ子の表・セルの中のテキストボックスの段落を含む。`Cell.blocks` の Para と `Table.paragraphs()`）にアトムがひとつもない
     （文字・画像・数式・注の参照がない。アトムの文字は検証の canonical_text と同じなので、「docx の文字がすべて空」と同じ）。
  3. 行を読む間に `self.images`・`self.floats`・`self.textboxes` が増えていない（隠し文字の画像も含めて、図形を読み飛ばさない。浮動配置の図形の
     アンカーが、出力しない段落を指すのを防ぐ）。
- 読み飛ばした行は `self.deleted_rows` に `DeletedRow(tid, row, head)` で記録する（row は docx の表の何行目か〈1 から。読み飛ばした行も数える〉、
  head は表の 1 行目の最初の文字のあるセルの文字の冒頭 20 字。利用者が Word で表を探す手がかり）。`Document.deleted_rows` → `Result.deleted_rows`。
- レポート 6 章の「other」に 1 行: 「変更履歴で削除された表の行 N 行は、Word で変更を承諾した状態と同じく出力していません（行の文字はすべて削除済み）:
  表「区分…」の 3 行目、…」。
- w:trPr/w:del があるのに、文字（などのアトム）が残っている行は、今までどおり出力し、10 章の警告に 1 行: 「表「区分…」の 3 行目: 変更履歴で削除された行
  ですが、削除されていない文字があるので、行のまま出力しました。Word で変更を承諾するとこの行は消えます。Word で確かめてください。」
  （LibreOffice も、この行を承諾の後に残した。`lo/n8` の R3）
- 検証（`fidelity.source_texts`）は変えない。読み飛ばす行の段落は docx の文字がすべて空で、`verify` は文字が空の段落を「出力漏れ」にしないので、
  読み取りと検証は同じ結果になる（試作で `n8.docx` の不変性は合格）。行を飛ばす処理を検証にも足すと、条件 2・3（アトム・図形）を検証の側でも
  持つことになり、独立の実装が増えるだけなので足さない（決めたこと。task の「fidelity.source_texts の側も同じ行を飛ばす」は、この理由で
  「何もしなくても同じ」とする）。ルート2 も、その行の段落には直す箇所がないので変えない。
- builder.table: 行を読み飛ばした表の縦の結合（vMerge）は、残った行で数え直される（今のコードのまま）。すべての行を読み飛ばした表は、今の
  「空の表には空の td を 1 つ」の処理で DTD に合う。

### 5.2 削除されたセル（w:tcPr/w:cellDel）: 読み飛ばさない

- 実験（`lo/n8.docx` の R4・R5）: LibreOffice は、w:cellDel のセルが 1 つでもある列を、承諾の後に**列ごと**消した（R4 の削除されていない左のセルは
  残り、右の列は削除されていない R1〜R6 の右のセルもすべて消えた）。Word の承諾は「そのセルだけを消して左に詰める」と考えられるが、確かめていない。
- セルを読み飛ばすと表の形（列の数・横の結合）が変わり、Word と LibreOffice でも結果が違うので、**セルは今までどおり出力する**（中の削除された文字は
  今も出さない）。10 章の警告に 1 行: 「表「区分…」の 4 行目に、変更履歴で削除されたセルがあります。セルはそのまま出力しました（削除された文字は
  出力していません）。Word で変更を承諾すると、セルが消えて表の形が変わることがあるので、Word で承諾してから変換し直してください。」
- w:trPr/w:ins・w:tcPr/w:cellIns・w:cellMerge は今までどおり（ふつうの行・セル）。

---

## 6. U3: 段落の中の改行（w:br・w:cr）

### 6.1 emit.py

- `Ctx` に `breaks: bool = False`（"\n" の前に `<break/>` を入れるか）と `newline_label: str = ""`（改行を要確認として知らせる文脈の名前。空なら
  知らせない）を足す。`CELL = Ctx(breaks=True)`、`TITLE = Ctx(..., newline_label="題目・副題")`、`NAME = Ctx(..., newline_label="著者名")`、
  `AFF = Ctx(..., newline_label="所属")`、`REF = Ctx(..., newline_label="引用文献")`。ほかは今のまま（BODY・SECTITLE・ABSTRACT・CAPTION・BACKP など）。
  `CELL` は値が `BODY` と違うものになる（今は同じ値。比べているところはない）。
- `Emitter.__init__`: `self.breaks = 0`（入れた `<break/>` の数）と `self.newlines = []`。
- `Emitter.span`: 切り出したアトムの文字の "\n" の数 n が 1 以上なら、書き出しの前後の `self.breaks` の差を b として、
  `self.newlines.append(Newline(src=para.src, count=n, breaks=b, label=ctx.newline_label))` を足す（model か emit に小さな dataclass）。
- `Emitter.write_inline` の `flush`:
  - 書き込み先（`parent`）が `jx:span` そのもの（`parent.tag == SPAN`。リンク〈xref・ext-link・uri〉の中ではない）で、`ctx.breaks` が真で、
    まとめた文字に "\n" があるときだけ、文字を "\n" で分け、2 つ目からの各部分の前に `parent` の子として `<break/>` を置き、その tail に "\n" を入れ
    （改行の文字は残す）、部分の文字は（空でなければ）書式の要素を作り直してその中に入れる。例: 太字の「太字の前\n太字の後」→
    `<bold>太字の前</bold><break/>\n<bold>太字の後</bold>`（書式の要素はいったん閉じる。`<bold>` の中に `<break/>` は置けない）。
    空の部分には書式の要素を作らない（試作の初版は先頭が "\n" のとき空の `<bold/>` を作りうる形だったので、空の部分は飛ばす）。
  - それ以外（"\n" がない、リンクの中、セル以外の文脈）は今のコードと同じ処理・同じ木（golden が変わらないこと）。
  - `write_atoms` の PCDATA だけの要素（uri・pub-id・year）の経路には入れない（リンクの中は今のまま）。
- 不変性: `<break/>` は文字を持たず、"\n" は tail に残るので、`fidelity.piece_text`・`final_check`・`stray_text`（jx:span の中）は変わらない（試作で確認）。

### 6.2 DTD で `<break/>` を置ける場所（`dtd_break.py`。同梱の JATS 1.1 Journal Publishing DTD）

| 置き場所 | DTD |
|---|---|
| `<td>`・`<th>` の直下（文字・`<bold>` の間、2 つ続き、`<inline-formula>` の前） | 合う |
| `<bold>`・`<italic>`・`<sup>` の中、`<xref>`・`<ext-link>` の中 | 合わない |
| `<p>` の中 | 合わない |
| `<article-title>`・`<sec>/<title>` の中 | 合う（ただし FIX_PLAN どおり、題目・見出しには入れない） |

J-STAGE の資料（2026-11-01 に確かめた）: 全文 XML 作成マニュアル 3.5.4 (6)「表」の `<th>`・`<td>` の「文字修飾」の一覧は
`<bold>,<italic>,<monospace>,<overline>,<roman>,<sans-serif>,<sc>,<strike>,<underline>,<sub>,<sup>,<ruby>,<code>,<inline-supplementary-material>,<chem-struct>`
で、`<break/>` は載っていない（`<xref>`・`<inline-formula>` も載っていないが、本ツールは前からセルに出している）。修飾タグ処理仕様（別紙 1）の
「修飾タグ許容一覧」は書誌の項目の一覧で、`<break/>`（HTML の `<br/>` に変換）は「電子付録（タイトル、説明）」だけ ○、タイトル・サブタイトル・
抄録・所属機関名・引用文献（論文タイトル・資料名）は ×。本ツールは 0.25.0 でもセルの段落の間に `<break/>` を出しているが、J-STAGE の画面での
表示は試験登載で確かめていない（DEVELOPMENT の「J-STAGE の試験登載で分かったこと」にない）。→ 決定事項 13(1)（セルでは補う）のとおり入れ、
試験登載で表示とアップロード時のエラーの有無を確かめる（9 章）。実装の担当は、この段落の内容を docs/JSTAGE_NOTES.md に根拠として書く。
題目・所属・引用文献で `<break/>` を使わないのは、別紙 1 とも合う。

### 6.3 builder.py

- `Builder.build` の最後（`self.info` を返す前）に、`self.em.newlines` を段落 ID ごとにまとめて（count・breaks の和）`self.info.newlines` に入れ、
  10 章の警告（`self.info.warnings`）を、文脈の組ごとに 1 行で足す（段落は「d12（場所）」の形で 10 件まで、それより多ければ「ほか N 段落」。場所は
  `plan.locations`）:
  - セル（breaks > 0）: 「表のセルの段落の中の改行（Shift+Enter）N か所の位置に、XML の改行 `<break/>` を入れました（改行の文字も残しています）: …」
    リンクの中の改行（count > breaks）があれば「（リンクの中の M か所は、改行の文字のまま）」を足す。
  - 知らせる文脈（label が空でない）: 「題目・著者・所属・引用文献の段落の中に改行（Shift+Enter）が N か所あります。XML では改行の文字のまま
    出力しました（J-STAGE の画面では、改行の位置が空白になるか、前後の文字が詰まって表示されます）: d3（題目・副題）…」
  - そのほか（本文・見出し・要旨・キャプションなど）: 「本文などの段落の中の改行（Shift+Enter）N か所は、XML では改行の文字のまま出力しました
    （J-STAGE の画面では空白になるか、詰まって表示されることがあります）: …」
- `BuildInfo` に `newlines: list` を足す。同じ plan で組み立て直すとき（ルート2 の番号・数式の取り消し）は、最後の組み立ての info を使う（今の
  `info.warnings` と同じ）。
- `cell_content`（段落の間の `<break/>`）は変えない。

### 6.4 Action（report.actions()）

- `report._newline_action(r)`: `r.newlines` のうち label が空でないものがあれば `Action(TO_CHECK, "newline", …)`。`actions()` の head の最後
  （`_note_overlap_action` の後）に足す。文言（案。利用者が後でまとめて直す方針なので、既存の形にそろえるだけ）:
  - top: 「> **要確認: 題目・著者・所属・引用文献の段落の中に、改行（Shift+Enter）が N か所あります（10 章）。** XML では改行の文字のまま
    出力しています。J-STAGE の画面では、改行の位置が空白になるか、前後の文字が詰まって表示されます。改行が要らなければ、Word でその改行を
    消して（題目の途中の改行は空白にするなど）、変換し直してください。対象の段落: d3「…」（題目・副題）、…」
  - checklist: 「- [ ] **題目・著者・所属・引用文献の中の改行**（N か所。10 章）: 要らなければ Word で改行を消して変換し直す」
  - box_title: 「題目・著者・所属・引用文献の中に改行があります（要確認）」
  - box_detail: top と同じ内容を、レポートの冒頭と 10 章を指す形で。
  - cli: 「要確認: 題目・著者・所属・引用文献の段落の中に改行が N か所あります（レポートの冒頭と 10 章）。要らなければ docx で改行を消して
    変換し直すこと」
  - 対象の段落の例は `_para_samples` に、場所（label）を添える。
- render・colab・cli・make_notebook.py には何も足さない（D の形）。
- pipeline.Result に `newlines: list`（`info.newlines`）を足す。

---

## 7. テストの計画

### 7.1 fixture（tests/make_fixtures.py）

- `Builder` に `self.styles_extra = []` を足し、`save` で word/styles.xml の `</w:styles>` の前に入れる（`footnotes_extra` と同じ仕組み）。
- 部品を足す:
  - `para_mark_deleted(style, *parts, kind="del"|"move", num_id=None)`: 段落記号を削除（w:pPr/w:rPr/w:del か w:moveFrom）した段落。w:id は中身から
    決める（`deleted()` と同じく `zlib.crc32`）。
  - `run_styled(text, rstyle=None, vanish=None, spec=False)`: 文字スタイル・直接の vanish（True/False）・specVanish のラン。
  - `para_styled(pstyle, *parts)`（`para` の pStyle に任意の ID を入れるだけなら `para` で足りる）。
  - `br()`（`<w:r><w:br/></w:r>`）と、太字のランの中の改行 `run_with_break(before, after, b=True)`。
  - `deleted_row(cells)`（w:trPr/w:del と、中の文字を `deleted()` で包んだ行）・`cell_deleted(content)`（w:tcPr/w:cellDel のセル）。
  - `add_break(p_el, ...)`: front_ja が作った題目の段落（lxml の要素）に、改行のランと続きの文字を足す（`Builder.set_text` では改行を入れられないため）。
  - スタイルの定義の文字列（G 用の文字スタイル・派生・val=0・段落スタイル・派生）を `READER_STYLES` として置く。
- `make_reader` の `READER_SECTIONS` に節を足す（どれも架空の文字。テストは段落の文字で対象を選ぶ）:
  1. 「段落記号の削除」: 本文＋本文、文字ごと削除した節見出し＋本文、節見出し＋本文、本文＋節見出し、表の直前の段落（と表）、セルの 1 段落目と
     最後の段落（セルの中の 2 段落）、3 段落の連鎖、番号付きの段落の連鎖（numId=7: 項目1、文字ごと削除した項目2＋項目3、項目4）、段落記号の
     moveFrom、間に bookmark、段落記号の vanish（スタイル区切り）、次が sdt・次が customXml、sdtContent の最後の段落、後ろの段落にテキストボックスの
     アンカー（画像とキャプションのテキストボックス。図の位置が機械的に決まる形〈`reader_textbox_sdt` と同じ形〉にする。
     `test_wrapped_rows_cells_and_textbox_paragraphs` が sample_reader の図形の位置がすべて mechanical であることを確かめているため）、テキストボックスの
     中の連鎖（キャプションを 2 段落に分けたもの）、脚注の 1 段落目の段落記号の削除（`b.footnotes_extra` に足し、本文から参照する）。
  2. 「スタイルの隠し文字」: FIX_PLAN の 6 つ（文字スタイルの vanish、派生の文字スタイル、段落スタイルの vanish、文字スタイルの vanish を直接の
     val="0" で打ち消したもの、段落スタイルと文字スタイルの両方〈反転で表示〉、直接の vanish）に、派生の段落スタイル、4.2 の u15 の形を足す。
     隠しランの中に画像は入れない（`test_fidelity_and_dtd` の `hidden_images == []` を保つ）。
  3. 「セルの改行」: 普通の文字の改行、太字のランの中の改行、ヘッダー行（th）の改行、セルの中のハイパーリンクの中の改行、段落の最後に改行のある
     セル（次の段落あり）、本文の段落の改行、引用文献の段落の改行（`make_reader` の引用文献の段落に）、題目の改行（`add_break`）。
  4. 「削除された表の行」: 中身ごと削除された行、文字の残った削除の行、削除されたセル（w:cellDel）。
- 作り直しは `make_reader` だけを呼ぶ（`python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_reader('tests/fixtures/sample_reader.docx')"`）。
  `git diff --stat tests/fixtures` で sample_reader.docx だけが変わることを確かめる。ルート2 の split の docx は fixture にせず、テストの中で
  `tmp_path` に作る（7.4。FIX_PLAN は sample_pdfcheck_split.docx を足す案だが、PDF は今のものを使うので、docx をリポジトリに足す必要がない。
  FIX_PLAN の付録の文面を合わせる）。make_pdfcheck に `split=False` の引数を足し、split=True なら d12 にあたる本文の段落「詳しくは資料の学習指導案を
  参照されたい。授業は2回行った。」を段落記号の削除で 2 つの w:p に分ける（`route2_split.py` と同じ形）。

### 7.2 tests/test_reader.py

- `test_reader_matches_canonical`: 比べる相手を `ooxml.canonical_texts`（`fidelity.source_texts` 経由のままでもよい。G の後は source_texts が
  canonical_texts を使う）にする。加えて、つないだ連鎖の後ろの ID が読み取りの段落にも検証の辞書にもないこと（`joined_paragraphs` で求めた ID）。
  今の逆向きの確かめ（文字のある ID がすべて 1 回だけ読まれる）はそのまま。脚注（f）も対象（今も対象）。
- 新しいテスト（sample_reader）:
  - つないだ段落の文字・スタイル・ID の欠番（A・B・C・D・P、3 段落の連鎖、bookmark、moveFrom）。
  - つながない場所（表の直前・セルの最後・sdt・customXml・sdtContent の最後・段落記号の vanish）は 2 段落のままで、10 章の警告（`doc.warnings`）に
    「承諾してから変換し直す」の行が段落の ID ごとに出る。段落記号の vanish の段落は警告に出ない。文字のない段落は警告に出ない。
  - 自動番号: 「項目1」1.、つないだ「項目3」が 2.、「項目4」が 3.。
  - 後ろの段落のテキストボックスの `Float.anchor_src`・`TextBox.anchor_src` が最初の段落の ID。テキストボックスの中の連鎖が 1 段落のキャプションになる。
  - 脚注の 1 段落目の段落記号の削除で、`doc.footnotes` の段落が 1 つ・文字が「注の前半と注の後半。」の形。
  - スタイルの違う連鎖が `doc.joins` に入り、plan の判断（4 章）に Decision が出る（test_structure か test_pipeline で）。
  - U8: 隠すもの（文字スタイル・派生・段落スタイル・派生の段落スタイル・直接・u15 の形の反対の…）が出力されず `doc.hidden_text` に載り、表示するもの
    （val=0・段落と文字の両方・u15）が出力される。隠し文字の一覧に改行・記号（w:br・w:sym・w:noBreakHyphen）が載る（`_plain_of_run_child` の拡張）。
  - N8: 中身ごと削除された行がなく、`doc.deleted_rows` に記録される。文字の残った削除の行は残り、警告が出る。削除されたセルは残り、警告が出る。
- `ooxml` の単体テスト（XML の文字列で作る。docx は要らない）:
  - `HiddenRule`: 4.2 の 21 通りの期待（LibreOffice と一致したもの。u19 は specVanish で隠す）と、FIX_PLAN の付録の追加 4 通り（派生した文字スタイルが
    自分も vanish → 隠す、派生した文字スタイルが val=0 → 表示、派生した段落スタイルが自分も vanish → 隠す、派生した段落スタイルが val=0 → 表示）、
    段落スタイル（vanish）に文字スタイル（vanish）と直接の val=0 を重ねたもの（表示）、docDefaults（段落スタイルなし → 隠す、段落スタイル vanish →
    隠す、段落スタイル val=0 → 表示、文字スタイル vanish → 表示）、既定の段落スタイル（pStyle のない段落）、basedOn の循環で止まること。
  - `joined_paragraphs`・`unjoined_deleted_marks`: 本文の最後（w:sectPr の前）・次が w:ins のブロック・コメントの目印をはさむもの・3 段落の連鎖の
    途中が表の直前（2 段落で止まる）。
  - `canonical_texts`: 連鎖の後ろの ID がない、連鎖の文字が連結になる。

### 7.3 tests/test_pipeline.py

- docs/fix_plan_repro_tests.py の `test_PROBLEM_deleted_paragraph_mark_keeps_two_paragraphs` の期待を逆にして取り込む
  （`test_deleted_paragraph_mark_joins_paragraphs`: 「前半の文と後半の文。」が 1 つの `<p>` で、「前半の文と」だけの `<p>` がない。不変性合格）。
  あわせて、節見出し＋本文が 1 つの `<title>`（見出しのまま）、文字ごと削除した節見出し＋本文が `<p>` になること（FIX_PLAN の付録 D5）。
  取り込んだテストは fix_plan_repro_tests.py から消し、冒頭の docstring に「単位 G（0.26.0）で取り除いたもの」を足す。
- U3（sample_reader）: td・th の中に `<break/>` があり、その直後（tail の先頭）に "\n" がある。太字の改行は `<bold>…</bold><break/>\n<bold>…</bold>`。
  リンクの中には `<break/>` がない。`<p>`・`<mixed-citation>`・`<article-title>` には `<break/>` がない（"\n" は残る）。段落の最後の改行の後に
  段落の間の `<break/>` が続くセルも DTD に合う。不変性・最終・DTD 合格、`fid.drops` が「姓と名の間の空白」だけ（`test_fidelity_and_dtd` が見る）。
- レポート: 10 章に改行の一覧（セル・知らせる文脈・そのほかの 3 行）、冒頭と 14 章に要確認「題目・著者・所属・引用文献の中の改行」（`Action` の key
  "newline"）、6 章につないだ段落と削除された行の行、4 章にスタイルの違う連鎖の Decision。
- sample_edge（本文の段落の改行 1 つ）: 10 章に「本文などの段落の中の改行」の 1 行が増え、1 章の警告の件数が 1 増える。XML は変わらない。
  `test_edge_cases`（`tracked_changes == 2` など）は変わらない。
- `report.actions` の要確認（終了コード 0）: 改行の Action だけなら `needs_action` は偽（CLI の終了コード 0）。

### 7.4 tests/test_pdfmatch.py（ルート2）

- `make_pdfcheck(tmp_path/…, split=True)` と今の sample_pdfcheck.pdf でルート2: つないだ段落が 1 つの段落 ID で照合され、「資料→付録」「2→２」が
  直り、XML が 1 つの `<p>`、直した docx を読み直した文字が直した結果と同じ（`_verify` が空）、不変性・DTD 合格。
- 段落記号の削除をまたぐ直し: `_apply_paragraph` に、2 つの w:p の単位を連結した units と、前の w:p の最後の文字と後ろの w:p の最初の文字にかかる Fix を
  渡し、直した木の w:t がそれぞれの w:p に分かれて書き込まれ、読み直した文字（`paragraph_units` の連結）が `expected_text` と同じ（FIX_PLAN の付録）。
- `paragraph_units(p, rule)` の文字の連結が、読み取りの `Para.plain()` と同じ（sample_reader のすべての段落のうち `_Complex` でないもの。連鎖は
  w:p の単位を連結して比べる。U8 の段落を含む）。3 か所（読み取り・canonical_texts・paragraph_units）が同じ文字になることを、ここでまとめて確かめる。

### 7.5 既存テストの書き換え

- `test_reader_matches_canonical`（7.2）。そのほかは、件数で確かめるテスト（sample_edge の tracked_changes など）に触れないので書き換えはない見込み。
  sample_reader の段落が増えるので、sample_reader の段落の件数や ID に頼るテストがないこと（今もない。段落の文字で選んでいる）を確かめる。
- `tests/__pycache__` がリポジトリにある（この設計の前からあった）。テストの後に消す。

---

## 8. 合格の条件（物差しごと）

- **pytest**: 3.13 と 3.10（`PYTHONPATH=src …/venv310/bin/python -m pytest -q -p no:cacheprovider`）ですべて合格。試作（D5・U8・U3・N8 の読み取り・
  検証・ルート2・emit だけ）で、既存の 891 件はすべて合格した。
- **ruff**: `ruff check src tests tools` の件数が HEAD より増えない。
- **golden**（23 件）: 違ってよいのは次だけ。違いは本体を diff して 1 つずつ理由を書く。
  - sample_reader_manual・sample_reader_split: 新しい節（XML・レポート・AI 依頼文）。
  - sample_edge_manual・sample_edge_split: レポートの 10 章の「本文などの段落の中の改行」の 1 行と、1 章の警告の件数（XML は同じ）。
  - ほかの 19 件は同じ（試作では、レポートを変えていないので 23 件すべて同じだった。fixture に G の要素があるのは sample_edge の本文の改行 1 つと
    直接の隠し文字 1 つだけで、どちらも XML は変わらない）。「変更履歴が N 箇所あります」の文は変えないので、sample_structure・pdfcheck_route2 の
    レポートは変わらない。
- **td1〜3（tests/private/colab）**: ルート1・ルート2 とも、0.25.0 と比べて
  - td1・td2: XML・レポート・直した docx がすべて同じ（試作で確かめた。G の要素がない）。
  - td3: XML は `<break/>` 17 個が増えるだけ（`<break/>` を除くと同じ。試作で確かめた）。レポートは、10 章に改行の一覧（セルの行と、知らせる文脈〈題目・英文の題目〉の行）
    と、冒頭・14 章・Colab の赤い枠に要確認「題目・著者・所属・引用文献の中の改行」（題目と英文の題目に 1 つずつ）が増える。直した docx は同じ。
  - 不変性・最終・DTD・J-STAGE のチェックは合格。XML に入らなかった画像は増えない。
- **本誌の出版版 PDF（tests/private/pdf）の確かめ用 docx**（`b21/isolate/realpdf/out/docx` の 7 本。PDF の文字から作ったもの）: G の要素が 0 件
  （`realpdf_counts.json`）なので、ルート2 の結果が 0.25.0 と同じ（実装の後に、realpdf の check.py で確かめる）。
- **架空の境界の例**（`scratchpad/g/design/lo/*.docx` と、それを作るスクリプト）: 試作と同じ結果（3 章・4.2・5 章）で、不変性・DTD 合格。

---

## 9. 残る限界と、利用者に確かめてもらうこと

- **Word での確かめ（DEVELOPMENT の「残っている課題」に足す）**:
  1. sample_reader.docx を Word で開いて「すべての変更を反映」した後の段落のつながりとスタイル（D5）。特に、LibreOffice と違う 3 つ（sdt・customXml の
     境界、段落記号の moveFrom、脚注の参照のある段落）と、書式の元（前の段落が空なら後ろ。画像だけの段落）と、番号の数え方。
  2. スタイルの隠し文字の表示（U8）。特に、LibreOffice に合わせた 2 か所（4.2 の 1・2）と、specVanish だけのラン。
  3. 削除されたセル（w:cellDel）を承諾した後の表の形（LibreOffice は列ごと消す）。
- **J-STAGE の試験登載で確かめること**: セルの `<break/>`（段落の間のものも。マニュアルの td・th の文字修飾の一覧に載っていない）の表示と、
  アップロード時のエラーの有無（6.2）。
- **限界（DESIGN.md 7 章に書く）**: 段落をまたぐフィールドは扱わない。つないだ段落の後ろの w:p の隠し文字は、その w:p 自身の段落スタイルで決める。
  画像だけの段落は書式の元にならない。数式・表スタイル・番号の書式・段落記号の vanish は扱わない。docDefaults の vanish は LibreOffice の中でも表示が
  食い違う。隠し文字だけの段落は「空白のみの段落」の理由で除外される。削除されたセルは出力する。sdt・customXml の境界の段落記号の削除はつながない
  （警告だけ）。
- **実際の原稿の件数**（`td_counts.json`。数だけ）: td1〜3 に、段落記号の削除・移動 0、段落記号の vanish 0、隠し文字（直接・スタイル・docDefaults）0、
  削除・挿入の変更履歴 0、削除された行・セル 0。改行（w:br・w:cr）のある段落は td3 だけで、docx の w:p で数えると、表のセルの中 7・テキストボックスの中 4（祖先に txbxContent があるもの。
  テキストボックスの中の表のセルを含む）・そのほか 2（題目と英文の題目）。0.25.0 の XML では、改行の文字は td の中に 14 か所の文字の並び（改行の数で 17）と、
  `article-title`・`trans-title` に 1 つずつ（`td_br.py`）。
  本誌の出版版 PDF の確かめ用 docx 7 本はすべて 0。→ G で出力が変わるのは td3 のセルの `<break/>` 17 個と、題目の改行の要確認だけ。
  D5・U8・N8 は、実際の原稿では確かめられない（架空の fixture だけ）。

---

## 10. 変更するファイルの一覧（実装の担当向け）

| ファイル | 変更 |
|---|---|
| src/jasme_jats/ooxml.py | 冒頭の文字ポリシーの docstring（段落記号の削除・スタイルの隠し文字・扱わないもの・削除された行）、`HiddenRule`・`NO_RULE`、`JOIN_SKIP`・`paragraph_mark_deleted`・`_join_target`・`joined_paragraphs`・`unjoined_deleted_marks`・`canonical_texts`、`canonical_text(p, hidden=None)`、`run_hidden` を消す |
| src/jasme_jats/docx_reader.py | 2.4 のとおり（`__init__`・`_set_joins`・`read`・`read_notes`・`read_block`・`read_paragraph`・`_textboxes`・`_read_nested_paragraph`・`_read_nested_table`・`_walk`）、`read_table` の削除された行・セル（5 章）、`_plain_of_run_child` の拡張（4.5）、モジュールの docstring |
| src/jasme_jats/model.py | `Document.joined`・`joins`・`deleted_rows`、`JoinInfo`・`DeletedRow`（と、emit の `Newline` を置くならここ） |
| src/jasme_jats/fidelity.py | `source_texts` が `HiddenRule` と `canonical_texts` を使う。docstring |
| src/jasme_jats/pdfdocx.py | `paragraph_units(p, hidden=None)`、`_chains`、`write_fixed_docx`（2.7）、モジュールの docstring（つないだ段落・隠し文字） |
| src/jasme_jats/emit.py | `Ctx.breaks`・`newline_label`、`CELL`・`TITLE`・`NAME`・`AFF`・`REF`、`Emitter.breaks`・`newlines`、`span`、`write_inline` の `flush` |
| src/jasme_jats/builder.py | `BuildInfo.newlines`、`build` の最後の改行の一覧と 10 章の警告 |
| src/jasme_jats/structure.py | `Classifier.run` の最後に、スタイルの違う連鎖の Decision |
| src/jasme_jats/pipeline.py | `Result.joined`・`deleted_rows`・`newlines` を渡す |
| src/jasme_jats/report.py | 6 章の 2 行（つないだ段落・削除された行）、`_newline_action` と `actions()` への追加 |
| src/jasme_jats/__init__.py・pyproject.toml | 0.26.0 |
| notebooks（tools/make_notebook.py で作り直す） | 版の表示だけ（スクリプトは変えない） |
| tests | 7 章のとおり（make_fixtures.py・fixtures/sample_reader.docx・test_reader.py・test_pipeline.py・test_pdfmatch.py。test_structure.py は Decision を見るなら） |
| docs/DESIGN.md | 4.1 文字ポリシー（段落記号の削除・スタイルの隠し文字・扱わないもの・削除された行・セルの改行）、4.3（つないだ段落は「出力しない段落」ではない。削除された行）、4.4（ルート2 のつないだ段落）、7 章の限界 |
| docs/DEVELOPMENT.md | 守るべき原則 5（`ooxml.canonical_text` だけでなく、`canonical_texts`・`joined_paragraphs`・`HiddenRule` を読み取り・検証・`pdfdocx.paragraph_units`/`write_fixed_docx` で共有する）、テストの節（sample_reader の新しい節）、残っている課題（9 章の確かめ） |
| CLAUDE.md | 最優先の原則に「段落のつながり（`ooxml.joined_paragraphs`）と隠し文字の判定（`ooxml.HiddenRule`）は、読み取り・検証・ルート2 で共有する」を 1 行（FIX_PLAN の計画全体の作業） |
| docs/STYLE_MAPPING.md | 37 行の「セルの複数段落は `<break/>` でつなぐ」に「セルの段落の中の改行（Shift+Enter）の位置にも `<break/>` を入れる（改行の文字も残す）」 |
| docs/JSTAGE_NOTES.md | 6.2 の根拠（マニュアル 3.5.4 (6) の td・th の文字修飾、別紙 1 の修飾タグ許容一覧、試験登載で確かめること） |
| docs/FIX_PLAN.md | G の節に暫定の注記（冒頭）と、4.2 の 2 か所の規則の変更、5.2 の削除されたセルの扱い、付録の D5 の sample_pdfcheck_split.docx を「テストの中で作る」に。反映の順序の表の G の「（実装済み）」 |
| docs/fix_plan_repro_tests.py | D5 のテストを取り除き、docstring に G の行 |
| README.md | レポートの見方に、10 章の改行の一覧・要確認の改行（利用者向けの説明があれば） |
</content>
</invoke>
