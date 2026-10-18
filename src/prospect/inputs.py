"""Turn CLI arguments and an input file into a clean, de-duplicated company list."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompanyInput:
    name: str
    domain: str | None


def _parse_line(line: str) -> CompanyInput | None:
    line = line.split(" #")[0].strip()  # inline comments: "Acme  # why it is here"
    if not line or line.startswith("#"):
        return None
    name, _, domain = (part.strip() for part in line.partition("|"))
    domain = domain.removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
    return CompanyInput(name, domain or None) if name else None


def parse_input(args: list[str], file: Path | None) -> list[CompanyInput]:
    lines = list(args) + (file.read_text().splitlines() if file else [])
    seen: set[str] = set()
    out = []
    for c in filter(None, map(_parse_line, lines)):
        if c.name.casefold() not in seen:
            seen.add(c.name.casefold())
            out.append(c)
    return out
