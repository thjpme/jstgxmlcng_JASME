"""点検の結果（docs/FIELD_TEST_2026-11.md）と修正計画（docs/FIX_PLAN_RELEASE.md）を組み立てる。"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

S = Path(__file__).resolve().parent.parent
R = Path("/home/user/jstgxmlcng_JASME")
v = json.load(open(S / "verified.json", encoding="utf-8"))
cl = json.load(open(S / "clusters.json", encoding="utf-8"))
cl = cl["clusters"] if isinstance(cl, dict) else cl
finds = {f["id"]: f for f in map(json.loads, open(S / "all.jsonl", encoding="utf-8"))}

SEV = ["must_fix", "high", "medium", "low", "record_only"]
SEV_JA = dict(must_fix="修正必須", high="高", medium="中", low="低", record_only="記録しておくだけ")
MODEL_JA = dict(haiku="Haiku", sonnet="Sonnet", opus="Opus", fable="Fable")
RANK = dict(haiku=0, sonnet=1, opus=2, fable=3)

FRONT = {"C009", "C010", "C015", "C016", "C035", "C036", "C064", "C072", "C043", "C130", "C136"}
FIG = {"C002", "C003", "C028", "C070", "C062", "C078", "C122", "C124"}
UNITS = [
    ("R1", "A", "読み取り（docx の文字・番号）", "ooxml.py・docx_reader.py・numbering.py・omml.py"),
    ("R1", "B", "図・表の本体の組み立て", "structure.py（place_floats・cell_figures・table_for_figure）・builder.py・floats.py・report.py"),
    ("R1", "C", "冒頭部（題目・著者・所属）", "structure.py（build_front_ja・read_author_table_ja）・builder.py（person_name）"),
    ("R1", "D", "本文・後付けの構造（見出し・領域・引用文献の節）", "structure.py（split_regions・build_back・guess_heading）"),
    ("R1", "E", "引用文献の解析とリンク", "refparse.py・linker.py"),
    ("R1", "F", "XML の組み立て・守り・知らせ", "builder.py・emit.py・pipeline.py・fidelity.py・report.py"),
    ("R1", "G", "AI 補完（依頼文・回答の検証と適用）", "ai_assist.py・pipeline.py"),
    ("R1", "H", "画像・ZIP・画面・書誌情報", "images.py・package.py・app.py・cli.py・config.py"),
    ("R1", "I", "リリースの準備・安全・文書", "pyproject.toml・tools/・notebooks/・docs/・CI"),
    ("R2", "P", "PDF との照合（誤った直しを作らない）", "pdfmatch.py"),
    ("R2", "Q", "docx の補完と補完の確かめ", "pdfdocx.py・fidelity.py（verify_supplement）"),
    ("R2", "N", "ルート2 の知らせ（13 章）とその他", "report.py・pdfmatch.py・pyproject.toml"),
]


def unit_of(c):
    cid, a = c["cid"], c["area"]
    if c["route"] == "R2":
        return "P" if a in ("pdfmatch", "perf") else "Q" if a in ("pdfdocx", "verify_guard") else "N"
    if cid in FRONT:
        return "C"
    if cid in FIG or a == "figure_table":
        return "B"
    return dict(read="A", structure="D", link_ref="E", build_xml="F", verify_guard="F", notice_report="F", ai="G",
                images_zip="H", app_ui="H", meta_config="H", release="I", security="I", docs="I", perf="F",
                test_data="Z")[a]


def model_of(c):
    r = v.get(c["cid"])
    if r:
        return r["fix_model"]
    ms = [finds[m].get("fix_difficulty") for m in c["members"] if finds[m].get("fix_difficulty")]
    if ms:
        return max(ms, key=RANK.get)
    return "haiku" if c["proposed"] == "low" and c["area"] in ("notice_report", "docs") else "sonnet"


rows = []
for c in cl:
    r = v.get(c["cid"])
    rows.append(dict(c, sev=r["severity"] if r else c["proposed"], route=r["route"] if r else c["route"], verified=bool(r),
                     model=model_of(c), size=r["size"] if r else "", unit=unit_of(c),
                     dec=bool((r or {}).get("owner_decision") or (not r and c.get("owner_decision"))),
                     shape=bool(r and r["output_changes"]), verdict=(r or {}).get("verdict", "")))
by = defaultdict(list)
for x in rows:
    by[(x["route"], x["sev"])].append(x)

# 2026-11-12 の所有者の決定を反映した扱い（docs/FIX_PLAN_RELEASE.md の「所有者の決定」）
DONE = {"C008": "自動番号を abstractNum ごとに数える", "C010": "字間に空白のある氏名を分ける。推定は要確認",
        "C064": "分けられない氏名を要確認に（C010 と一緒）", "C072": "氏名の前後の空白を落とす（C010 と一緒）",
        "C011": "記号用フォントの文字を普通の文字にして知らせる", "C012": "記号の挿入の文字を読む",
        "C013": "要確認で知らせる。任意の画像の場所も W1 で済み",
        "C017": "引用文献の年の位置", "C019": "依頼文・見本を貼った回答を断る", "C056": "照合の鍵を必ず 1 文字に",
        "C041": "空白の段落での領域の切り替え。文字のない段落を文献にしない", "C045": "DTD 不合格の知らせに場所と直し方",
        "C018": "W1 で、入れた画像を図番号の名前で持ち越す（別の図の画像を入れない）", "C070": "W1 で、画像が要る図・表の一覧に番号・キャプション・場所・名前を出す",
        "C085": "W1 で、入れた画像の中身を変えずに入れる",
        "W1": "図・表の画像を、作業する人が用意する方式にした（実装済み。0.33.0 で main に反映した）"}
HOLD = {"C001": "テンプレートに資料のセクションを入れて対応", "C093": "数式の画像はテンプレートでなくなる見込み"}
GONE = {  # 方式の変更でなくなる（直さない）
    "W1": ["C002", "C007", "C033", "C124", "C040", "C069", "C076", "C084", "C086", "C125", "C081", "C101"],
    "W2": ["C024", "C053", "C054", "C112", "C162"],
}
MERGED = {  # 新しい項目の中で作る・直す
    "W1": ["C004", "C005", "C006", "C028", "C029", "C030"],
    "W2": ["C023", "C055", "C109", "C113", "C116"],
    "W3": ["C049", "C107", "C110", "C149", "C152"],
    "W4": ["C115"],
    "W5": ["C106"],
    "W8": ["C039", "C042", "C059", "C066", "C071", "C082", "C118", "C119", "C121"],
}
RAISED = {"C018": "must_fix", "C070": "high", "C085": "high"}
LOWERED = {"C021": "medium", "C025": "medium", "C052": "medium", "C051": "medium", "C022": "high"}
NEW = [
    dict(cid="W2", route="R2", sev2="must_fix", unit="P", model="opus", size="L", freq="全論文",
         title="校正の直し (B) を docx に書き込むのをやめ、違いの分類を「知らせるか」で引き直す（句読点の統一は組版の違いに入れる）"),
    dict(cid="W3", route="R2", sev2="high", unit="N", model="sonnet", size="M", freq="全論文",
         title="PDF との食い違いの知らせを 1 つの要確認にまとめ、ルートを 1 本にし、レポートを短くする"),
    dict(cid="W4", route="R2", sev2="high", unit="N", model="sonnet", size="S", freq="—",
         title="別の論文のファイルを渡したとき（題目が PDF になく、段落の半分以上が見つからない）は変換を中止する"),
    dict(cid="W5", route="R2", sev2="high", unit="N", model="sonnet", size="M", freq="全論文",
         title="巻・号・ページ・受付日・採用日を PDF から読んで入力欄に先に入れ、入力と PDF が違えば知らせる"),
    dict(cid="W6", route="R1", sev2="high", unit="C", model="sonnet", size="M", freq="—",
         title="題目・著者名・所属が PDF の 1 ページ目にあるかを確かめる（著者・題目のスタイルの誤りをまとめて要対応にする）"),
    dict(cid="W8", route="R1", sev2="high", unit="G", model="opus", size="L", freq="15/28",
         title="AI 補完を必須にせず強く推奨する仕上げにし、出版版 PDF を AI に渡し、依頼文を作り直す（スタイルの直し方の提案を含む）"),
]
OUT = set(DONE) | set(HOLD) | {c for v in GONE.values() for c in v} | {c for v in MERGED.values() for c in v}
rows2 = [dict(n, dec=False, verified=True, verdict="", n_papers=0, new=True) for n in NEW]
RETITLE = {"C003": "本体のない表（キャプションだけの table-wrap）が要対応にならない（図の側は W1 で済み）"}
for x in rows:
    if x["cid"] in OUT:
        continue
    y = dict(x, sev2=RAISED.get(x["cid"], LOWERED.get(x["cid"], x["sev"])), new=False)
    if x["cid"] in RETITLE:
        y["title"] = RETITLE[x["cid"]]
    rows2.append(y)
ORDER = {s: i for i, s in enumerate(SEV)}
rows2.sort(key=lambda y: (ORDER[y["sev2"]], y["cid"]))
by2 = defaultdict(list)
for y in rows2:
    by2[(y["route"], y["sev2"])].append(y)


def table2(ys, full=True):
    if not full:
        out = ["| 番号 | 問題 | 単位 | 担当 |", "|---|---|---|---|"]
        return "\n".join(out + [f"| {y['cid']} | {esc(y['title'])} | {y['unit']} | {MODEL_JA[y['model']]} |" for y in ys])
    out = ["| 番号 | 問題 | 起きた論文 | 検証 | 単位 | 担当 | 規模 | 変更 |", "|---|---|---|---|---|---|---|---|"]
    for y in ys:
        if y["new"]:
            who = MODEL_JA[y["model"]] + ("（設計は Fable）" if y["size"] == "L" else "")
            out.append(f"| {y['cid']} | {esc(y['title'])} | {y['freq']} | — | {y['unit']} | {who} | {y['size']} | 新しい項目 |")
            continue
        ver = ("確認" if y["verdict"] == "confirmed" else "一部確認") if y["verified"] else "未検証"
        ch = (f"{SEV_JA[y['sev']]}から上げた" if y["cid"] in RAISED else f"{SEV_JA[y['sev']]}から下げた" if y["cid"] in LOWERED
              else "範囲を表に限った" if y["cid"] in RETITLE else "")
        out.append(f"| {y['cid']} | {esc(y['title'])} | {freq(y)} | {ver} | {y['unit']} | {MODEL_JA[y['model']]} | {y['size'] or '—'} | {ch} |")
    return "\n".join(out)


def count_table2():
    out = ["| | 修正必須 | 高 | 中 | 低 | 記録しておくだけ | 計 |", "|---|---|---|---|---|---|---|"]
    for rt, name in (("R1", "ルート1（両方に関わるものを含む）"), ("R2", "ルート2（出版版 PDF で補う）")):
        n = [len(by2[(rt, s)]) for s in SEV]
        m = [len(by[(rt, s)]) for s in SEV]
        out.append(f"| {name} | " + " | ".join(f"{a}（{b}）" if a != b else str(a) for a, b in zip(n, m)) + f" | {sum(n)}（{sum(m)}） |")
    return "\n".join(out)


def title_of(cid):
    return next(esc(x["title"]) for x in rows if x["cid"] == cid)


def revised():
    return (f"""## 決定を反映した優先度の一覧（2026-11-12）

