# 単位 u3-tables（0.30.0）: 表の縦結合・飛ばしたグリッドと、表の形の確かめ

## 要点

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

## 再現（確かめたこと）

再現・試作のスクリプトは `docs/fix_plan_2026-11/protos/u3-tables/`（設計者）と `docs/fix_plan_2026-11/protos/review-u3-tables/`（点検者）にある。どれも作業用フォルダ（scratchpad）のパスを前提に書いてあり、出力のフォルダ・生成した docx は残っていない。手本として読むもので、そのまま実行するものではない。`scan_private.py`・`count_unmatched.py`・`scan_outputs*.py` は tests/private の原稿を読むので、リポジトリのテストにはしない。

| # | 形（テストでの名前） | 0.29.0 で起きたこと | スクリプト |
|---|---|---|---|
| 1 | 3 行・2 列で、2 行目が 2 列とも継続（both_cont）。継続に文字がある版（cont_text）も同じ | docx は 3 行なのに tr は 2 つ。A・B に `rowspan="2"` が残り、C・D が 3・4 列目にずれる（占有列数 [2,4]） | `repro_vmerge.py`（形は `shape.py`） |
| 2 | 1 列目が 3 行とも結合、2 列目は 2 行目だけ継続（col1_all_col2_row2） | A が rowspan=3、B が rowspan=2。表は 2 行なので tbody の外にはみ出し、D は 3 列目（[2,3]） | `repro_vmerge.py` |
| 3 | 見出し行 2 行のうち 1 列目が本文の 1 行目まで結合（head_to_body） | 2 行しかない thead に `th rowspan="3"`。tbody の 1 行目はセル 1 つ（[2,2,1,2]） | `repro_vmerge.py` |
| 4 | 見出し行のセルがすべて本文の 1 行目まで結合（head_all_to_body） | 本文の 1 行目がすべて継続なので消え、thead の th が `rowspan="2"` ではみ出す | `repro_vmerge.py` |
| 5 | 3 列の表で 2 行目だけ前（before_plain）か後ろ（after_plain）に 1 グリッド飛ばす | 2 行目が左に詰まる（[3,2,3]）。docx_reader は gridBefore・gridAfter・wBefore・wAfter・tblGrid を 1 つも読んでいない | `repro_grid.py` |
| 6 | 列 1 の継続が gridBefore=1 の行にある（before_vmerge_lost） | builder の col が 0 から数えるので継続を列 0 と取り違え、結合が消えて空の td | `repro_grid.py` |
| 7 | 列 0・1 がどちらも結合元で、継続が gridBefore=1 の行にある（before_vmerge_wrong） | 継続が列 0 の A に結合され、A が rowspan=2 | `repro_grid.py` |
| 8 | 結合元が 2 列ぶん・継続が 1 列（span_mismatch_wide_top）と、その逆（span_mismatch_narrow_top） | 2 行目が 4 列ぶん（[3,4,3]）／ 2 列ぶん（[3,2,3]）。継続を開始列だけで結合元に結び付け、幅を比べていない | `repro_vmerge.py` |
| 9 | 1 行目の列 1 が結合元、2 行目に列 0〜1 の横に広いセル、3 行目の列 1 に継続（owner_not_cleared） | `owner.pop(col)` は開始列（0）しか消さないので、3 行目の継続が 1 行目の A に結合。A の rowspan=2 が 2 行目のセルと重なり、3 行目は 1 列ぶん（[2,2,1]） | `repro_vmerge.py` |
| 10 | 各行の先頭のセルが `gridSpan w:val="0"`（span0_uniform）。その右に restart（span0_merge） | 読み取りは `int(wval(gs, "1") or 1)` なので 0 のまま（"-1" は -1、"abc" は ValueError で変換が落ちる）。span0_uniform は、設計どおりの形の確かめだと docx の列数 1 と比べて誤って要対応になる。span0_merge は結合元の列を取り違え、結合が黙って消える | `review-u3-tables/edge2.py` |
| 11 | 見出し行 1 行 + セルのない行（`<w:tr/>`）だけの本文（cellless_only_body） | `<table><thead>…</thead></table>` になり DTD 不合格（要対応 dtd）。直した後も同じ（既存の問題。DTD が知らせる） | `review-u3-tables/edge.py` |

どの形も（11 を除き）不変性チェック・最終チェック・DTD 検証は合格で、`actions()` は空だった。

根: `builder.py` 654〜707 行の `table` は 1 回の走査で `rowspan` を数え、その後の書き出しで「すべてのセルが継続の行」の tr を `if not len(tr): sec.remove(tr)` で消す。消した行も `rowspan` に数えたままになる。結合を覚える `owner` は「開始列 → セル」の辞書で、(1) 継続の幅（gridSpan）を結合元と比べない、(2) 横に広いセルが覆った列の結合元を消さない、(3) 見出し行と本文の行の区切り（`n_head`）を考えない、(4) 行の先頭の列を常に 0 とする（`docx_reader` が `w:gridBefore`・`w:gridAfter` を読まず、`model.Row` に持っていない）。

試作で確かめたこと:

- 試作（`proto.py`。実行時に `Reader.read_table` と `Builder.table` を差し替える）を入れると、上の 1〜9 の 13 通りがすべて占有列数のそろった形になり、形の確かめの問題は 0 件。不変性チェック・DTD 検証は合格のまま。見出し行をまたぐ結合と幅の違う継続では、10 章の警告が 1 件ずつ出た。
- 試作を入れても全テスト 1298 件が通り、fixtures 15 件と tests/private 10 件の出力 XML は 0.29.0 とバイト単位で同じだった（点検者が 50 個の XML を cmp で比べて差 0）。ただしこれは u1 で fixture を作り直す前の fixture での結果なので、実装のときに作り直した後の基準と比べ直す。
- 形の確かめ（`shape.py`）を今の出力に当てても誤報はない: fixtures と tests/private の 25 件の表 101 個で 0 件、全テストの中の 653 回の変換の表 468 個でも 0 件（`shapeplugin.py`。読めなかった 3 回は最終出力をわざと壊すテストのもの）。
- 実際の原稿の docx 側の数え（`scan_private.py`・`count_unmatched.py`）: gridBefore・gridAfter・wBefore 0、tblHeader 0、行ごとの列数の不ぞろい 0、tblGrid との不一致 0、入れ子の表 0、結合元のない継続・幅の違う継続・見出し行をまたぐ結合・すべて継続の行 0。vMerge はテストデータ2・3 と fixture `sample_full` にだけある（`count_unmatched.py` はテキストボックスの中の表を数えていない）。
- 点検の edge.py で、docx がもともと不ぞろいの表（irregular・irregular_merge）、変更履歴で削除された結合元の行（deleted_top）、gridBefore の行がすべて継続（dropped_with_before）、セルのない行（cellless_row）で形の確かめが鳴らないことを確かめた。継続側の文字が本文の 1 行目のセルに出ること（head_cross_text）も確かめた。

## 直し方

行番号は 0.29.0 のもの。同じファイルを触る順（builder.py・model.py・pipeline.py・report.py・docx_reader.py・structure.py・make_fixtures.py）の最初がこの単位なので、0.29.0 の行番号のまま読める。

