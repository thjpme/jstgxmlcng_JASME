export const meta = {
  name: 'jasme-unit-h',
  description: '単位 H（0.27.0）: リンクの誤検出と AI 依頼文の保守（上付きの指数・単位が注へのリンクになる D2、語の中の「図1」「表1」が図表へのリンクになる M5、依頼文の氏名の切り出し U4、既定のモデル名 U5）。設計と独立の反例 → 実装 → 確かめ → 仕上げ → 3 観点の点検 → 修正と再点検（最大 3 回）',
  phases: [
    { title: 'Design', detail: '設計書 DESIGN_H.md（Opus high）と、実装を見ない担当の架空の docx・期待（Opus high）' },
    { title: 'Implement', detail: '設計どおりに実装し、テストを足す（Opus max）' },
    { title: 'Verify', detail: '物差し（pytest・golden・td1〜3）と、独立の反例での確かめ（Opus high）' },
    { title: 'Finalize', detail: '版 0.27.0・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '原則（Opus max）・回帰（Opus high）・利用者向け（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus max）' },
    { title: 'Recheck', detail: '修正後の点検。原則（Opus max）・回帰（Opus high）' },
  ],
}

// args: { scratch: 作業用の場所 }
const S = args.scratch
const E = `${S}/h`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「H（0.27.0）: リンクの誤検出と AI 依頼文の保守（D2・M5・U4・U5）」を作るチームの一員です。
HEAD は main の 4533222（0.26.0。detached HEAD）。作業ツリーはコミットと同じで、H の変更はコミットしていない差分として積む。
単位 B2.1（照合 pdfmatch.py の守り）は保留中で別の控えにある。H では pdfmatch.py・pdfdocx.py（照合・ルート2）と structure.py（I で分割する）には触らない。
まず読むもの: docs/FIX_PLAN.md の「H」の節と項目の表の D2・M5・U4・U5、付録の「### D2」「### M5」「### U4」「### U5」の項（反証の記録と規則の根拠）、「同じファイルを触る順と、既存テストの書き換え」、「毎回の共通作業」、「利用者に決めてもらったこと」のリンクに関する決定事項、
docs/DESIGN.md のリンク（図・表・式・注の参照、URL・DOI）と AI 依頼文の章、1 章の「許容する誤り」、docs/DEVELOPMENT.md の「守るべき原則」「残っている課題」、docs/fix_plan_repro_tests.py の D2・M5 の再現テスト（test_PROBLEM_… の名前で探す）、
src/jasme_jats/linker.py（RE_FIGREF・RE_TABREF・RE_FN_MARK・RE_FN_PLAIN、Linker.run・float_refs・_link_num・fn_marks・fn_marks_plain・_has_sup・note、body_paragraphs〈F の BoxNode を含む〉）、src/jasme_jats/model.py（LinkSpec・Para・Atom）、
src/jasme_jats/ai_assist.py（DEFAULT_MODEL・build_request・call_api・latest_opus・call_provider）、src/jasme_jats/pipeline.py（Options.ai_model、build_request を呼ぶ箇所と「姓と名の区切りがない氏名」を notes の文言から切り出している箇所）、src/jasme_jats/builder.py（BuildInfo・notes）、
tools/make_notebook.py（モデル名を書いている箇所）、notebooks/JASME_docx_to_JSTAGE_XML.ipynb は生成物（直接編集しない）、tests/make_fixtures.py（Builder・para・run・sup の部品、make_* と末尾の一覧）、tests/test_linker.py か test_links.py があればそれ、tests/test_ai.py（モデル名の直書き）、tests/test_notebook.py、tests/test_fidelity.py の test_fidelity_and_dtd（jstage_issues == [] の条件）。
FIX_PLAN に書かれた行番号（L267〜278 など）は古い版のもので当てにならない。名前で探す。H の節と付録の文面を正本にする。
H の内容（FIX_PLAN の H の節と付録が正本。要点）:
- D2（linker.py だけ）: 上付きの指数・単位（cm²・x²・s⁻¹・10³ など）が注へのリンク（fn_marks）になる。fn_marks の正規表現を RE_SUP_FN = (?:[注註][\\s　]*)?[(（]?[\\s　]*(NUM)[\\s　]*[)）]? にし、_strong_mark は「注・註で始まる、または閉じ括弧で終わる」で判定する。
  Linker.run で論文ごとの bare_notes（番号だけの注の書き方かどうか）を決める（__init__ で True に初期化）。上付きの外の文字でも補う。数字だけの一致が上付きの続きの最後にあり、直後の本文の文字が閉じ括弧で _exponent_like でなければ、番号の形がはっきりした注番号として扱う。
  続きの直前が「注・註」ならリンクする（書き方の判定には使わない）。数字と区切りだけの続き（1-3、1, 2）は続き全体の前後で指数かどうかを判定する。符号で始まる続き（⁻¹）は指数とみなす。リンクしなかった箇所は Decision（記録）としてレポートと AI 依頼文に出すだけで、actions() には入れない（単位 D の方針）。
- M5（linker.py だけ）: 語の中の「図1」「表1」（地図1・図表1・発表1回目・付表1）が図・表へのリンクになる。float_refs を finditer から regex.search(plain, pos) のループに変え、直前の文字が漢字で FLOAT_REF_OK_BEFORE='掲至及' に入らない一致は語の一部とみなし、pos = m.end(2)（先頭の番号の直後）から探し直す（tail ごと飛ばすと『図表1と表1』の後ろの正しい『表1』まで落ちる）。
  記録は、先頭の番号の図・表があるときだけ残す。
- U4: builder.BuildInfo に unsplit_names: list（(段落ID, text.strip(' 　\\t'), lang)）を足し、pipeline の文言からの切り出しをやめ、build_request(plan, linker, info.exclusions, info.unsplit_names) にする。英文を除く処理は build_request の中に置く（単体テストで確かめられるように）。
- U5: pipeline.Options.ai_model の既定を ai_assist.DEFAULT_MODEL にする。tools/make_notebook.py は ai_assist.py から DEFAULT_MODEL をファイルとして読み、一致しなければ分かるエラーにする。表示名・料金・提供終了の予定は DEFAULT_MODEL_INFO にまとめる。tests/test_ai.py の直書きのモデル名を DEFAULT_MODEL に置き換え、test_notebook.py はパッケージから import した DEFAULT_MODEL と比べる。
- 新しい fixture: sample_links.docx（注の書き方が「注1）」などはっきりした形）と sample_links_bare.docx（番号だけの上付きの注）を make_fixtures.py の make_links()・make_links_bare() で作り、tests/test_links.py を新しく書く。fixture は test_fidelity_and_dtd の jstage_issues == [] を満たす形（図に画像、表に本体、注の一覧、引用文献、英文要旨を入れる）。
- 版は 0.27.0（リンクが変わるので 2 桁目）。
- まとめ役の暫定の判断（利用者にはまだ確かめていない。設計書と FIX_PLAN に「暫定」と明記する）: H の「前提」の利用者の判断（注番号の書き方を論文ごとに判定する方針、記録の件数、参照の前に来てよい漢字 FLOAT_REF_OK_BEFORE、英文 1 語の氏名を AI 依頼文から外すこと）は、利用者が「指示がなければどんどん続けてよい」と言っているので、
  FIX_PLAN の H の節と付録の規則をそのまま実装し、暫定として報告する。画面（Colab・CLI）の文言・見え方は、利用者が後でまとめて直す方針なので、表示の仕組みは変えない（U5 でノートブックのモデル名の出どころを変えるのは可）。
原則（CLAUDE.md・DEVELOPMENT.md「守るべき原則」）: docx の本文の文字を 1 文字も変えない。文字列を書き換えるコードを書かない。リンクはアトムに LinkSpec を付けて表し（文字は変えない）、XML の段落の文字は Emitter.span() を通す。
リンクを付けない判断は Decision としてレポート（4 章）と AI 依頼文に出す（actions() には入れない）。H はリンクの規則を変える単位なので、リンクを付けた・付けなかった結果が XML の xref の有無だけに現れ、文字・段落の構造・不変性チェックが変わらないことを確かめる。
要対応・要確認の知らせは report.actions() に Action を足すだけ（H では足さない）。利用者は技術に詳しくない編集委員なので、記録の文言は、何が起きて、どこを見て、何をすればよいかを短く書く。
文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従い、文書の側を合わせる。見つけた食い違いは、直したものも直さなかったものも、報告（deviations か checked）にすべて列挙する。
実際の原稿: tests/private/colab/td1〜3（td1.docx〜td3.docx と td?.pdf。コミットしない。文字を書き写さない。上付きの指数・単位や語の中の「図1」が実際にあるかを数えてよいが、文字は記録しない）。
変換: cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml --route docx --ai manual --out <出力先>（ルート2 は --route pdf --pdf <pdf>）。0.26.0 の src の写しは ${E}/base0260_src（比べる相手）。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider。指定した src で本体のテストを流すのは sh ${S}/fixB2r4/tools/pytest_src.sh <src> <python> [引数]）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${E}/golden_base/manifest.json〈0.26.0〉と同じ名前の 23 件で比べる。
違ってよいのは、H で意図したリンクの変化（上付きの指数・単位が注にリンクされなくなる、語の中の「図1」がリンクされなくなる）とそれに伴う 4 章の記録・AI 依頼文の行だけ。違いは本体を diff して 1 つずつ理由を書く）、
td1〜3 の変換（ルート1 とルート2 で 0.26.0 と XML・レポート・AI 依頼文を比べる。xref の違いをすべて列挙し、それぞれが D2・M5 で意図したものかを示す。文字・段落・不変性・最終・DTD・J-STAGE のチェックは変わらない。XML に入らなかった画像が増えない）、
ruff（ruff check src tests tools。HEAD より件数を増やさない）。
厳守:
- git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- python tests/make_fixtures.py をそのまま実行して既存の fixture を作り直さない（LibreOffice の版で sample_pdfcheck.pdf のバイト列が変わる）。新しい docx は make_links()・make_links_bare() を足し、その関数だけを呼んで作る
  （例: python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_links('tests/fixtures/sample_links.docx')"）。末尾の一覧（main）にも入れる。作った後に git status で、意図した docx だけが増え、既存の fixture が変わっていないことを確かめる。
- 実際の論文の本文（tests/private の docx・PDF の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る）。実験は ${E}/<担当名>/ の下に置く。tests/ に一時ファイルを残さない（tests/__pycache__ も消す）。
- ディスクの空きを df -h / で確かめ、3GB を切りそうなら自分の古い作業ファイルを消す。担当の最後に、大きな出力（docx・pdf・xml・zip・画像）を消す（結果の JSON・ログ・スクリプトは残す）。
- コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    design_doc: { type: 'string', description: `${E}/DESIGN_H.md のパス` },
    decisions: { type: 'string', description: 'D2・M5・U4・U5 ごとに決めたこと（正規表現、bare_notes の判定、指数の判定、FLOAT_REF_OK_BEFORE、探し直しの位置、記録の条件と文言、BuildInfo.unsplit_names、DEFAULT_MODEL_INFO と make_notebook の読み方）と、決めなかったこと・却下した案・暫定の判断' },
    changes: { type: 'string', description: 'ファイル・関数ごとの変更点' },
    tests: { type: 'string', description: 'テストの計画（fixture の docx・確かめること・既存テストの修正）' },
    acceptance: { type: 'string', description: '合格の条件（物差しごと。golden・td1〜3 で変わってよいもの）' },
    risks: { type: 'string' },
  },
  required: ['design_doc', 'decisions', 'changes', 'tests', 'acceptance', 'risks'],
}
const ORACLE_SCHEMA = {
  type: 'object',
  properties: {
    dir: { type: 'string', description: '架空の docx・期待を置いた場所' },
    cases: { type: 'string', description: 'ケースごとの docx・期待（どの箇所が注・図・表へのリンクになり、どの箇所がならないか、記録の有無、AI 依頼文の氏名の行、不変性チェックの合否）の一覧' },
    runner: { type: 'string', description: '期待と実際を比べる道具の使い方' },
    base_result: { type: 'string', description: '0.26.0（作業ツリーの今の src）での結果' },
    notes: { type: 'string' },
  },
  required: ['dir', 'cases', 'runner', 'base_result', 'notes'],
}
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string', description: 'golden・td1〜3・独立の反例の結果（0.26.0 と並べる。xref の違いの一覧）' },
    deviations: { type: 'string', description: '設計と違えたこと・直さなかった指摘と理由・文書とコードの食い違いの列挙' }, open_issues: { type: 'string' },
  },
  required: ['changed_files', 'summary', 'tests_added', 'pytest_result', 'measures', 'deviations', 'open_issues'],
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    passed_all: { type: 'boolean' }, measures: { type: 'string' },
    problems: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'should', 'nit'] },
      where: { type: 'string' }, problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' },
    }, required: ['severity', 'where', 'problem', 'evidence', 'fix'] } },
  },
  required: ['passed_all', 'measures', 'problems'],
}
const FIND_SCHEMA = {
  type: 'object',
  properties: {
    checked: { type: 'string', description: '何をどう確かめたか。指摘がなくても書く。文書とコードの食い違いもここに列挙する' },
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'should', 'nit'] },
      file: { type: 'string' }, line: { type: 'integer' },
      problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' },
    }, required: ['severity', 'file', 'line', 'problem', 'evidence', 'fix'] } },
  },
  required: ['checked', 'findings'],
}

