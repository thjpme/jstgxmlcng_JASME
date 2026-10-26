export const meta = {
  name: 'jasme-unit-e',
  description: '単位 E（0.24.0）: 注（Word の文末脚注）と資料の見出し（N6・D4・D3）。設計と独立の反例 → 実装 → 確かめ → 仕上げ → 3 観点の点検 → 修正と再点検（最大 3 回）',
  phases: [
    { title: 'Design', detail: '設計書 DESIGN_E.md（Opus high）と、実装を見ない担当の架空の docx・期待（Opus high）' },
    { title: 'Implement', detail: '設計どおりに実装し、テストを足す（Opus max）' },
    { title: 'Verify', detail: '物差し（pytest・golden・td1〜3）と、独立の反例での確かめ（Opus high）' },
    { title: 'Finalize', detail: '版 0.24.0・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '原則（Opus max）・回帰（Opus high）・利用者向け（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus max）' },
    { title: 'Recheck', detail: '修正後の点検。原則（Opus max）・回帰（Opus high）' },
  ],
}

// args: { scratch: 作業用の場所 }
const S = args.scratch
const E = `${S}/e`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「E（0.24.0）: 注（Word の文末脚注）と資料の見出し（N6・D4・D3）」を作るチームの一員です。
HEAD は main の e2dbf73（0.23.1。detached HEAD）。作業ツリーは HEAD と同じ（コミットしていない差分なし）で、E の変更はコミットしていない差分として積む。
単位 B2.1（照合 pdfmatch.py の守り）は保留中で、別の控え（67a854b）にある。E では pdfmatch.py・pdfdocx.py に、D4 が必要とする箇所（pdfmatch._para_seq の注の鍵、pdfdocx の PARTS・raw_paragraph_ids・paragraph_units・_all_paragraphs・_structure の
文末脚注と領域の扱い）だけ触り、それ以外（_isolate・_classify・_joint などの照合の規則）は変えない。
まず読むもの: docs/FIX_PLAN.md の「E」の節と項目の表の N6・D4・D3、「利用者に決めてもらうこと」の 7・8 と決定事項 7・8、付録の D3・D4（テストの一覧）、「毎回の共通作業」、
docs/DESIGN.md の注・領域（front_en・app・back）に関する章、docs/DEVELOPMENT.md の「守るべき原則」、docs/fix_plan_repro_tests.py の test_PROBLEM_appendix_with_paren_goes_into_abstract・test_PROBLEM_endnotes_are_excluded、
src/jasme_jats/structure.py の RE_APPENDIX・AFTER_BODY_REGIONS・build_front_en・build_back・attach_word_notes・assign_ids、src/jasme_jats/model.py（FnNode・Atom の fnref）、src/jasme_jats/docx_reader.py の read_notes と
footnoteReference/endnoteReference（customMarkFollows）、src/jasme_jats/builder.py の fn_numbers、src/jasme_jats/emit.py の write_object（fnref）、src/jasme_jats/linker.py の fn_marks、
src/jasme_jats/ai_assist.py の ROLES・REGION_ROLES・role_overrides・build_request（除外一覧の案内）・_placement_problem、src/jasme_jats/report.py の word_note_refs と 8 章・13 章、
src/jasme_jats/pdfmatch.py の _para_seq（fnref・fnlist）、src/jasme_jats/pdfdocx.py の PARTS・raw_paragraph_ids・paragraph_units・_structure、tests/test_notes.py・tests/test_structure.py・tests/test_pdfmatch.py、
tests/make_fixtures.py（Builder・para・tail・make_structure・make_notes）。FIX_PLAN に書かれた行番号（L789 など）は古い版のもので当てにならない。名前で探す。
FIX_PLAN に出てくる rvz_d3.py・rvz_d4.py・exp_struct_re.py（計画を作ったときの実験）はもう残っていない。付録の D3・D4 の一覧と、FIX_PLAN の E の節の文面を正本にする。
E の内容（FIX_PLAN の E の節が正本。要点）:
- N6: ai_assist に set_role_problem(p, plan, role) を作り、role_overrides と build_request の除外一覧の案内の両方で使う。拒否: float_id のある段落、Word の脚注・文末脚注の段落（すべて）、region のない段落。テキストボックスの規則は F で足す。
- D4: 文末脚注を注として出す。model.note_key(fn_kind, fn_id)・note_label(key)（'-custom' を除いて判定）。FnNode に word_kind、word_id には note_key。attach_word_notes を書き直す
  （本文の参照を参照順に集め、続けて注の中の参照、除外された段落の中の参照も数える。脚注・文末脚注を通し番号の FnNode にする〈決定事項 7: 本文で最初に参照される順の通し番号、形式は fn_mark「1)」〉。
  参照されていない注の段落は plain() が空でなければ除外、空白だけなら exclude_blank。最後の「未対応」の除外のループ〈A の暫定の知らせを含む〉は削除）。
  参照の照合を note_key に直す: emit.write_object（fn_numbers を note_key で引く）、pdfmatch._para_seq、pdfdocx の PARTS（word/endnotes.xml: 'e'）と _all_paragraphs、report の word_note_refs と 8 章・13 章、ai_assist の注の一覧の表記。
  既存テストの修正: tests/test_pdfmatch.py の fnref・fnlist の鍵を ('fnref','footnote:5')・('fnlist','footnote:5') に、tests/test_notes.py の拒否理由の文言。ルート2 のテストは sample_pdfcheck.pdf を作り直さず、extract_pages を差し替える。
