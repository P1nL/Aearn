def responses_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1/responses") or normalized.endswith("/responses"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/responses"
    return f"{normalized}/v1/responses"


def normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1/responses"):
        return normalized[: -len("/responses")]
    if normalized.endswith("/responses"):
        return normalized[: -len("/responses")]
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def normalize_deepseek_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    lowered = normalized.lower()
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1/responses", "/responses", "/v1"):
        if lowered.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized.rstrip("/")


def deepseek_chat_completions_url(base_url: str) -> str:
    return f"{normalize_deepseek_base_url(base_url)}/chat/completions"


def deepseek_responses_url(base_url: str) -> str:
    """Return the documented DeepSeek Responses endpoint without an OpenAI `/v1` suffix."""

    return f"{normalize_deepseek_base_url(base_url)}/responses"