phase('Design')
const [design, oracle] = await parallel([
  () => agent(`${COMMON}
## 担当: 設計（design）
H の設計書 ${E}/DESIGN_H.md を書く（コードは変えない。試作は ${E}/design/ の下の写しで）。FIX_PLAN の H の節と付録 D2・M5・U4・U5 を正本として、次を決めて書く:
1. リンクの今の形: linker.py の fn_marks・fn_marks_plain・float_refs・_link_num・_has_sup・note と Linker.run の順序、Decision の記録のしかた（category・文言）、AI 依頼文（build_request）がリンクの記録をどう載せるかを読んで表にする。
2. D2: RE_SUP_FN・_strong_mark・bare_notes の判定（論文ごと。Linker.run のどの時点で決めるか。上付きの外の文字の補い方）、_exponent_like（直後の文字・符号・区切り・単位の形）の仕様、続き（1-3、1, 2、⁻¹）の扱い、注・註の直前の扱い、リンクしなかった箇所の記録（category・文言・件数の上限があるなら理由）。
   fn_marks_plain（本文の「（注1）」）との関係。F の BoxNode（囲みの中の上付き）も同じ規則になること。
3. M5: float_refs の探し直し（regex.search と pos = m.end(2)）、FLOAT_REF_OK_BEFORE、「図表1と表1」「地図1」「発表1回目」「付表1」「前掲図1」「至図1」の期待、記録の条件（先頭の番号の図・表があるときだけ）と文言。式の参照（eq_refs）は変えないこと。
4. U4: builder.BuildInfo.unsplit_names の作り方（どこで氏名を集めるか。lang の決め方）、build_request の引数と英文を除く処理、pipeline の切り出しの削除。AI 依頼文の文字が 0.26.0 とバイト単位で同じになること（英文 1 語の氏名を外す以外）。
5. U5: DEFAULT_MODEL・DEFAULT_MODEL_INFO（表示名・料金・提供終了の予定）の形、pipeline.Options.ai_model の既定、make_notebook.py が ai_assist.py からモデル名を読む方法（パッケージを import しないでファイルとして読む理由を確かめる）と一致しないときのエラー、tests/test_ai.py・test_notebook.py の直し方。
6. td1〜3 で、上付きの数字（指数・単位・注番号）と語の中の「図N」「表N」が実際に何件あり、0.26.0 でどうリンクされているかを数える（数値だけ記録。文字は書かない）。H の後で xref がどう変わるかを見積もる。
7. テストの計画: tests/make_fixtures.py の make_links()・make_links_bare()（部品: 上付きの run、注の一覧、図・表・画像・引用文献・英文要旨）、tests/test_links.py（リンクされる・されない箇所、記録、bare_notes の両方の書き方、境界）、docs/fix_plan_repro_tests.py の D2・M5 の再現テストの期待を逆にして tests/ に取り込む、U4・U5 の単体テスト、既存テスト（test_linker・test_ai・test_notebook）の修正。
8. 合格の条件: pytest すべて合格、golden は H で意図した変化だけ、td1〜3 はルート1・ルート2 とも文字・段落が同じで xref の違いがすべて D2・M5 の意図したもの、不変性・DTD 合格、画像の出力漏れが増えない、AI 依頼文は意図した行以外同じ。
9. 残る限界と、利用者に確かめてもらうこと（注番号の書き方の判定、記録の件数、FLOAT_REF_OK_BEFORE、英文 1 語の氏名。DEVELOPMENT の「残っている課題」）。
設計書は、関数ごとの変更点まで書く（実装の担当が迷わないように）。独立の反例の担当（oracle）とは相談しない。`, { label: 'design', phase: 'Design', schema: DESIGN_SCHEMA, model: 'opus', effort: 'high' }),
  () => agent(`${COMMON}
## 担当: 実装を見ない反例（oracle_h）
あなたは実装を見ない担当です。設計書 ${E}/DESIGN_H.md と、linker.py の fn_marks・float_refs・_link_num の中身、ai_assist.py の build_request の中身、pipeline.py の中身は読まない（期待が実装に引きずられないように）。
読んでよいもの: FIX_PLAN の H の節と付録 D2・M5・U4・U5、DESIGN.md、docs/fix_plan_repro_tests.py、tests/make_fixtures.py の部品（Builder・para・run・sup・table・画像・注の一覧の書き方と make_* の形）、tests/test_linker.py があればその確かめ方、XML の出力（xref の形。同梱の DTD）、jasme_jats の公開 API（convert・Options・Result）、レポートの 4 章（判断）の形。
FIX_PLAN の H だけから、架空の文字で、原稿（docx）と期待（どの箇所が注・図・表への xref になり、どの箇所がならないか〈文字は変わらない〉、記録（4 章）の有無、AI 依頼文の「姓と名の区切りがない氏名」の行、不変性チェックの合否）の組を 15〜30 件作り、${E}/oracle/ に置く。
docx は make_fixtures.py の部品を import して作る（make_fixtures.py 自体は変えない。足りない部品は自分の生成器 ${E}/oracle/gen_h.py に書く）。範囲:
- D2: 注の一覧がある原稿で、上付きの「1」「2)」「注1」「（1）」（注番号）と、上付きの「2」「3」「⁻¹」「2,3」「1-3」が cm・x・10・s・m の後ろに来るもの（指数・単位）、上付きの外の「注」「）」で補う形、番号だけの注の書き方の原稿（bare）と「注1）」の書き方の原稿で同じ本文がどう変わるか、注の一覧の番号を超える上付き、注のない原稿の上付き。
- M5: 「図1」「表1」「図 1」「Fig. 1」「Table 1」と、「地図1」「図表1」「発表1回目」「付表1」「図表1と表1」「前掲図1」「至図1」「及図1」、図・表のない番号、文の先頭の「図1」、括弧の中の「（図1）」、式の参照「式(1)」が変わらないこと、F の囲み（テキストボックス）の中の参照。
- U4: 姓と名の間に空白がない和文の著者名（依頼文に出る）、英文 1 語の氏名（出ない）、空白のある和文の氏名（出ない）。
- U5 は実装の形の変更なので反例は要らない（変換の出力が変わらないことだけ）。
期待は、FIX_PLAN の方針から一つに決まるものだけ「exact」にし、決めかねるもの（記録の文言・件数）は「どちらか」（許される結果を列挙）にする。期待と実際を比べる道具 ${E}/oracle/run_h.py を書く（指定した src で変換し、XML の xref と 4 章と AI 依頼文を見て、ケースごとに OK/FAIL と理由を出す。
実行してよいのは自分の道具と python -m jasme_jats と jasme_jats の公開 API〈convert・Options〉だけ）。作業ツリーの今の src（0.26.0 の動き）で流し、結果を base_result に書く（期待どおりでないのが H で直すもの）。
新しい架空の文字が実際の論文（tests/private）の文字と 12 文字以上一致しないことを確かめる。`, { label: 'oracle_h', phase: 'Design', schema: ORACLE_SCHEMA, model: 'opus', effort: 'high' }),
])
log(`design: ${design ? 'ok' : '失敗'} / oracle: ${oracle ? 'ok' : '失敗'}`)

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 実装（impl）
${E}/DESIGN_H.md（設計書）を読み、作業ツリーの src・tools に実装する。設計書に書かれていないことで決める必要が出たら、FIX_PLAN の H の方針と原則に沿って決め、deviations に書く。
テストは設計書の計画どおり tests/make_fixtures.py（make_links・make_links_bare の追加。既存のほかの fixture は作り直さない）・tests/test_links.py（新規）・既存の linker・ai・notebook のテストに足す。
足したテストが 0.26.0 の src（${E}/base0260_src。sh ${S}/fixB2r4/tools/pytest_src.sh ${E}/base0260_src python <テスト>）で落ちることを確かめる（fixture を使うものは落ちること、U5 の形のテストは落ちるか import できないこと）。docs/fix_plan_repro_tests.py の D2・M5 の再現テストは、期待を逆にして tests/ に取り込み、元のファイルの冒頭の説明を直す。
独立の反例（${E}/oracle。run_h.py の使い方は報告のとおり）も流し、FAIL が残れば、期待が FIX_PLAN の方針に合っているかを確かめたうえで、実装の誤りなら直し、期待の誤りなら理由を書く（反例のファイルは変えない）。
docs/DESIGN.md（リンクと AI 依頼文の章）と docs/DEVELOPMENT.md（コードの構成・残っている課題）を実装に合わせる（版・ノートブック・FIX_PLAN・README は仕上げの担当。ただし tools/make_notebook.py を変えたら python tools/make_notebook.py を一度流して動くことを確かめる）。pytest（3.13・3.10）・ruff・golden・td1〜3（ルート1・ルート2）を流す。
文書とコードの食い違いを見つけたら、コードに合わせて直し、deviations に列挙する。
設計の担当の報告:
${JSON.stringify(design, null, 1)}
実装を見ない担当の報告:
${JSON.stringify(oracle, null, 1)}`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、設計書の合格の条件と物差し（pytest 3.13・3.10、ruff、golden〈23 件の違いを本体の diff で 1 つずつ確かめる〉、td1〜3 をルート1・ルート2 で 0.26.0 と比べる〈文字・段落が同じこと、xref の違いをすべて列挙して D2・M5 の意図したものか、記録の件数、不変性・DTD・J-STAGE のチェック、画像の出力漏れ、AI 依頼文〉、
独立の反例 ${E}/oracle の run_h.py）で測る。自分でも架空の docx を 5 件ほど作り（指数と注番号の境界、bare と「注1）」の両方の書き方、語の中の「図1」と正しい「表1」の並び、囲みの中の参照、和文・英文の氏名）、XML の xref・4 章の記録・AI 依頼文を目で確かめる。
リンクの規則が文字・段落の構造・不変性チェックに影響しないこと（xref の有無だけが変わること）を、XML から xref を外して 0.26.0 と比べる実験で確かめる。
ファイルは変更しない（実験は ${E}/verify/ の下）。問題は severity を付けて problems に書く。文書とコードの食い違いを見つけたら problems（nit）に書く。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify', phase: 'Verify', schema: VERIFY_SCHEMA, model: 'opus', effort: 'high' })
let pre = null
if (verify && (verify.problems || []).some(p => p.severity !== 'nit')) {
  pre = await agent(`${COMMON}
