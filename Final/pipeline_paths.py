"""Paths to the Final scripts and the shared project inputs."""

from pathlib import Path


FINAL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = FINAL_DIR.parent
GRAPHS_DIR = PROJECT_DIR / "Graphs"
BIN_DIR = PROJECT_DIR / "bin"


def graph_input_path(value):
    """Resolve a benchmark number, benchmark name, or graph file path."""
    name = str(value).strip()
    if not name:
        raise ValueError("A graph number, name, or path is required.")

    raw = Path(name)
    if name.isdigit():
        candidates = (GRAPHS_DIR / f"Graph{int(name)}.txt",)
    elif raw.is_absolute():
        candidates = (raw,)
    else:
        candidates = (raw, GRAPHS_DIR / raw.name)

    for path in candidates:
        if path.is_file():
            return path.resolve()
        if path.name and not path.suffix:
            with_suffix = path.with_suffix(".txt")
            if with_suffix.is_file():
                return with_suffix.resolve()

    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Graph file not found: {name}. Checked: {checked}")