- D3: RE_APPENDIX を広げる（先頭の括弧【［[〔〈《＜<(（、語の後の番号の前に -－‐ と枝番、番号の直後に空白・コロン・ピリオド・読点・括弧・ダッシュ・行末、ASCII のハイフンは語の直後に許さない、
  番号にⅠ-Ⅻ・ⅰ-ⅻ・①-⑳）。build_front_en で、英文要旨の後に章・節・項見出しのスタイルの段落が来たら資料を始め Decision を記録（決定事項 8(a)）。和文の論文で英文要旨にかな・漢字が 3 割以上の段落があれば Decision（applied=False）と 10 章の警告。
  ai_assist の ROLES に app_heading、REGION_ROLES の front_en と app に加え、app に abstract も加える。pdfdocx._structure の比較に plan.region を加える。
- まとめ役の暫定の判断（利用者にはまだ確かめていない。設計書と FIX_PLAN に「暫定」と明記する）: (1) 決定事項 8(b) の、引用文献の後ろに置かれた資料は、資料にせず警告（10 章の要確認）だけにする（扱える原稿が実際に出てから広げる）。
  (2) customMarkFollows の文末脚注は、今の脚注の customMarkFollows と同じ扱い（番号を 1 つ使い、本文の印の文字は docx のまま）。範囲外として文書に明記する。
- 版は 0.24.0（XML に fn-group の注が増える・資料の領域が変わるので 2 桁目）。
原則（CLAUDE.md・DEVELOPMENT.md「守るべき原則」）: docx の本文の文字を 1 文字も変えない。文字列を書き換えるコードを書かない（構造は LinkSpec か段落の役割で表す）。XML の段落の文字は Emitter.span() を通す。
出力しない段落は理由付きで記録し（plan.exclude()・exclude_blank()）、出力した段落を除外にも記録しない。XML に入らなかった画像は pipeline.lost_images() が検出する。
要対応・要確認の知らせは report.actions() に Action を足すだけ（個別の表示を render・colab・cli・make_notebook.py に足さない。単位 D の形）。
新しい docx の要素（文末脚注）は、ooxml.canonical_text（検証）と docx_reader（変換）、ルート2 の pdfdocx.paragraph_units / raw_paragraph_ids を同じ文字ポリシーで直す。
利用者は技術に詳しくない編集委員なので、知らせの文言は、何が起きて、どこを見て、何をすればよいかを短く書く。
文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従い、文書の側を合わせる。見つけた食い違いは、直したものも直さなかったものも、報告（deviations か checked）にすべて列挙する。
実際の原稿: tests/private/colab/td1〜3（td1.docx〜td3.docx。コミットしない。文字を書き写さない）。文末脚注があるかは実際に読んで確かめる。
変換: cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml --route docx --ai manual --out <出力先>。0.23.1 の src の写しは ${E}/base0231_src（比べる相手）。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider。指定した src で本体のテストを流すのは sh ${S}/fixB2r4/tools/pytest_src.sh <src> <python> [引数]）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${E}/golden_base/manifest.json〈0.23.1〉と同じ名前の 23 件で比べる。
違ってよいのは、fixture に D3・D4 の要素を足した sample_structure 系と、意図した出力の変化（注の鍵の形など）だけ。違いは本体を diff して 1 つずつ理由を書く）、
td1〜3 の変換（0.23.1 と XML・レポートを比べる。違ってよいのは E で意図したもの〈文末脚注が注に出る、資料の領域、注の鍵の表記〉だけ。不変性・最終・DTD・J-STAGE のチェックは合格。XML に入らなかった画像が増えない）、
ruff（ruff check src tests tools）。
厳守:
- git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- python tests/make_fixtures.py をそのまま実行して既存の fixture を作り直さない（LibreOffice の版で sample_pdfcheck.pdf のバイト列が変わる）。sample_structure.docx に D3・D4 の要素を足すときは、make_fixtures.py の make_structure（と Builder）を直し、
  その関数だけを呼んで作る（例: python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_structure('tests/fixtures/sample_structure.docx')"）。作り直した後に git diff --stat tests/fixtures で、意図した docx だけが変わったことを確かめる。
  新しい docx を足すなら make_<名前>() を足し、末尾の一覧（main）にも入れる。tests/conftest.py の ALL_DOCS に入れるなら golden の件数が増える。
- 実際の論文の本文（tests/private の docx の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る）。実験は ${E}/<担当名>/ の下に置く。tests/ に一時ファイルを残さない（tests/__pycache__ も消す）。
- ディスクの空きを df -h / で確かめ、3GB を切りそうなら自分の古い作業ファイルを消す。担当の最後に、大きな出力（docx・pdf・xml・zip・画像）を消す（結果の JSON・ログ・スクリプトは残す）。
- コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    design_doc: { type: 'string', description: `${E}/DESIGN_E.md のパス` },
    decisions: { type: 'string', description: 'N6・D4・D3 ごとに決めたこと（注の番号の規則、鍵の形、除外の規則、資料の見出しの規則、set_role の拒否の規則、知らせの文言）と、決めなかったこと・却下した案・暫定の判断' },
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
    cases: { type: 'string', description: 'ケースごとの docx・期待（注の番号・リンク・除外・領域・知らせ）の一覧' },
    runner: { type: 'string', description: '期待と実際を比べる道具の使い方' },
    base_result: { type: 'string', description: '0.23.1（作業ツリーの今の src）での結果' },
    notes: { type: 'string' },
  },
  required: ['dir', 'cases', 'runner', 'base_result', 'notes'],
}
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string', description: 'golden・td1〜3・独立の反例の結果（0.23.1 と並べる）' },
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
E の設計書 ${E}/DESIGN_E.md を書く（コードは変えない。試作は ${E}/design/ の下の写しで）。FIX_PLAN の E の節を正本として、次を決めて書く:
1. D4 の注の番号: 脚注と文末脚注を、本文で最初に参照される順の通し番号にする規則（決定事項 7）。「参照の順」の定義（doc.all_paragraphs() の順か、本文の領域 → 注の中 → 除外された段落の順か。FIX_PLAN の文面に従う）。
   注の中からの参照（脚注の中から文末脚注を参照）・除外された段落の中の参照・削除の変更履歴の中の参照の扱い（番号は付け、リンクのない注になることを Decision と 8 章で知らせる）。参照されていない注の除外の理由の文言。
   note_key の形（'footnote:5'・'endnote:5'。'-custom' の扱い）と note_label（「Word の脚注 5」「Word の文末脚注 5」）。FnNode.word_kind・word_id、builder.fn_numbers・emit.write_object・linker・pdfmatch._para_seq・pdfdocx・report・ai_assist で鍵をそろえる箇所。
   customMarkFollows の文末脚注の扱い（暫定: 脚注と同じ）。plan.locations の文言。A の暫定の知らせ（ENDNOTE_EXCLUDED と、文末脚注の件数を要確認として出す仕組み。report.actions() の中）をどう外すか。
