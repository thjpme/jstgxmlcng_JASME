"""全 fixture の出力（XML・AI依頼文・レポート）のハッシュと本体を保存する。

  python golden.py 保存先フォルダ
レポートの「作成日時」「ツール」の行は除く。比べるときは、2 つの保存先の manifest.json を比べ、違うものは本体を diff する。
"""
import hashlib, json, sys, tempfile
from pathlib import Path

REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
from conftest import ALL_DOCS, DATA, FLOAT, FULL, PDFCHECK, PDFCHECK_PDF  # noqa: E402
from jasme_jats.config import ArticleMeta, JournalConfig  # noqa: E402
from jasme_jats.pipeline import AIRequiredError, Options, convert  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
j = JournalConfig.load()
def meta():
    return ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12",
                                  "pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20",
                                  "peer_review": "あり", "keywords": "proof; 論証; 数学的探究"})
cases = []
for p in ALL_DOCS:
    cases.append((f"{p.stem}_manual", p, dict(ai_mode="manual")))
    cases.append((f"{p.stem}_split", p, dict(split_labels=True)))
cases.append(("sample_full_ai", FULL, dict(ai_mode="manual", ai_response=(DATA / "ai_response_sample_full.json").read_text(encoding="utf-8"))))
cases.append(("sample_float_ai", FLOAT, dict(ai_mode="manual", ai_response=(DATA / "ai_response_sample_float.json").read_text(encoding="utf-8"))))
cases.append(("sample_float_manual", FLOAT, dict(ai_mode="manual")))
cases.append(("pdfcheck_route1", PDFCHECK, dict(pdf_path=PDFCHECK_PDF, route="docx")))
cases.append(("pdfcheck_route2", PDFCHECK, dict(pdf_path=PDFCHECK_PDF, route="pdf")))
manifest = {}
for name, path, kw in cases:
    with tempfile.TemporaryDirectory() as td:
        try:
            res = convert(path, meta(), j, Options(out_dir=Path(td), convert_metafiles=False, **kw))
        except AIRequiredError as e:
            manifest[name] = {"error": str(e)[:200]}
            continue
        d = out / name; d.mkdir(exist_ok=True)
        files = {"xml": res.xml_path.read_bytes(),
                 "report": "\n".join(l for l in res.report_path.read_text(encoding="utf-8").splitlines()
                                     if not l.startswith(("- 作成日時", "- ツール"))).encode("utf-8")}
        if res.prompt_path:
            files["prompt"] = res.prompt_path.read_bytes()
        manifest[name] = {}
        for k, v in files.items():
            (d / k).write_bytes(v)
            manifest[name][k] = hashlib.sha256(v).hexdigest()[:16]
        manifest[name]["ok"] = [res.fidelity.ok, res.fidelity.final_ok, res.dtd_valid, len(res.jstage_issues)]
(out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v.get("ok", v) for k, v in manifest.items()}, ensure_ascii=False))
