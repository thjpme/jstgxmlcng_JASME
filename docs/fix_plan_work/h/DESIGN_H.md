# 単位 H（0.27.0）の設計: リンクの誤検出と AI 依頼文の保守（D2・M5・U4・U5）

作成: 設計の担当（2026-11-01）。基準は main の 4533222（0.26.0）。正本は docs/FIX_PLAN.md の「H」の節と付録の D2・M5・U4・U5。
試作は `scratchpad/h/design/src/jasme_jats/linker.py`（D2・M5 だけ。差分は `scratchpad/h/design/proto_linker.diff`）、
fixture の試作は `scratchpad/h/design/tools/proto_fixtures.py`、計測のスクリプトは `scratchpad/h/design/tools/`。
（以下、`scratchpad` は `/tmp/claude-0/-home-user-jstgxmlcng-JASME/d6c16a4c-c8c0-592a-be84-ec12faff29b8/scratchpad` のこと。）

## 0. まとめ役に先に確かめてほしいこと（正本どうしの食い違い）

1. **U4 の英文 1 語の氏名（いちばん大きい食い違い）**。FIX_PLAN の H の節（U4）と付録 U4 の (3) は「英文を除く処理を build_request に置き、
   d12 の行は依頼文に出ない」と書くが、FIX_PLAN の「決定事項」の **17（2026-10-14 の利用者の回答）は「英文 1 語の氏名も、今までどおり
   AI 依頼文に載せる。あわせて、英文の氏名を姓と名に分けられなかったことを警告する」**。H の節は回答の前に書かれたもので、決定事項に合わせて
   直されていない（同じ節の D2 の「数が多い論文での行のまとめ方は、利用者が決める」も、決定事項 15 ですでに決まっている）。
   作業の指示（まとめ役の暫定の判断）は「英文 1 語の氏名を外すことは利用者に未確認なので、H の節どおり暫定で外す」だが、決定事項 17 は
   利用者の回答として記録されている。**この設計は決定事項 17 に従う（外さない・警告を足す）**。まとめ役が H の節どおりにするなら、
   build_request の 1 行（4.3 の「別案」）とテスト 1 件の期待を逆にするだけで済むように書いた。
2. **決定事項 15・16 はすでに利用者が決めている**（作業の指示は「未確認・暫定」としているが、FIX_PLAN の決定事項に回答がある）。
   15: 論文ごとに注番号の書き方を判定し、**明らかな指数（直前が英数字・演算の記号）は段落ごとに 1 行にまとめて記録する**。
   16: FLOAT_REF_OK_BEFORE は「掲・至・及」のまま。→ この設計は 15・16 をそのまま実装する（暫定ではない）。
   決めていないのは「指数でない、番号だけの上付きの数字（『1)』の書き方の論文の『²』）の記録の件数」だけで、これは 1 件ずつの記録にした（2.6）。
3. FIX_PLAN の「同じファイルを触る順」は ai_assist.py に「H（… D2 の SYSTEM_PROMPT の 1 文）」と書くが、H の節にも付録にもない。
   SYSTEM_PROMPT は手動モードの AI依頼文.txt の先頭に入るので、足すと golden の 23 件すべての依頼文が変わる。記録の文面に link_note の
   text と occurrence を書くので AI には足りる。**足さない**（却下。5 章）。

## 1. リンクの今の形（0.26.0）

### 1.1 Linker.run の順序

| 順 | 処理 | 対象の段落（`body_paragraphs` の文脈） | 記録 |
|---|---|---|---|
| 1 | `label_formulas` | 別行数式の番号 → `LinkSpec(kind="label")` | なし |
| 2 | `word_hyperlinks` | すべて（引用文献では表示が URL そのものなら外す） | なし（`count["word"]`） |
| 3 | `urls` | すべて（DOI・URL） | `note("url", …)`（http:// を補ったとき） |
| 4 | `float_refs`（図・表） | 引用文献（ref）以外。図・表のキャプションの段落は除く | 図表がなければ `unresolved`（`("fig"\|"table", src, m.group(0), "図N に対応する図が見つからない")`） |
| 5 | `eq_refs` | ref・formula 以外 | なし |
| 6 | `fn_marks`（上付き） | ref・fn 以外（`fn_ids` が空なら何もしない） | 注がなければ `unresolved`（`("fn", src, m.group(0), "上付きの「…」に対応する注が見つからない")`） |
| 7 | `fn_marks_plain`（本文の大きさの「（注1）」） | ref・fn 以外 | リンクしたら `note("note", src, "上付きでない注番号「…」を注 fnN にリンクした")` |
| 8 | `refparse.link_citations` | 引用文献（著者・年、番号方式） | `unresolved`（bibr）・Decision（citation） |

- `body_paragraphs` の文脈: body / title（節見出し）/ caption / cell（表のセル・`plan.cell_paras`・**F の囲み BoxNode の段落**）/ formula /
  abstract / back（付記・謝辞・資料）/ fn / ref。囲みの段落は `walk(node.children, "cell")` で cell になり、上付きの規則も本文と同じに当たる。
- `fn_ids = {fn.number: fn.fid}`（手で書いた注だけ。Word の脚注・文末脚注は除く）。`fig_ids`・`tab_ids` は番号 → F1・T1。

### 1.2 個別の関数

| 関数 | 今の形 | H で直すか |
|---|---|---|
| `fn_marks` | 上付きのテキストのアトムが続く範囲（リンクなし）を 1 つの文字列にし、`(?:注[\s　]*)?[(（]?[\s　]*(NUM)[\s　]*[)）]?` を finditer。空白だけの一致を除き、番号の注があればリンク、なければ unresolved。**数字だけの上付きもすべて注番号**（D2 の原因）。「註」は認めない | 直す（D2） |
| `fn_marks_plain` | `RE_FN_PLAIN`（「（注1）」「注1)」。「注」の前が漢字なら不可）を finditer。上付きにかかる一致は飛ばす（`_has_sup`）。リンクしたら Decision | 変えない |
| `_has_sup` | 範囲に sup のテキストのアトムがあるか | 変えない |
| `float_refs` | `RE_FIGREF`・`RE_TABREF` を finditer。先頭の番号（`m.group(2)`）と並び（`m.group(3)` の数字）をそれぞれ `_link_num`。**直前の文字を見ない**（M5 の原因。「地図1」「図表1」「発表1回目」「付表1」） | 直す（M5） |
| `_link_num` | 番号の図表があれば `apply_span`、なければ unresolved | 変えない |
| `note` | `plan.decide("mechanical", category, src, msg)`（applied は既定の True） | `applied` 引数を足す |
| `RE_FN_MARK` | 定義だけで、どこからも使われていない（行頭・行末に固定した版） | 変えない（食い違いとして報告） |

### 1.3 記録が出る場所

