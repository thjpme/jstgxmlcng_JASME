import io
from PIL import Image
# build JPEG with exif containing IFD1 thumbnail
thumb=io.BytesIO(); Image.new("RGB",(16,8),"red").save(thumb,"JPEG"); tb=thumb.getvalue()
ex=Image.Exif(); ex[0x010F]="Cam"
# craft IFD1 thumbnail manually is complex; use piexif if present
try:
    import piexif
    exif=piexif.dump({"0th":{piexif.ImageIFD.Make:b"Cam"},"1st":{piexif.ImageIFD.JPEGInterchangeFormat:0,piexif.ImageIFD.JPEGInterchangeFormatLength:len(tb)},"thumbnail":tb})
except ImportError:
    exif=None; print("no piexif")
if exif:
    b=io.BytesIO(); Image.new("RGB",(64,32),"blue").save(b,"JPEG",exif=exif)
    s=Image.open(io.BytesIO(b.getvalue()))
    raw=s.info["exif"]; print("raw has thumb", tb[:20] in raw, len(raw))
    print("getexif tobytes has thumb", tb[:20] in s.getexif().tobytes())
