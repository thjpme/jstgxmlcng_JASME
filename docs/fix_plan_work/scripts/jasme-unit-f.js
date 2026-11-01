export const meta = {
  name: 'jasme-unit-f',
  description: '単位 F（0.25.0）: 文字だけのテキストボックス（囲み）と、本文の外に結び付いた図形（D1・N7）。設計と独立の反例 → 実装 → 確かめ → 仕上げ → 3 観点の点検 → 修正と再点検（最大 3 回）',
  phases: [
    { title: 'Design', detail: '設計書 DESIGN_F.md（Opus high）と、実装を見ない担当の架空の docx・期待（Opus high）' },
    { title: 'Implement', detail: '設計どおりに実装し、テストを足す（Opus max）' },
    { title: 'Verify', detail: '物差し（pytest・golden・td1〜3）と、独立の反例での確かめ（Opus high）' },
    { title: 'Finalize', detail: '版 0.25.0・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '原則（Opus max）・回帰（Opus high）・利用者向け（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus max）' },
    { title: 'Recheck', detail: '修正後の点検。原則（Opus max）・回帰（Opus high）' },
  ],
}

// args: { scratch: 作業用の場所 }
const S = args.scratch
const E = `${S}/f`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「F（0.25.0）: 文字だけのテキストボックス（囲み）と、本文の外に結び付いた図形（D1・N7）」を作るチームの一員です。
HEAD は main の 3157349（0.24.1。detached HEAD）。作業ツリーには、まとめ役の FIX_PLAN.md の小さな変更（決定事項 9(3)・10 の確認の追記）だけがあり、F の変更はコミットしていない差分として積む。
単位 B2.1（照合 pdfmatch.py の守り）は保留中で別の控えにある。F では pdfmatch.py の照合の規則には触らない（pdfdocx.paragraph_units / raw_paragraph_ids の文字ポリシーをテキストボックスで合わせる必要があれば、その箇所だけ）。
まず読むもの: docs/FIX_PLAN.md の「F」の節と項目の表の D1・N7、「利用者に決めてもらうこと」の 9・10 と決定事項 9・10、付録の D1（テストの一覧）、「毎回の共通作業」、
docs/DESIGN.md の読み取り（テキストボックス・図形）・浮動配置の図表（6.1）・AI 補完（5 章）・レポートの章、docs/DEVELOPMENT.md の「守るべき原則」、docs/fix_plan_repro_tests.py の test_PROBLEM_text_only_textbox_is_dropped_from_xml、
src/jasme_jats/model.py（Para.in_textbox・Table.in_textbox・Float・ImageRef・Document.textbox_excluded）、src/jasme_jats/docx_reader.py（テキストボックス・VML・グループ図形・wp:anchor / wp:inline の読み取り）、
src/jasme_jats/floats.py（at_anchor・estimate_top_left・Layout）、src/jasme_jats/structure.py（in_shape・TEXTBOX_TEXT_EXCLUDED と textbox_caption・place_floats・body_seq・assign_ids・compute_locations・node_paras・AFTER_BODY_REGIONS・float_decisions）、
src/jasme_jats/emit.py と builder.py（ノードの出力。boxed-text は JATS 1.1 の要素。同梱の DTD で確かめる）、src/jasme_jats/linker.py の body_paragraphs、
src/jasme_jats/ai_assist.py（PLACEMENT_SCHEMA・FIELD_GUIDE・MANUAL_EXAMPLE・manual_prompt・SYSTEM_PROMPT・set_role_problem〈E で作った〉・float_placements・_placement_problem）、
src/jasme_jats/report.py（PROVISIONAL の textbox・provisional_exclusions・actions()）、src/jasme_jats/pipeline.py（lost_images・actions の採用の一覧）、docs/JSTAGE_NOTES.md（boxed-text の記述があれば）、
tests/make_fixtures.py（textbox()・group()・drawing()・Builder・make_structure・make_float・make_float_text）、tests/test_structure.py・tests/test_floats.py・tests/test_ai.py・tests/test_lost_images.py。
FIX_PLAN に書かれた行番号（L557 など）は古い版のもので当てにならない。名前で探す。FIX_PLAN に出てくる rvz_d1.py・rvz_back.py（計画を作ったときの実験）はもう残っていない。付録の D1 の一覧と F の節の文面を正本にする。
F の内容（FIX_PLAN の F の節が正本。要点）:
- D1: 読み取りで model.TextBox（xid・anchor_src・float_id・inline・offset・大きさ）と Para.textbox_id / Table.textbox_id を記録する（入れ子の内側は外側の textbox_id を継ぐ。使われていない Document.textbox_excluded は削除）。
  floats.textbox_kind で、囲み（box）・図の注記（label）・決められない、を機械的に判定する（しきい値は、決定事項 9(3) のとおり tests/private/colab/td1〜3 で確かめて決める。td1・td2 の 276〜402 文字の 2 件ずつは囲み、td3 の 0〜数文字の 31 件は図に重ねた注記。
  文字数だけでなく、幅・位置〈画像の近く〉・行数などの組み合わせで決め、境界の例をテストにする）。BoxNode を <boxed-text> にする（本文の冒頭では <p> で包む。DTD に合うことを validate で確かめる）。AI は placements の kind box・label で指定する。
  反証で足すこと (1)〜(9): テキストボックスの段落への set_role は、float_id のない段落では fig_caption・table_caption・exclude だけを受け付け、ほかは「placements（kind box / label）で指定する」として拒否する（set_role_problem に規則を足す。SYSTEM_PROMPT も合わせる）。
  BoxNode を assign_ids（囲みの中の別行数式に FD の ID）・compute_locations・node_paras・linker.body_paragraphs・builder.nodes に足す。box・label の指定の Decision は plan.float_decisions[xid] に入れる（組み直した後に after が本文の段落でなければ指定なしに戻す）。
  plan.body_seq から textbox_id のある段落を除く。空白だけの段落はどの経路でも exclude_blank（中身が空白だけのテキストボックスは、囲みにも要確認にもしない）。place_boxes は doc.textboxes を回し、place_floats とは別のパスにする。
  幅を読めないとき（VML の pt 以外の単位）は幅の条件を使わない。near_image には浮動配置の画像（ImageRef.inline=False）も含める。FIELD_GUIDE と manual_prompt に box・label を足す。グループ図形の中の注記は今の扱い（図の後に p）のまま範囲外と明記する。
  決められないもの・位置を推定したものは Action（要確認）としてレポート・Colab・CLI に出す（report.actions() に足すだけ）。A の暫定の知らせ（PROVISIONAL の textbox・provisional_exclusions）は削除する。
- N7: アンカーが本文の外（引用文献・注・付記・謝辞・英文要旨。AFTER_BODY_REGIONS）にある図形の中身は、その領域の段落として扱わない。画像・キャプション・表を含むものは place_floats で「位置を決められない図表」にし（決定事項 10: AI を使わない設定では止める。B3 の置き場所の規則に従う）、
  文字だけのものは D1 の place_boxes で扱う。資料（app）の中の図形は今の扱い（資料の中に出す）を保つ。テキストボックスの外にあっても、引用文献などの段落そのものにある画像は、A の N1（lost_images）で要対応として知らせ続ける。
- 版は 0.25.0（XML に boxed-text が増え、図形の中身の行き先が変わるので 2 桁目）。
- まとめ役の暫定の判断（利用者にはまだ確かめていない。設計書と FIX_PLAN に「暫定」と明記する）: 画面（Colab・CLI）の文言・見え方は、利用者が後でまとめて直す方針なので、F では既存の形（赤い枠・手順 8・標準エラー）に Action を足すだけにし、表示の仕組みは変えない。
原則（CLAUDE.md・DEVELOPMENT.md「守るべき原則」）: docx の本文の文字を 1 文字も変えない。文字列を書き換えるコードを書かない（構造は LinkSpec か段落の役割で表す）。XML の段落の文字は Emitter.span() を通す。
出力しない段落は理由付きで記録し（plan.exclude()・exclude_blank()）、出力した段落を除外にも記録しない。XML に入らなかった画像は pipeline.lost_images() が検出する。
要対応・要確認の知らせは report.actions() に Action を足すだけ（個別の表示を render・colab・cli・make_notebook.py に足さない。単位 D の形）。
新しい docx の要素は、ooxml.canonical_text（検証）と docx_reader（変換）、ルート2 の pdfdocx.paragraph_units / raw_paragraph_ids を同じ文字ポリシーで直す。
利用者は技術に詳しくない編集委員なので、知らせの文言は、何が起きて、どこを見て、何をすればよいかを短く書く。
文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従い、文書の側を合わせる。見つけた食い違いは、直したものも直さなかったものも、報告（deviations か checked）にすべて列挙する。
実際の原稿: tests/private/colab/td1〜3（td1.docx〜td3.docx。コミットしない。文字を書き写さない。囲みと注記の実例があり、しきい値を決める根拠にする。幅・位置・文字数などの数値は記録してよいが、文字は記録しない）。
変換: cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml --route docx --ai manual --out <出力先>。0.24.1 の src の写しは ${E}/base0241_src（比べる相手）。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider。指定した src で本体のテストを流すのは sh ${S}/fixB2r4/tools/pytest_src.sh <src> <python> [引数]）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${E}/golden_base/manifest.json〈0.24.1〉と同じ名前の 23 件で比べる。
違ってよいのは、fixture に D1・N7 の要素を足した sample_structure 系と、意図した出力の変化（テキストボックスの文字が boxed-text に出る、A の暫定の知らせが消える、依頼文の書式）だけ。違いは本体を diff して 1 つずつ理由を書く）、
td1〜3 の変換（0.24.1 と XML・レポートを比べる。違ってよいのは F で意図したもの〈囲みが boxed-text に出る、注記の除外の理由、知らせ〉だけ。本文の文字はすべて同じ。不変性・最終・DTD・J-STAGE のチェックは合格。XML に入らなかった画像が増えない）、
ruff（ruff check src tests tools。HEAD より件数を増やさない）。
厳守:
- git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- python tests/make_fixtures.py をそのまま実行して既存の fixture を作り直さない（LibreOffice の版で sample_pdfcheck.pdf のバイト列が変わる）。sample_structure.docx に D1・N7 の要素を足すときは、make_fixtures.py の make_structure（と部品）を直し、
  その関数だけを呼んで作る（例: python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_structure('tests/fixtures/sample_structure.docx')"）。作り直した後に git diff --stat tests/fixtures で、意図した docx だけが変わったことを確かめる。
  AI 補完が必要になる docx（位置を決められない図形を含むもの）は ALL_DOCS に入れず、別の fixture にする（sample_b3_place の例）。新しい docx を足すなら make_<名前>() を足し、末尾の一覧（main）にも入れる。
- 実際の論文の本文（tests/private の docx の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る）。実験は ${E}/<担当名>/ の下に置く。tests/ に一時ファイルを残さない（tests/__pycache__ も消す）。
- ディスクの空きを df -h / で確かめ、3GB を切りそうなら自分の古い作業ファイルを消す。担当の最後に、大きな出力（docx・pdf・xml・zip・画像）を消す（結果の JSON・ログ・スクリプトは残す）。
- コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    design_doc: { type: 'string', description: `${E}/DESIGN_F.md のパス` },
    decisions: { type: 'string', description: 'D1・N7 ごとに決めたこと（textbox_kind のしきい値と根拠、boxed-text の出し方、place_boxes の置き場所、AI の kind box/label、set_role の規則、N7 の行き先、知らせの文言）と、決めなかったこと・却下した案・暫定の判断' },
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
    cases: { type: 'string', description: 'ケースごとの docx・期待（boxed-text の有無と位置、除外の理由、位置を決められない図表、知らせ、AI の指定の採否）の一覧' },
    runner: { type: 'string', description: '期待と実際を比べる道具の使い方' },
    base_result: { type: 'string', description: '0.24.1（作業ツリーの今の src）での結果' },
    notes: { type: 'string' },
  },
  required: ['dir', 'cases', 'runner', 'base_result', 'notes'],
}
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string', description: 'golden・td1〜3・独立の反例の結果（0.24.1 と並べる）' },
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
F の設計書 ${E}/DESIGN_F.md を書く（コードは変えない。試作は ${E}/design/ の下の写しで）。FIX_PLAN の F の節を正本として、次を決めて書く:
1. 読み取り: model.TextBox と Para/Table.textbox_id の形、docx_reader でどこから取るか（wps のテキストボックス、VML の v:textbox、wp:anchor / wp:inline、入れ子、グループ図形の中は範囲外）。大きさ・位置の単位の扱い（EMU・pt・読めないとき）。
2. floats.textbox_kind のしきい値: tests/private/colab/td1〜3 の文字だけのテキストボックス（td1・td2 の囲み 2 件ずつ、td3 の注記 31 件）の幅・高さ・文字数・行数・画像との距離・アンカーの位置を実際に測り（数値だけ記録。文字は書かない）、
   囲み（box）・注記（label）・決められない、の 3 つに分ける規則を決める。境界の例（幅が広く短い「（ヒント）」、画像の近くの 1 行）を挙げ、どれが「決められない」になるかを表にする。グループ図形の中の注記は範囲外。
