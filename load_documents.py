"""Load and clean the document sources listed in planning.md.

The script reads the URLs from the Documents section, fetches each source,
removes obvious site boilerplate, and keeps the cleaned text in memory so it
can be printed or consumed by downstream code.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Sequence

import pdfplumber
import requests
from bs4 import BeautifulSoup, Comment
from playwright.sync_api import sync_playwright


ROOT_DIR = Path(__file__).resolve().parent
PLANNING_PATH = ROOT_DIR / "planning.md"
DEFAULT_TIMEOUT = 30
CHROME_CANDIDATES = [
	"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
	"/Applications/Chromium.app/Contents/MacOS/Chromium",
]
USER_AGENT = (
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
	"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

BLOCK_TAGS = {
	"script",
	"style",
	"noscript",
	"header",
	"footer",
	"nav",
	"aside",
	"form",
	"button",
	"input",
	"select",
	"option",
	"textarea",
	"svg",
	"iframe",
	"canvas",
}

BOILERPLATE_PATTERNS = [
	r"^\s*•\s*$",
	r"^\s*skip to content\s*$",
	r"^\s*go to .*\s*$",
	r"^\s*r/[a-z0-9_]+\s*$",
	r"^\s*sort by:?\s*$",
	r"^\s*promoted\s*$",
	r"^\s*reply\s*$",
	r"^\s*share\s*$",
	r"^\s*upvote\s*$",
	r"^\s*downvote\s*$",
	r"^\s*join the conversation\s*$",
	r"^\s*more posts you may like\s*$",
	r"^\s*related posts\s*$",
	r"^\s*accept all cookies\s*$",
	r"^\s*accept cookies\s*$",
	r"^\s*cookie policy\s*$",
	r"^\s*cookie settings\s*$",
	r"^\s*read more\s*$",
	r"^\s*share\s*$",
	r"^\s*comments?\s*$",
	r"^\s*comment count\s*$",
	r"^\s*advertisement\s*$",
	r"^\s*advertise\s*$",
	r"^\s*sign up\s*$",
	r"^\s*log in\s*$",
	r"^\s*login\s*$",
	r"^\s*subscribe\s*$",
	r"^\s*newsletter\s*$",
	r"^\s*share this article\s*$",
	r"^\s*more from\s+.*$",
	r"^\s*related articles\s*$",
]

BOILERPLATE_RE = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)
WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
NEWLINE_RE = re.compile(r"\n{3,}")
URL_RE = re.compile(r"https?://[^|\s)]+")


@dataclass(frozen=True)
class SourceRecord:
	index: int
	source: str
	description: str
	url: str

	@property
	def slug(self) -> str:
		base = re.sub(r"[^a-z0-9]+", "-", self.description.lower()).strip("-")
		return f"{self.index:02d}-{base or 'source'}"



@dataclass(frozen=True)
class LoadedDocument:
	index: int
	source: str
	description: str
	url: str
	text: str


def parse_arguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Load and clean source documents.")
	parser.add_argument(
		"--planning",
		type=Path,
		default=PLANNING_PATH,
		help="Path to planning.md containing the Documents table.",
	)
	parser.add_argument(
		"--index",
		type=int,
		default=None,
		help="1-based document index to print. If omitted, all documents are printed.",
	)
	parser.add_argument(
		"--sleep",
		type=float,
		default=1.0,
		help="Delay in seconds between requests to reduce rate limiting.",
	)
	return parser.parse_args()


def extract_source_table(planning_text: str) -> list[SourceRecord]:
	records: list[SourceRecord] = []
	table_started = False

	for line in planning_text.splitlines():
		if line.strip().startswith("| # | Source | Description | URL or location |"):
			table_started = True
			continue

		if not table_started:
			continue

		if not line.strip().startswith("|"):
			if records:
				break
			continue

		if line.strip().startswith("|---"):
			continue

		columns = [part.strip() for part in line.strip().strip("|").split("|")]
		if len(columns) < 4 or not columns[0].isdigit():
			continue

		url_match = URL_RE.search(columns[3])
		if not url_match:
			continue

		records.append(
			SourceRecord(
				index=int(columns[0]),
				source=columns[1],
				description=columns[2],
				url=url_match.group(0),
			)
		)

	if not records:
		raise ValueError("No source URLs were found in planning.md")

	return records


def fetch_url(url: str) -> requests.Response:
	response = requests.get(
		url,
		headers={"User-Agent": USER_AGENT},
		timeout=DEFAULT_TIMEOUT,
	)
	response.raise_for_status()
	return response


def fetch_rendered_text(url: str) -> str:
	chrome_path = next((path for path in CHROME_CANDIDATES if Path(path).exists()), None)
	launch_kwargs = {"headless": True}
	if chrome_path:
		launch_kwargs["executable_path"] = chrome_path

	with sync_playwright() as playwright:
		browser = playwright.chromium.launch(**launch_kwargs)
		page = browser.new_page(
			user_agent=USER_AGENT,
			viewport={"width": 1440, "height": 1600},
		)
		page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT * 1000)
		page.wait_for_timeout(2500)
		try:
			rendered_text = page.locator("main").inner_text(timeout=5000)
		except Exception:
			rendered_text = page.locator("body").inner_text(timeout=5000)
		browser.close()

	return rendered_text


def clean_text(text: str) -> str:
	text = html.unescape(text)
	text = text.replace("\r", "\n")
	text = WHITESPACE_RE.sub(" ", text)
	text = NEWLINE_RE.sub("\n\n", text)

	cleaned_lines: list[str] = []
	previous_line = ""

	for raw_line in text.splitlines():
		line = raw_line.strip()
		if not line:
			if cleaned_lines and cleaned_lines[-1] != "":
				cleaned_lines.append("")
			continue

		if BOILERPLATE_RE.match(line):
			continue

		lower = line.lower()
		if any(
			marker in lower
			for marker in (
				"cookie",
				"privacy policy",
				"terms of service",
				"advertisement",
				"promoted",
				"share this",
				"comment count",
				"read more",
				"sort by",
				"upvote",
				"downvote",
				"reply",
			)
		) and len(line) < 120:
			continue

		if line == previous_line:
			continue

		cleaned_lines.append(line)
		previous_line = line

	cleaned = "\n".join(cleaned_lines)
	cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
	return cleaned


def remove_boilerplate_nodes(soup: BeautifulSoup) -> None:
	for tag in soup.find_all(True):
		if tag.name and tag.name.lower() in BLOCK_TAGS:
			tag.decompose()

	for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
		comment.extract()

	selectors = [
		"[class*='cookie' i]",
		"[id*='cookie' i]",
		"[class*='consent' i]",
		"[id*='consent' i]",
		"[class*='banner' i]",
		"[id*='banner' i]",
		"[class*='share' i]",
		"[id*='share' i]",
		"[class*='social' i]",
		"[id*='social' i]",
		"[class*='advert' i]",
		"[id*='advert' i]",
		"[class*='ad-' i]",
		"[id*='ad-' i]",
		"[class*='footer' i]",
		"[id*='footer' i]",
		"[class*='header' i]",
		"[id*='header' i]",
		"[class*='nav' i]",
		"[id*='nav' i]",
		"[class*='comment-count' i]",
		"[id*='comment-count' i]",
		"[class*='read-more' i]",
		"[id*='read-more' i]",
	]

	for selector in selectors:
		for element in soup.select(selector):
			element.decompose()


def html_to_text(html_content: str) -> str:
	soup = BeautifulSoup(html_content, "html.parser")
	remove_boilerplate_nodes(soup)

	for anchor in soup.find_all("a"):
		anchor_text = anchor.get_text(" ", strip=True)
		if anchor_text and anchor_text.lower() in {"read more", "share"}:
			anchor.decompose()

	preferred_root = soup.find("main") or soup.find("article") or soup.body or soup
	text = preferred_root.get_text("\n", strip=True)
	return clean_text(text)


def extract_pdf_text(pdf_bytes: bytes) -> str:
	lines: list[str] = []
	with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
		for page in pdf.pages:
			page_text = page.extract_text() or ""
			if page_text.strip():
				lines.append(page_text)
	return clean_text("\n\n".join(lines))


def load_source(record: SourceRecord) -> str:
	url = record.url
	lower_url = url.lower()

	if lower_url.endswith(".pdf"):
		response = fetch_url(url)
		return extract_pdf_text(response.content)

	try:
		response = fetch_url(url)
		text = html_to_text(response.text)
		if text.strip():
			return text
	except requests.RequestException:
		pass

	rendered_text = fetch_rendered_text(url)
	return clean_text(rendered_text)


def build_manifest(records: Sequence[LoadedDocument]) -> dict:
	return {
		"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
		"documents": [
			{
				"index": record.index,
				"source": record.source,
				"description": record.description,
				"url": record.url,
				"character_count": len(record.text),
			}
			for record in records
		],
	}


def load_documents_from_planning(
	planning_path: Path = PLANNING_PATH,
	sleep: float = 1.0,
	index: int | None = None,
) -> list[LoadedDocument]:
	planning_text = planning_path.read_text(encoding="utf-8")
	records = extract_source_table(planning_text)
	if index is not None:
		records = [record for record in records if record.index == index]
		if not records:
			raise IndexError(f"Document index {index} is out of range for the available sources")

	documents: list[LoadedDocument] = []
	for record in records:
		print(f"Loading {record.index}: {record.description}")
		try:
			content = load_source(record)
		except Exception as exc:  # pragma: no cover - surfaced to user
			raise RuntimeError(f"Failed to load {record.url}: {exc}") from exc

		if not content.strip():
			raise RuntimeError(f"No usable text was extracted from {record.url}")

		documents.append(
			LoadedDocument(
				index=record.index,
				source=record.source,
				description=record.description,
				url=record.url,
				text=content.strip(),
			)
		)

		if sleep > 0:
			time.sleep(sleep)

	return documents


def print_documents(documents: Sequence[LoadedDocument]) -> None:
	for document in documents:
		print(f"\n{'=' * 80}")
		print(f"[{document.index}] {document.description}")
		print(f"Source: {document.source}")
		print(f"URL: {document.url}")
		print(f"Characters: {len(document.text)}")
		print("-" * 80)
		print(document.text)


def print_document_content_by_index(documents: Sequence[LoadedDocument], index: int) -> None:
	if index < 1 or index > len(documents):
		raise IndexError(f"Document index {index} is out of range for {len(documents)} loaded documents")

	document = documents[index - 1]
	print(document.text)


def main() -> int:
	args = parse_arguments()
	documents = load_documents_from_planning(args.planning, sleep=args.sleep, index=args.index)
	for document in documents:
		print(document.text)
	print(
		json.dumps(build_manifest(documents), indent=2, ensure_ascii=False)
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
