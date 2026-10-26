# 単位 E（0.24.0）の設計: 注（Word の文末脚注）と資料の見出し（N6・D4・D3）

- 作成: 2026-10-26（設計の担当）。対象: main の e2dbf73（0.23.1）。コードは変えていない（試作は `scratchpad/e/design/` の写しだけ）。
- 正本: `docs/FIX_PLAN.md` の E の節・項目の表の N6・D4・D3・決定事項 7・8・付録の D3・D4。FIX_PLAN の行番号は古いので、名前で書く。
- 試作: `scratchpad/e/design/src`（0.23.1 の写しに `patch.py`・`patch2.py` を当てたもの。D4・N6・D3 の主な部分だけ。
  この設計書の 2.3 の英文題目の規則、FnNode.linked・custom_mark、8 章の表、Action、番号の後ろの ASCII ハイフンの扱いは入っていない）。
  試作で確かめたもの: `gen_e.py`（架空の docx を作る）・`run_e.py`・`run_ai.py`・`run_r2.py`・`run_r2b.py`・`img_en.py`・`re_app.py`（正規表現の最終案と一覧）。
  実装は試作の写しではなく、この設計書から作る。

## 0. 要点

| 項目 | 決めたこと |
|---|---|
| 注の鍵 | `model.note_key(fn_kind, fn_id)` → `"footnote:5"` / `"endnote:5"`（`-custom` は除く）。`model.note_label(key)` → 「Word の脚注 5」「Word の文末脚注 5」 |
| 注の番号 | Word の脚注・文末脚注をまとめて、`doc.all_paragraphs()` の順（document.xml の段落の順。除外した段落もその位置で数える）で最初に参照された順、続けて集めた注の中の参照の順の通し番号。形式は `fn_mark`（「1)」）。決定事項 7 |
| 参照のない注 | 段落を除外（理由「Word の文末脚注 5（本文から参照されていない注）」、参照が変更履歴で削除されたものは別の理由）。空白だけの段落は `exclude_blank` |
| A の暫定の知らせ | `ENDNOTE_EXCLUDED` と `PROVISIONAL["endnote"]` を消す（テキストボックスの暫定の知らせは F まで残す） |
| 資料の見出し | `RE_APPENDIX` を広げる（3.1 の表）。英文要旨の後ろの章・節・項見出しのスタイルの段落から資料を始め、Decision を記録（決定事項 8(a)） |
| 英文要旨の中の和文 | かな・漢字が 3 割以上の段落は、Decision（applied=False）・10 章の警告・要確認の Action（自動では移さない） |
| 引用文献の後ろの資料 | 暫定: 資料にせず、10 章の警告と要確認の Action だけ（決定事項 8(b) は利用者に未確認） |
| customMarkFollows の文末脚注 | 暫定: 脚注と同じ（番号を 1 つ使い、本文の印は docx の文字のまま）。範囲外と文書に明記し、Decision で知らせる |
| N6 | `ai_assist.set_role_problem(p, plan, role)`（理由の文字列か ''）。`role_overrides` と依頼文の除外の一覧の案内の両方で使う |
| 版 | 0.24.0（XML に注が増え、資料の領域が変わる） |

td1〜3 には Word の脚注・文末脚注がなく（脚注 0・文末脚注 0・参照 0）、英文要旨の後ろの見出しスタイルの段落・引用文献の後ろの資料らしい段落・
英文要旨の和文の段落もない。td3 の資料 1 件は 0.23.1 の正規表現でも新しい正規表現でも同じに認識される。試作では td1〜3 の XML とレポートは
0.23.1 と同じで、AI 依頼文だけが変わった（役割の一覧に app_heading、冒頭の除外 3 段落の案内。N6 の意図した変化）。

## 1. D4: Word の文末脚注を注として出す

### 1.1 鍵と表記（model.py）

```python
NOTE_KINDS_JA = {"footnote": "脚注", "endnote": "文末脚注"}

def note_key(fn_kind: str, fn_id: str) -> str:
    """Word の脚注・文末脚注の鍵（"footnote:5" / "endnote:5"）。脚注と文末脚注は ID が重なりうるので、種類と ID の組で区別する。
    記号を自分で付けた参照（fn_kind が "footnote-custom" など）も、同じ注を指す鍵にする。"""
    kind = fn_kind[:-len("-custom")] if fn_kind.endswith("-custom") else fn_kind
    return f"{kind}:{fn_id}"

def note_label(key: str) -> str:
    """note_key の人が読める表記（「Word の脚注 5」「Word の文末脚注 5」）。"""
```

- `note_label` も `-custom` を除いて判定する（鍵に `-custom` が残っていても同じ表記）。
- `Atom` の docstring の `fnref` を「Word の脚注・文末脚注の参照（fn_kind: footnote / endnote。記号を自分で付けたものは末尾に -custom。fn_id。
  注の鍵は note_key）」に直す。
- `Document` に `deleted_note_refs: set`（変更履歴で削除された参照の note_key）を足す。docx_reader が記録する（1.3）。

### 1.2 参照の順と番号（決定事項 7）

FIX_PLAN の文面「まず、本文の参照を note_key で参照順に集める。続けて、集めた注の段落の中の参照も順に足す。除外された段落の中の参照も参照として
数え、注を出力する」を、次のように決めた。

1. **本文の参照**: `doc.all_paragraphs()`（document.xml の段落。本文・表のセル・テキストボックス・冒頭・英文の部分・除外した段落を、docx の順に）の
   `fnref` を順に見て、注の鍵の一覧 `order` に、初めて出た鍵を足す。**除外した段落の参照も、その位置で数える**（領域の順〈本文 → 注の中 →
   除外した段落〉にはしない）。理由: Word 自身の脚注番号の数え方（文書の中の参照の順）と同じで、0.23.1 の脚注だけの原稿の番号が変わらない。
   出版版 PDF の番号も、組版で文書の順に付けられる。
2. **注の中の参照**: `order` の先頭から順に、その注の段落の参照を見て、まだない鍵を末尾に足す（足した注の中も続けて見る。幅優先）。
   脚注の中から文末脚注を参照する形で、その文末脚注が除外されないようにするため。参照されていない注の中の参照は数えない（その注は出力しないので）。
3. 参照先の注が docx にない・段落が 0 の参照は、今までどおり注にしない（`notes.get(k)` が空なら飛ばす。本文の参照は何も出力されない。docx の文字ではない）。
4. `order` の順に `FnNode(word_note=True)` を `plan.fns` の後ろに足す。番号は今までどおり `builder.word_note_marks`（Word の注の中での順。`fn.number or k`）
   が付けるので、`attach_word_notes` では `number` を設定しない（0.23.1 と同じ）。

**削除の変更履歴の中の参照**は、参照として数えない（docx_reader は今も w:del・w:moveFrom の中の参照をアトムにしない。文字ポリシーの
「削除された変更履歴は含めない」と、Word で変更をすべて承諾した表示に合わせる）。その注は「参照されていない注」として除外し、理由で
削除の変更履歴だと分かるようにする（1.4）。computed task の「削除の変更履歴の中の参照（番号は付け、リンクのない注にする）」とは扱いが違う。
番号を付けて出力すると、Word で承諾した原稿にはない注が XML に出るので、こちらを採った（却下した案として 7 章に記録）。

**除外した段落の中の参照**（冒頭の装飾・英文の部分の題目以外の段落・テキストボックスの文字など）は数え、注は出力する。参照のある段落が
すべて除外した段落なら、その注は本文からリンクのない注になるので、Decision（category "note"）を記録し、8 章の表に「リンクなし」と出す。
判定に使う除外は、`attach_word_notes` の時点の `plan.exclusions`（AI の exclude を含む）。builder の段階の除外（図の画像の段落の空白）は
文字のない段落なので関係しない。

