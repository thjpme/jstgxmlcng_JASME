# 修正計画（2026-10 のコードレビューに基づく）

- 作成: 2026-10-14
- 対象: main の 0.18.1（コミット 60fdb49）。この計画の時点では、コードは変えていない。
- 文中の行番号は 0.18.1 のもの。文中の `scratchpad/…` は、計画づくりに使った一時的な実験スクリプトで、リポジトリには残っていない。不具合の再現テストは [fix_plan_repro_tests.py](fix_plan_repro_tests.py) にある（使い方はファイルの冒頭）。

## この計画の作り方

1. コードレビューで見つけた 19 件（D: データ損失、M: 誤動作、U: 使い勝手・保守性）を 4 つのまとまりに分けた。
2. まとまりごとに、指摘が実在するかをコードと実験で確かめ、原則（docx の文字を 1 文字も変えない）を守る修正方針を設計した。
3. 別の担当が反証の立場で設計を点検した。点検で直した方針を採っている（項目の説明の「反証で revise」）。
4. 設計と点検の途中で見つかった不具合を N1〜N8 として加えた。
5. 最後に、反映の単位・順序・版・同じファイルを触る順・抜けている作業を点検した。

レビューで挙げた「最初の章見出しの前の標準スタイルの段落が落ちる」は、点検で再現しなかったため計画から外した。

## 項目の一覧

| ID | 種類 | 内容 | 単位 |
|---|---|---|---|
| D1 | データ損失 | 文字だけのテキストボックス（囲みの問題文・ヒントなど）が XML から消え、AI でも戻せない | F |
| D2 | データ損失 | 上付きの指数・単位（cm²・x²・s⁻¹）が注へのリンクになる | H |
| D3 | データ損失 | 「資料（授業プリント）」のような資料の見出しを認識できず、以降の段落が英文要旨（trans-abstract）に入る | E |
| D4 | データ損失 | Word の文末脚注（endnotes）が XML に出ない。あわせて、脚注と ID が同じ文末脚注の参照が脚注へのリンクになる | E |
| D5 | データ損失 | 段落記号の削除（w:pPr/w:rPr/w:del）を承諾した状態として、次の段落とつなぐ | G |
| M1 | 誤動作 | EMF/WMF を変換できなかったとき、アップロード用 ZIP に「要変換/」フォルダと EMF が入る | C |
| M2 | 誤動作 | 同じ出力フォルダで 2 本目を変換すると、2 本目の ZIP に 1 本目の記事フォルダも入る | C |
| M3 | 誤動作 | w:sdt・w:customXml に包まれた表の行・セル（とテキストボックスの段落）も読む | A |
| M4 | 誤動作 | ルート2 で PDF の文字を読めなかったとき、Colab に赤い枠が出ず、CLI も終了コード 0 | D |
| M5 | 誤動作 | 語の中の「図1」「表1」（地図1・図表1・発表1回目・付表1）が図・表へのリンクになる | H |
| M6 | 誤動作 | 不変性チェックで、出力と除外の矛盾、空白のはずの除外に文字があることを不合格にする（図形の中の画像段落の文字の脱落も直す） | A |
| U1 | 使い勝手・保守性 | 日付の入力で 2026/3/31・2026.3.31 のようにゼロ埋めしない書き方を読めない | C |
| U2 | 使い勝手・保守性 | J-STAGE のアップロード時チェックで要対応があっても CLI の終了コードが 0。要対応の知らせ方が画面ごとにそろっていない | D |
| U3 | 使い勝手・保守性 | 段落内の改行（w:br）: 表のセルでは <break/> を補い、それ以外は文字のまま残してレポートで知らせる | G |
| U4 | 使い勝手・保守性 | AI 依頼文の「姓と名の区切りがない氏名」を、メッセージの文言から切り出している | H |
| U5 | 使い勝手・保守性 | 既定の AI モデル名が複数の場所に直書きされている | H |
| U6 | 使い勝手・保守性 | structure.py（1263 行）の分割 | I |
| U7 | 使い勝手・保守性 | PDF の柱（ヘッダー）・ページ番号が本文の違いとして報告され、ルート2 で docx に挿入される | B |
| U8 | 使い勝手・保守性 | 文字スタイル・段落スタイル・既定の書式の w:vanish（隠し文字）も、Word と同じく隠す | G |
| N1 | 計画づくりで見つけたもの | 引用文献・題目・著者などの段落にある画像が、警告もなく XML と Graphics から消える（画像の出力漏れを検出するしくみがない） | A |
| N2 | 計画づくりで見つけたもの | テキストボックスの段落のスタイルで領域が切り替わる（本文中のテキストボックスに「英文要旨」スタイルの段落が 1 つあると、以降の本文と引用文献がすべて英文要旨に入る。不変性チェック・DTD は合格） | A |
| N3 | 計画づくりで見つけたもの | 空白だけの段落の除外漏れで、不変性チェックが不合格になる（テキストボックスの中、文末脚注の中の全角空白だけの段落） | A |
| N4 | 計画づくりで見つけたもの | 巻・号・ページを全角や「31巻」の形で入力すると、ZIP 名・フォルダ名が日本語になる（J-STAGE で EMSGM034E） | C |
| N5 | 計画づくりで見つけたもの | コマンドラインで --ai api を指定し API キーがないと、トレースバックで落ちる | D |
| N6 | 計画づくりで見つけたもの | AI 依頼文が、必ず捨てられる set_role を勧める（set_role を受け付けるかの判定が 1 か所にない） | E |
| N7 | 計画づくりで見つけたもの | 引用文献などの段落に結び付いた図形の中身が引用文献になり、図の画像が消える | F |
| N8 | 計画づくりで見つけたもの | 変更履歴で削除された表の行が、空の行として出力される | G |

## 反映の順序

単位ごとに版を上げて main に反映する（main への反映は、Colab の利用者にすぐ届く）。出力の形が変わる単位は版の 2 桁目、それ以外は 3 桁目を上げる。

| 単位 | 版 | 内容 | 項目 |
|---|---|---|---|
| A | 0.19.0 | 黙って文字・画像が落ちる、別の場所に入る不具合を止める（検証の強化を含む） | M6、N3、N2、N1、M3 |
| B | 0.20.0 | ルート2 で、PDF の柱・ページ番号が本文に入るのを止める | U7 |
| C | 0.21.0 | アップロード用 ZIP の中身と、書誌情報の入力値 | M1+M2、N4、U1 |
| D | 0.21.1 | 要対応の知らせ方を 1 か所にまとめる（レポート・Colab・コマンドライン） | U2、M4、N5 |
| E | 0.22.0 | 注（Word の文末脚注）と資料の見出し | N6、D4、D3 |
| F | 0.23.0 | 文字だけのテキストボックス（囲み）と、本文の外に結び付いた図形 | D1、N7 |
| G | 0.24.0 | 読み取りの文字ポリシー（段落記号の削除・スタイルの隠し文字・セルの改行） | D5、U8、U3、N8 |
| H | 0.25.0 | リンクの誤検出と AI 依頼文の保守 | D2、M5、U4、U5 |
| I | 0.25.1 | structure.py の分割（動作を変えない） | U6、golden |

A（黙って文字・画像が落ちる不具合と、それを捕まえる検証の強化）を最初に置く。後の大きな変更で同じ種類の誤りが起きても、テストと不変性チェックで捕まえられるようにするため。structure.py の分割（I）は、structure.py を触る A・E・F・G がすべて終わった後に置く。

## 利用者に決めてもらうこと

推奨は、設計と点検の結論。各単位の作業は、関係する判断が決まってから始める（判断を待たずに進められる部分は、各単位の「前提」に書いた）。

1. **テキストボックスの中で、画像と文字が同じ段落にあり、図キャプションもある図（今は、その文字が『図の画像だけの段落にある空白』として黙って消える）をどう扱うか。**（関係する項目: M6）
   - 案: 画像を図に入れ、同じ段落の文字は図の直後に本文の段落として出す（AI なしでも変換できる）
   - 案: 変換を止めて AI に任せる（ただし今の AI の検証規則では配置できず、本文の冒頭に仮に置いて要対応になる）
   - 推奨: 前者。文字を 1 文字も落とさず、AI なしでも図になる。後者は利用者が XML を手で直す必要があり、技術に詳しくない編集委員には難しい。
2. **コマンドラインで記事フォルダに手で置いた PDF・画像（前回の変換の残りも含む）を、アップロード用の ZIP に入れないことにしてよいか。**（関係する項目: M1、M2）
   - 案: 入れない（--pdf・--images、または Colab の手順 2・7 で指定し直す。入れなかったファイルはレポート 10 章に出す）
   - 案: 今までどおり記事フォルダの中身をすべて入れる
   - 推奨: 入れない。ZIP の中身とレポートの内容が一致し、別の記事や古いファイルが混ざって J-STAGE で弾かれたり（EMSGM074E・219E）、記事が 2 本登録されたりするのを防げる。
3. **書誌情報の巻・号・開始ページに英数字以外（『31巻』など）が入力されたら、変換を止めてよいか（全角の数字は自動で半角にする）。**（関係する項目: N4）
   - 案: 止めて、欄の名前を入れたエラーを出す
   - 案: 今までどおり入力のまま使う（ZIP 名・フォルダ名に日本語が入りうる）
   - 推奨: 止める。日本語のフォルダ名・ZIP 名は J-STAGE で EMSGM034E になる。
4. **ルート2（出版版 PDF に合わせてから作る）で PDF の文字を読めなかったときの扱いと、『別の記事の PDF かもしれない』（段落の半分以上が見つからない）をどこまで強く知らせるか。**（関係する項目: M4）
   - 案: 変換を続け（結果は『docx から作る』と同じ）、赤い枠・レポートの冒頭・コマンドラインの終了コード 1 で知らせる。別の記事の疑いは要確認（終了コード 0）
   - 案: 変換を止める
   - 案: 別の記事の疑いも要対応（終了コード 1）にする
   - 推奨: 最初の案。画像だけの PDF でも J-STAGE には登載でき、やり直しの手間も小さい。別の記事の疑いの判定は、出版社の実際の PDF でまだ試していないので、試すまでは要確認にとどめる。
5. **『要対応』（コマンドラインの終了コード 1、Colab の手順 8 で一度止める）に含める範囲。特に、(a) AI を使う設定なのに AI の回答を反映できなかったとき、(b) PDF がないとき（J-STAGE では必須）、(c) 手動モードで AI の回答を貼り戻す前の出力（位置を決められない図表が本文の冒頭に仮に置かれている）をダウンロードしようとしたとき、(d) 文字の不変性チェックが不合格のとき。**（関係する項目: U2）
   - 案: (a) 要対応、(b) 今までどおり 14 章のチェックリストだけ、(c) 要対応（手順 8 で一度止め、手順 6 を案内する）、(d) 手順 8 で一度止めるがダウンロードはできる
   - 案: (a)〜(c) を要確認にとどめる
   - 案: (d) のときはダウンロードさせない
   - 推奨: 最初の案。(b) は PDF を後から入れる使い方があるのでチェックリストに残す。(d) は原因を調べるためにダウンロードが必要。
6. **ルート2 の柱・ページ番号の扱いを確かめるために、本誌の最近の号の出版版 PDF（1〜2 本。2 ページ以下の記事があればそれも）を tests/private 用に提供してもらえるか。**（関係する項目: U7）
   - 案: 提供する（反映の前に実際の PDF で確かめる）
   - 案: 提供しない（合成したテストだけで反映する）
   - 推奨: 提供する。柱が誌名・巻号・著者名・題目のどれか、何文字か、ページ番号の形（『－ 1 －』など）で、直す必要の大きさが変わる。
7. **Word の脚注と文末脚注の両方がある原稿の注の番号と、文末脚注の番号の形式をどうするか。**（関係する項目: D4）
   - 案: 脚注・文末脚注を、本文で最初に参照される順の通し番号にし、形式は本誌の『1)』（設定 fn_mark）にそろえる
   - 案: 脚注と文末脚注を別の番号にする（同じ注の一覧に『1)』が 2 つ並ぶ）
   - 案: 文末脚注は今までどおり出力しない（除外して知らせる）
   - 推奨: 最初の案。Word の文末脚注の既定の表示（i, ii, iii）は本誌の形式と違い、脚注と同じ方針（番号は本誌の形式で生成）にそろえるのが自然。番号の付け替えは Decision としてレポートに残す。
8. **資料（付録）の見出しの認識を広げるにあたり、(a) 英文要旨の後に章・節・項見出しのスタイルの段落が来たら、資料の見出しとみなしてよいか。(b) 引用文献の後ろ（英文の前）に置かれた資料も資料として扱うか。**（関係する項目: D3）
   - 案: (a) はい、(b) はい（資料として扱い、レポートの 4 章に記録する）
   - 案: (a) はい、(b) いいえ（警告だけ出す）
   - 案: (a) いいえ
   - 推奨: (a) はい（英文要旨の中に見出しのスタイルは来ない）。(b) は、本誌で資料を引用文献の後ろに置く原稿が実際にあるなら『はい』、なければ警告だけで十分。
9. **文字だけのテキストボックス（問題文・ヒントなどの囲み）の出し方。(1) <boxed-text>（J-STAGE の『コラム』）にするか、ただの <p> にするか。(2) AI を使わない設定で、囲みか図の注記か決められないものをどうするか。(3) 判定のしきい値を、実際の論文で確かめてから決めてよいか。**（関係する項目: D1、N7）
   - 案: (1) boxed-text（試験登載で表示を確認）、(2) 除外したまま要確認にする、(3) tests/private の実際の論文で確かめる
   - 案: (1) ただの <p>
   - 案: (2) 囲みとして出す
   - 案: (2) 変換を止める（AI を必須にする）
   - 推奨: 最初の案。boxed-text は JATS・J-STAGE でコラムに当たる要素で、DTD にも合う。決められないものを本文に混ぜると図の注記（矢印のラベルなど）が本文に入るので、除外して知らせ、AI か人に任せる。しきい値は、囲みと注記のある実際の論文を 2〜3 本提供してもらって決める。
