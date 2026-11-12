"""段落の役割（見出し・本文・図表・文献など）を決め、論文の構造（ArticlePlan）を組み立てる。

役割は原則として Word のスタイル名で決める（config の [styles]）。
スタイルが想定外の段落には、番号の形式などから機械的に推定した役割を与え、
推定したことを Decision として記録する（レポートと AI 補完の対象になる）。
構造の組み立ては文字列を一切変更しない。出力しない段落は Exclusion として必ず記録する。

構造の型（ArticlePlan と、章・段落・図表・注などのノード、FloatInfo・BoxInfo）と _para_text は article.py にある（修正計画の
U6 で本体を変えずに移した。これまでどおり、ここからも import できる）。ここには、役割を決める規則（役割の集合・番号の形の
正規表現・除外の理由の文言）と、組み立て（Classifier）を置く。

処理とメソッドの目次:

- classify: Classifier(...).run() で組み立てる。本文の外（引用文献・注・付記・謝辞・英文の部分）の段落に結び付いた図形が
  あれば（Classifier.outside）、1 回目が段落に書き込んだもの（_doc_paragraphs）を戻して、もう 1 回組み立てる（修正計画の N7）。
- Classifier.run の流れ:
  1. 段落の役割: role_of（AI の指定 overrides、なければ style_role〈スタイルの基準の連鎖をたどる〉）。Word の脚注・文末脚注の
     段落も plan.paras・plan.note_of に記録する。AI が exclude とした段落は理由付きで除外する。
  2. 領域に分ける: split_regions（和文の冒頭・本文・後付け・英文の部分。table_roles・back_heading_by_text・guess_heading）。
  3. 和文の冒頭: build_front_ja（read_author_table_ja・author_paragraph_ja → add_author_ja → aff_for。著者名に付かない所属は
     aff_conflict が plan.structure_conflicts に記録する〈K2〉。題目・著者以外の段落は front_decoration で、テンプレートの
     装飾・誌名行〈JournalConfig.front_lines〉なら FRONT_DECORATION_EXCLUDED〈知らせない〉、そうでなければ位置を決められない
     除外 FRONT_OTHER_EXCLUDED〈UNPLACED_EXCLUSIONS。要確認 excluded_unsure〉）。
  4. 本文: build_body
     - 浮動配置の図表の置き場所: place_floats（float_captions・float_number・float_summary。機械的に組む float_mechanical
       〈表のセルの画像とキャプション cell_figures・cell_pairs・cell_caption〉、AI の指定で組む float_from_spec、位置を
       決められない図表の仮の位置 provisional_target・run_end〈list_or_quote〉。図形の中身を取る _take・_take_table・
       _caption_decision・_drop_blank）
     - 文字だけのテキストボックス（囲み・図の注記）: place_boxes（text_only・near_image・box_children・run_end・_xid_list）
     - 段落の役割の推定（textbox_caption・guess_heading〈all_bold〉）と、本文スタイルの図表キャプションの推定（same_place・
       is_image_para）
     - 図表・箇条書き・引用・別行数式に組む: assemble_floats（same_place・table_for_figure・formula_node・
       doc_numbering_is_bullet）
     - 章・節・項の入れ子: nest。段落の位置の説明: compute_locations（node_paras）
  5. 後付け（付記・謝辞・注・引用文献）: build_back（outside_key・back_heading_by_text・note_mark・appendix_heading・formula_node。
     同じ種類の見出しが 2 つになるときは replace_back が plan.structure_conflicts に記録する〈K1〉。注の節の中の表は FnNode.tables
     に入れる〈表の枝の pending・caption_only・note_table・settle。注に入れられない表は flush が BACK_TABLE_EXCLUDED で除外〉）
  6. 英文の部分と資料: build_front_en（outside_key・appendix_heading・appendix_sentence・note_appendix_sentence・
     check_abstract_ja・add_author_en・add_aff_en。英文要旨の見出しが 2 つになるときも replace_back が記録する。題目・著者・
     要旨・資料以外の段落と表は EN_OTHER_EXCLUDED・EN_TABLE_EXCLUDED〈EN_PART_EXCLUSIONS。英文要旨が 1 段落もなければ
     abstract_missing_srcs が要対応 abstract_missing の対象にする〉）
  7. Word の脚注・文末脚注を注にする: attach_word_notes（unreferenced_note_reason・no_link_rule）
  8. ID を付ける: assign_ids（図・表・数式・注・文献・所属）
  9. 段落記号の削除でつないだ段落のスタイルの違いを判断の一覧に記録する: joined_styles
- レポート・AI 依頼文・Colab・コマンドラインが使う関数: float_caption・float_ids・float_targets（浮動配置の図形の中身と、それを
  出力した XML の要素の説明）。
- 除外の理由の文言は定数（FRONT_*・BACK_*・EN_*_EXCLUDED など）で書き、位置を決められずに除く理由は UNPLACED_EXCLUSIONS に
  まとめる（report が要確認 excluded_unsure・要対応 abstract_missing で知らせる）。
- pipeline.convert が使う関数: conflict_overrides（AI の set_role で構造の衝突ができたときに、まず使わない指定〈衝突の範囲の中の
  段落への指定〉）。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# 構造の型は article.py にある（ここでも使う）。structure から import しているコード（tests など）のために、これまでどおりの
# 名前でここにも置く（互換のため。どれもこのファイルで使っているので noqa: F401 は付けない〈付けると ruff の RUF100 になる〉）
from .article import (
    Aff,
    AppNode,
    ArticlePlan,
    Author,
    BackSec,
    BoxInfo,
    BoxNode,
    FigNode,
    FloatInfo,
    FnNode,
    FormulaNode,
    ListNode,
    PNode,
    QuoteNode,
    RefNode,
    Sec,
    StructureConflict,
    TableNode,
    _para_text,
)
from .floats import NEAR_PARAS, at_anchor, box_lines, textbox_kind, why_not_at_anchor
from .model import Para, Table, note_key, note_label
from .ooxml import is_ws

BODY_ROLES = {"sec1", "sec2", "sec3", "p", "fig_caption", "table_caption", "quote", "fn"}
FRONT_JA_ROLES = {"title", "subtitle", "aff_ja", "author_ja"}
FRONT_EN_ROLES = {"title_en", "subtitle_en", "author_en", "aff_en", "abstract_heading", "abstract"}
BACK_HEADINGS = {"notes_heading": "notes", "ack_heading": "ack", "fn_heading": "fn", "ref_heading": "refs"}
HEADING_LEVEL = {"sec1": 1, "sec2": 2, "sec3": 3}

# 図表の入った図形（キャプション・画像・表のあるテキストボックス・グループ図形）の中の、キャプションでも図表の本体でもない
# 段落を除外したときの理由（図表の一部とみなす。要確認で知らせる〈report._textbox_figure_text_action〉。文字だけの
# テキストボックスは Classifier.place_boxes で扱う）
TEXTBOX_TEXT_EXCLUDED = "テキストボックス内の文字（図の一部とみなして本文から除外）"
# 文字だけのテキストボックス（Classifier.place_boxes）の文字を出力しないときの理由。どれも「テキストボックス内の文字」で始める
TEXTBOX_LABEL_EXCLUDED = "テキストボックス内の文字（図に重ねた注記とみなして本文から除外）"
TEXTBOX_UNDECIDED_EXCLUDED = "テキストボックス内の文字（囲みか図の注記か決められないため本文から除外。要確認）"
TEXTBOX_AI_LABEL_EXCLUDED = "テキストボックス内の文字（AI による補完で図に重ねた注記と判断し、本文から除外）"
# 引用文献・注の節の、画像だけの段落（文字は 1 文字もない。blank の除外。画像は pipeline.lost_images が知らせる）を除外したときの理由
REF_IMAGE_EXCLUDED = "画像だけの段落（引用文献の節の中。引用文献には画像を出力できない）"
FN_IMAGE_EXCLUDED = "画像だけの段落（注の節の中。注が始まる前の段落は注にしない。注には画像を出力できない）"
# 冒頭部の、テンプレートの装飾・誌名行の段落（意図した除外。知らせない。front_decoration で決める）
FRONT_DECORATION_EXCLUDED = "冒頭部のテンプレート装飾・誌名行など（題目・著者以外の段落）"
# 論文の中の位置（役割）を決められずに除いたときの理由。要確認 excluded_unsure（report._unplaced_action）で知らせる
FRONT_OTHER_EXCLUDED = "冒頭部の、題目・著者以外の段落（テンプレートの装飾・誌名行ではない）"
FRONT_TABLE_EXCLUDED = "冒頭部の表（著者表以外）の文字"
AUTHOR_TABLE_OTHER_EXCLUDED = "著者表の中の、所属・著者名以外の文字"
BACK_TABLE_EXCLUDED = "後付けの位置づけが不明な表の文字"
BACK_OTHER_EXCLUDED = "位置づけが不明な段落（本文と後付けの間）"
EN_AUTHOR_TABLE_OTHER_EXCLUDED = "英文著者表の中の、所属・著者名以外の文字"
EN_TABLE_EXCLUDED = "英文部分の表（著者表以外）の文字"
EN_OTHER_EXCLUDED = "英文部分の、題目・著者・要旨以外の段落"
UNPLACED_EXCLUSIONS = (FRONT_OTHER_EXCLUDED, FRONT_TABLE_EXCLUDED, AUTHOR_TABLE_OTHER_EXCLUDED, BACK_TABLE_EXCLUDED,
                       BACK_OTHER_EXCLUDED, EN_AUTHOR_TABLE_OTHER_EXCLUDED, EN_TABLE_EXCLUDED, EN_OTHER_EXCLUDED)
# 英文要旨がないときに要対応 abstract_missing の対象にする理由（abstract_missing_srcs）
EN_PART_EXCLUSIONS = (EN_TABLE_EXCLUDED, EN_OTHER_EXCLUDED)
# 本文の外の領域（図形のアンカー段落がある領域。Classifier.outside の値）の日本語（修正計画の N7）
OUTSIDE_JA = {"refs": "引用文献", "fn": "注", "notes": "付記", "ack": "謝辞", "back": "後付け", "front_en": "英文の部分"}
# 位置を決められない図表を仮に置く位置のうち「本文の最後」（本文の領域の最後の要素の後ろ）。place_floats の差し込み位置
BODY_END = float("inf")
# 囲み（文字だけのテキストボックス。BoxNode）の置き場所（same_place・Classifier.provisional の値）。図表の組み立てでは、囲みを
# 図形の外の要素の隣として数えない（build_body）
BOX_PLACE = "@box"
# 本文より後ろにある領域（ArticlePlan.region の値）。AI がこれらの段落の後ろを指定した図表は、本文の最後に仮に置く
# （ai_assist.float_placements。本誌のテンプレートでは、英文の部分・資料も本文より後ろ）
AFTER_BODY_REGIONS = {"notes", "ack", "fn", "refs", "back", "front_en", "app"}

# 想定外スタイルの段落から役割を推定する規則
RE_HEAD1 = re.compile(r"^[0-9０-９]{1,2}[．.](?![0-9０-９])\s*\S.{0,40}$")
RE_HEAD2 = re.compile(r"^[(（][0-9０-９]{1,2}[)）]\s*\S.{0,40}$")
RE_HEAD3 = re.compile(r"^[①-⑳]\s*\S.{0,40}$")
RE_FIGCAP = re.compile(r"^(?:図|Figure|Fig\.?)\s*([0-9０-９]+)")
RE_TABCAP = re.compile(r"^(?:表|Table)\s*([0-9０-９]+)")
# キャプションの番号のすぐ後ろの枝番（「図1-2」「図2.1」）の区切りの文字（正規表現の文字クラスの中身。枝番の区切りの定義はここ
# 1 か所で、builder の RE_LABEL_SPLIT〈split_labels のときに <label> に分ける番号の形〉と linker の RE_BRANCH_REF〈参照の枝番〉が
# これを使う）。「-」「‐」「‑」「‒」「–」「—」「―」「−」「.」と、NFKC 前の全角の「．」「－」。後ろに枝番の数字（CAP_BRANCH_NUM）が
# 続くときだけ区切りとする
CAP_BRANCH_SEP = "\\-\u2010-\u2015\u2212.\uff0e\uff0d"
# 枝番の数字: 1〜2 桁で、直後に数字が続かないもの（「図1―2019年度の推移」の「2019」は年なので枝番にしない。区切りと同じく 3 か所
# で使う定義）。NFKC 前の全角の数字も含める
CAP_BRANCH_NUM = "[0-9０-９]{1,2}(?![0-9０-９])"
# キャプションの番号のすぐ後ろの枝番（NFKC 後の文字に使う）。枝番はキャプションの番号の一部で、整数だけを読む RE_FIGCAP・RE_TABCAP
# では「図1-1」「図1-2」がどちらも「図1」になる（linker が参照のリンクを決めるときに使う）
RE_CAP_BRANCH = re.compile(rf"[{CAP_BRANCH_SEP}](?={CAP_BRANCH_NUM})")


def caption_label(para: Para, regex) -> tuple:
    """図・表のキャプションの段落 para の番号と、番号のすぐ後ろに枝番があるか: (番号, 枝番あり)。regex は RE_FIGCAP・RE_TABCAP。
    番号を読めなければ (None, False)。番号は assign_ids が FigNode.number・TableNode.number に入れるものと同じ。"""
    t = nfkc(_para_text(para)).strip()
    m = regex.match(t)
    if not m:
        return None, False
    return int(m.group(1)), RE_CAP_BRANCH.match(t, m.end(1)) is not None
# テキストボックス内のキャプションの形（NFKC 後）。番号の直後がひらがな・読点・範囲の記号なら「図1は…」のような本文の文
RE_TEXTBOX_CAP = re.compile(r"^(?:(?P<fig>図|Figure|Fig\.?)|(?P<tab>表|Table))\s*[0-9]+(?![0-9ぁ-ゟ,、・~〜\-–—])")
RE_FORMULA_LABEL = re.compile(r"^[\s\u3000]*([(（][\s\u3000]*[0-9０-９]+(?:[.．\-－][0-9０-９]+)?[\s\u3000]*[)）])[\s\u3000]*$")
# 注の一覧の各注の先頭の番号: 「1)」「(1)」「注1)」/「（注1）」「［注1］」/「注1　…」（「註」も）
_WS = r"[\s\u3000]*"
RE_NOTE_MARK = re.compile(
    rf"^{_WS}("
    rf"(?:[注註]{_WS})?[(（]?{_WS}(?P<n1>[0-9０-９]{{1,3}}){_WS}[)）]"
    rf"|[(（\[［〔]{_WS}[注註]{_WS}(?P<n2>[0-9０-９]{{1,3}}){_WS}[)）\]］〕]"
    rf"|[注註]{_WS}(?P<n3>[0-9０-９]{{1,3}})(?=[\s\u3000:：.．,，、]|$)"
    rf")")
RE_REF_HEADING_TEXT = re.compile(r"^\s*(?:引用(?:・|及び|および)?参考文献|参考(?:・|及び|および)?引用文献|引用文献|参考文献|文献"
                                 r"|References?|REFERENCES?|Bibliography)\s*$")
RE_ACK_TEXT = re.compile(r"^\s*(?:謝辞|Acknowledge?ments?)\s*$")
RE_NOTES_TEXT = re.compile(r"^\s*付記\s*$")
RE_FN_TEXT = re.compile(r"^\s*(?:注|註|注釈|Notes?)\s*$")
# 資料（付録）の見出し: 「資料」「付録」「附録」「Appendix」で始まる段落（英文要旨の後ろで、資料の始まりとみなす。build_front_en）。
# 先頭の開き括弧を 1 つ許す（「【資料1】」「（資料3）」。閉じ括弧はそろえなくてよい）。語の後ろの番号は、数字・英字・
# Ⅰ-Ⅻ・ⅰ-ⅻ・①-⑳で、前に空白と全角のハイフン「－」・ハイフン「‐」、後ろに枝番（「資料1-2」）を許す。番号の直後には、
# 空白・コロン・ピリオド・読点・括弧・ダッシュ・行末だけを許す（「資料1を配布した」「資料12の結果」は本文の文）。ASCII の
# ハイフン「-」は語の直後に許さない（「資料-1」は本文の文とみなす。枝番の区切りにだけ使う）。番号がないときは、語の直後に
# 空白・コロン・括弧・ダッシュ・行末だけを許す（「資料、図表」「資料.」は本文の文）。この形に合う文（「資料1、2は…である。」
# 「Appendix shows ….」）は appendix_sentence で見分ける
_APP_OPEN = "【［\\[〔〈《＜<(（"
_APP_CLOSE = "】］\\]〕〉》＞>)）"
_APP_DASH = "－‐‒–—―"          # ASCII のハイフン「-」は入れない（枝番の区切りにだけ使う）
_APP_NUM = "[0-9０-９A-ZＡ-Ｚ]+|[Ⅰ-Ⅻ]|[ⅰ-ⅻ]|[①-⑳]"
RE_APPENDIX = re.compile(
    rf"^{_WS}[{_APP_OPEN}]?{_WS}(?:資料|付録|附録|Appendix)"
    rf"(?:{_WS}[－‐]?{_WS}(?:{_APP_NUM})(?:[-{_APP_DASH}](?:{_APP_NUM}))*"                 # 番号（前に全角のハイフン、後ろに枝番）
    rf"(?=[\s\u3000:：.．、,，{_APP_OPEN}{_APP_CLOSE}{_APP_DASH}]|$)"                      # 番号の直後
    rf"|(?=[\s\u3000:：{_APP_OPEN}{_APP_CLOSE}{_APP_DASH}]|$))")                           # 番号のないとき、語の直後
# RE_APPENDIX に合う段落のうち、文の形のもの（appendix_sentence。資料の見出しとみなさない）を見分ける規則。和文の文は、語・番号の
# 後ろにかな・漢字があり、段落が「。」か「．」で終わるもの（「資料1、2は…である。」。括弧・かぎ括弧の中の「。」〈「資料2　…
# （下線は筆者。）」〉は段落の終わりでないので数えない）。英文の文は、語・番号（と閉じ括弧）の後ろが「空白 + 英小文字」で、
# かな・漢字がなく、段落が「.」「?」「!」で終わるもの（「(Appendix 1) lists ….」。「Appendix 1 questionnaire」「資料2 iPad の画面」は見出し）
RE_APPENDIX_SENTENCE = re.compile(rf"[{_APP_CLOSE}]*[\s\u3000]+[a-z]")
RE_JA_SENTENCE_END = re.compile(r"[。．][\s\u3000]*$")
RE_EN_SENTENCE_END = re.compile(r"[.?!][\s\u3000]*$")
# かな・漢字（英文要旨の中の和文の段落の判定。config.RE_JA_CHARS は全角英数字も含むので使わない）
RE_KANA_KANJI = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff々]")
ABSTRACT_JA_RATIO = 0.3        # 英文要旨の段落のうち、かな・漢字がこの割合以上なら和文の段落とみなして知らせる
# 引用文献などの後ろの資料の見出しと思われる段落を知らせるときの、後付けの節の名前（build_back。決定事項 8(b) は暫定で警告だけ）
APP_PLACE = {"refs": "引用文献", "fn": "注", "notes": "付記", "ack": "謝辞"}
# 注の番号をリンクにしない段落の種類（ArticlePlan.no_link_paras。判断の一覧と、レポートの 8 章の表で知らせる）
NO_LINK_KINDS = "題目・副題・著者名・所属・引用文献"


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def front_decoration(para: Para, lines=()) -> bool:
    """和文の冒頭の、題目・著者以外の段落が、テンプレートの装飾か。文字（text）と画像以外のアトム（数式・注の参照など）があれば偽。
    そうでなければ、空白を除き NFKC にした文字が、空か、文字・数字を含まない（記号だけの装飾行）か、雑誌の設定の誌名行
    （JournalConfig.front_lines）のどれかと同じなら真。画像だけの段落は装飾とする（画像は lost_images の要対応で知らせる）。"""
    if any(a.kind not in ("text", "image") for a in para.atoms):
        return False
    t = re.sub(r"\s", "", nfkc(_para_text(para)))
    if not t or t in {re.sub(r"\s", "", nfkc(x)) for x in lines}:
        return True
    return not any(unicodedata.category(c)[0] in "LN" for c in t)


def abstract_missing_srcs(plan) -> list:
    """英文要旨が 1 段落もない（plan.abstract が空）のに、英文の部分の段落・表の文字を位置を決められずに除いたとき、その段落 ID
    （docx の順。空白だけ・文字のない段落を除く）。英文の部分がない原稿、英文要旨がある原稿では []。"""
    if plan.abstract:
        return []
    return [e.src for e in plan.exclusions if e.reason in EN_PART_EXCLUSIONS and not e.blank and e.text.strip()]


def num_of(s: str) -> Optional[int]:
    try:
        return int(nfkc(s))
    except ValueError:
        return None


def note_mark(s: str) -> Optional[tuple]:
    """注の先頭の番号（「1)」「（注1）」など）の (開始, 終了, 番号)。番号で始まっていなければ None。"""
    m = RE_NOTE_MARK.match(s or "")
    if not m:
        return None
    return m.start(1), m.end(1), num_of(m.group("n1") or m.group("n2") or m.group("n3"))


def appendix_sentence(text: str) -> str:
    """資料の見出しの形（RE_APPENDIX）に合う段落が文の形なら、その形の名前（判断の一覧の文言に使う）。合わない・文の形でなければ ''。

    和文の文: 語・番号の後ろにかな・漢字があり、段落が「。」か「．」で終わる（「資料1、2は授業の記録である。」「（資料1）に
    示すように、…。」）。括弧・かぎ括弧の中の「。」（「資料2　児童の記述（下線は筆者。）」「資料1　問い「なぜだろう。」の…」）は
    段落の終わりでないので、見出しのまま。英文の文: 語・番号（と閉じ括弧）の後ろが「空白 + 英小文字」で、かな・漢字がなく、
    段落が「.」「?」「!」で終わる（「(Appendix 1) lists ….」）。英文の終わりがない「Appendix 1 questionnaire」と、和文の
    「資料2 iPad の画面」は見出しのまま（0.23.1 と同じ）。
    """
    m = RE_APPENDIX.match(text)
    if not m:
        return ""
    rest = text[m.end():]
    if RE_KANA_KANJI.search(rest):
        return "「。」か「．」で終わる和文の文" if RE_JA_SENTENCE_END.search(rest) else ""
    if RE_APPENDIX_SENTENCE.match(rest) and RE_EN_SENTENCE_END.search(rest):
        return "番号などの後ろが英小文字の語で、「.」などで終わる英文の文"
    return ""


def block_id(b) -> str:
    """本文のブロック b（段落・表）の識別子（段落は src、表は tid）。文言に使う。"""
    return b.src if isinstance(b, Para) else b.tid


def appendix_heading(text: str) -> bool:
    """段落の文字が資料（付録）の見出しの形か（英文要旨の後ろの資料の始まり〈build_front_en〉と、引用文献などの後ろの資料の
    知らせ〈build_back〉で使う）。RE_APPENDIX に合い、文の形（appendix_sentence）でないもの。
    """
    return bool(RE_APPENDIX.match(text)) and not appendix_sentence(text)


def unreferenced_note_reason(key: str, deleted: bool) -> str:
    """本文から参照されていない Word の脚注・文末脚注を除外したときの理由（レポートの 6 章）。

    deleted: 参照が削除の変更履歴の中にだけある（Word で変更をすべて承諾すると、注も消える）。
    """
    if deleted:
        return f"{note_label(key)}（本文の参照が変更履歴で削除された注。Word で変更をすべて承諾すると消える）"
    return f"{note_label(key)}（本文から参照されていない注）"


def no_link_rule(kinds) -> str:
    """注の番号をリンクにしない段落の中の、Word の注の参照の書き出し方（判断の一覧の説明）。

    kinds: 参照のある段落の種類（ArticlePlan.no_link_paras の値。「題目」「著者名」など）。題目・所属・引用文献などでは
    上付きの番号だけを出し、著者名では番号も出さない（著者名の要素には上付きの文字を置けない。emit.Emitter.write_object）。
    """
    kinds = list(dict.fromkeys(kinds))
    out = []
    shown = [k for k in kinds if k != "著者名"]
    if shown:
        out.append(f"{'・'.join(shown)}の中の注の番号は、リンクにせず上付きの番号だけにする")
    if "著者名" in kinds:
        out.append("著者名の中の注の番号は、著者名に上付きの文字を置けないので出力しない")
    return "。".join(out)


def _xid_list(xids) -> str:
    """テキストボックスの ID の並びの短い表記（「x3」「6 件（x3〜x8）」「3 件（x3・x5・x9）」「21 件（x7〜x28 の一部）」）。"""
    if len(xids) == 1:
        return xids[0]
    nums = [int(x[1:]) for x in xids if x[1:].isdigit()]
    if len(nums) == len(xids) and nums == list(range(nums[0], nums[0] + len(nums))):
        return f"{len(xids)} 件（{xids[0]}〜{xids[-1]}）"
    if len(xids) <= 6:
        return f"{len(xids)} 件（{'・'.join(xids)}）"
    return f"{len(xids)} 件（{xids[0]}〜{xids[-1]} の一部）"


def in_shape(b) -> bool:
    """図形（テキストボックス・グループ図形）の中の段落・表か（Para・Table の in_textbox または float_id）。"""
    return b.in_textbox or bool(b.float_id)


def float_caption(info) -> str:
    """浮動配置の図形の中のキャプション（表のセルの中のものも）の冒頭。レポート・Colab・コマンドラインで図表を示すのに使う。"""
    caps = []
    for q in info.paras + [c for t in info.tables for c in t.paragraphs()]:
        t = nfkc(q.plain()).strip()
        if RE_FIGCAP.match(t) or RE_TABCAP.match(t):
            caps.append(f"「{q.plain().strip()[:20]}」")
    return "".join(caps) or "キャプションなし"


def float_ids(plan, info) -> str:
    """浮動配置の図形の中身を出力した図・表の ID（F1、T2 など。「・」でつなぐ）。表のセルの画像とキャプションで組んだ図、
    表のない表キャプションも（キャプションのない図には ID がないので出ない）。レポート・Colab・コマンドラインで、XML の中の
    図表を示すのに使う。"""
    paras = {id(q) for q in info.paras} | {id(q) for t in info.tables for q in t.paragraphs()}
    tables = {id(t) for t in info.tables}
    ids = [f.fid for f in plan.figures if f.fid and (
        any(id(q) in paras for q in f.image_paras + ([f.caption] if f.caption is not None else []))
        or any(id(t) in tables for t in f.tables))]
    ids += [t.tid for t in plan.tables if (t.table is not None and id(t.table) in tables)
            or (t.caption is not None and id(t.caption) in paras)]
    return "・".join(ids)


def float_targets(plan, info) -> str:
    """浮動配置の図形の中身を出力した XML の要素の説明（手作業で移す図表の知らせ。レポート・Colab・コマンドラインで使う）。

    図・表の ID（float_ids）と、図形の中身から本文の段落として出した段落（画像と文字が同じ段落の文字など。図の直後に出す）。
    ID のある図表か段落があれば、キャプションのない図（ID がない）も数える（知らせどおりに移したときに、図形の中身が仮の位置に
    残らないように）。例: 「F1・F2 と段落「説明文：左のセルの画像と同じ段」」「F1 とキャプションのない図」「段落「…」」。
    どれもなければ（キャプションのない図だけのときなど）空文字で、呼び出し側は「図表の中身」と示す。
    """
    mine = {id(q) for q in info.paras} | {id(q) for t in info.tables for q in t.paragraphs()}

    def walk(nodes):
        for node in nodes:
            if isinstance(node, Sec):
                yield from walk(node.children)
            else:
                yield node

    nodes = list(walk(plan.body))
    nocap = sum(1 for n in nodes if isinstance(n, FigNode) and not n.fid and any(id(q) in mine for q in n.image_paras))
    paras = [q for n in nodes if not isinstance(n, (FigNode, TableNode)) for q in Classifier.node_paras(n) if id(q) in mine]
    ids = float_ids(plan, info)
    items = [ids] if ids else []
    if ids or paras:
        if nocap:
            items.append("キャプションのない図" + (f" {nocap} つ" if nocap > 1 else ""))
        if paras:
            items.append("段落" + "".join(f"「{_para_text(q).strip()[:20]}」" for q in paras))
    out = ""
    for item in items:
        out += ((" と" if out[-1].isascii() else "と") + item) if out else item
    return out


def same_place(flat, provisional) -> tuple:
    """本文の要素の列 flat の要素ごとに、同じ置き場所の、すぐ前・すぐ後ろの要素の位置（なければ None）。戻り値: (前, 後ろ)。

    置き場所は、位置を決められない図表（仮の位置に置いた図形）の中身なら仮に置いた位置（provisional: 要素の id -> 置き場所。
    同じ位置に仮に置いた図形の中身は同じ値）、囲み（BoxNode）なら BOX_PLACE、それ以外（図形の外の要素と、位置の決まった
    図形の中身）は ""。仮に置いた図形の中身は本当はそこにないので、図表の組み立てで前後を見るときは、同じ置き場所の要素だけを
    見る（Classifier.assemble_floats・build_body）。同じ位置に仮に置いた図形の中身どうし（同じ段落に結び付いた、画像だけの
    図形とキャプションだけの図形など）は隣り合う要素として見る。囲みは、図形の外の要素の前後に数えない（間に囲みがあっても、
    画像と図キャプションは隣り合う要素として見る。0.24.1 までは囲みの文字を除外していて、要素の列になかった）。
    """
    n = len(flat)
    here = [provisional.get(id(b), "") for _, b in flat]
    prev, nxt, last = [None] * n, [None] * n, {}
    for k in range(n):
        prev[k] = last.get(here[k])
        last[here[k]] = k
    last = {}
    for k in range(n - 1, -1, -1):
        nxt[k] = last.get(here[k])
        last[here[k]] = k
    return prev, nxt


# ----------------------------------------------------------------------------- roles
class Classifier:
    def __init__(self, doc, journal, overrides=None, placements=None, outside=None):
        self.doc = doc
        self.journal = journal
        self.mapping = journal.styles
        self.overrides = overrides or {}      # src -> role（AI 補完）
        # 浮動配置の図形・文字だけのテキストボックスの ID -> 配置の指定（AI 補完。ai_assist.float_placements）
        self.placements = placements or {}
        # 仮の位置に置いた図形の中身: 本文の要素（flat）の id -> 置き場所（仮に置いた位置。同じ位置に仮に置いた図形の中身は同じ値。
        # build_body）
        self.provisional = {}
        # 本文の外（引用文献・注・付記・謝辞・英文の部分）の段落に結び付いた図形: 図形の ID（浮動配置の図形の s1 など、
        # 文字だけのテキストボックスの x1 など）-> 領域（OUTSIDE_JA のキー）。1 回目の組み立ての build_back・build_front_en が
        # 記録し、2 回目の組み立て（classify）では split_regions がその中身を本文の最後に回す（修正計画の N7）
        self.outside = dict(outside or {})
        self.box_members = {}       # テキストボックスの ID -> その最上位の要素 [(段落・表, 役割)]（run。AI の exclude を除く）
        self._top, self._top_index = [], {}     # 図形の外の最上位の段落・表の列と、段落 ID -> その位置（near_image）
        self._heading_by_text = {}      # 後付けの見出しの段落 ID -> 文字から推定した見出しか（back_heading_by_text。replace_back が使う）
        self._loose_affs, self._loose_used = [], True   # 和文の所属の段落で、まだ著者名に付いていないもの（build_front_ja）と、付いたか
        self.plan = ArticlePlan(lang=journal.lang)

    def style_role(self, para: Para) -> Optional[str]:
        sid = para.style_id
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            st = self.doc.styles.get(sid)
            if st is None:
                break
            if st.name in self.mapping:
                return self.mapping[st.name]
            sid = st.based_on
        return None

    def role_of(self, para: Para) -> str:
        if para.src in self.overrides:
            para.role_origin = "ai"
            return self.overrides[para.src]
        r = self.style_role(para)
        para.role_origin = "style" if r and r != "normal" else ""
        return r or "normal"

    # 推定の補助
    @staticmethod
    def all_bold(para: Para) -> bool:
        texts = [a for a in para.atoms if a.kind == "text" and a.text.strip()]
        return bool(texts) and all("bold" in a.fmt for a in texts)

    def guess_heading(self, para: Para, strict: bool) -> Optional[str]:
        t = _para_text(para).strip()
        if not t or "。" in t or any(a.kind != "text" for a in para.atoms):
            return None
        if strict and not self.all_bold(para):
            return None
        if RE_HEAD1.match(t):
            return "sec1"
        if RE_HEAD2.match(t):
            return "sec2"
        if RE_HEAD3.match(t):
            return "sec3"
        return None

    # ----------------------------------------------------------------- main
    def run(self) -> ArticlePlan:
        plan = self.plan
        flat = []   # (block, role)
        for b in self.doc.blocks:
            if isinstance(b, Table):
                flat.append((b, "table"))
                for p in b.paragraphs():
                    plan.paras[p.src] = p
            else:
                plan.paras[b.src] = b
                flat.append((b, self.role_of(b)))
        for kind, notes in (("footnote", self.doc.footnotes), ("endnote", self.doc.endnotes)):
            for nid, paras in notes.items():
                for p in paras:
                    plan.paras[p.src] = p
                    plan.note_of[p.src] = note_key(kind, nid)

        kept = []
        for b, role in flat:
            if role == "exclude":
                plan.exclude(b, "AI 補完で、論文の本文ではない（テンプレートの装飾など）と判断")
                plan.region[b.src] = "excluded"
                continue
            kept.append((b, role))
        flat = kept
        # 文字だけのテキストボックスの判定（text_only・near_image）に使う: テキストボックスごとの最上位の要素と、図形の外の
        # 最上位の段落・表の並び
        for b, role in flat:
            if b.textbox_id:
                self.box_members.setdefault(b.textbox_id, []).append((b, role))
        self._top = [b for b in self.doc.blocks if not in_shape(b)]
        self._top_index = {b.src: k for k, b in enumerate(self._top) if isinstance(b, Para)}
        regions = self.split_regions(flat)
        self.build_front_ja(regions["front_ja"])
        self.build_body(regions["body"])
        self.build_back(regions["back"])
        self.build_front_en(regions["front_en"])
        self.attach_word_notes()
        self.assign_ids()
        self.joined_styles()
        return plan

    def joined_styles(self):
        """段落記号の削除でつないだ段落のうち、段落のスタイルが違うもの（docx_reader の JoinInfo）を判断の一覧に記録する。

        今の判断の番号を変えないように、組み立ての最後に足す（つないだ段落のない原稿では何も足さない）。
        """
        def name(sid):
            st = self.doc.styles.get(sid)
            return st.name if st is not None else (sid or "スタイルなし")
        for j in self.doc.joins:
            names = "」「".join(dict.fromkeys(name(s) for s in j.style_ids))
            self.plan.decide(
                "mechanical", "style", j.src,
                f"変更履歴で段落記号が削除された {'・'.join(j.srcs)} を、1 つの段落 {j.src} につないだ（Word で変更をすべて承諾した"
                f"状態）。段落のスタイルが違う（「{names}」）ので、文字のある最初の段落（すべて空なら最後の段落）のスタイル"
                f"「{name(j.used)}」にした（Word で承諾した後のスタイルと同じかは確かめていない。Word で変更をすべて承諾した後の"
                "この段落のスタイル〈見出しか本文かなど〉を確かめ、違えば、Word で承諾して保存してから変換し直す）")

    def table_roles(self, t: Table) -> set:
        return {self.role_of(p) for p in t.paragraphs()}

    def split_regions(self, flat):
        """ブロックを領域（和文の冒頭・本文・後付け・英文の部分）に分ける。

        領域は、段落の役割（スタイル）と文字から、図形の外のブロックだけで決める。図形（テキストボックス・グループ図形）の
        中の段落・表では状態を変えず（図形の中のセクション区切りでも切り替えず）、その時点の領域に入れる。テキストボックスの
        中の「英文要旨」スタイルの段落や「注」だけの段落で、以降の本文と引用文献が英文要旨や注に入るのを防ぐため。
        図形の中身は結び付いている段落（アンカー段落）の後ろに並ぶので、アンカー段落と同じ領域に入る。ただし、アンカー段落が
        和文の冒頭の最後の段落（セクション区切り）なら、切り替えた後の本文に入る（テンプレートの冒頭に図形はないので、本文の
        中身とみなす）。図形の中の題目の段落は「題目を見た」ことにする（題目をテキストボックスに入れた原稿でも、冒頭の最後の
        セクション区切りで本文に切り替えるため）。
        図形の外の、空白だけの段落（画像のある段落は含まない）は、スタイルが後付けの見出し・英文要旨でも領域を切り替えず、注の節の推定
        （fn_guess・fn_guess_span）も動かさず、その時点の領域に入れる（C041。本文から後付け・和文の冒頭から後付け・英文の部分へ切り替える
        はずだったときは、判断の一覧に記録する）。ただし、後ろの最初の中身がその見出しの中身の役割（引用文献の見出しなら参考文献、
        注の見出しなら注本文。blank_heading_leads）なら、今までどおり切り替える。後付けの中の節の切り替え（build_back）も同じ規則。
        本文の外の段落に結び付いた図形（self.outside。2 回目の組み立て）の中身は、その時点の領域にかかわらず、本文の最後に
        回す（docx の順。領域は変えない。修正計画の N7）。
        本文スタイルの「注」だけの段落（表の注の見出しなど）は、文字から注の見出しと推定して後付けに切り替える（back_heading_by_text）が、
        引用文献・付記・謝辞などの見出しが続く前に、見出しのスタイルの段落（スタイルから決まった sec1・sec2・sec3）が現れ、かつ
        その段落が資料の見出し（appendix_heading）でなければ、注の節ではなく本文の続きとして、その「注」の段落から見出しの前までを
        本文に戻し、判断の一覧に記録して要確認で知らせる（点検の K5・F10・G2。fn_guess）。「注」の直後が注の番号で始まるか
        （note_list_follows）は戻すかどうかの条件にせず、知らせの文に使うだけにする（注の番号で始まる表の注〈「1) 数値は平均である。」〉
        の後ろに章見出しが続く原稿も戻す）。資料の見出しが続いたときは、今までどおり注の節として扱う。文字から推定した注の節の中に
        注の一覧に見えない段落が続いたまま後付けの見出し（または文書の終わり）に着いたときは、注の節として扱ったまま、要確認で
        知らせる（plan.fn_guess_checks。check_fn_guess）。ブロックは段落でも表でもよい（表の識別子は tid。block_id）。
        文字から注の見出しと推定した「注」ごとに、その段落を「注見出し」スタイルにしたときに注の一覧に入る段落を plan.fn_guess_span に
        記録する（feed_fn_span。助言が言う範囲）。文字から注の見出しと推定される「注」の段落はすべて plan.fn_guess_notes に記録する
        （「注」が 2 つ以上あるときの助言に使う。構造は変えない）。
        """
        regions = {"front_ja": [], "body": [], "back": [], "front_en": []}
        state = "front_ja"
        seen_title = False
        # 本文から後付けへの切り替えが、文字から推定した注の見出し（本文スタイルの「注」だけの段落。表の注の見出しなど）によるとき、
        # その段落の regions["back"] の中の位置。後付けの見出しが続けば本当の注の節（None に戻す。注の番号で始まらない段落が続いた
        # ままなら要確認で知らせる）、見出しのスタイルの段落が先に現れ、それが資料の見出しでなければ、注の節ではなく本文の続き
        # だったとして本文に戻す（K5・F10・G2）
        fn_guess = None
        # 文字から注の見出しと推定した「注」の段落 ID → その後ろが今、注の節の中か（その段落を「注見出し」スタイルにしたとき、
        # 後ろの段落が注の節に入るかを数えている間。plan.fn_guess_span。feed_fn_span）。英文の部分に切り替わると数えるのをやめる
        fn_open = {}
        for k, (b, role) in enumerate(flat):
            # 図形の外の、空白だけの段落（画像のある段落は含まない）。スタイルが後付けの見出し・英文要旨でも領域を切り替えず、
            # 注の節の推定（fn_guess）も動かさず、その時点の領域に入れる（C041。本文の途中の空行のスタイルで、後ろの本文が
            # 引用文献・注・英文要旨になるのを防ぐ）。ただし、後ろの最初の中身がその見出しの中身の役割なら、今までどおり切り替える
            # （後付けの見出しのスタイルが空の段落の直後に、参考文献スタイルの文献・注本文スタイルの注が続く原稿）
            blank_para = (isinstance(b, Para) and b.is_blank and not in_shape(b)
                          and not (self.blank_heading_leads(role, flat[k + 1:], False)))
            if fn_open and not in_shape(b):
                self.feed_fn_span(fn_open, b, role, blank_para)
            if (state in ("body", "back") and isinstance(b, Para) and not in_shape(b) and role not in BACK_HEADINGS
                    and self.back_heading_by_text(b, role) == "fn_heading"):
                self.plan.fn_guess_notes.append(b.src)        # 記録だけ（助言に添える。fn_guess_notes）
            if fn_guess is not None and state == "back" and not in_shape(b) and not blank_para:
                if role in BACK_HEADINGS or (isinstance(b, Para) and self.back_heading_by_text(b, role) not in (None, "fn_heading")):
                    self.check_fn_guess(regions["back"][fn_guess:], f"後ろの後付けの見出し {block_id(b)}")    # 引用文献・付記・謝辞などの見出しが続く: 本当の注の節
                    fn_guess = None
                elif role in HEADING_LEVEL and isinstance(b, Para) and not appendix_heading(_para_text(b)):
                    listed = self.note_list_follows(regions["back"][fn_guess + 1:])      # 知らせの文の材料（戻すかどうかには使わない）
                    moved = regions["back"][fn_guess:]
                    del regions["back"][fn_guess:]
                    regions["body"].extend(moved)
                    state, fn_guess = "body", None
                    head = moved[0][0]
                    kind = {"sec1": "章", "sec2": "節", "sec3": "項"}[role]
                    after = ("「注」の直後は注の番号で始まるが、注の番号で始まる表の注の可能性もあるため" if listed
                             else "「注」の直後が注の番号で始まらないため")
                    self.plan.decide(
                        "mechanical", "style", head.src,
                        f"本文スタイルの段落「{_para_text(head).strip()[:20]}」を、文字から注の見出しと推定して後付けに切り替えたが、"
                        f"後ろに{kind}見出しのスタイルの段落 {b.src}「{_para_text(b).strip()[:20]}」が続き、資料の見出しではなく、{after}、"
                        f"注の節ではなく本文の続き（表の注の見出しなど）とみなし、この段落から{kind}見出しの前までの {len(moved)} "
                        "ブロックを本文に戻した")
                    # 戻した範囲の、注の番号で始まる段落（本当の注の一覧かもしれない。知らせの文に件数と抜粋を出す。H7）
                    numbered = [x.src for x, _ in moved[1:] if isinstance(x, Para) and not in_shape(x) and self.note_starts(x)]
                    if numbered:
                        self.plan.fn_guess_numbered[head.src] = numbered
                    self.plan.fn_guess_checks.append(
                        (head.src, "returned", f"{len(moved)} ブロックを本文に戻した（後ろの{kind}見出し {b.src}）"
                         + (f"。戻した範囲に注の番号で始まる段落が {len(numbered)} 件ある" if numbered else "")))
            if in_shape(b) and self.outside and ((b.float_id and b.float_id in self.outside)
                                                 or (b.textbox_id and b.textbox_id in self.outside)):
                regions["body"].append((b, role))
                continue
            if in_shape(b):
                seen_title = seen_title or (state == "front_ja" and role == "title")
                regions[state].append((b, role))
                continue
            troles = self.table_roles(b) if isinstance(b, Table) else set()
            if blank_para and (role in FRONT_EN_ROLES or (role in BACK_HEADINGS and state in ("front_ja", "body"))):
                if state in ("front_ja", "body"):
                    self.plan.decide(
                        "mechanical", "style", b.src,
                        f"空白だけの段落のスタイル「{b.style_name}」は、{'英文の部分' if role in FRONT_EN_ROLES else '後付け'}の"
                        "始まりを示すが、空白だけの段落なので領域を切り替えなかった（後ろの段落は、今の領域のまま）")
            elif role in FRONT_EN_ROLES or troles & {"author_en", "aff_en"}:
                state = "front_en"
            elif state == "front_ja":
                if role in FRONT_JA_ROLES or troles & FRONT_JA_ROLES:
                    seen_title = seen_title or role == "title"
                elif role in BODY_ROLES and not (role == "p" and b.is_blank):
                    state = "body"
                elif role in BACK_HEADINGS:
                    state = "back"
                elif role == "normal" and isinstance(b, Para) and self.guess_heading(b, strict=False):
                    state = "body"
                elif isinstance(b, Table) and seen_title and not troles & FRONT_JA_ROLES:
                    state = "body"
            elif state == "body":
                guess = None if role in BACK_HEADINGS or not isinstance(b, Para) else self.back_heading_by_text(b, role)
                if role in BACK_HEADINGS or guess:
                    state = "back"
                    if guess == "fn_heading":
                        fn_guess = len(regions["back"])
                        fn_open[b.src] = True
                        self.plan.fn_guess_span[b.src] = []
            if state != "back":
                if fn_guess is not None:
                    self.check_fn_guess(regions["back"][fn_guess:], f"後ろの英文の部分 {block_id(b)}")      # 英文の部分に切り替わった
                fn_guess = None
            regions[state].append((b, role))
            if state == "front_ja" and isinstance(b, Para) and b.section_break and seen_title:
                state = "body"
        if fn_guess is not None and state == "back":
            self.check_fn_guess(regions["back"][fn_guess:], "文書の終わり")       # 後付けの見出しが続かないまま文書が終わった
        return regions

    def blank_heading_leads(self, role, rest, in_back) -> bool:
        """空白だけの段落（役割 role。後付けの見出し・英文の部分の役割）の後ろ rest（[(段落・表, 役割)]）が、その見出しの中身で始まるか。

        図形の外の、空白だけでない最初の段落（表なら最初の空白だけでない段落）の役割で決める: 引用文献の見出しなら参考文献の役割（ref）、
        注の見出しなら注本文の役割（fn）、英文の部分の役割なら英文の部分の役割。付記・謝辞の見出しの中身には決まった役割がないので、
        本文などの途中（in_back が偽）では切り替えない。後付けの中（in_back が真）では、ほかの節の中身の役割（ref・fn）でなければ
        切り替える（後ろの文献が付記・謝辞に入るのを防ぐ）。見出しの役割でなければ偽。真のとき、空白だけの段落も、中身のある見出しと
        同じに領域を切り替える（C041 の守りの例外）。
        """
        if role not in FRONT_EN_ROLES and role not in BACK_HEADINGS:
            return False
        nxt = None
        for b, r in rest:
            if in_shape(b):
                continue
            if isinstance(b, Table):
                found = next((p for p in b.paragraphs() if not p.is_blank), None)
                if found is None:
                    continue
                r = self.role_of(found)
            elif b.is_blank:
                continue
            nxt = r
            break
        if nxt is None:
            return False
        if role in FRONT_EN_ROLES:
            return nxt in FRONT_EN_ROLES
        kind = BACK_HEADINGS[role]
        if kind in ("refs", "fn"):
            return nxt == {"refs": "ref", "fn": "fn"}[kind]
        return in_back and nxt not in ("ref", "fn")

    def feed_fn_span(self, fn_open, b, role, skip=False):
        """ブロック b（図形の外）を、文字から推定した「注」の段落（fn_open のキー）ごとの plan.fn_guess_span に足す。

        その「注」を「注見出し」スタイルにすると、後付けの領域は「注」から英文の部分まで続き、build_back が段落を分ける:
        後付けの見出し（役割かテキストから決まるもの）に着くと、その節に切り替わる。注の見出し（別の「注」の段落）は見出しとして注の節に
        戻るだけで、注の一覧の段落には入らない。注の節の中の段落（空白だけの段落と表を除く）が、助言が言う「注の節に入る段落」。
        英文の部分に切り替わる段落・表からは数えない（fn_open を空にする）。
        """
        if skip:
            return          # 領域を切り替えない空白だけの段落（blank_para。split_regions）は、注の節の数え方も変えない
        if role in FRONT_EN_ROLES or (isinstance(b, Table) and self.table_roles(b) & {"author_en", "aff_en"}):
            fn_open.clear()
            return
        if not isinstance(b, Para):
            return
        heading = role if role in BACK_HEADINGS else self.back_heading_by_text(b, role)
        if heading:
            for head in fn_open:
                fn_open[head] = heading == "fn_heading"
        elif not b.is_blank:
            for head, in_fn in fn_open.items():
                if in_fn:
                    self.plan.fn_guess_span[head].append(b.src)

    def note_lead(self, b: Para) -> tuple:
        """注の一覧の中の段落 b の、新しい注の始まりを示す番号: (Word の自動番号の注の番号、手で打った番号、上付きの数字)。どれもなければ
        すべて None（前の注の続きの段落）。build_back が注を分けるときと、split_regions が注の一覧に見えるかを確かめるときに使う。"""
        auto = note_mark(b.autonum) if b.autonum else None
        mark = None if auto else note_mark(b.plain())
        sup_lead = None
        if not (auto or mark) and b.atoms and b.atoms[0].kind == "text" and "sup" in b.atoms[0].fmt:
            sup_lead = re.match(r"^[\s\u3000]*([0-9０-９]+)", b.atoms[0].text)
        return auto, mark, sup_lead

    def note_starts(self, b) -> bool:
        """段落 b が新しい注の始まり（注の番号で始まる。AI の fn_start の指定を含む）か。"""
        if not isinstance(b, Para):
            return False
        return any(self.note_lead(b)) or self.overrides.get(b.src) == "fn_start"

    def note_list_follows(self, items) -> bool:
        """文字から推定した「注」の段落の後ろの items（[(段落・表, 役割)]）の、図形の中と空白だけの段落を除く最初の段落が、注の番号で
        始まるか（注の一覧が続くか）。items が空・最初が表・番号で始まらない段落なら False。"""
        for b, _ in items:
            if in_shape(b) or (isinstance(b, Para) and b.is_blank):
                continue
            return self.note_starts(b)
        return False

    def check_fn_guess(self, items, where):
        """文字から推定した注の節 items（先頭が「注」の段落。[(段落・表, 役割)]）が、後付けの見出し・英文の部分・文書の終わり（where。
        文言）に着いたとき、注の一覧に見えない段落が残っていれば、注の節として扱ったまま plan.fn_guess_checks に記録する（要確認。F10）:
        「注」の直後が注の番号で始まらない（表の注のあとの本文が続いたままなど）か、見出しのスタイルの段落が混じっている。"""
        first = items[0][0]
        rest = [b for b, _ in items[1:] if not in_shape(b) and isinstance(b, Para) and not b.is_blank]
        no_list = not self.note_list_follows(items[1:])
        heads = [b for b, r in items[1:] if r in HEADING_LEVEL and not in_shape(b) and isinstance(b, Para)]
        if not rest or not (no_list or heads):
            return
        why = "「注」の直後が注の番号で始まらない" if no_list else f"見出しのスタイルの段落 {heads[0].src} が含まれる"
        plain = sum(1 for x in rest if not self.note_starts(x))
        self.plan.decide(
            "mechanical", "style", first.src,
            f"本文スタイルの段落「{_para_text(first).strip()[:20]}」を、文字から注の見出しと推定して後付けに切り替え、{where}までを注の節と"
            f"して扱った（{why}。注の番号で始まらない段落 {plain} 件を含む）。表の注の見出しなど、本文の続きなら、Word でその段落の"
            "スタイルを確かめる")
        self.plan.fn_guess_checks.append(
            (first.src, "kept", f"{where}まで {len(items)} ブロックを注の節として扱った（{why}）"))

    def back_heading_by_text(self, para: Para, role: str) -> Optional[str]:
        """スタイル違反の後付け見出し（「引用文献」を章見出しスタイルで書いた等）をテキストから推定。

        AI の補完が役割を指定した段落（overrides。後付けの見出しの役割 BACK_HEADINGS なら呼ぶ前に決まっている）は推定しない:
        「注」だけの段落に set_role の p を指定すれば、後付けの見出しと推定されない本文の段落にできる（表の注の見出しなど）。
        """
        if role not in ("sec1", "normal", "p") or para.src in self.overrides:
            return None
        t = nfkc(_para_text(para)).strip()
        if RE_REF_HEADING_TEXT.match(t):
            return "ref_heading"
        if RE_ACK_TEXT.match(t):
            return "ack_heading"
        if RE_NOTES_TEXT.match(t):
            return "notes_heading"
        if RE_FN_TEXT.match(t):
            return "fn_heading"
        return None

    # ----------------------------------------------------------------- front (ja)
    def build_front_ja(self, items):
        plan = self.plan
        self._loose_affs, self._loose_used = [], True
        for b, role in items:
            if isinstance(b, Table):
                if self.table_roles(b) & {"aff_ja", "author_ja"}:
                    self.read_author_table_ja(b)
                else:
                    for p in b.paragraphs():
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
                            plan.exclude(p, FRONT_TABLE_EXCLUDED)
                continue
            plan.region[b.src] = "front_ja"
            if role == "title":
                plan.title.append(b)
                plan.locations[b.src] = "題目"
            elif role == "subtitle":
                plan.subtitle.append(b)
                plan.locations[b.src] = "副題"
            elif role in ("aff_ja", "author_ja"):
                self.author_paragraph_ja(b, role)
            elif b.is_blank:
                plan.exclude_blank(b)
            else:
                plan.locations[b.src] = "冒頭部"
                why = (FRONT_DECORATION_EXCLUDED if front_decoration(b, self.journal.front_lines)
                       else FRONT_OTHER_EXCLUDED)
                plan.exclude(b, why)
        if self._loose_affs and not self._loose_used:
            self.aff_conflict(self._loose_affs, None, "loose")      # 最後の所属に著者名が続かない

    def read_author_table_ja(self, t: Table):
        current_affs, used = [], True       # 行の所属と、著者名に付いたか（付かないまま次の所属に置き換わると落ちる。K2）
        for row in t.rows:
            row_affs, row_names = [], []
            for c in row.cells:
                for blk in c.blocks:
                    paras = [blk] if isinstance(blk, Para) else list(blk.paragraphs())
                    for p in paras:
                        r = self.role_of(p)
                        # AI への依頼文にも載せる（確認のため。役割の変更は受け付けない）
                        self.plan.region[p.src] = "authors"
                        p.role = p.role or r
                        if p.is_blank:
                            self.plan.exclude_blank(p)
                            continue
                        if r == "aff_ja":
                            row_affs.append(p)
                        elif r == "author_ja":
                            row_names.append(p)
                        else:
                            self.plan.exclude(p, AUTHOR_TABLE_OTHER_EXCLUDED)
            if row_affs:
                if current_affs and not used:
                    self.aff_conflict(current_affs, row_affs[0], "table")
                current_affs, used = row_affs, False
            for n in row_names:
                self.add_author_ja(n, current_affs)
                used = True
        if current_affs and not used:
            self.aff_conflict(current_affs, None, "table")      # 表の最後の所属の行に著者名がない

    def author_paragraph_ja(self, p, role):
        if p.is_blank:
            self.plan.exclude_blank(p)
            return
        if role == "aff_ja":
            if self._loose_affs and not self._loose_used:
                self.aff_conflict(self._loose_affs, p, "loose")     # 著者名に付かないまま次の所属で置き換わる
            self._loose_affs, self._loose_used = [p], False
        else:
            self.add_author_ja(p, self._loose_affs)
            self._loose_used = True

    def aff_conflict(self, affs, by, where):
        """著者名に付かないまま捨てられる所属 affs（空白だけの段落は入らない）を、plan.structure_conflicts に記録する（K2）。

        by: それを置き換えた次の所属の段落（最後に著者名が続かないまま残った所属なら None）。where: "loose"（段落）か "table"（著者表）。
        """
        self.plan.structure_conflicts.append(
            StructureConflict("aff", [p.src for p in affs], by.src if by is not None else "", where=where))

    def add_author_ja(self, name_para, aff_paras):
        plan = self.plan
        a = Author(name_ja=name_para)
        plan.locations[name_para.src] = f"著者{len(plan.authors) + 1}（和文）"
        for ap in aff_paras:
            a.affs.append(self.aff_for(ja=ap))
        plan.authors.append(a)

    def aff_for(self, ja=None, en=None) -> Aff:
        plan = self.plan
        key_ja = _para_text(ja).strip() if ja else None
        for aff in plan.affs:
            if ja is not None and aff.ja is not None and _para_text(aff.ja).strip() == key_ja:
                if aff.ja is not ja:
                    plan.exclude(ja, f"重複する所属（{aff.ja.src} と同一の文字列のため 1 つにまとめた）")
                return aff
        aff = Aff(ja=ja, en=en)
        plan.affs.append(aff)
        if ja is not None:
            plan.locations[ja.src] = f"所属{len(plan.affs)}（和文）"
        return aff

    # ----------------------------------------------------------------- body
    def build_body(self, items):
        plan = self.plan
        order = {id(b): k for k, (b, _) in enumerate(items)}
        src_index = {b.src: k for k, (b, _) in enumerate(items) if isinstance(b, Para)}
        boxes_in = list(items)
        items, inserts, raw, prov = self.place_floats(items)
        # 文字だけのテキストボックス（囲み・図に重ねた注記）。差し込み位置は、place_floats と同じく元の items での位置
        box_inserts, taken = self.place_boxes(boxes_in, src_index, len(inserts))
        inserts += box_inserts
        items = [x for x in items if id(x[0]) not in taken]
        flat = []
        for b, role in items:
            # 位置を決められない図表のうち、中身をそのまま出すものの要素は、役割をここで決めてから、その図表の差し込みに入れる
            # （仮に置く位置。place_floats）
            out = raw.get(id(b), flat)
            if isinstance(b, Table):
                out.append(("table", b))
                for tp in b.paragraphs():
                    plan.region[tp.src] = "body"
                    tp.role = tp.role or "cell"
                continue
            plan.region[b.src] = "body"
            # 図表の入った図形の中の段落（文字だけのテキストボックスの段落は place_boxes で扱ったので、ここには来ない）
            if b.in_textbox and role not in ("fig_caption", "table_caption") and not b.images:
                cap = self.textbox_caption(b)
                if cap is None:
                    if b.is_blank:
                        plan.exclude_blank(b)      # 全角空白だけの段落も記録する（記録しないと出力漏れになる）
                    else:
                        plan.exclude(b, TEXTBOX_TEXT_EXCLUDED)
                    continue
                role = cap
                b.role_origin = "heuristic"
                kind = "図" if cap == "fig_caption" else "表"
                plan.decide("mechanical", "style", b.src,
                            f"テキストボックス内のスタイル「{b.style_name}」の段落「{_para_text(b)[:30]}」を"
                            f"{kind}キャプションと推定（「{kind}N」で始まる）")
            if b.is_blank:
                plan.exclude_blank(b)
                continue
            if role in ("normal", None) or role not in BODY_ROLES | {"table"}:
                guessed = self.guess_heading(b, strict=False)
                if guessed:
                    role = guessed
                    b.role_origin = "heuristic"
                    plan.decide("mechanical", "style", b.src,
                                f"スタイル「{b.style_name}」の段落「{_para_text(b)[:30]}」を"
                                f"{ {'sec1': '章', 'sec2': '節', 'sec3': '項'}[role]}見出しと推定（番号の形式から）")
                else:
                    role = "p"
                    b.role_origin = "heuristic"
                    b.note = "style_unknown"
            elif role == "p":
                guessed = self.guess_heading(b, strict=True)
                if guessed:
                    role = guessed
                    b.role_origin = "heuristic"
                    plan.decide("mechanical", "style", b.src,
                                f"本文スタイルの段落「{_para_text(b)[:30]}」を"
                                f"{ {'sec1': '章', 'sec2': '節', 'sec3': '項'}[role]}見出しと推定（全体が太字で番号の形式）")
            b.role = role
            out.append((role, b))

        # 配置を決めた浮動配置の図表を、決めた位置（items での位置）に差し込む。本文の最後（BODY_END）は最後に足す
        merged, pending = [], sorted(inserts, key=lambda x: (x[0], x[1]))
        for entry in flat:
            while pending and pending[0][0] <= order[id(entry[1])]:
                merged.extend(pending.pop(0)[2])
            merged.append(entry)
        for _, _, entries in pending:
            merged.extend(entries)
        flat = merged
        # 位置を決められない図表（仮の位置に置いた図形）の中身。本当はそこにないので、図表を組み立てるときに、その外の要素と
        # 組にしない（assemble_floats・table_for_figure）。置き場所は仮に置いた位置で、同じ位置に仮に置いた図形の中身どうし
        # （同じ段落に結び付いた、画像だけの図形とキャプションだけの図形など）は組にする
        self.provisional = {id(obj): f"@{target}" for target, entries in prov for _, obj in entries}
        # 囲み（文字だけのテキストボックス）も、図表を組み立てるときに隣の要素として数えない（0.24.1 までは文字を除外していて、
        # 要素の列になかった。画像と図キャプション、表キャプションと表などの間に囲みを置いても、0.24.1 と同じく組にする。
        # 図はキャプションの位置に組み立てるので、画像とキャプションの間にあった囲みは、キャプションが画像の後ろなら図の前、
        # 前なら図の後ろに出る。表は表キャプションと表の先に来る方の位置に組み立てるので、間の囲みは表の後ろに出る）
        for _, _, entries in box_inserts:
            for _, node in entries:
                self.provisional[id(node)] = BOX_PLACE

        # 本文スタイルのまま書かれた図表キャプションの推定（隣は同じ置き場所の要素。仮に置いた図形の中身とその外は隣にしない）
        before, ahead = same_place(flat, self.provisional)
        for k, (role, b) in enumerate(flat):
            if role != "p" or not isinstance(b, Para):
                continue
            t = nfkc(_para_text(b)).strip()
            if len(t) > 80 or t.endswith("。"):
                continue
            nxt = flat[ahead[k]] if ahead[k] is not None else (None, None)
            prv = flat[before[k]] if before[k] is not None else (None, None)
            if RE_TABCAP.match(t) and (nxt[0] == "table" or prv[0] == "table"):
                flat[k] = ("table_caption", b)
                b.role, b.role_origin = "table_caption", "heuristic"
                plan.decide("mechanical", "style", b.src, f"本文スタイルの段落「{t[:30]}」を表キャプションと推定（隣が表）")
            elif RE_FIGCAP.match(t) and (self.is_image_para(nxt[1]) or self.is_image_para(prv[1])):
                flat[k] = ("fig_caption", b)
                b.role, b.role_origin = "fig_caption", "heuristic"
                plan.decide("mechanical", "style", b.src, f"本文スタイルの段落「{t[:30]}」を図キャプションと推定（隣が画像）")

        nodes = self.assemble_floats(flat)
        plan.body = self.nest(nodes)
        self.compute_locations(plan.body, [])

    # ----------------------------------------------------------------- 浮動配置の図表
    def place_floats(self, items):
        """浮動配置の図形（テキストボックス・グループ図形）に入った図表を、本文のどこに置くかを決める。

        図を置く位置の規則は「Word で表示したときに、図の左上の直上にある本文の文章を含む段落の直後」。
        - AI の指定（placements）があれば、その組み合わせで、指定された段落の直後に置く。
        - なければ、図の左上がアンカー段落の左上の位置にあり（floats.at_anchor）、中身が単純（キャプション 1 つと本体 1 つ、
          表のセルに画像とキャプションが並ぶ図など。float_mechanical）な場合だけ、機械的にアンカー段落の前に置く。
        - どちらでもなければ「位置を決められない図表」として記録し、仮の位置に置く（利用者が手作業で移す。決定事項 21）。
          仮の位置は、アンカー段落のすぐ後ろ。AI が本文の外（注・引用文献など）の段落の後ろを指定したとき（ai_assist.float_placements
          の印 where="end"）と、アンカー段落が本文の段落でないとき（本文の外の段落に結び付いた図形。self.outside）は、本文の最後
          （provisional_target）。中身が単純なら図の本体とキャプションを組にし、そうでなければ中身をそのまま（これまでの扱いで。
          役割は build_body で決める）出す。
        - 本文の外（引用文献・注・付記・謝辞・英文の部分）の段落に結び付いた図形（修正計画の N7。2 回目の組み立てで、中身は
          split_regions が本文の最後に回している）は、図の左上の位置にかかわらず「位置を決められない図表」にする（決定事項 10）。
          グループ図形の画像は、アンカー段落（本文の外の段落）から集める。
        - 文字だけのテキストボックス（図表ではない図形）は、ここでは扱わない（place_boxes）。
        戻り値: (並べ直した items, [(items での位置, 同じ位置での順番, [(役割, 要素)])], 中身をそのまま出す図形の要素の id →
        その図形の差し込みの一覧, [(仮の位置に置いた図形の items での位置, その差し込みの一覧)])。items での位置は「その位置の要素の前」で、
        アンカー段落の後ろは アンカー段落の位置 + 1、本文の最後は BODY_END。同じ位置に置くものはキャプションの番号順（番号が
        なければ後ろ）、同じ番号なら docx の順
        """
        plan = self.plan
        src_index = {b.src: k for k, (b, _) in enumerate(items) if isinstance(b, Para)}
        plan.layout = getattr(self.doc, "layout", None)
        # 本文の段落（図形の中の段落〈浮動配置の図形・テキストボックス〉を除く。AI の after・行数の推定・仮の位置に使う）
        plan.body_seq = [b.src for b, _ in items if isinstance(b, Para) and not b.float_id and not b.textbox_id]
        body = set(plan.body_seq)
        members, group_imgs, roles = {}, {}, {}
        for b, role in items:
            if b.float_id:
                members.setdefault(b.float_id, []).append(b)
                roles[id(b)] = role
            elif isinstance(b, Para):
                for img in b.images:
                    if img.float_id:
                        group_imgs.setdefault(img.float_id, []).append(img)
        placed, inserts, raw, prov = set(), [], {}, []
        layout = plan.layout
        for fl in getattr(self.doc, "floats", []):
            outside = self.outside.get(fl.fid, "")      # アンカー段落が本文の外にある（N7）
            if fl.anchor_src not in src_index and not outside:
                continue
            blocks = members.get(fl.fid, [])
            imgs = group_imgs.get(fl.fid, [])
            if outside and not imgs:
                # グループ図形の画像は、アンカー段落（本文の外の段落。items にない）の中にある
                anchor = plan.paras.get(fl.anchor_src)
                imgs = [i for i in (anchor.images if anchor is not None else []) if i.float_id == fl.fid]
            info = FloatInfo(float=fl, paras=[b for b in blocks if isinstance(b, Para)],
                             tables=[b for b in blocks if isinstance(b, Table)], images=imgs)
            groups, others = self.float_captions(info.paras, roles)
            if not (info.images or info.tables or groups or any(q.images for q in info.paras)):
                continue        # 文字だけのテキストボックスは図表ではない（place_boxes で扱う。text_only と同じ判定）
            plan.floats[fl.fid] = info
            spec = self.placements.get(fl.fid)
            end = bool(spec) and spec.get("where") == "end"     # AI が本文の外の段落の後ろを指定した（本文の最後に仮に置く）
            if spec and not end and spec["after"] not in src_index:
                spec = None     # AI の役割の指定で、指定された段落が本文でなくなった
            if spec and not end:
                entries = self.float_from_spec(info, spec)
                target = src_index[spec["after"]] + 1
                info.mode = "ai"
            else:
                mech = at_anchor(fl, layout) and not end and not outside
                entries = self.float_mechanical(info, groups, others) if mech else None
                if entries is None:
                    info.mode = "unplaced"
                    if outside:
                        info.reason = f"図形が本文の外（{OUTSIDE_JA.get(outside, outside)}）の段落に結び付いている"
                    elif not at_anchor(fl, layout):
                        info.reason = why_not_at_anchor(fl, layout)
                    else:
                        info.reason = "中身の組み合わせ（図表の本体とキャプション）を機械的に決められない"
                    info.where, info.end_why, info.end_after, target = self.provisional_target(
                        fl, spec if end else None, src_index, body)
                    if info.where == "anchor":
                        # アンカー段落が箇条書き・引用の途中なら、その最後の段落の後ろにずらす（箇条書き・引用を 2 つに分けない）
                        last = self.run_end(items, target - 1)
                        info.after_src, target = items[last][0].src, last + 1
                    place = ("AI が本文の外の段落の後ろを指定したので、本文の最後に仮に置く" if info.end_why == "ai"
                             else f"指定がなければ{plan.float_place(fl.fid)}に仮に置く")
                    plan.decide("mechanical", "figure", fl.anchor_src,
                                f"テキストボックス・グループ図形 {fl.fid}（{self.float_summary(info)}）は、位置を機械的に"
                                f"決められない（{info.reason}）。AI による補完で位置を指定する必要がある（{place}）",
                                applied=False)
                    # 組み合わせは、中身が単純なら機械的に組む。単純でなければ中身をそのまま出す（build_body で役割を決めてから、
                    # この図形の差し込みに入れる）
                    entries = self.float_mechanical(info, groups, others)
                    if entries is None:
                        entries = []
                        for b in blocks:
                            raw[id(b)] = entries
                    else:
                        placed.update(id(b) for b in blocks)
                    inserts.append((target, (self.float_number(info), len(inserts)), entries))
                    prov.append((target, entries))
                    continue
                target = src_index[fl.anchor_src]
                info.mode = "mechanical"
                plan.decide("mechanical", "figure", fl.anchor_src,
                            f"テキストボックス・グループ図形 {fl.fid}（{self.float_summary(info)}）を、アンカー段落"
                            f"「{_para_text(plan.paras[fl.anchor_src])[:20]}」の前に置いた（図の左上がアンカー段落の左上の位置にあるため）")
            placed.update(id(b) for b in blocks)
            inserts.append((target, (self.float_number(info), len(inserts)), entries))
        rest = [(b, r) for b, r in items if id(b) not in placed]
        return rest, inserts, raw, prov

    # ----------------------------------------------------------------- 文字だけのテキストボックス（囲み・図に重ねた注記）
    def text_only(self, xid) -> bool:
        """テキストボックス xid が文字だけのテキストボックスか（place_boxes の対象。place_floats の「図表ではない」と同じ判定）。

        最上位の要素（self.box_members。AI の exclude を除いたもの）に、表・画像のある段落・図表キャプション（役割が
        fig_caption・table_caption か、textbox_caption の形）がなく、浮動配置の図形の中なら、その図形が図表の入った図形
        （plan.floats）でないもの。図表の入った図形（グループ図形を含む）の中のテキストボックスは、今までどおりその図表の
        一部として扱う（修正計画の F の (9)）。
        """
        members = self.box_members.get(xid, [])
        if not members:
            return False
        for b, role in members:
            if isinstance(b, Table) or b.images or role in ("fig_caption", "table_caption") or self.textbox_caption(b):
                return False
        fid = members[0][0].float_id
        return not (fid and fid in self.plan.floats)

    def outside_key(self, b) -> str:
        """本文の外の領域（後付け・英文の部分）の要素 b が、その領域の段落として扱わない図形の中身なら、その図形の ID（浮動配置の
        図形の ID か、浮動配置でない文字だけのテキストボックスの ID）。そうでなければ ''（修正計画の N7）。

        浮動配置でない（行内・VML の）テキストボックスで、キャプション・画像・表のあるものは、今までどおりその領域の段落にする。
        """
        if b.float_id:
            return b.float_id
        if b.textbox_id and self.text_only(b.textbox_id):
            return b.textbox_id
        return ""

    def near_image(self, tb) -> bool:
        """テキストボックス tb（model.TextBox）が画像の近くにあるか（floats.textbox_kind）。

        グループ図形・描画キャンバスの中なら真。そうでなければ、アンカー段落とその前後 NEAR_PARAS 個の、図形の外の最上位の段落に、
        画像（行内・浮動配置・Word の図形。隠し文字の画像はアトムにならないので数えない）か、図キャプション（キャプションの
        スタイル、または「図N」で始まり「。」で終わらない 80 字以下の段落）があるか、画像のある浮動配置の図形が結び付いているとき。
        """
        if tb.group:
            return True
        k = self._top_index.get(tb.anchor_src)
        if k is None:
            return False
        figs = {img.float_id for img in getattr(self.doc, "images", []) if img.float_id and not img.hidden}
        fig_anchors = {fl.anchor_src for fl in getattr(self.doc, "floats", []) if fl.fid in figs}
        for b in self._top[max(0, k - NEAR_PARAS):k + NEAR_PARAS + 1]:
            if not isinstance(b, Para):
                continue
            if b.images or b.src in fig_anchors:
                return True
            t = nfkc(_para_text(b)).strip()
            if self.style_role(b) == "fig_caption" or (RE_FIGCAP.match(t) and len(t) <= 80 and not t.endswith("。")):
                return True
        return False

    def box_children(self, paras, roles) -> list:
        """囲みの中の段落（空白だけの段落を除く）を、本文と同じ要素にする: 引用のスタイルの段落は QuoteNode（続けば 1 つ）、別行数式は
        FormulaNode、自動番号の段落は同じ番号の定義が続く間 ListNode、それ以外（見出しのスタイルの段落も）は PNode。
        boxed-text の中に sec は作らない（J-STAGE の boxed-text の子に sec はない）。"""
        out = []
        for p in paras:
            if roles.get(id(p)) == "quote":
                self._take(p, "quote")
                if out and isinstance(out[-1], QuoteNode):
                    out[-1].paras.append(p)
                else:
                    out.append(QuoteNode(paras=[p]))
                continue
            self._take(p, "p")
            fnode = self.formula_node(p)
            if fnode:
                out.append(fnode)
            elif p.numbering and p.autonum:
                if out and isinstance(out[-1], ListNode) and out[-1].items[-1].numbering[0] == p.numbering[0]:
                    out[-1].items.append(p)
                else:
                    out.append(ListNode(items=[p], ordered=not self.doc_numbering_is_bullet(p)))
            else:
                out.append(PNode(p))
        return out

    def place_boxes(self, items, src_index, start=0):
        """文字だけのテキストボックスの扱いと置き場所を決める（place_floats とは別のパス。doc.textboxes を出現順に回す）。

        items は place_floats に渡したものと同じ本文の要素の列、src_index はその段落 ID -> 位置。種類は floats.textbox_kind
        （AI の指定〈placements の kind box・label〉があればそれ）で決める:
        - 空白だけ（blank）: 空白だけの段落を exclude_blank するだけ（判断も知らせも出さない）。
        - 図に重ねた注記（label）: 文字のある段落を理由付きで除外し、判断の一覧とアンカー段落ごとの警告（10 章。AI の判断なら
          AI の判断と分かる別の警告）に記録する（本文の文字なら、AI が placements の kind box で囲みに戻せる。
          ai_assist._box_placement_problem。暫定の判断）。
        - 決められない（undecided）: 文字のある段落を理由付きで除外し、判断の一覧に記録する（applied=False。要確認の知らせは
          report._textbox_undecided_action）。
        - 囲み（box）: BoxNode（<boxed-text>）にして、置く位置（items での位置）に差し込む。図の左上がアンカー段落の左上に
          ある浮動配置（floats.at_anchor）はアンカー段落の前。行内（wp:inline・位置指定のない VML）はアンカー段落の後ろ。それ以外
          （位置を指定した浮動配置・VML の position:absolute）は、位置を推定してアンカー段落の後ろ（要確認）。アンカー段落が
          箇条書き・引用の途中なら、その終わりの後ろ（run_end）。アンカー段落が本文の外（N7）なら本文の最後（要確認）。
          アンカー段落が本文の要素にない（和文の冒頭の最後のセクション区切りの段落など）なら、テキストボックスの最初の段落の
          位置（要確認）。AI の指定（kind box）は、指定の段落の後ろ（ずらさない）。
        どの種類でも、空白だけの段落は exclude_blank する。戻り値: (差し込みの一覧〈place_floats と同じ形。同じ位置の図表の後ろ〉,
        扱ったテキストボックスの要素の id の集合〈build_body の役割の決め方に流さない〉)。
        """
        plan = self.plan
        layout = plan.layout
        roles = {id(b): r for b, r in items}
        pos = {id(b): k for k, (b, _) in enumerate(items)}
        floats = {fl.fid: fl for fl in getattr(self.doc, "floats", [])}
        inserts, taken, labels = [], set(), {}     # labels: (アンカー段落, AI の判断か) -> 図に重ねた注記と判断した ID
        for tb in getattr(self.doc, "textboxes", []):
            members = [b for b, _ in items if b.textbox_id == tb.xid]
            if not members or not self.text_only(tb.xid):
                continue        # 表のセル・冒頭・資料の中など本文の要素にないもの、図表の入った図形の中のもの（今までどおり）
            taken.update(id(b) for b in members)
            paras = [b for b in members if isinstance(b, Para)]
            texts = [p for p in paras if not p.is_blank]
            for p in paras:
                plan.region[p.src] = "body"
                if p.is_blank:
                    plan.exclude_blank(p)       # 全角空白だけの段落も記録する（文字のまったくない段落は記録しない）
            fl = floats.get(tb.float_id) if tb.float_id else None
            info = BoxInfo(box=tb, paras=paras, float=fl,
                           outside=self.outside.get(tb.float_id, "") if tb.float_id else self.outside.get(tb.xid, ""))
            plan.textboxes[tb.xid] = info
            chars = sum(len(re.sub(r"\s", "", p.plain())) for p in paras)
            if not chars:
                info.kind, info.why = "blank", "空白だけ"
                continue
            spec = self.placements.get(tb.xid)
            if spec and spec.get("kind") == "box" and spec.get("after") not in src_index:
                spec = None     # AI の役割の指定で組み直した後に、指定された段落が本文の段落でなくなった
            info.near = self.near_image(tb)
            kind, info.why = textbox_kind(chars, tb.width_cm, box_lines(texts, tb.width_cm, layout), info.near, tb.group, layout)
            info.kind, info.mode = (spec["kind"], "ai") if spec else (kind, "mechanical")
            head = f"「{_para_text(texts[0]).strip()[:20]}」" + (f"など {len(texts)} 段落" if len(texts) > 1 else "")
            what = f"テキストボックス {tb.xid}（{head}）"
            if info.kind == "label":
                reason = TEXTBOX_AI_LABEL_EXCLUDED if spec else TEXTBOX_LABEL_EXCLUDED
                for p in texts:
                    plan.exclude(p, reason)
                if spec:
                    plan.float_decisions[tb.xid] = plan.decide(
                        "ai", "box", tb.anchor_src, f"{what}を図に重ねた注記と判断し、本文から除外した。{spec.get('reason', '')}",
                        spec.get("confidence", ""))
                else:
                    plan.decide("mechanical", "box", tb.anchor_src, f"{what}を図に重ねた注記と判断し、本文から除外した（{info.why}）")
                labels.setdefault((tb.anchor_src, bool(spec)), []).append(tb.xid)
                continue
            if info.kind == "undecided":
                for p in texts:
                    plan.exclude(p, TEXTBOX_UNDECIDED_EXCLUDED)
                plan.decide("mechanical", "box", tb.anchor_src,
                            f"{what}は、囲みか図の注記か決められない（{info.why}）。本文から除外した（AI による補完の placements で"
                            " kind box・label を指定できる）", applied=False)
                continue
            # 囲み（boxed-text）
            node = BoxNode(xid=tb.xid, children=self.box_children(texts, roles))
            anchor = plan.paras.get(tb.anchor_src)
            anchor_head = _para_text(anchor).strip()[:20] if anchor is not None else tb.anchor_src
            if spec:
                target = src_index[spec["after"]] + 1
                info.where, info.after_src = "ai", spec["after"]
                after = plan.paras.get(spec["after"])
                # 機械的な判定を変えたときは、それも書く（図に重ねた注記とみなしたものを、AI が本文の囲みに戻したときなど）
                was = {"label": "（機械的には図に重ねた注記と判断していた）",
                       "undecided": "（機械的には囲みか図の注記か決められなかった）"}.get(kind, "")
                plan.float_decisions[tb.xid] = plan.decide(
                    "ai", "box", spec["after"],
                    f"{what}を囲み（boxed-text）として段落「{_para_text(after).strip()[:20] if after else spec['after']}」の後に"
                    f"置いた{was}。{spec.get('reason', '')}", spec.get("confidence", ""))
            elif info.outside:
                target, info.where, info.estimated = BODY_END, "end", True
                info.place_why = f"アンカー段落が本文の外（{OUTSIDE_JA.get(info.outside, info.outside)}）にある"
                plan.decide("mechanical", "box", tb.anchor_src,
                            f"{what}を囲み（boxed-text）とし、{info.place_why}ので、本文の最後に置いた（{info.why}。要確認）")
            elif tb.anchor_src not in src_index:
                target, info.where, info.estimated = pos[id(members[0])], "after", True
                info.place_why = "アンカー段落が本文の段落でない"
                prev = next((items[j][0].src for j in range(target - 1, -1, -1)
                             if isinstance(items[j][0], Para) and not in_shape(items[j][0])), "")
                info.after_src = prev
                plan.decide("mechanical", "box", tb.anchor_src,
                            f"{what}を囲み（boxed-text）とし、{info.place_why}ので、テキストボックスの位置（{plan.box_place(tb.xid)}）に"
                            f"置いた（{info.why}。要確認）")
            elif fl is not None and at_anchor(fl, layout):
                target, info.where, info.after_src = src_index[tb.anchor_src], "before", tb.anchor_src
                plan.decide("mechanical", "box", tb.anchor_src,
                            f"{what}を囲み（boxed-text）とし、アンカー段落「{anchor_head}」の前に置いた（{info.why}。"
                            "図の左上がアンカー段落の左上の位置にあるため）")
            else:
                last = self.run_end(items, src_index[tb.anchor_src])
                target, info.where, info.after_src = last + 1, "after", items[last][0].src
                if tb.inline:
                    plan.decide("mechanical", "box", tb.anchor_src,
                                f"{what}を囲み（boxed-text）とし、行内のテキストボックスなので、{plan.box_place(tb.xid)}に置いた"
                                f"（{info.why}）")
                else:
                    info.estimated = True
                    info.place_why = why_not_at_anchor(fl, layout) if fl is not None else "VML の position:absolute の位置指定"
                    plan.decide("mechanical", "box", tb.anchor_src,
                                f"{what}を囲み（boxed-text）とした。位置は docx から決められない（{info.place_why}）ので、"
                                f"{plan.box_place(tb.xid)}に置いた（{info.why}。要確認）")
            inserts.append((target, (BODY_END, start + len(inserts)), [("node", node)]))
        for (src, ai), xids in labels.items():
            what = _xid_list(xids)
            what += "" if what.endswith("）") else " "
            if ai:
                plan.warnings.append(f"{src}: AI が図に重ねた注記と判断したテキストボックス {what}の文字を、本文から除外しました"
                                     "（2 章・6 章）。図の注記でなく本文の文字（問題文など）なら、AI に出し直してもらうか、Word で"
                                     "文字をテキストボックスの外に出して変換し直してください")
            else:
                plan.warnings.append(f"{src}: 図に重ねた注記と判断したテキストボックス {what}の文字を、本文から除外しました（6 章）。"
                                     "図の注記でなく本文の文字（問題文など）なら、AI による補完で囲みに指定するか、Word で文字を"
                                     "テキストボックスの外に出して変換し直してください")
        return inserts, taken

    @staticmethod
    def provisional_target(fl, end_spec, src_index, body) -> tuple:
        """位置を決められない図表を仮に置く位置（決定事項 21）。戻り値: (where, end_why, end_after, items での差し込み位置)。

        - AI が本文の外（注・引用文献など）の段落の後ろを指定した（end_spec。ai_assist.float_placements の印）: 本文の最後
        - アンカー段落が本文の段落（body。plan.body_seq）でない（本文の外の段落に結び付いた図形。修正計画の N7。self.outside）:
          本文の最後
        - それ以外: アンカー段落のすぐ後ろ（AI の指定の after と同じ形）。アンカー段落が箇条書き・引用の途中なら、place_floats が
          その箇条書き・引用の最後の段落の後ろにずらす（run_end）
        """
        if end_spec:
            return "end", "ai", end_spec.get("after", ""), BODY_END
        if fl.anchor_src not in body:
            return "end", "anchor", "", BODY_END
        return "anchor", "", "", src_index[fl.anchor_src] + 1

    def list_or_quote(self, b, role):
        """本文の要素 b（items の役割 role）が、assemble_floats で前後の段落と 1 つにまとめる箇条書きの項目か引用の段落なら、
        その種類（引用は "quote"、箇条書きは ("list", 番号の定義の ID)）。そうでなければ None。

        役割は build_body と同じ考えで見る（役割の決まっていない段落・本文の段落のうち、見出しと推定するものは箇条書きにしない）。
        画像だけの段落（図になる）と別行数式の段落（数式になる）は、assemble_floats と同じく箇条書きの項目にしない（箇条書きは
        その前で終わる）。画像と文字が同じ段落の項目は、箇条書きの項目のまま。図形の中の段落（XML に出さないものもある）は、
        箇条書きにしない（迷うものは None。仮の位置をずらさないだけ）。
        """
        if not isinstance(b, Para) or in_shape(b):
            return None
        if role == "quote":
            return "quote"
        if not (b.numbering and b.autonum) or self.is_image_para(b) or self.formula_node(b) is not None:
            return None
        if role in ("normal", None, "") or role not in BODY_ROLES | {"table"}:
            heading = self.guess_heading(b, strict=False)
        elif role == "p":
            heading = self.guess_heading(b, strict=True)
        else:
            return None
        return None if heading else ("list", b.numbering[0])

    def run_end(self, items, k) -> int:
        """仮に置く位置のすぐ前の要素 items[k]（アンカー段落）が、続いた箇条書きの項目（同じ番号の定義）か引用の段落の途中に
        あれば、その並びの最後の段落の位置。そうでなければ k。

        位置を決められない図表をアンカー段落のすぐ後ろに仮に置くと、箇条書き・引用が 2 つに分かれ、図表を手作業で移しても
        分かれたまま残るため（assemble_floats は、続いた箇条書きの項目と引用の段落を 1 つの list・disp-quote にまとめる）。
        AI が指定した位置はずらさない。間の図形の中身と空白だけの段落は飛ばす（その位置には出力しない）。アンカー段落が空の
        段落なら、その前の要素で見る。
        """
        def skip(b):
            # 文字だけのテキストボックスの段落も、その位置には出力しない（place_boxes）。キャプションなどのある浮動配置でない
            # テキストボックスの段落は、その位置に出力するので飛ばさない（list_or_quote で止まる）
            return (bool(b.float_id) or (isinstance(b, Para) and b.is_blank)
                    or (bool(b.textbox_id) and self.text_only(b.textbox_id)))

        prev = next((j for j in range(k, -1, -1) if not skip(items[j][0])), None)
        want = self.list_or_quote(*items[prev]) if prev is not None else None
        if want is None:
            return k
        last = k
        for j in range(k + 1, len(items)):
            b, role = items[j]
            if skip(b):
                continue
            if self.list_or_quote(b, role) != want:
                break
            last = j
        return last

    @staticmethod
    def float_number(info) -> float:
        """浮動配置の図形の中の最初の図表番号（なければ無限大）。"""
        for q in info.paras + [c for t in info.tables for c in t.paragraphs()]:
            m = RE_FIGCAP.match(nfkc(_para_text(q)).strip()) or RE_TABCAP.match(nfkc(_para_text(q)).strip())
            if m:
                return int(nfkc(m.group(1)))
        return float("inf")

    def float_captions(self, paras, roles):
        """テキストボックスの段落からキャプションを探す。戻り値: ([(役割, [段落…])], キャプションでも画像でもない段落)"""
        groups, others = [], []
        prev_cap = False
        for p in paras:
            if p.is_blank or p.images:
                prev_cap = prev_cap and p.is_blank
                continue
            role = roles.get(id(p), "")
            cap = role if role in ("fig_caption", "table_caption") else self.textbox_caption(p)
            t = nfkc(_para_text(p)).strip()
            if cap and (RE_FIGCAP.match(t) or RE_TABCAP.match(t) or not groups):
                groups.append((cap, [p]))
                prev_cap = True
            elif role in ("fig_caption", "table_caption") and prev_cap:
                groups[-1][1].append(p)       # 番号で始まらないキャプションの続き（出典など）
            else:
                others.append(p)
                prev_cap = False
        return groups, others

    @staticmethod
    def float_summary(info) -> str:
        """浮動配置の図形の中身の要約（レポート用）: キャプションの冒頭と、本体の種類（表のセルの中のキャプション・画像も）。"""
        paras = info.paras + [c for t in info.tables for c in t.paragraphs()]
        texts = [nfkc(_para_text(q)).strip() for q in paras if not q.is_blank]
        caps = [t[:20] for t in texts if RE_FIGCAP.match(t) or RE_TABCAP.match(t)]
        body = (["画像"] if info.images or any(q.images for q in paras) else []) + (["表"] if info.tables else [])
        head = "、".join(f"「{c}」" for c in caps) if caps else "キャプションなし"
        return f"{head}／中身: {'・'.join(body) or '文字'}"

    def _take(self, p: Para, role: str, origin=""):
        p.role = role
        if origin:
            p.role_origin = origin
        self.plan.region[p.src] = "body"

    def _take_table(self, t: Table):
        for tp in t.paragraphs():
            self.plan.region[tp.src] = "body"
            tp.role = tp.role or "cell"

    def _caption_decision(self, p: Para, role: str):
        if p.role_origin != "style" or self.style_role(p) not in ("fig_caption", "table_caption"):
            kind = "図" if role == "fig_caption" else "表"
            self.plan.decide("mechanical", "style", p.src,
                             f"テキストボックス内のスタイル「{p.style_name}」の段落「{_para_text(p)[:30]}」を"
                             f"{kind}キャプションと推定（「{kind}N」で始まる）")
            return "heuristic"
        return ""

    def _drop_blank(self, p: Para):
        self.plan.region[p.src] = "body"
        self.plan.exclude_blank(p)

    def float_mechanical(self, info, groups, others):
        """位置が機械的に決まる浮動配置の図形の中身を組む。中身が単純でなければ None（AI に任せる）。

        単純な中身: キャプション 1 つと本体 1 つ（画像・表）、または表 1 つだけで、そのセルに画像とキャプションが並ぶ図
        （cell_figures）。画像と文字が同じ段落は、図に組むときは画像を図に移し、段落は文字ごと図の直後に本文の段落として出す。
        キャプションのない図形は図にしないので、これまでどおり画像も文字も段落のまま出す。表 1 つだけの図形で、セルの画像と
        キャプションの組み方が一つに決まらないものも、これまでどおり（0.21.0 と同じ）キャプションのない表として出す。
        """
        image_paras = [q for q in info.paras if q.images]
        if len(info.tables) == 1 and not (groups or others or image_paras or info.images):
            cells = self.cell_figures(info)
            if cells is not None:
                return cells        # 表のセルに画像とキャプションが並ぶ図
        if len(groups) > 1 or others or len(info.tables) > 1 or (info.tables and (image_paras or info.images)):
            return None
        if groups and groups[0][0] == "table_caption" and (image_paras or info.images):
            return None
        # ここから先は必ず組む（状態を変えるのは、組めると決まってから）
        for q in info.paras:
            if q.is_blank and not q.images:
                self._drop_blank(q)
        for t in info.tables:
            self._take_table(t)
        for q in image_paras:
            self._take(q, "p")
        if not groups:
            # キャプションのない画像・表（これまでの扱い: キャプションなしの図・表）
            return [("p", q) for q in image_paras] + [("table", t) for t in info.tables]
        role, caps = groups[0]
        for q in caps:
            self._take(q, role, self._caption_decision(q, role))
        if role == "table_caption":
            if not info.tables:
                return [(role, q) for q in caps]
            return [("node", TableNode(table=info.tables[0], caption=caps[0], caption_more=caps[1:]))]
        if not (image_paras or info.images or info.tables):
            return [(role, q) for q in caps]     # キャプションだけ（隣の画像と組にする。これまでの扱い）
        # 画像と文字が同じ段落（画像だけの段落でないもの）は、画像を図に移し（段落の中では出さない）、
        # 段落は文字ごと図の直後に本文の段落として出す
        mixed = [q for q in image_paras if not self.is_image_para(q)]
        extra = list(info.images) + [i for q in mixed for i in q.images]
        for q in mixed:
            self.plan.decide("mechanical", "figure", q.src,
                             f"テキストボックス・グループ図形 {info.float.fid} の段落「{_para_text(q).strip()[:20]}」は、"
                             "画像と文字が同じ段落にある。画像は図に入れ、段落の文字は図の直後に本文の段落として出した")
        self.plan.moved_images.update(i.image_id for i in extra)
        return ([("node", FigNode(image_paras=[q for q in image_paras if q not in mixed], caption=caps[0],
                                  caption_more=caps[1:], tables=list(info.tables), extra_images=extra))]
                + [("p", q) for q in mixed])

    def cell_caption(self, q: Para) -> str | None:
        """表のセルの段落がキャプションか（キャプションのスタイル、またはキャプションの形。float_captions と同じ考え）。

        表のセルの段落には items の役割がないので、スタイルから求める（role_of）。
        """
        role = self.role_of(q)
        return role if role in ("fig_caption", "table_caption") else self.textbox_caption(q)

    def cell_figures(self, info):
        """浮動配置の図形の中の表 1 つのセルに、画像と図キャプションが並ぶ図（N18）を、表を出さずに図に組む。

        戻り値: 組んだ要素の一覧。組まないときは None で、呼び出し側（float_mechanical）がこれまで（0.21.0）の扱いにする
        （キャプションのない表として出す。位置が機械的に決まる図形はアンカー段落の前に置き、位置を決められない図形は今までどおり
        AI に任せる）。
        - 図キャプションが表全体で 1 つ: すべてのセルの画像（行・列の順）を本体にした図 1 つ
        - 2 つ以上: どのセルも「画像とキャプション 1 つ」か「空白だけ」なら、セルごとの図。画像だけのセルとキャプション 1 つだけの
          セルが並ぶ表（画像の行とキャプションの行など）は、隣り合う画像とキャプションの組が一つに決まるときだけ（cell_pairs）
        組まない（None）とき: セルに画像と番号で始まる図キャプションの両方がない（この形ではない。セルに図キャプションと問題文
        だけがある表で組んだ図も、表のまま出す）、表キャプションがある、キャプションでも画像でもない文字の段落（「（a）」などの
        小見出しも。表の構造を捨てると読めなくなるおそれがある）や入れ子の表がある、画像とキャプションの組を一つに決められない。
        組むときのセルの段落は、画像の段落・キャプション（とその続きの出典など）・空白だけなので、表を出さなくても文字は落ちない。
        画像と文字が同じ段落は、float_mechanical と同じく、画像を図に移し、段落は文字ごと図の直後に本文の段落として出す。
        状態を変えるのは、組めると決まってから（float_mechanical と同じ約束）。
        """
        t = info.tables[0]
        grid, blanks = [], []          # grid: 行ごとの [(画像の段落の一覧, [キャプションの組（段落の一覧）…])]
        n_img = n_cap = 0
        stop = False                   # 表キャプション・キャプションでない文字の段落・入れ子の表がある
        for row in t.rows:
            line = []
            for c in row.cells:
                imgs, caps, prev_cap = [], [], False
                for q in c.blocks:
                    if isinstance(q, Table):
                        stop, prev_cap = True, False
                        continue
                    if q.images:
                        imgs.append(q)
                        prev_cap = False
                        continue
                    if q.is_blank:
                        blanks.append(q)
                        continue
                    text = nfkc(_para_text(q)).strip()
                    if self.cell_caption(q) == "fig_caption" and RE_FIGCAP.match(text):
                        caps.append([q])
                        prev_cap = True
                    elif prev_cap and self.role_of(q) == "fig_caption" and not RE_TABCAP.match(text):
                        caps[-1].append(q)          # 番号で始まらないキャプションの続き（出典など。float_captions と同じ）
                    else:
                        stop, prev_cap = True, False    # 表キャプション、キャプションでない文字の段落
                line.append((imgs, caps))
                n_img += len(imgs)
                n_cap += len(caps)
            grid.append(line)
        if not (n_cap and n_img) or stop:
            return None
        cells = [x for line in grid for x in line]
        if n_cap == 1:
            figs = [([q for imgs, _ in cells for q in imgs], next(caps[0] for _, caps in cells if caps))]
        elif all((imgs and len(caps) == 1) or not (imgs or caps) for imgs, caps in cells):
            figs = [(imgs, caps[0]) for imgs, caps in cells if caps]
        else:
            figs = self.cell_pairs(t, grid)
            if figs is None:
                return None
        # ここから先は必ず組む
        plan = self.plan
        plan.decide("mechanical", "figure", info.float.anchor_src,
                    f"テキストボックス・グループ図形 {info.float.fid} の表 {t.tid} のセルにある画像とキャプションを、図"
                    + "、".join(f"「{_para_text(caps[0]).strip()[:20]}」" for _, caps in figs) + "に組んだ（表としては出力しない）")
        for q in blanks + [q for q in info.paras if q.is_blank and not q.images]:
            self._drop_blank(q)
        entries = []
        for imgs, caps in figs:
            plan.cell_paras.update(q.src for q in imgs + caps)
            for q in imgs:
                self._take(q, "p")
            for q in caps:
                self._take(q, "fig_caption", self._caption_decision(q, "fig_caption"))
            mixed = [q for q in imgs if not self.is_image_para(q)]
            for q in mixed:
                plan.decide("mechanical", "figure", q.src,
                            f"テキストボックス・グループ図形 {info.float.fid} の段落「{_para_text(q).strip()[:20]}」は、"
                            "画像と文字が同じ段落にある。画像は図に入れ、段落の文字は図の直後に本文の段落として出した")
            extra = [i for q in mixed for i in q.images]
            plan.moved_images.update(i.image_id for i in extra)
            entries.append(("node", FigNode(image_paras=[q for q in imgs if q not in mixed], caption=caps[0],
                                            caption_more=caps[1:], extra_images=extra)))
            entries.extend(("p", q) for q in mixed)
        return entries

    @staticmethod
    def cell_pairs(t, grid):
        """画像だけのセルとキャプション 1 つだけのセルが並ぶ表で、画像とキャプションの組を決める（cell_figures）。

        同じ列で上下に隣り合う組（画像の行とキャプションの行など）か、同じ行で左右に隣り合う組で、表全体で向き
        （列ごとか行ごとか、画像が先かキャプションが先か）が一つに決まるときだけ組む（空白だけのセルは飛ばす）。
        結合したセル・飛ばしたグリッド（gridBefore・gridAfter）がある、行ごとのセルの数が違う、どの向きでも組めない・二つ以上の向きで組めるときは None。
        戻り値: [(画像の段落の一覧, キャプションの組)]（組の最初のセルの行・列の順）
        """
        if (any(c.gridspan != 1 or c.vmerge for row in t.rows for c in row.cells)
                or any(r.grid_before or r.grid_after for r in t.rows) or len({len(line) for line in grid}) != 1):
            return None
        kind = {}
        for r, line in enumerate(grid):
            for c, (imgs, caps) in enumerate(line):
                if (imgs and caps) or len(caps) > 1:
                    return None
                if imgs or caps:
                    kind[(r, c)] = "img" if imgs else "cap"
        nrow, ncol = len(grid), len(grid[0])
        found = []
        for lines in ([[(r, c) for r in range(nrow)] for c in range(ncol)],      # 列ごと（上下に隣り合う）
                      [[(r, c) for c in range(ncol)] for r in range(nrow)]):     # 行ごと（左右に隣り合う）
            for first, second in (("img", "cap"), ("cap", "img")):
                pairs = []
                for line in lines:
                    seq = [pos for pos in line if pos in kind]
                    if len(seq) % 2 or any(kind[pos] != (first, second)[k % 2] for k, pos in enumerate(seq)):
                        pairs = None
                        break
                    pairs += [(seq[k], seq[k + 1]) for k in range(0, len(seq), 2)]
                if pairs:
                    found.append(pairs)
        if len(found) != 1:
            return None
        out = []
        for a, b in sorted(found[0]):
            img, cap = (a, b) if kind[a] == "img" else (b, a)
            out.append((grid[img[0]][img[1]][0], grid[cap[0]][cap[1]][1][0]))
        return out

    def float_from_spec(self, info, spec):
        """AI が指定した組み合わせ（ai_assist.float_placements で検証済み）で、浮動配置の図形の中身を組む。"""
        plan = self.plan
        paras = {q.src: q for q in info.paras}
        cells = {q.src: t for t in info.tables for q in t.paragraphs()}
        cell_paras = {q.src: q for t in info.tables for q in t.paragraphs()}
        tables = {t.tid: t for t in info.tables}
        group_imgs = {i.image_id: i for i in info.images}
        img_para = {i.image_id: q for q in list(info.paras) + list(cell_paras.values()) for i in q.images}
        used, used_tables, dissolved, entries, descs = set(), set(), set(), [], []
        for item in spec["items"]:
            caps = []
            for src in item.get("caption") or []:       # 検証（ai_assist._placement_problem）は falsy を空の一覧として通す
                q = paras.get(src) or cell_paras[src]
                if src in cells:
                    dissolved.add(cells[src].tid)
                role = "fig_caption" if item["kind"] == "fig" else "table_caption"
                self._take(q, role, "ai")
                caps.append(q)
                used.add(q.src)
            image_paras, extra, tbls, mixed = [], [], [], []
            for x in item.get("body") or []:
                if x in tables:
                    tbls.append(tables[x])
                    used_tables.add(x)
                    self._take_table(tables[x])
                elif x in group_imgs:
                    extra.append(group_imgs[x])
                else:
                    q = paras.get(x) or cell_paras.get(x) or img_para[x]
                    if q.src in cells:
                        dissolved.add(cells[q.src].tid)
                    if not self.is_image_para(q):
                        # 画像と文字が同じ段落: 画像は図に移し、段落は文字ごと図の直後に本文の段落として出す
                        if q not in mixed:
                            mixed.append(q)
                            extra.extend(q.images)
                            self._take(q, "p")
                            used.add(q.src)
                    elif q not in image_paras:
                        image_paras.append(q)
                        self._take(q, "p")
                        used.add(q.src)
            plan.moved_images.update(i.image_id for i in extra)
            cap, more = (caps[0], caps[1:]) if caps else (None, [])
            if item["kind"] == "table":
                entries.append(("node", TableNode(table=tbls[0], caption=cap, caption_more=more)))
            else:
                entries.append(("node", FigNode(image_paras=image_paras, caption=cap, caption_more=more,
                                                tables=tbls, extra_images=extra)))
                entries.extend(("p", q) for q in mixed)
            what = "表" if item["kind"] == "table" else "図"
            body = "表" if tbls else "画像"
            if mixed:
                body += (f"。画像と文字が同じ段落 {', '.join(q.src for q in mixed)} は、画像を図に入れ、"
                         "文字は図の直後に本文の段落として出した")
            descs.append(f"{what}「{_para_text(cap)[:20] if cap else 'キャプションなし'}」（本体: {body}）")
        # 指定に含まれなかった中身は、図表の後にそのまま出す（文字を落とさないため）
        for q in info.paras:
            if q.src in used:
                continue
            if q.is_blank and not q.images:
                self._drop_blank(q)
            else:
                self._take(q, "p")
                entries.append(("p", q))
        for t in info.tables:
            if t.tid in dissolved:
                for q in t.paragraphs():
                    if q.src in used:
                        continue
                    if q.is_blank and not q.images:
                        self._drop_blank(q)
                    else:
                        self._take(q, "p")
                        entries.append(("p", q))
            elif t.tid not in used_tables:
                self._take_table(t)
                entries.append(("table", t))
        after = plan.paras.get(spec["after"])
        d = plan.decide("ai", "figure", spec["after"],
                        f"テキストボックス・グループ図形 {info.float.fid} の中身を{'、'.join(descs)}として組み、段落"
                        f"「{_para_text(after)[:20] if after else spec['after']}」の後に置いた。{spec.get('reason', '')}",
                        spec.get("confidence", ""))
        plan.float_decisions[info.float.fid] = d
        return entries

    @staticmethod
    def textbox_caption(b: Para) -> Optional[str]:
        """図表キャプションのスタイルでないテキストボックス内の段落が、キャプションの形をしていれば役割を返す。"""
        t = nfkc(_para_text(b)).strip()
        if len(t) > 80 or t.endswith("。"):
            return None
        m = RE_TEXTBOX_CAP.match(t)
        if not m:
            return None
        return "fig_caption" if m.group("fig") else "table_caption"

    @staticmethod
    def is_image_para(b) -> bool:
        if not isinstance(b, Para):
            return False
        return bool(b.images) and all(a.kind == "image" or (a.kind == "text" and is_ws(a.text)) for a in b.atoms)

    def assemble_floats(self, flat):
        """図（画像段落＋図キャプション）と表（表キャプション＋表）を組み立て、本文の要素列にする。

        位置を決められない図表（仮の位置に置いた図形。self.provisional）の中身は、本当はそこにないので、その外の要素とは組に
        しない（図キャプションと画像、表キャプションと表、キャプションの続き、図の本体の表〈table_for_figure〉）。前後の要素は、
        同じ置き場所の要素（図形の外の要素なら図形の外の要素、仮に置いた図形の中身なら同じ位置に仮に置いた図形の中身）だけで
        数える（間に図形の中身を仮に置いていても、docx で隣り合う画像と図キャプションは組にする。同じ段落に結び付いた、画像だけの
        図形とキャプションだけの図形は、同じ位置に仮に置くので組にする）。囲み（BoxNode。置き場所は BOX_PLACE）も前後に数えない
        （図はキャプションの位置に組み立てるので、画像とキャプションの間の囲みは、キャプションが画像の後ろなら図の前、前なら図の
        後ろに出る。表は表キャプションと表の先に来る方の位置に組み立てるので、間の囲みは、キャプションが表の上でも下でも表の後ろに出る）。
        """
        plan = self.plan
        out = []
        used = set()
        n = len(flat)
        prev, nxt = same_place(flat, self.provisional)
        where = {}                  # out の要素の id -> 置き場所（provisional の値。図形の外は ""）

        def put(node, k):
            out.append(node)
            where[id(node)] = self.provisional.get(id(flat[k][1]), "")

        def last_out(k, m=1):       # out の最後から、flat[k] と同じ置き場所の要素の位置（m 個まで。後ろから）
            here, got = self.provisional.get(id(flat[k][1]), ""), []
            for j in range(len(out) - 1, -1, -1):
                if len(got) == m:
                    break
                if where[id(out[j])] == here:
                    got.append(j)
            return got

        def ahead(k, m):            # flat[k] の後ろの、同じ置き場所の要素の位置（m 個まで）
            got, j = [], nxt[k]
            while j is not None and len(got) < m:
                got.append(j)
                j = nxt[j]
            return got

        below = sum(1 for k in range(n) if flat[k][0] == "fig_caption" and prev[k] is not None
                    and self.is_image_para(flat[prev[k]][1]))
        above = sum(1 for k in range(n) if flat[k][0] == "fig_caption" and nxt[k] is not None
                    and self.is_image_para(flat[nxt[k]][1]))
        captions_below = below >= above
        for k, (role, b) in enumerate(flat):
            if role == "node":          # 組み立て済みの図表（浮動配置の図形）
                put(b, k)
                continue
            if id(b) in used:
                continue
            last = last_out(k)
            if role in ("fig_caption", "table_caption") and last and prev[k] is not None \
                    and flat[prev[k]][1] is not None \
                    and isinstance(out[last[0]], FigNode if role == "fig_caption" else TableNode) \
                    and out[last[0]].caption is not None and flat[prev[k]][0] == role \
                    and not (RE_FIGCAP if role == "fig_caption" else RE_TABCAP).match(nfkc(_para_text(b)).strip()):
                # 番号で始まらないキャプション段落が続く → 直前のキャプションの続き
                out[last[0]].caption_more.append(b)
                plan.decide("mechanical", "figure" if role == "fig_caption" else "table", b.src,
                            f"キャプションの続きの段落「{_para_text(b)[:20]}」を直前の{'図' if role == 'fig_caption' else '表'}のキャプションに含めた")
                continue
            if role == "fig_caption":
                img = None
                for j in last_out(k, 2):
                    if isinstance(out[j], PNode) and self.is_image_para(out[j].para):
                        img = out.pop(j).para
                        break
                if img is None:
                    for j in ahead(k, 2):
                        # キャプションを画像の下に置く原稿では、直後に図キャプションがある画像はそのキャプションの図のもの
                        if captions_below and nxt[j] is not None and flat[nxt[j]][0] == "fig_caption":
                            continue
                        if self.is_image_para(flat[j][1]) and id(flat[j][1]) not in used:
                            img = flat[j][1]
                            used.add(id(img))
                            break
                fig = FigNode(image_paras=[img] if img else [], caption=b)
                if img is None:
                    # 画像がなければ、隣のキャプションのない表を図の本体にする（表で組んだ図。決定事項 22）
                    tbl, why = self.table_for_figure(flat, out, k, used, captions_below, self.provisional)
                    if tbl is not None:
                        fig.tables.append(tbl)
                        plan.decide("mechanical", "figure", b.src,
                                    f"画像のない図キャプション「{_para_text(b).strip()[:20]}」の"
                                    f"{'直前' if captions_below else '直後'}にある、キャプションのない表 {tbl.tid} を、"
                                    "図の本体として組んだ（図の中に表を入れる）")
                    elif why:
                        plan.figure_issues.append((b.src, why))
                        plan.decide("mechanical", "figure", b.src, f"図キャプションに対応する画像が見つからない（{why}）",
                                    applied=False)
                    else:
                        plan.decide("mechanical", "figure", b.src, "図キャプションに対応する画像が見つからない（図形・グループ化等の可能性）")
                put(fig, k)
                continue
            if role == "table_caption":
                tbl = None
                for j in ahead(k, 2):
                    if flat[j][0] == "table" and id(flat[j][1]) not in used:
                        tbl = flat[j][1]
                        used.add(id(tbl))
                        break
                if tbl is None and last and isinstance(out[last[0]], TableNode) and out[last[0]].caption is None:
                    out[last[0]].caption = b
                    continue
                if tbl is None:
                    plan.decide("mechanical", "table", b.src, "表キャプションに対応する表が見つからない")
                put(TableNode(table=tbl, caption=b), k)
                continue
            if role == "table":
                put(TableNode(table=b), k)
                continue
            if role in HEADING_LEVEL:
                put(Sec(level=HEADING_LEVEL[role], heading=b), k)
                continue
            if role == "quote":
                if out and isinstance(out[-1], QuoteNode):
                    out[-1].paras.append(b)
                else:
                    put(QuoteNode(paras=[b]), k)
                continue
            # 本文段落
            if self.is_image_para(b):
                put(PNode(b), k)   # 図キャプションが後に来れば図になる。最後まで残れば下で処理
                continue
            fnode = self.formula_node(b)
            if fnode:
                put(fnode, k)
                continue
            if b.numbering and b.autonum:
                ordered = not self.doc_numbering_is_bullet(b)
                if out and isinstance(out[-1], ListNode) and out[-1].items[-1].numbering[0] == b.numbering[0]:
                    out[-1].items.append(b)
                else:
                    put(ListNode(items=[b], ordered=ordered), k)
                continue
            put(PNode(b), k)
        # キャプションのない画像段落 → キャプションなしの図
        final = []
        for node in out:
            if isinstance(node, PNode) and self.is_image_para(node.para):
                fig = FigNode(image_paras=[node.para])
                imgs = node.para.images
                small = all(0 < i.height_cm < 2.2 and i.width_cm / max(i.height_cm, 0.01) > 2.5 for i in imgs)
                if small:
                    plan.decide("mechanical", "formula", node.para.src,
                                "キャプションのない横長の小さな画像（数式画像の可能性）。キャプションなしの図として出力")
                else:
                    plan.decide("mechanical", "figure", node.para.src, "キャプションのない画像。キャプションなしの図として出力")
                final.append(fig)
            else:
                final.append(node)
        return final

    @staticmethod
    def table_for_figure(flat, out, k, used, captions_below, provisional=None):
        """画像のない図キャプション flat[k] の本体にする、キャプションのない表（N19。決定事項 22: fig の中の table-wrap）。

        図キャプションを図の下に置く原稿（captions_below。画像の図がなければ下とみなす）では直前、上に置く原稿では直後の、
        キャプションのない表を本体にする。間にほかの段落があれば組まない（空白だけの段落は flat にない）。直後の表の次が
        表キャプションなら、その表は表キャプションのもの（表の下に表キャプションを置く書き方）かもしれないので組まない。
        位置を決められない図表（仮の位置に置いた図形。provisional: flat の要素の id → 置き場所〈仮に置いた位置〉）の中身は、
        本当はそこにないので、その外の要素とは組にしない。図キャプションの前後は、同じ置き場所の要素（図形の外の図キャプション
        なら図形の外の要素、仮に置いた図形の中の図キャプションなら同じ位置に仮に置いた図形の中身）だけで数える（間にほかの図形の
        中身を仮に置いていても、docx で隣り合う表と図キャプションは組にする）。
        直前の表は out（組み立て済み）から取り出す（後ろの表の ID が詰まる）。直後の表は used に入れる。
        戻り値: (表, "") / (None, 組めなかった理由。近くに表の候補があるとき) / (None, "")（近くにキャプションのない表がない）
        """
        provisional = provisional or {}
        here = provisional.get(id(flat[k][1]), "")
        near = [j for j in range(len(flat)) if provisional.get(id(flat[j][1]), "") == here]
        p = near.index(k)

        def at(d):          # 図キャプションから d 個先（負なら前）の、同じ置き場所の要素の flat での位置（なければ None）
            return near[p + d] if 0 <= p + d < len(near) else None

        def role(d):
            j = at(d)
            return flat[j][0] if j is not None else None

        def node(d):        # d 個前の要素が表なら、その TableNode（out の中。組み立て済み）
            j = at(d)
            if j is None or flat[j][0] != "table":
                return None
            return next((x for x in reversed(out) if isinstance(x, TableNode) and x.table is flat[j][1]), None)

        def before(d):      # d 個前の要素が、キャプションのない表か
            x = node(d)
            return x if x is not None and x.caption is None else None

        def after(d):       # d 個先の要素が、キャプションのない表か
            j = at(d)
            if j is None or flat[j][0] != "table" or id(flat[j][1]) in used:
                return False
            return role(d + 1) != "table_caption" and role(d - 1) != "table_caption"

        if captions_below:
            x = node(-1)
            if x is not None:
                if x.caption is None:
                    del out[next(i for i in range(len(out) - 1, -1, -1) if out[i] is x)]
                    return x.table, ""
                return None, f"直前の表に表キャプション「{_para_text(x.caption).strip()[:20]}」が付いている"
            if after(1):
                return None, ("直後にキャプションのない表があるが、この原稿は図キャプションを図の下に置いているため、"
                              "図の本体にしなかった")
            if before(-2) or before(-3):
                return None, "図キャプションの前にキャプションのない表があるが、間にほかの段落がある"
            return None, ""
        j = at(1)
        if j is not None and flat[j][0] == "table" and id(flat[j][1]) not in used:
            if role(2) == "table_caption":
                return None, "直後の表の次に表キャプションがあり、どちらの表か決められない"
            used.add(id(flat[j][1]))
            return flat[j][1], ""
        if before(-1):
            return None, ("直前にキャプションのない表があるが、この原稿は図キャプションを図の上に置いているため、"
                          "図の本体にしなかった")
        if after(2) or after(3):
            return None, "図キャプションの後ろにキャプションのない表があるが、間にほかの段落がある"
        return None, ""

    @staticmethod
    def doc_numbering_is_bullet(b):
        return b.autonum and not re.search(r"[0-9０-９A-Za-zⅠ-Ⅻ①-⑳ア-ンイ一-十]", b.autonum)

    def formula_node(self, b: Para) -> Optional[FormulaNode]:
        if not b.has_display_math:
            return None
        plain = b.plain()
        if any(a.kind not in ("math", "text") for a in b.atoms):
            return None
        # 数式以外の文字が空白と式番号だけなら別行数式
        outside = "".join(a.text if a.kind == "text" else "" for a in b.atoms)
        if outside.strip() and not RE_FORMULA_LABEL.match(outside):
            return None
        node = FormulaNode(para=b)
        if outside.strip():
            m = re.search(r"[(（][\s\u3000]*[0-9０-９]+(?:[.．\-－][0-9０-９]+)?[\s\u3000]*[)）]", plain)
            if m:
                node.label = m.group(0)
                node.label_range = (m.start(), m.end())
        return node

    def nest(self, nodes):
        root = []
        stack = []   # Sec
        for node in nodes:
            if isinstance(node, Sec):
                while stack and stack[-1].level >= node.level:
                    stack.pop()
                (stack[-1].children if stack else root).append(node)
                stack.append(node)
            else:
                (stack[-1].children if stack else root).append(node)
        return root

    def compute_locations(self, nodes, path):
        plan = self.plan
        count = 0
        for node in nodes:
            if isinstance(node, Sec):
                title = _para_text(node.heading).strip()[:24] if node.heading else ""
                if node.heading:
                    plan.locations[node.heading.src] = " > ".join(path + [title]) + "（見出し）"
                self.compute_locations(node.children, path + [title])
                continue
            count += 1
            where = " > ".join(path) if path else "本文冒頭"
            for p in self.node_paras(node):
                plan.locations.setdefault(p.src, f"{where} / 第{count}要素")

    def add_back_para(self, children, b: Para, formula: bool = True, heading: bool = False):
        """付記・謝辞・資料の段落を children に足す: 別行数式は FormulaNode、Word の自動番号の段落は同じ番号の定義が続く間 ListNode
        （本文と同じ。番号は <list-item> の <label> に出る）、それ以外は PNode。heading: 見出しの役割（章・節・項見出しのスタイル）の
        段落。自動番号があっても箇条にせず（前後の同じ番号の <list> にまとめない。本文では見出しは節の見出しで、箇条にならない）、
        PNode にする。次の同じ番号の段落は、見出しで切れた新しい ListNode から始まる。"""
        fnode = self.formula_node(b) if formula else None
        if fnode:
            children.append(fnode)
        elif b.numbering and b.autonum and not heading:
            if children and isinstance(children[-1], ListNode) and children[-1].items[-1].numbering[0] == b.numbering[0]:
                children[-1].items.append(b)
            else:
                children.append(ListNode(items=[b], ordered=not self.doc_numbering_is_bullet(b)))
        else:
            children.append(PNode(b))

    @staticmethod
    def textless(b) -> bool:
        """段落 b に文字が 1 文字もないか: 空白と画像だけ（数式・脚注の参照・Word の自動番号があれば偽）。"""
        return (isinstance(b, Para) and not b.autonum
                and all(a.kind == "image" or (a.kind == "text" and not a.text.strip()) for a in b.atoms))

    @staticmethod
    def node_paras(node):
        if isinstance(node, PNode):
            return [node.para]
        if isinstance(node, QuoteNode):
            return node.paras
        if isinstance(node, ListNode):
            return node.items
        if isinstance(node, FigNode):
            return (node.image_paras + ([node.caption] if node.caption else []) + node.caption_more
                    + [p for t in node.tables for p in t.paragraphs()])
        if isinstance(node, TableNode):
            out = ([node.caption] if node.caption else []) + node.caption_more
            if node.table:
                out += list(node.table.paragraphs())
            return out
        if isinstance(node, FormulaNode):
            return [node.para]
        if isinstance(node, BoxNode):
            return [p for c in node.children for p in Classifier.node_paras(c)]
        return []

    # ----------------------------------------------------------------- back
    def replace_back(self, kind, old, new, new_role) -> bool:
        """後付けの見出し（付記・謝辞は節。BackSec）・英文要旨の見出し old を、同じ種類の見出し new で置き換えてよいか。真なら呼び出し側が
        plan に new を代入する。

        old（前の見出し・前の BackSec）を new で置き換えると old の段落が出力も除外もされなくなる（K1）。そうなるときだけ
        plan.structure_conflicts に記録する（組み立ては止めず、すべての箇所を集める。pipeline.convert が中止する）。空白だけの見出しは
        前でも後ろでも空白の除外にして記録しない: 後ろの見出し new が空白だけなら new を除外して False（前の見出し・節を残す）、
        前の見出し（と中身）が空白だけならそれらを除外して True。落ちる節に中身があるとき、その節の空白だけの段落（見出しが空白だけなど）も
        空白の除外に記録する（lost は含めない）。kind: ref_heading / fn_heading / notes / ack / abstract_heading。
        new_role: new の役割（後付けの見出しの役割でなければ、文字から推定した見出し）。
        """
        plan = self.plan
        if old is None:
            return True
        if new.is_blank:
            plan.exclude_blank(new)
            return False
        paras = [old] if isinstance(old, Para) else [old.heading] + [p for c in old.children for p in self.node_paras(c)]
        lost = [p for p in paras if not p.is_blank]
        if not lost:
            for p in paras:
                plan.exclude_blank(p)
            return True
        by_text = (False, False)
        if kind != "abstract_heading":
            by_text = (self._heading_by_text.get(paras[0].src, False), new_role not in BACK_HEADINGS)
        for p in paras:
            if p.is_blank:      # 落ちる節の空白だけの段落（空白だけの見出しなど）も、出力しないので空白の除外に記録する
                plan.exclude_blank(p)
        plan.structure_conflicts.append(StructureConflict(
            kind, [p.src for p in lost], new.src, by_text=by_text, between=self._back_between(kind, paras[-1].src, new.src)))
        return True

    def _back_between(self, kind, last_src, new_src) -> bool:
        """前の見出しの節の最後の段落 last_src の後ろから後ろの見出し new_src の手前までに、kind とは別の種類の後付けの段落
        （付記・謝辞・注・引用文献）があるか。真なら、後ろの見出しを消すだけでは、その後ろの段落が前の節に入らない
        （report.structure_conflict_text の直し方が変わる）。英文要旨の見出しでは偽。"""
        mine = {"ref_heading": "refs", "fn_heading": "fn", "notes": "notes", "ack": "ack"}.get(kind)
        if mine is None:
            return False
        plan = self.plan
        srcs = list(plan.paras)
        if last_src not in plan.paras or new_src not in plan.paras:
            return False
        first, last = srcs.index(last_src), srcs.index(new_src)
        return any(plan.region.get(x) in ("notes", "ack", "fn", "refs") and plan.region.get(x) != mine
                   for x in srcs[first + 1:last])

    def build_back(self, items):
        plan = self.plan
        state = None
        current_fn = None
        # 注の節の中の表（FnNode.tables）。注にまだ入れていない表 [(キャプションの段落か None, Table)]（docx の順）: 注の見出しの後ろで
        # 注がまだ始まっていないときの表と、キャプションだけの注の候補（caption_only）の前の表
        pending = []
        fn_role = {}        # 注に入れた段落の役割（src -> role）。キャプションの判定に使う（role_of は role_origin を書き換えるので呼び直さない）

        def caption_only(fn) -> bool:
            """注 fn が、注がまだない所（注の見出しの直後）の「表キャプション」の段落 1 つだけでできた番号のない注か。次が表なら、注を
            作らず、その段落を表のキャプションにする（表が続かなければ注のまま）。"""
            if fn is None or not plan.fns or fn is not plan.fns[-1] or len(fn.paras) != 1 or fn.number is not None or fn.tables:
                return False
            c = fn.paras[0]
            return fn_role.get(c.src) == "table_caption" and self.overrides.get(c.src) != "fn_start"

        def note_table(fn, k, node, first):
            """注 fn に表 node を入れ（paras の k 段落の後ろ）、判断の一覧（4 章）に記録する。first: 最初の注より前にあった表。"""
            fn.tables.append((k, node))
            n = next(i for i, f in enumerate(plan.fns, 1) if f is fn)
            if node.caption is not None:
                src = node.caption.src
                plan.locations[src] = f"注 {n}件目の表キャプション"
            else:
                src = next((q.src for q in node.table.paragraphs() if not q.is_blank), block_id(node.table))
            where = ("注の見出しの後ろ、最初の注の前にあった表を、その注の 1 段落目の後ろに入れた" if first
                     else "注の段落の間、docx の順")
            plan.decide("mechanical", "note", src,
                        f"注の節の中の表を、注 {n}件目の中に出力した（{where}）。J-STAGE の画面で注の中の表が"
                        "表示されるかは確かめていないので、プレビューで確かめる")

        def settle(fn):
            """注に入れていない表（pending）を、注 fn の 1 段落目の後ろ（k=1。注の番号が <fn> の先頭に来るように）に入れる。"""
            for cap, t in pending:
                note_table(fn, 1, TableNode(table=t, caption=cap), first=True)
            pending.clear()

        def flush():
            """注に入れられなかった表（とそのキャプション）を、位置を決められない除外に記録する（要確認 excluded_unsure）。"""
            for cap, t in pending:
                for p in ([cap] if cap is not None else []) + list(t.paragraphs()):
                    if p.is_blank:
                        plan.exclude_blank(p)
                    else:
                        plan.exclude(p, BACK_TABLE_EXCLUDED)
            pending.clear()

        for k, (b, role) in enumerate(items):
            key = self.outside_key(b) if in_shape(b) else ""
            if key:
                # 本文の外（引用文献・注など）の段落に結び付いた図形の中身は、その領域の段落にしない（N7）。状態を変えずに飛ばし、
                # 記録する（classify が組み立て直して、本文の最後に回す）
                self.outside.setdefault(key, state or "back")
                continue
            if isinstance(b, Table):
                if state == "refs":
                    for p in b.paragraphs():
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
                            plan.refs.append(RefNode(para=p))
                    continue
                if state == "fn":
                    if caption_only(current_fn):
                        # (a) 注の見出しの直後の「表キャプション」の段落から番号のない注ができていた: 注を作らず、(キャプション, 表) を
                        # 次の注に回す
                        c = current_fn.paras[0]
                        plan.fns.pop()
                        current_fn = None
                        plan.locations[c.src] = "注の表キャプション"
                        pending.append((c, b))
                    elif current_fn is None:
                        pending.append((None, b))       # (b) 注がまだ始まっていない
                    else:
                        # (c) 注の段落の後ろの表。直前の「表キャプション」の段落（注の 2 段落目以降）をキャプションにする
                        cap = None
                        if len(current_fn.paras) >= 2 and fn_role.get(current_fn.paras[-1].src) == "table_caption":
                            cap = current_fn.paras.pop()
                        note_table(current_fn, len(current_fn.paras), TableNode(table=b, caption=cap), first=False)
                    continue
                target = {"notes": plan.notes, "ack": plan.ack}.get(state)
                if target is not None:
                    target.children.append(TableNode(table=b))
                else:
                    for p in b.paragraphs():
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
                            plan.exclude(p, BACK_TABLE_EXCLUDED)
                continue
            if (isinstance(b, Para) and b.is_blank and not in_shape(b) and role in BACK_HEADINGS
                    and not self.blank_heading_leads(role, items[k + 1:], True)):
                # 空白だけの後付けの見出しのスタイルの段落は、後ろの最初の中身がその見出しの中身でなければ、節を切り替えない
                # （後ろの文献が注・謝辞・付記になるのを防ぐ。C041。split_regions と同じ規則）。空白の除外に記録するだけ
                plan.region[b.src] = state or "back"
                plan.exclude_blank(b)
                continue
            heading = role if role in BACK_HEADINGS else self.back_heading_by_text(b, role)
            if heading:
                if role not in BACK_HEADINGS:
                    plan.decide("mechanical", "style", b.src,
                                f"スタイル「{b.style_name}」の段落「{_para_text(b)[:20]}」を後付けの見出しと推定（文字列から）")
                state = BACK_HEADINGS[heading]
                plan.region[b.src] = state
                keep_prev = False       # 空白だけの後ろの見出しで、前の見出し（の節）を残すとき真（replace_back が False）
                # 同じ種類の見出しが 2 つになるときは、前の見出し（の節）が出力にも除外にも入らなくなる（replace_back。K1）
                if state == "notes":
                    if self.replace_back("notes", plan.notes, b, role):
                        plan.notes = BackSec(heading=b)
                    else:
                        keep_prev = True
                    plan.locations[b.src] = "付記（見出し）"
                elif state == "ack":
                    if self.replace_back("ack", plan.ack, b, role):
                        plan.ack = BackSec(heading=b)
                    else:
                        keep_prev = True
                    plan.locations[b.src] = "謝辞（見出し）"
                elif state == "fn":
                    if self.replace_back("fn_heading", plan.fn_heading, b, role):
                        plan.fn_heading = b
                    else:
                        keep_prev = True
                    plan.locations[b.src] = "注（見出し）"
                    if plan.ref_heading is not None:
                        plan.decide("mechanical", "note", b.src,
                                    "注の節が引用文献の後ろにある（テンプレートでは引用文献の前）。XML では位置に関係なく注の一覧として出力した")
                elif state == "refs":
                    if self.replace_back("ref_heading", plan.ref_heading, b, role):
                        plan.ref_heading = b
                    else:
                        keep_prev = True
                    plan.locations[b.src] = "引用文献（見出し）"
                if keep_prev:
                    continue            # 空白だけの見出しは除外に記録するだけ。注の途中の状態（表の候補・current_fn）は変えない
                self._heading_by_text[b.src] = role not in BACK_HEADINGS
                if pending and current_fn is not None:
                    settle(current_fn)      # キャプションだけの注の候補（表が続かなかった）の前の表は、その注に入れる
                flush()                     # 次の見出しまでに注が始まらなかった表は除外（要確認）
                current_fn = None
                continue
            plan.region[b.src] = state or "back"
            if state in APP_PLACE and not b.is_blank and role != "ref" and appendix_heading(_para_text(b)):
                # 引用文献などの後ろの、資料の見出しと思われる段落（参考文献のスタイル以外で、「資料1　…」などの見出しの形の
                # 段落。見出しのスタイルでも文字で決める〈引用文献を分ける「＜英文献＞」などの小見出しを知らせない〉）。暫定の判断で、
                # 資料にはせず知らせるだけにする（決定事項 8(b) は利用者に未確認）。段落の扱い（引用文献の 1 件など）は変えない
                plan.app_after_refs.append(b.src)
                plan.warnings.append(f"{b.src}: {APP_PLACE[state]}の中に、資料の見出しと思われる段落「{_para_text(b).strip()[:20]}」"
                                     f"があります。今の版では、引用文献などの後ろの資料は資料として扱わず、{APP_PLACE[state]}の"
                                     "段落として出力しました")
            if b.is_blank:
                plan.exclude_blank(b)
                continue
            if state in ("refs", "fn") and self.textless(b) and (state == "refs" or current_fn is None):
                # 引用文献の節の、文字が 1 文字もない段落（画像・図形を結び付けただけの段落）は、中身のない <ref> にせず、空白の
                # 除外に記録する（注の節では、注がまだ始まっていない所の同じ形の段落だけ。続きの段落は注の中に残す）。文字は 1 文字も
                # ないので blank の除外（不変性チェックが空白だけと確かめる）で、理由だけ画像用にする。画像は、XML に入らなかった画像
                # として pipeline.lost_images が今までどおり知らせる（理由と場所は、その知らせの手がかりになる）
                if state == "refs":
                    plan.exclude_blank(b, REF_IMAGE_EXCLUDED)
                    plan.locations[b.src] = (f"引用文献 {len(plan.refs)}件目の後ろ" if plan.refs
                                             else "引用文献（見出しの後ろ、1件目の前）")
                else:
                    plan.exclude_blank(b, FN_IMAGE_EXCLUDED)
                    plan.locations[b.src] = (f"注 {len(plan.fns)}件目の後ろ" if plan.fns else "注（見出しの後ろ、1件目の前）")
                continue
            if state == "refs":
                plan.refs.append(RefNode(para=b))
                plan.locations[b.src] = f"引用文献 {len(plan.refs)}件目"
            elif state == "fn":
                # 番号（Word の自動番号の「1)」、手で打った「1)」「（注1）」、上付きの数字）で始まる段落から新しい注。
                # 番号のない段落は前の注の続き。AI の指定（fn_start: 新しい注の始まり / p: 前の注の続き）があればそれに従う
                auto, mark, sup_lead = self.note_lead(b)
                starts = bool(auto or mark or sup_lead)
                ai_role = self.overrides.get(b.src)
                if ai_role == "fn_start":
                    starts = True
                elif ai_role == "p" and current_fn is not None:
                    starts = False
                if starts or current_fn is None:
                    if pending and current_fn is not None:
                        settle(current_fn)  # キャプションだけの注の候補（表が続かなかった）の前の表は、その注に入れる
                    current_fn = FnNode(paras=[b])
                    if auto:
                        current_fn.number = auto[2]
                    elif mark:
                        current_fn.number = mark[2]
                        current_fn.mark_range = mark[:2]
                    elif sup_lead:
                        current_fn.number = num_of(sup_lead.group(1))
                        current_fn.mark_range = (sup_lead.start(1), sup_lead.end(1))
                    plan.fns.append(current_fn)
                    fn_role[b.src] = role
                    if pending and not caption_only(current_fn):
                        settle(current_fn)  # 最初の注より前の表は、その注の 1 段落目の後ろ
                else:
                    if pending:
                        settle(current_fn)  # キャプションだけの注の候補に続きの段落があった: 候補の前の表は、その 1 段落目の後ろ
                    current_fn.paras.append(b)
                    fn_role[b.src] = role
                plan.locations[b.src] = f"注 {len(plan.fns)}件目"
            elif state in ("notes", "ack"):
                target = plan.notes if state == "notes" else plan.ack
                self.add_back_para(target.children, b, heading=role in HEADING_LEVEL)
                plan.locations[b.src] = ("付記" if state == "notes" else "謝辞") + f" 第{len(target.children)}段落"
            else:
                plan.exclude(b, BACK_OTHER_EXCLUDED)
        if pending and current_fn is not None:
            settle(current_fn)
        flush()

    # ----------------------------------------------------------------- front (en) + appendix
    def build_front_en(self, items):
        plan = self.plan
        in_abstract = False
        app = None
        pending_name = None
        ai_abstract = False         # AI が abstract を指定した段落があった（後ろで資料が始まっていなければ、そこから英文要旨が続く）
        for b, role in items:
            key = self.outside_key(b) if app is None and in_shape(b) else ""
            if key:
                # 資料が始まる前（英文の題目・著者・要旨）の段落に結び付いた図形の中身は、英文の部分の段落にしない（N7。build_back と
                # 同じく、状態を変えずに飛ばして記録する）。資料の中の図形は、今までどおり資料の中に出す
                self.outside.setdefault(key, "front_en")
                continue
            if isinstance(b, Table):
                troles = self.table_roles(b)
                if troles & {"author_en", "aff_en"} and app is None:
                    for p in b.paragraphs():
                        r = self.role_of(p)
                        plan.region[p.src] = "authors"
                        p.role = p.role or r
                        if p.is_blank:
                            plan.exclude_blank(p)
                            continue
                        if r == "author_en":
                            pending_name = self.add_author_en(p)
                        elif r == "aff_en":
                            self.add_aff_en(p, pending_name)
                        else:
                            plan.exclude(p, EN_AUTHOR_TABLE_OTHER_EXCLUDED)
                    continue
                if in_abstract or app is not None:
                    if app is None:
                        app = AppNode(title=None)
                        plan.apps.append(app)
                    app.children.append(TableNode(table=b))
                else:
                    for p in b.paragraphs():
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
                            plan.exclude(p, EN_TABLE_EXCLUDED)
                continue
            plan.region[b.src] = "front_en"
            if b.is_blank:
                plan.exclude_blank(b)
                continue
            text = _para_text(b)
            ai = b.src in self.overrides
            by_style = by_text = False
            sentence = ""
            # 「資料1　…」などの見出しの形の段落（文の形の段落は除く。appendix_heading）と、英文要旨の後ろの、章・節・項見出しの
            # スタイルの段落（英文要旨の中に見出しは来ないので、資料の始まりとみなす。決定事項 8(a)。資料の中の見出しのスタイルの
            # 段落は、今までどおり資料の中の段落）。AI の指定がなければ、ここから資料を始める
            head_text = (in_abstract or app is not None) and appendix_heading(text)
            head_style = in_abstract and app is None and (self.style_role(b) if ai else role) in HEADING_LEVEL
            if ai and role in ("abstract", "p"):
                starts = False              # AI が資料の見出しではないと指定した（文字・見出しのスタイルより優先）
            elif role == "app_heading":
                starts = True               # AI が資料の見出しと指定した
            elif head_text:
                starts = by_text = True
            else:
                starts = by_style = head_style and b.role_origin == "style"
                if not starts and (in_abstract or app is not None):
                    # 見出しの形に合うが、文とみなした段落（判断の一覧に記録する。下。AI が役割を指定した段落は、上で決まる）
                    sentence = appendix_sentence(text)
            if ai and role == "abstract":
                app = None                  # AI の指定で英文要旨に戻す（後ろの段落も、次の資料の見出しまで英文要旨）
                ai_abstract = True
            elif ai and role == "p" and app is None and not (in_abstract and ai_abstract and not (head_text or head_style)):
                # AI が資料の中の段落と指定した段落の前に資料がない（最初の資料の見出しへの p など）: 見出しのない資料を始め、
                # その最初の段落にする（資料の文字を英文要旨に入れない。英文要旨に戻すのは abstract だけ）。ただし、AI が
                # abstract で英文要旨に戻した後ろの、見出しでない段落への p は、英文要旨のまま（資料を始めない）
                app = AppNode(title=None)
                plan.apps.append(app)
                in_abstract = False
            if starts:
                first = app is None
                app = AppNode(title=b)
                plan.apps.append(app)
                plan.region[b.src] = "app"
                plan.locations[b.src] = f"資料{len(plan.apps)}（見出し）"
                in_abstract = False
                head = text.strip()[:20]
                if by_style:
                    plan.decide("mechanical", "style", b.src,
                                f"英文要旨の後ろの、見出しのスタイル「{b.style_name}」の段落「{head}」から資料とした"
                                "（英文要旨の中に見出しは来ないため）。資料でなければ、Word でその段落のスタイルを英文要旨の"
                                "スタイルに直して変換し直す（AI による補完では、set_role の abstract で英文要旨に戻せる）")
                elif by_text:
                    # 文字の規則で始めた資料も記録する（文の形の段落を見出しと誤ったときに、レポートの 4 章と AI 依頼文の推定で
                    # 気づけるように）
                    back = "英文要旨の段落（abstract）" if first else "前の資料の段落（p）"
                    plan.decide("mechanical", "style", b.src,
                                f"段落「{head}」を資料の見出しとした（「資料」「付録」「附録」「Appendix」で始まる見出しの形のため）。"
                                f"資料の見出しでなければ、AI による補完の set_role で{back}に戻せる")
                continue
            if app is not None:
                plan.region[b.src] = "app"
                plan.locations[b.src] = f"資料{len(plan.apps)} 第{len(app.children) + 1}要素"
                if sentence:
                    self.note_appendix_sentence(b, text, sentence, first=False)
                if role in HEADING_LEVEL or self.guess_heading(b, strict=False):
                    self.add_back_para(app.children, b, formula=False, heading=True)   # 資料内の見出しは段落として出力（箇条にしない）
                elif self.is_image_para(b) and not self.formula_node(b):
                    app.children.append(FigNode(image_paras=[b]))
                else:
                    self.add_back_para(app.children, b)
                continue
            if role == "title_en":
                plan.title_en.append(b)
                plan.locations[b.src] = "英文題目"
            elif role == "subtitle_en":
                plan.subtitle_en.append(b)
                plan.locations[b.src] = "英文副題"
            elif role == "author_en":
                pending_name = self.add_author_en(b)
            elif role == "aff_en":
                self.add_aff_en(b, pending_name)
            elif role == "abstract_heading":
                if self.replace_back("abstract_heading", plan.abstract_heading, b, role):
                    plan.abstract_heading = b
                plan.locations[b.src] = "英文要旨（見出し）"
                in_abstract = True
            elif role == "abstract" or in_abstract:
                plan.abstract.append(b)
                plan.locations[b.src] = f"英文要旨 第{len(plan.abstract)}段落"
                in_abstract = True
                if sentence:
                    self.note_appendix_sentence(b, text, sentence, first=True)
                if plan.lang == "ja":
                    self.check_abstract_ja(b, text, sentence)
            else:
                plan.locations[b.src] = "英文部分"
                plan.exclude(b, EN_OTHER_EXCLUDED)

    def note_appendix_sentence(self, b, text, sentence, first):
        """「資料」などで始まり資料の見出しの形（RE_APPENDIX）に合うが、文の形（appendix_sentence）なので資料の見出しにしなかった
        段落を、判断の一覧に記録する（applied=False。レポートの 4 章と、AI 依頼文の「推定:」に載る）。

        文の形の判定で見出しを文と誤ったときに、気づいて直せるように（最初の資料なら見出しと資料の段落が英文要旨に入り、2 つ目
        からの資料なら前の資料につながる）。first: 英文要旨の段落（最初の資料の見出しの位置）か。
        """
        where = "英文要旨の段落のまま" if first else "前の資料の段落のまま"
        how = ("Word でその段落に章・節・項見出しのスタイルを付けて変換し直すと、文字はそのままで資料になる（AI による補完では、"
               "set_role の app_heading で資料にできる）") if first else "AI による補完の set_role の app_heading で資料にできる"
        self.plan.decide("mechanical", "style", b.src,
                         f"段落「{text.strip()[:20]}」は「資料」「付録」「附録」「Appendix」で始まるが、{sentence}の形なので、"
                         f"資料の見出しにしなかった（{where}）。資料の見出しなら、{how}", applied=False)

    def check_abstract_ja(self, b, text, sentence=""):
        """英文要旨の段落に、かな・漢字が 3 割以上あれば知らせる（資料などの和文が英文要旨に入っているかもしれない）。

        自動では移さない。判断の記録（applied=False。AI 依頼文の「推定:」に載り、AI が app_heading を提案できる）と、
        10 章の警告と、要確認の知らせ（report.actions の abstract_ja）にする。sentence: 段落が「資料1　…。」のように資料の見出しの
        形で始まるが、文の形なので資料の見出しにしなかった（appendix_sentence）。このときは、見出しを付ける案内ではなく、その段落に
        見出しのスタイルを付ける案内にする（文字を変えずに資料にできる）。
        """
        plan = self.plan
        t = "".join(text.split())
        if not t or len(RE_KANA_KANJI.findall(t)) < ABSTRACT_JA_RATIO * len(t):
            return
        head = text.strip()[:20]
        plan.abstract_ja.append(b.src)
        plan.decide("mechanical", "style", b.src,
                    f"英文要旨の段落「{head}」は、かな・漢字が 3 割以上ある（資料などの和文が英文要旨に入っているかもしれない）。"
                    "自動では移していない", applied=False)
        if sentence:
            how = (f"この段落は「資料」などで始まりますが、{sentence}の形なので、資料の見出しにしていません。資料の見出しなら、Word で"
                   "この段落に章・節・項見出しのスタイルを付けて変換し直してください（文字はそのままで資料になります）")
        else:
            how = ("資料などの和文なら、Word で資料の見出しの段落に章・節・項見出しのスタイルを付けて（見出しがなければ、資料の前に"
                   "「資料1」などの見出しを付けて）変換し直してください")
        plan.warnings.append(f"{b.src}: 英文要旨の段落「{head}」に、かな・漢字が 3 割以上あります。{how}")

    def add_author_en(self, p) -> Author:
        plan = self.plan
        idx = getattr(self, "_en_count", 0)
        self._en_count = idx + 1
        plan.locations[p.src] = f"著者{idx + 1}（英文）"
        if idx < len(plan.authors):
            plan.authors[idx].name_en = p
            return plan.authors[idx]
        a = Author(name_en=p)
        plan.authors.append(a)
        return a

    def add_aff_en(self, p, author: Optional[Author]):
        plan = self.plan
        plan.locations[p.src] = "所属（英文）"
        text = _para_text(p).strip()
        if author is not None:
            # 和文所属と対応付ける（同じ著者の和文所属のうち、英文が未設定のもの）
            for aff in author.affs:
                if aff.en is None:
                    aff.en = p
                    return
                if _para_text(aff.en).strip() == text:
                    if aff.en is not p:
                        plan.exclude(p, f"重複する所属（{aff.en.src} と同一の文字列のため 1 つにまとめた）")
                    return
        for aff in plan.affs:
            if aff.en is not None and _para_text(aff.en).strip() == text:
                if author is not None and aff not in author.affs:
                    author.affs.append(aff)
                plan.exclude(p, f"重複する所属（{aff.en.src} と同一の文字列のため 1 つにまとめた）")
                return
        aff = Aff(en=p)
        plan.affs.append(aff)
        if author is not None:
            author.affs.append(aff)

    def attach_word_notes(self):
        """Word の脚注・文末脚注を、本文で最初に参照される順の通し番号で、注のリストの後ろに加える（決定事項 7）。

        参照の順は doc.all_paragraphs() の順（document.xml の段落の順。XML に出力しなかった段落の参照も、その位置で数える。
        Word が脚注に番号を付ける順と同じ）。続けて、集めた注の中の参照を順に足す（脚注の中から参照した文末脚注も出力する）。
        番号は、builder.word_note_marks が plan.fns の中の Word の注の順に付ける（設定 fn_mark。本誌は「1)」）。
        削除の変更履歴の中の参照は、参照として数えない（docx_reader が Document.deleted_note_refs に記録する）。
        参照されていない注の段落は、理由を付けて除外する（空白だけの段落は exclude_blank）。
        参照がどれも、XML に出力しなかった段落か、注の番号をリンクにしない段落（題目・著者名・所属・引用文献など。
        ArticlePlan.no_link_paras）の中にある注は、本文からのリンクのない注（FnNode.linked が偽）として出力し、判断の一覧と
        レポートの 8 章で知らせる。手で書いた注と番号が重なるときは、番号は変えずに plan.note_overlap に記録し、10 章の警告に
        する（要確認の知らせは report の note_overlap）。
        """
        plan = self.plan
        notes = {note_key(kind, nid): paras
                 for kind, d in (("footnote", self.doc.footnotes), ("endnote", self.doc.endnotes)) for nid, paras in d.items()}
        order, where, custom = [], {}, set()

        def collect(paras):
            for p in paras:
                for a in p.atoms:
                    if a.kind != "fnref":
                        continue
                    k = note_key(a.fn_kind, a.fn_id)
                    if not notes.get(k):
                        continue            # 参照先の注が docx にない（今までどおり注にしない。本文の参照は何も出力されない）
                    refs = where.setdefault(k, [])
                    if p.src not in refs:
                        refs.append(p.src)
                    if a.fn_kind.endswith("-custom"):
                        custom.add(k)
                    if k not in order:
                        order.append(k)

        collect(self.doc.all_paragraphs())
        i = 0
        while i < len(order):               # 集めた注の中の参照（足した注の中も続けて見る）
            collect(notes[order[i]])
            i += 1
        # リンクにならない参照: XML に出力しなかった段落と、注の番号をリンクにしない段落（題目・著者名・所属・引用文献など）の中のもの
        nolink = plan.no_link_paras()
        unlinked = {e.src for e in plan.exclusions} | set(nolink)
        nodes = []
        for n, k in enumerate(order, 1):
            paras = notes[k]
            node = FnNode(paras=paras, word_note=True, word_kind=k.partition(":")[0], word_id=k, word_refs=where[k],
                          linked=any(s not in unlinked for s in where[k]), custom_mark=k in custom)
            for j, p in enumerate(paras, 1):
                plan.region[p.src] = "fn"
                plan.locations[p.src] = f"{note_label(k)}（注 {n}）" + (f" 第{j}段落" if len(paras) > 1 else "")
            plan.fns.append(node)
            nodes.append((n, node))
        for k, paras in notes.items():      # 参照されていない注
            if k in where:
                continue
            why = unreferenced_note_reason(k, k in self.doc.deleted_note_refs)
            for p in paras:
                plan.locations[p.src] = note_label(k)
                if p.is_blank:
                    plan.exclude_blank(p)   # 空白だけの段落（文字がまったくない段落は記録しない）
                elif p.plain():
                    plan.exclude(p, why)
        if not nodes:
            return
        ends = sum(1 for _, fn in nodes if fn.word_kind == "endnote")
        if ends == len(nodes):
            what = f"Word の文末脚注機能で書かれた注 {ends} 件を、本文で最初に参照される順の通し番号で注の一覧にした"
        elif ends:
            what = (f"Word の脚注・文末脚注機能で書かれた注 {len(nodes)} 件（脚注 {len(nodes) - ends} 件・文末脚注 {ends} 件）を、"
                    "本文で最初に参照される順の通し番号で注の一覧にした")
        else:
            what = f"Word の脚注機能で書かれた注 {len(nodes)} 件を、注の一覧にした"
        plan.decide("mechanical", "note", nodes[0][1].paras[0].src,
                    f"{what}（テンプレートの規定は、本文に上付きの「1)」を書き、注は「注」の節にまとめる）。"
                    "本文と注の一覧の番号、注の見出しは補った（8 章）")
        # 手で書いた注（「注」の節の「1)」など）と番号が重なる Word の注（Word の注は 1 から番号を付ける〈builder.word_note_marks〉）。
        # 手で書いた注の後ろから番号を続けるかは利用者に確かめていないので、番号は変えずに知らせる（10 章の警告と要確認）
        manual = {fn.number for fn in plan.fns if not fn.word_note and fn.number is not None}
        plan.note_overlap = sorted(manual & set(range(1, len(nodes) + 1)))
        if plan.note_overlap:
            marks = "、".join(self.journal.fn_mark.format(n=k) for k in plan.note_overlap)
            plan.warnings.append(f"手で書いた注と Word の脚注・文末脚注が両方あり、注の番号 {marks} が重なっています（Word の注の番号は"
                                 "本誌の形式で 1 から付けるため）。注の一覧に、同じ番号の別の注が並びます（本文からリンクしている"
                                 "注は、それぞれ正しい注を指します）。Word でどちらかの書き方にそろえて、変換し直してください")
        for n, fn in nodes:
            label = f"{note_label(fn.word_id)}（注 {n}）"
            if not fn.linked:
                out, shown = plan.unlinked_places(fn.word_refs)
                move = "本文からリンクする注なら、Word で参照を本文の段落に移して変換し直す"
                if not shown:
                    msg = (f"{label}は、本文の参照が XML に出力しなかった段落（{'、'.join(out)}）の中にだけあるので、"
                           f"本文からのリンクのない注として出力した（8 章）。{move}")
                else:
                    # 題目・引用文献などの中の参照（注の番号は上付きの文字だけで、リンクにしない。著者名の中では番号も出さない）
                    before = f" XML に出力しなかった段落 {'、'.join(out)} と、" if out else ""
                    msg = (f"{label}は、参照が{before}{'、'.join(shown)} の中にだけあるので、本文からのリンクのない注として"
                           f"出力した（{no_link_rule(nolink[s] for s in fn.word_refs if s in nolink)}。8 章）"
                           + (f"。{move}" if out else ""))
                plan.decide("mechanical", "note", fn.paras[0].src, msg)
            if fn.custom_mark:
                # 暫定の判断: 記号を自分で付けた注も、脚注と同じく番号を 1 つ使う（本文の記号は docx の文字のまま）。本文の参照は
                # 中身のない <xref> で、記号はその後ろに出るので、記号はリンクにならない（emit.Emitter.write_object）
                plan.decide("mechanical", "note", fn.paras[0].src,
                            f"{label}は、本文の記号を自分で付けた注（Word の「記号」）。本文の記号は docx の文字のまま、"
                            f"注の一覧の番号は「{self.journal.fn_mark.format(n=n)}」にした（本文と注の一覧で記号が違う。"
                            "本文の注へのリンクは記号の前の中身のない参照で、記号はリンクにならない。PDF と照らし、J-STAGE の"
                            "プレビューで確認すること）")

    def assign_ids(self):
        plan = self.plan
        figs, tabs, forms = [], [], []

        def walk(nodes):
            for node in nodes:
                if isinstance(node, Sec):
                    walk(node.children)
                elif isinstance(node, FigNode):
                    figs.append(node)
                elif isinstance(node, TableNode):
                    tabs.append(node)
                elif isinstance(node, FormulaNode):
                    forms.append(node)
                elif isinstance(node, (BackSec, AppNode, BoxNode)):
                    walk(node.children)         # 囲みの中の別行数式にも FD の ID を付ける
        walk(plan.body)
        for extra in (plan.notes, plan.ack):
            if extra:
                walk(extra.children)
        for fn in plan.fns:
            tabs.extend(node for _, node in fn.tables)      # 注の節の中の表（docx の順。付記・謝辞の表の後ろ、資料の表の前）
        for app in plan.apps:
            walk(app.children)
        seen = set()
        k = 0
        for f in figs:
            if f.caption is not None:
                k += 1
                f.fid = f"F{k}"
                m = RE_FIGCAP.match(nfkc(_para_text(f.caption)).strip())
                if m:
                    f.number = int(m.group(1))
                    if f.number in seen:
                        plan.decide("mechanical", "figure", f.caption.src, f"図番号 {f.number} が重複している")
                    seen.add(f.number)
        seen = set()
        for i, t in enumerate(tabs, 1):
            t.tid = f"T{i}"
            if t.caption is not None:
                m = RE_TABCAP.match(nfkc(_para_text(t.caption)).strip())
                if m:
                    t.number = int(m.group(1))
                    if t.number in seen:
                        plan.decide("mechanical", "table", t.caption.src, f"表番号 {t.number} が重複している")
                    seen.add(t.number)
        for i, fm in enumerate([f for f in forms if f.label], 1):
            fm.fid = f"FD{i}"
        for i, fn in enumerate(plan.fns, 1):
            fn.fid = f"fn{i}"
        for i, r in enumerate(plan.refs, 1):
            r.rid = f"B{i}"
        for i, a in enumerate(plan.affs, 1):
            a.aid = f"aff{i}"
        plan.figures, plan.tables, plan.formulas = figs, tabs, forms


def classify(doc, journal, overrides=None, placements=None) -> ArticlePlan:
    """段落の役割を決め、論文の構造を組み立てる。

    本文の外（引用文献・注・付記・謝辞・英文の部分）の段落に結び付いた図形があるときだけ、組み立てを 2 回行う（修正計画の N7）:
    どの図形が本文の外かは、英文の部分では資料が始まったかどうかで決まり（build_front_en の中でしか分からない）、本文は
    その前に組み立てるため。1 回目に見つけた図形（Classifier.outside）の中身を、2 回目は本文の最後に回す（split_regions）。
    1 回目が段落に書き込んだもの（役割・役割の由来・覚え書き）は、2 回目の前に戻す。本文の外の図形がなければ 1 回だけ
    （0.24.1 と同じ処理・同じ判断の番号）。
    """
    saved = [(p, p.role, p.role_origin, p.note) for p in _doc_paragraphs(doc)]
    first = Classifier(doc, journal, overrides, placements)
    plan = first.run()
    if not first.outside:
        return plan
    for p, role, origin, note in saved:
        p.role, p.role_origin, p.note = role, origin, note
    return Classifier(doc, journal, overrides, placements, outside=first.outside).run()


FRONT_JA_REGIONS = ("front_ja", "authors", "excluded")   # conflict_overrides: 著者名の付かない最後の所属の範囲が続く領域


def conflict_overrides(plan, overrides) -> set:
    """AI の set_role（overrides。段落 ID -> 役割）のうち、構造の衝突（plan.structure_conflicts。K1・K2）の範囲の中の段落への指定の、
    段落 ID の集合。pipeline.convert が、AI の回答で組み直した後に衝突ができたとき、まずこれらの指定だけを使わずに組み直す。

    範囲は衝突ごとに、落ちる段落（lost）と置き換えた段落（by）の、plan.paras の並び（docx の順）での最初から最後まで。著者名が
    続かないまま残った所属（aff で by が ""）は、最初の所属から、和文の冒頭（front_ja・authors と、AI が除外した段落 excluded）が
    続くところまで（本文・後付けへの指定を巻き込まない）。範囲の中に指定がなければ空の集合。
    """
    srcs = list(plan.paras)
    order = {s: i for i, s in enumerate(srcs)}
    spans = []
    for c in plan.structure_conflicts:
        pos = [order[s] for s in list(c.lost) + ([c.by] if c.by else []) if s in order]
        if not pos:
            continue
        lo, hi = min(pos), max(pos)
        if c.kind == "aff" and not c.by:
            end = next((k for k in range(lo + 1, len(srcs)) if plan.region.get(srcs[k]) not in FRONT_JA_REGIONS), len(srcs))
            hi = max(hi, end - 1)
        spans.append((lo, hi))
    return {s for s in overrides if s in order and any(lo <= order[s] <= hi for lo, hi in spans)}


def _doc_paragraphs(doc):
    """doc のすべての段落（本文・表のセル・テキストボックス・Word の脚注・文末脚注）。"""
    yield from doc.all_paragraphs()
    for notes in (doc.footnotes, doc.endnotes):
        for paras in notes.values():
            yield from paras
