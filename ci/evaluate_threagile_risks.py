#!/usr/bin/env python3
"""Evaluates Threagile's risks.json and reports unhandled risks.

Codes 3 and 4 are permitted in the pipeline via allow_failure:exit_codes;
the job then ends with a warning and the pipeline continues. A Code
Quality report is also produced, which GitLab shows in the merge request.

Notes
-----
Exit codes:

0
    No unhandled risks.
3
    Unhandled risks, highest severity low to elevated.
4
    At least one unhandled risk with severity high/critical.
1
    Evaluation not possible (file missing, invalid JSON, unknown value).
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNHANDLED = 3
EXIT_UNHANDLED_HIGH = 4

# Statuses from risk_tracking that count as unhandled;
# accepted, in-progress, mitigated and false-positive count as handled
UNHANDLED_STATUS = {"unchecked", "in-discussion"}
KNOWN_STATUS = UNHANDLED_STATUS | {
    "accepted", "in-progress", "mitigated", "false-positive"}

# Threagile severities in ascending order
SEVERITY_ORDER = ["low", "medium", "elevated", "high", "critical"]
HIGH_SEVERITIES = {"high", "critical"}

# Mapping to the severities of GitLab's Code Quality report
CODEQUALITY_SEVERITY = {
    "low": "info",
    "medium": "minor",
    "elevated": "major",
    "high": "critical",
    "critical": "blocker",
}


class EvaluationError(Exception):
    """Raised when the evaluation cannot be performed."""


def load_risks(path: str | Path):
    """Load and validate the risks written by Threagile.

    Parameters
    ----------
    path : str or Path
        Path to Threagile's ``risks.json``.

    Returns
    -------
    list of dict
        The risks, each with ``risk_status`` set (``unchecked`` if absent).

    Raises
    ------
    EvaluationError
        If the file is missing, is not valid JSON, does not contain a
        list, or a risk has an unknown status or severity.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EvaluationError(
            f"{path} nicht gefunden; hat Threagile das Modell analysiert?")
    except json.JSONDecodeError as err:
        raise EvaluationError(f"{path} ist kein gültiges JSON: {err}")
    if data is None:  # Threagile writes "null" when there are no risks
        return []
    if not isinstance(data, list):
        raise EvaluationError(f"{path} enthält keine Liste von Risiken")
    for risk in data:
        risk_id = risk.get("synthetic_id")
        status = risk.get("risk_status") or "unchecked"
        severity = risk.get("severity")
        if status not in KNOWN_STATUS:
            raise EvaluationError(
                f"unbekannter Status '{status}' bei {risk_id}")
        if severity not in SEVERITY_ORDER:
            raise EvaluationError(
                f"unbekannter Schweregrad '{severity}' bei {risk_id}")
        risk["risk_status"] = status
    return data


def plain(text: str | None):
    """Strip the HTML markup Threagile uses in titles.

    Parameters
    ----------
    text : str or None
        Title text, possibly containing HTML tags.

    Returns
    -------
    str
        The text without tags and surrounding whitespace; empty if
        `text` is None.
    """
    return re.sub(r"<[^>]+>", "", text or "").strip()


def make_id(value: str):
    """Build an identifier the way Threagile does (MakeID).

    Parameters
    ----------
    value : str
        Name to convert.

    Returns
    -------
    str
        Lowercase identifier with runs of non-alphanumeric characters
        replaced by a single hyphen.
    """
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("- ")


def find_line(model_lines: list[str], risk: dict[str, Any]):
    """Find the line in the model where the affected element is defined.

    Parameters
    ----------
    model_lines : list of str
        Lines of the Threagile model file.
    risk : dict
        A risk from ``risks.json``.

    Returns
    -------
    int
        1-based line number of the most relevant element, or 1 if none
        is found.
    """

    def id_line(element_id: str, start: int = 0):
        pattern = re.compile(
            r"^\s*id:\s*['\"]?" + re.escape(element_id) + r"['\"]?\s*$")
        for number in range(start, len(model_lines)):
            if pattern.match(model_lines[number]):
                return number
        return None

    # Communication link: identifier "source>link-name"
    link = risk.get("most_relevant_communication_link")
    if link and ">" in link:
        source, link_key = link.split(">", 1)
        start = id_line(source)
        if start is not None:
            for number in range(start, len(model_lines)):
                key = re.match(r"^\s+([^:#][^:]*):\s*$", model_lines[number])
                if key and make_id(key.group(1)) == link_key:
                    return number + 1
    for field in ("most_relevant_technical_asset",
                  "most_relevant_trust_boundary",
                  "most_relevant_shared_runtime",
                  "most_relevant_data_asset"):
        element = risk.get(field)
        if element:
            number = id_line(element)
            if number is not None:
                return number + 1
    return 1