- `plan.decisions`（Decision）→ レポート 4 章「機械処理による推定」（番号・種類〈`CAT_JA`: note=注、figure=図、table=表〉・場所・内容）。
  AI 依頼文では `build_request` の「# 機械処理で解決できなかった箇所」に、category が style・formula・figure・table・note・box のものだけ
  `- [src] 推定: {message}` の 1 行で載る。**report.actions() は Decision を見ない**（要対応・要確認にならない。単位 D の方針どおり）。
- `linker.unresolved` → レポート 3 章（`pipeline` の `unresolved_after`）と AI 依頼文の同じ節に `- [src] fn: 「raw」 … detail`。
- AI 依頼文の段落一覧は `para_view_with_links`（リンク済みの箇所は «文字→ID»）で、**上付きかどうかは示さない**。だから記録の文面に
  link_note の text（数字だけ）と occurrence（段落の中で何回目か）を書く。AI の回答の検証は `find_in_para(p, text, occurrence)`
  （`plain.find(text, start + 1)` を繰り返す数え方。重なる一致も数える）で、既にリンクのある範囲は `apply_span` が断る。

### 1.4 「姓と名の区切りがない氏名」（U4 の今の形）

- `builder.Builder.person_name` は、分ける位置が決まらないと `info.notes.append(("name", src, "氏名「{text.strip()}」に姓と名の区切り（空白）がないため、全体を姓（surname）として出力"))`。
  和文（eastern, ja）・英文（western, en）のどちらでも同じ。
- `pipeline.convert` の AI の節が `msg.split("「", 1)[-1].split("」", 1)[0]` で文言から氏名を切り出し、`build_request(plan, linker, info.exclusions, unsplit)`
  に (src, text) の 2 つ組で渡す。`build_request` は全件を `- [src] 姓と名の区切りがない氏名: 「text」` にする（英文も載る）。
- AI の split_name の検証（`apply_ops`）は、英文（lang != ja）を断り、和文は `text.strip(" 　\t") == 姓 + 名` を求める。
  文言の `text.strip()`（改行なども除く）とは空白の扱いが違う（U4 で `strip(' 　\t')` にそろえる）。

## 2. D2: 上付きの指数・単位が注へのリンクになる（linker.py だけ）

### 2.1 定数（linker.py の冒頭。RE_FN_PLAIN の後ろ）

```python
# 上付きの注番号（上付きの続きの中で finditer する。「1),2)」のように並ぶものも。「註」も認める）
RE_SUP_FN = re.compile(rf"(?:[注註][\s　]*)?[(（]?[\s　]*({NUM})[\s　]*[)）]?")
# 数字と区切りだけの続き（「1-3」「1, 2」「1,2)」「注1・2」）。続き全体の前後で指数かどうかを決める（fullmatch で使う）
RE_SUP_LIST = re.compile(rf"[\s　]*(?:[注註][\s　]*)?[(（]?[\s　]*{NUM}"
                         rf"(?:[\s　]*[,，、・\-－–‐~～〜][\s　]*{NUM})+[\s　]*[)）]?[\s　]*")
SUP_SIGNS = "-−－‐–+＋±⁻⁺"            # 上付きの続きの先頭がこれなら指数（m s⁻¹ を Word で「s」＋上付き「-1」と書いたもの）
OPERATORS = "+-−－＋±×÷=＝<>＜＞≦≧≤≥^*/／"
RE_EXP_BEFORE = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ0-9０-９α-ωΑ-Ω]")   # 直前がこれなら指数・単位（cm²・x²・10³・π²）
```

`RE_SUP_FN` は FIX_PLAN の式そのもの（今の fn_marks の式に「註」を足しただけ）。`RE_FN_MARK`（未使用）は消さない。

### 2.2 上付きの続きと、候補の種類

- `_sup_runs(p) -> [(s, e, text)]`（モジュール関数）: sup のテキストのアトムでリンクのないものが**plain の上で隣り合って**続く範囲。
  今の fn_marks の内側のループと同じ区切り（リンクのあるアトム・数式・画像で切れる）。plain の位置は `atom_offsets` で求め、
  リンクを付けても plain は変わらないので、fn_marks の最初に 1 回だけ求めればよい（今のようにアトムを数え直して進める必要はない）。
- `_exponent_like(plain, s, e, text) -> bool`: 続き `plain[s:e]` が指数・単位の形か。次のどれかなら真。
  1. 続きの先頭（前の空白を除く）が `SUP_SIGNS`（符号で始まる続き。⁻¹）
  2. 続きの直前の 1 文字が `RE_EXP_BEFORE`（英字・数字〈全角も〉・ギリシャ文字。cm²・x²・10³）か `OPERATORS`
  3. 続きの直後の 1 文字が `OPERATORS`（(a+b)²+c の ²）
  直前・直後の文字は空白を飛ばさない（「3 cm」＋²の直前は m）。直前が OBJ（数式・画像・Word の注の参照）・漢字・かな・句読点・
  閉じ括弧（「（試験, 2024）²」）なら指数とみなさない。
- `_sup_marks(plain, s, e, text) -> [(ms, me, 番号, 種類)]`（モジュール関数）: 続きの中の `RE_SUP_FN` の一致（空白だけを除く）ごとに種類を決める。
  - 前もって: `sign`（規則 1）、`exp = _exponent_like(...)`、`note_before`（`plain[:s]` が `[注註][\s　]*$` で終わる）、
    `tail_close`（直後の本文の 1 文字が「)」「）」で、`exp` が偽で、続きが数字〈と空白〉で終わる）。
  - `_strong_mark(g)`: 一致の文字（前後の空白を除く）が「注・註」で始まる、または「)」「）」で終わる（FIX_PLAN の定義）。
  - **数字と区切りだけの続き**（`RE_SUP_LIST.fullmatch(text)`）: 続き全体で 1 つの種類にする。
    sign → exponent、`_strong_mark(text)` か tail_close → strong、note_before → after_note、exp → exponent、それ以外 → bare。
  - それ以外の続き: 一致ごとに、sign → exponent、`_strong_mark(一致)`、または「最後の一致で tail_close」→ strong、note_before → after_note、
    exp → exponent、それ以外 → bare。
  - 優先は **sign > strong > after_note > exponent > bare**。符号で始まる続きは「−1)」でも指数（注番号は符号で始まらない）。
  - リンクの範囲は一致の前後の空白を除く（`_trim_span`。「1, 2」の「 2」の空白を xref に入れない。今は入る。fixture と td1〜3 には
    この形がないので出力は変わらない）。

### 2.3 論文ごとの書き方 bare_notes（FIX_PLAN の bare_notes）

