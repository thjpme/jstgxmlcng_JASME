export const meta = {
  name: 'jasme-unit-g',
  description: '単位 G（0.26.0）: 読み取りの文字ポリシー（段落記号の削除・スタイルの隠し文字・セルの改行・削除された表の行。D5・U8・U3・N8）。設計と独立の反例 → 実装 → 確かめ → 仕上げ → 3 観点の点検 → 修正と再点検（最大 3 回）',
  phases: [
    { title: 'Design', detail: '設計書 DESIGN_G.md（Opus high）と、実装を見ない担当の架空の docx・期待（Opus high）' },
    { title: 'Implement', detail: '設計どおりに実装し、テストを足す（Opus max）' },
    { title: 'Verify', detail: '物差し（pytest・golden・td1〜3・出版版 PDF）と、独立の反例での確かめ（Opus high）' },
    { title: 'Finalize', detail: '版 0.26.0・ノートブック・文書（Sonnet medium）' },
    { title: 'Review', detail: '原則（Opus max）・回帰（Opus high）・利用者向け（Opus high）' },
    { title: 'Fix', detail: '反映を止める指摘がなくなるまで（Opus max）' },
    { title: 'Recheck', detail: '修正後の点検。原則（Opus max）・回帰（Opus high）' },
  ],
}

// args: { scratch: 作業用の場所 }
const S = args.scratch
const E = `${S}/g`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。利用者は学会の編集委員で Google Colab から使う）で、
修正計画 docs/FIX_PLAN.md の単位「G（0.26.0）: 読み取りの文字ポリシー（段落記号の削除・スタイルの隠し文字・セルの改行・削除された表の行。D5・U8・U3・N8）」を作るチームの一員です。
HEAD は main の c35defd（0.25.0。detached HEAD）。作業ツリーはコミットと同じで、G の変更はコミットしていない差分として積む。
単位 B2.1（照合 pdfmatch.py の守り）は保留中で別の控えにある。G では pdfmatch.py の照合の規則には触らない（ルート2 の pdfdocx.paragraph_units / raw_paragraph_ids / write_fixed_docx の文字ポリシーを、読み取り・検証と同じにするのが G の仕事）。
まず読むもの: docs/FIX_PLAN.md の「G」の節と項目の表の D5・U8・U3・N8、「同じファイルを触る順と、既存テストの書き換え」の docx_reader._textboxes の行、「毎回の共通作業」、付録に D5・U8・U3・N8 の項があればそれも、
docs/DESIGN.md の読み取り（文字ポリシー・隠し文字・変更履歴・テキストボックス）・出力（emit）・レポートの章、docs/DEVELOPMENT.md の「守るべき原則」「残っている課題」、docs/fix_plan_repro_tests.py の test_PROBLEM_deleted_paragraph_mark_keeps_two_paragraphs、
src/jasme_jats/ooxml.py（canonical_text・隠し文字・変更履歴の扱い）、src/jasme_jats/docx_reader.py（read_paragraph・read_block・read_table・_textboxes〈F で TextBox を記録する箇所〉・_read_nested_paragraph・read_notes・_walk）、
src/jasme_jats/fidelity.py（source_texts。不変性チェックの docx 側の文字）、src/jasme_jats/pdfdocx.py（raw_paragraph_ids・paragraph_units・write_fixed_docx。ルート2 で docx を直すときの段落の対応）、
src/jasme_jats/emit.py（Ctx・CELL・Emitter.write_inline・span）、src/jasme_jats/builder.py（セルの出力）、src/jasme_jats/numbering.py（自動番号の label）、src/jasme_jats/report.py（6 章の隠し文字・10 章の警告・actions()）、
tests/make_fixtures.py（Builder・para・run の部品、make_reader〈sample_reader.docx。A で作った〉、変更履歴・隠し文字の部品があるか）、tests/test_reader.py（test_reader_matches_canonical など）、tests/test_fidelity.py・tests/test_pdfdocx.py・tests/test_emit.py があればそれも。
FIX_PLAN に書かれた行番号（L287・L585 など）は古い版のもので当てにならない。名前で探す。FIX_PLAN に出てくる rvz_u8_fixed.py・d5_row.py（計画を作ったときの実験）はもう残っていない。G の節の文面を正本にする。
G の内容（FIX_PLAN の G の節が正本。要点）:
- D5: 段落記号の削除（w:pPr/w:rPr の w:del・w:moveFrom。段落記号の w:vanish〈スタイル区切り〉はつながない）を承諾した状態として、次の段落とつなぐ。ooxml に paragraph_mark_deleted(p)・joined_paragraphs(root)（同じ親の中で、次の兄弟が w:p のときだけ。bookmark などは飛ばす）・
  unjoined_deleted_marks(root)（つなぐ先のない段落とその理由）・canonical_texts(root, prefix, hidden) を足し、読み取り（docx_reader）・検証（fidelity.source_texts）・ルート2（pdfdocx.write_fixed_docx・raw_paragraph_ids・paragraph_units）の 3 か所で同じ規則を使う。
  後の段落の ID は欠番。書式は、前の段落が空なら後の段落のもの、そうでなければ前の段落のもの。sectPr は最後の段落のもの。自動番号は連鎖の最後で 1 回だけ label を呼ぶ。sdt・customXml の境界、表の直前、セル・テキストボックス・注・本文の最後ではつながず、10 章の警告に「承諾できず 2 段落のまま出力した」と出す。
  pStyle の違う段落をつないだときは Decision（4 章）に記録する。F の TextBox の段落一覧は、つないだ後に残った段落だけにする。test_reader_matches_canonical は canonical_texts と比べる形にする。