題目・著者名・所属・引用文献の段落の参照（emit の `xref=False` の文脈）は、今までどおり上付きの番号だけでリンクにならない。これは 0.23.1 の
脚注と同じで、E では知らせを足さない（7 章の限界）。

### 1.3 docx_reader.py

- `_run` の `footnoteReference` / `endnoteReference`: 削除の中（`deleted` で、フィールドコードの中でない）なら、
  `self.deleted_note_refs.add(note_key(kind, id))` してから今までどおり飛ばす。`read()` の最初で `self.deleted_note_refs = set()`、
  `Document(..., deleted_note_refs=self.deleted_note_refs)`。注の中の削除された参照も同じ集合に入る（read_notes も `_run` を通る）。
- 文字の読み方は変えない。文末脚注は、`read_notes("word/endnotes.xml", "endnote", "e")`・`ooxml.canonical_text`（fidelity は endnotes.xml を読む）・
  `pdfdocx.paragraph_units`（`endnoteReference`・`endnoteRef` を脚注と同じに扱う）で、すでに同じ文字ポリシーで読んでいる
  （A の `tests/test_reader.py` が本文・脚注・文末脚注のすべての w:p を比べている）。customMarkFollows の参照の後ろの印は、どれも w:t の文字として読む。

### 1.4 structure.py

**定数**: `ENDNOTE_EXCLUDED` を消す。`TEXTBOX_TEXT_EXCLUDED` の上のコメントを「文字だけのテキストボックスの段落を除外したときの理由。
レポートは、この理由の除外の件数を…（文字だけのテキストボックスを XML に出力できるようになるまでの暫定の知らせ）」に直す。
参照のない注の理由の文言（関数にする）:

```python
def unreferenced_note_reason(key: str, deleted: bool) -> str:
    """本文から参照されていない Word の脚注・文末脚注を除外したときの理由（レポートの 6 章）。"""
    if deleted:
        return f"{note_label(key)}（本文の参照が変更履歴で削除された注。Word で変更をすべて承諾すると消える）"
    return f"{note_label(key)}（本文から参照されていない注）"
```

**FnNode**: `word_kind: str = ""`（footnote / endnote）、`word_id: str = ""`（note_key。コメントを直す）、
`word_refs: list`（参照のある段落の ID。docx の順・重複なし）、`linked: bool = True`（参照のある段落の少なくとも 1 つを出力するか）、
`custom_mark: bool = False`（参照のどれかが記号を自分で付けたもの）を足す。

**ArticlePlan**: 次を足す。
- `note_of: dict`（Word の脚注・文末脚注の段落 ID → note_key。参照の有無にかかわらず、すべての注の段落）
- `warnings: list`（構造の組み立ての警告。pipeline が 10 章の警告に加える）
- `abstract_ja: list`（英文要旨の中の、かな・漢字が 3 割以上の段落 ID。2.3）
- `app_after_refs: list`（引用文献などの後ろの、資料の見出しと思われる段落 ID。2.4）

**Classifier.run**: 注の段落を `plan.paras` に入れるところで、`plan.note_of[p.src] = note_key(kind, nid)` も入れる
（`for kind, notes in (("footnote", self.doc.footnotes), ("endnote", self.doc.endnotes))`）。

**attach_word_notes（書き直す）**:

```python
def attach_word_notes(self):
    """Word の脚注・文末脚注を、本文で最初に参照される順の通し番号で、注のリストの後ろに加える（決定事項 7）。

    参照の順は doc.all_paragraphs() の順（出力しなかった段落の参照も、その位置で数える）。続けて、集めた注の中の参照を順に足す。
    参照されていない注の段落は、理由を付けて除外する（空白だけの段落は exclude_blank）。"""
    notes = {note_key(kind, nid): paras for kind, d in (("footnote", ...), ("endnote", ...)) for nid, paras in d.items()}
    order, where, custom = [], {}, set()
    def collect(paras): ...       # fnref ごとに k = note_key(...)。notes.get(k) が空なら飛ばす。where[k] に p.src を（重複なしで）足す。
                                   # a.fn_kind が "-custom" で終われば custom に k。k が order になければ足す
    collect(self.doc.all_paragraphs()); i = 0
    while i < len(order): collect(notes[order[i]]); i += 1
    excluded = {e.src for e in plan.exclusions}
    for n, k in enumerate(order, 1):
        paras = notes[k]
        node = FnNode(paras=paras, word_note=True, word_kind=k.split(":")[0], word_id=k, word_refs=where[k],
                      linked=not all(s in excluded for s in where[k]), custom_mark=k in custom)
        for j, p in enumerate(paras, 1):
            plan.region[p.src] = "fn"
            plan.locations[p.src] = f"{note_label(k)}（注 {n}）" + (f" 第{j}段落" if len(paras) > 1 else "")
        plan.fns.append(node)
        (Decision: linked が False のとき・custom_mark のとき。下の文言)
    for k, paras in notes.items():           # 参照されていない注
        if k in where: continue
        why = unreferenced_note_reason(k, k in self.doc.deleted_note_refs)
        for p in paras:
            plan.locations[p.src] = note_label(k)
            if p.is_blank: plan.exclude_blank(p)        # 空白だけ（文字がまったくなければ記録しない）
            elif p.plain(): plan.exclude(p, why)
    (まとめの Decision。下の文言)
```

- 最後の「未対応」の除外のループ（A の文末脚注の空白段落の処理と ENDNOTE_EXCLUDED）は消す。空白の扱い（`is_blank` なら `exclude_blank`）は
  参照されていない注の処理に引き継ぐ。参照された注の空白だけの段落は、脚注と同じく注の中に出力する（0.23.1 の脚注と同じ。空白は span で書く）。
- 注の最初の段落の `gen` アトム（Word の番号）だけの段落は `is_blank` が False で `plain()` が OBJ なので、`exclude(p, why)`（文字は空で記録）。
  画像だけの段落も同じ（画像は `pipeline.lost_images` が要対応として知らせる。場所は `plan.locations` の「Word の文末脚注 4」）。
- `plan.locations` の文言: 参照された注は「Word の文末脚注 5（注 2）」（2 段落以上なら「… 第1段落」）、参照されていない注は「Word の文末脚注 5」。
  0.23.1 の「Word の脚注 1件中」（全件数を書いていた）は直す（golden の sample_edge のレポート 4 章と AI 依頼文が変わる。意図した変化）。

**Decision の文言**（category はどれも "note"。src は注の最初の段落）:
- まとめ（Word の注が 1 件以上）: 文末脚注がなければ **今の文言のまま**
  「Word の脚注機能で書かれた注 {n} 件を、注の一覧にした（テンプレートの規定は、本文に上付きの「1)」を書き、注は「注」の節にまとめる）。
  本文と注の一覧の番号、注の見出しは補った（8 章）」（tests/test_notes.py が確かめている）。文末脚注があれば
  「Word の脚注・文末脚注機能で書かれた注 {n} 件（脚注 {a} 件・文末脚注 {b} 件）を、本文で最初に参照される順の通し番号で注の一覧にした
  （テンプレートの規定は、本文に上付きの「1)」を書き、注は「注」の節にまとめる）。本文と注の一覧の番号、注の見出しは補った（8 章）」。
- リンクのない注: 「{label}（注 {n}）は、本文の参照が XML に出力しなかった段落（{src の一覧}）の中にだけあるので、本文からのリンクのない注として
  出力した（8 章）。注が本文に必要なら、Word で参照を本文の段落に移して変換し直す」。
- 記号を自分で付けた注（暫定。2 種類とも）: 「{label}（注 {n}）は、本文の記号を自分で付けた注（Word の『記号』）。本文の記号は docx の文字のまま、
  注の一覧の番号は「{fn_mark の番号}」にした（本文と注の一覧で記号が違う。PDF と照らして確認すること）」。番号の文字は `journal.fn_mark.format(n=n)`。
  0.23.1 の脚注の customMarkFollows も同じ扱いだったが知らせがなかったので、ここで足す（既存の fixture に customMarkFollows はないので golden は変わらない）。