- `Linker.__init__` で `self.bare_notes = True`（今までどおりの動き。run を通らずに fn_marks を呼んでも同じ）。
- `Linker.run` の中、`fn_ids` を作った直後・段落のループの前に `if fn_ids: self.bare_notes = self.note_style(paras)`。
- `Linker.note_style(paras) -> bool`: ref・fn 以外の段落（fn_marks と同じ対象。囲みの cell・キャプション・表のセル・要旨・付記も入る）の
  すべての上付きの続きを `_sup_marks` にかけ、**strong が 1 つでもあれば False**（「1)」「注1」の書き方の論文）、なければ True（番号だけの論文）。
  - 「上付きの外の文字でも補う」= 上付きの「1」＋本文の「)」（tail_close）も strong に数える。
  - after_note（直前が「注」の上付きの数字）は数えない（FIX_PLAN「書き方の判定には使わない」）。exponent も数えない。
  - 1 件でも strong があれば決まる（決定事項 15 の「1 つでもあれば」）。件数のしきい値は置かない。

### 2.4 fn_marks（書き直す）

```
fn_marks(p, fn_ids):
    if not fn_ids: return
    plain = p.plain(); exps = []
    for s, e, text in _sup_runs(p):
        for ms, me, n, kind in _sup_marks(plain, s, e, text):
            rid = fn_ids.get(n); raw = plain[ms:me]
            if rid is None:
                if kind != "exponent": unresolved に ("fn", src, raw, f"上付きの「{raw}」に対応する注が見つからない")（今と同じ文言）
                continue
            if kind in (strong, after_note) or (kind == bare and self.bare_notes):
                apply_span(...xref fn rid...) → count["fn"] += 1; continue
            # リンクしない: 記録（その番号の注があるときだけ）
            digit = 一致の数字（RE_SUP_FN.match(plain, ms).group(1) の位置の文字。text は m.group(1)）
            k = occurrence_at(p, 数字の開始位置, digit)
            exponent → exps に「digit」（k 回目）を足す / bare（「1)」の論文）→ 1 件ずつ記録（2.6）
    exps があれば、段落ごとに 1 件だけ記録（2.6）
```

- 注がない番号の扱い: リンク候補（strong・after_note・bare）は今までどおり unresolved（bare は「1)」の論文でも出す。今までの 3 章の
  知らせを減らさないため）。**exponent は知らせない**（今は cm² の「2」に注 2 がないと「対応する注が見つからない」と 3 章と依頼文に
  出ていた。これが消えるのは D2 の意図した変化）。
- `occurrence_at(p, pos, text) -> int`（モジュール関数。find_in_para と同じ数え方で、pos から始まる text が段落の中で何回目か）:
  `start = -1; k = 0; while True: start = plain.find(text, start + 1); if start < 0 or start > pos: return max(k, 1); k += 1; if start == pos: return k`。
- `fn_marks_plain` は変えない（本文の大きさの「（注1）」。上付きにかかる一致は今までどおり fn_marks に任せる）。「注」＋上付き「1」＋本文「)」は
  RE_FN_PLAIN に当たるが `_has_sup` で飛ばされ、fn_marks が「1」を（tail_close で strong として）リンクする。

### 2.5 囲み（F の BoxNode）と他の文脈

- 囲みの段落は body_paragraphs で cell として来るので、note_style と fn_marks の対象に入る（本文と同じ規則）。試作で、囲みの中の「9 cm²」は
  リンクされず記録され、「である¹⁾」は fn1 にリンクされることを確かめた（`scratchpad/h/design/tools/box_case.py`）。
- 題目・著者などの冒頭の段落は body_paragraphs に入らない（今までどおり）。Word の脚注・文末脚注の参照（fnref のアトム）は対象外。
- ルート2: pdfdocx は linker を使って直した docx の構造を比べる（`_structure`・`_lost`）。bare_notes は論文全体で決まるので、ある段落の直し
  （上付きの数字の後ろに PDF の「)」を足すなど）で別の段落の注のリンクが消えることがありうる。pdfdocx._lost が消えた注のリンクを見つけ、
  すべての注の番号を守り（`NOTE_REASON`）、それでも崩れればリンクのある段落全体を直さず、守る範囲が広がらなければ何も直さない、の順で
  守る（pdfdocx は触らない）。リンクが**増える**直しは _lost が見ないので、ルート2 で注のリンクが増えることはある（XML は直した docx の
  文字のまま。DESIGN 4.4 の文言を「元のリンクが失われないか」に直す。6 章）。td1〜3 のルート2 では変わらないことを確かめた（7 章）。

### 2.6 記録（Decision）の条件と文言（applied=False・category "note"）

`Linker.note(category, src, msg, applied=True)` に `applied` を足し、`plan.decide(..., applied=applied)` に渡す（「…しなかった」記録は
既存の structure の記録と同じく applied=False）。actions() には入らない。記録は**その番号の注があるときだけ**（M5 と同じ）。件数の上限は置かない
（決定事項 15 は「段落ごとに 1 行にまとめる」までで、上限は決めていない。指数の多い論文でも、注の番号以下の指数がある段落の数まで）。

- 明らかな指数・単位（exponent）。**段落ごとに 1 件**（決定事項 15）:
  `上付きの数字 「2」（1 回目）、「3」（1 回目） は、指数・単位（cm²・x² などの形）とみなして注にリンクしなかった（回目は、段落の中で同じ数字が現れる順）。注番号なら、AI による補完の link_note（text は数字、occurrence はその回目）か、XML の手直しでリンクを足す`
- 「1)」の書き方の論文の、番号だけの上付きの数字（bare）。**1 件ずつ**（指数ではなく、注番号の書き損じかもしれないため。決定事項 15 の対象外。暫定）:
  `上付きの数字「2」（段落の中で 2 回目の「2」）は、番号だけの形のため注 fn2 にリンクしなかった（この論文の注番号は「1)」「注1」のような形）。注番号なら、AI による補完の link_note（text「2」、occurrence 2）か、XML の手直しでリンクを足す`
- 文面の text は `m.group(1)`（数字だけ。空白を含まない）、回数は `occurrence_at(p, 数字の開始位置, 数字)`。どちらも試作で、その text と occurrence の
  link_note を手動モードで貼り戻すと採用されることを確かめた（`tools/run_ai.py`。cm² の「2」、f(x²) の後ろの番号だけの「2」とも accepted）。
- 実装の担当は文言を短くしてよいが、「何が起きたか（注にリンクしなかった）・どこか（場所の欄。Decision.location）・どうするか（AI の link_note の
  text と occurrence、または XML の手直し）」は残す。

### 2.7 例（試作の結果。sample_links / sample_links_bare）

