export const meta = {
  name: 'jasme-unit-d',
  description: '単位 D（0.23.1）: 要対応の知らせ方を 1 か所にまとめる（U2・M4・N5）。設計と実装 → 確かめ → 仕上げ → 2 観点の点検 → 修正と再点検（最大 3 回）。軽い構成',
  phases: [
    { title: 'Implement', detail: '設計メモと実装・テスト（Opus high）' },
    { title: 'Verify', detail: '物差しと FIX_PLAN の付録のテスト項目での確かめ（Sonnet medium）' },
    { title: 'Finalize', detail: '版 0.23.1・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '原則・回帰（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus high）' },
    { title: 'Recheck', detail: '修正後の点検。原則・回帰（Opus high）' },
  ],
}

// args: { scratch: 作業用の場所 }
const S = args.scratch
const C = `${S}/d`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「D（0.23.1）: 要対応の知らせ方を 1 か所にまとめる（レポート・Colab・コマンドライン）（U2・M4・N5）」を作るチームの一員です。
main と HEAD は 3e0f0d6（0.23.0。単位 C まで反映済み）。D の変更は作業ツリーのコミットしていない差分として積む（git commit はまとめ役が行う）。
まず読むもの: docs/FIX_PLAN.md の「D」の節（設計の方針が具体的に書いてある。これが正本。行番号は 0.18.1 当時のもので今とは違う）と項目の表の U2・M4・N5、決定事項 4・5、
付録の「U2」「M4」（設計と点検で挙げたテスト項目。そのまま tests に取り込む）、docs/DEVELOPMENT.md の「守るべき原則」と「毎回の共通作業」（FIX_PLAN）、
src/jasme_jats/report.py（render の冒頭・14 章・images_to_prepare・upload_issues などの知らせ）・pipeline.py（Result・forced_floats・lost_images・pdf_check・docx_fix・unresolved_after）・
colab.py（unplaced_box・figure_body_box・pdf_diff_box などの枠）・cli.py（終了コードと標準エラー）・ai_assist.py（call_api の例外の扱い）、tools/make_notebook.py の手順 5・6・8、
tests/test_pipeline.py・tests/test_colab.py・tests/test_notebook.py・tests/test_pdfmatch.py・tests/test_floats.py・tests/test_ai.py。
原則（CLAUDE.md）: docx の本文の文字を 1 文字も変えない（この単位は docx の文字にも XML・ZIP の形にも触れない。知らせ方〈レポートの冒頭・14 章、Colab の赤い枠と手順 8 の止め方、CLI の終了コードと標準エラー〉を 1 か所〈report.Action・actions()〉にまとめるだけ）。
B3・C で足した知らせ（仮に置いた図表、図の本体、途中で切れた回答、ZIP の検査、ZIP に入れなかったファイル、入力値の正規化）も、今の文面を変えずに actions() に集める。
文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従い、文書の側を合わせる。見つけた食い違いは、直したものも直さなかったものも、報告（deviations か checked）にすべて列挙する。
利用者は技術に詳しくない編集委員なので、知らせの文言は、何が起きて、どこを見て、何をすればよいかを短く書く。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider）、ruff check src tests tools（0.23.0 の 197 件と比べる）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${S}/c/golden_final/manifest.json〈0.23.0〉と比べる。
XML と AI 依頼文は同じであること。レポートの冒頭・14 章は文面を変えない方針なので、違いがあれば本体を diff して 1 つずつ理由を書く）、
td1〜3 の変換（tests/private/colab/tdN/tdN.docx・tdN.pdf。コミットしない。文字を書き写さない。cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml
--pdf <pdf> --route pdf --ai manual --out <出力先>。0.23.0 の src の写しは git archive 3e0f0d6 src/jasme_jats で ${C}/base023_src に作る。XML と ZIP が 0.23.0 と同じか、レポートの冒頭・14 章の知らせが同じ内容を保っているか、終了コードが設計どおりか）。
厳守:
- git commit・push・branch の切り替え・stash・reset・checkout -- をしない。git worktree は使ってよい（終わったら消す）。pdfmatch.py・pdfdocx.py・structure.py・builder.py には触らない。
- python tests/make_fixtures.py をそのまま実行しない（既存の docx を作り直さない）。この単位では新しい fixture は要らないはず（既存の PDFCHECK・NOTES・TEMPLATE と monkeypatch で足りる）。要るなら make_<名前>() を足してその関数だけを呼ぶ。
- 実際の論文の本文（tests/private）を、テスト・docs・src・コメントに書き写さない。実験は ${C}/<担当名>/ の下に置く。tests/ に一時ファイル・__pycache__ を残さない。
- ディスクの空きを df -h / で確かめ、担当の最後に大きな出力（docx・pdf・xml・zip・画像）を消す。
- コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string' },
    deviations: { type: 'string', description: '設計（FIX_PLAN の C）と違えたこと・直さなかった指摘と理由・文書とコードの食い違いの列挙' }, open_issues: { type: 'string' },
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
    checked: { type: 'string', description: '何をどう確かめたか。文書とコードの食い違いもここに列挙する' },
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'should', 'nit'] },
      file: { type: 'string' }, line: { type: 'integer' },
      problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' },
    }, required: ['severity', 'file', 'line', 'problem', 'evidence', 'fix'] } },
  },
  required: ['checked', 'findings'],
}

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 設計と実装（impl）
FIX_PLAN の D の節の「設計の方針」（U2・M4・N5）を正本として実装する。先に ${C}/DESIGN_D.md に短い設計メモ（Action の一覧〈level・key・冒頭の文・14 章の行・枠の見出しと本文〉、関数ごとの変更点、決めたこと、FIX_PLAN と違えるなら理由）を書き、それに沿って作業ツリーの src を直す。
- U2: report.Action と actions(r)。level は「要対応」（CLI の終了コード 1、Colab の手順 8 で一度止める、赤い枠）と「要確認」（赤い枠・冒頭・14 章だけ。終了コード 0）。今ある冒頭の文・14 章の行・枠の文面は変えずに移す
  （不変性チェック不合格、仮に置いた図表、図の本体、途中で切れた回答、画像不足、XML に入らなかった画像、ルート1 の PDF との違い、J-STAGE のチェック〈jstage_issues + zip_issues〉、DTD 不合格、AI のエラー〈手動と API で見出しを書き分ける〉、
  別の記事の PDF の疑い〈要確認〉、柱とみなした行の件数〈要確認〉）。ルート2 の「docx を直してから変換しました」の案内と 14 章の「Word で開き、変更履歴を確認する」は actions() に入れず、今の条件のまま固定の部分に残す。not_zipped は 10 章の警告のまま。
  Result.ok は変えず property needs_action を足す。cli.main は要対応の一覧を標準エラーに出し、return 1 if res.needs_action else 0（2 は中止のまま。--meta なしでも 1 になることを README に明記）。colab.result_boxes(res) を作り、make_notebook.py の手順 5・6 の個別の枠を置き換え、
  手順 8 の「一度止める」を要対応すべてに広げる（画像不足のときの文面は変えない）。B3 の枠（unplaced_box・figure_body_box・partial の枠）と C の表示（アップロード時チェック・not_zipped）もこの仕組みに載せる。既存テストの修正は FIX_PLAN のとおり（test_cli_images_option、tests/test_pdfmatch.py の --meta）。
