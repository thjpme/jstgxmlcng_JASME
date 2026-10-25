"""出版版 PDF との照合（docx の段落の文字と、記事の PDF の文字を段落ごとに突き合わせる）。

PDF は著者校正を経た最終版なので、XML の本文が PDF と違えば、J-STAGE には同じ記事の 2 つの版が並ぶことになる。
受け取った docx が校正後の最終版とは限らない（組版で印刷所がかっこ・句読点を全角にそろえる、校正の直しが docx に
戻されていない、など）ため、docx の段落ごとに PDF の中の対応する箇所を探して比べ、違いを次のように分ける。

  ・英数字・記号の全角・半角だけの違い（width）と、その文字のすぐ前後の空白で PDF にないもの（drops）
  ・それ以外の文字の違い（diffs。「資料」と「付録」など）
  ・PDF の中に見つからない段落（unmatched）
  ・Word が付ける番号（自動段落番号・脚注番号）の全角・半角の違い（numbers）

ルート1（docx から作る）では、照合の結果をレポートに載せるだけで、文字は変えない。
ルート2（出版版 PDF に合わせてから作る）では、この結果から、PDF に合わせて直した docx（Word の変更履歴つき）を作り
（pdfdocx.py）、それをルート1 と同じ処理で XML にする。Word が付ける番号は docx の文字ではないので、変換のときに
全角・半角を PDF に合わせる（plan.pdf_numbers）。

PDF から XML を作るのではない（構造はすべて docx のスタイルから決める）。PDF から取り出した文字には組版の都合
（両端そろえの空白、行末のハイフン、図の中の文字、数式、柱）が混じるため、空白は照合に使わず、段落ごとに PDF の中の
対応する箇所を探してから比べる。照合の手順:

  1. PDF の文字の列（pdf_stream）: 空白とページ番号を除いた列を作り、組版で入る文字・図や表の中の文字には印を付ける（下）
  2. まとめての照合（_joint）: docx の全段落（表のセル・図の中の文字も含む）を docx の順につないだ列と PDF の列を、どちらにも
     1 回だけ出る文字の並び（アンカー）の最長増加列と、その間の difflib で単調に（順序を保って）対応させ、段落ごとの「塊」
     （PDF の中で続いて一致した部分）にする。PDF の中で段落が表・図の中の文字・別の段落（2 段組みの読み順のずれ）に分断され
     ても、分断された部分（段落の後ろ・前・途中）を段落の文字として探す（隣の塊のすぐ隣、次〈前〉の段落のすぐ前〈後ろ〉、
     アンカーの順。どれもない段落は、docx で前後の段落の PDF の位置の間で、段落と同じ文字列を探す）。段落の窓（段落を照合する
     PDF の文字の位置のリスト）は、段落の塊のある行と、そのすぐ前後の照合に使わない行で作り、ほかの段落の塊の文字は入れない
     （0.20.0 までの「段落の長さ + 60 文字ほど」の窓では、分断された段落の後ろが窓の外に出て、窓の中のほかの文字と並べられ、
     ルート2 で docx の本文を消したり置き換えたりしていた）
  3. 段落ごとの照合（_align）: 段落の文字と窓を difflib で照合する（全角・半角、大文字・小文字、ハイフン・ダッシュの違いは
     無視して位置を合わせる）。一致した文字が 85% 未満の段落は「PDF に見つからない段落」とする
  4. 違いの分類（_classify・_report_regions）: 違う部分を、直せる違いと、直さない違い（TextDiff.why に理由。13 章に出す）に
     分ける。決められない違いは、docx に足さない・docx の文字を消さない側に倒す（下）

PDF には、組版で入る docx にない文字（ページ番号・誌名の行・柱・投稿受付日など）や、docx では画像・Word の表になっている
図・表の中の文字もある。段落の途中にあると、PDF にだけある文字として違いになり、ルート2 では docx に足されてしまうので、
次のように扱う（pdf_stream）。

  ・ページ番号（各ページの最初か最後の行の数字だけの行で、ページの順に番号が続いているもの。1 ページに 1 つ）は、列から除く
  ・ページの端の行（ページ番号を除いた後の、各ページの最初の 2 行と最後の 2 行）、ページの途中の数字だけの行、何ページにも
    出る行（3 ページ以上に同じ文字列で現れる 8 文字以上の行。柱の形の行）、短い行（MIN_CHARS 文字未満）は「柱の候補の行」
    とし、その行のどの文字もどの段落にも当たらなければ、その行の文字は照合に使わない
  ・ページの途中の数字だけの行（表のセルなど。前の行の続き〈前の行が数字＋ハイフン・波線で終わる、引用文献の「pp.11-」の
    改行の後の「16」〉を除く）と何ページにも出る行（ページの端の柱を含む）は、全体の照合にも段落ごとの照合にも使う列から
    除いて照合し、docx の文字がその行の文字とまったく同じに続くときだけ行全体で一致させる（PdfStream.line_only。表の数字が
    docx の数字と偶然 1 文字だけ一致して、その行の文字が docx に入らないように。本文の段落の最後の行がたまたま 3 ページの
    端に出ても、段落に行全体が当たれば照合に使う）
  ・投稿受付日などの文字（RE_RECEIVED）は、ページのどこにあっても、どの段落にも当たらなければ照合に使わない（文字ごと）
  ・文字として取り出せない数式の位置（pdfium は、数式の字形を全角の空白を含む空白の並びにする）に印を付ける
    （PdfStream.formula）

照合に使わなかった文字のうち、段落の違いの範囲の中にあったものを記録する（ignored_lines。レポートの 13 章）。
直さない違い（TextDiff.why）にするもの（足さない・消さない側に倒す）:

  ・PDF の側に照合に使わない文字しかない位置の docx の文字（HEAD_WHY）。段落の最後（最初）の docx の文字で、同じ行に PDF の
    文字がなく、すぐ後ろ（前）の行が照合に使わない行のとき（出版版で直された、別の行の年・ページ・見出しの番号など）も同じ。
    照合に使わない文字を除いた残りが、どの段落の文字とも一致しない行の文字（docx にない図・表の中の文字など）だけのときも
    同じで、その文字で docx を直さず、docx に足さない
  ・PDF にだけある 20 文字以上の文字（図の中の文字などの可能性が高い）で、段落の文字のある行にかかるものと、PDF の側が docx の
    側より 20 文字以上長い置き換え（LONG_WHY）。段落の文字のある行にかからない 20 文字以上の文字は、照合に使わなかった文字にする
  ・段落の最初・最後の、どこまでが段落の文字か決められない PDF の文字（EDGE_WHY。同じ行に空白をはさんでつながった図の中の
    文字、段落の最後の文の終わりの後ろに空白をはさまずにつながった、文の終わりで終わらない文字〈「…分析した。図３」〉、次の行に
    続く文、行の中の 1〜2 文字だけの偶然の一致の外側の文字など）。文の終わりで終わらない docx の段落の最後に足す文字が、すぐ
    後ろの、どの段落にも当たらない行にだけある（「。」だけの行、英文の最後の 1 語だけのページの最後の行など）ときも同じ。段落の
    最初（最後）の docx の文字で、同じ行に PDF の文字がなく、すぐ前（後ろ）の行が、どの段落とも一致しない行のときも同じ
    （消さない）
  ・段落の最初・最後の docx の文字が PDF の中に見つからず、校正で消されたのか、PDF の別の位置にあるのか決められないもの
    （UNSURE_WHY。消さない）: PDF のその位置にどの段落とも一致しない文字が続くとき、docx ですぐ後ろ（前）の本文の段落の塊の
    すぐ前（後ろ）に、その文字と 3 分の 1 以上並ぶ、どの段落にも当たらない文字が続くとき（表・図の後ろに出て、校正で大きく
    直された段落の最後の行かもしれない。_Joint.stray_edge）、段落の最後の文字で、すぐ後ろの段落の塊のすぐ後ろに、文の終わりで
    終わる、どの段落にも当たらない行があるとき（2 段組みの読み順のずれ。_Joint.tail_beyond）、窓のすぐ外の 3 行までに、どの
    段落の照合にも使われなかった行があり、その文字の半分以上と並ぶとき（隣り合う段落に同じ文があり、まとめての照合で隣の段落が
    取った、この段落の行かもしれない。_edges_near_unused_lines）
  ・段落の途中の、どの段落にも当たらない行まるごと（WHOLE_WHY。図・表のキャプションなど。足さず、照合に使わなかった文字にする。
    段落の行ほどの幅のその行の前か後ろに PDF の文字が続くときは、校正で足された長い語句の行かもしれないので、残りの文字でも
    直さない）
  ・PDF の中で、図・表の文字に挟まれた位置にある、分断された段落の部分（DISPLACED_WHY。図の中の原稿の写しかもしれない）。
    分断する表・図の中の文字とみなした位置の文字に並べた docx の文字は、全角・半角・大文字・小文字・行末のダッシュの違いも
    直さない
  ・PDF の中で段落が分断されていて、段落の本体から離れた最初・最後の部分にかかる違い（FAR_WHY。_isolate）。照合で一致した
    文字を、本文の行の流れが切れるところ（PDF の中の順が docx と逆になるところ、間にほかの段落の文字か、どの段落にも当たらない
    行〈図・表の中の文字・キャプションなど〉があるところ、段落の終わりの行〈行の幅より短く文の終わりで終わる行〉の後ろ、字下げの
    ない行から段落の 1 行目〈字下げの全角の空白で始まる行〉へ移るところ、図・表の中の行かもしれない行の前後、間の飛ばした行〈短い
    行・ページの最後の端の行・幅いっぱいの行〉の向こうがキャプションのすぐ隣のところ）で分け、いちばん長い部分と、それと本文の行
    （段落の行の幅いっぱいの行。段落がその幅で組まれていれば、段落の行の幅は、文書の本文の段落の途中の行のいちばん多い幅を
    上限にする〈_document_width〉）でつながる部分を本体とする（一致がキャプション・表のセルの行だけの部分の向こうは、つなげない）。
    離れた部分は、段落の本文の続きか、段落の文字とよく似た図の中の語句か、隣の段落の行かを PDF から決められないので、全角・
    半角・大文字・小文字・行末のダッシュの違いも直さない（足さず、消さず、置き換えない）。ただし、離れた最後の部分が、図・表
    などに押し出された段落の続きで、ほかの説明がないとき（_plain_tail）は、本体と同じに直す
  ・文字として取り出せない数式の位置にかかるもの（MATH_WHY。校正で足された数式を含む語句は、PDF の文字では数式の欠けた語句に
    なる。docx の数式の位置に、PDF では数式の空白の並びと文字が並ぶ〈校正で数式の間に足された「，」〉ときも）

段落の最初（最後）の、同じ行の PDF にだけある文字が、docx で段落のすぐ前（後ろ）にある照合しない短い段落（MIN_CHARS 文字未満。
「付記」などの見出し）の文字と同じなら、PDF で見出しが段落の行に追い込まれたものなので、違いにしない。
docx のダッシュ（en dash「–」・em dash「—」・水平線「―」・マイナス「−」・数字幅のダッシュ「‒」。DASHES）と同じ位置に、PDF では
英数字の後の行末の「-」があれば、PDF に合わせて「-」に直す（行の途中のダッシュと PDF の「-」と同じ。PDF の行末が U+FFFE など
〈何の字形か分からない〉なら docx のまま）。docx のハイフンの仲間（「‐」、Word の改行なしハイフン「‑」など。HYPHENS）と、PDF の
行末の、docx と違う「-」「‐」も同じ。
"""
from __future__ import annotations

import bisect
import difflib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .model import OBJ

FW_FIRST, FW_LAST = 0xFF01, 0xFF5E   # 全角の英数字・記号（！〜～）。半角の 0x21〜0x7E と 1 対 1 に対応する
SKIP = ""        # docx の数式・画像・脚注番号・自動番号（docx の文字ではない、または PDF と文字で比べられないもの）
SEP = ""         # 段落の区切り
SOFT = {"￾", "­", "\x02"}   # PDF の行末のハイフン（ソフトハイフン）
# docx のハイフン。PDF の行末のハイフン（PdfStream.soft。SOFT の文字と、英数字の後の行末の「-」「‐」）と同じ位置で並べば、
# 同じ文字とみなす（_align・_classify）。本当のハイフン（self-explanation）が行末に来ると、pdfium は U+FFFE にするので、
# 行末のハイフン（ハイフネーション）と区別できない。docx にハイフンがあれば、docx のまま残す（PDF の行末の文字が、docx と違う
# 「-」「‐」なら、行の途中と同じく PDF に合わせて直す。docx の「‑」〈Word の改行なしハイフン〉と PDF の「-」など）
HYPHENS = "-‐‑－"
# docx のダッシュ（en dash・em dash・水平線・マイナス・数字幅のダッシュ）。照合では HYPHENS と同じく「-」とみなし（_hyphen_key。
# 違う文字とみなすと、PDF の行末の「-」を行末のハイフネーションとして無視するので、docx のダッシュを消してしまう）、PDF の英数字の
# 後の行末の「-」「‐」（PdfStream.soft）と同じ位置で並べば、PDF に合わせて「-」に直す（行の途中のダッシュと PDF の「-」も、
# ふつうの違いとして「-」に直している。修正計画の決定事項 20・23）。PDF の行末が U+FFFE など（何の字形か分からない）なら、
# docx のまま（違いにしない）
DASHES = "–—―−‒"
MIN_CHARS = 4         # これより短い段落は照合しない（短すぎて PDF の中の位置を決められない）
MIN_COVERAGE = 0.85    # 段落の文字のうち PDF と一致した割合がこれ以上なら「照合できた」とする
# ページ番号の行（数字だけ、かっこ付きの「（25）」、ダッシュで挟んだ「－ 1 －」「- 1 -」）。ページの最初か最後の行にあるときだけ
# ページ番号として除く（ページの途中の数字だけの行は、引用文献の「pp.11-」の後の「16」や表のセルのことがある。pdf_stream）
RE_PAGE_NO = re.compile(r"^[\s　]*(?:[(（]?[0-9０-９]{1,4}[)）]?|[-－‐−–—―][\s　]*[0-9０-９]{1,4}[\s　]*[-－‐−–—―])[\s　]*$")
# 数字だけの行を、前の行の続き（引用文献の「pp.11-」「pp.11～」の改行の後の「16」）とみなす、前の行の終わり（数字のすぐ後ろの
# ハイフン・波線）。続きの行は、ページの途中でも普通の行と同じに照合する（表のセルの数字とは扱いを分ける）。本文の行が「，」
# 「、」で終わった直後の数字だけの行（ページの区切りをまたぐものも）や、表の「－」（該当なし）のセルの次の数字のセルは、表のセルや
# 図の目盛りのことがあるので続きとみなさない（普通の行として照合すると、近くで docx の数字が出版版で直されているとき、セルの
# 数字が docx の数字と偶然 1 文字だけ一致して、セルの残りの数字が docx に入る）。年（「第29号，」の後の「2018」）なども、
# 同じ文字なら行全体で一致させ（_whole_lines）、直されていれば直さずに 13 章に出す（HEAD_WHY。段落の途中でも、段落の最後の
# 行でも。_classify）
RE_CONTINUED = re.compile(r"[0-9０-９][-－‐−–—―~～〜]$")
RE_BARE_NUMBER = re.compile(r"^[\s　]*[0-9０-９]{1,4}[\s　]*$")     # かっこ・ダッシュの付かない数字だけの行
RE_ALNUM = re.compile(r"[0-9A-Za-z]")
RE_INDENT = re.compile("\u3000+ ?")      # 行の最初の字下げ（全角の空白の並びと、その後ろの半角の空白 1 つ）
# 投稿受付・採用決定などの日付。本誌（全国数学教育学会誌『数学教育学研究』）の出版版 PDF では 1 ページ目に組版で入り、docx には
# 普通ない。本文の行の後ろにつながったり、ページの途中で 2 行にわたったりする。形は「2025年８月31日投稿受付，2025年11月24日
# 採用決定」「2025年２月27日投稿受付，2025年７月30日再投稿受付，」（改行）「2025年10月10日採用決定」（数字は全角・半角）と、
# 古い号のかっこ付きの「（2025.11.30受理）」（日付は例）。かっこのない「受付」「受理」は、本文の日付（「…日受付分」など）にも
# 当たるので、かっこ付きの形でだけ認める
_DIGIT = "[0-9０-９]"
_DATE_JA = rf"{_DIGIT}{{4}}\s*年\s*{_DIGIT}{{1,2}}\s*月\s*{_DIGIT}{{1,2}}\s*日"
_DATE_DOT = rf"{_DIGIT}{{4}}\s*[.．]\s*{_DIGIT}{{1,2}}\s*[.．]\s*{_DIGIT}{{1,2}}"
_RECEIVED = rf"{_DATE_JA}\s*(?:再投稿受付|投稿受付|採用決定)"                               # 本誌の 1 ページ目の形
_RECEIVED_OLD = rf"(?:{_DATE_JA}|{_DATE_DOT})\s*(?:再投稿受付|投稿受付|採用決定|受付|受理)"   # かっこの中の形
_RECEIVED_SEP = r"\s*[，,、]?\s*"          # 日付と日付の間（読点と、空白・改行）
# 日付の並びの最後の区切り。2 行の受付日の両方が別々の本文の行につながると（「本文…2025年８月31日投稿受付，」「本文…2025年11月
# 24日採用決定」）、1 つ目の並びが「，」で終わる。日付のすぐ後ろの 1 文字だけ（その後ろの本文の読点を受付日に含めないように）
_RECEIVED_END = r"[，,、]?"
RE_RECEIVED = re.compile(rf"{_RECEIVED}(?:{_RECEIVED_SEP}{_RECEIVED})*{_RECEIVED_END}"
                         rf"|[（(]\s*{_RECEIVED_OLD}(?:{_RECEIVED_SEP}{_RECEIVED_OLD})*\s*[）)]")
# ルート2 で直さない理由（PDF の側に、照合に使わなかった文字〈柱・投稿受付日など。どの段落とも一致しない行の文字を含む〉しか
# ない位置の docx の文字）
HEAD_WHY = ("PDF のこの位置には、照合に使わなかった文字（誌名の行・柱・投稿受付日・表や図の中の文字など。13 章の最後の一覧）"
            "しかなく、どう直すか決められない。PDF のその位置の本文と見比べ、docx が違っていれば手で直してから変換し直す")
# ルート2 で直さない理由（段落の途中の、PDF にだけある 20 文字以上の文字で、その段落の文字のある行にかかるもの。図や表の中の
# 文字なら足してはいけないが、校正で足された本文かもしれない）
LONG_WHY = ("PDF にだけある長い文字（20 文字以上）で、図や表の中の文字か、校正で足された本文かを決められない。PDF のその位置の"
            "本文と見比べ、docx に本文が足りなければ手で直してから変換し直す")
# ルート2 で直さない理由（段落の最初・最後の、どこまでが段落の文字か決められない PDF の文字。段落の最初〈最後〉の docx の文字で、
# 同じ行に PDF の文字がなく、すぐ前〈後ろ〉の行がどの段落とも一致しない行のときも）
EDGE_WHY = ("PDF のこの段落の最初（最後）の、docx と違う文字が、どこまでこの段落の文字か決められない（すぐ前〈後ろ〉の、"
            "どの段落とも一致しない行〈13 章の最後の一覧〉に続いているか、同じ行に空白をはさんで並んだ図や表の中の文字か、図や表の"
            "中の文字の行と 1〜2 文字だけ偶然一致したかもしれない）。PDF と見比べ、違っていれば手で直してから変換し直す")
# ルート2 で直さない理由（段落の最初・最後の docx の文字が PDF のどこにも見つからず、PDF のその位置にどの段落とも一致しない文字が
# 続くもの。校正で消されたのか、PDF の中の別の位置〈表の後ろなど〉にあるのか決められない）
UNSURE_WHY = ("PDF では、この段落のこの部分の位置にどの段落とも一致しない文字（図や表の中の文字など。13 章の最後の一覧）が"
              "続き、docx のこの文字が校正で消されたのか、PDF の別の位置にあるのか決められない。PDF と見比べ、違っていれば"
              "手で直してから変換し直す")
# ルート2 で直さない理由（段落の途中の違いの PDF の側に、どの段落にも当たらない行がまるごとある。段落の途中の本文の行は両端そろえで
# 行の幅いっぱいになり、校正で足された語句は前後の行の組み直しになる〈行の途中から始まる〉ので、まるごと PDF にだけある行は
# 図・表の中の文字〈キャプション・軸の名前など〉と考えられる。足さず、照合に使わなかった文字として 13 章の最後の一覧にも出す）
WHOLE_WHY = ("PDF の段落の途中に、どの段落とも一致しない行がまるごとあり、図や表の中の文字か、校正で足された語句かを決められない"
             "（足していない）。PDF のその位置の本文と見比べ、docx に語句が足りなければ手で直してから変換し直す")
# ルート2 で直さない理由（PDF の中で分断された段落の部分で、前と後ろの両方が図・表の文字に挟まれたもの。図の中の原稿の写しと
# 並べたものかもしれない。分断する表・図の中の文字とみなした位置〈floaty〉の文字と並べた docx の文字も）
DISPLACED_WHY = ("PDF の中でこの段落が分断されていて、この部分は図や表の中の文字に挟まれた位置か、図や表のキャプションのすぐ隣に"
                 "ある（図の中の原稿の写しか、段落の文字とよく似た図の中の語句か、隣の段落の行かもしれない）ので、違いを直さない。"
                 "PDF のその位置の本文と見比べ、違っていれば手で直してから変換し直す")
# ルート2 で直さない理由（PDF の中で段落が分断されていて、段落の本体〈一致した文字のいちばん長い部分と、それと本文の行で
# つながる部分〉から、本文の行の流れが切れるところ〈ほかの段落・どの段落にも当たらない行《図・表の中の文字・キャプションなど》を
# はさむ、段落の終わりの行《行の幅より短く文の終わりで終わる行》の後ろ、字下げの行への移り、図の中の行かもしれない行の前後〉で
# 離れた最初・最後の部分の違い。段落の本文の続きか、段落の文字とよく似た図の中の語句かを決められない。PDF の側に文字のない違い
# 〈docx の文字がどこにも並ばない〉は、校正で消されたのか、PDF の別の位置で書き換えられているのかを決められない。_isolate）
FAR_WHY = ("PDF の中でこの段落が分断されていて、この部分（段落の最初・最後の部分）は、本文の行の並び（図・表・キャプション・ほかの"
           "段落をはさむ、段落の終わりの短い行の後ろ、字下げの行への移りなど）から見て段落の本体と続いておらず、段落の本文の続きか、"
           "図や表の中の文字かを決められないので、違いを直さない（PDF の欄が空なら、docx のこの文字が校正で消されたのか、PDF の"
           "別の位置〈図・表・ほかの段落の後ろなど〉で書き換えられているのかを決められない）。この表のとおりに置き換えず、PDF の"
           "その位置の本文と見比べ、違っていれば手で直してから変換し直す")
# ルート2 で直さない理由（違う部分の PDF の文字の間や両隣に、文字として取り出せない数式の位置〈PdfStream.formula〉がある。校正で
# 足された数式を含む語句は、PDF の文字では数式の欠けた語句になる）
MATH_WHY = ("PDF のこの位置には、数式など文字として読み取れない部分があるようで（PDF の文字では空白の並び。〓 の位置）、"
            "足す（置き換える）文字を決められない。PDF と見比べ、docx に数式や文字が足りなければ手で直してから変換し直す")
# 直せない違い（why のあるもの）の PDF の文字と、照合に使わなかった文字の一覧で、PDF の行の変わり目を示す記号（本文の「／」と
# 見分けられるように、本文に出ない記号にする）
LINE_MARK = "⏎"
# 直せない違い（MATH_WHY）の PDF の文字で、文字として取り出せない数式の位置を示す記号（レポートで docx の数式を示す記号と同じ）
FORMULA_MARK = "〓"


def fold(c: str) -> str:
    """全角の英数字・記号を半角にする（それ以外の文字はそのまま。文字数は変わらない）。"""
    o = ord(c)
    return chr(o - 0xFEE0) if FW_FIRST <= o <= FW_LAST else c


def key(c: str) -> str:
    """照合（位置合わせ）に使う文字: 全角・半角と大文字・小文字の違いを無視する（違いの判定は元の文字で行う）。"""
    return fold(c).lower()


def is_width_pair(a: str, b: str) -> bool:
    """a と b が、英数字・記号の全角と半角の違いだけか。"""
    return len(a) == len(b) == 1 and a != b and fold(a) == fold(b) and 0x21 <= ord(fold(a)) <= 0x7E


@dataclass
class TextDiff:
    src: str
    docx: str        # docx の文字（違う部分）
    pdf: str         # PDF の文字（違う部分。単語の間の空白は戻してある。直せない理由 why のあるものは、行の変わり目に LINE_MARK）
    context: str     # docx の前後の文字
    start: int = 0   # docx の段落（plain）の中の範囲 [start, end)。PDF にだけある文字なら start == end（その位置に足す）
    end: int = 0
    fixable: bool = True   # ルート2 で docx を直せるか（数式・Word が付ける番号・リンクの文字にかかるものは直さない）
    why: str = ""    # 直せない理由（ルート2 のレポートに出す）。空なら pdfdocx.plan_fixes の決まった文言