所有者の決定（上）で、なくなる問題・1 つの作り変えにまとまる問題・重さが変わる問題がある。それを反映した、**これから直す対象**の一覧。
点検の時点の一覧と、問題ごとの詳細は `docs/FIELD_TEST_2026-11.md`。

件数（括弧の中は点検の時点）:

{count_table2()}

一覧から外したもの（{len(OUT)} 件）:

| 扱い | 問題 |
|---|---|
| 直した | """ + "、".join(f"{c}（{w}）" for c, w in DONE.items()) + """ |
| 保留 | """ + "、".join(f"{c}（{title_of(c)}。{w}）" for c, w in HOLD.items()) + """ |
""" + "".join(f"| {k} でなくなる" + ("（済み。0.33.0）" if k == "W1" else "（直さない）") + " | " + "、".join(f"{c}（{title_of(c)}）" for c in v) + " |\n" for k, v in GONE.items()) + "".join(
    f"| {k} の中で作る・直す" + ("（済み。0.33.0）" if k in ("W1", "W8") else "") + " | " + "、".join(f"{c}（{title_of(c)}）" for c in v) + " |\n" for k, v in MERGED.items()) + f"""
### ルート1（両方のルートに関わるものを含む）

#### 修正必須（{len(by2[('R1', 'must_fix')])} 件）

