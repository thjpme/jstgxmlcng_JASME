export const meta = {
  name: 'jasme-unit-b21',
  description: '単位 B2.1（0.21.1）: B2 で残った分断された段落の端のまれな配置の誤り（N20）を、一般的な守りの 3 案を試作・反証で比べて選び、実装・確かめ・点検で収束させる',
  phases: [
    { title: 'Design', detail: '一般的な守りの 3 案の試作（max）と、実装を見ない反例集（high）' },
    { title: 'Judge', detail: '同じ物差しで測り直し、反証で選ぶ（max）' },
    { title: 'Implement', detail: '選んだ案を本体に入れる（max）' },
    { title: 'Verify', detail: '物差しすべてと td1〜3（high）' },
    { title: 'Finalize', detail: '版 0.21.1・文書・FIX_PLAN・ノートブック（medium）' },
    { title: 'Review', detail: '原則・回帰（max）、利用者向け（high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（max）' },
    { title: 'Recheck', detail: '修正後の点検（max）' },
  ],
}

const S = args.scratch
const O = `${S}/oracle`
const B = `${S}/b21`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール）で、修正計画 docs/FIX_PLAN.md の単位「B2.1（0.21.1）」を作るチームの一員です。
main とこのブランチ（claude/jstage-xml-converter-review-dw2f0u）は 45d8314（0.21.0。単位 B2 を反映済み）。0.21.0 の src の写しは ${B}/base021_src、0.20.0 は ${S}/n10/judge/base_src。
まず docs/FIX_PLAN.md の「B2」「B2.1」の節（とくに B2.1 の「4 回目の点検で残った指摘」と「設計の方針」）、docs/DESIGN.md 4.4、src/jasme_jats/pdfmatch.py の冒頭と _Joint・_classify を読む。
単位 B2 の 4 回の点検の結果は ${S}/b2_review/（review_*・recheck*_*・fix*_result.json、workflow_final.json の remaining が残った 6 件）。
B2.1 の目的: B2 で、分断された段落の端の 1 行と、すぐ隣の図・表の中の行・キャプション・ほかの段落がよく似ているまれな配置で、図の中の文字を足す・本当の校正の直しを直さない・
docx にも PDF にもない文字にする誤りが、点検のたびに別の形で見つかり、個別の規則（_loose_edge・stray_edge・figure_edge_lines・facing_hole・better_line など）の追加では収束しなかった。
これを、個別の形の継ぎはぎではなく、原則（決められない違いは docx のまま残し、理由を付けて 13 章に出す）に沿った一般的な守りで止める。
原則（CLAUDE.md）: XML の本文は出版版 PDF の本文と 1 文字も違ってはいけない。ルート2 は docx の文字を PDF に合わせて直すが、組版の文字、docx にない図・表の中の文字、ほかの段落の文字を
docx に足してはいけない。PDF の本文にある docx の文字を消してはいけない。決められない違いは docx のまま残し、13 章に出す。docx を直すのは pdfdocx.py だけ。
守りの代償: 本当の校正の直しの一部が「直さなかった箇所」（13.2）に回ると、利用者（技術に詳しくない編集委員）が手で確かめる箇所が増える。物差しでは、原則違反（足す・消す・黙った違い）を
減らすことを第一に、13.2 に回る本当の直しの数（本誌の出版版 PDF・td1〜3・乱数の例）も測って、増えすぎない案を選ぶ。
物差しの道具（作業用の場所。使い方は各ファイルの冒頭か ${S}/n10/DESIGN_N10.md 2 章）:
- pytest: python -m pytest -q（3.13）、PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider（3.10）。別の src を測るときは ${S}/n10/judge/tools/pytest_src.sh。
- golden: ${S}/golden/golden.py（0.20.0 の出力は ${S}/n10/golden_base。0.21.0 でも 19 件とも同じ）。
- 本誌の出版版 PDF 5 本・7 通り: ${S}/n10/judge/realpdf/check.py（--before-src に比べる版、--route1）。PDF は tests/private/pdf/。
- 反例集すべて: sh ${S}/fixB2r4/tools/run_oracle.sh <src> <タグ> o34 n10 n10g rv89 judge judge2 b2 x xm r1 y y2（ログは ${S}/fixB2r4/logs。タグは担当名を入れて重ならないように）。
  4 回目の点検の反例: ${S}/b2_review/r4p/cases_w_only.py・${S}/b2_review/r5p/cases_v_only.py（python ${O}/run_all.py <src> <ケース> --name <名前>）。
