# 単位 u5-exclusions（0.31.0）: 「位置づけが不明」の除外の知らせ・英文要旨が見つからないとき・注の節の表

## 要点

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

## 再現（確かめたこと）

再現と試作のスクリプトは `docs/fix_plan_2026-11/protos/u5-exclusions/` と `docs/fix_plan_2026-11/protos/review-u5-exclusions/` にある。
どれも計画のときの作業フォルダ（scratchpad）のパスを前提に書かれていて、そのままでは動かない。手本として読むものである。
出力のフォルダ・生成した docx・`count.json`・`pytest_proto.txt` は写していない（結果は下の表に書いた）。

| 項目 | 結果 | スクリプト | 見たこと |
|---|---|---|---|
| (a) 注の節の表（K7） | 再現 | `u5-exclusions/repro.py`（a1〜a4） | 注の項目の後ろ（a1）・注の見出しの直後で項目がまだない（a2）・「表キャプション」スタイルのキャプション付き（a3）・注の段落が本文スタイル（a4）のどれも、`ok=True`・`needs_action=False`・`actions=[]`。表のセルの段落（a1 は d15・d16）が理由「後付けの位置づけが不明な表の文字」で除外され、`table-wrap` は 0 個。a3 ではキャプションが注 fn1 の 2 段落目の `p` になる |
| (a') 注の節の表のセルの画像 | 再現 | `u5-exclusions/fnfig.py` | セルの画像は要対応 `lost`（img2・d17）で知らされるが、表の文字（d17・d18）は除外のまま知らせなし。表の外の画像だけの段落は `fn/p` の `inline-graphic` で出る |
| (b) 見出しがなく標準スタイルの英文要旨（K12） | 再現 | `u5-exclusions/repro.py`（b1〜b3） | b1（Abstract の見出しを消し、要旨 2 段落の pPr を外す）: `actions=[]`・`plan.abstract` 0 段落・`trans-abstract` なし。d21・d22 が「英文部分の、題目・著者・要旨以外の段落」で除外。b2（見出しは残し要旨だけ標準）と b3（見出しなし、要旨は英文要旨スタイル）は問題ない。AI の回答 `set_role(d21, abstract)` で 2 段落とも英文要旨になる（`u5-exclusions/ai_check.py`） |
| (b') 英文の部分のスタイルがすべてない | 再現（この単位では直さない） | `u5-exclusions/allplain.py` | 英文題目のスタイルがないと英文の部分（front_en）に切り替わらず、英文の題目・著者表・要旨が引用文献の項目になる（refs 8 件、知らせなし）。除外ではないので、この単位の知らせでは見つからない。REVIEW に記録する |
| DTD | 確かめた | `u5-exclusions/dtd_check.py` | `fn/p/table-wrap`（新しい p・既存の p の中・id とキャプション付き・p が table-wrap だけの fn）はすべて妥当。`fn` の直下の `table-wrap` は不合格（fn の内容は `label?, p+`）。点検の `edge.py` の 3 つの形でも `dtd_valid` は真 |
| 試作（注の表を注に入れる） | 確かめた | `u5-exclusions/proto_fn_table.py`（実行中の関数を差し替える） | 注の項目の後ろ: fn1 = p, p/table-wrap#T2, p。キャプション付き: 直前の「表キャプション」の段落が caption になり、本文の「表2」が T2 にリンクされる。注の見出しと表だけ: 表は除外のまま。本文の表 T1 の ID は変わらない。fidelity・DTD とも合格 |
| キャプションが注の見出しの直後 | 確かめた（設計の欠陥） | `review-u5-exclusions/edge.py`（cap_first） | 注見出し → 表キャプション → 表 → 「1) …」の並びを設計どおりに組むと、番号のない注（キャプションだけ）が 1 件増え、本文の「表2」はリンクされない。直し方 4.3 の条件 (a) で直す |
| キャプションの番号が本文と重なる | 確かめた | `review-u5-exclusions/edge.py`（cap_dup） | 注の表のキャプションが「表1」で本文にも表1 があると、`assign_ids` が「表番号 1 が重複している」を記録し、本文の「表1」はリンクされず要確認 `float_ref` が出る（今は本文の表1 にリンクされる）。動きとしては正しい回帰 |
| 既存テストへの影響 | 確かめた | `u5-exclusions/proto_patch.py` | 試作と仮の Action を入れて全テストを動かすと 1297 件が通り、落ちたのは `tests/test_pipeline.py::test_blank_paragraphs_in_front_and_back_tables_are_excluded` の 1 件だけ（注の表の全角空白が出力され、空白の除外が 5 件から 4 件になる） |
| 件数 | 確かめた | `u5-exclusions/count.py`・`count_proto.py` | fixture 15 件と tests/private の docx 10 件（テストデータ1〜5 の 9 件とテンプレート）をルート1・`ai_mode="manual"`（回答なし）で変換。どの docx にも冒頭部の装飾が 3 件（誌名行 1・記号だけの行 2。中身は全件で同じ）。「位置づけが不明」の理由はテストデータ1〜5 と全 fixture で 0 件。tests/private のテンプレートだけ英文の部分の段落 4 件（d87・d88・d90・d186）とセル 121 件、`plan.abstract` 0 段落 |
| 英文要旨の別名 | 確かめた | `review-u5-exclusions/alias.py`・`alias2.py` | 別名を足すと、テストデータ1〜5 の 9 件と fixture 15 件は plan・除外・actions とも同じ。tests/private のテンプレートだけ、英文要旨が d87（見出し）・d88、資料が 2 つ（d90 と T2、d186 と T3）になり、英文の部分の除外は 0、`abstract_missing` は出ない |
| 除外の理由の網羅 | 確かめた | （点検で grep） | `plan.exclude`・`exclude_blank`・`exclusions.append`・`Exclusion(` をすべて拾い、下の分類で抜けがないことを確かめた |

原因: 除外（`plan.exclude`）が、意図した除外（テンプレートの装飾・重複する所属・AI の判断・図の注記など）と、「役割を決められなかったので除いた」ものを同じに扱っている。
知らせがあるのはテキストボックスの 2 つの理由（`textbox_figure_text`・`textbox_undecided`）と画像（`lost`）だけ。
(K7) `structure.Classifier.build_back`（1910 行〜）の表の枝（1921〜1938 行）は、state が refs なら引用文献、notes・ack なら `BackSec.children` に入れるが、
fn には入れ先がない（`FnNode` は `paras` しか持たず、`builder.fn` も `p` しか書かない）ので、else の除外に落ちる。
(K12) `build_front_en`（2010 行〜）は英文要旨を見出し（abstract_heading）のスタイルか段落の abstract のスタイルだけで見つける（`in_abstract`）。
どちらもなければ、英文の題目・著者以外の段落は 2143 行の除外に、英文の部分の表は 2050 行の除外に落ち、資料の見出しも資料の始まりにならない（`head_text` は `in_abstract` が真のときだけ）。

## 直し方

### 1. structure.py: 除外の理由の定数（82〜86 行の TEXTBOX_* の後ろ）

```python
# 冒頭部の、テンプレートの装飾・誌名行の段落（意図した除外。知らせない。front_decoration で決める）
FRONT_DECORATION_EXCLUDED = "冒頭部のテンプレート装飾・誌名行など（題目・著者以外の段落）"
# 論文の中の位置（役割）を決められずに除いたときの理由。要確認 excluded_unsure（report._unplaced_action）で知らせる
FRONT_OTHER_EXCLUDED = "冒頭部の、題目・著者以外の段落（テンプレートの装飾・誌名行ではない）"
FRONT_TABLE_EXCLUDED = "冒頭部の表（著者表以外）の文字"
AUTHOR_TABLE_OTHER_EXCLUDED = "著者表の中の、所属・著者名以外の文字"
BACK_TABLE_EXCLUDED = "後付けの位置づけが不明な表の文字"
BACK_OTHER_EXCLUDED = "位置づけが不明な段落（本文と後付けの間）"
EN_AUTHOR_TABLE_OTHER_EXCLUDED = "英文著者表の中の、所属・著者名以外の文字"
EN_TABLE_EXCLUDED = "英文部分の表（著者表以外）の文字"
EN_OTHER_EXCLUDED = "英文部分の、題目・著者・要旨以外の段落"
UNPLACED_EXCLUSIONS = (FRONT_OTHER_EXCLUDED, FRONT_TABLE_EXCLUDED, AUTHOR_TABLE_OTHER_EXCLUDED, BACK_TABLE_EXCLUDED,
                       BACK_OTHER_EXCLUDED, EN_AUTHOR_TABLE_OTHER_EXCLUDED, EN_TABLE_EXCLUDED, EN_OTHER_EXCLUDED)
# 英文要旨がないときに要対応 abstract_missing の対象にする理由（abstract_missing_srcs）
EN_PART_EXCLUSIONS = (EN_TABLE_EXCLUDED, EN_OTHER_EXCLUDED)
```

- 678・693・715・1937・2007・2038・2050・2143 行の文字列を定数に置き換える。文言は `FRONT_OTHER_EXCLUDED` 以外は今のまま（既存テストが文言で確かめている）。
- 理由の文字列で判定する（既存の `TEXTBOX_*` と `report.figure_text_exclusions` と同じ）。`model.Exclusion` に印を足さず、`plan.exclude(..., unsure=True)` のような引数も作らない。
- 除外の分類（点検で全件を突き合わせた。この表を structure.py の定数の上のコメントには書かず、DESIGN.md 4.3 に書く）:
  - 意図した除外（知らせない）: 429 行（AI の exclude。AI の報告に載る）、693 行の装飾（`FRONT_DECORATION_EXCLUDED`）、746・2208・2214 行（重複する所属）、
    1106 行（`TEXTBOX_LABEL_EXCLUDED`・`TEXTBOX_AI_LABEL_EXCLUDED`。判断の一覧と 10 章で知らせている）、2282 行（Word で表示されない注）、
    builder 774 行（注の見出しだけ）、`exclude_blank`（空白だけ）と builder 574 行（図の画像だけの段落の空白）。
  - すでに知らせがある: 784 行 `TEXTBOX_TEXT_EXCLUDED`（`textbox_figure_text`）、1117 行 `TEXTBOX_UNDECIDED_EXCLUDED`（`textbox_undecided`）。
  - 位置を決められない（新しい知らせ）: 678・693（装飾でないもの）・715・1937（直した後に残る分）・2007・2038・2050・2143 行。
- u6 は所属の衝突を中止にするので、新しい除外の理由を足さない（u6 の設計書）。

### 2. 冒頭部の装飾の判定（build_front_ja 690〜693 行）

- `src/jasme_jats/data/jasme.toml` の `[journal]` の `image_name_pattern` の後ろに足す（雑誌に固有の値なので toml に置く）:

  ```toml
  # テンプレートの冒頭の誌名行（題目の前の段落。冒頭部の装飾として、知らせずに除く。structure.front_decoration）
  front_lines = ["全国数学教育学会誌　数学教育学研究"]
  ```

  値は fixture のテンプレート（`tests/fixtures/JASME_template_20261009.docx`）の d1 の文字（全角空白を含む）と同じ。実装のときに fixture から読んで確かめる。
- `config.JournalConfig` に `front_lines: list = field(default_factory=list)` を足す（`fn_title_en` の後ろ。`load` は `[journal]` を `**j` で渡すので、フィールドを足すだけで読める）。
- structure.py にモジュール関数を足す（`nfkc`〈173 行〉の後ろ）:

  ```python
  def front_decoration(para: Para, lines=()) -> bool:
      """和文の冒頭の、題目・著者以外の段落が、テンプレートの装飾か。文字（text）と画像以外のアトム（数式・注の参照など）があれば偽。
      そうでなければ、空白を除き NFKC にした文字が、空か、文字・数字を含まない（記号だけの装飾行）か、雑誌の設定の誌名行
      （JournalConfig.front_lines）のどれかと同じなら真。画像だけの段落は装飾とする（画像は lost_images の要対応で知らせる）。"""
      if any(a.kind not in ("text", "image") for a in para.atoms):
          return False
      t = re.sub(r"\s", "", nfkc(_para_text(para)))
      if not t or t in {re.sub(r"\s", "", nfkc(x)) for x in lines}:
          return True
      return not any(unicodedata.category(c)[0] in "LN" for c in t)
  ```

- 693 行を次にする:
  `plan.exclude(b, FRONT_DECORATION_EXCLUDED if front_decoration(b, self.journal.front_lines) else FRONT_OTHER_EXCLUDED)`。
  `plan.locations[b.src] = "冒頭部"` は今のまま。全 docx（fixture 15・tests/private 10）で、冒頭部の 3 件はすべて装飾と判定される（実測）。

### 3. jasme.toml: 英文要旨の別名（計画者の決定）

`[styles]` の `"英文要旨" = "abstract"`（70 行）の直後に足す。順番を守る（`report._abstract_missing_action` は値が abstract・abstract_heading の最初のスタイル名を文に出すので、「英文要旨」「英文要旨見出し」を先にする）:

```toml
# テンプレートの別の版の英文要旨のスタイル名（別名。同じ役割）
"英文要約見出し" = "abstract_heading"
"英文要約" = "abstract"
```

### 4. 注の節の中の表（K7）

#### 4.1 article.py

- `FnNode`（94 行）に足す:

  ```python
  # 注の節の中の表 [(k, TableNode)]（docx の順）。k は表の前にある paras の数で、builder.fn が paras[k] の <p> の前に
  # <p><table-wrap> を書く（k == len(paras) なら最後）。最初の注より前にあった表は k=1（注の番号が <fn> の先頭に来るように）
  tables: list = field(default_factory=list)
  ```

- `ArticlePlan` に足す（`no_link_paras` の前）:

  ```python
  def fn_table_paras(self) -> set:
      """注の節の中の表（FnNode.tables）のキャプション・キャプションの続き・セルの段落の ID。linker が注番号をリンクしないために使う
      （注の段落と同じ扱い）。"""
      out = set()
      for fn in self.fns:
          for _, t in fn.tables:
              out.update(q.src for q in ([t.caption] if t.caption is not None else []) + list(t.caption_more))
              if t.table is not None:
                  out.update(q.src for q in t.table.paragraphs())
      return out
  ```

#### 4.2 structure.Classifier.build_back: 変数と補助関数

ループの前（1913 行 `current_fn = None` の後ろ）に置く:

```python
pending = []        # 注の見出しの後ろで、注がまだ始まっていないときの表 [(キャプションの段落か None, Table)]（docx の順）
fn_role = {}        # 注に入れた段落の役割（src -> role）。キャプションの判定に使う（role_of は role_origin を書き換えるので呼び直さない）

def flush():
    """注に入れられなかった表（とそのキャプション）を、位置を決められない除外に記録する（要確認 excluded_unsure）。"""
    for cap, t in pending:
        for p in ([cap] if cap is not None else []) + list(t.paragraphs()):
            if p.is_blank:
                plan.exclude_blank(p)
            else:
                plan.exclude(p, BACK_TABLE_EXCLUDED)
    pending.clear()

def note_table(fn, k, node, first):
    """注 fn に表 node を入れ、判断の一覧（4 章）に記録する。first: 最初の注より前にあった表。"""
    fn.tables.append((k, node))
    if node.caption is not None:
        src = node.caption.src
    else:
        src = next((q.src for q in node.table.paragraphs() if not q.is_blank), block_id(node.table))
    where = ("注の見出しの後ろ、最初の注の前にあった表を、その注の 1 段落目の後ろに入れた" if first
             else "注の段落の間、docx の順")
    plan.decide("mechanical", "note", src,
                f"注の節の中の表を、注 {len(plan.fns)}件目の中に出力した（{where}）。J-STAGE の画面で注の中の表が"
                "表示されるかは確かめていないので、プレビューで確かめる")
```

- キャプションは注から外したので出力されない。除外に記録してよい（不変性チェックの conflicts にならない）。
- 表のセルの段落の `plan.region`・`plan.locations` は、付記・謝辞の表と同じく付けない（`set_role_problem` が「表のセルなど…変えられない」を返す今の扱いのまま）。

#### 4.3 build_back: 表の枝（1921〜1938 行）

`if state == "refs": …; continue` の後ろ、`target = {…}` の前に足す:

```python
if state == "fn":
    c = current_fn.paras[0] if current_fn is not None and len(current_fn.paras) == 1 else None
    if (c is not None and plan.fns and current_fn is plan.fns[-1] and current_fn.number is None and not current_fn.tables
            and fn_role.get(c.src) == "table_caption" and self.overrides.get(c.src) != "fn_start"):
        # (a) 注の見出しの直後のキャプションから番号のない注ができていた: 注を作り直さず、(キャプション, 表) を次の注に回す
        plan.fns.pop()
        current_fn = None
        plan.locations[c.src] = "注の表キャプション"
        pending.append((c, b))
        continue
    if current_fn is None:
        pending.append((None, b))       # (b) 注がまだ始まっていない
        continue
    cap = None                          # (c) 注の段落の後ろの表。直前の「表キャプション」の段落（注の 2 段落目以降）をキャプションにする
    if len(current_fn.paras) >= 2 and fn_role.get(current_fn.paras[-1].src) == "table_caption":
        cap = current_fn.paras.pop()
        plan.locations[cap.src] = f"注 {len(plan.fns)}件目の表キャプション"
    note_table(current_fn, len(current_fn.paras), TableNode(table=b, caption=cap), first=False)
    continue
```

- キャプションが注の 1 段落目しかない（その段落で番号のある注が始まった）ときは移さない（注が空になるため。キャプションは注の `p` のまま）。
- 本文スタイルの「表1 …」はキャプションにしない（注の `p` のまま）。
- state が None・"back" の表（今の else）は今までどおり `BACK_TABLE_EXCLUDED`。

#### 4.4 build_back: 見出しの枝・注の始まり・ループの後ろ

- 見出しの枝（1939〜1962 行）: `current_fn = None`（1961 行）の直前で `flush()` を呼ぶ（次の見出しまでに注が始まらなかった表は除外のまま、要確認の対象）。
  u6 が後で同じ枝に `replace_back` を足す。見出しの枝の並び: 分岐の前は今のまま（文字から推定したときの decide → `state = BACK_HEADINGS[heading]` → `plan.region[b.src] = state`）→ 種類ごとの分岐で `if self.replace_back(kind, old, b, role): plan.X = b`（u6）と `plan.locations[b.src] = …`・注の節が引用文献の後ろのときの decide（今のまま）→ `self._heading_by_text[b.src] = role not in BACK_HEADINGS`（u6）→ `flush()`（u5）→ `current_fn = None` → `continue`。`flush()` と `current_fn = None` は `replace_back` の戻り値に関係なく呼ぶ（u6 の設計書にも書く）。
- 注の段落の枝（1978〜1999 行）: 注を始めた段落にも続きの段落にも `fn_role[b.src] = role` を記録する。
  注の始まり（1998 行 `plan.fns.append(current_fn)` の後ろ）に足す:

  ```python
  for cap, t in pending:
      note_table(current_fn, 1, TableNode(table=t, caption=cap), first=True)
  pending.clear()
  ```

  k=1 なので、表は注の 1 段落目の後ろに出る（注の番号が `<fn>` の先頭に来る。docx の文字は変わらず、並びだけが変わる。単位どうしの点検の決定）。
  後で同じ注に足す表の k も 1 以上なので、`fn.tables` は k の順に並ぶ。
- ループの後ろ（文書の終わり）で `flush()`。
- Word の脚注・文末脚注（`attach_word_notes`）の `FnNode` には tables を作らない（`docx_reader.read_notes` が注の中の表を段落に開いているので、今までどおり段落で出る）。

#### 4.5 structure.Classifier.assign_ids（2329 行〜）

`for extra in (plan.notes, plan.ack): …`（2346〜2348 行）の後ろ、`for app in plan.apps:` の前に足す:

```python
for fn in plan.fns:
    tabs.extend(node for _, node in fn.tables)      # 注の節の中の表（docx の順。付記・謝辞の表の後ろ、資料の表の前）
```

キャプションのある表は表番号も読まれ、本文の「表N」がリンクされる。注の表は `plan.tables` に入るので、AI の依頼文の「図・表・注・数式」・
10 章の「キャプションのない表」・`builder._cell_tables`・`ai_assist` の ID の確かめ（1450 行）にも本文の表と同じく現れる。

#### 4.6 builder.Builder.fn（826 行〜。u3-autonum の形の上に 3 か所）

u3-autonum の形の `fn` に、u3-autonum の設計書で `# u5 が足す` と示した 3 か所の位置へ次を足す（コードにコメントは残っていない）:

```python
tables = list(fn.tables)
for i, p in enumerate(fn.paras):
    while tables and tables[0][0] == i:
        self.table_wrap(_sub(el, "p"), tables.pop(0)[1])
    pe = _sub(el, "p")
    ...（u3-autonum の形のまま）
for _, node in tables:
    self.table_wrap(_sub(el, "p"), node)
```

- 注の表は必ず `table_wrap` を通す（直接 `self.table` を呼ばない。u3-tables の `table_problems` と u3-autonum のキャプションの番号が本文の表と同じに効く）。
- docstring の箇条に「注の節の中の表は `<p>` で包む（fn の内容は `label?, p+`。付記・謝辞の `<p>` の表と同じ）」を足す。

#### 4.7 linker.py・pdfdocx.py

- `body_paragraphs`（182〜184 行）: fn のループを次にする。キャプションは "caption"、セルは "cell" になる（本文の表と同じ）。
  `pdfmatch.target_paragraphs` はキャプションを照合し、セルは照合しない（ルート2 でもセルは直さない）。`_flow_paragraphs` も caption・cell を本文の流れから外す。

  ```python
  for fn in plan.fns:
      for p in fn.paras:
          yield p, "fn"
      yield from walk([node for _, node in fn.tables], "fn")
  ```

  docstring の文脈の説明に「注の節の中の表（FnNode.tables）のキャプションは caption、セルは cell」を足す。
- `Linker.run`（208 行〜）: `fn_ids` の前で `self.fn_table = self.plan.fn_table_paras()` を作り、238 行を `if where not in ("fn",) and p.src not in self.fn_table:` にする
  （注の中の表の「1)」などを注へのリンクにしない）。`note_style`（449 行〜）の `if where in ("ref", "fn"):` も `or p.src in self.fn_table` を足す
  （`note_style` は `run` から呼ばれるので、`self.fn_table` は先に作る）。引用文献の引用・URL・図表の参照は本文の表のセルと同じくリンクする。
