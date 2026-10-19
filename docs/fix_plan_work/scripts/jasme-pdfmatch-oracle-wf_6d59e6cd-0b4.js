export const meta = {
  name: 'jasme-pdfmatch-oracle',
  description: 'ルート2 の照合を、実装を見ない担当が作る合成の反例集で確かめる仕組みを作る（作業用の場所だけ。単位 B の修正と次の N10 の確かめに使う）',
  phases: [
    { title: 'Runner', detail: '反例集の書式と実行の仕組み（0.19.0 の作業ツリーで動かす）' },
    { title: 'Generate', detail: '配置・組版の文字・校正の 3 つの観点で反例を作る' },
    { title: 'Critique', detail: '期待が原則どおりか反証し、まとめる' },
  ],
}

const S = args.scratch
const O = `${S}/oracle`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール）の「ルート2」を、実装とは独立に確かめる「反例集」を作るチームの一員です。
ルート2 は、docx の段落と出版版 PDF の文字を照合し（src/jasme_jats/pdfmatch.py）、docx の文字を PDF に合わせて直した docx（Word の変更履歴つき）を作り（pdfdocx.py）、それを XML にする。

## 原則（反例の期待はこれだけで決める）
- XML の本文は、出版版 PDF の本文と 1 文字も違ってはいけない。直した docx の段落の文字は XML の本文と同じ。
- PDF にある組版の文字（ページ番号・誌名の行・柱・投稿受付日）、docx にない図・表の中の文字、ほかの段落の文字を、docx の段落に足してはいけない。
- 出版版 PDF の本文にある docx の文字を消してはいけない。
- 直せない違い・決められない違いは、黙って落とさず、レポートの 13 章（照合の違い・直さなかった箇所・PDF の中に見つからない段落・照合に使わなかった PDF の文字）に出す。

## 本誌（『数学教育学研究』）の出版版 PDF の形（tests/private/pdf/ の 5 本で確かめたもの）
- 2 段組み。和文の 1 行はおよそ 24 文字。ページ番号は各ページの最初の行の「（25）」。柱はない（ほかの雑誌の形として、ページの最後のページ番号・「－ 1 －」の形・著者名や題目の柱も考える）。
- 1 ページ目の 2 行目に「全国数学教育学会誌　数学教育学研究　第24巻　第１号　2018　pp.25～36」の形の行がある。
- 投稿受付日「2025年８月31日投稿受付，2025年11月24日採用決定」（再投稿受付が入ることもある）は 1 ページ目にあり、本文の行の後ろにつながる、ページの途中で 2 行にわたる、ページの最後の行になる、などの形で出る。古い号は「（2017.11.30受理）」。docx には普通ない。
- 表のセル・図の中の文字が、段落の途中（ページや段の区切り）に、数字だけの行（「27」「16」）や短い行（「卒」「年目」「表１」）として出る。docx では表は Word の表、図は画像なので、その文字は docx の段落にない。
- 引用文献の「…第29号，pp.11-」の後の改行で「16」だけの行になる。
- 文字の取り出しでは 2 段組みの読み順がずれて、段落が別の段落や図表の文字で分断されることがある（長い表・図の文字・別の段落が、段落の途中に何十〜何百文字も入る）。行末のハイフン（U+FFFE）や制御文字（\\x07）が混じる。
- 既に分かっている不具合（0.19.0 で起きるはず）: N9（ページの途中の数字だけの行をページ番号として除き、引用文献の「16」を消す）、U7（組版の文字を docx に足す）、N10（段落が図表などで分断されると、段落の後ろが照合の範囲の外に出て、本文を消したり置き換えたりする）。

