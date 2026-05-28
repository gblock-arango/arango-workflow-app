"""LangChain chat model compatible with Databricks ``/serving-endpoints`` OpenAI API."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models import base as openai_chat_base


class DatabricksServingChatOpenAI(ChatOpenAI):
    """
    Databricks foundation-model chat rejects ``max_completion_tokens`` (OpenAI o-series field).

    Recent ``langchain_openai.ChatOpenAI`` rewrites ``max_tokens`` → ``max_completion_tokens``;
    this subclass keeps the chat-completions payload Databricks accepts.
    """

    @property
    def _default_params(self) -> dict[str, Any]:
        return openai_chat_base.BaseChatOpenAI._default_params.__get__(self, type(self))

    def _get_invocation_params(
        self,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        params = super()._get_invocation_params(stop=stop, **kwargs)
        if "max_completion_tokens" in params:
            if params.get("max_tokens") is None and params["max_completion_tokens"] is not None:
                params["max_tokens"] = params.pop("max_completion_tokens")
            else:
                params.pop("max_completion_tokens", None)
        return params

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = openai_chat_base.BaseChatOpenAI._get_request_payload(
            self, input_, stop=stop, **kwargs
        )
        if "max_completion_tokens" in payload:
            if payload.get("max_tokens") is None and payload["max_completion_tokens"] is not None:
                payload["max_tokens"] = payload.pop("max_completion_tokens")
            else:
                payload.pop("max_completion_tokens", None)
        return payload