### 1.5 番号と鍵をそろえる箇所

| 場所 | 変更 |
|---|---|
| `builder.Builder.__init__`・`fn`・`word_note_marks` | 変えない（`fn.word_id` がそのまま note_key になる）。`word_note_marks` の docstring の「Word の脚注 ID」を「注の鍵（note_key）」に。`fn_numbers` の鍵も note_key |
| `emit.Emitter.write_object` | `self.fn_numbers.get(note_key(a.fn_kind, a.fn_id), (None, None))`。`Emitter.__init__` のコメントを「注の鍵（model.note_key）-> (fid, 番号)」に。今は ID だけを見るので、脚注 5 と文末脚注 5 が同じ fn1 になる（D4 の後半） |
| `linker` | 変えない（`fn_ids` は Word の注を除く。Word の注のリンクは emit が付ける）。`body_paragraphs` は `plan.fns` の段落を "fn" で返すので、文末脚注も照合・リンクの対象になる |
| `pdfmatch._para_seq` | `a.kind == "fnref" and a.fn_kind in ("footnote", "endnote") and note_key(a.fn_kind, a.fn_id) in fn_marks` なら `number("fnref", note_key(...), ...)`。`-custom` は今までどおり番号を入れない（SKIP）。`from .model import OBJ, note_key`。`_para_seq`・`compare`・`PdfCheck.numbers` の docstring・コメントの「Word の脚注 ID」を「注の鍵（note_key）」に。`list_marks` は `fn.word_id` のままでよい |
| `pdfdocx` | `PARTS` に `"word/endnotes.xml": "e"`（書き込み・`tracked_counts`）。`_all_paragraphs` に `doc.endnotes` を足す（読み直しの確かめ `_verify` の文字）。`raw_paragraph_ids`・`paragraph_units` は変えない（文末脚注をすでに同じ規則で読む。試作で、文末脚注の段落の全角・半角と空白の直しを endnotes.xml に書き込み、読み直しが合うことを確かめた） |
| `report` | `number_rows` の `f"Word の脚注 {ident}"` → `note_label(ident)`。`word_note_refs` を note_key で数える（1.6）。8 章・1 章（1.6）。`from .model import note_key, note_label` |
| `ai_assist` | `build_request` の注の一覧の `where = note_label(fn.word_id) if fn.word_note else …`。`para_view` の `fnref` は、文末脚注なら「⟦Word の文末脚注参照⟧」、脚注は今のまま「⟦Word の脚注参照⟧」 |
| `pipeline` | `warnings = list(dict.fromkeys(doc.warnings + plan.warnings + info.warnings))`。`NOTE_PARTS` は残す（場所がないときの予備） |

`ai_assist._placement_problem` は変えない（Word の注の段落は領域 "fn" なので、AI がその後ろを指定した図表は今までどおり本文の最後に仮に置く。
参照のない注の段落は領域がないので、ふつうの不採用）。

### 1.6 report.py の 1 章・8 章・13 章と、A の暫定の知らせを外す

- **暫定の知らせ**: `provisional_exclusions` のループを `(("textbox", TEXTBOX_TEXT_EXCLUDED),)` だけにし、`PROVISIONAL` から "endnote" を消す。
  docstring の「と Word の文末脚注の段落」を消す。`actions()`・`render` の `PROVISIONAL` の使い方はそのまま（"textbox" だけが残る）。
  テキストボックスの暫定の知らせは F で外す。
- **1 章**（`word_note_refs`）: `ids = {fn.word_id for fn in plan.fns if fn.word_note}`、参照は `note_key(a.fn_kind, a.fn_id) in ids` で数える。
  docstring のとおり「注へのリンクとして出力されるもの」にするため、`plan.exclusions` の段落の参照は数えない（0.23.1 は数えていた。
  除外した段落に参照のある原稿は既存の fixture・td1〜3 にない）。表記: 文末脚注があれば「注 {n}（うち Word の脚注・文末脚注 {wn}）」、
  なければ今のまま「（うち Word の脚注 {wn}）」。
- **8 章**: 冒頭の説明の「（Word の脚注機能で書かれた注の番号だけは、Word の表示「1」ではなく本誌の形式（設定 fn_mark）にしています）」を、
  文末脚注があるときだけ「（Word の脚注・文末脚注機能で書かれた注の番号だけは、Word の表示〈脚注は「1」、文末脚注は「i」など〉ではなく、本文で
  最初に参照される順の通し番号を本誌の形式〈設定 fn_mark〉で付けています。対応は下の表）」にする。文末脚注・リンクのない注・記号を自分で
  付けた注のどれかがあるときだけ、次の表を足す（脚注だけで、どれもなければ今のまま。golden の sample_edge は変わらない）。

  ```
  Word の脚注・文末脚注と、XML の注の対応:
  | XML の注 | Word の注 | 番号 | 本文からのリンク |
  | fn2 | Word の文末脚注 5 | 2) | あり |
  | fn3 | Word の文末脚注 7 | 3) | あり（本文の記号は docx の文字のまま） |
  | fn5 | Word の文末脚注 9 | 5) | なし（参照は XML に出力しなかった段落 d21 の中だけ） |
  ```
  番号は `plan.pdf_numbers.get(("fnlist", fn.word_id)) or r.journal.fn_mark.format(n=fn.number)`（`fn.number` は builder が設定する）。
- **13 章**: `number_rows` の場所の欄が note_label になる（「| 本文の脚注番号 | Word の文末脚注 5 | 「2)」→「2）」 |」）。13 章のほかの表の場所は
  `plan.locations`（1.4 の文言）。

## 2. D3: 資料の見出し

### 2.1 RE_APPENDIX（structure.py）

```python
_APP_OPEN = "【［\\[〔〈《＜<(（"
_APP_CLOSE = "】］\\]〕〉》＞>)）"
_APP_DASH = "－‐‒–—―"          # ASCII のハイフン「-」は入れない（枝番の区切りにだけ使う）
_APP_NUM = "[0-9０-９A-ZＡ-Ｚ]+|[Ⅰ-Ⅻ]|[ⅰ-ⅻ]|[①-⑳]"   # 数字・英字、Ⅰ-Ⅻ、ⅰ-ⅻ、①-⑳
RE_APPENDIX = re.compile(
    rf"^{_WS}[{_APP_OPEN}]?{_WS}(?:資料|付録|附録|Appendix)"
    rf"(?:{_WS}[－‐]?{_WS}(?:{_APP_NUM})(?:[-{_APP_DASH}](?:{_APP_NUM}))*"          # 番号（前に全角のハイフン、後ろに枝番）
    rf"(?=[\s　:：.．、,，{_APP_OPEN}{_APP_CLOSE}{_APP_DASH}]|$)"               # 番号の直後
    rf"|(?![\s　]+[a-z])(?=[\s　:：{_APP_OPEN}{_APP_CLOSE}{_APP_DASH}]|$))")  # 番号のないとき、語の直後
```

`_WS` は既存の `RE_NOTE_MARK` の前にある定義を使う（`RE_APPENDIX` より前にあるので、そのまま使える）。照合は今までどおり `_para_text(b)`
（NFKC をかけない docx の文字）に対して `match`。

