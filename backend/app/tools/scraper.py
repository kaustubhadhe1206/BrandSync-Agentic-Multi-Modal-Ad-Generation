"""Real web scraper. Walks a small site, captures copy + visual cues + sample images.

This is the tool the Brand Strategist uses to ingest a website. We deliberately
keep it modest (depth-limited, page-capped) — the Strategist only needs enough
signal to write a brief, not a full archive.
"""
from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types as genai_types
from PIL import Image as PILImage

from ..config import settings


@dataclass
class ScrapedSite:
    base_url: str
    title: str
    description: str
    pages: list[dict] = field(default_factory=list)   # [{url, text, headings}]
    image_urls: list[str] = field(default_factory=list)
    css_colors: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    visual_context: str = ""  # what the *actual* site images show (campaigns,
                               # seasonal themes, promos) — text scraping alone
                               # misses purely-visual context like a banner ad

    def to_brain_input(self) -> str:
        """Compact text representation for the Strategist LLM."""
        pages_text = "\n\n".join(
            f"### {p['url']}\nHeadings: {', '.join(p['headings'][:8])}\n{p['text'][:1500]}"
            for p in self.pages[:settings.SCRAPER_MAX_PAGES]
        )
        visual_context_block = (
            f"## Current visual context (from the site's actual images)\n{self.visual_context}\n\n"
            if self.visual_context
            else ""
        )
        return (
            f"# Site: {self.base_url}\n"
            f"Title: {self.title}\n"
            f"Meta description: {self.description}\n\n"
            f"## Visual cues\n"
            f"CSS colors detected: {', '.join(self.css_colors[:12])}\n"
            f"Fonts detected: {', '.join(self.fonts[:6])}\n"
            f"Sample image URLs: {', '.join(self.image_urls[:8])}\n\n"
            f"{visual_context_block}"
            f"## Pages\n{pages_text}"
        )


_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
_FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;{}]+)", re.IGNORECASE)

_VISUAL_CONTEXT_PROMPT = """\
You are looking at images scraped from a business's website. Identify any
CURRENT promotional context that pure text might miss: limited-time offers,
seasonal themes, special campaigns, or thematic tie-ins visible in the
imagery but not necessarily spelled out anywhere in the page copy.

Describe the THEME and TONE only — e.g. "playful animated-movie character
tie-in promotion" or "summer seasonal discount campaign with bright colors".
Do NOT name specific copyrighted characters, franchises, or trademarks by
name, even if you recognize them — describe the vibe, not the IP. This
description will inform an ad brief and must never be used to ask an image
generator to reproduce someone else's copyrighted characters.

If you see nothing beyond normal product/business photography, respond with
exactly: "No current promotional or seasonal visual context detected."

Respond with 1-3 plain sentences. No JSON, no markdown.
"""


async def _fetch_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    try:
        r = await client.get(url, timeout=settings.SCRAPER_TIMEOUT_SEC, follow_redirects=True)
        content_type = r.headers.get("content-type", "").split(";", 1)[0].strip()
        if r.status_code != 200 or not content_type.startswith("image/") or content_type == "image/svg+xml":
            return None
        return r.content, content_type
    except (httpx.HTTPError, httpx.TimeoutException):
        return None


def _is_meaningful_image(data: bytes, min_side: int = 150) -> bool:
    """Filter out icons/logos/spacers — tiny images rarely carry promotional
    context and just waste multimodal-call budget on noise."""
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            return min(img.size) >= min_side
    except Exception:
        return False


async def _describe_visual_context(images: list[tuple[bytes, str]]) -> str:
    def _call() -> str:
        client = genai.Client()
        parts: list = [_VISUAL_CONTEXT_PROMPT]
        for data, mime_type in images:
            parts.append(genai_types.Part.from_bytes(data=data, mime_type=mime_type))
        resp = client.models.generate_content(model=settings.MODEL_FAST, contents=parts)
        return (resp.text or "").strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        # Best-effort signal, not a required step — a failure here should
        # never sink the scrape itself.
        return ""


