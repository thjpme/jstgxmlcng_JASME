"""変換途中の XML に付ける一時的な目印（追跡用の名前空間）。

  <jx:span src="d12" seq="0">…</jx:span>
      docx の段落 d12 の文字列をこの中に出力したことを示す。1 つの段落を複数の要素に分けて出力する
      （姓と名など）場合は、docx 上の順に seq を 0, 1, 2… と振る。
  <jx:drop src="d12" seq="1" reason="…">　</jx:drop>
      構造の区切りとして出力しない空白（姓と名の間など）。検証で空白だけであることを確かめてから取り除く。
  <jx:gen kind="autonum">1.</jx:gen>
      docx の文字ではなく Word が自動生成して表示する文字（自動番号・脚注番号）。
  jx:implicit="1"（MathML の mo 要素）
      数式の括弧・積分記号など、docx では文字ではなく属性として持っている記号。
  <jx:ai decision="A-003">…</jx:ai>
      AI が画像から読み取って併記した数式など、docx の文字ではないと明示された追加。
      不変性チェックでは「docx にない文字」とは扱わず、レポートに別に一覧を出す。
  jx:o="3"（MathML のトークン要素）
      docx の数式中での文字の出現順。MathML では根号の指数などの順序が入れ替わるため、検証時に使う。

文字の不変性チェックはこれらの目印を使って行い、最終出力の前に目印をすべて取り除く。
目印の除去は要素のタグを外すだけなので、文字列は変わらない。
"""
JX_NS = "urn:jasme-jats:tracking"
JX = f"{{{JX_NS}}}"
SPAN = JX + "span"
GEN = JX + "gen"
IMPLICIT = JX + "implicit"
ORDER = JX + "o"
AI = JX + "ai"