### 1. 中間表現（`src/jasme_jats/model.py`）

- `Row`（162 行付近）に 3 つの欄を足す（既定値つき）:
  ```python
  @dataclass(eq=False)
  class Row:
      cells: list = field(default_factory=list)
      header: bool = False
      grid_before: int = 0    # 行の前で飛ばしたグリッドの列の数（w:trPr/w:gridBefore。セルのない列）
      grid_after: int = 0     # 行の後ろで飛ばしたグリッドの列の数（w:trPr/w:gridAfter）
      number: int = 0         # docx の表の何行目か（1 から。変更履歴で削除して読み飛ばした行も数える。警告の行の番号）
  ```
- `Cell.rowspan`（`rowspan: int = 1`）を消す。どこからも読み書きされていない（src と tests を grep して確かめた。`Cell(` を作るのは docx_reader と test_structure の 1 か所で、どちらも rowspan を渡していない）。builder は「中間表現は書き換えない」方針で rowspan を自分の辞書で持つので、誤解のもとになる。
- `LostImage`（258 行）の後に足す:
  ```python
  @dataclass
  class TableProblem:
      """出力した XML の表の形の崩れ（pipeline.table_problems が変換の後に調べる。要対応 table_shape）。

      不変性チェックは文字しか、DTD 検証は要素の並びしか見ないので、出力した表の形（行ごとの列の数・セルの重なり・縦の結合が
      見出し行や本文の行の外にはみ出していないか・セルのない行）はここで確かめる。崩れていれば変換ツールの不具合の可能性がある。
      """
      tid: str            # model.Table.tid（組み立ての記録がない表は空）
      where: str          # Word で探す手がかり（builder の where。docx_reader.table_where の形）
      name: str           # 知らせに出す名前（「表 T1」「図 F1 の中の表」。どちらの id もなければ where）
      problems: list      # 問題の文の一覧（同じ文は 1 つ）
  ```

### 2. 読み取り（`src/jasme_jats/docx_reader.py`）

- モジュールの関数を 2 つ足す（`read_table` の前）:
  ```python
  def _grid_span(gs) -> int:
      """w:gridSpan の値（横に結合した列の数）。0・負・数でない値は 1（Word などは 1 として表示する）。"""
      try:
          return max(1, int(wval(gs, "1") or 1))
      except ValueError:
          return 1


  def _grid_skip(trpr, name) -> int:
      """w:trPr の w:gridBefore / w:gridAfter（行の前後で飛ばしたグリッドの列の数）。なければ 0。負・数でない値も 0。"""
      el = trpr.find(w(name)) if trpr is not None else None
      if el is None:
          return 0
      try:
          return max(0, int(wval(el, "0") or 0))
      except ValueError:
          return 0
  ```
- `Reader.read_table`:
  - 251 行の `row = Row(header=...)` の直後に `row.grid_before = _grid_skip(trpr, "gridBefore")`、`row.grid_after = _grid_skip(trpr, "gridAfter")`、`row.number = k` を書く（k は 249 行の `enumerate(..., 1)` の番号。読み飛ばした行も数える。`DELETED_ROW_KEPT_MSG`・`CELL_DELETED_MSG` の行の番号と同じ数え方）。
  - 265 行の `cell.gridspan = int(wval(gs, "1") or 1)` を `cell.gridspan = _grid_span(gs)` にする。
  - `w:wBefore`・`w:wAfter`（幅だけ）と `w:tblGrid` は読まない。tblGrid は Word が古い列を残すことがあり、比べる相手にしない。
- 文字ではないので `canonical_text`・`fidelity.source_texts`・`pdfdocx` は直さない（CLAUDE.md の「段落のつながり・隠し文字の規則を 3 か所で共有する」の対象外）。

### 3. 組み立て（`src/jasme_jats/builder.py`）

#### 3.1 定数（40 行の `ALL_ROWS_DELETED_MSG` の後ろ）

```python
# 表の縦の結合を XML の表の形に合わせて変えたときの 10 章の警告（文字は落とさない。Action にはしない）
TABLE_HEAD_SPAN_MSG = ("{where}: 見出し行から本文の行へ続く縦の結合を、見出し行の終わりで止めました（本文の行の側は別のセルとして"
                       "出力しました。文字は落としていません）。")
TABLE_SPAN_MISMATCH_MSG = ("{where}の {row} 行目: 縦に結合したセルの幅（横に結合した列の数）が上の行のセルと違うため、結合せずに"
                           "別のセルとして出力しました。Word で表の結合を確かめてください。")
```

`{row}` は docx の表の何行目か（`Row.number`。0 なら t.rows の番号 + 1）。

#### 3.2 `BuildInfo`（45 行）

`unsplit_names` の後ろに足す:

```python
    # 出力した表 [(<table> の要素, model.Table, Word で探す手がかり)]。pipeline.table_problems が出力した表の形を確かめるのに使う
    tables: list = field(default_factory=list)
```

BuildInfo は asdict・deepcopy されないので、lxml の要素を持たせてよい（点検で grep して確かめた）。

#### 3.3 呼び出し

- `table_wrap`（642 行）: `self.table(tw, node.table)` を `self.table(tw, node.table, node.caption)` にする。キャプションの分岐（630〜638 行）は u3-autonum が `self.caption` にまとめるので、この単位では触らない（形は `if node.caption is not None: …` → `self.table(tw, node.table, node.caption)`）。
- `fig`（596 行。表で組んだ図）: `self.table(_sub(f, "table-wrap"), t)` を `self.table(_sub(f, "table-wrap"), t, node.caption)` にする（`_cell_tables`〈194 行〉と同じく、図のキャプションを手がかりにする。10 章の改行の警告と表の警告で同じ表が別の名前にならないように）。
- u5（0.31.0）の注の表は、必ず `table_wrap` を通す（直接 `self.table` を呼ばない）。この単位の設計書では指示だけ書き、直すのは u5。

#### 3.4 `table` の書き直し（654〜707 行）

モジュールの関数を足す:

```python
def _overlaps(owner, col, span) -> bool:
    """列の範囲 [col, col+span) が、結合元（owner: 開始列 -> (セル, 幅)）のどれかの範囲と重なるか。"""
    return any(s < col + span and col < s + w for s, (_, w) in owner.items())
```

`table` を次の形にする（試作 `proto.py` の `table` に、点検の直し〈本文の 1 行目の重なりの判定・行の番号・caption・記録〉を入れたもの）:

```python
    def table(self, parent, t, caption=None):
        """表を <table> にする。縦の結合（vMerge）は rowspan にする（中間表現は書き換えない）。

        結合元は「開始列 -> (セル, 幅)」で覚え、行ごとに作り直す（その行に合う継続か restart があった列だけ結合が続く。
        横に広いセル・飛ばしたグリッド・セルのない列で切れる）。継続は、開始列と幅が結合元と同じときだけ結合し、幅が違えば
        別のセル（新しい結合元）にする（10 章の警告）。HTML の表では rowspan を行グループ（thead/tbody）の外に延ばせないので、
        本文の 1 行目で結合を止める（10 章の警告）。結合元のない継続（表・本文の 1 行目、削除された結合元の下）は新しい結合元に
        する。すべてのセルが結合した継続の行は出力せず（セルの文字は結合元のセルに続けて出す）、rowspan は出力する行だけで数える。
        行の前後で飛ばしたグリッド（gridBefore・gridAfter）は空のセルで埋める。
        """
        rows = t.rows
        n_head = 0
        for row in rows:
            if row.header:
                n_head += 1
            else:
                break
        if n_head == len(rows):
            n_head = 0      # すべての行が見出し行なら <thead> は作らない（DTD は thead? の後に tbody+ が必要。A4）
        top_of, conts, extra = {}, {}, {}   # id(継続) -> 結合元、id(結合元) -> 継続の行の番号、id(結合元) -> 継続の blocks
        owner = {}                          # 開始列 -> (結合元のセル, 幅)
        crossed, mismatch = False, []
        for r, row in enumerate(rows):
            col = row.grid_before
            if n_head and r == n_head:
                # 本文の 1 行目: 見出し行の結合の範囲に重なる継続があれば、止めたことを警告する（幅は比べない）
                c0 = col
                for c in row.cells:
                    if c.vmerge == "continue" and _overlaps(owner, c0, c.gridspan):
                        crossed = True
                    c0 += c.gridspan
                owner = {}
            new = {}
            for c in row.cells:
                span = c.gridspan
                if c.vmerge == "continue":
                    o = owner.get(col)
                    if o is not None and o[1] == span:
                        top = o[0]
                        top_of[id(c)] = top
                        conts.setdefault(id(top), []).append(r)
                        # 結合された側のセルに文字があれば、結合元のセルに続けて出す（文字を落とさないため）
                        extra.setdefault(id(top), []).extend(c.blocks)
                        new[col] = o
                    else:
                        if _overlaps(owner, col, span):
                            mismatch.append(row.number or r + 1)
                        new[col] = (c, span)
                elif c.vmerge == "restart":
                    new[col] = (c, span)
                col += span
            owner = new
        # 出力しない行: すべてのセルが結合した継続の行（セルのない行も。今と同じ）
        dropped = {r for r, row in enumerate(rows) if all(id(c) in top_of for c in row.cells)}
        rowspan = {k: 1 + sum(1 for r in rs if r not in dropped) for k, rs in conts.items()}
        where = table_where(table_head(t), caption.text_only() if caption is not None else "")
        if crossed:
            self.info.warnings.append(TABLE_HEAD_SPAN_MSG.format(where=where))
        for k in dict.fromkeys(mismatch):
            self.info.warnings.append(TABLE_SPAN_MISMATCH_MSG.format(where=where, row=k))
        tbl = _sub(parent, "table")
        for tag, lo, hi in (("thead", 0, n_head), ("tbody", n_head, len(rows))):
            if lo >= hi:
                continue
            sec = _sub(tbl, tag)
            cell_tag = "th" if tag == "thead" else "td"
            for r in range(lo, hi):
                if r in dropped:
                    continue
                row = rows[r]
                tr = _sub(sec, "tr")
                self._grid_cell(tr, cell_tag, row.grid_before)
                for c in row.cells:
                    if id(c) in top_of:
                        continue
                    td = _sub(tr, cell_tag)
                    if c.gridspan > 1:
                        td.set("colspan", str(c.gridspan))
                    if rowspan.get(id(c), 1) > 1:
                        td.set("rowspan", str(rowspan[id(c)]))
                    self.cell_content(td, c.blocks + extra.get(id(c), []))
                self._grid_cell(tr, cell_tag, row.grid_after)
            if not len(sec):
                tbl.remove(sec)
        if not len(tbl):
            tr = _sub(_sub(tbl, "tbody"), "tr")
            _sub(tr, "td")
        self.info.tables.append((tbl, t, where))

    @staticmethod
    def _grid_cell(tr, tag, n):
        """飛ばしたグリッド n 列ぶんの空のセル（n が 0 なら何もしない。2 以上なら colspan）。文字がないので不変性チェックに関係しない。"""
        if n > 0:
            el = _sub(tr, tag)
            if n > 1:
                el.set("colspan", str(n))
```

決めたこと（どれも実装に入れる）:

- 結合元のない継続は新しい結合元にする（点検の決定）。変更履歴で削除された結合元の行を読み飛ばした形（deleted_top）では、Word で削除を承諾した後の表示（次の行が結合の始まり）に近くなる。今の版は別々のセルで、その下に継続が続く形でだけ出力が変わる（実際の原稿では 0 件）。
- 見出し行をまたぐ結合・幅の違う継続は 10 章の警告にとどめる（要確認にしない。点検の決定）。文字は落ちず、出力の表の形はそろう。
- 本文の 1 行目では、継続の範囲が見出し行の結合の範囲に重なれば（幅が違っても）`crossed` にする。幅の違う継続が境目にあっても、警告なしに結合が切れないようにするため。結合を止めるのは同じなので出力は変わらない。
- 表の 1 行目と本文の 1 行目は、セルがあれば dropped にならない（owner が空なので）。セルのない行（`<w:tr/>`）は今までどおり出力しない。そのため、見出し行 + セルのない行だけの本文は `<thead>` だけの `<table>` になる（今の版と同じ。DTD 不合格で要対応 dtd が出る）。この単位では直さず REVIEW に記録する（「新しく見つけた問題」）。
- 継続側のセルの文字: 同じ節の中の結合では結合元のセルの後ろに続ける（今と同じ）。見出し行の境目で止めた場合、本文の 1 行目の継続は自分のセルとして出し、その下の継続の文字もそのセルに続く。
- `where` の文字は警告のときだけ要るが、記録（`info.tables`）にも使うので毎回作る。`table_where`・`table_head` は builder.py の 19 行で import 済み。
- 入れ子の表は `cell_content` で段落に平らにされ、`self.table` を通らない（今のまま。形の確かめの対象にもならない）。

### 4. 表の形の確かめ（`src/jasme_jats/pipeline.py`）

`lost_images`（242 行）の後ろに足す。`from .model import Decision, LostImage, TableProblem` にする。

