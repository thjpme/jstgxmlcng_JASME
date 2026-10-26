export const meta = {
  name: 'jasme-unit-b3',
  description: '単位 B3（0.22.0）: 位置を決められない図表の置き場所と、表で組んだ図の組み方（N15〜N19）。設計と独立の反例 → 実装 → 確かめ → 仕上げ → 3 観点の点検 → 修正と再点検（最大 4 回）',
  phases: [
    { title: 'Design', detail: '設計書 DESIGN_B3.md（Opus high）と、実装を見ない担当の架空の docx・模擬の AI 回答・期待（Opus high）' },
    { title: 'Implement', detail: '設計どおりに実装し、テストを足す（Opus max）' },
    { title: 'Verify', detail: '物差し（pytest・golden・td1〜3）と、独立の反例での確かめ（Opus high）' },
    { title: 'Finalize', detail: '版 0.22.0・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '原則（Opus max）・回帰（Opus high）・利用者向け（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus max）' },
    { title: 'Recheck', detail: '修正後の点検。原則（Opus max）・回帰（Opus high）' },
  ],
}

// args: { scratch: 作業用の場所（道具の中のパスと同じ。symlink で新しい場所に向く） }
const S = args.scratch
const B = `${S}/b3`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「B3（0.22.0）: 位置を決められない図表の置き場所と、表で組んだ図の組み方（N15〜N19）」を作るチームの一員です。
main とこのブランチ（claude/jstage-xml-converter-review-dw2f0u）の HEAD は 45d8314（0.21.0）。作業ツリーにはまとめ役の FIX_PLAN.md の小さな変更（決定事項 25・B2.1 の保留の記録）があり、
B3 の変更はその上にコミットしていない差分として積む。単位 B2.1 は保留中で、B3 とは独立（照合 pdfmatch.py には触らない）。
まず読むもの: docs/FIX_PLAN.md の「B3」の節と項目の表の N15〜N19、「利用者に決めてもらうこと」の 21・22 と決定事項 21・22、docs/DESIGN.md の 5 章（AI 補完）と 6.1（浮動配置の図表）、
docs/DEVELOPMENT.md の「守るべき原則」、src/jasme_jats/structure.py の place_floats・float_captions・float_mechanical・float_from_spec・assemble_floats・unplaced_floats、
src/jasme_jats/ai_assist.py の MANUAL_EXAMPLE・FIELD_GUIDE・manual_prompt・SYSTEM_PROMPT・PLACEMENT_SCHEMA・RESPONSE_SCHEMA・parse_response・float_placements・_placement_problem、
src/jasme_jats/floats.py、src/jasme_jats/pipeline.py の convert（手動モード・forced_floats・unresolved_after）、report.py・colab.py・cli.py の「本文の冒頭に仮に置いた」の文言、
tests/test_floats.py、tests/make_fixtures.py の make_float・make_float_text と textbox()・group()・table() の部品、tests/data/ai_response_sample_float.json。
B3 の内容（FIX_PLAN の B3 の節の「設計の方針」が正本。要点）:
- N15: AI の回答の書式で placements を回答の先頭に書かせる（依頼文の FIELD_GUIDE・MANUAL_EXAMPLE・manual_prompt、API の SYSTEM_PROMPT・RESPONSE_SCHEMA）。途中で切れた回答から、閉じている placements の要素だけを
  読み取れるかを検討する（読み取ったものも _placement_problem で確かめる）。JSON の読み取りの誤りが "Unterminated string" のときも「途中で切れている可能性があります」の案内を出す。
- N16: AI が注・引用文献などの本文の外の段落の後ろと答えた図表は、本文の冒頭に置くのをやめ、本文の最後に置いて要対応として知らせる（決定事項 21）。本文の外に図表を入れない規則は変えない。
- N17: AI でも位置を決められない図表は、アンカー段落のすぐ後ろに仮に置き、要対応として知らせる。アンカー段落が本文でなければ本文の最後（決定事項 21）。レポートの冒頭・3 章・14 章、Colab の枠、
  コマンドラインの表示の「本文の冒頭に仮に置いた」の文言を、置いた位置に合わせて直す。手動モードで AI の回答を貼り戻す前の出力も同じ置き方にする。
- N18: 表のセルに画像とキャプションが並ぶ図形は、AI なしでも機械的に図に組む（float_mechanical。セルの画像を図の本体、セルのキャプションを図のキャプション）。組み方が一つに決まらないときは今までどおり AI に任せる。
- N19: 画像のない図キャプションの直前にある、キャプションのない表は、その図の本体として組む（決定事項 22: fig の中の table-wrap）。組めないとき（表とキャプションの間にほかの段落がある、表にほかのキャプションが付いているなど）は要対応として知らせる。
- 版は 0.22.0（XML の図表の位置が変わるので 2 桁目）。テストは tests/make_fixtures.py に架空の文字で docx を足す（表のセルに画像とキャプションが並ぶ図形、画像のない図キャプションと直前の表、
  本文の外の段落に結び付いた図形）と、模擬の AI 回答（途中で切れた回答、注の後ろと答える回答、位置を答えない回答）。
原則（CLAUDE.md・DEVELOPMENT.md「守るべき原則」）: docx の本文の文字を 1 文字も変えない。文字列を書き換えるコードを書かない。XML の段落の文字は Emitter.span() を通す。出力しない段落は理由付きで記録し
（plan.exclude()・exclude_blank()）、出力した段落を除外にも記録しない。XML に入らなかった画像は pipeline.lost_images() が検出する。要対応・要確認の知らせ方（レポートの冒頭・14 章・Colab の枠・CLI）は既存の形に合わせる。
利用者は技術に詳しくない編集委員なので、知らせの文言は、何が起きて、どこを見て、何をすればよいかを短く書く。
実際の原稿: tests/private/colab/td1〜3（td1.docx・td2.docx に、位置を決められない図表がある。利用者が 2026-10-18 に「XML の冒頭に図表が来る」「図1 が表のように見える」と指摘した元のデータ。コミットしない。
文字を書き写さない）。変換: cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml --route docx --ai manual --out <出力先>
（模擬の AI 回答は --ai-response <JSON ファイル>。--ai none だと位置を決められない図表があると止まる）。0.21.0 の src の写しは ${S}/b21/base021_src（比べる相手）。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${S}/n10/golden_base/manifest.json〈0.20.0・0.21.0 と同じ〉と、
同じ名前の 19 件で比べる。違ってよいのは、位置を決められない図表の置き場所が変わる sample_float 系と、意図した出力の変化だけ。違いは本体を diff して 1 つずつ理由を書く）、
td1〜3 の変換（0.21.0 と XML・レポートを比べる。違ってよいのは B3 で意図した図表の位置・組み方・知らせの文言だけ。不変性・最終・DTD・J-STAGE のチェックは合格。XML に入らなかった画像が増えない）、
ruff（ruff check src tests tools）。
厳守:
- ブランチは claude/jstage-xml-converter-review-dw2f0u のまま。git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- pdfmatch.py・pdfdocx.py には触らない（B2.1 の保留中の作業と重ならないように）。
- python tests/make_fixtures.py をそのまま実行して既存の fixture を作り直さない（既存の docx のバイト列が変わると golden が崩れる）。新しい docx は、make_fixtures.py に make_<名前>() を足し、
  その関数だけを呼んで作る（例: python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_b3_xxx('tests/fixtures/sample_b3_xxx.docx')"）。
  make_fixtures.py の末尾の一覧（main）にも新しい関数を足す。tests/conftest.py の ALL_DOCS に新しい docx が入るなら、golden の件数が増える（19 件の比べ方は上のとおり）。
- 実際の論文の本文（tests/private の docx の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る）。実験は ${B}/<担当名>/ の下に置く。tests/ に一時ファイルを残さない（tests/__pycache__ も消す）。
- ディスクの空きが少ない（df -h / で確かめる。3GB を切りそうなら自分の古い作業ファイルを消す）。担当の最後に、大きな出力（docx・pdf・xml・zip・画像）を消す（結果の JSON・ログ・スクリプトは残す）。
- コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    design_doc: { type: 'string', description: `${B}/DESIGN_B3.md のパス` },
    decisions: { type: 'string', description: 'N15〜N19 ごとに決めたこと（置き場所の規則、組み方の条件、回答の書式、途中で切れた回答の扱い、知らせの文言）と、決めなかったこと・却下した案' },
    changes: { type: 'string', description: 'ファイル・関数ごとの変更点' },
    tests: { type: 'string', description: 'テストの計画（fixture の docx・模擬の AI 回答・確かめること）' },
    acceptance: { type: 'string', description: '合格の条件（物差しごと。golden・td1〜3 で変わってよいもの）' },
    risks: { type: 'string' },
  },
  required: ['design_doc', 'decisions', 'changes', 'tests', 'acceptance', 'risks'],
}
const ORACLE_SCHEMA = {
  type: 'object',
  properties: {
    dir: { type: 'string', description: '架空の docx・模擬の回答・期待を置いた場所' },
    cases: { type: 'string', description: 'ケースごとの docx・回答・期待（置き場所・組み方・知らせ）の一覧' },
    runner: { type: 'string', description: '期待と実際を比べる道具の使い方' },
    base_result: { type: 'string', description: '0.21.0（作業ツリーの今の src）での結果' },
    notes: { type: 'string' },
  },
  required: ['dir', 'cases', 'runner', 'base_result', 'notes'],
}
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string', description: 'golden・td1〜3・独立の反例の結果（0.21.0 と並べる）' },
    deviations: { type: 'string', description: '設計と違えたこと・直さなかった指摘と理由' }, open_issues: { type: 'string' },
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
    checked: { type: 'string', description: '何をどう確かめたか。指摘がなくても書く' },
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
B3 の設計書 ${B}/DESIGN_B3.md を書く（コードは変えない。試作は ${B}/design/ の下の写しで）。FIX_PLAN の B3 の「設計の方針」を正本として、次を決めて書く:
1. N17・N16 の置き場所の規則を、構造の組み立て（place_floats の inserts・front）でどう実現するか。アンカー段落のすぐ後ろ（= その段落の直後。アンカー段落が本文の段落でないときの「本文の最後」の定義: 本文の領域の最後の要素の後ろ）。
   同じ位置に複数の図表が来るときの順（キャプションの番号順。既存の float_number）。手動モードで回答を貼り戻す前の出力も同じ。plan.unplaced_floats・forced_floats・unresolved_after・レポート（冒頭・3 章・14 章）・Colab の枠・CLI の文言の変更点。
   「本文の最後」に置いた図表と、アンカー段落の後ろに置いた図表で、知らせの文言を分けるか。
