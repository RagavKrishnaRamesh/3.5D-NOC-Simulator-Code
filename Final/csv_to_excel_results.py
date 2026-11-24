"""Export pipeline CSVs to the reference static and dynamic Excel layouts."""

from __future__ import annotations

import argparse
import csv
import re
import tempfile
import zipfile
from html import escape
from pathlib import Path
from typing import Iterable


STATIC_SHEET = "Static Results"
DYNAMIC_SHEET = "Dynamic Results"

STATIC_COLUMNS = [
    "Benchmark",
    " CC",
    "TSV Dir_Up",
    "Down TSV flow",
    "Normalized",
    "CPU time(sec)",
]

DYNAMIC_COLUMNS = [
    "Benchmark",
    "avg Delay",
    "avg Throughput",
    "\tTotal Energy",
    "received Pkts",
    "avg Pkt Energy in µJ",
]

STATIC_COLUMN_MAP = {
    " CC": "comm_cost",
    "TSV Dir_Up": "Variance Up",
    "Down TSV flow": "Variance Down",
    "Normalized": "Normalized Variance",
    "CPU time(sec)": "CPU Time",
}

DYNAMIC_COLUMN_MAP = {
    "avg Delay": "Global average delay (cycles)",
    "avg Throughput": "Average IP throughput (flits/cycle/IP)",
    "\tTotal Energy": "Total energy (J)",
    "received Pkts": "Total received packets",
    "avg Pkt Energy in µJ": None,
}
SIMULATOR_COLUMNS = tuple(column for column in DYNAMIC_COLUMN_MAP.values() if column is not None)

PIPELINE_CSV_COLUMNS = [
    "Graph",
    "Algorithm",
    "Dimension",
    "Population",
    "Iterations",
    "Runtime",
    "Real Time",
    "User Time",
    "System Time",
    "CPU Time",
    "comm_cost",
    "Variance",
    "Variance Up",
    "Variance Down",
    "Normalized Variance",
    "Effective Fitness",
    "Fitness Workers",
    "Optimizer Seed",
    "Simulator Seed",
    "Simulation Time",
    "... simulator metric columns parsed from the log, including the dynamic columns above",
]

BENCHMARK_ORDER = [
    "G9",
    "G10",
    "G1",
    "VPOD(G8)",
    "G12",
    "G13",
    "DVPOD(G4)",
    "G17 (64)",
    "G18",
    "G19",
    "G20",
    "G21",
    "G22",
    "G23",
    "BLACKSCHOLES_G50",
    "BODYTRACK_G51",
    "CANNEAL_G52",
    "DEDUP_G53",
    "FERRET_G54",
    "FLUIDANIMATE_G55",
    "FREQMINE_G56",
    "VIPS_G58",
    "BARNES_G60",
    "CHOLESKY_G61",
    "FFT_G62",
    "LU_CB_G63",
    "LU_NCB_G64",
    "OCEAN_CP_G65",
    "G25 (128)",
    "G26",
    "G27",
    "G28",
    "G29",
    "G30",
]

BENCHMARK_TO_GRAPH = {
    benchmark: int(re.search(r"G(?:raph)?\s*(\d+)", benchmark, re.IGNORECASE).group(1))
    for benchmark in BENCHMARK_ORDER
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export one pipeline CSV or combine the three variants into a workbook."
    )
    parser.add_argument(
        "csv", type=Path, nargs="+",
        help="One results CSV or three CSVs in PSO, PSO_DP, PSO_DP_MT order",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .xlsx path. Required with three CSVs.",
    )
    parser.add_argument(
        "--show-mapping",
        action="store_true",
        help="Print the pipeline CSV to Excel column mapping.",
    )
    args = parser.parse_args()
    if len(args.csv) not in (1, 3):
        parser.error("provide one CSV or all three variant CSVs")
    if len(args.csv) == 3 and args.output is None:
        parser.error("--output is required with three CSVs")
    return args


def require_columns(headers: Iterable[str], columns: Iterable[str]) -> None:
    header_set = set(headers)
    missing = [column for column in columns if column not in header_set]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")