```python
SECTION_JA = {"thead": "見出し行（thead）", "tbody": "本文の行（tbody）", "tfoot": "脚の行（tfoot）"}
NO_RECORD = "組み立ての記録がない表"


def _cell_span(cell, name) -> int:
    try:
        return max(1, int(cell.get(name, "1")))
    except ValueError:
        return 1


def _shape_problems(tbl, expect) -> list:
    """<table> の形を HTML の表の割り当てで調べる。expect は docx の表の列の数（docx がもともと不ぞろいなら None）。"""
    out = []
    for sec in tbl:
        if sec.tag not in SECTION_JA:       # コメントなどは tag が文字列でないので入らない
            continue
        name = SECTION_JA[sec.tag]
        carry = {}                          # 列 -> 上の行の rowspan がまだ覆う行の数（この行を含む）
        trs = [x for x in sec if x.tag == "tr"]
        for k, tr in enumerate(trs, 1):
            cells = [x for x in tr if x.tag in ("th", "td")]
            taken = set(carry)
            nxt = {c: n - 1 for c, n in carry.items() if n > 1}
            if not cells:
                out.append(f"XML の{name}の {k} 行目にセルがない")
            col = 0
            for cell in cells:
                while col in taken:
                    col += 1
                cover = range(col, col + _cell_span(cell, "colspan"))
                rs = _cell_span(cell, "rowspan")
                if any(x in taken for x in cover):
                    out.append(f"XML の{name}の {k} 行目でセルが重なっている")
                taken.update(cover)
                if rs > 1:
                    for x in cover:
                        nxt[x] = rs - 1
                col = cover.stop
            if taken and max(taken) + 1 != len(taken):
                out.append(f"XML の{name}の {k} 行目に、どのセルも覆わない列がある")
            if expect is not None and cells and len(taken) != expect:
                out.append(f"XML の{name}の {k} 行目が {len(taken)} 列ぶん（docx の表は {expect} 列）")
            carry = nxt
        if carry:
            out.append(f"縦の結合（rowspan）が XML の{name}の外にはみ出している")
    return out


def _table_name(tbl, where) -> str:
    anc = next((a for a in tbl.iterancestors("table-wrap", "fig") if a.get("id")), None)
    if anc is None:
        return where
    aid = anc.get("id")
    return f"表 {aid}" if anc.tag == "table-wrap" else f"図 {aid} の中の表"


def table_problems(root, info) -> tuple:
    """出力した表の形の確かめ（不変性チェックは文字しか、DTD 検証は要素の並びしか見ないため）。

    builder の結合の判断には頼らず、docx の行ごとの列の数（gridBefore + gridSpan の和 + gridAfter）と、出力した <table> の
    HTML の表の割り当て（行ごとの列の数・セルの重なり・縦の結合の節の外へのはみ出し・セルのない行）だけで判定する。
    docx の表がもともと行ごとに列の数の違う表なら、列の数は比べない。root の外に外した表（数式の画像にした図の中の表）は数えず、
    root の中の組み立ての記録がない <table> は、割り当てだけ確かめて「組み立ての記録がない表」とする。
    戻り値: (TableProblem の一覧, 確かめた表の数)
    """
    found, checked, recorded = [], 0, []
    for tbl, t, where in info.tables:
        if tbl.getroottree().getroot() is not root:
            continue
        recorded.append(tbl)
        if not t.rows:
            continue        # 変更履歴ですべての行が削除された表（空の td を 1 つ書く。10 章の警告）
        checked += 1
        widths = {row.grid_before + sum(max(1, c.gridspan) for c in row.cells) + row.grid_after
                  for row in t.rows if row.cells}
        expect = next(iter(widths)) if len(widths) == 1 else None
        probs = list(dict.fromkeys(_shape_problems(tbl, expect)))
        if probs:
            found.append(TableProblem(tid=t.tid, where=where, name=_table_name(tbl, where), problems=probs))
    for tbl in root.iter("table"):
        if any(tbl is x for x in recorded):
            continue
        checked += 1
        probs = list(dict.fromkeys([NO_RECORD] + _shape_problems(tbl, None)))
        found.append(TableProblem(tid="", where=NO_RECORD, name=_table_name(tbl, NO_RECORD), problems=probs))
    return found, checked
```

- `info.tables` が要素の参照を持っているので、lxml の要素の同一性（`is`）で比べてよい。`id()` の集合にしてもよいが、参照を持っている間に限る。
- f 文字列の式の中に引用符・バックスラッシュを書いていない（Python 3.10）。`_table_name` の `aid` は式の外で変数にしている。
- 呼ぶ場所: `convert` の 458 行（`lost, hidden_images = lost_images(...)`）の直後に `table_issues, tables_checked = table_problems(root, info)`。単位どうしの点検で決めた順（8. 守り: `lost_images` → `table_problems` → `lost_autonums`。u3-autonum が `lost_autonums` をこの後ろに足す）。root と info は、AI の再変換（413・423 行）・ルート2 の `pdf_numbers`（439 行付近）・DTD の取り消し（数式の取り消しで build をやり直す）の後の、最後のもの（`lost_images` と同じ）。
- `Result`（137 行）に既定値つきで足す（`lost_images` の行の後ろ）:
  ```python
  table_problems: list = field(default_factory=list)  # 出力した XML の表の形の崩れ（TableProblem。要対応 table_shape）
  tables_checked: int = 0                             # 形を確かめた表の数（12 章。すべての行が削除された空の表は数えない）
  ```
  542 行の `Result(...)` に `table_problems=table_issues, tables_checked=tables_checked` を渡す。
- `Result.ok` は変えない（ok の意味は不変性・DTD・補完の確かめ。tests/test_pipeline.py 771 行付近の「ok の意味は変えない」と同じ扱い）。要対応は `needs_action` で出る（終了コード 1）。
- `add_images`（560 行）は Result を作り直すとき `dataclasses.replace` などで欄を引き継いでいるか確かめ、`table_problems`・`tables_checked` が消えないようにする（実装のときに確かめること）。

### 5. 知らせ（`src/jasme_jats/report.py`）

#### 5.1 `_table_shape_action`（`_dtd_action`〈721 行〉の後ろ）

```python
TABLE_SHAPE_WHY = ("行ごとの列の数がそろわない・縦の結合が見出し行や本文の行の外にはみ出すなど、docx の表と違う形で出力しました"
                   "（変換ツールの不具合の可能性があります）。")


def _table_shape_action(r):
    """出力した XML の表の形の崩れ（pipeline.table_problems）。なければ None。"""
    probs = r.table_problems
    if not probs:
        return None
    n = len(probs)
    lines = [(p.name, "、".join(p.problems)) for p in probs]
    names = "、".join(esc(name) for name, _ in lines)
    shown = lines[:DTD_SHOWN]
    rest = [f"…ほか {n - DTD_SHOWN} 件"] if n > DTD_SHOWN else []
    return Action(
        NEEDS_ACTION, "table_shape",
        top="\n".join([f"> **要対応: 出力した XML の表 {n} 件の形が崩れています（12 章）。** {TABLE_SHAPE_WHY}"
                       "この XML は登載に使わず、変換レポートを添えて開発者に知らせてください。", ">"]
                      + [f"> - {esc(name)}: {esc(what)}" for name, what in lines]),
        checklist=(f"- [ ] **表の形が崩れている {n} 件**（12 章）: この XML は登載に使わない（変換レポートを添えて開発者に"
                   f"知らせる）: {names}"),
        box_title=f"出力した XML の表の形が崩れています（{n} 件。この XML は登載に使わないでください）",
        box_detail=("docx の表と違う形（行ごとの列の数・縦の結合の範囲など）で出力しました。変換ツールの不具合の可能性があります。"
                    "レポートの 12 章を確認し、変換レポートを添えて開発者に知らせてください。\n"
                    + "\n".join([f"・{name}: {what}" for name, what in shown] + rest)),
        cli=(f"要対応: 出力した XML の表 {n} 件の形が崩れている（行ごとの列の数がそろわないなど。レポートの冒頭と 12 章。"
             "変換ツールの不具合の可能性がある）。この XML は登載に使わないこと。\n"
             + "\n".join([f"  {name}: {what}" for name, what in shown] + rest)))
```