{table2(by2[('R1', 'must_fix')])}

#### 高（{len(by2[('R1', 'high')])} 件）

{table2(by2[('R1', 'high')])}

#### 中（{len(by2[('R1', 'medium')])} 件。すべて未検証か、検証で中に下げたもの）

{table2(by2[('R1', 'medium')], False)}

#### 低（{len(by2[('R1', 'low')])} 件）

{table2(by2[('R1', 'low')], False)}

#### 記録しておくだけ（{len(by2[('R1', 'record_only')])} 件）

{table2(by2[('R1', 'record_only')], False)}

### ルート2（出版版 PDF との照合と、組版の違いの直し）

#### 修正必須（{len(by2[('R2', 'must_fix')])} 件）

{table2(by2[('R2', 'must_fix')])}

#### 高（{len(by2[('R2', 'high')])} 件）

{table2(by2[('R2', 'high')])}

#### 中（{len(by2[('R2', 'medium')])} 件）

{table2(by2[('R2', 'medium')], False)}

#### 低（{len(by2[('R2', 'low')])} 件）

{table2(by2[('R2', 'low')], False)}

#### 記録しておくだけ（{len(by2[('R2', 'record_only')])} 件）

{table2(by2[('R2', 'record_only')], False)}

""")


def esc(s):
    s = s.replace("|", "｜")
    s = re.sub(r"(?<!`)<(/?[A-Za-z][A-Za-z0-9:-]*)>(?!`)", r"`<\1>`", s)      # 生のタグをコード書式に
    return re.sub(r"\b([A-Za-z][A-Za-z0-9]*>=\d+)", r"`\1`", s)                 # pypdfium2>=4 など


FREQ = json.load(open(S / "doc/freq.json", encoding="utf-8")) if (S / "doc/freq.json").exists() else {}


def freq(x):
    if x["cid"] in FREQ:
        return FREQ[x["cid"]]
    return f"{x['n_papers']}/28" if x["n_papers"] else "—"


def table(xs, detail=False):
    out = ["| 番号 | 問題 | 起きた論文 | 検証 | 単位 | 担当 | 規模 | 決定 |", "|---|---|---|---|---|---|---|---|"]
    for x in xs:
        ver = ("確認" if x["verdict"] == "confirmed" else "一部確認") if x["verified"] else "未検証"
        num = f"[{x['cid']}](#{x['cid'].lower()})" if detail and (S / "doc/detail" / f"{x['cid']}.md").exists() else x["cid"]
        out.append(f"| {num} | {esc(x['title'])} | {freq(x)} | {ver} | {x['unit']} | {MODEL_JA[x['model']]} | {x['size'] or '—'} | "
                   f"{'要' if x['dec'] else ''} |")
    return "\n".join(out)


def count_table():
    out = ["| | 修正必須 | 高 | 中 | 低 | 記録しておくだけ | 計 |", "|---|---|---|---|---|---|---|"]
    for rt, name in (("R1", "ルート1（両方に関わるものを含む）"), ("R2", "ルート2（出版版 PDF で補う）")):
        n = [len(by[(rt, s)]) for s in SEV]
        out.append(f"| {name} | " + " | ".join(map(str, n)) + f" | {sum(n)} |")
    return "\n".join(out)


planted = json.load(open(S / "planted.json", encoding="utf-8"))
OUT_JA = dict(recovered_correctly="正しく復元", flagged_actionable="知らせて直し方も伝わる", flagged_but_unclear="知らせたが直し方が伝わらない",
              silent_wrong="黙って誤った構造を出した", aborted_with_guidance="中止して案内", other="その他")
PL = [  # 仕込んだミスと、関わる問題（点検の判定を、検証の結果で見直したもの）
    ("本文が標準スタイル", "黙って誤った構造を出した", "本文は正しく出るが、番号つきの箇条が章見出しになる", "C014"),
    ("本文にコピペ書式混入", "正しく復元", "XML はミスなしの版と同じ", ""),
    ("注が Word 脚注", "正しく復元", "注の一覧にし、本文からリンク", ""),
    ("節見出しと項見出しが逆", "AI が直した（機械は気づかない）", "AI の回答がなければ誤った入れ子のまま、知らせなし", "C038"),
    ("章番号が自動番号", "正しく復元", "Word の表示どおりの番号を `<label>` に出す", ""),
    ("所属と氏名のセルが逆", "黙って誤った構造を出した", "氏名に所属、所属に氏名が入る", "C036"),
    ("ブロック引用が本文スタイル", "AI が直した（機械は気づかない）", "AI の回答がなければ本文の段落のまま、知らせなし", "C129"),
    ("図表キャプションが逆", "知らせたが直し方が伝わらない", "要対応は出るが原因（スタイルの入れ替わり）を言わず、本体が 1 つずれて組まれる", "C034"),
    ("空行に章見出しスタイル", "正しく復元", "空の見出しは出力しない", ""),
    ("英文部分が 2 段組み", "正しく復元", "XML はミスなしの版と同じ", ""),
    ("Abstract 見出しが英文要約スタイル", "黙って誤った構造を出した", "「Abstract」が要旨の 1 段落目になる", "C073"),
    ("著者情報が表でない", "知らせたが直し方が伝わらない", "和文の著者・所属が XML から消え、要確認は「そのままでかまいません」と読める", "C009"),
    ("参考文献見出しが章見出し", "正しく復元", "文字から後付けの見出しと推定", ""),
    ("見出しと本文が同一段落", "知らせたが直し方が伝わらない", "本文が丸ごと `<title>` に入り、知らせは 10 章の改行の警告だけ", "C037"),
    ("参考文献が途中で改段落", "黙って誤った構造を出した", "1 件の文献が 2 つの `<ref>` に分かれる", "C026"),
    ("題目が本文スタイル", "知らせたが直し方が伝わらない", "題目と著者表が本文に入り、要対応は原因も直し方も言わない", "C035"),
    ("章見出しが本文スタイル", "正しく復元", "太字と番号の形から章見出しと推定", ""),
    ("副題が題目スタイル", "黙って誤った構造を出した", "題目と副題が区切りなしでつながる", "C016"),
    ("参考文献が本文スタイル", "正しく復元", "引用文献の見出しの後ろを引用文献として扱う", ""),
    ("英文著者が表でない", "知らせたが直し方が伝わらない", "英文の著者・所属が XML から消え、案内は英文要旨のスタイルを勧める", "C009"),
]


PL_C = Counter(b for _, b, _, _ in PL)
PL_SUMMARY = f"{len(PL)} 種類のうち、" + "、".join(f"{k} {n}" for k, n in PL_C.most_common()) + "。"


def details(route):
    out = []
    for sev in ("must_fix", "high"):
        for x in by[(route, sev)]:
            p = S / "doc/detail" / f"{x['cid']}.md"
            if p.exists():
                t = p.read_text(encoding="utf-8").strip()
                t = re.sub(r"^### C\d{3} [^\n]*", f'<a id="{x["cid"].lower()}"></a>\n\n### {x["cid"]}（{SEV_JA[sev]}） {esc(x["title"])}', t, count=1)
                out.append(t)
    return "\n\n".join(out)


dec_path = S / "doc/decisions.md"
decisions = dec_path.read_text(encoding="utf-8").strip() if dec_path.exists() else "（未作成）"
decisions = re.sub(r"\A# [^\n]*\n+", "", decisions)
decisions = re.sub(r"(?m)^(#{2,4}) ", r"#\1 ", decisions)
nf = len(finds)
models = None

field = f"""# 実地テストとソース点検の結果（2026-11-11。0.31.1）

