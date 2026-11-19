import asyncio
import re

import httpx

from app.config import get_settings


class LLMNotConfigured(Exception):
    pass


class LLMError(Exception):
    pass


async def complete(messages: list[dict], temperature: float | None = None) -> str:
    s = get_settings()
    if not s.llm_base_url:
        raise LLMNotConfigured("私有化模型未配置（LLM_BASE_URL 为空）")
    body = {
        "model": s.llm_model,
        "messages": messages,
        "temperature": s.llm_temperature if temperature is None else temperature,
        "max_tokens": max(1, s.llm_max_tokens),
    }
    if not s.llm_enable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    attempts = 0
    while True:
        attempts += 1
        try:
            async with httpx.AsyncClient(timeout=s.llm_timeout) as client:
                resp = await client.post(
                    s.llm_base_url.rstrip("/") + "/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {s.llm_api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
            break
        except httpx.TransportError as e:
            if attempts == 1 and not isinstance(e, httpx.TimeoutException):
                await asyncio.sleep(2)
                continue
            raise LLMError(
                f"LLM 请求失败: {type(e).__name__}（{s.llm_timeout}s 超时上限，已试 {attempts} 次）"
            ) from e
    try:
        choice = data["choices"][0]
        content = choice["message"].get("content")
        finish = choice.get("finish_reason")
    except (KeyError, IndexError, AttributeError, TypeError) as e:
        raise LLMError(f"模型响应格式异常: {e}") from e
    if not (content or "").strip():
        used = (data.get("usage") or {}).get("completion_tokens")
        if finish == "length":
            why = (
                f"思考未结束即被截断（已生成 {used} tokens，达 LLM_MAX_TOKENS={s.llm_max_tokens} 上限），"
                "请调大 LLM_MAX_TOKENS 或设 LLM_ENABLE_THINKING=false"
            )
        else:
            why = f"模型未给出正文（finish_reason={finish}，已生成 {used} tokens），请检查模板或思考开关配置"
        raise LLMError(f"模型未输出正文：{why}")
    return content


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.+?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip().rstrip(";").strip()
    if not sql:
        raise LLMError("未能从模型输出中提取 SQL")
    return sql

