import json
from pathlib import Path

from forge_api.main import create_app


def main() -> None:
    target = Path(__file__).resolve().parents[5] / "packages" / "shared-types" / "src"
    target.mkdir(parents=True, exist_ok=True)
    (target / "openapi.json").write_text(json.dumps(create_app().openapi(), indent=2))
    print("OpenAPI contract exported.")


if __name__ == "__main__":
    main()