- U8: ooxml.HiddenRule(styles_root)。style_value(sid) は basedOn をたどり、vanish を最初に指定しているスタイル（いちばん派生した側）の値。para_state は docDefaults の値 XOR 段落スタイルの値。run は、直接の w:vanish があればその値、specVanish なら隠す、rStyle があれば ps XOR style_value(rStyle)、どれもなければ ps。
  canonical_text(p, hidden=None)・docx_reader._walk・pdfdocx.paragraph_units に同じ規則を渡す。数式（m:r）・表スタイル・番号の書式の vanish は扱わないことを文字ポリシー（DESIGN.md）に明記する。隠し文字のレポート（6 章）は w:t とタブしか記録していないので、w:br・w:sym・w:noBreakHyphen にも広げるか、レポートの説明を正確にする。
- U3: emit.Ctx に breaks を足し、CELL = Ctx(breaks=True)。Emitter.write_inline の flush で、書き込み先が jx:span そのもののときだけ \n の前に <break/> を入れる（\n は文字のまま残す。書式の要素はいったん閉じる。リンクの中は今のまま）。p・題目・見出し・引用文献の \n はそのまま出力する。
  レポートの 10 章（警告）に一覧を出し、題目・著者・所属・引用文献にあるものは Action（report.actions()）にする。
- N8: 変更履歴で削除された表の行（w:trPr/w:del）が空の行として出力される。read_table で、w:trPr/w:del があり、かつ canonical_text がすべて空の行だけを読み飛ばし、読み飛ばした行は記録する。削除されたセル（w:tcPr/w:cellDel）も同じ扱いになるかを設計で確かめる。
- 版は 0.26.0（XML の段落の切れ目と <break/> が変わるので 2 桁目）。
- まとめ役の暫定の判断（利用者にはまだ確かめていない。設計書と FIX_PLAN に「暫定」と明記する）: FIX_PLAN の G の「前提」の利用者の確認（Word で sample_reader.docx の段落のつながりとスタイルを見る〈D5〉、スタイルの隠し文字の表示を Word で見る〈U8〉、セルの改行に <break/> を補うか〈U3〉）は、
  利用者が後で行う。G では FIX_PLAN の G の節の規則（LibreOffice で確かめたもの）をそのまま実装し、利用者の確認で違いが出たら直す。画面（Colab・CLI）の文言・見え方は、利用者が後でまとめて直す方針なので、既存の形（赤い枠・手順 8・標準エラー）に Action を足すだけにし、表示の仕組みは変えない。
