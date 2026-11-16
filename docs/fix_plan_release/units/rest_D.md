# 単位 D「本文・後付けの構造」の設計（C032・C026・C014・C037）

- 対象の版: 0.34.0（main と開発ブランチは同じ。72e0cbe）。この設計はコードを変えない。
- 確かめに使ったもの（すべて scratchpad の `design/rest/D/` の下。リポジトリの中には作っていない）:
  - `run.py` … 起きた論文（data4 の変種・data13 の変種 2 つ・data18 と変種・data24・data3・data14・data17）を 0.34.0 で両ルート・AI なしで変換し直した（出力は `D/runs/`）。`show.py` はその XML の節・後付け・文献を数える。
  - `probe.py`・`scan.py`・`backscan.py`・`rolescan.py`・`refscan.py`・`refscan2.py`・`around.py`・`refseq.py` … 46 docx の plan（`classify` の結果）を数える（推定した見出し、改行のある見出し、長い見出し、後付けの見出しらしい段落、年のない文献）。原稿の文字は手元で見ただけで、設計書には形と数だけを書く。
  - `repro.py` … `tests/make_fixtures.py` の部品で作る架空の最小の docx 10 種（4 章の表）。
  - `proto/`・`patch_proto.py` … 手順 D7（後付けの見出しの比べ方）と D8（C014 の規則 3）の試作（ソースの写しだけを書き換えたもの）。
    `regress_proto1.log`（D7 の試作。基準は `runs_w2f2`）・`regress_proto2.log`（D7＋D8。基準は D7 の試作の出力 `runs_Dproto1`）。
    基準の確かめとして、0.34.0 そのままで 46 docx × 2 ルートを変換し直し、`runs_w2f2` と 92 件すべて同じだった（`regress_Dbase.log`）。
- 原稿は dataN と段落 ID（d123）で呼ぶ。例の文は架空。

## 1. 現状（0.34.0 でまだ起きるか）

| 問題 | 今の版 | 起きる原稿（46 docx） | 今の出力と知らせ |
|---|---|---|---|
| C032 後付けの見出しを文字から拾えない | **まだ起きる** | data24・data26（本文スタイルの「【謝　辞】」。括弧と字間の全角空白）、data18 と変種（「付記　本研究は…」の見出しと本文が 1 段落） | 謝辞・付記が本文の最後の節の `<p>` になる。AI なしでは知らせ 0。data24・data26 は、AI 役の回答があるときだけ、AI だけが見つけた提案として要確認 `style_check` に載る（W8 の仕組み。機械の検出ではない） |
| C026 引用文献の続きの段落 | **まだ起きる** | data13 の変種「参考文献が途中で改段落」（3）、data3（2）、data14（1）、data17（URL の行 5）、data24（3）、data26（2） | 続きの段落が別の `<ref>` になる。知らせは 3 章の「どこからもリンクされていない文献」の 1 行に紛れるだけ |
| C014 標準スタイルの番号つきの段落が見出しになる | **まだ起きる** | data4 の変種「本文が標準スタイル」（7 段落が偽の章。2 章が割れる）。実原稿は 0 | 4 章の推定の一覧だけ。要確認なし |
| C037 見出しと本文が Shift+Enter で 1 段落 | **まだ起きる** | data13 の変種「見出しと本文が同一段落」（見出し 3 件。254・272・459 字の `<title>`） | 10 章の「改行が要らなければ Word で消して」の 1 行だけ（直し方が逆）。要確認なし |

- W1・W2・W8 でなくなったもの・形が変わったものはない。W8 は、機械の検出の入れ物（`article.StyleSuspect`・`ArticlePlan.style_suspects`・`STYLE_SUSPECT_KINDS` の
  heading_body〈C037〉・heading_level〈C038〉・quote_like〈C129〉・heading_guess〈C014〉）と表示（要確認 `style_check`・推奨の手順 `ai_finish` の出す条件 3・AI の依頼文の
  「# スタイルを確かめる段落」）を作ったが、**検出は単位 D に残した**（article.py 31〜33 行の注記）。0.34.0 で検出しているのは `ref_symbol`（structure.py 3062 行）だけで、
  heading_body・heading_guess は宣言だけで一度も作られない。このため C014・C037 は、0.34.0 でも知らせが出ない。
- 頻度の数え直し: FIELD_TEST の C032 は「2/28（data24・data18）」だが、data26 も同じ形（3 本）。C026 は「5/28」だが、data26 も同じ（6 本）。
- 架空の docx の再現（`repro.py`。AI なし）:

| fixture | 形 | 0.34.0 の出力 | 知らせ |
|---|---|---|---|
| c032_ack_bracket | 本文スタイルの太字「【謝　辞】」と謝辞の本文 | 2 段落とも本文の `<p>`。`<ack>` なし | なし |
| c032_ref_numbered | 章見出しスタイルの「５．引用文献」と参考文献スタイルの文献 | 「５．引用文献」が本文の章になり、文献は本文の `<p>`。**`<ref-list>` がなく、本文の引用もリンクされない** | **なし**（needs_action 偽） |
| c032_ref_bracket | 章見出しスタイルの「【引用文献】」 | 同上 | なし |
| c032_notes_inline | 本文スタイルの「付記　本研究は…」 | 本文の `<p>` | なし |
| c026_split | URL の行・「著者（年）．」だけの行・DOI の行で分かれた文献 3 件 | 7 件の `<ref>`（うち 3 件が続き） | なし |
| c026_ok | 同じ文献を分けずに書いたもの（対照） | 3 件 | なし |
| c014_normal_list | 章見出しの章の中に標準スタイルの「1. …」が 3 つ続く | 3 つが偽の章（sec1）。後ろの本文がその中に入る | なし |
| c014_no_styles | スタイルのない原稿で、標準スタイルの「1. はじめに」→本文→「2. 方法」（対照） | 2 つの章（正しい推定） | なし |
| c037_heading_body | 章見出しの段落に Shift+Enter で本文 60 字 | 見出しと本文が 1 つの `<title>` | なし（10 章に「改行を消して」） |
| c037_short_break | 章見出しの中の短い 2 行目（「―…―」。対照） | `<title>` に改行の文字 | なし |

## 2. W8 の style_check との関係（全体の方針）

- 知らせは、新しい Action を問題ごとに作らず、W8 の入れ物に機械の検出を足す（`plan.style_suspects` に `StyleSuspect` を足すだけで、要確認 `style_check` の 1 行・2 章の表・
  AI の依頼文の「# スタイルを確かめる段落」・推奨の手順 `ai_finish` に出る）。FIELD_TEST の C014・C037・C026 の「直し方（最低限）」が書く別の Action
  （`heading_guess`・`_heading_body_action`・`ref_fragment`）は、W8 の前の案で、この入れ物に置き換わった（8 章の食い違い 1）。
