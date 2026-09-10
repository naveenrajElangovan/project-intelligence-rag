"""Publish exact Git-owned LangChain prompt templates to Phoenix for comparison."""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
from typing import Iterator

from evaluation.phoenix_assets import git_sha, prompt_payload
from evaluation.phoenix_client import PhoenixClient


def prompt_templates(path: Path) -> Iterator[tuple[str, str]]:
    """Extract literal templates from each ChatPromptTemplate construction."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        ordinal = 0
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr != "from_messages":
                continue
            strings = [value.value for value in ast.walk(child) if isinstance(value, ast.Constant) and isinstance(value.value, str)]
            if not strings:
                continue
            ordinal += 1
            yield f"rag-{node.name.replace('_', '-')}-{ordinal}", "\n\n".join(strings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("app/llm.py"))
    parser.add_argument("--owner", default="ai-platform")
    parser.add_argument("--tag", choices=("candidate", "staging", "production"), required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-provider", default="OLLAMA")
    parser.add_argument("--phoenix-url", default=os.getenv("PI_RAG_PHOENIX_URL", "http://127.0.0.1:6006"))
    parser.add_argument("--api-key", default=os.getenv("PI_RAG_PHOENIX_API_KEY", ""))
    args = parser.parse_args()
    sha = git_sha(args.source.resolve().parent.parent)
    client = PhoenixClient(args.phoenix_url, args.api_key)
    for name, template in prompt_templates(args.source):
        client.create_prompt(prompt_payload(name=name, template=template, owner=args.owner, sha=sha, tag=args.tag, model_name=args.model_name, model_provider=args.model_provider))


if __name__ == "__main__":
    main()
