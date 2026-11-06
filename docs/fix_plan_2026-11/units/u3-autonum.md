# 単位 u3-autonum（0.30.0）: Word の自動番号の出力漏れ（表のセルほか）と、自動番号の出力の確かめ

## 要点

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

## 再現（確かめたこと）

再現と試作のスクリプトは `docs/fix_plan_2026-11/protos/u3-autonum/` と `docs/fix_plan_2026-11/protos/review-u3-autonum/` にある。
どれも計画のときの作業フォルダ（scratchpad）のパスを前提に書かれていて、そのままでは動かない。手本として読むものである。
出力のフォルダ・生成した docx（監査の docx を含む）は写していない。

| 項目 | 結果 | スクリプト | 見たこと |
|---|---|---|---|
| 表のセルの自動番号 | 再現 | `u3-autonum/repro_cell.py` | `make_article` で、セルに `list_item(num_id=7)` を置いた表（1 段落のセル・2 段落のセル）を変換。plan の autonum は d13=`1.`・d15=`2.`・d16=`3.` なのに、td は「番号付きの質問」「二つ目の質問<break/>三つ目の質問」だけ。`fidelity.generated` は空、不変性チェック・DTD は合格、`needs_action` は偽。`--proto`（試作）では「1. 番号付きの質問」「2. 二つ目の質問<break/>3. 三つ目の質問」になり、不変性チェック・DTD とも合格 |
| ルート2 のセルの番号 | 再現せず（心配した形は起きない） | `u3-autonum/route2_cells.py` | pdfmatch は XML でなく plan を照合し、`_para_seq` は全段落（セルも）の照合の列の先頭に autonum を入れる。セルの段落は `linker.body_paragraphs` の文脈 `cell` で `target_paragraphs` に入らず、`_classify` されない。テストデータ1（セルの番号の段落 5）・テストデータ2（11）で、ルート1・ルート2 とも違い 0・番号の直し 0・直す箇所 0、補完の確かめは合格。`supplement_targets` の numbers はセルの番号も含むが、`pdf_numbers` に鍵がないので確かめの対象にならない |
| 番号が落ちる経路の洗い出し | 再現 | `u3-autonum/audit.py` | numId=7 の段落を各所に置いた docx（題目・副題・著者・所属は document.xml を後から書き換えて numPr を付けた）で、`Builder.autonum` が呼ばれたかと文字の XML の位置を表にした。番号が落ちる: `article-title`・`subtitle`・和文著者 `surname`・`institution`・`trans-title`・`trans-subtitle`・英文著者・英文所属、`disp-quote/p`、`disp-formula`、`fig/caption/p`・キャプションの続き・`table-wrap/caption/p`、`td`（本文の表・表で組んだ図の表・資料の表）、`notes/title`・`ack/title`・`fn-group/title`・`ref-list/title`・`trans-abstract/title`・`app/title`、`trans-abstract/p`、`fn/p` の 2 段落目以降（手で書いた注の続きと、自動番号「1.」の形で始まる 2 つ目の注〈`RE_NOTE_MARK` に合わず前の注の続きになる。K8〉）、Word の脚注の 2 段落目。番号が出る: `sec/label`、本文の `list-item/label`、囲みの中の箇条、付記・謝辞・資料の箇条と見出しの役割の段落（A7）、`ref/label`、手で書いた注の 1 段落目。文字を出さないので守りにも見えない: 画像だけの段落（`FigNode.image_paras`）、文字のない番号だけの段落、除外した段落 |
| 全 docx の実際の出力漏れ | 再現 | `u3-autonum/scan.py` | fixture 15 件・tests/private の docx 10 件のルート1、PDF のある 6 件のルート2、計 31 回。番号が落ちていたのは表のセルだけ（テストデータ1 で 5、テストデータ2 の 2 つの docx で各 11）。ほかの経路と fixture は 0 件 |
| 試作の直し方と守り | 確かめた | `u3-autonum/proto.py`・`proto_plugin.py`・`chk/test_chk.py` | 実行時に builder・emit を差し替える試作。監査の docx と 31 回の変換で、不変性チェック・最終出力の再チェック・DTD・補完の確かめはすべて合格。守りの報告は、わざと src を付けなかった引用文献の label の 1 件だけ（付け忘れを検出できる）。既存のテスト 1298 件は試作を当てても全部通った（`python -m pytest -q -p proto_plugin`）。今のコードに守りだけを当てると、テストデータ1 で 5 件、テストデータ2 で 11 件（どれもセル）を報告する。試作の守りは題目・著者・所属を祖先の要素で飛ばしていて、この計画の `unshown_numbers` での飛ばし方は試作していない |
| Word の脚注の 1 段落目の自動番号 | 確かめた | `review-u3-autonum/fn_first.py` | 試作を当て、footnotes.xml の 1 段落目に numPr を足した。本文が空白で始まらない形では「1) 1. 脚注の一段落目。」で、不変性チェック・DTD とも合格、守りの報告 0。本文が空白で始まる形は、試作では「1)1. …」になる（`_starts_with_space` で 2 つの区切りがどちらも空。コードを読んで確かめた）。直し方の `fn` で直す |
| `jx:gen` に src を足す影響 | 確かめた | （コードを読んだ） | `fidelity.verify` は GEN から kind と text だけを読み、`final_check` は itertext だけ、`finalize` は strip_tags で属性ごと消す。tests/ に `jx:gen` の属性を確かめるものはない |
| 段の書式で隠した番号 | 確かめた | （点検で探した） | tests/private と fixture の全 docx の numbering.xml の `w:lvl` に `w:vanish` は 0 件 |

原因: Word の自動番号は読み取り（`docx_reader.py` 330 行目）が `Para.autonum` に入れるだけで、XML に出すかどうかは builder の書き出し関数ごとに任されている。
番号を出すのは `sec`（492〜494 行目）・`list_node`（550〜552）・`paragraph_or_formula(autonum_mark=True)`（529〜542。付記・謝辞・資料の PNode だけ）・
`ref`（819〜821）・`fn` の 1 段落目（836〜844）だけで、ほかは `self.em.span(...)` だけを呼ぶ。structure は本文・付記・謝辞・資料・囲みの番号付きの段落を
`ListNode` にするので本文ではほぼ表に出ないが、`ListNode` にならない場所の番号は落ちる。`jx:gen` には段落 ID がないので、どの段落の番号を出したかを後から確かめられない。