2. N15: 回答の書式で placements を先頭にする変更（MANUAL_EXAMPLE・FIELD_GUIDE・manual_prompt の本文・SYSTEM_PROMPT・RESPONSE_SCHEMA の順。API のスキーマは順を保証しないので、依頼文の指示で先頭に書かせる）。
   途中で切れた JSON から閉じている placements の要素だけを読む案を検討し、採るか否かと理由（採るなら、推測で直すのではなく「閉じた要素だけを読む」範囲を厳密に決め、読めた要素も _placement_problem で検証し、途中で切れたことを利用者に知らせる）。
   "Unterminated string" の案内。
3. N18: float_mechanical で、表のセルに画像とキャプションが並ぶ図形（表 1 つ、セルに画像の段落とキャプションの段落）を図に組む条件（一意に決まるとき: 画像のセルが 1 つ以上、図キャプションが 1 つ。表キャプションが混ざる・複数の図キャプション・画像のないセルに文字があるなど一意でないときは None）。
   セルの画像を図の本体にし、表そのものは出さない（表の構造は捨ててよいか: セルの文字がキャプション以外にあるときは組まない、で守る）。既存の決定（図の中の画像と文字が同じ段落のときの扱い）との整合。
4. N19: assemble_floats で、画像のない図キャプションの直前（キャプションの上に表があるか、下にあるかは原稿で揺れる: 既存の captions_below の判定と同じ考えで決める）にキャプションのない表があれば、FigNode の tables に入れる。
   組めないときの要対応の知らせ（既存の「図キャプションに対応する画像が見つからない」の判断をどう変えるか）。