## 担当: 確かめで見つかった問題を直す（fix_verify）
次の問題のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。直した後、pytest 3.13・3.10・ruff・golden・td1〜3（ルート1・ルート2）・独立の反例を流し直す。
問題:
${JSON.stringify(verify.problems, null, 1)}
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'fix_verify', phase: 'Verify', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })
}

phase('Finalize')
const fin = await agent(`${COMMON}
## 担当: 仕上げ（finalize）
1. 版を 0.27.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す（U5 でモデル名の出どころが変わっているので、生成物のモデル名が ai_assist.DEFAULT_MODEL と一致することを確かめる）。
2. docs/FIX_PLAN.md: 反映の順序の表の H を「（実装済み）」にし、H の節に、設計の要点・テスト・実装で決めたこと・暫定の判断（利用者に確かめてもらう: 注番号の書き方を論文ごとに判定する方針、記録の件数、参照の前に来てよい漢字、英文 1 語の氏名を依頼文から外すこと）・確かめた数（td1〜3 の件数は数値だけ）・残る限界・
   文書とコードの食い違いの扱いを書く。D2・M5・U4・U5 の行と付録の項は、実装に合わせて必要なら書き直す。「同じファイルを触る順と、既存テストの書き換え」の節に H で触ったファイルを入れる。
3. CLAUDE.md・docs/DEVELOPMENT.md（コードの構成・守るべき原則・残っている課題）・docs/DESIGN.md・README.md（利用者向けの説明に、上付きの指数・単位は注にリンクしないこと、語の中の「図1」はリンクしないこと、リンクしなかった箇所は 4 章に出ることを短く）・docs/fix_plan_repro_tests.py の冒頭の説明が実装と合うか確かめて直す。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる（tests/private の docx・PDF の文字から作った 12 文字の並びと、足した行を突き合わせる）。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', model: 'opus', effort: 'max', text: `原則とリンクの正しさ: 注番号・図・表の参照の判定で、本来リンクすべき箇所（はっきりした注番号「注1」「1)」、本文の「図1」「表1」、「図表1と表1」の後ろの「表1」、前掲・至・及の後ろ）がリンクされなくなる経路、指数・単位や語の中の「図1」がなおリンクされる経路、
文字が変わる・段落の構造が変わる・Emitter.span() を通さない文字・文字列を書き換えるコードがないか、LinkSpec の付け方（apply_span・range_linked）で既存のリンク（URL・DOI・式・Word のハイパーリンク）が壊れないか、記録（Decision）の漏れと過剰、AI 依頼文（build_request）の内容が 0.26.0 と意図せず違わないか、
F の BoxNode の中の参照が同じ規則か、bare_notes の判定が論文ごとに一貫するか。実験で、架空の docx（${E}/oracle のものと自分で作るもの）と td1〜3（ルート1・ルート2）で、xref の差分・不変性チェック・lost_images・DTD を確かめる。` },
  { key: 'regression', model: 'opus', effort: 'high', text: `回帰とテスト: pytest 3.13・3.10、ruff、golden（23 件の違いを本体の diff で確かめ、意図した変化だけか）、td1〜3（ルート1・ルート2）を 0.26.0 と比べる（xref 以外に違いがないか。G の文字ポリシー・F のテキストボックス・図表〈B3〉・注〈E〉・照合〈B2〉が変わっていないか）、独立の反例 ${E}/oracle。