def normalize_value(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return number


def graph_number(value) -> int | None:
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    match = re.fullmatch(r"G(?:raph)?\s*(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def benchmark_rows(rows: list[dict[str, str]]) -> list[tuple[str, dict[str, str] | None]]:
    benchmark_rows_out = []
    rows_by_graph = {}
    named_rows = []
    for row in rows:
        name = row.get("Graph", "")
        graph = graph_number(name)
        if graph is None:
            named_rows.append((name, row))
        else:
            rows_by_graph.setdefault(graph, []).append(row)

    for benchmark in BENCHMARK_ORDER:
        graph = BENCHMARK_TO_GRAPH[benchmark]
        benchmark_rows_out.extend((benchmark, row) for row in rows_by_graph.get(graph, [None]))

    reference_graphs = set(BENCHMARK_TO_GRAPH.values())
    for graph in sorted(graph for graph in rows_by_graph if graph not in reference_graphs):
        benchmark_rows_out.extend((f"G{graph}", row) for row in rows_by_graph[graph])
    benchmark_rows_out.extend(named_rows)
    return benchmark_rows_out


def average_packet_energy_uj(row: dict[str, str]):
    total_energy = row.get("Total energy (J)")
    packets = row.get("Total received packets")
    if total_energy in (None, "") or packets in (None, "") or float(packets) == 0:
        return None
    return float(total_energy) / float(packets) * 1_000_000


def mapped_value(row: dict[str, str] | None, excel_column: str, column_map: dict[str, str | None]):
    if row is None:
        return None
    source_column = column_map[excel_column]
    if source_column is None:
        return average_packet_energy_uj(row)
    return normalize_value(row.get(source_column))


def sheet_rows(
    columns: list[str],
    column_map: dict[str, str | None],
    rows: list[tuple[str, dict[str, str] | None]],
) -> list[list[object]]:
    output_rows: list[list[object]] = [columns]
    for benchmark, row in rows:
        output_rows.append(
            [benchmark] + [mapped_value(row, column, column_map) for column in columns[1:]]
        )
    return output_rows


def print_mapping() -> None:
    print("Full-pipeline CSV columns from run_pipeline.py:")
    for column in PIPELINE_CSV_COLUMNS:
        print(f"  - {column}")

    print("\nStatic Results sheet mapping:")
    for excel_column in STATIC_COLUMNS[1:]:
        print(f"  {excel_column} <- {STATIC_COLUMN_MAP[excel_column]}")

    print("\nDynamic Results sheet mapping:")
    for excel_column in DYNAMIC_COLUMNS[1:]:
        source = DYNAMIC_COLUMN_MAP[excel_column]
        if source is None:
            source = "Total energy (J) / Total received packets * 1_000_000"
        print(f"  {excel_column} <- {source}")

    print("\nBenchmark row name to Graph number map:")
    for benchmark in BENCHMARK_ORDER:
        print(f"  {benchmark} -> {BENCHMARK_TO_GRAPH[benchmark]}")


def result_sheets(csv_path: Path, prefix: str = ""):
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        rows = list(reader)

    required = ["Graph", *STATIC_COLUMN_MAP.values(), *SIMULATOR_COLUMNS]
    require_columns(headers, required)

    ordered_rows = benchmark_rows(rows)

    return [
        (prefix + STATIC_SHEET, sheet_rows(STATIC_COLUMNS, STATIC_COLUMN_MAP, ordered_rows)),
        (prefix + DYNAMIC_SHEET, sheet_rows(DYNAMIC_COLUMNS, DYNAMIC_COLUMN_MAP, ordered_rows)),
    ]


def convert(csv_path: Path, output_path: Path) -> None:
    write_xlsx(output_path, result_sheets(csv_path))


def convert_comparison(csv_by_algorithm: dict[str, Path], output_path: Path) -> None:
    sheets = []
    for algorithm, csv_path in csv_by_algorithm.items():
        sheets.extend(result_sheets(csv_path, f"{algorithm} "))
    write_xlsx(output_path, sheets)


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def cell_xml(value, row_index: int, column_index: int) -> str:
    ref = f"{column_name(column_index)}{row_index}"
    style = ' s="1"' if row_index == 1 else ' s="2"'
    if value is None:
        return f'<c r="{ref}"{style}/>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"{style}><is><t>{escape(str(value))}</t></is></c>'


def worksheet_xml(rows: list[list[object]]) -> str:
    max_columns = max(len(row) for row in rows)
    columns = "".join(
        f'<col min="{index}" max="{index}" width="20" customWidth="1"/>'
        for index in range(1, max_columns + 1)
    )
    sheet_data = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(
            cell_xml(value, row_index, column_index)
            for column_index, value in enumerate(row, start=1)
        )
        sheet_data.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<cols>{columns}</cols><sheetData>{''.join(sheet_data)}</sheetData>"
        "</worksheet>"
    )


def workbook_xml(sheets: list[tuple[str, list[list[object]]]]) -> str:
    sheet_tags = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _) in enumerate(sheets, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_tags}</sheets></workbook>"
    )


def workbook_rels_xml(sheets: list[tuple[str, list[list[object]]]]) -> str:
    relationships = []
    for index, _ in enumerate(sheets, start=1):
        relationships.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
    relationships.append(
        f'<Relationship Id="rId{len(sheets) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(relationships)}</Relationships>"
    )


def content_types_xml(sheets: list[tuple[str, list[list[object]]]]) -> str:
    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index, _ in enumerate(sheets, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheet_overrides}</Types>"
    )


def root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF7"/></patternFill></fill></fills>'
        '<borders count="2"><border/><border><left style="thin"><color rgb="FFB7B7B7"/></left>'
        '<right style="thin"><color rgb="FFB7B7B7"/></right><top style="thin"><color rgb="FFB7B7B7"/></top>'
        '<bottom style="thin"><color rgb="FFB7B7B7"/></bottom></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/></cellXfs>'
        '</styleSheet>'
    )


def write_xlsx(output_path: Path, sheets: list[tuple[str, list[list[object]]]]) -> None:
    with tempfile.NamedTemporaryFile(dir=output_path.parent, suffix=".xlsx", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types_xml(sheets))
            archive.writestr("_rels/.rels", root_rels_xml())
            archive.writestr("xl/workbook.xml", workbook_xml(sheets))
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(sheets))
            archive.writestr("xl/styles.xml", styles_xml())
            for index, (_, rows) in enumerate(sheets, start=1):
                archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet_xml(rows))
        temp_path.replace(output_path)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    output_path = args.output or args.csv[0].with_suffix(".xlsx")
    if len(args.csv) == 1:
        convert(args.csv[0], output_path)
    else:
        variants = ("PSO", "PSO_DP", "PSO_DP_MT")
        convert_comparison(dict(zip(variants, args.csv)), output_path)
    print(f"Wrote {output_path}")
    if args.show_mapping:
        print_mapping()


if __name__ == "__main__":
    main()