- 画面の操作（変換し直す手順）は案内しないので、目印 `report.step()` は使わない。
- `actions()`（1656 行）の head の並びで `_dtd_action` のすぐ後ろ（`_upload_action` の前）に入れる。0.30.0 の最終の並びは「fidelity, supplement, dtd, **table_shape**, upload, ai_error, ai_pending, partial, forced, figbody, textbox_undecided, textbox_place, textbox_figure_text, images, lost, autonum_lost（u3-autonum）, image_crop, image_edits（u4）, style_hidden, …（今のまま）」+ pdf_actions。excluded_unsure・abstract_missing の位置は 0.31.0 の u5 が埋める。この単位では `_table_shape_action` を 1 つ足すだけにする。
- `app.AppState.REPASTE_KEYS` には入れない（手動の欄の表示に関係しない）。Colab・1 画面版・コマンドラインの表示は Action から自動で出るので、個別の表示は足さない。

#### 5.2 12 章（2016〜2037 行）

- 見出し「## 12. DTD 検証と J-STAGE のアップロード時チェックの詳細」の文字は変えない（計画者の決定）。
- 「### J-STAGE のアップロード時チェック」の節の後ろ（2036 行の `L.append("")` の後、13 章の前）に足す:
  ```python
  L.append("### 表の形の確かめ")
  L.append("")
  if r.table_problems:
      L.append(f"出力した表 {r.tables_checked} 件のうち {len(r.table_problems)} 件の形が、docx の表と違います（変換ツールの"
               "不具合の可能性があります。この XML は登載に使わず、変換レポートを添えて開発者に知らせてください）。")
      L.append("")
      L.append(table(["表", "Word で探す手がかり", "見つかった問題"],
                     [(p.name, p.where, "、".join(p.problems)) for p in r.table_problems]))
  elif r.tables_checked:
      L.append(f"出力した表 {r.tables_checked} 件について、行ごとの列の数（縦に結合したセルが覆う列を含む）が docx の表と同じか、"
               "セルが重なっていないか、縦の結合が見出し行・本文の行の外にはみ出していないか、セルのない行がないかを確かめ、"
               "問題はありませんでした（変更履歴ですべての行が削除された表は数えていません）。")
  else:
      L.append("出力した表はありません。")
  L.append("")
  ```
- `table()` は各欄を `esc` するので、文の中に生のタグを書かない（「（thead）」はタグの形ではない）。
- 1 章の要約の表には行を足さない（冒頭の囲みで出る）。

### 6. 周辺

- `structure.Classifier.cell_pairs`（1466 行）の None の条件に `or any(r.grid_before or r.grid_after for r in t.rows)` を足し、docstring の「結合したセルがある、」を「結合したセル・飛ばしたグリッド（gridBefore・gridAfter）がある、」にする。
- `tests/make_fixtures.py`: `tr()`（739 行）の後ろに足す。既定の fixture の出力は変えない（fixture を作り直さない。新しい docx は `tmp_path` に作る）。
  ```python
  def table_row(cells, header=False, grid_before=0, grid_after=0):
      """表の行（table_of_rows と組み合わせる）。cells は cell() の XML か文字列。trPr に gridBefore・gridAfter
      （と幅の wBefore・wAfter）・tblHeader を書く（OOXML の順: gridBefore, gridAfter, wBefore, wAfter, …, tblHeader）。"""
      trpr = ""
      if grid_before:
          trpr += f'<w:gridBefore w:val="{grid_before}"/>'
      if grid_after:
          trpr += f'<w:gridAfter w:val="{grid_after}"/>'
      if grid_before:
          trpr += f'<w:wBefore w:w="{2000 * grid_before}" w:type="dxa"/>'
      if grid_after:
          trpr += f'<w:wAfter w:w="{2000 * grid_after}" w:type="dxa"/>'
      if header:
          trpr += "<w:tblHeader/>"
      pr = f"<w:trPr>{trpr}</w:trPr>" if trpr else ""
      body = "".join(c if c.startswith("<") else cell(c) for c in cells)
      return f"<w:tr>{pr}{body}</w:tr>"
  ```
  f 文字列の式の中に文字列の連結や引用符を書かない（Python 3.10。`pr` を先に作る）。モジュールの docstring の部品の一覧に `table_row` を足す。
  不正な gridSpan のセルは `cell(...)` の XML の `</w:tcPr>` の前に `<w:gridSpan w:val="0"/>` を差し込んで作る（点検の `edge2.py` の `raw` と同じ）。テストの中の補助にし、make_fixtures には足さない。

## テスト

新しいファイル `tests/test_tables.py`。docx は make_fixtures（`make_article`・`table`・`table_of_rows`・`table_row`・`cell`）で `tmp_path` に作る（内容は架空）。AI は `ai_mode` の既定（none）か、回答を使うテストでは `{"placements": [], "operations": [], "notes": []}` の形（0.30.0 から `operations` が必須）。

補助:

- `_grid(tbl)`: 出力の `<table>` を `{"thead": [...], "tbody": [...]}`（行ごとの `[(セルの文字, rowspan, colspan, 要素名)]`）にする。
- `_convert(tmp_path, rows, header_rows=0, raw_rows=None)`: `make_article` に表キャプション「表1　…」と表（`raw_rows` があれば `table_of_rows`）を入れて `convert` し、`res.fidelity.ok`・`final_ok`・`dtd_valid`・`res.table_problems == []` を確かめてから `(res, tbl)` を返す。

テスト（名前と入力の形）:

1. `test_rows_all_continued_are_not_output_and_rowspan_counts_output_rows`（parametrize）
   - both_cont = `[[A(restart), B(restart)], [""(cont), ""(cont)], [C, D]]` → tbody が `[[A, B], [C, D]]` で rowspan なし。
   - col1_all_col2_row2 = `[[A(r), B(r)], [""(c), ""(c)], [""(c), D]]` → `[[A rowspan=2, B], [D]]`。
   - cont_text（both_cont の継続に文字 A2・B2）→ A のセルが「A」`<break/>`「A2」。
   - どれも tr の数 = docx の行数 − すべて継続の行の数。tests/private/review-repros の merge の場合（架空の表）はこの both_cont と同じ入力なので、正式なテストに移した項目として最後の報告で挙げる。
2. `test_vmerge_stops_at_head_body_boundary`
   - head_to_body = 見出し 2 行 `[[H1(r), H2], [""(c), H3]]` + 本文 `[[""(c), X], [Y, Z]]` → thead `[[H1 rowspan=2, H2], [H3]]`、tbody `[["", X], [Y, Z]]`。
   - head_all_to_body = 見出し 1 行 `[[H1(r), H2(r)]]` + 本文 `[[""(c), ""(c)], [Y, Z]]` → tbody の 1 行目は空のセル 2 つ。
   - 継続側に文字「続き」を入れた版 → その文字が tbody の 1 行目のセルに出る。
   - 幅の違う版: 見出し行の 2 列ぶんの restart `[[H(span=2, r), H3]]` の下に本文の 1 行目で 1 列の継続 `[[""(c), X, Y], [P, Q, R]]` → tbody の 1 行目は `["", X, Y]`、形の確かめ 0 件。
   - どの版も `res.warnings` に「見出し行の終わりで止めました」が 1 件。
