"""Proof files (certificates, offer letters, photos), free of paid services:

- type by magic bytes, never by extension: PDF, JPEG or PNG only, at most 5 MB;
- PDFs with active content (JavaScript, launch actions, embedded files, auto-run actions) are refused: that's what a
  malicious PDF needs, and a certificate never has it;
- images are decoded and re-encoded with Pillow, which drops EXIF (including GPS) and any bytes hidden after the image;
- stored encrypted (Fernet, key outside the database) in Postgres; only metadata is queried. `STORAGE_BACKEND=s3` is the
  switch for when S3/R2 is added later: the interface (put/get/url) stays the same;
- served through short-lived signed URLs (HMAC, 10 minutes) that are also checked against the viewer's access.
"""

import hashlib
import hmac
import io
import re
import time
import uuid

from app.config import settings

MAX_BYTES = 5 * 1024 * 1024
URL_TTL_S = 600


class ProofRejected(ValueError):
    pass


def sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


_PDF_ACTIVE = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFile|EmbeddedFiles|RichMedia|XFA|OpenAction\s*<<[^>]*?/S\s*/JavaScript|AA\s*<<)\b")


def clean(data: bytes, filename: str = "") -> tuple[bytes, str]:
    """(safe bytes, mime) or ProofRejected with a reason the student can act on."""
    if len(data) > MAX_BYTES:
        raise ProofRejected("The file is over 5 MB")
    if not data:
        raise ProofRejected("The file is empty")
    mime = sniff(data)
    if mime is None:
        raise ProofRejected("Upload a PDF, JPG or PNG")
    if mime == "application/pdf":
        if _PDF_ACTIVE.search(data):
            raise ProofRejected("This PDF contains scripts or embedded files. Save it again as a plain PDF (Print → Save as PDF)")
        try:
            from pypdf import PdfReader

            PdfReader(io.BytesIO(data)).pages  # noqa: B018 - must parse as a PDF
        except Exception as exc:
            raise ProofRejected("This PDF couldn't be read") from exc
        return data, mime
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ProofRejected("This image couldn't be read") from exc
    if img.width * img.height > 40_000_000:
        raise ProofRejected("The image is too large (over 40 megapixels)")
    out = io.BytesIO()
    if mime == "image/jpeg":
        img.convert("RGB").save(out, "JPEG", quality=88)  # no exif= argument: EXIF and GPS are dropped
    else:
        img.save(out, "PNG")  # text chunks aren't copied
    return out.getvalue(), mime


def encrypt(data: bytes) -> bytes:
    from app.security import _fernet

    return _fernet().encrypt(data)


def decrypt(blob: bytes) -> bytes:
    from app.security import _fernet

    return _fernet().decrypt(blob)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sig(campus_id: uuid.UUID, file_id: uuid.UUID, exp: int, viewer: uuid.UUID) -> str:
    msg = f"{campus_id}:{file_id}:{exp}:{viewer}".encode()
    return hmac.new(settings.jwt_secret.encode(), msg, hashlib.sha256).hexdigest()[:40]


def signed_url(campus_id: uuid.UUID, file_id: uuid.UUID, viewer: uuid.UUID) -> str:
    exp = int(time.time()) + URL_TTL_S
    return f"/api/campus/files/{campus_id}/{file_id}?exp={exp}&sig={_sig(campus_id, file_id, exp, viewer)}"


def check_signature(campus_id: uuid.UUID, file_id: uuid.UUID, exp: int, sig: str, viewer: uuid.UUID) -> bool:
    return exp >= time.time() and hmac.compare_digest(sig, _sig(campus_id, file_id, exp, viewer))


def offer_letter_text(data: bytes, mime: str) -> str:
    if mime == "application/pdf":
        from pypdf import PdfReader

        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages[:6])[:20000]
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("tesseract"):
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(data)
        f.flush()
        try:
            return subprocess.run(["tesseract", f.name, "-", "-l", "eng"], capture_output=True, text=True, timeout=20).stdout[:20000]
        except (subprocess.SubprocessError, OSError):
            return ""
