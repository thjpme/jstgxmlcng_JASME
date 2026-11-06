# 単位 u1-small（0.30.0）: 小さい独立の修正（sanitize・AI の回答の形・引用文献の曖昧さ・自動番号の上書き）

## 要点

- 目的: 互いに独立した 4 つの小さい不具合を直す。(1a) `tools/sanitize_docx.py` が入力と出力に同じファイルを指定すると原稿を壊す・個人情報を取り残す（O5）。
  (1b) `ai_assist.parse_response` が最上位が一覧（`[ ]`）の回答や `operations` のない回答を「操作 0 件」で黙って通し（A9）、深い入れ子の回答で変換が `RecursionError` で止まる（A10）。
  (1c) `refparse.match_citation` が同じ第一著者・同じ年の文献 3 件以上で曖昧さを取り違える（K10）。(1d) `numbering.py` が `w:lvlOverride/w:lvl` を無視する（R6）。
- 直し方: (1a) sanitize を lxml で作り直し、同じファイルを断り、一時ファイルに書いて本文の文字が同じことを確かめてから置き換える。変更履歴の作成者・ヘッダー/フッターの文字（ページ番号のフィールドは残す）・customXml・
  テンプレートのパス・文書のプロパティ（題目を含む）を取り除く。テンプレートの fixture を sanitize し直して fixture を作り直す（`sample_pdfcheck.pdf` は git で戻す）。
  (1b) 最上位の一覧を断り、`operations` を必須にし、`RecursionError` を読めない回答として扱う。`split_ops` の `{ }` でない操作は `outcome.rejected` に理由付きで記録する。
  (1c) 最大の当てはまりの候補の数で曖昧さを決める。(1d) 上書きの `w:lvl` に書かれた子要素だけを `abstractNum` の段の値に重ねる。
- 実際の原稿での影響: 出力（XML）の違いは 0 件。tests/private の docx 10 件（テストデータ1〜5 の 9 件とテンプレート）すべてに sanitize で取り除く個人情報があった。
  引用の照合 750 件で K10 の直しによる違いは 0 件、`w:lvlOverride` は 0 件。公開リポジトリのテンプレートと fixture 14 件に、ユーザー名を含むローカルのパスが残っている（直す。git の履歴は利用者の返事待ち）。
- 順: 0.30.0 の最初の commit は (1a)（sanitize と fixture の作り直し）だけにし、その直後に 0.29.0 のコードで回帰の基準を取る。(1b)(1c)(1d) は u2 と並行してよい。版は 0.30.0 の最後に 1 回だけ上げる。
- 担当: 作るのは (1a)(1b)(1d) が Sonnet（エフォート medium）、(1c)（4 行の直しとテスト）が Haiku（エフォート low）。点検は Opus（エフォート medium）。Opus が自分で書く部分はない。
  点検で見るのは (1a) ヘッダー/フッターのフィールドの判定と作り直した fixture の `git diff --stat`、(1b) `parse_cut_response` の一覧の判定と深い入れ子の期待（`None`）、(1d) `_levels` が `self.abstract` の共有の dict を書き換えていないこと。

## 再現（確かめたこと）

再現と試作のスクリプトは `docs/fix_plan_2026-11/protos/u1-small/` と `docs/fix_plan_2026-11/protos/review-u1-small/` にある。
どちらも計画のときの作業フォルダ（scratchpad）のパスを前提に書かれていて、そのままでは動かない。手本として読むものである。出力のフォルダ・生成した docx・画像は写していない。

| 項目 | 結果 | スクリプト | 見たこと |
|---|---|---|---|
| (1a) `sanitize(src, src)` | 再現 | `u1-small/repro_1a.py` | `sample_full.docx` の写し（48201 バイト）に `sanitize(p, p)` を当てると、`BadZipFile`（Truncated file header）のあと 22 バイトの空の ZIP になり、元の内容が失われた。`zipfile.ZipFile(dst, "w")` を入力を読む前に開くため |
| (1a) O5 の取り残し | 再現 | `u1-small/survey_o5.py` | 実際の原稿 10 件すべてに、header/footer の部品 6 個（文字のランは 2）、`customXml/` の部品 3〜5 個（Word の文献管理 `b:Sources`。文献 0 件）、`settings.xml` の `w:attachedTemplate` と `word/_rels/settings.xml.rels` の外部パス、core の `dc:title`・`dc:creator`・`cp:lastModifiedBy`、app の `Template`・`Company`、app の `TitlesOfParts` の `vt:lpstr`（11 件すべて空でなく、うち 3 件は `dc:title` と同じ文字）があった。`docProps/custom.xml`・`w:initials`・`w:docVar`・`w:dataBinding` は 0 件。`w:author` はテンプレートの comments.xml の 2 件だけ。公開リポジトリの `tests/fixtures/JASME_template_20261009.docx` とそれを元にした fixture 14 件の `word/_rels/settings.xml.rels` に、ユーザー名を含むローカルのパスが残っている |
| (1a) 試作で本文が変わらないか | 確かめた | `u1-small/sanitize_proto.py`・`run_sanitize_proto.py --convert` | 実際の原稿 10 件と fixture 15 件で、`fidelity.source_texts`・`read_docx` の（段落 ID・文字・自動番号）・ルート1 の XML（バイト単位）が sanitize の前後で同じ。LibreOffice で開けることも確かめた（`review-u1-small/lo_check.py`。Word では未確認） |
| (1a) fixture の作り直し | 確かめた | `review-u1-small/`（写したリポジトリで実行） | 試作の sanitize をテンプレートに当てて `make_fixtures.py` を実行すると、既存のテスト 1298 件はすべて通った。ただしヘッダー/フッターを丸ごと空にする試作では、作り直した PDF から各ページのページ番号が消えた（直し方でページ番号のフィールドを残す） |
| (1b) A9 `[{"op": …}]` | 再現 | `u1-small/repro_1b.py`・`repro_1b_pipeline.py` | 外側の `[ ]` を捨てて `{op…}` を dict として読み、`operations` がないので操作 0 件。コードブロックで囲んだ形・後ろに文がある形も同じ。手動モードの convert で `res.ai.error` が空、`actions()` が空、`needs_action` が False。最上位が操作 1 件の `{"op": …}` も同じく通る |
| (1b) A9 `[{…},{…}]` | 再現せず | `u1-small/repro_1b.py` | 最初の要素だけを読むことはなく、「n 行目 m 文字目で JSON として読めません（Extra data）」になる（`_before_trailing_text` は最後の `}` の後ろに文字があるときだけ読み直す）。原因（一覧であること）を示さない。`[]` は「JSON が見つかりません」 |
| (1b) 一覧の回答が途中で切れる | 再現 | （点検で確かめた） | `parse_cut_response` は `t.find("{")` から読むので、切れた一覧の中の placements を部分の回答として返す |
| (1b) A10 | 再現 | `u1-small/repro_1b_a10.py`・`repro_1b_deep_ok.py`・`review-u1-small/deep_ok.py` | Python 3.13 では深さ 3000 まで読め、上限（約 9998）の少し手前の入れ子も convert まで例外なし。深さ 20000 では `parse_response` と `parse_cut_response` の両方が `RecursionError`。convert では `parse_response` の例外は pipeline の `except Exception` で捕まるが、続く `_read_cut` → `parse_cut_response` の `json.loads`（ai_assist.py 1059 行目）が投げて捕まらず、変換が止まった。3.10・3.11 ではもっと浅い（約 1000）はず（未確認） |
| (1c) K10 共著・共著・単著 | 再現 | `u1-small/repro_1c.py`・`repro_1c_real.py` | 共著の引用が `(B1, "exact")`（正しくは特定できない） |
| (1c) K10 単著・共著・単著 | 再現 | 同上 | 共著の引用が `(None, "ambiguous", …B1、B2、B3)`（正しくは `B2` の exact）。単著の引用の説明に当てはまらない B2 も挙がる |
| (1c) 同じ形のコード | なし | grep | 先頭と末尾だけを比べる判定は refparse.py 323 行目だけ |
| (1d) R6 | 再現 | `u1-small/repro_1d.py`・`numfix.py` | `abstractNum 0`（`%1.`・decimal）を指す num 92（上書きの lvl: upperLetter・`(%1)`）と num 93（startOverride 5 と lvl: lowerRoman・`%1)`）の autonum が `1.`・`2.`・`5.`（正しくは `(A)`・`(B)`・`v)`） |
| (1d) 子要素の足りない上書き | 確かめた | `review-u1-small/partial.py` | 子要素の足りない上書きを既定値で置き換える案では、start だけ・numFmt だけの上書きの label が `''` になる（今のコードでは `(1)(2)`・`(1)`）。重ねる案を採る |
| (1d) ルート2 | 確かめた | `u1-small/repro_1d_route2.py` | 直す前は PDF の `(A)(B)` との違い 2 件が直せない違いになり要確認 pdf_unfixed。直した後は違い 0。PDF が全角の `（Ａ）（Ｂ）` なら number_edits 2 件、補完の確かめ・不変性チェックとも合格 |
| 試作をすべて当てた既存のテスト | 確かめた | `u1-small/plug/allfix.py`・`plug/opsprobe.py` | 1298 件すべて通った。既存のテストで `parse_response` が読む 151 回の回答はどれも `operations` を持つ |