- `report.note_notes` は xref の順を数えるだけなので変えない。
- `pdfdocx._structure`（731 行）の `fns` に表の形を足す（ルート2 の構造の確かめが、注の表のキャプションの付け方の変化も見るように）:
  `fns = {fn.fid: (fn.number, tuple(q.src for q in fn.paras), tuple((k, t.caption.src if t.caption is not None else "") for k, t in fn.tables)) for fn in plan.fns}`。

#### 4.8 Opus の点検で通す形

設計の試作の 3 つ（注の項目の後ろ・最初の注の前・キャプション付き）と、点検の 3 つ（cap_first・cap_dup・注の見出しと表だけ）。
それぞれで、`fidelity.conflicts == []`・`missing == []`・`dtd_valid`・注の数・`<fn>` の最初の子が番号のある `<p>` であること・`table_problems == []`・`lost_autonums == []` を見る。

### 5. structure.abstract_missing_srcs（モジュール関数。report と ai_assist で共有）

```python
def abstract_missing_srcs(plan) -> list:
    """英文要旨が 1 段落もない（plan.abstract が空）のに、英文の部分の段落・表の文字を位置を決められずに除いたとき、その段落 ID
    （docx の順。空白だけ・文字のない段落を除く）。英文の部分がない原稿、英文要旨がある原稿では []。"""
    if plan.abstract:
        return []
    return [e.src for e in plan.exclusions if e.reason in EN_PART_EXCLUSIONS and not e.blank and e.text.strip()]
```

