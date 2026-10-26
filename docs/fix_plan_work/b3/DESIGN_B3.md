# B3（0.22.0）の設計: 位置を決められない図表の置き場所と、表で組んだ図の組み方（N15〜N19）

- 正本: `docs/FIX_PLAN.md` の B3 の節の「設計の方針」と、決定事項 21・22。この設計書は、それを関数ごとの変更まで具体にしたもの。
- 基点: main = 45d8314（0.21.0）。B2.1 は保留中で独立（`pdfmatch.py`・`pdfdocx.py` には触らない）。
- 触るファイル: `structure.py`・`ai_assist.py`・`pipeline.py`・`report.py`・`colab.py`・`cli.py`・`tools/make_notebook.py`（→ ノートブック）・
  `__init__.py`・`pyproject.toml`・`tests/make_fixtures.py`・`tests/conftest.py`・`tests/test_floats.py`・`tests/test_ai.py`・`tests/test_colab.py`・
  `docs/DESIGN.md`・`docs/DEVELOPMENT.md`・`docs/FIX_PLAN.md`。触らない: `pdfmatch.py`・`pdfdocx.py`・`builder.py`・`docx_reader.py`・`floats.py`・`fidelity.py`。
- 試作: `scratchpad/b3/design/src`（0.21.0 の写しに、1〜4 章の要の部分を入れたもの。差分は `scratchpad/b3/design/proto_*.diff`）。
  fixture の案は `scratchpad/b3/design/fixtures_b3.py`、確かめのスクリプトは `check_b3.py`・`check_b3b.py`・`cut_test.py`・`seq_float.py`・`run_td.py`、
  td1〜3 の結果は `td_base.json`（0.21.0）・`td_proto.json`（試作。どちらも構造の要約だけで、文字は入れていない）。
  試作は確かめ用で、文言・細部はこの設計書のほうが正しい（6.4 の「試作から直すこと」）。

---

## 0. 今の動き（0.21.0）と、変える点の要約

| 項目 | 0.21.0 | B3 |
|---|---|---|
| 位置を決められない図表（AI なし・貼り戻し前・AI でも決まらない） | 本文の冒頭（最初の章の前）に仮に置く | アンカー段落のすぐ後ろに仮に置く。アンカー段落が本文の段落でなければ本文の最後 |
| AI が注・引用文献などの段落の後ろと答えた図表 | 不採用にして本文の冒頭 | 不採用（規則は変えない）。本文の最後に仮に置く |
| 回答の JSON の順 | operations → placements → notes | placements → operations → notes（依頼文・見本・スキーマ） |
| 途中で切れた回答 | すべて捨てる（"Expecting …" で末尾 2 文字以内のときだけ案内） | 最後まで書かれた placements の要素だけを読んで検証・反映し、要対応として知らせる。"Unterminated string" も案内 |
| 表のセルに画像とキャプションが並ぶ図形 | キャプションのない表（セルに画像）として出す | 一つに組めれば、セルの画像を本体・セルのキャプションをキャプションにした図に組む。組めなければ AI に任せる |
| 画像のない図キャプションと隣のキャプションのない表 | キャプションだけの図と、キャプションのない表に分かれる | 表をその図の本体（fig の中の table-wrap）にする。近くに表があるのに組めなければ要対応 |

---

## 1. N17・N16: 位置を決められない図表の置き場所

### 1.1 規則（言葉の定義）

- **アンカー段落のすぐ後ろ** = items（本文の領域のブロックの並び。`build_body` に渡るもの）での、アンカー段落の直後。
  `place_floats` の差し込み位置（`inserts` の target）で `src_index[アンカー段落] + 1` と表す（AI の `after` と同じ形）。
  アンカー段落の直後には、docx の読み取りで、その段落に結び付いた図形の中身（テキストボックスの段落・表）が並んでいる。
  差し込みは「order が target 以上の最初の要素の前」に入るので、アンカー段落の次の本文の要素の前（図形の中身はどれも差し込みに移る）に入る。
- **本文の段落** = `plan.body_seq`（本文の領域の段落のうち図形の中のものを除く。`_placement_problem` の after の判定と同じ集合）。
- **本文の最後** = 本文の領域の最後の要素の後ろ（`BODY_END = float("inf")` を target にする。今の merge の「残った差し込みは最後に足す」で入る）。
  章の入れ子（`nest`）では、最後の章（節）の終わりに入る。付記・謝辞・注・引用文献（後付け）の前。
- **本文の外の段落**（N16）= 本文より後ろの領域の段落: `plan.region` が `notes`・`ack`・`fn`・`refs`・`back`・`front_en`・`app` のもの
  （`structure.AFTER_BODY_REGIONS`。本誌のテンプレートでは英文の部分・資料も本文より後ろ）。和文の冒頭（`front_ja`）・除外した段落・
  図形の中の段落・表のセル・存在しない ID は含めない（これらは「AI でも決められない」として、アンカー段落の規則にする）。

規則（決定事項 21）:

1. AI の指定（placements）が検証で採用された図形: 今までどおり、指定された段落の直後（`float_from_spec`）。
2. AI が本文の外の段落の後ろを指定した図形（N16）: その指定は不採用（`_placement_problem` の規則は変えない）。図表は**本文の最後**に仮に置く。
   組み合わせは、AI の items ではなく、3. と同じく機械的に組めれば組み、組めなければ中身をそのまま出す（不採用の指定の一部だけを使わない）。
3. それ以外で位置が決まらない図形（AI なしで決められない、手動モードで貼り戻す前、AI の回答に指定がない・不採用）: **アンカー段落のすぐ後ろ**。
   アンカー段落が本文の段落でなければ**本文の最後**。
4. 同じ位置に複数の図表が来るときは、キャプションの番号順（`float_number`。番号がなければ後ろ）、同じ番号なら docx の順。
   位置を決められない図表どうしだけでなく、同じ差し込み位置に入る AI の指定の図表・機械的に配置した図表（次のアンカー段落の前）とも、
   この順で並ぶ（今の `inserts` の並べ方と同じ）。中身をそのまま出す図形も、組んだ図形と同じ差し込みに入れるので、この順に入る（1.3）。

**B3 で「アンカー段落が本文でない」が起きるか**: `place_floats` は今どおり、アンカー段落が本文の領域にある図形だけを扱う（`fl.anchor_src not in src_index`
なら飛ばす）。docx の読み取りは図形の中に図形を作らない（`docx_reader` の `outer is None`）ので、アンカー段落は図形の中の段落にならず、
本文の領域にあれば必ず `body_seq` に入る。つまり B3 では 3. の「本文の最後」の分岐は通らない。注・引用文献などに結び付いた図形
（td3 の表のセルに結び付いた図形も）は、今までどおりその領域の段落として扱われる（`docs/DESIGN.md` 7 章。F の N7 で
「位置を決められない図表」にする。F の前提の利用者の判断が要る）。B3 では分岐を小さな関数（1.2 の `provisional_target`）に切り出して
単体テストで確かめ、F がアンカー段落の条件を広げたときにそのまま使えるようにする。

### 1.2 `structure.Classifier.place_floats` の変更

戻り値を `(items, inserts, front)` から `(items, inserts, raw)` にする。`raw` は「中身をそのまま出す図形の要素の `id` → その図形の差し込みの一覧
（list。`inserts` の 3 つ目と同じオブジェクト）」。

```
body = set(plan.body_seq)
for fl in doc.floats:
    ...（今までどおり info を作る。文字だけのテキストボックスは飛ばす）
    spec = self.placements.get(fl.fid)
    end = bool(spec) and spec.get("where") == "end"          # N16（ai_assist.float_placements が作る。1.4）
    if spec and not end and spec["after"] not in src_index:
        spec = None                                           # 今までどおり
    if spec and not end:
        ...（今までどおり AI の指定で組む）
    else:
        entries = float_mechanical(...) if at_anchor(fl, layout) and not end else None
        if entries is None:                                   # 位置を決められない
            info.mode = "unplaced"; info.reason = ...（今までどおり）
            info.where, info.end_why, info.end_after, target = self.provisional_target(fl, spec if end else None, src_index, body)
            plan.decide(..., f"…（指定がなければ{plan.float_place(fl.fid)}に仮に置く）", applied=False)
            entries = self.float_mechanical(info, groups, others)
            if entries is None:                               # 中身をそのまま出す
                entries = []
                for b in blocks:
                    raw[id(b)] = entries                      # build_body が役割を決めてから、この一覧に入れる
            else:
                placed.update(id(b) for b in blocks)
            inserts.append((target, (self.float_number(info), len(inserts)), entries))
            continue
        ...（機械的に配置: 今までどおり target = src_index[アンカー段落]）
rest = [(b, r) for b, r in items if id(b) not in placed]
return rest, inserts, raw
```