10. **引用文献・注・英文要旨などの段落に結び付いたテキストボックス・図形（Word の配置の都合で、最後のページの図が引用文献の段落に結び付いた場合など）を、『位置を決められない図表』として AI に位置を指定させ、AI を使わない設定では変換を止めてよいか。**（関係する項目: N7）
   - 案: はい（AI を使えば正しい位置に置ける。使わなければ止まる）
   - 案: 止めずに、本文の最後に置いて要確認にする
   - 推奨: はい。今の浮動配置の図表と同じ扱いで、図の位置を誤って黙って出すより安全。
11. **変更履歴が残った docx の『段落記号の削除』（2 つの段落を 1 つにする変更）を、すべて承諾した状態として 1 つの段落にしてよいか。あわせて、試験用の docx（sample_reader.docx）を Word で開き、『すべての変更を反映』した後の段落のつながりとスタイルが、ツールの出力と同じかを確かめてもらえるか。**（関係する項目: D5）
   - 案: 1 つの段落にする（Word で確かめた後に反映）
   - 案: 今までどおり 2 段落のまま出し、警告だけ出す
   - 案: 変更履歴が残った docx は、Word で承諾してから変換するよう求める
   - 推奨: 最初の案。ツールはもともと『すべて承諾した状態』を読む方針で、ルート2 でも PDF の 1 段落と段落の切れ目が合うようになる。書式の規則（前の段落が空なら後の段落のもの）は LibreOffice でしか確かめていないので、Word で一度確かめる。
12. **スタイル（文字スタイル・段落スタイル）で隠した文字も、Word と同じく XML に出さないようにする変更を、いつ入れるか。**（関係する項目: U8）
   - 案: 段落記号の削除（D5）と同じ単位で入れる（Word で隠し文字の表示も確かめる）
   - 案: 後回しにする（本誌のテンプレートに隠し文字のスタイルはない）
   - 推奨: D5 と同じ単位で入れる。同じ箇所を触るので、別々に直すより衝突が少ない。ただし Word で確かめられないなら後回しでよい。
13. **段落内の改行（Word の Shift+Enter）の扱い。(1) 表のセルでは <break/> を補うか。(2) 題目・著者・所属・引用文献の中の改行を、要確認としてレポートの冒頭とチェックリストに出すか。**（関係する項目: U3）
   - 案: (1) 補う、(2) 要確認として出す
   - 案: (1) 補わず、レポートで知らせるだけ
   - 案: (2) 10 章の警告だけにする
   - 推奨: (1) 補う（セルの中の段落の間にはすでに <break/> を入れているので、見え方がそろう）。(2) 要確認として出す（J-STAGE の書誌に改行文字が入り、画面で空白になるか詰まる）。
14. **変更履歴で削除された表の行（中身がすべて削除されたもの）を、空の行として出さずに読み飛ばしてよいか。**（関係する項目: N8）
   - 案: 読み飛ばし、レポートに記録する
   - 案: 今までどおり空の行として出す
   - 推奨: 読み飛ばす（Word で承諾した表示と同じ）。優先度は低いので、G に入れるか後回しにするかは任せる。
15. **上付きの数字を注へのリンクにするか、論文ごとに決める方針でよいか。本文に『1)』『注1』の形の上付きの注番号が 1 つでもあれば、数字だけの上付き（cm² など）は注番号にしない。リンクしなかったものはレポートと AI 依頼文に載せる。指数の多い論文では、その件数が増える。**（関係する項目: D2）
   - 案: その方針で、リンクしなかったものを全件載せる
   - 案: その方針で、明らかな指数（直前が英数字・演算の記号）は段落ごとに 1 行にまとめる
   - 案: 今までどおり上付きの数字はすべて注番号とみなす
   - 推奨: 2 つ目。機械処理は迷ったらリンクしない側に倒し（足りないリンクは AI で補える）、明らかな指数で一覧が埋もれないようにする。
16. **『図1』『表1』の直前が漢字なら語の一部（地図1・付表1 など）とみなしてリンクしないことにする。例外として前に来てよい漢字（今の案は『掲・至・及』。前掲・乃至・及び）に足すものはあるか。本誌で『本図1』『第1表』のような書き方は使われるか。**（関係する項目: M5）
   - 案: 今の案（掲・至・及）のまま
   - 案: 足す漢字を指定する
   - 案: 『第1表』などの書き方にも別に対応する
   - 推奨: 今の案のまま。リンクしなかった箇所は、その番号の図表があればレポートと AI 依頼文に載るので、AI か人が補える。
17. **英文の氏名が 1 語（姓と名を分けられない）のものを、AI 依頼文の『姓と名の区切りがない氏名』から外してよいか（AI はもともと英文の氏名を分けられない。レポートには引き続き載る）。**（関係する項目: U4）
   - 案: 外す
   - 案: 今までどおり載せる
   - 推奨: 外す。AI にできないことを頼まない。
18. **structure.py（1263 行）を分ける、動作を変えないだけの版（0.25.1）を出してよいか。分ける前後で出力が同じかを比べるテスト（golden）を常設するか。**（関係する項目: U6）
   - 案: データの部分（article.py）だけを分け、golden は常設する
   - 案: データの部分だけを分け、golden は作業のときだけ使う
   - 案: 分けずに、structure.py の冒頭に目次を書くだけにする
   - 推奨: 最初の案。将来ほかの人が生成 AI で直すとき、目的の処理を探しやすくなる。golden で意図しない出力の変化をすぐ見つけられる（意図した変化のときは作り直しのスクリプトで更新する）。
19. **反映の進め方。単位ごと（A〜I）に main に反映してよいか（Colab の利用者に即座に届く）。試験運用中の論文の変換と重なる時期を避ける必要はあるか。**（関係する項目: M6、M1、M2、U2、D1）
   - 案: 単位ごとに反映する（C と D は 1 回にまとめてもよい）
   - 案: いくつかの単位をまとめて反映する
   - 案: 反映の前に、開発版（USE_DEV_VERSION）で利用者が試してから反映する
   - 推奨: 単位ごとに反映し、出力が大きく変わる単位（A・C・F）は開発版で一度試してから main に入れる。変換作業中の論文がある時期は避ける。

## 決定事項（2026-10-14 の回答）

「利用者に決めてもらうこと」の番号で記録する。

1. M6: 画像を図に入れ、同じ段落の文字は図の直後に本文の段落として出す（推奨の前者）。
2. M1・M2: 記事フォルダに手で置いたファイルは、アップロード用 ZIP に入れない。
3. N4: 英数字以外が入力されたら止める。全角の数字は半角にし、その旨を表示する。英数字以外の文字があるときは、その文字を示し、全角の文字が原因だと分かるエラーにする。
4. M4: 変換を続けて知らせる（最初の案）。出版版 PDF をどれだけ提供するかは後で相談する。
5. U2: (a)〜(d) すべて最初の案。(a) AI の回答を反映できなかったときは要対応。(b) PDF がないときは 14 章のチェックリストだけ。(c) 手動モードで回答を貼り戻す前の出力は要対応。(d) 不変性チェックが不合格のときは、手順 8 で一度止めるが、ダウンロードはできる。
6. U7: 相談中。PDF は提供できるが、docx の提供は難しい。
7. D4: 脚注・文末脚注を、本文で最初に参照される順の通し番号にし、形式は fn_mark（「1)」）にする。
8. D3: (a) はい。(b) 推奨どおり（引用文献の後ろに資料を置く原稿が実際にあれば資料として扱い、なければ警告だけ）。どちらにするかは確認中。
9. D1・N7: (1) boxed-text。(2) 囲みか注記か決められないものは除外して要確認にし、AI による補完を使うよう強く勧める警告を出す。(3) しきい値は相談中。
10. N7: はい（位置を決められない図表として扱い、AI を使わない設定では止める）。
11. D5: 1 つの段落にする。
12. U8: D5 と同じ単位で入れる。docx は追加で提供できないので、難しければ保留する。
13. U3: (1) セルでは break を補う。(2) 題目・著者・所属・引用文献の改行は要確認として出す。
14. N8: 読み飛ばしてレポートに記録する。docx は追加で提供できないので、難しければ保留する。
15. D2: 方針どおり、論文ごとに注番号の書き方を判定する。明らかな指数（直前が英数字・演算の記号）は、段落ごとに 1 行にまとめて記録する（推奨の案）。
16. M5: 今の案（掲・至・及）のまま。
17. U4: 英文 1 語の氏名も、今までどおり AI 依頼文に載せる。あわせて、英文の氏名を姓と名に分けられなかったことを警告する。
18. U6: データの部分（article.py）だけを分け、出力の比較（golden）を常設する。
19. 単位ごとに main に反映する。

## 各単位の詳細

### A. 黙って文字・画像が落ちる、別の場所に入る不具合を止める（検証の強化を含む）（0.19.0）

**理由**: この 5 項目は、不変性チェック・DTD 検証が合格しているのに、XML から文字や画像が消える、または本文が英文要旨に入る不具合と、それを捕まえる検証の強化である（M3 と N3 は、変換結果を使えなくなる不合格）。最優先の原則に直結するので、最初に出す。どれも小さく、触る関数が別々で、ほかのまとまりに依存しない。検証（conflicts・bad_excluded・画像の出力漏れ・test_reader の逆向きの確認）を先に強めておくと、後の E・F・G の大きな変更で同じ種類の誤りが起きても、テストと不変性チェックで捕まる。出力の形が変わるのは、M6 の float_mechanical と N2 の領域の決め方だけ（既存 fixture の出力は変わらないことを試作で確かめた）。これに合わせて 2 桁目を上げる。

**前提**: 今の main（0.18.1）から始める。M6 の直し方（推奨の extra_images 案か、変換を止める案か）を利用者が決める。答えがまだなら、まず verify の強化・exclude_blank・builder.fig を先に入れ、float_mechanical の変更は判断を待ってもよい。

- M6（反証で revise）: fidelity.verify の L151〜153 の pass をやめる。FidelityResult に conflicts（出力したのに除外にもある段落）と bad_excluded（blank=True の除外なのに、検証側の文字が空白でない）を足し、res.ok（L166）の条件に入れる。excl.setdefault（L115〜117）は最初の 1 件しか見ないので、blank の確認は exclusions をすべて回して行う。model.Exclusion に blank: bool = False を足す。structure.ArticlePlan.exclude_blank(para) を作り、理由「空白のみの段落」と blank=True はここだけで作る。今の 7 か所（structure.py:390・409・484・676・1022・1079・1101）をこれに置き換える。builder.fig（builder.py:460〜463）は、is_ws(_para_text(ip)) のときだけ除外（blank=True）にする。それ以外は除外せず warnings に記録する（万一の取りこぼしも verify の missing で不合格になる）。float_mechanical は、図（FigNode）を組む枝だけ直す（キャプションのない枝 L692〜694 は今のまま。広く直すとキャプションのない図形まで AIRequiredError になる。rvz_m6_nocap.py で確認済み）。画像と文字が同じ段落の扱いは利用者が決める。推奨: その段落の画像を FigNode.extra_images と plan.moved_images に移す（Emitter.skip_images で段落の中には出さない）。段落は文字ごと、図の直後に ('p', q) で出す。ai_assist._placement_problem（L893）も、その画像の ID を body として認める。もう一つの案: L683 の直後で return None にする。ただしこの案では、AI でも配置できず（_placement_problem L882・893）本文の冒頭に仮に置かれ、要対応になる。report.py 5 章（L406〜408）に、conflicts と bad_excluded を『変換ツールの不具合』として出す。
- N3（空白だけの段落の除外漏れ。どの設計にもなく反証で見つけた。rvz_tbws.py と rvz_d4b.py で再現。missing [('d14','　')]・[('e4',' ')]）: structure.py:472〜474（テキストボックスの段落の除外。`if not b.is_blank` のときしか記録しない）と、1202〜1205（文末脚注の除外）を直す。is_blank の段落は、plain() が空でなければ exclude_blank に回す（_drop_blank と同じ）。is_blank は全角空白も空白とみなすので、今は全角空白だけの段落が除外にも出力にもならず、不変性チェックが『出力漏れ』で不合格になる。
- N2（テキストボックスの段落で領域が切り替わる。D1 の反証で見つけた）: structure.split_regions（L325〜350）で、図形の中の段落・表（Para.in_textbox または float_id、Table.float_id）では状態を変えない。図形の中身は、直前にある図形の外のブロックと同じ領域に入れる。試作 scratchpad/plan_final/pf_regions_proto.py（領域は外側のブロックだけで決め、図形の中身は直前の外側の領域に続ける）で次を確かめた。全テスト 146 件が通る。既存 fixture の XML・AI依頼文・レポートのハッシュは変わらない。今は本文と引用文献がすべて trans-abstract に入る例（rvz_tbabs.py。結果は sec 1 つ・ref 0 件）が sec 2 つ・ref 1 件になる。本文が注 1 件になる例（rvz_tbhead.py）も、sec 2 つ・fn なしになる。どちらも今は、不変性チェックも DTD 検証も合格してしまう。
- N1（画像の出力漏れの検出と、暫定の知らせ。どの設計にもない）: pipeline.convert で build の後に、doc.images のうち info.images に入らなかった画像を Result.lost_images に記録する。対象は、引用文献・題目・著者・所属・ラベルのように images=False の文脈（emit.py:39〜48、231）にある段落の画像と、引用文献の段落に結び付いた図形の中の画像。記録した画像は、レポートの冒頭（要対応）・9 章・14 章、CLI の標準エラー（終了コード 1）、Colab の赤い枠（colab.py に枠を足し、make_notebook.py の手順 5・6 で表示）に出す。試作 scratchpad/plan_final/pf_n1.py で確かめた。既存の fixture（sample_full と sample_float の AI 模擬回答、ルート1・2 の sample_pdfcheck を含む）では 0 件。rvz_back.py では img1 を検出した（今は XML にも Graphics にもなく、警告も出ない）。あわせて、D1・D4 が入るまでの暫定の知らせを足す。文字だけのテキストボックスの段落や Word の文末脚注を除外したときに、件数と対処をレポートの冒頭と 14 章に『要確認』として出す。対処は、Word でテキストボックスの外に出す、または本文の注に移してから変換し直すこと。
- M3（反証で revise）: docx_reader に _children(el, tags) を作り、子を文書の順にたどる。w:sdt なら w:sdtContent の中を、w:customXml ならその中を、再帰でたどる。これを次の 3 か所で使う: read_table（L181）の行、行の中のセル（L184〜191 の sdt の特別扱いを置き換える）、_textboxes（L405）の段落と表。テストの穴も埋める。tests/test_reader.py の test_reader_matches_canonical に逆向きの確認を足す（canonical で空でない段落 ID がすべて読まれていること。脚注・文末脚注も対象）。今のテストは読み落としを見ない（rvz_m3_testgap.py）。既存 fixture の未読は 0 件。新しい sample_reader.docx（ALL_DOCS に入れる。D の後の G で D5・U3・U8 の段落を足す）に、次を入れる: sdt に包んだ行、customXml に包んだ行、customXml に包んだセル、入れ子の sdt に包んだ行、テキストボックスの中の sdt の段落。

