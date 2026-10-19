export const meta = {
  name: 'jasme-unit-b2',
  description: '単位 B2（0.21.0）: N10 とその仲間・en dash・Colab で見つかったルート2 の誤りを、設計 C に沿って実装し、確かめ、仕上げ、3 観点で点検して直す',
  phases: [
    { title: 'Implement', detail: '設計 C の実装と、数式の欠けた挿入の新しい規則（max）／実装を見ない担当の反例集（high）' },
    { title: 'Verify', detail: '物差しすべて（high）／Colab のテストデータ1〜3 の実データ（high）' },
    { title: 'Finalize', detail: '版 0.21.0・ノートブック・文書・FIX_PLAN（medium）' },
    { title: 'Review', detail: '原則・回帰（max）、利用者向け（high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで修正（max）' },
    { title: 'Recheck', detail: '修正後の点検（max）' },
  ],
}

const S = args.scratch
const O = `${S}/oracle`
const N = `${S}/n10`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール）で、修正計画の新しい単位「B2（0.21.0）」を作るチームの一員です。
作業ツリーの基点は 6ab1769（0.20.0。main と同じ）。この単位の変更は、コミットしていない差分として作業ツリーに入れる。
単位 B2 で直すもの:
1. N10 とその仲間（ルート2）: PDF で表・図の中の文字・ほかの段落に分断された段落の後ろ・前・途中が照合の窓の外に出て、ルート2 が本文を消す・別の文字に置き換える・
   図の中の文字を足す不具合。行末のハイフンをまたぐ 2 つの直し（「pp.45-58」が「pp.46 59」になる）、段落の最初・最後の黙った違い。
   設計は ${N}/DESIGN_N10.md（3 案を試作で比べて選んだ「組み合わせ C」。必ず全部読む）。試作は ${N}/judge/C_src（0.20.0 の src を写して変えたもの）。
2. en dash: 利用者の決定（決定事項 20）は案 (b)「PDF に合わせて『-』に直す」。DASHES は en dash「–」だけにする（em dash などは利用者の判断を待つ。DESIGN_N10.md 8 章）。
   切り替えの定数・引数は残さなくてよい（残すなら利用者に見えない内部の定数だけ）。
3. 利用者が Colab で 0.20.0 のルート2 を試して見つかった誤り（実データ。tests/private/colab/td1・td2・td3 に元の docx〈tdN.docx〉と出版版 PDF〈tdN.pdf〉。コミットしない。gitignore 済み）:
   - td2 の d56: PDF で図1（2 段ぶち抜きの問題文の図）が段落を分断し、図の中の「。」「…」を本文に足した（「るもの」という確」→「るもの」。。。。。……という確」）。試作 C では直っている。
   - td2 の d365: 「. 51–56.」→「. 5156.」（en dash を消した）。試作 C では「51-56」に直る（決定 20 のとおり）。
   - td1 の d71: 校正で足された「（p1，…，p6 とする）」の数式が PDF の文字に入っていない（pdfium の文字では数式の位置が全角・半角の空白の並びになる。
     例: 「経験的確率 （\\u3000 \\u3000， …， \\u3000 \\u3000とする） が」）。0.20.0 も試作 C も「（，…，とする）」だけを docx に足す。これは
     数式の欠けた文を足すので誤り。新しい規則を作る: PDF の文字の側に、数式など文字として取り出せない部分があると見られる違い（足す・置き換える文字の間や両隣に、
     英文の単語の間でない空白の並び〈全角空白を含む 2 文字以上の空白など〉がある、など）は直さず、理由（例: MATH_WHY「PDF のこの位置には、数式など文字として
     読み取れない部分があるようで、足す文字を決められない」）を付けて 13.2 に出す。PDF の空白は信頼できない（行の両端そろえで句読点の後に空白が入る）ので、
     ふつうの本文の直しを取りこぼさないこと（物差しで確かめる）。docx の数式（OBJ）と並ぶ位置も手がかりになる。
   0.20.0 と試作 C で td1〜3 をルート2 で変換した出力が ${S}/colab_v20/run/base/tdN と ${S}/colab_v20/run/C/tdN にある
   （cd /tmp && PYTHONPATH=<src> python -m jasme_jats /home/user/jstgxmlcng_JASME/tests/private/colab/tdN/tdN.docx --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml
    --pdf …/tdN.pdf --route pdf --ai manual --out <出力先>。td1・td2 は位置を決められない図表があるので --ai manual にする）。
