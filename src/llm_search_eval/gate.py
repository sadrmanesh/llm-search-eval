"""Quality gates for CI: fail a build when ranking quality regresses.

Two kinds of checks are supported and can be combined:

* **Floors**: a metric must stay at or above a fixed value, for example
  ``ndcg@10 >= 0.6``.
* **Regression limits**: a metric may not drop by more than an absolute or
  relative amount, either against the report's baseline system or against the
  same system in a reference report (for example the last run on ``main``).
  With ``significant_only`` a drop fails the gate only when the paired
  randomization test finds it significant at ``alpha``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from llm_search_eval.errors import ConfigError
from llm_search_eval.evaluate import paired_randomization_test
from llm_search_eval.metrics import Metric


@dataclass(frozen=True, slots=True)
class Check:
    kind: str  # "floor", "baseline", or "reference"
    system: str
    metric: str
    value: float | None
    against: float | None
    passed: bool
    message: str
    p_value: float | None = None


@dataclass(slots=True)
class GateResult:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": [asdict(c) for c in self.checks]}

    def to_markdown(self, title: str = "Search quality gate") -> str:
        status = "passed" if self.passed else f"failed ({len(self.failures)} check(s))"
        lines = [f"### {title}: {status}", ""]
        if not self.checks:
            return "\n".join([*lines, "No checks were configured.", ""])
        lines += [
            "| Result | Check | System | Metric | Value | Compared with | Details |",
            "| :---: | :--- | :--- | :--- | ---: | ---: | :--- |",
        ]
        for c in self.checks:
            lines.append(
                f"| {'pass' if c.passed else '**FAIL**'} | {c.kind} | `{c.system}` | {c.metric} | "
                f"{_fmt(c.value)} | {_fmt(c.against)} | {c.message} |"
            )
        lines.append("")
        return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def load_report(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(data, dict) or "systems" not in data or "config" not in data:
        raise ConfigError(f"{path} is not an llm-search-eval report.json")
    return data


def _system(data: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    return next((s for s in data["systems"] if s["name"] == name), None)


def _mean(system: Mapping[str, Any], metric: str) -> float | None:
    entry = system["metrics"].get(metric)
    return None if entry is None else entry["mean"]


def _drop_check(
    kind: str,
    name: str,
    metric: str,
    value: float | None,
    against: float | None,
    p_value: float | None,
    *,
    max_drop: float | None,
    max_relative_drop: float | None,
    significant_only: bool,
    alpha: float,
    against_name: str,
) -> Check:
    if value is None or against is None:
        return Check(kind, name, metric, value, against, True, "not comparable (no data)", p_value)
    drop = against - value
    relative = drop / against if against else 0.0
    problems = []
    if max_drop is not None and drop > max_drop + 1e-12:
        problems.append(f"dropped {drop:.4f} (limit {max_drop:.4f})")
    if max_relative_drop is not None and relative > max_relative_drop + 1e-12:
        problems.append(f"dropped {relative:.1%} (limit {max_relative_drop:.1%})")
    significant = p_value is not None and p_value < alpha
    p_text = "" if p_value is None else f", p={p_value:.4f}"
    if problems and significant_only and not significant:
        return Check(
            kind,
            name,
            metric,
            value,
            against,
            True,
            f"{'; '.join(problems)} vs {against_name}, not significant{p_text}",
            p_value,
        )
    if problems:
        return Check(
            kind,
            name,
            metric,
            value,
            against,
            False,
            f"{'; '.join(problems)} vs {against_name}{p_text}",
            p_value,
        )
    change = value - against
    return Check(
        kind,
        name,
        metric,
        value,
        against,
        True,
        f"{change:+.4f} vs {against_name}{p_text}",
        p_value,
    )


def _paired_p(
    current: Mapping[str, Any], other: Mapping[str, Any], metric: str, permutations: int, seed: int
) -> float | None:
    a_values, b_values = [], []
    for qid, values in current["per_query"].items():
        other_values = other["per_query"].get(qid)
        if other_values is None:
            continue
        x, y = values.get(metric), other_values.get(metric)
        if x is not None and y is not None:
            a_values.append(x)
            b_values.append(y)
    return paired_randomization_test(a_values, b_values, permutations, seed)


def check_report(
    data: Mapping[str, Any],
    *,
    reference: Mapping[str, Any] | None = None,
    metrics: Sequence[str] | None = None,
    floors: Mapping[str, float] | None = None,
    max_drop: float | None = None,
    max_relative_drop: float | None = None,
    systems: Sequence[str] | None = None,
    significant_only: bool = False,
    alpha: float = 0.05,
    permutations: int = 10_000,
    seed: int = 13,
) -> GateResult:
    """Evaluate gate rules against a report produced by :func:`~llm_search_eval.evaluate`.

    ``metrics`` defaults to the report's primary metric and applies to the
    regression limits. Baseline checks run only when a regression limit is set;
    with a ``reference`` report the comparison is made against it instead.
    """
    if not 0 < alpha < 1:
        raise ConfigError("alpha must be between 0 and 1")
    for limit in (max_drop, max_relative_drop):
        if limit is not None and limit < 0:
            raise ConfigError("regression limits must not be negative")
    config = data["config"]
    known = set(config["metrics"])
    selected = [Metric.parse(m).label for m in (metrics or [config["primary_metric"]])]
    floors = {Metric.parse(m).label: v for m, v in (floors or {}).items()}
    for metric in [*selected, *floors]:
        if metric not in known:
            raise ConfigError(
                f"metric {metric!r} is not in the report; available: {', '.join(sorted(known))}"
            )
    names = list(systems) if systems else [s["name"] for s in data["systems"]]
    for name in names:
        if _system(data, name) is None:
            raise ConfigError(f"system {name!r} is not in the report")

    result = GateResult()
    for name in names:
        system = _system(data, name)
        assert system is not None
        for metric, floor in floors.items():
            value = _mean(system, metric)
            ok = value is not None and value + 1e-12 >= floor
            message = f">= {floor:.4f} required" if ok else f"below the floor of {floor:.4f}"
            result.checks.append(Check("floor", name, metric, value, floor, ok, message))

    if max_drop is None and max_relative_drop is None:
        return result
    limits: dict[str, Any] = {
        "max_drop": max_drop,
        "max_relative_drop": max_relative_drop,
        "significant_only": significant_only,
        "alpha": alpha,
    }
    if reference is not None:
        for name in names:
            current = _system(data, name)
            previous = _system(reference, name)
            assert current is not None
            for metric in selected:
                if previous is None or metric not in previous["metrics"]:
                    result.checks.append(
                        Check(
                            "reference",
                            name,
                            metric,
                            _mean(current, metric),
                            None,
                            True,
                            "not in the reference report",
                        )
                    )
                    continue
                p = _paired_p(current, previous, metric, permutations, seed)
                result.checks.append(
                    _drop_check(
                        "reference",
                        name,
                        metric,
                        _mean(current, metric),
                        _mean(previous, metric),
                        p,
                        against_name="reference",
                        **limits,
                    )
                )
        return result

    baseline_name = config["baseline"]
    baseline = _system(data, baseline_name)
    assert baseline is not None
    for name in names:
        if name == baseline_name:
            continue
        current = _system(data, name)
        assert current is not None
        for metric in selected:
            p = _paired_p(current, baseline, metric, permutations, seed)
            result.checks.append(
                _drop_check(
                    "baseline",
                    name,
                    metric,
                    _mean(current, metric),
                    _mean(baseline, metric),
                    p,
                    against_name=f"baseline `{baseline_name}`",
                    **limits,
                )
            )
    return result
