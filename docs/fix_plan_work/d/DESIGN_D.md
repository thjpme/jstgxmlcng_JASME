# 単位 D（0.23.1）の設計メモ（impl）

正本は docs/FIX_PLAN.md の D の節（U2・M4・N5）と決定事項 4・5。XML・ZIP・docx の文字・AI 依頼文には触れない。

## report.Action と actions(r)

```
@dataclass
class Action:
    level: str        # "要対応"（CLI 1・手順 8 で一度止める・赤い枠）/ "要確認"（赤い枠・冒頭・14 章だけ。CLI 0）
    key: str
    top: str = ""     # レポートの冒頭の囲み（Markdown。空なら出さない）
    checklist: str = ""   # 14 章の行（空なら出さない）
    box_title: str = ""   # Colab の赤い枠（空なら枠を出さない）
    box_detail: str = ""
    cli: str = ""         # コマンドラインの標準エラー（FIX_PLAN の 6 項目に足した。画像の「--images で指定するか」など CLI だけの文面があるため）
```

actions(r) の並び（= 冒頭の並び。今の冒頭の順を保ち、新しいものを間に入れる）:

| key | level | 冒頭 | 14 章 | 枠の見出し | 条件 |
|---|---|---|---|---|---|
| fidelity | 要対応 | 今の「注意: 文字の不変性チェックが不合格です」 | 新: 不合格・登載に使わない | 新 | not fid.ok or not fid.final_ok |
| dtd | 要対応 | 新 | 新 | 新 | not dtd_valid |
| upload | 要対応 | 新「要対応: J-STAGE のアップロード時チェック…」 | 新（12 章） | 新 | upload_issues(r) |
| ai_error | 要対応 | 新（manual / api で見出しを書き分け） | 新 | 今の Colab の見出し 2 種 | ai.error |
| ai_pending | 要対応 | なし（今の output_note が冒頭にある） | 新 | 新（手順 5 では出さない。依頼文の枠があるため） | 手動モードで回答なし（決定事項 5(c)） |
| partial | 要対応 | 今の文 | 今の行 | 今の Colab の見出し | ai.partial |
| forced | 要対応 | 今の文 | 今の行 | unplaced_box の文面 | r.forced_floats |
| figbody | 要対応 | 今の文 | 今の行 | figure_body_box の文面 | plan.figure_issues |
| images | 要対応 | 今の文 | 今の行 | missing_images_box の文面 | images_to_prepare |
| lost | 要対応 | 今の文 | 今の行 | lost_images_box の文面 | r.lost_images |
| （ルート2 の「docx を直してから変換しました」は actions に入れず、ここに固定で出す） |
| pdf_fallback | 要対応 | 新「要対応: 出版版 PDF に合わせられませんでした」 | 新「docx を PDF に合わせていない」 | 新 | r.pdf_fallback |
| pdf_unread | 要確認 | 新「出版版 PDF と照合できませんでした」 | 新 | 新（照合できませんでした） | ルート1 で not pc.ok |
| pdf_diff | 要確認 | 今の文 | 今の行 | pdf_diff_box のルート1 の文面 | ルート1・pc.ok・違いあり |
| pdf_unfixed | 要確認 | なし（固定の案内に「直せなかった箇所」がある） | なし（固定の行） | pdf_diff_box のルート2 の文面 | ルート2・直せなかった箇所か残る違い |
| pdf_suspect | 要確認 | 新「別の記事の PDF かもしれません」 | 新 | 新 | report.pdf_suspect(r) |
| pdf_ignored | 要確認 | 新 | 今の行 | 新 | ignored_lines(r) |
| textbox / endnote | 要確認 | 今の文 | 今の行 | 新（今は Colab に枠がない） | provisional_exclusions |

- 14 章の並び: 今は PDF の行（違い・照合に使わなかった文字）が先なので、PDF の項目（pdf_*）を先に、残りを actions の順に。
  「[x] 画像はすべて Graphics/」は今と同じく lost・textbox・endnote の前に出す。
- 冒頭の並び: pdf_* と textbox・endnote の前に、ルート2 の固定の案内を出す（今と同じ）。
- needs_action = any(a.level == "要対応")。not res.ok なら必ず真（fidelity・dtd）。

## 関数ごとの変更

- report.py: Action・actions・pdf_suspect・box の文面の関数（colab から移す。_marks_note も）。render の冒頭・14 章は actions のループに。
  pdf_summary の別記事の判定は pdf_suspect を使う。render の作り方の行は r.pdf_fallback。
- pipeline.py: Result.needs_action・pdf_fallback（route=='pdf' and docx_fix is None and pdf_check is not None）。ok は変えない。
- colab.py: result_boxes(res, level=None, skip=())。missing_images_box・lost_images_box・figure_body_box・unplaced_box・pdf_diff_box は
  report の文面で枠を作る薄い関数として残す（テストと手順 7・8 が使う）。pdf_diff_box は not pc.ok でも枠（M4）、pdf_suspect の枠を足す。
- cli.py: --ai api で API キーがなければ ap.error（N5）。actions を標準エラーに出し（add_images の後に計算）、return 1 if needs_action else 0。
- ai_assist.call_api: TypeError（API キーが見つからない）を out.error に（N5）。
- make_notebook.py: 手順 5・6 の個別の枠を result_boxes に（手順 5 は ai_pending を除く）。手順 5 に PDF に合わせられなかったときの 1 行。
  手順 8: 要対応がひとつでもあれば一度止める（画像だけのときは今の文面）。ダウンロードの後に result_boxes。説明を「（PDF の文字を読めたとき）」に。
  手順 9 で片付ける変数を _NEEDS_ACTION_OK に。

## 決めたこと・FIX_PLAN と違えること

- Action に cli を足した（FIX_PLAN は 6 項目）。CLI の文面は今のまま（画像は「--images で指定するか」）。AI のエラーは「AI: …」から
  「要対応: <見出し>。…」に（見出しをそろえる）。
- 決定事項 5(c)（手動モードで回答を貼り戻す前の出力は要対応）を ai_pending として入れた（D の節の Action の一覧には書かれていない）。
  コマンドラインの --ai manual（回答なし）も 1 を返す。
- 図の本体（figbody）は今「要対応」の文なので要対応にし、CLI の終了コードも 1 にする（B3 では「終了コードは変えない」としていた）。
- 既存テストの書き換えは FIX_PLAN の 2 つに加え、test_figure_body の CLI（--meta なし → 1。図の本体は要対応）、test_notebook の
  手順 5・6・8 の枠の import の確かめ（result_boxes に置き換えたため）。