正式リリースの前に、実際の原稿でツールを通しで動かし、あわせてソース全体を読み直した結果。見つけた問題に優先度を付け、
ルート1（docx から作る）とルート2（docx から作り、出版版 PDF で補う）に分けて挙げる。**両方のルートに関わる問題はルート1 に入れた**
（ルート2 も docx → XML は同じ処理を通る）。ルート1 で PDF を照合してレポートに載せる機能（`pdfmatch.py`）の問題は、照合の仕組みの
問題なのでルート2 に入れた。直す順番と担当は `docs/FIX_PLAN_RELEASE.md`。

この点検ではコードを直していない。実際の原稿は未公開なので、この文書では論文を「data14」のようにテスト用フォルダの番号だけで呼び、
著者名・題目・本文は書かない（原稿と変換結果は `tests/private/`〈`.gitignore` 済み〉と作業用フォルダにだけ置いた）。

## 確かめ方

- **実地テスト**: 実際の原稿 28 論文（docx と出版版 PDF の対。元原稿をテンプレートに機械的に流し込んだもの）と、そのうち 10 論文に
  「人がやりそうなミス」を 1 つずつ仕込んだ docx 18 件（ミスは 20 種類。1 件は 3 つのミスを 1 つのファイルに入れたもの）の、計 46 docx。
  それぞれをルート1 とルート2 で変換した。浮動配置の図表があって AI による補完が必須の 21 docx は、手動モードの依頼文に AI 役（Opus。
  依頼文と添付画像だけを見て答える）が回答し、その回答を反映して変換し直した。
  変換結果は、論文ごとに 1 エージェント（Opus）が、XML・レポート・補った docx を出版版 PDF と見比べて点検した。