- 生成例: sh ${S}/fixB2r4/gen.sh <src> <タグ>（18 種）と sh ${S}/b2_review/r5p/run_gen.sh <src> <タグ> <名前…>（5 回目の点検の gen_r5*.py。名前は ${S}/b2_review/r5p/exp と r5reg の gen_*.py）。
- 点検の例 quick・乱数の例 fuzz4・fuzz8: ${S}/n10/judge/tools/run_suites.sh・sum_q.py・run8_all.py（${S}/fixB2r4/tools/run8_all.py）・sum_fz.py・cmp_fz.py。210 件: ${S}/fixB/fixB_all.py --compare。速さ: ${S}/n10/judge/tools/t_speed.py。
- Colab の実データ td1〜3（tests/private/colab/tdN/tdN.docx・tdN.pdf。コミットしない）: cd /tmp && PYTHONPATH=<src> python -m jasme_jats …/tdN.docx --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml --pdf …/tdN.pdf --route pdf --ai manual --out <出力先>。0.21.0 の出力は作って比べる。
厳守:
- ブランチは claude/jstage-xml-converter-review-dw2f0u のまま。git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- 実際の論文の本文（tests/private の docx・PDF の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る）。実験は ${B}/<担当名>/ の下に置く。tests/ に一時ファイルを残さない。
- ディスクの空きが少ない（df -h / で確かめる。3GB を切りそうなら自分の古い作業ファイルを消す）。担当の最後に、自分が作った oracle/_work/<名前> と、大きな出力（docx・pdf・xml・zip）を消す（結果の JSON・ログ・スクリプトは残す）。
- python tests/make_fixtures.py を実行しない。コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
`
const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    approach: { type: 'string', description: '守りの考え方と、消した・置き換えた個別の規則' },
    prototype_dir: { type: 'string' },
    results: { type: 'string', description: '物差しごとの数（0.20.0・0.21.0・試作）。13.2 に回った本当の直しの数も' },
    covers: { type: 'string' },
    risks: { type: 'string' },
  },
  required: ['approach', 'prototype_dir', 'results', 'covers', 'risks'],
}
const ORACLE_SCHEMA = {
  type: 'object',
  properties: {
    cases_file: { type: 'string' }, count: { type: 'integer' },
    groups: { type: 'string' }, base_result: { type: 'string', description: '0.20.0 と 0.21.0 での OK/REPORTED/FAIL' }, notes: { type: 'string' },
  },
  required: ['cases_file', 'count', 'groups', 'base_result', 'notes'],
}
const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    chosen: { type: 'string', description: '選んだ案（組み合わせなら中身）と理由' },
    design_doc: { type: 'string', description: '${B}/DESIGN_B21.md のパス' },
    prototype_dir: { type: 'string' },
    measures: { type: 'string' },
    rejected: { type: 'string' },
    limits: { type: 'string' },
  },
  required: ['chosen', 'design_doc', 'prototype_dir', 'measures', 'rejected', 'limits'],
}
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, deviations: { type: 'string' }, open_issues: { type: 'string' },
  },
  required: ['changed_files', 'summary', 'tests_added', 'pytest_result', 'deviations', 'open_issues'],
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
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'should', 'nit'] },
      file: { type: 'string' }, line: { type: 'integer' },
      problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' },
    }, required: ['severity', 'file', 'line', 'problem', 'evidence', 'fix'] } },
  },
  required: ['findings'],
}

phase('Design')
const DESIGNS = [
  { key: 'isolate', text: `案 A「離れた端は直さない」: 段落ごとに、本体の塊（最も長い一続きの塊と、それと本文の行の流れで続く塊）を決め、本体から、ほかの段落の塊・キャプション・どの段落にも当たらない行・
受付日の行・柱のどれかをはさんで離れた端の部分（とその行）にある違いは、文字の違い・全角・半角・大文字・小文字・ダッシュのどれも直さず 13 章に出す（足す・消すもしない）。
離れた端の部分が本当に段落のものか（図の中の文字か）を決めようとする個別の規則（_loose_edge・stray_edge・figure_edge_lines・facing_hole・better_line など）は、この守りに置き換えられるものは消す。` },
  { key: 'ambiguity', text: `案 B「ほかの説明ができるなら直さない」: 端の違い（と端の行）ごとに、その PDF の文字を、段落の文字として並べる説明と、ほかの段落・図の中の文字・キャプション・どの段落にも当たらない行として
並べる説明の両方を作って比べ、ほかの説明がほぼ同じくらいよく当てはまる（あいまい）なら直さず 13 章に出す。はっきり段落の文字のときだけ直す。個別の規則は、この判定に置き換えられるものは消す。` },
  { key: 'evidence', text: `案 C「証拠の重みで決める」: 端の違いに、段落の文字である証拠（本体と同じ行・本文の行の流れの続き・行の幅・字下げ・文の終わり・docx の順との一致）と、図・表の中の文字である証拠