- 種類（kind）は、W8 が決めた heading_body・heading_guess をそのまま使い、2 つ足す: **back_heading**（C032。後付けの見出しの形の本文の段落）と
  **ref_cont**（C026。前の文献の続きの疑い）。ref_symbol と同じく、直し方が決まっていて AI の提案を待たない種類（`report.STYLE_NO_AI_KINDS`）にする。
  heading_body・heading_guess は W8 の設計どおり AI の提案を待つ種類にする（PDF を見れば見出しか箇条かが分かる。推奨の手順 `ai_finish` が出る）。
- 構造を変えるのは 2 つだけにする（所有者の決定と D-R1-01 の例外の考え: 範囲が狭く、黙って誤った出力を正しい形に戻す直し）:
  - C032 の「【謝　辞】」「５．引用文献」の形を、比べ方を直して後付けの見出しにする（手順 D7）。修正必須で、外れると `<ref-list>` が丸ごとなくなる形があるため。
  - C014 の規則 3（同じ階層の見出しのスタイルがある原稿では、標準スタイルの段落を番号の形だけで見出しにしない。手順 D8）。D-R1-17 の (2)(a)。
  - ほか（C026 の文献をつなぐ、C037 の見出しと本文を分ける、C032 の見出しと本文が 1 段落の付記を分ける）は、構造を変えず、`style_check` で知らせて Word で直してもらう
    （D-R1-16・D-R1-20・D-R1-25 の勧めのとおり）。
- 守り: 引用文献の一覧が 1 件もないのに本文に「著者（年）」の引用があるときは、要対応 `refs_missing` を足す（手順 D5。c032_ref_numbered の形が黙って通るのを止める。
  D7 の比べ方で拾えない形〈「Ⅴ 文献一覧」など〉も止まる）。

## 3. 問題ごとの設計

### 3.1 C037 見出しと本文が 1 段落（知らせだけ）

- **起きる条件**: スタイルで決まった見出し（sec1〜sec3）の段落に、Shift+Enter の改行のあと本文が続く。`builder.sec`・`labelled`（builder.py 781〜826 行）が見出しの段落全体を
  `E.SECTITLE` で 1 つの `<title>` に span する。`E.SECTITLE` には `newline_label` がなく、`builder.newline_warnings`（407〜442 行）の「そのほか」の 1 行（改行を消して）に入る。
- **直し方（知らせ）**:
  1. `structure.Classifier.build_body`（1235〜1348 行）の `b.role = role`（1295 行）の直前で、役割が HEADING_LEVEL の段落に `heading_body_suspect(b)` を当て、合えば
     `StyleSuspect("heading_body", b.src, detail)` を足す。判定（新しい関数。structure.py のモジュールの関数）:
     - (a) 段落の文字（`Para.plain()`）に改行（"\n"）があり、最初の改行の後ろの文字（空白を除く）が `HEADING_BODY_MIN`（30 字）以上か「。」を含む。
     - (b) 改行がなくても、見出しの文字が 60 字を超え、「。」で終わる文を含む（見出しと本文を空白だけで続けた形）。
     - 46 docx で (a) に当たるのは data13 の変種の 3 件だけ、(b) は 0 件（実原稿の見出しは最長 89 字で、「。」と改行を含むものはない）。
  2. detail の文: (a)「見出しの段落の中の改行（Shift+Enter）の後ろに、本文らしい文（{n} 字）が続いています。今は見出しと本文がまとめて{章・節・項}の見出しになっています」、
     (b)「見出しのスタイルの段落に、文（「。」で終わる文）が続いています。今は全体が{章}の見出しになっています」。
  3. `report.STYLE_SUSPECT_JA["heading_body"]` の直し方を、改行の場合も読める形に直す: 「見出しと本文の間で Enter を押して段落を分け（改行〈Shift+Enter〉があれば、それを消してから）、後ろを本文のスタイルにする」。
  4. `builder.newline_warnings` の「そのほか」（other）から、heading_body に挙がった段落を除く（`{s.src for s in self.plan.style_suspects if s.kind == "heading_body"}`）。10 章に「改行を消して」と書かない。
- **原則との関係**: XML の文字・構造は変えない（`Emitter.span()` の呼び方も変えない）。知らせは `style_check` の行（`report.actions()` の既存の Action）だけ。除外なし。PDF は関わらない。
- **足すテスト**（tests/test_style_check.py か新しい tests/test_heading_suspects.py。架空の内容）: c037_heading_body の形で、`style_suspects` に heading_body が 1 つ、`style_check` の行に
  「Enter を押して段落を分け」、10 章に「改行を消して」がない、`needs_action` 偽、不変性チェック合格。c037_short_break では heading_body が出ず、10 章の行は今のまま。
  (b) の形（改行なし、「。」の文を続けた 70 字の見出し）でも出る。
- **回帰の見込み**: data13 の変種「見出しと本文が同一段落」の両ルートで、要確認 `style_check`（3 か所）と推奨の手順 `ai_finish` が足される。10 章の「そのほか」の行が消える。XML は同じ。
- **危険と避ける条件**: 見出しの 2 行目に副題を Shift+Enter で書く原稿（「―…―」）で誤報が出る。30 字・「。」の条件で避ける（c037_short_break）。しきい値は実装で決める表に置く。

### 3.2 C014 標準スタイルの番号つきの段落が見出しになる（知らせ＋規則 3）

- **起きる条件**: 役割が決まらないスタイル（標準など。role normal）の段落が `guess_heading(strict=False)`（structure.py 788〜800 行）の「。」のない 40 字以内の番号の形
  （`RE_HEAD1〜3`）に合う。`build_body` の 1275〜1286 行がそのまま sec1〜sec3 にする。本文スタイル（role p）の段落は、全体が太字のときだけ（strict=True。1287〜1294 行）。
- 46 docx で推定した見出しがあるのは 2 本だけ: data4 の変種（標準スタイル。7 つ。章見出しのスタイルの章が 9 つある原稿）と、data15 の変種「章見出しが本文スタイル」
  （本文スタイルの太字の章見出し 6 つ。章見出しのスタイルの段落はない。推定は正しい）。