- `plan.lang` で分けない（英文の論文でも英文要旨は `plan.abstract`。英文の部分がない原稿では EN_PART の除外ができないので誤報しない）。
- 見出しだけあって段落のない英文要旨は、除外がなければ知らせない。
- AI の `set_role` の abstract で `plan.abstract` ができれば消え、残りの英文の部分の除外は `excluded_unsure` に移る。AI の exclude（429 行）は理由が違うので数えない。

### 6. report.py

`from .structure import …`（24 行）に `UNPLACED_EXCLUSIONS, EN_OTHER_EXCLUDED, EN_TABLE_EXCLUDED, FRONT_OTHER_EXCLUDED, FRONT_TABLE_EXCLUDED,
AUTHOR_TABLE_OTHER_EXCLUDED, BACK_TABLE_EXCLUDED, BACK_OTHER_EXCLUDED, EN_AUTHOR_TABLE_OTHER_EXCLUDED, abstract_missing_srcs, appendix_heading` を足す。

#### 6.1 要確認 excluded_unsure

```python
def unplaced_exclusions(r) -> list:
    """論文の中の位置を決められずに XML に出力しなかった段落（理由が structure.UNPLACED_EXCLUSIONS。文字のないものと、
    abstract_missing で知らせるものを除く）: [(段落 ID, 理由, 文字)]（docx の順）。"""
    miss = set(abstract_missing_srcs(r.plan))
    return [(s, why, t) for s, why, t in r.fidelity.excluded if why in UNPLACED_EXCLUSIONS and t.strip() and s not in miss]

# 位置を決められない除外の理由ごとの名前と、Word での直し方（_unplaced_action）
UNPLACED_GUIDE = {
    FRONT_OTHER_EXCLUDED: ("冒頭部の段落", "題目・副題・著者名・所属なら、Word でその段落に「題目（日）」「著者名（日）」「所属（日）」などのスタイルを付ける。本文なら、最初の章見出しの後ろに移す"),
    FRONT_TABLE_EXCLUDED: ("冒頭部の表", "本文の表なら、Word で最初の章見出しの後ろに移す"),
    AUTHOR_TABLE_OTHER_EXCLUDED: ("著者表の中の段落", "著者名・所属なら、Word でその段落に「著者名（日）」「所属（日）」スタイルを付ける"),
    BACK_TABLE_EXCLUDED: ("後付けの表", "注・付記・謝辞の表なら、Word で表をその節の中（注なら注の本文の後ろ）に移す。本文の表なら、引用文献・注などの見出しより前に移す"),
    BACK_OTHER_EXCLUDED: ("本文と後付けの間の段落", "前にある見出しのスタイル（「注見出し」「付記見出し」「謝辞見出し」「参考文献見出し」）を確かめる"),
    EN_AUTHOR_TABLE_OTHER_EXCLUDED: ("英文著者表の中の段落", "英文の著者名・所属なら、Word でその段落に「著者名（英）」「所属（英）」スタイルを付ける"),
    EN_TABLE_EXCLUDED: ("英文の部分の表", "資料の表なら、Word で表の前に資料の見出し（「資料1」など）を付ける"),
    EN_OTHER_EXCLUDED: ("英文の部分の段落", "英文要旨の見出し（Abstract）なら「英文要旨見出し」、英文要旨の段落なら「英文要旨」スタイルを付ける。資料なら、前に資料の見出し（「資料1」など）を付ける"),
}
```

