export const meta = {
  name: 'jasme-b21-review',
  description: '単位 B2.1（0.21.1）の点検から再開: 原則・回帰・利用者向けの 3 観点で点検し、反映を止める指摘がなくなるまで修正と再点検をくり返す（最大 4 回）',
  phases: [
    { title: 'Review', detail: '原則（1 回目は Fable max。終わった担当はキャッシュ）・回帰（Opus max）・利用者向け（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（1 回目は Fable max でキャッシュ、2 回目以降は Opus max）' },
    { title: 'Recheck', detail: '修正後の点検。原則・回帰（Opus max）' },
  ],
}

// args: { scratch: 作業用の場所（道具の中のパスと同じ。symlink で新しい場所に向く）, fin: 仕上げの担当の報告（finalize.json の中身）,
//         impl: 実装の担当の報告（impl.json）, verify: 確かめの担当の報告（verify_measures.json・verify_colab.json）, judge_limits: judge.json の limits }
const S = args.scratch
const O = `${S}/oracle`
const B = `${S}/b21`
const R = `${S}/fix_plan_work/b21/results`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール）で、修正計画 docs/FIX_PLAN.md の単位「B2.1（0.21.1）」の実装を点検する担当です。
main とこのブランチ（claude/jstage-xml-converter-review-dw2f0u）は 45d8314（0.21.0。単位 B2 を反映済み）。B2.1 の実装は、作業ツリーのコミットしていない差分（git diff・git status。11 ファイル）。
0.21.0 の src の写しは ${B}/base021_src、0.20.0 は ${S}/n10/judge/base_src。試作 F の src は残っていない（作業ツリーの src が F と同じ動きをすることは実装の担当が確かめた。
設計どおりかを見るときは ${S}/fix_plan_work/b21/diffs/final_pdfmatch.diff〈0.21.0 → F〉と作業ツリーの差分を比べる）。
この点検は、前のセッション（数日前）で途中で止まったものの再開。前の点検の結果は残っていない。設計・実装・確かめ・仕上げの担当の報告は ${R}/*.json
（design_*.json・oracle_b21.json・judge.json・impl.json・verify_measures.json・verify_colab.json・finalize.json）。設計の文書は ${B}/DESIGN_B21.md（7.4 が合格の条件、8 が残る限界）。
まず docs/FIX_PLAN.md の「B2」「B2.1」の節、docs/DESIGN.md 4.4、src/jasme_jats/pdfmatch.py の冒頭と _Joint・_classify・_isolate・_plain_tail を読む。
単位 B2 の 4 回の点検の結果は ${S}/b2_review/（review_*・recheck*_*・fix*_result.json、workflow_final.json の remaining が残った 6 件）。
B2.1 の目的: B2 で、分断された段落の端の 1 行と、すぐ隣の図・表の中の行・キャプション・ほかの段落がよく似ているまれな配置で、図の中の文字を足す・本当の校正の直しを直さない・
docx にも PDF にもない文字にする誤りが、点検のたびに別の形で見つかり、個別の規則の追加では収束しなかった。これを、個別の形の継ぎはぎではなく、
原則（決められない違いは docx のまま残し、理由を付けて 13 章に出す）に沿った一般的な守り（_isolate・FAR_WHY・_plain_tail・_edges_near_unused_lines）で止める。
原則（CLAUDE.md）: XML の本文は出版版 PDF の本文と 1 文字も違ってはいけない。ルート2 は docx の文字を PDF に合わせて直すが、組版の文字、docx にない図・表の中の文字、ほかの段落の文字を
docx に足してはいけない。PDF の本文にある docx の文字を消してはいけない。決められない違いは docx のまま残し、13 章に出す。docx を直すのは pdfdocx.py だけ。
守りの代償: 本当の校正の直しの一部が「直さなかった箇所」（13.2）に回ると、利用者（技術に詳しくない編集委員）が手で確かめる箇所が増える。物差しでは、原則違反（足す・消す・黙った違い）を
減らすことを第一に、13.2 に回る本当の直しの数（本誌の出版版 PDF・td1〜3・乱数の例）も測って、増えすぎないことを確かめる。
物差しの道具（作業用の場所 ${S}。使い方は各ファイルの冒頭、${S}/fix_plan_work/TOOLS.md の「物差し」の表、${S}/n10/DESIGN_N10.md 2 章）:
- pytest: python -m pytest -q -p no:cacheprovider（3.13）、PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider（3.10）。別の src を測るときは ${S}/fixB2r4/tools/pytest_src.sh。
- golden: ${S}/golden/golden.py（0.20.0 の出力は ${S}/n10/golden_base。0.21.0 でも 19 件とも同じ）。
- 本誌の出版版 PDF 5 本・7 通り: ${S}/n10/judge/realpdf/check.py（--before-src に比べる版、--after-src、--route1、--tag）。PDF は tests/private/pdf/。
- 反例集すべて: sh ${S}/fixB2r4/tools/run_oracle.sh <src> <タグ> o34 n10 n10g rv89 judge judge2 b2 x xm r1 y y2（ログは ${S}/fixB2r4/logs。タグは担当名を入れて重ならないように）。
  B2.1 の反例: ${O}/cases_b21.py（実装を見ない担当）、${B}/judge/cases_judge21.py（比べる担当）、4 回目の点検の反例 ${S}/b2_review/r4p/cases_w_only.py・${S}/b2_review/r5p/cases_v_only.py
  （python ${O}/run_all.py <src> <ケース…> --name <名前>）。反例ごとに比べるのは ${S}/fixB2r4/tools/cmp_or.py。
- 生成例: sh ${S}/fixB2r4/gen.sh <src> <タグ>（18 種）と sh ${S}/b2_review/r5p/run_gen.sh <src> <タグ> <名前…>（gen_r5*.py）。集計は agg_gen.py・cmp_gen.py。
- 点検の例 quick・乱数の例 fuzz4・fuzz8: ${S}/fixB2r4/tools/run_suites.sh・sum_q.py・run8_all.py・sum_fz.py・cmp_fz.py。210 件: ${S}/fixB/fixB_all.py --compare。速さ: ${S}/fixB2r4/tools/t_speed.py・t_small.py。
- 物差しをまとめて流す: sh ${B}/isolate/tools/master_iso.sh <src> <タグ> [real]（1 版 10 分ほど。real を付けると本誌の PDF・td1〜3・速さも）。
- Colab の実データ td1〜3（tests/private/colab/tdN/tdN.docx・tdN.pdf。コミットしない）: sh ${B}/isolate/tools/run_td.sh <src> <タグ>（出力は ${B}/isolate/td/）。
  0.21.0 と作業ツリーの再開時の出力は ${B}/isolate/td/{base021_resume,wt_resume}_r{1,2}/tdN と cmp_{base021_resume,wt_resume}.json にある。
厳守:
- ブランチは claude/jstage-xml-converter-review-dw2f0u のまま。git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- 実際の論文の本文（tests/private の docx・PDF の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る。新しいテスト・反例は、実際の PDF の文字と 12 文字以上一致しないか確かめる）。
  実験は ${B}/review/<担当名>/ の下に置く。tests/ に一時ファイルを残さない。
- ディスクの空きが少ない（df -h / で確かめる。3GB を切りそうなら自分の古い作業ファイルを消す）。担当の最後に、自分が作った oracle/_work/<名前> と、大きな出力（docx・pdf・xml・zip）を消す（結果の JSON・ログ・スクリプトは残す）。
- python tests/make_fixtures.py を実行しない。コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string', description: '流し直した物差しの数（0.21.0・修正前と並べる）' },
    deviations: { type: 'string' }, open_issues: { type: 'string' },
  },
  required: ['changed_files', 'summary', 'tests_added', 'pytest_result', 'measures', 'deviations', 'open_issues'],
}
const FIND_SCHEMA = {
  type: 'object',
  properties: {
    checked: { type: 'string', description: '何をどう確かめたか（流した物差し・実験・読んだ範囲）。指摘がなくても書く' },
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'should', 'nit'] },
      file: { type: 'string' }, line: { type: 'integer' },
      problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' },
    }, required: ['severity', 'file', 'line', 'problem', 'evidence', 'fix'] } },
  },
  required: ['checked', 'findings'],
}

const LENSES = [
  { key: 'principle', model: 'fable', effort: 'max', text: `原則と文字の不変性（ルート2）: 新しい守り（_isolate・FAR_WHY・_plain_tail・_edge_alternative・_figure_line・字下げの区切り・_edges_near_unused_lines・tail_beyond）に、
docx にも PDF の本文にもない文字を足す経路、PDF の本文にある docx の文字を消す経路、決められない違いを黙って落とす経路がないか。
B2 の 4 回の点検で見つかった形（${S}/b2_review/ の指摘）と、その近くの境界（キャプションの上下・ページの区切り・受付日の行・柱・1 行だけの図・表・2 段組みの読み順のずれ・字下げ）で、
0.21.0・0.20.0 より悪くなる例を実験で探す（DESIGN_B21.md 8 章の既知の限界は除く）。反例は ${B}/review/principle/cases_review.py に置き、0.20.0・0.21.0・作業ツリーで流して比べる。` },
  { key: 'regression', model: 'opus', effort: 'max', text: `回帰とテスト: 物差しすべて（pytest 3.13・3.10、golden、本誌の PDF 7 通り、反例集すべてと cases_b21・cases_judge21・w_only・v_only、生成例、quick、fuzz4、fuzz8、210 件、速さ）と td1〜3 を、
自分で流して 0.21.0 と比べ、悪くなったものがないか、DESIGN_B21.md 7.4 の合格の条件を満たすか（担当の報告の数をそのまま信じない）。13.2 に回る本当の直しが増えすぎていないか。
新しいテストが 0.21.0 で落ちるか。テストが実装の細部に寄りかかりすぎていないか（守りを 1 つずつ外す・弱めると、どのテストが落ちるかを試す。落ちないテストで守られていない規則があれば指摘）。` },
  { key: 'user', model: 'opus', effort: 'high', text: `利用者への見え方と文書: レポートの 13 章（FAR_WHY の添え書きの文面、13.2 の長さと、技術に詳しくない編集委員が PDF と見比べて直せるか）、Colab の表示、
README・DESIGN・DEVELOPMENT・CLAUDE.md・FIX_PLAN（B2.1 の節・N20 の行・反映の順序の表）が実装と合っているか（規則の名前・数・限界）。td1〜3 と本誌の PDF のレポートを実際に読んで確かめる。
版が 0.21.1 にそろい（__init__.py・pyproject.toml・ノートブック）、ノートブックが tools/make_notebook.py で作り直されているか。実際の論文の本文がコミットされる場所（git diff）に入っていないか。
確かめの担当が nit とした 2 件（速さの書き方: 1 回の値でなく交互に測った平均と最小どうしの比で書く。DESIGN.md 4.4 の「0.21.0 より悪くなる形のない」の言い方: 何が悪くならないのかを書く）が直っているかも見る。` },
]
const reviewOf = (l, extra, opts) => agent(`${COMMON}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 B2.1 の実装を厳しく点検する。ファイルは変更しない（実験は ${B}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.21.0・0.20.0 との比較を evidence に書く）。blocking は原則違反（文字の挿入・脱落・黙った違い）で 0.21.0 より悪くなるもの・
テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.21.0 にもあって B2.1 で悪くなっていないもの・DESIGN_B21.md 8 章の既知の限界は、新しく見つけたものだけ nit にする。
指摘の直し方（fix）は、個別の形の規則を足すのではなく、守りの範囲で直す・直さず 13 章に出す側に倒す形で書く。問題がなければ findings は空でよい（checked に何を確かめたかを書く）。
${extra}`, { label: `review:${l.key}`, phase: opts.phase, schema: FIND_SCHEMA, model: opts.model || l.model, effort: opts.effort || l.effort })

phase('Review')
const PREV = `仕上げの担当の報告:\n${JSON.stringify(args.fin, null, 1)}\n確かめの担当の報告（物差し・Colab）:\n${JSON.stringify(args.verify, null, 1)}\n比べる担当が書いた残る限界:\n${JSON.stringify(args.judge_limits, null, 1)}`
const reviews = await parallel(LENSES.map(l => () => reviewOf(l, PREV, { phase: 'Review' })))
const failedFirst = reviews.map((r, i) => r ? null : LENSES[i].key).filter(Boolean)
let todo = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
const firstFindings = todo
log(`指摘: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length} / nit ${todo.filter(f => f.severity === 'nit').length}${failedFirst.length ? ' / 失敗した観点: ' + failedFirst.join(',') : ''}`)

const rounds = []
let incomplete = null
for (let round = 1; round <= 4 && todo.some(f => f.severity !== 'nit'); round++) {
  phase('Fix')
  const fix = await agent(`${COMMON.replace('の実装を点検する担当です', 'の点検の指摘を直す担当です')}
## 担当: 点検の指摘を直す（${round} 回目）
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ。個別の形の規則を足さず、DESIGN_B21.md の守りの範囲で直す。
守りで扱えない形は、直さず 13 章に出す側に倒す。直した後、物差し（少なくとも pytest 3.13・3.10、golden、本誌の PDF、反例集すべてと cases_b21・cases_judge21、生成例、quick、fuzz8、td1〜3）を流し直し、
DESIGN_B21.md 7.4 の合格の条件を満たすことを確かめる（満たさなくなった数があれば理由を書く）。必要なら文書（FIX_PLAN の B2.1 の節・DESIGN.md 4.4・DEVELOPMENT.md）・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, model: round === 1 ? 'fable' : 'opus', effort: 'max' })
  phase('Recheck')
  const RE = [LENSES[0], LENSES[1]]
  const rr = await parallel(RE.map(l => () => reviewOf(l, `${round} 回目の修正の後の点検。直した指摘が本当に直ったか（再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。
前の指摘:
${JSON.stringify(todo, null, 1)}
修正の担当の報告:
${JSON.stringify(fix, null, 1)}`, { phase: 'Recheck', model: 'opus', effort: 'max' })))
  const failedLens = rr.map((r, i) => r ? null : RE[i].key).filter(Boolean)
  todo = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: RE[i].key, ...f })))
  rounds.push({ round, fix, findings: todo, failedLens })
  log(`${round} 回目の点検: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length}${failedLens.length ? ' / 失敗した観点: ' + failedLens.join(',') : ''}`)
  if (failedLens.length) { incomplete = failedLens; break }   // 観点が失敗（上限・再起動）したら収束とみなさず、まとめ役に返す
}
return { reviews, failedFirst, firstFindings, rounds, remaining: todo, incomplete }