- M4: Result に property pdf_fallback。report.pdf_suspect(r)。colab.pdf_diff_box は not pc.ok のときに空文字を返さず、ルート2 は「出版版 PDF に合わせられませんでした」、ルート1 は「照合できませんでした」の赤い枠。pdf_suspect のときは「別の記事の PDF かもしれません」の枠。
  どちらも actions() に入れる。手順 8 の説明と手順 5 の 1 行も直す。
- N5: cli.main で API キーがなければ ap.error で止める。call_api でも TypeError を out.error にする。
テスト: FIX_PLAN の付録 U2・M4 のテスト項目をすべて tests に取り込む（既存のファイルの書き方に合わせる。N5 は CLI と call_api の単体テスト）。足したテストが 0.23.0 の src で落ちることを確かめる
（別の src で pytest を流すには PYTHONPATH=<src> python -m pytest -q -p no:cacheprovider -o pythonpath=tests --rootdir . <テスト>）。
docs/DESIGN.md（3 章・関係する箇所）、docs/DEVELOPMENT.md（コードの構成の表・テストの節・残っている課題。「利用者に知らせることは report.actions() に足す」の原則）、README（終了コードの意味、要対応・要確認の見方）を実装に合わせる（版・ノートブック・FIX_PLAN の記録は仕上げの担当）。
pytest（3.13・3.10）・ruff・golden・td1〜3 を流す。文書とコードの食い違いを見つけたら、コードに合わせて直し、deviations に列挙する。`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'high' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、FIX_PLAN の D の節と付録（U2・M4）のテスト項目のすべて、物差し（pytest 3.13・3.10、ruff、golden〈0.23.0 との違いを本体の diff で 1 つずつ確かめる。XML・AI 依頼文は同じ、レポートの冒頭・14 章の文面は保たれているか〉、
td1〜3 の変換〈XML・ZIP が 0.23.0 と同じか、レポートの冒頭と 14 章の知らせが同じ内容か、終了コードが設計どおりか〉）で測る。
Colab の手順 5・6・8 のセル（tools/make_notebook.py）を、要対応のある res・要確認だけの res・何もない res で exec して、赤い枠と「一度止める」の動きが設計どおりかを見る（tests/test_notebook.py の書き方を参考に）。CLI は、--meta なし、画像不足、J-STAGE のチェックの要対応、PDF を読めない場合、API キーなしの各場合で終了コードと標準エラーを確かめる。
ファイルは変更しない（実験は ${C}/verify/ の下）。問題は severity を付けて problems に書く。文書とコードの食い違いを見つけたら problems（nit）に書く。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify', phase: 'Verify', schema: VERIFY_SCHEMA, model: 'sonnet', effort: 'medium' })
let pre = null
if (verify && (verify.problems || []).some(p => p.severity !== 'nit')) {
  pre = await agent(`${COMMON}