| 段落（架空） | 0.26.0 | H |
|---|---|---|
| 「1)」の論文: 「面積は 3 cm」＋²＋「である」＋「1)」 | ² → fn2、1) → fn1 | 1) → fn1 だけ（² は指数の記録） |
| 「式 x」＋²＋「+y」＋²＋…＋「1,2)」 | ²²（fn2）・1・2) | 1 → fn1、2) → fn2（²² は 1 件の記録に 2 つ） |
| 「m s」＋「−1」＋…＋「1-3)」 | −1 の 1 → fn1、1・3) | 1 → fn1、3) → fn3（−1 は指数の記録） |
| ＋「註1」、＋「注3」 | 註1 の「1」だけ → fn1、注3 → fn3 | 註1 → fn1（「註」ごと）、注3 → fn3 |
| ＋「1」＋本文「)」／本文「注」＋「1」 | fn1・fn1 | fn1・fn1（strong・after_note） |
| 「f(x」＋²＋「)」／「番号だけの」＋² | fn2・fn2 | どちらもリンクなし（前は指数の記録、後は 1 件の記録） |
| 番号だけの論文: 「主張である」＋¹、「（試験, 2024）」＋² | fn1・fn2 | fn1・fn2 |
| 「4 m」＋² | fn2 | リンクなし（指数の記録） |
| 「1-3」、「1, 2」 | 1・3、1・「 2」 | 1・3、1・2（空白を入れない） |

note_style: sample_links は False（「1)」がある）、sample_links_bare は True。

## 3. M5: 語の中の「図1」「表1」が図・表へのリンクになる（linker.py だけ）

### 3.1 定数

```python
# 「図1」「表1」の直前に来てよい漢字（前掲図1・乃至図2・及び表1）。ほかの漢字の直後は語の一部（地図1・付表1・発表1回目）
FLOAT_REF_OK_BEFORE = "掲至及"
RE_KANJI = re.compile(r"[㐀-鿿々]")     # RE_FN_PLAIN の「注」の前の漢字と同じ範囲
```

### 3.2 float_refs（書き直す）

```
plain = p.plain(); pos = 0
while (m := regex.search(plain, pos)) is not None:
    n = fw_int(m.group(2)); s, e = m.start(1), m.end(2); prev = plain[s-1] if s else ""
    if RE_KANJI.match(prev) and prev not in FLOAT_REF_OK_BEFORE:      # 語の一部
        if n in ids: 記録（3.3）
        pos = e            # 先頭の番号の直後から探し直す（tail ごと飛ばさない）
        continue
    今までどおり: 先頭の番号と tail の数字を _link_num
    pos = m.end()
```

- 語の一部でない一致の扱いは finditer と同じ（次の探索は m.end() から）なので、今リンクされているものは変わらない。
- `pos = m.end(2)` にする理由: 「図表1と表1」で RE_TABREF の一致は「表1と表1」（tail「と表1」）で、tail ごと飛ばすと後ろの正しい「表1」まで
  落ちる。先頭の番号の直後から探し直すと「表1」（直前は「と」）が T1 にリンクされる。「地図1、図2」も同じく図2 が F2 になる。
  「地図1、2」は探し直しても「、2」に「図」がないので、どちらもリンクされない（記録は 1 件）。
- 直前が漢字かだけを見る。かな・カタカナ・英字・括弧・句読点・行頭・OBJ の直後は今までどおりリンク（「ヒストグラム図1」もリンク）。
  英語の「Figure 1」「Table 1」は直前が漢字になることがまれなので、同じ規則のまま。
- `eq_refs`（式の参照）は変えない（「数式(1)」の「式(1)」は今までどおりリンク。M5 の対象外）。

### 3.3 記録（applied=False・category は図が "figure"、表が "table"）

先頭の番号の図・表があるときだけ（tail の数字は記録しない。なければ unresolved にもしない。今は「地図5」に図5 がないと unresolved だった）:

`「図1」は、直前の「地」と続く語の一部（地図1・付表1 など）とみなし、図 F1 にリンクしなかった。図1 への参照なら、AI による補完の link_figure（text「図1」、occurrence 1）か、XML の手直しでリンクを足す`

text は `plain[m.start(1):m.end(2)]`（docx の文字のまま。「図 1」のような空白も含む）、occurrence は `occurrence_at(p, m.start(1), text)`。
表は「表 T1」「link_table」。試作で link_figure（text「図1」、occurrence 1）の貼り戻しが採用されることを確かめた。

### 3.4 期待（試作の結果）

| 文字 | H | 記録 |
|---|---|---|
| 地図1・概念図1 | リンクなし | 図 F1 があれば 1 件ずつ |
| 図表1・発表1回目・代表1名・付表1 | リンクなし | 表 T1 があれば 1 件ずつ |
| 前掲表1 | T1 | なし |
| 図1乃至図2 | F1・F2 | なし |
| （図1）・図1、2 | F1、F1・F2 | なし |
| 図表1と表1 | 後ろの表1 → T1 | 図表1 の 1 件 |
| 地図1、図2 | 図2 → F2 | 地図1 の 1 件 |
| 地図1、2 | どちらもなし | 1 件 |

## 4. U4: 姓と名の区切りがない氏名を、文言から切り出さない

### 4.1 builder.py

- `BuildInfo` に `unsplit_names: list = field(default_factory=list)  # 姓と名を分けられなかった氏名 (段落の ID, 氏名〈前後の空白・タブを除く〉, 言語 ja/en)。AI 依頼文（ai_assist.build_request）に渡す`。
- `Builder.person_name` の `pieces is None` の枝で、今の `info.notes.append(("name", …))`（文言は変えない）に加えて
  `self.info.unsplit_names.append((p.src, text.strip(" 　\t"), lang))`。`lang` は person_name の引数（和文 ja・英文 en）。
  `text.strip(' 　\t')` は AI の split_name の検証（`apply_ops` の core）と同じ空白の扱い。
- 決定事項 17 の後半（英文の氏名を姓と名に分けられなかったことを警告する）: 同じ枝で `lang == "en"` なら
  `self.info.warnings.append(f"英文の氏名「{core}」に姓と名の区切り（空白）がないため、全体を姓（surname）として出力しました。J-STAGE の著者名を確かめ、姓と名に分けるなら Word で姓と名の間に空白を入れて変換し直してください")`
  （10 章の警告。actions() には入れない。表示の仕組みは変えない）。fixture と td1〜3 には英文 1 語の氏名がないので出力は変わらない（`tools/count_names.py`: 姓と名の区切りがない氏名は JASME_template の和文 2 件・sample_full の和文 1 件だけ。英文 0 件）。

### 4.2 pipeline.py

- `unsplit = [(src, msg.split("「", 1)[-1]...) for …]` の行を消し、`req_text, req_images = build_request(plan, linker, info.exclusions, info.unsplit_names)`。
- 版・日時以外の出力は変わらない（切り出した文字と `text.strip(' 　\t')` は、全 fixture と td1〜3 で同じ。`tools/count_names.py` の same_text）。
  違いが出るのは、氏名に「」」があるとき（今は途中で切れる）と、前後に改行など空白・タブ以外の空白文字があるとき（今は文言の strip() で消える。
  H の後は AI の検証と同じく残る）だけ。

### 4.3 ai_assist.build_request

