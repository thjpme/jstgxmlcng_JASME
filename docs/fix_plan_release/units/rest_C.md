# 単位 C「冒頭部（題目・著者・所属）」の設計（0.34.0 の後）

対象: C009・C015・C016・C036・W6（あわせて C035 の知らせ、要確認 `name_split` を PDF で絞れるかの下調べ）。
この文書はコードを変えない設計だけ。未公開原稿の中身（氏名・題目・所属・本文）は書かない。例の文字はすべて架空。

再現・下調べの道具（作業用フォルダの中だけ。リポジトリには置いていない）:

- `design/rest/C/repro/repro.py` … 架空の最小の docx（`tests/make_fixtures.py` の `Builder`・`front_ja`・`front_en` で作る）13 種を変換して、題目・contrib・aff・知らせの key を出す。
- `design/rest/C/runs/` … 実際の原稿 9 docx × 2 ルートを 0.34.0 で変換した結果（`tools/one.py`、AI なし）。`show.py` で形だけを出す。
- `design/rest/C/w6/probe*.py` … 46 docx × 自分の PDF で、題目・著者名・所属が PDF のどこにあるか（probe.py）、英文の項目の照合の結果（probe7.py）、
  和文の氏名の PDF の字間（probe3.py・probe4.py）、判定案の件数（probe5.py）、候補の段落が 1 ページ目にあるか（probe6.py）。出すのは件数と形だけ。


---

## 0. 点検（C_review.md）を受けた設計の直しと、監督の決定（実装の前に反映したもの）

監督の決定: 4 章の「決めること」はすべて勧めのとおり（1: `authors_missing` を別の key。2: `front_check` は 1 つの key で、要対応の項目があれば要対応。3: C015 は出力したまま要対応。4: C036 は要確認。
5: PDF に見つからない英文の項目は `front_check` の要確認の項目。6: 2.6 は 0.35.0 で一緒に入れる。7: スタイルのない著者表は本文の表のまま `authors_missing`。8: `name_split` は PDF で絞らない。
9: `NAME_NEAR` は 0.6）。版は単位ごとに上げず、0.35.0 にまとめる。点検の指摘は、指摘の直し方のとおりに設計を直した（食い違うときは指摘に従う）:

1. **要対応どうしの重なり（should_fix）**: 和文の著者名が 1 人もないとき（`authors_missing`）は、`plan_findings` が `aff_missing`・`en_count`・`ja_missing`・swap を出さない
   （同じ原因を 2 つの要対応で言わない）。2.4 の「`en_count` は data17 だけ」は誤りで、`authors_missing` が出ない条件の下では data17 だけ。回帰の見込みの表
   （data12 の変種・data15 の変種）は `authors_missing`（と、data15 の変種は題目の `front_check`）だけ。架空の (3')（「所属　氏名」の 1 段落に著者名（日）を付けた形）は、
   和文の所属がないので要対応の `aff_missing`、著者名に所属の語があるので要確認の swap が 1 つの `front_check`（要対応）に入る。
2. **`style_check` との重なり（should_fix）**: `report.style_check_rows` と、スタイルの提案の数え方（`_ai_finish_action` の `m`）・2 章の表は、`authors_missing`・`front_check` に挙げた段落を除く
   （要対応の側を残す）。CLAUDE.md・DEVELOPMENT.md の `style_check` の記述に書き足した。
3. **`pdf_missing`（should_fix）**: 要確認にする（要対応にするのは、形から確かな template・swap の一部・著者名の欠けなど、PDF の要らない項目だけ）。`pdf_en_missing` は要確認のまま。
   CLAUDE.md の PDF の区分 (3)(4) に、冒頭部の項目だけの例外を 1 行書いた（照合の結果を読んで知らせるだけで、docx に足さない・直さない）。
   data17 の template と `pdf_missing` の段落が重なるときは、PDF の項目の側から重なる段落を除く（`frontcheck.front_findings`）。
4. **2.6（minor）**: `plan.decide` を書く枝を足した（条件を変えるだけでは記録されない）。端の形（空の章見出し＋標準スタイルの本文）と、本文の途中の空の章見出しをテストに足した。
5. **`excluded_unsure` の重複除き（minor）**: 除くのは `authors_missing` が出るときの候補と `front_check` の項目の段落だけ（`report.front_reported_srcs`）。出ないときの冒頭部の段落
   （誌名行など）は今までどおり `excluded_unsure` に出る。候補 (a) は、和文の題目より後ろの段落だけ（誌名行・題目より前を挙げない）。
6. **循環 import（minor）**: `frontcheck` は `pdfmatch` を import し、`pdfmatch.check_pdf` が `frontcheck.pdf_findings` を遅れて import して呼ぶ（`compare` の最後ではなく `check_pdf` の最後。
   route pdf で補う前の照合〈`pdfdocx`〉でも `check_pdf` は呼ばれるが、結果は知らせに使わない）。失敗しても照合の結果を損なわない（空にする）。
7. **回帰の基準（minor）**: この単位の基準は `runs_uB`（単位 B の後の出力）。
8. **C043・C130・C136（minor）**: 今回の対象外。次に回す（C130 は `title_multi` と同じ題目の組み立て〈`Builder.multi`・`title_group`〉に関わるので、そのとき同じテストに入れられるか検討する）。
9. **規模（minor）**: 手順 1 は M、手順 3 は M の上限（重複除きの規則を手順 3 にまとめた）。

---

## 1. 問題ごとの現状（0.34.0）

| 問題 | 起きた論文 | 0.34.0 | 今の出方 |
|---|---|---|---|
| C009 | data12 の変種（著者情報が表でない）、data18 の変種（英文著者が表でない）、架空の最小の docx | **まだ起きる**（形は一部変わった） | 下の 1.1 |
| C015 | data17（両ルート） | **まだ起きる**（変わらず） | 下の 1.2 |
| C016 | data18 の変種（副題が題目スタイル） | **まだ起きる**（変わらず） | 下の 1.3 |
| C036 | data8 の変種（所属と氏名のセルが逆） | **まだ起きる**（知らせの形が変わった） | 下の 1.4 |
| W6 | — | 未実装 | 下の 1.5 |
| C035（参考） | data15 の変種（題目が本文スタイル） | まだ起きる | 要対応は `upload`（EMSGM097E）だけで、原因（題目のスタイル）と直し方を言わない |

W1・W2・W8 で、この単位の問題が消えたものはない。W2〜W5 で入った `paper_verdict`（別の論文の判定）は、段落の半分を超えて見つからないときにだけ題目を見るので、
冒頭の誤りの確かめには使われていない。`pdfbiblio` は 1 ページ目の誌名の行と日付だけを読む。

### 1.1 C009（和文の著者名・所属が XML に入らなくても要対応にならない）

実際の原稿の変種（両ルート同じ）:

- data12 の変種（著者を表でなく 1 段落に書いた）: XML の contrib は英文の名前だけで、和文の氏名・所属がない。知らせは要確認 `excluded_unsure`
  （「XML に入れない文字なら、そのままでかまいません」）だけ。`needs_action` が真なのは図の画像の手順のため。
- data18 の変種（英文著者が表でない）: 英文の氏名・所属がない。知らせは `excluded_unsure` だけ（英文要旨のスタイルを勧める案内）。

架空の最小の docx（repro.py。すべて不変性チェック合格・DTD 合格・`needs_action` 偽）:

| 形 | XML | 知らせ |
|---|---|---|
| (1) 著者表のセルが標準のスタイル | 和文の著者・所属が消え、**著者表が本文の最初の `<table-wrap>` になる** | **なし** |
| (1') 著者表のセルが本文のスタイル | 同上 | **なし** |
| (2) 副題と著者表の間の空の段落が章見出しのスタイル | 同上（空の章見出しで本文に切り替わり、著者表が本文の表になる） | **なし** |
| (3) 「所属　氏名」の 1 段落（標準） | 和文の著者・所属が消える（除外 `FRONT_OTHER_EXCLUDED`） | 要確認 `excluded_unsure` |
| (3') 案内どおり (3) に「著者名（日）」を付けた | 姓に所属、名に氏名が入る | 要確認 `name_split`（「姓と名の分け方を確かめる」。直し方が違う） |
| (b2) 著者表がない | 和文の著者・所属がない | **なし** |
| (4) 英文の著者・所属がスタイルのない段落 | 英文の氏名・所属が消える | 要確認 `excluded_unsure` |

(2) は C041（0.33.0）で直ったと読める記録があるが、C041 が守るのは「空の段落の、後付けの見出し・英文の部分のスタイル」だけで、
**空の段落の本文の役割（章見出しなど）は `split_regions` の `role in BODY_ROLES` の枝で今も本文に切り替える**（structure.py 980 行）。

### 1.2 C015（白字のテンプレートの残り「氏名２／所属２」）

data17（両ルート）: contrib が 2 つで、2 人目は姓だけ（見本の文字「氏名２(MS明朝，11pt)」）、aff も 2 つ目（「所属２(MS明朝，10pt)」）。
知らせは要確認 `name_split`（見本の文字を氏名として「姓と名の分け方を確かめる」）だけ。行を消すという直し方は伝わらない。
架空の docx（著者表に白字の見本の行を足す）でも同じ形になる。

### 1.3 C016（題目のスタイルの段落が 2 つ）

data18 の変種（両ルート）: `<article-title>` が題目と副題を区切りなしでつないだ 1 つ（文字数が題目＋副題）で、`<subtitle>` がない。知らせなし。
架空の docx（副題を題目（日）のスタイルにする）でも同じ（`<article-title>` が「氏名の検証用文書―副題を題目のスタイルで―」）。
英文の題目でも同じ作り（`Builder.multi`）なので、英文では単語がつながる。

### 1.4 C036（所属と氏名の入れ替わり）

data8 の変種（両ルート）: 6 人すべてで、姓に所属の全体、名なし、所属に氏名が入る。知らせは要確認 `name_split`（6 人の「氏名」として所属を並べ、
「姓と名の間に空白を 1 つ置く」と勧める）。0.33.0 の C010・C064 で `name_split` が出るようになったので、**知らせなしではなくなったが、直し方が逆**。
架空の docx（セルを入れ替える）でも同じ。

### 1.5 W6 の下調べ（46 docx × 自分の PDF）

- **この誌の PDF では、和文の題目・著者名・所属は 1 ページ目、英文の題目・著者名・所属は論文の最後（9〜22 ページ目）にある。**
  W6 の「1 ページ目」は和文だけに当てはまり、英文は PDF の全体で探す必要がある。
- 和文の題目・著者名・所属を `pdfmatch.core`（NFKC・小文字・約物と記号を除く）にして、1 ページ目の `core` の中にそのままあるかを見ると、
  元の docx 28 本（変種を含め 46 本）で、**見つからないのは data17 の見本の行（氏名・所属の 2 つ）だけ**。誤報は 0。
  見つからないものの 1 ページ目との一致の割合（`_title_ratio` と同じ窓）は 0.27・0.36。
- 入れ替わり（data8 の変種）は、氏名も所属も 1 ページ目にあるので、PDF の有無では見つからない（形の確かめが要る）。
- 英文: 照合（`compare`）で**見つからない段落**（`PdfCheck.unmatched`）になった英文の項目は 4 本・4 件（data5・data16・data26 の英文の所属、data17 の英文の氏名 1 人）。
  今は 13 章の記録（区分 (4)）だけで、知らせにならない。C049 の「実物で本物だったのは英文の所属 2 件で、W6 が拾う」はこれ（0.34.0 では 4 件）。
  照合できて違いのあるもの（data14 の英文の氏名、data28 の英文の題目）は、既に要確認 `pdf_mismatch` に載る。
- 候補の段落: data12 の変種の 1 段落の著者（除外 `FRONT_OTHER_EXCLUDED`）、data15 の変種の題目（本文の段落）と著者表（本文の表のセル）は、
  どれも 1 ページ目にある。ただし誌名の行などの装飾（`FRONT_DECORATION_EXCLUDED`）も 1 ページ目にあるので、「1 ページ目にある」だけでは候補にできない
  （候補は理由・位置で選び、1 ページ目にあるかは添えるだけにする）。data18 の変種の英文の氏名・所属の段落は、1 ページ目にはなく、PDF の最後にある。
- 判定案の件数（probe5.py。46 docx）: 著者名に所属の語・所属が氏名の形（C036 の案）は data8 の変種だけ（6/6）。テンプレートの見本の形（C015 の案）は data17 だけ（2）。
  題目の段落が 2 つ以上は data18 の変種だけ。和文と英文の著者数の違いは data17 だけ。和文の著者 0 人は data12 の変種・data15 の変種だけ。元の 28 本はどれにも当たらない。

### 1.6 要確認 `name_split` を PDF で絞れるか（下調べの結論: ほとんど絞れない）

- 0.34.0 で `name_split` が出る元の論文は **11 本**（data3・4・10・11・13・14・17・18・20・21・22。FIX_PLAN_RELEASE の「9 論文」と違う。13 章の 3 の食い違い）。
  内訳: 空白のない 4 字の氏名（data3・4・10・11・20・22）、空白のない 3 字・5 字の氏名（data13・14）、字間の空白で分けた氏名（data18 はいちばん長い空白、data21 は字数の推定）、
  テンプレートの見本（data17。C015 を直せば消える）。
- **PDF の英文著者名では絞れない。** ローマ字の姓（「SHIKEN」）から漢字の字数は決まらない（読みが分からない）。
- **PDF の 1 ページ目の和文の氏名の字間**（pypdfium2 の文字の箱。probe4.py）: 4 字の氏名は、docx に「姓　名」の空白があるものも含めて、すべて字間が均等
  （字の高さの約 1.2 倍）で、境目が見えない。3 字の氏名は 2＋1・1＋2 の境目にだけ広い空き（約 3.3 倍）があり、境目が分かる。5 字は 2＋3 で「空いた字と詰めた字」の並び。
  したがって、PDF で境目が分かるのは 3 字の氏名だけで、`name_split` が消せるのは data18（PDF の境目が分け方と一致）の 1 本だけ。
  data13・data14 は空白がないので XML に名がなく、PDF の境目が分かっても要確認は残る（直し方に「PDF では 2 字目の後ろが空いている」と添えることはできる）。
- **PDF から姓と名を分けることはしない。** 「docx → XML の処理は PDF の有無で変わらない」（CLAUDE.md の原則）に反する。PDF は知らせの文にだけ使える。
- 勧め: 今回は絞らない（11 本 → 10 本の効果に比べ、字の箱の読み取りという新しい仕組みが増える）。C015 の直しで data17 の `name_split` は消える（下の 2.2）。

---

## 2. 設計

全体の形: **構造は変えず、知らせる**（所有者の決定 C009・C015、D-R1-09・13・18・29、C036 の勧め）。構造を変えるのは、空の段落で領域を切り替えない 1 か所（2.6）だけ。
知らせは `report.actions()` に 2 つの `Action` を足す。

| key | 重さ | 中身 | PDF |
|---|---|---|---|
| `authors_missing` | 要対応 | 記事が和文なのに、和文の著者名が 1 人もない（C009。FIX_PLAN の「PDF がないときのために…別に持つ」） | 要らない（あれば候補が 1 ページ目にあるかを添える） |
| `front_check` | 要対応の項目が 1 つでもあれば要対応、なければ要確認（`meta_pdf` と同じ作り） | 冒頭部の確かめをまとめた 1 つ（W6）: C015・C035・C016・C036・C009 の残り・PDF にない題目／著者名／所属 | 項目の一部だけが要る |

新しいモジュール `src/jasme_jats/frontcheck.py` を作り、判定をここに集める（plan を読むだけで、文字も構造も変えない）:

```python
@dataclass
class FrontFinding:
    kind: str        # 下の項目の名前（template・title_missing・title_multi・swap・ja_missing・aff_missing・en_missing・
                     #   en_count・pdf_missing・pdf_near・pdf_en_missing）
    level: str       # "must"（要対応）か "check"（要確認）
    srcs: list       # 段落 ID（docx の順）
    note: str = ""   # 文に添える短い材料（「2 段落目がダッシュで始まる」「所属の語『大学』」など。原稿の文字は抜粋だけ）

def plan_findings(plan, lang) -> list          # PDF の要らない項目
def author_candidates(plan) -> list            # 和文の著者名・所属らしい段落の ID
def pdf_findings(plan, pages, res) -> list     # PDF の要る項目（pdfmatch.compare の最後で呼ぶ）
def front_findings(r) -> list                  # report が使う: plan_findings ＋ r.pdf_check.front
```

記事の言語は `builder.Builder.article_lang` と同じ規則（`meta.lang or plan.lang or journal.lang`）で決め、`report` 側で求めて渡す（英文の記事では和文の項目を見ない）。

### 2.1 C009 — 和文の著者が取れないとき（要対応 `authors_missing`）

- **起きる条件**: 記事が和文（上の規則）で、`plan.authors` に `name_ja` のある著者が 1 人もない。原因は 1.1 の (1)〜(b2)。
- **直し方（知らせるだけ）**:
  1. `frontcheck.author_candidates(plan)`: 候補の段落を docx の順で返す。(a) 除外の理由が `FRONT_OTHER_EXCLUDED`・`FRONT_TABLE_EXCLUDED`・`AUTHOR_TABLE_OTHER_EXCLUDED` の段落、
     (b) 本文の領域（`plan.region` が body）で、最初の章・節・項見出し（役割が `HEADING_LEVEL`）より前の段落と表のセル（1.1 の (1)(2) で本文の表になった著者表）。空白だけの段落は除く。
  2. `report.py` に `_authors_missing_action(r)` を足し、`actions()` の `head` の、`_unplaced_action` の前に入れる（3195〜3199 行の並び）。
     PDF があり照合できたとき（`r.pdf_check.ok`）は、候補のうち `core` が 1 ページ目（2.5 の「題目のページ」）にあるものに「PDF の 1 ページ目にあります」と添える。
  3. `report.unplaced_exclusions`（1868〜1872 行）で、`authors_missing` の候補に挙げた段落を除く（`abstract_missing` と同じ扱い。同じ段落を赤と黄で 2 回出さない）。
  4. `UNPLACED_GUIDE`（1876〜1885 行）の文を直す: `FRONT_OTHER_EXCLUDED` に「所属と氏名が 1 つの段落なら、Enter で 2 段落に分けてから付ける」を足す。
     `EN_OTHER_EXCLUDED` に「英文の著者名・所属なら『著者名（英）』『所属（英）』」を足す（C009 の手順 2・3）。スタイル名は `_first_style` で引く。
- **文の案**（スタイル名は `_first_style(journal, "author_ja", "著者名（日）")` などで引く）:
  - top: 「**要対応: 和文の著者名が 1 人も見つかりません（XML の書誌に和文の著者名・所属が入っていません。6 章）。** Word で、著者表の氏名のセルに「著者名（日）」、
    所属のセルに「所属（日）」のスタイルを付けて（所属と氏名が 1 つの段落なら、Enter で 2 段落に分けてから付けて）、変換し直してください。
    著者名・所属らしい段落: d5「架空大学　試験…」（PDF の 1 ページ目にあります）、d7「試験　六郎」（本文の最初の表として出力しています）。」
  - checklist: 「- [ ] **和文の著者名・所属**（6 章）: 著者表に「著者名（日）」「所属（日）」のスタイルを付けて変換し直す」（印は `checklist_line` が付ける）
  - box_title: 「和文の著者名が見つかりません（要対応）」。box_detail は top と同じ中身（画面の操作の語は `report.step()` の目印で書く）。
  - cli: 「要対応: 和文の著者名が見つからない（XML に和文の著者名・所属が入っていない。レポートの冒頭と 6 章）。docx の著者表に『著者名（日）』『所属（日）』のスタイルを付けて変換し直すこと。候補: d5「…」」
- **原則との関係**: 文字も構造も変えない（XML は今と同じ）。除外は今までどおり理由付き（`FRONT_OTHER_EXCLUDED` など）で、知らせの重複を除くだけ。知らせは Action だけ。PDF は候補の添え書きに読むだけで、docx に足さない。
- **足すテスト**（tests/test_front.py を新しく作る。repro.py の作り方を `tests/make_fixtures.py` に `front_variant(...)` として移す。内容は架空）:
  (1)(1')(2)(3)(b2) で `authors_missing` が要対応・`needs_action` が真・CLI の終了コードが 1、候補の段落 ID が文に入る。(3) では `excluded_unsure` に同じ段落が出ない。
  (4) では `authors_missing` が出ず（和文はある）、`excluded_unsure` の文に「著者名（英）」が入る。英文の記事（`meta.lang` が en）で和文の著者がなくても出ない。
  既存の fixture（sample_full・sample_pdfcheck など）で出ない。
- **回帰で変わる見込み**: data12 の変種（+`authors_missing`、`excluded_unsure` が消える）、data15 の変種（+`authors_missing`）。元の 28 本は変わらない（和文の著者 0 人は 0 本）。XML はどれも変わらない。
- **危険と避ける条件**: 英文で書かれた記事で誤って要対応になる → 言語の規則を `article_lang` と同じにする。候補に本文の段落が混ざる（著者表がなく本文がすぐ始まる原稿で、最初の見出しより前の本文の段落）→ 候補は「らしい段落」と書き、要対応の理由は「和文の著者 0 人」だけにする（候補の当たり外れで重さを変えない）。

### 2.2 C015 — テンプレートの見本の行（`front_check` の項目 template・要対応）

- **起きる条件**: 著者表（和文・英文）か段落の著者名・所属が、テンプレートの見本の形。判定 `frontcheck.template_placeholder(text)`:
  NFKC にして空白を除いた文字が `^(氏名|所属|著者名?|name|affiliation|author)[0-9]*(\(.*\))?$`（大文字・小文字を問わない）か、括弧の中にフォント名（明朝・ゴシック・Century・Times など）と
  「NNpt」の書式見本を含む。白字（`w:color`）は見ない（形だけで data17 に当たり、黒字の残りも拾える。`HiddenRule` は広げない。D-R1-13 (2)(a)）。
- **直し方（知らせるだけ。所有者の決定「変換は変えず、知らせる」）**: `plan_findings` で、`plan.authors` の `name_ja`・`name_en` と `plan.affs` の `ja`・`en` に当て、当たった段落を 1 つの項目にする。
  文: 「著者表に、テンプレートの見本の行（d40「氏名２(MS明朝，11pt)」、d41「所属２(MS明朝，10pt)」）が残っていて、XML に 2 人目の著者・所属として出ています。
  単著なら、Word で著者表のその行を消して（白字で見えないことがあります）変換し直してください。」
  `report.name_split_items`（2785〜2789 行）で、`front_check` の template・swap の項目の段落を除く（同じ段落を「姓と名の分け方」として出さない）。
- **原則との関係**: 文字も構造も変えない。D-R1-13 の勧め (b)（理由付きで除外）は採らない（FIX_PLAN の所有者の決定が後）。除外するなら出力の形が変わる（4 章の決めること）。
- **足すテスト**: 架空の単著の著者表に見本の行を足した docx（白字版・黒字版）で、`front_check` が要対応・template の項目に 2 段落、`name_split` に見本の氏名が出ない。
  見本の形でない架空の実名（「氏名　太郎」「所属　花子」のような 2 語）では出ない。英文の見本（「Name2 (Century, 11pt)」）でも出る。
- **回帰で変わる見込み**: data17（両ルート）: +`front_check`（要対応）、`name_split` が消える（1 人目の氏名は空白 1 つで分けられるので載らない）。XML は変わらない。`needs_action` は今も真（図の画像）。
- **危険**: 判定が広いと実名を見本にする → 番号つきの「氏名N」の形と、書式見本の括弧（フォント名と pt）に限る。46 docx で当たるのは data17 の 2 段落だけ。

### 2.3 C016・C035 — 題目（項目 title_multi・要確認、title_missing・要対応）

- **title_multi（C016。D-R1-18 (a)）**: `plan.title`・`plan.subtitle`・`plan.title_en`・`plan.subtitle_en` のどれかが 2 段落以上。項目の srcs はその段落、
  note は場所（題目（日）・副題（日）・題目（英）・副題（英））と、2 段落目がダッシュ（―－—–〜~）で始まるか。
  文: 「題目（日）のスタイルの段落が 2 つあり、XML では 1 つの題目に区切りなしでつないでいます（d3・d4）。d4 はダッシュで始まるので副題のようです。
  副題なら Word でその段落を「副題（日）」のスタイルに、題目の続きなら 1 段落にまとめて（改行が要るなら Shift+Enter）、変換し直してください。」
  `BuildInfo` に `multi_titles` を足す案（C016 の詳細）は採らない。`plan` だけで決まり、builder を触らずに済む（`Builder.multi` は今のまま）。
- **title_missing（C035。D-R1-29 (a)）**: 記事が和文で `plan.title` が空。srcs は `author_candidates` と同じ考えで、最初の見出しより前の本文の段落（題目らしい段落）。
  文: 「『題目（日）』のスタイルの段落がありません（XML に和文の題目がありません）。Word で題目の段落にそのスタイルを付けて変換し直してください。題目らしい段落: d3「…」（PDF の 1 ページ目にあります）。」
  要対応 `upload`（EMSGM097E）はそのまま残る（J-STAGE の確かめで別の知らせ）。
- **原則との関係**: 文字も構造も変えない（D-R1-18 (b) の自動で副題にする直しは採らない。(c) 英文の題目の段落の間に空白を足すことは docx にない文字なのでしない）。
- **足すテスト**: (a) 題目（日）が 2 段落（2 段落目が「―」で始まる）で title_multi が要確認・両方の段落 ID・「副題のよう」、`<article-title>` の文字は今と同じ。
  (b) 題目（英）が 2 段落で同じ。(c) 普通の 1 段落の題目・副題で出ない。(d) 題目が本文のスタイルの docx で title_missing が要対応。不変性チェックはどれも合格のまま。
- **回帰で変わる見込み**: data18 の変種（+`front_check`、要確認）、data15 の変種（+`front_check`、要対応）。元の 28 本は変わらない（題目の段落が 2 つ以上は 0 本）。

### 2.4 C036 と C009 の残り — 著者表の形（項目 swap・ja_missing・aff_missing・en_missing・en_count）

- **swap（C036。要確認。決めること「少なめの語で、要確認」）**: 和文の著者名（`Author.name_ja`）に所属の語があるか、和文の所属が「空白で区切った 1〜5 字の 2 語」の氏名の形で所属の語を含まない。
  所属の語（少なめ）: 大学・学校・高校・高専・学園・学院・研究科・研究所・研究院・学部・学科・センター・教育委員会・機構・附属・付属・University・School・College・Institute・Graduate・Faculty・Department。
  1.1 の (3')（「所属　氏名」の 1 段落に「著者名（日）」）もこれで拾える。
  文: 「著者名 d10「…大学…」に所属の語（「大学」）があります（所属 d9「試験　六郎」は氏名の形です）。著者表の所属と氏名のセルのスタイルが入れ替わっていないか確かめ、
  入れ替わっていれば Word でセルのスタイル（『著者名（日）』『所属（日）』）を付け直して変換し直してください。所属と氏名が 1 つの段落なら、Enter で 2 段落に分けてください。」
  `name_split_items` から、この項目の氏名を除く（2.2 と同じ）。
- **ja_missing（要対応）**: 和文の著者がいる（`authors_missing` が出ない）のに、`name_ja` のない著者（英文だけの著者）がいる。英文の著者数が和文より多いとき。
- **aff_missing**: 和文の所属（`Aff.ja`）が 1 つもない → 要対応（所属のセルのスタイル違い。`AUTHOR_TABLE_OTHER_EXCLUDED` の段落を候補に挙げる）。
- **en_missing（C009 の (4)。要確認。D-R1-09 (1)(a)）**: 英文の題目がある記事で `name_en` のある著者が 1 人もない。候補は除外 `EN_AUTHOR_TABLE_OTHER_EXCLUDED`・`EN_OTHER_EXCLUDED` のうち英文の題目の後ろ・英文要旨の見出しの前の段落。
  `unplaced_exclusions` から候補を除く。
- **en_count（C015 の 3。要確認）**: 英文の著者が 1 人以上いて、和文と英文の著者数が違う（見本の形に当たらない残りも拾う網）。template の項目と同じ段落なら 1 つにまとめる。
- **原則との関係**: 役割の入れ替え（自動で所属と氏名を入れ替える）はしない（C036 の「その後」の結論）。文字も構造も変えない。
- **足すテスト**: 所属と氏名のセルを入れ替えた架空の著者表で swap が要確認・`name_split` に出ない。空白のない架空の氏名（「試験六郎」）・「大学」を含まない所属で出ない。
  「所属　氏名」の 1 段落に著者名（日）を付けた docx で swap が出る。英文著者を標準の段落にした docx で en_missing。和文 2 人・英文 1 人で en_count、2 人・2 人で出ない。
- **回帰で変わる見込み**: data8 の変種（+`front_check`〈要確認〉、`name_split` が消える）、data18 の変種（en_missing が title_multi と同じ `front_check` に入る。`excluded_unsure` が消える）、
  data17（en_count。template と同じ `front_check`）。元の 28 本は変わらない（swap・en_missing は 0 本、en_count は data17 だけ）。
- **危険**: 「学院」「大学」を含む実在の姓（まれ）で誤報 → 要確認にとどめる。所属が氏名の形の判定は、所属の語のない短い 2 語に限る（「架空　研究会」のような所属で誤報がありうるが要確認）。

### 2.5 W6 — 題目・著者名・所属が PDF にあるか（項目 pdf_missing・pdf_near・pdf_en_missing）

- **どこで計算するか**: `pdfmatch.compare` の最後（917〜920 行の `paper_verdict` の後）で `res.front = frontcheck.pdf_findings(plan, pages, res)` を呼ぶ。
  `PdfCheck`（428 行〜）に `front: list` を足す。`check_pdf` が PDF を読む 1 回の `pages` を使い、`pipeline` は触らない。`res.ok` が偽（読めない）か `verdict` が wrong・garbled なら空。
  `pdfbiblio` は 1 ページ目の誌名の行と日付だけを読むので使わない（作りの手本だけ: 読めなければ空にし、例外にしない）。
- **題目のページ**: 和文の題目（`plan.title` の段落を `core` してつないだもの。`TITLE_MIN` 字以上）が `core` のままある最初のページ。なければ `_title_ratio` の窓で `TITLE_RATIO` 以上のいちばん高いページ。
  どちらもなければ 0 ページ目。号全体の PDF（題目が後ろのページ）でも誤報にしないため（`paper_verdict` の TITLE_PAGES は 2 ページだけ）。和文の題目がなければ 0 ページ目。
- **和文の項目**（題目の段落・和文の著者名・和文の所属。それぞれ 1 段落ごと。`core` が空や 2 字未満は見ない）:
  `core` が題目のページ（とその次のページ）の `core` の中にあれば何もしない。なければ同じ窓の一致の割合を求め、`NAME_NEAR`（0.6。推測）以上なら pdf_near（要確認。
  「PDF の 1 ページ目の文字と少し違います。異体字・校正の直しかもしれません」）、未満なら pdf_missing（要対応）。
  題目の段落は、照合（`target_paragraphs`）でも違いが `pdf_mismatch` に出るので、題目は pdf_missing（未満）だけを項目にし、pdf_near は出さない（重複を避ける）。
- **英文の項目**（英文の題目・著者名・所属）: 照合で見つからない段落（`res.unmatched` にあり `res.found_elsewhere` にない）だけを pdf_en_missing（要確認）にする。
  照合できて違いのあるものは `pdf_mismatch` に既に載るので足さない。英文は PDF の最後のページにあるので、1 ページ目では探さない。13 章の記録（区分 (4)）はそのまま。
- **文の案**（`front_check` の 1 項目）: 「出版版 PDF の 1 ページ目に見つからない和文の項目: 著者名 d40「…」、所属 d41「…」。著者表に余分な行がないか、docx が校正後の版かを確かめ、
  Word で直して変換し直してください。」／「出版版 PDF に見つからない英文の所属 d1272「…」（校正で直ったのかもしれません）。PDF が正しければ docx を直して変換し直してください。」
- **`front_check` の全体の文**: top は「**要対応（または要確認）: 題目・著者・所属を確かめてください（4 章・7 章）。**」の後に、要対応の項目、確かめる項目の順に箇条で並べる
  （項目ごとに直し方の 1 文）。checklist は「- [ ] **題目・著者・所属**（N 件。4 章・7 章）: …」、cli は「要対応: 題目・著者・所属に直す所がある（テンプレートの見本の行、PDF にない著者名 ほか。レポートの冒頭）」。
  画面の文は `step()` の目印で書く。種類の印は `checklist_line` が付ける（文に手で書かない）。
- **原則との関係**: PDF は読むだけで docx に足さない・消さない・置き換えない。docx → XML の処理は PDF の有無で変わらない（`res.front` は知らせにだけ使う）。
  補完の確かめ（`fidelity.verify_supplement`）には触れない。ルート pdf では補った docx の plan と照らすが、`core` は表記の違い（区分 (1)）を見ないので結果は同じ。
- **足すテスト**: `pdf_findings` を、ページの文字（文字列のリスト）を渡して単体で確かめる: 著者名・所属があるとき空、ないとき pdf_missing、1 字違い（「髙」と「高」）で pdf_near、
  題目が 3 ページ目にある号全体の形でも誤報しない、英文の所属が `unmatched` のとき pdf_en_missing、`found_elsewhere` のとき出ない。sample_pdfcheck.docx ＋ sample_pdfcheck.pdf の変換で `front_check` が出ない。
- **回帰で変わる見込み**: data17（pdf_missing 2 件と英文の氏名の pdf_en_missing が template と同じ `front_check` に入る）、
  **data5・data16・data26（両ルート）: +`front_check`（要確認。英文の所属が PDF に見つからない）**。ほかの元の論文は変わらない（和文の項目は 28 本すべて 1 ページ目にある）。
- **危険**: 異体字・合字の違いで要対応の誤報 → 一致の割合が高ければ要確認に下げる。号全体の PDF → 題目のページから探す。英文の所属の 3 本は要確認が 1 件増える（本物の違い。警告を増やさない方針との釣り合いは 4 章の決めること）。

### 2.6 構造を変える直し: 和文の冒頭で、空の段落の本文の役割で本文に切り替えない（C009 の (2)）

- **起きる条件**: 和文の冒頭（題目の後・著者表の前）に、章見出しなど本文の役割のスタイルの**空の**段落がある（テンプレートの空行のスタイルが変わったとき）。
- **直し方**: structure.py `split_regions` の和文の冒頭の枝（977〜991 行）の `elif role in BODY_ROLES and not (role == "p" and b.is_blank):` を、
  `elif role in BODY_ROLES and not b.is_blank:` にする（空白だけの段落は、役割によらず和文の冒頭のまま。C041 の「空白だけの段落で領域を切り替えない」を本文の役割にも広げる）。
  画像のある空の段落は `is_blank` が偽なので今のまま。切り替えなかったことは C041 と同じく `plan.decide` に記録する。
- **原則との関係**: 文字は変えない。空の段落は今までどおり `exclude_blank` か本文の空の見出し（出力しない）で、落とすのは空白だけ。
- **足すテスト**: 1.1 の (2) の docx で、著者表が著者として読まれ（contrib に和文の氏名）、本文に `<table-wrap>` がない。空の章見出しスタイルが本文の途中にある docx（data9 の変種の形）は今と同じ。
- **回帰で変わる見込み**: 46 docx では 0 本の見込み（元の 28 本に、題目の後の空の本文の役割の段落はない。実装の後に回帰で確かめる）。出力の形が変わるので版は 2 桁目。
- **危険**: 冒頭の空の章見出しのすぐ後ろが本当の本文の表（著者表でない）の原稿 → 表は今の規則（題目を見た後の、著者の役割のない表で本文に切り替える）で本文に入るので変わらない。

### 2.7 構造を変える直しと、知らせるだけの直しの勧め

| 問題 | 構造を変える案 | 知らせるだけの案 | 勧め |
|---|---|---|---|
| C009 (1)(1') スタイルのない著者表 | 形から著者表と推定して読む／冒頭の表として除外する（C009 の「その後」の 4） | `authors_missing`（要対応）で Word のスタイルを直してもらう | **知らせるだけ**。推定を誤ると氏名が化ける（D-R1-09 (2)(a)）。除外に回しても要対応は残り、利用者の手間は同じ |
| C009 (2) 空の本文の役割の段落 | 2.6（1 行） | `authors_missing` | **構造を変える**。空白だけの段落で領域を切り替えないのは推定ではなく、C041 と同じ規則の穴埋め |
| C009 (3) 1 段落の「所属　氏名」 | 空白で分けて所属と氏名にする | `authors_missing`・swap | **知らせるだけ**（推定になる） |
| C015 | 見本の行を理由付きで除外（D-R1-13 (b)） | template（要対応） | **知らせるだけ**（所有者の決定「変換は変えず、知らせる」）。除外するかは 4 章で確かめる |
| C016 | ダッシュの 2 段落目を副題にする（D-R1-18 (b)） | title_multi（要確認） | **知らせるだけ**（D-R1-18 (a)） |
| C035 | 題目を推定して戻す（D-R1-29 (b)） | title_missing（要対応） | **知らせるだけ**（D-R1-29 (a)） |
| C036 | 役割の入れ替え | swap（要確認） | **知らせるだけ**（原則に反する） |
| name_split | PDF の字間で姓と名を分ける | 字間を直し方に添える | **どちらも今回はしない**（1.6。分けるのは原則に反する） |

---

## 3. 実装の手順

テストが通る小さな単位。規模は S（1 関数・50 行以内）・M（数関数・テスト込み 300 行以内）。

| 番号 | 中身 | 規模 | 担当 |
|---|---|---|---|
| 1 | `tests/make_fixtures.py` に冒頭部の変種を作る関数（`front_variant`。repro.py の 13 形を架空の内容で）を足し、今の出方を固定する再現テスト（xfail）を書く | S | Sonnet |
| 2 | `frontcheck.py` の骨組み（`FrontFinding`・`author_candidates`）と `report._authors_missing_action`、`unplaced_exclusions` の重複除き、`UNPLACED_GUIDE` の文（2.1） | M | Sonnet |
| 3 | `plan_findings` の template・title_multi・title_missing と、`report._front_check_action`（重さの決め方・文の組み立て）、`name_split_items` の重複除き（2.2・2.3） | M | Sonnet |
| 4 | `plan_findings` の swap・ja_missing・aff_missing・en_missing・en_count（2.4） | S | Sonnet |
| 5 | `pdf_findings`（題目のページ・和文の項目・英文の項目）と `PdfCheck.front`、`compare` からの呼び出し。ページの文字を渡す単体テスト（2.5） | M | Opus（しきい値と、照合の結果との重複の整理） |
| 6 | `split_regions` の空の段落（2.6）と、その回帰（46 docx × 2 ルート。XML の差が 0 か、変わったのが狙いの形だけか） | S | Sonnet（点検は Opus） |
| 7 | 46 docx × 2 ルートの回帰（`regress.py`。基準は runs_ のうち最新）。知らせの差が 2 章の「回帰で変わる見込み」どおりかを確かめ、外れれば 2〜6 に戻る | S | Sonnet |
| 8 | 文書: `docs/DEVELOPMENT.md`（知らせの一覧）・`ARCHITECTURE.md`（frontcheck の位置と逆引き）・`DESIGN.md`・`USAGE.md`（冒頭部の知らせの読み方）・`FIELD_TEST_2026-11.md` の対応の記録・`FIX_PLAN_RELEASE.md`（name_split の本数）。版を 0.35.0 に（2.6 で出力の形が変わる）、ノートブックを作り直す | S | Haiku（文）／Sonnet（記録） |
| 9 | 点検（原則・回帰・利用者向け）。修正と再点検は最大 3 回 | — | Opus（原則）、Sonnet（回帰・利用者向け） |

手順 2〜4 は XML を変えない（知らせだけ）ので、2.6（手順 6）を外して 0.34.1 として先に出すこともできる（4 章の決めること 6）。

---

## 4. 所有者・監督が決めること

1. **和文の著者 0 人の要対応を別の key にするか**: (a) `authors_missing` を別に持ち、`front_check` はそれ以外をまとめる（FIX_PLAN の書き方どおり。**勧め**。いちばん多い形を 1 つの直し方で伝えられ、PDF がなくても同じ）、
   (b) `front_check` の 1 項目にする（知らせの数が 1 つ減る）。
2. **`front_check` の重さ**: (a) 1 つの key で、要対応の項目があれば要対応・なければ要確認（`meta_pdf` と同じ作り。**勧め**）、(b) 要対応 `front_check` と要確認 `front_suspect` の 2 つに分ける。
3. **C015 の見本の行**: (a) 出力したまま要対応（**勧め**。所有者の決定「変換は変えず、知らせる」）、(b) 理由付きで除外して要確認（D-R1-13 の勧め。出力の形が変わる）。
4. **C036 の重さ**: (a) 要確認（**勧め**。決定事項の勧め。所属の語を含む実名がありうる）、(b) 氏名と所属の両方が当たる（入れ替わりが確か）ときだけ要対応。
5. **PDF に見つからない英文の所属・氏名（data5・data16・data26・data17）**: (a) `front_check` の要確認の項目にする（**勧め**。C049 で本物と確かめた違いで、冒頭部の知らせを 1 か所にまとめる）、
   (b) `pdf_mismatch` の一覧に入れる、(c) 今のまま 13 章の記録だけ。(a)(b) では元の 3 本で要確認が 1 件増える。
6. **空の本文の役割の段落で切り替えない直し（2.6）を入れる版**: (a) 0.35.0 で知らせと一緒に入れる（**勧め**）、(b) 知らせだけを 0.34.1 で先に出し、2.6 は後で。
7. **スタイルのない著者表（C009 の (1)）**: (a) 本文の表のまま `authors_missing` で知らせる（**勧め**）、(b) 著者をまだ見ていない間は冒頭の表として除外する（C009 の「その後」の 4。出力の形が変わる）。
8. **`name_split` を PDF で絞るか**: (a) 今回はしない（**勧め**。1.6 の結果で、消せるのは 1 本）、(b) 3 字の氏名だけ PDF の 1 ページ目の字間で確かめ、一致すれば載せない・空白のない氏名には PDF の境目を直し方に添える（S。字の箱の読み取りが増える）。
9. **しきい値**: 和文の項目を「少し違う」（要確認）とみなす一致の割合 `NAME_NEAR` を 0.6 にする（推測。46 docx では見つからない 2 件が 0.27・0.36、当たるべきものはすべてそのままある）。実物の次の号で測り直す。

---

## 5. 文書と既存のコードの食い違い（見つけたもの。どれも直していない）

1. `docs/FIX_PLAN_RELEASE.md`・`docs/FIELD_TEST_2026-11.md`（C010 の記録）は「`name_split` は 28 論文中 9 論文で出る」とするが、0.34.0 では元の 28 本のうち 11 本で出る（1.6）。
2. `docs/FIELD_TEST_2026-11.md` の C009 の条件 (2)（副題と著者表の間の空行が本文の役割のスタイル）は、C041（0.33.0）の記録から直ったように読めるが、C041 が守るのは後付けの見出し・英文の部分の
   スタイルの空の段落だけで、本文の役割の空の段落では今も本文に切り替わる（structure.py 980 行。2.6）。
3. `docs/FIX_PLAN_RELEASE.md` の W6 は「PDF の 1 ページ目にあるか」とするが、この誌の PDF では英文の題目・著者名・所属は論文の最後のページにある（1.5）。設計では英文は PDF の全体（照合の結果）で見る。
4. `docs/FIELD_TEST_2026-11.md` の C049 の記録「実物で本物だったのは英文の所属 2 件」に対し、0.34.0 の照合で見つからない英文の項目は 4 件（所属 3・氏名 1）。
5. `docs/FIX_PLAN_RELEASE.md` の問題ごとの決定（C015「変換は変えず、知らせる」）と、同じ文書が参照する決定事項 D-R1-13 の勧め (1)(b)（理由付きで除外）が違う。日付の新しい所有者の決定を採った（4 章の 3）。
6. `docs/FIELD_TEST_2026-11.md` の C016 の直し方は `BuildInfo.multi_titles` を `Builder.title_group` で記録するとするが、この設計では `plan` だけで決まるので builder を触らない形にした（2.3）。


---

## 実装の記録（2026-11-15）

済ませた手順: 1〜8（版上げ・ノートブックの作り直し・手順 9 の点検は、監督が版をまとめて 0.35.0 にするので行わない。回帰は回した）。

- 手順 1: `tests/make_fixtures.py` に `front_variant`（冒頭部の変種。kind は ok・table_normal・table_body・blank_sec1・one_para・one_para_author・no_author・template・template_black。
  著者・題目・英文の著者を引数で変えられる）と `make_template_filled`（テンプレートそのままの docx の見本の行を架空の著者・所属に書き換えた `tests/fixtures/JASME_template_filled.docx`。
  conftest の `TEMPLATE_FILLED`）。xfail の再現テストは作らず、実装と同時に `tests/test_front.py` にした（今の出方は実装前に `front_variant` の変換で確かめた）。
- 手順 2: `frontcheck.py`（`FrontFinding`・`authors_missing_applies`・`author_candidates`）、`report._authors_missing_action`（`actions()` の `_unplaced_action` の前）、
  `report.front_reported_srcs`（`unplaced_exclusions`・`style_check_rows`・`_ai_finish_action` の数え・2 章のスタイルの提案・6 章の印で使う）、`UNPLACED_GUIDE` の文。
- 手順 3・4: `frontcheck.plan_findings`（template・title_missing・title_multi・swap・ja_missing・aff_missing・en_missing・en_count。`authors_missing` が出るときは swap・ja_missing・aff_missing・en_count を出さない）、
  `report._front_check_action`・`_front_item_text`、`name_split_items` の重複除き。
- 手順 5: `frontcheck.pdf_findings`・`title_page`、`pdfmatch.PdfCheck.front`・`front_on_page`（`check_pdf` が遅れて import して呼ぶ。失敗しても照合の結果は損なわない）。
- 手順 6: `structure.split_regions` の和文の冒頭の枝（空白だけの段落は、本文の役割でも領域を切り替えない。本文の役割が `p` 以外のときは `plan.decide` に記録）。
- 手順 7: 回帰（`regress.py uC --base uB`。46 docx × 2 ルート、92 件）: 違うのは 20 件（10 原稿 × 2 ルート）で、設計の見込みどおり。XML・状態（不変性チェック・最終チェック・補完の確かめ・例外・DTD）の差は 0。
  知らせの key の差: data12 の変種に要対応 `authors_missing`（要確認 `excluded_unsure` が消える）、data15 の変種（題目が本文スタイル）に要対応 `authors_missing` と要対応 `front_check`（題目の段落がない）、
  data17 に要対応 `front_check`（見本の行・英文の氏名が PDF に見つからない。要確認 `name_split` が消える）、data18 の変種に要確認 `front_check`（題目の段落が 2 つ・英文の著者名がない。`excluded_unsure` が消える）、
  data8 の変種に要確認 `front_check`（所属と氏名の入れ替わり。`name_split` が消える）、data5 の 3 件・data16・data26 に要確認 `front_check`（英文の所属が PDF に見つからない）。
  元の 28 本のうち上のほかは変わらない。2.6 の直しは 46 docx で XML の差が 0（見込みどおり）。
- 手順 8: 文書（CLAUDE.md・docs/DEVELOPMENT.md・ARCHITECTURE.md・DESIGN.md・USAGE.md、`mkdoc.py`・`plan_body.md` から FIELD_TEST・FIX_PLAN を作り直した）。
- テスト: `tests/test_front.py`（32 件）。ほかのテストの直し: `tests/test_pipeline.py`・`tests/test_notebook.py` は、テンプレートそのままでなく `TEMPLATE_FILLED`
  （テンプレートそのままは見本の行が残るので `front_check` が要対応になる）を使う。`tests/test_pdfmatch.py` の `REST` に英文の題目・副題・著者・所属の行を足した
  （PDF の文字に英文の項目がないと、`front_check`〈PDF に見つからない英文の項目〉が出るため。この誌の PDF では英文は最後のページ）。

設計と違えた所:

1. 手順 1 の xfail の再現テストは作らなかった（上のとおり、実装前の出方を確かめて、実装と同時にテストにした）。
2. `author_candidates` に長さの上限（80 字）・最大 6 個・footnote の段落（`f` で始まる）の除外を足した（本文の段落が長く続いても知らせを長くしない）。
3. `pdf_findings` は、`(項目の一覧, 題目のページにある候補の段落の集合)` の 2 つを返す（設計は項目の一覧だけ。`authors_missing` の添え書きに使う）。
4. 題目の段落がなく `title_missing` が出るとき、`authors_missing` の候補から題目らしい段落を除く（同じ段落を 2 つの要対応で挙げない）。
5. CLAUDE.md の PDF の区分に、冒頭部の項目だけの例外（`front_check` の要確認）を 1 行書いた（点検の指摘 3。決めること 5 の勧めが区分 (3)(4) の外にあるため）。監督が不要と判断するなら、`pdf_*` の 3 項目を `KIND_LEVEL` から外す
   のではなく、`PdfCheck.front` を空にする（`check_pdf` の最後の 4 行を消す）だけで戻せる。

次の担当への申し送り:

- 回帰の出力は runs_uC を残した（runs_uB は消した。次の単位の基準は runs_uC）。
- `authors_missing` の「PDF の題目のページにあります」の添え書きは、回帰の data12・data15 の変種（両ルート）で実際に出ている（候補の `core` が題目のページとその次に そのままあるとき）。
- `name_split` を PDF で絞る案は今回しない（1.6）。C043・C130・C136 は次に回す。

文書とコードの食い違い（見つけたもの）:

- 設計の 5 章の 6 件のうち、1（`name_split` の 11 論文）は FIELD_TEST・FIX_PLAN の記述に「0.34.0 で数え直すと 11 論文」と書き足した。2（C041 が空の本文の役割の段落を守らない）は 2.6 で直した。
  3（W6 の「1 ページ目」は和文だけ）・4（C049 の 2 件と 4 件）・5（D-R1-13 の勧めと所有者の決定）・6（C016 の `multi_titles` を作らない）は、FIELD_TEST の詳細の文（点検の時点の記録）なので直していない。
- 設計の 2.4 の「`en_count` は data17 だけ」は誤りだった（点検の指摘 1。data12・data15 の変種にも当たる）。実装は `authors_missing` が出るときに `en_count` を出さないので、実際に当たるのは data17 だけ。

### 点検 review19 の 1 回目の直し（2026-11-15）

- 指摘 2（should_fix。直していない）: CLAUDE.md・DEVELOPMENT.md の PDF の区分 (3)(4) に書き足した冒頭部の例外は、所有者の承認が要る。
  RESUME.md の「所有者の返事を待っていること」に、戻すときの手順（`pdfmatch.check_pdf` の 4 行・CLAUDE.md の 1 行・DEVELOPMENT.md の文）とともに書いた。
- 指摘 10（should_fix）: `frontcheck.pdf_findings` は、英文の著者名の語（`name_words`。文字だけのつながり。所属の印の数字・記号は除く）が PDF の
  1 つの行の語にすべてあれば、姓と名の順だけの違いとして見つかったとみなす（data17 の「SATO Manabu」は出なくなり、data17 の front_check は
  見本の行の 1 件だけになった）。要対応と要確認の項目が混ざるときは、囲み・枠・コマンドラインの要確認の項目の文の頭と、一覧の行の項目名の後ろに
  「（要確認）」を付ける（`report._front_check_action`）。
- 指摘 12（should_fix）: `report._upload_action` は、EMSGM097E（題目なし）に front_check の title_missing があれば「（冒頭部の確かめ〈題目の段落がない〉を
  直すと消えます）」を、EMSGM233E/250E（姓のない著者）に authors_missing があれば「（…を直すと消えるかもしれません）」を添え、問題がすべて
  冒頭部の確かめと同じ原因なら、直し方を「冒頭部の確かめの直し方のとおりに docx を直して」だけにする（書誌情報の手順を案内しない）。
  data15 の変種「題目が本文スタイル」がこの形になった。
- 指摘 5（minor）: 2 章のスタイルの表の注記は、載せた知らせの重さのとおりに書く（authors_missing に載せた段落は要対応、front_check は
  その重さ。`report.ai_style_section` の `front_note`）。
- 指摘 6（minor）: tests/test_front.py の架空の所属名を「架空大学人間科学研究科」にした（漏えい検査で実際の原稿の語と重ならないように）。
- 指摘 7（minor）: 対応なし（指摘 10 の直しで data17 の英文の氏名の項目は消えた）。
- テスト: tests/test_front.py に `test_pdf_en_name_in_other_order_is_found`・`test_chapter2_note_follows_front_check_level` を足し、
  `test_front_check_reads_pdf_findings_and_dedups_with_template`（混ざるときの印）・`test_title_missing_is_needs_action`（upload の添え書き）に確かめを足した。
- 文書: docs/DESIGN.md の冒頭部の確かめの項に、姓と名の順と「（要確認）」の印を書き足した。
- 回帰（タグ fx1。基準は直前の runs_uPQ）: 92 件すべて同じ（XML・状態・知らせの key の差なし。文の差だけ）。不変性チェック・最終チェック・補完の確かめ・例外・DTD の不合格は増えていない。

### 点検 review19 の 2 回目の直し（2026-11-16）

- 指摘（should_fix。直していない）: CLAUDE.md・DEVELOPMENT.md の PDF の区分 (3)(4) の冒頭部の例外は、今も所有者の承認待ち（main に反映する前に監督が
  所有者に確かめる。認めないときは RESUME.md の手順で戻す）。
- 要対応 `authors_missing`（should_fix）: 題目の段落がなく（front_check の title_missing）、候補の段落にもう「著者名（日）」「所属（日）」のスタイルが
  付いているときは、スタイルを付ける直し方を書かず、「著者表のスタイルは付いていますが、題目の段落がないため冒頭部の著者表として読めていません。
  冒頭部の確かめ〈題目の段落がない〉を直すと消えます。」（`report.AUTHORS_TITLE_NOTE`）にする。一覧の行・コマンドラインも同じ（`report._authors_missing_action`）。
  スタイルが付いているが題目はあるとき、題目がなくスタイルも付いていないときは、今の直し方にそれぞれ 1 文を添える。data15 の変種「題目が本文スタイル」がこの形。
- front_check の swap（minor）: 例を、所属の語がある著者名（著者名のスタイルの段落）と、氏名らしい所属（所属のスタイルの段落）に分けて書く
  （`report._front_item_text`。`frontcheck.label_of` で分ける）。
- 漏えい検査（minor）: RESUME.md の架空の所属名の例を外した。scan_all.py の一致は 25 件に戻った（基準どおり）。
- テスト: tests/test_front.py に `test_authors_missing_with_styled_table_points_to_title_missing` を足し、`test_swap_asks_to_check_and_not_name_split` に例の分け方の確かめを足した。
- 文書: docs/USAGE.md の authors_missing の項に、題目の段落がない場合の 1 文を足した。docs/DESIGN.md の冒頭部の確かめの項の後ろで、
  引用文献の節の文字のない段落の項の頭（「- 引用文献の節の、文字が 1 文字もない段落（画像・図形を結び付けただけの段落。」）が消えて 2 つの項がつながっていたのを戻した。
- 回帰（タグ fx2。基準は直前の runs_fx1）: 92 件すべて同じ（XML・状態・知らせの key の差なし。文の差だけ。描かれない PDF の文字の数も全件同じ）。不変性チェック・最終チェック・補完の確かめ・例外・DTD の不合格は増えていない。