## 直し方

文字列は 1 文字も変えない（番号は生成文字で、docx の文字ではない）。番号は必ず `Builder.autonum(p)`（ルート2 の `plan.pdf_numbers` を引く。91〜93 行目）を通す。

### 1. emit.py・tracking.py

- `Emitter.gen(parent, text, kind, src=None)`（emit.py 121〜125 行目）: `src` があれば `el.set("src", src)`。kind が `"autonum"` の呼び出しには、すべて番号の段落の ID（`p.src`）を渡す。
  `footnote-mark`・`fn-title` は今のまま（src なし）。fidelity・finalize は変えない。
- tracking.py の docstring の jx:gen の行を `<jx:gen kind="autonum" src="d12">1.</jx:gen>` にし、説明に「kind が autonum のとき、src は番号の段落の ID（`pipeline.lost_autonums` が使う）」を足す。
- 既存の kind autonum の呼び出しに src を足す: `sec`（494: `h.src`）、`list_node`（552: `p.src`）、`ref`（821: `r.para.src`）。`fn` は 4.(g) で書き直す。
  kind autonum の呼び出しは、直した後は `sec`・`list_node`・`ref`・`fn`・`autonum_mark`・`caption` の 6 か所になる。どれにも src を付ける。

### 2. builder.py の補助関数

```python
def autonum_mark(self, parent, p) -> None:
    """段落 p の Word の自動番号を、生成した文字（jx:gen kind autonum、src は p.src）として parent の今の末尾に補う（段落の jx:span の直前に呼ぶ）。
    番号と本文の区切りは、docx の文字が空白で始まるか、番号が全角の文字で終われば補わず、そうでなければ半角の空白 1 つ。"""
    if not p.autonum:
        return
    mark = self.autonum(p).strip()
    if mark:
        sep = "" if _starts_with_space(p) or unicodedata.east_asian_width(mark[-1]) in ("F", "W") else " "
        self.em.gen(parent, mark + sep, "autonum", p.src)

def heading_title(self, parent, p):
    """後付け（付記・謝辞・注・引用文献・資料）と英文要旨の見出しの <title>。自動番号は <title> の先頭に生成文字で補う。"""
    t = _sub(parent, "title")
    self.autonum_mark(t, p)
    self.em.span(t, p, E.SECTITLE)
    return t

def unshown_number(self, p, what) -> None:
    """題目・副題・著者名・所属の段落の自動番号は XML に出さず、記録する（10 章の警告。守り lost_autonums は飛ばす）。"""
    if (p.autonum or "").strip():
        self.info.unshown_numbers.append((p.src, self.autonum(p).strip(), what, p.text_only().strip()[:20]))
```

`BuildInfo`（builder.py 45 行目）に `unshown_numbers: list = field(default_factory=list)` を足す。コメントは
「番号を XML に出さなかった題目・副題・著者名・所属の段落 [(段落 ID, 番号, 場所の名前, 段落の文字の冒頭 20 字)]（10 章の警告。pipeline.lost_autonums は飛ばす）」。

### 3. 書き出し経路ごとの直し（すべて段落の jx:span の直前で番号を出す）

(a) **表のセル** `cell_content`（708〜731 行目）: ループの中の `if not first: _sub(td, "break")` の後、`self.em.span(td, p, E.CELL)` の直前に
`self.autonum_mark(td, p)`。2 段落目以降は `<break/>` の後ろに番号が来る。`p.is_blank and not p.plain()` で飛ばす段落は今のまま飛ばす。
本文の表・表で組んだ図の表（`fig` の `node.tables`）・付記・謝辞・資料の表・注の節の表（u5）のすべてがここを通る。

(b) **paragraph_or_formula**（529〜542）: 引数 `autonum_mark` をなくし、常に `self.autonum_mark(pe, p)` を呼んでから span を書く。
呼び出し元 `backsec`（788）・`app_children`（801）の `autonum_mark=True` を消す（取り残すと TypeError）。本文の PNode に自動番号の段落は来ない
（structure の assemble が `ListNode` にする）ので本文は変わらず、英文要旨の段落（305）の番号が出るようになる。docstring は次にする。

```
段落 p を <p> に書く。自動番号のある段落の番号は、生成した文字（jx:gen。docx の文字ではない）として <p> の先頭に補う。
自動番号のある段落が <p> になるのは、箇条（ListNode）にしない段落だけ: 後付け（付記・謝辞・資料）の中の見出しの役割の段落
（structure.add_back_para）と、英文要旨の段落など。<p> に <label> は置けないので、番号は注と同じく生成した文字で補う。
```

(c) **引用** `nodes` の QuoteNode（464〜468）: `pe = _sub(dq, "p")` の後に `self.autonum_mark(pe, p)`。

(d) **別行数式** `formula`（733〜739）: `self.em.span(df, p, E.DISPF)` の前に `self.autonum_mark(df, p)`（disp-formula は混合内容で DTD を通る。試作で確かめた）。

(e) **図・表のキャプション**: `fig`（559〜568）と `table_wrap`（630〜638）のキャプションの分岐の重複を `self.caption(holder, cap)` にまとめる。

```python
def caption(self, holder, cap):
    """図・表のキャプション。自動番号があれば、章見出しと同じく番号を <label> に出し、キャプションの文字は分けない
    （split_labels にかかわらず）。なければ今までどおり（split_labels のとき「図1」を <label> に分ける）。"""
    if cap.autonum and self.autonum(cap).strip():
        self.em.gen(_sub(holder, "label"), self.autonum(cap), "autonum", cap.src)
        self.labelled(holder, cap, RE_LABEL_SPLIT, E.CAPTION, title_tag="caption", allow_label=False, wrap_p=True)
        return
    m = RE_LABEL_SPLIT.match(cap.plain()) if self.split else None
    if m and m.group(2):
        self.labelled(holder, cap, RE_LABEL_SPLIT, E.CAPTION, title_tag="caption", wrap_p=True)
    else:
        pe = _sub(_sub(holder, "caption"), "p")
        self.em.span(pe, cap, E.CAPTION)
```