- 引数は今の名前のまま `unsplit_names=()`。要素は (src, text, lang) の 3 つ組。`for src, text, lang in unsplit_names: lines.append(f"- [{src}] 姓と名の区切りがない氏名: 「{text}」")`
  （**決定事項 17: 英文も今までどおり載せる**）。docstring に「英文の氏名も載せる（AI は split_name を和文にしか使えないが、利用者の決定事項 17）」と書く。
- 別案（H の節どおり。まとめ役が選ぶなら）: ループの先頭に `if lang == "en": continue  # 英文の氏名は AI が分けられない（split_name は和文だけ）`。
  英文を除く処理はここ 1 か所（単体テストで確かめられる）。
- 3 つ組以外（古い 2 つ組）を渡す呼び出しは、リポジトリの中にない（tests/test_floats.py などは unsplit_names を渡さない）。

## 5. U5: 既定の AI モデル名を 1 か所に

### 5.1 ai_assist.py

```python
DEFAULT_MODEL = "claude-opus-5-5"
# 既定のモデルの表示名・料金（100 万トークンあたりの米ドル）・提供終了の予定（この日より前には終わらない）。ノートブックの説明
# （tools/make_notebook.py がこのファイルを読む）に使う。モデルを変えるときは DEFAULT_MODEL と一緒に直し、ノートブックを作り直す
DEFAULT_MODEL_INFO = {"name": "Claude Opus 5.5", "input_usd": 4, "output_usd": 20, "not_before": "2027-09-22"}
```

値は今のノートブックの文と同じ（料金は claude-api の資料〈2026-10-06 時点〉で $4 / $20 を確かめた。提供終了の予定日は資料にないので、今の文のまま）。
どちらも**リテラルだけで書く**（make_notebook.py が ast.literal_eval で読むため。式や他の定数を使わない）。

### 5.2 pipeline.py・cli.py

- `from .ai_assist import (... DEFAULT_MODEL ...)` を足し、`Options.ai_model: str = DEFAULT_MODEL  # claude 以外では利用者が指定する`。
- cli.py はすでに `DEFAULT_MODEL` を使っている（変えない）。

### 5.3 tools/make_notebook.py

- パッケージを import せず、`ROOT / "src" / "jasme_jats" / "ai_assist.py"` をファイルとして読む。理由: (1) 版（`__init__.py` の正規表現）・
  原稿種別（jasme.toml）と同じく、リポジトリの src の値を使う（インストール済みの別の版の jasme_jats を読まない。editable でない install や
  古い site-packages があっても、作るノートブックはリポジトリの値になる）、(2) ai_assist は lxml などを import するので、依存を入れずに
  スクリプトを動かせる。
- 読み方: `ast.parse` の最上位の `Assign`/`AnnAssign` から名前で探し、`ast.literal_eval`。関数に分ける:
  ```python
  def module_constants(path, names) -> dict:
      """path の最上位の「名前 = リテラル」の値（パッケージを import しない）。見つからなければ、分かるエラーで止める。"""
      ...
      if missing:
          raise SystemExit(f"{path.relative_to(ROOT)} に {'・'.join(missing)} = … の行が見つかりません"
                           "（ノートブックの既定のモデル名はこの行から作ります。名前を変えたなら tools/make_notebook.py も直してください）")
  _AI = module_constants(ROOT / "src" / "jasme_jats" / "ai_assist.py", ("DEFAULT_MODEL", "DEFAULT_MODEL_INFO"))
  DEFAULT_MODEL, DEFAULT_MODEL_INFO = _AI["DEFAULT_MODEL"], _AI["DEFAULT_MODEL_INFO"]
  ```
  DEFAULT_MODEL が空でない文字列か、DEFAULT_MODEL_INFO に name・input_usd・output_usd・not_before があるかも確かめ、なければ同じく SystemExit。
  （FIX_PLAN は正規表現と書くが、辞書を読むので ast にした。「行が見つからない」と分かるエラーにする点は同じ。）
- 置き換える箇所（`claude-opus-5-5` を直書きしている 4 か所）:
  - API_HELP の 4. の料金の行 → `DEFAULT_MODEL`・`input_usd`・`output_usd`。API_HELP（55 行目からの '''…'''）には波括弧がないので f-string に
    してよい（念のため、作り直したノートブックが今と同じになることで確かめる）。
  - API_HELP の 5. の既定のモデルの行 → `DEFAULT_MODEL`・`name`、提供終了の行 → `not_before` を「2027 年 9 月 22 日」の形にする
    （`y, m, d = not_before.split("-")` → `f"{int(y)} 年 {int(m)} 月 {int(d)} 日"`）。
  - 手順 4 のセルの `MODEL = "claude-opus-5-5"  #@param ["claude-opus-5-5", "自動（最新の Opus）"] {allow-input: true}` → この 1 行だけを
    文字列の連結で作る（セル全体は辞書の波括弧などを含むので f-string にしない。`guard(1, 2, 3)` と同じく `""" + MODEL_LINE + """` の形）。
- 合格の条件: `python tools/make_notebook.py` で作り直したノートブックが、0.26.0 のものと**版の表示だけ**違う（モデル名・料金・日付の文は同じ）。

### 5.4 テスト

- tests/test_ai.py: `from jasme_jats.ai_assist import DEFAULT_MODEL`（既存の import に足す）。直書きの 4 か所（今の 138・152・190・326 行。FIX_PLAN の
  109・123・160・296 は古い）を `DEFAULT_MODEL` に: `calls["model"] == DEFAULT_MODEL`、`available=(DEFAULT_MODEL,)`、
  `calls == [DEFAULT_MODEL, "claude-opus-6"]`、`for model in ("", "auto", DEFAULT_MODEL)`。架空のモデル（claude-opus-5・claude-opus-6・
  claude-sonnet-6・claude-typo）は変えない。足す: `assert Options(out_dir=tmp_path).ai_model == DEFAULT_MODEL`。
- tests/test_notebook.py: `from jasme_jats.ai_assist import DEFAULT_MODEL, DEFAULT_MODEL_INFO`（パッケージから）。足す:
  - `test_default_model_comes_from_ai_assist`: `cell_source("#@title 4.")` に `MODEL = "{DEFAULT_MODEL}"` と `#@param ["{DEFAULT_MODEL}", "自動（最新の Opus）"]`、
    `mk.API_HELP` に `DEFAULT_MODEL` と `DEFAULT_MODEL_INFO["name"]`、`mk.DEFAULT_MODEL == DEFAULT_MODEL`（ファイルから読む部分の誤りを捕まえる）。
  - `test_module_constants_reports_missing_line`: tmp_path に `X = 1` だけの .py を書き、`mk.module_constants(path, ("DEFAULT_MODEL",))` が
    SystemExit で、文言に「DEFAULT_MODEL」と「見つかりません」があること（path は ROOT の外なので、relative_to が失敗しない書き方にする。
    `path.relative_to(ROOT)` ではなく、ROOT の下ならその相対パス、なければ path をそのまま出す）。
  - 既存の `test_notebook_is_up_to_date` で再生成し忘れも検出される。