### B. ルート2 で、PDF の柱・ページ番号が本文に入るのを止める（0.20.0）

**理由**: Colab の初期値はルート2 で、ほとんどの利用者がこの経路を使う。8 文字未満の柱（著者名など）、2 ページの記事の柱、『－ 1 －』の形のページ番号が段落の途中にあると、PDF に合わせて直した docx にその文字が挿入される。XML も（直した docx を相手にするので不変性チェックは合格したまま）『…FT）に試験四郎基づく…』のような誤った本文になる（exp_linkmaint/u7_exp2.py・u7_exp3.py）。docx に無い文字が公開本文に入るので、A の次に急ぐ。触るのは pdfmatch.py、pdfdocx.plan_fixes の理由の 1 行、report.py の 13 章だけで、ほかのまとまりと独立している。ルート2 の XML が変わるので、2 桁目を上げる。

**前提**: A を反映した後（版の番号を順に上げるため。コードはほぼ独立）。本誌の実際の出版版 PDF（1〜2 本、tests/private に置く）で、柱とページ番号の形を確かめられると望ましい。PDF がなくても、extract_pages を差し替える合成テストで進められる。ただし、反映の前に実際の PDF で一度試すことを勧める。

- U7（反証で revise）: pdfmatch.pdf_stream（L119〜149）で、文字ごとに行番号（line）を付ける。あわせて、ページ番号の行などを除いた後で、その行がページの最初か最後の 2 行に入るかの印（edge）も付ける。compare（L215〜268）では、段落ごとの照合の後に owned_lines = {st.line[g] for g in owner} を求める。ページの端の行で、どの段落にも当たらない行の文字は、_classify の mine()（L320）で False にする。_classify の中で、柱を除かない js_all（owner と soft だけで絞ったもの）と、柱も除いた js を比べる。js が空で、js_all と docx の側には文字がある領域は、TextDiff(fixable=False) にして削除としては直さない。表示する PDF の文字は js_all から作る。TextDiff に why: str = '' を足し、この場合は why=『PDF のこの位置にある行は、柱・ページ番号とみなした行だけで、docx の文字の代わりになる文字を決められない』とする。pdfdocx.plan_fixes（L81〜83）は reason=d.why or 既存の文言 にする。PdfCheck.ignored_lines は (段落 ID, 行の文字列) のリストにする。記録するのは、段落の違いの範囲（_classify の insert/replace の j1..j2）の中から実際に除いた行だけで、重複は除く。段落の切れ目にある柱は、今の規則（L347）でもともと違いにならないので載せない。レポートは、13 章に一覧（『本文の一部なら、docx を手で直してから変換し直す』）、ルート2 の冒頭の要約に件数を出す。

### C. アップロード用 ZIP の中身と、書誌情報の入力値（0.21.0）

**理由**: 今の ZIP には、要変換/（日本語のフォルダ名。EMSGM034E・074E）、前回の変換の残り、同じ出力フォルダで変換したほかの記事（EMSGM219E。記事が 2 本登録されるおそれ）が入る。ZIP は J-STAGE に直接アップロードするので、公開に実害が出る。M1 と M2 は package.make_zip の同じ書き換えなので、1 つにまとめる。N4 と U1 は、どちらも ArticleMeta.from_dict の入力値の扱いで、ZIP 名・フォルダ名にも効く（全角の巻）ので同じ単位にする。ZIP の中身と 要変換/ の場所が変わるので、2 桁目を上げる。U2（知らせ方の一本化）より先に出し、zip_issues と not_zipped を D の actions() がそのまま受け止められるようにする。

**前提**: A・B を反映した後。利用者の判断: 記事フォルダに手で置いたファイルを ZIP に入れないこと（推奨は入れない）。巻・号・開始ページに英数字以外を入れたら止めること（推奨は止める）。

- M1+M2（反証で revise。必ず 1 つの変更にまとめる）: images.export_images(…, keep_dir=None) に引数を足し、pipeline から out_dir/'要変換'（出力フォルダの直下）を渡す。メッセージの先頭の理由の部分は変えない。package.upload_entries(out_dir, journal, meta, image_names, has_pdf) を作る。ZIP に入れるのは、{aid}.xml、今回置いた {aid}.pdf、Graphics のうち状態が ok・converted・user の画像だけ。make_zip は、この一覧だけを詰める（write_package と add_images の両方）。検証側として package.zip_problems(zpath, journal, meta) を作る。ZIP を読み直して、次を確かめる。(a) ZIP の名前が [A-Za-z0-9._-]+ か（EMSGM034E）。(b) パスの各部分が英数字か（違反はフォルダ名・ファイル名ごとに 1 件。Graphics の画像名は jstage_rules と重ねない）。(c) 記事フォルダの外の項目（'-'。EMSGM219E のおそれ）と、記事フォルダの中の想定外の項目（EMSGM074E）。(d) 0 バイトのファイル（XML は EMSGM053E、PDF は EMSGM059E、画像は EMSGM073E）。結果は Result.zip_issues に持ち、jstage_issues とは混ぜない。表示には両方を使う。記事フォルダにあるのに ZIP に入れなかったファイルは、package.unzipped_files で求めて Result.not_zipped に持つ。zip_issues と not_zipped は、convert と add_images の両方で計算し直す（res.warnings には入れない。add_images の後に古い警告が残るため）。not_zipped はレポート 10 章に出し、PDF は --pdf か手順 2、画像は --images か手順 7 で指定し直すよう案内する。レポート 14 章の PDF の行（report.py の『記事フォルダに入れる』）は、Colab なら手順 2、コマンドラインなら --pdf で変換し直す案内に変える。README の 要変換/ の行も直す。
- N4（巻・号・ページの入力の正規化。M1 の反証で見つけた）: ArticleMeta.from_dict（config.py:149〜153）で、volume・issue・fpage・lpage を NFKC で正規化する。volume・issue・fpage が [A-Za-z0-9]+ でなければ、欄の名前を入れた ValueError にする。今は巻・開始ページを全角で入れると、ZIP 名が jasme_３１_１.zip、フォルダ名が jasme/３１/1/３１_１/ になり、J-STAGE で EMSGM034E になるおそれがある。しかも誰も知らせない（rv_pkgnotify_check.py の 4）。docx の外の入力値なので、原則には触れない。
- U1（反証で ok、補足あり）: config._date(v, label='日付') を書き直す。fromisoformat は使わない。datetime は .date() にする（isinstance は datetime を先に判定する）。値を NFKC にして空白を除き、[0-9]{4}[0-9]{2}[0-9]{2} か、[0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2}日? に fullmatch すれば日付にする。それ以外は ValueError（文面に 'YYYY-MM-DD' を残す）。from_dict の日付の繰り返しで、欄の名前（発行日・受付日など）を渡す。2 桁の年と和暦は読まない。make_notebook.py の手順 3 の説明は『2026-03-31 の形で（2026/3/31 でもかまいません）』にする。

### D. 要対応の知らせ方を 1 か所にまとめる（レポート・Colab・コマンドライン）（0.21.1）

**理由**: 今は、何を要対応とするかが、レポートの冒頭（report.render L283〜315）、14 章（L548〜570）、Colab の枠（make_notebook.py の手順 5・6・8）、CLI（cli.py L95〜106）の 4 か所にばらばらに書かれている。DTD 不合格・J-STAGE のアップロード時チェック・PDF を読めなかった場合は、Colab に赤い枠が出ず、CLI も 0 を返す。A・B・C で増えた知らせ（画像の出力漏れ、柱とみなした行、ZIP の検査）をここで 1 か所に集める。こうしておけば、後の E・F・G で増える知らせ（文字だけのテキストボックスの未決定、改行のある題目など）は Action を 1 つ足すだけになり、make_notebook.py を毎回直さずに済む。出力（XML・ZIP）の形は変えないので 3 桁目。ただし CLI の終了コードの意味が変わる（--meta なし・画像不足でも 1）ので、README と変更点の知らせに明記する。

**前提**: C を反映した後（zip_issues と not_zipped が必要）。利用者の判断: 要対応の範囲（AI のエラー、PDF がない場合、手動モードで回答を貼り戻す前の出力）と、不変性チェックが不合格のときの手順 8 の止め方。ルート2 で PDF を読めないときの扱い（続けて知らせる）と、『別の記事の PDF』の疑いを要対応にするか要確認にするか。

- U2（反証で revise）: report.py に Action(level, key, top, checklist, box_title, box_detail) と actions(r) を作る。level は 2 つで、『要対応』は CLI の終了コード 1・Colab の手順 8 で一度止める・赤い枠、『要確認』は赤い枠・レポートの冒頭・14 章だけ（終了コードは 0）。今ある冒頭の文は、文面を変えずに top・checklist に移す（『注意: 文字の不変性チェックが不合格です』、仮に置いた図表、画像不足、ルート1 の PDF との違い）。14 章の行も同じ。新しく足す Action は次のとおり。DTD 不合格。jstage_issues + zip_issues。N1 の lost_images と暫定の知らせ（A で入れた個別の表示を移す）。pdf_fallback（M4）。ai.error。別の記事の PDF の疑い（要確認）。U7 の ignored_lines の件数（要確認）。ルート2 の『docx を直してから変換しました』の冒頭の案内と、14 章の『Word で開き、変更履歴を確認する』は actions() に入れず、今と同じ条件（fx is not None）で render の固定の部分に残す。入れると、すべて直せた場合にも赤い枠が出てしまう。not_zipped は 10 章の警告のまま。Result.ok の意味は変えず、property needs_action を足す。cli.main は要対応の一覧を標準エラーに出す。画像の項目は今の文面（『--images で指定するか』）をそのまま使い、`return 1 if res.needs_action else 0` にする（2 は中止のまま）。colab.result_boxes(res) を作る。AI のエラーの見出しは、mode が manual なら『貼り付けた回答を読み込めませんでした…』、API なら『AI による補完ができませんでした』と書き分ける。make_notebook.py の手順 5・6 の個別の枠をこれに置き換え、手順 8 の『一度止める』を要対応すべてに広げる（画像不足のときの文面は変えない）。既存テストの修正は次の 2 つ: test_pipeline.test_cli_images_option の 1 回目（== 0 → == 1）、test_pdfmatch.py の 274・278 行（--meta examples/meta_example.toml を足せば 0 のまま。rv_pkgnotify_check2.py で確認）。
- M4（反証で ok）: pipeline.Result に property pdf_fallback（route=='pdf' かつ docx_fix is None かつ pdf_check がある）を足す。report.render の 249 行目、colab、cli はすべてこれを使う。report.pdf_suspect(r)（段落の半分以上が見つからない）を切り出す。colab.pdf_diff_box は、`not pc.ok` のときに空文字を返さない。ルート2 では『出版版 PDF に合わせられませんでした』、ルート1 では『照合できませんでした』の赤い枠にする。pdf_suspect のときは『別の記事の PDF かもしれません』の枠を足す。どちらも U2 の actions() に入れる。make_notebook.py の手順 8 の説明は『（PDF の文字を読めたとき）PDF に合わせて直した docx も入っています』にする。手順 5 には、PDF に合わせられなかったときの 1 行を足す。
- N5（担当範囲の外で見つけた）: コマンドラインで --ai api を指定し、API キーがないと、anthropic SDK の TypeError のトレースバックで落ちる（ai_assist.call_api L404〜455 は anthropic.* の例外しか捕まえない）。cli.main で、API キーが見つからなければ ap.error で止める。call_api でも TypeError を out.error にする。

### E. 注（Word の文末脚注）と資料の見出し（0.22.0）