tests/private の実際の原稿での件数（`u1-small/private_1c.py`・`survey_1d.py`）: 引用の照合 750 回（テストデータ1: 68、2: 71×2、3: 30×3、4: 211×2、5: 28、テンプレート: 0）で直す前後の違い 0。
種別は exact 727、missing 10、year_mismatch 2、unparsed 1、ambiguous 0。`w:lvlOverride`・`w:isLgl`・`w:lvlRestart` は 10 件とも 0。fixture 15 件も 0。

## 直し方

### (1a) tools/sanitize_docx.py（作り直す。本文の文字には触れない）

依存: `lxml`、`jasme_jats.ooxml.w`、`jasme_jats.pdfdocx.AUTHOR`、`jasme_jats.fidelity.source_texts`（editable install 済みなので import できる）。
`posixpath`・`tempfile`・`os`・`zipfile`・`re`・`sys`。

定数:

```python
AUTHOR_PLACEHOLDER = "作成者"
SAME_FILE_MSG = "入力と出力に同じファイルが指定されています。元の docx を残すため、出力には別のファイル名を指定してください"
CHANGED_MSG = "本文の文字が変わったので書き出さなかった（このツールの不具合です）"
COMMENT_PARTS = re.compile(r"word/(?:comments|commentsExtended|commentsExtensible|commentsIds|people)\.xml$")
DROP_PARTS = re.compile(r"(?:customXml/.*|docProps/custom\.xml|docProps/thumbnail\.[A-Za-z]+)$")
HF_PART = re.compile(r"word/(?:header|footer)\d*\.xml$")
PAGE_FIELD = re.compile(r"(?:PAGE|NUMPAGES|SECTIONPAGES)\b", re.I)
LOCAL_PATH = re.compile(r"^(?:file:|[A-Za-z]:\\|\\\\|/Users/|/home/)|Users\\")
```

`_dropped(name) -> bool`: `COMMENT_PARTS.match(name) or DROP_PARTS.match(name)`。`docProps/thumbnail.*` は 1 ページ目の画像（題目・氏名が写る）。

`sanitize(src, dst)`:

1. `src, dst = Path(src), Path(dst)`。どのファイルも開く前に、`dst.exists() and os.path.samefile(src, dst)` なら `ValueError(SAME_FILE_MSG)`。シンボリックリンク・ハードリンクも samefile で見分けられる。
2. `fd, tmp = tempfile.mkstemp(suffix=".docx", dir=dst.parent)`、`os.close(fd)`。以下を try/finally で包み、finally で tmp が残っていれば消す。
3. `zipfile.ZipFile(src)` の `infolist()` を順に見る。ディレクトリの項目もそのまま写す（実際の原稿 9 件にディレクトリの項目がある）。`_dropped` なら写さない。それ以外は `zout.writestr(item, clean_part(name, data))`。
4. 書き出した tmp を確かめる。`source_texts(src) != source_texts(tmp)` か、`word/media/` の名前の集合が違えば `ValueError(CHANGED_MSG)`（dst には触れない）。
   あわせて、残った rels のうち `TargetMode="External"` で Target が `LOCAL_PATH` に当たるものがあれば、
   `"警告: 外部のパスを含む関係が残っています（" + 部品名 + "、" + Type の最後の / より後ろ + "）"` を標準エラーに出す（パスそのものは出さない。書き出しは止めない）。
5. `os.replace(tmp, dst)`。

`clean_part(name, data) -> bytes`: lxml で読み、変えたときだけ `etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)` を返す。変えなければ元のバイト列を返す。

