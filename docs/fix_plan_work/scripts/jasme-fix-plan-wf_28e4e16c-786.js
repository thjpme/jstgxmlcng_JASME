export const meta = {
  name: 'jasme-fix-plan',
  description: 'レビュー指摘ごとに修正方針を設計し、反証で詰め、順序と抜けを点検する',
  phases: [
    { title: 'Design', detail: 'まとまりごとに修正方針を設計（コードは変えない）' },
    { title: 'Critique', detail: '設計を原則・DTD・ルート2・回帰の観点で反証' },
    { title: 'Sequence', detail: '全体の順序・版・依存・抜け・利用者の判断事項' },
  ],
}

const SCRATCH = args.scratch
const COMMON = `
あなたは、リポジトリ /home/user/jstgxmlcng_JASME（論文 docx → J-STAGE 全文 XML 変換ツール）の修正計画を作る担当です。
先に docs/DEVELOPMENT.md と docs/DESIGN.md の関係する章を読み、該当するソースを実際に読んで確かめてください。
厳守:
- リポジトリのファイルは一切変更しない（git の操作もしない）。実験用のスクリプトは ${SCRATCH} の下に、自分専用のファイル名で書く。
- 実験は python スクリプトで行う（例: sys.path に /home/user/jstgxmlcng_JASME/tests を足して make_fixtures を import し、
  JournalConfig.load() と ArticleMeta.from_dict({...}) を直接使って pipeline.convert を呼ぶ）。tests/ にファイルを置かない。
- レビューで問題を再現したテストが ${SCRATCH}/test_review.py にある（読むだけ。各問題の再現手順の参考にする）。
- 最優先の原則: docx の本文の文字を 1 文字も変えない。構造はアトムに LinkSpec を付けるか段落の役割で表す。出力しない段落は理由付きで記録する。
  新しい種類の docx 要素に対応するときは ooxml.canonical_text()（検証側）と docx_reader.py（変換側）の両方を同じ文字ポリシーで直す。
  ルート2（pdfdocx.py）の paragraph_units / raw_paragraph_ids も読み取りと同じ文字ポリシーでなければならない。
- J-STAGE の仕様: docs/JSTAGE_NOTES.md。必要なら ToolSearch で WebFetch を読み込み、
  https://www.jstage.jst.go.jp/static/pages/GuidelineAndManuals/zenbun-xml-jats1_1-manual/-char/ja の該当要素の説明を確かめる。
  XML が同梱 DTD に合うかは jasme_jats.validate.validate で確かめられる。
- 利用者は技術に詳しくない編集委員もいる。将来ほかの人が生成 AI でツールを直せるようにしたい。速度はこだわらない。
- 出力の形が変わる修正は版の 2 桁目、それ以外は 3 桁目を上げる決まり。
文章はすべて日本語で、具体的に（関数名・行・条件）書く。推測ではなく、コードを読み実験して確かめたことを書く。
`

const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          title: { type: 'string' },
          confirmed: { type: 'boolean', description: '指摘が実在すると確かめたか' },
          confirm_note: { type: 'string', description: '確かめた方法と結果。指摘が不正確なら何が違うか' },
          root_cause: { type: 'string' },
          approach: { type: 'string', description: '具体的な修正方針（どの関数をどう変えるか）' },
          alternatives_rejected: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } },
          principle_check: { type: 'string', description: '文字不変・検証側と変換側の両方・ルート2・AI 依頼文への影響' },
          tests: { type: 'string', description: '追加・変更するテストと fixture（make_fixtures.py への追加など）' },
          docs: { type: 'string', description: '直す文書（DESIGN.md、STYLE_MAPPING.md、README など）' },
          output_shape_change: { type: 'boolean' },
          effort: { type: 'string', enum: ['S', 'M', 'L'] },
          risk: { type: 'string' },
          user_decision: { type: 'string', description: '利用者（学会側）が決めるべきこと。なければ空文字' },
        },
        required: ['id', 'title', 'confirmed', 'confirm_note', 'root_cause', 'approach', 'alternatives_rejected', 'files',
          'principle_check', 'tests', 'docs', 'output_shape_change', 'effort', 'risk', 'user_decision'],
      },
    },
    cross_notes: { type: 'string', description: 'まとまりの中の項目どうしの依存・衝突' },
  },
  required: ['items', 'cross_notes'],
}