@dataclass
class PdfCheck:
    ok: bool = True                 # PDF の文字を読めたか
    message: str = ""               # 読めなかった理由など
    checked: int = 0                # 照合した段落の数
    unmatched: list = field(default_factory=list)   # PDF の中に見つからなかった段落の src
    width: dict = field(default_factory=dict)       # src -> {plain 上の位置: PDF の文字}
    drops: dict = field(default_factory=dict)       # src -> {plain 上の位置（落とす空白）}
    diffs: list = field(default_factory=list)       # TextDiff
    numbers: dict = field(default_factory=dict)     # Word が付ける番号: (種類, 段落 ID または脚注 ID) -> {番号の中の位置: PDF の文字}
    original: dict = field(default_factory=dict)    # Word が付ける番号の元の文字列: (種類, ID) -> 文字列
    # 種類: auto（段落の自動番号。ID は段落）/ fnref（本文の脚注番号）/ fnlist（注の一覧の脚注番号。ID は Word の脚注 ID）
    # 組版で入る文字（誌名の行・柱・投稿受付日など）や図・表の中の文字とみなして照合に使わなかった PDF の文字:
    # [(段落 ID, 行または投稿受付日の文字列)]。
    # 段落の違いの範囲（段落の途中の、PDF にだけある文字と、docx の文字と違う PDF の文字）から実際に除いたものと、段落の最初・
    # 最後の docx の文字を直さなかった（HEAD_WHY）ときに、段落のすぐ隣に続いていた照合に使わない行（_ignored_rows）だけ（重複なし）。
    # それ以外の段落の切れ目（段落の前後）や数式などの位置にあるものは、もともと違いにならないので載せない
    ignored_lines: list = field(default_factory=list)

    @property
    def number_edits(self) -> dict:
        """Word が付ける番号を PDF に合わせたもの: (種類, ID) -> 出力する文字列（ルート2 で使う）。"""
        return {k: "".join(m.get(i, c) for i, c in enumerate(self.original[k])) for k, m in self.numbers.items()}

    @property
    def width_count(self) -> int:
        return sum(len(v) for v in self.width.values())

    @property
    def drop_count(self) -> int:
        return sum(len(v) for v in self.drops.values())


# ---------------------------------------------------------------------------- PDF の文字
def extract_pages(pdf_path) -> list:
    """PDF の各ページの文字（pypdfium2）。"""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()


@dataclass
class PdfStream:
    """PDF の本文の文字の列（空白を除いたもの）と、各文字の前の空白・改行、各文字の行。

    ページ番号（各ページの最初か最後の行の数字だけの行で、ページの順に番号が続いているもの。1 ページに 1 つ）は、
    列に入れない（pdf_stream）。
    柱の候補の行（head）と投稿受付日などの文字（date）は列に入れたまま印を付け、どの段落にも当たらなければ照合に使わない
    （ignored）。ページの途中の数字だけの行（前の行の続きを除く）と何ページにも出る行（ページの端の柱を含む。line_only。
    0.19.0 では列から除いていた行）は、全体の照合にも段落ごとの照合にも使う列から除き、行全体でしか docx の文字と
    一致させない（compare・_align）。
    """
    chars: list = field(default_factory=list)
    space_before: list = field(default_factory=list)    # 前に空白（改行以外）がある
    newline_before: list = field(default_factory=list)  # 前に改行がある
    soft: list = field(default_factory=list)            # 行末のハイフン（照合で無視してよい文字）
    line: list = field(default_factory=list)            # 各文字の行の番号（lines の位置。列に入れた行だけを数える）
    lines: list = field(default_factory=list)           # 行の文字列（目に見えない文字と前後の空白を除いたもの。レポートに出す）
    line_indent: list = field(default_factory=list)     # 行ごとの（lines と同じ位置）、行の最初が全角の空白（段落の
    #                                                     1 行目の字下げ）か（_flow_breaks）
    edge: list = field(default_factory=list)            # 各文字の行が、ページの端の行（ページ番号を除いた後の、空でない
    #                                                     最初の 2 行と最後の 2 行）か
    top: list = field(default_factory=list)             # 各文字の行が、ページの最初の端の行（ページ番号を除いた後の、空でない
    #                                                     最初の 2 行。柱が出る位置）か
    head: list = field(default_factory=list)            # 各文字の行が、柱の候補の行（ページの端の行、ページの途中の数字だけの
    #                                                     行、3 ページ以上に同じ文字列で現れる 8 文字以上の行、短い行）か
    line_only: list = field(default_factory=list)       # 各文字の行が、行全体でしか docx の文字と一致させない行（ページの途中の
    #                                                     数字だけの行〈前の行の続きを除く〉、何ページにも出る行）か
    date: list = field(default_factory=list)            # 各文字が投稿受付日などの文字（RE_RECEIVED）なら dates の位置、違えば -1
    dates: list = field(default_factory=list)           # 投稿受付日などの文字列（空白・改行を除いたもの）
    formula: list = field(default_factory=list)         # 各文字の前の空白の並びが、文字として取り出せない数式の位置に見えるか
    #                                                     （_formula_gap。0: 見えない、1: 同じ行の中か前の行の最後、2: この行の最初）
    wide_space: list = field(default_factory=list)      # 各文字の前に、同じ行の中の全角の空白があるか（追い込みの見出しと本文の
    #                                                     間など。両端そろえの空白は半角の空白。_contests）

    @property
    def keys(self) -> str:
        return "".join(key(c) for c in self.chars)

    def line_range(self, ln: int) -> range:
        """行 ln の文字の、列の位置の範囲（line は列の順に増える）。"""
        return range(bisect.bisect_left(self.line, ln), bisect.bisect_right(self.line, ln))

    def ignored(self, k: int, owner, owned_lines) -> str:
        """k 番目の文字を、組版で入る文字（誌名の行・柱・投稿受付日など）や図・表の中の文字とみなして照合に使わないなら、
        その行（投稿受付日などの文字なら、その日付）の文字列。照合に使うなら空文字。

        owner: どれかの段落に当たった文字の位置（compare）。owned_lines: どれかの段落に当たった文字のある行の番号。
        投稿受付日などの文字は文字ごとに、柱の候補の行は行ごとに、どの段落にも当たらないものを照合に使わない
        （docx に同じ文字の段落があれば、その段落に当たるので普通に照合される）。
        """
        if k in owner:
            return ""
        if self.date[k] >= 0:
            return self.dates[self.date[k]]
        if self.head[k] and self.line[k] not in owned_lines:
            return self.lines[self.line[k]]
        return ""


def _visible(line: str) -> bool:
    """行に、列に入る文字（空白・制御文字以外）があるか。"""
    return any(not c.isspace() and (unicodedata.category(c) not in ("Cc", "Cf", "Cn") or c in SOFT) for c in line)


def _shown(line: str) -> str:
    """行の目に見える文字（制御文字・行末のハイフンの印〈U+FFFE など〉を除き、前後の空白を除いたもの。レポートに出す）。"""
    return "".join(c for c in line.replace("\t", " ") if unicodedata.category(c) not in ("Cc", "Cf", "Cn")).strip()


def _continues(prev: str, line: str) -> bool:
    """数字だけの行 line が、前の行 prev（目に見える文字）の続き（引用文献の「pp.11-」の改行の後の「16」）か。

    かっこ・ダッシュの付かない数字だけの行で、前の行が数字＋ハイフン・波線（RE_CONTINUED）で終わるもの。
    """
    return bool(RE_CONTINUED.search(prev) and RE_BARE_NUMBER.match(line))


def _page_numbers(page_lines) -> list:
    """各ページのページ番号の行の位置（なければ None）。

    候補は、ページの空でない最初の行と最後の行のうち、数字だけの行（RE_PAGE_NO）。その数とページの順番（何ページ目か）の
    差が、ほかのページの候補と同じもの（ページの順に番号が続いているもの）を選ぶ（ページの最後か最初にある、引用文献の
    「pp.11-」の後の「16」や表の数字を、ページ番号と取り違えないため。本誌の PDF では、すべてのページの最初の行の「（25）」）。
    番号が続いている候補がどのページにもない（1 ページだけの PDF、ページ番号のない PDF など）ときは、最初の行、それがなければ
    最後の行の候補を選ぶ。ただし、前の行の続きの数字（「pp.11-」の改行の後の「16」。_continues）は選ばない（ページ番号として
    除くと、ルート2 で docx のその数字を消してしまう）。
    """
    cands = []           # ページごとの [(行の位置, 番号とページの順番の差, 前の行の続きか)]
    last = ""            # 前のページの、最後の空でない行
    for n, ls in enumerate(page_lines):
        shown = [i for i, x in enumerate(ls) if _visible(x)]
        c = []
        for i in dict.fromkeys(shown[:1] + shown[-1:]):
            if RE_PAGE_NO.match(ls[i]):
                k = shown.index(i)
                before = _shown(ls[shown[k - 1]]) if k else last
                c.append((i, int(re.sub(r"[^0-9]", "", unicodedata.normalize("NFKC", ls[i]))) - n, _continues(before, ls[i])))
        cands.append(c)
        if shown:
            last = _shown(ls[shown[-1]])
    votes = Counter(d for c in cands for d in {d for _, d, _ in c})
    if not any(v >= 2 for v in votes.values()):
        return [next((i for i, _, cont in c if not cont), None) for c in cands]
    out = []
    for c in cands:
        good = [(votes[d], -k, i) for k, (i, d, _) in enumerate(c) if votes[d] >= 2]
        out.append(max(good)[2] if good else None)
    return out


def _visible_count(line: str) -> int:
    """行の目に見える文字の数（空白・制御文字・行末のハイフンの印を除く）。"""
    return sum(1 for c in line if not c.isspace() and unicodedata.category(c) not in ("Cc", "Cf", "Cn"))


def pdf_stream(pages) -> PdfStream:
    """PDF の各ページの文字（extract_pages）から、照合に使う文字の列を作る（PdfStream）。"""
    page_lines = [re.split(r"\r\n|\r|\n", p) for p in pages]
    # 柱: 3 ページ以上に同じ文字列で現れる 8 文字以上の行
    cnt = Counter(s for ls in page_lines for s in {x.strip() for x in ls} if len(s) >= 8)
    heads = {s for s, n in cnt.items() if n >= 3}
    kept = []          # 列に入れる行: (行の文字列, ページの端の行か, 柱の候補の行か, 行全体でしか一致させない行か,
    #                    ページの最初の端の行か)
    prev = ""          # 直前に列に入れた、空でない行の目に見える文字（数字だけの行が前の行の続きかを見る）
    for ls, page_no in zip(page_lines, _page_numbers(page_lines)):
        shown = [i for i, x in enumerate(ls) if _visible(x)]
        rest = [i for i in shown if i != page_no]
        edge = set(rest[:2] + rest[-2:])
        before = prev  # 前のページの最後の行（ページの最初の端の行は、その前の柱などを飛ばして、この行の続きかも見る）
        for i, ln in enumerate(ls):
            if i == page_no:
                continue           # ページ番号
            # ページの途中の数字だけの行・何ページにも出る行は、引用文献や表の文字のことがあるので、除かずに柱の候補にする。
            # ページの端の柱（何ページにも出る行）も、本文の段落の最後の行（「ことが明らかになった。」など）がたまたま 3 ページの
            # 端に出たものかもしれないので、除かずに柱の候補にする（段落に行全体が当たれば照合に使う）。
            # 短い行（図の中の点の名前・軸のラベル、表の短いセルなど）も柱の候補にする（本文の短い行は段落の最後にしかなく、
            # 段落に当たる）
            digits = bool(RE_PAGE_NO.match(ln))
            repeated = ln.strip() in heads
            head = i in edge or digits or repeated or 0 < _visible_count(ln) < MIN_CHARS
            # 前の行の続きの数字だけの行（「pp.11-」の改行の後の「16」）。ページの最初の端の行なら、前のページの最後の行の
            # 続きかも見る（ページの最初の柱〈8 文字未満の著者名・2 ページの記事の柱〉の次の行が「16」のとき）
            cont = digits and (_continues(prev, ln) or (i in rest[:2] and _continues(before, ln)))
            # 前の行の続きでない数字だけの行と、何ページにも出る行（0.19.0 では列から除いていた行）は、行全体でしか一致させない
            kept.append((ln, i in edge, head, (digits and not cont) or repeated, i in rest[:2]))
            # ページの端の柱は、数字だけの行が前の行の続きかを見るときには飛ばす（0.19.0 では列から除いていた行）
            if _visible(ln) and not (i in edge and repeated):
                prev = _shown(ln)
    text = "\n".join(ln for ln, *_ in kept)
    line_of = [n for n, (ln, *_) in enumerate(kept) for _ in range(len(ln) + 1)]     # text の各文字の行（+1 は改行）
    st = PdfStream(lines=[_shown(ln) for ln, *_ in kept],
                   line_indent=[ln.lstrip(" \t")[:1] == "\u3000" for ln, *_ in kept])   # 空白を除く前の行で見る
    date_of = [-1] * len(text)
    for m in RE_RECEIVED.finditer(text):
        st.dates.append(re.sub(r"\s+", "", m.group()))
        date_of[m.start():m.end()] = [len(st.dates) - 1] * (m.end() - m.start())
    sp = nl = False
    gap = ""           # 直前の文字からの空白の並び（改行は "\n"）
    for k, c in enumerate(text):
        if c == "\n":
            nl = True
            gap += c
            continue
        if c.isspace():
            sp = True
            gap += c
            continue
        if unicodedata.category(c) in ("Cc", "Cf", "Cn") and c not in SOFT:
            continue             # 制御文字など（PDF の目に見えない文字）
        soft = c in SOFT
        if c in "-‐" and k + 1 < len(text) and text[k + 1] == "\n" and st.chars and RE_ALNUM.match(st.chars[-1]):
            soft = True          # 英単語の途中の改行のハイフン
        st.chars.append(c)
        st.space_before.append(sp)
        st.newline_before.append(nl)
        st.soft.append(soft)
        n = line_of[k]
        st.line.append(n)
        st.edge.append(kept[n][1])
        st.top.append(kept[n][4])
        st.head.append(kept[n][2])
        st.line_only.append(kept[n][3])
        st.date.append(date_of[k])
        st.formula.append(_formula_gap(gap))
        st.wide_space.append("\n" not in gap and "　" in gap)
        sp = nl = False
        gap = ""
    return st


def _formula_gap(gap: str) -> int:
    """PDF の文字の前の空白の並び gap（改行は "\n"）が、文字として取り出せない数式の位置に見えるか。

    pdfium は、文字として取り出せない数式の字形（添字付きの文字など）の位置を、全角の空白を含む空白の並びにする（「（　 　，
    …，　 　とおく）」）。本文の行の中の空白は、両端そろえで句読点の後や和文と英数字の間に入る半角の空白 1 つ、図・表の
    キャプション「図１　…」・見出し・箇条の記号の後の全角の空白 1 つがふつうなので、全角の空白を含む 2 文字以上の空白の並びを
    数式の位置とみなす（全角の空白を含まない半角の空白の並び〈U+2005 など〉は、英文の単語の間や字間の調整のことがあるので
    みなさない）。行の最初の、全角の空白だけの並び（と、その後ろの半角の空白 1 つ）は字下げ（段落の 1 行目の「　」、英文要旨の
    「　　 」など）なのでみなさない。
    戻り値: 0（みなさない）、1（同じ行の中か、前の行の最後にある）、2（この行の最初にある）。
    """
    parts = gap.split("\n")
    if len(parts[0]) >= 2 and "\u3000" in parts[0]:
        return 1
    lead = parts[-1]
    if len(parts) > 1 and len(lead) >= 2 and "\u3000" in lead and not RE_INDENT.fullmatch(lead):
        return 2
    return 0


# ---------------------------------------------------------------------------- 照合
def _para_seq(p, fn_marks=None, list_marks=None):
    """段落の照合用の文字の列 [(文字, plain 上の位置)] と、Word が付ける番号の文字
    {列の位置: (種類, ID, 番号の中の位置, 番号のアトムの plain 上の位置（段落の自動番号は -1）)}。

    空白は除く。数式・画像は SKIP。Word が付ける番号（段落の自動番号、本文の脚注番号、注の一覧の脚注番号）は、
    出力する文字を列に入れ、plain 上の位置は -1 とする。fn_marks: Word の脚注 ID -> 本文・注の一覧に出力する番号。
    list_marks: 注の一覧の最初の段落 ID -> Word の脚注 ID。
    """
    fn_marks, list_marks = fn_marks or {}, list_marks or {}
    seq, gens = [], {}

    def number(kind, ident, text, apos):
        for k, c in enumerate(text):
            if not c.isspace():
                gens[len(seq)] = (kind, ident, k, apos)
                seq.append((c, -1))

    number("auto", p.src, p.autonum or "", -1)
    pos = 0
    for a in p.atoms:
        if a.kind == "text":
            for k, ch in enumerate(a.text):
                if not ch.isspace():
                    seq.append((ch, pos + k))
            pos += len(a.text)
            continue
        if a.kind == "fnref" and a.fn_kind == "footnote" and a.fn_id in fn_marks:
            number("fnref", a.fn_id, fn_marks[a.fn_id], pos)
        elif a.kind == "gen" and a.fn_kind == "mark" and p.src in list_marks and list_marks[p.src] in fn_marks:
            number("fnlist", list_marks[p.src], fn_marks[list_marks[p.src]], pos)
        elif a.kind != "gen":
            seq.append((SKIP, pos))
        pos += 1
    return seq, gens


def _locked_positions(p) -> set:
    """全角・半角を変えない位置（URL・DOI などのリンクの文字。表示とリンク先がずれないように）。"""
    out = set()
    pos = 0
    for a in p.atoms:
        n = len(a.text) if a.kind == "text" else 1
        if a.href or (a.link is not None and a.link.kind in ("uri", "ext-link", "pub-id")):
            out.update(range(pos, pos + n))
        pos += n
    return out


def target_paragraphs(plan) -> list:
    """照合する段落: 題目・本文・見出し・キャプション・注・付記・謝辞・引用文献・英文要旨（表のセル・別行数式・資料は除く）。"""
    from .linker import body_paragraphs
    out = []
    for p in list(plan.title) + list(plan.subtitle) + list(plan.title_en) + list(plan.subtitle_en):
        out.append(p)
    for p, where in body_paragraphs(plan):
        if where not in ("cell", "formula"):
            out.append(p)
    seen = set()
    return [p for p in out if not (p.src in seen or seen.add(p.src))]


def compare(plan, pages, fn_marks=None) -> PdfCheck:
    """docx の段落と PDF の文字を照合する。pages は PDF の各ページの文字（extract_pages）。

    fn_marks: Word の脚注 ID -> 出力する脚注番号（builder.word_note_marks）。Word の脚注番号も PDF と照合する。
    段落の途中にある柱・投稿受付日・図や表の中の文字など（どの段落にも当たらない、ページの端の行など）は照合に使わず、
    res.ignored_lines に記録する（ページ番号は列から除く。pdf_stream）。
    """
    res = PdfCheck()
    fn_marks = fn_marks or {}
    list_marks = {fn.paras[0].src: fn.word_id for fn in plan.fns if fn.word_note and fn.paras}
    st = pdf_stream(pages)
    if not st.chars:
        res.ok = False
        res.message = "PDF から文字を取り出せなかった（画像だけの PDF の可能性がある）"
        return res
    targets = {p.src for p in target_paragraphs(plan)}
    # 位置合わせには、照合しない段落（図の中の文字・表のセル・資料など）も docx の順で使う。PDF の文字のうち、
    # ほかの段落に当たった文字を「PDF にだけある文字」と数えないため
    allp = list(plan.paras.values())
    paras, gaps = [], []      # gaps: 段落の直前に、paras に入らなかった docx の段落（短い段落・画像だけの段落など）があるか
    shorts = [[]]             # paras の各段落の直前の、paras に入らなかった短い段落の文字（key。最後の要素は最後の段落の後ろ）
    between = False
    for p in allp:
        q, g = _para_seq(p, fn_marks, list_marks)
        if sum(1 for c, _ in q if c != SKIP) >= MIN_CHARS:
            paras.append((p, q, g))
            gaps.append(between)
            shorts.append([])
            between = False
        else:
            between = between or not p.is_blank
            t = "".join(key(c) for c, _ in q if c != SKIP)
            if t:
                shorts[-1].append(t)
    # 1. まとめての照合: 段落ごとの PDF の中の位置（窓。列の位置のリスト）を決める（_joint）
    jt = _joint(plan, paras, st, gaps)
    # 2. 段落ごとに、窓と照合する
    aligned = {}
    owner = {}                 # PDF の文字の位置 -> その文字に当たった段落
    for k, ((p, seq, gens), win) in enumerate(zip(paras, jt.windows)):
        ops = _align(seq, st, win) if win else None
        if ops is None:
            continue
        aligned[p.src] = (p, seq, gens, win, ops, jt.unsure[k])
        for tag, i1, i2, j1, j2 in ops:
            if tag == "equal":
                for x in range(j1, j2):
                    owner.setdefault(win[x], p.src)
    # どれかの段落に当たった文字のある行（柱の候補の行のうち、これに入らない行の文字は照合に使わない）
    owned_lines = {st.line[g] for g in owner}
    # どれかの段落の文字が ISLAND 文字より多く当たったか、文字の半分以上が当たった行（_classify で、どの段落の文字とも一致
    # しない行かを見るとき。段落の照合が、表のキャプションの行の 1〜2 文字を偶然一致させても、その行を段落の行とみなさない。
    # 段落の文字が 3 文字以上続いて当たった行は、残りが校正で足された文でも段落の行とみなす）
    per_line = Counter(st.line[g] for g in owner)
    size = Counter(st.line[k] for k in range(len(st.chars)) if not st.soft[k] and st.date[k] < 0)   # 受付日の文字は数えない
    dense_lines = {ln for ln, n in per_line.items() if n > ISLAND or 2 * n >= size[ln]}
    _edges_near_unused_lines([aligned[p.src] for p, _, _ in paras if p.src in aligned and p.src in targets], st, owner)
    # 3. 照合する段落の違いを分類する
    from .linker import body_paragraphs
    heads = {p.src for p, where in body_paragraphs(plan) if where == "title"} | \
        {p.src for p in [*plan.title, *plan.subtitle, *plan.title_en, *plan.subtitle_en]}     # 題目・見出し
    short_end = {}             # 段落 ID -> 段落の最後に一致した文字の行が目に見えて短いか（_classify）
    # 本文の流れでない段落（図・表のキャプション・表のセル・図形の中の段落）。_isolate で、図・表の中の行を見分けるのに使う
    nonflow = {p.src for (p, _, _), u in zip(paras, jt.unsure) if not u["flow"]}
    doc_width = _document_width(st, owner, nonflow)
    for n, (p, seq, gens) in enumerate(paras):
        for (kind, ident, k, _) in gens.values():
            res.original.setdefault((kind, ident), (p.autonum or "") if kind == "auto" else fn_marks[ident])
        if p.src not in targets:
            continue
        res.checked += 1
        if p.src not in aligned:
            res.unmatched.append(p.src)
            continue
        short_end[p.src] = _classify(*aligned[p.src], st, owner, owned_lines, res, dense_lines, (shorts[n], shorts[n + 1]),
                                     p.src in heads, nonflow, doc_width)
        _contested_edges(res, p, seq, aligned[p.src][5], st)
    # 4. docx で隣り合う 2 つの段落の間（間に docx の段落がないもの）にある、どの段落にも当たらない PDF の行（校正で足された
    # 一文かもしれない）は、照合に使わなかった文字として前の段落に記録する（13 章の最後の一覧）。前の段落の最後の行のすぐ後ろに
    # あり、段落が文の終わりで終わらず、その行が文の終わりで終わるときは、直さない違い（EDGE_WHY）にもする（_end_rows_diff）
    for k in range(len(paras) - 1):
        a, b = paras[k][0], paras[k + 1][0]
        if gaps[k + 1] or a.src not in aligned or b.src not in aligned or a.src not in targets:
            continue
        wa, wb = aligned[a.src][3], aligned[b.src][3]
        if not wa or not wb or wa[-1] >= wb[0]:
            continue
        lo, hi = wa[-1] + 1, wb[0]
        if st.line[hi - 1] - st.line[lo] > 3:
            continue                  # 4 行以上（docx にないページ・図の中の文字など）
        rows = {}
        for g in range(lo, hi):
            if not st.ignored(g, owner, owned_lines) and g not in owner and not st.soft[g]:
                rows.setdefault(st.line[g], g)
        first = next(iter(rows.values()), None)       # 最初の行の、照合に使う最初の文字の位置
        rows = [st.lines[n] for n in rows]
        # 校正で足された一文は 1〜2 行。長く続くもの（docx にないページ・図の中の文字など）は載せない
        if rows and len(rows) <= 3 and sum(len(r) for r in rows) <= 60:
            _ignore(res, a.src, rows)
            if a.src not in heads:
                # 最初の行が、段落の最後に一致した文字の行のすぐ後ろの行か（間に、ほかの文字のある行がない）
                last = max((g for g in wa if owner.get(g) == a.src), default=None)
                while first > 0 and st.line[first - 1] == st.line[first]:
                    first -= 1
                if last is not None and first > 0 and st.line[first - 1] == st.line[last]:
                    _end_rows_diff(res, a, paras[k][1], paras[k][2], aligned[a.src][5], short_end.get(a.src), rows)
    order = {p.src: n for n, (p, _, _) in enumerate(paras)}
    res.diffs.sort(key=lambda d: order.get(d.src, len(order)))       # 手順 4 で加えた違いも段落の順に（同じ段落の中の順は変えない）
    return res


def _contested_edges(res: PdfCheck, p, seq, unsure, st: PdfStream):
    """段落 p の最初（最後）が、PDF の同じ行でほかの段落の最後（最初）と接していて、間の PDF の文字がどちらの段落の文字か
    決められなかった（_contests）のに、この段落の最初（最後）に違いがない（間の文字はもう一方の段落の窓にある）とき、間の
    PDF の文字を、この段落の最初（最後）に足すかもしれない文字として、直さない違い（EDGE_WHY）に加える（どちらの段落の
    13 章にも出す）。"""
    if not unsure["contested"]:
        return
    text = p.plain()
    pos = [q for c, q in seq if q >= 0]
    if not pos:
        return
    shown = "".join(st.chars[k] for k in sorted(unsure["contested"]))
    mine = [d for d in res.diffs if d.src == p.src]
    for flag, n in (("head_contested", pos[0]), ("tail_contested", pos[-1] + 1)):
        if not unsure[flag] or any((d.start <= n) if flag == "head_contested" else (d.end >= n) for d in mine):
            continue
        ctx = (text[max(0, n - 12):n] + "［］" + text[n:n + 12]).replace(OBJ, FORMULA_MARK)
        res.diffs.append(TextDiff(p.src, "", shown, ctx, n, n, False, EDGE_WHY))