足したテストが 0.26.0 で落ちるか。規則の条件を外す・境界を動かすとテストが落ちるか（_exponent_like の各分岐、bare_notes の両方の値、FLOAT_REF_OK_BEFORE の各文字、探し直しの位置、unsplit_names の lang、DEFAULT_MODEL の不一致のエラー）。tools/make_notebook.py が動き、生成物のノートブックが 0.26.0 とモデル名以外で同じか。` },
  { key: 'user', model: 'opus', effort: 'high', text: `利用者への見え方と文書: レポートの 4 章（リンクしなかった箇所の記録）と AI 依頼文（「姓と名の区切りがない氏名」の行、リンクの記録）が、技術に詳しくない編集委員に「何が起きて、どこを見て、何をするか」分かるか。記録が多すぎて 4 章が読めなくならないか（td1〜3 で件数を見る）。
README・DESIGN・DEVELOPMENT・CLAUDE.md・FIX_PLAN（H の節・D2・M5・U4・U5・反映の順序の表）が実装と合っているか。版が 0.27.0 にそろい、ノートブックが作り直され、ノートブックのモデル名・料金の説明が DEFAULT_MODEL_INFO と合っているか。
td1〜3 のレポート（ルート1・ルート2）と AI 依頼文を実際に読む。実際の論文の文字がコミットされる場所に入っていないか。` },
]
const reviewOf = (l, extra, opts) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 H の実装を厳しく点検する。ファイルは変更しない（実験は ${E}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.26.0 との比較を evidence に書く）。blocking は原則違反（文字の変化・段落の構造の変化・不変性チェックの不合格・既存のリンクの破壊・画像の出力漏れ・DTD 不合格）・
本来リンクすべき箇所がリンクされなくなる回帰（0.26.0 で正しかったもの）・テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.26.0 にもあって H で悪くなっていないものは、新しく見つけたものだけ nit にする。
文書とコードの食い違いは、コードに合わせて直す側で指摘し（nit）、checked にも列挙する。問題がなければ findings は空でよい（checked に何を確かめたかを書く）。
${extra}`, { label: `review:${l.key}`, phase: opts.phase, schema: FIND_SCHEMA, model: opts.model || l.model, effort: opts.effort || l.effort })
const PREV = `仕上げの担当の報告:\n${JSON.stringify(fin, null, 1)}\n確かめの担当の報告:\n${JSON.stringify(verify, null, 1)}`
const reviews = await parallel(LENSES.map(l => () => reviewOf(l, PREV, { phase: 'Review' })))
const failedFirst = reviews.map((r, i) => r ? null : LENSES[i].key).filter(Boolean)
let todo = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
const firstFindings = todo
log(`指摘: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length} / nit ${todo.filter(f => f.severity === 'nit').length}${failedFirst.length ? ' / 失敗した観点: ' + failedFirst.join(',') : ''}`)