- 先頭の括弧（【［[〔〈《＜<(（）を 1 つだけ許す（閉じ括弧はそろえなくてよい）。
- 語の後の番号の前に空白と、全角のハイフン「－」・ハイフン「‐」を許す。**ASCII の「-」は語の直後に許さない**（「資料-1」は本文の文とみなす）。
  枝番の区切り（「資料1-2」の「-」）には ASCII の「-」と全角・ダッシュを許す。
- 番号の直後に、空白・コロン・ピリオド・読点・開き/閉じ括弧・ダッシュ（ASCII の「-」を除く）・行末を許す。番号がないときは、空白・コロン・
  括弧・ダッシュ・行末だけ（読点・ピリオドは許さない。「資料、図表」「資料.」を本文の文とみなす）。
- 番号がなく、語の後ろが「空白 + 英小文字」なら認識しない（「Appendix shows the data」。0.23.1 は認識していた。FIX_PLAN にない絞り込みで、
  英文要旨の段落の書き出しが Appendix の英文だと資料にされるのを防ぐ。試作の途中で、英文要旨「Appendix abstract.」が資料にされるのを見つけた）。

**認識する書き方**（`scratchpad/e/design/re_app.py` の YES。tests/test_structure.py の parametrize にそのまま使う）:

| 書き方 | 0.23.1 |
|---|---|
| 資料（授業プリント） | × |
| 資料Ⅰ　授業プリント / 資料Ⅱ（ワークシート） / 資料ⅰ　授業記録 | × |
| 付録①　調査票 / 資料⑳ | × |
| 資料1-2 / 資料１－２ / 資料1-2-3　表 / 資料A-1 | × |
| 資料－1 / 資料‐2（全角・Unicode のハイフンの後の番号） | × |
| 【資料1】授業プリント / ［資料２］ / （資料3）ワークシート / 〈付録〉 / <資料1> | × |
| 資料2. 授業記録 / 資料1．授業記録 / 資料1、2 / 資料1―授業 / 資料―授業プリント― | × |
| Appendix A / Appendix B: Questionnaire / Appendix Questionnaire / Appendix | ○ |
| 資料　授業プリント / 資料 / 資料1 / 資料１：調査票 / 資料 3 / 　資料3　問題 / 資料A / 資料Ａ　調査票 / 附録1 | ○ |

**認識しない書き方**（NO）:

| 書き方 | 0.23.1 |
|---|---|
| 資料を配布した。 / 資料の分析 / 資料提供 / 資料編 / 付録として示す / 付録は | × |
| 資料-1 / 資料-1 を見よ（ASCII のハイフンが語の直後） | × |
| 資料1- / 資料1-授業（番号の後の ASCII のハイフンに枝番が続かない） | × |
| 資料12の結果 / 資料1を配布した / 資料1は / 資料Aと資料B / 資料Ⅰの / 資料一 | × |
| 資料、図表 / 資料. | × |
| Appendices / Appendix-based | × |
| Appendix shows the data / Appendix abstract.（語の後ろが空白と英小文字） | ○（0.23.1 は認識していた） |

「資料 を配布した」（語の後ろに半角空白）は、0.23.1 と同じく認識する（語の後ろの空白は許すため。英文要旨の後ろでしか使わないので害は小さい）。

### 2.2 build_front_en（資料を始める規則）

段落（表以外・空白でない）ごとに、資料を始めるか（`starts`）を次の順で決める（`ai = b.src in self.overrides`）。

1. `ai and role in ("abstract", "p")` → 始めない（AI が見出しではないと指定した。文字や見出しのスタイルより優先）。
2. `role == "app_heading"`（AI の set_role）→ 始める。
3. `(in_abstract or app is not None) and RE_APPENDIX.match(text)` → 始める（今までどおり。Decision は記録しない）。
4. `in_abstract and app is None and role in HEADING_LEVEL and b.role_origin == "style"`（英文要旨の後ろの、章・節・項見出しのスタイルの段落）→ 始め、
   Decision（mechanical, "style", applied=True）「英文要旨の後ろの、見出しのスタイル「{b.style_name}」の段落「{text.strip()[:20]}」から資料とした
   （英文要旨の中に見出しは来ないため）」（決定事項 8(a)）。資料の中の見出しスタイルの段落は、今までどおり資料の中の段落（PNode）。
5. それ以外は始めない。

続けて、`ai and role == "abstract" and app is not None` なら `app = None`（AI の指定で英文要旨に戻す。その後ろの段落も、次の資料の見出しまで
英文要旨）。`starts` なら今までどおり `AppNode(title=b)`・`region = "app"`・`in_abstract = False`。それ以外の流れ（資料の中の段落、題目・著者・
要旨の振り分け）は変えない。AI の `p`（資料の見出しではない）は、資料の中なら資料の段落、資料の前なら英文要旨の段落になる（2.5 に書く）。
スタイルの "abstract"（英文要旨のスタイル）の段落は、資料の中でも今までどおり資料の段落（td3 は英文要旨のスタイルで資料の見出しを書いている）。

### 2.3 英文要旨の中の和文の段落

`plan.abstract.append(b)` の直後で、`plan.lang == "ja"` なら、`t = "".join(text.split())` のうち `RE_KANA_KANJI`
（`[぀-ヿ㐀-鿿豈-﫿々]`。config.RE_JA_CHARS は全角英数字 U+FF01–FF65 も含むので使わない）に合う文字が
`ABSTRACT_JA_RATIO`（0.3）× len(t) 以上なら:

- `plan.abstract_ja.append(b.src)`
- Decision（mechanical, "style", applied=False）「英文要旨の段落「{text.strip()[:20]}」は、かな・漢字が 3 割以上ある（資料などの和文が英文要旨に
  入っているかもしれない）。自動では移していない」（category "style" なので、AI 依頼文の「推定:」に載り、AI が app_heading を提案できる）
- `plan.warnings.append(f"{b.src}: 英文要旨の段落「{…[:20]}」に、かな・漢字が 3 割以上あります。資料などの和文なら、Word でその前に資料の見出し
  （「資料1」など）を付けて変換し直してください")`

自動では移さない（FIX_PLAN のとおり）。記事の言語は `meta.lang` で英文にもできるが、構造の組み立ては meta を見ないので `plan.lang`（雑誌の設定）で
判定する（英文の論文で英文要旨に和文があっても、知らせて害はない）。

### 2.4 引用文献の後ろの資料（暫定: 警告だけ）

決定事項 8(b) は「確認中」なので、まとめ役の暫定の判断で、資料にはせず知らせるだけにする（扱える原稿が実際に出てから広げる。FIX_PLAN と
DESIGN.md に「暫定」と書く）。`build_back` で、見出しの判定（`heading`）の後、`plan.region[b.src] = state or "back"` の直後に:

```python
if state in ("refs", "fn", "notes", "ack") and not b.is_blank and (
        (role in HEADING_LEVEL and b.role_origin == "style") or (role != "ref" and RE_APPENDIX.match(_para_text(b)))):
    plan.app_after_refs.append(b.src)
    plan.warnings.append(f"{b.src}: {APP_PLACE[state]}の中に、資料の見出しと思われる段落「{…[:20]}」があります。今の版では、"
                         f"引用文献などの後ろの資料は資料として扱わず、{APP_PLACE[state]}の段落として出力しました")
```
`APP_PLACE = {"refs": "引用文献", "fn": "注", "notes": "付記", "ack": "謝辞"}`。段落の扱い（引用文献の 1 件など）は変えない（文字は落ちない）。
FIX_PLAN の「扱うなら」の規則（章・節・項見出しのスタイル、または参考文献のスタイル以外で RE_APPENDIX に合う段落）を、検出の条件にそのまま使う。
td1〜3・既存の fixture には当たる段落がない。

### 2.5 AI の役割（ai_assist.py）

- `ROLES` に `"app_heading": "資料の見出し（英文要旨の後ろの、資料・付録の始まり）"` を `abstract` の後ろに足す（依頼文の役割の一覧に出る）。
- `REGION_ROLES`: `"front_en": {"abstract", "app_heading", "exclude"}`、`"app": {"p", "abstract", "app_heading", "exclude"}`。
- `SYSTEM_PROMPT` の 3. set_role の役割の一覧の後ろに次を足す:
  「Word の脚注・文末脚注の段落と、英文の題目・副題の段落の役割は変えられません。英文要旨の後ろの資料（付録）が英文要旨に入っているときは、
  資料の見出しの段落を app_heading にしてください（その段落から後ろが資料になります）。逆に、英文要旨の段落が誤って資料にされているときは、
  その資料の見出しの段落を abstract にしてください（次の資料の見出しまで英文要旨に戻ります）。」
- 動き: app_heading の段落から資料が始まる（2.2 の 2）。資料の見出しへの abstract で、その見出しとそれに続く段落が英文要旨に戻る（2.2 の 1 と続き）。
  資料の見出しへの p は、資料の中なら前の資料の段落、最初の資料なら英文要旨の段落になる（既存の REGION_ROLES の app の "p" をそのまま残すため。
  「資料の見出しではない」の意味）。

### 2.6 ルート2: pdfdocx._structure の比較に領域を加える

`_structure` の段落ごとの値を `((p.role, plan.region.get(src, "")), links)` にする（役割と領域の組を 1 つ目の要素にする）。`_lost` は
`got[0] != role` で比べているので、変えずに領域の違いも「構造が変わる」として検出し、その段落の直しを `STRUCTURE_REASON` で直さない。
`_structure` の docstring を「段落ごとの（役割, 領域）とリンクの並び …」に、`make_fixed_docx` の docstring の (2) を「段落の役割・領域・リンク…」に直す。
英文要旨・資料の段落は role が '' のままなので、0.23.1 は境の変化を見ていなかった。試作で、英文要旨の段落「資料-1 shows …」（ASCII のハイフン。
資料ではない）を PDF の「資料－1 …」に合わせると新しい正規表現で資料の見出しになる形を作り、領域を比べると直さない（13 章に出る）、比べないと
直して資料に移ることを確かめた（`run_r2b.py`。変異でも確かめた）。

### 2.7 要確認の知らせ（report.actions。単位 D の形）

`report.py` に 2 つの関数を足し、`actions()` の `head` の `lost_action` の後ろに入れる（レポートの冒頭・14 章・Colab の赤い枠・CLI の標準エラーは
`Action` から出る。render・colab・cli・make_notebook.py には何も足さない）。どちらも `TO_CHECK`（要確認。終了コードは変えない）。対象の段落の例は
`_para_samples([(src, plan.paras[src].text_only()) …])`。

- `_abstract_ja_action(r)`（key "abstract_ja"。`r.plan.abstract_ja` が空なら None）:
  - top: 「> **要確認: 英文要旨（trans-abstract）に、和文と思われる段落が {n} 件あります（10 章）。** 資料・付録などの和文が英文要旨に入っている
    かもしれません。資料なら、Word でその段落の前に資料の見出し（「資料1」「資料（授業プリント）」など）を付けて、変換し直してください。
    対象の段落: {例}」
  - checklist: 「- [ ] **英文要旨の中の和文の段落**（{n} 件。10 章）: 資料などの和文なら、Word で資料の見出しを付けて変換し直す」
  - box_title: 「英文要旨に和文の段落があります（要確認）」
  - box_detail: 「英文要旨（XML の trans-abstract）に、かな・漢字が 3 割以上の段落が {n} 件あります。資料・付録などの和文が英文要旨に入っている
    かもしれません。資料なら、Word でその段落の前に資料の見出し（「資料1」など）を付けてから、変換し直してください（レポートの冒頭と 10 章）。
    \n対象の段落: {例}」
  - cli: 「要確認: 英文要旨に和文と思われる段落が {n} 件あります（レポートの冒頭と 10 章）。資料なら、docx に資料の見出しを付けて変換し直すこと」
- `_app_after_refs_action(r)`（key "app_after_refs"。`r.plan.app_after_refs` が空なら None）:
  - top: 「> **要確認: 引用文献などの後ろに、資料の見出しと思われる段落があります（10 章）。** 今の版では、引用文献などの後ろの資料は資料（付録）
    として扱わず、引用文献などの段落のまま出力しています。資料なら、Word で英文要旨の後ろ（論文の最後）に移して、変換し直してください。
    対象の段落: {例}」
  - checklist: 「- [ ] **引用文献などの後ろの資料の見出し**（{n} 件。10 章）: 資料なら、Word で英文要旨の後ろに移して変換し直す」
  - box_title: 「引用文献などの後ろに資料があるかもしれません（要確認）」
  - box_detail: 「引用文献・注・付記・謝辞の中に、資料の見出しと思われる段落があります。今の版では資料として扱わず、引用文献などの段落のまま
    出力しています。資料なら、Word でその見出しと中身を英文要旨の後ろ（論文の最後）に移してから、変換し直してください（レポートの冒頭と 10 章）。
    \n対象の段落: {例}」
  - cli: 「要確認: 引用文献などの後ろに、資料の見出しと思われる段落があります（レポートの冒頭と 10 章）。資料なら、docx で英文要旨の後ろに移して
    変換し直すこと」

10 章の警告（`plan.warnings`）は段落ごとの 1 行（2.3・2.4）。D4 の注は、Decision（4 章）と 8 章で知らせるだけで、Action は足さない
（リンクのない注・記号を自分で付けた注は出力され、文字は落ちないため）。

## 3. N6: set_role の可否を 1 つの関数にまとめる（ai_assist.py）

```python
def set_role_problem(p, plan: ArticlePlan, role: str) -> str:
    """段落 p に set_role で役割 role を指定できない理由（指定できれば ''）。role_overrides（回答の検証）と、依頼文の除外の一覧の案内で使う。"""
```

拒否の規則（上から順に見て、最初に当たった理由を返す）:

| 順 | 条件 | 理由の文言 |
|---|---|---|
| 1 | `role not in ROLES` | 役割「{role}」は指定できない（今のまま） |
| 2 | `p.float_id` | テキストボックス・グループ図形の中の段落の役割は placements で指定する（今のまま。tests/test_floats.py が "placements" を確かめる） |
| 3 | `p.src in plan.note_of`（Word の脚注・文末脚注の段落すべて。fn_start に限らない。参照のない注も） | Word の脚注・文末脚注の段落の役割は変えられない（注の区切りは Word のとおりにする） |
| 4 | `not plan.region.get(p.src)`（領域のない段落: 冒頭・後付け・英文の部分の表のセルなど） | 表のセルなど、論文の中の位置が決まっていない段落の役割は変えられない |
| 5 | `p` が `plan.title_en`・`plan.subtitle_en` の段落（暫定。FIX_PLAN にない） | 英文の題目・副題の段落の役割は変えられない（変えると英文の題目・副題が XML から落ちる） |
| 6 | `role == "app_heading"` で、領域が "app" でなく、`p` が `plan.abstract` にない | 資料の見出し（app_heading）にできるのは、英文要旨と資料の段落だけ |
| 7 | `role not in REGION_ROLES.get(region, set())` | この位置（{region}）では役割「{role}」を指定できない（今のまま） |

- 3: Word の注の段落は `Classifier.role_of` を通らない（`flat` に入らない）ので、どの役割も必ず捨てられていた（「採用」と記録されるのに何も変わらない。
  e3・f3 の形）。
- 4: 領域のない段落の役割は `split_regions` の表の役割の判定（`table_roles`）にしか使われず、題目の役割で冒頭の領域を変えてしまうことがある。
- 5: 試作で、英文題目への app_heading が採用され、英文副題が XML から落ちて不変性チェックが不合格になるのを見つけた。0.23.1 でも、英文題目への
  exclude・abstract で同じことが起きる（英文副題が `subtitle_en` に入るが、題目がないので書き出されない。不変性チェックは不合格になるので黙っては
  落ちない）。FIX_PLAN の「英文題目への app_heading は採用されない」を、英文の題目・副題の段落への役割すべてに広げた（暫定の判断として記録する）。
- テキストボックスの段落（float_id のないもの）の規則は F で足す（今は領域 "body" なので p などを受け付ける）。

`role_overrides` は、段落の有無を確かめた後、`why = set_role_problem(plan.paras[src], plan, role)` が空でなければ `rejected` に入れる
（今の 4 つの if を置き換える）。

**依頼文の除外の一覧の案内**（`build_request`）: 今は除外したすべての段落に「（本文の一部なら set_role を提案）」と書いている
（冒頭の段落に p を出すと必ず捨てられる）。次の関数で書き分ける（`plan.paras.get(e.src)` がなければ案内を書かない）。

```python
def set_role_hint(p, plan) -> str:
    if not set_role_problem(p, plan, "p"):
        return "（本文の一部なら set_role を提案）"                       # 本文・付記・謝辞・注・後付け・資料（今のまま）
    ok = [r for r in ROLES if r != "exclude" and not set_role_problem(p, plan, r)]
    if ok:
        return f"（set_role で指定できる役割: {', '.join(ok)}）"          # 冒頭の段落なら「title, subtitle」
    return "（この段落の役割は set_role では変えられない）"               # Word の注・著者表・領域のない段落・図形の中の段落
```

`tests/test_notes.py` の `test_ai_cannot_split_word_footnotes` の期待を、3 の文言に直す。

## 4. テストの計画

### 4.1 fixture（tests/make_fixtures.py）

- `Builder.endnotes_extra` は A で足し済み（FIX_PLAN の「足す」は古い）。`footnotes_extra` も既存。
- 部品を足す: `footnote(nid, text, *more)`（脚注。1 段落目は `w:footnoteRef` と text。sample_edge の書き方と同じスタイル a8/a9）、
  `footnote_ref(nid, custom=False)`、`endnote_ref(nid, custom=False)` に custom を足す（`w:customMarkFollows="1"`）、`deleted(xml)`（`w:del` で包む）。
- `make_article` に `footnotes=()`・`abstract=("Small article abstract.",)`・`appendix=None` を足す（既定は今と同じ出力）。
- **sample_structure.docx**（ALL_DOCS。`STRUCTURE_SECTIONS` に節を足し、`make_structure` に資料を足す）:
  - 節「Word の脚注と文末脚注」（`structure_word_notes(b)`）: 段落 1「脚注を付けた文」+脚注 5 の参照+「と文末脚注を付けた文」+文末脚注 5 の参照+「。」、
    段落 2「削除した参照」+ `w:del` の中の脚注 6 の参照+「のある文。」、段落 3「記号を自分で付けた文末脚注」+文末脚注 7 の参照（customMarkFollows）+
    上付きの「*」+「の文と，注の中から文末脚注を参照する脚注」+脚注 8 の参照+「の文。」。脚注 5・6・8（8 の本文に文末脚注 8 の参照）・9（参照なし。
    2 段落目は全角空白だけ）、文末脚注 5（2 段落）・7・8。期待: fn1=脚注 5「1)」、fn2=文末脚注 5「2)」、fn3=文末脚注 7（本文は「*」のまま、
    注の一覧は「3)」）、fn4=脚注 8、fn5=文末脚注 8（脚注 8 の中からリンク）。脚注 6（削除）・9（参照なし）は除外。
  - 資料: `make_structure` の `mf.tail(b, appendix=…)` に、英文要旨のスタイルの「資料（授業プリント）」と、続く 2 段落（「問1　…」「問2　…」）。
    期待: app-group/app/title が「資料（授業プリント）」、続く 2 段落は app の中、trans-abstract は「Structure abstract.」だけ。
  - 不変性・最終・DTD・jstage_issues == [] を満たすこと（試作の同じ形の docx で確かめた）。
  - 作り直しは `python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_structure('tests/fixtures/sample_structure.docx')"`
    だけ。`git diff --stat tests/fixtures` で sample_structure.docx だけが変わったことを確かめる。
  - 既存の N2 のテスト（test_structure.py）は段落の文字で選ぶので壊れない。
