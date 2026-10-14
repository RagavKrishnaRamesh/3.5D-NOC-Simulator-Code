#!/usr/bin/env python3
"""Export 3D particles as mapping, placement, assignment on each graph's line."""

import argparse
import json
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
PARTICLE_NAME = re.compile(r".*Particle([1-9][0-9]*)\.txt")
GRAPH_NAME = re.compile(r"Graph([1-9][0-9]*)")
FIELDS = ("core_to_router", "tsv_placement", "tsv_assignment")


def read_particle(path, graph_number):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("graph") != f"Graph{graph_number}":
        raise ValueError(f"{path}: graph name does not match filename")
    chiplets = data.get("chiplets", [])
    if len(chiplets) != 1 or chiplets[0].get("type") != "3d":
        raise ValueError(f"{path}: expected exactly one 3D chiplet")
    arrays = [chiplets[0].get(field) for field in FIELDS]
    for field, values in zip(FIELDS, arrays):
        if not isinstance(values, list) or any(type(value) is not int for value in values):
            raise ValueError(f"{path}: {field} must be a list of integers")
    return " ".join(json.dumps(values, separators=(",", ":")) for values in arrays)


def export_particles(particle_folder, output, graph_count=None):
    if not particle_folder.is_dir():
        raise ValueError(f"Particle folder does not exist: {particle_folder}")
    lines = {}
    for path in sorted(particle_folder.glob("*Particle*.txt")):
        match = PARTICLE_NAME.fullmatch(path.name)
        if not match:
            continue
        number = int(match.group(1))
        if number in lines:
            raise ValueError(f"Multiple particle files found for Graph{number}")
        if output.resolve() == path.resolve():
            raise ValueError("Output must not overwrite a source particle file")
        lines[number] = read_particle(path, number)
    if not lines:
        raise ValueError(f"No *Particle<number>.txt files found in {particle_folder}")

    if graph_count is None:
        repository_numbers = [
            int(match.group(1))
            for path in (REPO_ROOT / "Graphs").glob("Graph*.txt")
            if (match := GRAPH_NAME.fullmatch(path.stem))
        ]
        graph_count = max([*lines, *repository_numbers])
    if graph_count < max(lines):
        raise ValueError(f"--graph-count must be at least {max(lines)} to include all particles")

    text = "".join(lines.get(number, "[][][]") + "\n" for number in range(1, graph_count + 1))
    output.write_text(text, encoding="utf-8")
    return len(lines), graph_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("particle_folder", type=Path, help="Folder containing *Particle<number>.txt files")
    parser.add_argument("-o", "--output", type=Path, help="Output text file (default: particles_3d.txt beside the particle folder)")
    parser.add_argument("--graph-count", type=int, help="Total graph lines; default covers repository graphs and all particles")
    args = parser.parse_args()
    if args.graph_count is not None and args.graph_count < 1:
        parser.error("--graph-count must be positive")
    output = args.output if args.output is not None else args.particle_folder.resolve().parent / "particles_3d.txt"
    try:
        present, total = export_particles(args.particle_folder, output, args.graph_count)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        parser.error(str(error))
    print(f"Wrote {total} graph lines to {output} ({present} particles, {total - present} missing).")


if __name__ == "__main__":
    main()