5. テストの計画: make_fixtures.py に足す docx（架空の文字。各ケースの構造）、模擬の AI 回答（途中で切れた JSON、注の後ろ〈引用文献・注の段落 ID〉と答える回答、位置を答えない回答、placements が先頭の回答）、確かめること。
6. 合格の条件: pytest すべて合格、golden は sample_float 系の意図した変化だけ、td1〜3 では位置を決められない図表がアンカー段落の後ろに来て、本文の文字・ほかの要素は 0.21.0 と同じ、不変性・DTD 合格、画像の出力漏れが増えない。
   利用者が 2026-10-18 に指摘した「XML の冒頭に図表が来る」「図1 が表のように見える」が td1・td2 でどう変わるかを、設計の段階で td1・td2 を変換して確かめる（0.21.0 の出力と比べる。文字は書き写さない）。
7. 残る限界（ページ・段の区切りを考慮しない推定、AI の回答の形は試験運用で確かめる、など）。
設計書は、関数ごとの変更点まで書く（実装の担当が迷わないように）。独立の反例の担当（oracle）とは相談しない。`, { label: 'design', phase: 'Design', schema: DESIGN_SCHEMA, model: 'opus', effort: 'high' }),
  () => agent(`${COMMON}
## 担当: 実装を見ない反例（oracle_b3）
あなたは実装を見ない担当です。設計書 ${B}/DESIGN_B3.md と、structure.py の place_floats・float_mechanical・assemble_floats の中身は読まない（期待が実装に引きずられないように）。
読んでよいもの: FIX_PLAN の B3 の節・N15〜N19・決定事項 21・22、DESIGN.md 5 章・6.1、ai_assist.py の回答の書式（MANUAL_EXAMPLE・FIELD_GUIDE・PLACEMENT_SCHEMA）、tests/make_fixtures.py の部品（textbox・group・table・para・drawing・Builder）と
make_float・make_float_text の書き方、tests/test_floats.py の確かめ方（body_sequence・after）、tests/data/ai_response_sample_float.json。
FIX_PLAN の B3 と決定事項 21・22 だけから、架空の文字で、原稿（docx）・模擬の AI 回答・期待（XML の本文の中でその図表がどこに来るか、何として組まれるか、要対応の知らせが出るか）の組を 15〜30 件作り、
${B}/oracle/ に置く。docx は make_fixtures.py の部品を import して作る（make_fixtures.py 自体は変えない。自分の生成器 ${B}/oracle/gen_b3.py に書く）。範囲:
- 位置を決められない図表（アンカー段落から離れたテキストボックス・グループ図形）× AI の回答なし（--ai manual で回答を貼る前）／位置を答えない回答／注・引用文献の後ろ（本文の外の段落 ID）と答える回答／本文の段落を正しく答える回答／途中で切れた回答（placements が先頭で閉じている要素 1 つ＋切れた要素、
  placements が末尾で切れている、文字列の途中で切れている）。アンカー段落が本文の段落・注の段落・引用文献の段落・和文の冒頭の段落の各場合。同じ段落に複数の図表が結び付く場合（番号順）。