2. D3 の資料の見出し: RE_APPENDIX の新しい正規表現（認識する書き方・しない書き方の一覧を設計書に表で書く。「資料（授業プリント）」「資料Ⅰ　授業プリント」「資料Ⅱ（ワークシート）」「付録①　調査票」「資料1-2」「Appendix A」は認識、
   「資料を配布した。」「資料-1」のような本文の文は認識しない）。build_front_en で見出しのスタイルから資料を始める規則と Decision の文言。英文要旨に和文の段落があるときの判定（かな・漢字の割合 3 割）と警告（10 章・要確認。report.actions()）。
   引用文献の後ろの資料は警告だけ（暫定）。AI の app_heading・abstract の役割（REGION_ROLES）と、set_role で資料と英文要旨の境を動かす動き。pdfdocx._structure の比較に region を加える方法。
3. N6: set_role_problem(p, plan, role) の仕様（戻り値は理由の文字列か ''）。role_overrides と build_request の除外一覧の案内の両方で使う。拒否するもの（float_id・Word の注の段落・region のない段落）と理由の文言。既存の tests/test_notes.py の文言の修正。
4. テストの計画: 付録 D3・D4 の一覧をすべて含める（tests/make_fixtures.py の Builder に endnotes_extra、sample_structure.docx に脚注 id=5 と文末脚注 id=5・w:del の中の参照・customMarkFollows の文末脚注・「資料（授業プリント）」と続く 2 段落、
   test_notes.py・test_structure.py・test_ai.py・test_pdfmatch.py のテスト、docs/fix_plan_repro_tests.py の 2 つの PROBLEM テストの期待を逆にして tests/ に取り込む）。ルート2 は extract_pages の差し替えで。