3. BoxNode と <boxed-text> の出し方（本文の冒頭では <p> で包む。DTD で確かめる。中の段落・別行数式〈FD の ID〉・表の扱い）。place_boxes の置き場所の規則（アンカー段落の前か後か: 付録 D1 の (a) は前、(c) の inline は後。B3 の place_floats の置き方との整合）。
   plan.body_seq・compute_locations・node_paras・linker.body_paragraphs・builder.nodes・assign_ids の変更点。空白だけのテキストボックスの扱い。
4. AI: placements の kind に box・label を足す（PLACEMENT_SCHEMA・FIELD_GUIDE・MANUAL_EXAMPLE・manual_prompt・SYSTEM_PROMPT・float_placements・_placement_problem）。Decision を plan.float_decisions[xid] に入れ、採用の一覧に載せる。after が図形の中の段落・本文の外なら不採用。
   set_role_problem のテキストボックスの規則（float_id のない段落では fig_caption・table_caption・exclude だけ）。
5. N7: アンカーが本文の外にある図形の中身の行き先（画像・キャプション・表 → 位置を決められない図表、文字だけ → place_boxes、資料の中 → 今のまま）。B3 の N16・N17 の規則（本文の最後に置く・AI なしで止める）との関係。lost_images との役割分担。
6. 知らせ: 決められないもの・位置を推定したもの・N7 で位置を決められない図表にしたものを Action でどう出すか（key・level・文言）。A の暫定の知らせ（PROVISIONAL の textbox）を外す。レポートの 3 章・6 章の変更点。
7. テストの計画: 付録 D1 の一覧をすべて含める（make_fixtures.py の textbox_inline・vml_textbox の部品、sample_structure.docx に (a)〜(f)、tests/test_structure.py・test_floats.py・test_ai.py のテスト、floats.textbox_kind の境界の単体テスト、
   docs/fix_plan_repro_tests.py の PROBLEM テストの期待を逆にして tests/ に取り込む、点検で足したテストの一覧）。N7 の fixture（引用文献の段落に結び付いた、画像を含む図形と、文字だけの図形。AI 補完が必要になるなら ALL_DOCS に入れない）。