原則（CLAUDE.md の最優先の原則）: XML の本文は、出版版 PDF の本文と 1 文字も違ってはいけない。ルート2 は docx の文字を PDF に合わせて直すが、組版の文字（ページ番号・
誌名の行・柱・投稿受付日）、docx にない図・表の中の文字、ほかの段落の文字を docx に足してはいけない。PDF の本文にある docx の文字を消してはいけない。決められない違いは
docx のまま残し、理由を付けてレポートの 13 章に出す。docx を直すのは pdfdocx.py だけ。
確かめの道具（作業用の場所。コミットしない。使い方は各ファイルの冒頭か DESIGN_N10.md 2 章）:
- pytest: python -m pytest -q（3.13）、PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q（3.10）。別の src を測るときは ${N}/judge/tools/pytest_src.sh（pyproject の pythonpath が
  PYTHONPATH より前に入るので、PYTHONPATH だけでは本体の src を読んでしまう。DESIGN_N10.md 2 章）。
- golden: ${S}/golden/golden.py。0.20.0 の出力は ${N}/golden_base（19 件）。
- 本誌の出版版 PDF 5 本・7 通り: ${N}/judge/realpdf/check.py（--before-src ${N}/judge/base_src --route1。PDF は tests/private/pdf/）。
- 反例集: python ${O}/run_all.py <src> <ケースのファイル…> --name <名前>。ケース: ${O}/cases_seed.py・cases_artifact.py・${S}/rvB2_principle_cases.py（34 件）、
  ${N}/cases_n10.py（146）・cases_n10_guard.py（139）・cases_judge.py（39）・cases_judge2.py（10）、rv89（DESIGN_N10.md 2 章）。cases_layout.py は壊れているので使わない。
