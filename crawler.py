from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import aiohttp

USER_AGENT = "Mytarik-public-docs/1.0 (+local research)"
PDF_MAGIC = b"%PDF-"


def _robots_allowed(url: str, robots_cache: dict[str, RobotFileParser]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    root = f"{parsed.scheme}://{parsed.netloc}"
    parser = robots_cache.get(root)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(f"{root}/robots.txt")
        try:
            parser.read()
        except OSError:
            # A missing robots.txt is not an authorization to ignore site rules.
            return False
        robots_cache[root] = parser
    return parser.can_fetch(USER_AGENT, url)


def _filename(url: str, digest: str) -> str:
    name = Path(urlparse(url).path).name
    name = name if name.lower().endswith(".pdf") else f"{name or 'document'}.pdf"
    return f"{digest[:12]}-{name}"


async def download_pdf(
    session: aiohttp.ClientSession,
    url: str,
    download_dir: str,
    semaphore: asyncio.Semaphore,
    robots_cache: dict[str, RobotFileParser],
) -> dict | None:
    async with semaphore:
        if not _robots_allowed(url, robots_cache):
            print(f"robots.txt disallows {url}")
            return None
        for attempt in range(5):
            try:
                async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
                    if response.status in {429, 500, 502, 503, 504}:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            wait = max(float(retry_after), 2 ** attempt)
                        except (TypeError, ValueError):
                            wait = 2 ** attempt
                        if attempt < 4:
                            print(f"HTTP {response.status} {url}; retry in {wait:.1f}s")
                            await asyncio.sleep(wait)
                            continue
                        print(f"Failed {url}: HTTP {response.status}")
                        return None
                    if response.status != 200:
                        print(f"Failed {url}: HTTP {response.status}")
                        return None
                    content = await response.read()
                    if not content.startswith(PDF_MAGIC):
                        print(f"Skipped non-PDF response: {url}")
                        return None
                    digest = hashlib.sha256(content).hexdigest()
                    target = Path(download_dir) / _filename(url, digest)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    print(f"Downloaded {url} -> {target}")
                    return {"url": url, "path": str(target), "sha256": digest, "bytes": len(content)}
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt < 4:
                    wait = 2 ** attempt
                    print(f"Error {url}: {exc}; retry in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                print(f"Failed {url}: {exc}")
                return None


async def main(urls: Iterable[str], download_dir: str, concurrency_limit: int = 1) -> list[dict]:
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max(1, concurrency_limit))
    robots_cache: dict[str, RobotFileParser] = {}
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [download_pdf(session, url, download_dir, semaphore, robots_cache) for url in urls]
        results = await asyncio.gather(*tasks)
    return [result for result in results if result]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: crawler.py <download_dir> <url> [url ...]")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[2:], sys.argv[1]))
