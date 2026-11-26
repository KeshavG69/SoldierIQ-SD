# decide-service

SoldierIQ's own decision model for camera alerts: **d1-omni-600M fine-tuned on colour and presence questions,
int8** (`Keshav069/soldieriq-decide-600m-colour-int8`), served on CPU behind the same `/systemone` API as
OpenRouter's decisions API. Each camera's **Alert watch → Decision model** picks Perplexity (cloud) or this model;
the sensor hub sends that camera's checks here. `MODEL_REPO=Keshav069/d1-omni-600m-int8` serves the untrained base
instead (it can't see colour).

Inference: PyTorch + Hugging Face transformers (Liquid's own model code) + torchao for the int8
weights. One check with 5 questions takes about 1.2 s on an Apple M-series CPU.

## Run locally

```bash
cd decide-service
echo "DECIDE_API_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" > .env
uv run python server.py        # http://127.0.0.1:8095/health -> "ready" after ~10 s
```

The first start downloads the model (~860 MB) from the private HF repo, so you need `hf auth login`
or `HF_TOKEN` in `.env`. Then in `sensor-hub/.env`:

```
DECIDE_URL=http://127.0.0.1:8095
DECIDE_API_KEY=<same key>
```

## Deploy on Railway

1. New service from this repo, root directory `decide-service` (uses `Dockerfile` + `railway.json`).
2. Variables: `DECIDE_API_KEY` (random, long), `HF_TOKEN` (read access to the model repo),
   optionally `TORCH_THREADS` (= the vCPUs you give it).
3. Add a volume mounted at `/data` so the model isn't downloaded again on every restart.
4. Give it at least 2 GB RAM. Expect roughly 1–3 s per check on shared vCPUs.
5. In the sensor hub's variables set `DECIDE_URL=https://<this service's URL>` and the same
   `DECIDE_API_KEY`. Private networking (`http://decide-service.railway.internal:<PORT>`) also works
   if both are in one Railway project.

## API

`POST /api/v1/systemone` with `Authorization: Bearer <DECIDE_API_KEY>`:

```json
{"state": [{"type": "text", "text": "Live security camera frame."},
           {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}],
 "questions": {"vehicle": {"type": "choice", "instructions": "Is a car or truck visible?",
                           "criteria": {"yes": "clearly visible", "no": "not visible"}}}}
```

→ `{"model": "soldieriq/d1-omni-600m-int8", "answers": {"vehicle": {"type": "choice", "choice": "yes",
"probabilities": {"yes": 1.0, "no": 0.0}}}, "latency_ms": 780}`

Yes/no choices are asked as d1 `noul` questions (how it was trained on images); other choice and score
questions pass through. Images must be `data:` URLs. `GET /health` reports `loading` / `ready` /
`failed`.

## How good it is

Colour-trained vs the base model, on photos never used in training (AUROC: 1.0 perfect, 0.5 chance):

- "Is a red car visible?"-style questions: 0.970 (base 0.627). Colour choice: 85% (base 45%).
- Camera alerts on COCO: person 0.986, vehicle 0.920, car/truck 0.989, dog 1.000, bird 1.000, animal 0.933
  (base 0.978 / 0.865 / 0.982 / 1.000 / 0.945 / 0.783).
- Weak: small distant people in wide street views, counting (31%). Full numbers in the model card.

Licence: LFM Open License v1.0 (Liquid AI). Commercial use only for organisations under US$10M
annual revenue; above that a licence from Liquid AI is needed.