`_unplaced_action(r)`: `rows = unplaced_exclusions(r)`。なければ None。`n = len(rows)`。理由ごとに（`UNPLACED_EXCLUSIONS` の順で）行を作る:
`f"{name} {k} 件（{_para_samples(sub, 3)}）: {how}"`（`sub` はその理由の `[(s, t)]`。`_para_samples` が `esc` と「ほか」を付ける）。件数は段落の数（表はセルの段落の数）。

- level `TO_CHECK`、key `"excluded_unsure"`。
- top: `"> **要確認: 論文の中の位置を決められず、XML に出力していない段落が {n} 件あります（6 章）。** 本文などに必要な文字なら、下の直し方で Word を直して変換し直してください（XML に入れない文字なら、そのままでかまいません）。"` の後ろに、理由ごとに `"\n>\n> - " + 行`（区切りの文字列は変数にし、f 文字列の式に `\n` を書かない）。
- checklist: `"- [ ] **位置を決められず XML に出力していない段落**（{n} 件。6 章）: 本文などに必要なら、Word でスタイル・位置を直して変換し直す"`。
- box_title: `"論文の中の位置を決められない段落 {n} 件を、XML に出力していません（要確認）"`。
- box_detail: `"本文などに必要な文字なら、Word で直してから変換し直してください（レポートの冒頭と 6 章）。"` ＋ 理由ごとの行を `"\n・"` でつなぐ。Word の直し方だけなので目印 `step()` は使わない。
- cli: `"要確認: 論文の中の位置を決められず、XML に出力していない段落が {n} 件あります（レポートの冒頭と 6 章）。本文などに必要な文字なら、docx でスタイル・位置を直して変換し直すこと。対象: {samples}"`（`samples` は全体の先頭 5 件の `_para_samples`）。

#### 6.2 要対応 abstract_missing

```python
# 英文要旨がないため資料も落ちていることの説明（_abstract_missing_action）
ABSTRACT_MISSING_APP = ("英文要旨がないため、英文の部分の資料（「資料1」などの見出しの段落と表）も位置を決められず、出力していません。"
                        "英文要旨を直すと、資料も出力されます。")

def _first_style(journal, role, default):
    return next((name for name, v in journal.styles.items() if v == role), default)
```

`_abstract_missing_action(r)`: `srcs = abstract_missing_srcs(r.plan)`。なければ None。

- `reason = {e.src: e.reason for e in plan.exclusions}`、`k = 段落の数（EN_OTHER_EXCLUDED）`、`c = 表のセルの段落の数（EN_TABLE_EXCLUDED）`。
  `count = f"段落 {k} 件"`（c があれば `+ f"と表のセルの段落 {c} 件"`）。
