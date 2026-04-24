#!/usr/bin/env python3
"""Run the JobHunter pipeline using user needs from config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import LLMLayer


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "discord_config.json"


def _normalize_name_need(raw_name_need: object) -> Dict[str, Dict[str, str]]:
	"""Normalize supported nameNeed formats into {key: {name, need}}."""
	normalized: Dict[str, Dict[str, str]] = {}
	if not isinstance(raw_name_need, dict):
		return normalized

	for raw_key, raw_value in raw_name_need.items():
		key = str(raw_key).strip()
		if not key:
			continue

		if isinstance(raw_value, dict):
			name = str(raw_value.get("name") or "").strip()
			need = str(raw_value.get("need") or "").strip()
		elif isinstance(raw_value, str):
			# Backward-compatible format: {"Name": "Need text"}
			name = key
			need = raw_value.strip()
		else:
			continue

		if not name or not need:
			continue

		normalized[key] = {"name": name, "need": need}

	return normalized


def load_user_needs(config_path: Path) -> Tuple[List[str], List[str]]:
	raw = json.loads(config_path.read_text(encoding="utf-8"))
	normalized = _normalize_name_need(raw.get("nameNeed", {}))
	if not normalized:
		raise ValueError(
			"No user needs found in config. Add entries to 'nameNeed' first. "
			"Example: \"nameNeed\": {\"4892...\": {\"name\": \"Harry\", \"need\": \"...\"}}"
		)

	# Use name as the DB identity and prefer Discord user-id keyed entries when duplicated.
	needs_by_name: Dict[str, str] = {}
	for key, entry in normalized.items():
		name = entry["name"]
		need = entry["need"]
		if name not in needs_by_name or key.isdigit():
			needs_by_name[name] = need

	user_names = list(needs_by_name.keys())
	user_needs = [needs_by_name[name] for name in user_names]
	return user_names, user_needs


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Run JobHunter with config-driven user needs.")
	parser.add_argument(
		"--config",
		default=str(DEFAULT_CONFIG_PATH),
		help="Path to config JSON containing nameNeed. Default: discord_config.json",
	)
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	config_path = Path(args.config)
	if not config_path.exists():
		raise FileNotFoundError(
			f"Config file not found: {config_path}. Copy discord_config.example.json to discord_config.json and fill your values."
		)

	user_names, user_needs = load_user_needs(config_path)
	job_finder = LLMLayer.LLMClient()
	LLMLayer.FindMeSomeJobs(user_needs, user_names, job_finder)


if __name__ == "__main__":
	main()