5. 合格の条件: pytest すべて合格、golden は sample_structure 系と意図した変化だけ、td1〜3 では本文の文字・ほかの要素が 0.23.1 と同じで、不変性・DTD 合格、画像の出力漏れが増えない。td1〜3 に文末脚注・資料があるかを設計の段階で確かめる（文字は書き写さない）。
6. 残る限界と、利用者に確かめてもらうこと（J-STAGE の試験登載での文末脚注の番号の表示など。DEVELOPMENT の「残っている課題」）。
設計書は、関数ごとの変更点まで書く（実装の担当が迷わないように）。独立の反例の担当（oracle）とは相談しない。`, { label: 'design', phase: 'Design', schema: DESIGN_SCHEMA, model: 'opus', effort: 'high' }),
  () => agent(`${COMMON}
## 担当: 実装を見ない反例（oracle_e）
あなたは実装を見ない担当です。設計書 ${E}/DESIGN_E.md と、structure.py の attach_word_notes・build_front_en・build_back の中身、ai_assist.py の role_overrides の中身は読まない（期待が実装に引きずられないように）。
読んでよいもの: FIX_PLAN の E の節・N6・D4・D3・決定事項 7・8・付録の D3・D4、DESIGN.md、docs/fix_plan_repro_tests.py、tests/make_fixtures.py の部品（Builder・para・tail・run・drawing と make_doc の書き方）、tests/test_notes.py・tests/test_structure.py の確かめ方、
tests/test_ai.py の模擬の回答の書き方、XML の出力（fn-group・xref・app-group・trans-abstract の形）。
FIX_PLAN の E と決定事項 7・8 だけから、架空の文字で、原稿（docx）と期待（XML の fn-group の注の数と順、本文の xref の rid と番号の文字、除外の記録、資料の領域〈app-group/app/title〉と trans-abstract の中身、
不変性チェックの合否、要確認の知らせの有無、AI の set_role の採否）の組を 15〜30 件作り、${E}/oracle/ に置く。docx は make_fixtures.py の部品を import して作る（make_fixtures.py 自体は変えない。文末脚注は docs/fix_plan_repro_tests.py のように zip を書き換えて足すか、
自分の生成器 ${E}/oracle/gen_e.py に書く）。範囲:
- 文末脚注だけ／脚注だけ／両方（本文の参照順が入れ違う、脚注 id と文末脚注 id が同じ 5 で衝突）／脚注の中から文末脚注を参照／参照が w:del の中／参照されていない脚注・文末脚注（文字あり・空白だけ）／文末脚注の中の空白だけの段落／customMarkFollows の文末脚注。
- 資料の見出し: 「資料（授業プリント）」「資料Ⅰ　授業プリント」「資料Ⅱ（ワークシート）」「付録①　調査票」「資料1-2　…」「【資料1】」「Appendix A」「資料」だけの行／認識しない「資料を配布した。」「資料-1」／英文要旨の後に章見出しのスタイルの段落／
  英文要旨の中に和文の段落／引用文献の後ろの資料（暫定: 警告だけ。期待は「どちらか」）。
