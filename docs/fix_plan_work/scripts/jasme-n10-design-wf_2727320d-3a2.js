export const meta = {
  name: 'jasme-n10-design',
  description: 'N10（段落の後ろ・前が照合の窓の外に出て、ルート2 が本文を消す）とその仲間の直し方を、独立した 3 案の試作で比べ、反証で選ぶ（作業用の場所だけ）',
  phases: [
    { title: 'Design', detail: '3 つの考え方で、それぞれ試作して測る（max）' },
    { title: 'Judge', detail: '同じ物差しで測り直し、反証して 1 つの設計にまとめる（max）' },
  ],
}

const S = args.scratch
const N = `${S}/n10`
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール。main は 0.20.0、コミット 6ab1769）の「ルート2」
（出版版 PDF の文字に合わせて docx を直してから XML にする。src/jasme_jats/pdfmatch.py・pdfdocx.py）の不具合の直し方を設計するチームの一員です。
原則（CLAUDE.md の最優先の原則）: XML の本文は出版版 PDF の本文と 1 文字も違ってはいけない。ルート2 は、組版の文字・docx にない図表の文字・ほかの段落の文字を
docx に足してはいけない。PDF の本文にある docx の文字を消してはいけない。決められない違いは docx のまま残し、レポートの 13 章に理由付きで出す（黙って落とさない）。
まず docs/DESIGN.md 4.4（照合）、docs/DEVELOPMENT.md の「残っている課題」、docs/FIX_PLAN.md の単位 B の「実装で決めたこと」、src/jasme_jats/pdfmatch.py の全体を読む。

## 直す対象（どれも 0.19.0 からあり、単位 B では直していない）
1. N10: PDF の中で段落が長い表・図の中の文字・別の段落（2 段組みの読み順のずれ）に分断されると、段落の後ろ（または前）が照合の窓（_window。段落の長さ＋60 文字ほど）の外に出る。
   そこにある別の文字と並べられて、ルート2 で docx の本文を消したり置き換えたりする。段落は 85% 以上一致するので「照合できた」扱いになり、不変性チェックも合格する。
   再現: ${S}/realpdf_B/exp_tail.py（架空の文字）。本誌の出版版 PDF（tests/private/pdf/。コミットしない）では 30 巻 59 ページと 29 巻 79 ページで起きる
   （${S}/realpdf_B/check.py で確かめられる。確かめ用 docx は PDF の本文から作るので、作業用の場所にだけ置く）。
   段落の最後の文字・数字が窓の中の次の段落・次の文献（「（2019）」など）の文字と偶然一致して、違いにならない（黙って残る）・一部を消す、という仲間の形もある。
2. 行末のハイフンをまたぐ 2 つの直し: docx「pp.45-58」、PDF「pp.46-」（改行）「59」で、まとめた違いの PDF の文字から行末のハイフンが落ち、行の変わり目が空白とみなされて、
   ルート2 で「pp.46 59」になる。再現: ${S}/fixB2/exp/soft_merge.py。
3. 段落の最初・最後の黙った違い: 段落の最初・最後にある PDF にだけある文字（校正で足された一文・「。」など）は、ほかの段落の文字かもしれないとして使わず、記録もしない。
   校正で docx の段落の最後の文字が消されていて、その文字が次の段落の書き出しにもあると、そちらと並べられて違いにならない。どちらも 13 章のどこにも出ない。
4. （利用者の判断待ち。設計には選べる形で入れる）docx の en dash「–」と、PDF の英数字の後の行末の「-」が同じ位置にあると、ルート2 で docx の「–」を消す。
   案 (a) docx のまま残す、案 (b) PDF に合わせて「-」に直す。再現: ${S}/fix3/exp/fix3_endash.py。

## 物差し（どの案も同じもので測る）
- pytest（python -m pytest -q がすべて通る。Python 3.10 は ${S}/venv310）。既存のテストを変えるときは、変える理由を書く。
- golden（${S}/golden/golden.py。0.20.0 の出力を ${N}/golden_base に取り、XML・AI 依頼文が変わらないこと）。
- 本誌の出版版 PDF（${S}/realpdf_B/check.py。--before-src に 0.20.0 の src を渡す。組版の文字による挿入・削除 0 のまま、N10 の段落が直るか、悪くなった段落がないか）。
- 反例集（python ${S}/oracle/run_all.py <src> ${S}/oracle/cases_seed.py ${S}/oracle/cases_artifact.py ${S}/rvB2_principle_cases.py。0.20.0 は 34 件すべて OK）と、点検の担当の例
  （${S}/rvB2p/ の cases_*.py・fuzz_gen.py・fuzz_run.sh、${S}/fixB3/cases_b3_edge.py、${S}/rvB8p/ など。0.20.0 との違いを数える）。
- N10 の新しい反例（${N}/cases_n10.py。最初の設計担当が作り、ほかの担当も使う。架空の文字で、段落の後ろ・前・途中が、短い〜長い（20・60・200・600 文字）表・図の文字・
  別の段落で分断される形、よく似た文字列が近くにある形、校正の直しがその近くにある形）。
- 照合の速さ（7 通りの実 PDF の合計時間。0.20.0 より極端に遅くしない）。

## 厳守
- 本体の作業ツリー（/home/user/jstgxmlcng_JASME）のファイルを変えない。git の状態を変えない（stash・checkout・reset・commit をしない）。
- 試作は ${N}/<自分の担当名>/ に 0.20.0 の src を写して（cp -r /home/user/jstgxmlcng_JASME/src ${N}/<担当名>/src）、そこで直す。テストは、写した src を PYTHONPATH の先頭に入れて
  本体の tests を実行する（PYTHONPATH=${N}/<担当名>/src python -m pytest -q /home/user/jstgxmlcng_JASME/tests。読んだコードが写した方か jasme_jats.__file__ で確かめる）。