- **ソース点検**: `src/jasme_jats/` と `tools/`・ノートブック・CI を 12 の領域（読み取り、構造、リンク、XML の組み立て、検証と全体の流れ、
  PDF との照合、docx の補完、知らせとレポート、AI 補完、1 画面版と画像・ZIP、リリースの準備、原則とセキュリティの横断）に分け、
  領域ごとに 1 エージェント（Fable）が通読し、疑いは小さな docx を作って再現を試みた。`docs/REVIEW_2026-11.md` の既知の問題は除いた
  （既知でもリリース前に直すべきと判断したものは挙げた）。
- **統合と検証**: 指摘 {nf} 件を、同じ原因（同じ直しで直るもの）ごとに {len(rows)} 件の問題にまとめた。そのうち「修正必須」「高」と見立てた
  57 件は、1 件ずつ別のエージェント（修正必須は Opus、高は Sonnet）が反証を試みて確かめ、原因のコードと直し方を決めた。
  反証されたものは 0 件、確認 53 件、一部確認 4 件。検証で重さを変えたものがある（下の表は検証の後の重さ）。
  「中」以下は検証していない（点検者の再現を根拠にそのまま載せた。表の「未検証」）。

## 結果の概要

- 46 docx × 2 ルートの変換で、例外・タイムアウトは 0 件。変換できたものは、文字の不変性チェック・最終出力の再チェック・補完の確かめが
  すべて合格した。DTD 検証の不合格は 1 論文（data14。要対応として知らせは出る。C001・C044・C045）。
- つまり、**今の守り（不変性チェック・DTD・補完の確かめ）をすべて通ったうえで、文字・番号・構造が誤っている出力**が見つかった。
  不変性チェックは「読み取った文字が XML に出たか」を確かめるので、読み取りと検証が同じ読み方で落とす文字（C012・C013）、生成文字
  （自動番号。C008・C011）、構造の誤り（図・表の本体、著者、見出し）、ルート2 が docx を直した後の文字（C020〜C025）は見つけられない。
- 46 docx のうち 21 docx（28 論文中 15 論文）は、浮動配置の図表があり AI による補完がないと変換できない。

問題の数（検証の後の重さ）:

{count_table()}

優先度の意味:

| 優先度 | 意味 |
|---|---|
| 修正必須 | 文字・番号・構造が**知らせなしに**誤る。登載できない XML を知らせなしで出す。ルート2 が docx にも PDF にもない文字を作る・PDF にある文字を消す |
| 高 | 誤るが知らせはある。知らせが的外れで直し方が伝わらない。まれな原稿で黙って誤る |
| 中 | 手戻りが増える。誤報。件数が多すぎて読めない知らせ |
| 低 | 文言・見た目・細部 |
| 記録しておくだけ | テストデータ（流し込み）の間違い、確かめていない推測、仕様どおりで扱いが妥当なもの |

表の列: 「起きた論文」は実際の原稿 28 論文のうち起きた数（「変種」は、もとの 28 論文では起きず、ミスを仕込んだ docx でだけ起きたもの。
— は合成の docx・ソース点検だけで確かめたもの。未検証の問題の数は点検者の申告で、変種を含むことがある）、「単位」は修正計画の単位、
「担当」は直すのに必要な最も軽いモデルの見立て、「規模」は S（1 関数・50 行以内）・M（数関数・テスト込み 300 行以内）・L（それ以上）、
「決定」は直し方に所有者の判断が要るもの（末尾の「決定事項」）。

### 仕込んだミスの結果

| 仕込んだミス | 結果 | 何が起きたか | 関わる問題 |
|---|---|---|---|
""" + "\n".join(f"| {a} | {b} | {c} | {d} |" for a, b, c, d in PL) + f"""

{PL_SUMMARY}

## ルート1 の問題（両方のルートに関わるものを含む）

### 修正必須（{len(by[('R1', 'must_fix')])} 件）

{table(by[('R1', 'must_fix')], True)}

### 高（{len(by[('R1', 'high')])} 件）

{table(by[('R1', 'high')], True)}

### 中（{len(by[('R1', 'medium')])} 件）

{table(by[('R1', 'medium')])}

### 低（{len(by[('R1', 'low')])} 件）

{table(by[('R1', 'low')])}

### 記録しておくだけ（{len(by[('R1', 'record_only')])} 件）

{table(by[('R1', 'record_only')])}

## ルート2 の問題（出版版 PDF で補う）

### 修正必須（{len(by[('R2', 'must_fix')])} 件）

{table(by[('R2', 'must_fix')], True)}

### 高（{len(by[('R2', 'high')])} 件）

{table(by[('R2', 'high')], True)}

### 中（{len(by[('R2', 'medium')])} 件）

{table(by[('R2', 'medium')])}

### 低（{len(by[('R2', 'low')])} 件）

{table(by[('R2', 'low')])}

### 記録しておくだけ（{len(by[('R2', 'record_only')])} 件）

{table(by[('R2', 'record_only')])}

## 詳細（ルート1 の修正必須・高）

{details('R1')}

## 詳細（ルート2 の修正必須・高）

{details('R2')}

## 決定事項（所有者が決めること）

直し方が出力の形や原則との兼ね合いに関わり、どちらに倒すかを変換ツールの側で決めるべきでないもの。「勧め」は検証の結果に基づく案で、
決定ではない。

{decisions}

## 対応の記録