- 小さな原稿はテストの中で `make_article` などで作る（ALL_DOCS に入れない。golden の件数は 23 のまま）。

### 4.2 tests/test_notes.py（D4・N6）

1. `test_endnote_becomes_fn_and_ids_do_not_collide`（STRUCTURE）: 文末脚注 5 が fn2、本文の参照が rid=fn2・`<sup>`「2)」、脚注 5 の参照は fn1・「1)」。
   fn-group の fn の数 5、`text(fn2)` が「2) 」で始まり 2 段落。不変性・最終・DTD。
2. `test_note_numbers_follow_first_reference`（STRUCTURE）: rid の並びと番号（fn1〜fn5）。脚注 8 の中の参照が fn5 へのリンクで、文末脚注 8 が除外されない。
3. `test_custom_mark_endnote_keeps_docx_mark`（STRUCTURE）: fn3 への xref は中身が空（`<sup>` なし）、直後の docx の「*」はそのまま、注の一覧は「3)」。
   Decision「本文の記号を自分で付けた注」。
4. `test_unreferenced_and_deleted_notes_are_excluded`（STRUCTURE）: 脚注 9 の段落が理由「Word の脚注 9（本文から参照されていない注）」、全角空白の段落が
   「空白のみの段落」（blank）、脚注 6 が「本文の参照が変更履歴で削除された注」。不変性に合格（`fid.missing == []`・`bad_excluded == []`）。
