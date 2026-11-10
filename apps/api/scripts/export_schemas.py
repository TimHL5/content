"""`make types`, step 1: Pydantic models -> one JSON Schema document.

Step 2 (`pnpm --filter @stylecut/schemas generate`) turns it into TypeScript.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic.json_schema import models_json_schema

from stylecut.schemas import EXPORTED_MODELS

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "packages" / "schemas" / "generated" / "schemas.json"


def build_schema() -> dict[str, Any]:
    _, defs = models_json_schema(
        [(model, "serialization") for model in EXPORTED_MODELS],
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "StyleCutSchemas",
        "description": "Generated from apps/api/stylecut/schemas. Do not edit.",
        "type": "object",
        "additionalProperties": False,
        "$defs": dict(sorted(defs["$defs"].items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