8. 合格の条件: pytest すべて合格、golden は sample_structure 系と意図した変化だけ、td1〜3 では td1・td2 の囲みが boxed-text で出て td3 の注記は理由付きで除外され、本文の文字・ほかの要素は 0.24.1 と同じで、不変性・DTD 合格、画像の出力漏れが増えない。
9. 残る限界と、利用者に確かめてもらうこと（J-STAGE の試験登載での boxed-text の表示など。DEVELOPMENT の「残っている課題」）。
設計書は、関数ごとの変更点まで書く（実装の担当が迷わないように）。独立の反例の担当（oracle）とは相談しない。`, { label: 'design', phase: 'Design', schema: DESIGN_SCHEMA, model: 'opus', effort: 'high' }),
  () => agent(`${COMMON}
## 担当: 実装を見ない反例（oracle_f）
あなたは実装を見ない担当です。設計書 ${E}/DESIGN_F.md と、structure.py の place_floats・textbox_caption の中身、floats.py の中身、ai_assist.py の float_placements・role_overrides の中身は読まない（期待が実装に引きずられないように）。
読んでよいもの: FIX_PLAN の F の節・D1・N7・決定事項 9・10・付録の D1、DESIGN.md、docs/fix_plan_repro_tests.py、tests/make_fixtures.py の部品（Builder・para・textbox・group・drawing・table と make_float・make_float_text・make_structure の書き方）、
tests/test_structure.py・tests/test_floats.py の確かめ方、tests/test_ai.py の模擬の回答の書き方、XML の出力（boxed-text・fig・p の形。同梱の DTD）。
FIX_PLAN の F と決定事項 9・10 だけから、架空の文字で、原稿（docx）と期待（XML に boxed-text が出るか・どの段落の前後か、除外の理由、位置を決められない図表になるか、要確認の知らせの有無、AI の placements kind box/label と set_role の採否、不変性チェックの合否）の組を 15〜30 件作り、
${E}/oracle/ に置く。docx は make_fixtures.py の部品を import して作る（make_fixtures.py 自体は変えない。足りない部品〈wp:inline のテキストボックス、VML の position:absolute、大きさの指定〉は自分の生成器 ${E}/oracle/gen_f.py に書く）。範囲:
- 幅の広い囲み（200〜400 文字。アンカー段落の前）／段落の末尾の inline の囲み（後）／画像の段落の近くの数文字の注記（v が負・小さい）／幅が広く短い「（ヒント）」（決められない）／VML だけの囲み／図キャプションを含むテキストボックス（今の扱いのまま）／
  空白だけのテキストボックス（何も出ない）／囲みの中の別行数式「(1)」と本文の「式(1)」／囲みの中に全角空白だけの段落／入れ子のテキストボックス／グループ図形の中の注記（範囲外。今のまま）。