5. `test_blank_paragraphs_in_notes_pass_fidelity`（make_article）: 参照された文末脚注と参照されていない脚注・文末脚注に、全角・半角の空白だけの段落を
   入れて、不変性に合格（付録の点検のテスト）。
6. `test_note_referenced_only_from_excluded_paragraph`（make_article。英文の部分の題目以外の段落に文末脚注の参照）: 注は出力され、xref はなく、
   Decision「本文からのリンクのない注」、8 章の表に「なし（参照は XML に出力しなかった段落 …）」。
7. `test_ai_cannot_set_role_on_word_notes`（STRUCTURE）: 文末脚注の段落への set_role p・exclude、脚注の段落への fn_start が、すべて理由 3 で不採用
   （`res.ai.accepted` に入らない）。参照のない注の段落（領域なし）も理由 3。
8. 既存 `test_ai_cannot_split_word_footnotes` の期待を理由 3 の文言に（FIX_PLAN の test_notes.py:91）。
9. `test_report_wording_for_footnotes_only_is_unchanged`: 既存の `test_word_footnotes_use_journal_mark_and_get_a_title`（EDGE）の文言の確かめ
   （「注 1（うち Word の脚注 1）」「Word の脚注機能で書かれた注 1 件を、注の一覧にした」）がそのまま通ることに加え、8 章に対応の表が出ないこと。
   STRUCTURE では 1 章が「（うち Word の脚注・文末脚注 …）」、8 章に表が出て「| fn2 | Word の文末脚注 5 | 2) | あり |」がある。
10. `test_note_key_and_label`: `note_key("footnote-custom", "5") == "footnote:5"`、`note_label("endnote:5") == "Word の文末脚注 5"`、
    `note_label("endnote-custom:5")` も同じ。

### 4.3 tests/test_structure.py（D3）

1. `test_appendix_heading_forms`: `re_app.py` の YES・NO を parametrize（`RE_APPENDIX.match`）。
2. `test_appendix_with_paren_is_not_in_abstract`（STRUCTURE）: app-group/app/title「資料（授業プリント）」、2 段落は app の中、trans-abstract に入らない。
   不変性・DTD（fix_plan_repro_tests の `test_PROBLEM_appendix_with_paren_goes_into_abstract` の逆）。
3. `test_appendix_heading_variants_become_app_titles`（小さな原稿。`make_article(appendix=…)`）: 「資料Ⅰ　授業プリント」「資料Ⅱ（ワークシート）」
   「付録①　調査票」が app-group/app/title になる（付録の点検のテスト）。
