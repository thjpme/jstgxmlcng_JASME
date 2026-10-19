export const meta = {
  name: 'jasme-unit-b-round2',
  description: '単位 B の 2 回目: 反例集で見つかった 3 件を直し、直した部分全体を 3 つの観点で点検し、指摘を直す',
  phases: [
    { title: 'Fix3', detail: '反例集の FAIL 3 件（柱と取り違える本文の行・受付日の後ろの読点・行末の本当のハイフン）' },
    { title: 'Review', detail: '原則・回帰（max）、利用者向け（high）' },
    { title: 'Fix', detail: '確かめられた指摘を直す（max。照合の中心の直しのため）' },
    { title: 'Recheck', detail: '直した部分を原則・回帰の観点で点検（max）。反映を止める指摘がなくなるまで、最大 3 回' },
  ],
}

const S = args.scratch
const O = `${S}/oracle`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール）で、修正計画 docs/FIX_PLAN.md の「単位 B（0.20.0。U7・N9）」を仕上げるチームの一員です。
作業ツリーには、1fe3bc7（0.19.0。main）からのコミットしていない変更として、単位 B の実装と、1 回目の点検の指摘（19 件）の修正が入っている。
docs/FIX_PLAN.md の単位 B の節と「実装で決めたこと」、docs/DESIGN.md 4.4、src/jasme_jats/pdfmatch.py・pdfdocx.py・report.py を読んでから始める。
原則（CLAUDE.md の最優先の原則）: XML の本文は出版版 PDF の本文と 1 文字も違ってはいけない。ルート2 は docx の文字を PDF に合わせて直すが、
組版の文字（ページ番号・誌名の行・柱・投稿受付日）や docx にない図・表の文字・ほかの段落の文字を docx に足してはいけない。PDF の本文にある docx の文字を消してはいけない。
決められない違いは docx のまま残し、レポートの 13 章に出す。docx を直すのは pdfdocx.py だけ。
確かめの道具（作業用の場所。コミットしない）:
- 出力の比較: ${S}/golden/golden.py（使い方は冒頭）。変更前（0.19.0）の出力は ${S}/golden/before_B。違ってよいのは、pdfcheck_route1・route2 のレポートの 13 章の節だけ（XML・AI 依頼文は同じのはず）。
- 実際の出版版 PDF での確認: ${S}/realpdf_B/check.py（使い方は冒頭。--before-src ${S}/realpdf_B/head_src/src --route1 で 0.19.0 と比べる）。PDF は tests/private/pdf/（コミットしない）。
- 実装を見ない担当が作った反例集: python ${O}/run_all.py <src のフォルダ> ${O}/cases_seed.py ${O}/cases_artifact.py --name <名前>（0.19.0 は ${O}/wt_head/src）。cases_layout.py は作りかけで読み込めないので使わない。
- 1 回目の点検の担当の架空の例 210 件: ${S} の下の fixB_all.py（あれば）。
- Python 3.10: PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q
厳守:
- ブランチは claude/jstage-xml-converter-review-dw2f0u のまま。git commit・push・branch の切り替え・stash・reset をしない（まとめ役が行う）。
- 実際の論文の本文をテストやコメントに書き写さない（架空の文字で作る）。実験のファイルは ${S} の下に、自分の担当名を付けて置く。tests/ に一時ファイルを残さない。
- python tests/make_fixtures.py を実行しない。コメント・docstring・テストの説明は日本語で、既存の書き方に合わせる。ノートブック（ipynb）は直接編集しない（tools/make_notebook.py を直して作り直す）。
- 段落の後ろが照合の窓の外に出る既知の不具合（N10。${S}/realpdf_B/exp_tail.py）は、単位 B の後の別の単位で直す。単位 B の変更で悪くなった分だけを扱う。
- 自分の担当の最後に python -m pytest -q を実行し、すべて通ることを確かめる。
`
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: '何をどう変えたか（関数単位）と、確かめた結果（pytest 3.13・3.10、golden、realpdf、反例集の 0.19.0 と単位 B の件数）' },
    tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' },
    deviations: { type: 'string' },
    open_issues: { type: 'string' },
  },
  required: ['changed_files', 'summary', 'tests_added', 'pytest_result', 'deviations', 'open_issues'],
}
const FIND_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'should', 'nit'] },
      file: { type: 'string' }, line: { type: 'integer' },
      problem: { type: 'string' }, evidence: { type: 'string', description: '確かめた方法と結果（実験・テスト）。0.19.0 との比較も' },
      fix: { type: 'string' },
    }, required: ['severity', 'file', 'line', 'problem', 'evidence', 'fix'] } },
  },
  required: ['findings'],
}

phase('Fix3')
const fix3 = await agent(`${COMMON}
## 担当: 反例集で見つかった 3 件を直す（どれも 0.19.0 にもある。単位 B の範囲で直す）
反例集の結果（${O}/results_unitB.json と results_head_v019.json。-v で詳しく出る）で、単位 B のコードでも FAIL の 3 件:
1. art_head_repeated_body_line: 本文の 3 つの段落の最後の行が、どれも同じ「ことが明らかになった。」（11 文字）で、3 ページのページの端に出る。
   柱（3 ページ以上に同じ文字列で出る 8 文字以上の行）として、ページの端の行を流れから除くため、ルート2 で docx の本文の「こ」「が明らかになっ」を消す。
   直し方の方針: ページの端の柱も流れから除かず、ページの途中の柱と同じく「柱の候補の行」（line_only。全体の照合と窓には数えない）にする。
   段落に行全体が当たる（_whole_lines）なら照合に使い、どの段落にも当たらなければ照合に使わない（足さない）。本物の柱（著者名・題目）が段落の途中にあっても足さないこと、
   既存のテスト（柱・ページ番号）がすべて通ること、実際の PDF での結果が変わらないことを確かめる。