## 6. 関数・ファイルごとの変更点

| ファイル | 変更 |
|---|---|
| src/jasme_jats/linker.py | 定数 RE_SUP_FN・RE_SUP_LIST・SUP_SIGNS・OPERATORS・RE_EXP_BEFORE・FLOAT_REF_OK_BEFORE・RE_KANJI。`Linker.__init__`（bare_notes=True）、`Linker.note`（applied 引数）、`Linker.run`（fn_ids の後で note_style）、`Linker.note_style`（新）、`Linker.float_refs`（search のループ・記録）、`Linker.fn_marks`（書き直し・記録）。モジュール関数 `occurrence_at`・`_sup_runs`・`_exponent_like`・`_sup_marks`・`_trim_span`（新）。モジュールの docstring の「注 : 上付きの「1)」などを」に「数字だけの上付きは、論文の注番号の書き方と指数・単位の形で決める」、「図・表」に「直前が漢字（前掲・乃至・及びを除く）なら語の一部としてリンクしない」を足す。試作の差分は `scratchpad/h/design/proto_linker.diff`（そのまま使ってよいが、文言と docstring は見直す） |
| src/jasme_jats/builder.py | `BuildInfo.unsplit_names`、`Builder.person_name`（3 つ組と英文の警告） |
| src/jasme_jats/pipeline.py | 切り出しの行を消し `info.unsplit_names` を渡す。`Options.ai_model = DEFAULT_MODEL`（import に足す） |
| src/jasme_jats/ai_assist.py | `DEFAULT_MODEL_INFO`。`build_request` の unsplit_names を 3 つ組に（docstring）。SYSTEM_PROMPT は変えない |
| tools/make_notebook.py | `module_constants`、DEFAULT_MODEL・DEFAULT_MODEL_INFO を使う 4 か所 |
| src/jasme_jats/__init__.py・pyproject.toml | 0.27.0 |
| notebooks/JASME_docx_to_JSTAGE_XML.ipynb | `python tools/make_notebook.py` で作り直す（版の表示だけ変わる） |
| tests/make_fixtures.py | `links_parts(b, bare=False)`・`make_links(path, bare=False)`・`make_links_bare(path)`、冒頭の docstring の一覧、末尾の main と print（7 章） |
| tests/fixtures/sample_links.docx・sample_links_bare.docx | 新規（make_links・make_links_bare だけを呼んで作る） |
| tests/conftest.py | `LINKS`・`LINKS_BARE` を定義し ALL_DOCS に足す |
| tests/test_links.py | 新規（7 章） |
| tests/test_ai.py・tests/test_notebook.py | 5.4、U4 のテスト（7.4） |
| docs/fix_plan_repro_tests.py | D2・M5 の 2 件（`test_PROBLEM_superscript_exponent_linked_as_note`・`test_PROBLEM_figure_reference_inside_word`）を取り除き、冒頭の説明に「単位 H（0.27.0）で取り除いたもの」と逆のテストの場所（tests/test_links.py）を足す |
| docs/DESIGN.md | 6 章の「注」の行（上付きの数字の判定・註・記録）、「本文中の図表番号」の判断（なければ行を足す: 直前が漢字なら語の一部、FLOAT_REF_OK_BEFORE）、4.4 の (2)「リンク…が元の docx と同じに決まるか」→「元のリンクが失われないか（増えるリンクは見ない）」、5 章のモデル（DEFAULT_MODEL・DEFAULT_MODEL_INFO が 1 か所）、7 章の既知の限界（9 章のもの） |
| docs/DEVELOPMENT.md | テストの節に sample_links・sample_links_bare・tests/test_links.py、残っている課題（9 章）、よくある拡張に「既定の AI モデルを変える: ai_assist.DEFAULT_MODEL と DEFAULT_MODEL_INFO を直し、ノートブックを作り直す」 |
| docs/FIX_PLAN.md | H の節に実装の記録（決定事項 15〜17 との対応、暫定の判断〈番号だけの上付きの 1 件ずつの記録〉、SYSTEM_PROMPT を足さなかったこと、行番号の古さ）、「同じファイルを触る順」に H で触ったファイル |
| README.md | 4 章の記録の説明があれば「注・図表にリンクしなかった箇所」を足す（なければ触らない） |

触らないもの: pdfmatch.py・pdfdocx.py・structure.py（I で分割）・report.py・colab.py・cli.py（DEFAULT_MODEL は既に使用）。

## 7. テストの計画

### 7.1 fixture（tests/make_fixtures.py）

`links_parts(b, bare=False)` が章見出しから注の一覧までを返し、`make_links(path, bare=False)` が `make_article(path, 題目, lambda b: links_parts(b, bare))`、
`make_links_bare(path)` が `make_links(path, bare=True)`。部品は既存の `para`・`run(…, sup=True)`・`drawing`・`png_bytes`・`table`・`cell`・`make_article`
（題目・著者・引用文献 1 件〈試験六郎（2024）〉・英文要旨は make_article が入れる）。試作は `scratchpad/h/design/tools/proto_fixtures.py`（そのまま移せる）。

- 共通（M5）: 「地図1と図表1を見る。発表1回目は概念図1で、代表1名が付表1を示した。」「前掲表1、図1乃至図2、（図1）、図1、2を参照する。」
  「図表1と表1を比べる。地図1、図2も見る。地図1、2は架空である。」、図1・図2（画像あり）、表1（本体あり）、注の見出し。
- sample_links（「1)」の書き方）: 2.7 の表の 6 段落と、注の一覧「1) …」「2) …」「3) …」。上付きの符号は「−」（U+2212）。
- sample_links_bare（番号だけ）: 「これは架空の主張である」＋¹、「架空の報告がある（試験, 2024）」＋²（**FIX_PLAN の例の 2020 は引用文献の年と
  合わず、3 章に引用の知らせが出るので 2024 にする**）、「教室の広さは 4 m」＋²、「架空の議論がある」＋「1-3」、「別の議論もある」＋「1, 2」
  （FIX_PLAN の注意どおり、上付きの直前に「注」の字を置かない）、注の一覧は上付きの数字で始まる段落（`run("1", sup=True), " 一つ目の架空の注。"`）。
- 作ったら `git status` で 2 つの docx だけが増えたことを確かめる（`python tests/make_fixtures.py` は実行しない）。試作の 2 つは
  strict・split のどちらでも、不変性・最終・DTD・jstage_issues == []・lost_images == []・hidden_images == []・drop の理由（姓と名・番号と本文）を満たした。

### 7.2 tests/test_links.py（新規）

`load(res)`（XML の 3 行目から）と `fn_links(root)` = `[(xref の文字, rid, 段落の先頭 N 字)]` の補助を置く（段落の文字で対象を選ぶ。件数に依存しない）。