- **2026-11-12: C008・C010（と C064・C072）を直した**（版は 0.33.0 としてまとめて上げた。0.32.0 は出していない）。
  - C008: 自動番号を abstractNum ごとに数え、`startOverride` は「その num を最初に使った段落で振り直す」だけにした
    （`numbering.py`。`docx_reader` の削除された表の行の読み飛ばしは `Numbering.snapshot()`・`restore()` を使う）。実際の原稿では
    data3（4 か所）と data16（12 か所）の番号が変わり、すべて出版版 PDF と一致した。ルート2 では、番号が合って段落が PDF と対応づくように
    なり、data16 の見出しの組版の直しが 1 か所増えた（番号の文字だけが変わるわけではない）。
  - C010: 字間に空白のある和文著者名を、いちばん長い空白で分ける。いちばん長い空白が複数あって決められなければ、論文の中の引用の形から、
    なければ字数から推定する（`builder.split_eastern`）。字間・前後の空白は落として記録する（C072）。要確認 `name_split` で、どの氏名を
    どう分けたか・推定かどうか・確かめ方と直し方を知らせる（字数だけの推定はいちばん強く。AI が分けた氏名と、姓と名に分けられなかった
    氏名〈C064〉も載せる）。実際の原稿では data18 と data21 の姓と名が、出版版 PDF の英文著者名と一致するようになった。
    `name_split` は 28 論文中 9 論文で出る（空白のない氏名が多い）。
  - 原則・回帰・利用者向けの観点で点検し、修正と再点検を 3 回行った。
- **2026-11-12: C017・C019・C056・C041・C045 を直した**（版は 0.33.0 としてまとめて上げた）。
  - C017: 引用文献の `<year>` の位置を 1 文字ずつの対応の上で求め直す（`refparse.tag_reference`）。実際の原稿の文献の年がすべて年の形になった。
  - C019: 依頼文そのもの・見本の写し・コードブロックが複数ある回答は、回答全体を断る（`ai_assist.parse_response`。要対応 `ai_error`）。
  - C056: `pdfmatch.key` が必ず 1 文字を返す。
  - C041: 空白だけの段落のスタイルでは、後ろにその節の中身が続くときだけ領域を切り替える（`Classifier.blank_heading_leads`）。
    引用文献・注の節の文字のない段落は `<ref>`・注にせず、除外として記録する（C001 の一部の守り。画像は今までどおり要対応で知らせる）。
    実際の原稿で、中身のない `<ref>` は 0 件になった。
  - C045: DTD 不合格の知らせを、件数でまとめ、原因の場所と日本語の説明、直し方を示す形にした（XML は変えない）。
- **2026-11-12: C012・C011・C013 を直した**（読み取りの単位。版は 0.33.0 としてまとめて上げた）。
  - C012: `ooxml.choose_alternate` が mc:AlternateContent を MCE の規則どおりに選ぶ（読めない名前空間の Choice では Fallback を読む）。
    data25・data6 で消えていた丸数字が出るようになり、ルート2 の補った docx に同じ字が二重に入らなくなった。R13 も解消した。
  - C011: 記号用フォント（Symbol・Wingdings 系）の文字と箇条書きの記号を、対応表で普通の文字にする（規則は `ooxml.py` の 1 か所。
    対応表は公式の対応と突き合わせ、確かめられないものは入れていない）。置き換えは要確認 `symbol_replaced`（件数でまとめる）、
    対応表になく最終の XML に残った私用領域の文字は要対応 `pua_left`。data16 の 86 か所が「•」になり、XML に残る私用領域の文字は 0。
  - C013: 結果のないフィールド（囲い文字など）を記録し、要確認 `resultless_field` で知らせる（XML は変えない）。画像を入れる任意の場所は W1。
  - 新しい知らせが出るのは、実際の原稿 28 論文のうち、それぞれ 1 論文だけ。
- **2026-11-12: 所有者の決定**（詳しくは `docs/FIX_PLAN_RELEASE.md` の「所有者の決定」と「決定を反映した優先度の一覧」）。
  上の表・詳細・決定事項は点検の時点のままなので、次の扱いの変更をあわせて読むこと。
  - 前提の変更: 著者に校正後の docx も提出してもらう。ルート2 は校正の直し (B) を docx に書き込まず、組版の違い (A) だけを直し、
    それでも食い違う箇所は要確認で知らせる。図・表の画像は作業する人がすべて用意する。AI による補完は必須にせず、強く推奨する仕上げにし、
    AI には出版版 PDF を渡す。警告は最小限にする。
  - これにより、ルート1 では C002・C007・C033 ほかがなくなり、C004・C005・C006・C028・C029・C030 は新しい項目 W1（画像の方式の作り変え）の
    中で作り直す。C018 は修正必須に、C070・C085 は高に上げた。C001 は保留（テンプレートで対応）。
  - ルート2 では、(B) の書き込みが原因だった C021・C023・C024・C025・C052・C055 などが docx を壊さなくなり、なくなるか「知らせの誤り」として
    中に下がった。残る修正必須は C020・C056 と、新しい項目 W2（(B) を書き込まず、分類を引き直す）。
  - D-R1-02・04・06・08・21・22・24・26 と、D-R2-02・04・05・06・10・12・15 は要らなくなった。