- `provisional_target(fl, end_spec, src_index, body) -> (where, end_why, end_after, target)`（新設。staticmethod でよい）:
  - `end_spec` があれば `("end", "ai", end_spec["after"], BODY_END)`
  - `fl.anchor_src not in body` なら `("end", "anchor", "", BODY_END)`
  - それ以外は `("anchor", "", "", src_index[fl.anchor_src] + 1)`
- 0.21.0 の「位置は決められないので本文の冒頭に置く」の `inserts.append((-1, …))` と `front.extend(…)` は無くなる（`front` は返さない）。
- `float_mechanical` を 2 回呼ぶ形（位置の判定のためと、組み合わせのため）は今と同じ。1 回目は `at_anchor` のときだけで、None なら状態を
  変えていない（`float_mechanical` は「組めると決まってから状態を変える」。N18 の `cell_figures` も同じ約束を守る。3 章）。
- `FloatInfo` に `where: str = ""`（`anchor` / `end`）、`end_why: str = ""`（`ai` / `anchor`）、`end_after: str = ""`（AI が指定した本文の外の段落 ID）を足す。
- `ArticlePlan.float_place(fid) -> str`（新設）: 仮に置いた位置の説明。レポート・Colab・コマンドライン・決定の文言で共通に使う。
  - `where == "end"` → `本文の最後`
  - それ以外 → アンカー段落から `body_seq` を前にたどり、文字のある最初の段落の冒頭 20 字で `段落「…」の後ろ`（アンカー段落に文字が
    ないことがある。td1 の図形 s2 のアンカー段落は空の段落）。どこにもなければ `本文の最初`。
- docstring（L578〜590 相当）の「本文の冒頭に仮に置く」と戻り値の説明を直す。

### 1.3 `structure.Classifier.build_body` の変更

```
order = {id(b): k for k, (b, _) in enumerate(items)}       # 今と同じ（place_floats の前の items で数える）
items, inserts, raw = self.place_floats(items)
flat = []
for b, role in items:
    out = raw.get(id(b), flat)        # 中身をそのまま出す図形の要素は、その図形の差し込みに入れる
    ...（今までどおり。flat.append(...) の 2 か所を out.append(...) にする）
```

- `order[k] = -1` の行は消す。
- 中身をそのまま出す図形の要素も、今までどおりこのループで役割を決める（テキストボックスの中の文字だけの段落の除外 `TEXTBOX_TEXT_EXCLUDED`、
  `textbox_caption` による推定、空白段落の `exclude_blank`）。出力・除外の記録は 0.21.0 と同じで、入る場所（差し込みの一覧）だけが変わる。
  要素が除外・空白なら一覧に何も入らない。
- merge（「配置を決めた浮動配置の図表を…差し込む」）は変えない。`BODY_END` は `order` のどの値よりも大きいので、最後の「残りを足す」で入る。
- 後の「本文スタイルのまま書かれた図表キャプションの推定」と `assemble_floats` は、merge の後の並びに対して今までどおり動く。

### 1.4 N16: `ai_assist.float_placements` の変更

`_placement_problem` は変えない（本文の外の段落を after にした指定は今までどおり不採用）。`float_placements` で、不採用にした指定のうち、
次をすべて満たすものを「本文の最後に置く」印として記録する:

- 指定が dict で、`float` が `plan.floats` にあり `mode == "unplaced"`
- その図形について、まだ採用した指定がなく、印もない
- `after` が文字列で `body_seq` になく、`plan.region.get(after) in AFTER_BODY_REGIONS`

```
out, ends = {}, {}
for pl in data.get("placements", []) or []:
    op = placement_op(pl)
    why = _placement_problem(pl, plan, body, out)
    if why:
        if <上の条件>:
            ends[fid] = {"where": "end", "after": after, "op": op}
            why += "。図表は本文の最後に仮に置いた（手作業で正しい位置に移すこと）"
        outcome.rejected.append((op, why))
        continue
    out[fid] = {...今までどおり}
for fid, spec in ends.items():
    out.setdefault(fid, spec)        # 同じ図形の、後ろの正しい指定が採用されていれば、そちらを使う
return out
```

- 印を `out` と別の `ends` に貯めるのは、`_placement_problem` の「指定が 2 回ある」の判定（`done = out`）に印を入れないため
  （本文の外を指定した後に正しい指定があれば、正しいほうを採用する）。
- `pipeline.convert` の `for sid, spec in placements.items(): if sid in plan.float_decisions` は、印の図形が `float_decisions` に入らないので変えなくてよい。
- `AFTER_BODY_REGIONS` は `structure.py` に置き（`ai_assist` は `structure` から import している）、`REGION_ROLES` のキーと揃える。

### 1.5 手動モードで AI の回答を貼り戻す前

1 回目の組み立て（`placements` なし）で 1.1 の 3. がそのまま効くので、追加の処理は要らない。`pipeline.convert` の `output_note` の文言だけ直す（1.6）。
AI 依頼文の段落一覧は docx の順で、図形の中の段落の位置は「図形 sN の中」と書く（`build_request`）ので、仮の位置は AI の判断に影響しない
（`docs/DESIGN.md` 5 章の記述を直す）。依頼文の「# 図・表・注・数式」の F 番号は、仮の位置が変わる分だけ 0.21.0 と変わる（AI のリンク先は
`target_keys` / `retarget_ops` で読み替えるので問題ない）。

### 1.6 知らせ（文言の案）

文言は「何が起きて、どこを見て、何をすればよいか」を短く。`plan.float_place(fid)` で置いた位置を示す。

**`pipeline.convert`**（L378〜394 相当）:

```
pending_ai = ...（今と同じ）
for sid in plan.unplaced_floats:
    fi = plan.floats[sid]
    ids = _float_ids(plan, fi)
    place = plan.float_place(sid)
    where = f"XML の{place}にある {ids}" if ids else f"XML の{place}にある図表の中身"
    if pending_ai:
        detail = (f"テキストボックス・グループ図形 {sid} の位置を決められない（{fi.reason}）。AI の回答を反映すると配置される"
                  f"（今は{place}に仮に置いている）")
    else:
        if fi.end_why == "ai":
            head = (f"AI が本文の外（{REGION_JA[region]}）の段落 {fi.end_after} の後ろを指定したが、本文の外には図表を置けないため、"
                    "本文の最後に仮に置いた。")
        elif fi.end_why == "anchor":
            head = "図が結び付いている段落が本文の段落でないため、本文の最後に仮に置いた。"
        else:
            head = f"AI による補完でも位置を決められなかったため、{place}に仮に置いた。"
        detail = (head + f"手作業で、{where}を正しい位置（Word で表示したときに図の左上の直上にある本文の段落の後）に移すこと。"
                  f"機械的に決められなかった理由: {fi.reason}")
        forced_floats.append(f"{float_caption(fi)}: {where}")
    unresolved_after.append(("float", fi.float.anchor_src, float_caption(fi), detail))
```

- `REGION_JA = {"fn": "注", "refs": "引用文献", "notes": "付記", "ack": "謝辞", "back": "後付け", "front_en": "英文の部分", "app": "資料"}`
  （`pipeline.py` か `report.py` に置く。region は `plan.region.get(fi.end_after)`）。
