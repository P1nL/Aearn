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
    if lowered.endswith("/v1/chat/completions"):
        normalized = normalized[: -len("/v1/chat/completions")]
    elif lowered.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    elif lowered.endswith("/v1"):
        normalized = normalized[: -len("/v1")]
    return normalized.rstrip("/")


def deepseek_chat_completions_url(base_url: str) -> str:
    return f"{normalize_deepseek_base_url(base_url)}/chat/completions"