## 厳守
- 本体の作業ツリー /home/user/jstgxmlcng_JASME は、いま別の担当（単位 B の指摘の修正）が書き換えている。その中のファイルを変えない。git の状態を変える操作（stash・checkout・reset・commit・add・branch）をしない。python tests/make_fixtures.py を実行しない（tests/make_fixtures.py の関数を import して使うのはよい）。
- 変更前のコード（0.19.0。コミット 1fe3bc7）は ${O}/wt_head（git worktree）に置く。反例はこのコードで動かして結果を記録する。本体の作業ツリーのコードは途中の状態なので、記録には使わない。
- 実装の内部（_window・_classify などの細かい規則）に合わせて反例を作らない。原則と、上の PDF の形から作る。期待（truth・expect）は原則だけで決め、0.19.0 の結果に合わせない。
- 実際の論文の本文を書き写さない（架空の文字で作る）。tests/private/pdf の PDF を読んで形を確かめるのはよい。
- 作るファイルはすべて ${O} の下に置く。コメント・説明は日本語で、Python 3.10 で動く書き方にする。
`

const RUNNER_SCHEMA = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    format: { type: 'string', description: '反例の書式と補助関数の説明（生成の担当が読む要点）' },
    run_command: { type: 'string' },
    seed_results: { type: 'string', description: '種の反例の 0.19.0 での結果' },
    open_issues: { type: 'string' },
  },
  required: ['files', 'format', 'run_command', 'seed_results', 'open_issues'],
}
const CASES_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    cases: { type: 'array', items: { type: 'object', properties: {
      name: { type: 'string' }, item: { type: 'string' }, description: { type: 'string' },
      expect: { type: 'string' }, head_result: { type: 'string', description: '0.19.0 での判定（OK / REPORTED / FAIL）と理由' },
    }, required: ['name', 'item', 'description', 'expect', 'head_result'] } },
    notes: { type: 'string' },
  },
  required: ['file', 'cases', 'notes'],
}
const CRITIC_SCHEMA = {
  type: 'object',
  properties: {
    total: { type: 'integer' },
    removed_or_fixed: { type: 'array', items: { type: 'string' }, description: '期待が誤っていて直した・除いた反例と理由' },
    fail_on_head: { type: 'array', items: { type: 'string' }, description: '0.19.0 で FAIL の反例（項目ごと）' },
    new_bugs: { type: 'array', items: { type: 'string' }, description: '計画（docs/FIX_PLAN.md）にない新しい不具合: 反例の名前と原因の見立て' },
    run_command: { type: 'string' },
    summary: { type: 'string' },
  },
  required: ['total', 'removed_or_fixed', 'fail_on_head', 'new_bugs', 'run_command', 'summary'],
}

phase('Runner')
const runner = await agent(`${COMMON}
## 担当: 反例集の書式と実行の仕組み
1. ${O} を作り、git -C /home/user/jstgxmlcng_JASME worktree add --detach ${O}/wt_head 1fe3bc7 で変更前のコードを出す（既にあれば使う）。
2. ${O}/runner.py を作る。書式と補助は docstring に書く（生成の担当がこれだけ読んで反例を書けるように）。
   - 1 つの反例は dict: name、angle（layout / artifact / edit）、item（U7・N9・N10 など。分からなければ "new"）、
     paras（docx の段落の並び。(役割, 文字) のリスト。役割は題目・著者・本文・見出し・注・引用文献・英文要旨など、tests/make_fixtures.py の部品で作れるもの。
     docx の表（セルの文字）と画像の段落も置けるようにする）、
     truth（出版版での段落の文字 {paras の番号: 文字}。書かない段落は docx と同じ）、
     pages（extract_pages の代わりに返す各ページの文字。行は \\n）、
     expect（"exact": 直した後の段落が truth と一致すること / "reported": 一致しなくてもよいが、一致しない段落の違いが 13 章に出ること）、note。
   - 補助: wrap(text, width=24)（本誌の 1 行の長さで行に分ける）、page(no, lines)（先頭に「（no）」の行）、誌名の行・受付日の行を作る関数、
     段落の文字を行に分けてページに流し込み、指定した位置に別の行（表の数字・図の文字・別の段落など）を差し込む関数など。
   - run_case(case) -> 段落ごとに、元の docx の文字・直した後の文字（直した docx を読み直したもの）・truth・判定と理由。
     判定: truth と一致すれば OK。一致しないとき、expect が reported で、その段落の違いが 13 章に出ていて（照合の違いの fixable=False・ignored_lines・PDF の中に見つからない段落など）、
     元の docx より truth から遠ざかっていなければ REPORTED。それ以外は FAIL（docx にも truth にもない文字を足した、truth にある文字を消した、など。足した・消した文字を理由に書く）。
     truth を書いていない段落が変わったら FAIL。変換が止まったら FAIL（例外の内容を書く）。
   - pipeline.convert を route="pdf" で、pdfmatch.extract_pages を差し替えて実行する（tests/test_pdfmatch.py のやり方を参考に）。PDF のファイルは空のダミーでよい。
   - ${O}/run_all.py: 「python ${O}/run_all.py <src のフォルダ> [反例のファイル...]」で、指定したコード（PYTHONPATH にそのフォルダを先頭に入れた別のプロセス。どのコードを読んだかを
     jasme_jats.__file__ で確かめて表示する）で反例を実行し、表で結果を出し、JSON を ${O}/results_<名前>.json に保存する。反例のファイルを省いたら ${O}/cases_*.py をすべて。
3. 種の反例を 3 つ ${O}/cases_seed.py に作り、${O}/wt_head/src で実行して仕組みが正しく動くことを確かめる
   （例: 段落の途中のページの区切りに「（2）」があるだけ → OK。受付日が段落の途中の行につながる → FAIL（足す）のはず。引用文献の「pp.11-」「16」→ FAIL（消す）のはず）。`,
  { label: 'runner', phase: 'Runner', schema: RUNNER_SCHEMA, effort: 'high' })
log(`runner: ${runner ? runner.seed_results.slice(0, 200) : '失敗'}`)

phase('Generate')
const ANGLES = [
  { key: 'layout', text: `配置と読み順: 段落がページ・段の区切りで分かれる位置（段落の最初の行の後・途中・最後の行の前）、
