from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        document = yaml.safe_load(source)
    if not isinstance(document, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML mapping.")
    return document


def references(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            yield reference
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def resolve_reference(reference: str, source: Path, documents: dict[Path, dict[str, Any]]) -> None:
    file_name, separator, fragment = reference.partition("#")
    target_path = (source.parent / file_name).resolve() if file_name else source
    if target_path not in documents:
        raise ValueError(f"{source.name}: unknown reference file {file_name!r}.")

    target: Any = documents[target_path]
    if separator and fragment:
        if not fragment.startswith("/"):
            raise ValueError(f"{source.name}: invalid JSON pointer in {reference!r}.")
        for encoded_part in fragment.removeprefix("/").split("/"):
            part = encoded_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                raise ValueError(f"{source.name}: unresolved reference {reference!r}.")
            target = target[part]


def validate_mcp(document: dict[str, Any]) -> None:
    tools = document.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValueError("contracts/mcp-tools.yaml must define at least one tool.")

    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("Every MCP tool must be a mapping.")
        missing = {
            key
            for key in ("name", "effect", "scope", "inputSchema", "outputSchema")
            if key not in tool
        }
        if missing:
            raise ValueError(f"MCP tool is missing fields: {sorted(missing)}")

        name = tool["name"]
        if not isinstance(name, str) or not name:
            raise ValueError("Every MCP tool must have a non-empty name.")
        if name in names:
            raise ValueError(f"Duplicate MCP tool name: {name}")
        names.add(name)

        if tool["effect"] in {"write", "external-write"}:
            schema = tool["inputSchema"]
            required = schema.get("required", []) if isinstance(schema, dict) else []
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            if "idempotencyKey" not in required or "idempotencyKey" not in properties:
                raise ValueError(f"Write tool {name} must require idempotencyKey.")


def main() -> None:
    paths = sorted(CONTRACTS.glob("*.yaml"))
    documents = {path.resolve(): load_yaml(path) for path in paths}
    mcp_path = (CONTRACTS / "mcp-tools.yaml").resolve()
    validate_mcp(documents[mcp_path])

    for path, document in documents.items():
        for reference in references(document):
            resolve_reference(reference, path, documents)

    print(f"Validated {len(documents)} YAML contracts and their local references.")


if __name__ == "__main__":
    main()