- 実際の論文の本文を、試作のテストや設計の文書に書き写さない（架空の文字で作る）。実際の PDF での結果は、段落 ID と件数で書く。
- コメント・文書は日本語で。
`
const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    approach: { type: 'string', description: '考え方の要点（何を、どの関数で、どう変えるか）' },
    prototype_dir: { type: 'string' },
    results: { type: 'string', description: '物差しごとの結果（pytest・golden・実 PDF・反例集・点検の例・N10 の反例・速さ）。0.20.0 との違いを数で' },
    covers: { type: 'string', description: '直る対象（1〜4 のどれ）と、直らない形' },
    risks: { type: 'string', description: '新しく足す・消す経路の危険、境界、0.20.0 より悪くなる例' },
    test_plan: { type: 'string', description: '本体に入れるときのテスト（架空の文字）' },
  },
  required: ['approach', 'prototype_dir', 'results', 'covers', 'risks', 'test_plan'],
}
const APPROACHES = [
  { key: 'reanchor', text: `窓の取り直し: 段落の前・後ろの照合が悪い（一致の塊が窓の端で切れる、最後の一致の後に docx の文字が続くのに PDF の側が別の文字）ときに、
窓の外（その段落の残りの文字列）を PDF の中で探し直し、段落を複数の部分（分断された塊）として照合する。分断の間にある文字は、ほかの段落・照合に使わない文字として扱い、
docx に足さない。最初に ${N}/cases_n10.py（物差しの「N10 の新しい反例」）を作り、ほかの担当が使えるようにする（作った後で、ほかの担当が読むのでファイル名を変えない）。` },
  { key: 'guard', text: `安全側の守り: 照合の仕組みは大きく変えず、直しを決める段階（_classify・_report_regions・pdfdocx.plan_fixes）で、怪しい直しを「直さない違い」（fixable=False・why）
にして 13 章に出す。例: PDF の側が docx より大きく長い置き換え、PDF の側の文字がほかの段落・照合に使わない文字だけの位置での docx の文字の削除、段落の最後の文字の削除で
その文字が次の段落の書き出しにもあるもの、段落の最初・最後にある PDF にだけある文字（黙って捨てずに 13 章に出す）。行末のハイフンをまたぐ 2 つの直しも、まとめ方を直す。
直る数と、直さなくなる（13 章に回る）本当の校正の数の両方を測る。${N}/cases_n10.py がまだなければ、最初の担当が作るのを待たずに自分の分を ${N}/cases_n10_guard.py に作る。` },
  { key: 'joint', text: `まとめての照合: 段落ごとの窓をやめるか補い、全段落を docx の順に、PDF の文字の列へ単調に（順序を保って）割り当てる照合（段落の境目を制約にした動的計画法など）にする。
段落が分断されても、間の文字はどの段落にも割り当てない「すきま」として扱う。2 段組みの読み順のずれ（段落の順序が PDF と違う）は、割り当てられなかった段落を別に探す。
速さに気をつける。${N}/cases_n10.py がまだなければ、自分の分を ${N}/cases_n10_joint.py に作る。` },
]

phase('Design')
const designs = await parallel(APPROACHES.map(a => () => agent(`${COMMON}
## 担当: 直し方の案（${a.key}）を試作して測る
考え方: ${a.text}
対象 1〜3 を直すことを目指し、4 は (a)・(b) を切り替えられる形にする（既定は (b)）。物差しのすべてで測り、0.20.0 との違いを数で書く。うまくいかない形も正直に書く。`,
  { label: `design:${a.key}`, phase: 'Design', schema: DESIGN_SCHEMA, effort: 'max' })))

phase('Judge')
const judge = await agent(`${COMMON}
## 担当: 3 つの案を比べ、1 つの設計にまとめる
3 人の設計担当の試作（下の報告の prototype_dir）を、同じ物差しで自分で測り直す（報告の数を信じず、実行して確かめる）。それぞれの案の弱点を反証で探す
（新しい反例を ${N}/cases_judge.py に作ってよい）。原則（足さない・消さない・決められなければ 13 章に出す）を最もよく守り、本当の校正の直しを取りこぼさず、
速さが許せる設計を選ぶ。案を組み合わせてもよい（例: 照合の改善に、安全側の守りを重ねる）。
${N}/DESIGN_N10.md に、次を書く（日本語。実際の論文の本文は書かない）:
- 選んだ設計と理由、捨てた案と理由（測った数で）
- 関数ごとの変更点（本体に入れる担当がそのまま実装できる細かさ）と、入れる順
- テストの計画（架空の文字。cases_n10 などの反例をテストにする形）と、物差しでの合格の条件
- 4（en dash）の (a)・(b) のそれぞれの実装と影響（利用者が選ぶ）
- 残る限界
返り値の summary には、選んだ設計の要点と、3 案の比べた数を短く書く。

設計担当の報告:
${JSON.stringify(designs, null, 1)}`, { label: 'judge', phase: 'Judge', effort: 'max',
  schema: { type: 'object', properties: { summary: { type: 'string' }, chosen: { type: 'string' }, doc: { type: 'string' }, open_questions: { type: 'string' } }, required: ['summary', 'chosen', 'doc', 'open_questions'] } })
return { designs, judge }