1. `test_superscript_notes_with_marks`（sample_links）: 注の xref の (文字, rid, 段落) の集合が**ちょうど** 2.7 の H の列と同じ。cm²・x²・s⁻¹・f(x²) の² と
   番号だけの² にはリンクがない。「1,2)」「1-3)」の 1 にはある。「註1」は文字「註1」で fn1。`linker.bare_notes is False`（`_mechanical` で）。
2. `test_superscript_notes_bare`（sample_links_bare）: ¹ ²（括弧の後ろ）が fn1・fn2、「1-3」の 1・3、「1, 2」の 1・2（xref の文字に空白なし）、m² はなし。`bare_notes is True`。
3. `test_unlinked_superscripts_are_recorded`: `plan.decisions` の category note・applied False の記録が、指数の段落ごとに 1 件（cm² の段落 1 件、x²+y² の段落に
   「2」が 2 つの 1 件）、番号だけの² が 1 件。文面に「link_note」「text「2」」「occurrence 2」があり、text に空白が入らない。レポートの 4 章に同じ文面、
   AI依頼文.txt に `- [d…] 推定: 上付きの数字` の行。**report.actions(res) に増えたものがない**（記録だけ。0.26.0 と同じ Action の種類）。
4. `test_link_note_from_record_is_accepted`（手動モードの貼り戻し）: 記録の text と occurrence の link_note（cm² の「2」→ fn2、番号だけの「2」→ fn2）が accepted、
   不変性・最終・DTD 合格（試作 `tools/run_ai.py` と同じ）。
5. `test_exponent_without_note_is_not_unresolved`: 注 1 だけの論文で「3 cm」＋² → 3 章（unresolved_after）に fn の行がない。番号だけの「1)」の論文で
   注のない上付き「5)」→ 今までどおり「対応する注が見つからない」。
6. 境界（`make_article` でその場で作る。parametrize）: 上付き「−1)」（符号が先）→ リンクなし、「x」＋「2)」→ fn2（strong が指数より先）、
   「（試験, 2024）」＋² の「1)」の論文 → 番号だけなのでリンクなし・記録あり、本文「注 」（空白）＋¹ → after_note でリンク、
   「1)」の論文でも note_style に after_note だけでは False にならない（注＋¹ だけの論文は bare_notes True）、全角の上付き「２）」→ fn2。
7. `test_note_marks_inside_box`: 囲み（`textbox_inline`、`test_links_inside_box` と同じ大きさ）の中の「9 cm」＋² はリンクなし・記録あり、「である」＋「1)」は fn1
   （試作 `tools/box_case.py`）。
8. `test_figure_refs_inside_words`（sample_links。M5）: fig・table の xref の (文字, rid, 段落の先頭) が 3.4 の表どおり（前掲表1・乃至・括弧・tail・図表1と表1 の
   後ろ・地図1、図2 の図2 だけ）。記録: 地図1・概念図1（図）、図表1・発表1・代表1・付表1（表）、「地図1、2」は 1 件、「図表1と表1」は 1 件。
   文面に「link_figure」「text「図1」」。
9. `test_float_refs_search_again_after_head`（単体。plan を作らない）: `Para`・`Atom` で段落を作り、`Linker(plan_stub).float_refs(p, RE_TABREF, {1: "T1"}, "table", "表")`
   （`ArticlePlan()` は既定値で作れる。試作で確かめた）。`Para(src="d1", atoms=[Atom(kind="text", text=…)])` に対して
   「図表1と表1を比べる。」→ 後ろの表1 だけ T1（記録 1 件）、「地図1、2と地図1、図2」→ 図2 だけ F2（記録 2 件）。これが fix_plan_repro_tests の `test_PROBLEM_figure_reference_inside_word` の逆
   （FIX_PLAN の注意: 正規表現の結果ではなく float_refs の結果で確かめる）。
10. `test_eq_refs_unchanged`: 「数式(1)」の「式(1)」は今までどおり FD1 にリンク（sample_full の「式(1)より」が FD1 であることは既存のテストにあればそれでよい）。
11. `test_superscript_exponent_not_linked`（fix_plan_repro_tests の `test_PROBLEM_superscript_exponent_linked_as_note` の逆。同じ docx: 「面積は 3 cm」＋²＋「 である」＋「1)」、
    注 1)・2)）: ("1)", "fn1") はあり、("2", "fn2") はない。

### 7.3 既存テスト

- test_pipeline.test_fidelity_and_dtd は ALL_DOCS に足した 2 件で 4 ケース増える（変更なし）。
- 試作の linker で 0.26.0 の全テスト（951 件）が通った（`pytest_src.sh <design/src>`）。書き換えが要る既存テストはない（U5 の test_ai の直書き 4 か所は
  置き換えであって期待は変わらない）。
- golden.py は ALL_DOCS を読むので、H の後は sample_links・sample_links_bare の 4 件が増える。比べるのは 0.26.0 と同じ名前の 23 件。

### 7.4 U4 のテスト（tests/test_ai.py）

1. sample_full を手動モードで変換し、AI依頼文.txt に `- [d11] 姓と名の区切りがない氏名: 「研究次郎」` がある（今の出力にもある。回帰）。
2. `_mechanical(FULL)` → `build(plan, meta, journal, None)` の `info.unsplit_names == [("d11", "研究次郎", "ja")]`。
3. `build_request(plan, linker, (), [("d11", "研究次郎", "ja"), ("d12", "KENKYU", "en")])` の依頼文に d11 と **d12 の行がある**（決定事項 17）。
   別案を採るなら d12 の行がないことに逆にする。
4. 英文 1 語の著者名（`make_article` の英文の著者を「KENKYU」1 語にした docx）を変換すると、res.warnings に「英文の氏名「KENKYU」」の警告があり、
   build_notes（4 章）にも今までどおりの記録がある。actions() は増えない。