4. `test_heading_style_after_abstract_starts_appendix`: 英文要旨の後ろの章見出しスタイルの「授業の記録」から資料、Decision の文言。
5. `test_japanese_paragraph_in_abstract_is_reported`: 英文要旨に「問2　…」（英文要旨のスタイル）。trans-abstract に残る（自動で移さない）、
   Decision（applied=False）、10 章の警告、冒頭と 14 章の要確認（Action "abstract_ja"）。英文だけの要旨では出ない（STRUCTURE で確かめる）。
6. `test_appendix_after_references_is_warned`: 引用文献の後ろの章見出しスタイルの「資料　授業プリント」。app-group は作らない、段落は引用文献のまま
   （文字は落ちない）、10 章の警告と要確認（Action "app_after_refs"）（付録の点検のテスト「引用文献の後ろに…の期待（app-group、または警告）」の
   警告の側。暫定）。

### 4.4 tests/test_ai.py（D3・N6）

1. `test_set_role_app_heading_starts_appendix`: 英文要旨の和文の段落への app_heading が採用され、その段落から資料になる（app/title）。
2. `test_set_role_app_heading_on_english_title_is_rejected`: 英文題目への app_heading が不採用（理由 5）、不変性に合格。英文題目への exclude も不採用。
3. `test_set_role_abstract_returns_heading_style_appendix`: 見出しのスタイルで始めた資料の見出しへの abstract で、その段落と続く段落が英文要旨に戻る。
4. `test_set_role_problem_rules`: `set_role_problem` を直接呼ぶ単体テスト（理由 1〜7 のそれぞれ。領域のない段落は `plan.region` から消して作る）。
5. `test_request_hints_follow_set_role_problem`: 依頼文の除外の一覧の案内が、冒頭の段落は「（set_role で指定できる役割: title, subtitle）」、
   Word の注・著者表の重複する所属は「（この段落の役割は set_role では変えられない）」、本文の段落は今のまま。依頼文の役割の一覧に app_heading がある。

### 4.5 tests/test_pdfmatch.py（D4・D3 のルート2）

1. 既存 `test_word_footnote_numbers_follow_pdf` の `number_edits` の鍵を `("fnref", "footnote:5")`・`("fnlist", "footnote:5")` に（FIX_PLAN の :190）。
   レポートの「| 注の一覧の脚注番号 | Word の脚注 5 | … |」はそのまま。
2. `test_endnote_numbers_and_text_follow_pdf_in_route2`: `make_article` の小さな原稿（脚注 5 と文末脚注 5）を `convert_with_pages(…, "pdf", docx=…)`
   （extract_pages の差し替え。sample_pdfcheck.pdf は作り直さない）。期待: `number_edits` に `("fnref", "endnote:5")`、文末脚注の段落 e… の全角・半角の
   直しが `docx_fix.applied` に入り、直した docx を読み直して合う、13 章の番号の表に「Word の文末脚注 5」、fn2 の文字が PDF に合う（試作 `run_r2.py`）。
3. `test_route2_keeps_abstract_appendix_border`: 英文要旨の段落「資料-1 shows …」と PDF「資料－1 …」。直さない（`STRUCTURE_REASON`）で 13 章に出し、
   XML の英文要旨に残る（試作 `run_r2b.py`。領域を比べないと資料に移ることを変異で確かめた）。

### 4.6 A の暫定の知らせのテストの書き直し（FIX_PLAN の「既存テストの修正は 2 つ」は古い。A で足したテストも直す）

- `tests/test_lost_images.py`:
  - モジュールの docstring から「・Word の文末脚注」を消す。
  - `test_image_in_endnote_is_reported_with_location` → 2 つに: 参照された文末脚注の画像は XML に出る（`lost_images == []`、fn の中の inline-graphic、DTD 合格）。
    参照されていない文末脚注の画像は要対応（`li.location == "Word の文末脚注 4"`、理由が「XML に出力しなかった段落（理由「Word の文末脚注 4（本文から
    参照されていない注）」」で始まる、9 章の行）。試作 `img_en.py` で両方を確かめた。
  - `test_provisional_notices_for_textbox_and_endnote` → `test_provisional_notices_for_textbox`: 文末脚注の行・並びの確かめを消し、文末脚注が fn-group に
    出て「要確認: Word の文末脚注」が出ないことを確かめる。`make_provisional` の docstring も直す。
  - `test_cli_shows_provisional_notices`: 文末脚注の行を「出ない」確かめに。
- `tests/test_pipeline.py::test_blank_paragraphs_in_textbox_and_endnote_are_excluded`: 参照された文末脚注の空白段落は注の中に出力されるので、N3 の確かめの
  ために参照されていない文末脚注（全角・半角の空白の段落つき）を足し、期待の `("e", " "), ("e", "　")` はそちらから来るようにする。
  `reasons[" 文末脚注の本文。"]` の確かめは、参照された文末脚注が fn に出ることと、参照されていない文末脚注の理由に変える。
- `docs/fix_plan_repro_tests.py`: `test_PROBLEM_appendix_with_paren_goes_into_abstract`・`test_appendix_with_space_is_recognized`（比較）・
  `test_PROBLEM_endnotes_are_excluded` を取り除き、冒頭の docstring に「単位 E（0.24.0）で取り除いたもの: …（逆は tests/test_structure.py・
  tests/test_notes.py）」を足す。PROBLEM の逆は 4.2 の 1・4.3 の 2 で取り込む。
- `tests/__pycache__` を残さない。

## 5. 合格の条件

- **pytest**: すべて合格（3.13 と 3.10。`python -m pytest -q -p no:cacheprovider`、3.10 は venv310）。ruff check src tests tools が通る。
  試作（D4・N6・D3 の主な部分）では、意図して変わる 6 件（4.6 の 4 件、test_notes の文言、test_pdfmatch の鍵）以外の 680 件が通った。
- **golden**（23 件）: XML は sample_structure 系（sample_structure_manual・_split）だけが変わる（D3・D4 の要素を足すため）。それ以外で変わってよいもの:
  - すべての `prompt`（AI 依頼文）: 役割の一覧に app_heading、SYSTEM_PROMPT の set_role の 1 段落、冒頭の除外の段落の案内（「（set_role で指定できる役割:
    title, subtitle）」）、著者表の重複する所属の案内（「（この段落の役割は set_role では変えられない）」）。
  - sample_edge の `prompt`・`report`: Word の脚注の段落の場所「Word の脚注 1件中」→「Word の脚注 5（注 1）」（4 章の表・依頼文の段落一覧）、
    依頼文の注の一覧「（Word の脚注）」→「（Word の脚注 5）」。
  - 試作では、XML の変化は 0 件、レポートの変化は sample_edge の 2 件だけ、依頼文の変化は 13 件だった（sample_structure の fixture を足す前）。
  - 違いは本体を diff して 1 つずつ理由を書く。
- **td1〜3**（ルート1・AI 手動。0.23.1 と比べる）: XML とレポート（版・日時の行を除く）が 0.23.1 と同じ（Word の注がなく、資料の認識も同じなので）。
  AI 依頼文は、役割の一覧・SYSTEM_PROMPT の 1 段落・冒頭の除外 3 段落の案内だけが違う（試作で確かめた。テキストボックスの除外の案内は変わらない）。
  不変性・最終・DTD・J-STAGE のチェックに合格、XML に入らなかった画像が増えない、終了コードが 0.23.1 と同じ（1。手動モードで回答前）。
- 版 0.24.0（`__init__.py`・`pyproject.toml`）、ノートブックの作り直し（`tests/test_notebook.py`）。

## 6. 文書の直し