- `word/` の下の `.xml`（取り除かないもの。document・footnotes・endnotes・header・footer・settings など）に、次を順に当てる。
  1. `w:commentRangeStart`・`w:commentRangeEnd`・`w:commentReference` を取り除く。取り除いた後、親が `w:r` で、残る子が `w:rPr` だけ（または子がない）なら、その `w:r` も取り除く。footnotes・endnotes の中のコメントの範囲もこれで消える（今の正規表現の実装は document.xml だけを見ていた）。
  2. `w:author` 属性を持つすべての要素で、値が `pdfdocx.AUTHOR` でなければ `AUTHOR_PLACEHOLDER` にする。`AUTHOR` は残す（`fidelity._ours`・`verify_supplement` の old_ids・`pdfdocx.tracked_counts` がこのツールの変更履歴を作成者名で見分けるため）。`w:initials` 属性は空にする。`w:date`・`w:id` は変えない。
  3. ヘッダー/フッター（`HF_PART`）では、文字のランだけを取り除く。部品の全体を文書の順（`root.iter()`）に見て、フィールドの状態をスタックで持つ（段落をまたぐフィールドもあるので、段落ごとに戻さない）。
     - `w:fldChar` の `w:fldCharType` が `begin` なら `{"instr": "", "sep": False}` を積む。`separate` なら一番上の `sep` を True に、`end` なら一番上を降ろす（空なら何もしない）。
     - `w:instrText` の文字は、一番上が `sep` でなければその `instr` に足す。
     - `w:r` で、直接の子に `w:t` か `w:delText` があるもの（`run.find(w("t"))` のように直接の子だけを見る。テキストボックスを含むランの子孫の `w:t` で判定しない）は、次のどちらでもなければ取り除く候補にする:
       (a) スタックが空でなく、一番上が `sep` で、`PAGE_FIELD.match(instr.strip())`。(b) 祖先に `w:fldSimple` があり、その `w:instr` が `PAGE_FIELD.match(instr.strip())`。
     - 見終わってから候補をまとめて取り除く（iter の途中で木を変えない）。段落・`w:pPr`・`w:sdt`・`w:fldChar`・`w:instrText` のランは残す。
     テンプレートのヘッダー（文字なし）とフッター（PAGE のフィールドの結果だけ）は変わらず、元のバイト列のまま残る。
  4. `word/settings.xml` では `w:attachedTemplate` を取り除く。
- `*.rels`: 次の Relationship を取り除く。Type が `/attachedTemplate` で終わるもの。または TargetMode が External でなく、ターゲットが `_dropped` の部品であるもの。
  ターゲットは、Target が `/` で始まれば先頭の `/` を除いたもの、そうでなければ `posixpath.normpath(posixpath.join(posixpath.dirname(posixpath.dirname(rels_name)), Target))`
  （`word/_rels/document.xml.rels` なら `word`、`_rels/.rels` なら `""` が基準）。外部のハイパーリンクは本文のリンクなので残す。
- `[Content_Types].xml`: PartName（先頭の `/` を除く）が `_dropped` の部品である `Override` を取り除く（`Default` は変えない）。
- `docProps/core.xml`: `dc:creator`・`cp:lastModifiedBy`・`dc:title`・`dc:subject`・`dc:description`・`cp:keywords`・`cp:category` の text を空にする（要素は残す）。
- `docProps/app.xml`（名前空間 `http://schemas.openxmlformats.org/officeDocument/2006/extended-properties`）: `Company`・`Manager`・`HyperlinkBase` の text と、
  `TitlesOfParts` の下のすべての `{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}lpstr` の text を空にする（要素の数と `HeadingPairs` は変えない）。
- そのほかは元のバイト列のまま。

取り除かないもの（モジュールの docstring に書く）: `w:rsid*`、`w14:paraId`、変更履歴の `w:date`、本文の `w:customXml` 要素（本文の文字を包むもの）、外部ハイパーリンク、styles・numbering・theme・fontTable、ヘッダー/フッターのページ番号のフィールド。

コマンドライン: `main(argv=None)`。引数が 2 つでなければ使い方を標準エラーに出して終了コード 2。`(ValueError, OSError, zipfile.BadZipFile)` を捕まえて、文を標準エラーに出し終了コード 1（トレースバックを出さない）。
成功したら今までどおり `written: …` を出して 0。`if __name__ == "__main__": sys.exit(main())`。

モジュールの docstring を書き直す: 取り除く部品・空にするもの・置き換えるもの（作成者）・残すもの・同じファイルを断ること・書き出す前の確かめ（本文の文字と画像の名前）・外部パスの警告。

テンプレートと fixture の作り直し（(1a) の commit に含める）:

1. `python tools/sanitize_docx.py tests/fixtures/JASME_template_20261009.docx <別名>.docx` を実行し、`<別名>` でテンプレートを置き換える（同じファイルは断られる）。
2. `python tests/make_fixtures.py` を実行する（soffice があると `sample_pdfcheck.pdf` も作り直される）。
3. `git diff --stat tests/fixtures` を見る。docx 15 件のバイト列が変わる（make_fixtures は ZIP の日時を固定しない）。`git checkout tests/fixtures/sample_pdfcheck.pdf` で PDF を戻す。
4. 全テストを通す。新しいテンプレートの `word/_rels/settings.xml.rels` に外部パスがないこと、fixture 14 件にもないことを `unzip -p` か小さいスクリプトで確かめる。
5. git の履歴を書き換えるかは利用者の返事待ち。書き換えはこの作業に含めない。

### (1b) src/jasme_jats/ai_assist.py

定数（parse_response の近く。文は、何が違うかと正しい形までを書き、頼み方は手動のときだけの指示と分かる形にする。画面の手順番号・欄の名前は書かない。「回答の書き方」は依頼文の節の名前）:

```python
ASK_AGAIN = ("チャットで使っているときは、AI に「回答の書き方の見本の形で、```json のコードブロック 1 つで"
             "出し直してください」と頼んでください")
TOP_ARRAY_MSG = ("回答の JSON が一覧（[ ] で囲んだもの）になっています。回答は見本のとおり、{ で始まり placements・"
                 "operations・notes を持つ 1 つのまとまりにします。" + ASK_AGAIN)
SINGLE_OP_MSG = ("回答の JSON が操作 1 件だけ（op を持つ { }）になっています。操作は operations の一覧の中に書きます。" + ASK_AGAIN)
NO_OPS_MSG = ("JSON に operations の一覧がありません（提案する操作がないときも \"operations\": [] と書く決まりです）。" + ASK_AGAIN)
OPS_NOT_LIST_MSG = "JSON の operations が一覧（[ ]）になっていません"
DEEP_MSG = "JSON の入れ子（[ ] や { } の中の [ ] や { }）が深すぎて読めません。" + ASK_AGAIN
```

`_top_level_array(t: str) -> bool`（t は `_json_text` の結果）:

```python
def _top_level_array(t: str) -> bool:
    """回答の JSON の最上位が一覧（[ ]）か。最初の { の直前（空白を除く）が [ なら、一覧の最初の要素とみなす。"""
    if t.startswith("{"):
        return False
    i = t.find("{")
    return i > 0 and t[:i].rstrip().endswith("[")
