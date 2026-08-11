"""Llamadas a OpenRouter para el backtest con agencia.

- Retry en respuesta vacia (algunos providers la devuelven esporadicamente).
- Tolera fences ```json (Gemini las envuelve aunque se le pida que no).
- Log de costos/latencia por llamada en un CSV junto a la corrida.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.request
from pathlib import Path

PRECIO = {  # $/M tokens (in, out)
    "google/gemini-2.5-pro": (1.25, 10.0),
    "deepseek/deepseek-r1-0528": (0.5, 2.15),
    "openai/gpt-5.6-luna": (0.1, 0.6),
}


class LLM:
    def __init__(self, model: str, log_path: Path, max_tokens: int = 20000):
        self.model, self.log_path, self.max_tokens = model, Path(log_path), max_tokens
        self.gastado = 0.0

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)

    def call(self, prompt: str, tag: str, effort: str | None = None) -> str:
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if effort:
            body["reasoning"] = {"effort": effort}
        t0, ti, to = time.time(), 0, 0
        content = ""
        for intento in range(3):
            d = self._post(body)
            u = d.get("usage", {})
            ti += u.get("prompt_tokens", 0)
            to += u.get("completion_tokens", 0)
            content = d["choices"][0]["message"]["content"] or ""
            if content.strip():
                break
        pi, po = PRECIO.get(self.model, (0, 0))
        costo = ti / 1e6 * pi + to / 1e6 * po
        self.gastado += costo
        nuevo = not self.log_path.exists()
        with open(self.log_path, "a") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["tag", "model", "latency_s", "tok_in", "tok_out", "cost_usd"])
            w.writerow([tag, self.model, f"{time.time()-t0:.1f}", ti, to, f"{costo:.4f}"])
        return content


def parse_json(texto: str) -> dict:
    """JSON del modelo, tolerando fences y texto alrededor."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini == -1 or fin <= ini:
        raise ValueError(f"sin JSON en la respuesta: {texto[:200]!r}")
    return json.loads(texto[ini:fin + 1])