def _end_rows_diff(res: PdfCheck, p, seq, gens, unsure, short, rows):
    """compare の手順 4: 段落 p（題目・見出しでないもの）の最後に一致した文字の行のすぐ後ろから続く、どの段落にも当たらない
    行 rows（PDF の行の文字列）が、校正で段落の最後に足された文の続きかもしれないなら、直さない違い（EDGE_WHY）として
    res.diffs に加える（足さない）。

    本文の流れの段落で、段落の最後の行が目に見えて短くなく（short でない）、docx の段落が文の終わりで終わらず、rows の最後の
    行が文の終わりで終わるとき（docx の行の幅いっぱいで終わる最後の行の次の行に、校正で足された「（架空，2020）。」だけが
    出る形など）。段落の最後に、すでに直さない違いがあれば加えない。"""
    if not unsure["flow"] or not unsure["tail_free"] or short or not _ends_sentence(rows[-1]) or \
            _ends_sentence(_docx_tail(seq, gens)):
        return
    text = p.plain()
    n = max([q + 1 for c, q in seq if q >= 0] or [0])
    if any(d.src == p.src and d.why and d.start == d.end == n for d in res.diffs):
        return
    ctx = (text[max(0, n - 12):n] + "［］" + text[n:n + 12]).replace(OBJ, FORMULA_MARK)
    res.diffs.append(TextDiff(p.src, "", LINE_MARK.join(rows), ctx, n, n, False, EDGE_WHY))


DOC_WIDTH_LINES = 5   # 文書の本文の行の幅（_document_width）とみなすのに要る、その幅の段落の途中の行の数


def _document_width(st: PdfStream, owner, nonflow) -> float:
    """compare の手順 2 の後: 文書の本文の行の幅（本文の流れの段落の途中の行のうち、和文の行の、いちばん多い幅。字下げの全角の
    空白も数える）。段落がその幅で組まれているとき（_classify）、段落の行の幅（_classify の own_width。段落の行のいちばん長い行の
    幅）の上限にする（_isolate・_plain_tail）。約物の詰め・半角の文字・pdfium が 2 段の行をつないだ行で、1 行だけ幅が大きく出ると
    （本誌の出版版 PDF で 26〜47。ふつうの行は 23〜24）、幅いっぱいのふつうの行が FULL_LINE に届かず、段落の終わりの行・図の中の
    行とみなされ、本文の行とも認められないので、分断されていないふつうの段落の端が本体から離れた部分になり、本当の直しを 13 章に
    回していた。

    短い行の幅を上限にすると、段落の終わりの短い行や、表の後ろに出た段落の続きの短い行が幅いっぱいとみなされて、すぐ後ろの、
    校正で消された最後の文の写しにごく近い図の中の行が本体に入り、図の中の文字で docx の文字を置き換える（表のキャプションの
    「１」と並べた docx の「1」を残したまま隣の「2」を「13」に直す〈「113点」〉形も）。そうならないように、数えるのは段落の途中の
    行（次の行も同じ本文の段落の行で、どちらの行にもキャプション・表のセルなど〈nonflow〉の文字がないもの）だけにする: 段落の
    途中の行は両端そろえで行の幅いっぱいになるが、段落の最後の行・1 行だけの短い段落の行・表のすぐ前の短い行は、そうとは限らない。
    キャプション・セルの行は本文の行でない（キャプションの「１」がこの段落の文字と偶然一致すると、キャプションの行も、そのすぐ前の
    短い行も、次の行が同じ段落の行に見える）。英文・数式の行は、文字の数で測る幅の誤差が大きく、和文の行の幅と違うので数えない
    （英文の段落の行の幅で、和文の段落に上限をかけない）。いちばん多い幅の行が DOC_WIDTH_LINES 本に満たなければ、決められないと
    して 0（上限にしない）。"""
    widths = Counter()
    below = set()                        # 次の行の、本文の流れの段落の ID（キャプションなどの文字のある行・文字のない行なら空）
    for ln in range(len(st.lines) - 1, -1, -1):
        ks = [k for k in st.line_range(ln) if not st.soft[k] and st.date[k] < 0]
        owners = {owner.get(k) for k in ks} - {None}
        flow = set() if owners & nonflow else owners
        if flow & below and _mostly_wide("".join(st.chars[k] for k in ks)):
            widths[round(_shown_width(st, ln))] += 1
        below = flow
    width, n = widths.most_common(1)[0] if widths else (0, 0)
    return width if n >= DOC_WIDTH_LINES else 0


def _edges_near_unused_lines(aligned, st: PdfStream, owner):
    """compare の手順 2 の後: 段落の最初（最後）の docx の文字が PDF に見つからない（照合の最初〈最後〉が docx にだけある文字で、
    消すことになる）とき、窓のすぐ前（後ろ）の 3 行までに、どの段落の照合にも使われなかった行があり、その行が docx のその文字の
    半分以上と並ぶなら、その文字を消さない（段落の印 head・tail を立てる。_classify が UNSURE_WHY にする）。隣り合う段落に同じ
    文があると、まとめての照合で隣の段落がこの段落の行を取り、隣の段落の照合ではその行が使われないことがある。間の、受付日の
    文字かページの端の行の文字だけで、docx のその文字と半分も並ばない行（1 ページ目の最後の受付日の行、次のページの最初の柱など）は
    飛ばす。

    aligned: 照合する段落の (p, seq, gens, win, ops, unsure) のリスト。owner: どれかの段落に当たった PDF の文字の位置。"""
    for _, seq, _, win, ops, unsure in aligned:
        for step, op in ((1, ops[-1]), (-1, ops[0])):
            if op[0] != "delete":
                continue
            hole = [key(c) for c, _ in seq[op[1]:op[2]] if c != SKIP]
            if not hole:
                continue
            ln, seen = st.line[win[-1] if step > 0 else win[0]] + step, 0
            while 0 <= ln < len(st.lines) and seen < 3:
                ks = st.line_range(ln)
                ln += step
                if not ks:
                    continue                 # 文字のない行
                seen += 1
                if any(k in owner for k in ks):
                    break                    # どれかの段落の照合に使われた行
                if all(st.date[k] >= 0 or st.edge[k] for k in ks) and \
                        2 * _lcs_prefix(hole, [key(st.chars[k]) for k in ks])[-1] < len(hole):
                    continue                 # 受付日の文字かページの端の行の文字だけの行
                if 2 * _lcs_prefix(hole, [key(st.chars[k]) for k in ks if not st.soft[k]])[-1] >= max(2, len(hole)):
                    unsure["tail" if step > 0 else "head"] = True
                break


# ---------------------------------------------------------------------------- まとめての照合
# 段落ごとに PDF の窓（段落の長さ + 60 文字ほど）を決めて照合すると、PDF の中で段落が長い表・図の中の文字・別の段落（2 段組みの
# 読み順のずれ）に分断されたとき、段落の後ろ（前）が窓の外に出て、窓の中のほかの文字と並べられ、ルート2 で docx の本文を消したり
# 置き換えたりしていた（0.20.0 まで）。全段落を docx の順につないだ列を PDF の列に単調に対応させ（_backbone）、段落ごとの
# 塊にしてから、窓を塊のある行から作る（_window_lines）。
JOINT_K = 8          # アンカー（docx と PDF のどちらにも 1 回だけ出る文字の並び）の長さ
JOINT_SOLID = 8      # 段落の主な塊から離れた塊は、これだけの文字が一致しなければ偶然の一致とみなす
JOINT_GAP = 20       # 塊の間の PDF の文字が docx の文字よりこれだけ多ければ、段落が分断されているとみなす
JOINT_FREE = 20      # 分断された塊のすぐ後ろ（前）に、どの段落にも当たらない文字がこれだけ続くなら、その塊は疑わしい
# 2 つの段落の境目を、PDF の行の境目に置くときの点（_contests。点が同じときだけ行の境目にする。1 文字の一致より小さくする:
# 大きいと、次の段落の書き出しの 1 文字〈行の最後の「話」〉を前の段落のものにして、ルート2 でその文字を消していた）
LINE_BONUS = 0.5
JOINT_EDGE = 5       # 段落の最後（最初）の穴の、最後（最初）からまったく同じに続く部分だけを置くときの最小の長さ
SENTENCE_END = "。．.!?！？」』）)"     # 段落の最後に足す文字がこれで終わっていれば、文が終わっているとみなす
# 文の終わり（句点・疑問符など。半角の「.」は英数字が続かないものだけ〈「pp.11」「3.5」の「.」は文の終わりでない〉）と、その
# 後ろの閉じかっこ・かぎかっこ。SENTENCE_END と違い、閉じかっこだけ（図の中の「時間（分）」の「）」など）では文の終わりとしない
RE_STOP = re.compile(r"(?:[。．!?！？]|\.(?![0-9A-Za-z]))[」』）)]*")


def _ends_sentence(s: str) -> bool:
    """文字列 s（前後の空白は見ない）が、文の終わり（RE_STOP）で終わるか。"""
    s = s.rstrip()
    return any(m.end() == len(s) for m in RE_STOP.finditer(s))


def _after_stop(before: str, added: str):
    """段落の最後（docx の最後の文字が before で終わる）に足す PDF の文字 added のうち、before の最後か added の中の、いちばん
    後ろの文の終わり（RE_STOP）より後ろの文字。そのような文の終わりがなければ None。"""
    full = before + added
    last = None
    for m in RE_STOP.finditer(full):
        if m.end() >= len(before):
            last = m
    return None if last is None else full[last.end():]


def _docx_tail(seq, gens, n=8) -> str:
    """段落の照合用の文字の列 seq の、最後の n 文字（数式・画像〈SKIP〉と Word が付ける番号の文字を除く）。"""
    return "".join(c for i, (c, _) in enumerate(seq) if c != SKIP and i not in gens)[-n:]


@dataclass
class _JointResult:
    """まとめての照合の結果（段落は compare の paras の順）。

    windows: 段落ごとの窓（列の位置のリスト）。見つからなければ None。
    unsure: 段落ごとの印の辞書。head・tail: 段落の最初・最後の docx の文字の位置を決められないか（UNSURE_WHY）。flow: 本文の
    流れの段落か（図・表のキャプション・表のセル・図形の中の段落でない）。floaty: 列の位置のうち、段落を分断する表・図の中の
    文字とみなすもの。doubt: 図の中の文字に挟まれた、分断された部分の行の番号（図の中の原稿の写しかもしれない。
    DISPLACED_WHY）。tail_beyond: 段落の最後の docx の文字がどの塊にも入らず、docx ですぐ後ろの本文の段落の塊のすぐ後ろに、
    文の終わりで終わる、どの段落にも当たらない行があるか（_Joint.tail_beyond。段落の最後の PDF の同じ行に文字がなければ、
    消さない。UNSURE_WHY）。head_free・tail_free: 窓のすぐ前（後ろ）の行が、どの段落の塊の文字もなく、照合に使わない文字だけ
    でもない行か。tail_free_end: さらに、窓のすぐ後ろのその行が、文の終わりの記号（SENTENCE_END）で終わるか（段落の最後の行が、
    校正で直されて docx の文字と一致しなくなったものかもしれない）。
    """
    windows: list
    unsure: list


def _backbone(D: str, P: str):
    """docx の段落をつないだ列 D（段落の区切りは SEP）と PDF の列 P の、単調な（順序を保った）対応。

    D と P のどちらにも 1 回だけ出る JOINT_K 文字の並び（アンカー）を D の順に並べ、P の位置が増える最長の列（最長増加列）を
    取り、その間を difflib で埋める（0.20.0 の difflib による全体の照合とほぼ同じ対応になり、何十倍も速い）。
    戻り値: (d2c, points)。d2c は D の各位置の P の位置（なければ -1）。points はアンカーの (D の位置, P の位置) のすべて
    （D の位置の順。単調な対応に入らなかった、順序の違う段落・部分を探すのに使う）。
    """
    def grams(s):
        first, dup = {}, set()
        for i in range(len(s) - JOINT_K + 1):
            g = s[i:i + JOINT_K]
            if g in first:
                dup.add(g)
            else:
                first[g] = i
        return {g: i for g, i in first.items() if g not in dup and SEP not in g and SKIP not in g}
    gd, gp = grams(D), grams(P)
    points = sorted((gd[g], gp[g]) for g in gd.keys() & gp.keys())
    # 最長増加列（patience sorting）
    tails, idx, prev = [], [], [-1] * len(points)
    for n, (_, c) in enumerate(points):
        x = bisect.bisect_left(tails, c)
        if x == len(tails):
            tails.append(c)
            idx.append(n)
        else:
            tails[x] = c
            idx[x] = n
        prev[n] = idx[x - 1] if x else -1
    chain = []
    n = idx[-1] if idx else -1
    while n >= 0:
        chain.append(points[n])
        n = prev[n]
    chain.reverse()
    d2c = [-1] * len(D)
    last_d, last_c = -1, -1
    for d0, c0 in chain:
        for k in range(JOINT_K):
            d, c = d0 + k, c0 + k
            if d > last_d and c > last_c:
                d2c[d] = c
                last_d, last_c = d, c
    # アンカーの間を difflib で埋める
    fixed = [(d, d2c[d]) for d in range(len(D)) if d2c[d] >= 0]
    for (d0, c0), (d1, c1) in zip([(-1, -1)] + fixed, fixed + [(len(D), len(P))]):
        if d1 - d0 > 1 and c1 - c0 > 1:
            sm = difflib.SequenceMatcher(None, D[d0 + 1:d1], P[c0 + 1:c1], autojunk=False)
            for a, b, m in sm.get_matching_blocks():
                for k in range(m):
                    d2c[d0 + 1 + a + k] = c0 + 1 + b + k
    return d2c, points


def _runs(pairs):
    """[(seq の位置, core の位置)]（seq の順）を、PDF の中で続いた塊に分ける。塊の間で、PDF の文字が docx の文字より
    JOINT_GAP 文字以上多いか、PDF の位置が戻るところで分ける。"""
    out = []
    for i, c in pairs:
        if out:
            pi, pc = out[-1][-1]
            if c > pc and (c - pc) - (i - pi) < JOINT_GAP:
                out[-1].append((i, c))
                continue
        out.append([(i, c)])
    return out


def _match(H, cs, P):
    """docx の文字 H（key の列）と、core の位置 cs の文字の照合。一致した (H の位置, core の位置) のリスト。"""
    sm = difflib.SequenceMatcher(None, H, "".join(P[c] for c in cs), autojunk=False)
    return [(a + k, cs[b + k]) for a, b, m in sm.get_matching_blocks() for k in range(m)]


def _edge_block(m, n, cs, step) -> list:
    """照合の結果 m（(H の位置, core の位置) のリスト）のうち、H（長さ n）の最後と cs の最後（step < 0 なら、H の最初と cs の
    最初）から、どちらも続いて一致した部分。"""
    if not m or not cs:
        return []
    if step > 0:
        if m[-1] != (n - 1, cs[-1]):
            return []
        k = len(m) - 1
        while k > 0 and m[k - 1] == (m[k][0] - 1, m[k][1] - 1):
            k -= 1
        return m[k:]
    if m[0] != (0, cs[0]):
        return []
    k = 0
    while k + 1 < len(m) and m[k + 1] == (m[k][0] + 1, m[k][1] + 1):
        k += 1
    return m[:k + 1]


def _flow_paragraphs(plan, paras) -> list:
    """段落ごとに、本文の流れの段落か（図・表のキャプション・表のセル・図形の中の段落でないか）。PDF では、図・表の文字は
    本文の段落の間（途中）のどこにでも出るので、段落の前後の部分を探すときに飛ばす。"""
    from .linker import body_paragraphs
    where = {p.src: w for p, w in body_paragraphs(plan)}
    return [where.get(p.src) not in ("caption", "cell", "formula") and not p.float_id and not p.in_textbox
            for p, _, _ in paras]