- **直し方 1（知らせ。手順 D3）**: `build_body` の 2 か所（1277〜1282 行と 1289〜1294 行）で推定したとき、`StyleSuspect("heading_guess", b.src, detail)` を足す。detail は
  「「{スタイル名}」スタイルの段落を、番号の形から{章・節・項}見出しにしました」。`STYLE_SUSPECT_JA["heading_guess"]` の直し方を「見出しなら見出しのスタイル（「章見出し」など）を、
  本文の番号つきの箇条なら「本文」のスタイルを付ける」にする。4 章の記録（`plan.decide`）は今のまま。
- **直し方 2（構造。規則 3。手順 D8）**: 推定の前に、本文の要素の役割のうち、スタイル（か AI の区切り以外の指定）で決まった見出しの階層の集合 `styled_levels`
  （`{role for _, role in items if role in HEADING_LEVEL}`）を `build_body` の最初で作り、`self._styled_levels` に置く。role normal の段落の推定（strict=False）で、推定した階層が
  `styled_levels` にあれば見出しにせず、p（`note = "style_unknown"`）のままにし、`StyleSuspect("heading_guess", b.src, "番号の形ですが、{章}見出しのスタイルの段落がほかにあるので、本文の段落にしました")` を足す。
  同じ判定を `list_or_quote`（1711〜1732 行）でも使う（新しいメソッド `body_heading_guess(b, role)` に 2 か所の推定をまとめ、`build_body` と `list_or_quote` の両方から呼ぶ）。
  `split_regions` の和文の冒頭から本文への切り替え（984 行）と資料の中の見出し（3208 行）は変えない（領域の切り替えと資料の中の段落の出し方で、見出しの階層を決めないため）。
  本文スタイルの太字（strict=True）の推定は変えない（data15 の変種を壊さない。スタイルで決まった同じ階層があっても、太字の番号の段落を見出しと見る今の動きを保つ）。
  FIELD_TEST の規則 (1)（番号が続きでない）・(2)（本文をはさまずに 2 つ以上続く）は入れない（規則 3 だけで data4 の変種が元の原稿と同じ構造に戻り、(1)(2) は
  スタイルのない原稿〈data15 の変種〉で正しい推定を外す恐れがある）。
- **原則との関係**: 段落の役割を変えるだけ（`Emitter.span()`。文字は変えない）。除外なし。知らせは `style_check`。
- **足すテスト**: c014_normal_list で、D3 では heading_guess が 3 つ・XML は今のまま、D8 では 3 段落が 2 章の `<sec>` の中の `<p>` になり heading_guess が 3 つ（detail が「本文の段落にしました」）。
  c014_no_styles では、どちらの手順の後も 2 つの章のまま、heading_guess が 2 つ。本文スタイルの太字の「１．…」（章見出しのスタイルなし）は D8 の後も章のまま。
  自動番号の段落（`list_item`）の箇条書きは、D8 の後も `<list>` のまま。
- **回帰の見込み**: D3 で data4 の変種（両ルート）に `style_check` 7 か所・`ai_finish`、data15 の変種「章見出しが本文スタイル」（両ルート）に `style_check` 6 か所・`ai_finish`。XML は同じ。
  D8 で data4 の変種の XML が 28 行変わり、節の並びが元の原稿（data4）と同じになる（試作で確かめた: 節の数・長さ・`<p>` の数が元の原稿と一致）。ほかの 90 件は同じ。
- **危険と避ける条件**: 章見出しのスタイルを 1 つの章だけ付け忘れた原稿（標準スタイルの「3. 考察」）で、D8 の後はその章が本文の段落になる（今は正しく章として出ている形で、
  構造が悪くなる。点検の指摘 7）。heading_guess の行（「本文の段落にしました。章見出しなら、Word でこの段落に章見出しのスタイルを付けてください」）で知らせるので黙っては誤らない
  （heading_guess は AI を待つ種類なので `ai_finish` も出る）。実装では、全体が太字の段落は規則 3 の外にした（9 章の 1）。役割 p（本文スタイル）は規則 3 の外にするので、本文スタイルで付け忘れた太字の章見出しは今までどおり章になる。

### 3.3 C032 後付けの見出しの形（構造＋知らせ＋守り）

- **起きる条件**: `back_heading_by_text`（structure.py 1109〜1125 行）は、役割 sec1・normal・p の段落を、NFKC の後の完全一致（`RE_REF_HEADING_TEXT`・`RE_ACK_TEXT`・
  `RE_NOTES_TEXT`・`RE_FN_TEXT`。正規表現は前後の空白だけを許す）で見る。章番号（「５．」）・前後の括弧（「【…】」）・字間の空白（NFKC で全角の空白が半角になる「謝 辞」）で外れる。
  外れた段落は本文の p（`style_unknown` でもない本文スタイルのまま）になり、後ろの謝辞の本文も本文に残る。「５．引用文献」が章見出しのスタイルだと、後ろの文献も本文の p になり、
  `<ref-list>` がなく、本文の引用もリンクされず、知らせが 1 つも出ない（c032_ref_numbered）。
- **直し方 1（構造。手順 D7）**:
  1. 比べるための文字を作る関数 `back_heading_key(t)`（モジュールの関数。出力の文字は変えない）: NFKC・前後の空白を除いた文字から、(i) 先頭の章番号（1〜2 桁の数字か Ⅰ〜Ⅻ と、
     後ろの「.」「．」「、」と空白）、(ii) 前後で組になる括弧（【】［］[]〔〕()（）〈〉＜＞<>）、(iii) すべての空白、を外す。
  2. `back_heading_by_text` を、完全一致（今のまま）を先に見て、合わなければ `back_heading_key` の文字で **ref・ack・notes の 3 つだけ** を見る（**注〈fn〉は完全一致のまま**。
     「【注】」「注：」まで広げると、K5・F10 の文字から推定した注の節〈`fn_guess`〉が本文の中の表の注で動く）。比べ方は完全一致のまま（前方一致にしない）。
  3. 比べ方を直して初めて合った段落（緩い一致）は、前もって 1 回だけ見て受け入れるかを決める（新しいメソッド `loose_back_headings(flat)` を `run()` の `split_regions` の前に呼び、
     受け入れた段落 ID → 種類を `self._loose_back` に置く。`back_heading_by_text` は完全一致か `self._loose_back` にあるときだけ種類を返す。呼び出し側〈split_regions の 930・934・989 行、
     `feed_fn_span`、`build_back` の 2987 行〉は変えなくてよく、判定がずれない）。受け入れる条件（すべて）:
     - (g1) 後ろ（次の後付けの見出し〈スタイルで決まったものか完全一致の文字のもの〉か、英文の部分の役割の段落・表まで）に、スタイルで決まった見出し（sec1〜sec3。資料の見出し
       〈`appendix_heading`〉を除く）と、役割 normal で番号の形から見出しと推定する段落（`guess_heading(strict=False)`）がない（本文の途中の「【文献】」などで、後ろの本文がすべて後付けに
       なるのを防ぐ）。役割 ref・fn の段落は数えない（番号の形式の文献「1. …」を見出しと数えない）。
     - (g2) 後ろに、同じ種類の後付けの見出し（スタイルで決まったものか、完全一致の文字のもの）がない（2 つ目の同じ見出しで K1 の中止〈`replace_back`〉に入るのを防ぐ）。
     - (g3) 図形の中の段落でない。
     受け入れなかった緩い一致は `StyleSuspect("back_heading", src, "{謝辞}の見出しの形ですが、後ろに{章見出しのスタイルの段落}があるので、本文の段落のまま出力しました")` を足す。
  4. 受け入れたときの 4 章の記録は今の文（「後付けの見出しと推定（文字列から）」。2990〜2991 行）のまま。スタイルの誤りは残るが XML は正しいので、要確認にはしない（完全一致の今の動きと同じ）。
