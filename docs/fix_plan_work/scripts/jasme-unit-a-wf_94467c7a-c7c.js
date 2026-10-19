export const meta = {
  name: 'jasme-unit-a',
  description: '修正計画の単位 A（0.19.0）を実装し、3 つの観点で反証レビューし、指摘を直す',
  phases: [
    { title: 'Implement', detail: 'M3 → M6+N3 → N2 → N1 → 版・文書・ノートブック（同じ作業ツリーで順に）' },
    { title: 'Review', detail: '原則・回帰・利用者向けの 3 観点で反証' },
    { title: 'Fix', detail: '確かめられた指摘を直す' },
  ],
}

const S = args.scratch
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール）で、修正計画 docs/FIX_PLAN.md の「単位 A（0.19.0）」を実装するチームの一員です。
作業の前に docs/FIX_PLAN.md の「決定事項」「単位 A」「同じファイルを触る順と、既存テストの書き換え」「毎回の共通作業」、付録の該当項目のテスト、
docs/DEVELOPMENT.md の「守るべき原則」を読んでください。単位 A の本文は ${S}/unitA.md にも抜き出してあります。
決定事項 1（M6）は「画像を図に入れ、同じ段落の文字は図の直後に本文の段落として出す」（推奨の前者）です。
計画の行番号は 0.18.1 のもので、前の担当の変更でずれていることがあります。
厳守:
- ブランチは claude/jstage-xml-converter-review-dw2f0u のまま。git commit・push・branch の切り替えはしない（まとめ役が行う）。
- docx の本文の文字を変えるコードを書かない。XML の段落の文字は Emitter.span だけで書く。出力しない段落は理由付きで記録する。
- 新しいテスト用 docx は tests/make_fixtures.py に関数として足し、__main__ にも登録する。ただし生成は、その関数だけを
  python -c で呼んで行う（python tests/make_fixtures.py を実行すると既存の docx・PDF のバイトが変わるため実行しない）。
  conftest.ALL_DOCS に入れる docx は、不変性チェック・最終チェック・DTD・jstage_issues == [] をすべて満たす形にする。内容は架空にする。
- 実験用のファイルは ${S} の下に、自分の担当名を付けたファイル名で置く。tests/ に一時ファイルを残さない。
- コメント・docstring・テストの説明は日本語で、既存の書き方に合わせる。ノートブック（ipynb）は直接編集しない。
- 自分の担当の最後に python -m pytest -q を実行し、すべて通ることを確かめる。通らなければ直す。
- 出力の比較: ${S}/golden/golden.py（使い方は冒頭）。変更前の出力は ${S}/golden/before にある。
`
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: '何をどう変えたか（関数単位）' },
    tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string', description: 'python -m pytest -q の最後の行' },
    deviations: { type: 'string', description: '計画と違う判断をしたところと理由（なければ空）' },
    open_issues: { type: 'string', description: '残った懸念（なければ空）' },
  },
  required: ['changed_files', 'summary', 'tests_added', 'pytest_result', 'deviations', 'open_issues'],
}

const STEPS = [
  { key: 'M3', prompt: `## 担当: M3（w:sdt・w:customXml に包まれた表の行・セル、テキストボックスの段落の読み落とし）
単位 A の M3 の方針どおりに実装する。docx_reader に _children(el, tags) を作り、read_table の行と行の中のセル、_textboxes の段落と表で使う
（入れ子の sdt・customXml も再帰でたどる。既存のセルの sdt の特別扱いは置き換える）。
tests/test_reader.py の test_reader_matches_canonical に逆向きの確認を足す（canonical で空でない段落 ID が、脚注・文末脚注も含めてすべて読まれていること）。
新しい fixture sample_reader.docx（make_reader 関数。ALL_DOCS に入れる）に、sdt に包んだ行、customXml に包んだ行、customXml に包んだセル、
入れ子の sdt に包んだ行、テキストボックスの中の sdt の段落を入れ、test_reader に行数とセルの文字の順序のテスト、テキストボックスの中の
sdt の段落が in_textbox=True で読まれるテストを足す。後の単位（G）で D5・U3・U8 の段落を足す予定なので、拡張しやすい作りにする。` },
  { key: 'M6N3', prompt: `## 担当: M6 と N3（不変性チェックの強化、空白だけの除外、図形の中の画像と文字の段落、空白だけの段落の除外漏れ）
