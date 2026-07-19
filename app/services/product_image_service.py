"""
Product image upload handling.

Validates the upload is actually a readable image (not just trusting
the file extension or browser-supplied content-type, both of which are
easy to spoof), resizes it to a sane maximum so a 20MB phone photo
doesn't bloat the static folder, and saves it under a name derived from
the product code so old images are cleanly replaced on re-upload.
"""
import logging
from pathlib import Path
from typing import Tuple

from PIL import Image, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_DIMENSION = 800  # pixels, longest side
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


class ImageUploadError(Exception):
    pass


class ProductImageService:
    @staticmethod
    def validate_and_save(product_code: str, file_bytes: bytes, content_type: str) -> str:
        """
        Validates the upload and saves a resized copy to
        app/static/product_images/{product_code}.jpg, overwriting any
        previous image for that product. Returns the web-relative path.
        """
        if len(file_bytes) == 0:
            raise ImageUploadError("The uploaded image is empty.")
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise ImageUploadError("Image is too large (max 5 MB). Please resize it and try again.")

        # Don't trust the browser-supplied content_type alone — verify
        # by actually attempting to decode the image bytes with Pillow.
        try:
            import io
            image = Image.open(io.BytesIO(file_bytes))
            image.verify()  # raises if the data isn't a valid image
            # verify() leaves the file object unusable for further ops, so reopen
            image = Image.open(io.BytesIO(file_bytes))
        except (UnidentifiedImageError, OSError):
            raise ImageUploadError(
                "This doesn't look like a valid image file. Please upload a JPEG, PNG, or WebP."
            )

        # Convert to RGB (handles PNG transparency / palette modes) and
        # resize so the longest side is at most MAX_DIMENSION, preserving
        # aspect ratio — keeps storage and page-load size reasonable.
        image = image.convert("RGB")
        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

        filename = f"{product_code}.jpg"
        filepath = settings.product_image_dir / filename
        image.save(filepath, format="JPEG", quality=85)

        logger.info("Saved product image for %s (%sx%s)", product_code, image.width, image.height)
        return f"/static/product_images/{filename}"

    @staticmethod
    def delete_image(image_path: str) -> None:
        """Best-effort cleanup when a product's image is replaced or the product is deleted."""
        if not image_path:
            return
        filename = Path(image_path).name
        filepath = settings.product_image_dir / filename
        try:
            if filepath.exists():
                filepath.unlink()
        except OSError as exc:
            logger.warning("Could not delete old product image %s: %s", filepath, exc)