- **2026-11-13: W1（図・表の画像を作業する人が用意する方式）の実装が終わった**（**W8 と一緒に 0.33.0 として main に反映した**〈0.31.1 の次が 0.33.0。0.32.0 は出さない〉。設計は `docs/fix_plan_release/units/W1.md`、実装で違えた所は同 12 章）。
  - 前半（コミット e70a72b）: 手順の型（`report.STEP`・`Action` の `required`・`report.blocking()`。画像を入れるのは必須、AI の仕上げは推奨）、
    画像の置き場所と名前（`article.ImageSlot`。図番号から決める名前。同じ画像が 2 回出る重なりをなくした）、図の決め方（`Classifier.figure_units`・`float_units`。
    図キャプション 1 つに画像 1 枚）、画像で貼った表と表のセルの図。図形の中のキャプションの形の段落は、除外せず図のキャプションにした。
  - 後半（コミット cc1edd1・3c56360・96546df）: docx の画像の書き出し・変換・切り取りをやめた（`images.check_user_image` は中身を変えずに受け取る）、
    入れた画像の受け取り（まとめて入れる・「入れない」・`--images`）、変換し直したときの持ち越し（`kept_images`・`reapply_images`）、
    取り違えの確かめの一覧（`imagelist`・「{{記事識別子}}_図の確かめ.html」。レポート 9 章）、置き場所を作れなかった画像の守り（`lost_images`）、
    図形の中の文字・飾り・図形で描いた図の一覧、任意の置き場所（結果のないフィールドの位置の `<inline-graphic>`。C013）。1 画面版・ノートブック・コマンドラインを合わせた。
    テストは全部通る（1950 件）。
  - **W1 で解消したと判断した問題と根拠**: C007（同じ画像が 2 回出る。置き場所を 1 つに決め、`xlink:href` に重なりがないことをテストで確かめた）、
    C013（任意の画像の場所。手順 15）、C018・C085・C070（入れた画像を図番号の名前で持ち越す／中身を変えない／一覧に番号・キャプション・場所・名前を出す）、
    C002・C033・C124・C125・C040・C076・C084・C086（docx の画像を書き出さなくなり、重ね・分かれた画像は図 1 枚の置き場所に含まれ、向き・形式・EMF の変換は作業する人の画像になったので、起きなくなった）、
    C069（LibreOffice を使わなくなった。`src` に残っていない）、C081・C101（AI に画像を渡さなくなった。`call_provider(..., [], ...)`）、
    図の本体がない知らせ `figbody` の図の側（置き場所と備考に置き換え）。W1 の中で作ったもの: C004（図形の中の文字を図形ごとの要確認に）・C005・C006・C028（飾りは記録だけ）・C029。
    C003 は図の側だけで、表の側は残っている。C030 は決定と違えた（下の「所有者への報告」）。
  - 手順 16 で、書き出しの部品（`export_images`・`crop_image`・`convert_metafile` など）、`ImageRef.crop`・`edits`・`export_name`、`Options.convert_metafiles`、
    要確認 `image_crop`・`image_edits` をなくした。任意の画像は手順に数えず、画面の行にも出さない。
  - 決定との違い（`docs/FIX_PLAN_RELEASE.md` の「所有者への報告」）: C030 は知らせを足さず行で伝える。Word の図形で描いた図は飾りの一覧から分けた。
    図形の中の「資料：…」などキャプションの形の段落は図のキャプションにした。持ち越しのあいまい一致は要確認 `image_changed`。
- **2026-11-13: W8（AI 補完を強く推奨する仕上げにし、出版版 PDF を AI に渡し、依頼文を作り直す）の実装**（**W1 と一緒に 0.33.0 として main に反映した**）。
  設計と実装の記録は `docs/fix_plan_release/units/W8.md`。手順 0〜23・25・26 を実装した（手順 24〈本物の API での実験 2〉は未実施。所有者がノートブックで Claude の API を確かめる）。
  - 動きの変わったもの: AI なしでも中止しない（位置を決められない図は結び付いた段落の後ろに置いて変換を続け、推奨の手順 `ai_finish` で知らせる。
    推奨の手順は終了コードに数えない）。AI の回答の段落の役割は、区切りだけ XML に反映し、ほかの直し（見出しの階層・引用・謝辞など）は提案にして
    要確認 `style_check` で知らせる。依頼文を作り直し、回答の新しい形にした。依頼の番号と先頭の文字で、どの依頼への回答かを確かめる。出版版 PDF を AI に渡し、
    回答が PDF を見たかを確かめる（`pdf_seen`）。同じ依頼への回答は使い回す。
  - なくなった問題: C042（AI の除外で本文・見出し・文献が落ちても知らせが出ない。AI は段落を除外できなくなった）、C082（AI なしでは中止する。
    AI なしでも中止せず、推奨の手順 `ai_finish` で知らせる）、C019 の残り（依頼の番号と先頭の文字で回答を確かめる）。
  - 直した問題: C039・C059・C066・C118・C119・C121 など依頼文の問題（依頼文を作り直した。図形の位置の情報と判断の基準を足し、表のセルのくり返しを縮めた）。
    C141（リンクの text が全角・半角だけ違うときの守り）は手順 26。
  - **実験 1（AI 役。15 論文・図形 66 個）**: 出版版 PDF から 2 人が別々に正解を付け、食い違いは 3 人目が決めた。反映の後の位置を正解と比べた
    （同じ／2 段落以内）。AI なし 33%・62%、新しい依頼文・PDF なし 47%・74%、新しい依頼文・PDF あり 88%・95.5%。2 段にまたがる機械的な図形も PDF を見た回答で
    置くようにした後は 97%・100%。位置を聞いた図形 55 個では PDF ありが 100%・100%。AI 役も正解を付けた側も同じ系統のモデルなので甘く出ている可能性があり、
    本物の API での確かめが要る。詳しい表は `docs/fix_plan_release/units/W8.md` の 6.3。
  - **実験の後の監督の決定 4 つ**（`docs/fix_plan_release/units/W8.md` の 6.5）: (1) 採用の目安を満たしたので、新しい依頼文と PDF ありの回答を採用する。
    (2) AI なしの既定の位置（`Classifier.provisional_target`）は変えない（推定は結び付いた段落の後ろを上回らなかった）。
    (3) PDF を見ていない回答の位置も使い続ける（PDF なしの新しい依頼文は推定を上回った）。依頼文の「PDF を見ていないとき」の項も縮めない。
    (4) 機械的に位置を決めた図形のうち 2 段にまたがるものは、PDF を見た回答のときだけ AI の位置を採る（1 段の機械的な図形は聞かない）。
    費用の目安（`per_run_usd`）は実験 2 の後に決める（仮の値のまま）。
  - 動作を確かめた API は偽のクライアントだけ。ChatGPT・Gemini・Sakana AI への PDF の渡し方は、実機では未確認（ノートブックと利用の手引きに書いた）。
  - **決定・設計と違えた所と報告**は `docs/FIX_PLAN_RELEASE.md` の「所有者への報告（W8 …）」。
  - **残っている小さな指摘（最後の確かめの minor 6 件。次の版で直す）**:
    (1) PDF を見た回答で 2 段の図形が機械的な位置のまま残っても、済みの行がそれを言わない。
    (2) page のない指定を不採用にするとき、理由が「ページ（0）」になる。
    (3) fallback の部があっても、モデル名が同じなら記録しない。
    (4) 位置を聞く図形と 2 段の図形の両方がある論文で、枠に似た文が 2 回続く。
    (5) 見出しの「（残り n 個）」に 2 段の図形が入らない。
    (6) 14 章の「PDF を見ていない」行で括弧が 2 つ続く。
  - **まだ番号のない問題**: 機械が「該当なし」とした引用（著者・年の引用）が、実際には文献リストにある（実験の AI 役の回答で見つかった。data19・data20・data22・data27・data28）。
    引用の文献への結び付け（`linker.py`）の問題で、W8 の範囲の外。既存の C 番号に同じものはない（C087 は番号つきの文献リストで 1 つもリンクされない場合）。次の版で番号を付けて直す。
