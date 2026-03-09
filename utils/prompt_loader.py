# utils/prompt_loader.py
# Generic YAML prompt loader.
#
# YAML structure expected:
#
#   assembly_order:
#     - role
#     - rules
#     - output_schema
#     - examples
#
#   role: |
#     You are a query classifier ...
#
#   rules:
#     - Never answer the query
#     - Return only JSON
#
#   output_schema:
#     primary_group: <INSPECTION | TASK | WORKFLOW>
#     user_scoped: <true | false>
#
#   examples: |
#     WRONG: [ { "rank": 1 ... } ]
#     CORRECT: { "primary_group": "INSPECTION" ... }
#
# Section values may be: str | list | dict — each is rendered cleanly.
# assembly_order controls which sections appear and in what order.
# Any section not listed in assembly_order is ignored.

import yaml
from pathlib import Path
from utils.logger import get_app_logger

logger = get_app_logger("prompt_loader")


def load(prompt_path: Path) -> str:
    """
    Loads a YAML prompt file and assembles sections in the order defined
    by the `assembly_order` key.

    @param prompt_path: Absolute path to the YAML prompt file.
    @returns: Assembled system prompt string.
    @raises RuntimeError: If the file is missing, malformed, assembly_order
                          is absent, or the assembled result is empty.
    """
    raw = _read_yaml(prompt_path)
    order = _get_assembly_order(raw, prompt_path)
    parts = _assemble_sections(raw, order, prompt_path)
    assembled = "\n\n".join(parts)

    if not assembled.strip():
        raise RuntimeError(
            f"Prompt at '{prompt_path}' assembled to an empty string. "
            f"Check that 'assembly_order' keys match section names in the YAML."
        )

    logger.info(
        f"Prompt loaded: '{prompt_path.name}' — "
        f"{len(order)} sections, {len(assembled)} chars"
    )
    return assembled


# ── Private ───────────────────────────────────────────────────────────────────

def _read_yaml(prompt_path: Path) -> dict:
    """Reads and parses the YAML file. Raises RuntimeError on any failure."""
    if not prompt_path.exists():
        raise RuntimeError(
            f"Prompt file not found: '{prompt_path}'. "
            f"Ensure the knowledge/prompts directory is present and the filename is correct."
        )
    try:
        content = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Failed to parse YAML at '{prompt_path}': {exc}") from exc

    if not isinstance(content, dict):
        raise RuntimeError(
            f"Prompt file '{prompt_path}' must be a YAML mapping at the top level, "
            f"got {type(content).__name__}."
        )
    return content


def _get_assembly_order(raw: dict, prompt_path: Path) -> list[str]:
    """Extracts and validates the assembly_order list."""
    order = raw.get("assembly_order")
    if not order:
        raise RuntimeError(
            f"Prompt file '{prompt_path}' is missing the 'assembly_order' key. "
            f"Add an assembly_order list to control section sequencing."
        )
    if not isinstance(order, list):
        raise RuntimeError(
            f"'assembly_order' in '{prompt_path}' must be a list, "
            f"got {type(order).__name__}."
        )
    return order


def _assemble_sections(raw: dict, order: list[str], prompt_path: Path) -> list[str]:
    """
    Renders each section in assembly_order into a string.
    Skips sections that are missing from the YAML with a warning.
    """
    parts = []
    for section in order:
        if section not in raw:
            logger.warning(
                f"Prompt '{prompt_path.name}': section '{section}' listed in "
                f"assembly_order but not found in YAML — skipping."
            )
            continue
        rendered = _render_section(section, raw[section])
        if rendered.strip():
            parts.append(rendered)
    return parts


def _render_section(name: str, value) -> str:
    """
    Renders a single YAML section value into a string.

    - str  → returned as-is (stripped)
    - list → each item prefixed with '- ' and joined by newlines
    - dict → rendered as YAML block (preserves structure for schema sections)
    """
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, str):
                lines.append(f"- {item.strip()}")
            else:
                # Nested dict/list inside a list (e.g. few-shot examples)
                lines.append(yaml.dump(item, default_flow_style=False).strip())
        return "\n".join(lines)

    if isinstance(value, dict):
        return yaml.dump(value, default_flow_style=False).strip()

    # Fallback: cast anything else to string
    return str(value).strip()