- 表のセルに画像とキャプションが並ぶ図形（1 セル、2 セル横並び、画像のセルとキャプションのセルが別の行、表キャプションが混ざる、キャプションのないセルの文字がある〈組めない〉）。
- 画像のない図キャプションの直前にキャプションのない表（キャプションが表の下／上、表とキャプションの間に本文の段落がある〈組めない〉、表に表キャプションが付いている〈組めない〉、表の後ろに画像の段落もある）。
期待は、FIX_PLAN の方針から一つに決まるものだけ「exact」にし、決めかねるものは「どちらか」（許される結果を列挙）にする。期待と実際（XML の本文の要素の並びと、レポートの要対応の有無・文言の要点）を比べる道具 ${B}/oracle/run_b3.py を書く
（指定した src で変換し、ケースごとに OK/FAIL と理由を出す。実行してよいのは自分の道具と python -m jasme_jats だけ）。作業ツリーの今の src（0.21.0 の動き）で流し、結果を base_result に書く（期待どおりでないのが B3 で直すもの）。
新しい架空の文字が実際の論文（tests/private）の文字と 12 文字以上一致しないことを確かめる。`, { label: 'oracle_b3', phase: 'Design', schema: ORACLE_SCHEMA, model: 'opus', effort: 'high' }),
])
log(`design: ${design ? 'ok' : '失敗'} / oracle: ${oracle ? 'ok' : '失敗'}`)

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 実装（impl）
${B}/DESIGN_B3.md（設計書）を読み、作業ツリーの src に実装する。設計書に書かれていないことで決める必要が出たら、FIX_PLAN の B3 の方針と原則に沿って決め、deviations に書く。
テストは設計書の計画どおり tests/make_fixtures.py（新しい docx の関数。既存の fixture は作り直さない）・tests/data（模擬の AI 回答）・tests/test_floats.py などに足す。足したテストが 0.21.0 の src（${S}/b21/base021_src。pytest_src.sh は ${S}/fixB2r4/tools/pytest_src.sh）で落ちることを確かめる。
独立の反例（${B}/oracle。run_b3.py の使い方は報告のとおり）も流し、FAIL が残れば、期待が FIX_PLAN の方針に合っているかを確かめたうえで、実装の誤りなら直し、期待の誤りなら理由を書く（反例のファイルは変えない）。
docs/DESIGN.md 6.1・5 章と docs/DEVELOPMENT.md（コードの構成・残っている課題）を実装に合わせる（版・ノートブック・FIX_PLAN は仕上げの担当）。pytest（3.13・3.10）・ruff・golden・td1〜3 を流す。
設計の担当の報告:
${JSON.stringify(design, null, 1)}
実装を見ない担当の報告:
${JSON.stringify(oracle, null, 1)}`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、設計書の合格の条件と物差し（pytest 3.13・3.10、ruff、golden〈19 件の違いを本体の diff で 1 つずつ確かめる〉、td1〜3 を 0.21.0 と比べる〈位置を決められない図表の置き場所、組み方、要対応の文言、本文の文字が同じこと、
不変性・DTD・J-STAGE のチェック、画像の出力漏れ〉、独立の反例 ${B}/oracle の run_b3.py）で測る。模擬の AI 回答（途中で切れたもの・注の後ろと答えるもの・位置を答えないもの）を td1・td2 の依頼文の段落 ID で作って流し、知らせが利用者に分かる文言かも見る。
ファイルは変更しない（実験は ${B}/verify/ の下）。問題は severity を付けて problems に書く。
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
1. 版を 0.22.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md: 反映の順序の表の B3 を「（実装済み）」にし、B3 の節に、設計の要点・テスト・実装で決めたこと・確かめた数・残る限界を書く。N15〜N19 の行は実装に合わせて必要なら書き直す。
   「同じファイルを触る順と、既存テストの書き換え」の節に B3 で触ったファイルを入れる。決定事項 25・B2.1 の保留の記録（まとめ役が書いたもの）は変えない。