単位 A の M6・N3 の方針どおりに実装する。要点:
- model.Exclusion に blank を足す。ArticlePlan.exclude_blank(para) を作り、理由「空白のみの段落」と blank=True をここだけで作る。今の「空白のみの段落」の呼び出しをすべて置き換える（_drop_blank も）。
- fidelity.verify: 出力と除外の両方にある段落を conflicts に、blank の除外なのに検証側の文字が空白でないものを bad_excluded に記録し、ok の条件に入れる。除外はすべて回して確かめる（setdefault で最初の 1 件だけを見ない）。report.py の 5 章に「変換ツールの不具合」として出す。
- builder.fig: 画像段落の文字が空白だけ（is_ws）のときだけ blank の除外にする。それ以外は除外せず警告にする。
- 決定事項 1: structure.float_mechanical の図（FigNode）を組む枝で、画像だけでない段落（Classifier.is_image_para が偽）の画像を FigNode.extra_images と plan.moved_images に移し（Emitter.skip_images で段落の中には出さない）、その段落は文字ごと図の直後に ('p', q) で出す。キャプションのない枝は今のまま。ai_assist._placement_problem と structure.float_from_spec でも、画像だけでない段落の画像の ID（と、その段落 ID）を body に指定されたら同じ扱いにする（画像は図へ、段落は図の後に p）。
- N3: テキストボックスの段落の除外分岐と、Word の文末脚注の除外で、is_blank の段落は plain() が空でなければ exclude_blank に回す（今は全角空白だけの段落が除外にも出力にもならず、不変性チェックが不合格になる）。
- テスト: tests/test_fidelity.py に conflicts と bad_excluded（同じ段落に除外が 2 件あり 2 件目だけが blank で文字がある場合も）のテスト。make_fixtures に sample_float_text.docx（ALL_DOCS に入れない。テキストボックスに、画像と文字が同じ段落＋図キャプション）を作り、test_floats で、AI を使わない設定でも止まらず文字が図の直後の <p> に出ること、画像が図の <graphic> になること、キャプションのない場合は今のままであることを確かめる。N3 は全角空白だけの段落を含む文字だけのテキストボックスと文末脚注のテストで確かめる（fixture か、テストの中で make_fixtures の部品で作る）。
- 変更後に golden.py を実行し、before との違いがすべて意図したものか確かめる（既存 fixture では変わらない見込み）。` },
  { key: 'N2', prompt: `## 担当: N2（テキストボックスの段落のスタイル・文字で、領域が切り替わる）
単位 A の N2 の方針どおりに実装する。structure.Classifier.split_regions で、図形の中の段落・表（Para.in_textbox または float_id、Table.float_id。
テキストボックスの中の表も）では状態（state）を変えない。図形の中身は、直前にある図形の外のブロックと同じ領域に入れる。
back_heading_by_text と FRONT_EN_ROLES による切り替えも、図形の中の段落では起こさない。前の段落の section_break による切り替えも図形の中の段落では起こさないこと。
新しい fixture sample_structure.docx（make_structure。ALL_DOCS に入れる。後の単位 E・F で D3・D4・D1 の要素を足す予定）に、
本文中のテキストボックスに「英文要旨」スタイルの英語の段落があるもの、「注」だけのテキストボックスがあるもの、を入れる。
テストで、sec の数、引用文献の数、trans-abstract の段落、fn-group の有無が、テキストボックスがない場合と同じになることを確かめる
（docs/fix_plan_repro_tests.py の test_PROBLEM_N2_textbox_style_switches_region の逆）。golden.py で既存 fixture の出力が変わらないことを確かめる。` },
  { key: 'N1', prompt: `## 担当: N1（画像の出力漏れの検出と、暫定の知らせ）