**理由**: D4 は、Word の文末脚注が XML から消える（除外として記録されるだけ）不具合である。脚注と文末脚注の ID が重なると、文末脚注の参照が脚注 fn1 へのリンクになる（誤った出力）。参照が削除の変更履歴の中にある脚注は、不変性チェックが不合格になる。D3 は、資料の見出しを認識できず、資料の文字が英文要旨（trans-abstract）に入る。どちらも structure.py の中では別の関数（attach_word_notes と RE_APPENDIX・build_front_en・build_back）を触り、ai_assist の set_role の規則（N6）を共有する。F の D1 より小さく独立しているので、先に出す。F が使う set_role_problem と pdfdocx._structure の領域の比較も、ここで用意する。出力の形が変わるので 2 桁目。

**前提**: D を反映した後（知らせは actions() に足す）。A の N3（文末脚注の空白段落）を土台にする。利用者の判断: 脚注と文末脚注の両方がある原稿の番号（推奨は本文で最初に参照される順の通し番号）と、文末脚注の番号の形式（推奨は fn_mark の『1)』）。英文要旨の後の見出しスタイルを資料とみなすか。引用文献の後ろの資料を扱うか。

- N6（set_role の可否を 1 つの関数にまとめる。D1・D4 と構造の反証で共通に見つけた）: ai_assist に set_role_problem(p, plan, role) を作る。role_overrides（L789〜813）と、build_request の除外一覧の案内『（本文の一部なら set_role を提案）』の両方で使う。今は、必ず捨てられる set_role を AI に勧めていたり、『採用』と記録されるのに何も変わらなかったりする（rvz_d4.py: e3・f3 への set_role）。この単位で拒否するもの: float_id のある段落（今のまま）、Word の脚注・文末脚注の段落（fn_start に限らずすべて）、region のない段落。テキストボックスの段落の規則は、F で足す。
- D4（反証で revise）: model.note_key(fn_kind, fn_id) と note_label(key) を足す。'-custom' は除いて判定する。FnNode に word_kind を足し、word_id には note_key を入れる。structure.attach_word_notes（L1179〜1205）を書き直す。まず、本文の参照を note_key で参照順に集める。続けて、集めた注の段落の中の参照も順に足す。除外された段落の中の参照も参照として数え、注を出力する（リンクのない注になることは Decision と 8 章で知らせる）。そのうえで、脚注・文末脚注を通し番号の FnNode にする。参照されていない注の段落は、plain() が空でなければ除外する（空白だけなら exclude_blank）。最後の『未対応』の除外のループ（A の暫定の知らせを含む）は削除する。参照の照合を直すのは次の箇所: emit.Emitter.write_object（note_key で fn_numbers を引く。今は ID だけを見るので、脚注 5 と文末脚注 5 が同じ fn1 になる）、pdfmatch._para_seq、pdfdocx の PARTS（word/endnotes.xml: 'e'）と _all_paragraphs、report の word_note_refs と 8 章・13 章（note_label）、ai_assist の注の一覧の表記。既存テストの修正は 2 つ: tests/test_pdfmatch.py:190 の鍵を ('fnref','footnote:5') と ('fnlist','footnote:5') に、tests/test_notes.py:91 の拒否理由の文言。ルート2 のテストは、sample_pdfcheck.pdf を作り直さず、extract_pages を差し替えて確かめる。customMarkFollows の文末脚注は、今の脚注と同じ扱い（中身のない xref、番号を 1 つ使う）を範囲外と明記するか、利用者が決める。
- D3（反証で revise）: structure.RE_APPENDIX（L47）を広げる。先頭の括弧（【［[〔〈《＜<(（）を許す。語の後の番号の前に『-－‐』と枝番を許す。番号の直後に、空白・コロン・ピリオド・読点・括弧・ダッシュ・行末を許す。ASCII のハイフンは語の直後に許さない（exp_struct_re.py の先読みに残っているハイフンは除く）。番号の文字に、Ⅰ-Ⅻ（U+2160–216B）、ⅰ-ⅻ（U+2170–217B）、①-⑳（U+2460–2473）を加える。build_front_en（L1064〜1140）では、英文要旨の後に章・節・項見出しのスタイルの段落が来たら資料を始め、Decision を記録する。和文の論文で、英文要旨にかな・漢字が 3 割以上の段落があれば、Decision（applied=False）と 10 章の警告を出す（自動では移さない）。ai_assist の ROLES に app_heading を足し、REGION_ROLES の front_en と app に加える。app には abstract も加え、誤って資料にした見出しを AI が英文要旨に戻せるようにする。ルート2 で英文要旨と資料の境が動いても検出できるよう、pdfdocx._structure（L485〜498）の比較に plan.region を加える（英文要旨・資料の段落は role が '' のままなので、今は比べていない）。引用文献の後ろに置かれた資料（rvz_d3.py）を扱うかは、利用者が決める。扱うなら build_back で、状態が refs・fn・notes・ack のときに、章・節・項見出しのスタイル、または参考文献のスタイル以外で RE_APPENDIX に合う段落から AppNode を始める。

### F. 文字だけのテキストボックス（囲み）と、本文の外に結び付いた図形（0.23.0）

**理由**: 問題文・ヒントなどの囲みは、数学教育の論文によくある。それが『図の一部』として XML から消え、AI でも戻せない（set_role は不採用、placements の対象外）。N7 も、同じ『図形の中身の行き先』の問題である。読み取り・構造・XML・AI・レポートにまたがる最大の変更（L）で、利用者の判断（boxed-text にするか、しきい値）も多い。そのため、検証の強化（A）、領域の切り替えの修正（A の N2）、sdt の読み取り（A の M3）、知らせ方（D）、set_role の規則と pdfdocx の領域の比較（E）がそろった後に置く。これらを先に入れておけば、この単位の差分は囲みそのものに集中する。出力の形が変わるので 2 桁目。

**前提**: A・D・E を反映した後。利用者の判断: <boxed-text> にするか <p> にするか（推奨は boxed-text。J-STAGE での表示は試験登載で確認）。AI なしで決められないものの扱い（推奨は除外して要確認）。判定のしきい値は、tests/private の実際の論文の囲みと注記で確かめてから決める（実際の論文の提供が必要）。本文の外に結び付いた図形を『位置を決められない図表』にし、AI なしでは中止することでよいか。

- D1（反証で revise）: 骨格は次のとおり。読み取りで model.TextBox（xid・anchor_src・float_id・inline・offset・大きさ）と Para.textbox_id / Table.textbox_id を記録する。入れ子の内側のテキストボックスは、外側の textbox_id を継ぐ。使われていない Document.textbox_excluded は削除する。floats.textbox_kind で、囲み（box）・図の注記（label）・決められない、のどれかに機械的に判定する。BoxNode を <boxed-text> にする（本文の冒頭では <p> で包む）。AI は placements の kind box・label で指定する。反証で次を加える・直す。(1) テキストボックスの段落への set_role（E の set_role_problem）: float_id のない段落では fig_caption・table_caption・exclude だけを受け付ける。ほかの役割は『placements（kind box / label）で指定する』として拒否する。今効いている VML のキャプションへの set_role fig_caption（rvz_d1.py）を壊さないため。SYSTEM_PROMPT:148 も合わせる。(2) BoxNode を、structure.assign_ids（L1207〜1259。囲みの中の別行数式に FD の ID を付けるため）、compute_locations、node_paras、linker.body_paragraphs、builder.nodes に足す。(3) box・label の指定の Decision は plan.float_decisions[xid] に入れ、pipeline.py:243 の採用の一覧に載るようにする。組み直した後に after が本文の段落でなければ、指定なしに戻す。(4) plan.body_seq（L557）から、textbox_id のある段落を除く。(5) 空白だけの段落は、どの経路でも exclude_blank にする。中身が空白だけのテキストボックスは、囲みにも要確認にもしない。(6) place_boxes は doc.textboxes を回し、place_floats とは別のパスにする。(7) 幅を読めないとき（VML の pt 以外の単位）は、幅の条件を使わない。near_image には、浮動配置の画像（ImageRef.inline=False）も含める。(8) FIELD_GUIDE（ai_assist.py:702〜706）と manual_prompt の文に、box・label を足す。(9) グループ図形の中の注記は、今の扱い（図の後に p）のまま範囲外と明記する。決められないもの・位置を推定したものは、Action（要確認）としてレポート・Colab・CLI に出す（D の actions() に 1 つ足すだけ）。A の暫定の知らせは削除する。
- N7（引用文献などの段落に結び付いた図形。反証で見つけた。rvz_back.py: 今は画像が XML と Graphics から黙って消え、テキストボックスの文字と図キャプションが mixed-citation になる）: アンカーが本文の外（引用文献・注・付記・謝辞・英文要旨）にある図形の中身は、その領域の段落として扱わない。画像・キャプション・表を含むものは place_floats で『位置を決められない図表』にする（今は structure.py:570 で本文にアンカーのある図形しか扱わない）。文字だけのものは、D1 の place_boxes で扱う。資料の中の図形は、今の扱い（資料の中に出す）を保つ。テキストボックスの外にあっても、引用文献などの段落そのものにある画像は、A の N1 で要対応として知らせ続ける。

### G. 読み取りの文字ポリシー（段落記号の削除・スタイルの隠し文字・セルの改行）（0.24.0）

**理由**: D5 と U8 は、どちらも ooxml（canonical_text の引数、新しい canonical_texts）、fidelity.source_texts、pdfdocx.write_fixed_docx・paragraph_units、docx_reader の同じ関数を触る。別々に出すと、同じ箇所を 2 回書き換えることになる。U3 と N8 も読み取りと出力の小さな直しで、新しい sample_reader.docx（A で作ったもの）を共用する。データの脱落ではなく『Word の表示との一致』の問題なので、脱落を直す A〜F の後に置く。どれも Word での確認が要る判断を含むため、利用者の確認を待つ時間を取りやすい位置でもある。D5 は docx_reader._textboxes（F で TextBox を記録する箇所）も触るので、F の後に置けば衝突を順に解ける。出力の形が変わるので 2 桁目。

**前提**: A（M3 の _children と test_reader の逆向きの確認）と F（TextBox の記録）を反映した後。F の判断が長引く場合は、G を F より先にしてもよい。そのときは、F の TextBox の記録で、つないだ段落を飛ばす。利用者の確認: sample_reader.docx を Word で開いて『すべての変更を反映』した後の段落のつながりとスタイルを見る（D5）。スタイルの隠し文字の表示を Word で見る（U8。後回しにするなら G から外す）。表のセルの改行に <break/> を補うか（U3）。

- D5（反証で revise）: ooxml に paragraph_mark_deleted(p)（w:pPr/w:rPr の w:del・w:moveFrom だけ。段落記号の w:vanish、つまりスタイル区切りはつながない）を足す。あわせて、joined_paragraphs(root)（同じ親の中で、次の兄弟が w:p のときだけつなぐ。bookmark などは飛ばす）、unjoined_deleted_marks(root)（つなぐ先のない段落とその理由）、canonical_texts(root, prefix, hidden) を足す。読み取り（docx_reader.read_paragraph・read_block・_textboxes・_read_nested_paragraph・read_notes）、検証（fidelity.source_texts）、ルート2（pdfdocx.write_fixed_docx）の 3 か所で、同じ規則を使う。後の段落の ID は欠番になる。書式は、前の段落が空なら後の段落のもの、そうでなければ前の段落のものにする。sectPr は最後の段落のものを使う。自動番号は、連鎖の最後で 1 回だけ label を呼ぶ（連鎖の途中かどうかは集合で判定する）。sdt・customXml の境界、表の直前、セル・テキストボックス・注・本文の最後ではつながない。LibreOffice は sdt・customXml の境界でもつなぐが、Word では未確認なので、ここでもつながない。代わりに 10 章の警告に『承諾できず 2 段落のまま出力した』と出す。pStyle の違う段落をつないだときは、Decision（4 章）に記録する。report.py:424 の文言も直す。F で入れた TextBox の段落一覧は、つないだ後に残った段落だけになるようにする。test_reader_matches_canonical は canonical_texts と比べる形に変える。
- U8（反証で revise。規則を直す）: ooxml.HiddenRule(styles_root) を作る。style_value(sid) は basedOn をたどり、vanish を最初に指定しているスタイル（いちばん派生した側）の値を返す。para_state は、docDefaults の値 XOR 段落スタイルの値。run は、直接の w:vanish があればその値、specVanish なら隠す、rStyle があれば ps XOR style_value(rStyle)、どれもなければ ps。この規則は LibreOffice の表示と 16 か所で一致した（rvz_u8_fixed.py）。設計の『連鎖の中で反転』の規則は、派生スタイルで食い違う。canonical_text(p, hidden=None)、docx_reader._walk（L287）、pdfdocx.paragraph_units に同じ規則を渡す。数式（m:r）・表スタイル・番号の書式の vanish は扱わないことを、文字ポリシーに明記する。隠し文字のレポート（_plain_of_run_child。L585〜590）は w:t とタブしか記録しないので、w:br・w:sym・w:noBreakHyphen にも広げるか、レポートの説明を正確にする。
- U3（反証で ok）: emit.Ctx に breaks を足し、CELL = Ctx(breaks=True) にする。Emitter.write_inline の flush で、書き込み先が jx:span そのもののときだけ、\n の前に <break/> を入れる（\n は文字のまま残す。書式の要素はいったん閉じる。リンクの中は今のまま）。p・題目・見出し・引用文献の \n はそのまま出力する。レポートの 10 章（警告）に一覧を出し、題目・著者・所属・引用文献にあるものは Action（D の actions()）にする。
- N8（D5 の関連。優先度は低い）: 変更履歴で削除された表の行（w:trPr/w:del）が空の行として出力される（d5_row.py。LibreOffice では行が消える）。read_table で、w:trPr/w:del があり、かつ canonical_text がすべて空の行だけを読み飛ばす。読み飛ばした行は記録する。削除されたセル（w:tcPr/w:cellDel）も同じ扱いになるか、実装の前に確かめる。

### H. リンクの誤検出と AI 依頼文の保守（0.25.0）

**理由**: D2（指数・単位の上付きが注へのリンクになる）と M5（『地図1』『付表1』が図・表へのリンクになる）は、リンクの誤りである。DESIGN 1 章が許容している種類なので、文字の脱落や構造の誤りより後にする。どちらも linker.py だけで済み、新しい sample_links.docx・sample_links_bare.docx と tests/test_links.py を共用する。U4 と U5 は保守性の直しで、U4 は D2・M5 と同じく AI 依頼文の中身に関わる（依頼文を確かめるテストをまとめられる）。U5 は make_notebook.py を触るので、版上げでノートブックを作り直す回にそろえる。structure.py は触らないので、I の分割とは順序が関係ない。リンクが変わるので 2 桁目。

**前提**: D を反映した後（リンクしなかった箇所は Decision としてレポートと AI 依頼文に出るだけで、actions() には入れない）。F の linker.body_paragraphs（BoxNode）の後にすると、囲みの中の上付きも同じ規則になる。利用者の判断: 注番号の書き方を論文ごとに判定する方針、記録の件数、参照の前に来てよい漢字、英文 1 語の氏名を AI 依頼文から外すこと。新しい fixture は、test_fidelity_and_dtd の jstage_issues == [] を満たす形で作る（図に画像、表に本体、注の一覧・引用文献・英文要旨を入れる）。

- D2（反証で revise）: 直すのは linker.py だけ。fn_marks の正規表現を RE_SUP_FN = (?:[注註][\s　]*)?[(（]?[\s　]*(NUM)[\s　]*[)）]? にし、_strong_mark は『注・註で始まる、または閉じ括弧で終わる』で判定する。Linker.run で論文ごとの bare_notes を決める（Linker.__init__ で True に初期化する）。上付きの外の文字でも補う。数字だけの一致が上付きの続きの最後にあり、直後の本文の文字が閉じ括弧で _exponent_like でなければ、番号の形がはっきりした注番号として扱う。続きの直前が『注・註』ならリンクする（書き方の判定には使わない）。数字と区切りだけの続き（1-3、1, 2）は、続き全体の前後で指数かどうかを判定する。符号で始まる続き（⁻¹）は指数とみなす。リンクしなかった数字は Decision に記録する。text は m.group(1)、回数は occurrence_at(p, s0+m.start(1), …) で数える。文面には link_note の text と occurrence を書く（AI 依頼文の段落一覧は上付きを示さないため）。数が多い論文での行のまとめ方は、利用者が決める。
- M5（反証で revise）: float_refs（L267〜278）を finditer から regex.search(plain, pos) のループに変える。直前の文字が漢字で、FLOAT_REF_OK_BEFORE='掲至及' に入らない一致は、語の一部とみなす。そのときは pos = m.end(2)（先頭の番号の直後）から探し直す。tail ごと飛ばすと、『図表1と表1』の後ろの正しい『表1』まで落ちるため。記録は、先頭の番号の図・表があるときだけ残す。
- U4（反証で revise）: builder.BuildInfo に unsplit_names: list（(段落ID, text.strip(' 　\t'), lang)）を足す。pipeline.py:205 の文言からの切り出しをやめ、build_request(plan, linker, info.exclusions, info.unsplit_names) にする。英文を除く処理は build_request の中に置く（単体テストで確かめられるように）。
- U5（反証で ok）: pipeline.Options.ai_model の既定を ai_assist.DEFAULT_MODEL にする。tools/make_notebook.py は、ai_assist.py から DEFAULT_MODEL をファイルとして読む。一致しなければ、分かるエラーにする。表示名・料金・提供終了の予定は DEFAULT_MODEL_INFO にまとめる。tests/test_ai.py の直書きのモデル名を DEFAULT_MODEL に置き換える。test_notebook.py は、パッケージから import した DEFAULT_MODEL と比べる。

### I. structure.py の分割（動作を変えない）（0.25.1）

**理由**: structure.py は、A（exclude_blank・float_mechanical・split_regions・除外漏れ）、E（attach_word_notes・RE_APPENDIX・build_front_en・build_back）、F（build_body・place_boxes・assign_ids・compute_locations・node_paras・body_seq）、G（任意の Decision）で直す。それより前に分けると、これらの差分がすべて衝突し、読みにくくなる。だから、structure.py を触る単位がすべて終わった後、新しい構造の作業を始める前に置く。H は structure.py を触らないので、H と I の順序はどちらでもよい。最後に置いて、それまでの全修正を含む出力が分割の前後で同じかを確かめる。出力は変わらないので 3 桁目。

**前提**: A・E・F・G を反映した後。利用者の判断: 動作を変えないリファクタリングだけの版を出すこと。出力の比較を常設のテスト（golden）にするか。

- U6（反証で revise。第 1 段階だけを推奨）: 新しい article.py に、構造のノード（Sec … FloatInfo。F で足した BoxNode も）、ArticlePlan、_para_text をそのまま移す。structure.py では `from .article import …  # noqa: F401 互換のため` で再 export する（ai_assist は _para_text を、tests は RefNode・FigNode・Sec・ArticlePlan を structure から import している）。structure.py の冒頭の docstring に、処理とメソッドの目次を書く。第 2 段階（図表の組み立ての分割）は任意で、行うなら次の 3 点を守る。(1) 共有の定数・関数（RE_FIGCAP・RE_TABCAP・RE_TEXTBOX_CAP・HEADING_LEVEL・nfkc・num_of）を先に article.py か小さな共通モジュールへ移す（循環 import を避ける）。(2) pipeline.py:67 の `from .structure import RE_FIGCAP, RE_TABCAP` を再 export で保つ。(3) 名前は、assemble_floats が本文のすべての図表を組むことが分かるものにする（例: figures.py / FigureAssembly）。docstring には、使う Classifier のメソッドと属性を列挙する。
- golden（出力の比較）: 分割の前後で、全 fixture（ALL_DOCS、AI の模擬回答つきの FLOAT と FULL、PDFCHECK のルート1・2）の XML・AI依頼文・レポート（版・日時・コミットの行を除く）が、バイト単位で同じであることを確かめる。比べ方は scratchpad/rvlm/fixdiff.py と同じ形。tests/test_golden.py と作り直しのスクリプトとして常設するかは、利用者が決める。

## 同じファイルを触る順と、既存テストの書き換え

- 各まとまりの設計は、どれも自分の変更を『0.19.0 にまとめる』と書いていて食い違う。この計画では単位ごとに版を分けた: A 0.19.0 → B 0.20.0 → C 0.21.0 → D 0.21.1 → E 0.22.0 → F 0.23.0 → G 0.24.0 → H 0.25.0 → I 0.25.1。main への反映はそのまま利用者に届くので、単位ごとに版を上げる。
- structure.py: 触る順は次のとおり。A（exclude_blank と L390・409・484・676・1022・1079・1101 の置き換え、L472〜474 と L1202〜1205 の空白段落、split_regions L325〜350、float_mechanical L678〜707）→ E（attach_word_notes L1179〜1205 を書き直す。A で直した文末脚注の空白段落の処理は、ここで消える。plain() に基づく空白の扱いは新しいコードに引き継ぐ）→ F（build_body L455〜541 の除外分岐 L470〜475、place_boxes、assign_ids L1207〜1259、compute_locations、node_paras、body_seq L557、split_regions の本文の外の図形）→ G（D5 の任意の Decision）→ I（分割）。分割（U6）を A〜G のどれかより先にすると、すべての差分が衝突する。
- docx_reader._textboxes / _read_nested_paragraph: A（M3 の _children）→ F（D1 の TextBox・textbox_id の記録）→ G（D5 で戻り値が None になる段落の扱いと、つないだ段落。U8 で段落の隠し文字の状態を退避して戻す）。F と G の順を入れ替えるときは、F の TextBox.paras を『つないだ後に残った段落』から作る。
- ai_assist.py: A（M6 で推奨案を採るなら、_placement_problem の body に画像の ID を認める）→ E（set_role_problem・REGION_ROLES の app_heading・Word の注の拒否）→ F（_placement_problem に box・label の分岐、テキストボックスの段落の役割の規則、FIELD_GUIDE・manual_prompt・SYSTEM_PROMPT:148）→ H（U4 で build_request に 3 つ組を渡す、D2 の SYSTEM_PROMPT の 1 文）。D1 の元の設計（in_textbox の段落への set_role をすべて拒否）は、今動いている VML のキャプションへの set_role fig_caption を壊す。反証の規則（fig_caption・table_caption・exclude は受け付ける）を採る。
- report.py の冒頭・14 章: A（N1 の画像の出力漏れと暫定の知らせを個別に足す。5 章の conflicts・bad_excluded）→ B（13 章の ignored_lines）→ C（14 章の PDF の行、10 章の not_zipped、12 章の zip_issues）→ D（U2 がこれらをすべて actions() に移す。ルート2 の『docx を直してから変換しました』と『変更履歴を確認する』は固定の部分に残す）→ E（note_label で 8 章・13 章）→ F・G（Action を足すだけ）。D より後の単位は、冒頭・14 章・Colab の枠に個別の表示を足さない。
- pdfdocx.py: B（plan_fixes の理由に TextDiff.why）→ E（PARTS に endnotes、_all_paragraphs、_structure に plan.region の比較）→ G（write_fixed_docx で段落をつなぐ規則、paragraph_units に HiddenRule）。どれも、書き込んだ後の確かめ（読み直した文字列と構造）は外さない。
- pdfmatch.py: B（U7 の pdf_stream・compare・_classify）→ E（D4 で _para_seq の note_key）。D4 で plan.pdf_numbers の鍵の形が ('fnref','footnote:5') に変わるので、tests/test_pdfmatch.py:190 の fnref と fnlist の両方の鍵を直す。
- pipeline.py: A（lost_images）→ C（write_package・add_images・zip_issues・not_zipped）→ D（pdf_fallback・needs_action）→ F（box の Decision を float_decisions 経由で採用に載せる、unresolved_after）→ H（L205 の unsplit、Options.ai_model）。どれも convert の別の節で、順に直せば衝突しない。
- tools/make_notebook.py: A（画像の出力漏れの枠）→ C（手順 3 の日付の説明）→ D（手順 5・6 の枠を result_boxes 1 つに、手順 8 の止め方と説明）→ H（DEFAULT_MODEL）。F の D1 は、D が先なら Action を足すだけで make_notebook.py は触らない（D1 の元の設計にある colab.textbox_box と手順 5・6 の変更は要らなくなる）。版を上げるたびにノートブックを作り直す。
- 既存テストの書き換えが要る箇所: D で test_pipeline.test_cli_images_option の 1 回目（== 0 → == 1）と、tests/test_pdfmatch.py の 274・278 行（--meta examples/meta_example.toml を足す）。E で tests/test_pdfmatch.py:190 と tests/test_notes.py:91（拒否理由の文言）。A で tests/test_reader.py の test_reader_matches_canonical（逆向きの確認）、G で同じテストを canonical_texts と比べる形に。H で tests/test_ai.py の 109・123・160・296 行のモデル名。
- fixture の共用と取り合い: sample_reader.docx は A で作り（M3）、G で D5・U3・U8 の段落を足す。sample_structure.docx は A で作り（N2・N3 の例）、E で D3・D4、F で D1・N7 を足す。sample_float_text.docx（M6。ALL_DOCS に入れない）、sample_pdfcheck_split.docx（D5）、sample_links.docx・sample_links_bare.docx（D2・M5）も足す。足すたびに件数で確かめるテストが壊れないよう、テストは段落の文字で対象を選ぶ。sample_edge・sample_notes は変えない（test_edge_cases の tracked_changes == 2、『注 1（うち Word の脚注 1）』などを保つ）。
- 設計と反証の食い違いは、すべて反証の方針を採る。M1（ZIP に入れなかったファイルは warnings ではなく not_zipped）、M2（テストに route の指定と importorskip は要らない）、M3（テストの逆向きの確認）、M6（判定は図の枝だけ。verify は除外をすべて回す）、U2（2 段階に、ルート2 の案内を外す）、D5（sdt・customXml の境界はつながずに警告）、U8（basedOn の連鎖は上書き）、D1（10 点の追加）、D3（ローマ数字・丸数字、ハイフン、ルート2 の領域の比較）、D4（空白段落、注の中の参照）、D2（註、上付きの外の文字、範囲の数字）、M5（tail ごと飛ばさず、探し直す）、U4（英文を除く処理は build_request に）、U6（循環 import、2 段階）、U7（理由の文言、実際に除いた行だけを記録、判定の場所）。

## 計画全体で足した作業

- 画像の出力漏れを検出するしくみがない（どの設計にもない。A の N1 に入れた）。不変性チェックは文字しか見ないので、images=False の文脈（題目・著者・所属・引用文献・ラベル。emit.py:39〜48、231）の段落にある画像は、警告もなく XML と Graphics から消える。scratchpad/plan_final/pf_n1.py で次を確かめた: doc.images と info.images の差は既存の fixture（AI の模擬回答・ルート2 を含む）で 0 件、rvz_back.py では img1。
- テキストボックスの段落で領域が切り替わる不具合（split_regions）を直す項目が、D1 の反証で見つかっただけで、どの設計にも入っていなかった。A の N2 に入れた。scratchpad/plan_final/pf_regions_proto.py で、全テストが通り、既存 fixture の出力が変わらず、rvz_tbabs.py・rvz_tbhead.py が直ることを確かめた。
- 引用文献などの段落に結び付いた図形の中身は、引用文献になる。画像は黙って消える（rvz_back.py）。これもどの設計にもない。A の N1 で知らせ、F の N7 で構造を直す。
- D1・D4 が入るまで、文字だけのテキストボックスと文末脚注は、レポート 6 章の除外の一覧に出るだけで目立たない。暫定の知らせ（冒頭と 14 章の要確認。対処は Word でテキストボックスの外に出す、本文の注に移す）を A に入れた。
- すでに J-STAGE に登載した記事、または変換済みの記事の確かめ直し。A（M6・N2・N1）、B（U7）、E（D4）、F（D1・N7）の不具合は、合格と表示されたまま文字・画像が消えたり、柱が本文に入ったりする。試験運用で変換した記事があれば、A・B の反映後に新しい版で変換し直し、XML と ZIP を前の出力と比べる（文字が増えた・画像が増えた箇所が、前の出力で落ちていたもの）。
- 利用者（編集委員）向けの変更点の知らせ場所がない。README にも docs にも更新履歴がなく、版ごとの変更はコミットメッセージにしかない。D（CLI の終了コードの意味、手順 8 の止め方）、C（ZIP の中身、要変換/ の場所）、F（囲みの出力）は、利用者の手順や結果の見え方を変える。docs/CHANGES.md（または README の『更新履歴』）を作り、ノートブックの手順 1 の版の表示からたどれるようにすることを勧める。
- CLAUDE.md の更新。A: 空白だけの除外は exclude_blank、画像の出力漏れも検出する。C: ZIP に入れるものは package.upload_entries だけで決め、zip_problems で読み直す。D: 利用者に知らせることは report.actions() に足す。CLI の終了コードは、0 が要対応なし、1 が要対応あり、2 が中止。G: 段落のつながり（ooxml.joined_paragraphs）と隠し文字の判定（ooxml.HiddenRule）は、読み取り・検証・pdfdocx で共有する。I: 分割後のファイルの役割。DEVELOPMENT.md の『守るべき原則』も同じ内容にそろえる。
- docs/DEVELOPMENT.md の更新。テストの節は今の 5 つの fixture しか挙げていない。sample_reader・sample_structure・sample_float_text・sample_pdfcheck_split・sample_links・sample_links_bare と tests/test_links.py を加える。コードの構成の表に、package.py の ZIP の確認と、article.py（と分割したファイル）を加える。『残っている課題』に、boxed-text・td の <break/>・文末脚注の番号の J-STAGE での表示、Word での変更の承諾（D5）とスタイルの隠し文字（U8）の確認、実際の出版版 PDF の柱（U7）を加える。『よくある拡張』に、actions() とモデルの変え方（U5）を加える。『Colab ノートブック』の手順 8 の説明も直す。
- DESIGN.md 4.4 の『リンク（注・引用文献・図表など）が元の docx と同じに決まるか』は、実際には『元のリンクが失われないか』である（pdfdocx._lost L501〜528 は削除・置換しか見ない）。D2・M5 で判定の規則が変わると、ルート2 でリンクが増えることがある。正確に書き直す（H）。
- fixture の作り直しの注意。python tests/make_fixtures.py はすべての docx と、LibreOffice があれば sample_pdfcheck.pdf も作り直す（この環境には /usr/bin/soffice がある）。LibreOffice の版によって PDF のバイトが変わりうるので、PDF の差分は意図したときだけコミットする。D4 のルート2 のテストは、PDF を作り直さずに extract_pages を差し替えて書く。
- scratchpad/test_review.py の PROBLEM テストを、期待を逆にして tests/ に取り込む。割り当ては、ZIP の 2 件は C、文字だけのテキストボックスは F、上付きの指数は H、括弧付きの資料は E、sdt の行は A、文末脚注は E、出力と除外の重なりは A、語の中の図番号は H（正規表現そのものを調べるテストなので、M5 の後も結果は変わらない。float_refs の結果で確かめる形に書き直す）、日付は C、段落記号の削除は G。test_PROBLEM_normal_paragraph_before_first_heading… は、今のコードでは再現しない（scratchpad/plan_final/pf_front.py で、その段落が body の先頭の <p> に出ることを確かめた）。取り込まない。
- AI の依頼文と回答の形を変える項目（F の placements の box・label、E の app_heading と set_role の拒否、H の『推定:』の行）は、模擬回答でしか確かめられない。試験運用で、実際の AI（少なくとも Claude）で一度ずつ確かめる。
- 実際の論文での確認。D1 のしきい値（文章の 20 字、段の幅の 6 割、注記の 15 字・4 割）と、U7 の柱・ページ番号の形は、架空の fixture では決められない。tests/private の実際の論文と出版版 PDF で、各単位の反映の前に、前後の出力（XML・レポート）を比べる。
- Colab の手順 6 は output を消さずに変換し直す。前回の画像が Graphics/ に残り、手順 8 の『変換結果』の ZIP に入りうる。C でアップロード用の ZIP には入らなくなるが、『変換結果』には残る。実害は小さい。手順 6 の最初で、その記事の Graphics/ と 要変換/ だけを空にすることを検討する。
- G の関連で、削除されたセル（w:tcPr/w:cellDel）の扱いは確かめていない。隠し文字のレポートは w:t とタブしか記録しない（w:sym・改行・ハイフンが 6 章に載らない）。数式・表スタイル・番号の書式の vanish は扱わない。これらを文字ポリシーに明記する。
- CI は Python 3.10 と 3.12 で動く（DEVELOPMENT.md）。U1 は、date.fromisoformat の版による違い（3.11 以降は ISO 週の形も読む）をなくす変更なので、3.10 でもテストが通ることを CI で確かめる。正規表現の \d ではなく [0-9] を使う。

## 毎回の共通作業

- セッションの最初に pip install -e ".[dev]" を実行し、docs/DEVELOPMENT.md と docs/DESIGN.md の関係する章を読む。main から作業用のブランチを作る（main に直接コミットしない。反映は利用者の了承の後）。
- 変更の前に基準の出力を取る。scratchpad/rvlm/fixdiff.py と同じ形のスクリプトで、全 fixture の出力のハッシュを記録する。対象は ALL_DOCS（手動モード）、AI の模擬回答つきの FLOAT と FULL、PDFCHECK のルート1・2。記録するのは XML・AI依頼文.txt・レポート（版・日時・コミットの行を除く）。tests/private に実際の論文があれば、その出力も残す。変更の後にもう一度取り、違いがすべて意図したものであることを確かめる（コミットメッセージに書く）。
- 原則の確かめ。文字列を書き換えるコードを足さない（構造は LinkSpec か段落の役割で表す）。XML の段落の文字は Emitter.span だけで書く。出力しない段落は plan.exclude（空白だけなら A の後は exclude_blank）で理由を付けて記録する。新しい docx の要素は、ooxml.canonical_text（検証）と docx_reader（変換）、ルート2 の pdfdocx.paragraph_units / raw_paragraph_ids を同じ文字ポリシーで直す。
- テスト用の docx は tests/make_fixtures.py で作る（内容は架空）。ALL_DOCS に入れるものは、不変性チェック・最終チェック・DTD・jstage_issues == [] をすべて満たす形にする。python tests/make_fixtures.py の後に git diff --stat tests/fixtures を見て、意図しない docx・PDF の変化（LibreOffice で作り直した sample_pdfcheck.pdf など）を戻す。実際の論文は tests/private にだけ置き、コミットしない。新しい docx をリポジトリに加えるときは tools/sanitize_docx.py を通す。
- scratchpad/test_review.py の、その単位に当たる PROBLEM テストの期待を逆にして tests/ に取り込む。python -m pytest -q がすべて通ることを確かめる（GitHub Actions の Python 3.10 / 3.12 でも通ること）。
- XML が同梱の DTD に合うことは、jasme_jats.validate.validate で確かめる。J-STAGE の仕様に関わる変更（boxed-text、break、ZIP の構成、メッセージの番号）は、docs/JSTAGE_NOTES.md とマニュアル（https://www.jstage.jst.go.jp/static/pages/GuidelineAndManuals/zenbun-xml-jats1_1-manual/-char/ja）で確かめ、根拠を JSTAGE_NOTES.md に書く。
- 版を上げる。src/jasme_jats/__init__.py と pyproject.toml の version を、計画の版（出力の形が変わる単位は 2 桁目、それ以外は 3 桁目）にそろえる。
- python tools/make_notebook.py でノートブックを作り直す（ipynb は直接編集しない）。tests/test_notebook.py の test_notebook_is_up_to_date が通ることを確かめる。
- 文書を直す。DESIGN.md（該当する章）、DEVELOPMENT.md（コードの構成の表・守るべき原則・テストの節・残っている課題・よくある拡張）、README.md（利用者向けの説明・出力されるもの・レポートの見方）、STYLE_MAPPING.md、JSTAGE_NOTES.md、モジュールの docstring。原則・手順が変わる単位では CLAUDE.md も直す。変更点の知らせ場所（docs/CHANGES.md など）を作るなら、そこにも書く。どれも日本語で、既存の書き方に合わせる。
- コミットメッセージは日本語で、既存の形（『…（0.x.y）』）に合わせ、指定の帰属の行を付ける。main への反映の後は、Colab でノートブックを開き直し、『セッションを再起動』してから手順 1 を実行して、版の表示と、サンプルの変換（ルート1・2）を確かめる。出力が大きく変わる単位は、反映の前に開発版（USE_DEV_VERSION）で利用者に試してもらう。
- 試験運用で確かめることを DEVELOPMENT.md の『残っている課題』に記録し、確かめた結果を JSTAGE_NOTES.md に残す。対象は、J-STAGE の試験登載での表示（boxed-text、td の <break/>、文末脚注の番号）、ZIP のアップロード、Word での変更履歴の承諾、実際の AI での新しい回答の形。

## 付録: 項目ごとのテスト（設計と点検で挙げたもの）

N1〜N8 のテストは、各単位の詳細の中に書いた。

### D1 文字だけのテキストボックス（囲みの問題文・ヒントなど）が XML から消え、AI でも戻せない

tests/make_fixtures.py に足すもの:
- 部品: textbox_inline（wp:inline の wps）、vml_textbox（position:absolute の有無を選べる）。
- make_structure で作る sample_structure.docx（conftest の ALL_DOCS に入れる）。中身:
  - (a) at_anchor の幅の広い囲み（問1…。／ヒント…。）
  - (b) 画像の段落・図キャプションの次の段落に付けた、v を負にした小さい注記「A 点」
  - (c) 段落の末尾にある inline の囲み
  - (d) 幅が広く短い「（ヒント）」（決められないもの）
  - (e) VML だけの囲み（position:absolute）
  - (f) 図キャプションを含むテキストボックス（今の扱いが変わらないことを見る）
  - D3・D4 の要素もこの fixture に入れる

tests/test_structure.py に足すテスト:
- (a) は <boxed-text> になり、アンカー段落の前に置かれる。(c) はアンカー段落の後に置かれる。
- (b) は除外され、理由が「図に重ねた注記」で、警告が出る。
- (d) は AI なしでは除外され、レポートの冒頭とチェックリストに要確認が出る。
- (e) はアンカー段落の後に置かれ、3 章に要確認が出る。
- 手動モードの回答（placements の kind box・label）で、(d) が指定の段落の後の boxed-text になる。label の場合は除外される。after が図形の中の段落なら採用されない。
- (e) の段落への set_role は、placements で指定するよう求めて採用されない。
- すべての docx で、不変性チェック・最終チェック・DTD・jstage_rules に合格する。
- floats.textbox_kind の単体テスト（しきい値の境界）。

scratchpad の test_review.py の test_PROBLEM_text_only_textbox_is_dropped_from_xml を、期待を逆にして取り込む。

点検で足したテスト: - VML テキストボックスの「図1　…。」に set_role fig_caption を出すと採用され、F1 のキャプションになる（回帰しない）。同じ段落への set_role p は placements を案内して拒否される。
- 囲みの中に「(1)」付きの別行数式があるとき、disp-formula に id FD1 と label が付き、本文の「式(1)」がリンクになる。
- 囲み・label・undecided・未配置の図形（手動モードで回答前）のそれぞれに全角空白だけの段落を入れても、不変性チェックに合格する。
- 本文のテキストボックスに「英文要旨」スタイルの段落や「注」だけの段落があっても、sec の数、trans-abstract の段落数、fn-group の有無が変わらない。
- 手動モードで kind box を指定すると、ai.accepted に place_float として載る。after に囲みの中の段落を指定すると不採用になる。
- 空のテキストボックスでは、boxed-text も要確認も出ない。
- VML の width が pt 以外のとき、label に倒れない。

### D2 上付きの指数・単位（cm²・x²・s⁻¹）が注へのリンクになる

tests/make_fixtures.py に make_links(path, bare=False) を足して、2 つの docx を作る。sample_links.docx は「1)」の書き方で、本文に「3 cm²」「x²+y²」「m s⁻¹」「1,2)」「1-3)」「注3」があり、注は 1)〜3)。sample_links_bare.docx は数字だけの書き方で、本文に「主張である¹」「（試験, 2020）²」「4 m²」があり、注の一覧は上付きの数字。どちらも conftest の ALL_DOCS に足して、不変性と DTD の共通テストにかける。新しい tests/test_links.py では次を確かめる。(1) 注の xref の (文字, rid) の集合がちょうど期待どおりで、cm²・x²・s⁻¹ にはリンクがなく、「1,2)」「1-3)」の 1 にはある。(2) 数字だけの論文では ¹ ² がリンクされ、m² はされない。(3) リンクしなかった数字が plan.decisions（category note）とレポートに出る。(4) 手動モードで link_note（text「2」、occurrence は decision に書いた回数）を貼り戻すと採用される。既存のテストは変えずに通ることを試作で確かめた。make_fixtures.py を実行すると全 docx と（LibreOffice があれば）sample_pdfcheck.pdf も作り直されるので、差分を確かめてからコミットする。