- N7: 引用文献の段落に結び付いた、画像とキャプションを含む図形（AI なしでは止まる・手動モードでは位置を決められない図表として知らせる）／注の段落に結び付いた文字だけの図形（囲みか注記かの判定へ）／資料の中の図形（今のまま）／引用文献の段落そのものにある画像（lost_images のまま）。
- AI: 決められないものに kind box を指定 → 指定の段落の後の boxed-text、kind label → 除外、after に図形の中の段落 → 不採用。VML のキャプションへの set_role fig_caption → 採用、同じ段落への set_role p → placements を案内して拒否。
期待は、FIX_PLAN の方針から一つに決まるものだけ「exact」にし、しきい値に依存するものや決めかねるものは「どちらか」（許される結果を列挙）にする。期待と実際を比べる道具 ${E}/oracle/run_f.py を書く（指定した src で変換し、ケースごとに OK/FAIL と理由を出す。
実行してよいのは自分の道具と python -m jasme_jats と jasme_jats の公開 API〈convert・Options〉だけ）。作業ツリーの今の src（0.24.1 の動き）で流し、結果を base_result に書く（期待どおりでないのが F で直すもの）。
新しい架空の文字が実際の論文（tests/private）の文字と 12 文字以上一致しないことを確かめる。`, { label: 'oracle_f', phase: 'Design', schema: ORACLE_SCHEMA, model: 'opus', effort: 'high' }),
])
log(`design: ${design ? 'ok' : '失敗'} / oracle: ${oracle ? 'ok' : '失敗'}`)

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 実装（impl）
${E}/DESIGN_F.md（設計書）を読み、作業ツリーの src に実装する。設計書に書かれていないことで決める必要が出たら、FIX_PLAN の F の方針と原則に沿って決め、deviations に書く。
テストは設計書の計画どおり tests/make_fixtures.py（textbox_inline・vml_textbox の部品、make_structure の追加、N7 の fixture。既存のほかの fixture は作り直さない）・tests/test_structure.py・tests/test_floats.py・tests/test_ai.py・tests/test_lost_images.py などに足す。
足したテストが 0.24.1 の src（${E}/base0241_src。sh ${S}/fixB2r4/tools/pytest_src.sh ${E}/base0241_src python <テスト>）で落ちることを確かめる。docs/fix_plan_repro_tests.py の test_PROBLEM_text_only_textbox_is_dropped_from_xml は、期待を逆にして tests/ に取り込み、元のファイルの冒頭の説明を直す。
独立の反例（${E}/oracle。run_f.py の使い方は報告のとおり）も流し、FAIL が残れば、期待が FIX_PLAN の方針に合っているかを確かめたうえで、実装の誤りなら直し、期待の誤りなら理由を書く（反例のファイルは変えない）。
docs/DESIGN.md（読み取り・図形・浮動配置・AI・レポートの章）と docs/DEVELOPMENT.md（コードの構成・残っている課題）、docs/JSTAGE_NOTES.md（boxed-text の根拠。J-STAGE のマニュアルで確かめる）を実装に合わせる（版・ノートブック・FIX_PLAN・README は仕上げの担当）。pytest（3.13・3.10）・ruff・golden・td1〜3 を流す。
文書とコードの食い違いを見つけたら、コードに合わせて直し、deviations に列挙する。
設計の担当の報告:
${JSON.stringify(design, null, 1)}
実装を見ない担当の報告:
${JSON.stringify(oracle, null, 1)}`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、設計書の合格の条件と物差し（pytest 3.13・3.10、ruff、golden〈23 件の違いを本体の diff で 1 つずつ確かめる〉、td1〜3 を 0.24.1 と比べる〈td1・td2 の囲みが boxed-text に出ること、td3 の注記の除外、本文の文字が同じこと、不変性・DTD・J-STAGE のチェック、画像の出力漏れ〉、
独立の反例 ${E}/oracle の run_f.py）で測る。自分でも架空の docx を 5 件ほど作り（しきい値の境界の大きさ・文字数、画像の近くの短い囲み、引用文献に結び付いた図形）、XML の boxed-text・fig・除外の記録を目で確かめる。
手動モードの回答（kind box・label）を td1 の依頼文の段落 ID で作って流し、知らせが利用者に分かる文言かも見る。
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
1. 版を 0.25.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md: 反映の順序の表の F を「（実装済み）」にし、F の節に、設計の要点（しきい値とその根拠の数値）・テスト・実装で決めたこと・暫定の判断（利用者に確かめてもらう）・確かめた数・残る限界・
   文書とコードの食い違いの扱いを書く。D1・N7 の行は実装に合わせて必要なら書き直す。「同じファイルを触る順と、既存テストの書き換え」の節に F で触ったファイルを入れる。決定事項 9 にしきい値の実際の値を「（2026-11-01。F で決めた値）」として追記する。まとめ役の追記（決定事項 9(3)・10）は変えない。