単位 A の N1 の方針どおりに実装する。
- pipeline.convert で、build の後に、読み取った画像（doc.images）のうち、出力した画像（info.images）に入らなかったものを Result.lost_images に記録する。
  隠し文字のランの中の画像（段落のアトムにならないもの）は、隠し文字として扱われているので対象から外すか、理由を分けて記録する。
  記録には画像 ID、段落 ID、場所（plan.locations）、理由の推定（引用文献・題目などの画像を置けない場所、出力しなかった段落の中、など）を持たせる。
- 知らせ: レポートの冒頭（要対応）・9 章・14 章、CLI の標準エラーと終了コード 1、Colab の赤い枠（colab.py に枠の関数を足し、tools/make_notebook.py の手順 5・6 で表示し、
  python tools/make_notebook.py で作り直す）。文面は、技術に詳しくない編集委員が何をすればよいか分かるように（例: Word でその画像を本文の段落に移して変換し直す）。
- 暫定の知らせ（D1・D4 が入るまで）: 文字だけのテキストボックスの段落、Word の文末脚注を除外したときに、件数と対処をレポートの冒頭と 14 章に「要確認」として出す。
  対処の文面: テキストボックスは、問題文などの囲みなら Word でテキストボックスの外（本文の段落）に出して変換し直す。文末脚注は、本文の注（テンプレートの書き方）に移して変換し直す。
- テスト: 引用文献の段落に画像がある docx（テストの中で make_fixtures の部品で作る）で、lost_images に入り、レポートの冒頭・14 章、CLI の終了コード 1 と標準エラーに出ること。
  既存 fixture（AI の模擬回答・ルート2 を含む）では lost_images が 0 件であること。暫定の知らせのテスト。
  docs/fix_plan_repro_tests.py の test_PROBLEM_N1_image_in_reference_is_lost_silently の逆。
- golden.py で既存 fixture の出力の違いを確かめる（レポートに暫定の知らせが加わる fixture があれば、その違いだけであること）。` },
  { key: 'finalize', prompt: `## 担当: 仕上げ（版・ノートブック・文書・再現テスト）
前の担当が単位 A の M3・M6・N3・N2・N1 を実装した。git diff で変更を確かめてから、次を行う。
- 版を 0.19.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
- 文書を直す（日本語、既存の書き方）: docs/DESIGN.md（4 章の不変性チェック: 出力と除外の矛盾・空白の除外の確かめ、画像の出力漏れの検出。6.1: 図形の中の画像と文字の段落の扱い、図形の中の段落で領域が変わらないこと）、
  docs/DEVELOPMENT.md（守るべき原則に exclude_blank と画像の出力漏れの検出、テストの節に新しい fixture: sample_reader・sample_structure・sample_float_text、コードの構成の表の必要な箇所）、
  README.md（変換レポートの見方: 画像の出力漏れ、暫定の知らせ）、CLAUDE.md（原則に、空白だけの除外は exclude_blank、画像の出力漏れも検出する、を短く足す）、docs/STYLE_MAPPING.md（必要なら）。