- **直し方 2（知らせ。見出しと本文が 1 段落。手順 D6）**: D-R1-16 の (a)。`build_body` の役割を決めた後（1295 行の前）で、本文の領域の p の段落の文字（NFKC）が
  「（括弧）付記・謝辞（括弧）」（語は `back_heading_key` と同じく括弧・字間の空白を外して比べる。「【謝　辞】　本研究は…」も当たる。点検の指摘 5）のあとに空白か「：」「:」が続き、その後ろに 10 字以上の文字があるものに `StyleSuspect("back_heading", src, "付記の見出しと本文が 1 つの段落です。今は本文の段落として出力しています")` を足す。
  「注」「引用文献」「参考文献」で始まる段落は挙げない（本文の「注：…」・表の注で誤報が多い）。46 docx で当たるのは data18 と変種の 1 段落ずつだけ。
- **直し方 3（守り。手順 D5）**: `refparse.link_citations`（358〜396 行）の `if not refs: return`（362〜363 行）の前で、本文の段落（`paras`。ref・formula を除く）の `extract_citations` の数を
  数え（数えるのは名前のある引用〈narrative・parenthetical で names がある〉だけ。引用文献の見出しらしい段落〈`back_heading_key` の文字に「文献」を含む 15 字以内〉より後ろは数えない。
  番号の形式の引用〈［1］〉は対象の外。文は「少なくとも n か所」。点検の指摘 4）、`plan.refs_missing_cites`（新しい欄。ArticlePlan）に入れる。`report.py` に `_refs_missing_action`（要対応、key `refs_missing`）を足して `report.actions()` に入れる。
  出す条件: `plan.refs` が空で、`refs_missing_cites` が 1 以上。46 docx で当たる原稿は 0（すべてに引用文献がある）。
- **Action の文の案**:
  - `STYLE_SUSPECT_JA["back_heading"]` = (「付記・謝辞・引用文献の見出しの形ですが、本文の段落として出力しています」,
    「付記・謝辞なら、見出しの段落を「付記見出し」「謝辞見出し」のスタイルにする（見出しと本文が 1 つの段落なら、見出しの後ろで Enter を押して分け、後ろを本文のスタイルにする）」)。
  - `refs_missing`（要対応）: top「**要対応: 引用文献の一覧が見つかりません（3 章）。** 本文に「著者（年）」の形の引用が {n} か所ありますが、引用文献の見出しが見つからず、XML に
    引用文献の一覧（{md_tag('<ref-list>')}）がありません。Word で、引用文献の見出しの段落を「参考文献見出し」のスタイルに、各文献の段落を「参考文献」のスタイルにして、変換し直してください。」、
    checklist「- [ ] **引用文献の一覧がない**（3 章）: Word で引用文献の見出しと文献のスタイルを付けて変換し直す」、box_title「引用文献の一覧が見つかりません（要対応）」、
    cli「要対応: 引用文献の一覧が見つからない（本文に著者（年）の引用が {n} か所ある）。docx で引用文献の見出し・文献のスタイルを付けて変換し直すこと」。印は `checklist_line` が付ける。
- **原則との関係**: D7 は段落の役割（どの節に入るか）を変えるだけで、`<ack>` の `<title>`・`<p>`、`<ref-list>` の `<title>` も `Emitter.span()` で書く（試作の XML で、見出しの太字が
  `<title><bold>` に入ることを確かめた）。比べるための文字は判定にだけ使い、出力の文字は変えない（「５．引用文献」は `<ref-list>` の `<title>` にそのまま出る）。除外は増えない。
  D5・D6 は知らせだけ（`report.actions()`）。PDF は関わらない。
- **足すテスト**（tests/test_structure.py。架空の内容）: c032_ack_bracket・c032_ref_numbered・c032_ref_bracket が D7 の後に `<ack>`・`<ref-list>` になり、本文の引用がリンクされる。
  c032_notes_inline は D6 で back_heading が 1 つ、XML は今のまま。D5: c032_ref_numbered を D7 の前の版の形（たとえば「Ⅴ 文献一覧」）にしたものに `refs_missing` が出て `needs_action` 真。
  逆向き: 本文の途中（後ろに章見出しが続く）の本文スタイルの「【文献】」は後付けにならず back_heading が出る（g1）。後ろに「謝辞見出し」スタイルの段落がある本文の「【謝辞】」も
  後付けにならない（g2。中止しない）。本文の「付記したように…」「注：数値は…」は挙げない。完全一致の今の fixture（「謝辞」の本文スタイル）は今のまま。
- **回帰の見込み**（試作で確かめた。試作は比べ方の直しだけで、g1〜g3 の守りは入れていない。data24・data26 の 2 つは、後ろが謝辞の本文・空白・注見出しだけで、g1〜g3 をどれも満たす）: D7 で data24・data26 の両ルート（docx_ai・pdf_ai）の XML が変わる（data24 は 14 行、data26 は 10 行。最後の節の 3 段落・2 段落が `<back>` の `<ack>` に移る）。
  D7 で後付けにした段落（`plan.loose_back`）に AI の古い提案（「謝辞見出しにする」）があれば、要確認 `style_check` の行に「機械が文字から謝辞の見出しと推定し、XML ではそのように出力しています。
  Word のスタイルだけ直してください」と添える（点検の指摘 2 の (a)。data24・data26 の行の文が変わる）。
  data26 は要確認 `float_end` が足される（資料の図形が謝辞の段落に結び付いていて、謝辞が本文の外になったので、本文の最後に置いた。図の位置は今と同じ本文の最後で、
  知らせの文〈資料の図なら英文要旨の後ろに移す〉は合っている）。ほかの 88 件は同じ。D6 で data18 と変種（両ルート）に `style_check` 1 か所が足される（back_heading は AI を待たない種類なので
  `ai_finish` は出ない）。D5 は 0 件。