- AI の set_role: 英文要旨の段落に app_heading → 資料が始まる、英文題目に app_heading → 不採用、注の段落に p/exclude → 不採用（理由あり）、図形の段落（float_id）→ 不採用。
期待は、FIX_PLAN の方針から一つに決まるものだけ「exact」にし、決めかねるものは「どちらか」（許される結果を列挙）にする。期待と実際を比べる道具 ${E}/oracle/run_e.py を書く（指定した src で変換し、ケースごとに OK/FAIL と理由を出す。
実行してよいのは自分の道具と python -m jasme_jats と jasme_jats の公開 API〈convert・Options〉だけ）。作業ツリーの今の src（0.23.1 の動き）で流し、結果を base_result に書く（期待どおりでないのが E で直すもの）。
新しい架空の文字が実際の論文（tests/private）の文字と 12 文字以上一致しないことを確かめる。`, { label: 'oracle_e', phase: 'Design', schema: ORACLE_SCHEMA, model: 'opus', effort: 'high' }),
])
log(`design: ${design ? 'ok' : '失敗'} / oracle: ${oracle ? 'ok' : '失敗'}`)

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 実装（impl）
${E}/DESIGN_E.md（設計書）を読み、作業ツリーの src に実装する。設計書に書かれていないことで決める必要が出たら、FIX_PLAN の E の方針と原則に沿って決め、deviations に書く。
テストは設計書の計画どおり tests/make_fixtures.py（Builder の endnotes_extra・make_structure の追加。既存のほかの fixture は作り直さない）・tests/test_notes.py・tests/test_structure.py・tests/test_ai.py・tests/test_pdfmatch.py などに足す。
足したテストが 0.23.1 の src（${E}/base0231_src。sh ${S}/fixB2r4/tools/pytest_src.sh ${E}/base0231_src python <テスト>）で落ちることを確かめる。docs/fix_plan_repro_tests.py の 2 つの PROBLEM テストは、期待を逆にして tests/ に取り込み、元のファイルの冒頭の説明を直す。
独立の反例（${E}/oracle。run_e.py の使い方は報告のとおり）も流し、FAIL が残れば、期待が FIX_PLAN の方針に合っているかを確かめたうえで、実装の誤りなら直し、期待の誤りなら理由を書く（反例のファイルは変えない）。
docs/DESIGN.md（注・領域の章）と docs/DEVELOPMENT.md（コードの構成・残っている課題）を実装に合わせる（版・ノートブック・FIX_PLAN・README は仕上げの担当）。pytest（3.13・3.10）・ruff・golden・td1〜3 を流す。
文書とコードの食い違いを見つけたら、コードに合わせて直し、deviations に列挙する。
設計の担当の報告:
${JSON.stringify(design, null, 1)}
実装を見ない担当の報告:
${JSON.stringify(oracle, null, 1)}`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、設計書の合格の条件と物差し（pytest 3.13・3.10、ruff、golden〈23 件の違いを本体の diff で 1 つずつ確かめる〉、td1〜3 を 0.23.1 と比べる〈注の数と番号、資料の領域、本文の文字が同じこと、不変性・DTD・J-STAGE のチェック、画像の出力漏れ〉、
独立の反例 ${E}/oracle の run_e.py）で測る。自分でも架空の docx を 5 件ほど作り（脚注と文末脚注の参照が入れ違う順、注の中からの参照、資料の見出しの揺れ）、XML の fn-group・xref・app-group を目で確かめる。
ルート2（--route pdf。出版版 PDF がなければ extract_pages を差し替えるテストの形）で、文末脚注の番号の表と 13 章の表記が利用者に分かるかも見る。
ファイルは変更しない（実験は ${E}/verify/ の下）。問題は severity を付けて problems に書く。文書とコードの食い違いを見つけたら problems（nit）に書く。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify', phase: 'Verify', schema: VERIFY_SCHEMA, model: 'opus', effort: 'high' })
let pre = null
if (verify && (verify.problems || []).some(p => p.severity !== 'nit')) {
  pre = await agent(`${COMMON}
## 担当: 確かめで見つかった問題を直す（fix_verify）
次の問題のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。直した後、pytest 3.13・3.10・ruff・golden・td1〜3・独立の反例を流し直す。
問題:
${JSON.stringify(verify.problems, null, 1)}
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'fix_verify', phase: 'Verify', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })
}

phase('Finalize')
const fin = await agent(`${COMMON}
## 担当: 仕上げ（finalize）
1. 版を 0.24.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md: 反映の順序の表の E を「（実装済み）」にし、E の節に、設計の要点・テスト・実装で決めたこと・暫定の判断（決定事項 8(b) は警告だけ、customMarkFollows の文末脚注は脚注と同じ扱い。利用者に確かめてもらう）・確かめた数・残る限界・
   文書とコードの食い違いの扱いを書く。N6・D4・D3 の行は実装に合わせて必要なら書き直す。「同じファイルを触る順と、既存テストの書き換え」の節に E で触ったファイルを入れる。決定事項 8 に暫定の判断を「（暫定。2026-10-26）」として追記する。
3. docs/DESIGN.md、docs/DEVELOPMENT.md、README.md（利用者向けの説明に、Word の文末脚注が注として出ること、資料の見出しの認識が広がったことを短く）、docs/STYLE_MAPPING.md（資料の見出しの書き方があれば）、docs/fix_plan_repro_tests.py の冒頭の説明が実装と合うか確かめて直す。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる（tests/private の docx の文字から作った 12 文字の並びと、足した行を突き合わせる）。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', model: 'opus', effort: 'max', text: `原則と文字の不変性: 注の番号付けと資料の領域の変更で、docx の文字が XML から落ちる・二重に出る・別の場所に入る経路、除外の記録の漏れ（参照されていない注・空白だけの段落・w:del の中の参照）、
Emitter.span() を通さない文字、文字列を書き換えるコードがないか。脚注 id と文末脚注 id の衝突で xref の rid が入れ違わないか。注の中からの参照・除外された段落の中の参照の番号。ルート2（pdfdocx）で文末脚注の段落が docx の修正の対象になるときの文字ポリシー。
実験で、架空の docx（${E}/oracle のものと自分で作るもの）と td1〜3 で、不変性チェック・lost_images・DTD を確かめる。` },
  { key: 'regression', model: 'opus', effort: 'high', text: `回帰とテスト: pytest 3.13・3.10、ruff、golden（23 件の違いを本体の diff で確かめ、意図した変化だけか）、td1〜3 を 0.23.1 と比べる（注・資料以外に違いがないか）、独立の反例 ${E}/oracle。
足したテストが 0.23.1 で落ちるか。新しい規則（RE_APPENDIX の範囲・通し番号・set_role_problem の拒否）を外す・弱めるとテストが落ちるか。既存の sample_notes・sample_edge の期待（「注 1（うち Word の脚注 1）」など）が保たれているか。` },
  { key: 'user', model: 'opus', effort: 'high', text: `利用者への見え方と文書: レポートの 8 章・10 章・13 章・冒頭・14 章、Colab の赤い枠、CLI の文言が、技術に詳しくない編集委員に「何が起きて、どこを見て、何をするか」分かるか（文末脚注が注になったこと、リンクのない注、資料と英文要旨の境、和文の段落が英文要旨にあること）。
依頼文（AI依頼文.txt）の注の一覧の表記と app_heading の説明がチャットの AI に伝わる形か。README・DESIGN・DEVELOPMENT・FIX_PLAN（E の節・N6・D4・D3・反映の順序の表・決定事項 8 の暫定）が実装と合っているか。版が 0.24.0 にそろい、ノートブックが作り直されているか。
td1〜3 のレポートを実際に読む。実際の論文の文字がコミットされる場所に入っていないか。` },
]
const reviewOf = (l, extra, opts) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 E の実装を厳しく点検する。ファイルは変更しない（実験は ${E}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.23.1 との比較を evidence に書く）。blocking は原則違反（文字の脱落・重複・別の場所への混入、画像の出力漏れ、除外の記録漏れ、注の番号・リンクの誤り）・
テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.23.1 にもあって E で悪くなっていないものは、新しく見つけたものだけ nit にする。
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
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書とコードの食い違いは、コードに合わせて文書を直す）。FIX_PLAN の E の方針と原則の範囲で直す。
直した後、pytest 3.13・3.10・ruff・golden・td1〜3・独立の反例を流し直す。必要なら文書・ノートブックも合わせる。
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