- 0.21.0 の `near`（「図形 sN のアンカー段落「…」付近」）は、置いた位置そのものがアンカー段落の後ろになったので消す（`forced_floats` も 3 章も）。
- `_float_caption` は Colab からも使うので、`structure.py` に `float_caption(info)` として移す（pipeline の 4 か所の呼び出しを置き換える。中身は今と同じ）。
- `Result.forced_floats` のコメント（L126）を「AI による補完でも位置が決まらず、仮の位置（アンカー段落の後ろ・本文の最後）に置いた図表の説明」に。
- `output_note`（L305〜306）: `位置を決められない図表（3 章）は、AI の回答を反映するまで、図が結び付いている段落（アンカー段落）のすぐ後ろ（その段落が本文でなければ本文の最後）に仮に置いています。`
- `AIRequiredError` の文言は変えない（AI なしでは今までどおり止まる。決定事項 10）。

**`report.py`**:

- 結果の要約の行（L438〜439）: `f"{n} 件（{float_places(plan)}に仮に配置）"`。`float_places(plan)` は新設で、全部アンカー段落の後ろなら
  `アンカー段落の後ろ`、全部本文の最後なら `本文の最後`、混ざれば `アンカー段落の後ろ 2 件・本文の最後 1 件`。
- 冒頭の要対応（L446〜449）:
  `> **要対応: 位置を決められなかった図表が {n} 件あります（AI による補完でも決まりませんでした）。** 図が結び付いている段落（アンカー段落）のすぐ後ろか、本文の最後に仮に置いています。登載の前に、XML の中でこれらの図表を手作業で正しい位置（Word で表示したときに、図の左上の直上にある本文の段落の後）に移してください（3 章）: ` + 各図表（`「図1　…」: XML の段落「…」の後ろにある F1`）
- 3 章: `unresolved_after` の行がそのまま出る（種類「図表の位置」）。
- 14 章（L767〜768）: `- [ ] 仮の位置（アンカー段落の後ろ・本文の最後）に置いた図表（3 章の「図表の位置」）を、XML の中で手作業で正しい位置に移す`

**`colab.unplaced_box(plan)`**（引数は今と同じ）:

```
title: 位置を決められなかった図表があります（仮の位置に置いています。手作業で直してください）
detail:
AI の回答に、次の図表の位置（placements）の指定がないか、指定が検証で採用されませんでした（レポートの 2 章・3 章）。
これらは仮の位置に置いているので、登載の前に、XML の中で手作業で正しい位置（Word で表示したときに、図の左上の直上にある
本文の段落の後）に移してください。
・s1（「図1　…」）: 段落「…」の後ろ
・s2（「図3　…」）: 本文の最後（AI が注などの本文の外の段落の後ろを指定したため）
AI に出し直してもらう場合は、…（今と同じ）
```

**`cli.main`**（L112〜114）:
`位置を決められなかった図表を、仮の位置（アンカー段落の後ろ、または本文の最後）に置きました。XML の中で手作業で正しい位置に移してください（レポート 3 章）: s1（段落「…」の後ろ）、s2（本文の最後）`。終了コード 1 は今と同じ。

**`structure.place_floats` の決定**（レポート 4 章と AI 依頼文の「推定」に出る）: `（指定がなければ{place}に仮に置く）`。

### 1.7 「本文の最後」と「アンカー段落の後ろ」で文言を分けるか

**決定: 知らせの項目（冒頭・3 章・14 章・Colab の枠・CLI）は 1 つのまま、図表ごとに置いた位置を示す。理由が違う「本文の最後」だけ、3 章の理由と
Colab の枠に理由を添える。** 利用者がすること（XML の中で正しい位置に移す）は同じなので、枠や章を分けると見る場所が増えるだけになる。
図表ごとの位置（`段落「…」の後ろ` / `本文の最後`）は、XML の中で図表を探す手がかりとして必ず示す。要約の行は件数の内訳を示す。

### 1.8 試作で確かめたこと

- sample_float（手動モード・回答なし）: 0.21.0 は本文の冒頭に F1・F2・T1。試作は、F1 が s1 のアンカー段落の後ろ、T1（s2 の表）が s2 のアンカー段落の
  後ろ、F2 が s3 のアンカー段落の後ろ。最初の要素は章。不変性・最終・DTD 合格。
- 回答から s2 を抜いたもの: T1 が s2 のアンカー段落の後ろ。s1 の after を引用文献の段落にしたもの: 不採用の理由に「本文の最後に仮に置いた」が付き、
  F が本文の最後（2 章の最後の段落の後ろ）。
- 架空の fixture（`fixtures_b3.py` の `make_b3_place`）: 同じアンカー段落の図3・図2（docx の順）が、図2・図3 の順に並ぶ。文字のないアンカー段落の
  図4 は、前の文字のある段落の名前で「段落「…」の後ろ」と示される。注の段落を after にした AI の回答で、図1 が本文の最後。

---

## 2. N15: 回答の書式と、途中で切れた回答

### 2.1 placements を回答の先頭に書かせる

- `RESPONSE_SCHEMA`: properties と required の順を `placements, operations, notes` にし、placements の description に「回答の最初に書く」を足す。
  JSON スキーマは順を保証しない。構造化出力はスキーマの順に書くことが多い（OpenAI は順を保つと案内している）ので効く見込みはあるが、各社とも試験運用で確かめる。
- `SYSTEM_PROMPT`: 「reason には…」の段落の前に次を足す（API と手動の両方に効く）:
  `回答の JSON は、placements、operations、notes の順に書いてください（placements を最初に。回答が長すぎて途中で切れても、図表の位置の指定が残るようにするためです）。`
- `MANUAL_EXAMPLE`: 見本の JSON の順を placements → operations → notes にする（中身は今と同じ）。
- `FIELD_GUIDE`: 先頭に `回答は placements、operations、notes の順に書く（placements を最初に）。` を置き、placements の説明を operations の説明の前に移す
  （placements の reason・confidence は「下の operations と同じ」）。
- `manual_prompt` の「回答の書き方」: placements の行を operations の行の前に移し、`JSON は placements、operations、notes の順に書いてください（…）。` を足す。
- 読み取り（`parse_response`・`split_ops`・`float_placements`）はキーの順に依らないので、順の違う回答（0.21.0 の見本どおりの回答）も今までどおり読める。

### 2.2 途中で切れた回答から、閉じている placements の要素だけを読む（採る）

**決定: 採る。** 理由: 順を変えるだけでは、API モード（回答が切れると `call_*` が文字を捨てて誤りにする）では何も残らず、手動モードでも
JSON として読めないので、位置の指定は失われたままになる。位置の指定は、利用者が XML の中で図表を手で移す手間に直結する（B3 の理由）。
JSON の文法どおりに最後まで書かれた値だけを読むので、推測で補うことはなく、読んだ要素もふつうの回答と同じく `_placement_problem` で検証する。

**読む範囲（厳密に）** — `ai_assist.parse_cut_response(text) -> dict | None`（新設）:

1. 回答から JSON の部分を取り出す（`_json_text`。2.4）。最初の `{` から後ろを対象にする。
2. `json.loads` が成功したら切れていないので None。失敗したら、その誤りが `cut_at_end(e, t)`（2.4）でなければ None
   （途中の書き損じ〈飾りの引用符など〉は、切れた回答ではないので読まない）。`cut_at_end` なら、誤りの位置より前は JSON として正しい。
3. 最上位のオブジェクトを、`json.JSONDecoder().raw_decode` でキー（文字列）・`:`・値の順に 1 組ずつ読む。`placements` 以外のキーの値は、
   値全体を読めたら読み飛ばし、読めなければ（その値の途中で切れている）そこで止める。
4. `placements` の値は `[` の後ろの要素を 1 つずつ `raw_decode` で読む。最後まで読めた要素だけを集め、読めない要素（途中で切れている）で止める。
   `]` まで読めたら配列は閉じている。
5. 集めた要素が 1 つもなければ None。あれば `{"placements": [...], "operations": [], "notes": []}` を返す。
   operations と notes は、最後まで書かれた要素があっても使わない（2.5 の却下案）。

**使い方**（`pipeline.convert`）:

```
def _read_cut(outcome, text):                       # pipeline.py に新設
    data = parse_cut_response(text)
    if data is None:
        return None
    outcome.error = ""
    outcome.partial = PARTIAL_MSG.format(n=len(data["placements"]))
    return data
```