3. docs/DESIGN.md 6.1・5 章、docs/DEVELOPMENT.md、README.md（利用者向けの説明に、位置を決められない図表の置き場所が変わったことを短く）、docs/fix_plan_repro_tests.py の冒頭の説明が実装と合うか確かめて直す。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる（tests/private の docx の文字から作った 12 文字の並びと、足した行を突き合わせる）。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', model: 'opus', effort: 'max', text: `原則と文字の不変性: 置き場所と組み方の変更で、docx の文字が XML から落ちる・二重に出る・別の場所に入る経路、除外の記録の漏れ、画像が XML に入らない経路、
Emitter.span() を通さない文字、文字列を書き換えるコードがないか。表のセルの画像を図の本体にしたときにセルの文字が落ちないか。途中で切れた回答の読み取りが、推測で直す形になっていないか。
実験で、架空の docx（${B}/oracle のものと自分で作るもの）と td1・td2 で、不変性チェック・lost_images・DTD を確かめる。` },
  { key: 'regression', model: 'opus', effort: 'high', text: `回帰とテスト: pytest 3.13・3.10、ruff、golden（19 件の違いを本体の diff で確かめ、意図した変化だけか）、td1〜3 を 0.21.0 と比べる（図表の位置・組み方・文言以外に違いがないか）、