3. docs/DESIGN.md、docs/DEVELOPMENT.md、README.md（利用者向けの説明に、囲みが boxed-text として出ること、図に重ねた注記は出ないこと、決められないものは要確認になること、本文の外に結び付いた図形の扱いを短く。A の暫定の知らせの説明を消す）、docs/JSTAGE_NOTES.md、docs/fix_plan_repro_tests.py の冒頭の説明が実装と合うか確かめて直す。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる（tests/private の docx の文字から作った 12 文字の並びと、足した行を突き合わせる）。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', model: 'opus', effort: 'max', text: `原則と文字の不変性: テキストボックスの中身を boxed-text に出す・注記として除外する・N7 で行き先を変える経路で、docx の文字が XML から落ちる・二重に出る・別の場所に入る経路、除外の記録の漏れ（注記・空白だけの段落・決められないもの）、
出力した段落を除外にも記録する矛盾、画像が XML に入らない経路（N7 の図形の画像、囲みの中の画像）、Emitter.span() を通さない文字、文字列を書き換えるコードがないか。入れ子・VML・グループ図形・inline の各形で確かめる。
実験で、架空の docx（${E}/oracle のものと自分で作るもの）と td1〜3 で、不変性チェック・lost_images・DTD を確かめる。` },
  { key: 'regression', model: 'opus', effort: 'high', text: `回帰とテスト: pytest 3.13・3.10、ruff、golden（23 件の違いを本体の diff で確かめ、意図した変化だけか）、td1〜3 を 0.24.1 と比べる（囲み・注記・知らせ以外に違いがないか。図表の位置と組み方〈B3〉、注〈E〉が変わっていないか）、独立の反例 ${E}/oracle。