- 手動モード: `parse_response` が失敗したら `_read_cut` を試し、None なら今までどおり `outcome.error = "貼り付けられた回答を JSON として読めませんでした: …"`。
- API モード: `call_*` が切れたこと（`outcome.cut`）を返す（2.3）。`if outcome.raw and (not outcome.error or outcome.cut):` で `parse_response` を試し
  （上限ちょうどで JSON が閉じていることもある。読めたら `outcome.error = ""`）、失敗したら `_read_cut`、それも None なら、切れたときは今の誤り
  「AI の回答が長すぎて途中で切れました」のまま、切れていないときは「AI の回答を JSON として読めませんでした: …」。
- 読めた placements は、ふつうの回答と同じく `float_placements` で検証し、`_mechanical(..., overrides={}, placements)` で組み直す
  （operations がないので set_role の上書きもリンクの操作もない）。読めなかった図形・最後の切れた要素の図形は、位置を決められない図表として
  1 章の規則で仮に置き、`forced_floats` で知らせる。
- `AIOutcome` に `cut: bool = False`（API の回答が上限で切れた。raw は切れたところまで）と `partial: str = ""`（一部だけ反映したときの説明。要対応）を足す。

**知らせ**（`PARTIAL_MSG`）:
`AI の回答が途中で切れていました。図表の位置の指定（placements）のうち、最後まで書かれていた {n} 件だけを反映しました。リンクなどの操作（operations）と気づき（notes）は反映していません。AI に出し直してもらうと、すべてが反映されます（手動モードではチャットで「回答が途中で切れました。同じ形式で最初から出し直してください」と頼んで手順 6 で貼り付け直し、API モードでは手順 5 をもう一度実行します）。`

- レポートの冒頭: `> **要対応: AI の回答が途中で切れていました（2 章）。** {partial}`（`r.ai.partial` があるとき。`output_note` の前）
- レポートの 2 章: 冒頭の説明の後に `回答が途中で切れていたため、反映したのは図表の位置の指定だけです: {partial}`。`render_ai_only` にも同じ 1 行。
- 14 章: `- [ ] AI の回答が途中で切れていた（2 章）: AI に出し直してもらい、もう一度変換する`
- Colab（`tools/make_notebook.py` の手順 5 と 6）: `if res.ai.partial: display(HTML(error_box("AI の回答が途中で切れていました（図表の位置の一部だけを反映しました）", res.ai.partial)))`
  （`res.ai.error` の枠の隣。error は空になっているので「読み込めませんでした」の枠は出ない）
- CLI: `if res.ai.partial: print(f"AI: {res.ai.partial}", file=sys.stderr)`。終了コードは変えない（残った位置を決められない図表があれば今までどおり 1）。

### 2.3 API の各社の呼び出し

切れたとき（上限に達したとき）に、誤りは今のまま設定し、受け取れた文字を `out.raw` に入れ、`out.cut = True` にする:

- `call_api`（Claude）: `stop_reason == "max_tokens"` のとき、`text` を取り出してから `out.raw, out.cut = text, True`（今は取り出す前に return している）。
- `call_openai`: `status == "incomplete"` かつ `reason == "max_output_tokens"` のとき `out.raw = resp.output_text or ""`、`out.cut = True`。
- `call_sakana`: `finish_reason == "length"` のとき `out.raw = msg.content or ""`、`out.cut = True`。
- `call_gemini`: `finish_reason == "MAX_TOKENS"` のとき、`resp.text` を try で読み（例外なら ""）、`out.cut = True`。
- `tests/test_ai.py` の今のテスト（「途中で切れました」が誤りに入る）は、そのまま通る（誤りの文言は変えない）。

### 2.4 「途中で切れている可能性があります」の案内と、閉じのないコードブロック

- `_json_text(text)`（新設）: ```` ```json ```` のコードブロックがあればその中身。閉じの ```` ``` ```` がなければ最後まで（回答が切れると閉じがない。
  今は閉じがないと `rfind("}")` で切るので、最後の `}` の後ろが捨てられ、誤りの位置もずれる）。`parse_response` の最初の 4 行をこれに置き換える
  （`{` で始まらないときの `find("{")`〜`rfind("}")` は今のまま残す）。
- `cut_at_end(e, t) -> bool`（新設）: `e.msg` が `Unterminated string` で始まる（文字列の途中で入力が終わった。Python の json は、閉じの `"` が
  見つからないまま終わったときだけこの誤りを出す）、または `Expecting` で始まり、`t[e.pos:].strip()` が空か、`true`・`false`・`null`・数の
  書きかけ（正規表現 `^(?:-?[0-9.eE+-]*|t(?:r(?:ue?)?)?|f(?:a(?:l(?:se?)?)?)?|n(?:u(?:ll?)?)?)$`）であるとき True。
- `parse_response` の案内（L763〜764）: `elif cut_at_end(e, t):` にする（今の「Expecting で末尾 2 文字以内」を含み、"Unterminated string" も案内する）。
  飾りの引用符の案内を先に判定するのは今と同じ。

### 2.5 決めなかったこと・却下した案

- **operations の、最後まで書かれた要素も読む案**: 却下。リンクの操作の多くは件数が多く、どこで切れたかを利用者が確かめにくい（途中までの
  リンクだけが付き、3 章の未解決の一覧と混ざる）。位置の指定は図形ごとに独立で、読めなかった図形は要対応として図形ごとに示せる。
  出し直しを促す知らせで足りる。
- **切れた JSON の閉じ括弧を補って読む案**: 却下（推測で直さない。`parse_response` の方針どおり）。
- **AI に回答を短くさせる指示（確度の低い操作を省くなど）**: 決めない。AI の回答の形は試験運用で確かめる（FIX_PLAN「計画全体で足した作業」）。
- **Gemini の `propertyOrdering`**: 入れない（`response_json_schema` で順が保たれるかは試験運用で確かめる。依頼文の指示で先頭に書かせる）。

---

## 3. N18: 表のセルに画像とキャプションが並ぶ図形を機械的に組む

### 3.1 条件

`float_mechanical` の最初で、次のときだけ `cell_figures(info)`（新設）を試す:
図形の中の表がちょうど 1 つで、テキストボックスの段落（表の外）に、キャプション・キャプション以外の文字の段落・画像の段落がなく
（空白の段落はよい）、グループ図形の画像もない（`len(info.tables) == 1 and not (groups or others or image_paras or info.images)`）。

`cell_figures(info)` は表のセルを行・列の順に見て、セルの段落を次のように分ける:

- 画像のある段落（画像だけ、または画像と文字が同じ段落）→ そのセルの画像
- 空白だけの段落 → 落とす（`_drop_blank`）
- 図キャプション（`cell_caption(q)` が `fig_caption` で、文字が `RE_FIGCAP` で始まる）→ そのセルの新しいキャプションの組
- 図キャプションのスタイルで番号で始まらない段落が、同じセルのキャプションの直後にある → そのキャプションの続き（出典など。`float_captions` と同じ考え）
- 表キャプション（`RE_TABCAP`）→ **組まない（None）**
- それ以外の文字の段落、入れ子の表 → この形ではない、または組まない（下）

`cell_caption(q)`（新設）: `role_of(q)` が `fig_caption` / `table_caption` ならそれ、なければ `textbox_caption(q)`（`float_captions` と同じ判定。
表のセルの段落は items の役割を持たないので、スタイルから求める）。

戻り値は 3 通り:

- **False（この形ではない）**: セルに画像も番号付きのキャプションもない（または片方しかなく、ほかに文字の段落・入れ子の表がある）。
  `float_mechanical` は今までどおりに続ける（キャプションのない表、表を本体にした図など）。
- **None（組み方が一つに決まらない。AI に任せる）**: 次のどれか。
  - セルに表キャプションがある
  - キャプションでも画像でもない文字の段落がある（「（a）」などの小見出しも。表の構造を捨てると読めなくなるおそれがある）、入れ子の表がある
  - 図キャプションはあるが画像がない（N19 とは別。表の中のキャプションなので、表を本体にするかは決めない）、画像はあるがキャプションがない（→ False でよい。今の扱い）
  - 図キャプションが 2 つ以上で、画像とキャプションが同じセルにないセルがある（画像の行とキャプションの行が分かれた表〈sample_float の s2〉。
    列ごとか行ごとかを決められない）、または 1 つのセルにキャプションが 2 つ以上ある