- `rows = [(s, plan.paras[s].text_only()) for s in srcs]`、`samples = _para_samples(rows)`。
- `styles`: 対象の段落のスタイル名（`dict.fromkeys` で重複を除き先頭 3 つ。名前が空なら「（スタイルなし）」）を「」でくくって「・」でつなぐ。
- `abs_style = _first_style(r.journal, "abstract", "英文要旨")`、`head_style = _first_style(r.journal, "abstract_heading", "英文要旨見出し")`。
- `app = ABSTRACT_MISSING_APP if c or any(appendix_heading(plan.paras[s].text_only()) for s in srcs if reason[s] == EN_OTHER_EXCLUDED) else ""`。
- level `NEEDS_ACTION`、key `"abstract_missing"`。
- top: `"> **要対応: 英文要旨が見つかりません。英文の部分の {count}を XML に出力していません（6 章）。** 英文要旨の段落に「{abs_style}」スタイルがなく、見出し（Abstract）にも「{head_style}」スタイルがないため、英文の題目・著者名・所属以外の段落の位置を決められませんでした（段落のスタイル: {styles}）。{app}英文要旨なら、Word で要旨の段落に「{abs_style}」スタイルを（見出しがあれば見出しに「{head_style}」スタイルを）付けて、変換し直してください。AI による補完では、英文要旨の最初の段落に set_role の abstract を指定すると、後ろの段落も英文要旨になります。対象の段落: {samples}"`。
- checklist: `"- [ ] **英文要旨が見つからない**（英文の部分の {count}を出力していない。6 章）: Word で英文要旨の段落に「{abs_style}」スタイルを付けて変換し直す"`。
- box_title: `"英文要旨が見つかりません（要対応）"`。
- box_detail: top と同じ説明（「英文要旨の段落に…変換し直してください。」まで。`app` を含む）＋ AI の状態で 1 文:
  `r.ai.mode == "none"` → `"AI による補完を使うときは、" + step("ai_choose") + "変換し直すと、AI が英文要旨の段落を指定できます（set_role の abstract）。"`、
  `ai_pending(r)` → `step("answer_apply") + "と、AI の指定が反映されます。"`、それ以外（API・回答を反映した後の手動）→ `"AI の回答で直すときは、英文要旨の最初の段落に set_role の abstract を指定してもらいます。"`。
  最後に `"\n対象の段落: " + samples`（区切りは変数に出す）。
- cli: `"要対応: 英文要旨が見つかりません。英文の部分の {count}を XML に出力していません（レポートの冒頭と 6 章）。{app}docx で要旨の段落に「{abs_style}」スタイルを付けて変換し直すこと（AI による補完では set_role の abstract）。対象: {samples}"`。
- 対象の段落は `excluded_unsure` から外す（`unplaced_exclusions` の `miss`）。

#### 6.3 actions() の並び（1656〜1660 行）

単位どうしの点検で決めた head の並びにする（u3-tables・u3-autonum・u4 が先に足した後の形）:
`_fidelity, _supplement, _dtd, _table_shape, _upload, _ai_error, _ai_pending, _partial, _forced, figure_body, _textbox_undecided, _textbox_place,
_textbox_figure_text, _unplaced（この単位）, images, lost, lost_autonum, _abstract_missing（この単位）, _image_crop, _image_edits, _style_hidden, _abstract_ja,
_app_after_refs, _note_overlap, _float_ref, _fn_guess, _newline` ＋ `pdf_actions`。

#### 6.4 6 章（render 1855〜1860 行）

理由の列に印を足す（docx の文字の列は変えない）: `abstract_missing_srcs(plan)` に入る段落は `reason + "（要対応）"`、ほかの `UNPLACED_EXCLUSIONS` の段落は `reason + "（要確認）"`。

### 7. ai_assist.build_request（330〜334 行の「出力から除外」のループの後ろ）

`from .structure import …`（30 行）に `abstract_missing_srcs` を足し、ループの後ろに:

```python
miss = abstract_missing_srcs(plan)
if miss:
    shown = ", ".join(miss[:8]) + (" ほか" if len(miss) > 8 else "")
    lines.append(f"- 英文要旨の段落が見つからない（英文の部分の {shown} を出力から除外した）。英文要旨なら、その最初の段落に set_role の abstract を提案（後ろの段落も英文要旨になる）")
```

除外の各行と `set_role_hint` は変えない（既存テストが行の末尾で確かめている）。注の表のセルは除外でなくなるので、依頼文から「出力から除外」の行が消えるだけ。

### 8. app.py: REPASTE_KEYS（242 行）

`REPASTE_KEYS` に `"abstract_missing"` を足す（文が AI の set_role を勧めるので、手動モードで回答を反映した後も貼り直せるように。`textbox_undecided` と同じ理由）。
上のコメント（240〜241 行）と `answer_box_open` の docstring（248〜250 行）に「英文要旨が見つからない（abstract_missing）」を足す。
`excluded_unsure` は足さない（Word の直し方だけを案内する）。app.py は u2（0.30.0）が `_run` などを作り直した後の形の上で直す。

### 9. 書き方の注意

- f 文字列の式の中にバックスラッシュ・外側と同じ引用符を書かない（`"\n>\n> - "`・`"、"` などの区切りは変数に出す。`tests/test_syntax.py`）。
- レポートの文に JATS のタグを書かない（書くなら `md_tag`）。新しい目印（STEP_NAMES）は足さない。
- Result の欄は足さない。

## テスト

AI の回答は必ず `{"placements": [], "operations": [...], "notes": []}` の形で書く（u1 で operations が必須になるため。操作がなくても `"operations": []`）。
docx は `tests/make_fixtures.py` の部品で `tmp_path` に作る（fixture を作り直さない。`make_fixtures.py` の既定の出力を変えない）。
`tests/test_report.py` はないので、レポートの文のテストは `tests/test_structure.py` に置く（`textbox_figure_text` のテストと同じ）。

### tests/test_notes.py（注の節の表）

- `test_table_in_notes_section_is_output`: `make_article` の本文に `[sec1, body「本文の表1と注1)。」, tab_cap「表1　本文の表」, table, fn_head「注」, fn_body「1) 注の本文。」, table([[cell("注の表A"), cell("2)")]]), fn_body「続きの段落。」, fn_body「2) 次の注。」]`。
  期待: `fid.ok`・`final_ok`・`dtd_valid`、fn1 の子が `p, p/table-wrap, p` の順、fn2 は別、`plan.exclusions` に `BACK_TABLE_EXCLUDED` がない、注の表の tid は本文の表の後ろ（T2）、
  セルの「2)」は xref にならない、判断の一覧（category note）に「注の節の中の表を、注 1件目の中に出力した」の記録、`res.table_problems == []`・`res.lost_autonums == []`。
- `test_table_before_first_note_goes_after_first_paragraph`: fn_head の直後に表、その後に「1) 注の本文。」「続き。」。期待: fn1 の子が `p（番号のある 1 段落目）, p/table-wrap, p`、
  `<fn>` の最初の子の文字が「1)」で始まる、判断の一覧に「最初の注の前にあった表を、その注の 1 段落目の後ろに入れた」。