段落の途中に入る長い表（数字のセル・語句のセル）・図の中の文字・キャプション・別の段落（読み順のずれ）の長さを変えたもの（10 文字・60 文字・200 文字・500 文字）、
段落の後ろ・前が分断されるもの（N10）、短い段落（見出し・図表のキャプション）、長い段落、引用文献の行分け（「pp.11-」「16」、URL・DOI の途中の改行）、英文の段落の行末のハイフン。` },
  { key: 'artifact', text: `組版の文字: ページ番号の形と位置（ページの最初・最後、「（25）」「－ 1 －」「- 1 -」「25」）、ページの最初の行が数字だけの本文の行のとき、
誌名の行、投稿受付日のすべての形と位置（本文の行につながる、ページの途中で 2 行にわたる、ページの最後、古い「（2017.11.30受理）」）、
柱（8 文字未満の著者名、8 文字以上の題目、2 ページの記事、3 ページ以上）、行末のハイフン（U+FFFE）・制御文字（\\x07）・全角と半角の違い、
本文の中の日付（「2020年８月30日に受付を始めた」など。本文なので照合に使うべきもの）。` },
  { key: 'edit', text: `校正の直し: 出版版で docx から直された文字（置き換え・挿入・削除）を、ページの途中・ページの端の行・組版の文字や表の数字のすぐ隣・段落が分断された位置の近く・引用文献の中・
ページをまたぐ文の中に置いたもの。表の数字と同じ数字の直し（偶然の一致）、本文の日付の直し、全角・半角だけの違い、校正で足された一文がページの端の行にまるごと入るもの、
docx にあって出版版で消された一文。直すべきもの（exact）と、決められないのでレポートに出ればよいもの（reported）を原則から分ける。` },
]
const gens = await parallel(ANGLES.map(a => () => agent(`${COMMON}
## 担当: 反例を作る（観点: ${a.key}）
${O}/runner.py の書式と補助を読み、${O}/cases_${a.key}.py に 12〜20 個の反例を作る。どれも python ${O}/run_all.py ${O}/wt_head/src ${O}/cases_${a.key}.py で 0.19.0 で実行し、結果を記録する。
1 つの反例では 1 つのことを確かめる（原因を切り分けられるように）。本誌の PDF で実際に起きる形と、その少し先の形（もっと長い表、ほかの雑誌の形など）を入れる。
観点の内容: ${a.text}
仕組み（runner.py）に足りないところがあれば、${O}/runner.py は直さず、自分のファイルの中に補助を書く（ほかの担当とぶつからないように）。仕組みの誤りを見つけたら notes に書く。

仕組みの担当の報告:
${JSON.stringify(runner, null, 1)}`, { label: `gen:${a.key}`, phase: 'Generate', schema: CASES_SCHEMA, effort: 'max' })))
log(`反例: ${gens.filter(Boolean).map(g => g.cases.length).join(' / ')}`)

phase('Critique')
const critic = await agent(`${COMMON}
## 担当: 反例集の反証とまとめ
3 人の担当が作った反例（${O}/cases_*.py）を読み、それぞれの truth と expect が原則どおりかを厳しく確かめる。
- pages の文字と truth が食い違っていないか（truth にない文字が PDF の本文の位置にある、など）。組版の文字や図表の文字を本文としていないか。本文を組版の文字としていないか。
- expect の exact と reported の分け方が原則どおりか（決められない違いを exact にしていないか、直せるはずの違いを reported にしていないか）。
- 判定の仕組み（runner.py の run_case）が、FAIL を見逃したり、OK を FAIL にしたりしていないか（わざと誤った出力を与えて確かめる）。
誤った反例は直すか取り除き、仕組みの誤りは runner.py を直す。それぞれ理由を記録する。重複を除く。
python ${O}/run_all.py ${O}/wt_head/src で全反例を 0.19.0 で実行し、FAIL の反例を項目（U7・N9・N10・計画にない新しいもの）ごとにまとめる。
計画（/home/user/jstgxmlcng_JASME/docs/FIX_PLAN.md）にない新しい不具合があれば、再現の反例の名前と原因の見立てを書く。
最後に ${O}/README.md に、ほかのコード（単位 B の修正の後の作業ツリーなど）で実行する手順と、結果の読み方を書く。本体の作業ツリーでは実行しない（途中の状態のため）。

担当の報告:
仕組み: ${JSON.stringify(runner, null, 1)}
反例: ${JSON.stringify(gens, null, 1)}`, { label: 'critic', phase: 'Critique', schema: CRITIC_SCHEMA, effort: 'high' })
return { runner, gens, critic }