- **組んだ要素の一覧**:
  - 図キャプションが表全体で 1 つ: すべてのセルの画像（行・列の順）を本体にした図 1 つ（画像の行とキャプションの行が分かれていてもよい。
    図は 1 つなので組み方は一つ）。
  - 2 つ以上: セルごとに、そのセルの画像とキャプションで図を組む（どのセルも「画像 1 つ以上とキャプション 1 つ」か「空白だけ」）。
    図は行・列の順に並べる。

`float_mechanical` は、`cell_figures` が False でなければその結果を返す（None なら None）。

### 3.2 組み方

- 表そのもの（table-wrap）は出さない。セルの段落は、画像の段落・キャプション・続き・空白だけと確かめてあるので、文字は落ちない
  （画像の段落は図の `<graphic>`、キャプションは `<caption>`、空白は `exclude_blank`）。表の外のテキストボックスの空白段落も `_drop_blank` する
  （試作の初版はここを落としていた。空白が全角空白なら不変性チェックが出力漏れで不合格になる）。
- 画像と文字が同じ段落（画像だけの段落でないもの）は、決定事項 1（M6）と同じく、画像を図の `extra_images` と `plan.moved_images` に移し、
  段落は文字ごと図の直後に `("p", q)` で出す（`float_mechanical` の今の枝と同じ）。
- キャプションの段落は `_take(q, "fig_caption", self._caption_decision(q, "fig_caption"))`、画像の段落は `_take(q, "p")`。状態を変えるのは、
  組めると決まってから（`float_mechanical` の約束）。
- 決定の記録: `plan.decide("mechanical", "figure", アンカー段落, f"テキストボックス・グループ図形 {fid} の表 {tid} のセルにある画像とキャプションを、図 {「図1　…」、「図2　…」} に組んだ（表としては出力しない）")`。
- 位置は、図の左上がアンカー段落の左上にあれば今までどおり機械的にアンカー段落の前、そうでなければ位置を決められない図表（1 章の規則で仮に置き、
  AI に位置を指定させる）。AI の指定が採用されれば、AI の組み合わせ（`float_from_spec`）が優先する。

### 3.3 既存の決定との整合

- 決定事項 1（M6。図の中の画像と文字が同じ段落）: 3.2 のとおり同じ扱い。
- 決定事項 22（表で組んだ図は fig の中の table-wrap）: N18 は「セルに画像がある表」で、表は図の器にすぎないので、表は出さずに画像を図にする。
  「セルに文字の問題文を並べた表＋図キャプション」（td1・td2 の図1、sample_float の s1）は N18 ではなく、今までどおり fig の中の table-wrap。
- 振る舞いの変化: 図の左上がアンカー段落の左上にある図形で、セルに画像と図キャプションがあるのに組み方が決まらないもの（3.1 の None）は、
  0.21.0 ではキャプションのない表として機械的に置いていたが、B3 では位置を決められない図表になり、AI なしでは変換を止める（AIRequiredError）。
  キャプションのない表として出すと、図が図として参照できない誤った構造になるため（FIX_PLAN の「組み方が一つに決まらないときは AI に任せる」）。
  既存の fixture ではこの形はない（golden の AI なしの 7 件は変わらないことを試作で確かめた）。

### 3.4 試作で確かめたこと

- td2 の図形 s2（1 行 2 列の表。各セルに画像だけの段落と図キャプション）: 0.21.0 はキャプションのない表 T1（セルに画像）を本文の冒頭に出し、
  本文の「図3」「図4」の参照は「対応する図が見つからない」（3 章に 4 件）。試作は図 2 つ（graphic 各 1）をアンカー段落の後ろに出し、参照がリンクされる
  （機械的なリンク 図 19 → 21、3 章の未解決 7 → 3 件）。画像の出力数は同じ、出力漏れ 0。
- 架空の fixture: 1 行 2 列（図2 つ）、2 行 1 列（画像 2 つの行とキャプション 1 つの行 → 図 1 つに graphic 2）を AI なしで組む。
  画像の行とキャプションの行が分かれた図 2 つ・セルの小見出し・セルの表キャプションは AIRequiredError（AI に任せる）。

---

## 4. N19: 画像のない図キャプションの隣の、キャプションのない表を図の本体にする

### 4.1 条件（`assemble_floats` の図キャプションの枝）

今の画像の探し方（前 2 要素・後ろ 2 要素）で画像が見つからなかったときだけ、`table_for_figure(flat, out, k, used, captions_below)`（新設）で表を探す。
表を探す向きは、画像のときと同じ `captions_below`（その原稿で図キャプションを図の下に置いているか。画像と図キャプションの隣り合いの数から決める。
画像の図がなければ「下」）で決める:

- **下（captions_below）**: 直前の要素 `flat[k-1]` が表で、それから作った `out[-1]`（TableNode）がキャプションを持たない → `out.pop()` してその表を図の本体にする。
- **上**: 直後の要素 `flat[k+1]` が表で、まだ使われておらず、その次 `flat[k+2]` が表キャプションでない → その表を図の本体にする（`used` に入れる）。
  次が表キャプションなら、その表は表キャプションのもの（表キャプションを表の下に置く書き方）かもしれないので組まない。

「間にほかの段落がない」は、flat で隣り合っていること（空白だけの段落は `build_body` で除外済みで flat にないので、間にあってもよい）。

組んだとき: `FigNode(image_paras=[], caption=b, tables=[表])`（決定事項 22 の fig の中の table-wrap。`builder.fig` は今のまま出せる）。決定の記録:
`画像のない図キャプション「…」の直前（直後）にある、キャプションのない表 tN を、図の本体として組んだ（図の中に表を入れる）`。
その表は TableNode にならないので、後ろの表の ID（T 番号）が 1 つずつ詰まる（キャプションのない表にも T 番号が付いている）。

### 4.2 組めないときの知らせ（要対応）

画像も表も見つからないとき、近くにキャプションのない表の候補があれば、組めなかった理由を `plan.figure_issues`（新設 `list[(段落 ID, 理由)]`）に記録し、
決定も `図キャプションに対応する画像が見つからない（{理由}）`（applied=False）にする。候補の判定と理由:

| 向き | 形 | 理由の文言 |
|---|---|---|
| 下 | 直前の表に表キャプションが付いている | `直前の表に表キャプション「…」が付いている` |
| 下 | 直前ではなく直後にキャプションのない表がある | `直後にキャプションのない表があるが、この原稿は図キャプションを図の下に置いているため、図の本体にしなかった` |
| 下 | 2〜3 要素前に表があり、間に段落がある | `図キャプションの前にキャプションのない表があるが、間にほかの段落がある` |
| 上 | 直後の表の次に表キャプションがある | `直後の表の次に表キャプションがあり、どちらの表か決められない` |
| 上 | 直後ではなく直前にキャプションのない表がある | `直前にキャプションのない表があるが、この原稿は図キャプションを図の上に置いているため、図の本体にしなかった` |
| 上 | 2〜3 要素後ろに表があり、間に段落がある | `図キャプションの後ろにキャプションのない表があるが、間にほかの段落がある` |

近くに表がなければ、今までどおり `図キャプションに対応する画像が見つからない（図形・グループ化等の可能性）` の決定だけ（要対応にしない）。
**決めたこと: 要対応にするのは、表の候補があって組めなかったときだけ。** 候補がないもの（sample_edge の、キャプションだけのテキストボックス）は
今までどおり決定の一覧（レポート 4 章と AI 依頼文）に出すだけにする。利用者にできること（docx で表を図キャプションの隣に移して変換し直す）が
はっきりしているのは候補があるときで、候補がないものまで要対応にすると、golden の sample_edge のレポートが変わり、すべきことも示せない。
決定の文言を候補がないときは変えないので、AI 依頼文も変わらない。

知らせ（すべて `plan.figure_issues` から作る。Result に欄は足さない）:

- 3 章: `unresolved_after.append(("figbody", src, キャプションの冒頭, 詳細))`。`UNRES_JA["figbody"] = "図の本体"`。詳細:
  `図キャプションに対応する画像が見つからず、近くの表も図の本体にできなかった（{理由}）。XML ではキャプションだけの図になる。docx で図の本体（画像・表）を確かめ、表がこの図の本体なら、表を図キャプションのすぐ上（図キャプションを図の上に置く原稿では、すぐ下）に移し、間の段落を除いて、変換し直すこと`