2. art_received_both_lines_joined: 受付日の 2 行が、それぞれ本文の行の後ろにつながる（「本文…2025年８月31日投稿受付，」「本文…2025年11月24日採用決定」）。
   1 つ目の日付の後ろの「，」が RE_RECEIVED に入らず、ルート2 で本文に「，」を足す。直し方: 日付の並びの最後にも区切り（「，,、」）を 1 つだけ含めてよいことにする
   （本文の読点を受付日として誤って除かないよう、日付のすぐ後ろの 1 文字だけ）。
3. art_hyphen_real_as_fffe: 英文の本当のハイフン（self-explanation）が行末に来て、PDF の文字の取り出しで U+FFFE（行末のハイフンの印）になる（本誌の引用文献でも実際に出る形）。
   SOFT の文字は照合で無視するので、docx の「-」が違いになって、ルート2 で消す。直し方の方針: docx のハイフン（-、‐ など）が PDF の SOFT の文字（U+FFFE・U+00AD・\\x02、
   英数字の後の行末の「-」）と同じ位置で並ぶときは、同じ文字として扱う（違いにしない。docx のまま）。docx にハイフンがないとき（行末のハイフネーション）は今までどおり足さない。
   出版版で本当にハイフンが消された場合と区別できないので、docx のまま残すのが原則（決められない違いは docx のまま）に合う。
それぞれ、反例と同じ形の合成テスト（架空の文字）を tests/test_pdfmatch.py に足し、変更前のコードで落ちることを確かめる（git worktree を使う。終わったら消す）。
直した後、pytest（3.13・3.10）、golden、realpdf_B/check.py、反例集（0.19.0 と比べて、悪くなった反例がないこと）を実行して結果を summary に書く。
docs/DESIGN.md 4.4 と docs/FIX_PLAN.md の単位 B の「実装で決めたこと」に、3 件の扱いを短く書き足す。`,
  { label: 'fix3', phase: 'Fix3', schema: IMPL_SCHEMA, effort: 'high' })
log(`fix3: ${fix3 ? fix3.pytest_result : '失敗'}`)

phase('Review')
const LENSES = [
  { key: 'principle', effort: 'max', text: `原則と文字の不変性（ルート2）: 1 回目の点検の後に入った仕組み（compare の pf_core と PdfStream.line_only、_window の core の位置の戻し方、
_align で line_only の文字を None にすること、_whole_lines、_page_numbers、短い行の柱の候補、RE_RECEIVED の種類と後ろの区切り、柱を流れから除かない扱い、
docx のハイフンと SOFT の文字）に、docx にも PDF の本文にもない文字を足す経路、PDF の本文にある docx の文字を消す経路がないか。境界（窓の端・ページの端・1 ページだけの PDF・
空のページ・ページ番号のない PDF・ページ番号が飛ぶ PDF・2 段組みの読み順・行が 1 文字だけの表・英文の行末のハイフン）で、0.19.0 より悪くなる例がないかを、実験で探す。
反例集（${O}）と点検の架空の例を使ってよい。新しい反例を作ったら ${S}/rvB2_principle_cases.py に置く。` },
  { key: 'regression', effort: 'max', text: `回帰とテスト: golden（違うのは 13 章の節だけか）、実際の PDF 5 本（realpdf_B/check.py。組版の文字による挿入・削除が 0 件か、わざと入れた違いが期待どおりか、
0.19.0 より悪くなった段落がないか）、反例集（0.19.0 と比べて悪くなった反例がないか）、点検の架空の例 210 件、Python 3.10、照合の速さ（大きな PDF で極端に遅くならないか）。
新しいテストが、直す前のコード（0.19.0 と、1 回目の点検の前の版。前者は git worktree で 1fe3bc7、後者は ${S}/partial_B_review.patch を 1fe3bc7 に当てたもの）で落ちるか。
テストが実装の細部に寄りかかりすぎていないか。` },
  { key: 'user', effort: 'high', text: `利用者への見え方と文書: レポートの 13 章（照合に使わなかった PDF の文字の一覧と説明、HEAD_WHY の文面、段落ごとのまとめ方）、14 章のチェックリストの項目、
