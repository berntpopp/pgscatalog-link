"""Guard: every tool and argument a hint names must exist on this server.

Scans the package source for literal ``cmd("<tool>", <arg>=...)`` builders and
``{"tool": "<tool>", "arguments": {...}}`` dicts (``_meta.next_commands``) and checks them
against the live input schemas. Other fleet servers are named by their gateway name
(``<namespace>_<tool>``) and checked against a pinned argument set from the sibling repo's
signature; update the pin if a sibling renames.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from fastmcp import Client

import pgscatalog_link

_CROSS_SERVER: dict[str, set[str]] = {"mondo_resolve_disease": {"query", "response_mode"}}


def _source_refs() -> list[tuple[str, set[str], str]]:
    out: list[tuple[str, set[str], str]] = []
    for path in Path(pgscatalog_link.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "cmd"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                kws = {k.arg for k in node.keywords if k.arg is not None}
                out.append((node.args[0].value, kws, path.name))
            elif isinstance(node, ast.Dict):
                d = {
                    k.value: v
                    for k, v in zip(node.keys, node.values, strict=True)
                    if isinstance(k, ast.Constant)
                }
                tool, args = d.get("tool"), d.get("arguments")
                if isinstance(tool, ast.Constant) and isinstance(args, ast.Dict):
                    names = {k.value for k in args.keys if isinstance(k, ast.Constant)}
                    out.append((str(tool.value), names, path.name))
    return out


async def test_every_hint_names_a_real_tool_and_real_arguments(facade: Any) -> None:
    async with Client(facade) as client:
        schemas = {
            t.name: set(t.input_schema.get("properties", {})) for t in await client.list_tools()
        }
    assert not schemas.keys() & _CROSS_SERVER.keys()
    schemas |= _CROSS_SERVER
    refs = _source_refs()
    assert len(refs) >= 8, "scan found too few hint builders; did the cmd() helper move?"
    bad = [r for r in refs if r[0] not in schemas or not r[1] <= schemas[r[0]]]
    assert not bad, bad
