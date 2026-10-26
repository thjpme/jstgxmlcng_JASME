export const meta = {
  name: 'jasme-unit-c',
  description: '単位 C（0.23.0）: アップロード用 ZIP の中身と、書誌情報の入力値（M1+M2・N4・U1）。設計と実装 → 確かめ → 仕上げ → 2 観点の点検 → 修正と再点検（最大 3 回）。軽い構成',
  phases: [
    { title: 'Implement', detail: '設計メモと実装・テスト（Opus high）' },
    { title: 'Verify', detail: '物差しと FIX_PLAN の付録のテスト項目での確かめ（Sonnet medium）' },
    { title: 'Finalize', detail: '版 0.23.0・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '原則・回帰（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus high）' },
    { title: 'Recheck', detail: '修正後の点検。原則・回帰（Opus high）' },
  ],
}

// args: { scratch: 作業用の場所 }
const S = args.scratch
const C = `${S}/c`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「C（0.23.0）: アップロード用 ZIP の中身と、書誌情報の入力値（M1+M2・N4・U1）」を作るチームの一員です。
main と HEAD は 17b3498（0.22.0。単位 B3 まで反映済み）。C の変更は作業ツリーのコミットしていない差分として積む（git commit はまとめ役が行う）。
まず読むもの: docs/FIX_PLAN.md の「C」の節（設計の方針が具体的に書いてある。これが正本）と項目の表の M1・M2・N4・U1、決定事項 2・3、
付録の「M1」「M2」「U1」（設計と点検で挙げたテスト項目。そのまま tests に取り込む）、docs/DEVELOPMENT.md の「守るべき原則」と「毎回の共通作業」（FIX_PLAN）、
docs/JSTAGE_NOTES.md（EMSGM の番号の意味）、src/jasme_jats/package.py・images.py（export_images）・pipeline.py（convert・add_images・Result）・config.py（ArticleMeta.from_dict・_date）・
report.py（10 章・14 章の PDF の行）・cli.py・colab.py、tools/make_notebook.py の手順 3 の説明、tests/test_pipeline.py・tests/test_package.py・tests/test_config.py（あるもの）。
原則（CLAUDE.md）: docx の本文の文字を 1 文字も変えない（この単位は docx の文字に触れない。入力値〈巻・号・ページ・日付〉と ZIP の中身だけ）。
文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従い、文書の側を合わせる。見つけた食い違いは、直したものも直さなかったものも、報告（deviations か checked）にすべて列挙する。
利用者は技術に詳しくない編集委員なので、知らせの文言は、何が起きて、どこを見て、何をすればよいかを短く書く。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider）、ruff check src tests tools（0.22.0 と件数を比べる）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${S}/b3/golden_final/manifest.json〈0.22.0〉と比べる。
違ってよいのは、レポートの 10 章・14 章の文言など意図した変化だけ。違いは本体を diff して 1 つずつ理由を書く）、
td1〜3 の変換（tests/private/colab/tdN/tdN.docx・tdN.pdf。コミットしない。文字を書き写さない。cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml
--pdf <pdf> --route pdf --ai manual --out <出力先>。0.22.0 の src の写しは git archive 17b3498 src/jasme_jats で ${C}/base022_src に作る。ZIP の namelist が記事フォルダの中だけで ASCII だけか、不変性・DTD・J-STAGE のチェックが合格か、XML が 0.22.0 と同じか）。
厳守:
- git commit・push・branch の切り替え・stash・reset・checkout -- をしない。git worktree は使ってよい（終わったら消す）。pdfmatch.py・pdfdocx.py・structure.py には触らない。
- python tests/make_fixtures.py をそのまま実行しない（既存の docx を作り直さない）。この単位では新しい fixture は要らないはず（TEMPLATE に EMF がある）。要るなら make_<名前>() を足してその関数だけを呼ぶ。
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
FIX_PLAN の C の節の「設計の方針」（M1+M2・N4・U1）を正本として実装する。先に ${C}/DESIGN_C.md に短い設計メモ（関数ごとの変更点、決めたこと、FIX_PLAN と違えるなら理由）を書き、それに沿って作業ツリーの src を直す。
- M1+M2: images.export_images(…, keep_dir=None)、package.upload_entries・make_zip・zip_problems・unzipped_files、Result.zip_issues・not_zipped（convert と add_images の両方で計算し直す）、
  レポート 10 章の not_zipped の案内と 14 章の PDF の行、README の 要変換/ の行。EMSGM の番号は docs/JSTAGE_NOTES.md と jstage_rules.py の書き方に合わせる。
- N4: ArticleMeta.from_dict で volume・issue・fpage・lpage を NFKC で正規化し、volume・issue・fpage が英数字でなければ欄の名前と原因の文字を示す ValueError（決定事項 3: 全角の数字は半角にしてその旨を表示する。
  表示の場所は Colab の手順 3 の後の出力と CLI。どう表示するかは既存の書き方に合わせて決め、設計メモに書く）。
- U1: config._date(v, label='日付') を FIX_PLAN のとおり書き直す。make_notebook.py の手順 3 の説明も直す。
テスト: FIX_PLAN の付録 M1・M2・U1 のテスト項目をすべて tests に取り込む（tests/test_pipeline.py など既存のファイルの書き方に合わせる）。足したテストが 0.22.0 の src で落ちることを確かめる
（別の src で pytest を流すには -o pythonpath=tests が要る: python -m pytest -q -p no:cacheprovider -o pythonpath=tests --rootdir . <テスト> を PYTHONPATH=<src> で）。
docs/DESIGN.md（3 章の流れ・4.3・7 章など関係する箇所）、docs/DEVELOPMENT.md（コードの構成の表・テストの節・残っている課題）、docs/JSTAGE_NOTES.md（根拠）を実装に合わせる（版・ノートブック・FIX_PLAN の記録は仕上げの担当）。
pytest（3.13・3.10）・ruff・golden・td1〜3 を流す。文書とコードの食い違いを見つけたら、コードに合わせて直し、deviations に列挙する。`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'high' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、FIX_PLAN の C の節と付録（M1・M2・U1）のテスト項目のすべて、物差し（pytest 3.13・3.10、ruff、golden〈0.22.0 との違いを本体の diff で 1 つずつ確かめる〉、td1〜3 の変換〈ZIP の中身が記事フォルダの中だけで ASCII だけか、
同じ出力フォルダで 2 本続けて変換したときに 2 本目の ZIP に 1 本目が入らないか、EMF のある TEMPLATE の 要変換/ の場所、不変性・DTD・J-STAGE のチェック、XML が 0.22.0 と同じか〉）で測る。
Colab の手順 3 の入力（全角の巻・「31巻」・ゼロ埋めしない日付・和暦）で、知らせの文言が利用者に分かるかも見る（tools/make_notebook.py の該当のセルのコードを読み、同じ関数を呼んで確かめる）。
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
1. 版を 0.23.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md: 反映の順序の表の C を「（実装済み）」にし、C の節に、実装で決めたこと・テスト・確かめた数・残る限界・文書とコードの食い違いの扱いを書く。M1・M2・N4・U1 の行は実装に合わせて必要なら書き直す。
   「同じファイルを触る順と、既存テストの書き換え」の節に C で触ったファイルを入れる。
3. docs/DESIGN.md・DEVELOPMENT.md・README.md・docs/JSTAGE_NOTES.md・docs/fix_plan_repro_tests.py の冒頭の説明が実装と合うか確かめて直す。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', text: `原則と公開への実害: ZIP に入るものが記事フォルダの中の {aid}.xml・今回の PDF・状態が ok/converted/user の画像だけになっているか（手で置いたファイル・前回の残り・ほかの記事・要変換/ が入らない。決定事項 2）。
ZIP に入れなかったものが必ず知らされるか（not_zipped・zip_issues。add_images の後も正しいか）。入力値の正規化で、docx の文字に触れていないか、記事識別子・DOI・ZIP 名・フォルダ名が英数字だけになるか、
全角を半角にしたことが利用者に表示されるか（決定事項 3）、日付の読み取りが FIX_PLAN の範囲どおりで、読めないときの文言に YYYY-MM-DD があるか。実験で、手作りの ZIP・2 本続けての変換・td1〜3 で確かめる。` },
  { key: 'regression', text: `回帰とテスト: pytest 3.13・3.10、ruff、golden（0.22.0 との違いを本体の diff で確かめ、意図した変化だけか）、td1〜3 を 0.22.0 と比べる（ZIP の中身と知らせ以外に違いがないか。XML は同じか）。
足したテストが 0.22.0 で落ちるか。FIX_PLAN の付録 M1・M2・U1 のテスト項目がすべてテストにあるか。新しい規則（zip_problems の (a)〜(d)、N4 の正規化、_date）を外す・弱めるとテストが落ちるか。Colab の手順 2・3・7 と CLI の --pdf・--images の案内が実装と合うか。` },
]
const reviewOf = (l, extra) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 C の実装を厳しく点検する。ファイルは変更しない（実験は ${C}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.22.0 との比較を evidence に書く）。blocking は公開に実害が出るもの（記事フォルダの外のファイルや日本語の名前が ZIP に入る、
docx の文字が変わる、必要なファイルが黙って ZIP から落ちる）・テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.22.0 にもあって C で悪くなっていないものは、新しく見つけたものだけ nit にする。
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
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書とコードの食い違いは、コードに合わせて文書を直す）。FIX_PLAN の C の方針と原則の範囲で直す。
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