const CRITIC_SCHEMA = {
  type: 'object',
  properties: {
    reviews: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          verdict: { type: 'string', enum: ['ok', 'revise', 'reject'] },
          problems: { type: 'string', description: '設計の誤り・見落とし（なければ空）' },
          revised_approach: { type: 'string', description: 'revise / reject のときの修正後の方針（ok なら空）' },
          extra_tests: { type: 'string' },
          evidence: { type: 'string', description: '確かめた方法（読んだコード・実験）' },
        },
        required: ['id', 'verdict', 'problems', 'revised_approach', 'extra_tests', 'evidence'],
      },
    },
    missing: { type: 'array', items: { type: 'string' }, description: 'このまとまりで設計に漏れている論点' },
  },
  required: ['reviews', 'missing'],
}

const clusters = args.clusters

phase('Design')
const results = await pipeline(
  clusters,
  c => agent(`${COMMON}
## 担当するまとまり: ${c.name}
次の指摘それぞれについて、(1) 実在するかをコードと実験で確かめ、(2) 根本原因を特定し、(3) 原則を守る具体的な修正方針を設計してください。
コードは書き換えず、方針・変更する関数・テスト・文書・リスク・利用者が決めるべきことを返します。
指摘が誤り・過大なら confirmed=false とし、その理由を書いてください。直す価値が低いものは、その判断と理由を approach に書いてください。

${c.items.map(i => `- ${i.id}: ${i.text}`).join('\n')}
`, { label: `design:${c.key}`, phase: 'Design', schema: DESIGN_SCHEMA }),
  (design, c) => agent(`${COMMON}
## 反証担当: ${c.name}
別の担当者が作った修正方針（下の JSON）を、厳しく点検してください。各項目について、次を実際にコードを読み、必要なら実験して確かめます。
- 文字を変える・落とす経路ができないか。canonical_text と docx_reader の両方、pdfdocx（ルート2）の文字ポリシーがそろうか。
- 出力 XML が同梱 DTD に合うか。J-STAGE の画面で意図どおり表示されるか（仕様で使える要素か）。
- 既存の fixture（tests/fixtures の docx）とテストへの回帰。AI 依頼文・RESPONSE_SCHEMA・apply_ops との整合。
- もっと単純で安全な方法がないか。過剰な修正になっていないか。テストは問題を確実に捕まえるか。
問題がなければ verdict=ok、直すべき点があれば revise と修正後の方針、方針自体が誤りなら reject と代案。

設計:
${JSON.stringify(design, null, 1)}
`, { label: `critique:${c.key}`, phase: 'Critique', schema: CRITIC_SCHEMA })
    .then(critique => ({ cluster: c.key, name: c.name, design, critique })),
)

const done = results.filter(Boolean)
log(`設計と反証: ${done.length}/${clusters.length} まとまり完了`)

phase('Sequence')
const SEQ_SCHEMA = {
  type: 'object',
  properties: {
    batches: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          version: { type: 'string', description: '反映するときの版（現在 0.18.1）' },
          items: { type: 'array', items: { type: 'string' } },
          rationale: { type: 'string' },
          prerequisites: { type: 'string' },
        },
        required: ['name', 'version', 'items', 'rationale', 'prerequisites'],
      },
    },
    conflicts: { type: 'array', items: { type: 'string' } },
    missing: { type: 'array', items: { type: 'string' }, description: '計画全体で抜けている論点・作業' },
    user_decisions: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          question: { type: 'string' },
          options: { type: 'array', items: { type: 'string' } },
          recommendation: { type: 'string' },
          blocks: { type: 'array', items: { type: 'string' }, description: 'この判断を待つ項目 ID' },
        },
        required: ['question', 'options', 'recommendation', 'blocks'],
      },
    },
    common_tasks: { type: 'array', items: { type: 'string' }, description: '版上げ・ノートブック再生成・fixture 再生成など各回に必要な作業' },
  },
  required: ['batches', 'conflicts', 'missing', 'user_decisions', 'common_tasks'],
}
const seq = await agent(`${COMMON}
## 全体の点検と順序づけ
4 つのまとまりについて、設計と反証の結果が下にあります。全体を見て次を返してください。
- 反映の単位（batches）と順序。データ損失の修正を先に。同じファイル（特に structure.py・docx_reader.py・ooxml.py）を触る項目の衝突と、
  structure.py の分割（保守性）をどの時点に置くと他の修正とぶつからないか。各単位の版（現在 0.18.1。出力の形が変わるなら 2 桁目）。
- 反証で revise / reject になった項目は、修正後の方針を前提にする。
- 計画全体で抜けている論点（文書・ノートブックの再生成・fixture の追加・CLAUDE.md の更新、試験運用での確認など）。
- 利用者（学会の編集委員）が決めるべき事項と、その推奨。
- 毎回必要な共通作業。

結果:
${JSON.stringify(done, null, 1)}
`, { label: 'sequence', phase: 'Sequence', schema: SEQ_SCHEMA })

return { clusters: done, sequence: seq }
