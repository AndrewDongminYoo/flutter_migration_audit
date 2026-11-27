"""Render an audit report as plain text or JSON."""

from __future__ import annotations

import json
import textwrap
from dataclasses import asdict

from .rules import AFFECTED, LABELS, NEEDS_CHECK, NOT_AFFECTED, Report

ORDER = {AFFECTED: 0, NEEDS_CHECK: 1, NOT_AFFECTED: 2}


def _wrap(text: str, indent: str) -> str:
    return textwrap.fill(
        text, width=100, initial_indent=indent, subsequent_indent=indent
    )


def to_text(report: Report) -> str:
    out = [
        f"Flutter {report.current} → {report.target} · Android 시스템 바 / edge-to-edge",
        f"입력: {', '.join(report.files) if report.files else '(없음)'}",
    ]
    if report.retriever:
        out.append(f"근거 검색: {report.retriever} + 버전 필터")
    out.append("")
    counts = {v: sum(f.verdict == v for f in report.findings) for v in ORDER}
    out.append("요약: " + " · ".join(f"{LABELS[v]} {counts[v]}" for v in ORDER))
    out.append("")
    for f in sorted(report.findings, key=lambda f: ORDER[f.verdict]):
        out.append(f"[{LABELS[f.verdict]}] {f.title}")
        out.append(_wrap(f.reason, "  "))
        if f.clues:
            out.append("  앱 단서:")
            out += [f"    {c.render()}" for c in f.clues]
        if f.evidence:
            out.append("  문서 근거:")
            for ev in f.evidence:
                out.append(_wrap(f"“{ev.quote}”", "    "))
                where = ev.title + (f" › {ev.heading}" if ev.heading else "")
                out.append(f"      {where} · {ev.source_label()}")
                out.append(f"      {ev.url}")
        if f.missing_evidence:
            out.append(f"  찾지 못한 근거: {', '.join(f.missing_evidence)}")
        if f.check:
            out.append(_wrap("확인할 것: " + f.check, "  "))
        if f.tests:
            out.append("  직접 테스트:")
            out += [_wrap("- " + t, "    ") for t in f.tests]
        out.append("")
    for note in report.notes:
        out.append(_wrap("참고: " + note, ""))
    return "\n".join(out).rstrip() + "\n"


def to_json(report: Report) -> str:
    data = asdict(report)
    for f in data["findings"]:
        f["verdict_label"] = LABELS[f["verdict"]]
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
