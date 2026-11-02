# 単位 I（0.27.1）の設計メモ: structure.py の分割の第 1 段階（U6）

正本は docs/FIX_PLAN.md の I。動作を 1 つも変えない。

## 1. structure.py（0.27.0、2,498 行）のクラス・関数の一覧

| 行 | 名前 | 種類 | 扱い |
|---|---|---|---|
| 19〜95 | BODY_ROLES … NO_LINK_KINDS（役割の集合・理由の文言・RE_*・定数） | 定数 | 残す |
| 98〜166 | nfkc, num_of, note_mark, appendix_sentence, appendix_heading, unreferenced_note_reason, no_link_rule | 関数 | 残す |
| 170〜316 | Sec, PNode, ListNode, QuoteNode, FigNode, TableNode, FormulaNode, BoxNode, FnNode, RefNode, BackSec, AppNode, Author, Aff, FloatInfo, BoxInfo | データクラス（ノードと図形の記録） | **article.py へ** |
| 319〜478 | ArticlePlan（unplaced_floats, undecided_boxes, estimated_boxes, box_place, float_text_src, float_place, no_link_paras, unlinked_places, decide, exclude, exclude_blank） | データクラス | **article.py へ** |
| 481 | _para_text | 関数 | **article.py へ** |
| 485〜580 | _xid_list, in_shape, float_caption, float_ids, float_targets, same_place | 関数 | 残す（float_targets は Classifier.node_paras を使う） |
| 583〜2471 | Classifier（run と各段階のメソッド） | クラス | 残す |
| 2474〜2498 | classify, _doc_paragraphs | 関数 | 残す |

model.Decision・Exclusion は model.py にある（structure.py のものではない）。ArticlePlan.decide・exclude・exclude_blank はメソッドごと移す。

## 2. import の向き

- article.py: `from .model import Decision, Exclusion, Float, Para, Table` と dataclasses・typing だけ（Float・Table は注釈だけで使う。
  `from __future__ import annotations` なので実行時には評価しないが、未定義名〈F821〉にしないため import する）。
- structure.py → article.py の一方向。article.py は structure・floats・ooxml を import しない。
- structure.py: `from .article import (AppNode, ArticlePlan, Aff, Author, BackSec, BoxInfo, BoxNode, FigNode, FloatInfo, FnNode,
  FormulaNode, ListNode, PNode, QuoteNode, RefNode, Sec, TableNode, _para_text)  # noqa: F401 互換のため`。
  移した後に structure.py で使わなくなる import（model の Decision・Exclusion・Float、dataclasses、Optional）は ruff で確かめて消す。
- src で import の向き先を article に変える: linker.py（ノードと ArticlePlan）、builder.py（ノードと _para_text）、
  ai_assist.py（ArticlePlan・_para_text。AFTER_BODY_REGIONS・float_caption は structure のまま）、pipeline.py（_para_text。
  classify・float_caption・float_targets は structure のまま）。pdfdocx.py・report.py は移した名前を import していないので変えない。
- tests・docs/fix_plan_repro_tests.py は変えない（structure からの import のまま通ること）。

## 3. structure.py の冒頭の docstring（目次）

今の 6 行の説明を残し、その後に「処理とメソッドの目次」を足す: classify（2 回の組み立て）→ Classifier.run の流れ
（role_of → AI の exclude → split_regions → build_front_ja → build_body〈place_floats・place_boxes → 役割の推定 → assemble_floats
→ nest → compute_locations〉→ build_back → build_front_en → attach_word_notes → assign_ids → joined_styles）と、段階ごとの補助
メソッドの名前。ノードと ArticlePlan は article.py にあることを書く。

## 4. 確かめ方

1. 移した本体の同一性: git show HEAD:src/jasme_jats/structure.py の 170〜482 行（ノード〜_para_text）を切り出し、article.py の
   対応する部分と diff（差がないこと）。structure.py の残りも、HEAD から移した範囲を除いたものと diff（docstring と import 以外は同じ）。
2. 別プロセスの import のテスト（tests/test_structure.py に足す）: `python -c "import jasme_jats.structure, jasme_jats.pipeline"` を
   subprocess で。あわせて structure から import した名前が article のものと同じオブジェクトであること。
3. pytest（3.13・3.10）、ruff（HEAD の 201 件と同じか減る）、golden（27 件の manifest が golden_base と一致）、
   td1〜3 のルート1・2（XML・AI 依頼文・レポート〈版・日時の行を除く〉・直した docx のバイト比較。版は仕上げで上げるので、
   この段階では版の行も同じになるはず）。

## 5. 実装で設計から変えたこと

- 再 export の `# noqa: F401 互換のため` は付けなかった。移した 18 の名前はどれも structure.py の中で使っているので F401 は出ず、
  noqa を付けると ruff の RUF100（使われていない noqa）が 1 件増える。代わりに import の前のコメントに「互換のため」と理由を書いた。
  import は ruff の isort（I001）の形（1 行に 1 つ）にした（builder.py と同じ折り返しの形だと I001 が 1 件増える）。
- 別プロセスの import のテストは、新しい tests/test_article.py に置いた（test_structure.py の docstring は構造の判定のテスト）。