- **危険と避ける条件**: 本文の中の「【文献】」「（参考文献）」などの小見出しで、後ろの本文が丸ごと引用文献になる（いちばん重い誤り）。g1 で、後ろに見出しのスタイルの段落があるときは
  受け入れない。スタイルのない原稿（見出しが推定だけ）でも効くように、g1 は番号の形から推定する見出しも数える。
  役割 sec2・sec3 は対象にしない（「（１）文献」のような本文の節の誤判定を避ける。実原稿に例がない。7 章の決めること 3）。

### 3.4 C026 引用文献の続きの段落（知らせだけ）

- **起きる条件**: `build_back`（2889〜3103 行）が引用文献の節の空白でない段落を 1 段落 1 件の `RefNode` にする（3056〜3058 行）。Word で文献の途中で Enter を押した原稿
  （URL・DOI の前、著者と年の後ろ、ページの前、英語の語の途中）で、続きが別の `<ref>` になる。続きは年が読めず（`refparse.parse_entry` の `year` が None）、本文からリンクされない。
- **直し方（知らせ。手順 D4）**: `refparse.link_citations` の解析のループ（364〜369 行）の後、numeric の分岐の前に、新しい関数 `ref_continuations(plan, numeric)` を呼ぶ:
  - 作者年の形式: 年の読めない文献（`r.parsed["year"] is None`）。番号の形式: 番号で始まらず（`RE_NUM_START`）、Word の自動番号もない文献。どちらも、記号だけの段落（`symbol_only`。
    ref_symbol で挙げ済み）と、資料の見出しの疑い（`plan.app_after_refs`）から後ろは除く。
  - **3 件以上続く所から後ろは挙げない**（引用文献の節の後ろの資料〈C001〉の中身で、続きの段落ではない。data17 は 35 件目から、data23 は 36 件目から）。ただし、URL・DOI で始まる
    段落（`^(https?[:.]|www\.|doi[:.])`。大文字小文字を区別しない）は、続く数にかかわらず挙げる（続きであることがはっきりしている）。URL・DOI で始まる段落は続く数に数えない
    （数えるのは、年がなく URL でもない段落だけ。URL の段落は続きを切らない。年のある文献で数え直す。点検の指摘 3）。打ち切った所の最初の段落は `plan.ref_yearless_runs` に入れ、
    要確認 `app_after_refs` に「年の読めない段落が 3 件以上続く所」の 1 行を出す（決めること 5 の (a)）。
  - 挙げた文献ごとに `StyleSuspect("ref_cont", src, detail)`。detail「前の文献 {前の rid}「{先頭 15 字}」の続きの疑いがあります（{年が読めません／URL・DOI で始まります}）。今は別の文献 {rid} として出力しています」。
  - 3 章の「どこからもリンクされていない文献」の一覧（report.py 3415〜3418 行）で、ref_cont に挙がった文献に「（前の文献の続きの疑い）」を添える。
- `STYLE_SUSPECT_JA["ref_cont"]` = (「前の文献の続きの疑いがあります（年が読めず、別の文献として出力しています）」,
  「前の文献の続きなら、Word で前の段落の終わりの段落記号を消して 1 つの段落にする」)。AI を待たない種類（`STYLE_NO_AI_KINDS`）。
- **原則との関係**: XML は変えない（文献をつなぐ変換はしない。D-R1-20 の (2)。W8 の後は AI が文献の区切りを直せない〈`ai_assist.BOUNDARY_KINDS` は注の区切りと資料の始まりだけ〉ので、
  「AI の指定があるときだけつなぐ」も今はできない。7 章の決めること 4）。知らせは `style_check`。
- **足すテスト**（tests/test_refparse.py か test_style_check.py）: c026_split で ref_cont が 3 つ（URL の行・「著者（年）．」の次の行・DOI の行）、`<ref>` の数と文字は今のまま、不変性チェック合格。
  c026_ok では出ない。年のない正規の文献（「文部科学省（n.d.）」「…（印刷中）」）では出ない。参考文献スタイルの段落が 4 件続けて年なし（資料を引用文献の後ろに置いた形）では、URL で始まらない限り出ない。
- **回帰の見込み**（`refscan2.py` で数えた。XML は変わらない）: data13 の変種「参考文献が途中で改段落」3・data3 2・data14 1・data17 5（URL の行。35 件目の URL の行を含む）・data24 3・data26 2 の
  両ルートで `style_check` が出る（data24・data26 は AI の回答の行と合わせて行が増える）。ほかの 40 docx は 0 件。ref_cont は AI を待たない種類なので、`ai_finish` は増えない。
  AI の依頼文の「# スタイルを確かめる段落」に載るが、依頼の番号（`request_stamp`）の構造の印は変わらないので、前の回答はそのまま使われる（点検の指摘 1 で直した）。
- **危険と避ける条件**: 年のない正規の文献（法令・ウェブの頁・年の書き方の違う文献）での誤報。`RE_YEAR_PAREN` は「n.d.」「印刷中」「in press」を年として読む。46 docx では、
  資料の部分を除くと、年のない文献はすべて続きの段落だった（誤報 0）。年を括弧で書かない文献の書き方（「Hei, A., 2018.」）の原稿が来たら誤報が増えるので、
  1 原稿で挙げる数が多い（文献の 3 割を超える）ときは、行を挙げずに「年の読めない文献が N 件あります」の 1 行にする。3 割の分母は、`app_after_refs` と打ち切りの前の文献の数
  （点検の指摘 3）。分子は年のない段落（URL・DOI を除く）で、3 件以上のときだけまとめる（URL・DOI の行は 1 件ずつ挙げる。実装で決めた）。

## 4. 共通の変更

- `article.py`: `STYLE_SUSPECT_KINDS` に back_heading・ref_cont を足す。注記（31〜33 行）を、検出した場所（structure の build_body・loose_back_headings、refparse の ref_continuations）に直す。
  `ArticlePlan.refs_missing_cites`（int。0）を足す。
- `report.py`: `STYLE_SUSPECT_JA` に 2 つ足し、heading_body・heading_guess の直し方を直す（1506〜1512 行）。`STYLE_NO_AI_KINDS` に back_heading・ref_cont（1514 行）。`_refs_missing_action`。
  `STYLE_SUSPECT_JA` のキーと `STYLE_SUSPECT_KINDS` が同じであることをテストで固定する。
