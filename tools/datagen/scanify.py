"""Convierte un PDF nativo en una digitalización verosímil.

No cambia el contenido: rasteriza a 150-200 ppp, aplica una iluminación
desigual, ruido de sensor, desenfoque leve, una rotación de menos de 1,5° y
compresión JPEG. El resultado es un PDF de imágenes, como el que sale de un
escáner de oficina.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import fitz
from PIL import Image, ImageChops, ImageEnhance, ImageFilter


def _illumination(img: Image.Image, rng: random.Random) -> Image.Image:
    width, height = img.size
    gradient = Image.linear_gradient("L")
    gradient = gradient.rotate(rng.choice((0, 90, 180, 270)))
    gradient = gradient.resize((width, height))
    # 255 en el lado claro, ~208 en el oscuro
    lut = [255 - int(value * rng.uniform(0.10, 0.20)) for value in range(256)]
    mask = gradient.point(lut)
    return ImageChops.multiply(img, Image.merge("RGB", (mask, mask, mask)))


def _degrade(img: Image.Image, rng: random.Random, angle: float) -> Image.Image:
    img = _illumination(img, rng)
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.88, 0.98))
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.97, 1.03))
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.25, 0.55)))
    noise = Image.effect_noise(img.size, rng.uniform(9, 20)).convert("RGB")
    img = Image.blend(img, noise, rng.uniform(0.018, 0.045))
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(252, 252, 250))
    # Sombra suave del borde del escáner.
    if rng.random() < 0.6:
        shadow = Image.new("L", img.size, 0)
        band = int(img.size[1] * rng.uniform(0.004, 0.012))
        for i in range(band):
            value = int(70 * (1 - i / band))
            shadow.paste(value, (0, i, img.size[0], i + 1))
        black = Image.new("RGB", img.size, (30, 30, 30))
        img = Image.composite(black, img, shadow.point(lambda v: v // 3))
    return img


def scanify(src: Path, dst: Path, rng: random.Random, angle: float) -> None:
    document = fitz.open(src)
    images: list[Image.Image] = []
    # Un escáner no cambia de resolución entre páginas: un DPI por documento.
    dpi = rng.randint(150, 200)
    try:
        for page in document:
            pixmap = page.get_pixmap(dpi=dpi)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            image = _degrade(image, rng, angle + rng.uniform(-0.25, 0.25))
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=rng.randint(60, 80), optimize=True)
            buffer.seek(0)
            images.append(Image.open(buffer).convert("RGB"))
    finally:
        document.close()

    if not images:
        raise RuntimeError(f"PDF vacío: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        dst,
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=150,
        quality=72,
    )