- `test_table_caption_in_notes_section`: (1) fn_body「1) 注の本文。」, tab_cap「表2　注の表」, table。期待: `table-wrap/caption` が「表2　注の表」、fn1 の `p` にキャプションの文字がない、本文の「表2」が注の表の id にリンク。
  (2) cap_first: fn_head → tab_cap「表2　注の表」 → table → fn_body「1) 注の本文。」。期待: fn は 1 件（番号 1）、fn1 の 2 つ目の子が caption つきの `p/table-wrap`、本文の「表2」がその表にリンク、番号のない注がない。
  (3) cap_dup: 本文に表1、注の表のキャプションも「表1　注の表」。期待: 要確認 `float_ref` が出て、本文の「表1」はリンクされない（回帰として固定）。
- `test_table_only_notes_section_is_unplaced`: (1) fn_head と表だけ。期待: セルの段落は `BACK_TABLE_EXCLUDED`、actions に `(要確認, excluded_unsure)`、`needs_action` は偽、注の見出しは builder の「注の本文がない」除外。
  (2) fn_head → tab_cap → table で文書が終わる（引用文献の見出しの後ろに置かない形も）。期待: キャプションとセルが `BACK_TABLE_EXCLUDED`、`excluded_unsure`、`fid.conflicts == []`。
- `test_image_in_note_table_is_output`: 注の表のセルに drawing の画像。期待: `lost_images == []`、`res.images` にその画像。
- `test_merged_and_numbered_cells_in_note_table`: 注の表に縦結合・gridSpan のある行（u3-tables の部品）と、セルに `list_item(num_id=7)`（u3-autonum）を置く。
  ルート1 で `table_problems == []`・`lost_autonums == []`・不変性チェック・DTD が合格。sample_pdfcheck と同じ作り方の PDF を作れるならルート2 も（`verify_supplement` 合格）。作れなければルート1 だけでよい。

### tests/test_pdfmatch.py

- `test_note_table_cells_are_not_targets`: 上の注の表（キャプション付き）の原稿の plan で、`target_paragraphs` にセルの段落がなく、キャプションの段落がある。

### tests/test_pipeline.py（既存を直す）

- `test_blank_paragraphs_in_front_and_back_tables_are_excluded`（391 行〜）: 416 行の空白の除外を 4 件にする（注の表のセルの全角空白は出力される）。
  419 行を、「注の表」が除外にないこと（`"注の表" not in reasons`）と、XML の `fn` の中の `table-wrap` にあることに変える。冒頭の囲みの表・英文の表の理由（418・420 行）は今のまま
  （この原稿では `excluded_unsure` も出るが、このテストは actions を見ない）。

### tests/test_structure.py

- 英文要旨のない docx を作る関数 `_no_abstract_style_docx(tmp_path, journal_lang=…)`: `mf.Builder()`・`mf.front_ja`・本文・引用文献のあとに `english = mf.front_en(b, …, ["First abstract.", "Second abstract."])` を作り、
  `del english[5]`（Abstract 見出し）をして、要旨の段落を `mf.para(None, …)`（スタイルなし）に置き換えてから `b.save`（形は `protos/u5-exclusions/repro.py` の b1）。
- `test_abstract_without_style_or_heading_needs_action`: 期待: `plan.abstract == []`、actions に `(要対応, abstract_missing)`、`res.needs_action`、`excluded_unsure` に同じ段落が出ない、
  top・cli に段落 ID と「英文要旨」スタイル名、6 章のその段落の理由に「（要対応）」。
- `test_abstract_missing_with_english_article`: 同じ docx を `dataclasses.replace(journal, lang="en")` で変換しても `abstract_missing`。
- `test_abstract_missing_mentions_appendix`: 上の docx の要旨の後ろに `mf.para(None, "Appendix 1 …")` と表を足す。期待: 文に `ABSTRACT_MISSING_APP` があり、件数が「段落 k 件と表のセルの段落 c 件」に分かれる。
- `test_no_english_part_does_not_report_missing_abstract`: 英文の部分（front_en）を入れない原稿（`mf.Builder` で front_ja＋本文＋引用文献＋`tail`）。期待: `abstract_missing` も `excluded_unsure` もない。
- `test_abstract_heading_with_plain_paragraphs_is_ok`: 見出しは残し要旨だけ標準スタイル（b2）。期待: `plan.abstract` 2 段落、知らせなし。
- `test_extra_english_paragraph_is_unplaced`: 英文の著者表と Abstract 見出しの間に標準スタイルの英文の段落を足す（英文要旨はある）。期待: `EN_OTHER_EXCLUDED`、`(要確認, excluded_unsure)`、`needs_action` は偽。
- `test_front_decoration`: 単体テスト。記号だけ（❚×40）→ 真、誌名行（全角空白・半角空白・空白なし）→ 真、空 → 真、「受付日　2025年」→ 偽、`front_lines` を空にした誌名行 → 偽、
  数式（`Atom(kind="math")`）だけの段落 → 偽、画像だけの段落 → 真。
- `test_front_paragraph_other_than_decoration_is_unplaced`: 和文の冒頭（題目の前）に標準スタイルの文字の段落を足す。期待: `FRONT_OTHER_EXCLUDED`、`excluded_unsure`。テンプレートの誌名行・装飾行は `FRONT_DECORATION_EXCLUDED` のまま。
- `test_abstract_style_aliases`: `JournalConfig.load().styles` で「英文要約」が abstract、「英文要約見出し」が abstract_heading、値が abstract の最初の名前が「英文要旨」、abstract_heading の最初が「英文要旨見出し」。
  `front_lines` が読めること。
- `test_unplaced_action_texts`: 理由が 2 種類・合わせて 7 件の原稿（冒頭部の段落 4 件と英文の部分の段落 3 件など）で、top に理由ごとの行と抜粋 3 件＋「ほか」、checklist に件数、
  `colab.step_text(box_detail, …)` が例外にならず目印が残らない、cli に段落 ID、6 章の理由に「（要確認）」。
- `test_no_unplaced_notices_for_fixtures`: `sorted((Path(__file__).parent / "fixtures").glob("*.docx"))` の全件（`ALL_DOCS` には 4 件がないので glob で回す）を
  `Options(ai_mode="manual", convert_metafiles=False)`（回答なし。AI が必要な fixture で `AIRequiredError` にしないため）で変換し、`excluded_unsure`・`abstract_missing` が出ない（回帰の守り）。
- `test_two_abstract_heading_styles`（単位どうしの点検の決定）: 「英文要旨見出し」の見出しと、スタイル名「英文要約見出し」の見出しが両方ある docx（スタイルは document.xml と styles.xml を書き換えて足す）。
  期待は u6 の中止（`StructureConflictError`。英文要旨の見出しが 2 つ）。u5 の時点では `pytest.mark.xfail(strict=True, reason="u6 で中止にする")` を付け、u6 の実装者が印を外す。`StructureConflictError` はテスト関数の中で import する（u5 の時点ではないので、モジュールの先頭に書かない）。

### tests/test_ai.py

- `test_set_role_abstract_fixes_missing_abstract`: 上の docx に `ai_mode="manual"`・回答 `{"placements": [], "operations": [{"op": "set_role", "src": <最初の要旨の段落>, "role": "abstract"}], "notes": []}`。
  期待: `plan.abstract` 2 段落、`abstract_missing` なし。回答の前の依頼文に「英文要旨の段落が見つからない」の行がある。

### tests/test_app.py

- `test_manual_fields_stay_for_repaste`（312 行〜）の `cases` に abstract_missing を足す（英文要旨のない docx と、`"operations": []` の回答）か、別のテストで、
  手動モードで回答を反映した後に `abstract_missing` が残ると `answer_box_open` が真であることを確かめる。

## 回帰の確かめ（基準との比較で想定する違い）