（キャプションに隣り合う・短い行・どの段落にも当たらない行に囲まれる・ページの端・ほかの段落とのよく似た文字）を点数にして、段落の側が十分に強いときだけ直し、それ以外は 13 章に出す。
個別の規則は、この点数に置き換えられるものは消す。` },
]
const designOf = d => agent(`${COMMON}
## 担当: 設計の試作（${d.key}）
${d.text}
0.21.0 の src を ${B}/${d.key}/src に写して試作する（本体の作業ツリーは変えない）。まず、B2 の 4 回目の点検で残った 6 件（workflow_final.json の remaining）と、それまでの点検の指摘の形を、
架空の文字の再現の例にして ${B}/${d.key}/ に置き、0.21.0 と 0.20.0 での結果を確かめる。試作の後、上の物差しをすべて流し（pytest は、既存のテストのうち期待が変わるものを理由付きで挙げる）、
0.20.0・0.21.0 と数を並べる。とくに: 原則違反（足す・消す・黙った違い）の数、13.2 に回った本当の直しの数（本誌の出版版 PDF 7 通り・td1〜3・quick・fuzz8）、
4 回目の点検の反例と生成例の FAIL、照合の速さ。案の弱点も正直に risks に書く。`, { label: `design:${d.key}`, phase: 'Design', schema: DESIGN_SCHEMA, effort: 'max' })
const oracleTask = () => agent(`${COMMON}
## 担当: 実装を見ない反例集（oracle_b21）
あなたは実装を見ない担当です。作業ツリーの差分、src の pdfmatch.py の _Joint・_classify の中身、${B} の下の試作は読まないこと（反例の期待が実装に引きずられないように）。
読んでよいもの: CLAUDE.md、docs/DESIGN.md 4.4 と docs/FIX_PLAN.md の B2・B2.1 の節（直したいことと原則）、${O} の runner.py・run_all.py と既存のケースの書き方、
本誌の出版版 PDF の形（tests/private/pdf/。文字は書き写さない）。
原則と本誌の PDF の形だけから、B2.1 の対象（分断された段落の端の 1 行と、すぐ隣の図・表の中の行・キャプション・ほかの段落・受付日の行・柱がよく似ている、または入れ替わって見える配置）の
反例を ${O}/cases_b21.py に 60〜120 件作る（すべて架空の文字。既存のケースと同じ形式）。各組で、本当の校正の直し（直すのが期待）と、図の中の文字を段落の文字と取り違えやすい形
（直さず 13 章に出すのが期待。足す・消すは FAIL）の両方を、ページの区切り・段の区切り・受付日の行・柱・キャプションの上下・1 行だけの図・表の有無で組み合わせる。
期待の判断に迷うケースは「直すか、docx のまま 13 章に出すかのどちらか」（fix_or_keep。cases_b2.py に書き方がある）にする。
各ケースを 0.20.0（${S}/n10/judge/base_src）と 0.21.0（${B}/base021_src）で流して件数を base_result に書く（実行してよいのは run_all.py だけ）。`,
  { label: 'oracle_b21', phase: 'Design', schema: ORACLE_SCHEMA, effort: 'high' })
const designOut = await parallel([...DESIGNS.map(d => () => designOf(d)), oracleTask])
const designs = designOut.slice(0, 3)
const oracle = designOut[3]
log(`design: ${designs.map((d, i) => d ? DESIGNS[i].key : DESIGNS[i].key + '(失敗)').join(', ')} / oracle: ${oracle ? oracle.count : '失敗'}`)

phase('Judge')
const judge = await agent(`${COMMON}
## 担当: 比べて選ぶ（judge）
3 つの試作を、同じ物差し・同じ条件で測り直して比べ、反証で弱点を探し、選ぶ（組み合わせてもよい）。設計担当の報告の数はそのまま使わず、自分で測る
（試作は ${B}/judge/<案>_src に写してから測る）。実装を見ない担当の反例 ${O}/cases_b21.py も 3 案・0.20.0・0.21.0 で流す。
選ぶ基準: (1) 原則違反（足す・消す・黙った違い）が最も少ない。0.21.0 より悪くなる形がない（あれば理由と数）。(2) 13.2 に回る本当の直しが少ない（本誌の PDF・td1〜3 では増やさない）。
(3) 規則が少なく一般的で、点検で新しい形が見つかっても同じ守りで扱える。(4) 速さ。
足りない点があれば、選んだ案を直した試作 ${B}/judge/final_src を作ってよい。${B}/DESIGN_B21.md に、結論・物差しの数・各案の弱点・選んだ理由・関数ごとの変更点・テストの計画・
合格の条件（試作の数。これより悪くしない）・残る限界を書く（実際の論文の結果は段落 ID と件数だけ）。
設計担当の報告:
${JSON.stringify(designs.map((d, i) => ({ key: DESIGNS[i].key, ...(d || { failed: true }) })), null, 1)}
実装を見ない担当の報告:
${JSON.stringify(oracle, null, 1)}`, { label: 'judge', phase: 'Judge', schema: JUDGE_SCHEMA, effort: 'max' })

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 実装（impl）
${B}/DESIGN_B21.md（judge が選んだ設計）を読み、選んだ試作（${judge ? judge.prototype_dir : '（judge の報告なし）'}）を土台に、作業ツリーの src に入れる。写すだけでなく読み直し、
本体の書き方（コメントの量・名前・日本語の説明）に合わせ、置き換えた個別の規則・使われない定数・関数を消す。pdfmatch.py の冒頭の説明、docs/DESIGN.md 4.4（守りと限界）、
docs/DEVELOPMENT.md の「残っている課題」を合わせる（版・ノートブック・FIX_PLAN は仕上げの担当が行う）。
テスト: DESIGN_B21.md の計画のとおり tests/test_pdfmatch.py に足し・直す（期待を変える既存のテストは理由を docstring とコメントに書く）。足したテストが 0.21.0 で落ちることを確かめる。
確かめ: DESIGN_B21.md の合格の条件を、物差しすべてで確かめる（pytest 3.13・3.10、golden、本誌の PDF 7 通り、反例集すべてと cases_b21・w_only・v_only、生成例、quick・fuzz4・fuzz8、210 件、速さ、td1〜3）。
judge の報告:
${JSON.stringify(judge, null, 1)}`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, effort: 'max' })