ルート1・2 の冒頭の要約、Colab の表示（pdf_diff_box・手順 2 の説明）、README・DESIGN・DEVELOPMENT・CLAUDE.md・FIX_PLAN が実装と合っているか。技術に詳しくない編集委員が、
何を見て何をすればよいか分かる文面か。実際の PDF のレポート（realpdf_B の出力）を読んで、一覧が長すぎないか、本文が混じっていないか。版が 0.20.0 にそろい、ノートブックが作り直されているか。
実際の論文の本文がコミットされる場所（tests・docs・src）に入っていないか（git diff で確かめる）。` },
]
const reviews = await parallel(LENSES.map(l => () => agent(`${COMMON.replace('を仕上げるチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 B の実装を厳しく点検する。ファイルは変更しない（実験は ${S} の下で行う）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.19.0 との比較を evidence に書く）。blocking は原則違反（文字の挿入・脱落）・テストの失敗・誤った合格など反映を止めるべきもの、
should は反映前に直すべきもの、nit は任意。0.19.0 にもあって単位 B で悪くなっていないもの（N10 など）は、新しく見つけたものだけ nit として書き、既知のものは書かない。問題がなければ findings は空でよい。

直前の担当（反例集の 3 件の修正）の報告:
${JSON.stringify(fix3, null, 1)}`, { label: `review:${l.key}`, phase: 'Review', schema: FIND_SCHEMA, effort: l.effort })))
const findings = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
log(`指摘: blocking ${findings.filter(f => f.severity === 'blocking').length} / should ${findings.filter(f => f.severity === 'should').length} / nit ${findings.filter(f => f.severity === 'nit').length}`)

phase('Fix')
// 反映を止める指摘（blocking・should）がなくなるまで、修正と点検をくり返す（最大 3 回）
const rounds = []
let todo = findings
let fix = null
for (let round = 1; round <= 3 && todo.some(f => f.severity !== 'nit'); round++) {
  fix = await agent(`${COMMON}
## 担当: 点検の指摘を直す（${round} 回目）
次の指摘のうち blocking と should をすべて直す（指摘が誤っていると確かめた場合は直さず、その理由を deviations に書く）。nit は、直す価値がはっきりしていて小さいものだけ直す。
指摘に試作（${S} の下の rvB2p/・rvB4_regress/ など）があれば読んでから直す。照合（pdfmatch.py）の直しは、0.19.0 より文字を多く足す・消す例が出ないことを、反例集・点検の例・実際の PDF で確かめる。
直した後、pytest（3.13・3.10）、golden、realpdf_B/check.py、反例集（cases_seed・cases_artifact と、点検の担当が作った ${S}/rvB2_principle_cases.py などがあればそれも）を実行し直して結果を summary に書く。
必要ならノートブックを作り直し、文書（DESIGN.md 4.4 の限界、FIX_PLAN.md の単位 B の「実装で決めたこと」）も合わせる。

指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, effort: 'max' })
  const RECHECK = [
    { key: 'principle', text: '原則と文字の不変性（ルート2）: 今回の修正で、docx にも PDF の本文にもない文字を足す経路、PDF の本文にある docx の文字を消す経路、決められない違いを黙って落とす経路ができていないか。直した指摘が本当に直ったか（指摘の再現の例で確かめる）。0.19.0 より悪くなる例を、境界の形で探す。' },
    { key: 'regression', text: '回帰とテスト: pytest（3.13・3.10）、golden（違うのは 13 章の節だけか）、実際の PDF 5 本（組版の文字による挿入・削除が 0 件か、0.19.0 より悪い段落がないか）、反例集と点検の例（0.19.0 と比べて悪くなったものがないか）、新しいテストが直す前のコードで落ちるか、照合の速さ。' },
  ]
  const rr = await parallel(RECHECK.map(l => () => agent(`${COMMON.replace('を仕上げるチームの一員です', 'の実装を点検する担当です')}
## 点検（${round} 回目の修正の後）: ${l.text}
直前の修正の担当の報告と、その前の指摘を読み、作業ツリーのコミットしていない差分（git diff）で、直した部分を中心に厳しく点検する。ファイルは変更しない（実験は ${S} の下で行う）。
指摘は、実際に確かめたものだけにする（確かめた方法と、0.19.0 との比較を evidence に書く）。blocking は原則違反（文字の挿入・脱落）・テストの失敗・誤った合格、should は反映前に直すべきもの、nit は任意。
0.19.0 にもあって単位 B で悪くなっていないもの（N10、en dash の件など）は、新しく見つけたものだけ nit として書く。問題がなければ findings は空でよい。

前の指摘:
${JSON.stringify(todo, null, 1)}

修正の担当の報告:
${JSON.stringify(fix, null, 1)}`, { label: `recheck:${l.key}:${round}`, phase: 'Recheck', schema: FIND_SCHEMA, effort: 'max' })))
  todo = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: RECHECK[i].key, ...f })))
  rounds.push({ round, fix, findings: todo })
  log(`${round} 回目の点検: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length} / nit ${todo.filter(f => f.severity === 'nit').length}`)
}
return { fix3, findings, rounds, remaining: todo }