`fig` は `if node.caption is not None: self.caption(f, node.caption); self.caption_more(f, node.caption_more)`。
`table_wrap` は u3-tables の後の形に合わせ、`if node.caption is not None: self.caption(tw, node.caption); self.caption_more(tw, node.caption_more)` の後に
`self.table(tw, node.table, node.caption)`（u3-tables が引数を足した呼び出し。`all_rows_deleted` の分岐は今のまま）。
`caption_more`（604〜612）は各 `pe` に `self.autonum_mark(pe, p)` を span の前に。`<label>` は fig・table-wrap の caption の前に置ける（DTD で確かめた）。

(f) **後付け・英文要旨の見出し**: `heading_title` を、英文要旨の見出し（301〜303。`self.heading_title(ab, plan.abstract_heading)`）・
`ref_heading`（748〜750）・資料の見出し（757〜759。`app.title` が None のときの空の `<title>` は今のまま `_sub(ap, "title")`）・
`fn_heading`（763〜765）・`backsec` の見出し（781〜783）で使う。章見出し（`sec`。`<label>`）と違い、`<title>` の先頭に生成文字で補う
（ack・ref-list などの `<label>` を J-STAGE が表示するか確かめていないため）。

(g) **注** `fn`（826〜845）を次の形にする（u5 の注の表の 3 行は u5 で足す。ここでは `# u5` の行を書かない）。

```python
el = _sub(fg, "fn", id=fn.fid)
mark = ""
if fn.word_note:
    mark = self.plan.pdf_numbers.get(("fnlist", fn.word_id), self.marks[fn.word_id][1])
elif fn.paras and fn.paras[0].autonum:
    mark = self.autonum(fn.paras[0]).strip()
# tables = list(getattr(fn, "tables", []))        # u5 が足す
for i, p in enumerate(fn.paras):
    # while tables and tables[0][0] == i:          # u5 が足す（最初の注より前の表は k=1。u5 の設計書）
    #     self.table_wrap(_sub(el, "p"), tables.pop(0)[1])
    pe = _sub(el, "p")
    if i == 0 and mark:
        wide = unicodedata.east_asian_width(mark[-1]) in ("F", "W")
        if fn.word_note:
            numbered = bool(p.autonum and self.autonum(p).strip())
            # 1 段落目に自動番号があれば、脚注番号の後ろには必ず空白を補う（「1)1. …」にしない）
            sep = "" if wide or (_starts_with_space(p) and not numbered) else " "
            self.em.gen(pe, mark + sep, "footnote-mark")
            self.autonum_mark(pe, p)               # 1 段落目の自動番号（区切りは docx の文字で決める）
        else:
            sep = "" if _starts_with_space(p) or wide else " "
            self.em.gen(pe, mark + sep, "autonum", p.src)   # 自動番号を注の番号にした（2 回出さない）
    else:
        self.autonum_mark(pe, p)
    self.em.span(pe, p, E.BACKP)
# for _, node in tables:                           # u5 が足す
#     self.table_wrap(_sub(el, "p"), node)
```

Word の注の 1 段落目に自動番号があるときは「1) 1. …」（脚注番号が先）にする。J-STAGE の注は `<p>` の先頭に注の番号を置くので、注を見分ける番号を先頭にする
（Word の表示は自動番号が先だが、まれな形）。docstring の箇条に「2 段落目以降の自動番号も、生成した文字として各 `<p>` の先頭に補う」を足す。

(h) **題目・副題・著者名・所属**: 番号は出さず、`unshown_number` で記録する。呼ぶのは次の 4 か所。

- `multi(self, parent, paras, ctx, what)`（357）に引数 `what` を足し、ループの先頭で `self.unshown_number(p, what)`。
  `title_group` の 4 つの呼び出しで、`"題目"`・`"副題"`・`"翻訳題目"`・`"翻訳副題"` を渡す（本文の言語の題目が「題目」）。
- `person_name`（394）の最初（`nm = …` の前。姓と名を分ける処理と、分けられないときの早い return より前）で `self.unshown_number(p, "著者名")`。
- `contrib_group` の所属の 2 つの枝（aff-alternatives の中の `self.em.span(inst, p, E.AFF)` と、単独の aff の同じ行）の直前で `self.unshown_number(p, "所属")`。

`build()`（112〜131）の `self.newline_warnings()` の後に `self.unshown_warnings()` を呼び、`unshown_numbers` があれば 10 章の警告を 1 行足す。

```python
def unshown_warnings(self):
    if not self.info.unshown_numbers:
        return
    items = "、".join(f"{src}「{head}」（{what}）の「{num}」" for src, num, what, head in self.info.unshown_numbers)
    self.info.warnings.append(UNSHOWN_NUMBERS_MSG.format(items=items))
```

`UNSHOWN_NUMBERS_MSG` は builder.py の定数（`ALL_ROWS_DELETED_MSG` の後ろ）。文は「利用者向けの文」の節。f 文字列の式の中に引用符・バックスラッシュを書かない（`tests/test_syntax.py`）。

### 4. model.py の LostNumber

`LostImage`（258〜270 行目）の後に置く。

```python
@dataclass
class LostNumber:
    """Word の自動番号のある段落で、段落の文字は XML に出したのに番号を出さなかったもの（pipeline.lost_autonums。要対応）。

    番号は docx の文字ではないので、文字の不変性チェックでは見つからない。題目・副題・著者名・所属の段落は、番号を出さないと
    決めているので対象にしない（BuildInfo.unshown_numbers。10 章の警告）。"""
    src: str
    number: str        # Word の番号（ルート2 では PDF に合わせたもの。builder.autonum と同じ）
    location: str      # 段落の場所（plan.locations。なければ領域の名前・Word の脚注など）
    where: str         # 段落の文字を出した XML の要素（td・p など。最初の jx:span の親の要素名）
    text: str = ""     # 段落の文字の冒頭 20 字（Word で探す手がかり）
```

### 5. pipeline.py の守り lost_autonums

- `lost_images` の 293〜294 行目の場所の式を `_place(plan, src)` に出し、`lost_images` と `lost_autonums` の両方で使う（`lost_images` の振る舞いは変えない）。
  `def _place(plan, src): return (plan.locations.get(src) or REGION_JA.get(plan.region.get(src, ""), "") or NOTE_PARTS.get(src[:1], ""))`