- レポートの冒頭: `> **要対応: 図の本体（画像・表）が見つからない図が {n} 件あります（3 章）。** XML では、キャプションだけの図になっています。docx で、図キャプションの近くの表がその図の本体なら、表を図キャプションのすぐ上（図キャプションを図の上に置く原稿では、すぐ下）に移し、間の段落を除いてから変換し直してください: 「図2　…」（理由）、…`
- 14 章: `- [ ] 図の本体が見つからない図 {n} 件（3 章の「図の本体」）を docx で確かめ、表が図の本体なら docx を直して変換し直す`
- Colab: `colab.figure_body_box(res)`（新設。`error_box` で、題目 `図の本体（画像・表）が見つからない図が {n} 件あります`、本文は冒頭と同じ説明と一覧）。
  `tools/make_notebook.py` の手順 5・6 で `lost_images_box` の隣に表示する。
- CLI: `要対応: 図の本体（画像・表）が見つからない図 {n} 件（レポートの冒頭と 3 章）: 「図2　…」（理由）、…`。終了コードは変えない
  （表の文字は XML に入っている。画像を用意できなかった図〈`images_to_prepare`〉と同じ扱い）。

### 4.3 試作で確かめたこと

- td2 の図2（本文の表〈1 行 1 列の問題文〉の直後に、画像のない図キャプション）: 0.21.0 はキャプションのない表 T5 と、キャプションだけの図 F2
  （10 章の警告「F2: 画像が見つからないため <graphic> なしで出力」）。試作は F2 の中に table-wrap、警告なし。後ろの表の T 番号が 1 つ詰まる。
- 架空の fixture: 直後の図キャプション（組む）、間に段落（要対応・理由「間にほかの段落」）、表キャプションの付いた表（要対応・理由「表キャプション」）、
  図キャプションを図の上に置く原稿で、図キャプションの直後の表（組む）。

---

## 5. テストの計画

### 5.1 fixture（`tests/make_fixtures.py` に足す。内容は架空。試作は `scratchpad/b3/design/fixtures_b3.py`）

既存の部品（`make_article`・`para`・`cell`・`table`・`textbox`・`drawing`・`png_bytes`）だけで作る。`__main__` の一覧とモジュールの docstring にも足す。
fixture を作るときは、その関数だけを呼ぶ（`python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_b3_cells('tests/fixtures/sample_b3_cells.docx')"`。
`python tests/make_fixtures.py` は実行しない）。

1. `make_b3_cells(path, variant="")` → `tests/fixtures/sample_b3_cells.docx`（`conftest.CELLS`。ALL_DOCS に入れる。AI なしで変換できる）
   - s1: アンカー段落の左上にあるテキストボックスに、1 行 2 列の表。各セルに画像だけの段落と図キャプション（図1・図2）→ 図 2 つ
   - s2: 同じく、2 行 1 列の表。1 行目のセルに画像だけの段落 2 つ、2 行目に図キャプション 1 つ（図3）→ graphic 2 つの図 1 つ
   - variant（テストの中で tmp_path に作る）: `columns`（s2 を、画像の行とキャプションの行が分かれた 2 列〈図3・図4〉に）、`text`（s1 の右のセルに「（a）」の段落）、
     `tabcap`（s1 の右のセルのキャプションを表キャプションに）、`down`（s1 をアンカー段落から 2 cm 下に）、`mixed`（s1 の左のセルの画像の段落に説明の文字を足す）
2. `make_b3_tablefig(path, variant="")` → `tests/fixtures/sample_b3_tablefig.docx`（`conftest.TABLEFIG`。ALL_DOCS に入れる。図形はない）
   - 図1: キャプションのない表（1 行 1 列の問題文）の直後に図キャプション → 組む
   - 図2: キャプションのない表、本文の段落、図キャプション → 要対応（間に段落）
   - 図3: 表キャプション＋表の直後に図キャプション → 要対応（表キャプション）
   - variant `above`: 図キャプションを図の上に置いた画像の図（図5）と、図キャプション（図4）の直後のキャプションのない表 → 図4 に組む
3. `make_b3_place(path, outside=False)` → `tests/fixtures/sample_b3_place.docx`（`conftest.PLACE`。AI が要るので ALL_DOCS に入れない）
   - s1: アンカー段落から 3 cm 下の図1（位置を決められない）
   - s2・s3: 同じアンカー段落に、docx の順で図3・図2（どちらも位置を決められない）
   - s4: 文字のない段落に結び付いた図4
   - 引用文献の後ろに「注」の見出しと注の段落 1 つ（N16 の after に使う）
   - variant `outside=True`: 注の段落に図形（画像＋図5）を結び付ける（本文の外の段落に結び付いた図形）

`conftest.ALL_DOCS` に CELLS・TABLEFIG を足すと、golden の件数は 19 → 23（新しい 4 件は比べる相手がないので、合格〈ok〉だけを見る）。
`docs/DEVELOPMENT.md` の「テスト」の fixture の一覧と、`tests/test_floats.py` の説明（L78〜）に足す。

### 5.2 模擬の AI 回答（テストの中で作る。`ai_response_sample_float.json` から作るので、見本と食い違わない）

