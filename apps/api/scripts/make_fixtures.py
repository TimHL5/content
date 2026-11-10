"""`make fixtures`: write the synthetic test clips to tests/fixtures/."""

import argparse
from pathlib import Path

from stylecut.media.ffmpeg import run_ffmpeg
from stylecut.media.fixtures import FIXTURES

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def make_fixtures(out_dir: Path, force: bool = False) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, build in FIXTURES.items():
        path = out_dir / name
        if path.exists() and not force:
            continue
        run_ffmpeg(build(path))
        written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--force", action="store_true", help="regenerate existing files")
    args = parser.parse_args()
    written = make_fixtures(args.out, force=args.force)
    for path in written:
        print(f"wrote {path}")
    if not written:
        print(f"all fixtures already exist in {args.out} (use --force to regenerate)")


if __name__ == "__main__":
    main()