class _Joint:
    """まとめての照合の途中の状態（compare の中だけで使う）。

    own: core の位置 -> 段落の番号（どの段落の塊でもなければ -1）。kept: 段落の番号 -> [(seq の位置, core の位置)]（seq の順）。
    """

    def __init__(self, plan, paras, st: PdfStream, gaps=None):
        self.paras, self.st = paras, st
        self.core = [k for k in range(len(st.chars)) if not st.line_only[k]]
        self.cidx = [-1] * len(st.chars)
        for x, k in enumerate(self.core):
            self.cidx[k] = x
        keys = st.keys
        self.P = "".join(keys[k] for k in self.core)
        self.line_of = [st.line[k] for k in self.core]
        self.line_len = Counter(self.line_of)
        whole, self.spans = [], []
        for p, seq, _ in paras:
            self.spans.append((len(whole), len(whole) + len(seq)))
            whole.extend(key(c) for c, _ in seq)
            whole.append(SEP)
        self.d2c, self.points = _backbone("".join(whole), self.P)
        self.flow = _flow_paragraphs(plan, paras)
        # docx で段落のすぐ後ろ（前）に、図・表など（図・表のキャプション・表のセル・画像だけの段落など、本文の流れの段落で
        # ないもの）があるか。PDF で段落の後ろ（前）に続く図・表の文字が、docx のそれに当たるか
        gaps = gaps or [False] * len(paras)
        self.material_after = [k + 1 < len(paras) and (not self.flow[k + 1] or gaps[k + 1]) for k in range(len(paras))]
        self.material_before = [k > 0 and (not self.flow[k - 1] or gaps[k]) for k in range(len(paras))]
        self.real = [[i for i, (c, _) in enumerate(seq) if c != SKIP] for _, seq, _ in paras]
        self.own = [-1] * len(self.P)
        self.kept = [[] for _ in paras]
        self.doubt = set()        # core の位置: 図の中の文字に挟まれた、分断された部分（図の中の原稿の写しかもしれない）

    # ------------------------------------------------------------------ 補助
    def set_kept(self, n, pairs):
        for _, c in self.kept[n]:
            if self.own[c] == n:
                self.own[c] = -1
        self.kept[n] = sorted(pairs)
        for _, c in self.kept[n]:
            self.own[c] = n

    def free(self, c):        # core の位置 c が、どの段落の塊でもなく、照合に使わない文字（受付日・柱の候補の行）でもないか
        k = self.core[c]
        return self.own[c] < 0 and self.st.date[k] < 0 and not self.st.head[k]

    def free_after(self, c, stop=JOINT_FREE):    # c の行の次の行から、どの段落にも当たらない文字がいくつ続くか
        lo = self.line_of
        n, x = 0, c + 1
        while x < len(self.P) and lo[x] == lo[c]:
            x += 1
        while x < len(self.P) and n < stop and self.own[x] < 0:
            n += self.free(x)
            x += 1
        return n

    def free_before(self, c, stop=JOINT_FREE):
        lo = self.line_of
        n, x = 0, c - 1
        while x >= 0 and lo[x] == lo[c]:
            x -= 1
        while x >= 0 and n < stop and self.own[x] < 0:
            n += self.free(x)
            x -= 1
        return n

    def figure_ctx(self, c, step, stop=JOINT_FREE, short=False):
        """core の位置 c の行の次（前）の行から、図・表の文字とみなせる文字（どの段落にも当たらない文字と、図・表の
        キャプション・表のセルの塊の文字。照合に使わない文字は数えない）がいくつ続くか（本文の流れの段落の塊の文字で止める。
        stop で打ち切る）。short なら、ページの途中の短い行（表のセル「1組」など。柱の候補の行のうちページの端でないもの）の
        文字も数える。"""
        lo = self.line_of
        n, x = 0, c + step
        while 0 <= x < len(self.P) and lo[x] == lo[c]:
            x += step
        while 0 <= x < len(self.P) and n < stop:
            o = self.own[x]
            if o >= 0 and self.flow[o]:
                break
            k = self.core[x]
            n += o >= 0 or (self.st.date[k] < 0 and (not self.st.head[k] or (short and not self.st.edge[k])))
            x += step
        return n

    def in_figure(self, n, first, last):
        """本文の流れの段落 n の、core の位置 first から last までの部分の前と後ろの両方に、図・表の文字とみなせる文字が
        JOINT_FREE 以上続くか（図の中の原稿の写しなど。本当に分断された段落の部分なら、少なくとも一方は本文の段落に接する。
        図・表のキャプションなどは、図・表の文字の隣にあるのがふつうなので、調べない）。"""
        return self.flow[n] and self.figure_ctx(first, -1) >= JOINT_FREE and self.figure_ctx(last, 1) >= JOINT_FREE

    def place_between(self, n):
        """どの塊もない段落 n を、docx で前後の、塊のある段落（主な塊）の PDF の位置の間で探す。段落の文字（key）と同じ文字列が
        どの段落にも当たらない文字の中にあれば、前の段落にいちばん近いもの（アンカーにならない、2 回以上出る文字列の段落。
        図の中の原稿の写しにも同じ文字列があるキャプションなど）。

        core の中に見つからなければ、行全体でしか一致させない行（PdfStream.line_only。core に入らない）の文字も、行全体が段落の
        文字の中にあれば使って探す（くり返し示す問題文など、同じ文字の段落の最初の行が何ページにも出る形。その行は core に
        入らないので、段落の文字の半分も core にないと、ほかの方法では置けない）。返すのは core の位置の部分だけ（その行は、窓を
        作るときに隣の照合に使わない行として窓に入り、段落ごとの照合で行全体で一致する）。"""
        def main(m):
            return max(_runs(self.kept[m]), key=len)
        prev = next((m for m in range(n - 1, -1, -1) if self.kept[m]), None)
        nxt = next((m for m in range(n + 1, len(self.paras)) if self.kept[m]), None)
        lo = main(prev)[-1][1] if prev is not None else -1
        hi = main(nxt)[0][1] if nxt is not None else len(self.P)
        if hi <= lo:
            return None
        seq = self.paras[n][1]
        idx = [i for i in self.real[n]]
        text = "".join(key(seq[i][0]) for i in idx)
        cs = [c for c in range(lo + 1, hi) if self.own[c] < 0]
        at = "".join(self.P[c] for c in cs).find(text)
        if at >= 0 and all(cs[at + k] == cs[at] + k for k in range(len(text))):
            return [(i, cs[at + k]) for k, i in enumerate(idx)]
        st = self.st
        k0 = self.core[lo] + 1 if lo >= 0 else 0
        k1 = self.core[hi] if hi < len(self.P) else len(st.chars)
        ks = [k for k in range(k0, k1) if self.cidx[k] < 0 or self.own[self.cidx[k]] < 0]
        at = "".join(key(st.chars[k]) for k in ks).find(text)
        if at < 0 or any(ks[at + q] != ks[at] + q for q in range(len(text))):
            return None
        span = ks[at:at + len(text)]
        lines = {st.line[k] for k in span if self.cidx[k] < 0}
        if any(st.line[k] in lines for k in range(span[0] - 1, span[-1] + 2) if 0 <= k < len(st.chars)
               and not span[0] <= k <= span[-1]):
            return None               # 行全体でしか一致させない行の一部だけが段落の文字（段落ごとの照合で一致しない）
        pairs = [(i, self.cidx[k]) for i, k in zip(idx, span) if self.cidx[k] >= 0]
        return pairs or None

    def adjacent(self, c, step, limit):
        """core の位置 c のすぐ隣（step = 1 なら後ろ、-1 なら前）から、どの段落の塊でもない位置を limit 個まで（順に並べて）。"""
        cs = []
        x = c + step
        while 0 <= x < len(self.P) and self.own[x] < 0 and len(cs) < limit:
            cs.append(x)
            x += step
        return cs if step > 0 else cs[::-1]

    def hole_text(self, n, i0, i1):
        return "".join(key(self.paras[n][1][i][0]) for i in range(i0, i1))

    def trim(self, run):
        """塊の最初・最後の 2 行以上が、この段落の一致が疎らな行（どの一致も 2 文字以下で、行の core の文字の半分以下）なら、
        それらの行を外す。アンカーの間を埋める difflib が、段落の後ろ（前）の、PDF にない docx の文字（校正で消された文）を、
        すぐ後ろ（前）の図の中の文字などと偶然並べたものを、段落の塊に入れないため（1 行だけなら、校正で大きく直された段落の
        最後〈最初〉の行かもしれないので外さない）。"""
        def sparse(line_pairs):
            blocks, last = [], None
            for i, c in line_pairs:
                if last is not None and c == last[1] + 1 and i == last[0] + 1:
                    blocks[-1] += 1
                else:
                    blocks.append(1)
                last = (i, c)
            return bool(blocks) and max(blocks) <= 2 and \
                len(line_pairs) * 2 <= self.line_len[self.line_of[line_pairs[0][1]]]
        lines = sorted({self.line_of[c] for _, c in run})
        by_line = {ln: [(i, c) for i, c in run if self.line_of[c] == ln] for ln in lines}
        drop = set()
        for seq_lines in (lines[::-1], lines):
            k = 0
            while k < len(seq_lines) - 1 and sparse(by_line[seq_lines[k]]):
                k += 1
            if k >= 2:
                drop.update(seq_lines[:k])
        return [x for x in run if self.line_of[x[1]] not in drop]

    # ------------------------------------------------------------------ 1 回目: 単調な対応から段落の塊を作る
    def first_pass(self):
        for n, (s, e) in enumerate(self.spans):
            runs = [self.trim(r) for r in _runs([(i - s, self.d2c[i]) for i in range(s, e) if self.d2c[i] >= 0])]
            runs = [r for r in runs if r]
            if runs:
                main = max(runs, key=len)
                runs = [r for r in runs if r is main or len(r) >= JOINT_SOLID]
                if sum(len(r) for r in runs) < 0.5 * len(self.real[n]):
                    runs = []           # 段落の半分も一致しない（偶然の一致）: 段落の一部の文字列で探し直す
            self.set_kept(n, [x for r in runs for x in r])

    def recheck_runs(self):
        """段落の主な塊から離れた塊（分断された部分）を確かめる。

        (1) その塊の docx の文字が、主な塊の側の隣の塊のすぐ隣（間の、どの段落にも当たらない文字）とも一致するなら、すぐ隣に
        移す（段落の書き出しの写しが段落のすぐ前の図の中の文字にある形。段落の文字は、分断されていなければ続いている）。
        (2) 本文の段落の塊で、その前と後ろの両方に図・表の文字とみなせる文字が JOINT_FREE 以上続くもの（in_figure）は、
        図の中の原稿の写しと並べたものかもしれない。外すと docx のその文字を消してしまう（本当に分断された部分のこともある）
        ので、塊には残し、その行の違いは直さない（doubt。DISPLACED_WHY）。
        """
        for n in range(len(self.paras)):
            runs = _runs(self.kept[n])
            if len(runs) < 2:
                continue
            m = runs.index(max(runs, key=len))
            changed = False
            for x in list(range(m - 1, -1, -1)) + list(range(m + 1, len(runs))):
                r = runs[x]
                i0, i1 = r[0][0], r[-1][0] + 1
                H = self.hole_text(n, i0, i1)
                step = 1 if x < m else -1
                y = x + step
                while not runs[y]:                                   # 外した塊は飛ばす（主な塊は外さない）
                    y += step
                near = runs[y]                                       # 主な塊の側の隣の塊
                if (x < m and near[0][1] > r[-1][1]) or (x > m and near[-1][1] < r[0][1]):
                    between = range(r[-1][1] + 1, near[0][1]) if x < m else range(near[-1][1] + 1, r[0][1])
                    if all(self.own[c] in (-1, n) for c in between):
                        cs = self.adjacent(near[0][1], -1, len(H) + 4) if x < m else \
                            self.adjacent(near[-1][1], 1, len(H) + 4)
                        cs = [c for c in cs if c not in {q for _, q in r}]
                        moved = _match(H, cs, self.P)
                        if len(moved) >= len(r) - 1 and moved:
                            runs[x] = [(i0 + a, c) for a, c in moved]
                            changed = True
                            continue
                if self.in_figure(n, r[0][1], r[-1][1]):
                    self.doubt.update(c for _, c in r)       # 外すと docx のその文字を消してしまう。直さないことにする
            if changed:
                self.set_kept(n, [p for r in runs for p in r])

    # ------------------------------------------------------------------ 2 回目: 穴を探す
    def holes(self, n):
        idx = {i for i, _ in self.kept[n]}
        out, cur = [], []
        for i in self.real[n]:
            if i in idx:
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append(i)
        if cur:
            out.append(cur)
        return out

    def neighbor(self, n, step):          # 次（前）の本文の段落で、塊のあるもの
        m = n + step
        while 0 <= m < len(self.paras) and (not self.flow[m] or not self.kept[m]):
            m += step
        return m if 0 <= m < len(self.paras) else None

    def find_hole(self, n, hole, wide):
        """段落 n の穴 hole（seq の位置のリスト）の PDF の中の位置。一致した (seq の位置, core の位置) のリスト（なければ None）。

        (1) 穴のすぐ隣の塊の、すぐ隣（はじめは穴の長さ + 4 文字、だめなら + 40 文字の中。校正で足された文字を挟んでもよい）。
        (2) 段落の最後（最初）の穴なら、塊の後ろ（前）の、どの段落にも当たらない文字の続きのうち、すぐ後ろ（前）が docx で
        後ろ（前）の本文の段落であるものの最後（最初）。間の図・表の文字・ほかの段落の塊は飛ばす。5 文字未満の穴は、
        まったく同じ文字のときだけ。ただし、続きが行まるごとで、すぐ後ろ（前）が docx ですぐ後ろ（前）の本文の段落の塊なら、
        穴の文字の一部が校正で直されたものでも置く（_loose_edge。表の後ろに出た最後の行「持った。」と docx の「取った。」。
        続きの最後〈最初〉の照合に使わない行だけの行を飛ばした後も。穴が docx で一文まるごとのときは置かない）。置いた部分が
        段落の本体から離れていれば、その違いは直さない（_isolate。図・表などに押し出された段落の続きと決められれば直す。
        _plain_tail）。
        (3) wide のとき、長い穴は、アンカー（単調な対応に入らなかったものも含む）で PDF 全体から。ほぼ続いて一致した部分
        だけを使い（分断された段落の一部分でもよい。残りは次の回に探す）、前後の両方が図・表の文字のもの（図の中の原稿の写し
        かもしれない）は、使うが直さない（doubt）。
        """
        i0, i1 = hole[0], hole[-1] + 1
        H = self.hole_text(n, i0, i1)
        need = len(hole)
        pos = dict(self.kept[n])
        left = max((i for i in pos if i < i0), default=None)
        right = min((i for i in pos if i >= i1), default=None)
        for slack in (4, 40):
            best = None
            for cs in ([self.adjacent(pos[left], 1, len(H) + slack)] if left is not None else []) + \
                      ([self.adjacent(pos[right], -1, len(H) + slack)] if right is not None else []):
                m = _match(H, cs, self.P)
                if len(m) >= max(3, 0.85 * need) and (best is None or len(m) > len(best)):
                    best = m
            if best:
                return [(i0 + a, c) for a, c in best]
        if (right is None) != (left is None):
            # (2) 段落の最後（最初）の穴: 段落の塊の後ろ（前）の、どの段落にも当たらない文字の続き（間に図・表の文字や
            # ほかの段落の塊があってもよい）のうち、すぐ後ろ（前）が docx で後ろ（前）の本文の段落の塊であるもので、その
            # 続きの最後（最初）が穴の文字と一致するもの（いちばん近いもの）
            step = 1 if right is None else -1
            c = pos[left] if right is None else pos[right]
            adj = self.neighbor(n, step)
            # 5 文字未満の穴（まったく同じ文字のときだけ置く）は、docx ですぐ後ろ（前）の本文の段落を越えた先は探さない
            # （引用文献の最初の 1 文字「試」が、前の文献を越えた先の柱「試験六郎」と並べられないように）
            nb = adj if need < JOINT_EDGE else None
            # 穴が docx で一文まるごと（段落の最後の穴なら、文の終わりの直後から始まる。段落の最初の穴なら、文の終わりか読点で
            # 終わる〈校正で消されることの多い、書き出しの「そこで，」「まず，」など〉）: 校正で消された文かもしれないので、
            # 一致した文字だけで置くこと（_loose_edge）はしない。すぐ後ろ（前）の図の中の文字の行が似ていると、図の中の文字で
            # docx の文字を置き換えてしまう（「…取った。その問題を示す。」と図の中の「問題を解きなさい。」）。置けなければ、
            # stray_edge で決められない違いになる（docx を消さない）
            sentence = _ends_sentence(self.hole_text(n, max(0, i0 - 4), i0)) if step > 0 else \
                (_ends_sentence(H) or H[-1:] in ("、", ","))
            seen, x = 0, c + step
            while 0 <= x < len(self.P) and seen < 3000:
                if self.own[x] >= 0:
                    if self.own[x] == nb:
                        break
                    x += step
                    seen += 1
                    continue
                run = []
                while 0 <= x < len(self.P) and self.own[x] < 0:
                    run.append(x)
                    x += step
                    seen += 1
                o = self.own[x] if 0 <= x < len(self.P) else None
                beyond = o is None or (self.flow[o] and (o > n if step > 0 else o < n))
                if not beyond:
                    continue
                # 続きの手前と先の両方が同じほかの本文の段落の塊の文字（その段落の塊の間の、抜けた部分）なら使わない（同じ文が
                # 隣の段落にもあり、その段落の文字の写しを、この段落の最初〈最後〉と並べないように）
                near = run[0] - step
                if o is not None and o != n and 0 <= near < len(self.P) and self.own[near] == o:
                    continue
                # 続きの最後（最初）の、照合に使わない行だけの行（次のページの最初の柱、1 ページ目の最後の投稿受付日の行など）は、
                # 3 行まで飛ばしてもよい（飛ばした後も、_loose_edge で置けるかを見る。そこに置いた部分が段落の本体から離れて
                # いれば、その違いは直さない。_isolate）
                for t in range(4):
                    cs = run[-(len(H) + 6):] if step > 0 else run[-(len(H) + 6):][::-1]
                    m = _match(H, cs, self.P)
                    end_ok = m and ((m[-1][1] >= cs[-1] - 1) if step > 0 else (m[0][1] <= cs[0] + 1))
                    if cs and len(m) >= max(1, 0.85 * need) and end_ok and (need >= 5 or len(m) == need):
                        return [(i0 + a, c) for a, c in m]
                    loose = self._loose_edge(n, run, H, step) if o is not None and o == adj and not sentence else None
                    if loose:
                        # 続きの最後（最初）の行まるごとが、校正で一部を直された段落の最後（最初）の行で、すぐ後ろ（前）が
                        # docx ですぐ後ろ（前）の本文の段落の塊: 一致した文字だけを置く（残りは段落ごとの照合で違いになる）
                        return [(i0 + a, c) for a, c in loose]
                    # 穴の最後（最初）の JOINT_EDGE 文字以上が、続きの最後（最初）とまったく同じに続いて一致する（穴の残りは
                    # 校正で直された文字。docx「資料に見いだした。」、PDF「付」〈受付日〉「録に見いだした。」）: その部分だけを置く
                    # （残りは次の回に探すか、段落ごとの照合で違いになる）
                    edge = _edge_block(m, len(H), cs, step)
                    if len(edge) >= JOINT_EDGE:
                        return [(i0 + a, c) for a, c in edge]
                    if not run:
                        break
                    ln = self.line_of[run[-1]]
                    tail_line = [c for c in run if self.line_of[c] == ln]
                    if not all(self.st.head[self.core[c]] or self.st.date[self.core[c]] >= 0 for c in tail_line):
                        break
                    run = [c for c in run if self.line_of[c] != ln]
        if wide and need >= JOINT_K:
            s = self.spans[n][0]
            lo_d, hi_d = s + i0, s + i1 - JOINT_K
            a = bisect.bisect_left(self.points, (lo_d, -1))
            votes = Counter()
            for d, c in self.points[a:]:
                if d > hi_d:
                    break
                if self.own[c] < 0:
                    votes[c - d] += 1
            for diag, _ in votes.most_common(4):
                c0 = diag + s + i0
                cs = [c for c in range(max(0, c0 - 6), min(len(self.P), c0 + (i1 - i0) + 12)) if self.own[c] < 0]
                m = _match(H, cs, self.P)
                # 一致した部分の docx の範囲で、ほぼ続いて一致したもの（分断された段落の一部分でもよい。残りは次の回に探す）
                while m and len(m) >= JOINT_K:
                    span = m[-1][0] - m[0][0] + 1
                    if len(m) >= 0.8 * span:
                        break
                    runs = _runs(m)
                    m = max(runs, key=len) if len(runs) > 1 else []
                if len(m) < JOINT_K:
                    continue
                if self.in_figure(n, m[0][1], m[-1][1]):
                    self.doubt.update(c for _, c in m)       # 図の中の原稿の写しかもしれない: 直さないことにする
                return [(i0 + a, c) for a, c in m]
        return None

    def _loose_edge(self, n, run, H, step):
        """find_hole の (2) で、本文の流れの段落 n の最後（step = 1。-1 なら最初）の穴 H を、どの段落にも当たらない文字の続き
        run（find_hole の走査の順）の、docx ですぐ後ろ（前）の本文の段落の塊の側の行まるごとに、一致した文字だけで置くなら、
        その一致（(H の位置, core の位置) のリスト）。置かないなら None。穴の文字の一部が校正で直されたもの（表の後ろに出た
        段落の最後の行「持った。」と docx の「取った。」。表のセルは 4 文字未満の段落なので、run に入る）。

        run のすぐ後ろ（前）が docx ですぐ後ろ（前）の本文の段落の塊であること（呼ぶ側で確かめる）に加えて、その側の 1 行
        以上の行まるごと（PDF の行の最初から行の終わりまで。長さが穴の半分以上になるまで行を足す）が、受付日の文字を含まず、
        長さが穴 + 2 文字以下で、穴の文字の半分以上が一致し、穴の最後（最初）の文字がその行の最後（最初）の文字と一致する
        もの。"""
        need = len(H)
        part = self._edge_part(n, run, need, step)
        if not need <= 2 * len(part) <= 2 * need + 4:
            return None
        st = self.st
        k0, k1 = self.core[part[0]], self.core[part[-1]]
        if (k0 > 0 and st.line[k0 - 1] == st.line[k0]) or (k1 + 1 < len(st.chars) and st.line[k1 + 1] == st.line[k1]) \
                or any(st.date[self.core[c]] >= 0 for c in part):
            return None
        m = _match(H, part, self.P)
        if not m or 2 * len(m) < need or (step > 0 and m[-1] != (need - 1, part[-1])) or \
                (step < 0 and m[0] != (0, part[0])):
            return None
        return m

    def _edge_part(self, n, run, need, step) -> list:
        """どの段落にも当たらない文字の続き run（find_hole の走査の順）の、docx ですぐ後ろ（前）の本文の段落の塊の側から、
        行ごとに、長さが need の半分以上になるまで取った部分（core の位置を順に。本文の流れの段落でなければ空）。"""
        if not self.flow[n] or not run:
            return []
        lines = []                       # run の行ごとの core の位置（列の順）
        for c in (run if step > 0 else run[::-1]):
            if lines and self.line_of[lines[-1][-1]] == self.line_of[c]:
                lines[-1].append(c)
            else:
                lines.append([c])
        part = []
        for ln in (lines[::-1] if step > 0 else lines):
            part = ln + part if step > 0 else part + ln
            if 2 * len(part) >= need:
                break
        return part

    def edge_run(self, n, step) -> list:
        """段落 n の最後（step = 1。-1 なら最初）の塊の後ろ（前）で、docx ですぐ後ろ（前）の本文の段落の塊のすぐ前（後ろ）に
        続く、どの段落にも当たらない文字の続き（core の位置。find_hole の走査の順。間の表・図・ほかの段落の塊は飛ばす。なければ
        空）。"""
        adj = self.neighbor(n, step)
        if adj is None:
            return []
        run, x = [], (self.kept[n][-1][1] if step > 0 else self.kept[n][0][1]) + step
        for _ in range(3000):
            if not 0 <= x < len(self.P):
                break
            o = self.own[x]
            if o == adj:
                return run
            run = [] if o >= 0 else run + [x]
            x += step
        return []

    def stray_edge(self, n, step) -> bool:
        """本文の流れの段落 n の最後（step = 1。-1 なら最初）の穴（どの塊にも入らなかった docx の文字）が、PDF の中で表・図・
        ほかの段落の後ろ（前）に出て、校正で大きく直されたもの（穴として置けなかった）かもしれないか（result。消さない）。

        docx ですぐ後ろ（前）の本文の段落の塊のすぐ前（後ろ）に、どの段落にも当たらない文字の続きがあり（edge_run）、その
        段落の側の行（_edge_part。その側の、投稿受付日かページの端の行〈柱など〉の文字だけの行は 3 行まで飛ばす）と穴の文字が、
        穴の 3 分の 1 以上一致するもの。表のセル（4 文字未満の段落なので、どの段落にも当たらない）・図の中の文字が続くだけなら、
        穴の文字は校正で消されたものとして今までどおり消す。"""
        holes = self.holes(n)
        if not holes:
            return False
        hole = holes[-1] if step > 0 else holes[0]
        if (step > 0 and hole[-1] != self.real[n][-1]) or (step < 0 and hole[0] != self.real[n][0]):
            return False
        H = self.hole_text(n, hole[0], hole[-1] + 1)
        run = self.edge_run(n, step)
        for _ in range(4):
            part = self._edge_part(n, run, len(H), step)
            m = _match(H, part, self.P) if part else []
            if m and 3 * len(m) >= len(H):
                return True
            # 続きの、docx ですぐ後ろ（前）の本文の段落の側の、投稿受付日の文字かページの端の行（柱など）の文字だけの行
            # （1 ページ目の最後の投稿受付日の行、次のページの最初の柱など）は、3 行まで飛ばして見る（find_hole の (2) と同じ。
            # ただし、図の中の短い行〈「↓」など。柱の候補の行〉は飛ばさない: 一致が穴の 3 分の 1 でよいので、飛ばして図の中に
            # 入ると、図の中の文字との偶然の一致で決められない違いにしてしまう）
            line = [c for c in run if self.line_of[c] == self.line_of[run[-1]]] if run else []
            if not line or not all(self.st.edge[self.core[c]] or self.st.date[self.core[c]] >= 0 for c in line):
                return False
            run = [c for c in run if self.line_of[c] != self.line_of[line[0]]]
        return False

    def tail_beyond(self, n) -> bool:
        """本文の流れの段落 n の最後の穴（どの塊にも入らなかった docx の文字）が、2 段組みの読み順のずれで、docx ですぐ後ろの
        本文の段落の後ろに出た、段落の最後の行かもしれないか（result。段落の最後の PDF の同じ行に文字がなければ、消さない）。

        段落 n の最後の塊の後ろで最初に出会う、docx ですぐ後ろの本文の段落の塊のすぐ後ろに、行まるごとどの段落にも当たらない、
        文の終わりで終わる和文の行（段落の最後の行らしい行。_tail_line_after）があるもの。"""
        if not self.flow[n]:
            return False
        holes = self.holes(n)
        if not holes or holes[-1][-1] != self.real[n][-1]:
            return False
        adj = self.neighbor(n, 1)
        if adj is None:
            return False
        x = self.kept[n][-1][1] + 1
        for _ in range(3000):
            if not 0 <= x < len(self.P):
                return False
            if self.own[x] == adj:
                return self._tail_line_after(x, adj)
            x += 1
        return False

    def _tail_line_after(self, x, adj) -> bool:
        """tail_beyond: core の位置 x から続く段落 adj の塊のすぐ後ろの、どの段落にも当たらない文字の続きの行（4 行まで）に、
        行まるごとどの段落にも当たらない、文の終わりで終わる和文の行（受付日の文字・行末のハイフンを除いて見る。ページの端の
        柱の候補の行・MIN_CHARS 文字未満の行は除く）があるか。"""
        st = self.st
        while x < len(self.P) and self.own[x] == adj:
            x += 1
        lines = []                       # 続きの行の番号（列の順。4 行目は最初の文字まで続いていればよい）
        while x < len(self.P) and self.own[x] < 0 and len(lines) <= 3:
            if not lines or lines[-1] != self.line_of[x]:
                lines.append(self.line_of[x])
            x += 1
        for ln in lines:
            body = [k for k in st.line_range(ln) if not st.soft[k] and st.date[k] < 0]
            if not body or any(self.cidx[k] >= 0 and self.own[self.cidx[k]] >= 0 for k in body) or \
                    (st.edge[body[0]] and st.head[body[0]]) or _visible_count(st.lines[ln]) < MIN_CHARS:
                continue
            s = "".join(st.chars[k] for k in body)
            if _mostly_wide(s) and _ends_sentence(s):
                return True
        return False

    def fill_holes(self):
        """段落の、どの塊にも入らなかった部分（穴）を探す（見つかった部分は段落の塊に加える）。

        回ごとに、まず、どの塊もない段落をアンカーで探し（その段落の文字を、ほかの段落の最後の部分と取り違えないように先に
        置く）、次に、塊のある段落の穴を探す（はじめの回は、穴のすぐ隣と、次〈前〉の本文の段落のすぐ前〈後ろ〉だけ。次の回から
        アンカーでも）。見つからなかった段落・部分のために、ほかの段落の位置が決まるたびに、もう一度探す（最大 6 回）。どの塊も
        ない段落（短い見出しなど、アンカーのないもの）は、新しく置けるものがなくなったら、docx で前後の段落の間で同じ文字列を
        探し、それもなければ段落の一部の文字列が PDF の中で 1 回だけ出る位置を探す（0.20.0 の探し方）。
        """
        for rnd in range(6):
            changed = False
            for whole in (True, False):
                order = sorted((n for n in range(len(self.paras)) if bool(self.kept[n]) != whole),
                               key=lambda n: -len(self.real[n]))
                for n in order:
                    for hole in self.holes(n):
                        found = self.find_hole(n, hole, whole or rnd > 0)
                        if found:
                            self.set_kept(n, self.kept[n] + found)
                            changed = True
            if rnd > 0 and not changed:
                placed = False
                for n in range(len(self.paras)):
                    if not self.kept[n] and self.real[n]:
                        m = self.place_between(n) or _unique_piece(self.paras[n][1], self.P, self.own)
                        if m:
                            self.set_kept(n, m)
                            placed = True
                if not placed:
                    break

    def release_islands(self):
        """段落の 1〜2 文字の塊（PDF の中で続いた文字）で、隣の塊との間にほかの段落の塊の文字があるもの（前か後ろの少なくとも
        一方）を外す。アンカーの間を埋める difflib が、校正で消された段落の最後の文字（「以上が…」の「が」）や、校正で動いた
        句点を、ほかの段落の中の同じ文字と偶然並べたもの（外さないと、その段落の窓からその文字が抜けて、ルート2 で消してしまう）。
        本当に分断された 1〜2 文字（表の後ろに出た段落の最後の「た。」）は、もう一度穴として探す（fill_holes）。
        段落の途中の、PDF の 1 行の中だけの偶然の一致（line_islands）も外す。"""
        for x in range(len(self.paras)):
            pairs = sorted(self.kept[x], key=lambda t: t[1])
            blocks = []
            for i, c in pairs:
                if blocks and c == blocks[-1][-1][1] + 1:
                    blocks[-1].append((i, c))
                else:
                    blocks.append([(i, c)])
            if len(blocks) < 2:
                continue
            drop = set()
            for b, blk in enumerate(blocks):
                if len(blk) > 2:
                    continue
                sides = []
                if b > 0:
                    sides.append(range(blocks[b - 1][-1][1] + 1, blk[0][1]))
                if b + 1 < len(blocks):
                    sides.append(range(blk[-1][1] + 1, blocks[b + 1][0][1]))
                if any(any(self.own[c] not in (-1, x) for c in rg) for rg in sides):
                    drop.update(c for _, c in blk)
            drop |= self.line_islands(x)
            if drop:
                self.set_kept(x, [(i, c) for i, c in self.kept[x] if c not in drop])

    def line_islands(self, x):
        """段落 x の途中の、PDF の 1 行の中だけの偶然の一致（その行の段落 x の文字が ISLAND 文字以下で、行の文字の半分以上が
        段落 x の文字でなく、段落 x の文字が前の行にも後ろの行にもあるもの。_line_islands と同じ）の core の位置の集合。
        docx にない表のキャプションの「表１」の「１」が、docx の「12点」の「1」と並べられたものなど（外さないと、docx の表の
        キャプションの段落がその行に置けず、段落の窓にその行が入る）。
        段落の最後（最初）の docx の文字がどの塊にも入っていない（穴がある）ときは、最後（最初）の行も同じに見る。段落の最後の
        数文字が、校正で直されて表・図の後ろに出たとき、その前の図の中の行（「前時の表を振り返る」）のよく使う文字（「時」
        「を」）が、段落の最後の docx の文字（「時間を取った。」）と偶然並ぶと、図の中の文字で docx の文字を置き換えてしまう
        （外した文字は、続く fill_holes で穴として探し直す）。"""
        per = {}
        for i, c in self.kept[x]:
            per.setdefault(self.line_of[c], []).append((i, c))
        if len(per) < 3:
            return set()
        first, last = min(per), max(per)
        seq = self.paras[x][1]
        kept_i = {i for i, _ in self.kept[x]}
        head_hole = bool(self.real[x]) and self.real[x][0] not in kept_i
        tail_hole = bool(self.real[x]) and self.real[x][-1] not in kept_i
        out = set()
        for ln, pairs in per.items():
            rest = self.line_len[ln] - len(pairs)
            edge = (ln == first and not head_hole) or (ln == last and not tail_hole)
            if edge or len(pairs) > ISLAND or rest < len(pairs) or rest >= ISLAND_REST:
                continue
            lo = min(i for i, _ in pairs)
            hi = max(i for i, _ in pairs)
            i0 = max((i for i, c in self.kept[x] if i < lo and self.line_of[c] != ln), default=-1)
            i1 = min((i for i, c in self.kept[x] if i > hi and self.line_of[c] != ln), default=len(seq))
            if any(seq[i][0] == SKIP for i in range(i0 + 1, i1)):
                continue
            out.update(c for _, c in pairs)
        return out

    # ------------------------------------------------------------------ 境目と窓
    def contests(self):
        self.contested = _contests(self.paras, self.kept, self.own, self.P, self.core, self.line_of, self.st)

    def result(self) -> _JointResult:
        windows, unsure = [], []
        line_start, line_end = {}, {}         # 行の番号 -> 列の最初・最後の位置
        for k, ln in enumerate(self.st.line):
            line_start.setdefault(ln, k)
            line_end[ln] = k
        heads_c, tails_c, chars_c = getattr(self, "contested", (set(), set(), {}))
        for n in range(len(self.paras)):
            if not self.kept[n]:
                windows.append(None)
                unsure.append({"head": False, "tail": False, "tail_beyond": False,
                               "flow": self.flow[n], "floaty": set(), "doubt": set(),
                               "head_free": False, "tail_free": False, "tail_free_end": False,
                               "head_contested": False, "tail_contested": False, "contested": set()})
                continue
            win, floaty, edges = _window_lines(n, self.kept[n], self.own, self.st, self.core, self.cidx, self.flow,
                                               line_start, line_end)
            windows.append(win)
            first, last = self.kept[n][0], self.kept[n][-1]
            # 段落の最初（最後）の docx の文字がどの塊にも入らず、PDF ではそのすぐ前（後ろ）にどの段落とも一致しない文字か、
            # 図・表の文字（キャプション・セルの段落の文字を含む。figure_ctx）が続く: docx のその文字が校正で消されたのか、
            # PDF の別の位置（表の後ろなど）にあるのか決められない
            # （docx で段落の後ろ〈前〉に図・表などがなければ、PDF のその位置の図・表の文字〈ページの途中の短い行も〉も数える。
            # docx にあれば、その図・表の文字とみなす）
            # 本文の流れの段落で、docx ですぐ後ろ（前）の本文の段落の塊のすぐ前（後ろ）に、どの段落にも当たらない文字の続きが
            # あり、その文字が docx のその文字と 3 分の 1 以上一致するときも同じ（stray_edge。表の後ろに出た段落の最後の行が
            # 校正で大きく直されて、穴として置けなかったもの〈「時間を取った。」と「場を設けて話し合わせた。」〉かもしれない）。
            # docx ですぐ後ろの本文の段落の塊のすぐ後ろに、段落の最後の行らしい行があるとき（2 段組みの読み順のずれ。tail_beyond。
            # 段落の最後の PDF の同じ行に、docx の文字の代わりになる文字がないときだけ使う。_classify）も消さない
            head_hole = any(i < first[0] for i in self.real[n])
            tail_hole = any(i > last[0] for i in self.real[n])
            head = head_hole and (max(
                self.free_before(first[1]),
                0 if self.material_before[n] else self.figure_ctx(first[1], -1, short=True)) >= JOINT_FREE
                or self.stray_edge(n, -1))
            tail = tail_hole and (max(
                self.free_after(last[1]),
                0 if self.material_after[n] else self.figure_ctx(last[1], 1, short=True)) >= JOINT_FREE
                or self.stray_edge(n, 1))
            tail_beyond = tail_hole and not tail and self.tail_beyond(n)
            # 図の中の原稿の写しかもしれない行（recheck_runs・find_hole）の違いは直さない（DISPLACED_WHY）
            doubt = {self.line_of[c] for _, c in self.kept[n] if c in self.doubt}
            unsure.append({"head": head, "tail": tail, "tail_beyond": tail_beyond,
                           "flow": self.flow[n], "floaty": floaty, "doubt": doubt, **edges,
                           "head_contested": n in heads_c, "tail_contested": n in tails_c,
                           "contested": chars_c.get(n, set())})
        return _JointResult(windows, unsure)