点検で足したテスト: 設計の sample_links / sample_links_bare に次を加え、期待値を確かめる。
・「1)」の書き方の論文: 上付き「註1」→ fn1。本文「である」＋上付き「1」＋本文「)」→ fn1。本文「注」＋上付き「1」→ fn1。本文「f(x」＋上付き「2」＋本文「)」→ リンクなし（記録あり）。上付き「⁻¹」→ リンクなし。
・数字だけの論文: 上付き「1-3」→ 1 と 3 がリンクされる。上付き「1, 2」→ 1 と 2。前に「注」の字がない段落で作ること（作った例では「並びの注」＋上付き「1, 2」が「注」の規則に当たった）。
・記録の text に空白が入らないこと。その回数で link_note を貼り戻すと採用されること（試作で accepted を確認済み）。
・既存 fixture の XML・AI依頼文・レポートが変わらないこと（golden の比較）。

### D3 「資料（授業プリント）」のような資料の見出しを認識できず、以降の段落が英文要旨（trans-abstract）に入る

- tests/test_structure.py に、RE_APPENDIX の認識する書き方・認識しない書き方の parametrize テスト（exp_struct_re.py の一覧）を足す。
- sample_structure.docx に、英文要旨の後の「資料（授業プリント）」と、それに続く 2 段落を入れる。期待: app-group/app/title が「資料（授業プリント）」になり、続く段落は app の中にあって trans-abstract に入らない。不変性チェックと DTD に合格する。
- 英文要旨の中に和文の段落がある docx で、Decision と警告が出ることを確かめる。
- test_ai.py: 英文要旨の段落への set_role app_heading で資料が始まること、英文題目への app_heading は採用されないこと。
- scratchpad の test_review.py の test_PROBLEM_appendix_with_paren_goes_into_abstract を、期待を逆にして取り込む。

