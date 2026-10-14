"""Write the generated OpenAPI document of the Evok API to a file.

The document is a build artifact, it is not committed; the release workflow runs::

    uv run python -m evok.openapi -o Evok_API_OAS.yaml

and attaches the file to the GitHub release, where the README links it.
"""

import argparse
import sys
from pathlib import Path

import yaml

from . import build_openapi

DEFAULT_OUTPUT = "Evok_API_OAS.yaml"


def render() -> str:
    return yaml.safe_dump(build_openapi(), sort_keys=False, allow_unicode=True, width=120)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o", "--output", default=DEFAULT_OUTPUT, help=f"path of the generated document (default '{DEFAULT_OUTPUT}')"
    )
    args = parser.parse_args()

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render())
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