足したテストが 0.24.1 で落ちるか。しきい値を動かす・条件を外すとテストが落ちるか（境界のテスト）。既存の VML のキャプションへの set_role fig_caption、sample_float・sample_b3 系の図形の扱いが保たれているか。` },
  { key: 'user', model: 'opus', effort: 'high', text: `利用者への見え方と文書: レポートの冒頭・3 章・6 章・14 章、Colab の赤い枠、CLI の文言が、技術に詳しくない編集委員に「何が起きて、どこを見て、何をするか」分かるか（囲みを boxed-text にしたこと、注記を出さなかったこと、決められないものと AI での指定の仕方、本文の外に結び付いた図形）。
依頼文（AI依頼文.txt）の kind box / label の説明がチャットの AI に伝わる形か。README・DESIGN・DEVELOPMENT・JSTAGE_NOTES・FIX_PLAN（F の節・D1・N7・反映の順序の表・決定事項 9 のしきい値）が実装と合っているか。版が 0.25.0 にそろい、ノートブックが作り直されているか。
td1〜3 のレポートを実際に読む（td1・td2 の囲みがどう出て、td3 の注記がどう知らされるか）。実際の論文の文字がコミットされる場所に入っていないか。` },
]
const reviewOf = (l, extra, opts) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status。まとめ役の FIX_PLAN の決定事項 9(3)・10 の追記は F の対象外）で、単位 F の実装を厳しく点検する。ファイルは変更しない（実験は ${E}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.24.1 との比較を evidence に書く）。blocking は原則違反（文字の脱落・重複・別の場所への混入、画像の出力漏れ、除外の記録漏れ、boxed-text の DTD 不合格）・
テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.24.1 にもあって F で悪くなっていないものは、新しく見つけたものだけ nit にする。
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
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書とコードの食い違いは、コードに合わせて文書を直す）。FIX_PLAN の F の方針と原則の範囲で直す。
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