3. `test_vmerge_with_different_span_is_not_merged`
   - `[[A(span=2, r), B], [""(c), x, y], [C, D, E]]` → 2 行目は `["", x, y]`、A は rowspan なし。
   - `[[A(r), B, Bb], [""(span=2, c), y], [C, D, E]]` → 2 行目は `["" colspan=2, y]`。
   - どちらも警告「の 2 行目: 縦に結合したセルの幅」が 1 件。
   - 変更履歴で削除された行（読み飛ばす空の行）を 1 行目の前に入れた版では、警告の行の番号が 3 になる（docx の行の番号。`Row.number`）。
4. `test_vmerge_is_cut_by_a_wide_cell`: `[[X, A(r)], [C(span=2)], [Y, ""(c)]]` → A に rowspan がなく、3 行目は `[Y, ""]`。警告はなし（結合元のない継続）。
5. `test_grid_before_and_after_are_filled`（`table_row` と `table_of_rows`、3 列）
   - gridBefore=1 の行 `[D, E]` → `["", D, E]`。gridAfter=1 → `[D, E, ""]`。gridBefore=2 の行 `[F]` → 空のセルに colspan=2。
   - 見出し行で gridBefore=1 → 空の th。
   - 列 1 の継続が gridBefore=1 の行にある（1 行目 `[A, B(r), C]`、2 行目 gridBefore=1 `[""(c), Z]`）→ B に rowspan=2。
   - 列 0・1 が結合元（`[A(r), B(r), C]`）で、継続が gridBefore=1 の行（`[""(c), Z]`）→ A は rowspan なし、B は rowspan=2。
6. `test_deleted_top_row_continuations_get_a_new_owner`: 変更履歴で削除された空の行（`w:trPr/w:del`、restart のセル）の下に継続が 2 行（1 つ目に文字 Q、2 つ目は空）→ 削除された行は読み飛ばし、Q のセルが rowspan=2 になり、文字が落ちない。
7. `test_reader_reads_grid_skips`: `read_docx` の `Row.grid_before`・`grid_after` が 1・2、`Row.number` が docx の行の番号（読み飛ばした行も数える）。gridBefore の値が "x" なら 0。gridSpan が "0"・"-1"・"x" のセルは `gridspan == 1`（"x" で変換が落ちない）。
8. `test_table_problems_unit`: lxml で作った `<table>` を目印のない `root`（`<article>` に入れたもの）に置き、`model.Table`（`Row`・`Cell`）と組にして `BuildInfo.tables` に入れて `table_problems(root, info)` を呼ぶ。
   - (a) rowspan が tbody の外にはみ出す、(b) セルが重なる、(c) 行が docx の列の数より少ない、(d) セルのない tr、のそれぞれで問題の文が 1 件。
   - (e) docx の行ごとの列数がもともと不ぞろい（2 列の行と 3 列の行）で、出力も同じ形なら 0 件。
   - (f) `t.rows` が空なら飛ばす（`tables_checked` にも数えない）。
   - (g) 各行の先頭が gridSpan=0 の docx を読み取りで 1 にそろえた後の表（変換を通す）で 0 件。
   - (h) root から外した `<table>`（`parent.remove` した要素の中）は数えない。
   - (i) `info.tables` に記録のない `<table>` が root にあれば、「組み立ての記録がない表」が 1 件（名前は祖先の table-wrap の id から「表 T9」）。
9. `test_table_shape_is_needs_action`（monkeypatch）: `Builder.table` を「元の `table` を呼んでから、最初の td に `rowspan="9"` を付ける」ものに差し替えて変換する。`fidelity.ok` と `dtd_valid` は真のまま、`actions()` の key に `"table_shape"` があり、`res.needs_action` が真、`res.ok` は真のまま。レポートの冒頭（`## 2.` の前）・12 章の「### 表の形の確かめ」の表・14 章に出る。`cli.main` の終了コードが 1 で、標準エラーに「表」と「変換ツールの不具合の可能性」が出る。
10. `test_table_problems_use_last_build`（単位どうしの点検の「守りが最後の木を見る」テスト）: `pipeline.build` を包んで呼ばれた (root, info) を記録し、手動モードで回答 `{"placements": [], "operations": [], "notes": []}` を渡して build を 2 回走らせる。
    - `res.tables_checked` が最後の info の行のある表の数と同じ。
    - 包んだ build が 1 回目の木の最初の td にだけ `rowspan="9"` を付けたときは `table_problems == []`、最後の木にだけ付けたときは 1 件。
    - 数式の画像の取り消し（DTD 不合格で build をやり直す）とルート2 の `pdf_numbers` の経路は、u3-autonum が `lost_autonums` と一緒に同じ形のテストを足す（この単位では AI の再変換の経路だけ）。
11. `tests/test_pipeline.py` の `test_fidelity_and_dtd`（20 行）に `assert res.table_problems == [], res.table_problems` を足す（ALL_DOCS で誤報がない）。
12. （任意）tests/private のある環境だけ実行するテスト（`skipif`）: 実際の原稿 10 件で `table_problems == []`。原稿の文字はテストに書かない。

既存のテスト: `tests/test_figure_body.py` の vmerge の場合（128〜135 行）・`cell_pairs` のテスト・`reader_wrapped_rows` の表が通ること。並びを確かめる既存のテスト（test_floats 731 行・test_pipeline 867 行・test_links 180 行・test_ai 1396 行・test_notebook 271 行）が落ちないこと（`table_shape` が fixture で鳴らないことの確かめも兼ねる）。全テスト（今は 1298 件）と `tests/test_syntax.py` を通す。

## 回帰の確かめ（基準との比較で想定する違い）

- 基準は、0.30.0 の最初の commit（u1 の (1a): sanitize と fixture の作り直し）の直後に、0.29.0 のコードで取ったもの（fixtures 15 件と tests/private 10 件のルート1、PDF のある 6 件はルート2 も。AI は manual・回答なし、`convert_metafiles=False`）。比べるのは XML のバイト列のハッシュ・actions の key と level・除外の理由ごとの件数・warnings の件数・ZIP の一覧と画像のハッシュ・終了コード。
- 想定する違い: **0**（XML・actions・warnings・ZIP すべて同じ）。actions に `table_shape` は出ず、warnings に `TABLE_HEAD_SPAN_MSG`・`TABLE_SPAN_MISMATCH_MSG` も出ない。レポートは 12 章に「### 表の形の確かめ」の節が増え、表の件数の文が入る（レポートは比べる対象のハッシュに入れていないが、増えるのはこの節だけであることを目で確かめる）。
- 試作での「バイト単位で同じ」は作り直す前の fixture での結果。作り直した後の基準でもう一度比べ、違いがあれば実装を止めて原因を調べる（想定外の違いの判断は Opus）。
- 出力が変わりうるのは、崩れる形の表（上の再現の 1〜10）と、結合元のない継続の下に継続が続く形、gridSpan の不正な値の表だけ。実際の原稿と fixtures ではどれも 0 件。

## ほかの単位・ルート2・AI 補完・画面との関係