- `docs/DESIGN.md`: 3 章の暫定の知らせの行（文末脚注を消す）、4.3（文末脚注の暫定の知らせを消し、参照のない注の除外を書く）、4.4（照合する段落の
  「資料」を正確に: 資料の見出しは照合しないが、資料の中の段落は照合する。Word が付ける番号に文末脚注、`_structure` の比べに領域）、
  5（set_role_problem の規則、app_heading・abstract）、6 章の表の「注」（文末脚注・通し番号・鍵・参照のない注・customMarkFollows）・「資料」（認識の
  規則・見出しのスタイル・和文の段落・引用文献の後ろは暫定で警告だけ）、7（文末脚注の暫定の行を消し、残る限界〈7 章〉を足す）。
- `docs/DEVELOPMENT.md`: コードの構成（model.note_key・note_label）、テストの節（sample_structure の D3・D4、test_notes・test_structure・test_ai・
  test_pdfmatch の新しいテスト）、残っている課題（「画像を出力できない場所…Word の文末脚注」の行を直し、文末脚注の番号と customMarkFollows の
  J-STAGE での表示、引用文献の後ろの資料〈決定事項 8(b)〉、AI の app_heading の実際の AI での確かめを足す）。
- `docs/FIX_PLAN.md`: E の節に「実施の記録」（決めたこと、暫定の判断 (1) 引用文献の後ろの資料は警告だけ・(2) customMarkFollows の文末脚注・
  N6 の英文の題目・副題の規則・Appendix の英小文字の規則・削除された参照の扱い、既存テストの書き直しの実際の件数）。決定事項 8 に「(b) は暫定で警告
  だけ（2026-10-26。利用者に未確認）」。「同じファイルを触る順と、既存テストの書き換え」に E で触ったファイル。
- `README.md`: 148 行あたりの要確認「Word の文末脚注」を消し、文末脚注は注として出る（番号は本文で最初に参照される順の通し番号）、新しい要確認
  （英文要旨の和文の段落・引用文献の後ろの資料）を足す。236 行あたりの「できないこと」から文末脚注を消し、customMarkFollows の注の記号を足す。
- docstring: structure（attach_word_notes・FnNode・TEXTBOX_TEXT_EXCLUDED のコメント）、model（Atom・Document）、emit、builder.word_note_marks、
  pdfmatch（_para_seq・compare・PdfCheck.numbers）、pdfdocx（_structure・make_fixed_docx）、report（provisional_exclusions・word_note_refs）。

## 7. 決めなかったこと・却下した案・残る限界・利用者に確かめること

**却下した案**
- 参照の順を領域の順（本文 → 注の中 → 除外した段落）にする: Word の番号の数え方と違い、0.23.1 の脚注の番号が変わりうるので採らない。
- 削除の変更履歴の中の参照も参照として数え、リンクのない注として出す: Word で変更を承諾した原稿にない注が XML に出るので採らない（理由で区別して除外）。
- 脚注と文末脚注を別の番号にする・文末脚注を除外のままにする（決定事項 7 の他の案）。
- 和文の段落を自動で資料に移す（FIX_PLAN のとおり移さない）。
- 引用文献の後ろの資料を AppNode にする（決定事項 8(b) の「はい」。暫定で採らない）。
- 依頼文の案内を「本文の一部なら set_role を提案」のままにして、`role_overrides` だけ直す（AI に必ず捨てられる操作を勧め続ける。N6 の趣旨に反する）。

**暫定の判断（利用者に確かめていない。FIX_PLAN と DESIGN.md に「暫定」と書く）**
1. 決定事項 8(b): 引用文献などの後ろの資料は、資料にせず 10 章の警告と要確認の知らせだけ。
2. customMarkFollows の文末脚注: 脚注と同じ（番号を 1 つ使い、注の一覧は「n)」、本文の印は docx の文字のまま）。本文と注の一覧の記号が合わないので、
   Decision と 8 章の表で知らせる。範囲外として DESIGN.md の 7 章に書く。
3. N6 で、英文の題目・副題の段落への set_role をすべて拒否する（FIX_PLAN は英文題目への app_heading だけ）。
4. RE_APPENDIX で、番号のない「Appendix」の後ろが空白と英小文字なら認識しない（0.23.1 より狭い）。

**残る限界**
- 題目・著者名・所属・引用文献の段落の中の Word の注の参照は、上付きの番号だけでリンクにならない（0.23.1 の脚注と同じ。知らせない）。
- 手で書いた注（「注」の節の「1)」）と Word の注が両方ある原稿では、Word の注の番号も 1 から始まり、注の一覧に同じ番号が 2 つ並ぶ（0.23.1 と同じ）。
- 文字だけのテキストボックスの中の段落（float_id のないもの）への set_role は、F まで今のまま受け付ける。
- 英文要旨の和文の判定は段落ごとの割合だけで、短い和文の行（「キーワード：…」など）でも要確認になる。
- 資料の見出しのスタイル（章・節・項見出し）で始める規則は、英文要旨の後ろの「Key words」などを見出しのスタイルで書いた原稿では、そこから資料に
  なる（Decision と AI の abstract で戻せる）。
- `pdfmatch.target_paragraphs` の docstring と DESIGN.md 4.4 は「資料は照合しない」と書くが、コードは資料の中の段落を照合し、資料の見出しだけを
  照合しない（下の食い違い 1）。

**利用者に確かめてもらうこと（DEVELOPMENT の「残っている課題」に書く）**
- J-STAGE の試験登載で、文末脚注から作った注（fn-group の fn）と本文の「n)」の表示、customMarkFollows の注（本文の記号と、注の一覧の番号）の表示。
- 決定事項 8(b)（引用文献の後ろに資料を置く原稿が本誌にあるか）。あれば資料として扱う規則（FIX_PLAN の「扱うなら」）に広げる。
- 実際の AI（少なくとも Claude）で、app_heading・abstract の set_role と、拒否される set_role を勧めなくなった依頼文の振る舞い。
- 英文要旨の和文の段落の要確認が、実際の原稿で出すぎないか。

## 8. 見つけた食い違い（文書とコード）

1. `pdfmatch.target_paragraphs` の docstring と `docs/DESIGN.md` 4.4（「照合する段落: …（表のセル・別行の数式・資料、4 文字未満の段落は除く）」）は
   資料を照合しないと書くが、`linker.body_paragraphs` が資料の中の段落を "back" で返すので、資料の中の段落は照合し、直す（資料の見出しは返さないので
   照合しない）。sample_full で確かめた。コードに合わせて DESIGN.md を直す。pdfmatch.py の docstring は、B2.1 の控えとの衝突を避けるため E では
   直さず、B2.1 を再開するときに直す（まとめ役の判断）。
2. FIX_PLAN の D4 の付録「Builder に endnotes_extra を足し」: A ですでに足してある（`make_article(endnotes=…)` もある）。
3. FIX_PLAN の E の節「既存テストの修正は 2 つ」: A で足した暫定の知らせのテスト（tests/test_lost_images.py の 3 件、tests/test_pipeline.py の 1 件）も
   直す必要がある（4.6）。
4. `structure.attach_word_notes` が付けていた場所「Word の脚注 {n}件中」は、注ごとの場所ではなく全件数（docstring・レポートの見出しの趣旨と合わない）。直す。
5. `report.word_note_refs` の docstring は「注へのリンクとして出力されるもの」だが、0.23.1 は除外した段落の参照も数えていた。docstring に合わせて直す。
6. `ai_assist.build_request` の除外の案内「（本文の一部なら set_role を提案）」は、冒頭・著者表・Word の注の段落では必ず捨てられる操作を勧めていた（N6）。
7. 0.23.1 の不具合（文書との食い違いではないが記録する）: AI の set_role で英文題目を exclude・abstract にすると、英文副題が XML から落ち、不変性
   チェックが不合格になる（黙っては落ちない）。E の set_role_problem の規則 5 で止める。
8. FIX_PLAN の文中の行番号（L789・L1179 など）と `rvz_d3.py`・`rvz_d4.py`・`exp_struct_re.py` は古い・残っていない（computed task のとおり）。