- `from .tracking import SPAN` を `from .tracking import GEN, SPAN` に、`from .model import Decision, LostImage` に `LostNumber` を足す。
- `lost_images` の後に次を置く。

```python
def lost_autonums(plan, root, info) -> list:
    """Word の自動番号のある段落のうち、段落の文字を XML に出した（jx:span がある）のに、番号（jx:gen kind autonum、src がその段落）を
    出していないもの（model.LostNumber）。不変性チェックは docx の文字しか見ず、番号は docx の文字ではないので、ここで調べないと黙って落ちる。
    root は最後の組み立ての XML（目印が残っているもの）、info はその BuildInfo。次は調べない: 文字を出していない段落（除外・空白だけ・
    画像だけ・段落記号の削除でつないだ後ろの段落）、番号が空白だけの段落、builder が番号を出さないと決めて記録した段落
    （info.unshown_numbers。題目・副題・著者名・所属）。"""
    shown = {g.get("src") for g in root.iter(GEN) if g.get("kind") == "autonum"}
    skip = {u[0] for u in info.unshown_numbers}
    out, seen = [], set()
    for sp in root.iter(SPAN):
        src = sp.get("src")
        if src in seen:
            continue
        seen.add(src)
        p = plan.paras.get(src)
        if p is None or src in shown or src in skip:
            continue
        number = plan.pdf_numbers.get(("auto", src), p.autonum or "").strip()
        if not number:
            continue
        parent = sp.getparent()
        out.append(LostNumber(src, number, _place(plan, src), parent.tag if parent is not None else "",
                              p.text_only().strip()[:20]))
    return out
```

- `convert`: 458 行目の `lost_images(...)` の直後に `lost_numbers = lost_autonums(plan, root, info)`。単位どうしの点検で決めた並び
  （`lost_images` → `table_problems(root, info)`〈u3-tables〉→ `lost_autonums`）にし、3 つを並べて書く。どれも、AI の再変換・ルート2 の `pdf_numbers` での
  組み立て直し・DTD 不合格の数式の取り消しの後の、最後の `root`・`info`・`plan` を使う。ARCHITECTURE.md の 4 章の段階は版の最後にまとめて直す。
- `Result`（137 行目〜）の `lost_images` の隣に、既定値つきで 2 つ足す（模擬の Result を作る test_app・test_report を壊さない）。

```python
lost_autonums: list = field(default_factory=list)     # Word の自動番号があるのに XML に番号を出さなかった段落（model.LostNumber。要対応）
unshown_numbers: list = field(default_factory=list)   # 番号を出さなかった題目・副題・著者名・所属の段落（BuildInfo.unshown_numbers。10 章）
```

  `Result(...)`（534 行目）に `lost_autonums=lost_numbers, unshown_numbers=list(info.unshown_numbers)` を渡す。`Result.ok` は変えない（要対応は actions で）。
  K1・K2 の中止（u6。0.31.0）は convert がこの前に止まるので、守りは走らない。

### 6. report.py

- `lost_autonum_label(ln)`（`lost_image_label` 174 行目の後）: `f"{ln.src}（{ln.location}）"` に段落の書き出しを足した見出し。
  例「d95（本文 > 3．方法 / 第4要素）「番号付きの質問」の番号「1.」（XML の td）」。location が空なら括弧を省く。
- `lost_autonum_action(r)`（`lost_action` 1082 行目の後）: `lost = getattr(r, "lost_autonums", None) or []`、空なら None。
  `Action(NEEDS_ACTION, "autonum_lost", top=…, checklist=…, box_title=…, box_detail=…, cli=…)`。文は「利用者向けの文」の節。目印 `report.step()` は使わない（画面の操作を指さないため）。
  行は `esc` を通す。
- `actions()`（1649〜1661）の head の並びは、単位どうしの点検で決めたとおり `…, images_action, lost_action, lost_autonum_action, _style_hidden_action, …`。
  0.31.0 の u5 で `lost_autonum_action` の後ろに `_abstract_missing_action` が入り、u4 の `_image_crop_action`・`_image_edits_action` はその後ろに入る。
  u3-tables の `_table_shape_action`（`_dtd_action` の直後）は先に入っている。
- 8 章（1911〜1931）:
  - 説明文（1919〜1922）を次にする（ルート2 の文は「利用者向けの文」の節）。題目の括弧書きは `r.unshown_numbers` があるときだけ足す。
  - 件数の行（`fid.generated` の集計）の後に、`r.lost_autonums` があれば「XML に番号を出せなかった段落（要対応。変換ツールの不具合の可能性）:」と
    `table(["段落", "場所", "Word の番号", "XML の要素", "段落の書き出し"], …)`（どの欄も `esc`。要素名は生のタグの形にしないので `md_tag` は要らない）。
- colab・cli・app・make_notebook には何も足さない（actions だけで冒頭・14 章・Colab の枠・標準エラーに出る）。`app.AppState.REPASTE_KEYS` にも入れない。

## テスト

既存の `make_article`（tests/make_fixtures.py 1088 行目）・`list_item(style, *parts, num_id=6)`（113）・`table`・`cell`（199・212）・`footnote(nid, text, *more)`（1062）・
スタイル表 `S`（73〜77）を使う。新しい docx はテストの中で tmp_path に作る（fixture は増やさない）。各テストで、不変性チェック・`final_ok`・DTD の合格と
`res.lost_autonums == []` を確かめ、さらに共通の補助関数 `assert_autonum_gens(root, plan)`（tests/test_lost_autonums.py に置き、test_article から import）で
「kind autonum の jx:gen は src ごとに 1 つまで」「その gen の親が、同じ src の最初の jx:span の親か、`sec`・`fig`・`table-wrap`・`ref`・`list-item` の子の `label`」
「src の段落の autonum が空でない」を確かめる。組み立てた木は `pipeline.build` を包んで最後に作った root を取る（`u3-autonum/scan.py` と同じやり方）。

### tests/test_article.py

