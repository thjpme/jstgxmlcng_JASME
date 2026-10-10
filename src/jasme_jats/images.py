"""画像の書き出し（J-STAGE が扱える jpg / gif / png にする）。

docx の画像はそのまま使えるものが多いが、Word の図（EMF / WMF）は変換が必要。
変換には LibreOffice（soffice）と pypdfium2 を使う。どちらもない環境では変換せず、
レポートで「要対応」として知らせる。
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DIRECT = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "gif": "gif"}
PILLOW = {"bmp", "tif", "tiff", "jfif", "pjpeg", "webp"}
METAFILE = {"emf", "wmf", "emz", "wmz"}


@dataclass
class ImageResult:
    image_id: str
    name: str
    source: str
    status: str        # ok / converted / failed / missing
    message: str = ""


def soffice_path():
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _crop_white(img, pad=12):
    from PIL import Image, ImageChops
    rgb = img.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    mask = ImageChops.difference(rgb, bg).convert("L").point(lambda v: 255 if v > 8 else 0)
    box = mask.getbbox()
    if not box:
        return rgb
    return rgb.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(rgb.width, box[2] + pad),
                     min(rgb.height, box[3] + pad)))


def convert_metafile(data: bytes, ext: str, min_width_px=1200):
    """EMF / WMF を PNG にする。戻り値: (png の bytes または None, メッセージ)"""
    soffice = soffice_path()
    if not soffice:
        return None, "LibreOffice が見つからないため EMF/WMF を変換できない（Colab では「EMF/WMF 画像を変換する」を有効にする）"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"image.{ext}"
        src.write_bytes(data)
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(src)],
                           check=True, capture_output=True, timeout=120)
        except Exception as e:  # noqa: BLE001
            return None, f"LibreOffice での変換に失敗: {e}"
        pdf = Path(td) / "image.pdf"
        if not pdf.exists():
            return None, "LibreOffice での変換に失敗（PDF ができない）"
        try:
            import pypdfium2 as pdfium
        except ImportError:
            pdfium = None
        from PIL import Image
        if pdfium is not None:
            doc = pdfium.PdfDocument(str(pdf))
            page = doc[0]
            w, h = page.get_size()
            low = page.render(scale=1).to_pil()
            cropped = _crop_white(low, pad=2)
            # 内容の範囲だけを高解像度で描き直す
            box = _bbox(low)
            if box:
                cw = box[2] - box[0]
                scale = max(300 / 72, min(1200 / 72, min_width_px / max(cw, 1)))
                crop = (max(0, box[0] - 2), max(0, h - box[3] - 2), max(0, w - box[2] - 2), max(0, box[1] - 2))
                img = page.render(scale=scale, crop=crop).to_pil()
                img = _crop_white(img)
            else:
                img = cropped
            doc.close()
        else:
            try:
                subprocess.run([soffice, "--headless", "--convert-to", "png", "--outdir", td, str(src)],
                               check=True, capture_output=True, timeout=120)
                img = _crop_white(Image.open(Path(td) / "image.png"))
            except Exception as e:  # noqa: BLE001
                return None, f"LibreOffice での PNG 変換に失敗: {e}"
        buf = io.BytesIO()
        img.save(buf, "PNG", dpi=(300, 300))
        return buf.getvalue(), f"{ext.upper()} を PNG に変換（{img.width}×{img.height} px）"


def _bbox(img):
    from PIL import Image, ImageChops
    rgb = img.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    return ImageChops.difference(rgb, bg).convert("L").point(lambda v: 255 if v > 8 else 0).getbbox()


def export_images(doc, images, out_dir: Path, convert_metafiles=True):
    """BuildInfo.images（出力した画像）を out_dir に書き出す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for img in images:
        name = img.export_name
        if img.shape_only or not img.target:
            results.append(ImageResult(img.image_id, name, "", "missing",
                                       "Word の図形・グラフなどで画像ファイルがない。PDF 等から画像を作り、この名前で Graphics/ に置くこと"))
            continue
        data = doc.media.get(img.target)
        src_ext = img.target.rsplit(".", 1)[-1].lower()
        if data is None:
            results.append(ImageResult(img.image_id, name, img.target, "missing", "docx の中に画像ファイルが見つからない"))
            continue
        want_ext = name.rsplit(".", 1)[-1]
        if DIRECT.get(src_ext) == want_ext:
            (out_dir / name).write_bytes(data)
            results.append(ImageResult(img.image_id, name, img.target, "ok"))
            continue
        if src_ext in PILLOW or (src_ext in DIRECT and DIRECT[src_ext] != want_ext):
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                if im.mode not in ("RGB", "RGBA", "L", "P"):
                    im = im.convert("RGB")
                im.save(out_dir / name, "PNG")
                results.append(ImageResult(img.image_id, name, img.target, "converted", f"{src_ext.upper()} を PNG に変換"))
            except Exception as e:  # noqa: BLE001
                results.append(ImageResult(img.image_id, name, img.target, "failed", f"変換に失敗: {e}"))
            continue
        if src_ext in METAFILE:
            if src_ext in ("emz", "wmz"):
                import gzip
                try:
                    data = gzip.decompress(data)
                    src_ext = src_ext[0] + "mf"
                except OSError:
                    pass
            png, msg = convert_metafile(data, src_ext) if convert_metafiles else (None, "EMF/WMF の変換を行わない設定")
            if png:
                (out_dir / name).write_bytes(png)
                results.append(ImageResult(img.image_id, name, img.target, "converted", msg))
            else:
                keep = out_dir.parent / "要変換" / f"{name.rsplit('.', 1)[0]}.{src_ext}"
                keep.parent.mkdir(parents=True, exist_ok=True)
                keep.write_bytes(data)
                results.append(ImageResult(img.image_id, name, img.target, "failed",
                                           f"{msg}。元の画像を 要変換/{keep.name} に保存した"))
            continue
        results.append(ImageResult(img.image_id, name, img.target, "failed", f"未対応の画像形式（{src_ext}）"))
    return results