独立の反例 ${B}/oracle。足したテストが 0.21.0 で落ちるか。新しい規則（N18 の組む条件・N19 の条件・N17 の置き場所）を外す・弱めるとテストが落ちるか。` },
  { key: 'user', model: 'opus', effort: 'high', text: `利用者への見え方と文書: レポートの冒頭・3 章・14 章、Colab の赤い枠、CLI の文言が、置いた位置と合っていて、技術に詳しくない編集委員が「どこを見て何をするか」分かるか。
依頼文（AI依頼文.txt）の書き方の変更が、チャットの AI に伝わる形か（placements を先頭に）。README・DESIGN・DEVELOPMENT・FIX_PLAN（B3 の節・N15〜N19・反映の順序の表）が実装と合っているか。
版が 0.22.0 にそろい、ノートブックが作り直されているか。td1・td2 のレポートを実際に読み、2026-10-18 の利用者の指摘（XML の冒頭に図表が来る、図1 が表のように見える）がどう変わったかを確かめる。実際の論文の文字がコミットされる場所に入っていないか。` },
]
const reviewOf = (l, extra, opts) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status。まとめ役の FIX_PLAN の決定事項 25・B2.1 の保留の記録の変更は B3 の対象外）で、単位 B3 の実装を厳しく点検する。ファイルは変更しない（実験は ${B}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.21.0 との比較を evidence に書く）。blocking は原則違反（文字の脱落・重複・別の場所への混入、画像の出力漏れ、除外の記録漏れ）・
テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.21.0 にもあって B3 で悪くなっていないものは、新しく見つけたものだけ nit にする。問題がなければ findings は空でよい（checked に何を確かめたかを書く）。
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
${round === 1 ? '前回（この担当の 1 回目の試み）は、使用量の上限で途中で止まった。作業ツリーには途中の変更が残っている（should 1「ルート2 の照合で N18・N19 のセルの段落をどう扱うか」の判断、should 2「assemble_floats が同じ差し込みの位置の要素だけを組にする」、should 3「float_mechanical の cells が None のときは 0.21.0 の経路を保つ」のうち、前の担当の作業の記録では should 2・3 は終わり、should 1 の判断の途中で止まった。nit と物差しの流し直し・文書はまだ）。まず git diff と git status で、仕上げの担当が終えた状態（控え e485ad7 の内容）からの変更を確かめ、途中の変更を引き継ぐか、やり直すかを決めてから進める。\n' : ''}次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ。FIX_PLAN の B3 の方針と原則の範囲で直す。${round >= 3 ? '\n利用者の決まり（2026-10-26）: 文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従って直す（文書の側を合わせる）。見つけた食い違いは、直したものも直さなかったものも、報告の deviations（点検なら findings の nit か checked）にすべて列挙する。' : ''}
直した後、pytest 3.13・3.10・ruff・golden・td1〜3・独立の反例を流し直す。必要なら文書・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })
  phase('Recheck')
  const RE = [LENSES[0], LENSES[1]]
  const rr = await parallel(RE.map(l => () => reviewOf(l, `${round} 回目の修正の後の点検。直した指摘が本当に直ったか（再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。${round >= 2 ? '\n利用者の決まり（2026-10-26）: 文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従って直すのが決まり。見つけた食い違いは、直したものも直さなかったものも、報告の deviations（点検なら findings の nit か checked）にすべて列挙する。' : ''}
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