- `ai_assist.suspect_section`: 変えない（種類ごとの決まった文を STYLE_SUSPECT_JA から取る）。
- 推奨の手順 `ai_finish`: heading_body・heading_guess の原稿で新しく出る（W8 の設計の出す条件 3）。終了コードは変わらない。
- 依頼の番号（点検の指摘 1 で直した）: `plan.style_suspects` は AI の依頼文の本文の印（data_text）だけを変える。構造の印（文献・図・表・式・注・図形・テキストボックスの ID と先頭の文字）は
  変わらないので、前の回答はそのまま使われる（`check_answer` の (b)）。使われなくなるのは、D7 で引用文献の一覧ができる形など、文献・注・図表の数が変わるときだけ。USAGE_AI.md には足さない。

## 5. 実装の手順

| 番号 | 内容 | 変わるもの | 規模 | 難しさ |
|---|---|---|---|---|
| D1 | 入れ物: `STYLE_SUSPECT_KINDS`・`STYLE_SUSPECT_JA`・`STYLE_NO_AI_KINDS` に back_heading・ref_cont を足し、heading_body・heading_guess の直し方の文を直す。キーと種類の一致のテスト | なし（文だけ） | S | Sonnet |
| D2 | C037: `heading_body_suspect` と `build_body` での検出、`newline_warnings` の除き方。テスト | 知らせ（data13 の変種） | S | Sonnet |
| D3 | C014 の知らせ: `build_body` の 2 か所の推定で heading_guess。`body_heading_guess` の共通化（構造は変えない形）を先に入れる（点検の指摘 6）。テスト | 知らせ（data4・data15 の変種） | S | Sonnet |
| D4 | C026: `refparse.ref_continuations` と 3 章の添え書き。3 割を超えたときのまとめ。テスト | 知らせ（6 原稿） | M | Sonnet |
| D5 | 守り: `refs_missing_cites` と要対応 `refs_missing`。テスト | 知らせ（実原稿 0） | S | Sonnet |
| D6 | C032 の見出しと本文が 1 段落: back_heading の検出。テスト | 知らせ（data18 と変種） | S | Sonnet |
| D7 | C032 の構造: `back_heading_key`・`loose_back_headings`（g1〜g3）・`back_heading_by_text` の変更。逆向きのテスト（本文の途中の「【文献】」、同じ見出しが 2 つ） | XML（data24・data26） | M | Opus（領域の切り替え・K1・fn_guess との関わり） |
| D8 | C014 の規則 3: `body_heading_guess` と `styled_levels`、`build_body`・`list_or_quote` の共通化。テスト | XML（data4 の変種） | M | Opus（箇条書き・仮の位置の判定とのずれ） |
| D9 | 版上げ（D7・D8 を入れるなら 0.35.0、知らせだけなら 0.34.1）・ノートブックの作り直し・文書（FIELD_TEST の対応の記録、DEVELOPMENT・ARCHITECTURE の style_suspects の検出の場所、USAGE の style_check の種類）・回帰 | — | S | Sonnet |

- 各手順の後に `python -m pytest -q` と `regress.py`（46 docx × 2 ルート）を回し、上の「回帰の見込み」と違う変化がないことを確かめる。D7・D8 は CLAUDE.md の難しい変更として、
  原則・回帰・利用者向けの観点で点検する（修正と再点検は最大 3 回）。
- D1〜D6 は出力の形を変えない（3 桁目）。D7・D8 は 2 桁目。D7・D8 を見送るときも、D1〜D6 だけで 4 つの問題すべてが「黙って誤る」から「知らせる」になる（C032 の
  c032_ref_numbered の形は D5 の要対応で止まる）。

## 6. 範囲の外で見つけたこと（単位 D の中・低と C001 に関わる）

1. **data17・data23 の引用文献の節に、資料（表・図キャプション・本文）が知らせなく入っている**（data17 は 391 件の `<ref>` のうち 356 件、data23 は 77 件のうち 41 件が資料の中身）。
   `build_back` の資料の見出しの知らせ（`app_after_refs`。3032〜3039 行）は、(a) 資料の見出しが「参考資料1：…」（`RE_APPENDIX` は「資料」で始まる形だけ。data17）、(b) 資料の段落が
   参考文献スタイル（`role != "ref"` の条件で見ない。data23）のときに外れる。C001 は保留（テンプレートで対応）だが、黙って誤る形なので、D4 の「年のない文献が 3 件以上続く所」を
   `app_after_refs` の知らせに足す案を 7 章の決めること 5 に挙げた。
2. heading_level（C038）・quote_like（C129）の検出も W8 の入れ物が待っている。単位 D の中・低で、同じ形（`build_body` で `StyleSuspect` を足す）で足せる。この設計には入れていない。

## 7. 所有者・監督が決めること

1. **D7（C032 の構造の直し）を入れるか**。(a) 入れる（g1〜g3 の守りつき。2 桁目）、(b) 知らせ（back_heading）だけにする。勧め: (a)。修正必須で、外れると `<ref-list>` が丸ごとなくなる形があり、
   範囲が狭い（46 docx で変わるのは data24・data26 だけ）。守りで受け入れなかったときは知らせる。
2. **D8（C014 の規則 3）を今回入れるか**。(a) 入れる（D-R1-17 の (2)(a)。2 桁目）、(b) 次の版。勧め: (a)。変わるのは仕込んだ変種 1 本だけで、元の原稿と同じ構造に戻る。
   規則 (1)(2) は入れない（スタイルのない原稿の正しい推定を外す恐れ）。
3. **後付けの見出しの文字の判定を、役割 sec2・sec3 にも広げるか**（FIELD_TEST の C032 の (2)）。(a) 広げない、(b) 広げる。勧め: (a)。実原稿に例がなく、「（１）文献」などの本文の節を誤る。
4. **文献の続きをつなぐ変換**（C026）。(a) しない（知らせだけ）、(b) AI の区切りの直し（`BOUNDARY_KINDS`）に「文献の続き」を足して、AI の回答でつなぐ。勧め: (a)。CLAUDE.md の
   「AI の回答で変えてよいもの」を増やすことになり、所有者の決定（AI はスタイルで直せない区切りだけ）を広げる。Word で段落をつなぐのは簡単。
5. **引用文献の節の後ろの資料の取りこぼし**（6 章の 1。data17・data23）。(a) D4 の「年のない文献が 3 件以上続く所」を `app_after_refs` の知らせに足す（要確認。XML は変えない）、
   (b) C001 の保留のまま何もしない。勧め: (a)。いま data17 は資料の中身 356 段落が黙って文献になり、data23 は画像の `lost` しか出ない。