- `test_table_cell_autonum_is_written_as_generated_text`（parametrize: 本文の表・表で組んだ図〈図キャプションの直後のキャプションのない表〉・資料の表）:
  `mf.table([[mf.cell(mf.list_item(S["body"], "番号付きの質問", num_id=7)), mf.cell("回答")], [mf.cell([mf.list_item(S["body"], "二つ目の質問", num_id=7), mf.list_item(S["body"], "三つ目の質問", num_id=7)]), mf.cell("回答")]])`
  を表キャプションの後に置く。期待: td の文字が「1. 番号付きの質問」と「2. 二つ目の質問」＋`<break/>`（tail が「3. 三つ目の質問」）、`("autonum", "1. ")` などが `res.fidelity.generated` にある、`needs_action` は偽。
- `test_autonum_in_other_contexts_is_written`（parametrize で 1 つずつ）: 引用のスタイル（`list_item(S["quote"], …)`）→ `disp-quote/p` の先頭／
  表キャプション（`list_item(S["tab_cap"], "表1　…")`）→ `table-wrap/label` が番号で `caption/p` は「表1　…」のまま／図キャプションの続き → caption の 2 つ目の p の先頭／
  別行数式（list_item に omathpara と tab と「(1)」）→ `disp-formula` の最初の文字／付記・謝辞・注・引用文献の見出し（`list_item(S["notes_head"], …)` など）→ 各 `<title>` の先頭／
  注の 2 段落目（`fn_body` の 2 段落目に num_id=6 の箇条）→ fn の 2 つ目の p の先頭が「• 」／英文要旨の段落（`make_article` の abstract に段落の XML を渡せるようにするか、
  英文要旨の後ろに `list_item(S["abs"], …)` を足す）→ `trans-abstract/p` の先頭／
  Word の脚注の 2 段落目（`mf.footnote(5, "…", mf.list_item("a8", "…", num_id=7))`）→ fn の 2 つ目の p の先頭。
- `test_caption_autonum_label`（parametrize: `split_labels` が真と偽）: 表キャプション「表1　授業の流れ」に自動番号。どちらでも `table-wrap/label` が自動番号で、
  `caption/p` は「表1　授業の流れ」のまま（真でも「表1」を label に分けない）。
- `test_title_author_aff_autonum_is_not_written_and_warned`: document.xml の題目・副題・著者名（姓と名に分けられるものと、空白がなく分けられないもの）・
  所属（和文だけのものと、和英両方がある aff-alternatives のもの）の w:p に numPr を足す小さな補助関数をテストに置く（`u3-autonum/audit.py` の後処理と同じやり方）。
  期待: `article-title`・`surname`・`institution` などの文字に番号がない、`res.warnings` に題目・著者名・所属の番号の警告が 1 行（各段落 ID を含む）、
  `res.unshown_numbers` が記録した段落の数だけある、`lost_autonums` が空、`needs_action` は偽、8 章に「題目・著者名・所属の段落の番号は出していません（10 章）」。
- `test_word_footnote_first_paragraph_autonum`（parametrize: 本文が空白で始まる形・始まらない形）: Word の脚注の 1 段落目に numPr（footnotes.xml の 1 段落目を後から書き換える。
  `review-u3-autonum/fn_first.py` と同じ）。fn の文字が「1) 1. …」で、gen が footnote-mark（src なし）と autonum（src は f の段落）の 1 つずつ。
- `test_hand_note_first_paragraph_autonum_once`: 手で書いた注の 1 段落目の自動番号が 1 回だけ出る（kind autonum の gen が 1 つ）。
- 既存の `test_ack_notes_app_display_elements_and_autonum`（98 行目）・`test_heading_with_autonum_in_back_sections_is_not_joined_to_lists`（157）は期待を変えずに通ること。

### tests/test_lost_autonums.py（新規）

- `test_guard_reports_missing_number`: monkeypatch で `Builder.autonum_mark` を、セルの段落（src を見て）だけ何もしない関数に替え、表のセルの番号の docx を変換。
  期待: `res.lost_autonums` に `LostNumber(src=セルの段落, number="1.", where="td", …)`、`report.actions(res)` に key `autonum_lost`・level 要対応の Action、
  `res.needs_action` が真、レポートの 8 章の表に段落 ID、`cli.main` の終了コードが 1。
- `test_guard_ignores_intentional_paths`: 変換して `lost_autonums` が空になる docx: 自動番号の章見出し（`sec/label`）、本文・付記・資料の箇条、引用文献、番号だけの空の段落
  （`list_item(S["body"], "")`）、番号付きの画像だけの段落、除外した番号付きの段落（structure の除外か AI の set_role exclude）、題目の番号。
- `test_lost_autonums_unit`: `pipeline.lost_autonums` を直接呼ぶ。小さな lxml の木と、`plan.paras`・`plan.pdf_numbers`・`plan.locations`・`plan.region` を持つ簡単な物で、
  `jx:span src=d1` と `jx:gen kind=autonum src=d1` → 空／gen の src なし → [d1]／`plan.paras["d1"].autonum` が `" "` → 空／`info.unshown_numbers` に d1 → 空／
  `plan.pdf_numbers[("auto", "d1")] = "１．"` → number が「１．」。
- `test_all_fixtures_have_no_lost_autonums`: conftest の `ALL_DOCS` をすべて変換し、`lost_autonums` が空で、`assert_autonum_gens` が通る。
- `test_guard_uses_final_tree`: `pipeline.lost_autonums` を包んで渡された root を記録し、`pipeline.build`（または `builder.build`）を包んで最後に作った root と同じ物であることを確かめる。
  原稿は、ルート2 で `pdf_numbers` が付くもの（tests/test_supplement.py の既存の作り方を使う）と、DTD 不合格の数式の取り消しで組み立てをやり直すもの（既存のテストにある作り方があれば使う。なければ省き、その旨を報告する）。

### tests/test_pdfmatch.py（または tests/test_supplement.py）

- `test_cell_autonum_is_not_compared_and_uses_word_form`: 表のセルに番号付きの段落を置いた plan で、`target_paragraphs` にセルの段落が入らず、`check_pdf` の
  number_edits に `("auto", セルの段落)` がない。`plan.pdf_numbers[("auto", セルの段落)] = "１．"` を入れて build すると、td の番号が「１．」（区切りの空白なし）になる
  （`builder.autonum` を通すことの確かめ）。

## 回帰の確かめ（基準との比較で想定する違い）