def _joint(plan, paras, st: PdfStream, gaps=None) -> _JointResult:
    """まとめての照合。段落ごとの窓（列の位置のリスト）を決める。"""
    jt = _Joint(plan, paras, st, gaps)
    jt.first_pass()
    jt.recheck_runs()
    jt.fill_holes()
    jt.release_islands()
    jt.fill_holes()
    jt.contests()
    return jt.result()


def _unique_piece(seq, P, own):
    """段落の一部の文字列（先頭・中ほど・最後の 24・16・10 文字か、段落の全体）が P の中で 1 回だけ出て、どの段落にも
    当たっていない位置を探し、その近くと段落を照合する。一致した (seq の位置, core の位置) のリスト（なければ空）。"""
    text = "".join(key(c) for c, _ in seq)
    n = len(text)
    for k in (24, 16, 10, n):
        if n < k or k < MIN_CHARS:
            continue
        for off in (0, max(0, n // 2 - k // 2), n - k):
            piece = text[off:off + k]
            if SKIP in piece:
                continue
            at = P.find(piece)
            if at < 0 or P.find(piece, at + 1) >= 0 or any(own[c] >= 0 for c in range(at, at + k)):
                continue
            start = at - off
            cs = [c for c in range(max(0, start - 6), min(len(P), start + n + 60)) if own[c] < 0]
            m = _match(text, cs, P)
            real = sum(1 for c, _ in seq if c != SKIP)
            if len(m) >= 0.5 * real:
                return m
    return []


def _lcs_prefix(A, Z):
    """F[s] = A と Z[:s] の最長共通部分列の長さ（s = 0..len(Z)）。"""
    row = [0] * (len(A) + 1)
    out = [0]
    for z in Z:
        prev = 0
        for x in range(1, len(A) + 1):
            cur = row[x]
            row[x] = prev + 1 if A[x - 1] == z else max(row[x], row[x - 1])
            prev = cur
        out.append(row[-1])
    return out


def _contests(paras, kept, own, P, core, line_of, st: PdfStream):
    """2 つの段落の塊が PDF の同じ行にあるとき（段落 A の塊が行の途中で終わり、段落 B の塊がその後ろから始まる）、その行の中の
    段落の境目を決め直す。

    境目 s（行の中の位置）ごとに、A のその塊の後ろの部分（次の塊までの docx の文字）と行の s より前、B のその塊の前の部分
    （前の塊からの docx の文字）と行の s より後ろの、最長共通部分列の長さを足し、s が行の始まりか終わりなら LINE_BONUS を
    足して、いちばん大きい s にする。PDF では段落は行の始まりから始まり、行の終わりで終わるので、校正で消された A の最後の
    文字（「以上」）が、B の書き出し（「以上のことから」）と並べられないように（アンカーが段落の境目をまたぐと起きる）。
    いちばん大きい s が 2 つ以上あるとき（間の文字が、校正で直された・足された文字で、どちらの段落の docx の文字とも一致
    しない）は、_contest_cut で決める。
    行の文字は、s より前を A、後ろを B のものにする（どちらの窓にも同じ文字が入らないように）。
    戻り値: (最初の docx の文字の境目を決められなかった段落の番号の集合, 最後の docx の文字の境目を決められなかった段落の番号の
    集合, 段落の番号 -> 決められなかった境目の PDF の文字の位置〈列の位置〉の集合)。_classify は、それらの段落の最初・最後の
    違いと、その文字にかかる違いを直さない（EDGE_WHY）。
    """
    heads, tails, chars = set(), set(), {}
    for b in range(len(paras)):
        for r in _runs(list(kept[b])):
            cb = r[0][1]
            if own[cb] != b:
                continue
            ln = line_of[cb]
            lo = cb
            while lo > 0 and line_of[lo - 1] == ln:
                lo -= 1
            hi = cb
            while hi + 1 < len(P) and line_of[hi + 1] == ln:
                hi += 1
            others = {own[c] for c in range(lo, cb) if own[c] >= 0 and own[c] != b}
            if len(others) != 1:
                continue
            a = others.pop()
            Z = list(range(lo, hi + 1))
            if any(own[c] not in (-1, a, b) for c in Z):
                continue
            a_line = [i for i, c in kept[a] if lo <= c <= hi]
            b_line = [i for i, c in kept[b] if lo <= c <= hi]
            if not a_line or not b_line:
                continue
            ia, ib = min(a_line), max(b_line)
            nxt = min((i for i, _ in kept[a] if i > max(a_line)), default=len(paras[a][1]))
            if any(c > hi for i, c in kept[a] if max(a_line) < i < nxt):
                continue
            prv = max((i for i, _ in kept[b] if i < min(b_line)), default=-1)
            # A の側は前の行、B の側は次の行の文字（どの段落にも当たらないか、その段落の文字）も合わせて照合する（同じ文が A の
            # 最後と B の中にあり、行の文字を A でも B でも説明できるとき、B が次の行で同じ文字を説明できるなら、その行は A の
            # もの。逆も同じ）
            prev_line = _side_line(lo - 1, -1, line_of, own, a)
            next_line = _side_line(hi + 1, 1, line_of, own, b)
            ps, ns = set(prev_line), set(next_line)
            pa = [i for i, c in kept[a] if c in ps]
            nb = [i for i, c in kept[b] if c in ns]
            A = [key(c) for c, _ in paras[a][1][min([ia] + pa):nxt]]
            B = [key(c) for c, _ in paras[b][1][prv + 1:max([ib] + nb) + 1]]
            Zk = [P[c] for c in Z]
            Fx = _lcs_prefix(A, [P[c] for c in prev_line] + Zk)
            F = Fx[len(prev_line):]
            Gx = _lcs_prefix(B[::-1], [P[c] for c in next_line][::-1] + Zk[::-1])
            G = [Gx[len(next_line) + len(Z) - x] for x in range(len(Z) + 1)]
            cur = max(x for x, c in enumerate(Z) if own[c] == a) + 1
            score = [F[s] + G[s] + (LINE_BONUS if s in (0, len(Z)) else 0) for s in range(len(Z) + 1)]
            ties = [s for s, v in enumerate(score) if v == max(score)]
            zpos = {c: x for x, c in enumerate(Z)}
            best, unsure = ties[0], False
            if len(ties) > 1:
                matched = {zpos[c] for i, c in kept[a] + kept[b] if c in zpos}
                best, unsure = _contest_cut(ties, cur, Z, P, st, core, matched)
            if unsure:
                # 境目を決められない: 間の文字は今までどおり B のものにし（cur）、A の最後・B の最初の違いと、間の文字にかかる
                # 違いを直さない（_classify）
                lo_t, hi_t = min(ties), max(ties)
                span = {core[Z[x]] for x in range(lo_t, hi_t)}
                chars.setdefault(a, set()).update(span)
                chars.setdefault(b, set()).update(span)
                if nxt == len(paras[a][1]):
                    tails.add(a)
                if prv < 0:
                    heads.add(b)
            for x, c in enumerate(Z):
                own[c] = a if x < best else b
            kept[a] = [(i, c) for i, c in kept[a] if not (c in zpos and zpos[c] >= best)]
            kept[b] = [(i, c) for i, c in kept[b] if not (c in zpos and zpos[c] < best)]
    return heads, tails, chars


def _contest_cut(ties, cur, Z, P, st: PdfStream, core, matched):
    """_contests で、点のいちばん大きい境目が 2 つ以上（ties。行の中の位置）あるときの境目と、決められないか。

    間の文字は、校正で直された・足された文字で、A・B のどちらの docx の文字とも一致しない（「確かめる」→「確かめた。」の
    「た。」、追い込みの見出し「（１）架空の目的」→「（１）架空の目標」の「標」）。どちらかに決めないと、A を途中まで直し、
    B の頭に A の文字を足す（「…確かめ」と「た。話し合いの中で…」）。次の順に決める。
      (1) 文の終わり（RE_STOP）の直後（いちばん後ろのもの。文の終わりまでは A の文）
      (2) 同じ行の中の全角の空白の直前（追い込みの見出しと本文の間。両端そろえの空白は半角）
    どちらでもなければ、決められない（間の文字を B のものにして〈今までの cur〉、直さない）。A の最後に docx の文字と一致
    しなかった文字があっても、A の最後の直し（「確かめる」→「確かめて」）と、A の最後の削除と B の書き出しの挿入（「確かめる」
    →「確かめ」と「話し合い…」→「そこで話し合い…」）は区別できない（どちらかに決めると、片方の形で、ほかの段落の文字を
    足し、足された語を落とす）。点が同じ境目の間に、docx の文字と一致した文字があるとき（同じ文が A の最後と B の最初の両方に
    あり、どちらの docx の文字でも説明できる）は、今までどおり cur にする（間の文字の持ち主は、照合で決まっている）。"""
    lo, hi = min(ties), max(ties)
    if any(lo <= x < hi for x in matched):
        return (cur if cur in ties else lo), False
    keys = "".join(P[c] for c in Z)
    stops = {m.end() for m in RE_STOP.finditer(keys)}
    t = [s for s in ties if s in stops]
    if t:
        return max(t), False
    t = [s for s in ties if s < len(Z) and st.wide_space[core[Z[s]]]]
    if t:
        return max(t), False
    return (cur if cur in ties else lo), True


def _side_line(c, step, line_of, own, n) -> list:
    """core の位置 c の行の文字のうち、どの段落にも当たらないか段落 n の文字の core の位置（順に。c が範囲の外なら空）。"""
    if not 0 <= c < len(line_of):
        return []
    ln = line_of[c]
    lo = hi = c
    while lo > 0 and line_of[lo - 1] == ln:
        lo -= 1
    while hi + 1 < len(line_of) and line_of[hi + 1] == ln:
        hi += 1
    return [x for x in range(lo, hi + 1) if own[x] in (-1, n)]


def _window_lines(n, pairs, own, st: PdfStream, core, cidx, flow, line_start, line_end):
    """段落 n の窓（列の位置のリスト）と、窓の中の、分断する表・図の中の文字とみなす位置（列の位置の集合）と、窓のすぐ前
    （後ろ）の行が、どの段落の塊の文字もない行か（{"head_free", "tail_free", "tail_free_end"}。_JointResult）。

    段落の塊（_runs）ごとに、塊の最初の行から最後の行までの文字（ほかの段落の塊の文字は除く）。塊と塊の間（PDF の位置が
    進むもの）は、間の行にほかの本文の流れの段落の塊の文字がなければすべて、あれば、塊のすぐ隣に続く、そのような文字のない
    行だけ（ほかの段落の行の、どの段落にも当たらない文字〈その段落の校正の直し〉を入れないように）。間の行に図・表の
    キャプション・表のセルの塊の文字があるとき（段落が表・図で分断されている）は、間の行の、どの段落にも当たらない文字を
    表・図の中の文字とみなす（段落に足さない。照合に使わなかった文字として記録する）。最初の塊の前と最後の塊の後ろは、
    すぐ隣に続く照合に使わない行（柱の候補の行・行全体でしか一致させない行・受付日だけの行）。
    """
    runs = _runs(pairs)
    nl = len(st.lines)

    def chars(ln):
        return range(line_start[ln], line_end[ln] + 1) if ln in line_start else range(0)

    def owners(ln):
        return {own[cidx[k]] for k in chars(ln) if cidx[k] >= 0 and own[cidx[k]] >= 0}

    def others(ln):                 # 行に、ほかの本文の流れの段落の塊の文字があるか
        return any(m != n and flow[m] for m in owners(ln))

    def ignorable(ln):              # 行の文字が、照合に使わない文字（になりうるもの）だけか（どの段落の塊の文字もない）
        for k in chars(ln):
            c = cidx[k]
            if c >= 0 and own[c] >= 0:
                return False
            if not (st.line_only[k] or st.head[k] or st.date[k] >= 0 or st.soft[k]):
                return False
        return True

    def free_line(ln):              # どの段落の塊の文字もなく、照合に使わない文字（になりうるもの）だけでもない行か
        return ln in line_start and not owners(ln) and not ignorable(ln)

    lines, floaty_lines = [], set()
    edges = {"head_free": False, "tail_free": False, "tail_free_end": False}
    for x, r in enumerate(runs):
        l0, l1 = st.line[core[r[0][1]]], st.line[core[r[-1][1]]]
        if x == 0:
            # 列に入らなかった行（ページ番号の行）は飛ばす
            while l0 > 0 and ((l0 - 1) not in line_start or ignorable(l0 - 1)):
                l0 -= 1
            edges["head_free"] = free_line(l0 - 1)
        block = list(range(l0, l1 + 1))
        if x + 1 < len(runs) and runs[x + 1][0][1] > r[-1][1]:
            m0 = st.line[core[runs[x + 1][0][1]]]
            gap = list(range(l1 + 1, m0))
            if any(others(ln) for ln in gap):
                head = []
                for ln in gap:
                    if others(ln):
                        break
                    head.append(ln)
                tail = []
                for ln in reversed(gap):
                    if others(ln):
                        break
                    tail.append(ln)
                gap = head + tail[::-1]
            if any(m != n and not flow[m] for ln in gap for m in owners(ln)):
                floaty_lines.update(gap)
            block += gap
        if x == len(runs) - 1:
            e = l1
            while e + 1 < nl and ((e + 1) not in line_start or ignorable(e + 1)):
                e += 1
                if e in line_start:
                    block.append(e)
            edges["tail_free"] = free_line(e + 1)
            edges["tail_free_end"] = edges["tail_free"] and st.lines[e + 1][-1:] in SENTENCE_END
        for ln in block:
            if ln in lines[-3:]:
                continue
            lines.append(ln)
    out, floaty = [], set()
    for ln in lines:
        for k in chars(ln):
            c = cidx[k]
            if c >= 0 and own[c] >= 0 and own[c] != n:
                continue
            out.append(k)
            if ln in floaty_lines:
                floaty.add(k)
    return out, floaty, edges


def _hyphen_key(c: str) -> str:
    """段落ごとの照合（_align）に使う文字: key に加えて、ハイフン（HYPHENS）とダッシュ（DASHES）をどれも「-」にする
    （ダッシュを違う文字とみなすと、PDF の行末の「-」を無視するので、docx のダッシュを消してしまう）。"""
    return "-" if c in HYPHENS or c in DASHES else key(c)


def _align(seq, st: PdfStream, win):
    """段落と PDF の窓（列の位置のリスト win）の照合（difflib の opcodes。PDF の側の位置は win の上の位置）。一致した文字が
    少なければ None。

    行全体でしか一致させない行（PdfStream.line_only。表のセルの数字の行など）の文字は、照合する列から除いて（0.19.0 の列と
    同じ）照合し、docx の文字がその行の文字とまったく同じに続くときだけ、行全体で一致させる（_opcodes・_whole_lines）。表の
    セルの「31」「27」の「1」「2」が docx の「12」と偶然一致して、その行の残りの文字が docx に入らないように。
    PDF の行末のハイフン（PdfStream.soft）は、docx のハイフン（HYPHENS）と同じ文字として照合する（_classify で違いにしない）。
    段落の途中の、PDF の 1 行の中だけの 1〜2 文字の偶然の一致（表のキャプションの「表１」の「１」など。_line_islands）の行は、
    照合に使わずに照合し直す。
    """
    d = "".join(_hyphen_key(c) for c, _ in seq)
    keys = ["-" if st.soft[k] else _hyphen_key(st.chars[k]) for k in win]
    w = [None if st.line_only[k] else c for k, c in zip(win, keys)]     # None はどの文字とも一致しない
    ops = _slide_inserts(_whole_lines(_opcodes(d, w), d, w, keys, st, win), w, keys, st, win)
    for _ in range(ISLAND_ROUNDS):
        # 段落の途中の、PDF の 1 行の中だけの偶然の一致の行は、照合に使わずに照合し直す（_line_islands。外した後に、
        # 次の図の行の同じ文字と偶然一致することがあるので、なくなるまで繰り返す）
        isl = _line_islands(ops, seq, w, st, win) | _date_islands(ops, w, st, win)
        if not isl:
            break
        w = [None if j in isl else c for j, c in enumerate(w)]
        ops = _slide_inserts(_whole_lines(_opcodes(d, w), d, w, keys, st, win), w, keys, st, win)
    real = sum(1 for c, _ in seq if c != SKIP)
    same = sum(i2 - i1 for t, i1, i2, _, _ in ops if t == "equal")
    return ops if same >= MIN_COVERAGE * real else None


ISLAND = 2           # 段落の途中の PDF の 1 行で、この段落の文字との一致がこれ以下なら、偶然の一致かもしれない
ISLAND_REST = 20     # その行の残りの文字がこれ以上なら外さない（PDF にだけある 20 文字以上の文字は足さない規則〈LONG_WHY〉を保つ）
ISLAND_ROUNDS = 10   # 段落ごとの照合で、偶然の一致の行を外して照合し直す回数の上限


def _line_islands(ops, seq, w, st: PdfStream, win) -> set:
    """段落の途中の、PDF の 1 行の中だけの偶然の一致の行の文字の、窓の中の位置（w が None でないもの）の集合。

    その行でこの段落の文字と一致したのが ISLAND 文字以下で、行の（窓の中の）文字の半分以上が一致せず、この段落の一致した
    文字が前の行にも後ろの行にもあるもの（docx にない表のキャプション「表１　架空の得点」の「１」や、表のセル「1組」の「1」が、
    出版版で直された docx の「12点」〈PDF「13点」〉の「1」と偶然一致したもの）。その一致を残すと、その行の残りの文字
    （キャプション・セル）を docx に足したり（行の最初の「表」）、数字を二重にしたり（「1」の後ろに「13」）する。その行を
    照合に使わずに照合し直すと、その行の文字は、隣の一致しない部分といっしょに今までどおり扱われる（照合に使わない文字の
    間にある、どの段落の文字とも一致しない行は足さない）。段落の行が校正でまるごと書き換えられて 1〜2 文字だけ同じ
    だったときは、同じ文字が隣の違いの部分に入るだけで、PDF に合わせた後の文字は変わらない。docx の数式・画像（SKIP）の
    すぐそばの行（PDF では数式の文字の行）と、行の残りの文字が ISLAND_REST 文字以上の行は外さない（一致を外すと、PDF に
    だけある長い文字が置き換えの一部になり、20 文字以上は足さない規則〈LONG_WHY〉が働かなくなる）。
    """
    eq = [op for op in ops if op[0] == "equal"]
    per = Counter()
    for _, _, _, j1, j2 in eq:
        for j in range(j1, j2):
            per[st.line[win[j]]] += 1
    if len(per) < 3:
        return set()
    first, last = min(per), max(per)
    # 行の文字の数（窓の中の、行全体でしか一致させない文字を除く。投稿受付日の文字も数える〈_classify の 20 文字の数え方と同じ〉）
    size = Counter(st.line[k] for j, k in enumerate(win) if w[j] is not None)
    lines = set()
    for ln, n in per.items():
        if ln in (first, last) or n > ISLAND or size[ln] < 2 * n or size[ln] - n >= ISLAND_REST:
            continue
        # その行の一致の前後の、ほかの行の一致の間の docx の文字に、数式・画像（SKIP）がない
        mine = [op for op in eq if st.line[win[op[3]]] == ln or st.line[win[op[4] - 1]] == ln]
        before = [op for op in eq if op[4] <= mine[0][3] and st.line[win[op[4] - 1]] != ln]
        after = [op for op in eq if op[3] >= mine[-1][4] and st.line[win[op[3]]] != ln]
        i0 = before[-1][2] if before else 0
        i1 = after[0][1] if after else len(seq)
        if any(seq[i][0] == SKIP for i in range(i0, i1)):
            continue
        lines.add(ln)
    return {j for j, k in enumerate(win) if st.line[k] in lines and w[j] is not None}


def _date_islands(ops, w, st: PdfStream, win) -> set:
    """一致した塊の中の、投稿受付日などの文字（RE_RECEIVED）のうち、その受付日の文字列の一部だけと並んだもの（docx の段落に
    受付日の文字列はなく、偶然の一致）の、窓の中の位置の集合。_align はこの位置を照合に使わずに照合し直す。docx の引用文献の
    最後の「29．」の「2」が、次の行の受付日「2026年…」の「2」と偶然並ぶと、残りの「9．」と受付日の文字が違いになり、その前に
    PDF の「30．」を足して「30．29．」にしていた（0.20.0）。塊の端の受付日の文字（「（試験，20」の後ろにつながった受付日の
    「2026」の「2」と、docx の「2021」の 3 文字目）も同じで、外さないと「20223」にしていた。"""
    size = None
    out = set()
    for t, i1, i2, j1, j2 in ops:
        if t != "equal":
            continue
        # 塊が受付日の文字列の一部だけと並んだ（docx の段落に受付日の文字列はない）なら、その受付日の文字を外す。塊の端の
        # 受付日の文字（「（試験，」の後ろにつながった受付日「2026年…」の「202」と、docx の「2021」の「202」）も同じ。
        # docx に同じ受付日の文字列があれば、その文字列全体と並ぶので外さない
        got = {}
        for j in range(j1, j2):
            d = st.date[win[j]]
            if d >= 0:
                got.setdefault(d, []).append(j)
        if not got:
            continue
        if size is None:
            size = Counter(x for x in st.date if x >= 0)
        for d, js in got.items():
            if len(js) < size[d]:
                out.update(j for j in js if w[j] is not None)
    return out


def _opcodes(d, w, i0=0, j0=0, i1=None, j1=None) -> list:
    """d[i0:i1] と w[j0:j1] の照合（difflib の opcodes。位置は d・w の上の位置）。

    w の None（行全体でしか一致させない行の文字）は、除いた文字の上で照合し（0.19.0 の列と同じ一致の塊になる）、結果を w の
    上の位置に戻す。None の文字は、隣の一致しない部分（replace・delete・insert）に入れ、一致した部分の間にあれば insert にする。
    None を w に残したまま照合すると、None の行が段落の一致の塊を 2 つに分け、窓の中のよく似た文字列（同じ著者・同じ年で書名の
    始まりが同じ文献など）のほうが長く続けて一致して、段落がそちらと並べられる（ルート2 で docx の文字を消す）。
    """
    i1 = len(d) if i1 is None else i1
    j1 = len(w) if j1 is None else j1
    core = [j for j in range(j0, j1) if w[j] is not None]
    blocks = []           # 一致した部分 [d の位置, w の位置, 長さ]（w の上で続いた部分ごとに分ける）
    for a, b, n in difflib.SequenceMatcher(None, d[i0:i1], [w[j] for j in core], autojunk=False).get_matching_blocks():
        for k in range(n):
            i, j = i0 + a + k, core[b + k]
            if blocks and blocks[-1][0] + blocks[-1][2] == i and blocks[-1][1] + blocks[-1][2] == j:
                blocks[-1][2] += 1
            else:
                blocks.append([i, j, 1])
    ops, i, j = [], i0, j0
    for bi, bj, n in blocks + [[i1, j1, 0]]:
        if bi > i or bj > j:
            ops.append(("replace" if bi > i and bj > j else "delete" if bi > i else "insert", i, bi, j, bj))
        if n:
            ops.append(("equal", bi, bi + n, bj, bj + n))
        i, j = bi + n, bj + n
    return ops


def _slide_inserts(ops, w, keys, st: PdfStream, win) -> list:
    """一致した部分の間の PDF にだけある文字（insert）を、同じ文字の並びの範囲でずらせるなら、行の境目から行の境目までにそろえる。

    difflib は同じ文字の並びのうち先にあるものと一致させるので、PDF の中で段落を分断する行（ページの最初の柱、docx にない図や
    表のキャプションなど）の最初の文字が、その次の本文の行の最初の文字と同じだと（柱「基づく架空の論文の柱です」と本文
    「基づく（試験…」、キャプション「表１…」と本文「表現を…」）、一致がその行の中まで伸びてその行が段落に当たる行になり、行の
    残りの文字と本文の文字を docx に足してしまう。insert の前後の一致を同じ文字の範囲で前か後ろにずらし、insert がちょうど
    行の境目から行の境目までになる位置があれば、いちばん近いその位置に移す。前後の一致は 1 文字以上残し、行全体でしか一致
    させない行の文字（w の None）は動かさない。
    """
    def edge(j):      # 窓の中の位置 j が行の境目（j の文字が行の最初の文字か、窓の終わり）か
        if j >= len(keys):
            return True
        k = win[j]
        return k == 0 or st.line[k] != st.line[win[j - 1] if j else k - 1]
    ops = list(ops)
    for x in range(1, len(ops) - 1):
        t, i1, _, j1, j2 = ops[x]
        pe, ne = ops[x - 1], ops[x + 1]
        if t != "insert" or pe[0] != "equal" or ne[0] != "equal" or (edge(j1) and edge(j2)):
            continue
        shifts = []
        k = 1               # 前へ k 文字（前の一致の最後の k 文字と、insert の最後の k 文字が同じ）
        while (k < pe[2] - pe[1] and keys[j1 - k] == keys[j2 - k]
               and w[j1 - k] is not None and w[j2 - k] is not None):
            shifts.append(-k)
            k += 1
        k = 1               # 後ろへ k 文字（insert の最初の k 文字と、後ろの一致の最初の k 文字が同じ）
        while (k < ne[2] - ne[1] and keys[j1 + k - 1] == keys[j2 + k - 1]
               and w[j1 + k - 1] is not None and w[j2 + k - 1] is not None):
            shifts.append(k)
            k += 1
        s = next((s for s in sorted(shifts, key=abs) if edge(j1 + s) and edge(j2 + s)), 0)
        if s:
            ops[x - 1] = ("equal", pe[1], pe[2] + s, pe[3], pe[4] + s)
            ops[x] = ("insert", i1 + s, i1 + s, j1 + s, j2 + s)
            ops[x + 1] = ("equal", ne[1] + s, ne[2], ne[3] + s, ne[4])
    return ops


def _whole_lines(ops, d, w, keys, st: PdfStream, win) -> list:
    """行全体でしか一致させない行（窓の中の w が None の文字。続いた行はまとめる）を、docx の文字がその行の文字とまったく
    同じに続くときだけ、行全体で一致（equal）にする。

    その行の直前の PDF の文字まで一致していて、docx の続きの文字がその行の文字とまったく同じで、さらに docx の段落がそこで
    終わるか、次の docx の文字がその行の次の PDF の文字と同じなら、その行を一致にして、後ろを照合し直す（引用文献の「p.」の
    改行の後の「16」、docx の表を本文に書いた段落の数字、引用文献の中の何ページにも出る行など）。その行のすぐ後ろから一致して
    いて、その前の docx の文字がその行の文字とまったく同じで、docx の段落がそこで始まるか、その前の docx の文字がその行の前の
    PDF の文字と同じときも同じ（前を照合し直す。段落の最初の行が、何ページにも出る表の見出しの行のときなど）。表のセルの「1」が、
    出版版で直された docx の「1回」（PDF では「２回」）の「1」と同じ文字でも、前後の文字が続かないので一致にしない。
    続いた行全体では一致しないとき、docx の段落がそこで終わる（始まる）なら、続いた行の最初（最後）の何行かだけでも一致にする
    （段落の最後の行「ことが明らかになった。」が何ページにも出る行としてページの最後にあり、次のページの最初の行が柱のときなど）。
    """
    runs = []
    j = 0
    while j < len(w):
        if w[j] is not None:
            j += 1
            continue
        k = j
        while k < len(w) and w[k] is None:
            k += 1
        a, b = win[j], win[k - 1]
        if (a == 0 or st.line[a - 1] != st.line[a]) and (b + 1 == len(st.chars) or st.line[b + 1] != st.line[b]) \
                and b - a == k - 1 - j:
            runs.append((j, k))           # 行の途中で窓が切れていないものだけ
        j = k
    done = 0                              # ops[:done] は決まったもの（それより前は照合し直さない）
    for a, b in runs:
        n, text = b - a, "".join(keys[a:b])
        i0, j0 = (ops[done - 1][2], ops[done - 1][4]) if done else (0, 0)
        if a < j0:
            continue
        cuts = [x for x in range(a + 1, b) if st.line[win[x]] != st.line[win[x - 1]]]    # 続いた行の、2 行目以降の始まり
        at = next((x for x in range(done, len(ops)) if ops[x][0] == "equal" and ops[x][4] == a), None)
        if at is not None:                # 一致した文字に続く行
            i = ops[at][2]
            if d[i:i + n] == text and (i + n == len(d) or (b < len(w) and w[b] is not None and d[i + n] == w[b])):
                ops = ops[:at + 1] + [("equal", i, i + n, a, b)] + _opcodes(d, w, i + n, b)
                done = at + 2
                continue
            # 続いた行の最初の何行かで、docx の段落が終わる
            c = next((c for c in reversed(cuts) if i + c - a == len(d) and d[i:] == "".join(keys[a:c])), None)
            if c is not None:
                ops = ops[:at + 1] + [("equal", i, len(d), a, c)] + _opcodes(d, w, len(d), c)
                done = at + 2
                continue
        at = next((x for x in range(done, len(ops)) if ops[x][0] == "equal" and ops[x][3] == b), None)
        if at is not None:                # 一致した文字の前の行
            i = ops[at][1]
            # 続いた行全体か、続いた行の最後の何行かで、docx の段落が始まる
            c = a if i - n >= i0 and d[i - n:i] == text and (
                i - n == 0 or (a > j0 and w[a - 1] is not None and d[i - n - 1] == w[a - 1])) else next(
                (c for c in cuts if i0 == 0 and i == b - c and d[:i] == "".join(keys[c:b])), None)
            if c is not None:
                mid = _opcodes(d, w, i0, j0, i - (b - c), c)
                ops = ops[:done] + mid + [("equal", i - (b - c), i, c, b)] + ops[at:]
                done += len(mid) + 1
    out = []
    for tag, i1, i2, j1, j2 in ops:       # 続いた一致はまとめる
        if tag == "equal" and out and out[-1][0] == "equal" and out[-1][2] == i1 and out[-1][4] == j1:
            _, i1, _, j1, _ = out.pop()
        out.append((tag, i1, i2, j1, j2))
    return out


SHORT_LINE = 0.6   # 段落の行のいちばん長い行の幅に対する、短い行（段落の最後の行・ほかのものの最後の行）の幅の割合の上限
# 段落の行のいちばん長い行の幅に対する、段落の行の幅いっぱいとみなす行の幅の割合（段落の本体から離れた最初・最後の部分を
# 決めるとき。_isolate）。両端そろえの段落の行は行の幅いっぱいになるので、これより短く文の終わりで終わる行で段落の本文の行の
# 流れが終わり（_ends_flow）、これより短く文の終わりで終わらない行は図・表の中の行かもしれない（_figure_line）。これ以上の幅の、
# どの段落にも当たらない行は、校正で足された文の行かもしれないので流れを切らない（_flow_breaks）
FULL_LINE = 0.9


def _line_width(line: str) -> float:
    """行の文字列の、目に見える幅（全角の文字を 1、半角の文字を 0.5 とする）。"""
    return sum(1 if unicodedata.east_asian_width(c) in "FWA" else 0.5 for c in line)


def _mostly_wide(s: str) -> bool:
    """文字列 s の文字の半分以上が、全角の文字（和文の文字など）か。和文の文字が半分に満たない行（英文・数式など）は、文字の数で
    行の幅を測ると誤差が大きいので、行の幅で本文の行を見分けない（_ends_flow・_figure_line など）。"""
    return sum(1 for c in s if unicodedata.east_asian_width(c) in "FWA") * 2 >= len(s)


def _shown_width(st: PdfStream, ln) -> float:
    """PDF の行 ln の目に見える幅。行の最初の字下げの全角の空白（PdfStream.line_indent。lines からは除いてある）も数える
    （段落の 1 行目を、ほかの行より 1 文字短く測らないように。本文の行の流れを行の幅で見分けるとき〈_isolate〉に使う）。"""
    return _line_width(st.lines[ln]) + (1 if st.line_indent[ln] else 0)


def _body_text(st: PdfStream, ln):
    """PDF の行 ln の文字（受付日の文字と行末のハイフンを除いたもの）と、受付日の文字を除いた行の幅（_shown_width。pdfium は、
    段の下の受付日を本文の行につなげることがある）。"""
    ks = st.line_range(ln)
    text = "".join(st.chars[k] for k in ks if st.date[k] < 0 and not st.soft[k])
    return text, _shown_width(st, ln) - _line_width("".join(st.chars[k] for k in ks if st.date[k] >= 0))


def _flow_breaks(src, ka, kb, st: PdfStream, owner, width, figure=None, capped=None) -> int:
    """_isolate: 段落 src の照合で一致した、PDF の列の位置 ka の文字から、次に一致した kb の文字へ、本文の行の流れが切れるか
    （0: 切れない、1: 切れる、2: 切れる〈間の飛ばした行の向こうがキャプションのすぐ隣。本体から離れた部分を _solid で本体に
    入れない〉）。

    切れるのは、PDF の中の順が docx の順と逆のとき、ka と kb の行が違い、ka の行が段落の終わりの行（_ends_flow）か、字下げの
    ない ka の行から段落の 1 行目（字下げの全角の空白で始まる行。PdfStream.line_indent）の kb の行へ移るか（字下げの行から字下げの
    行へは、docx の段落の中の全角の空白が行の最初に来たのかもしれないので切らない）、どちらかの行が図・表の中の行かもしれない行
    （figure。_figure_line）のときと、間に、ほかの段落に当たった文字か、どの段落にも当たらない行（図・表の中の文字・キャプション
    など）があるとき。ka・kb の行の中の、どの段落にも当たらない文字（校正の直し）と、間の次の行では切らない: 受付日の行・ページの
    最初の端の柱の候補の行（ページの区切りの組版の文字）、ページの最後の端の行、MIN_CHARS 文字未満の行（図の目盛りの数字・矢印
    など。段落の文字の代わりにならない）、段落の行の幅 width の FULL_LINE 以上の行（校正で足された文の行かもしれない）。
    ただし、間に飛ばした行が、図の中の文字かもしれない行（ページの最後の端の行・短い行・幅いっぱいの行。ページの最初の端の行と
    受付日の文字は組版の文字なので数えない）で、着く側の行 lb（戻る側の行 la）のすぐ隣が図・表のキャプションなど（本文の流れで
    ない段落の行。capped）なら切る（2）: 図の中の文字とキャプションの間に本当の段落の行は出ないので、lb（la）の行は、段落の文字と
    よく似た図の中の行かもしれない（消された最後の文の写しにごく近い図の中の行が、短い行だけの流れ図をはさんでキャプションの直前に
    ある形。写しが行の幅いっぱいで _solid でも、本体に入れない）。"""
    if kb <= ka:
        return 1
    la, lb = st.line[ka], st.line[kb]
    if kb == ka + 1 and la == lb:
        return 0
    if la != lb and (_ends_flow(st, la, width) or (st.line_indent[lb] and not st.line_indent[la]) or
                     (figure is not None and (figure(la) or figure(lb)))):
        return 1
    full = {}                            # 間の行の番号 -> 段落の行の幅いっぱいの行か
    skipped = False                      # 間に、図の中の文字かもしれない行（ページの最後の端の行・短い行・幅いっぱいの行）を飛ばしたか
    for k in range(ka + 1, kb):
        o = owner.get(k)
        if o == src or st.soft[k]:
            continue
        if o is not None:
            return 1                     # ほかの段落に当たった文字
        ln = st.line[k]
        if ln in (la, lb) or st.date[k] >= 0 or (st.edge[k] and st.head[k] and st.top[k]):
            continue                     # ka・kb の行の文字、受付日の文字、ページの最初の端の柱の候補の行の文字
        if st.edge[k] and st.head[k]:
            skipped = True
            continue                     # ページの最後の端の行の文字（柱の位置でない。図の中の文字かもしれない）
        if 0 < _visible_count(st.lines[ln]) < MIN_CHARS:
            skipped = True
            continue                     # 目に見えて短い行（図の目盛りの数字・矢印・点の名前など）
        if width:
            if ln not in full:
                full[ln] = _shown_width(st, ln) >= FULL_LINE * width
            if full[ln]:
                skipped = True
                continue                 # 段落の行の幅いっぱいの行（校正で足された文の行かもしれない）
        return 1
    if skipped and capped is not None and (capped(lb, 1) or capped(la, -1)):
        return 2                         # 飛ばした行が図の中の文字で、着く側（戻る側）の行がキャプションのすぐ隣
    return 0


def _ends_flow(st: PdfStream, ln, width) -> bool:
    """PDF の行 ln で、段落の本文の行の流れが終わるか（段落の終わりの行か）。段落の行は両端そろえで行の幅いっぱいになるので、
    段落の行の幅 width の FULL_LINE より短く、文の終わりで終わる和文の行で段落が終わる。"""
    if not width:
        return False
    text, w = _body_text(st, ln)
    return bool(text) and _mostly_wide(text) and w < FULL_LINE * width and _ends_sentence(text)


def _isolate(src, seq, win, ops, st: PdfStream, owner, width, doubt=(), nonflow=frozenset()):
    """本文の流れの段落 src の照合（ops）で一致した文字の、本体と、本体から離れた最初・最後の部分（離れた部分の違いは、全角・
    半角なども含めて直さない。FAR_WHY。_classify）。

    一致した文字を、本文の行の流れが切れるところ（_flow_breaks。図・表の中の行かもしれない行〈_figure_line〉の前後も）で分け、
    いちばん多くの文字が一致した部分から、その前後の、本文の行のある部分（_solid）のいちばん遠いものまで（間の、本文の行のない
    部分〈別行立ての式の前の短い行など〉も）を本体にする（図・表は本文の行の流れの外に置かれるので、図・表をはさんでいても、本文の
    行のある部分は段落の本文の続き）。ただし、間の飛ばした行の向こうがキャプションのすぐ隣で切れたところ（_flow_breaks の 2）の
    向こうの部分は、本文の行があっても本体に入れない（図の中の文字とキャプションの間に出た、段落の文字とよく似た行の幅いっぱいの
    図の中の行かもしれない）。一致がどれもキャプション・表のセルなど（本文の流れでない段落）の文字のある行にある部分の向こうの
    部分も、本文の行があっても本体に入れない（キャプション・セルの行は段落の本文の行でないので、その一致は偶然の一致〈docx の
    「12点」の「1」と、表のキャプション「表１」の「１」など〉で、そのすぐ隣の違いは段落の続きの違いか決められない。表の後ろの
    続きの行に行の幅いっぱいの行があると、本体に入れて「2」を「13」に直し、キャプションの「１」と並べた「1」を残して「113点」に
    していた。0.20.0 から）。本体の最後（最初）の行のすぐ向こうが図・表のキャプションなどで、その向こうに段落の最後
    （最初）の行らしい、どの段落にも当たらない行があれば（_edge_alternative）、本体のその行は、段落の文字とよく似た図の中の語句の
    行で、本当の段落の行はキャプションの向こうかもしれないので、本体から外す。
    width: 段落の行の幅（0 なら行の幅で見分けない）。doubt: 図の中の文字に挟まれた、分断された部分の行（図の中の原稿の写しかも
    しれないので、本文の行とみなさない）。nonflow: 本文の流れでない段落（図・表のキャプション・表のセルなど）の ID の集合。
    戻り値: (b, e, head_far, tail_far)。b・e: 本体の docx の範囲（seq の [b, e)。離れた最初〈最後〉の部分がなければ 0〈len(seq)〉）。
    head_far・tail_far: 離れた最初（最後）の部分があれば、(本体の最初〈最後〉の行, その部分の行の集合)、なければ None。"""
    pairs = [(i1 + k, win[j1 + k]) for tag, i1, i2, j1, j2 in ops if tag == "equal" for k in range(i2 - i1)]
    if not pairs:
        return 0, len(seq), None, None
    figures = {}                         # 行の番号 -> 図・表の中の行かもしれないか（_figure_line）

    def figure(ln):
        if ln not in figures:
            figures[ln] = _figure_line(st, ln, owner, nonflow, width)
        return figures[ln]

    def capped(ln, step):                # 行 ln のすぐ向こう（_line_kind が "skip" の行は飛ばす）が、キャプションなど（nonflow）の行か
        x = ln + step
        for _ in range(6):
            if not 0 <= x < len(st.lines):
                return False
            if _line_kind(st, x, owner, nonflow) != "skip":
                return bool(_line_owners(st, x, owner) & nonflow)
            x += step
        return False
    segs = [[pairs[0]]]                  # 本文の行の流れが続く部分（(seq の位置, 列の位置) のリスト）の並び
    capped_breaks = []                   # segs の境目ごとに、飛ばした行の向こうがキャプションのすぐ隣で切った（_flow_breaks の 2）か
    for x, y in zip(pairs, pairs[1:]):
        brk = _flow_breaks(src, x[1], y[1], st, owner, width, figure, capped)
        if brk:
            segs.append([])
            capped_breaks.append(brk == 2)
        segs[-1].append(y)
    m = max(range(len(segs)), key=lambda x: len(segs[x]))

    def caption_part(y):                 # 部分 y の一致がどれも、キャプション・表のセルなど（nonflow）の文字のある行にあるか
        return all(_line_owners(st, ln, owner) & nonflow for ln in {st.line[k] for _, k in segs[y]})

    def beyond_cap(x):                   # 部分 x と、いちばん多くの文字が一致した部分 m の間に、キャプションの隣で切った境目か、
        # 一致がどれもキャプション・表のセルなどの行にある部分があるか（x は本体に入れない）
        if any(capped_breaks[y] for y in (range(x, m) if x < m else range(m, x))):
            return True
        return any(caption_part(y) for y in (range(x + 1, m) if x < m else range(m + 1, x)))
    solid = [x for x in range(len(segs)) if x != m and not beyond_cap(x) and _solid(segs[x], st, width, doubt)]
    lo, hi = min([m, *solid]), max([m, *solid])
    # 本体の最後の行が、段落の文字とよく似た図の中の語句の行かもしれない: その行から後ろを本体から外す（その行だけの部分なら、
    # 本体はその前の部分まで）
    ln = st.line[segs[hi][-1][1]]
    if _edge_alternative(st, ln, 1, owner, nonflow, src, width):
        cut = next(x for x, (_, k) in enumerate(segs[hi]) if st.line[k] == ln)
        if cut:
            segs[hi:hi + 1] = [segs[hi][:cut], segs[hi][cut:]]
        elif hi > lo:
            hi -= 1
    # 本体の最初の行も同じ
    ln = st.line[segs[lo][0][1]]
    if _edge_alternative(st, ln, -1, owner, nonflow, src, width):
        cut = max(x for x, (_, k) in enumerate(segs[lo]) if st.line[k] == ln) + 1
        if cut < len(segs[lo]):
            segs[lo:lo + 1] = [segs[lo][:cut], segs[lo][cut:]]
            lo += 1
            hi += 1
        elif lo < hi:
            lo += 1
    main_lines = {st.line[k] for s in segs[lo:hi + 1] for _, k in s}
    head_far = tail_far = None
    if lo > 0:
        head_far = (st.line[segs[lo][0][1]], {st.line[k] for s in segs[:lo] for _, k in s} - main_lines)
    if hi + 1 < len(segs):
        tail_far = (st.line[segs[hi][-1][1]], {st.line[k] for s in segs[hi + 1:] for _, k in s} - main_lines)
    b = segs[lo][0][0] if lo > 0 else 0
    e = segs[hi][-1][0] + 1 if hi + 1 < len(segs) else len(seq)
    return b, e, head_far, tail_far


def _line_kind(st: PdfStream, ln, owner, nonflow) -> str:
    """PDF の行 ln の種類（_figure_line・_edge_alternative）。"figure": 本文の流れでない段落（図・表のキャプション・表のセルなど）
    の文字のある行か、どの段落にも当たらない和文の行（図・表の中の文字）。"text": 本文の流れの段落の文字があり、本文の流れでない
    段落の文字のない行。"skip": 受付日の文字だけの行と、どの段落にも当たらない、ページの端の柱の候補の行・MIN_CHARS 文字未満の
    行・全角の文字のない行（数式・数字だけの行など）。"""
    body = [k for k in st.line_range(ln) if not st.soft[k] and st.date[k] < 0]
    if not body:
        return "skip"
    owners = {owner.get(k) for k in body} - {None}
    if owners & nonflow:
        return "figure"
    if owners:
        return "text"
    if (st.edge[body[0]] and st.head[body[0]]) or _visible_count(st.lines[ln]) < MIN_CHARS or \
            not any(unicodedata.east_asian_width(st.chars[k]) in "FW" for k in body):
        return "skip"
    return "figure"


def _edge_alternative(st: PdfStream, ln, step, owner, nonflow, src, width) -> bool:
    """_isolate: 段落 src の本体の最後（step = 1。-1 なら最初）の行 ln のすぐ後ろ（前）が、図・表のキャプションなど（本文の流れで
    ない段落の文字の行。間の、_line_kind が "skip" の行は飛ばす）で、その向こうの、次（前）の本文の段落の行より手前（80 行まで）
    に、段落の最後（最初）の行らしい、どの段落にも当たらない和文の行（最後なら文の終わりで終わる行、最初なら段落の行の幅
    いっぱいの行。受付日の文字だけの行・ページの端の柱の候補の行・MIN_CHARS 文字未満の行を除く）があるか。"""
    if not width:
        return False
    x, sep = ln + step, False            # sep: キャプションなどの行を越えたか
    for _ in range(80):
        if not 0 <= x < len(st.lines):
            return False
        body = [k for k in st.line_range(x) if not st.soft[k] and st.date[k] < 0]
        owners = {owner.get(k) for k in body} - {None}
        if owners & nonflow:
            sep = True
        elif owners - {src}:
            return False                 # 次（前）の本文の段落の行
        elif not sep:
            if owners or _line_kind(st, x, owner, nonflow) != "skip":
                return False             # 本体の端の行のすぐ向こうが、キャプションなどでない
        elif body and not owners and not (st.edge[body[0]] and st.head[body[0]]) and \
                _visible_count(st.lines[x]) >= MIN_CHARS:
            s = "".join(st.chars[k] for k in body)
            if _mostly_wide(s) and (_ends_sentence(s) if step > 0 else _shown_width(st, x) >= FULL_LINE * width):
                return True
        x += step
    return False


def _figure_line(st: PdfStream, ln, owner, nonflow, width) -> bool:
    """_isolate: PDF の行 ln が、段落の本文の行でなく、図・表の中の行かもしれないか（その行の一致は、前後の行と本文の行の流れで
    続けない）。段落の行は両端そろえで行の幅いっぱいになり、段落の最後の行は文の終わりで終わるので、段落の行の幅 width の
    FULL_LINE より短く、文の終わりで終わらない和文の行は本文の行らしくない（図の中の語句「時間を見る」が、段落の続きの docx の
    文字「時間を取った。」と最初の数文字が同じだと、照合はその行を段落の行と並べる）。そのような行で、すぐ前かすぐ後ろの行
    （_line_kind が "skip" の行は 5 行まで飛ばす）が、図・表のキャプションなどの行か、どの段落にも当たらない和文の行のもの。"""
    if not width:
        return False
    text, w = _body_text(st, ln)
    if not text or not _mostly_wide(text) or w >= FULL_LINE * width or _ends_sentence(text):
        return False
    for step in (-1, 1):
        x = ln + step
        for _ in range(6):
            if not 0 <= x < len(st.lines):
                break
            kind = _line_kind(st, x, owner, nonflow)
            if kind == "figure":
                return True
            if kind == "text":
                break
            x += step
    return False


def _solid(seg, st: PdfStream, width, doubt=()) -> bool:
    """_isolate: 一致した文字の部分 seg（(seq の位置, 列の位置) のリスト）に、本文の行（段落の行の幅 width の FULL_LINE 以上の
    行で、行の文字〈受付日の文字・行末のハイフンを除く〉の半分以上が seg の文字のもの）があるか。図の中の文字に挟まれた行
    （doubt）が 1 つでもあれば、ないとみなす。"""
    if not width:
        return False
    cnt = Counter(st.line[k] for _, k in seg)
    if any(ln in doubt for ln in cnt):
        return False
    for ln, n in cnt.items():
        size = sum(1 for k in st.line_range(ln) if not st.soft[k] and st.date[k] < 0)
        if 2 * n >= size and _shown_width(st, ln) >= FULL_LINE * width:
            return True
    return False


def _line_owners(st: PdfStream, ln, owner) -> set:
    """PDF の行 ln の文字（受付日の文字・行末のハイフンを除く）が当たった段落 ID の集合。"""
    return {owner[k] for k in st.line_range(ln) if k in owner and not st.soft[k] and st.date[k] < 0}


def _typeset_line(st: PdfStream, ln, owner) -> bool:
    """_plain_tail: PDF の行 ln が、組版の文字だけの行（文字のない行・受付日の文字だけの行・ページの最初の端の柱の候補の行で、
    どの段落にも当たらないもの）か。ページの最後の端の行は柱の位置でないので、組版の文字とみなさない（図・表の中の文字や
    キャプション、本当の段落の最後の行かもしれない）。"""
    return all(st.date[k] >= 0 or (st.top[k] and st.head[k] and k not in owner)
               for k in st.line_range(ln) if not st.soft[k])


def _plain_tail(src, seq, fe, tail_far, st: PdfStream, owner, nonflow, width, doubt=()) -> bool:
    """段落 src の本体から離れた最後の部分（_isolate の tail_far。docx の seq[fe:]）が、PDF の中で図・表・キャプション・ほかの
    段落に押し出された段落の続きで、ほかの説明がないか（そうなら、その部分の違いも本体と同じに直す。_classify）。次のすべての
    とき。

      ・本体の最後の行が、段落の終わりの行でない（段落はその先へ続く。_ends_flow）
      ・離れた部分の行が、どれも本体の最後の行より後ろにあり、図の中の文字に挟まれた行（doubt）でも、図・表のキャプション・表の
        セルなど（本文の流れでない段落 nonflow）の文字のある行でもない（キャプション・セルの行は段落の本文の行でない。_isolate の
        キャプション・セルの行だけの部分と同じ。キャプションの番号「表１」だけの行の「１」が docx の「12点」の「1」と偶然一致すると、
        行の文字の半分が段落の文字になり、下の条件を通る）
      ・離れた部分の最後の行のすぐ後ろ（組版の文字だけの行〈_typeset_line〉は飛ばす）が、ほかの本文の流れの段落の行か、PDF の
        文字の終わり（押し出された段落の続きは、押し出した図・表などと次の段落の間に出る）
      ・離れた部分の行のそれぞれで、段落の文字と一致した文字が、行の文字（受付日の文字を除く）の半分以上（校正で大きく直された
        行・図の中の行・キャプションでない）
      ・離れた部分の PDF の文字が、docx のその部分の文字とよく並び（最長共通部分列が長いほうの 0.6 以上）、docx が文の終わりで
        終わるなら、その部分の最後の行も文の終わりで終わる
      ・本体の最後の行から離れた部分の最後の行までの、離れた部分でも組版の文字だけでもなく、本文の流れの段落の文字もない行
        （図・表の中の文字・キャプション・セル）に、docx のその部分の文字と、離れた部分の半分以上（4 文字以上）並ぶ行がない
        （その行が、本当の段落の続きかもしれない）"""
    body_ln, far = tail_far
    lines = sorted(far)
    if not lines or not width or lines[0] <= body_ln or any(ln in doubt or _line_owners(st, ln, owner) & nonflow for ln in lines) or \
            _ends_flow(st, body_ln, width):
        return False
    x = lines[-1] + 1
    while x < len(st.lines) and _typeset_line(st, x, owner):
        x += 1
    if x < len(st.lines):
        nxt = _line_owners(st, x, owner) - {src}
        if not nxt or nxt & nonflow:
            return False
    D = [key(c) for c, _ in seq[fe:] if c != SKIP]          # docx のその部分の文字
    if not D:
        return False
    Z, last = [], ""                     # 離れた部分の行の、この段落の文字とどの段落にも当たらない文字（key）と、最後の行のその文字
    for ln in lines:
        body = [k for k in st.line_range(ln) if not st.soft[k] and st.date[k] < 0]
        t = [k for k in body if owner.get(k, src) == src]
        if not t or 2 * sum(1 for k in t if k in owner) < len(body):
            return False                 # 段落の文字との一致が、行の半分に満たない
        Z += [key(st.chars[k]) for k in t]
        last = "".join(st.chars[k] for k in t)
    common = _lcs_prefix(D, Z)[-1]
    if common < 0.6 * max(len(D), len(Z)) or (_ends_sentence("".join(D)) and not _ends_sentence(last)):
        return False
    for ln in range(body_ln + 1, lines[-1]):
        if ln in far or _typeset_line(st, ln, owner) or (_line_owners(st, ln, owner) - nonflow):
            continue
        t = [key(st.chars[k]) for k in st.line_range(ln) if not st.soft[k] and st.date[k] < 0]
        if t and _lcs_prefix(D, t)[-1] >= max(4, 0.5 * common):
            return False
    return True


def _classify(p, seq, gens, win, ops, unsure, st: PdfStream, owner, owned_lines, res: PdfCheck, dense_lines,
              beside=((), ()), heading=False, nonflow=frozenset(), doc_width=0):
    """段落の照合（_align の opcodes。PDF の側の位置は窓 win の上の位置）の違う部分を、全角・半角の違い（res.width・drops）、
    Word が付ける番号の違い（res.numbers）、それ以外の違い（res.diffs。直せる違いと、直さない違い〈TextDiff.why〉）に分ける。

    unsure: まとめての照合（_joint）が付けた段落の印。owner・owned_lines: どれかの段落に当たった PDF の文字の位置と行。
    dense_lines: どれかの段落の文字が多く当たった行（どの段落の文字とも一致しない行かを見るときに使う。compare）。
    beside: docx で段落のすぐ前・すぐ後ろにある、照合しない短い段落（MIN_CHARS 文字未満）の文字（key）のリスト。
    heading: 題目・見出しの段落か（文の終わりで終わらないのがふつうなので、段落の最後の後ろの行を文の続きとみなさない）。
    doc_width: 文書の本文の行の幅（_document_width。0 なら使わない）。段落がその幅で組まれているとき、本体を見分けるときの
    段落の行の幅の上限。
    戻り値: 段落の最後に一致した文字の行が目に見えて短いか（段落はその行で終わっている。compare の手順 4 で使う）。
    """
    text = p.plain()
    locked = _locked_positions(p)
    d2w = {}          # seq の位置 -> PDF の文字の位置
    width = {}        # seq の位置 -> PDF の文字（全角・半角だけの違い）
    numbers = set()   # PDF に合わせた Word の番号の文字の seq の位置
    regions = []      # 違う部分 (i1, i2, j1, j2, 直せない理由)（seq と窓の中の位置）
    forced = {}       # 窓の中の位置 -> 直す（表示する）ときに使う PDF の文字（docx のダッシュと同じ位置の、PDF の行末の「-」）

    eq = [(j1, j2) for tag, _, _, j1, j2 in ops if tag == "equal"]
    first_eq, last_eq = eq[0][0], eq[-1][1] - 1      # 窓の中で最初・最後に一致した PDF の文字

    def weak(a, b):   # 窓の中の一致 a..b が、1 つの行の中だけの ISLAND 文字以下で、ほかにも一致があるか
        return len(eq) > 1 and b - a <= ISLAND and len({st.line[win[j]] for j in range(a, b)}) == 1
    weak_start, weak_end = weak(*eq[0]), weak(*eq[-1])
    weak_hit = set()  # その外側の違いを EDGE_WHY にした端（"start"・"end"）
    own_lines = {st.line[win[j]] for j1, j2 in eq for j in range(j1, j2)}     # この段落の文字が一致した行
    # 段落の最初に一致した文字の行のすぐ前の行（ページの端の行は飛ばす）が、段落のいちばん長い行より目に見えて短い
    # （SHORT_LINE）なら、その行はほかのもの〈図の中の「A」、表のセル、キャプションなど〉の最後の行で、段落はその次の行から
    # 始まっている。段落の行が 2 行以上で、最後に一致した文字の行が目に見えて短いなら、段落はその行で終わっている。
    # どちらも、最初（最後）に一致した文字の行が段落の行だと確かめられる（窓の中のその行の文字の半分以上がこの段落の文字と
    # 一致する〈solid〉か、最初〈最後〉の一致が次〈前〉の行から続いている）ときだけ。段落の行の幅は、solid の行で測る（図の
    # 中の文字と偶然一致した行で測らない）
    on_line, eq_line = Counter(st.line[k] for k in win), Counter(st.line[win[j]] for j1, j2 in eq for j in range(j1, j2))
    solid = {ln for ln, n in eq_line.items() if 2 * n >= on_line[ln]}
    own_width = max((_line_width(st.lines[ln]) for ln in solid), default=0)
    first_ln, last_ln = st.line[win[first_eq]], st.line[win[last_eq]]
    first_sure = first_ln in solid or st.line[win[eq[0][1] - 1]] != first_ln
    last_sure = last_ln in solid or st.line[win[eq[-1][0]]] != last_ln
    k = win[first_eq] - 1
    while k >= 0 and (st.line[k] == first_ln or st.edge[k]):
        k -= 1
    head_short = first_sure and k >= 0 and _line_width(st.lines[st.line[k]]) < SHORT_LINE * own_width
    tail_short = last_sure and bool(solid - {last_ln}) and _line_width(st.lines[last_ln]) < SHORT_LINE * own_width

    floaty = {j for j, k in enumerate(win) if k in unsure["floaty"]}   # 分断する表・図の中の文字とみなす位置（_joint）
    # 段落の本体から離れた最初・最後の部分（_isolate。その違いは直さない。FAR_WHY）: docx の seq の [0, fb) と [fe, len(seq))、
    # PDF の、本体の最初の行より前・最後の行より後ろと、その部分の行。離れた最後の部分が、図・表などに押し出された段落の続きで、
    # ほかの説明がなければ、本体と同じに直す（_plain_tail）。題目・見出しの行は、行の幅いっぱいにも文の終わりで終わるようにも
    # 組まれないので、行の幅で本文の行を見分けない（width 0）。段落が文書の本文の行の幅（doc_width。_document_width）で組まれて
    # いれば、段落の行の幅はその幅を上限にする（1 行だけ約物の詰めなどで幅が大きく出ても、幅いっぱいのふつうの行を本文の行と
    # 認めるように）。その幅で組まれているとみなすのは、段落の照合に使った行（solid）のうち、PDF の中でいちばん後ろの行（段落の
    # 最後の行か、そのすぐ後ろの、段落の文字とよく似た図の中の行。段落の途中の行と違って幅いっぱいとは限らない）を除いた、その幅の
    # FULL_LINE 以上の行（その幅で組まれていれば幅いっぱいの行）の半分より多くが、その幅 + 1 を超えないとき。そうでなければ
    # （ほかの幅で組まれた段落、短い本文の段落ばかりの小さな文書で文書の本文の行の幅が短い行の幅になったとき、行の少ない段落で
    # 決められないとき）、上限にしない（決められないときは、離れた部分を直さない側に倒す）
    if doc_width:
        full = [w for w in (_shown_width(st, ln) for ln in sorted(solid)[:-1]) if w >= FULL_LINE * doc_width]
        if 2 * sum(1 for w in full if round(w) <= doc_width + 1) <= len(full):
            doc_width = 0
    flow_width = 0 if heading else min(own_width, doc_width) if doc_width else own_width
    fb, fe, head_far, tail_far = _isolate(p.src, seq, win, ops, st, owner, flow_width, unsure["doubt"], nonflow) \
        if unsure["flow"] else (0, len(seq), None, None)
    if tail_far and _plain_tail(p.src, seq, fe, tail_far, st, owner, nonflow, flow_width, unsure["doubt"]):
        fe, tail_far = len(seq), None
    # 本体の docx の文字（seq の [fb, fe)）と一致した PDF の文字の行。2 段組みの読み順のずれで本体の一部が PDF の中で前後逆の
    # 位置にあっても（_isolate は本体に入れる）、その行の違いを離れた部分の側とみなさない
    body_lines = {st.line[win[j1 + k]] for tag, i1, i2, j1, j2 in ops if tag == "equal" for k in range(i2 - i1)
                  if fb <= i1 + k < fe}

    def far_pos(j):   # 窓の中の位置 j の PDF の文字が、本体から離れた部分の側の行（本体の文字の行でない）にあるか
        ln = st.line[win[j]]
        return ln not in body_lines and bool((head_far and (ln < head_far[0] or ln in head_far[1])) or
                                             (tail_far and (ln > tail_far[0] or ln in tail_far[1])))

    def far_docx(i1, i2):   # docx の seq[i1:i2]（i1 == i2 なら、その位置に足す文字）が、本体から離れた部分にかかるか
        return bool((head_far and (i1 < fb or i1 == i2 == fb)) or (tail_far and (i2 > fe or i1 == i2 == fe)))

    def mine(j):      # PDF の文字が、ほかの段落に当たっていない（この段落の違いとして扱ってよい）か
        return owner.get(win[j], p.src) == p.src and not st.soft[win[j]]

    def brk(x):       # 窓の中の位置 x - 1 と x の文字の間で、PDF の行が変わるか
        return st.line[win[x]] != st.line[win[x - 1]]

    stray = set()     # 窓の中の位置: 照合に使わない文字の間にある、どの段落の文字とも一致しない行の文字で、照合に使わないもの

    def used(j):      # mine で、照合に使わない文字（どの段落にも当たらない柱の候補の行・投稿受付日など）でもないか
        return mine(j) and not st.ignored(win[j], owner, owned_lines) and j not in stray and j not in floaty

    def formula_near(i1, i2, js, j):
        """違う部分（docx の seq[i1:i2] と、PDF の窓の中の位置 js。js が空なら、窓の中の位置 j の前）の PDF の文字の間か両隣に、
        文字として取り出せない数式の位置（PdfStream.formula）があるか。docx のその位置（と前後の空白）に全角の空白があれば、
        PDF の空白の並びはその空白かもしれないので見ない。"""
        a = next((seq[i][1] + 1 for i in range(i1 - 1, -1, -1) if seq[i][1] >= 0), 0)
        b = next((seq[i][1] for i in range(i2, len(seq)) if seq[i][1] >= 0), len(text))
        if "　" in text[a:b]:
            return False
        if not js:
            return 0 < j < len(win) and win[j] == win[j - 1] + 1 and bool(st.formula[win[j]])
        ks = [win[js[0]]] + [win[y] for x, y in zip(js, js[1:]) if win[y] == win[x] + 1]
        if win[js[-1]] + 1 < len(st.chars):
            ks.append(win[js[-1]] + 1)
        return any(st.formula[k] for k in ks)

    tail = _docx_tail(seq, gens)      # docx の段落の最後の数文字

    def end_row(cut):
        """段落の最後に一致した文字の行より後ろの、この段落の窓の PDF の文字 cut（窓の中の位置）のうち、すぐ後ろの行の文字
        （その行のどの文字もどの段落にも当たらず、受付日でもなく、行が文の終わりで終わるもの。段落の最後の行が目に見えて短い
        ときと、docx の段落が文の終わりで終わるときは空）。校正で段落の最後に足された文字が、次の行だけに出たものかもしれない
        （行の幅いっぱいの最後の行の次の「。」だけの行、英文の最後の 1 語だけのページの最後の行など）。"""
        if not cut or heading or tail_short or _ends_sentence(tail):
            return []
        ln = st.line[win[cut[0]]]
        row = [j for j in cut if st.line[win[j]] == ln]
        k0, k1 = win[row[0]], win[row[-1]]
        while k0 > 0 and st.line[k0 - 1] == ln:
            k0 -= 1
        while k1 + 1 < len(st.chars) and st.line[k1 + 1] == ln:
            k1 += 1
        if k0 == 0 or st.line[k0 - 1] != last_ln:
            return []                 # 段落の最後の行のすぐ後ろの行でない（間に、ほかの文字のある行がある）
        here = {win[j] for j in row}
        if any(k in owner or st.date[k] >= 0 or (k not in here and not st.soft[k]) for k in range(k0, k1 + 1)):
            return []
        return row if _ends_sentence(st.lines[ln]) else []

    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i2 - i1):
                dc = seq[i1 + k][0]
                pc = st.chars[win[j1 + k]]
                d2w[i1 + k] = win[j1 + k]
                if k and win[j1 + k] == win[j1 + k - 1] + 1 and st.formula[win[j1 + k]] and \
                        seq[i1 + k - 1][1] >= 0 and seq[i1 + k][1] == seq[i1 + k - 1][1] + 1:
                    # docx では続いている 2 文字の間に、PDF では文字として取り出せない数式がある（校正で数式だけが足された）:
                    # 文字の違いはないが、XML の本文は PDF と違う。docx に数式を足すことはできないので、直さない違いにする
                    regions.append((i1 + k, i1 + k, j1 + k, j1 + k, MATH_WHY))
                if dc == pc:
                    continue
                # 段落の本体から離れた最初・最後の部分（_isolate。FAR_WHY）と、分断する表・図の中の文字とみなした位置（floaty。
                # DISPLACED_WHY）の PDF の文字と並べた docx の文字は、全角・半角・大文字・小文字・行末のダッシュの違いも図の中の
                # 文字に合わせず、直さない違いにする（本文の最後の行「時間を２回取った。」がキャプションの後ろに出て、その前の図の
                # 中の行「時間を2回見る」と並べたとき、「２」を「2」にしない）。図の中の原稿の写しかもしれない行（recheck_runs・
                # find_hole の doubt）は、本当に分断された段落の部分のこともあるので、本体の中なら今までどおり合わせる
                far = far_docx(i1 + k, i1 + k + 1) or far_pos(j1 + k)
                fig = far or j1 + k in floaty
                why = FAR_WHY if far else DISPLACED_WHY if fig else ""
                if st.soft[win[j1 + k]] and (dc in DASHES or (dc in HYPHENS and not is_width_pair(dc, pc))):
                    # docx のダッシュ（en dash・em dash など）・ハイフンの仲間（「‐」、Word の改行なしハイフン「‑」など）と、
                    # PDF の英数字の後の行末の、docx と違う「-」「‐」: PDF に合わせて直す（docx のダッシュを消さない。行の途中の
                    # ダッシュ・ハイフンの違いと同じ）。PDF の文字が行末のハイフンの印（U+FFFE など。何の字形か分からない）なら、
                    # 本当のハイフンが行末に来たものか、行末のハイフン（docx にない）かを PDF から決められないので、docx のまま
                    # （違いにしない）
                    if pc in "-‐":
                        forced[j1 + k] = pc
                        regions.append((i1 + k, i1 + k + 1, j1 + k, j1 + k + 1, why))
                    continue
                if is_width_pair(dc, pc):
                    if fig:
                        if i1 + k in gens or seq[i1 + k][1] not in locked:
                            regions.append((i1 + k, i1 + k + 1, j1 + k, j1 + k + 1, why))
                    elif i1 + k in gens:          # Word が付ける番号
                        kind, ident, at, _ = gens[i1 + k]
                        res.numbers.setdefault((kind, ident), {})[at] = pc
                        numbers.add(i1 + k)
                    elif seq[i1 + k][1] not in locked:
                        width[i1 + k] = pc
                else:
                    regions.append((i1 + k, i1 + k + 1, j1 + k, j1 + k + 1, why))   # 大文字・小文字の違い
            continue
        if tag == "insert" and (i1 == 0 or i1 == len(seq)) and not unsure["flow"]:
            continue                     # 図・表のキャプションなどの前後の PDF の文字（図・表の中の文字など）
        js_all = [j for j in range(j1, j2) if mine(j)]
        # 段落の先頭・末尾の違いでは、最初・最後に一致した文字と同じ行の PDF の文字だけを使う（前・後の行の文字は、照合しない
        # 短い段落〈見出しの「註」など〉や、図・表の中の文字の可能性が高い）。窓には、ほかの段落の塊の文字は入っていない
        # （_joint）ので、段落の最初・最後の、同じ行の PDF にだけある文字（校正で足された「。」・語）も、ほかの段落の文字ではない。
        # cut_prev・cut_next: 外した前（後ろ）の行に、ページの端の行でも受付日でもない文字がある（PDF の文字が次の行に続いて
        # いるかもしれない）か
        cut_prev = cut_next = False
        after = []                       # 段落の最後に一致した文字の行より後ろの行の、外した PDF の文字（窓の中の位置）
        if i1 == 0:
            keep = [j for j in js_all if not any(brk(x) for x in range(j + 1, first_eq + 1))]
            cut_prev = any(not st.edge[win[j]] and st.date[win[j]] < 0 for j in js_all if j not in keep)
            js_all = keep
        if i2 == len(seq):
            keep = [j for j in js_all if not any(brk(x) for x in range(last_eq + 1, j + 1))]
            after = [j for j in js_all if j not in keep]
            cut_next = any(not st.edge[win[j]] and st.date[win[j]] < 0 for j in after)
            js_all = keep
        if tag == "insert" and js_all and (i1 == 0 or i2 == len(seq)):
            # 段落の最初（最後）の、同じ行の PDF にだけある文字が、docx で段落のすぐ前（後ろ）にある照合しない短い段落の文字と
            # 同じ: 追い込みの見出し（docx では「付記」の段落と次の段落に分かれ、PDF では「付記」が次の段落の最初の行の頭に
            # 入る）。docx にある文字なので、違いにしない
            near = beside[0] if i1 == 0 else beside[1]
            pk = "".join(key(st.chars[win[j]]) for j in js_all)
            if any(pk == "".join(near[-m:] if i1 == 0 else near[:m]) for m in range(1, len(near) + 1)):
                continue
        if (i1 == 0 and unsure["head_contested"]) or (i2 == len(seq) and unsure["tail_contested"]) or \
                any(win[j] in unsure["contested"] for j in js_all):
            # 段落の最初（最後）が、PDF の同じ行でほかの段落の最後（最初）と接していて、間の PDF の文字（校正で直された・足された
            # 文字）がどちらの段落の文字か決められない（_contests）: 足しも消しもしない（一方の段落を途中まで直し、もう一方の頭に
            # その文字を足すことにならないように）
            regions.append((i1, i2, js_all[0] if js_all else j1, js_all[-1] + 1 if js_all else j1, EDGE_WHY))
            continue
        # 段落の本体から離れた最初・最後の部分（_isolate）にかかる違いか。段落の本文の続きか、図・表の中の文字か決められない
        # ので、下の分け方で直す違いになっても直さない（FAR_WHY。足さず、消さず、置き換えない）
        far = far_docx(i1, i2) or any(far_pos(j) for j in js_all)
        # 照合に使わない文字（どの段落にも当たらない、ページの端の行・数字だけの行などと、投稿受付日など）を除く。分断する
        # 表・図の中の文字とみなした行（_joint）も同じ（照合に使わなかった文字として記録する）
        dropped = [st.ignored(win[j], owner, owned_lines) or (st.lines[st.line[win[j]]] if j in floaty else "")
                   for j in js_all]
        docx_side = any(c != SKIP for c, _ in seq[i1:i2])
        if docx_side and ((i1 == 0 and unsure["head"]) or
                          (i2 == len(seq) and (unsure["tail"] or (unsure["tail_beyond"] and not js_all)))):
            # 段落の最初（最後）の docx の文字が PDF のどこにも見つからず、PDF ではそのすぐ前（後ろ）か、すぐ後ろの段落の塊の向こう
            # （tail_beyond。同じ行に PDF の文字がないときだけ）に、どの段落とも一致しない文字が続く（図の中の文字など）か、窓の
            # すぐ外に、どの段落の照合にも使われなかった、その文字とよく並ぶ行がある（_edges_near_unused_lines）: 校正で消された
            # のか、別の位置にあるのか決められないので、消さない
            regions.append((i1, i2, js_all[0] if js_all else j1, js_all[-1] + 1 if js_all else j1, UNSURE_WHY))
            continue
        if docx_side and not js_all and (i1 == 0 or i2 == len(seq)):
            # 段落の最初（最後）の docx の文字の位置に、同じ行の PDF の文字がない。すぐ前（後ろ）の行が照合に使わない行
            # （どの段落にも当たらない数字だけの行・ページの端の行など）なら、その行が、出版版で直された段落の最初（最後）の
            # 文字（別の行の見出しの番号「（2）」、引用文献の「，」の後の年「2019」、「p.」の後の「17」など。行全体でしか
            # 一致させない行なので、docx と違う文字なら一致しない）かもしれない。docx の文字を消すことにはせず、直さない違いに
            # する（PDF の文字は、段落のすぐ隣に続く照合に使わない行を出す。その行も、照合に使わなかった文字として記録する）
            rows = _ignored_rows(st, win, range(j2 - 1, j1 - 1, -1) if i1 == 0 else range(j1, j2), owner, owned_lines, p.src)
            if rows:
                _ignore(res, p.src, [st.ignored(win[j], owner, owned_lines) for j in rows])
                regions.append((i1, i2, rows[0], rows[-1] + 1, HEAD_WHY))
                continue
            if (i1 == 0 and cut_prev) or (i2 == len(seq) and (cut_next or unsure["tail_free_end"])):
                # 同じ行の PDF の文字はないが、すぐ前（後ろ）の行に、この段落の窓の PDF の文字がある（cut_prev・cut_next）か、
                # すぐ後ろの行が、どの段落とも一致しない、文の終わりの記号で終わる行（段落の最後の行かもしれない）: その行が、
                # 出版版で直された段落の最初（最後）の文字かもしれない（直した語句が前〈次〉の行に折り返され、docx の文字と
                # 一致しない）ので、消さずに直さない違いにする（すぐ前〈後ろ〉の行がほかの段落の行や、表・図のキャプション・
                # セルなどの行なら、校正で消された文字として今までどおり消す）
                cut = [j for j in range(j1, j2) if mine(j)]
                regions.append((i1, i2, cut[0] if cut else j1, cut[-1] + 1 if cut else j1, EDGE_WHY))
                continue
        if any(dropped):
            # 照合に使わない文字のある範囲の、どの段落の文字とも一致しない行（docx にない図・表の中の文字や、照合に使わない
            # 短いセルの文字など）の文字も照合に使わない（ページの端の行を除いた残りの表の文字で docx の文字を置き換えたり、
            # 校正で足された文字がページや表をまたいで分かれたとき、間の表のキャプションなどを一緒に足したりしないように。
            # 使うのは段落に当たる行の文字だけ）。その行も、照合に使わなかった文字として記録する（13 章の最後の一覧）。
            # 段落に当たる行かは、文字が多く当たった行（dense_lines）で見る（表のキャプションの行の 1〜2 文字が偶然一致しても、
            # その行を段落の行とみなさない）
            loose = [not x and st.line[win[j]] not in dense_lines for j, x in zip(js_all, dropped)]
            dropped = [st.lines[st.line[win[j]]] if y else x for j, x, y in zip(js_all, dropped, loose)]
            stray.update(j for j, y in zip(js_all, loose) if y)
        js = [j for j, x in zip(js_all, dropped) if not x]
        whole = _whole_free_lines(js, win, st, owner, mine) if 0 < i1 and i2 < len(seq) else set()
        # 行まるごとのうち、段落の行ほどの幅の行（いちばん長い行の SHORT_LINE 以上）は、校正で足された長い語句が行をまたぎ、
        # 途中の行が語句の文字だけになったもの（「各自」→「授業の初めに配られた…二つ」）かもしれない（段落の途中の本文の行は
        # 行の幅いっぱいになる）。目に見えて短い行は、本文の行ではなく、図・表の中の文字（キャプションなど）と考える
        full = {n for n in whole if _line_width(st.lines[n]) >= SHORT_LINE * own_width}
        js_full = [j for j in js if st.line[win[j]] not in whole - full]   # 置き換えの PDF の側の長さ（LONG_WHY）は、これで数える
        if whole:
            # 段落の途中の違いの PDF の側に、どの段落にも当たらない行がまるごとある: その行は足さない（置き換えにも使わない）。
            # 段落の途中の本文の行は両端そろえで行の幅いっぱいになり、校正で足された語句は前後の行の組み直しになる（行の途中から
            # 始まる）ので、図・表の中の文字（キャプション・軸の名前など）と考える。照合に使わなかった文字として記録する（13 章の
            # 最後の一覧）。docx の側に文字があり、ほかに PDF の文字がなければ、docx の文字を消さずに直さない違いにする
            wl = [j for j in js if st.line[win[j]] in whole]
            _ignore(res, p.src, [st.lines[n] for n in sorted(whole)])
            js_rest = [j for j in js if st.line[win[j]] not in whole]
            stray.update(wl)
            if not js_rest:
                if docx_side:
                    regions.append((i1, i2, wl[0], wl[-1] + 1, WHOLE_WHY))
                continue
            if full and _spans_whole(js, full, win, st, keep=set(js_rest), both=False):
                # 段落の行ほどの幅の外した行（full）の前か後ろに、PDF の列の上で続いて、PDF にだけある文字が残る: 校正で足された
                # 長い語句の途中の行か、語句が行の境目から始まる（行の境目で終わる）行かもしれない。残りの文字だけで直すと、
                # docx にも PDF にもない文字（「授業つ」「授業の表」）になるので、直さない違いにする（範囲は外した行も含める。
                # _join_long が、隣の直せる違いもまとめて直さないように）
                regions.append((i1, i2, js[0], js[-1] + 1, WHOLE_WHY))
                continue
            js = js_rest
        if not docx_side:
            # docx の側に文字がない（数式・脚注番号は PDF では文字になっている）
            if tag != "insert":
                if js and formula_near(i1, i2, js, j1):
                    # docx の数式の位置の PDF の文字の前か後ろに、文字として取り出せない数式の位置がある: PDF の数式は空白の
                    # 並びで、この PDF の文字は数式の文字ではなく、校正で数式の隣に足された文字かもしれない（「（p，p）」→
                    # 「（p，p，p）」の「，」。足すと数式の欠けた式になり、docx に数式を足すことはできない）。直さない違いにする
                    regions.append((i1, i2, js[0], js[-1] + 1, MATH_WHY))
                continue
            # PDF にだけある長い文字（20 文字以上）は、図の中の文字などの可能性が高いので足さない。長さは、照合に使わない文字を
            # 除く前で数える（図の中の文字の行がページの端にかかって除かれても、残りを足さないように）。ただし、行全体でしか
            # 一致させない行（表の数字の行・何ページにも出る行）の文字と、分断する表・図の中の文字とみなした文字は数えない
            # （そのすぐ隣の、校正で足された短い文字まで足さないことにならないように）
            long = sum(1 for j in js_all if not st.line_only[win[j]] and j not in floaty) >= 20
            if long and js and not any(st.line[win[j]] in own_lines for j in js):
                # この段落の文字のある行にかからない（図の中の文字の行など）: その行も、照合に使わなかった文字として記録する
                dropped = [x or st.lines[st.line[win[j]]] for j, x in zip(js_all, dropped)]
                js = []
            _ignore(res, p.src, dropped)
            if not js:
                row = end_row(after) if tag == "insert" and i1 == len(seq) else []
                if row:
                    # 段落の最後の後ろの PDF にだけある文字が、すぐ後ろの、どの段落にも当たらない行にだけある（同じ行にない）。
                    # docx の段落は文の終わりで終わらず、その行は文の終わりで終わる: 校正で段落の最後に足された文字が次の行に
                    # 出たもの（「。」だけの行、英文の最後の 1 語の行）か、段落の後ろの図・表の中の文字か決められないので、足さずに
                    # 直さない違いにする（その行は、照合に使わなかった文字として 13 章の最後の一覧にも出す）
                    _ignore(res, p.src, [st.lines[st.line[win[row[0]]]]])
                    regions.append((i1, i2, row[0], row[-1] + 1, EDGE_WHY))
                continue
            if long:
                # この段落の文字のある行にかかる: 校正で足された本文かもしれないので、黙って捨てずに、直さない違いにする
                regions.append((i1, i2, js_all[0], js_all[-1] + 1, LONG_WHY))
                continue
        else:
            _ignore(res, p.src, dropped)
            if js_all and not js:
                # PDF のこの位置には、照合に使わない文字（と、どの段落とも一致しない行の文字）しかない:
                # docx の文字を消す（直す）ことにはしない
                regions.append((i1, i2, js_all[0], js_all[-1] + 1, HEAD_WHY))
                continue
            # 段落の途中の置き換えの PDF の側の、照合に使わないページの端の行（どの段落にも当たらない、段落の行と同じほどの幅の
            # 行で、PDF のほかの位置に同じ文字列の行がないもの。柱〈ほかのページにも出る〉・受付日を除く）: 校正で足された長い
            # 語句が、次のページの最初の行（前のページの最後の行）にかかったものかもしれない。その行を外した残りの文字だけで直すと、
            # docx にも PDF にもない文字になる（「各自」→「単元」）
            wide = {st.line[win[j]] for j, x in zip(js_all, dropped)
                    if x and st.edge[win[j]] and not st.line_only[win[j]]} if 0 < i1 and i2 < len(seq) else set()
            wide -= {st.line[win[j]] for j in js_all if st.date[win[j]] >= 0}
            wide = {n for n in wide if _line_width(st.lines[n]) >= SHORT_LINE * own_width
                    and st.lines.count(st.lines[n]) == 1}
            extra = sum(1 for j in js_all if st.line[win[j]] in wide)
            # 直さない違いの PDF の文字には、wide の行と full の行も出す（行の変わり目は LINE_MARK）
            shown = js_all if extra else js_full
            if len(js_full) + extra - sum(1 for c, _ in seq[i1:i2] if c != SKIP) >= 20:
                # 置き換えの PDF の側が docx の側より 20 文字以上長い: 図の中の原稿の写しなどで置き換えないように、直さない違いに
                # する（PDF にだけある 20 文字以上の文字を足さない規則と同じ長さ）。長さは、外した行まるごとのうち段落の行ほどの
                # 幅の行（full）と、ページの端の段落の行ほどの幅の行（wide）の文字も数える（校正で足された長い語句の途中の行を
                # 外した残りの文字で、置き換えないように。目に見えて短い行〈キャプションなど〉は数えない）
                regions.append((i1, i2, shown[0], shown[-1] + 1, LONG_WHY))
                continue
            if wide and _spans_whole(js_all, wide, win, st, keep=set(js), both=False):
                # PDF の文字が、wide の行に続く（行の前か後ろに、照合に使う PDF にだけある文字が続く。full の行と同じ。校正で足された
                # 長い語句が、次のページの最初の行から始まる形も）: 直さない
                regions.append((i1, i2, shown[0], shown[-1] + 1, WHOLE_WHY))
                continue
        if formula_near(i1, i2, js, j1):
            # PDF の文字の間か両隣に、文字として取り出せない数式がある: 足す（置き換える）PDF の文字は、数式の欠けた語句かも
            # しれない（校正で足された「（p1，…，p4 とおく）」が、PDF の文字では「（，…，とおく）」になる）。docx の文字を消す
            # 位置なら、その文字は PDF では数式になっているのかもしれない。直さない違いにする
            regions.append((i1, i2, js[0] if js else j1, js[-1] + 1 if js else j1, MATH_WHY))
            continue
        if (i1 == 0 or i2 == len(seq)) and js and (tag == "insert" or docx_side):
            # 段落の最初（最後）の、同じ行の PDF の文字（校正で足された「。」・語、直された語）。段落のすぐ前（後ろ）の行が、
            # どの段落にも当たらない行で、PDF の文字がその行に続いているかもしれない（文の終わりの記号で終わっていない）ときは、
            # どこまでが段落の文字か決められないので、直さない違いにする（その行も、照合に使わなかった文字として記録される。
            # 同じ行の部分だけで直すと、PDF と違う文字になる）。ただし、段落の最後の行が目に見えて短い（tail_short）か、
            # 段落の最初の行のすぐ前の行が目に見えて短い（head_short）ときは、段落はその行で終わる（その次の行から始まる）ので、
            # 同じ行の文字で直す
            ptext = "".join(st.chars[win[j]] for j in js)
            cont = (i2 == len(seq) and (unsure["tail_free"] or cut_next) and ptext[-1:] not in SENTENCE_END and
                    not tail_short) or (i1 == 0 and (unsure["head_free"] or cut_prev) and not head_short)
            if tag == "insert" and not cont:
                # 段落の最後（最初）の後ろ（前）の、同じ行の PDF にだけある文字と段落の一致した文字の間か、PDF にだけある文字
                # どうしの間（「設けた」の後ろの「。　時間（分）」）に、英文の単語の間でない空白がある: 本文の横に置かれた図の中の
                # 文字（「時間（分）」「点Ｐの位置」など）が同じ行につながったものかもしれない（和文の本文の行の中に空白は入らない。
                # 段落の最初の行の字下げは、PDF にだけある文字の前に来る）ので、足さない
                seq_g = [win[last_eq]] + [win[j] for j in js] if i2 == len(seq) else [win[j] for j in js] + [win[first_eq]]
                cont = any(st.space_before[b] and not (_latin(st.chars[a]) and _latin(st.chars[b]))
                           for a, b in zip(seq_g, seq_g[1:]))
                if not cont and i2 == len(seq):
                    # 段落の最後の文の終わり（docx の段落の最後か、足す PDF の文字の中の「。」など）の後ろに、文の終わりで終わらない
                    # PDF にだけある文字が続く（「…分析した。図３」、英文の「…ratios. Figure 3」）: 校正で足された文なら文の終わりで
                    # 終わるので、図の中の文字が同じ行につながったものかもしれない。足さない（文の終わりで終わる文〈「…分析した。
                    # 以上である。」、英文の「 All were coded.」〉や、docx の段落の最後に足す「。」「（架空，2020）。」は今までどおり
                    # 足す）。英文の「.」が文の終わりかを見分けられるように、PDF の空白のある位置には空白を入れて見る
                    added = "".join((" " if st.space_before[win[j]] else "") + st.chars[win[j]] for j in js)
                    rest = _after_stop(tail, added)
                    cont = bool(rest and rest.strip())
            if cont:
                regions.append((i1, i2, js[0], js[-1] + 1, EDGE_WHY))
                continue
        if (i1 == 0 and weak_start) or (i2 == len(seq) and weak_end):
            weak_hit.add("start" if i1 == 0 else "end")
            # 段落の最初（最後）の一致が、その行の中だけの ISLAND 文字以下（次〈前〉の行の一致と続いていない。「架空の学級は」の
            # 「架空」が、すぐ前の表のキャプション「表３　架空の件数」の「架空」と、文献の最後の「2018」の「2」が、すぐ後ろの
            # 表のセル「2組」の「2」と偶然一致したものかもしれない）: その行が段落の行か決められないので、足しも消しもしない
            # （段落の最後の短い行「た。」のように、前の行から続いて一致したものは今までどおり）
            regions.append((i1, i2, js[0] if js else j1, js[-1] + 1 if js else j1, EDGE_WHY))
            continue
        near = [j for j in (j1 - 1, j1, j2) if 0 <= j < len(win)]
        if any(st.line[win[j]] in unsure["doubt"] for j in js_all + near):
            # 図の中の文字に挟まれた、分断された部分（図の中の原稿の写しか、段落の文字とよく似た図の中の語句かもしれない）の
            # 違いは直さない
            regions.append((i1, i2, js[0] if js else j1, js[-1] + 1 if js else j1, DISPLACED_WHY))
            continue
        regions.append((i1, i2, js[0] if js else j1, js[-1] + 1 if js else j1, FAR_WHY if far else ""))
    regions = _join_long(regions)
    # 段落の最初（最後）の、その行の中だけの 1〜2 文字の一致（偶然の一致かもしれない。weak_start・weak_end）で、その外側の
    # 違う部分を EDGE_WHY にしたときは、その一致の全角・半角も PDF に合わせない（文献の最後の「2018」の「1」を、すぐ後ろの
    # 図のキャプション「図１」の「１」に合わせないように。段落の最後の短い行「で５８」「）。」のように、外側に違う部分がないか、
    # 照合に使わない文字〈図の目盛りの数字など〉しかないときは合わせる）
    eq_ops = [op for op in ops if op[0] == "equal"]
    for op, side in ((eq_ops[0], "start"), (eq_ops[-1], "end")):
        if side in weak_hit:
            for i in range(op[1], op[2]):
                width.pop(i, None)
    _report_regions(p, seq, gens, st, win, regions, mine, used, locked, forced, width, res)
    if width:
        res.width[p.src] = {seq[i][1]: c for i, c in width.items()}
    drops = set()
    for i in set(width) | numbers:
        for j, k in ((i - 1, i), (i, i + 1)):          # 前の文字との間・後ろの文字との間
            if j < 0 or k >= len(seq) or j not in d2w or k not in d2w or d2w[k] != d2w[j] + 1:
                continue
            if j in gens and k in gens:
                continue
            # Word が付ける番号との間なら、番号のアトムの位置から（段落の自動番号は段落の先頭から）
            start = gens[j][3] + 1 if j in gens else seq[j][1] + 1
            end = gens[k][3] if k in gens else seq[k][1]
            gap = range(start, end)
            if not gap or not all(text[x].isspace() for x in gap):
                continue
            pk = d2w[k]
            if not _pdf_space(st, pk):
                drops.update(x for x in gap if x not in locked)
    if drops:
        res.drops[p.src] = drops
    return tail_short


def _whole_free_lines(js, win, st: PdfStream, owner, mine) -> set:
    """窓の中の位置 js（段落の途中の違いの PDF の文字）に、まるごと入っている、どの段落にも当たらない行の番号の集合（行の、
    窓の中のこの段落の違いとして扱ってよい文字〈mine〉がすべて js にあり、窓の中のその行のどの文字もどの段落にも当たらない
    もの）。"""
    if not js:
        return set()
    jset = set(js)
    by_line = {}
    for j, k in enumerate(win):
        by_line.setdefault(st.line[k], []).append(j)
    out = set()
    for n in {st.line[win[j]] for j in js}:
        pos = [j for j in by_line[n] if mine(j)]
        if pos and all(j in jset for j in pos) and all(win[j] not in owner for j in by_line[n]):
            out.add(n)
    return out


def _join_long(regions) -> list:
    """違う部分 regions（(i1, i2, j1, j2, 理由)）のうち、直さない部分（PDF にだけある長い文字のための LONG_WHY・WHOLE_WHY と、
    段落の本体から離れた部分の FAR_WHY）と、docx でも PDF でも ISLAND 文字以下の一致をはさんで隣り合う、直せる部分に、同じ理由を
    付ける（まとめて直さない）。校正で足された長い語句の中の 1〜2 文字が、docx の文字と偶然一致すると、違いが 2 つに分かれ、
    片方だけを直して、docx にも PDF にもない文字にしていた（「各自」→「授業の初めに…前の時間に自分たちで…」の「自」）。"""
    out = list(regions)
    changed = True
    while changed:
        changed = False
        for x, (i1, i2, j1, j2, why) in enumerate(out):
            if why not in (LONG_WHY, WHOLE_WHY, FAR_WHY):
                continue
            for y, r in enumerate(out):
                if r[4] or y == x:
                    continue
                if (0 <= r[0] - i2 <= ISLAND and 0 <= r[2] - j2 <= ISLAND) or \
                        (0 <= i1 - r[1] <= ISLAND and 0 <= j1 - r[3] <= ISLAND):
                    out[y] = r[:4] + (why,)
                    changed = True
    return out


def _spans_whole(js, whole, win, st: PdfStream, keep, both=True) -> bool:
    """段落の途中の違いの PDF の文字 js（窓の中の位置。行まるごとを外す前）で、外した行（行の番号の集合 whole）の前と後ろの
    両方に（both が偽なら、前か後ろに）、PDF の列の上で続いて、残す文字（keep。窓の中の位置の集合）があるか（PDF にだけある
    文字の続きが、その行をまたいでいる〈その行に続いている〉）。"""
    segs = []                 # js の、窓の中でも PDF の列の上でも続いた部分
    for j in js:
        if segs and j == segs[-1][-1] + 1 and win[j] == win[segs[-1][-1]] + 1:
            segs[-1].append(j)
        else:
            segs.append([j])
    for s in segs:
        w = [x for x, j in enumerate(s) if st.line[win[j]] in whole]
        if not w:
            continue
        before = any(s[x] in keep for x in range(w[0]))
        after = any(s[x] in keep for x in range(w[-1] + 1, len(s)))
        if (before and after) if both else (before or after):
            return True
    return False


def _ignore(res: PdfCheck, src, dropped):
    """照合に使わなかった PDF の文字（柱の候補の行・投稿受付日など。PdfStream.ignored の文字列）を、段落ごとに重複なしで記録する。"""
    for d in dropped:
        if d and (src, d) not in res.ignored_lines:
            res.ignored_lines.append((src, d))


def _ignored_rows(st: PdfStream, win, js, owner, owned_lines, src) -> list:
    """窓の中の位置 js（段落の最初の前・最後の後ろから、段落に近い順）の文字が、照合に使わない文字（PdfStream.ignored）で
    続く間の位置（窓の中の順）。ほかの段落に当たった文字か、照合に使う文字があれば、そこで止める（段落のすぐ隣に続く、
    照合に使わない行だけを見る）。
    """
    out = []
    for j in js:
        if owner.get(win[j], src) != src or not st.ignored(win[j], owner, owned_lines):
            break
        out.append(j)
    return sorted(out)


def _pdf_space(st: PdfStream, k: int, prev: int = None) -> bool:
    """PDF の k 番目の文字の前に、本物の空白があるか。

    和文の文字（全角の記号を含む）の隣に PDF で見える空白は、両端そろえや字間の調整による見かけのものなので、空白とみなさない。
    前後がどちらも英文の文字（半角の英数字・記号、アクセント付きの文字、’ “ ” – などの記号）のとき（英文の単語の間）だけ、
    空白（行の折り返しを含む）とみなす。prev: 前の文字の位置（k - 1 の文字を飛ばしたとき〈照合に使わない行の文字など〉に、
    表示する前の文字を渡す）。
    """
    prev = k - 1 if prev is None else prev
    if prev < 0 or not (st.space_before[k] or st.newline_before[k]):
        return False
    return _latin(st.chars[prev]) and _latin(st.chars[k])


def _latin(c: str) -> bool:
    o = ord(c)
    return o < 0x250 or 0x2010 <= o <= 0x2027


def _report_regions(p, seq, gens, st: PdfStream, win, regions, mine, used, locked, forced, width, res: PdfCheck, near=12):
    """違う部分を、近いものどうしまとめて TextDiff にする。

    mine: PDF の文字が、ほかの段落に当たっていないか。used: さらに、照合に使わない文字（柱の候補の行・投稿受付日など、
    _classify の stray の行）でもないか。PDF の文字は used の文字だけを使う。ただし、直せない理由 why のある部分（PDF の側に
    照合に使わない文字しかない部分、PDF にだけある長い文字など）は、直さない（fixable=False）ので、表示のために mine の文字を
    すべて載せ、行の変わり目に LINE_MARK を入れる（受付日の後ろに続く本文の行を見分けられるように）。文字として取り出せない
    数式の位置（MATH_WHY）には FORMULA_MARK を入れる。直せない理由のある部分は、ほかの部分とまとめない（近くの直せる違いまで
    直さないことにならないように）。
    まとめた違いの PDF の文字は、違う部分ごとの PDF の文字と、その間（docx と PDF が一致した部分）の docx の文字をつないで作る
    （間の行末のハイフン〈docx の「-」と同じ文字とみなしたもの〉や docx の空白を落とさないように。「pp.45-58」と PDF「pp.46-」
    〈改行〉「59」で、「pp.46 59」にしない）。間の docx の文字のうち、全角・半角だけが違う文字（width: seq の位置 -> PDF の
    文字）は PDF の文字にして、直せるまとめた違いに含める（width から除く。別の直す箇所にすると、まとめた直しと重なって、
    plan_fixes がまとめた直しの一部だけを当てはめ、「pp.46-5-58」のような docx にも PDF にもない文字にしていた）。
    forced: 窓の中の位置 -> 使う PDF の文字（docx のダッシュの位置の行末の「-」）。
    """
    merged = []
    for r in sorted(regions):
        g = merged[-1] if merged else None
        if g and r[4] == g[0][4] and r[0] - max(x[1] for x in g) <= near and r[2] - max(x[3] for x in g) <= near:
            g.append(r)
        else:
            merged.append([r])
    text = p.plain()
    wtext = {seq[i][1]: c for i, c in width.items()}      # docx の段落の中の位置 -> 全角・半角だけが違う PDF の文字

    def docx_range(i1, i2):           # 違う部分の docx の段落の中の範囲と、足す位置を決められるか
        pos = [q for _, q in seq[i1:i2] if q >= 0]
        if pos:
            return pos[0], pos[-1] + 1, True
        if i1 > 0:                    # docx の側に文字がない（PDF にだけある）: 直前の docx の文字の後に足す
            prev = seq[i1 - 1]
            ok = prev[1] >= 0 and prev[0] != SKIP and (i1 - 1) not in gens
            a = (prev[1] + 1) if ok else max([q + 1 for _, q in seq[:i1] if q >= 0] or [0])
            return a, a, ok
        # 段落の最初: 最初の docx の文字の前に足す（Word が付ける番号・数式などで始まる段落は、位置を決められない）
        ok = bool(seq) and seq[0][1] >= 0 and seq[0][0] != SKIP and 0 not in gens
        return (seq[0][1], seq[0][1], True) if ok else (0, 0, False)

    def pdf_text(j1, j2, all_mine, formulas=False):
        """窓の中の位置 j1..j2 の PDF の文字（比べる文字と、表示する文字）。all_mine: mine の文字をすべて使い、行の変わり目に
        LINE_MARK を入れる（直せない部分）。formulas: 数式の位置（PdfStream.formula）に FORMULA_MARK を入れる。"""
        ptext = shown = ""
        last = None
        for j in range(j1, j2):
            if j in forced:
                ch = forced[j]
            elif not (mine(j) if all_mine else used(j)):
                continue
            else:
                ch = st.chars[win[j]]
            g = win[j]
            mark = FORMULA_MARK if formulas and st.formula[g] else ""
            if all_mine and last is not None and st.line[g] != st.line[last]:
                # 直せない部分は、行の変わり目を示す（数式が前の行の最後にあれば、その後ろに）
                shown += mark + LINE_MARK if st.formula[g] == 1 else LINE_MARK + mark
                ptext += mark
            elif mark:
                ptext += mark
                shown += mark
            elif ptext and _pdf_space(st, g, last):
                ptext += " "          # 表示のために単語の間の空白を戻す（照合では空白を使わない）
                shown += " "
            ptext += ch
            shown += ch
            last = g
        if formulas:
            # 違う部分の後ろ（PDF の文字がない位置なら、その位置）の数式
            k = last + 1 if last is not None else (win[j1] if j1 < len(win) else len(st.chars))
            if k < len(st.chars) and st.formula[k]:
                ptext += FORMULA_MARK
                shown += (LINE_MARK if st.formula[k] == 2 and last is not None else "") + FORMULA_MARK
        return ptext, shown

    for group in merged:
        why = group[0][4]
        i1, i2 = group[0][0], max(r[1] for r in group)
        j1, j2 = group[0][2], max(r[3] for r in group)
        num = "".join(seq[i][0] for i in range(i1, i2) if i in gens)
        ranges = [docx_range(r[0], r[1]) for r in group]
        if len(group) > 1 and ranges[0][0] == ranges[0][1]:
            # まとめた違いが PDF にだけある文字で始まるときは、まとめた範囲の最初の docx の文字の前に足す（直前の docx の文字の
            # 後ろの空白より後ろ。0.20.0 と同じ位置）
            q = next((q for _, q in seq[i1:i2] if q >= 0), None)
            if q is not None:
                ranges[0] = (q, q, ranges[0][2])
        anchor_ok = all(ok for _, _, ok in ranges)
        a, b = ranges[0][0], max(rb for _, rb, _ in ranges)
        if why or num:
            ptext, shown = pdf_text(j1, j2, bool(why), why == MATH_WHY)
        else:
            ptext = ""
            for k, r in enumerate(group):
                t, _ = pdf_text(r[2], r[3], False)
                ptext += t
                if k + 1 < len(group):
                    # 間の一致した部分は docx の文字（全角・半角だけが違う文字は PDF の文字）
                    ptext += "".join(wtext.get(x, text[x]) for x in range(ranges[k][1], ranges[k + 1][0]))
            r = group[0]
            if len(group) == 1 and r[0] == r[1] and ptext and (r[0] == 0 or r[0] == len(seq)):
                # 段落の最初の前・最後の後ろに足す PDF の文字と、段落の一致した文字の間が英文の単語の間の空白なら、空白も足す
                # （英文の段落の最初に校正で足された「Briefly,」を「Briefly,This」にしないように）
                if r[0] == 0 and r[3] < len(win) and _pdf_space(st, win[r[3]], win[r[3] - 1]):
                    ptext += " "
                elif r[0] == len(seq) and r[2] > 0 and _pdf_space(st, win[r[2]], win[r[2] - 1]):
                    ptext = " " + ptext
            shown = ptext
        # 表示する docx の文字と前後の文字では、docx の数式・画像（OBJ）を FORMULA_MARK で示す（レポートの 13 章のほかの表と同じ）
        dtext = text[a:b].replace(OBJ, FORMULA_MARK)
        if num:
            dtext = f"（Word が付けた番号「{num}」）" + dtext
        dk, pk = re.sub(r"\s", "", (num + text[a:b].replace(OBJ, ""))), re.sub(r"\s", "", ptext)
        if fold_str(dk) == fold_str(pk) and not (why in (DISPLACED_WHY, FAR_WHY) and dk != pk):
            # 全角・半角だけの違いは、違いにしない（res.width で扱う）。ただし、図の中の文字の行と並べたために直さなかった
            # 全角・半角の違い（DISPLACED_WHY）と、段落の本体から離れた部分の全角・半角の違い（FAR_WHY。_classify）は、
            # 黙って捨てずに直さない違いとして出す
            continue
        ctx = (text[max(0, a - 12):a] + "［" + text[a:b] + "］" + text[b:b + 12]).replace(OBJ, FORMULA_MARK)
        fixable = not why and anchor_ok and not num and OBJ not in text[a:b] \
            and not any(SKIP == seq[i][0] for i in range(i1, i2)) and not any(x in locked for x in range(a, max(b, a + 1)))
        res.diffs.append(TextDiff(p.src, dtext, shown, ctx, a, b, fixable, why))
        if fixable and len(group) > 1:
            # まとめた直しの範囲の、全角・半角だけの直し（PDF の文字は ptext に入っている）は、別の直す箇所にしない
            for i in [i for i in width if a <= seq[i][1] < b]:
                width.pop(i)


def fold_str(s: str) -> str:
    return "".join(fold(c) for c in s)


def check_pdf(plan, pdf_path, fn_marks=None) -> PdfCheck:
    """記事の PDF を読み、docx の段落と照合する。PDF を読めなければ ok=False（変換は続ける）。"""
    try:
        pages = extract_pages(pdf_path)
    except ImportError:
        return PdfCheck(ok=False, message="PDF の文字を読むための pypdfium2 が入っていない（pip install pypdfium2）")
    except Exception as e:  # noqa: BLE001
        return PdfCheck(ok=False, message=f"PDF を読めなかった: {e}")
    return compare(plan, pages, fn_marks)
