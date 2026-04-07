"""Serve the browser extension as a pre-configured ZIP."""

import io
import os
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from whatisup.api.deps import get_current_user
from whatisup.core.limiter import limiter

router = APIRouter(prefix="/extension", tags=["extension"])

# Resolve extension directory: env override > /app/extension (Docker volume) > dev fallback
_EXTENSION_DIR_ENV = os.environ.get("EXTENSION_DIR")
if _EXTENSION_DIR_ENV:
    EXTENSION_DIR = Path(_EXTENSION_DIR_ENV)
elif Path("/app/extension").is_dir():
    EXTENSION_DIR = Path("/app/extension")
else:
    # Dev fallback: relative to source tree
    EXTENSION_DIR = Path(__file__).resolve().parents[3] / "extension"


@router.get("/download")
@limiter.limit("10/minute")
async def download_extension(request: Request, _=Depends(get_current_user)):
    """Return a ZIP of the browser extension with server URL pre-configured."""
    if not EXTENSION_DIR.is_dir():
        raise HTTPException(status_code=503, detail="Extension files not available on this server.")

    origin = str(request.base_url).rstrip("/")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(EXTENSION_DIR.rglob("*")):
            if file_path.is_dir():
                continue
            rel = file_path.relative_to(EXTENSION_DIR)
            content = file_path.read_text(encoding="utf-8", errors="replace")

            # Inject server URL into options.js
            if str(rel) == "options/options.js":
                content = content.replace(
                    "if (serverUrl) serverUrlInput.value = serverUrl",
                    f"serverUrlInput.value = serverUrl || '{origin}'",
                )

            zf.writestr(f"whatisup-recorder/{rel}", content)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="whatisup-recorder.zip"'},
    )
