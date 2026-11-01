export const meta = {
  name: 'jasme-unit-i',
  description: '単位 I（0.27.1）: structure.py の分割（動作を変えない。U6 の第 1 段階: 構造のノードと ArticlePlan を article.py に移す）。設計と実装 → 確かめ（出力がバイト単位で同じ） → 仕上げ → 2 観点の点検 → 修正と再点検（最大 3 回）。軽い構成',
  phases: [
    { title: 'Implement', detail: '設計メモと実装（Opus high）' },
    { title: 'Verify', detail: '物差しと、分割の前後の出力の一致（Opus medium）' },
    { title: 'Finalize', detail: '版 0.27.1・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '同一性（Opus high）・構成と文書（Opus medium）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus high）' },
    { title: 'Recheck', detail: '修正後の点検（Opus high・medium）' },
  ],
}

// args: { scratch: 作業用の場所 }
const S = args.scratch
const E = `${S}/i`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「I（0.27.1）: structure.py の分割（動作を変えない）（U6）」を作るチームの一員です。
main と HEAD は __HEAD__（0.27.0。単位 H まで反映済み。detached HEAD）。I の変更は作業ツリーのコミットしていない差分として積む（git commit はまとめ役が行う）。
まず読むもの: docs/FIX_PLAN.md の「I」の節（正本）と項目の表の U6、付録の「### U6」、「同じファイルを触る順と、既存テストの書き換え」、「毎回の共通作業」、
docs/DEVELOPMENT.md の「コードの構成」の表と「守るべき原則」、docs/DESIGN.md の 5 章・6 章（構造の組み立て）、src/jasme_jats/structure.py の全体（約 2,500 行。クラス・関数の一覧を先に作る）、
structure から import している側: src の pdfdocx.py・report.py・ai_assist.py・linker.py・pipeline.py・builder.py と、tests の test_pipeline.py・test_links.py・test_floats.py・test_fidelity.py・test_notes.py・test_refparse.py・test_structure.py、docs/fix_plan_repro_tests.py。
I の内容（FIX_PLAN の I の節が正本。要点）:
- U6 の第 1 段階だけを行う: 新しい src/jasme_jats/article.py に、構造のノード（Sec・PNode・ListNode・QuoteNode・FormulaNode・FigNode・TableNode・FnNode・RefNode・BackSec・BoxNode など、structure.py にあるノードのクラスすべてと FloatInfo・TextBox 関係の記録）、
  ArticlePlan（Decision・exclude・exclude_blank・decide などのメソッドごと）、_para_text を **そのまま**（本体を 1 文字も変えずに）移す。structure.py では「from .article import …  # noqa: F401 互換のため」で再 export し、今 structure から import しているコード・テストは変えなくても動くようにする
  （import 文を article に向け直すのは src の中だけでよい。tests は structure からの import のまま通ること）。structure.py の冒頭の docstring に、処理とメソッドの目次（Classifier の run の流れと、各段階のメソッド名）を書く。
- 第 2 段階（図表の組み立て assemble_floats などの分割）は、この単位では行わない（FIX_PLAN は「第 1 段階だけを推奨」。残る作業として FIX_PLAN の I の節に書く）。
- 動作を 1 つも変えない: XML・AI 依頼文・レポート（版・日時・コミットの行を除く）・直した docx（ルート2）が、分割の前後でバイト単位で同じであること。定数・正規表現・関数の本体は移すだけで書き換えない。ruff の件数は HEAD と同じか減る（移したことで未使用 import が出たら消す。それ以外の整形はしない）。
- 循環 import を作らない（article.py は model・ほかの小さなモジュールにしか依存しない。structure → article の一方向）。
- 新しいテスト: 「python -c 'import jasme_jats.structure, jasme_jats.pipeline'」に当たる、別プロセスでの import のテスト（循環 import は最初の import で落ちる）を tests に足す。
  出力の比較を常設のテスト（tests/test_golden.py）にするかは利用者が決めることなので、この単位では足さず、確かめの道具（${S}/golden/golden.py）での比較にとどめる。
- 版は 0.27.1（出力は変わらないので 3 桁目）。
原則（CLAUDE.md・DEVELOPMENT.md「守るべき原則」）: docx の本文の文字を 1 文字も変えない。この単位は構造の組み立ての置き場所を変えるだけで、判定・出力・知らせのどれにも触れない。
文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従い、文書の側を合わせる。見つけた食い違いは、直したものも直さなかったものも、報告（deviations か checked）にすべて列挙する。
実際の原稿: tests/private/colab/td1〜3（td1.docx〜td3.docx と td?.pdf。コミットしない。文字を書き写さない）。
変換: cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml --route docx --ai manual --out <出力先>（ルート2 は --route pdf --pdf <pdf>）。0.27.0 の src の写しは ${E}/base0270_src（比べる相手）。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider）、ruff check src tests tools（HEAD と比べる）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${E}/golden_base/manifest.json〈0.27.0〉と比べる。23 件すべて XML・AI 依頼文・レポートのハッシュが同じであること。
1 件でも違えば本体を diff して原因を直す〈版の行だけの違いは仕上げの後なら許す〉）、td1〜3 の変換（ルート1・ルート2 で 0.27.0 と XML・レポート・AI 依頼文・直した docx を比べる。版の行以外はバイト単位で同じ）。
厳守:
- git commit・push・branch の切り替え・stash・reset・checkout -- をしない。git worktree は使ってよい（終わったら消す）。pdfmatch.py・pdfdocx.py の照合の規則、linker.py、emit.py、docx_reader.py には触らない（import の向き先を変える以外）。
- python tests/make_fixtures.py を実行しない（fixture は変えない。この単位で新しい fixture は要らない）。
- 実際の論文の本文（tests/private）を、テスト・docs・src・コメントに書き写さない。実験は ${E}/<担当名>/ の下に置く。tests/ に一時ファイル・__pycache__ を残さない。
- ディスクの空きを df -h / で確かめ、担当の最後に大きな出力（docx・pdf・xml・zip・画像）を消す。
- コメント・docstring・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string', description: 'golden 23 件と td1〜3 の一致（ハッシュの比較の結果）、ruff の件数、移した名前の一覧' },
    deviations: { type: 'string', description: '設計（FIX_PLAN の I）と違えたこと・直さなかった指摘と理由・文書とコードの食い違いの列挙' }, open_issues: { type: 'string' },
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
FIX_PLAN の I の節（U6 の第 1 段階）を正本として実装する。先に ${E}/DESIGN_I.md に短い設計メモ（structure.py のクラス・関数の一覧と、article.py に移すもの・残すものの表、import の向き、再 export の形、docstring の目次の案、確かめ方）を書き、それに沿って作業ツリーの src を直す。
手順:
1. 分割の前に、作業ツリー（0.27.0）で golden（${E}/golden_base がまとめ役の作ったもの。自分でも 1 回作って同じことを確かめる）と td1〜3（ルート1・ルート2）の出力を ${E}/impl/before/ に残す（XML・AI 依頼文・レポート・直した docx）。
2. article.py を作り、ノード・ArticlePlan・_para_text を本体を変えずに移す（移した関数・クラスの本体が前後で同じことを、git show HEAD:src/jasme_jats/structure.py から切り出して diff で確かめる）。structure.py は再 export し、冒頭の docstring に目次を書く。src の import は article に向け直してよい（tests は変えない）。
3. 別プロセスの import のテストを tests/test_structure.py（か新しい tests/test_article.py）に足す。
4. docs/DEVELOPMENT.md の「コードの構成」の表に article.py を足し、structure.py の説明を直す。docs/DESIGN.md で structure.py の置き場所を書いている箇所を直す（版・ノートブック・FIX_PLAN・README は仕上げの担当）。
5. pytest（3.13・3.10）・ruff・golden（23 件すべて同じハッシュ）・td1〜3（版の行以外バイト単位で同じ）を流す。1 件でも違えば原因を直す。
文書とコードの食い違いを見つけたら、コードに合わせて直し、deviations に列挙する。`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'high' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、物差し（pytest 3.13・3.10、ruff、golden〈23 件すべて同じハッシュ〉、td1〜3 のルート1・ルート2〈XML・AI 依頼文・レポート・直した docx が版の行以外バイト単位で同じ〉）で測る。
さらに: (1) 移したクラス・関数の本体が HEAD の structure.py と同じか（git show HEAD:src/jasme_jats/structure.py から切り出して diff）。(2) 循環 import がないか（別プロセスで jasme_jats.article / structure / pipeline / builder / linker / ai_assist / report / pdfdocx を 1 つずつ最初に import）。
(3) tests が structure からの import のまま通るか。(4) structure.py の docstring の目次が、実際のメソッド名と順序に合っているか。(5) ruff の件数が HEAD より増えていないか。
ファイルは変更しない（実験は ${E}/verify/ の下）。問題は severity を付けて problems に書く。文書とコードの食い違いを見つけたら problems（nit）に書く。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify', phase: 'Verify', schema: VERIFY_SCHEMA, model: 'opus', effort: 'medium' })
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
1. 版を 0.27.1 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md: 反映の順序の表の I を「（実装済み）」にし、I の節に、移したもの・残したもの・確かめた数（golden 23 件と td1〜3 が同じこと、pytest の件数、ruff）・第 2 段階を行わなかったこと（残る作業）・tests/test_golden.py を常設するかの利用者の判断待ち・文書とコードの食い違いの扱いを書く。
   「同じファイルを触る順と、既存テストの書き換え」の節に I で触ったファイルを入れる。
3. docs/DESIGN.md・DEVELOPMENT.md（コードの構成の表）・README.md（開発者向けのリンクやファイルの説明があれば）・CLAUDE.md（structure.py に触れていれば）・docs/HANDOFF.md が実装と合うか確かめて直す。
4. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'identity', model: 'opus', effort: 'high', text: `同一性: 分割の前後で動作が 1 つも変わっていないか。golden 23 件と td1〜3（ルート1・ルート2）の XML・AI 依頼文・レポート・直した docx が版の行以外バイト単位で同じか（自分で 0.27.0 の src と作業ツリーの両方で変換して比べる）。
移したクラス・関数・定数の本体が HEAD の structure.py と同じか（切り出して diff）。消した・足した行が import・再 export・docstring だけか。循環 import がないか（別プロセスで各モジュールを最初に import）。tests が structure からの import のまま通るか。pytest 3.13・3.10、ruff の件数。` },
  { key: 'structure', model: 'opus', effort: 'medium', text: `構成と文書: article.py と structure.py の分け方が FIX_PLAN の I（U6 の第 1 段階）のとおりか（ノード・ArticlePlan・_para_text は article、判定と組み立ては structure）。structure.py の冒頭の docstring の目次が実際の処理の流れとメソッド名に合っているか。
再 export の形（noqa のコメント）と、src の import の向きが一貫しているか。docs/DEVELOPMENT.md の「コードの構成」の表、DESIGN.md、README、HANDOFF、FIX_PLAN の I の節が実装と合っているか。版が 0.27.1 にそろい、ノートブックが作り直されているか。実際の論文の文字がコミットされる場所に入っていないか。` },
]
const reviewOf = (l, extra, opts) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 I の実装を厳しく点検する。ファイルは変更しない（実験は ${E}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.27.0 との比較を evidence に書く）。blocking は出力が変わるもの（golden・td1〜3 の 1 件でも違う）、本体を書き換えたもの、循環 import、テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。
0.27.0 にもあって I で悪くなっていないものは、新しく見つけたものだけ nit にする。文書とコードの食い違いは、コードに合わせて直す側で指摘し（nit）、checked にも列挙する。問題がなければ findings は空でよい。
${extra}`, { label: `review:${l.key}`, phase: opts.phase, schema: FIND_SCHEMA, model: l.model, effort: l.effort })
const PREV = `仕上げの担当の報告:\n${JSON.stringify(fin, null, 1)}\n確かめの担当の報告:\n${JSON.stringify(verify, null, 1)}`
const reviews = await parallel(LENSES.map(l => () => reviewOf(l, PREV, { phase: 'Review' })))
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
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書とコードの食い違いは、コードに合わせて文書を直す）。FIX_PLAN の I の方針（動作を変えない）の範囲で直す。
直した後、pytest 3.13・3.10・ruff・golden・td1〜3 を流し直す。必要なら文書・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, model: 'opus', effort: 'high' })
  phase('Recheck')
  const rr = await parallel(LENSES.map(l => () => reviewOf(l, `${round} 回目の修正の後の点検。直した指摘が本当に直ったか（再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。blocking・should・nit の基準は 1 回目と同じ。
前の指摘:
${JSON.stringify(todo, null, 1)}
修正の担当の報告:
${JSON.stringify(fix, null, 1)}`, { phase: 'Recheck' })))
  const failedLens = rr.map((r, i) => r ? null : LENSES[i].key).filter(Boolean)
  todo = rr.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
  rounds.push({ round, fix, findings: todo, failedLens })
  log(`${round} 回目の点検: blocking ${todo.filter(f => f.severity === 'blocking').length} / should ${todo.filter(f => f.severity === 'should').length}${failedLens.length ? ' / 失敗した観点: ' + failedLens.join(',') : ''}`)
  if (failedLens.length) { incomplete = failedLens; break }
}
return { impl, verify, pre, fin, reviews, failedFirst, firstFindings, rounds, remaining: todo, incomplete }
