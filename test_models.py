import base64, json, requests, time, concurrent.futures

with open("/home/power/projects/math-lab/.api_key_b64") as f:
    key = base64.b64decode(f.read().strip()).decode()

MODELS = {
    "barrier_rel": "qwen/qwq-32b",
    "barrier_nat": "deepseek-ai/deepseek-r1-distill-qwen-32b",
    "barrier_alg": "mistralai/mathstral-7b-v0.1",
    "conj_alpha": "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "conj_beta": "mistralai/mistral-large-3-675b-instruct-2512",
    "conj_gamma": "qwen/qwen3.5-397b-a17b",
    "decomposer": "deepseek-ai/deepseek-v3.2",
    "formal_pri": "qwen/qwen3-coder-480b-a35b-instruct",
    "formal_bak": "meta/llama-3.1-405b-instruct",
    "critic_cex": "deepseek-ai/deepseek-v3.1",
    "critic_trv": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "prover_a": "mistralai/devstral-2-123b-instruct-2512",
    "prover_b": "qwen/qwen3.5-122b-a10b",
    "intent": "mistralai/mistral-nemotron",
    "scribe": "mistralai/magistral-small-2506",
}

def test_model(name, model):
    try:
        t0 = time.time()
        resp = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "Say OK"}],
                  "temperature": 0.1, "max_tokens": 10},
            timeout=60
        )
        dt = time.time() - t0
        if resp.status_code == 200:
            data = resp.json()
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content") or msg.get("reasoning_content") or ""
            return name, model, "OK", f"{dt:.1f}s", content[:30]
        else:
            return name, model, "FAIL", f"{resp.status_code}", resp.text[:200]
    except Exception as e:
        return name, model, "ERROR", str(e)[:80], ""

print("Testing all 15 models in parallel...\n")
ok = 0
fail = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
    futures = {ex.submit(test_model, n, m): n for n, m in MODELS.items()}
    for f in concurrent.futures.as_completed(futures, timeout=90):
        r = f.result()
        status = "Y" if r[2] == "OK" else "X"
        if r[2] == "OK":
            ok += 1
        else:
            fail += 1
        print(f"  {status} {r[0]:12s} | {r[1]:50s} | {r[2]:5s} | {r[3]:8s} | {r[4] if len(r)>4 else ''}")

print(f"\n{ok}/15 OK, {fail}/15 FAILED")