- 点検の例と乱数の例: ${N}/judge/tools/run_suites.sh・sum_q.py・run8_all.py・sum_fz.py・cmp_fz.py・viol_kinds.py。210 件: fixB/fixB_all.py --compare。速さ: ${N}/judge/tools/t_speed.py。
- 合格の条件は DESIGN_N10.md 7.4（試作 C の数。これより悪くしない）。
厳守:
- ブランチは claude/jstage-xml-converter-review-dw2f0u のまま。git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- 実際の論文の本文（tests/private の docx・PDF の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る）。実験のファイルは ${S} の下に、担当名を付けて置く。tests/ に一時ファイルを残さない。
- python tests/make_fixtures.py を実行しない。コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブック（ipynb）は直接編集しない（tools/make_notebook.py を直して python tools/make_notebook.py）。
- 自分の担当の最後に python -m pytest -q を実行し、すべて通ることを確かめる（点検の担当も）。
`
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: '何をどう変えたか（関数単位）と、確かめた結果（数で）' },
    tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' },
    deviations: { type: 'string', description: '設計・指示と違えたことと理由' },
    open_issues: { type: 'string' },
  },
  required: ['changed_files', 'summary', 'tests_added', 'pytest_result', 'deviations', 'open_issues'],
}
const ORACLE_SCHEMA = {
  type: 'object',
  properties: {
    cases_file: { type: 'string' },
    count: { type: 'integer' },
    groups: { type: 'string', description: '組ごとの件数と、何を確かめる反例か' },
    base_result: { type: 'string', description: '0.20.0（${N}/judge/base_src）と試作 C（${N}/judge/C_src）での OK/REPORTED/FAIL' },
    notes: { type: 'string' },
  },
  required: ['cases_file', 'count', 'groups', 'base_result', 'notes'],
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    passed_all: { type: 'boolean', description: 'DESIGN_N10.md 7.4 と、この担当の合格の条件をすべて満たしたか' },
    measures: { type: 'string', description: '物差しごとの数（0.20.0・試作 C・実装）' },
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
      problem: { type: 'string' }, evidence: { type: 'string', description: '確かめた方法と結果（実験・テスト）。0.20.0 との比較も' },
      fix: { type: 'string' },
    }, required: ['severity', 'file', 'line', 'problem', 'evidence', 'fix'] } },
  },
  required: ['findings'],
}

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 実装（impl）
（前回はコンテナの再起動で途中で止まった。作業ツリーは 6ab1769 のまま変更なし。途中の調べのファイルが ${S}/b2_impl/ にある〈survey_gaps*.py・survey_lead.py・td_diffs.py・td_objs.py・logs・v・realpdf〉ので、
読んで使えるものは使い、引き継ぐ。実装を見ない担当が作った反例集 ${O}/cases_b2.py〈66 件。0.20.0 と試作 C の結果は ${O}/cases_b2_result.json〉も物差しに使う。）
1. DESIGN_N10.md 6 章の順（6.5 の「入れる順」）で、組み合わせ C を src に入れる。試作 ${N}/judge/C_src の pdfmatch.py・pdfdocx.py（0.20.0 との差分は
   ${N}/judge/C_vs_base_pdfmatch.patch・C_vs_base_pdfdocx.patch）を土台にしてよいが、写すだけでなく読み直し、本体の書き方（コメントの量・名前・日本語の説明）に合わせ、
   使われない定数・関数・試作のための切り替え（ENDASH の "docx" の枝を残すかは上の 2 のとおり。DASHES は「–」だけ）を整理する。pdfmatch.py の冒頭の説明も新しい照合の手順に合わせる。
2. report.py の WHY_MARKS に新しい理由（DISPLACED_WHY・EDGE_WHY・UNSURE_WHY・WHOLE_WHY・MATH_WHY など、実際に使うもの）の添え書きを足す（6.4）。
3. 上の 3 の td1 d71 の形（数式の欠けた挿入）の新しい規則を作る。まず架空の文字の再現テストを作り（0.20.0 で落ちることを確かめる）、規則を入れ、
   物差し（quick・fuzz4・fuzz8・N10・反例集・210 件・実 PDF）で、ふつうの直しを取りこぼしていないこと（試作 C の数より悪くしない）を確かめる。
4. テスト: DESIGN_N10.md 7.1〜7.3 のとおりに tests/test_pdfmatch.py に足す（joint の 43 件、judge の 16 件、reanchor・guard の C で通る形、en dash、7.3 の書き換え 1 件）。
   上の 3 の規則のテストと、td2 d56 の形（段落を分断する図の中の「。」「…」を足さない）の架空のテストも足す。足したテストが 0.20.0（git worktree で 6ab1769）で落ちることを確かめる。
5. 確かめ: pytest（3.13・3.10）、golden（19 件とも 0.20.0 と同じ）、実 PDF 7 通り、反例集すべて、quick・fuzz4・fuzz8、210 件、速さを測り、DESIGN_N10.md 7.4 の条件を満たすことを確かめる。
   td1〜3 をルート2 で変換し（出力は ${S}/b2_impl/colab/tdN）、${S}/colab_v20/run/base・C と比べて、d56・d365・d71 が期待どおりか、ほかに 0.20.0 と違う直しがあれば
   それが正しいか（PDF と docx を見て）を summary に段落 ID と件数で書く（実際の文字は書かない）。
6. 文書（docs/DESIGN.md 4.4 の照合の手順・守り・新しい理由・限界、docs/DEVELOPMENT.md の「残っている課題」）を実装に合わせる。版・ノートブック・FIX_PLAN は仕上げの担当が行うので触らない。
実装の判断に迷ったら、DESIGN_N10.md の理由に戻り、原則（足さない・消さない側に倒す）を優先する。`,
    { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, effort: 'max' })
// 実装を見ない担当（oracle_b2）は前回の実行で終わっている（${O}/cases_b2.py・cases_b2_result.json）。コンテナの再起動の後、作り直さずに使う
const oracle = { cases_file: `${O}/cases_b2.py`, count: 66, result_file: `${O}/cases_b2_result.json`, note: '組・0.20.0 と試作 C の件数・期待に迷ったものは result_file を読む' }
log(`impl: ${impl ? impl.pytest_result : '失敗'} / oracle_b2: ${oracle ? oracle.count + ' 件' : '失敗'}`)

