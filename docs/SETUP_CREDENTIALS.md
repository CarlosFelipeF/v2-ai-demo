# Credentials setup (least privilege)

Rule: **never paste a secret into chat.** Each value goes into a file or profile on your Mac
(`.env`, `~/.aws/config`), which Claude reads at run time and never prints.

Do the parts in this order. Parts 1–3 unblock the local build (Phase A). Part 4 is for AWS (Phase B).

---

## 1. Dynatrace (tenant `osg4479h`, sprint)

Open `https://osg4479h.sprint.apps.dynatracelabs.com`.

### 1a. Ingest token (goes to the app and the gateway)
Access Tokens → **Generate new token**, name `v2-ai-demo-ingest`, expiry 30 days.
Scopes, and nothing else: `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`.
→ `.env`: `DT_INGEST_TOKEN=`

### 1b. Read-only platform token (only for `scripts/verify.py`)
Account Management → Identity & access → **Platform tokens** → new, name `v2-ai-demo-verify`, expiry 30 days.
Scopes, and nothing else: `storage:spans:read`, `storage:logs:read`, `storage:events:read`,
`storage:metrics:read`, `storage:buckets:read`.
→ `.env`: `DT_PLATFORM_TOKEN=`

### 1c. RUM web frontend (links the browser click to the backend trace)
Experience Vitals / Web (the new RUM app) → **Add frontend** → name `v2-ai-demo` → manual injection.
- Copy the `<script ...></script>` snippet onto one line → `.env`: `DT_RUM_SNIPPET=`
- Turn on **W3C traceparent / request header propagation** for origins `http://127.0.0.1:8080` now, and the
  API Gateway domain later.
If the tenant UI differs from this, tell me what you see and I'll adapt.

> Optional hygiene: when the bot created this tenant on 2 Jul it posted the local login
> (email + password) in your Slack DM with `pre-prod-sfm bot`. If you still log in with that local
> account, change its password.

---

## 2. Arize AX (free tier)

1. Go to https://app.arize.com and sign up with your Dynatrace email. Accept the terms yourself.
2. Create a **Space** named `v2-ai-demo`. Region: the one closest to you (US is fine; the default OTLP endpoint is `otlp.arize.com`).
3. Space → **Settings → API Keys** → create a **Space API key** (scoped to this space, not a user/org key). Name `v2-ai-demo`.
4. Space ID: Space → Settings (or the URL after `/spaces/`).
→ `.env`: `ARIZE_SPACE_ID=`, `ARIZE_API_KEY=`
5. When the Arize SE is ready to join: Space → Members → invite them to **this space only**.

You do not create the project by hand. It is created on the first trace from the resource attribute
`openinference.project.name=v2-ai-demo`.

---

## 3. AWS for local runs: Bedrock invoke only (`v2-ai-demo-local`)

Local runs only call the Bedrock API. No AWS resources are created, so nothing needs tagging yet.

### 3a. Enable the models (console, once)
Region **ap-southeast-2 (Sydney)** → Amazon Bedrock → Model access → request **Amazon Nova Lite** and
**Anthropic Claude Haiku 4.5**. Anthropic asks for a short use-case form.

### 3b. Create the policy (CloudShell or console)
IAM → Policies → Create policy → JSON → paste `iam/local-bedrock-invoke.json` with `ACCOUNT_ID`
replaced by your 12-digit account ID. Name: `v2-ai-demo-local-bedrock-invoke`.

### 3c. Identity (pick one)
- **IAM Identity Center available (preferred):** create a permission set containing only that policy,
  assign it to yourself, then on your Mac: `aws configure sso --profile v2-ai-demo-local`.
- **No Identity Center:** IAM user `v2-ai-demo-local` with only that policy → create an access key
  (use case: CLI) → on your Mac run `aws configure --profile v2-ai-demo-local` (type the values in your terminal,
  not in chat). Delete the key when we're done.

### 3d. Check
```bash
aws sts get-caller-identity --profile v2-ai-demo-local
aws bedrock list-inference-profiles --region ap-southeast-2 --profile v2-ai-demo-local   # will be denied: expected
```
The second command should be **denied**. That confirms the profile can only invoke models.
Tell me the profile is ready and I'll run a real Bedrock call.

---

## 4. AWS for the deployment (Phase B)

I'll generate the exact JSON for the deployer role, the CloudFormation execution role and the
permissions boundary once I have **your tagging guidelines** (they go into the policy conditions and
`template.yaml`). Nothing is created on AWS before that.