- u3-autonum（次に builder.py・model.py・pipeline.py・report.py を直す）: `table_wrap` のキャプションの分岐を `self.caption` にまとめるのは u3-autonum。この単位は `self.table(tw, node.table, node.caption)` の呼び出しだけを変える。`convert` の守りの並び（`lost_images` → `table_problems` → `lost_autonums`）の後ろ 1 つは u3-autonum が足す。`actions()` の `lost` の直後（autonum_lost）も u3-autonum。
- u4（docx_reader.py・model.py・make_fixtures.py を次に直す）: `read_table` と `_graphic` は別の関数。test_reader.py にテストを足すときは名前を重ねない（この単位のテストは test_tables.py に置き、test_reader.py には足さない）。
- u5（0.31.0）: 注の節の中の表（`<fn><p><table-wrap>`）も `table_wrap` を通すので、`table_problems` の対象に入り、`TableProblem.name` も付く（注の表も `assign_ids` で tid が付く）。u5 のテストで、注の表で結合のあるものに `table_problems == []` を確かめる（u5 の設計書に書く）。謝辞（A5）で `<p>` に包む表も同じ。
- u6: なし。
- ルート2: `pdfdocx` は表の構造（vMerge・gridSpan・gridBefore）を変えないので、補った docx も同じ読み取りと組み立てを通る。`fidelity.verify_supplement` には関係しない。`pdfmatch.target_paragraphs` は plan のセルの段落を見るので、出力の行の並びの変化は影響しない（見出し行の境目で止めたとき継続の文字が出るセルが変わっても、段落ごとの照合は同じ）。
- AI 補完: `ai_assist` の依頼文は表の tid と行の数（`len(t.rows)`）だけを書き、行・列の形は使わない。`set_role`・`place_float` で表の形は変わらない。AI の回答を反映した 2 回目の build の `info.tables` で確かめる（テスト 10）。
- 画面: Colab の赤い枠・1 画面版の枠・コマンドラインの標準エラーは `Action` から自動で出る。`REPASTE_KEYS` には入れない。新しい目印は足さない。

## 利用者向けの文

- 要対応 `table_shape`（`report._table_shape_action`。文は「直し方 5.1」のとおり）:
  - レポートの冒頭: 「> **要対応: 出力した XML の表 {n} 件の形が崩れています（12 章）。** 行ごとの列の数がそろわない・縦の結合が見出し行や本文の行の外にはみ出すなど、docx の表と違う形で出力しました（変換ツールの不具合の可能性があります）。この XML は登載に使わず、変換レポートを添えて開発者に知らせてください。」に「>」の行と「> - 表 T1: XML の本文の行（tbody）の 2 行目が 4 列ぶん（docx の表は 3 列）」のような行を並べる。
  - 14 章: 「- [ ] **表の形が崩れている {n} 件**（12 章）: この XML は登載に使わない（変換レポートを添えて開発者に知らせる）: 表 T1、…」。
  - 枠の題: 「出力した XML の表の形が崩れています（{n} 件。この XML は登載に使わないでください）」。中身は「docx の表と違う形（行ごとの列の数・縦の結合の範囲など）で出力しました。変換ツールの不具合の可能性があります。レポートの 12 章を確認し、変換レポートを添えて開発者に知らせてください。」と「・{名前}: {問題}」（5 件まで、残りは「…ほか N 件」）。
  - コマンドライン: 「要対応: 出力した XML の表 {n} 件の形が崩れている（行ごとの列の数がそろわないなど。レポートの冒頭と 12 章。変換ツールの不具合の可能性がある）。この XML は登載に使わないこと。」と「  {名前}: {問題}」。終了コード 1。
- 問題の文（`TableProblem.problems`）: 「XML の本文の行（tbody）の {k} 行目にセルがない」「…でセルが重なっている」「…に、どのセルも覆わない列がある」「…が {m} 列ぶん（docx の表は {e} 列）」「縦の結合（rowspan）が XML の見出し行（thead）の外にはみ出している」「組み立ての記録がない表」。行の番号は XML の節ごとの tr の番号で、Word の表の行と対応しないので、必ず「XML の」を付ける。
- 10 章の警告（Action にしない）: `TABLE_HEAD_SPAN_MSG`「{where}: 見出し行から本文の行へ続く縦の結合を、見出し行の終わりで止めました（本文の行の側は別のセルとして出力しました。文字は落としていません）。」、`TABLE_SPAN_MISMATCH_MSG`「{where}の {row} 行目: 縦に結合したセルの幅（横に結合した列の数）が上の行のセルと違うため、結合せずに別のセルとして出力しました。Word で表の結合を確かめてください。」。
- 12 章の「### 表の形の確かめ」: 問題がなければ「出力した表 {n} 件について、行ごとの列の数（縦に結合したセルが覆う列を含む）が docx の表と同じか、セルが重なっていないか、縦の結合が見出し行・本文の行の外にはみ出していないか、セルのない行がないかを確かめ、問題はありませんでした（変更履歴ですべての行が削除された表は数えていません）。」。表がなければ「出力した表はありません。」。
- 中止（終了コード 2）は使わない。

## 文書の更新（CLAUDE.md は案だけ）

この単位の実装者が直すのはコードの docstring・コメントと `tests/make_fixtures.py` の docstring だけ。docs/ の文書は 0.30.0 の最後に Opus がまとめて直す（単位ごとの差分がぶつからないように）。そのときに入れる内容:

- `docs/STYLE_MAPPING.md` 43 行: 「縦の結合は `rowspan`」に足す。すべてのセルが結合の継続の行は出力せず、`rowspan` は出力した行だけで数える。見出し行から本文の行へは結合を延ばさない（10 章の警告）。幅の違う継続は結合しない（10 章の警告）。結合元のない継続は結合の始まりとして扱う。行の前後で飛ばしたグリッド（`gridBefore`・`gridAfter`）は空のセルで埋める。
- `docs/DESIGN.md` 180 行付近（すべての行が見出し行の表の後ろ）: 上と同じ規則と、表の形の確かめ（`pipeline.table_problems`、要対応 `table_shape`）。「表の 1 行目と本文の 1 行目は、セルがあれば出力しない行にならない」と書く（セルのない行だけの本文は今も `<thead>` だけになる。REVIEW の新しい項目）。
- `docs/ARCHITECTURE.md`: データの流れの図の `lost_images` の行の後に「pipeline.table_problems ──▶ 形の崩れた表」。`convert` の段階の 8（守り）に `table_problems`。pipeline.py・builder.py・model.py・docx_reader.py の行（`BuildInfo.tables`、`Result.table_problems`・`tables_checked`、`TableProblem`、`Row.grid_before`・`grid_after`・`number`、`Cell.rowspan` の削除、`_grid_span`・`_grid_skip`）と行数（`wc -l` に合わせる）。`actions()` の並び。テストの表に `test_tables.py`。
- `docs/DEVELOPMENT.md`: 守るべき原則 3 の `lost_images` の後ろに「表の形（行ごとの列の数・セルの重なり・縦の結合の範囲・セルのない行）は `pipeline.table_problems` が確かめ、崩れていれば要対応」。テストの節に `make_fixtures.table_row` と `tests/test_tables.py`。
- `docs/USAGE.md` の知らせの一覧（「たとえば次のものです」）に `table_shape`（出力した表の形の崩れ。要対応。変換ツールの不具合の可能性があるので、登載に使わず開発者に知らせる）。
- `docs/REVIEW_2026-11.md`: 直したものの表に、指摘 5・N6 を 0.30.0 で直したこととその直し方（上の「直し方」の要約）。新しい未修正の項目（下の「新しく見つけた問題」の REVIEW に記録するもの）。
- `CLAUDE.md`（実装者は直さない。版の最後に案の文を利用者に見せて承認を得てから直す）: 「不変性チェックは文字しか見ない。」の行を次の案にする（u3-autonum の案と 1 つにまとめて見せる）。
  > 不変性チェックは文字しか見ない。XML に入らなかった画像は `pipeline.lost_images()` が、出力した表の形の崩れ（行ごとの列の数・縦の結合の範囲など）は `pipeline.table_problems()` が、Word の自動番号の出力漏れは `pipeline.lost_autonums()` が検出し、要対応として知らせる。