0.29.0 のコードで取った基準（u1 の (1a) の直後。fixture 15 件・tests/private 10 件のルート1、PDF のある 6 件のルート2）と、u3-tables を入れた 1 つ前の commit とを比べる。

- XML: テストデータ1 の表のセル 5 段落、テストデータ2 の 2 つの docx の表のセル各 11 段落に、自動番号の生成文字（番号＋半角の空白）が増える。ほかの docx（テンプレート・テストデータ3〜5）と fixture 15 件は XML のバイト列が同じ。
- actions の key と level: 変わらない（`autonum_lost` はどれでも鳴らない）。warnings の件数: 変わらない（題目・著者・所属に自動番号のある原稿はない）。
- レポート: 8 章の自動番号の件数と例（テストデータ1・2）、8 章の説明文（すべての docx）。
- 除外の理由ごとの件数・ZIP の一覧と画像のハッシュ・終了コード: 変わらない。ルート2 の違い・番号の直し・補完の確かめ: 変わらない。
- 既存のテスト: 試作では 1298 件すべて通った。並びを確かめるテスト（test_floats 731 行・test_pipeline 867 行・test_links 180 行・test_ai 1396 行・test_notebook 271 行）が落ちないことで、
  fixture で新しい Action が鳴らないことも確かめる。test_colab の全 fixture の HTML の比較などで 8 章の文の変化が当たれば、期待を新しい文に直す（変わる理由を commit に書く）。

## ほかの単位・ルート2・AI 補完・画面との関係

- **u3-tables（先に入れる）**: `table_wrap` の `self.table(tw, node.table, node.caption)` と `BuildInfo.tables` を前提にする。`table_wrap` は caption → caption_more → table の順。
  守りは `lost_images` → `table_problems` → `lost_autonums` の順に並べる。model.py・pipeline.py・builder.py・report.py は u3-tables → u3-autonum → u4 の順に 1 つずつ commit する。
- **u4（後に入れる）**: report.actions の head で `lost_autonum_action` の後ろに u4 の 2 つ（間に 0.31.0 の `_abstract_missing_action`）。u4 のテストは lost の直後に並ぶことを前提にしない。
- **u5（0.31.0）**: 注の節の表は必ず `table_wrap` を通すので、キャプションの自動番号・セルの番号の直しがそのまま効き、守りも調べる。`fn` は 3.(g) の形に表の 3 行を足すだけにする。
  最初の注より前の表は最初の注の 1 段落目の後ろ（k=1）に入れ、注の番号が `<fn>` の先頭に来るようにする（u5 の設計書）。u5 のテストで、注の表のセルに自動番号があるものの `lost_autonums == []` を確かめる。
  守りは文字を出した段落だけを調べるので、除外した段落（理由「位置づけが不明」の要確認など）の番号と二重に知らせない。
- **u6（0.31.0）**: K1・K2 の中止（`StructureConflictError`）は守りの前に止まる。
- **u1**: `numbering.label` が番号を作れなかった（空の）段落は、守りでも見つからない。u1 は子要素の足りない上書きを abstractNum の値に重ねる形で実装し、空の番号を作らない。限界として DESIGN 7 章に書く。
- **ルート2**: `builder.autonum` が `plan.pdf_numbers` を引くので、照合する段落（題目・本文・章節項の見出し・キャプション・注・付記・謝辞・引用文献・英文要旨など）の番号は PDF の形、
  照合しない段落（表のセル・囲み・別行数式）と、付記・謝辞・注・引用文献・資料・英文要旨の見出し（`linker.body_paragraphs` が返さない）の番号は Word の形になる。
  pdfmatch・pdfdocx・`verify_supplement` は変えない（補完の確かめの 4. は `pdf_numbers` の鍵だけを見るので変わらない。試作で 6 回とも合格）。
  キャプション・要旨・注・引用は今も `pdf_numbers` が作られているのに XML に出ていなかったので、直した後はその番号が PDF の形で出る。`LostNumber.number` も `pdf_numbers` を引く。
  pdfdocx が番号の隣の空白を消した段落では、`autonum_mark` が半角の空白を補い直すことがある（番号が半角のとき。fn・付記の今の扱いと同じ）。
- **AI 補完**: set_role で段落の役割が変わると書き出し経路も変わるが、番号を出す処理は書き出し関数ごとなので、どの経路でも守りが調べる（AI の再変換の後の最後の木で）。依頼文は変えない。
- **画面**: Action を 1 つ足すだけ。colab・app・cli・make_notebook に個別の表示を足さない。ノートブックの作り直しは版の最後。

## 利用者向けの文

**要対応 `autonum_lost`**（`report.lost_autonum_action`）。n は件数、行は `lost_autonum_label`。手で番号を補う逃げ道は書かない（ほかの「変換ツールの不具合の可能性」の知らせと同じく、開発者に知らせるだけ）。

- top: `"> **要対応: Word の自動番号が XML に出ていない段落が {n} 件あります（8 章）。** Word では段落の先頭に番号が表示されますが、XML のその段落には番号がありません（変換ツールの不具合の可能性があります）。番号は docx の文字ではないため、文字の不変性チェックでは見つかりません。変換レポートを添えて開発者に知らせてください。\n>\n> - "` + 行（`esc`。行ごとに `> - `）
- checklist: `"- [ ] **XML に出ていない Word の自動番号 {n} 件**（8 章）: 変換レポートを添えて開発者に知らせる（変換ツールの不具合の可能性がある）: d95、d96、…"`（段落 ID を「、」でつなぐ）
- box_title: `"Word の自動番号が XML に出ていない段落が {n} 件あります（要対応）"`
- box_detail: 「Word では段落の先頭に番号が表示されますが、XML のその段落には番号がありません（変換ツールの不具合の可能性があります）。番号は docx の文字ではないため、文字の不変性チェックでは見つかりません。変換レポートを添えて開発者に知らせてください（レポートの冒頭と 8 章）。」＋改行で「・」＋行
- cli: `"要対応: Word の自動番号が XML に出ていない段落 {n} 件（変換ツールの不具合の可能性がある。レポートの冒頭と 8 章）。変換レポートを添えて開発者に知らせること。\n"` ＋ `"  d95: 「1.」…"` の行

