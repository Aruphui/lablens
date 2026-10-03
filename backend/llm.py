import os
from huggingface_hub import InferenceClient


def _client() -> InferenceClient:
    base = os.getenv("LLM_BASE_URL")
    if base:  # any OpenAI-compatible server, e.g. Ollama
        return InferenceClient(base_url=base, api_key=os.getenv("LLM_API_KEY", "none"))
    return InferenceClient(token=os.getenv("HF_TOKEN"))


def chat(system: str, user: str, max_tokens: int = 1200, temperature: float = 0.1) -> str:
    model = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    resp = _client().chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""