def codequality_report(unhandled: list[dict[str, Any]], model_path: str):
    """Build a GitLab Code Quality report for the unhandled risks.

    Parameters
    ----------
    unhandled : list of dict
        Unhandled risks from ``risks.json``.
    model_path : str
        Path to the model, relative to the repository.

    Returns
    -------
    list of dict
        Code Quality report entries, one per risk.
    """
    model_file = Path(model_path)
    model_lines = []
    if model_file.is_file():
        model_lines = model_file.read_text(encoding="utf-8").splitlines()
    report = []
    for risk in unhandled:
        title = plain(risk.get("title"))
        fingerprint = hashlib.sha256(
            risk["synthetic_id"].encode("utf-8")).hexdigest()
        report.append({
            "description": f"Threagile: {title} "
                           f"(Status: {risk['risk_status']})",
            "check_name": f"threagile/{risk.get('category')}",
            "fingerprint": fingerprint,
            "severity": CODEQUALITY_SEVERITY[risk["severity"]],
            "location": {
                "path": model_path.removeprefix("./"),
                "lines": {"begin": find_line(model_lines, risk)},
            },
        })
    return report


def main():
    """Run the evaluation from the command line.

    Returns
    -------
    int
        Process exit code (see the module docstring).
    """
    parser = argparse.ArgumentParser(
        description="Unbehandelte Risiken aus Threagile melden")
    parser.add_argument("--risks", required=True,
                        help="Pfad zur risks.json von Threagile")
    parser.add_argument("--model", required=True,
                        help="Pfad zum Modell, relativ zum Repository")
    parser.add_argument("--codequality", required=True,
                        help="Ausgabedatei für den Code-Quality-Bericht")
    args = parser.parse_args()

    try:
        risks = load_risks(args.risks)
    except EvaluationError as err:
        print(f"FEHLER: {err}", file=sys.stderr)
        return EXIT_ERROR

    unhandled = [r for r in risks if r["risk_status"] in UNHANDLED_STATUS]
    unhandled.sort(key=lambda r: SEVERITY_ORDER.index(r["severity"]),
                   reverse=True)

    report = codequality_report(unhandled, args.model)
    Path(args.codequality).write_text(json.dumps(report, indent=2),
                                      encoding="utf-8")

    print(f"Threagile-Risiken gesamt: {len(risks)}, "
          f"davon unbehandelt: {len(unhandled)}")
    if not unhandled:
        print("Keine unbehandelten Risiken.")
        return EXIT_OK

    counts = [f"{s}: {sum(1 for r in unhandled if r['severity'] == s)}"
              for s in reversed(SEVERITY_ORDER)
              if any(r["severity"] == s for r in unhandled)]
    print("WARNUNG: Das Bedrohungsmodell enthält unbehandelte Risiken ("
          + ", ".join(counts) + ").")
    for risk in unhandled:
        print(f"  [{risk['severity']:<8}] [{risk['risk_status']:<13}] "
              f"{plain(risk.get('title'))}")
        print(f"      {risk['synthetic_id']}")
    print("Behandlung im Abschnitt risk_tracking des Modells "
          "dokumentieren (accepted, in-progress, mitigated oder "
          "false-positive, jeweils mit Begründung).")

    if any(r["severity"] in HIGH_SEVERITIES for r in unhandled):
        return EXIT_UNHANDLED_HIGH
    return EXIT_UNHANDLED


if __name__ == "__main__":
    sys.exit(main())