点検で足したテスト: - 「資料Ⅰ　授業プリント」「資料Ⅱ（ワークシート）」「付録①　調査票」が app-group/app/title になる。
- ルート2（pdfmatch.extract_pages を monkeypatch）: 英文要旨と資料の境を変えてしまう変更が直されない。
- 見出しのスタイルで始めた資料に set_role abstract を出すと、英文要旨に戻る。
- 引用文献の後ろに、章見出しのスタイルの「資料　…」がある原稿の期待（app-group、または警告）。

### D4 Word の文末脚注（endnotes）が XML に出ない。あわせて、脚注と ID が同じ文末脚注の参照が脚注へのリンクになる

tests/make_fixtures.py:
- Builder に endnotes_extra を足し、save で word/endnotes.xml に追記するようにする。
- sample_structure.docx に次を入れる: 脚注 id=5 と文末脚注 id=5（衝突させる）、参照が w:del の中にある脚注、customMarkFollows の文末脚注。

tests/test_notes.py に足すテスト:
- 文末脚注が fn-group の fn2 になり、本文の参照が rid=fn2・「2)」になる。脚注の参照は fn1 のまま。
- 参照されていない脚注が理由付きで除外され、不変性チェックに合格する。
- 脚注・文末脚注の段落への AI の set_role（p・exclude）が採用されない。
- レポートの文言（脚注だけのときは今のまま）。