```

`{` のない回答（`[]` や `[` で始まる地の文）は一覧とみなさず、今の「JSON が見つかりません」の文になる。コードブロックの `` ```json\n[{ `` は `RE_FENCE` が `{` の先読みで当たらないので回答全体が t になり、この判定で当たる。`RE_FENCE` は変えない（変えると `parse_cut_response` の切り出しが変わる）。

`parse_response`（921 行目〜）:

1. `t, _ = _json_text(text)` の直後に `if _top_level_array(t): raise ValueError(TOP_ARRAY_MSG)`。
2. `json.loads(t)`（936 行目）の try に `except RecursionError: raise ValueError(DEEP_MSG) from None` を足す（`except json.JSONDecodeError` の枝は今のまま）。
   `_before_trailing_text` の `json.loads` は `except (json.JSONDecodeError, RecursionError): return None`。
3. 950〜951 行目を次に置き換える:
   ```python
   if not isinstance(data, dict):
       raise ValueError(NO_OPS_MSG)
   if "operations" not in data:
       raise ValueError(SINGLE_OP_MSG if "op" in data else NO_OPS_MSG)
   if not isinstance(data["operations"], list):
       raise ValueError(OPS_NOT_LIST_MSG)
   ```
   placements（なければ `[]`。`tests/data/ai_response_sample_full.json` は placements を持たない）と notes は今までどおり省略できる。
4. docstring に足す: 最上位が一覧（`[ ]`）の回答は読まない（回答全体を一覧で囲んだ `[{placements, operations, notes}]` も読まない）。`operations` は必須（操作がなくても `[]`）。深すぎる入れ子は読めない回答とする。

`operations` を必須にする根拠: 4 つの API（Claude・OpenAI・Gemini・Sakana）の構造化出力はどれも `RESPONSE_SCHEMA`（required に placements・operations・notes）を使い、
手動とスキーマなしの依頼文も「提案する操作がなければ "operations": [] とし」（745・910 行目）と求めている。推測で補わない原則にも合う。途中で切れた回答は `parse_cut_response` が今までどおり読む。

`parse_cut_response`（1043 行目〜）:

1. `t, closed = _json_text(text)` の直後に `if _top_level_array(t): return None`（切れた一覧の中の placements を推測で読まない）。
2. 最初の `json.loads(t)`（1059 行目）に `except RecursionError: return None` を足す。
   深い入れ子は、C の読み取りが入力の終わりに届く前に `RecursionError` になるので、途中で切れた回答でも最後まで書かれた要素を読まずに `None` になる。それでよい（切れたかどうかを決められない）。
3. 要素を読むループの `except json.JSONDecodeError: pass`（1097 行目）を `except (json.JSONDecodeError, RecursionError): pass` にする（守りとして置く。2 で先に返るので実際には届かない）。
4. docstring に「入れ子が深すぎる回答と、最上位が一覧の回答は、読まない（None）」と書く。

pipeline.py は変えない。手動・API のどちらでも、`parse_response` の `ValueError` → `_read_cut` → `None` → `outcome.error` になる（API で `outcome.cut` のときは今までどおり）。

`split_ops`（1120 行目〜）の 1127〜1128 行目 `if not isinstance(raw, dict): continue` を次にする:

```python
if not isinstance(raw, dict):
    if outcome is not None:
        op = {k: "" for k in OP_SCHEMA["properties"]}
        op["occurrence"] = 1
        if isinstance(raw, str):
            op["text"] = raw[:80]
        outcome.rejected.append((op, "操作が { } のまとまりでない（" + type(raw).__name__ + "）ので、この操作は使わなかった"))
    continue
```

一覧・辞書は `json.dumps`・`repr` しない（深い入れ子で `RecursionError` になる）。f 文字列の中に波括弧を書かず、文字列をつなげる。docstring の「outcome.rejected に記録して除く」の対象に「{ } でない操作」を足す。
レポートの 2 章の不採用の表（report.py 1771〜1776 行目）と AI の判断の一覧（2295〜2298 行目）は `op.get(...)` で読み、`table` が `esc` を通すので、そのまま表示できる。

### (1c) src/jasme_jats/refparse.py match_citation（exact の枝、322〜325 行目）

```python
best = max(fit(x) for x in exact)
top = [x for x in exact if fit(x) == best]
if len(top) > 1:
    return None, "ambiguous", "同じ著者・同じ年の文献が複数あり、どれか特定できない: " + "、".join(x.rid for x in top)
return top[0], "exact", ""
```

`r = max(exact, key=fit)` と今の if を置き換える。候補が 1 つ・2 つのときの結果は今と同じ。説明に挙げるのは最大の当てはまりの候補だけにする。

### (1d) src/jasme_jats/numbering.py

モジュールの関数と定数を足す:

```python
DEFAULT_LEVEL = {"start": 1, "fmt": "decimal", "text": ""}


def _level(lvl) -> dict:
    """abstractNum の段の定義（w:lvl）。子要素がなければ既定値（DEFAULT_LEVEL と同じ）。"""
    return {"start": int(wval(lvl.find(w("start")), "1") or 1),
            "fmt": wval(lvl.find(w("numFmt")), "decimal"),
            "text": wval(lvl.find(w("lvlText")), "")}


def _level_present(lvl) -> dict:
    """num の w:lvlOverride/w:lvl の、書かれている子要素（start・numFmt・lvlText）だけの dict。"""
    out = {}
    el = lvl.find(w("start"))
    if el is not None:
        out["start"] = int(wval(el, "1") or 1)
    el = lvl.find(w("numFmt"))
    if el is not None:
        out["fmt"] = wval(el, "decimal")
    el = lvl.find(w("lvlText"))
    if el is not None:
        out["text"] = wval(el, "")
    return out
```

- abstractNum の段の読み取り（98〜102 行目）を `levels[il] = _level(lvl)` にする（既定値は今と同じ。R9 の `int()` の保護はこの単位では足さない。R9・R11 で段の属性を足すときは `_level` と `_level_present` に足す）。
- `__init__`: `self.lvl_overrides = {}  # numId -> {ilvl: 書かれた子要素だけの段の定義}` を足す。108〜112 行目の各 `w:lvlOverride` で、ilvl は lvlOverride の `w:ilvl` から取る（中の `w:lvl` の `w:ilvl` ではない）。
  `w:startOverride` は今までどおり `overrides[il]`。中に `w:lvl` があれば `self.lvl_overrides.setdefault(nid, {})[il] = _level_present(lv)`。`self.nums[nid] = (aid, overrides)` の形は変えない。
- `_levels(self, num_id) -> dict`（label のたびに作る。`_follow_style_links` が `self.abstract` を後から置き換えるので `__init__` で固めない。`self.abstract` の dict は複数の abstractNum で共有されているので書き換えない）:
  ```python
  def _levels(self, num_id) -> dict:
      """num の段の定義: abstractNum の段に、w:lvlOverride/w:lvl に書かれた子要素を重ね、w:startOverride で開始番号を置き換える。"""
      aid, starts = self.nums[num_id]
      base = self.abstract.get(aid, {})
      levels = dict(base)
      for il, ov in self.lvl_overrides.get(num_id, {}).items():
          levels[il] = {**base.get(il, DEFAULT_LEVEL), **ov}
      for il, s in starts.items():
          if il in levels:
              levels[il] = dict(levels[il], start=s)
      return levels
  ```
  意味: `w:lvlOverride/w:lvl` はその num だけ段の定義を置き換える（ECMA-376 17.9.8）。書かれていない子要素は abstractNum の段の値を使う（Word では確かめていない。既定値で置き換えると番号が知らせなしに消えるので、安全な方を選ぶ）。`w:startOverride` は開始番号で、上書きの `w:start` より優先する。
- `label()`: `levels = self._levels(num_id)`。`if ilvl not in levels: return ""`、`start = levels[ilvl]["start"]`。`%k` の置き換えは `n = cnt.get(k, levels[k]["start"])` と `levels[k]["fmt"]`（上位の段の上書きも反映する）。`overrides` の変数は使わなくなる。
- `is_bullet()`: `lv = self._levels(num_id).get(ilvl)`。
- 数え方（counters。num ごと）は変えない。R7・R8・R11 は範囲外で今の動きのまま。numStyleLink の先の num（番号付けスタイルが指す num）自身の lvlOverride は使わない（今と同じ）。
- ルート2: 自動番号の元の文字（numbers_original・PdfCheck.original）と照合の文字（`_para_seq`）は同じ Numbering から作り、補った docx は numbering.xml を変えない（pdfdocx は PARTS だけを書く）ので、読み直しても同じ番号になる。pdfmatch・pdfdocx・fidelity は変えない。

## テスト

既存のテストで期待が変わるものはない（試作をすべて当てて 1298 件が通った）。足すテスト:

### tests/test_sanitize.py（新規）

`tests/test_notebook.py` と同じく `importlib.util.spec_from_file_location("sanitize_docx", ROOT / "tools" / "sanitize_docx.py")` で読む。

- `test_sanitize_refuses_same_file`: `FULL` を tmp_path に写し、`sanitize(p, p)` が `ValueError`（match="同じファイル"）で、p のバイト列が変わらないこと。`os.symlink` で作った別名でも同じ（symlink が作れない環境では skip）。
- `test_sanitize_failure_keeps_existing_output`: dst に `b"old"` を書き、ZIP でない src で sanitize。例外が出て dst が `b"old"` のまま、tmp_path に一時の `*.docx` が残らないこと。
- `test_sanitize_removes_personal_info_and_keeps_text`: `mf.make_article` で、本文に `mf.deleted(...)`（作成者「試験」）と
  `<w:ins w:id="77" w:author="{AUTHOR}" w:date="2026-01-01T00:00:00Z"><w:r><w:t>補</w:t></w:r></w:ins>` を含む段落を作る。
  `test_reader._with_style_linked_numbering` と同じ形の ZIP の書き換えで、次を足す: document.xml にコメントの範囲・参照のラン、word/comments.xml と people.xml（rels と Content_Types の Override も）、
  docProps/custom.xml と docProps/thumbnail.jpeg（`_rels/.rels` の関係と Override も）、app.xml の `TitlesOfParts` の lpstr に架空の題目、
  ヘッダーに地の文と AUTHOR フィールド（`begin`・instrText ` AUTHOR `・`separate`・結果のラン「架空太郎」・`end`）、フッターに PAGE フィールド（結果のラン「1」）。sanitize の後に確かめる:
  - コメント・people・`customXml/`・custom.xml・thumbnail の部品がない。`commentRangeStart`・`commentReference` がない。
  - すべての `w:author` が「作成者」か `AUTHOR`。`pdfdocx.tracked_counts` が前後で同じ。
  - settings.xml に `attachedTemplate` がなく、どの rels にも attachedTemplate の関係がない。
  - ヘッダーに w:t がない（地の文と AUTHOR の結果が消える）。フッターには PAGE の結果のラン「1」だけが残る。
  - core の creator・lastModifiedBy・title、app の Company と TitlesOfParts の lpstr が空。
  - 残った rels の内部のターゲットと Override の PartName がすべて ZIP にある。word/*.xml の r 名前空間の属性（id・embed・link）の値が、すべてその部品の rels の Id にある。
  - `fidelity.source_texts` が同じ。convert（ルート1）の XML のバイト列が元の docx の変換と同じで `fidelity.ok`。
- `test_sanitize_keeps_text_of_all_fixtures`: `conftest.ALL_DOCS` と `FLOAT`・`PLACE`・`OUTSIDE`・`FLOAT_TEXT` で parametrize。前後で `source_texts` と `read_docx` の（src, plain, autonum）が同じ。
- `test_sanitize_warns_local_external_path`: 画像の関係を `TargetMode="External"`・Target `file:///C:/Users/someone/a.png` で足した docx で、標準エラー（capsys）に「外部のパスを含む関係」が出て、パスの文字（`someone`）は出ないこと。書き出しはされること。
- `test_sanitize_cli_same_file`: `subprocess.run([sys.executable, str(ROOT / "tools" / "sanitize_docx.py"), p, p])` で終了コード 1、標準エラーに文が出て、p が変わらない。
- `test_sanitize_cli_bad_input`: ZIP でない入力で終了コード 1、標準エラーに `Traceback` がない。

### tests/test_ai.py

- `test_parse_response_rejects_top_level_array`: parametrize で `json.dumps([op])`、`"```json\n" + json.dumps([op]) + "\n```"`、`json.dumps([op, op2], indent=2)` をコードブロックで囲んだもの、`json.dumps([op]) + "\n以上です。"`、
  `json.dumps([{"placements": [], "operations": [], "notes": []}])`。どれも `ValueError`（match="一覧（\\[ \\] で囲んだもの）"）。`"[]"` は match="JSON（{ で始まり } で終わる部分）が見つかりません"。
- `test_parse_response_requires_operations`: op の 12 項目の dict → match="操作 1 件だけ"、`{"placements": []}` と `{"notes": []}` → match="operations の一覧がありません"、`{"operations": {}}` → match="operations が一覧"。
  `tests/data/ai_response_sample_full.json`（placements なし）と `MANUAL_EXAMPLE` は今までどおり読めること。
- `test_manual_array_answer_is_ai_error`: `convert(FULL, 手動モード, ai_response=json.dumps([_set_role(...)]))`。`res.ai.error` に「一覧」、`actions(res)` の key に `ai_error`、`res.needs_action` が真、`res.fidelity.ok`。
- `test_deeply_nested_answer_does_not_abort`: `resp = '{"placements": [], "operations": [' + '[' * 100000 + ']' * 100000 + ']}'`。convert が例外を出さず、`res.ai.error` に「入れ子」、`ai_error` が出る。
  `parse_cut_response('{"placements": [{"float": "s1"}, ' + '[' * 100000)` と `parse_cut_response('{"placements": [' + '[' * 100000)` がどちらも例外を出さず `None`（深さ 100000 はどの版の Python でも RecursionError になる）。
- `test_cut_top_level_array_is_not_partial`: `'```json\n[{"placements": [{"float": "s1", …}], "operations": [{"op": "link_'` と、コードブロックのない同じ形で、`parse_cut_response` が `None`。
  手動の convert で `res.ai.error` に「一覧」、`res.ai.partial` が空。
- `test_split_ops_records_non_dict_ops`: operations が `["link_citation d18", [1]]` のとき、`split_ops` が `[]`、`outcome.rejected` が 2 件で理由に `str`・`list` がある。手動の convert でレポートの 2 章の不採用の表に 2 行出る。

### tests/test_refparse.py

- `test_same_author_year_ambiguity_uses_all_best_candidates`: `make_refs` で架空の 3 件（同じ第一著者・同じ年「2001」、題目は別）を 2 組作る。
  1 組目は「試験・架空」の共著・「試験・架空」の共著・「試験」の単著。「試験・架空（2001）」の引用が `(None, "ambiguous")` で、説明に B1、B2 があり B3 がない。
  2 組目は単著・共著・単著。共著の引用が `(B2, "exact")`、単著の引用が ambiguous で説明が B1、B3 だけ。
  候補が 2 つの組（共著・単著）では今と同じ結果。

### tests/test_reader.py

- `_with_lvl_override(src, dst)` を `_with_style_linked_numbering` の隣に足す。numbering.xml の `</w:numbering>` の前に、abstractNum 0 を指す次の num を足す
  （abstractNum 0 の段 0 が decimal・`%1.` であることを実装のときに確かめ、違えば期待を合わせる）:
  num 92（lvlOverride ilvl 0 の lvl: start 1・upperLetter・`(%1)`）、num 93（startOverride 5 と lvl: lowerRoman・`%1)`）、num 94（lvl のない lvlOverride。startOverride 3 だけ）、
  num 95（ilvl 0 の lvl: upperLetter・`%1.`、ilvl 1 の lvl: decimal・`%1-%2`）。
- `test_lvl_override_numbering_is_used`: num 92 の 2 項目、num 93・94 の各 1 項目、num 95 の ilvl 0 と ilvl 1（ilvl 1 の段落は numPr を XML で直接書く）の autonum が
  `["(A)", "(B)", "v)", "3.", "A.", "A-1"]`。convert で `fidelity.ok` かつ final_ok、XML に `<list` と `(A)` がある。
- `test_lvl_override_partial_children_inherit_abstract`（Numbering の単体。etree の文字列で numbering.xml を作る）: abstractNum の段 0 が decimal・`(%1)` のとき、
  `<w:lvl w:ilvl="0"><w:start w:val="4"/></w:lvl>` だけの上書きで `(4)`・`(5)`、`<w:numFmt w:val="upperLetter"/>` だけの上書きで `(A)`。
- `test_lvl_override_bullet_and_start_priority`（単体）: 上書きの lvl の numFmt が bullet なら `is_bullet` が真。startOverride 7 と上書きの `w:start` 2 があれば 7 から数える。
- 既存の `test_num_style_link_numbering_is_followed` は `(1)(2)` と循環の空のまま通ること。

### tests/test_pdfmatch.py

- `test_autonum_level_override_follows_pdf`: `bullet_article` と同じ形で、`list_item(num_id=92)` の 2 項目の docx を `_with_lvl_override` で作る（共通の部品は `tests/make_fixtures.py` に関数として置くか、test の中に同じ書き換えを書く。make_fixtures の既定の出力は変えない）。
  PDF の行が `(A)`・`(B)` のとき `compare` の `diffs == []`、`number_edits == {}`。`（Ａ）`・`（Ｂ）` のとき `number_edits == {("auto", src): "（Ａ）", …}` で `diffs == []`、
  `convert_with_pages` のルート2 で `actions(res) == []`、`res.supplement.ok`、XML に `（Ａ）` がある。

## 回帰の確かめ（基準との比較で想定する違い）

- (1a) の commit: tests/fixtures の docx 15 件のバイト列が変わる。変換の XML は fixture 15 件とも変わらない（試作で確かめた）。`sample_pdfcheck.pdf` は戻すので変わらない。
  この commit の直後に、0.29.0 のコード（(1a) の後のもの）で回帰の基準を取る。対象は fixture 15 件と tests/private の 10 件（ルート1。PDF のある 6 件はルート2 も。AI は manual・回答なし、`convert_metafiles=False`）。
  取るもの: XML のバイト列のハッシュ、actions の key と level、除外の理由ごとの件数、warnings の件数、ZIP の一覧と画像のハッシュ、終了コード。保存先は scratchpad で、原稿の本文は保存しない。
- (1b)(1c)(1d) の commit: 基準と比べて違いは 0（fixture 15 件・実際の原稿 10 件とも）。AI の回答なしの基準なので (1b) は出力に出ない。K10 は 750 件で違い 0、R6 は該当 0。
- 違いが出たら、この単位の想定の外なので原因を調べてから進む。

## ほかの単位・ルート2・AI 補完・画面との関係

- 順（単位どうしの点検の決定）: 0.30.0 の最初の commit は (1a) だけ。(1b)(1c)(1d) は u2 と並行してよい（触るファイルが重ならない）。ai_assist.py は u1 → u4（`image_blocks`）→ u5（`build_request`）の順に直す。関数は重ならない。
- `tests/make_fixtures.py` は u1 では作り直すだけ（部品は変えない）。u3-tables と u4 は make_fixtures の部品を直すが、既定の出力を変えず、fixture を作り直さない。
- 0.31.0 の単位（u5・u6）のテストの AI の回答は、必ず `{"placements": […], "operations": […], "notes": []}` の形で書く（操作がなくても `"operations": []`）。u1 の後は `operations` のない回答が `ai_error` になるため。
- u3-autonum との関係: u3-autonum の守り（`lost_autonums`）は「autonum が空でないのに XML に番号がない段落」を探すので、numbering.py が `''` を返す誤りは見つけられない。そのため (1d) は値を重ねる案で実装し、番号を空にしない。u3-autonum が DESIGN.md 7 章にその限界を書く。
- ルート2: R6 の直しで、上書きされた番号が PDF と同じ文字になり、偽の違いと要確認 pdf_unfixed がなくなる。全角・半角の違いは今までどおり `plan.pdf_numbers`（number_edits）で PDF に合わせ、補完の確かめも合格する。
- AI 補完: (1b) の文は `outcome.error` に入り、既存の Action `ai_error`（要対応）として、冒頭・2 章・14 章・Colab の枠・コマンドライン（終了コード 1）に出る。1 画面版は `app.AppState.REPASTE_KEYS` に `ai_error` があるので回答の欄が出る。
  A10 の深い回答は、変換の中止（トレースバック）ではなく、AI 補完なしの出力と要対応になる。`{ }` でない操作は 2 章の不採用の表に出る（Action は足さない）。
- AI の依頼文: K10 で「特定できない」になった引用は `linker.unresolved` に入り、今までどおり依頼文の未解決の引用に載る。特定できるようになった引用は依頼文から消える。
- report.actions: Action の key は足さない・変えない。report.py・app.py・colab.py・cli.py・pipeline.py は変えない。sanitize はレポートと関係のない開発用のツール。

## 利用者向けの文

- 新しい Action・目印（`report.step()`）は足さない。文に XML のタグはないので `md_tag` は要らない。
- (1b) の文（`TOP_ARRAY_MSG`・`SINGLE_OP_MSG`・`NO_OPS_MSG`・`OPS_NOT_LIST_MSG`・`DEEP_MSG`。文は「直し方」の (1b) のとおり）は、要対応 `ai_error` の本文に入る。
  手動モードでは pipeline の前置き「貼り付けられた回答を JSON として読めませんでした: 」、API モードでは「AI の回答を JSON として読めませんでした: 」の後ろに続く。頼み方は「チャットで使っているときは、…」で、API モードでも食い違わない。
- `{ }` でない操作の不採用の理由: 「操作が { } のまとまりでない（str）ので、この操作は使わなかった」。
- (1a) のコマンドライン（開発用）: `SAME_FILE_MSG`・`CHANGED_MSG`・外部パスの警告（「直し方」の (1a)）。終了コードは 0（成功）・1（断った・読めない）・2（使い方の誤り）。
- (1c)(1d) は文を変えない（K10 の「特定できない」の説明に挙がる候補が、最大の当てはまりの候補だけになる）。
- `docs/USAGE_AI.md` 7 章の「うまくいかないとき」に 1 行足す:
  「- 回答の全体が一覧（[ ] で囲んだもの）になっている、operations の一覧がない（操作がないときも "operations": [] と書きます）、入れ子が深すぎる回答は読み込みません。チャットで「回答の書き方の見本の形で、```json のコードブロック 1 つで出し直してください」と頼んでください。」

## 文書の更新（CLAUDE.md は案だけ）

0.30.0 の最後に、文書をまとめて直す人が直す（単位ごとに直さない）。

- `docs/DESIGN.md` 4.1（141 行目の近く）: 自動番号に「num の `w:lvlOverride/w:lvl` は、その num だけ段の定義（numFmt・lvlText・start）を置き換える（書かれていない子要素は abstractNum の段の値）。`w:startOverride` は開始番号で、lvl の start より優先する（`numbering.Numbering._levels`）」を足す。
- `docs/DESIGN.md` 7 章（1136〜1138 行目）: 自動番号の限界から「段の書式の上書き（`w:lvlOverride/w:lvl`）」と R6 を除き、R7・R8・R11 だけにする。「上書きの lvl に書かれていない子要素は abstractNum の段の値を使う（Word では確かめていない）。numStyleLink の先の num 自身の lvlOverride は使わない」を足す。
- `docs/DESIGN.md` 733〜737 行目（AI の回答の読み取り）: 最上位が一覧の回答、操作 1 件だけ・operations のない回答、深すぎる入れ子は読めない回答とし、それぞれ専用の文を出すこと。operations は必須で、placements・notes は省略できること。途中で切れた回答でも、最上位が一覧のもの・深すぎるものは読まないこと。`{ }` でない操作は不採用として記録すること。
- `docs/ARCHITECTURE.md` 145 行目（numbering.py。「`w:lvlOverride` の `w:lvl`（段の定義の上書き）と `w:startOverride`」に直し、行数の欄を `wc -l` に合わせる）、167 行目（ai_assist.py の ③ に「最上位の一覧と operations のない回答は読まない」）、208 行目（sanitize: 取り除くもの・空にするもの・確かめ方）。
- `docs/DEVELOPMENT.md` 419〜420 行目: テンプレートを新しい sanitize で取り除き直したこと、sanitize が取り除くもの（コメント・変更履歴の作成者の名前・ヘッダー/フッターの文字〈ページ番号は残す〉・customXml・テンプレートのパス・文書のプロパティ）を書く。
  作り直しの手順（別名に sanitize して置き換える → `python tests/make_fixtures.py` → `git diff --stat tests/fixtures` → `git checkout tests/fixtures/sample_pdfcheck.pdf`）を書く。「テスト」の節に `tests/test_sanitize.py` を足す。572 行目の「S3 32 件…は未対応」の件数を、0.30.0 で直したもの（O5・A9・A10・K10・R6 ほか）に合わせる。
- `docs/USAGE_AI.md` 7 章: 上の 1 行。
- `docs/REVIEW_2026-11.md`「対応の記録」: O5・A9・A10・K10・R6 を 0.30.0 で直したことと直し方の表。A9 の複数要素の一覧は Extra data の誤りになり、最初の要素だけを読むことはなかったこと。新しい未修正の項目（下の「新しく見つけた問題」の記録するもの）。
- `tools/sanitize_docx.py` のモジュールの docstring（この単位の実装者が書く）。
- CLAUDE.md: この単位では直す案はない（「新しい docx をリポジトリに加えるときは `tools/sanitize_docx.py` を通す」は今のままで正しい）。

## 文書とコードの食い違い

- `docs/ARCHITECTURE.md` 145 行目は numbering.py が「`w:lvlOverride`・`w:startOverride`」を扱うと書くが、コードは lvlOverride の中の startOverride しか読まない（R6）。直した後に書き直す。
- `docs/DEVELOPMENT.md` 419 行目はテンプレートを「コメントと作成者情報を取り除いたもの」、`docs/ARCHITECTURE.md` 208 行目は sanitize を「コメント・作成者情報を取り除く」と書くが、テンプレートと fixture 14 件の settings.xml.rels にユーザー名を含むローカルのパスが残っている。直す（テンプレートを作り直す）。
- `tools/sanitize_docx.py` の docstring は app.xml の Company を空にすることを書いていない。作り直しで docstring も書き直す。
- CLAUDE.md・DEVELOPMENT.md は「新しい docx をリポジトリに加えるときは sanitize を通す」とするが、ツールは変更履歴の作成者・ヘッダー/フッター・customXml・テンプレートのパスを取り除かない（O5）。この単位で直す。
- `ai_assist.parse_response` の docstring と DESIGN.md 733 行目の「最初の { から最後の } までを読む」の結果として、最上位が一覧の回答は最初の要素を回答として読むが、どちらにも書かれていない（A9）。直した後に書き足す。
- `docs/REVIEW_2026-11.md` 181 行目（A10）の「ai_assist.py 1033」は、0.29.0 では `cut_at_end` の docstring の行で、捕まらない `json.loads` は `parse_cut_response` の 1059 行目。記録のときに行番号を直す。
- pipeline の前置き「…を JSON として読めませんでした: 」は、JSON としては読めたが形が違う回答（operations がない・placements が一覧でない）にも付き、意味が少し合わない。直さない（REVIEW に記録）。
- 今の「回答の中に JSON（{ で始まり } で終わる部分）が見つかりません。AI に「回答の書き方」に従って…頼んでください」（parse_response 932〜933 行目）は、API モードでは取れない操作を頼む。この単位の新しい文は手動のときだけの指示と分かる形にしたが、この既存の文は変えない（REVIEW に記録）。
- 計画の依頼の「複数要素の配列も最初の要素だけ読む可能性がある」は誤りで、実際は Extra data の誤りになる（REVIEW の A9 の本文にはこの主張はない）。
- 計画の依頼の「tests/private に実際の原稿 13 件」は、docx がテストデータ1〜5 の 9 件とテンプレートの 1 件の計 10 件（ほかに前回の点検の再現用の review-repros がある）。
- （未確認）ECMA-376 では `w:start` を省略したときの開始番号は 0 という理解だが、numbering.py は 1 を既定値にしている。この単位では変えない（R11 と一緒に確かめる）。

## 新しく見つけた問題（この単位で直すもの／直さず REVIEW に記録するもの）

この単位で直すもの:

- `split_ops` が `{ }` でない操作（文字列・一覧など）を `outcome.rejected` にも記録せずに捨てる（A9 と同じ「知らせなしに操作 0 件」の型）。
- 最上位が一覧の回答が途中で切れると、`parse_cut_response` が中の placements を読む。
- sanitize が footnotes.xml・endnotes.xml の中のコメントの範囲を残す（今の実装は document.xml だけを正規表現で見る）。
- sanitize が app.xml の `TitlesOfParts`（題目が入る）と `docProps/thumbnail.*` を残す。

直さず REVIEW に記録するもの:

- attachedTemplate 以外の外部の関係（リンクした画像・OLE、`file:` のハイパーリンク、差し込み印刷のデータ元など）のローカルのパスは、取り除くと本文の参照が切れるので消さず、警告だけを出す（今の原稿・fixture には 0 件）。
- pipeline の前置きの文の意味のずれ（上の食い違い）と、既存の「JSON が見つかりません」の文が API モードで取れない操作を頼むこと。
- `w:start` の既定値（0 か 1）が ECMA と合っているか（R11 と一緒に確かめる）。
- numStyleLink の先の num 自身の lvlOverride を使わないこと（Word の動きは未確認。0 件）。
- 最上位の一覧の判定は、コードブロックのない回答で最初の `{` の直前に `[` がある地の文を一覧と誤る（ほとんどない形）。

## 未決のこと（利用者の返事待ち／実装のときに確かめること）

利用者の返事待ち:

- git の履歴に残ったテンプレートのローカルのパスを、履歴を書き換えて消すか（main の書き換えは Colab の取得先とほかの人のクローンに影響する）。それとも今後の版からなくなればよいか。書き換えを選んだ場合も、その作業は版の反映と別にする。
- 前回の点検の再現スクリプト（tests/private/review-repros/reproduce.py）の項目のうち、この単位で正式なテストに移したもの（ai-array・sanitize-same-path・reference）を、利用者が reproduce.py から消す形でよいか。tests/private は利用者のフォルダなので、実装者は直さない。移した項目は最後の報告で一覧にする。

実装のときに確かめること:

- テストで使う abstractNum 0 の段 0 が decimal・`%1.` か（make_article のテンプレートの numbering.xml）。
- sanitize した docx（テンプレート・sample_full）が Word で開けるか。計画では LibreOffice でしか確かめていない。開けなければ lxml の書き出しの形（XML 宣言・standalone）を元の形に合わせる。
- 子要素の足りない lvlOverride/lvl の Word の表示（重ねる案が合っているか）。確かめられなければ DESIGN.md 7 章の「Word では確かめていない」のまま。
- Python 3.10 で `tests/test_syntax.py` が通ること（f 文字列の式の中にバックスラッシュ・外側と同じ引用符を書かない）。新しいテストの深さ 100000 で 3.10 でも RecursionError になること（GitHub Actions で確かめる）。

## 点検の指摘の反映表

| 重さ | 題 | 反映した節 |
|---|---|---|
| major | (1b) A10 のテストが設計と矛盾する（parse_cut_response の深い入れ子） | 直し方 (1b) の parse_cut_response の 2〜4、テストの `test_deeply_nested_answer_does_not_abort`（両方とも `None`） |
| major | (1b) 最上位が一覧の回答が途中で切れると、parse_cut_response が一覧の中の placements を読む | 直し方 (1b) の parse_cut_response の 1、テストの `test_cut_top_level_array_is_not_partial` |
| major | (1d) 子要素の足りない lvlOverride/lvl で自動番号が黙って消える | 直し方 (1d) の `_level_present`・`_levels`、テストの `test_lvl_override_partial_children_inherit_abstract`、文書の更新（DESIGN.md 7 章） |
| major | (1a) app.xml の TitlesOfParts に題目が残る | 直し方 (1a) の clean_part の app.xml、テストの `test_sanitize_removes_personal_info_and_keeps_text` |
| minor | (1a) ヘッダー/フッターを丸ごと空にするとページ番号のフィールドも消える | 直し方 (1a) の clean_part の 3（ページ番号のフィールドの結果は残す）、テスト（ヘッダーの AUTHOR・フッターの PAGE） |
| minor | split_ops が dict でない操作を黙って捨てる件は、この単位に入れる | 直し方 (1b) の split_ops、テストの `test_split_ops_records_non_dict_ops` |
| minor | (1b) _top_level_array の i<0 の枝が、[ で始まる地の文を「一覧」と誤る | 直し方 (1b) の `_top_level_array`（枝を削った）、テストの `"[]"` の期待 |
| minor | (1b) 新しい文の「AI に…と頼んでください」が、API モードでは取れない操作になる | 直し方 (1b) の定数（`ASK_AGAIN` を「チャットで使っているときは、…」にした）、利用者向けの文 |
| minor | (1a) sanitize の main が ValueError しか捕まえない | 直し方 (1a) のコマンドライン、テストの `test_sanitize_cli_bad_input`・`sys.executable` |
| minor | (1a) attachedTemplate 以外の外部ターゲットにあるローカルのパスを見つけられない | 直し方 (1a) の sanitize の 4（警告だけ）、テストの `test_sanitize_warns_local_external_path`、新しく見つけた問題（REVIEW に記録） |
| minor | (1a) テストの抜け: thumbnail と、切れた r:id | テストの `test_sanitize_removes_personal_info_and_keeps_text`（thumbnail・r 名前空間の属性） |
