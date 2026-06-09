from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from load_documents import LoadedDocument, load_documents_from_planning


DEFAULT_CHUNK_SIZE = 600
DEFAULT_OVERLAP = 100


@dataclass(frozen=True)
class Chunk:
	chunk_id: str
	source_index: int
	source_name: str
	source_description: str
	source_url: str
	chunk_index: int
	start_char: int
	end_char: int
	text: str


def parse_arguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Chunk cleaned documents with fixed-size character windows and overlap."
	)
	parser.add_argument(
		"--planning",
		type=Path,
		default=Path(__file__).resolve().parent / "planning.md",
		help="Path to planning.md with the Documents table.",
	)
	parser.add_argument(
		"--index",
		type=int,
		default=None,
		help="Optional 1-based source index to load and chunk only one document.",
	)
	parser.add_argument(
		"--chunk-size",
		type=int,
		default=DEFAULT_CHUNK_SIZE,
		help=f"Chunk size in characters (default: {DEFAULT_CHUNK_SIZE}).",
	)
	parser.add_argument(
		"--overlap",
		type=int,
		default=DEFAULT_OVERLAP,
		help=f"Chunk overlap in characters (default: {DEFAULT_OVERLAP}).",
	)
	parser.add_argument(
		"--sleep",
		type=float,
		default=1.0,
		help="Delay between source fetches (passed to the loader).",
	)
	parser.add_argument(
		"--json",
		action="store_true",
		help="Print chunks as JSON instead of plain text.",
	)
	return parser.parse_args()


def validate_chunking_params(chunk_size: int, overlap: int) -> None:
	if chunk_size <= 0:
		raise ValueError("chunk_size must be greater than 0")
	if overlap < 0:
		raise ValueError("overlap must be at least 0")
	if overlap >= chunk_size:
		raise ValueError("overlap must be smaller than chunk_size")


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int, str]]:
	step = chunk_size - overlap
	chunks: list[tuple[int, int, str]] = []

	if not text.strip():
		return chunks

	start = 0
	text_length = len(text)

	while start < text_length:
		end = min(start + chunk_size, text_length)
		chunk_value = text[start:end].strip()
		if chunk_value:
			chunks.append((start, end, chunk_value))

		if end >= text_length:
			break

		start += step

	return chunks


def chunk_documents(
	documents: Sequence[LoadedDocument], chunk_size: int, overlap: int
) -> list[Chunk]:
	validate_chunking_params(chunk_size, overlap)

	all_chunks: list[Chunk] = []
	for document in documents:
		spans = chunk_text(document.text, chunk_size, overlap)
		for i, (start_char, end_char, chunk_value) in enumerate(spans, start=1):
			all_chunks.append(
				Chunk(
					chunk_id=f"doc{document.index:02d}_chunk{i:04d}",
					source_index=document.index,
					source_name=document.source,
					source_description=document.description,
					source_url=document.url,
					chunk_index=i,
					start_char=start_char,
					end_char=end_char,
					text=chunk_value,
				)
			)

	return all_chunks


def print_chunks_plain(chunks: Sequence[Chunk]) -> None:
	for chunk in chunks:
		print("=" * 80)
		print(
			f"{chunk.chunk_id} | source={chunk.source_index} | "
			f"chunk={chunk.chunk_index} | chars={chunk.start_char}:{chunk.end_char}"
		)
		print("-" * 80)
		print(chunk.text)
		print()


def print_chunks_json(chunks: Sequence[Chunk]) -> None:
	print(json.dumps([asdict(chunk) for chunk in chunks], indent=2, ensure_ascii=False))


def main() -> int:
	args = parse_arguments()

	documents = load_documents_from_planning(
		planning_path=args.planning,
		sleep=args.sleep,
		index=args.index,
	)
	chunks = chunk_documents(
		documents=documents,
		chunk_size=args.chunk_size,
		overlap=args.overlap,
	)

	# Suppress printing of individual chunks; only emit total count for analysis
	# if args.json:
	#     print_chunks_json(chunks)
	# else:
	#     print_chunks_plain(chunks)

	# Print only the total number of chunks created
	print(f"chunks_created: {len(chunks)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