その他:
- tests/test_pdfmatch.py:190 の期待 ("fnref", "5") を ("fnref", "footnote:5") に変える。
- ルート2: sample_pdfcheck に文末脚注を足し、LibreOffice で PDF を作り直す。LibreOffice が使えなければ、pdfdocx.write_fixed_docx に文末脚注の段落の Fix を直接渡し、読み直して確かめるテストにする。
- scratchpad の test_review.py の test_PROBLEM_endnotes_are_excluded を、期待を逆にして取り込む。

点検で足したテスト: - 文末脚注と、参照されていない脚注に、全角・半角の空白だけの段落を入れても、不変性チェックに合格する。
- 脚注の中から文末脚注を参照しても、その文末脚注が除外されない。
- 脚注 id=5 と文末脚注 id=5 が衝突しても、rid が fn1・fn2 に分かれる。
- ルート2: 番号の表に「Word の文末脚注 5」と出る。

### D5 段落記号の削除（w:pPr/w:rPr/w:del）を承諾した状態として、次の段落とつなぐ

make_fixtures.py に、読み取りの境界ケースを集めた新しい fixture『sample_reader.docx』を作り、conftest.ALL_DOCS に加える。sample_edge に足すと test_edge_cases の tracked_changes == 2 などが変わるため。入れる段落: 本文+本文、文字ごと削除した節見出し+本文（後の書式になる）、節見出し+本文（見出しのまま）、本文+節見出し、表の直前の段落、セルの最後の段落、3 段落の連鎖、自動番号付きの段落の連鎖、テキストボックスを含む段落の連鎖。
test_reader.test_reader_matches_canonical は、w:p ごとの canonical_text ではなく ooxml.canonical_texts と比べるように変える。
test_reader に、つながった段落の文字・スタイル・ID の欠番・warnings・自動番号の計数を確かめるテストを追加する。
test_pipeline に、XML でつながった <p> と <title> になること（test_review.py の test_PROBLEM_deleted_paragraph_mark_keeps_two_paragraphs の逆）を確かめるテストを追加する。
make_pdfcheck に split=True を足して『sample_pdfcheck_split.docx』を作る（d12 を段落記号の削除で 2 つに分けたもの。PDF は今のものをそのまま使う）。test_pdfmatch に、ルート2 で 1 段落として PDF どおりに直ることを確かめるテストを追加する（scratchpad/rd_plan/d5_route2.py と同じ手順）。

点検で足したテスト: ・試作で確かめた境界（rvz_policy/rvz_d5_edges.py と同じ内容）を sample_reader.docx に入れ、test_reader で確かめる。
  - 脚注の中で、1 段落目の段落記号を削除した場合: doc.footnotes の段落が 1 つになり、文字が『注の前半と注の後半。』になる。
  - 文字ごと削除し、段落記号も削除した番号付き段落の次の番号付き段落の autonum が『2.』になる。
  - 後の段落にテキストボックスのアンカーがある場合: Float.anchor_src が最初の段落の ID になる。
  - テキストボックスの中での連鎖。
・次が w:sdt・w:customXml の場合と、sdtContent の最後の段落の場合: 2 段落のまま出力され、warnings に『承諾できず』の行が出る。
・test_reader_matches_canonical は ooxml.canonical_texts と比べる。さらに逆向きの確認（canonical で空でない ID がすべて読まれていること）を足し、脚注（f）も対象にする。
・test_pdfmatch: 段落記号の削除をまたぐ直し（前の段落の最後と、後の段落の最初にかかる Fix）が、w:t 単位で書き込まれ、読み直した文字列が一致する。

### M1 EMF/WMF を変換できなかったとき、アップロード用 ZIP に「要変換/」フォルダと EMF が入る

tests/test_pipeline.py に test_upload_zip_has_only_this_article を足す。(1) convert(TEMPLATE, convert_metafiles=False) の ZIP の namelist が ['jasme/31/1/31_1/31_1.xml'] だけであること、すべての名前が ASCII であること、(tmp_path/'要変換'/'31_1_01.emf').exists()、'要変換/31_1_01.emf' が images[0].message にあること、jstage_issues == [] を確かめる。(2) add_images(res, {'31_1_01.png': png}) の後の namelist が [xml, 'jasme/31/1/31_1/Graphics/31_1_01.png'] になること。(3) zipfile で手作りした ZIP（'jasme/31/1/31_1/要変換/x.emf' を含む）に zip_problems を当て、EMSGM034E と EMSGM074E が返ること。既存の test_package_layout・test_template_emf_conversion・test_add_images_puts_user_images_into_zip_and_report・tests/test_notebook.py の手順 7 のテストは、そのまま通るはず（メッセージの先頭と Graphics の場所は変えない）。make_fixtures.py の追加は要らない（TEMPLATE に EMF がある）。

点検で足したテスト: - test_rerun_with_user_images_keeps_report_consistent: 同じ tmp_path で次の順に実行する。TEMPLATE（convert_metafiles=False）を変換 → add_images({'31_1_01.png': png}) → もう一度変換 → add_images(同じもの, skip_unneeded=True)。その後に res.not_zipped == [] であること、レポート 10 章に「ZIP に入れなかった」がないこと、namelist に jasme/31/1/31_1/Graphics/31_1_01.png があることを確かめる。
- 1 回目の変換の後、記事フォルダに memo.txt を手で置いて変換し直す。res.not_zipped == ['memo.txt'] で、レポート 10 章にその旨が出ることを確かめる。
- zip_problems: zipfile で手作りした ZIP で確かめる。ZIP 名 jasme_３１_１.zip → EMSGM034E が 1 件。中身が 0 バイトの jasme/31/1/31_1/31_1.pdf → EMSGM059E。jasme/31/1/31_13/… が入っている → '-'。
- convert(PDFCHECK, pdf_path=空のファイル) → res.zip_issues に EMSGM059E があること。
- 入力の正規化を採るなら: ArticleMeta.from_dict({'volume': '３１', 'issue': '1', 'fpage': '１'}).article_id(journal) == '31_1' であること、volume='31巻' が ValueError になること。
- レポートの 14 章の PDF の行に '--pdf' と '手順 2' があること。

### M2 同じ出力フォルダで 2 本目を変換すると、2 本目の ZIP に 1 本目の記事フォルダも入る

tests/test_pipeline.py に test_zip_of_second_article_in_same_out_dir を足す。同じ tmp_path で FULL を fpage=1 と fpage=13 で変換し、r2.zip_path の namelist がすべて 'jasme/31/1/31_13/' で始まること、r1.zip_path の中身が変わらないことを確かめる。同じ記事識別子で、1 回目は PDFCHECK に pdf_path=PDFCHECK_PDF を付け、2 回目は PDF なしで変換し、'jasme/31/1/31_1/31_1.pdf' が ZIP にないこと、has_pdf が False であること、warnings に「31_1.pdf」があることを確かめる（pypdfium2 は要らない。PDF を写すだけなので route='docx' で照合を飛ばすか、pytest.importorskip を付ける）。

点検で足したテスト: test_zip_of_second_article_in_same_out_dir に次を足す。
- 同じ記事識別子で、1 回目は pdf_path にダミーの PDF を付け、2 回目は付けずに変換する。2 回目の後に次を確かめる: res.not_zipped == ['31_1.pdf']、ZIP に 'jasme/31/1/31_1/31_1.pdf' がない、has_pdf が False、14 章の PDF の行が '- [ ]' で '--pdf' を案内している。
- 開始ページを打ち間違えて変換し直した場合（fpage を 1 → 15）: 2 回目の ZIP の namelist がすべて 'jasme/31/1/31_15/' で始まり、zip_issues == [] であること。

### M3 w:sdt・w:customXml に包まれた表の行・セル（とテキストボックスの段落）も読む

sample_reader.docx（D5 と共用）に、次の 4 つの表を入れる: w:sdt に包んだ行、w:customXml に包んだ行、w:customXml に包んだセル、入れ子の w:sdt に包んだ行。テキストボックスの中で w:sdt に包んだ図キャプション（画像段落と組になる単純な形で、機械的に配置されるもの）も入れる。
test_reader_matches_canonical（ALL_DOCS）で、すべての段落が読まれることを確かめる。
test_reader に、表の行数とセルの文字の順序を確かめるテストを追加する。
test_pipeline.test_fidelity_and_dtd で、不変性チェックと DTD の合格を確かめる（test_review.py の test_PROBLEM_table_row_inside_sdt_is_not_read の逆）。

点検で足したテスト: ・test_reader: sample_reader.docx の 4 つの表で、行数（Table.rows）とセルの文字の順序を確かめる。
・テキストボックスの中の sdt の段落が、in_textbox=True、同じ float_id で読まれることを確かめる。
・上の逆向きの確認を ALL_DOCS + [FLOAT] に足す。

### M4 ルート2 で PDF の文字を読めなかったとき、Colab に赤い枠が出ず、CLI も終了コード 0

tests/test_pdfmatch.py の test_route2_with_unreadable_pdf_converts_original に足す。pdf_diff_box(res) に '#dc2626'・'出版版 PDF に合わせられませんでした'・'画像だけの PDF' があること。レポートの '## 2.' より前に '要対応: 出版版 PDF に合わせられませんでした' があること。'## 14.' の後ろに 'docx を PDF に合わせていない' があること。同じ monkeypatch のまま main([PDFCHECK, '--meta', examples/meta_example.toml, '--out', …, '--pdf', dummy, '--no-metafile-conversion']) が 1 を返し、capsys の err に理由が出ること。ルート1 で読めない場合は、枠の見出しが「照合できませんでした」になり、終了コードが 0 であることも確かめる。test_wrong_pdf_changes_nothing に、pdf_diff_box(res) に '別の記事の PDF' があることを足す。fixture の追加は要らない（既存の PDFCHECK・NOTES・sample_pdfcheck.pdf と monkeypatch で足りる）。

点検で足したテスト: - 壊れた PDF（monkeypatch なし）: tmp_path に 0 バイトの PDF を作り、ルート2 で変換する。res.pdf_fallback が True、pdf_diff_box(res) に「出版版 PDF に合わせられませんでした」と「PDF を読めなかった」があることを確かめる（M1 の zip_problems では EMSGM059E にもなる）。
- pypdfium2 がない場合: monkeypatch で pdfmatch.extract_pages が ImportError を投げるようにする。枠と CLI の標準エラーに「pypdfium2 が入っていない」が出て、終了コードが 1 になることを確かめる（コマンドラインでは [images] を入れていないと、この経路になりやすい）。
- ルート2 ですべて直せた PDFCHECK では、今までどおり pdf_diff_box(res) == '' で、pdf_suspect が False であることを確かめる。

