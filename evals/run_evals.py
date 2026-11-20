"""LLM-as-judge evals with Arize (replaces dt-evals, per field guidance of 30 Oct 2026).

1. Export the last N hours of spans for the project from Arize AX.
2. For each agent run (one per trace), collect question, answer, tool outputs and the
   load-generator scenario (with its expected behaviour from loadgen/scenarios.yaml).
3. Judge with Phoenix evals; the judge model is called through our own AI gateway
   (model alias "judge-llm", chaos-exempt), so its cost is visible in Dynatrace too.
4. Write labels/scores/explanations back to Arize on the agent span (context.span_id).

  uv run python -m evals.run_evals --hours 6
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml
from arize import ArizeClient
from phoenix.evals import LLM, create_classifier, evaluate_dataframe

EXPECT = {s["id"]: s["expect"] for s in yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "loadgen" / "scenarios.yaml").read_text())["scenarios"]}

CORRECTNESS = """You are grading an insurance claims assistant.
Question: {question}
Expected behaviour: {expected}
Assistant answer: {answer}
Does the answer match the expected behaviour (coverage decision, amounts, currency, refusal)?
Answer "correct" or "incorrect"."""

GROUNDED = """You are checking an insurance claims assistant for hallucinations.
Tool results the assistant received (JSON): {tool_outputs}
Assistant answer: {answer}
Is every fact and number in the answer supported by the tool results (or is it a refusal/handoff)?
Answer "grounded" or "hallucinated"."""


def _col(df: pd.DataFrame, *names: str) -> pd.Series:
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series([None] * len(df), index=df.index)


def collect(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(
        trace_id=_col(df, "context.trace_id"),
        span_id=_col(df, "context.span_id"),
        kind=_col(df, "attributes.openinference.span.kind"),
        inp=_col(df, "attributes.input.value"),
        out=_col(df, "attributes.output.value"),
        scenario=_col(df, "attributes.app.scenario"),
    )
    rows = []
    for trace_id, g in df.groupby("trace_id"):
        agent = g[g["kind"] == "AGENT"]
        if agent.empty:
            continue
        a = agent.iloc[0]
        scenario = next((s for s in g["scenario"].dropna() if s in EXPECT), None)
        tools = [str(x) for x in g[g["kind"] == "TOOL"]["out"].dropna()]
        rows.append({
            "context.span_id": a["span_id"],
            "trace_id": trace_id,
            "question": str(a["inp"])[:4000],
            "answer": str(a["out"])[:4000],
            "tool_outputs": json.dumps(tools)[:6000],
            "expected": EXPECT.get(scenario, "A helpful, policy-grounded answer or a clear handoff."),
        })
    return pd.DataFrame(rows)


def main(hours: float) -> None:
    space, key = os.environ["ARIZE_SPACE_ID"], os.environ["ARIZE_API_KEY"]
    project = os.getenv("ARIZE_PROJECT_NAME", "v2-ai-demo")
    client = ArizeClient(api_key=key)
    end = datetime.now(timezone.utc)
    spans = client.spans.export_to_df(space_id=space, project_name=project,
                                      start_time=end - timedelta(hours=hours), end_time=end)
    runs = collect(spans)
    print(f"exported {len(spans)} spans -> {len(runs)} agent runs to evaluate")
    if runs.empty:
        return

    judge = LLM(provider="openai", model="judge-llm",
                base_url=f"{os.environ['GATEWAY_URL'].rstrip('/')}/v1", api_key=os.environ["LITELLM_MASTER_KEY"])
    evaluators = [
        create_classifier(name="correctness", prompt_template=CORRECTNESS, llm=judge,
                          choices={"correct": 1.0, "incorrect": 0.0}),
        create_classifier(name="grounded", prompt_template=GROUNDED, llm=judge,
                          choices={"grounded": 1.0, "hallucinated": 0.0}),
    ]
    scored = evaluate_dataframe(dataframe=runs, evaluators=evaluators)

    out = pd.DataFrame({"context.span_id": scored["context.span_id"]})
    for name in ("correctness", "grounded"):
        col = f"{name}_score"
        vals = scored[col].apply(lambda v: json.loads(v) if isinstance(v, str) else (v or {}))
        out[f"eval.{name}.label"] = vals.apply(lambda v: v.get("label"))
        out[f"eval.{name}.score"] = vals.apply(lambda v: v.get("score"))
        out[f"eval.{name}.explanation"] = vals.apply(lambda v: v.get("explanation"))
    out = out.dropna(subset=["eval.correctness.label"])
    client.spans.update_evaluations(space_id=space, project_name=project, dataframe=out)
    print(out[["eval.correctness.label", "eval.grounded.label"]].value_counts().to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6)
    main(ap.parse_args().hours)