6. **要対応 `refs_missing` の重さ**。(a) 要対応、(b) 要確認。勧め: (a)。引用文献の一覧のない XML は登載できない。本文に「著者（年）」の引用がない原稿には出ない。
7. **C037 の見出しと本文を自動で分けるか**（D-R1-25）。勧めは今までどおり知らせだけ（分けるなら、見出しの `<title>` を改行の前まで、後ろを `<p>` にし、改行は `Emitter.drop()`
   で落とす形になる。docx の文字は変えないが、意図した改行〈2 行の見出し〉を壊す恐れがある）。

## 8. 文書とコードの食い違い（見つけたもの。この作業では直していない）

1. FIELD_TEST の C014・C037・C026 の「直し方（リリース前の最低限）」は、それぞれ別の Action（`heading_guess`・`_heading_body_action`・`ref_fragment`）と `plan.heading_guesses`・
   `plan.ref_fragments` を足すと書くが、W8（0.33.0）で `StyleSuspect` と要確認 `style_check` にまとめた。この設計は W8 の形に従う。FIELD_TEST の対応の記録に、置き換えたことを書く（D9）。
2. article.py 31〜33 行の注記「検出は修正計画の単位 D が足す」と report.py 1505 行の「AI を使っていないとき…使う」は今のコードどおりだが、0.34.0 では heading_body・heading_level・
   quote_like・heading_guess を作る所がなく、`test_style_check.py` は検出を手で入れて確かめているだけ。D2・D3 の後に、注記を検出した場所に直す。
3. FIELD_TEST の頻度: C032 は 3 本（data26 を足す）、C026 は 6 本（data26 を足す）。
4. FIELD_TEST の C032 の「原因」は、外れた段落が「p・style_unknown になる」と書くが、data24・data26・data18 の段落は本文スタイル（役割 p）で、`style_unknown` は付かない
   （4 章の想定外のスタイルの一覧にも出ない）。
5. structure.py の `split_regions` の docstring（883〜909 行。領域の切り替えと文字から推定した見出しの説明）と `back_heading_by_text` の docstring は、D7 で比べ方を変えたら合わせて直す。

## 9. 実装の記録（2026-11-15）

済ませた手順: D1〜D8（D9 の版上げ・ノートブック・反映は監督が行う。文書と回帰は済ませた）。設計の点検の指摘（D_review）は、上の本文に直し方のとおり書き入れて実装した。

- D1: `article.STYLE_SUSPECT_KINDS` に back_heading・ref_cont、`report.STYLE_SUSPECT_JA` に 2 つ（heading_body・heading_guess の直し方も直した）、`report.STYLE_NO_AI_KINDS` に 2 つ。
- D2: `structure.heading_body_detail`（30 字・60 字は `HEADING_BODY_MIN`・`HEADING_BODY_LONG`）と `Classifier.body_suspects`（`build_body` の役割を決めた後の 1 か所。D6 と共用）。
  `builder.newline_warnings` の「そのほか」から heading_body の段落を除いた。
- D3: `Classifier.body_heading_guess`（`build_body` と `list_or_quote` が共用）と、`build_body` の 2 か所の heading_guess。
- D4: `refparse.ref_continuations`（`link_citations` の解析の後）、`plan.ref_conts`（3 章の添え書き）、`plan.ref_yearless_runs`（要確認 `app_after_refs` の 1 行と 10 章の警告。見出しは
  資料の見出しがないとき「引用文献の後ろに、資料の中身と思われる段落があります」）。
- D5: `refparse.refs_missing_cites`・`plan.refs_missing_cites`・`report._refs_missing_action`（要対応 `refs_missing`。`abstract_missing` の後ろ）。3 章にも 1 行。
- D6: `structure.back_heading_inline`（`back_heading_key` と同じ比べ方）。
- D7: `structure.back_heading_key`・`exact_back_heading`・`loose_back_heading`・`Classifier.loose_back_headings`（g1〜g3）。`back_heading_by_text` は完全一致か受け入れた段落だけ。
  `plan.loose_back` と `report._loose_back_note`（AI の古い提案の行の添え書き）。
- D8: `Classifier.rule3_blocks` と `self._styled_levels`（`build_body` の最初）。規則 3 で本文にした段落は判断の一覧と heading_guess（「本文の段落にしました」）。
- テスト: `tests/test_body_back_suspects.py`（25 件）。既存のテストの直し: `sample_full.docx` の標準スタイルの太字「２．考察」が heading_guess になり、`style_check` と推奨の手順
  `ai_finish` が出るので、「知らせのない原稿」を前提にした `tests/test_ai_screens.py`・`test_steps.py`・`test_pipeline.py`（2 つ）を `sample_notes.docx` に替え、`test_ai_request.py`・
  `test_ai_unresolved.py` は検出を外してから見る形に、`test_colab.py`・`test_pipeline.py` の知らせの一覧は style_check・ai_finish を足した形にした。

設計と違えた所:

1. 規則 3 は、全体が太字の段落を外にした（`rule3_blocks`）。設計は「役割 p〈本文スタイル〉の太字だけ規則 3 の外」で、標準スタイルの太字の番号の段落も本文にする形だったが、
   `sample_full.docx` の「２．考察」（標準スタイル・太字。1 章だけスタイルを付け忘れた形）が本文になり、点検の指摘 7 の悪くなる形がそのまま出る。data4 の変種の 7 段落は太字でないので、
   回帰の結果は設計の見込みと同じ。
2. ref_cont の 3 割のまとめは、URL・DOI の行を分子に入れず、年のない段落が 3 件以上のときだけにした（設計は件数の下限なし。小さな原稿で 1 件の続きがまとめられるため）。
   まとめた 1 行は、最初の段落に 1 つの StyleSuspect として載せる。
3. 打ち切りの最初の段落（資料の中身の疑い）は `plan.app_after_refs` に足さず、別の `plan.ref_yearless_runs` にした（`app_after_refs` は `pdfmatch.paper_verdict` の数え方と
   `_dtd_app_hint` にも使われ、そちらを変えないため）。要確認 `app_after_refs` は、どちらかがあれば出す。
4. 規則 3 で本文にした段落の detail に「{章}見出しなら、Word でこの段落に{章}見出しのスタイルを付けてください」を足した（点検の指摘 7）。
5. 要対応 `refs_missing` の文は「少なくとも n か所」にし（点検の指摘 4）、3 章にも 1 行を出した（設計の文は「3 章」を指すが、3 章に対応する行がなかった）。
6. back_heading の受け入れなかった理由は、g1 を先に見つけたら g1 の文にする（後ろに同じ見出しもあっても）。