- docs/fix_plan_repro_tests.py から、単位 A で直った PROBLEM テスト（表の行が sdt の中、出力と除外の重なり、N1、N2、N3）を取り除く（逆にした形は tests/ にある。ないものは tests/ に足す）。残りのテストは今も通ること（tests/ に一時的に写して実行し、消す。手順はファイルの冒頭）。
- docs/FIX_PLAN.md の「反映の順序」の表の単位 A の行に「（実装済み）」と書き足す。
- golden.py を ${S}/golden/after に実行し、before と比べる。違いを一覧にし、それぞれが意図した変更かを判断して summary に書く。
- python -m pytest -q がすべて通ることを確かめる。` },
]

phase('Implement')
const impl = []
for (const st of STEPS) {
  const r = await agent(`${COMMON}\n${st.prompt}\n\nこれまでの担当の結果:\n${JSON.stringify(impl, null, 1)}`,
    { label: `impl:${st.key}`, phase: 'Implement', schema: IMPL_SCHEMA })
  impl.push({ step: st.key, result: r })
  log(`${st.key}: ${r ? r.pytest_result : '失敗'}`)
}

phase('Review')
const FIND_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'should', 'nit'] },
      file: { type: 'string' }, line: { type: 'integer' },
      problem: { type: 'string' }, evidence: { type: 'string', description: '確かめた方法と結果（実験・テスト）' },
      fix: { type: 'string', description: '具体的な直し方' },
    }, required: ['severity', 'file', 'line', 'problem', 'evidence', 'fix'] } },
  },
  required: ['findings'],
}
const LENSES = [
  { key: 'principle', text: '原則と文字の不変性: docx の文字を変える・落とす経路ができていないか。除外は理由付きで、空白以外を黙って落とさないか。canonical_text（検証側）と docx_reader（変換側）と pdfdocx（ルート2）の文字ポリシーがそろっているか。新しい検証（conflicts・bad_excluded・lost_images）が穴なく働き、誤って合格・不合格にしないか。AI の placements の検証と適用が整合しているか。' },
  { key: 'regression', text: '回帰とテスト: 既存の動作（既存 fixture の XML・レポート・AI依頼文、AI の模擬回答、ルート1・2）が意図せず変わっていないか（${S}/golden/before と after を比べ、自分でも golden.py を実行する）。新しいテストが問題を確実に捕まえるか（修正前のコード git stash で落ちるか）。境界ケース（VML のテキストボックス、入れ子の sdt、空の表、画像だけの段落の空白、隠し文字の中の画像、脚注の中の画像）。Python 3.10 で動くか（新しい構文を使っていないか）。' },
  { key: 'user', text: '利用者への見え方と文書: レポート・CLI（終了コード）・Colab の表示が、技術に詳しくない編集委員に分かる文面で、何をすればよいかが書かれているか。ノートブックが作り直されているか（test_notebook）。DESIGN・DEVELOPMENT・README・CLAUDE.md・STYLE_MAPPING が実装と合っているか。版が 0.19.0 にそろっているか。DTD に合う XML か。日本語の書き方が既存とそろっているか。' },
]
const reviews = await parallel(LENSES.map(l => () => agent(`${COMMON.replace('を実装するチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text.replace('${S}', S)}
git diff（main からの差分ではなく、作業ツリーの未コミットの差分: git diff と git status）で、単位 A の実装を厳しく点検する。ファイルは変更しない。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法を evidence に書く）。blocking は原則違反・データの脱落・テストの失敗・誤った合格など反映を止めるべきもの、
should は反映前に直すべきもの、nit は任意。直し方を具体的に書く。問題がなければ findings は空でよい。

実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: `review:${l.key}`, phase: 'Review', schema: FIND_SCHEMA })))
const findings = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ lens: LENSES[i].key, ...f })))
log(`指摘: blocking ${findings.filter(f => f.severity === 'blocking').length} / should ${findings.filter(f => f.severity === 'should').length} / nit ${findings.filter(f => f.severity === 'nit').length}`)

phase('Fix')
let fix = null
if (findings.some(f => f.severity !== 'nit')) {
  fix = await agent(`${COMMON}
## 担当: 点検の指摘を直す
次の指摘のうち blocking と should をすべて直す（指摘が誤っていると確かめた場合は直さず、その理由を deviations に書く）。nit は、直す価値がはっきりしていて小さいものだけ直す。
直した後、python -m pytest -q を通し、golden.py を ${S}/golden/after に実行し直して before との違いを確かめる。必要ならノートブックを作り直す。

指摘:
${JSON.stringify(findings, null, 1)}`, { label: 'fix', phase: 'Fix', schema: IMPL_SCHEMA })
}
return { impl, findings, fix }