5. pipeline.py に「msg.split("「"」の切り出しが残っていないこと（`inspect.getsource(pipeline.convert)` に `split("「"` がない、で十分）。

## 8. 合格の条件（物差しごと）

- pytest: `python -m pytest -q -p no:cacheprovider` と Python 3.10（`scratchpad/venv310`）ですべて合格。ruff（`ruff check src tests tools`）は HEAD の
  201 件から増やさない（試作の linker.py は HEAD と同じ 6 件〈I001・FURB167。既存〉）。
- golden（0.26.0 と同じ名前の 23 件）: **すべて同じ**であること。試作の D2・M5 で 23 件の manifest（XML・AI依頼文・レポート・ok）が 0.26.0 と一致した
  （`scratchpad/h/design/golden_proto/manifest.json`）。既存の fixture に指数の上付き・語の中の図表番号・英文 1 語の氏名がないため。U4（決定事項 17）・U5
  でも出力は変わらない見込み（U4 の文字は全 fixture で同じ、U5 はノートブックだけ）。違いが出たら意図したものではないので理由を調べる。
  別案（英文を外す）を採っても、fixture に英文 1 語の氏名がないので同じ。
- td1〜3（ルート1・ルート2、手動モード）: 0.26.0 と XML・レポート（作成日時・ツールの行を除く）・AI依頼文・ZIP の中の XML・ルート2 の直した docx の
  document.xml が**すべて同じ**（試作で、出力フォルダの 70 ファイルすべてと直した docx が一致。xref の違い 0 件）。不変性・最終・DTD・J-STAGE の
  チェックは 0.26.0 と同じ（ルート1・2 とも合格。終了コードはどちらの版も 1〈手動モードの要対応〉）。XML に入らなかった画像は増えない。
- AI依頼文: 意図した行（H の記録の「推定:」の行。fixture と td1〜3 には出ない）以外は同じ。SYSTEM_PROMPT は変えない。
- ノートブック: 作り直したものが 0.26.0 と版の表示だけ違う。test_notebook_is_up_to_date 合格。
- 変えてよいもの（新しい fixture と単体テストでだけ現れる）: 上付きの指数・単位・符号で始まる上付き・「1)」の論文の番号だけの上付きが注にリンクされない、
  「註1」が「註」ごとリンクされる、上付きの並びのリンクの文字の前後の空白が入らない、語の中の「図N」「表N」がリンクされない、
  「図表1と表1」の後ろの表1 が「表1」としてリンクされる（今は tail の「1」だけ）、それに伴う 4 章の記録・AI 依頼文の「推定:」の行、
  指数の形の上付きに注がないときの 3 章の知らせが出なくなること、語の中の図表番号に図表がないときの 3 章の知らせが出なくなること、
  英文 1 語の氏名の 10 章の警告。文字・段落の構造・不変性チェックは変わらない（リンクは LinkSpec だけで、文字を変えない）。

## 9. 残る限界と、利用者に確かめてもらうこと

- 決定事項 15〜17 は回答済み（0 章）。H で暫定にしたのは: (a) 「1)」の論文の、指数でない番号だけの上付きの数字を 1 件ずつ記録すること
  （まとめるかどうかは決定事項 15 の対象外）、(b) SYSTEM_PROMPT に 1 文を足さないこと、(c)（まとめ役が別案を選んだ場合）英文 1 語の氏名を外すこと。
- 注番号の書き方の判定は論文全体で 1 つ。「1)」の注と番号だけの注が混ざった原稿では、番号だけのものがリンクされない（記録には出る）。
  逆に、番号だけの論文に「1)」の形の上付きが 1 つでもあると、その論文の番号だけの注はすべてリンクされない（記録に出る）。
- 指数の判定は直前・直後の 1 文字と符号だけ。番号だけの論文で、英字・数字の直後の注番号（「Piaget¹」「2020年の調査では 30¹」など）は指数とみなして
  リンクしない（記録に出る）。「(a+b)²」の ² は直前が閉じ括弧なので指数とみなさず、番号だけの論文で注 2 があればリンクされる。数式（OMML）の直後の
  上付きの数字も指数とみなさない。直前が「注」の上付きは、「脚注」「受注」の「注」でもリンクする。
- 語の中の図表番号の判定は直前の 1 文字が漢字かだけ。「本図1」（直前「本」）はリンクしない、「第1表」はもともと対象外、カタカナの直後
  （「ヒストグラム図1」）はリンクする。「前掲・乃至・及び」以外に前に来てよい漢字が実際の原稿で見つかれば FLOAT_REF_OK_BEFORE に足す。
- ルート2 で、PDF に合わせた直しで注番号の形が変わると、論文全体の書き方の判定が変わりうる（pdfdocx の守りで直しをやめる側に倒れる。2.5）。
  リンクが増える直しは止めない。
- 記録の件数に上限はない。指数の多い論文（数学教育の論文で x²・cm² が多いもの）では、注の番号以下の指数がある段落の数だけ 4 章と AI 依頼文の行が増える。
  試験運用で件数を見て、多ければ利用者と相談する（DEVELOPMENT の「残っている課題」に書く）。
- 手元の実際の論文（td1〜3）には、上付きの指数・単位も、番号だけの上付きの注も、語の中の「図N」「表N」もない（6 で数えた）。H の規則は架空の
  fixture でしか確かめていない。実際の原稿で、指数の多い論文と番号だけの注の論文を試験運用で確かめる。
- 実際の AI（Claude）で、新しい「推定:」の行から link_note・link_figure が提案されるかは確かめていない（模擬回答だけ）。

## 10. td1〜3 の計数（数だけ。文字は記録しない。0.26.0 の `_mechanical` で数えた。`scratchpad/h/design/count_td_base.json`）

| | 手で書いた注 | 上付きの続き（数字を含む） | うち「N)」の形 | 指数・単位の形 | 番号だけ | 直前が「注」 | 0.26.0 で注にリンク | 語の中の図・表番号（直前が漢字） |
|---|---|---|---|---|---|---|---|---|
| td1 | 5 | 6（本文 5・キャプション 1） | 6 | 0 | 0 | 0 | 6（count fn 6） | 0（図の参照の一致 51 件中。キャプションの 10 件は対象外） |
| td2 | 4 | 4（本文 1・表のセル 3） | 4 | 0 | 0 | 0 | 4（count fn 4） | 0（図 22・表 12 件中） |
| td3 | 6 | 6（本文 6） | 6 | 0 | 0 | 0 | 6（count fn 6） | 0（図 13 件中） |

- 3 本とも「N)」の書き方（note_style は False）で、上付きはすべて「N)」の形。直前の文字は かな・漢字・閉じ括弧で、指数の形のものはない。
- 見積もり: H の後も xref は変わらない。試作で確かめた結果、ルート1・ルート2 とも出力（XML・レポート・AI依頼文・ZIP・直した docx）がすべて 0.26.0 と同じ
  （xref の違い 0 件）。姓と名の区切りがない氏名は 3 本とも 0 件。

## 11. 却下した案

- SYSTEM_PROMPT に D2 の 1 文を足す（「同じファイルを触る順」）: 全 fixture の依頼文が変わり、記録の文面で足りるので却下（0 章 3）。
- fn_marks の上付きの続きを今のようにアトムを数え直しながら進める: plain は変わらないので、最初に続きを求める方が簡単で同じ結果。
- 指数の判定で直前の空白を飛ばす: 「3 cm」の後ろの ² は直前が m なので要らない。飛ばすと「…である ¹」まで直前の文字で決まり、誤りが増える。
- 指数でも注がなければ 3 章に「対応する注が見つからない」を出す（今の動き）: 指数で一覧が埋もれる（D2 の趣旨）ので却下。番号だけ・番号の形がはっきりした
  ものは今までどおり出す。
- make_notebook.py で正規表現だけで読む: 辞書（DEFAULT_MODEL_INFO）を読むには ast.literal_eval の方が確か。分かるエラーにする点は同じ。
- `RE_FN_MARK`（未使用）を消す: H の範囲の外。食い違いとして報告だけする。