0.30.0 を反映した後の main（u1 の作り直した fixture）の出力を基準にし、fixture 15 件と tests/private の 10 件（ルート1。PDF のある 6 件はルート2 も。AI は manual・回答なし）を比べる。
取るもの・保存の仕方は計画の共通の作業（XML のハッシュ・actions の key と level・除外の理由ごとの件数・ZIP の一覧・終了コード。本文は保存しない）。

- 想定する違いは tests/private のテンプレートだけ: 英文要旨（見出し d87・段落 d88）と資料 2 つ（d90 と表 T2、d186 と表 T3）ができ、英文の部分の除外（段落 4・セル 121）が 0 になる。
  知らせは増えない（`abstract_missing` は別名のために出ない）。
- テストデータ1〜5 の 9 件と fixture 15 件: XML・除外・actions・終了コードとも違い 0。冒頭部の装飾の理由の文言は変わらない。
- AI の依頼文: fixture では変わらない（注の表のある原稿でだけ「出力から除外」の行が消える）。
- 表の ID: 注の表と資料の表の両方がある原稿では資料の表の T 番号が 1 つずつ後ろにずれる（実際の原稿にはない形）。
- 注の表のキャプションの番号が本文の表と重なると、本文の「表N」がリンクされなくなり要確認 `float_ref` が出る（今は本文の表にリンクされる）。
- 全テスト（1298 件＋追加分）を回す。落ちてよいのは直すと決めた `test_blank_paragraphs_in_front_and_back_tables_are_excluded` だけで、それも直す。並びを確かめる既存のテスト
  （test_floats 731 行・test_pipeline 867 行・test_links 180 行・test_ai 1396 行・test_notebook 271 行）が落ちないこと（新しい Action が fixture で鳴らないことの確かめも兼ねる）。
- u6 を入れた後に、u6 の sweep と `protos/u5-exclusions/count.py` の件数（位置づけが不明の除外 0、テンプレートの英文の部分の除外 0）を、両方が入った状態でもう一度確かめる。

## ほかの単位・ルート2・AI 補完・画面との関係

- u3-tables・u3-autonum（0.30.0）: 注の表は `table_wrap` を通すので、u3-tables の `table_problems`（`TableProblem.name`〈祖先の table-wrap の id から「表 T2」〉）と、u3-autonum のキャプション・セルの番号がそのまま効く。
  `builder.fn` は u3-autonum の形の上に 3 か所足すだけ。builder.py の順は u3-tables → u3-autonum → u5。
- u4（0.30.0）: 触る関数は重ならない。注の表のセルの画像も `export_images` を通るので、トリミングの切り取りが効く。
- u6（0.31.0、この単位の後）: `build_back` の見出しの枝を u6 も直す（並びは 4.4）。後付けの同じ種類の見出しが 2 つあると u6 が中止するので、「注」が 2 つある原稿で注の表の入れ先は考えなくてよい。
  見出しが 2 つで pending の表がある形は、flush で表が除外され、そのあと u6 が中止する。英文要旨の別名で「英文要約見出し」と「英文要旨見出し」の両方がある原稿は、u6 で中止になる（テストは xfail で用意する）。
  `article.py`・`structure.py`・`app.py`・`report.py` は u5 → u6 の順。
- `tests/private/review-repros/reproduce.py` の note-table と abstract-plain は、この単位のテストとして tests/ の正式なテストに移した項目として最後の報告で挙げる。
- ルート2: 補った docx はルート1 と同じ処理で変換するので、知らせは同じように出る。注の表のセル（cell）は照合も直しもしない。キャプションは今まで fn の段落として照合の対象で、これからも caption として対象。
  `_flow_paragraphs` だけが注の表のある原稿で変わる。`pdfdocx._structure` の fns に表の形を足す（4.7）。
- AI 補完: 英文の部分の段落は `set_role` の abstract で英文要旨にできる。冒頭部・本文と後付けの間の段落は `set_role_hint` が依頼文に指定できる役割を書く。表のセルは `set_role` では変えられない（今のまま）。
  注の表は `plan.tables` に入るので、依頼文の「図・表・注・数式」に `[T2] 表 …` として載る。
- 画面: どちらも `report.actions()` に `Action` を足すだけで、冒頭・14 章・Colab の枠・コマンドラインに出る。`abstract_missing` は終了コード 1。`app.AppState.REPASTE_KEYS` に `abstract_missing` だけを足す。
  中止（終了コード 2）はこの単位にはない。

## 利用者向けの文

- 要確認 `excluded_unsure`（黄色の枠）: 「論文の中の位置を決められない段落 N 件を、XML に出力していません（要確認）」。本文は「本文などに必要な文字なら、Word で直してから変換し直してください（レポートの冒頭と 6 章）。」と、
  理由ごとの行（例: 「英文の部分の段落 2 件（d21「…」、d22「…」）: 英文要旨の見出し（Abstract）なら「英文要旨見出し」、英文要旨の段落なら「英文要旨」スタイルを付ける。…」）。
  レポートの冒頭は太字の 1 文に理由ごとの行が続き、14 章は 1 行。6 章の理由の列に「（要確認）」。
- 要対応 `abstract_missing`（赤い枠）: 「英文要旨が見つかりません（要対応）」。本文は 6.2 の top と同じ説明（スタイル名は jasme.toml から「英文要旨」「英文要旨見出し」、除外した段落のスタイル名、
  資料も落ちているときはその 1 文）と、AI の状態に応じた 1 文（`step("ai_choose")`・`step("answer_apply")`）。コマンドラインの終了コードは 1。6 章の理由の列に「（要対応）」。
- 注の表は知らせにしない。判断の一覧（4 章）に、注に入れた表ごとに「注の節の中の表を、注 N件目の中に出力した（…）。J-STAGE の画面で注の中の表が表示されるかは確かめていないので、プレビューで確かめる」を記録する。

## 文書の更新（CLAUDE.md は案だけ）

文書は 0.31.0 の最後に 1 人（Opus）がまとめて直す。この単位の実装者は、下の内容を作業の報告に書いて渡す。

- `docs/DESIGN.md` 4.3: 除外を「意図した除外」と「位置を決められない除外（`UNPLACED_EXCLUSIONS`。要確認 `excluded_unsure`）」に分け、直し方 1 の分類を書く。
  英文要旨がないときの要対応 `abstract_missing`、冒頭部の装飾の判定（`front_decoration`・jasme.toml の `front_lines`）を書く。付記・謝辞の `<p>` の表の説明に、注の節の表も `<p>` で包むことを足す。
- `docs/STYLE_MAPPING.md`: 注見出しの行に「注の節の中の表は直前の注に入れ、`<fn><p><table-wrap>` で出す。直前の「表キャプション」の段落はキャプションになる。最初の注より前の表は最初の注の 1 段落目の後ろに入れる。
  注のない注の節の表は除外して要確認」。英文要旨の行に「英文要約見出し / 英文要約（テンプレートの別の版。同じ役割）」。
- `docs/JSTAGE_NOTES.md`: `fn` の中の `p/table-wrap` は DTD では妥当だが、J-STAGE での表示は確かめていない。
- `docs/USAGE.md` の知らせの一覧（「たとえば次のものです」）: 要対応「英文要旨が見つかりません」（abstract_missing）と要確認「論文の中の位置を決められない段落」（excluded_unsure）。
- `docs/ARCHITECTURE.md`: `article.FnNode.tables`・`ArticlePlan.fn_table_paras`、structure の除外の理由の定数・`UNPLACED_EXCLUSIONS`・`EN_PART_EXCLUSIONS`・`abstract_missing_srcs`・`front_decoration`、
  report の 2 つの Action と actions の並び（6.3）、`config.JournalConfig.front_lines`、`app.AppState.REPASTE_KEYS`。行数の表は `wc -l` に合わせる。