## 担当: 確かめで見つかった問題を直す（fix_verify）
次の問題のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。直した後、pytest 3.13・3.10・ruff・golden・td1〜3 を流し直す。
問題:
${JSON.stringify(verify.problems, null, 1)}
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'fix_verify', phase: 'Verify', schema: IMPL_SCHEMA, model: 'opus', effort: 'high' })
}

phase('Finalize')
const fin = await agent(`${COMMON}
## 担当: 仕上げ（finalize）
1. 版を 0.23.1 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md: 反映の順序の表の D を「（実装済み）」にし、D の節に、実装で決めたこと（Action の一覧）・テスト・確かめた数・残る限界・文書とコードの食い違いの扱いを書く。U2・M4・N5 の行は実装に合わせて必要なら書き直す。
   「同じファイルを触る順と、既存テストの書き換え」の節に D で触ったファイルを入れる。「計画全体で足した作業」の CLAUDE.md の D の 1 行（利用者に知らせることは report.actions() に足す。CLI の終了コード）は、CLAUDE.md に実際に足す。
3. docs/DESIGN.md・DEVELOPMENT.md・README.md・docs/fix_plan_repro_tests.py の冒頭の説明が実装と合うか確かめて直す（直した単位の再現テストがそのファイルにあれば取り除く）。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', text: `知らせの網羅と正しさ: 利用者に知らせるべきことが 1 つも落ちていないか（0.23.0 で冒頭・14 章・Colab の枠・CLI に出ていた知らせが、すべて actions() から同じ文面で出るか。B3・C で足した知らせも）。
要対応と要確認の区別が決定事項 5 のとおりか（AI の回答を反映できなかったとき・手動モードで回答を貼り戻す前・不変性チェック不合格は要対応。PDF がないときは 14 章だけ）。CLI の終了コードが、要対応で 1・中止で 2・それ以外 0 になるか。
Colab の手順 8 が要対応のときに一度止まり、もう一度でダウンロードできるか。ルート2 で PDF を読めないときに続けて知らせるか（決定事項 4）。docx の文字・XML・ZIP に変化がないか。実験で、各場合の res を作って確かめる。` },
  { key: 'regression', text: `回帰とテスト: pytest 3.13・3.10、ruff、golden（0.23.0 との違いを本体の diff で確かめ、XML・AI 依頼文が同じで、レポートの違いが意図した範囲か）、td1〜3 を 0.23.0 と比べる。
足したテストが 0.23.0 で落ちるか。FIX_PLAN の付録 U2・M4 のテスト項目がすべてテストにあるか。Action を 1 つ外す・level を入れ替えるとテストが落ちるか（網羅の守り）。make_notebook.py の手順 5・6・8 のセルの exec テストがあるか。README の終了コードの説明が実装と合うか。` },
]
const reviewOf = (l, extra) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 D の実装を厳しく点検する。ファイルは変更しない（実験は ${C}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.22.0 との比較を evidence に書く）。blocking は利用者に知らせるべきことが黙って落ちるもの（0.23.0 では出ていた知らせが出ない、要対応なのに終了コード 0・手順 8 で止まらない）、docx の文字・XML・ZIP が変わるもの、テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.23.0 にもあって D で悪くなっていないものは、新しく見つけたものだけ nit にする。
文書とコードの食い違いは、コードに合わせて直す側で指摘し（nit）、checked にも列挙する。問題がなければ findings は空でよい。
${extra}`, { label: `review:${l.key}`, phase: 'Review', schema: FIND_SCHEMA, model: 'opus', effort: 'high' })
const PREV = `仕上げの担当の報告:\n${JSON.stringify(fin, null, 1)}\n確かめの担当の報告:\n${JSON.stringify(verify, null, 1)}`
const reviews = await parallel(LENSES.map(l => () => reviewOf(l, PREV)))
const failedFirst = reviews.map((r, i) => r ? null : LENSES[i].key).filter(Boolean)
let todo = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
const firstFindings = todo
log(`指摘: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length} / nit ${todo.filter(f => f.severity === 'nit').length}${failedFirst.length ? ' / 失敗した観点: ' + failedFirst.join(',') : ''}`)

