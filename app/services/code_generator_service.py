"""
Generates QR codes and 1D barcodes for products so they can be printed
onto shelf labels and scanned during stock operations.
"""
import logging

import qrcode
import barcode
from barcode.writer import ImageWriter

from app.core.config import settings

logger = logging.getLogger(__name__)


class CodeGeneratorService:
    @staticmethod
    def generate_qr_code(product_code: str) -> str:
        """
        Encodes the product code into a QR image and returns the
        web-relative path (usable directly in <img src="...">).
        """
        img = qrcode.make(product_code)
        filename = f"{product_code}.png"
        filepath = settings.qr_code_dir / filename
        img.save(filepath)
        logger.info("Generated QR code for product_code=%s", product_code)
        return f"/static/qrcodes/{filename}"

    @staticmethod
    def generate_barcode(product_code: str) -> tuple[str, str]:
        """
        Generates a Code128 barcode image. Returns (web_path, barcode_value).
        The barcode value is derived from the product code so scanning it
        can be resolved back to the product deterministically.
        """
        barcode_value = product_code
        code128 = barcode.get_barcode_class("code128")
        filename_no_ext = f"{product_code}_barcode"
        instance = code128(barcode_value, writer=ImageWriter())
        full_path = instance.save(str(settings.barcode_dir / filename_no_ext))
        web_path = f"/static/barcodes/{filename_no_ext}.png"
        logger.info("Generated barcode for product_code=%s", product_code)
        return web_path, barcode_value