- `docs/DEVELOPMENT.md`: structure.py の行、守るべき原則 8 の `app.AppState.REPASTE_KEYS` の一覧に `abstract_missing`、守るべき原則 3 に「除外の理由は structure の定数で書き、位置を決められずに除くときは `UNPLACED_EXCLUSIONS` の理由を使う（要確認で知らせる）」。
- `docs/REVIEW_2026-11.md`: K7・K12 を 0.31.0 で直したと記録する（表の行番号も今のコードに合わせる）。新しい未修正の項目を足す（下の「直さず REVIEW に記録するもの」）。
- structure.py の冒頭の docstring（⑤ build_back に注の表、⑥ build_front_en に英文の部分の除外の理由）、`model.Exclusion` の docstring（「位置を決められない理由の除外は要確認・要対応で知らせる〈report._unplaced_action・_abstract_missing_action〉」）。
- CLAUDE.md の案（実装者は直さない。利用者の承認を待つ）: 「最優先の原則」の 2 つ目の箇条の後ろに、次の 1 文を足す案。
  「論文の中の位置を決められずに除く段落は、`structure.UNPLACED_EXCLUSIONS` の理由で記録し、要確認（`excluded_unsure`）で知らせる。英文要旨が 1 段落もなく英文の部分を除いたときは要対応（`abstract_missing`）。」

## 文書とコードの食い違い

- `docs/REVIEW_2026-11.md` の表の K7 は「structure.py 1754〜1762」、K12 は「1962〜1972」と書いているが、0.29.0 では 1921〜1938 行（build_back の表の枝）と 2130〜2143 行（build_front_en の最後の else）。0.28.1 の時点の行番号のまま。直す。
- `docs/DESIGN.md` 4.3 の「出力しない段落」の例に、位置を決められずに除く段落（後付けの表・英文の部分の段落など）と、それに知らせがないことが書かれていない。直す。
- `docs/JSTAGE_NOTES.md` は「注（fn）の子要素は p だけ」とだけ書き、p の中に置けるもの（table-wrap など）に触れていない。足す。
- `model.Exclusion` の docstring は「必ずレポートに一覧で出す」とだけ書き、要確認・要対応で知らせるのは一部の理由だけであることを書いていない。直す。
- 設計の材料はレポートのテストを `tests/test_report.py` に置くとしていたが、そのファイルはない。`tests/test_structure.py` に置く（既存の書き方に合わせる）。
- u3-autonum の設計書の `fn` の手本は `getattr(fn, "tables", [])` を使っているが、この単位で `FnNode.tables` を足すので `fn.tables` と書く。

## 新しく見つけた問題（この単位で直すもの／直さず REVIEW に記録するもの）

この単位で直すもの:

- 注の見出しの直後の「表キャプション」から番号のない注ができる形（cap_first）: 直し方 4.3 の (a)。
- 注の表を判断の一覧に記録するのが最初の注の前の表だけだった: 4.2 の `note_table` で全件を記録。
- 冒頭部の数式だけの段落が装飾とみなされ、知らせなく落ちる: `front_decoration` が text・image 以外のアトムで偽を返す。
- `abstract_missing` を勧める AI の操作が、手動の欄が閉じて使えない: `REPASTE_KEYS` に足す。
- 注の表のキャプションに注番号のリンクが付きうる: `fn_table_paras` にキャプションも入れる（今までキャプションは注の段落としてリンクされなかったので、それと同じにする）。

直さず REVIEW に記録するもの:

- 英文の部分にスタイルがない原稿（英文題目も標準）は front_en に切り替わらず、英文の題目・著者表・要旨が引用文献の項目になり、知らせがない（再現は `protos/u5-exclusions/allplain.py` の形。0.31.0 では直さない）。
- `docx_reader.read_notes` は、Word の脚注・文末脚注の中の表を段落の並びに開く。文字は残るが表の形は XML に出ない（コードを読んで確かめた）。
- 付記・謝辞・資料・注の表のセルの段落には `plan.region`・`plan.locations` を付けていないので、6 章・知らせの位置の欄が空になる（`set_role_problem` が変えられないと返すので害はない）。

## 未決のこと（利用者の返事待ち／実装のときに確かめること）

利用者の返事待ち:

- J-STAGE の画面で `<fn><p><table-wrap>` が表示されるか（試験登載で確かめてもらう）。確かめられるまで、判断の一覧への記録だけにする。
- CLAUDE.md の案の文（上）。

実装のときに確かめること:

- `front_lines` の値が、u1 で作り直した fixture のテンプレートの d1 の文字と同じこと（全角空白を含む）。
- u1 で sanitize し直した fixture のテンプレートの英文要旨のスタイル名（「英文要旨」か「英文要約」か）。どちらでも別名で英文要旨になるが、`test_abstract_style_aliases` と fixture の glob テストで確かめる。
- AI の placements の対象（位置を決められない図表）に、注の表が入らないこと（注の表は `plan.tables` に入るが、仮の位置の図表ではない）。
- 「表キャプション」の段落の役割が `build_back` の items で `table_caption` になっていること（`fn_role` の判定の前提）。AI が `set_role` で役割を変えた段落も items の役割で判定する。
- `test_merged_and_numbered_cells_in_note_table` のルート2 を作れるか（作れなければルート1 だけ）。

## 点検の指摘の反映表

| 重さ | 題 | 反映した節 |
|---|---|---|
| major | 計画者の決定「jasme.toml の styles に英文要約見出し・英文要約を別名で足す」が設計に入っていない | 直し方 3、テスト（`test_abstract_style_aliases`）、回帰の確かめ、文書の更新（STYLE_MAPPING） |
| major | 注の見出しの直後のキャプションと表から、番号のない別の注ができる | 直し方 4.3 の (a)・4.4、テスト（`test_table_caption_in_notes_section` の (2)、`test_table_only_notes_section_is_unplaced` の (2)） |
| major | 注の表を判断の一覧に記録するのが、最初の注より前の表だけ | 直し方 4.2 の `note_table`（すべての注の表を記録。where の文は k=1 に合わせた）、利用者向けの文 |
| minor | abstract_missing の文が資料も落ちていることを伝えない／件数が段落とセルで分かれない | 直し方 6.2（`ABSTRACT_MISSING_APP`・`count`）、テスト（`test_abstract_missing_mentions_appendix`） |
| minor | 6 章の「（要確認）」が abstract_missing の段落にも付く | 直し方 6.4 |
| minor | abstract_missing は AI の set_role を勧めるのに、1 画面版の手動の欄が閉じる | 直し方 8（REPASTE_KEYS に足す）、テスト（test_app） |
| minor | 注の表のキャプションの番号が本文の表と重なると、本文の「表N」がリンクされなくなる | 回帰の確かめ、テスト（`test_table_caption_in_notes_section` の (3)） |
| minor | キャプションの判定で role_of を呼び直すと role_origin を書き換える | 直し方 4.2・4.4（`fn_role`） |
| minor | front_decoration が数式だけの段落も装飾とみなす | 直し方 2（段落を受け取り、text・image 以外のアトムで偽）、テスト（`test_front_decoration`） |
| minor | 回帰の守りのテストが fixture の一部しか見ない／REVIEW への記録が抜けている | テスト（`test_no_unplaced_notices_for_fixtures` を glob で）、新しく見つけた問題（REVIEW に記録） |
| minor | EN_OTHER の直し方が、スタイルのない見出し「Abstract」を想定していない | 直し方 6.1 の `UNPLACED_GUIDE` |