コマンドラインの終了コードは `needs_action` で 1。中止（2）にはしない（XML の文字は docx と一致している）。

**10 章の警告**（`UNSHOWN_NUMBERS_MSG`）:
「題目・著者名・所属の段落に、Word の自動番号があります（{items}）。J-STAGE の書誌に番号が入らないよう、XML には番号を出していません（Word の表示と違います）。
番号が題目・著者名・所属の一部なら、Word で番号を文字として打ち込んでから変換し直してください。番号が要らなければ、このままでかまいません。」
（items の例: `d3「…」（題目）の「1.」、d5「…」（著者名）の「(1)」`）

**8 章の説明文**:
「Word の自動段落番号や脚注番号は docx の文字ではなく Word が表示時に作るものです。表示どおりの文字を XML に出力しました{word_marks}
{（題目・著者名・所属の段落の番号は出していません。10 章）← unshown_numbers があるときだけ}。
「docx から作り、出版版 PDF で補う」では、章・節・項の見出し・本文・キャプション・注・付記・謝辞・引用文献・英文要旨の段落の自動番号と脚注番号の全角・半角と字形を
PDF に合わせています（表のセル・囲み・別行数式の段落と、付記・謝辞・注・引用文献・資料・英文要旨の見出しの番号は PDF と照合しないので、Word の形のままです。13 章）。
docx に注の見出しがない場合（Word の脚注機能で書かれた注など）は、見出し（設定 fn_title）を補いました。」

8 章の表の前の行: 「XML に番号を出せなかった段落（要対応。変換ツールの不具合の可能性）:」

## 文書の更新（CLAUDE.md は案だけ）

DEVELOPMENT.md の原則・ARCHITECTURE.md・USAGE.md・REVIEW_2026-11.md は、版の最後に 1 人（Opus）がまとめて直す。この単位の実装者は次の案を commit の説明に書いて渡す
（builder.py・tracking.py・report.py の docstring と文は、この単位の実装者が直す）。

- **docs/DESIGN.md**
  - 3 章の処理の流れ（35 行目の 9. の後）に「**自動番号の出力漏れの検出**（`pipeline.lost_autonums`）: 自動番号のある段落で、文字を XML に出したのに番号を出していないものを調べる（4.3）」を足し、後ろの番号を送る。
  - 4.3 の A7 の段落（175 行目）を「Word の自動番号はどの場所でも生成文字（`jx:gen kind="autonum" src="段落 ID"`）で出す」形に書き直し、場所ごとの表を置く:
    章節項の見出し・図表のキャプションは `<label>`（キャプションの自動番号は `split_labels` にかかわらず `<label>`。章見出しと同じ。キャプションの文字は分けない）、
    本文・付記・謝辞・資料・囲みの箇条と引用文献は `<label>`、`<p>`（英文要旨・後付けの見出しの役割の段落）・`td`（2 段落目以降は `<break/>` の後ろ）・`disp-quote/p`・
    `disp-formula`・後付けと英文要旨の見出しの `<title>` は先頭、注は各 `<p>` の先頭（Word の注の 1 段落目は「1) 1. …」）、題目・副題・著者名・所属は出さず 10 章の警告。
    185 行目の `lost_images` の段落の後に、守り `lost_autonums` の 1 段落（調べないもの・要対応・Result の欄）。
  - 7 章（1136 行目の自動番号の項）に限界を足す: 画像だけの段落・文字のない番号だけの段落の番号は XML に出ず守りにも見えない／`numbering.py` が番号を作れなかった（空の）段落は守りでも見つからない／
    `numbering.py` は段の書式の `w:vanish` を見ないので、Word で隠した番号も XML に出る／ルート2 で照合しない段落と後付けの見出しの番号は Word の形のまま／
    自動番号で「図1」を付けたキャプションは、文字に番号がないので本文の「図1」の参照をリンクできない。
- **docs/DEVELOPMENT.md**: 守るべき原則 3 に「Word の自動番号が XML に出なかった段落は `pipeline.lost_autonums()` が検出し、要対応 `autonum_lost` で知らせる（`jx:gen` の kind autonum には段落 ID の src を付ける）」。
  43 行目の「ルート2 で Word の番号（自動番号・脚注番号）の全角・半角を PDF に合わせるときは」を「PDF と照合する段落の Word の番号…」に絞る。テストの節に test_lost_autonums.py。
- **docs/ARCHITECTURE.md**: 4 章の pipeline.convert の段階（守り 3 つの並び）、Result の `lost_autonums`・`unshown_numbers`、`model.LostNumber`、builder の行（`autonum_mark`・`caption`・`heading_title`・`unshown_number`）、
  report.py の行（actions の並びに `lost_autonum_action`〈key `autonum_lost`〉）、用語「生成文字」に jx:gen の src。
- **docs/USAGE.md**: 知らせの一覧（「たとえば次のものです」）に `autonum_lost` を足す。
- **docs/REVIEW_2026-11.md**: 表のセルほかの自動番号の出力漏れを 0.30.0 で直したと記録。新しい未修正の項目として「numbering.py が段の書式の w:vanish を見ない」を足す。
- **CLAUDE.md（実装者は直さない。利用者の承認を待つ案）**:
  - 「不変性チェックは文字しか見ない。XML に入らなかった画像は `pipeline.lost_images()` が検出し、要対応として知らせる。」の後に
    「Word の自動番号が XML に出なかった段落は `pipeline.lost_autonums()` が検出し、要対応として知らせる。」を足す（u3-tables の `table_problems` の文と合わせて 1 つの案にする）。
  - 「Word が付ける番号（自動番号・脚注番号）は docx の文字ではないので、変換のときに全角・半角と字形を PDF に合わせる。」を
    「…PDF と照合する段落では、変換のときに全角・半角と字形を PDF に合わせる（表のセル・囲み・別行数式の段落と後付けの見出しの番号は Word の形のまま）。」にする。

## 文書とコードの食い違い

- `builder.paragraph_or_formula` の docstring「自動番号のある段落が <p> になるのは、後付け（付記・謝辞・資料）の中の見出しの役割の段落だけ」「本文・英文要旨の <p> は変えない」:
  英文要旨の段落・引用の段落・注の 2 段落目以降・表のセルの段落も自動番号のまま番号なしで出ている。直す（3.(b)）。