phase('Verify')
const verifies = await parallel([
  () => agent(`${COMMON}
## 担当: 物差しすべてでの確かめ（verify_measures）
作業ツリーの実装（コミットしていない差分）を、DESIGN_N10.md 2 章の物差しすべてで測り、7.4 の合格の条件と比べる。0.20.0（${N}/judge/base_src）と試作 C（${N}/judge/C_src）の数も並べる。
実装を見ない担当が作った反例 ${O}/cases_b2.py も流す（0.20.0・試作 C・実装）。FAIL があれば、期待が原則に合っているかを確かめたうえで、実装の誤りなら problems に書く
（期待の誤りなら、その理由を problems に nit で書く）。新しいテストが 0.20.0 で落ちることも確かめる（7.4 の 40 件以上）。ファイルは変更しない（実験は ${S}/b2_verify/ の下）。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
実装を見ない担当の報告:
${JSON.stringify(oracle, null, 1)}`, { label: 'verify_measures', phase: 'Verify', schema: VERIFY_SCHEMA, effort: 'high' }),
  () => agent(`${COMMON}
## 担当: Colab の実データでの確かめ（verify_colab）
td1・td2・td3 を、作業ツリーの実装でルート2（--ai manual）とルート1（--route docx --pdf …）で変換し（出力は ${S}/b2_verify/colab/<ルート>/tdN）、0.20.0 の出力（${S}/colab_v20/run/base）と比べる。
- 13.1（直した箇所）・13.2（直さなかった箇所）・13.4・13.5・13.6 の違いをすべて段落ごとに挙げ、それぞれ PDF（pypdfium2 の文字。jasme_jats.pdfmatch.extract_pages）と docx を見て、
  実装の結果が正しいか（PDF の本文と同じ文字になったか／決められない違いを 13 章に出しているか／組版の文字・図表の中の文字・ほかの段落の文字を足していないか／本文を消していないか）を判定する。
- d56（td2）・d365（td2）・d71（td1）が期待どおりか。
- 不変性・最終・DTD・J-STAGE のチェックがすべて合格か。XML の本文が直した docx と同じか。
- 13 章の一覧が、編集委員が PDF と見比べられる長さ・文面か（長すぎる一覧、意味の分からない理由の文）。
結果は段落 ID と件数、短い説明で書く（実際の論文の文字は 10 文字以内の引用にとどめる）。誤りは problems に書く。ファイルは変更しない。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify_colab', phase: 'Verify', schema: VERIFY_SCHEMA, effort: 'high' }),
])
const vprobs = verifies.filter(Boolean).flatMap((v, i) => (v.problems || []).map(p => ({ from: ['verify_measures', 'verify_colab'][i], ...p })))
log(`verify: ${verifies.map(v => v ? (v.passed_all ? '合格' : '不合格') : '失敗').join(' / ')}、問題 ${vprobs.length} 件`)

let pre = null
if (vprobs.some(p => p.severity !== 'nit')) {
  pre = await agent(`${COMMON}
## 担当: 確かめで見つかった問題を直す（fix_verify）
（前回はコンテナの再起動で途中で止まった。作業ツリーに途中の変更があるかもしれないので、git diff を確かめて引き継ぐ。確かめの担当の全文の結果は ${S}/b2_verify/verify_measures_result.json・verify_colab_result.json。）
次の問題のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ。
直した後、問題の再現の例と、DESIGN_N10.md 7.4 の物差し（少なくとも pytest 3.13・3.10、golden、実 PDF、反例集すべて〈${O}/cases_b2.py を含む〉、quick、fuzz8、td1〜3）を流し直して summary に書く。
問題:
${JSON.stringify(vprobs, null, 1)}
確かめの担当の数:
${JSON.stringify(verifies.filter(Boolean).map(v => v.measures), null, 1)}`, { label: 'fix_verify', phase: 'Verify', schema: IMPL_SCHEMA, effort: 'max' })
}

phase('Finalize')
const fin = await agent(`${COMMON}
## 担当: 仕上げ（finalize）
1. 版を 0.21.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す（変更がなければそれでよい）。
2. docs/FIX_PLAN.md を更新する:
   - 新しい単位 B2（0.21.0。この単位）と B3（0.22.0。図表の位置。まだ実装しない）を、反映の順序の表の B と C の間に入れ、C〜I の版を 2 つずつ繰り下げる
     （C 0.23.0、D 0.23.1、E 0.24.0、F 0.25.0、G 0.26.0、H 0.27.0、I 0.27.1。本文中の版の記述もすべて合わせる）。
   - 項目の表に、N10（分断された段落。B2）、行末のハイフンをまたぐ 2 つの直し（B2）、段落の最初・最後の黙った違い（B2）、en dash（B2）、
     数式の欠けた挿入（td1 d71 の形。B2）、段落を分断する図の文字の挿入（td2 d56 の形。B2。N10 と同じ根なら N10 に含める）と、
     B3 の項目（AI の回答が途中で切れると位置の指定がすべて失われる〈回答の書式で placements を先頭に・「途中で切れている」の案内を "Unterminated string" でも出す〉、
     AI が注などの本文外の段落の後と答えた図表を不採用にして冒頭に置く〈本文の最後に置く〉、AI でも決められない図表を本文の冒頭に置く〈アンカー段落のすぐ後に置き要対応〉、
     表のセルに画像とキャプションが並ぶ図形を AI なしでは図に組めない〈機械的に組む〉、画像のない図キャプションの直前のキャプションなしの表を図の本体にしない〈組む。組めなければ要対応〉）
     を、既存の番号（N1〜N10）に続けて足す。見つけた経緯は「利用者の Colab での試験（2026-10-18、0.20.0、テストデータ1〜3）」。
   - 利用者に決めてもらったことに、決定事項 20（en dash は案 (b)）、21（AI でも位置を決められない図表は、図が結び付いている段落のすぐ後に仮に置き、要対応として知らせる。
     その段落が本文でなければ本文の最後）、22（表で組んだ図は今のまま〈fig の中に table-wrap〉。キャプションが「図1」なら問題ない）を足す。
   - 単位 B2 の節（理由・前提・設計の要点〈DESIGN_N10.md の結論。3 案を試作で比べて選んだこと〉・テスト・実装で決めたこと）を書く。B3 の節は項目と決定事項から、設計の方針だけ書く。
   - 単位 B が「実装済み」になっていることを確かめ、B2 も「実装済み」にする。
3. docs/DESIGN.md・DEVELOPMENT.md・README.md・CLAUDE.md の記述（照合の手順、13 章、en dash、残っている課題、版）が実装と合うか確かめて直す。docs/fix_plan_repro_tests.py に
   単位 B2 の再現（架空の文字）を足すかを、既存の書き方に合わせて判断する。
4. git diff --stat と git status で、実際の論文の文字が入ったファイル（tests/private 以外）がないか、一時ファイルが残っていないかを確かめる。pytest（3.13・3.10）を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', effort: 'max', text: `原則と文字の不変性（ルート2）: 新しい照合（_backbone・_Joint・_window_lines・_align の照合し直し）と守り（C1〜C5、数式の欠けた挿入の規則、en dash）に、
docx にも PDF の本文にもない文字を足す経路、PDF の本文にある docx の文字を消す経路、決められない違いを黙って落とす経路がないか。境界（窓の端・ページの端・1 ページだけの PDF・
空のページ・ページ番号のない PDF・2 段組みの読み順の逆転・同じ文のくり返し・アンカーの少ない論文・英文の段落・数式の多い段落・表の多い論文・別の記事の PDF）で、0.20.0 より
悪くなる例を実験で探す。反例を作ったら ${S}/rvB2x_principle_cases.py に置く。` },
  { key: 'regression', effort: 'max', text: `回帰とテスト: DESIGN_N10.md 7.4 の物差しすべて（pytest 3.13・3.10、golden、実 PDF 7 通り、反例集すべて〈${O}/cases_b2.py を含む〉、quick、fuzz4、fuzz8、210 件、速さ）と、
Colab の td1〜3（0.20.0 の出力 ${S}/colab_v20/run/base と比べて、悪くなった段落がないか）。新しいテストが 0.20.0 で落ちるか。テストが実装の細部に寄りかかりすぎていないか。
ルート1 の結果（13 章の違いの一覧）が、ルート2 と食い違っていないか。` },
  { key: 'user', effort: 'high', text: `利用者への見え方と文書: レポートの 13 章（新しい理由の文面、13.2・13.6 の長さと読みやすさ、段落ごとのまとめ方）、14 章のチェックリスト、ルート1・2 の冒頭の要約、
Colab の表示（pdf_diff_box など）、README・DESIGN・DEVELOPMENT・CLAUDE.md・FIX_PLAN（B2・B3 の節、決定事項 20〜22、版の繰り下げ）が実装と合っているか。
技術に詳しくない編集委員が、何を見て何をすればよいか分かる文面か。td1〜3 と実 PDF のレポートを実際に読んで確かめる。版が 0.21.0 にそろい、ノートブックが作り直されているか。
実際の論文の本文がコミットされる場所（tests・docs・src）に入っていないか（git diff で確かめる）。` },
]
const reviewOf = (l, extra) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 B2 の実装を厳しく点検する。ファイルは変更しない（実験は ${S}/b2_review/ の下で行う）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.20.0 との比較を evidence に書く）。blocking は原則違反（文字の挿入・脱落）・テストの失敗・
誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.20.0 にもあって B2 で悪くなっていないもの・DESIGN_N10.md 9 章の既知の限界は、
新しく見つけたものだけ nit として書く。問題がなければ findings は空でよい。
${extra}`, { label: `review:${l.key}`, phase: 'Review', schema: FIND_SCHEMA, effort: l.effort })
const reviews = await parallel(LENSES.map(l => () => reviewOf(l, `仕上げの担当の報告:\n${JSON.stringify(fin, null, 1)}`)))
let todo = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
log(`指摘: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length} / nit ${todo.filter(f => f.severity === 'nit').length}`)
const firstFindings = todo

const rounds = []
for (let round = 1; round <= 4 && todo.some(f => f.severity !== 'nit'); round++) {
  phase('Fix')
  const fix = await agent(`${COMMON}
## 担当: 点検の指摘を直す（${round} 回目）
${round === 1 ? `（前回は途中で止まった〈利用者の新しい決定を足すため〉。作業ツリーに途中の変更があるかもしれないので、git diff を確かめて引き継ぐ。点検の担当の全文の結果は ${S}/b2_review/review_*_result.json、確かめの担当は ${S}/b2_verify/*_result.json。）
利用者の新しい決定（決定事項 23、2026-10-19）: en dash 以外のダッシュ（em dash「—」、水平線「―」、マイナス「−」、数字幅のダッシュ「‒」など。今の OTHER_DASHES）も、en dash と同じく PDF に合わせて直す。
- 今 DASH_WHY で直さない違いにしている形（docx のダッシュと、PDF の英数字の後の行末の「-」が並ぶ）も、en dash と同じく PDF の「-」に直す。
- PDF の行末が U+FFFE（字形が分からない）のときは、今までどおり docx のまま（違いにしない）。docx にダッシュがない位置の行末のハイフネーションは、今までどおり足さない。
- 行の途中のダッシュの違い（docx と PDF で別のダッシュ・ハイフン）は、今までどおり PDF の文字に合わせる。
- 使わなくなる DASH_WHY・OTHER_DASHES などは整理する。テスト（em dash・マイナス・水平線の行末と、U+FFFE の行末）を足し・直し、cases_b2 の b2d の組を流す。
- 文書（docs/DESIGN.md、README.md、docs/DEVELOPMENT.md、docs/FIX_PLAN.md の問いと決定事項 23・N13・B2 の節、レポートの文面があれば）を合わせる。点検の nit（README 174 行・FIX_PLAN 209 行の em dash の説明）もこれで解消する。
` : ''}次の指摘のうち blocking と should をすべて直す（指摘が誤っていると確かめた場合は直さず、その理由を deviations に書く）。nit は、直す価値がはっきりしていて小さいものだけ直す。
照合（pdfmatch.py）の直しは、0.20.0 より文字を多く足す・消す例が出ないことを、反例集・点検の例・実 PDF・td1〜3 で確かめる。直した後、DESIGN_N10.md 7.4 の物差し
（少なくとも pytest 3.13・3.10、golden、実 PDF、反例集すべて、quick、fuzz8、td1〜3）を流し直して summary に書く。必要なら文書・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, effort: 'max' })
  phase('Recheck')
  const RECHECK = [LENSES[0], LENSES[1]]
  const rr = await parallel(RECHECK.map(l => () => reviewOf({ ...l, effort: 'max' },
    `${round} 回目の修正の後の点検。直した指摘が本当に直ったか（指摘の再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。
前の指摘:
${JSON.stringify(todo, null, 1)}
修正の担当の報告:
${JSON.stringify(fix, null, 1)}`)))
  todo = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: RECHECK[i].key, ...f })))
  rounds.push({ round, fix, findings: todo })
  log(`${round} 回目の点検: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length} / nit ${todo.filter(f => f.severity === 'nit').length}`)
}

return { impl, oracle, verifies, pre, fin, firstFindings, rounds, remaining: todo }