### M5 語の中の「図1」「表1」（地図1・図表1・発表1回目・付表1）が図・表へのリンクになる

sample_links.docx（D2 と共用）に、「地図1」「図表1」「発表1回目」「概念図1」「代表1名」「付表1」「前掲表1」「図1乃至図2」「（図1）」「図1、2」を含む段落と、図1・図2・表1 を入れる。test_links.py で、fig/table の xref が前掲表1・乃至・括弧・tail の参照だけであること、地図1 などに対応する Decision があり、発表1回目（表1 あり）にも Decision があることを確かめる。既存の fixture は XML が変わらないことを試作で確かめた（sample_full の「図1，2」「表1のとおり」なども今までどおり）。

点検で足したテスト: test_links.py に足す。
・「図表1と表1」: 後ろの「表1」が T1 にリンクされ、図表1 の「表1」はリンクされない。
・「地図1、図2」: 図2 が F2 にリンクされる。
・「地図1、2」: どちらもリンクされない（記録は 1 件）。
・「前掲表1」は T1、「付表1」はリンクされず記録あり。
sample_links.docx を ALL_DOCS に入れるなら、test_fidelity_and_dtd が `res.jstage_issues == []` まで求めるので、図1・図2 に画像を入れ、表1 に本体を付ける。

### M6 不変性チェックで、出力と除外の矛盾、空白のはずの除外に文字があることを不合格にする（図形の中の画像段落の文字の脱落も直す）

test_fidelity.py に 2 つ追加する。
- test_output_and_excluded_paragraph_is_detected: 出力した段落の src で Exclusion を足すと、not ok で conflicts に載る（test_review.py の test_PROBLEM_fidelity_does_not_flag... の逆）。
- test_blank_exclusion_with_text_is_detected: 文字のある段落の span を取り除き、Exclusion(src, 理由, '', blank=True) を足すと、not ok で bad_excluded に載る。
make_fixtures.py に、小さな『sample_float_text.docx』を作る（テキストボックスに、画像と文字の段落と図キャプション。ALL_DOCS には入れない）。test_floats で 2 つを確かめる: AI を使わない設定では AIRequiredError になること、手動モードの模擬回答で、その文字が XML に残ること。
既存の全 fixture で conflicts と bad_excluded が 0 件であることは、test_pipeline.test_fidelity_and_dtd で確かめられる。

点検で足したテスト: ・test_floats に追加する。
  - キャプションのないテキストボックスで、画像と文字が同じ段落にある場合: AI を使わない設定でも止まらず、文字が <p> に出る（rvz_m6_nocap.py の base と同じ結果）。
  - キャプションのある場合: AI を使わない設定では AIRequiredError になる。
  - 手動モードの回答で、その段落（または画像）を body にした場合: 不採用になり、文字は XML に残る（rvz_m6_ai.py）。
・test_fidelity: 同じ段落に除外が 2 件あり、2 件目だけが blank で文字がある場合も、bad_excluded として検出される。

### U1 日付の入力で 2026/3/31・2026.3.31 のようにゼロ埋めしない書き方を読めない

tests/test_pipeline.py に test_dates_accept_common_forms を足す。'2026-03-31'・'2026/3/31'・'2026.3.31'・'2026-3-31'・'2026年3月31日'・'２０２６／３／３１'・'20260331'・' 2026/3/31 ' がすべて date(2026, 3, 31) になること。'2026/13/1'・'2026-02-30'・'26/3/31'・'2026-W13-2'・'2026-03' は ValueError（match='YYYY-MM-DD'）になること。ArticleMeta.from_dict({'received': '2026/13/1'}) のエラーに「受付日」が入ること。既存の test_peer_review_missing_or_invalid の '2025/13/40' → match 'YYYY-MM-DD' は、文面にこの文字列を残すのでそのまま通る。

点検で足したテスト: 実装のときに次を確かめる。
- isinstance の判定は datetime を先にする（datetime は date の派生なので、date を先に判定すると datetime のまま返る）。tomllib は、引用符なしの日時を datetime で返す。
- label の既定値は「日付」にする（'' だと、文が「「…」を読めません」で始まる）。
- 空白だけの値（'　'）は、今と同じく None にする。
- 正規表現の数字は NFKC の後に [0-9] にする（\d のままだと、アラビア・インド数字なども通る。害はないが、範囲をはっきりさせるため）。
- テストに足す: _date(datetime(2026,3,31,10,0)) == date(2026,3,31)、_date('　') is None、'2026-03-31 10:00' は ValueError。

### U2 J-STAGE のアップロード時チェックで要対応があっても CLI の終了コードが 0。要対応の知らせ方が画面ごとにそろっていない

tests/test_pipeline.py: 受付日を受理日より後にして FULL を変換し、actions(res) に level '要対応' で EMSGM106E を含む項目があること、レポートの '## 2.' より前に「要対応: J-STAGE のアップロード時チェック」があること、14 章に「12 章」の項目があることを確かめる。CLI: tmp_path に誤った日付の meta.toml を書いて main([...]) が 1 を返し、err に 'EMSGM106E' が出ること。TEMPLATE を --meta examples/meta_example.toml --no-metafile-conversion で変換すると 1、--images に 31_1_01.png を置いたフォルダを渡すと 0 になること。tests/test_colab.py: result_boxes に jstage の枠が出ること、res.dtd_valid=False にすると DTD の枠が出ること。tests/test_notebook.py: 手順 8 のセルを、jstage_issues のある res で exec すると一度止まり、もう一度押すとダウンロードすること（既存の test_step8_stops_once_when_images_are_missing は文面を変えないので通る）。既存のテストの修正: tests/test_pdfmatch.py の 274 行目と 278 行目の main(...) == 0 は --meta なしなので EMSGM230E で 1 になる。examples/meta_example.toml を --meta に足す（tests/test_floats.py の 134 行目は、もとから 1 を期待しているのでそのまま）。

点検で足したテスト: - ルート2 ですべて直せた PDFCHECK の res: actions(res) が []、result_boxes(res) == ''、レポートの冒頭に「出版版 PDF に合わせて docx を直してから変換しました」、14 章に「Word で開き、変更履歴を確認する」が残っていることを確かめる。
- 手動モードで読めない回答を渡した res では、result_boxes に「貼り付けた回答を読み込めませんでした」が出ること。API モードで、偽のクライアントがエラーを返した res では「AI による補完ができませんでした」が出ること。
- res.fidelity.ok を False にして render すると、冒頭に「**注意: 文字の不変性チェックが不合格です。**」が今と同じ文で出て、needs_action が True になること。
- test_cli_images_option: 1 回目は 1 を返し、標準エラーに「--images で指定するか」があること。2 回目は 0 を返すこと。
- test_notebook: 手順 8 のセルを jstage_issues のある res で実行すると一度止まり、もう一度押すとダウンロードすること。画像不足のときの「手順 7 で画像をアップロード」の文面は変えない。

### U3 段落内の改行（w:br）: 表のセルでは <break/> を補い、それ以外は文字のまま残してレポートで知らせる

sample_reader.docx（D5 と共用）に、改行のあるセル（普通の文字と、太字のランの中の改行の 2 通り）、本文の段落・題目・引用文献の改行を入れる。
test_pipeline に 2 つを確かめるテストを追加する: td の中に <break/> があり、その直後に \n があること、p と mixed-citation には break がないこと（DTD も合格）。
レポートの 10 章（と 14 章）に、改行のある段落の一覧が出ることも確かめる。

点検で足したテスト: ・セルの中のハイパーリンク（uri）の中に \n がある場合: break を入れず、DTD に合う。
・セルの段落の最後に改行がある場合: <break/>\n の後に、段落の間の <break/> が続いても、DTD に合う。
・ヘッダー行（th）でも、同じく <break/> が入る。
・final_check が合格し、fid.drops が変わらない。

### U4 AI 依頼文の「姓と名の区切りがない氏名」を、メッセージの文言から切り出している

tests/test_ai.py に足す。(1) sample_full.docx を手動モードで変換し、AI依頼文.txt に「- [d11] 姓と名の区切りがない氏名: 「研究次郎」」があること（d11 は模擬回答 ai_response_sample_full.json の split_name の対象）。(2) build() の BuildInfo.unsplit_names が [("d11", "研究次郎", "ja")] であること。(3) テストの中で英文の著者名の段落を 1 語にした plan を build_request に渡すと、その行が依頼文に出ず、BuildInfo.notes には残ること。

点検で足したテスト: (1)(2) は設計どおり。(3) build_request(plan, linker, (), [("d11","研究次郎","ja"), ("d12","KENKYU","en")]) の依頼文に d11 の行があり、d12 の行がない。(4) 文言を変えても依頼文が変わらないことを確かめるため、builder.person_name の notes の文言に依存しないこと（pipeline に「「」の切り出しが残っていないこと）を grep で確かめるか、(1) を回帰テストとして残す。

### U5 既定の AI モデル名が複数の場所に直書きされている

tests/test_notebook.py に、手順 4 のセル（cell_source("#@title 4.")）に `MODEL = "{DEFAULT_MODEL}"` と選択肢の DEFAULT_MODEL があること、API_HELP に DEFAULT_MODEL があることを足す。tests/test_ai.py に `Options(out_dir=tmp_path).ai_model == ai_assist.DEFAULT_MODEL` を足し、直書きを置き換える。test_notebook_is_up_to_date で、再生成し忘れも検出される。

点検で足したテスト: test_notebook.py では、手順 4 のセルの `MODEL = "…"` と選択肢の値を、make_notebook の mk.DEFAULT_MODEL ではなく、パッケージから import した jasme_jats.ai_assist.DEFAULT_MODEL と比べる（ファイルから正規表現で読む部分の誤りも捕まえるため）。make_notebook.py では、正規表現が一致しなかったときに「ai_assist.py の DEFAULT_MODEL = "…" の行が見つからない」と分かるエラーを出す（.group(1) の AttributeError だけにしない）。

### U6 structure.py（1263 行）の分割

新しいテストは不要。全テストと、分割の前後で出力が同じかの比較で確かめる。任意で、将来のリファクタリングのために、fixture ごとの XML を保存して比べる回帰テスト（tests/test_golden.py と、作り直し用のスクリプト）を足すとよい。

点検で足したテスト: `python -c "import jasme_jats.structure, jasme_jats.pipeline"` に当たる import のテスト（既存のテストでも検出されるが、循環 import は最初の import で落ちるので分かりやすい）。分割の前後で、全 fixture（ALL_DOCS・模擬回答つきの FLOAT・PDFCHECK のルート1・2）の XML・AI依頼文・レポートのハッシュが同じであること（scratchpad/rvlm/fixdiff.py と同じ形）。

### U7 PDF の柱（ヘッダー）・ページ番号が本文の違いとして報告され、ルート2 で docx に挿入される

tests/test_pdfmatch.py に足す。既存の test_word_footnote_numbers_follow_pdf と同じく pdfmatch.extract_pages を差し替え、PUBLISHED の文字から、d12 の途中でページが変わる PDF の文字を作る。(a) 短い柱「試験四郎」→ d12 に違いがなく、plan_fixes にも挿入がない。(b) 2 ページの記事で 13 文字の柱 → 同じ。(c) 「－ 1 －」のページ番号 → 同じ。(d) 柱の隣の本当の修正 → 違いが「基→もと」だけ。(e) ページの端の行がまるごと違う → fixable=False で、docx は直さない。(f) route="pdf" で変換すると、XML に柱の文字がなく、res.pdf_check.ignored_lines に柱がある。既存の照合のテストは変わらずに通ることを試作で確かめた。

点検で足したテスト: 設計の (a)〜(f) に加える。
(g) ページの最初の行にまるごと入った校正の一文。diffs には出ないが、ignored_lines に ("d12", "校正で足した一文である。") があり、レポート 13 章に載る。
(h) (e) の場合に、ルート2 のレポート 13.2 の「直さなかった理由」が新しい文言になる。
(i) 同じ柱が複数のページで段落の途中にあっても、ignored_lines に重複がない。窓の外の柱（段落の切れ目にある柱）は載らない。

### U8 文字スタイル・段落スタイル・既定の書式の w:vanish（隠し文字）も、Word と同じく隠す

make_fixtures.Builder に styles_extra（styles.xml に足すスタイル。今の footnotes_extra と同じ仕組み）を足す。
sample_reader.docx に次の 6 つを入れる: 文字スタイルの vanish、派生の文字スタイル、段落スタイルの vanish、文字スタイルの vanish を直接の w:val="0" で打ち消したもの、段落スタイルと文字スタイルの両方（トグルで表示）、直接の vanish。
test_reader に 2 つを確かめるテストを追加する: 隠した文字が出力されずレポートの hidden_text に載ること、表示される 2 つ（val=0 とトグル）が出力されること。
トグルの規則（試作の u8_repro.py と u8_toggle.py の 7 つ）は、ooxml.HiddenRule の単体テストにする。
test_pdfmatch では、paragraph_units に規則を渡したときの文字列が読み取りと一致することを確かめる。

点検で足したテスト: ・ooxml.HiddenRule の単体テストに、次の 4 通りを加える: 派生した文字スタイルが自分も vanish（隠す）、派生した文字スタイルが val=0（表示）、派生した段落スタイルが自分も vanish（隠す）、派生した段落スタイルが val=0（表示）。
・あわせて、試作の 7 通りと、段落スタイル（vanish）に文字スタイル（vanish）と直接の val=0 を重ねた場合（どちらも表示）も確かめる。
・pdfdocx.paragraph_units に規則を渡したときの文字列が、読み取りと一致する（test_pdfmatch）。