- report.py 8 章の「表示どおりの文字を XML に出力しました」: 表のセル・キャプション・要旨・見出し・注の続きなどの番号は出ていない。この単位で直すと正しくなる。
- report.py 8 章の「『docx から作り、出版版 PDF で補う』では、自動番号・脚注番号の全角・半角と字形を PDF に合わせています」、CLAUDE.md の同じ文、DEVELOPMENT.md 43 行目:
  照合しない段落（表のセル・囲み・別行数式）と後付け・英文要旨の見出しの番号は合わせない。文書の側を直す（report.py はこの単位、DEVELOPMENT.md は版の最後、CLAUDE.md は案）。
- `pdfmatch.target_paragraphs` の docstring（656 行目）の「見出し」: `linker.body_paragraphs` は付記・謝辞の見出し・`ref_heading`・`fn_heading`・`abstract_heading` を返さないので、これらは照合されない
  （コードを読んで確かめた。PDF での実例は確かめていない）。「章・節・項の見出し」と書き分ける（この単位の実装者が docstring だけ直す。pdfmatch のコードは変えない）。
- DESIGN.md 4.3 の A7 の段落（175 行目）と 7 章の自動番号の項（1136 行目）: 付記・謝辞・資料の番号だけを書き、ほかの場所の番号が落ちることにも限界にも触れていない。書き直す。
- tracking.py の jx:gen の説明（kind だけ）: 直した後は src を持つ。合わせて直す（今は食い違いではない）。
- 設計の案で「DESIGN.md の 2 章の処理の流れ」「5 章（検証）」としていた所は、実際は 3 章（処理の流れ。35 行目）と 4.3。この設計書では正しい章で書いた。

## 新しく見つけた問題（この単位で直すもの／直さず REVIEW に記録するもの）

この単位で直すもの:

- 注の 2 段落目以降と Word の脚注の 2 段落目の自動番号が出ない（3.(g)）。
- Word の脚注の 1 段落目に自動番号があり、本文が空白で始まると「1)1. …」になる（試作の形。3.(g) の区切りで直す）。
- 題目・副題・著者名・所属の自動番号が黙って落ちる（出さないまま 10 章の警告にする。3.(h)）。

直さず記録するもの:

- 自動番号「1.」の形の注番号は `RE_NOTE_MARK` に合わず、2 つ目以降の注が 1 つ目の注の続きの段落になる（K8。既存の項目）。この単位で番号は出るが、注は分かれない。
- 画像だけの段落・文字のない番号だけの段落（表のセルの中も）の番号は出ず、守りにも見えない（DESIGN 7 章の限界）。
- `numbering.py` が段の書式の `w:vanish` を見ない（REVIEW に新しい項目。今のデータでは 0 件）。
- 自動番号で「図1」「表1」を付けたキャプションは、`structure.caption_label`・linker が番号を読めず、本文の参照をリンクできない可能性（確かめていない。DESIGN 7 章）。
- `colab.lost_images_box` など、actions を経ない個別の枠の関数が残っている（REVIEW の食い違い 29。この単位では触らない）。

## 未決のこと（利用者の返事待ち／実装のときに確かめること）

利用者の返事待ち:

- CLAUDE.md の 2 つの文の案（「文書の更新」の節）。版の最後に、ほかの単位の案とまとめて見せる。
- 後付け・英文要旨の見出しの番号を `<title>` の先頭に置いた形が J-STAGE で表示されるか（試験登載で確かめる）。表示に問題がなければこのまま。`<label>` に変える判断は利用者か Opus。
- J-STAGE で `<fig>`・`<table-wrap>` の自動番号の `<label>` が表示されるか（`split_labels` が偽の本誌では今までなかった出力。実際の原稿・fixture では 0 件）。

実装のときに確かめること:

- `make_article` の英文要旨に段落の XML を渡せるか（渡せなければ引数を足す。既定の出力は変えない）。
- `test_guard_uses_final_tree` に使える、DTD 不合格の数式の取り消しで組み立てをやり直す原稿の作り方が既存のテストにあるか。
- u3-tables の後の `table_wrap` の形（`self.table` の引数）が、この設計書の 3.(e) と合っているか。
- test_colab などで 8 章の文を固定しているテストがあるか（あれば期待を直す）。

## 点検の指摘の反映表

| 重さ | 題 | 反映した節 |
|---|---|---|
| major | 守り autonum_lost の文に「XML に手で番号を補う」逃げ道が残っている | 利用者向けの文（top・checklist・box_detail・cli から消した） |
| minor | 題目・著者名・所属の番号の 10 章の警告で勧める操作が XML を変えない | 利用者向けの文（10 章の警告） |
| minor | Word の脚注の 1 段落目に自動番号があると「1)1. …」になる | 直し方 3.(g)、テスト（`test_word_footnote_first_paragraph_autonum`） |
| minor | 8 章のルート2 の文と DEVELOPMENT.md が照合しない見出しを挙げ漏らしている | 利用者向けの文（8 章）、文書の更新（DEVELOPMENT.md 43 行目） |
| minor | 守りが番号の二重出力・置き場所の誤りを見逃す | テスト（`assert_autonum_gens`。利用者向けの知らせにはしない） |
| minor | unshown_numbers を記録する場所の書き方があいまい | 直し方 2（`unshown_number`）・3.(h)（4 か所）、テスト（分けられない著者名・aff-alternatives） |
| minor | キャプションに自動番号があると split_labels が偽でも <label> を作る | 直し方 3.(e)（このまま <label>）、文書の更新（DESIGN 4.3 に明記）、テスト（`test_caption_autonum_label`） |
| minor | Word で隠した番号を出してしまう限界が書かれていない | 文書の更新（DESIGN 7 章・REVIEW）、新しく見つけた問題 |
| minor | u3-tables・u5 と同じ関数を直すので、まとめ方を決めておく | 直し方 3.(e)・3.(g)、ほかの単位との関係（u3-tables → u3-autonum → u5、u5 の表は k=1） |
| minor | ARCHITECTURE.md の report.py の行と、8 章の固定の文 | 文書の更新（ARCHITECTURE の report.py の行）、直し方 5（`Result.unshown_numbers`）・6、利用者向けの文（題目の括弧書きは該当があるときだけ） |