- placements が先頭の回答: `json.dumps({"placements": …, "operations": …, "notes": …})`
- 途中で切れた回答（placements が先頭のものを、決まった位置で切る）:
  (a) operations の文字列の途中（Unterminated string）、(b) `"operations":` の直後（Expecting value）、(c) 2 つ目の placements の要素の途中
  （s1 だけ読める）、(d) (a) の前に ```` ```json ```` を付け、閉じを付けない
- 読まない回答: (e) 0.21.0 の順（operations が先頭）で operations の途中で切ったもの（placements に届かない）、(f) placements の途中の飾りの引用符
  （切れていない書き損じ）
- 注の後ろと答える回答: sample_b3_place の s1 の after を注の段落 ID に（段落 ID は `_mechanical` で文字から探す。test_floats の既存のテストと同じ）。
  引用文献の段落・英文要旨の段落・題目（和文の冒頭）・図形の中の段落を after にしたものも
- 位置を答えない回答: `{"placements": [], "operations": [], "notes": []}`、ある図形だけ抜いたもの（今の test_missing_placement）

### 5.3 確かめること（テスト）

`tests/test_floats.py`（今の 4 件を直す）:

- `test_mechanical_placement_and_request`: 最初の章の前に図表がない。F1（s1）が「この段落に図1のテキ…」の後ろ、TableNode t3（s2）が
  「この段落には図3と図4…」の後ろ、F（s3）が「図2は教科書の…」の後ろ。依頼文の確かめは今のまま。
- `test_missing_placement_is_reported_after_ai`: s2 の T1 がアンカー段落の後ろ。冒頭に「アンカー段落）のすぐ後ろか、本文の最後に仮に置いています」、
  14 章に「仮の位置（アンカー段落の後ろ・本文の最後）に置いた図表」、`forced_floats` に「XML の段落「…」の後ろにある T1」。CLI の終了コード 1 と表示。
- `test_unplaced_simple_float_is_paired_at_body_start` → `…_after_anchor`: F1 がアンカー段落の直後で fig の中に table-wrap。
- `test_manual_mode_before_response_places_floats_at_body_start` → `…_after_anchor`: `output_note` の文言、3 章の「（今は段落「…」の後ろに仮に置いている）」。

新しいテスト（`tests/test_floats.py`。数が多ければ `tests/test_floats_b3.py` に分けてよい）:

- N17: sample_b3_place（手動・回答なし）で、図2・図3 が同じアンカー段落の後ろに番号順、図4 が空のアンカー段落の位置にあり
  `plan.float_place("s4")` が前の文字のある段落の名前、`where` がすべて `anchor`。不変性・最終・DTD 合格。
- N17: `Classifier.provisional_target` の単体テスト（アンカー段落が `body` にない → `("end", "anchor", "", BODY_END)`、end の指定 → `("end", "ai", after, BODY_END)`）。
- N16: sample_b3_place で s1 の after を注の段落にした回答 → s1 の図が本文の最後（最後の章の最後の要素）。不採用の理由に「本文の段落ではない」と
  「本文の最後に仮に置いた」。`where == "end"`、`end_why == "ai"`。3 章の詳細に「AI が本文の外（注）の段落」。要約の行が「アンカー段落の後ろ 3 件・本文の最後 1 件」
  （s2〜s4 は回答に指定がない）。parametrize: 引用文献・英文要旨の段落 → 本文の最後、題目・図形の中の段落 → アンカー段落の後ろ。
  同じ図形に、注の後ろの指定と正しい指定が続く回答 → 正しい指定が採用される。
- 本文の外の段落に結び付いた図形（sample_b3_place の outside）: 0.21.0 と同じ扱い（その図形は `plan.floats` にない、図形の中身は注の中に出る、
  不変性合格）。F（N7）で扱うことをテストの説明に書く。
- N15: `list(json.loads(MANUAL_EXAMPLE の中身))`・`RESPONSE_SCHEMA` の properties と required の最初が placements。`SYSTEM_PROMPT`・`manual_prompt`・
  `FIELD_GUIDE` に順の指示。placements が先頭の回答で今の `test_ai_placements_are_validated_and_applied` と同じ結果。
- N15: (a)〜(d) で `parse_cut_response` が読む図形（(a)(b)(d) は s1〜s4、(c) は s1 だけ）。(e)(f) は None。(a)(c) で `parse_response` の誤りに
  「途中で切れている可能性があります」（(c) は Unterminated string）。
- N15: (c) を手動モードで変換 → `res.ai.error == ""`、`res.ai.partial` に「1 件だけを反映」、s1 だけ採用、s2・s3 はアンカー段落の後ろで `forced_floats`。
  s4 の要素（機械的に配置した図形）は不採用。レポートの冒頭・2 章・14 章に途中で切れた知らせ。不変性合格。
- N15（`tests/test_ai.py`）: Claude・OpenAI・Gemini・Sakana の模擬クライアントで、上限に達した回答の `out.raw` が残り `out.cut` が True。
  `pipeline.convert` を API モードで `call_provider` を差し替えて、切れた回答の placements が反映され、誤りが空・`partial` が入ること。
- N18: sample_b3_cells を AI なしで変換 → AIRequiredError にならない。F1・F2 は graphic 1 つずつ、F3 は 2 つ、table-wrap がない、キャプションの文字、
  決定の記録、画像の出力数、出力漏れ 0、不変性合格。`columns`・`text`・`tabcap` は AIRequiredError（`columns` は s2、ほかは s1）。手動モードでは
  その図形の表がアンカー段落の後ろにキャプションのない表として出る。`down` は手動モードで、組んだ図がアンカー段落の後ろ。`mixed` は画像が図に、
  文字が図の直後の段落に出る（M6 と同じ）。
- N19: sample_b3_tablefig → F1 の中に table-wrap、その表は独立の table-wrap でない。F2・F3 は graphic も table-wrap もなく、`plan.figure_issues` に
  それぞれの理由、3 章に種類「図の本体」、冒頭と 14 章に要対応、CLI の表示（終了コードは 0 のまま）。`above` で図4 に表。
  sample_edge の F1（候補なし）は `figure_issues` に入らず、決定の文言が 0.21.0 と同じ。
- `tests/test_colab.py`: `unplaced_box` を実際の plan（sample_float の `_mechanical`、と N16 の回答の後の plan）で確かめ、「本文の冒頭」がなく、
  図形ごとの位置（「段落「…」の後ろ」「本文の最後」）がある。`figure_body_box`。

---

## 6. 合格の条件

### 6.1 物差しごと

- **pytest**: すべて合格（3.13 と 3.10）。`tests/` に一時ファイル・`__pycache__` を残さない。
- **ruff**（`ruff check src tests tools`）: 0.21.0 にない指摘を足さない（この環境の ruff は既定の規則が多く、0.21.0 でも 197 件ある。ファイルと規則で比べる。
  新しいコードで `Optional[...]` ではなく `X | None` を使う〈`from __future__ import annotations` があるので 3.10 でも動く〉、import の並び、
  コレクションの中の暗黙の文字列連結に括弧、を守ると増えない。試作は 4 件増えた: I001・UP045×2・ISC004）。
- **golden**（19 件を 0.20.0・0.21.0 の基準と比べる）: 違ってよいのは次だけ（試作で確かめた）。
  - `*_manual` の 8 件と `sample_full_ai`・`sample_float_ai` の prompt（計 10 件）: 依頼文の N15 の文言（順の指示、見本と項目の説明の順）だけ。
    sample_float の prompt はさらに、仮の位置が変わったことによる段落の場所（「第N要素」）と、決定の「（指定がなければ…に仮に置く）」。
  - `sample_float_manual` の xml・report: s1・s2・s3 がアンカー段落の後ろ（本文の冒頭ではない）、F 番号の振り直し、要約の行・3 章・4 章の文言。
  - ほかの xml と report はすべて同じ（`sample_float_ai` の xml・report も同じ: すべて AI の指定どおり）。split の 7 件、pdfcheck の 2 件はすべて同じ。
  - 新しい 4 件（sample_b3_cells・sample_b3_tablefig の manual・split）は、不変性・最終・DTD 合格、J-STAGE のチェックの件数が他と同じ。
- **td1〜3**（`--route docx --ai manual`、回答なしと、`{"placements": [], "operations": [], "notes": []}` を貼った場合。0.21.0 と比べる。試作の結果）:
  - 不変性・最終・DTD・J-STAGE のチェックはすべて合格（0.21.0 と同じ）。XML に入らなかった画像は 0 件のまま、出力した画像の数も同じ（5・2・4）。
  - 本文の段落（章・節の直下の `<p>`）の文字と並びは 0.21.0 とまったく同じ（並びのハッシュが一致）。変わるのは図表の位置と組み方だけ。
  - **td1**: 0.21.0 は本文の冒頭（最初の章の前）に F1〜F4・T1・T2 の 6 つ。試作は最初の要素が章で、位置を決められない 5 つの図形（s1・s2・s4・s6・s7）が
    それぞれのアンカー段落の後ろ。F 番号がキャプションの番号の順（図1〜図6 = F1〜F6）になる。文字のないアンカー段落（s2）の図は、
    前の段落の名前で示される。レポートの違いは、要約の行・3 章（図表の位置）・4 章（決定の文言と番号）・9 章（画像の F 番号）・14 章の文言だけ。
  - **td2**: 0.21.0 は本文の冒頭に F1・T1・T2。試作は最初の要素が章で、図1（s1）・図3 と図4（s2。N18 で図 2 つ）・表4（s3）がそれぞれのアンカー段落の後ろ。
    図2 は N19 で fig の中に table-wrap（0.21.0 はキャプションのない表と、本体のない図）。T 番号が詰まる（T3〜T13 → T1〜T10、表4 は T11）。
    「図3・図4 に対応する図が見つからない」（3 章の 4 件）と 10 章の警告 1 件がなくなり、図へのリンクが 2 件増える。注の初出の順の指摘
    （3 章）がなくなる（本文の冒頭の図表の中の注の参照が、本来の位置に戻るため）。不変性チェックの「XML に出力 N 件」が 2 件減る（セルの画像だけの段落が
    図の graphic になり、文字の出力の単位でなくなるため。除外は 3 件のまま）。
  - **td3**: XML・レポートとも 0.21.0 と同じ（図形はすべて表のセルに結び付いていて、位置を決められない図表がない）。依頼文は N15 の文言だけ違う。
- **利用者の指摘（2026-10-18）がどう変わるか**:
  - 「XML の冒頭に図表が来る」: td1・td2 とも、AI の回答を貼り戻す前・AI でも決まらなかったときのどちらでも、本文の冒頭に図表が来なくなる
    （アンカー段落の後ろ）。AI が注の後ろと答えた図表は本文の最後で、冒頭には来ない。
  - 「図1 が表のように見える」: td1・td2 の図1 は、テキストボックスの中の文字の表（問題文）とキャプション「図1」で、決定事項 22 のとおり
    fig の中の table-wrap のまま（位置だけがアンカー段落の後ろに変わる）。J-STAGE の画面での見え方は変わらない。td2 で表のように見えていた
    図3・図4（キャプションのない表の中の画像）は、N18 で図になる。

### 6.2 実装の担当が反映の前に確かめること

- 版を 0.22.0 に（`src/jasme_jats/__init__.py`・`pyproject.toml`）→ `python tools/make_notebook.py` → pytest。
- `docs/DESIGN.md`: 5 章（placements を先頭、途中で切れた回答、N16 の本文の最後、仮の位置は AI の判断に影響しない、の文言）、6.1（仮の置き場所の規則、
  N18、N19、表で組んだ図の段落）、7 章（残る限界に 7 章の項目を足す）。`docs/DEVELOPMENT.md` の「テスト」（fixture の一覧、test_floats の説明）。
  `docs/FIX_PLAN.md` の B3 の節に実装の記録（決めたこと・確かめた結果・残る限界）。
- 実際の論文の文字を、テスト・文書・コメントに書き写さない（td の結果は件数と構造だけで書く）。

---

## 7. 残る限界・リスク

1. **アンカー段落の後ろは「近い」位置で、正しい位置ではない**。2 段組では、図がアンカー段落と別の段・別のページにあることが多い（td1 の s6 は
   アンカー段落から 9 cm 下）。行数による推定（`estimate_top_left`）を仮の位置に使う案は採らない（ページ・段の区切りを考慮しない目安で、
   決定事項 21 はアンカー段落の後ろ）。利用者は今までどおり手で移す必要があるが、移す距離は本文の冒頭からより短い。
2. **アンカー段落が画像の段落で、その後ろに図キャプションが続くとき**（画像と図形が同じ段落にある）、仮の図表がその間に入る。図キャプションの
   画像の探し方は前 2 要素までなので、差し込みが 2 つ以上だと画像とキャプションが組にならない（AI の指定で同じ段落の後ろに置いたときと同じ限界）。
3. **組み方が決まらない表（3.1 の None）を持つ、図の左上がアンカー段落の左上にある図形**は、0.21.0 と違い AI なしでは止まる（3.3）。
4. **N19 の誤り**: 画像が別の理由で見つからない図キャプション（Word の図形が読めないなど）の隣に、たまたまキャプションのない別の表があると、
   その表を図に入れてしまう。キャプションのない表は少なく、決定の一覧（4 章）に記録し、表の文字は失われない（表示の位置だけ）。
   `captions_below` は画像の図の隣り合いから決めるので、画像の図がない原稿では「下」とみなす（表で組んだ図のキャプションを上に置く原稿では、
   組めずに要対応になる）。
5. **N18 は図形（浮動配置のテキストボックス）の中の表だけ**。本文の表（図形でない）のセルに画像と図キャプションが並ぶものは、今までどおり
   キャプションのない表として出す。
6. **途中で切れた回答で反映するのは placements だけ**。リンクなどの操作は出し直しが要る（知らせで促す）。API モードでは、同じ依頼を出し直しても
   また切れることがある（そのときは手動モードを使う）。
7. **回答の順は AI に依る**。構造化出力はスキーマの順に書くことが多いが、Claude・ChatGPT・Gemini・Sakana AI・チャットの AI が placements を先頭に書くかは、
   試験運用で確かめる（FIX_PLAN「計画全体で足した作業」）。先頭に書かなかった回答が切れたときは、0.21.0 と同じく何も反映しない。
8. **本文の外の段落に結び付いた図形**（注・引用文献・表のセルなど）は、B3 では今までどおりその領域の段落として扱う（F の N7）。AI が
   アンカー段落を exclude にした場合も、その図形は「位置を決められない図表」から外れて中身が本文の段落として出る（0.21.0 からある。F で扱う）。
9. **F 番号・T 番号・段落の場所（「第N要素」）が 0.21.0 と変わる**（仮の位置・N18・N19 による）。AI のリンク先は `retarget_ops` で読み替える。
   レポート 4 章の決定の番号（M-00N）も並びが変わる。
10. 3 章の「場所」の列は、文字のないアンカー段落では段落 ID になる（0.21.0 から。`plan.locations` がない）。図表を探す手がかりは「理由」の列の
    「段落「…」の後ろ」で示す。

---

## 8. 関数ごとの変更一覧

### `src/jasme_jats/structure.py`

- 定数: `BODY_END = float("inf")`、`AFTER_BODY_REGIONS = {"notes", "ack", "fn", "refs", "back", "front_en", "app"}`（`TEXTBOX_TEXT_EXCLUDED` の後ろ）。
- `FloatInfo`: `where`・`end_why`・`end_after` を足す（1.2）。
- `ArticlePlan`: `figure_issues: list`（4.2）、`float_place(fid)`（1.2）。
- `float_caption(info)`（`pipeline._float_caption` を移す。モジュール関数）。
- `Classifier.build_body`: 1.3。
- `Classifier.place_floats`: 1.2（docstring も）。`provisional_target`（新設）。
- `Classifier.float_mechanical`: 最初に N18 の分岐（3.1）。docstring に「表のセルに画像とキャプションが並ぶ図（cell_figures）」を足す。
- `Classifier.cell_caption`・`Classifier.cell_figures`（新設。3.1・3.2）。
- `Classifier.assemble_floats`: 図キャプションの枝で、画像がないときに `table_for_figure`（4.1・4.2）。
- `Classifier.table_for_figure`（新設。4.1・4.2）。

### `src/jasme_jats/ai_assist.py`

- `RESPONSE_SCHEMA`・`SYSTEM_PROMPT`・`MANUAL_EXAMPLE`・`FIELD_GUIDE`・`manual_prompt`: 2.1。
- `AIOutcome`: `cut`・`partial`（2.2）。
- `call_api`・`call_openai`・`call_sakana`・`call_gemini`: 2.3。
- `_json_text`・`cut_at_end`・`parse_cut_response`（新設）、`parse_response` の取り出しと案内: 2.2・2.4。
- `float_placements`: 1.4（`AFTER_BODY_REGIONS` を `structure` から import）。`_placement_problem` は変えない。

### `src/jasme_jats/pipeline.py`

- import に `parse_cut_response`、`structure.float_caption`。
- `_read_cut`・`PARTIAL_MSG`（新設。2.2）、API・手動の読み取り（2.2）。
- `output_note`（1.6）、`forced_floats` と `unresolved_after`（1.6）、`figure_issues` の 3 章の行（4.2）、`REGION_JA`。
- `Result.forced_floats` のコメント。モジュールの docstring の手順に、途中で切れた回答の扱いを 1 行。

### `src/jasme_jats/report.py`

- `UNRES_JA["figbody"]`、`float_places(plan)`（新設）、要約の行、冒頭（図表の位置・図の本体・途中で切れた回答）、2 章、14 章、`render_ai_only`（1.6・2.2・4.2）。

### `src/jasme_jats/colab.py`

- `unplaced_box(plan)`: 1.6。`figure_body_box(res)`（新設。4.2）。

### `src/jasme_jats/cli.py`

- 位置を決められない図表の表示（1.6）、`res.ai.partial`（2.2）、図の本体の要対応（4.2）。

### `tools/make_notebook.py`（→ `python tools/make_notebook.py`）

- 手順 5・6: `figure_body_box` の表示、`res.ai.partial` の枠（2.2・4.2）。import に `figure_body_box`。

### テスト・fixture・版・文書

- 5 章と 6.2 のとおり。

---

## 9. 試作から直すこと（実装の担当へ）

試作（`scratchpad/b3/design/src`）は確かめ用で、次の点はこの設計書に合わせて直す:

- `pipeline` の 3 章の詳細: 「AI による補完でも…ため、AI が…ため、」と「ため」が重なる → 1.6 の 3 通りの文言。`end_after` と `REGION_JA` を使う。
- API モードの読み取り: 試作は `outcome.cut` のとき `parse_response` を試さずに `_read_cut` だけ → 2.2 のとおり先に `parse_response`。
- `call_openai`・`call_sakana`・`call_gemini` の `raw`・`cut`（試作は Claude だけ）。
- `colab.py`・`cli.py`・`make_notebook.py`・`figure_body_box`・レポートの冒頭（図の本体・途中で切れた回答）・`float_caption` の移動・`provisional_target` の切り出しは試作にない。
- ruff の 4 件（`Optional` → `X | None`、import の並び、ISC004）。
