export const meta = {
  name: 'jasme-b21-round5',
  description: '単位 B2.1（0.21.1）の 5 回目（最後）: 4 回目の再点検で残った指摘を直し、原則・回帰の 2 観点で再点検する（利用者の判断 25）',
  phases: [
    { title: 'Fix', detail: '4 回目の再点検の指摘を直す（Opus max）' },
    { title: 'Recheck', detail: '原則・回帰（Opus max）' },
  ],
}

// args: { scratch: 作業用の場所 }。4 回目の再点検で残った指摘（todo）と 4 回目の修正の担当の報告（fix4）は ${B}/review/round5_input.json（JSON）に置き、担当がそれを読む
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
  { key: 'principle', text: `原則と文字の不変性（ルート2）: 5 回目の修正の後の点検。前の指摘（とくに blocking 3 件: 図の中のふつうの行をはさんでキャプションの隣にある幅いっぱいの写しを本体に入れる経路と、4 回目の修正で開いた同じ穴の新しい経路）が本当に直ったかを再現の例で確かめ、
修正で新しく壊れたもの（docx にも PDF の本文にもない文字を足す経路、PDF の本文にある docx の文字を消す経路、決められない違いを黙って落とす経路）がないかを、キャプションの隣・図の中の行・幅いっぱいの写し・ページの区切り・受付日の行・字下げの境界で実験して探す。
これまでの点検の反例（${B}/review/principle/ 以下の cases_review*.py）も作業ツリーで流し直し、0.21.0 より悪くなった反例が 0 であることを確かめる。` },
  { key: 'regression', text: `回帰とテスト: 5 回目の修正の後の点検。物差しすべて（pytest 3.13・3.10、golden、本誌の PDF 7 通り、反例集すべてと cases_b21・cases_judge21・w_only・v_only・cases_review*、生成例、quick、fuzz4、fuzz8、210 件、465 件の置き換え、速さ）と td1〜3 を自分で流して 0.21.0 と修正前と比べ、
悪くなったものがないか、DESIGN_B21.md 7.4 の合格の条件を満たすか（速さは 0.21.0 の 1.15 倍までを利用者が受け入れた〈判断 25〉ので、それ以内か）。前の指摘が直ったかを再現の例で確かめる。足したテストが修正前・0.21.0 で落ちるか。新しい守りを外すとテストが落ちるか。` },
]
const reviewOf = (l, extra) => agent(`${COMMON}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 B2.1 の実装を厳しく点検する。ファイルは変更しない（実験は ${B}/review/${l.key}/r6/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.21.0・修正前との比較を evidence に書く）。blocking は原則違反（文字の挿入・脱落・黙った違い）で 0.21.0 より悪くなるもの・
テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.21.0 にもあって B2.1 で悪くなっていないもの・文書に書かれた既知の限界は、新しく見つけたものだけ nit にする。
これが最後の点検で、この後に修正の回はない（利用者の判断 25: 5 回目でも反映を止める指摘が残れば B2.1 は反映しない）。blocking・should の判定は、その基準に照らして正確に付ける（文書の記述の不足は nit）。問題がなければ findings は空でよい（checked に何を確かめたかを書く）。
${extra}`, { label: `review:${l.key}`, phase: 'Recheck', schema: FIND_SCHEMA, model: 'opus', effort: 'max' })

phase('Fix')
const fix = await agent(`${COMMON.replace('の実装を点検する担当です', 'の点検の指摘を直す担当です')}
## 担当: 点検の指摘を直す（5 回目。最後の修正）
利用者の判断 25: 5 回目の修正を 1 回だけ行い、その再点検で反映を止める指摘が残れば B2.1 は反映しない。照合の速さは 0.21.0 の 1.15 倍までを受け入れる（FIX_PLAN の決定事項 25 に記録済み。DESIGN.md 4.4・FIX_PLAN B2.1 の速さの記述もそれに合わせる）。
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書の記述の訂正は行う）。個別の形の規則を足さず、既存の守りの範囲で直す。
blocking 3 件の直し方は、2 観点の提案どおり、キャプションの隣で切る守り（_flow_breaks の 2）を、間の行が図・表の中の文字（どの段落にも当たらない、飛ばさない行）のときと、ka の行で流れが切れるときにも当てる（試作 capfig2。${B}/review/principle/ と ${B}/review/regression/ の r5 以下に試作と test_proposal_r5.py がある。場所は evidence・fix を読んで探す）。
試作をそのまま入れるのではなく読み直し、本体の書き方（コメント・日本語の説明）に合わせ、DESIGN.md 4.4 の守りの説明と FIX_PLAN B2.1 の規則・残る限界・代償の記述を実装に合わせる。test_proposal_r5.py のテストを tests/test_pdfmatch.py に取り込み、修正前・0.21.0 で落ちることを確かめる。
直した後、物差し（pytest 3.13・3.10、golden、本誌の PDF 7 通り、反例集すべてと cases_b21・cases_judge21・cases_review*、生成例、quick、fuzz8、210 件、465 件の置き換え、td1〜3、速さ）を流し直し、DESIGN_B21.md 7.4 の合格の条件（速さは 1.15 倍以内）を満たすことを確かめる。満たさなくなった数があれば理由を書く。
ノートブックは python tools/make_notebook.py で作り直す（版は 0.21.1 のまま）。
指摘（todo。8 件: blocking 3・should 1・nit 4）と、4 回目の修正の担当の報告（fix4。修正前の状態の説明）は、${B}/review/round5_input.json を読む（JSON。キー todo と fix4）。`, { label: 'fix:5', phase: 'Fix', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })

phase('Recheck')
const rr = await parallel(LENSES.map(l => () => reviewOf(l, `前の指摘（4 回目の再点検。8 件）は ${B}/review/round5_input.json のキー todo を読む。
5 回目の修正の担当の報告:
${JSON.stringify(fix, null, 1)}`)))
const failedLens = rr.map((r, i) => r ? null : LENSES[i].key).filter(Boolean)
const findings = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
log(`5 回目の点検: blocking ${findings.filter(f => f.severity === 'blocking').length} / should ${findings.filter(f => f.severity === 'should').length} / nit ${findings.filter(f => f.severity === 'nit').length}${failedLens.length ? ' / 失敗した観点: ' + failedLens.join(',') : ''}`)
return { fix, reviews: rr, findings, failedLens }
