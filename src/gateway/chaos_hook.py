"""Fault injection at the AI gateway, so Dynatrace Intelligence has something to find.

Modes (read every few seconds, no restart needed):
  off      normal
  latency  add CHAOS_LATENCY_S seconds before each LLM call (default 6)
  errors   fail CHAOS_ERROR_RATE of calls with HTTP 503 (default 0.6)

Source of the mode:
  * AWS:   SSM parameter named by CHAOS_SSM_PARAM (e.g. /v2-ai-demo/chaos)
  * local: file named by CHAOS_FILE (default ./.chaos at repo root), content = mode
Calls for the judge model are never disrupted.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from pathlib import Path

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

_CACHE_S = 5.0


class ChaosHook(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self._mode, self._checked = "off", 0.0
        self._ssm_param = os.getenv("CHAOS_SSM_PARAM")
        self._file = Path(os.getenv("CHAOS_FILE", ".chaos"))
        self._ssm = None

    def _read_mode(self) -> str:
        now = time.monotonic()
        if now - self._checked < _CACHE_S:
            return self._mode
        self._checked = now
        try:
            if self._ssm_param:
                if self._ssm is None:
                    import boto3

                    self._ssm = boto3.client("ssm")
                value = self._ssm.get_parameter(Name=self._ssm_param)["Parameter"]["Value"]
            else:
                value = self._file.read_text() if self._file.exists() else "off"
            self._mode = value.strip().lower() or "off"
        except Exception:  # never let chaos plumbing break the gateway
            self._mode = "off"
        return self._mode

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get("model") == "judge-llm":
            return data
        mode = self._read_mode()
        if mode == "latency":
            await asyncio.sleep(float(os.getenv("CHAOS_LATENCY_S", "6")))
        elif mode == "errors" and random.random() < float(os.getenv("CHAOS_ERROR_RATE", "0.6")):
            raise HTTPException(status_code=503, detail="ai-gateway: upstream capacity exceeded (chaos)")
        return data


chaos_instance = ChaosHook()