async def _build_visual_context(image_urls: list[str]) -> str:
    """Download a handful of the site's REAL images (not just URLs) and have
    a multimodal model describe any current promo/seasonal context. This is
    the only place actual image bytes get fetched — they're never persisted,
    never fed to Nano Banana/Veo, and discarded right after this call."""
    if not image_urls:
        return ""
    candidate_urls = image_urls[: settings.SCRAPER_MAX_IMAGES_TO_ANALYZE * 3]
    async with httpx.AsyncClient(
        headers={"User-Agent": "BrandSyncBot/1.0 (+https://brandsync.local)"}
    ) as client:
        fetched = await asyncio.gather(*[_fetch_image(client, u) for u in candidate_urls])

    meaningful: list[tuple[bytes, str]] = []
    for result in fetched:
        if result and _is_meaningful_image(result[0]):
            meaningful.append(result)
        if len(meaningful) >= settings.SCRAPER_MAX_IMAGES_TO_ANALYZE:
            break

    if not meaningful:
        return ""
    return await _describe_visual_context(meaningful)


async def _fetch(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, timeout=settings.SCRAPER_TIMEOUT_SEC, follow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except (httpx.HTTPError, httpx.TimeoutException):
        return None
    return None


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, timeout=settings.SCRAPER_TIMEOUT_SEC, follow_redirects=True)
        if r.status_code == 200:
            return r.text
    except (httpx.HTTPError, httpx.TimeoutException):
        return None
    return None


def _internal_links(soup: BeautifulSoup, base: str) -> list[str]:
    base_host = urlparse(base).netloc
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        absu = urljoin(base, a["href"]).split("#", 1)[0]
        if urlparse(absu).netloc != base_host:
            continue
        if absu in seen or absu == base:
            continue
        seen.add(absu)
        out.append(absu)
    return out


async def scrape_site(url: str) -> ScrapedSite:
    """Scrape a site: home page + up to N internal pages, plus CSS theme extraction."""
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"

    site = ScrapedSite(base_url=url, title="", description="")

    async with httpx.AsyncClient(
        headers={"User-Agent": "BrandSyncBot/1.0 (+https://brandsync.local)"}
    ) as client:
        html = await _fetch(client, url)
        if not html:
            raise RuntimeError(f"Could not fetch {url}")

        soup = BeautifulSoup(html, "html.parser")
        site.title = (soup.title.string or "").strip() if soup.title else ""
        meta = soup.find("meta", attrs={"name": "description"})
        site.description = (meta.get("content") or "").strip() if meta else ""

        # Capture home page text + headings + images
        site.pages.append(_extract_page(url, soup))
        site.image_urls.extend(_extract_images(soup, url))

        # Walk a few internal links in parallel
        links = _internal_links(soup, url)[: settings.SCRAPER_MAX_PAGES - 1]
        sub_htmls = await asyncio.gather(*[_fetch(client, l) for l in links])
        for link, sub in zip(links, sub_htmls):
            if sub:
                sub_soup = BeautifulSoup(sub, "html.parser")
                site.pages.append(_extract_page(link, sub_soup))
                site.image_urls.extend(_extract_images(sub_soup, link))

        # CSS theme extraction — inline styles + linked stylesheets
        css_blobs: list[str] = []
        for style_tag in soup.find_all("style"):
            css_blobs.append(style_tag.text)
        css_links = [
            urljoin(url, link["href"])
            for link in soup.find_all("link", rel="stylesheet", href=True)
        ][:3]
        css_fetched = await asyncio.gather(*[_fetch_text(client, l) for l in css_links])
        css_blobs.extend([c for c in css_fetched if c])

        full_css = "\n".join(css_blobs)
        site.css_colors = list(dict.fromkeys(_HEX_COLOR.findall(full_css)))[:20]
        site.fonts = list(dict.fromkeys(
            f.strip().strip("'\"") for m in _FONT_FAMILY.findall(full_css) for f in m.split(",")
        ))[:10]

    # Dedupe image urls
    site.image_urls = list(dict.fromkeys(site.image_urls))[:20]

    # Download a handful of the REAL images (not just URLs) so the Strategist
    # can catch promotional/seasonal context pure text scraping misses — e.g.
    # a campaign banner with no surrounding alt text or page copy.
    site.visual_context = await _build_visual_context(site.image_urls)

    return site


def _extract_page(url: str, soup: BeautifulSoup) -> dict:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    text = " ".join(soup.get_text(separator=" ").split())
    return {"url": url, "headings": headings, "text": text}


def _extract_images(soup: BeautifulSoup, base: str) -> list[str]:
    out: list[str] = []
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if src.startswith("data:"):
            continue
        out.append(urljoin(base, src))
    return out