const rounds = []
let incomplete = null
for (let round = 1; round <= 3 && todo.some(f => f.severity !== 'nit'); round++) {   // 最大 3 回（2026-10-26 の利用者の指示）
  phase('Fix')
  const fix = await agent(`${COMMON}
## 担当: 点検の指摘を直す（${round} 回目）
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書とコードの食い違いは、コードに合わせて文書を直す）。FIX_PLAN の H の方針と原則の範囲で直す。
直した後、pytest 3.13・3.10・ruff・golden・td1〜3（ルート1・ルート2）・独立の反例を流し直す。必要なら文書・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })
  phase('Recheck')
  const RE = [LENSES[0], LENSES[1]]
  const rr = await parallel(RE.map(l => () => reviewOf(l, `${round} 回目の修正の後の点検。直した指摘が本当に直ったか（再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。blocking・should・nit の基準は 1 回目と同じ。
前の指摘:
${JSON.stringify(todo, null, 1)}
修正の担当の報告:
${JSON.stringify(fix, null, 1)}`, { phase: 'Recheck' })))
  const failedLens = rr.map((r, i) => r ? null : RE[i].key).filter(Boolean)
  todo = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: RE[i].key, ...f })))
  rounds.push({ round, fix, findings: todo, failedLens })
  log(`${round} 回目の点検: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length}${failedLens.length ? ' / 失敗した観点: ' + failedLens.join(',') : ''}`)
  if (failedLens.length) { incomplete = failedLens; break }
}
return { design, oracle, impl, verify, pre, fin, reviews, failedFirst, firstFindings, rounds, remaining: todo, incomplete }