原則（CLAUDE.md・DEVELOPMENT.md「守るべき原則」）: docx の本文の文字を 1 文字も変えない。文字列を書き換えるコードを書かない（構造は LinkSpec か段落の役割で表す）。XML の段落の文字は Emitter.span() を通す。
「docx の文字」は、Word で表示される文字（変更履歴を承諾し、隠し文字を隠した状態）であり、読み取り（docx_reader）・検証（ooxml.canonical_text / fidelity.source_texts）・ルート2（pdfdocx）の 3 か所が同じ文字ポリシーを使う。G はその文字ポリシーを変える単位なので、3 か所を必ずそろえ、不変性チェックが docx と XML の両側で同じ規則で動くことを確かめる。
出力しない段落は理由付きで記録し（plan.exclude()・exclude_blank()）、出力した段落を除外にも記録しない。つないだ段落は「出力しない段落」ではなく「前の段落に続いた段落」として、不変性チェックの両側で同じにつなぐ（読み飛ばした削除行も記録する）。
要対応・要確認の知らせは report.actions() に Action を足すだけ（個別の表示を render・colab・cli・make_notebook.py に足さない。単位 D の形）。
利用者は技術に詳しくない編集委員なので、知らせの文言は、何が起きて、どこを見て、何をすればよいかを短く書く。
文書（docs・docstring・コメント）と既存のコードの書き方が食い違うときは、コードの書き方に従い、文書の側を合わせる。見つけた食い違いは、直したものも直さなかったものも、報告（deviations か checked）にすべて列挙する。
実際の原稿: tests/private/colab/td1〜3（td1.docx〜td3.docx と td?.pdf。コミットしない。文字を書き写さない。変更履歴・隠し文字・セルの改行・削除された行が実際にあるかを数えてよいが、文字は記録しない）。本誌の出版版 PDF（tests/private/pdf）はルート2 の確かめに使う。
変換: cd /tmp && PYTHONPATH=<src> python -m jasme_jats <docx> --meta /home/user/jstgxmlcng_JASME/examples/meta_example.toml --route docx --ai manual --out <出力先>（ルート2 は --route pdf --pdf <pdf>）。0.25.0 の src の写しは ${E}/base0250_src（比べる相手）。
物差し: pytest（python -m pytest -q -p no:cacheprovider。3.10 は PYTHONPATH=src ${S}/venv310/bin/python -m pytest -q -p no:cacheprovider。指定した src で本体のテストを流すのは sh ${S}/fixB2r4/tools/pytest_src.sh <src> <python> [引数]）、
golden（cd ${S}/n10 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<src> python ${S}/golden/golden.py <出力先> で manifest.json を作り、${E}/golden_base/manifest.json〈0.25.0〉と同じ名前の 23 件で比べる。
違ってよいのは、fixture に D5・U8・U3・N8 の要素を足した sample_reader 系と、意図した出力の変化（つないだ段落、隠した文字、セルの <break/>、消えた削除行、知らせ）だけ。違いは本体を diff して 1 つずつ理由を書く）、
td1〜3 の変換（ルート1 とルート2 で 0.25.0 と XML・レポート・直した docx を比べる。違ってよいのは G で意図したものだけ。不変性・最終・DTD・J-STAGE のチェックは合格。XML に入らなかった画像が増えない）、
ruff（ruff check src tests tools。HEAD より件数を増やさない）。
厳守:
- git commit・push・branch の切り替え・stash・reset・checkout -- をしない（まとめ役が行う）。git worktree は使ってよい（終わったら消す）。
- python tests/make_fixtures.py をそのまま実行して既存の fixture を作り直さない（LibreOffice の版で sample_pdfcheck.pdf のバイト列が変わる）。sample_reader.docx に D5・U8・U3・N8 の要素を足すときは、make_fixtures.py の make_reader（と部品）を直し、
  その関数だけを呼んで作る（例: python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_reader('tests/fixtures/sample_reader.docx')"）。作り直した後に git diff --stat tests/fixtures で、意図した docx だけが変わったことを確かめる。
  新しい docx を足すなら make_<名前>() を足し、末尾の一覧（main）にも入れる。ルート2 の確かめに PDF が要るなら、既存の sample_pdfcheck.pdf を使う（新しい PDF は作らない）。
