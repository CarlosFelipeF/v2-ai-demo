# V2 demo: one AI request, end to end, Dynatrace + Arize (~45 min, joint)

**Audience:** Marwan, Michael Ewald, Daghan (V2); Blair. **Presenters:** Carlos (Dynatrace), Arize SE (Arize part).
**V2's question:** can you follow one AI request from the user's click to the LLM, *through the AI gateway*, without the trace breaking?

> **Draft.** Click paths marked (verify) get confirmed in the dry run on the real tenant. Screenshots land in `screenshots/` after Phase A.

## The honest framing (say it, don't hide it)
Today this is **one OpenTelemetry trace, instrumented once, sent to both products**. Dynatrace answers *"is the AI service up, fast and cost-controlled, and where is the problem?"* Arize answers *"is the agent any good, and how do I improve it?"* A native integration that brings Arize eval scores into Dynatrace is planned for March. **Do not** claim a built-in end-to-end integration exists today.

## Run of show

| Min | Who | Section |
|---|---|---|
| 0–5 | Carlos | 1. Framing |
| 5–8 | Carlos | 2. The live click |
| 8–20 | Carlos | 3. Dynatrace: the SRE view |
| 20–22 | Carlos → Arize | 4. Handover with the trace ID |
| 22–37 | Arize SE | 5. Arize: the AI engineer view |
| 37–45 | Both | 6. Better together + next steps |

### 1. Framing (5 min)
**SAY:** "Two teams care about the same AI request. The SRE asks: is it up, fast, within budget, and where did it break? The AI engineer asks: was the answer right, and how do I make it better? Your question is whether one trace can serve both, even through a gateway."
**ON SCREEN:** architecture slide: browser → API → agent → **AI gateway (LiteLLM)** → Bedrock, with both backends underneath.
**SAY:** "Gateways are where traces usually break, because the hop drops the trace headers. That's what we'll prove doesn't happen here."

### 2. The live click (3 min)
**ON SCREEN:** the claims assistant page. Click **Storm claim**, then ask: "My policy is HOME-1001, hail wrecked my fence, $3,000." Point at the trace ID under the answer.
**SAY:** "A customer of an insurer asks about a claim. The agent looks up the policy, estimates the payout and answers. That ID under the answer is the whole request."

### 3. Dynatrace, the SRE view (12 min)
1. **RUM session (verify):** Experience → the user session → the click. "This is the customer's click."
2. **Distributed trace:** open the trace from the click. Walk the waterfall: browser → `claims-app` → `claims-assistant` agent → `ai-gateway` → Bedrock. **SAY:** "Same trace ID all the way. The gateway span is in the middle, and nothing broke."
3. **AI Observability (verify):** tokens in/out, latency and cost by model; the gateway's budget cap. **SAY:** "Cost and latency per call, per model, per use case. This is what finance and SRE need."
4. **Break it live:** `scripts/chaos.sh latency` (or `errors`), run the browser load for a minute (`uv run python -m loadgen.browser --sessions 3`).
5. **Dynatrace Intelligence problem (verify):** open the problem; root cause points at the `ai-gateway` service. **SAY:** "The AI service degraded, and Dynatrace Intelligence found the cause in the gateway, not in the app or the model."
6. `scripts/chaos.sh off`.

### 4. Handover (2 min)
**ON SCREEN:** copy the trace ID from the Dynatrace trace (or the page's "copy trace ID" button).
**SAY:** "I've shown you what happened and where. The AI engineers' question is a different one: was the answer *good*? Same trace ID. Over to Arize."

### 5. Arize, the AI engineer view (15 min, Arize SE leads)
Suggested beats (the Arize SE adapts): paste the trace ID in the project `v2-ai-demo` → agent graph and tool calls → inputs/outputs → eval labels (correctness, grounded) → filter to `incorrect` / `hallucinated` → open a bad answer (the unknown-policy and flood cases are built to fail) → how they'd fix the prompt and re-test.
**Backup if the Arize SE can't join:** Carlos covers this using `evals/run_evals.py` output and the screenshots; keep it to 8 min.

### 6. Better together and next steps (8 min)
- Instrument once with **OpenInference** (it replaces OpenLLMetry), send to both.
- **Dynatrace** for SRE, platform and operations. **Arize** for AI engineering. Executives: Arize with a Head of AI, Dynatrace with the CIO/CTO.
- Planned March integration: Arize eval scores visible to SRE users in Dynatrace.
- For V2: a repeatable reference stack they can show their own customers. Ask: which customer has an AI gateway today?

## Likely questions
- **"Is this one product?"** Two products, one shared trace. Native eval-score sharing is planned for March.
- **"Why not Dynatrace evals?"** They're being retired on 1 Jan 2027; Arize is the recommended evaluation platform. Existing results stay available as business events.
- **"Does the trace survive a different gateway (Kong, Azure APIM)?"** Yes, if the gateway is traced and passes `traceparent` on. Here we use LiteLLM.
- **"What does it cost to run?"** The demo stack costs a few dollars a month; the gateway has a hard budget cap.

## Fallbacks
Local stack (`scripts/dev.sh up`) if AWS is down · screenshots in `screenshots/` · a 3-min recording (to be made in the dry run).