## 文書とコードの食い違い

- `model.Cell.rowspan`（`rowspan: int = 1`）は宣言だけで、どこからも読み書きされていない。builder.table のコメント「中間表現は書き換えない」のとおり rowspan は builder の辞書で持つ。この単位で消す（直す）。
- `docs/STYLE_MAPPING.md` 43 行の「縦の結合は `rowspan`」は、すべて継続の行を出力しないこと・見出し行との区切り・gridBefore を書いていない。今のコードは rowspan が出力の行数と合わない（不具合のほう）。版の最後に文書を直す（直す）。
- `structure.Classifier.cell_pairs` の docstring「結合したセルがある、行ごとのセルの数が違う…ときは None」は、飛ばしたグリッドを考えていない。読み取りを足すのに合わせてコードと docstring を直す（直す）。
- 計画（`docs/FIX_PLAN_2026-11.md` の単位の表）は作るのを Sonnet・high とし、設計・点検の JSON は Sonnet・medium としていた。計画の表（high）に従う（食い違いは計画の書類どうしで、コードとの食い違いではない）。
- 設計の「thead・tbody が空になることはない」は、セルのない行では成り立たない（点検で確かめた）。この設計書と DESIGN.md の文は「セルがあれば」に直した。コードは今のまま（REVIEW に記録）。

## 新しく見つけた問題（この単位で直すもの／直さず REVIEW に記録するもの）

この単位で直すもの:

- 横に広いセルが結合元の列を覆っても結合が続く（owner_not_cleared）。セルの重なりと列数のずれになる。owner を行ごとに作り直すことで直す。
- `w:gridSpan` の 0・負の値を 0・負のまま読み、数でない値で変換が `ValueError` で落ちる。`_grid_span` で 1 にそろえる。
- 図の中の表の手がかり（where）がキャプションを使わず、`_cell_tables` と食い違う。`fig` から `node.caption` を渡す。
- 見出し行の境目で幅の違う継続があると、警告なしに結合が切れる。境目の判定を範囲の重なりにする。

直さず `docs/REVIEW_2026-11.md` に新しい項目として記録するもの:

- セルのない行（`<w:tr/>`）だけの本文の表が `<thead>` だけの `<table>` になり、DTD 不合格（要対応 dtd）になる（既存の問題。DTD が知らせるので黙っては壊れない。実際の原稿では 0 件）。直すなら、本文の行がすべて出力しない行のときは見出し行を tbody に入れる（`n_head = 0` と同じ扱い）。
- `w:hMerge`（古い形式の横の結合）を読まず、別々のセルとして出す（形の確かめは誤報しないが、横の結合が XML に出ない）。
- 飛ばしたグリッドの空のセルは、J-STAGE の画面で枠のある空のセルに見え、Word の表示（セルのない空き）と違う（実際の原稿では 0 件）。
- `w:cellDel`（変更履歴で削除されたセル）は今も出力して 10 章で警告する。docx の行の列数に削除されたセルも数えるので形の確かめは誤報しない見込みだが、Word で承諾した後の表の形とは違う。

## 未決のこと（利用者の返事待ち／実装のときに確かめること）

利用者の返事待ち:

- CLAUDE.md の「不変性チェックは文字しか見ない」の行に `table_problems` を足すか（上の案。u3-autonum の案と一緒に版の最後に聞く）。

実装のときに確かめること:

- 作り直した fixture での基準と比べて、出力の違いが 0 であること（試作の「バイト単位で同じ」は作り直す前の fixture での結果）。
- `pipeline.add_images` が Result を作り直すときに `table_problems`・`tables_checked` を引き継ぐこと（引き継がないと、画像を入れた後のレポートで 12 章の件数が 0 になり、要対応が消える）。
- `root.iter("table")` が目印付きの root で JATS の `<table>` だけを拾うこと（名前空間のない要素名。目印の要素が `<table>` の名前を使っていないこと）。
- 結合元のない継続（表・本文の 1 行目）を Word がどう表示するかは実物で確かめていない（実際の原稿では 0 件）。設計では結合の始まりとして扱う。確かめられる環境があれば、架空の docx を Word で開いて確かめ、違えば REVIEW に記録する。
- lxml の `iterancestors("table-wrap", "fig")`（複数のタグ）が今の lxml で使えること。

## 点検の指摘の反映表

| 重さ | 題 | 反映した節 |
|---|---|---|
| major | gridSpan が 0・負・数でないと、table_problems が誤って要対応を出し、結合も黙って消える | 直し方 2（`_grid_span`）・4（expect を `max(1, …)`）、テスト 7・8(g)、新しく見つけた問題 |
| minor | 見出し行と本文の行の境目で幅の違う継続は、警告なしに結合が切れる | 直し方 3.4（本文の 1 行目は `_overlaps` で判定）、テスト 2（幅の違う版） |
| minor | TABLE_SPAN_MISMATCH_MSG の「{row} 行目」が、読み取りの警告の行の数え方と違う | 直し方 1（`Row.number`）・2（`row.number = k`）・3.1・3.4（`row.number or r + 1`）、テスト 3（削除された行の版）・7 |
| minor | table_problems は builder が記録した表しか見ない（記録のない表・出力の木から外した表） | 直し方 4（`table_problems(root, info)`、root の外の表を飛ばす、記録のない表に「組み立ての記録がない表」）、テスト 8(h)(i) |
| minor | 設計の「thead・tbody が空になることはない」は、セルのない行では成り立たない | 直し方 3.4 の決めたこと（文を「セルがあれば」に）、文書の更新（DESIGN.md）、新しく見つけた問題（REVIEW に記録。直さない） |
| minor | 図の中の表の where がキャプションを使わず、builder._cell_tables と食い違う | 直し方 3.3（`fig` から `node.caption`）・4（`_table_name` が祖先の fig の id も見る） |
| minor | table_problems の文の「{k} 行目」は XML の行の番号で、Word の行と対応しない | 直し方 4（「XML の本文の行（tbody）の k 行目」、tr の子は th・td だけ数える）、利用者向けの文 |