- 実際の論文の本文（tests/private の docx・PDF の文字）を、テスト・docs・src・コメントに書き写さない（架空の文字で作る）。実験は ${E}/<担当名>/ の下に置く。tests/ に一時ファイルを残さない（tests/__pycache__ も消す）。
- ディスクの空きを df -h / で確かめ、3GB を切りそうなら自分の古い作業ファイルを消す。担当の最後に、大きな出力（docx・pdf・xml・zip・画像）を消す（結果の JSON・ログ・スクリプトは残す）。
- コメント・docstring・テストの説明・文書は日本語で、既存の書き方に合わせる。ノートブックは直接編集しない（python tools/make_notebook.py）。
- 同じコマンド・同じ手順に 2 回続けて失敗したら 3 回目は試さず、原因と、どう続けるかの案を報告に書く。
`
const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    design_doc: { type: 'string', description: `${E}/DESIGN_G.md のパス` },
    decisions: { type: 'string', description: 'D5・U8・U3・N8 ごとに決めたこと（つなぐ条件とつながない境界、書式・sectPr・自動番号の扱い、隠し文字の規則、<break/> の入れ方、削除行・削除セルの扱い、3 か所〈読み取り・検証・ルート2〉のそろえ方、知らせの文言）と、決めなかったこと・却下した案・暫定の判断' },
    changes: { type: 'string', description: 'ファイル・関数ごとの変更点' },
    tests: { type: 'string', description: 'テストの計画（fixture の docx・確かめること・既存テストの修正）' },
    acceptance: { type: 'string', description: '合格の条件（物差しごと。golden・td1〜3・出版版 PDF で変わってよいもの）' },
    risks: { type: 'string' },
  },
  required: ['design_doc', 'decisions', 'changes', 'tests', 'acceptance', 'risks'],
}
const ORACLE_SCHEMA = {
  type: 'object',
  properties: {
    dir: { type: 'string', description: '架空の docx・期待を置いた場所' },
    cases: { type: 'string', description: 'ケースごとの docx・期待（XML の段落の文字とつながり、隠した文字、セルの <break/>、消えた削除行、警告・知らせ、不変性チェックの合否、ルート2 で直した docx の段落）の一覧' },
    runner: { type: 'string', description: '期待と実際を比べる道具の使い方' },
    base_result: { type: 'string', description: '0.25.0（作業ツリーの今の src）での結果' },
    notes: { type: 'string' },
  },
  required: ['dir', 'cases', 'runner', 'base_result', 'notes'],
}
const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' }, tests_added: { type: 'array', items: { type: 'string' } },
    pytest_result: { type: 'string' }, measures: { type: 'string', description: 'golden・td1〜3・出版版 PDF・独立の反例の結果（0.25.0 と並べる）' },
    deviations: { type: 'string', description: '設計と違えたこと・直さなかった指摘と理由・文書とコードの食い違いの列挙' }, open_issues: { type: 'string' },
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
    checked: { type: 'string', description: '何をどう確かめたか。指摘がなくても書く。文書とコードの食い違いもここに列挙する' },
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
G の設計書 ${E}/DESIGN_G.md を書く（コードは変えない。試作は ${E}/design/ の下の写しで）。FIX_PLAN の G の節を正本として、次を決めて書く:
1. 文字ポリシーの今の形: ooxml.canonical_text・docx_reader（read_paragraph・read_block・_walk・_textboxes・_read_nested_paragraph・read_notes・read_table）・fidelity.source_texts・pdfdocx（raw_paragraph_ids・paragraph_units・write_fixed_docx）が、変更履歴・隠し文字・改行・段落の ID をどう扱っているかを読んで表にし、G でそろえる形を決める。
2. D5: paragraph_mark_deleted・joined_paragraphs・unjoined_deleted_marks・canonical_texts の仕様（どの親の中で・どの兄弟を飛ばし・どこでつながないか。sdt・customXml・表の直前・セル・テキストボックス・注・本文の最後）。つないだ段落の ID（前の段落の ID。後は欠番）、書式（前が空なら後の段落のもの）、sectPr、自動番号（連鎖の最後で 1 回）、
   pStyle が違うときの Decision、つなげないときの 10 章の警告の文言。F の TextBox（docx_reader._textboxes）との関係（つないだ後に残った段落だけ）。ルート2 では、直した docx（write_fixed_docx）がつないだ段落をどう扱うか（元の docx の 2 つの w:p のどちらに差し込むか）を決める。
3. U8: HiddenRule の仕様（style_value の basedOn のたどり方、docDefaults、para_state、run の規則、specVanish、rStyle）。canonical_text(p, hidden=None)・_walk・paragraph_units への渡し方。扱わないもの（数式 m:r・表スタイル・番号の書式）の明記。隠し文字のレポート（6 章）の範囲（w:br・w:sym・w:noBreakHyphen）。
   LibreOffice（soffice --headless）が使えるなら、架空の docx を PDF にして表示と比べ、規則が合うことを確かめる（使えなければ FIX_PLAN の規則をそのまま採る）。
4. U3: emit.Ctx の breaks と CELL、write_inline の flush での <break/> の入れ方（jx:span そのもののときだけ。書式の要素を閉じる。リンクの中は今のまま）。DTD で break が置ける場所を確かめる。10 章の一覧と、題目・著者・所属・引用文献の改行の Action（key・level・文言）。
5. N8: read_table で読み飛ばす行の条件（w:trPr/w:del かつ canonical_text がすべて空）と記録のしかた。削除されたセル（w:tcPr/w:cellDel）の扱いを実験で確かめて決める。fidelity.source_texts の側も同じ行を飛ばすこと。
6. td1〜3 と出版版 PDF で、変更履歴の段落記号の削除・スタイルの隠し文字・セルの改行・削除された行が実際に何件あるかを数える（数値だけ記録。文字は書かない）。あれば G の後で出力がどう変わるかを見積もる。
7. テストの計画: tests/make_fixtures.py の部品（段落記号の削除〈w:del・w:moveFrom〉、スタイルの vanish・specVanish・docDefaults の vanish、セルの w:br、削除された行・セル）と sample_reader.docx への追加、tests/test_reader.py・test_fidelity・test_pdfdocx・test_emit などのテスト、
   docs/fix_plan_repro_tests.py の test_PROBLEM_deleted_paragraph_mark_keeps_two_paragraphs の期待を逆にして tests/ に取り込む、境界のテスト（つながない場所、隠し文字の派生スタイル、break を入れない文脈）。ルート2 のテスト（sample_pdfcheck.docx と .pdf でつないだ段落を直す）。
8. 合格の条件: pytest すべて合格、golden は sample_reader 系と意図した変化だけ、td1〜3・出版版 PDF はルート1・ルート2 とも本文の文字が同じで（G で意図した変化だけ）、不変性・DTD 合格、画像の出力漏れが増えない。
9. 残る限界と、利用者に確かめてもらうこと（Word での段落のつながりとスタイル、隠し文字の表示、J-STAGE の試験登載での <break/> の表示。DEVELOPMENT の「残っている課題」）。
設計書は、関数ごとの変更点まで書く（実装の担当が迷わないように）。独立の反例の担当（oracle）とは相談しない。`, { label: 'design', phase: 'Design', schema: DESIGN_SCHEMA, model: 'opus', effort: 'high' }),
  () => agent(`${COMMON}
## 担当: 実装を見ない反例（oracle_g）
あなたは実装を見ない担当です。設計書 ${E}/DESIGN_G.md と、ooxml.py の canonical_text の中身、docx_reader.py の read_paragraph・_walk・read_table の中身、fidelity.py・pdfdocx.py の中身、emit.py の write_inline の中身は読まない（期待が実装に引きずられないように）。
読んでよいもの: FIX_PLAN の G の節・D5・U8・U3・N8、DESIGN.md、docs/fix_plan_repro_tests.py、tests/make_fixtures.py の部品（Builder・para・run・table・cell と make_reader の書き方）、tests/test_reader.py の確かめ方、XML の出力（p・table・break の形。同梱の DTD）、jasme_jats の公開 API（convert・Options・Result）。
FIX_PLAN の G だけから、架空の文字で、原稿（docx）と期待（XML の段落の文字とつながり、隠した文字が XML にないこと、セルの <break/>、消えた削除行、10 章の警告・要対応の有無、不変性チェックの合否、ルート2 で直した docx の段落の対応）の組を 15〜30 件作り、${E}/oracle/ に置く。
docx は make_fixtures.py の部品を import して作る（make_fixtures.py 自体は変えない。足りない部品〈段落記号の w:del・w:moveFrom、スタイルの w:vanish・specVanish、docDefaults の vanish、セルの w:br、w:trPr/w:del・w:tcPr/w:cellDel、sdt・customXml・bookmark の境界〉は自分の生成器 ${E}/oracle/gen_g.py に書く）。範囲:
- D5: 本文の 2 段落の段落記号の削除（つながる。ID は前の段落）／3 段落の連鎖／前が空の段落／pStyle が違う（Decision）／自動番号の段落／sdt の境界・表の直前・セルの最後・テキストボックスの最後・注の最後・本文の最後（つながず警告）／bookmark をはさむ／moveFrom／段落記号の vanish（つながない）。
- U8: 直接の w:vanish／文字スタイルの vanish／段落スタイルの vanish／docDefaults の vanish と段落スタイルで打ち消し／basedOn の派生で反転／specVanish／隠し文字が段落全体（段落が消える）／隠し文字の中の w:br・w:sym。
- U3: セルの中の w:br（<break/>）／本文・題目・見出し・引用文献の w:br（文字のまま、警告。題目などは要対応）／リンクの中の改行／書式（太字など）をまたぐ改行。
- N8: 削除された空の行（消える・記録）／削除マークがあるが文字の残る行（残る）／削除されたセル。
- ルート2: sample_pdfcheck.pdf と組み合わせられるなら、つないだ段落を含む docx をルート2 で変換して、直した docx の段落が壊れないこと。
期待は、FIX_PLAN の方針から一つに決まるものだけ「exact」にし、決めかねるもの（削除されたセル、警告の文言）は「どちらか」（許される結果を列挙）にする。期待と実際を比べる道具 ${E}/oracle/run_g.py を書く（指定した src で変換し、ケースごとに OK/FAIL と理由を出す。
実行してよいのは自分の道具と python -m jasme_jats と jasme_jats の公開 API〈convert・Options〉だけ）。作業ツリーの今の src（0.25.0 の動き）で流し、結果を base_result に書く（期待どおりでないのが G で直すもの）。
新しい架空の文字が実際の論文（tests/private）の文字と 12 文字以上一致しないことを確かめる。`, { label: 'oracle_g', phase: 'Design', schema: ORACLE_SCHEMA, model: 'opus', effort: 'high' }),
])
log(`design: ${design ? 'ok' : '失敗'} / oracle: ${oracle ? 'ok' : '失敗'}`)