回帰（`regress.py uD --base uC`。46 docx × 2 ルート）: 同じ 68 件、違う 24 件（12 原稿の両ルート）。状態（不変性チェック・最終チェック・補完の確かめ・DTD・例外・needs_action）の差は 0。

- XML の差: data4 の変種「本文が標準スタイル」28 行（D8。7 段落が 2 章の中の `<p>` になる）、data24 14 行・data26 10 行（D7。謝辞が `<ack>` になる。data26 は要確認 `float_end` が足される）。
- 知らせの key の差（XML は同じ）: 要確認 `style_check` が足された原稿は、data13 の変種「参考文献が途中で改段落」（ref_cont 3）、data13 の変種「見出しと本文が同一段落」（heading_body 3。
  推奨の手順 `ai_finish` も）、data14（ref_cont 1）、data15 の変種「章見出しが本文スタイル」（heading_guess 6。AI の回答のある組なので `ai_finish` は前からある）、data17（ref_cont 5）、
  data18 と変種（back_heading 1 ずつ）、data3（ref_cont 2）、data4 の変種（heading_guess 7。`ai_finish` も）。data24・data26 は前から AI の提案の `style_check` があり、ref_cont 3・2 の行と
  添え書きが足された（key は同じ）。要確認 `app_after_refs` が足されたのは data17・data23（年の読めない段落が続く所。設計の 6 章の 1 の資料の中身）。
- 見込みとの違い: なし（data15 の変種の `ai_finish` は、AI の回答のある組なので key の差に出ない）。

次の担当への申し送り:

- heading_level（C038）・quote_like（C129）の検出は、まだ入れ物だけ（`body_suspects` に足せる形）。
- 回帰の出力は runs_uD を残した（runs_uC は消した。次の単位の基準は runs_uD）。

文書とコードの食い違い（見つけたもの）:

1. 設計の 8 章の 1〜5 は、この実装で直した（1 は FIELD_TEST の対応の記録に置き換えたことを書いた。2 は article.py・report.py・DESIGN.md の注記を検出した場所に直した。
   3・4 は FIELD_TEST の詳細の文〈点検の時点の記録〉なので直していない。5 は `back_heading_by_text` の docstring を直した〈`split_regions` の docstring は比べ方を書いていないので変えていない〉）。
2. docs/STYLE_MAPPING.md の「AI 補完を使うと、AI がこれらを確認・修正する（`set_role`）」は W8 の後のコード（AI は提案だけ）と食い違っていたので、style_check に載る形に書き直した。
3. tests/test_style_check.py の docstring「検出そのものは修正計画の単位 D が足す」を、検出は tests/test_body_back_suspects.py で確かめる、に直した。
4. docs/DEVELOPMENT.md の tests/test_style_check.py の説明「`style_suspects` を手で入れた plan」は今も正しい（直していない）。

### 点検 review19 の 1 回目の直し（2026-11-15）

- 指摘 1（should_fix）: `Classifier.loose_back_headings` の (g2) は、先に候補を集め、同じ種類の緩い候補がほかにあれば（2 つ以上なら）どれも
  受け入れず、前に同じ種類のスタイルで決まった見出し・完全一致の文字の見出しがある候補も受け入れない（どちらも要確認 style_check の back_heading。
  文は「ほかにも…の見出しの形の段落 dN があるので」「前に同じ…の見出し dN があるので」）。章見出しの「５．引用文献」の後ろの本文スタイルの「【参考文献】」、
  「５．謝辞」の後ろの「【謝　辞】」、謝辞見出しのスタイルの「謝辞」の後ろの「【謝　辞】」は、K1 で中止しなくなった
  （tests/test_body_back_suspects.py の `test_two_loose_headings_of_same_kind_are_not_back`）。
- 指摘 8（minor）: 対応なし（RESUME.md の「既知の挙動・次の版」に記録した）。
- 指摘 14（minor）: 要確認 style_check の一覧の行とコマンドラインは、載せた行に ref_cont・heading_body があれば「スタイル（段落のつなぎ・分けを含む）を
  直して」と書く（`report._style_check_action`）。
- 指摘 16（minor）: style_check の行の場所は、見出しの文字の改行から後ろを「…」にする（`report._place_short`。表示だけで、plan.locations は変えない）。
  data13 の変種「見出しと本文が同一段落」は「d13（１．はじめに…（見出し））」になった。
- 指摘 4（minor。この差分の外）: 直していない（RESUME.md の「既知の挙動・次の版」に記録した。別の単位で調べる）。
- テスト: `test_heading_body_suspect_in_style_check` に場所の列と一覧の行の確かめを足した。
- 文書: docs/DESIGN.md の C032 の行の g2 を直した。
- 回帰（タグ fx1。基準は直前の runs_uPQ）: 92 件すべて同じ（XML・状態・知らせの key の差なし。文の差だけ）。不変性チェック・最終チェック・補完の確かめ・例外・DTD の不合格は増えていない。

### 点検 review19 の 2 回目の直し（2026-11-16）

- 要確認 style_check の back_heading（minor）: 直し方を、見出しの種類（付記・謝辞・引用文献）で出し分ける（`report._back_heading_how`。スタイルの名前は
  雑誌の設定から引き、引用文献は「参考文献見出し」）。同じ種類の見出しの形の段落がほかにも挙がっていれば「どちらか一方だけを見出しのスタイルにする」を添える。
  見出しと本文が 1 つの段落の形（`back_heading_inline`）は、今の決まった文のまま。
- style_check の枠の前置き（minor）: `report.STYLE_CHECK_HOW` の最後の文を「行の直し方が段落をつなぐ・分けるものなら、その行の直し方のとおりに Word で
  直して保存し、変換し直してください。」にした。
- セルの中の入れ子の表（minor。前からの問題）・ref_cont の URL・DOI（minor）・data28 の AI 回答の表リンク（minor）: 直していない（RESUME.md の「既知の挙動・次の版」）。
- テスト: tests/test_body_back_suspects.py の `test_two_loose_headings_of_same_kind_are_not_back` に直し方の確かめを足し、tests/test_ai_review14.py の前置きの確かめを新しい文にした。
- 文書: docs/USAGE.md の style_check の項に、後付けの見出しの形の段落の直し方を足した。
- 回帰（タグ fx2。基準は直前の runs_fx1）: 92 件すべて同じ（XML・状態・知らせの key の差なし。文の差だけ。描かれない PDF の文字の数も全件同じ）。不変性チェック・最終チェック・補完の確かめ・例外・DTD の不合格は増えていない。