const rounds = []
let incomplete = null
for (let round = 1; round <= 3 && todo.some(f => f.severity !== 'nit'); round++) {   // 最大 3 回（CLAUDE.md）
  phase('Fix')
  const fix = await agent(`${COMMON}
## 担当: 点検の指摘を直す（${round} 回目）
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書とコードの食い違いは、コードに合わせて文書を直す）。FIX_PLAN の D の方針と原則の範囲で直す。
直した後、pytest 3.13・3.10・ruff・golden・td1〜3 を流し直す。必要なら文書・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, model: 'opus', effort: 'high' })
  phase('Recheck')
  const rr = await parallel(LENSES.map(l => () => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
${round} 回目の修正の後の点検。直した指摘が本当に直ったか（再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。ファイルは変更しない（実験は ${C}/review/${l.key}/r${round + 1}/ の下）。
blocking・should・nit の基準は 1 回目と同じ。文書とコードの食い違いは、コードに合わせて直す側で指摘し（nit）、checked にも列挙する。
前の指摘:
${JSON.stringify(todo, null, 1)}
修正の担当の報告:
${JSON.stringify(fix, null, 1)}`, { label: `review:${l.key}`, phase: 'Recheck', schema: FIND_SCHEMA, model: 'opus', effort: 'high' })))
  const failedLens = rr.map((r, i) => r ? null : LENSES[i].key).filter(Boolean)
  todo = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
  rounds.push({ round, fix, findings: todo, failedLens })
  log(`${round} 回目の点検: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length}${failedLens.length ? ' / 失敗した観点: ' + failedLens.join(',') : ''}`)
  if (failedLens.length) { incomplete = failedLens; break }
}
return { impl, verify, pre, fin, reviews, failedFirst, firstFindings, rounds, remaining: todo, incomplete }