phase('Implement')
const impl = await agent(`${COMMON}
## 担当: 実装（impl）
${E}/DESIGN_G.md（設計書）を読み、作業ツリーの src に実装する。設計書に書かれていないことで決める必要が出たら、FIX_PLAN の G の方針と原則に沿って決め、deviations に書く。
テストは設計書の計画どおり tests/make_fixtures.py（部品と make_reader の追加。既存のほかの fixture は作り直さない）・tests/test_reader.py・不変性（fidelity）・ルート2（pdfdocx）・出力（emit）のテストに足す。
足したテストが 0.25.0 の src（${E}/base0250_src。sh ${S}/fixB2r4/tools/pytest_src.sh ${E}/base0250_src python <テスト>）で落ちることを確かめる。docs/fix_plan_repro_tests.py の test_PROBLEM_deleted_paragraph_mark_keeps_two_paragraphs は、期待を逆にして tests/ に取り込み、元のファイルの冒頭の説明を直す。
独立の反例（${E}/oracle。run_g.py の使い方は報告のとおり）も流し、FAIL が残れば、期待が FIX_PLAN の方針に合っているかを確かめたうえで、実装の誤りなら直し、期待の誤りなら理由を書く（反例のファイルは変えない）。
docs/DESIGN.md（読み取りの文字ポリシー・隠し文字・変更履歴・出力・レポートの章）と docs/DEVELOPMENT.md（コードの構成・残っている課題）を実装に合わせる（版・ノートブック・FIX_PLAN・README・CLAUDE.md は仕上げの担当）。pytest（3.13・3.10）・ruff・golden・td1〜3（ルート1・ルート2）を流す。
文書とコードの食い違いを見つけたら、コードに合わせて直し、deviations に列挙する。
設計の担当の報告:
${JSON.stringify(design, null, 1)}
実装を見ない担当の報告:
${JSON.stringify(oracle, null, 1)}`, { label: 'impl', phase: 'Implement', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })

phase('Verify')
const verify = await agent(`${COMMON}
## 担当: 確かめ（verify）
作業ツリーの実装を、設計書の合格の条件と物差し（pytest 3.13・3.10、ruff、golden〈23 件の違いを本体の diff で 1 つずつ確かめる〉、td1〜3 をルート1・ルート2 で 0.25.0 と比べる〈本文の文字が同じこと、G で意図した変化だけか、不変性・DTD・J-STAGE のチェック、画像の出力漏れ、直した docx の段落〉、
本誌の出版版 PDF（tests/private/pdf）のルート2、独立の反例 ${E}/oracle の run_g.py）で測る。自分でも架空の docx を 5 件ほど作り（つながる・つながらない境界、派生スタイルの隠し文字、セルと題目の改行、削除された行とセル）、XML の段落・break・除外の記録・10 章を目で確かめる。
不変性チェックが docx と XML の両側で同じ規則になっているか（つないだ段落・隠した文字・削除行を片側だけで扱っていないか）を、わざと片側を崩す実験で確かめる。
ファイルは変更しない（実験は ${E}/verify/ の下）。問題は severity を付けて problems に書く。文書とコードの食い違いを見つけたら problems（nit）に書く。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'verify', phase: 'Verify', schema: VERIFY_SCHEMA, model: 'opus', effort: 'high' })
let pre = null
if (verify && (verify.problems || []).some(p => p.severity !== 'nit')) {
  pre = await agent(`${COMMON}
## 担当: 確かめで見つかった問題を直す（fix_verify）
次の問題のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。直した後、pytest 3.13・3.10・ruff・golden・td1〜3（ルート1・ルート2）・独立の反例を流し直す。
問題:
${JSON.stringify(verify.problems, null, 1)}
実装の担当の報告:
${JSON.stringify(impl, null, 1)}`, { label: 'fix_verify', phase: 'Verify', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })
}

phase('Finalize')
const fin = await agent(`${COMMON}
## 担当: 仕上げ（finalize）
1. 版を 0.26.0 にする（src/jasme_jats/__init__.py と pyproject.toml）。python tools/make_notebook.py でノートブックを作り直す。
2. docs/FIX_PLAN.md: 反映の順序の表の G を「（実装済み）」にし、G の節に、設計の要点・テスト・実装で決めたこと・暫定の判断（利用者に確かめてもらう: Word での段落のつながりとスタイル〈D5〉、隠し文字の表示〈U8〉、セルの <break/>〈U3〉、削除されたセルの扱い）・確かめた数（td1〜3 と出版版 PDF の件数は数値だけ）・残る限界・
   文書とコードの食い違いの扱いを書く。D5・U8・U3・N8 の行は実装に合わせて必要なら書き直す。「同じファイルを触る順と、既存テストの書き換え」の節に G で触ったファイルを入れる。
3. CLAUDE.md の「最優先の原則」に、FIX_PLAN の「毎回の共通作業」の G の項（段落のつながり〈ooxml.joined_paragraphs〉と隠し文字の判定〈ooxml.HiddenRule〉は、読み取り・検証・pdfdocx で共有する）を、既存の書き方に合わせて 1 項目で足す。docs/DEVELOPMENT.md の「守るべき原則」も同じ内容にそろえる。
4. docs/DESIGN.md、docs/DEVELOPMENT.md、README.md（利用者向けの説明に、段落記号の削除は承諾した状態で読むこと、スタイルの隠し文字も隠すこと、表のセルの改行が <break/> になること、本文などの改行は知らせることを短く）、docs/fix_plan_repro_tests.py の冒頭の説明が実装と合うか確かめて直す。
5. git status と git diff で、実際の論文の文字や一時ファイルが入っていないかを確かめる（tests/private の docx・PDF の文字から作った 12 文字の並びと、足した行を突き合わせる）。pytest（3.13・3.10）・ruff を通す。
実装の担当の報告:
${JSON.stringify(impl, null, 1)}
確かめの担当の報告:
${JSON.stringify(verify, null, 1)}
確かめの修正の担当の報告（あれば）:
${JSON.stringify(pre, null, 1)}`, { label: 'finalize', phase: 'Finalize', schema: IMPL_SCHEMA, model: 'sonnet', effort: 'medium' })

phase('Review')
const LENSES = [
  { key: 'principle', model: 'opus', effort: 'max', text: `原則と文字の不変性: 段落をつなぐ・隠し文字を隠す・<break/> を入れる・削除行を読み飛ばす経路で、docx の文字（Word の表示）が XML から落ちる・二重に出る・別の段落に入る経路、隠すべきでない文字を隠す経路（派生スタイル・docDefaults・specVanish・数式）、
つないではいけない場所でつなぐ経路（sdt・customXml・表の直前・セル・テキストボックス・注・本文の最後）、不変性チェックの docx 側（fidelity.source_texts / canonical_texts）と XML 側が違う規則で動く経路（片側だけでつなぐ・隠す・読み飛ばす）、ルート2 の pdfdocx（raw_paragraph_ids・paragraph_units・write_fixed_docx）が読み取りと違う段落の対応になる経路、
除外・つなぎ・読み飛ばしの記録の漏れ、Emitter.span() を通さない文字、文字列を書き換えるコードがないか。実験で、架空の docx（${E}/oracle のものと自分で作るもの）と td1〜3（ルート1・ルート2）・出版版 PDF で、不変性チェック・lost_images・DTD・直した docx を確かめる。` },
  { key: 'regression', model: 'opus', effort: 'high', text: `回帰とテスト: pytest 3.13・3.10、ruff、golden（23 件の違いを本体の diff で確かめ、意図した変化だけか）、td1〜3（ルート1・ルート2）と出版版 PDF を 0.25.0 と比べる（G で意図した変化以外に違いがないか。テキストボックス〈F〉・図表〈B3〉・注〈E〉・照合〈B2〉が変わっていないか）、独立の反例 ${E}/oracle。
足したテストが 0.25.0 で落ちるか。規則の条件を外す・境界を動かすとテストが落ちるか（つながない場所、隠し文字の規則の各分岐、break を入れない文脈、削除行の条件）。ルート2 の変更履歴つき docx（write_fixed_docx）が Word で開ける形のままか（ooxml の検証・既存のテスト）。` },
  { key: 'user', model: 'opus', effort: 'high', text: `利用者への見え方と文書: レポートの 4 章（Decision）・6 章（隠し文字）・10 章（警告）・14 章、Colab の赤い枠、CLI の文言が、技術に詳しくない編集委員に「何が起きて、どこを見て、何をするか」分かるか（段落をつないだこと、つなげなかったこと、隠した文字、セルの改行を <break/> にしたこと、題目などの改行、消えた削除行）。
README・DESIGN・DEVELOPMENT・CLAUDE.md・FIX_PLAN（G の節・D5・U8・U3・N8・反映の順序の表・毎回の共通作業）が実装と合っているか。版が 0.26.0 にそろい、ノートブックが作り直されているか。
td1〜3 のレポート（ルート1・ルート2）を実際に読む。実際の論文の文字がコミットされる場所に入っていないか。` },
]
const reviewOf = (l, extra, opts) => agent(`${COMMON.replace('を作るチームの一員です', 'の実装を点検する担当です')}
## 点検の観点: ${l.text}
作業ツリーのコミットしていない差分（git diff と git status）で、単位 G の実装を厳しく点検する。ファイルは変更しない（実験は ${E}/review/${l.key}/ の下）。
指摘は、実際にコードを読み、実験やテストで確かめたものだけにする（確かめた方法と、0.25.0 との比較を evidence に書く）。blocking は原則違反（文字の脱落・重複・別の段落への混入、隠すべきでない文字を隠す、不変性チェックの両側の規則の食い違い、ルート2 の docx の破損、画像の出力漏れ、記録漏れ、DTD 不合格）・
テストの失敗・誤った合格など反映を止めるべきもの、should は反映前に直すべきもの、nit は任意。0.25.0 にもあって G で悪くなっていないものは、新しく見つけたものだけ nit にする。
文書とコードの食い違いは、コードに合わせて直す側で指摘し（nit）、checked にも列挙する。問題がなければ findings は空でよい（checked に何を確かめたかを書く）。
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
次の指摘のうち blocking と should をすべて直す（誤りと確かめた場合は直さず、理由を deviations に書く）。nit は小さく価値のあるものだけ（文書とコードの食い違いは、コードに合わせて文書を直す）。FIX_PLAN の G の方針と原則の範囲で直す。
直した後、pytest 3.13・3.10・ruff・golden・td1〜3（ルート1・ルート2）・独立の反例を流し直す。必要なら文書・ノートブックも合わせる。
指摘:
${JSON.stringify(todo, null, 1)}`, { label: `fix:${round}`, phase: 'Fix', schema: IMPL_SCHEMA, model: 'opus', effort: 'max' })
  phase('Recheck')
  const RE = [LENSES[0], LENSES[1]]
  const rr = await parallel(RE.map(l => () => reviewOf(l, `${round} 回目の修正の後の点検。直した指摘が本当に直ったか（再現の例で確かめる）と、修正で新しく壊れたものがないかを中心に見る。blocking・should・nit の基準は 1 回目と同じ。
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
