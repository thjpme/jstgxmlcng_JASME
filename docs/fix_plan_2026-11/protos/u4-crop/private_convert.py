"""実際の原稿を変換し、切り取りのある画像の出力の大きさを見る（本文の文字は出さない）。"""
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src")]
from lxml import etree
from PIL import Image
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.docx_reader import read_docx
from jasme_jats.pipeline import convert, Options
from jasme_jats.report import actions

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
WORK = Path(__file__).parent

for folder in ("テストデータ2", "テストデータ3", "テストデータ4", "テストデータ5"):
    for path in sorted((ROOT / "tests/private" / folder).glob("*.docx")):
        doc = read_docx(path)
        print(folder, path.name[:8], "images", [(i.image_id, i.source, Path(i.target).name, i.cx_emu, i.cy_emu,
                                                 i.inline, bool(i.float_id), i.shape_only) for i in doc.images])
        if folder in ("テストデータ3", "テストデータ5"):
            try:
                res = convert(path, meta, journal, Options(out_dir=WORK / f"conv-{folder}-{path.stem[:10]}",
                                                           convert_metafiles=False, ai_mode="manual"))
            except Exception as e:  # noqa: BLE001
                print("  convert failed", type(e).__name__, e)
                continue
            with zipfile.ZipFile(res.zip_path) as z:
                for r in res.images:
                    n = next((n for n in z.namelist() if n.endswith("/" + r.name)), None)
                    size = Image.open(io.BytesIO(z.read(n))).size if n else None
                    print("  out", r.image_id, r.name, Path(r.source).name, r.status, size)
            print("  actions", [a.key for a in actions(res)])
            ai = WORK / f"conv-{folder}-{path.stem[:10]}" / "AI添付画像"
            if ai.exists():
                print("  ai-images", [(p.name, Image.open(p).size) for p in sorted(ai.iterdir())])
