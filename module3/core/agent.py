"""
Спільне ядро: клієнт API + agent loop.

Цей файл не змінюється від модуля до модуля — змінюється те, ЩО в нього передають.
Окрім щасливого шляху, тут явно обробляються чотири види збоїв:
  api_error · tool_error · turns_exhausted · no_tool_used
"""

import inspect
import json
import time
from anthropic import Anthropic, APIError, APIStatusError
from config import API_KEY, MODEL, MODEL_FAST, MAX_TOKENS, MAX_TURNS

client = Anthropic(api_key=API_KEY)

# У anthropic 1.x параметр temperature прибрали з messages.create(): нові
# моделі ним не керуються. Щоб той самий код працював і на 0.x, і на 1.x,
# зʼясовуємо це один раз і мовчки прибираємо аргумент там, де його не беруть.
_ACCEPTS_TEMPERATURE = "temperature" in inspect.signature(
    client.messages.create).parameters

# накопичувач вартості прогону
USAGE = {"calls": 0, "in": 0, "out": 0, "by_model": {}}


def _track(model, usage):
    USAGE["calls"] += 1
    USAGE["in"] += usage.input_tokens
    USAGE["out"] += usage.output_tokens
    m = USAGE["by_model"].setdefault(model, {"calls": 0, "in": 0, "out": 0})
    m["calls"] += 1
    m["in"] += usage.input_tokens
    m["out"] += usage.output_tokens


def reset_usage():
    USAGE.update({"calls": 0, "in": 0, "out": 0, "by_model": {}})


def _call(**kwargs):
    """Виклик API з ретраями на перевантаження і rate limit."""
    if not _ACCEPTS_TEMPERATURE:
        kwargs.pop("temperature", None)
    for attempt in range(3):
        try:
            resp = client.messages.create(**kwargs)
            _track(kwargs["model"], resp.usage)
            return resp
        except APIStatusError as e:
            if e.status_code in (429, 500, 529) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
        except APIError:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise


def ask(system: str, user: str, max_tokens: int = 400, fast: bool = True,
        temperature: float = 0.0) -> str:
    """Допоміжний виклик без інструментів — роутер, guardrail, judge.
    За замовчуванням дешева модель і temperature=0: класифікація та оцінка
    мають бути детермінованими, інакше судді «хитають» eval-гейт."""
    resp = _call(model=MODEL_FAST if fast else MODEL, max_tokens=max_tokens,
                 temperature=temperature,
                 system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def ask_json(system: str, user: str, fallback: dict, fast: bool = True) -> dict:
    raw = ask(system + "\nПовертай ТІЛЬКИ валідний JSON, без пояснень.", user, fast=fast)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {**fallback, "_raw": raw[:200]}


def run_agent(system: str, tools: list, query: str, on_step=None) -> dict:
    """
    Цикл «міркуй → дій → спостерігай».

    Повертає, окрім відповіді:
      outcome     — ok | turns_exhausted | api_error
      failures    — перелік збоїв інструментів
      no_tool_used — модель відповіла, жодного разу не звернувшись до бекенду
    """
    from domain.backend import dispatch

    messages = [{"role": "user", "content": query}]
    trace, failures = [], []
    started = time.time()

    for turn in range(MAX_TURNS):
        kwargs = dict(model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools

        try:
            resp = _call(**kwargs)
        except Exception as e:                                    # ← збій API
            return {"answer": "Сервіс тимчасово недоступний. Передаю звернення оператору.",
                    "outcome": "api_error", "error": f"{type(e).__name__}: {e}",
                    "trace": trace, "failures": failures, "turns": turn,
                    "elapsed_sec": round(time.time() - started, 2), "usage": {}}

        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if resp.stop_reason != "tool_use":                        # ← фінальна відповідь
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"answer": text.strip(), "outcome": "ok",
                    "trace": trace, "failures": failures, "turns": turn + 1,
                    "no_tool_used": len(trace) == 0,
                    "elapsed_sec": round(time.time() - started, 2),
                    "usage": {"input_tokens": resp.usage.input_tokens,
                              "output_tokens": resp.usage.output_tokens}}

        results = []
        for tu in tool_uses:
            output = dispatch(tu.name, tu.input)
            step = {"turn": turn, "tool": tu.name, "input": tu.input, "output": output}
            if "error" in output:                                 # ← збій інструмента
                step["failed"] = True
                failures.append({"tool": tu.name, "error": output["error"]})
            trace.append(step)
            if on_step:
                on_step(step)
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(output, ensure_ascii=False),
                            "is_error": "error" in output})

        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": results})

    # ← вичерпано ліміт кроків
    return {"answer": "Не вдалося завершити обробку за відведену кількість кроків. "
                      "Передаю звернення оператору.",
            "outcome": "turns_exhausted", "trace": trace, "failures": failures,
            "turns": MAX_TURNS, "elapsed_sec": round(time.time() - started, 2), "usage": {}}