- 直したら、版と直し方の要点をここに書く。

## 確かめていないこと

- 「中」以下の問題は、点検者の再現だけが根拠で、反証を試みる検証をしていない。直す前に、単位ごとに再現を確かめる。
- J-STAGE の画面での表示（画像の表 `<table-wrap>` の中の `<graphic>`、注の中の表、`<label>` の自動番号など）は、試験登載で確かめる必要がある。
- AI 役は Opus が依頼文と PDF だけで答えた結果（点検の時点では画像）。API モード（自動実行）と、ほかの AI（ChatGPT・Gemini・Sakana AI）では試していない。W8 の実験 2（本物の API）は未実施。
- テストの docx は元原稿をテンプレートに機械的に流し込んだもので、流し込みの間違い（「記録しておくだけ」の C155〜C159）がまじる。
  著者が自分でテンプレートに書いた原稿とは、スタイルの付き方が違う可能性がある。
- Word の実機では確かめていない（自動番号の数え方 C008 は、出版版 PDF と LibreOffice の表示で確かめた）。
"""
(R / "docs/FIELD_TEST_2026-11.md").write_text(field, encoding="utf-8")


def unit_rows(route, code):
    xs = [x for x in rows2 if x["route"] == route and x["unit"] == code]
    cell = lambda sev: "・".join(x["cid"] for x in xs if x["sev2"] == sev) or "—"
    ms = Counter(x["model"] for x in xs if x["sev2"] in ("must_fix", "high"))
    return cell("must_fix"), cell("high"), cell("medium"), cell("low"), "、".join(f"{MODEL_JA[m]} {n}" for m, n in sorted(ms.items(), key=lambda t: RANK[t[0]])) or "—"


def unit_table(route):
    out = ["| 単位 | 範囲 | 主なファイル | 修正必須 | 高 | 中 | 低 | 修正必須・高の担当 |", "|---|---|---|---|---|---|---|---|"]
    for rt, code, name, files in UNITS:
        if rt == route:
            a, b, c, d, m = unit_rows(route, code)
            out.append(f"| {code} | {name} | {files} | {a} | {b} | {c} | {d} | {m} |")
    return "\n".join(out)


def model_table():
    models = Counter((x["sev2"], x["model"]) for x in rows2)
    out = ["| 優先度 | Haiku | Sonnet | Opus | Fable | 計 |", "|---|---|---|---|---|---|"]
    for s in SEV[:4]:
        n = [models[(s, m)] for m in ("haiku", "sonnet", "opus", "fable")]
        out.append(f"| {SEV_JA[s]} | " + " | ".join(map(str, n)) + f" | {sum(n)} |")
    return "\n".join(out)


plan = (S / "tools/plan_body.md").read_text(encoding="utf-8")
plan = plan.replace("{{UNITS_R1}}", unit_table("R1")).replace("{{UNITS_R2}}", unit_table("R2")).replace("{{MODELS}}", model_table())
plan = plan.replace("{{N_MUST}}", str(len(by2[("R1", "must_fix")]) + len(by2[("R2", "must_fix")])))
plan = plan.replace("{{N_R1_MUST}}", str(len(by2[("R1", "must_fix")]))).replace("{{N_R2_MUST}}", str(len(by2[("R2", "must_fix")])))
plan = plan.replace("{{N_R1_HIGH}}", str(len(by2[("R1", "high")]))).replace("{{N_R2_HIGH}}", str(len(by2[("R2", "high")])))
plan = plan.replace("{{REVISED}}", revised())
(R / "docs/FIX_PLAN_RELEASE.md").write_text(plan, encoding="utf-8")
print("rows", len(rows), {k: len(x) for k, x in sorted(by.items())})
print(model_table())
for rt in ("R1", "R2"):
    print(unit_table(rt))