phase('Verify')
const verifies = await parallel([
  () => agent(`${COMMON}
## 担当: 物差しすべてでの確かめ（verify_measures）
作業ツリーの実装を、DESIGN_B21.md の合格の条件と物差しすべてで測り、0.20.0・0.21.0・judge の試作と数を並べる。FAIL があれば、期待が原則に合っているかを確かめたうえで、
実装の誤りなら problems に書く。新しいテストが 0.21.0 で落ちることも確かめる。ファイルは変更しない（実験は ${B}/verify/ の下）。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify_measures', phase: 'Verify', schema: VERIFY_SCHEMA, effort: 'high' }),
  () => agent(`${COMMON}
## 担当: Colab の実データでの確かめ（verify_colab）
td1・td2・td3 を、作業ツリーの実装でルート2（--ai manual）とルート1（--route docx --pdf …）で変換し（出力は ${B}/verify_colab/<ルート>/tdN）、0.21.0（${B}/base021_src）の出力と比べる。
13.1・13.2・13.4・13.5・13.6 の違いをすべて段落ごとに挙げ、PDF（jasme_jats.pdfmatch.extract_pages）と docx を見て正しいか判定する。13.2 に新しく回った本当の直しは数と段落 ID を挙げる。
不変性・最終・DTD・J-STAGE のチェックがすべて合格か。結果は段落 ID と件数で書く（実際の論文の文字は 10 文字以内の引用にとどめる）。ファイルは変更しない。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify_colab', phase: 'Verify', schema: VERIFY_SCHEMA, effort: 'high' }),
])
const vprobs = verifies.filter(Boolean).flatMap((v, i) => (v.problems || []).map(p => ({ from: ['verify_measures', 'verify_colab'][i], ...p })))
let pre = null
if (vprobs.some(p => p.severity !== 'nit')) {
  pre = await agent(`${COMMON}
## 担当: 確かめで見つかった問題を直す（fix_verify）
次の問題のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。個別の形の規則を足すのではなく、DESIGN_B21.md の守りの範囲で直す。
守りで扱えない形は、直さず 13 章に出す側に倒す。直した後、物差し（少なくとも pytest 3.13・3.10、golden、本誌の PDF、反例集すべてと cases_b21、生成例、quick、fuzz8、td1〜3）を流し直す。
問題:
${JSON.stringify(vprobs, null, 1)}`, { label: 'fix_verify', phase: 'Verify', schema: IMPL_SCHEMA, effort: 'max' })
}

phase('Finalize')
const fin = await agent(`${COMMON}
## 担当: 仕上げ（finalize）
1. 版を 0.21.1 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md の B2.1 の節に、設計の要点（3 案を試作で比べて選んだこと）・テスト・実装で決めたこと・確かめた数・残る限界を書き、反映の順序の表で「（実装済み）」にする。
   N20 の行と、DESIGN.md 4.4 の N20 の限界の項目（「0.21.1 で…止める」）を、実装に合わせて書き直す。
3. docs/DESIGN.md・DEVELOPMENT.md・README.md・CLAUDE.md の記述が実装と合うか確かめて直す。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる。pytest（3.13・3.10）を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', effort: 'max', text: `原則と文字の不変性（ルート2）: 新しい守りに、docx にも PDF の本文にもない文字を足す経路、PDF の本文にある docx の文字を消す経路、決められない違いを黙って落とす経路がないか。
B2 の 4 回の点検で見つかった形（${S}/b2_review/ の指摘）と、その近くの境界で、0.21.0・0.20.0 より悪くなる例を実験で探す。反例は ${B}/review_cases.py に置く。` },
  { key: 'regression', effort: 'max', text: `回帰とテスト: 物差しすべて（pytest 3.13・3.10、golden、本誌の PDF 7 通り、反例集すべてと cases_b21・w_only・v_only、生成例、quick、fuzz4、fuzz8、210 件、速さ）と td1〜3 を、
0.21.0 と比べて、悪くなったものがないか。13.2 に回る本当の直しが増えすぎていないか。新しいテストが 0.21.0 で落ちるか。テストが実装の細部に寄りかかりすぎていないか（守りを外すとテストが落ちるか）。` },
  { key: 'user', effort: 'high', text: `利用者への見え方と文書: レポートの 13 章（新しい理由の文面、13.2 の長さと、編集委員が PDF と見比べて直せるか）、Colab の表示、README・DESIGN・DEVELOPMENT・CLAUDE.md・FIX_PLAN（B2.1 の節・N20）が
実装と合っているか。td1〜3 と本誌の PDF のレポートを実際に読んで確かめる。版が 0.21.1 にそろい、ノートブックが作り直されているか。実際の論文の本文がコミットされる場所に入っていないか。` },
]
const reviewOf = (l, extra) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 B2.1 の実装を厳しく点検する。ファイルは変更しない（実験は ${B}/review/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.21.0・0.20.0 との比較を evidence に書く）。blocking は原則違反（文字の挿入・脱落・黙った違い）で 0.21.0 より悪くなるもの・
テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.21.0 にもあって B2.1 で悪くなっていないもの・DESIGN_B21.md の既知の限界は、新しく見つけたものだけ nit にする。
指摘の直し方（fix）は、個別の形の規則を足すのではなく、守りの範囲で直す・直さず 13 章に出す側に倒す形で書く。問題がなければ findings は空でよい。
${extra}`, { label: `review:${l.key}`, phase: 'Review', schema: FIND_SCHEMA, effort: l.effort })
const reviews = await parallel(LENSES.map(l => () => reviewOf(l, `仕上げの担当の報告:\n${JSON.stringify(fin, null, 1)}`)))
let todo = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
const firstFindings = todo
log(`指摘: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length} / nit ${todo.filter(f => f.severity === 'nit').length}`)

const rounds = []
for (let round = 1; round <= 4 && todo.some(f => f.severity !== 'nit'); round++) {
  phase('Fix')
  const fix = await agent(`${COMMON}
## 担当: 点検の指摘を直す（${round} 回目）
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ。個別の形の規則を足さず、DESIGN_B21.md の守りの範囲で直す。
守りで扱えない形は、直さず 13 章に出す側に倒す。直した後、物差し（少なくとも pytest 3.13・3.10、golden、本誌の PDF、反例集すべてと cases_b21、生成例、quick、fuzz8、td1〜3）を流し直す。必要なら文書・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, effort: 'max' })
  phase('Recheck')
  const RE = [LENSES[0], LENSES[1]]
  const rr = await parallel(RE.map(l => () => reviewOf({ ...l, effort: 'max' }, `${round} 回目の修正の後の点検。直した指摘が本当に直ったか（再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。
前の指摘:
${JSON.stringify(todo, null, 1)}
修正の担当の報告:
${JSON.stringify(fix, null, 1)}`)))
  const failedLens = rr.map((r, i) => r ? null : RE[i].key).filter(Boolean)
  todo = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: RE[i].key, ...f })))
  rounds.push({ round, fix, findings: todo, failedLens })
  log(`${round} 回目の点検: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length}${failedLens.length ? ' / 失敗した観点: ' + failedLens.join(',') : ''}`)
}
return { designs, oracle, judge, impl, verifies, pre, fin, firstFindings, rounds, remaining: todo }
