import json
import re
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.services.context_engine import (
    infer_session_context,
)


OLLAMA_URL = "http://192.168.128.1:11434/api/chat"
OLLAMA_MODEL = "qwen3:4b"


SYSTEM_PROMPT = """
너는 Ambient Agent의 Solution Agent다.

사용자는 현재 작업 중이며,
Ambient Agent가 사용자의 브라우저 활동을 통해
이미 사용자의 목표, 작업, 상태, 문제를 추론했다.

너의 역할은 사용자가 문제를 다시 설명하게 만드는 것이 아니라,
주어진 현재 맥락을 이용해 바로 다음 행동을 제안하는 것이다.

규칙:

1. 사용자가 제공하지 않은 사실을 확정적으로 만들어내지 않는다.
2. 원인을 단정하지 않는다.
3. 현재 blocker를 해결하기 위한 가장 유용한 다음 행동을 제안한다.
4. 일반적인 장황한 설명보다 즉시 실행 가능한 단계를 우선한다.
5. 단계는 최대 4개로 제한한다.
6. 각 단계는 짧고 구체적으로 작성한다.
7. 명령어나 설정값이 필요하면 구체적인 예시를 줄 수 있다.
8. 현재 정보만으로 판단하기 어려운 부분은 "확인" 단계로 표현한다.
9. 한국어로 답한다.
10. 반드시 JSON만 반환한다.

반환 형식:

{
  "title": "짧은 해결 방향",
  "summary": "현재 상황에 대한 짧은 설명",
  "steps": [
    "첫 번째 실행 단계",
    "두 번째 실행 단계",
    "세 번째 실행 단계"
  ]
}
""".strip()


def _normalize_text(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    value = value.strip()

    if not value:
        return None

    return value


def _extract_json_object(
    text: str,
) -> dict[str, Any]:
    """
    Qwen이 markdown fence나 앞뒤 설명을 붙여도
    첫 JSON object를 최대한 안전하게 추출한다.
    """

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

        text = text.strip()

    try:
        parsed = json.loads(
            text
        )

        if isinstance(
            parsed,
            dict,
        ):
            return parsed

    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()

    for index, char in enumerate(
        text
    ):
        if char != "{":
            continue

        try:
            parsed, _ = (
                decoder.raw_decode(
                    text[index:]
                )
            )

            if isinstance(
                parsed,
                dict,
            ):
                return parsed

        except json.JSONDecodeError:
            continue

    raise ValueError(
        "Solution Agent 응답에서 "
        "유효한 JSON object를 찾지 못했습니다."
    )


def _validate_solution(
    result: dict[str, Any],
) -> dict[str, Any]:
    title = _normalize_text(
        result.get(
            "title"
        )
    )

    summary = _normalize_text(
        result.get(
            "summary"
        )
    )

    raw_steps = result.get(
        "steps"
    )

    steps: list[str] = []

    if isinstance(
        raw_steps,
        list,
    ):
        for step in raw_steps:
            normalized = (
                _normalize_text(
                    step
                )
            )

            if (
                normalized
                and normalized
                not in steps
            ):
                steps.append(
                    normalized
                )

    steps = steps[:4]

    if not title:
        raise ValueError(
            "Solution Agent 응답에 "
            "title이 없습니다."
        )

    if not summary:
        raise ValueError(
            "Solution Agent 응답에 "
            "summary가 없습니다."
        )

    if not steps:
        raise ValueError(
            "Solution Agent 응답에 "
            "유효한 steps가 없습니다."
        )

    return {
        "title": title,
        "summary": summary,
        "steps": steps,
    }


def _build_user_prompt(
    context: dict[str, Any],
) -> str:
    evidence = {
        "goal": context.get(
            "goal"
        ),
        "task": context.get(
            "task"
        ),
        "state": context.get(
            "state"
        ),
        "blocker": context.get(
            "blocker"
        ),
        "context_summary": (
            context.get(
                "summary"
            )
        ),
        "context_confidence": (
            context.get(
                "confidence"
            )
        ),
    }

    return (
        "다음은 Ambient Agent가 이미 추론한 "
        "사용자의 현재 작업 맥락이다.\n\n"
        + json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
        )
        + "\n\n"
        "이 맥락을 다시 분석하거나 "
        "사용자에게 문제를 다시 설명하라고 하지 말고, "
        "현재 blocker를 해결하기 위한 "
        "가장 유용한 다음 행동을 제안하라."
    )


def _call_qwen(
    context: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    _build_user_prompt(
                        context
                    )
                ),
            },
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.2,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
        headers={
            "Content-Type": (
                "application/json"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:
            response_body = (
                response.read()
            )

    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Solution Agent가 Ollama에 "
            f"연결하지 못했습니다: {OLLAMA_URL}"
        ) from exc

    except TimeoutError as exc:
        raise RuntimeError(
            "Solution Agent의 Qwen 호출이 "
            "시간 초과되었습니다."
        ) from exc

    try:
        response_json = json.loads(
            response_body.decode(
                "utf-8"
            )
        )

    except json.JSONDecodeError as exc:
        raise ValueError(
            "Ollama 응답이 JSON이 아닙니다."
        ) from exc

    content = (
        response_json
        .get(
            "message",
            {},
        )
        .get(
            "content"
        )
    )

    if not isinstance(
        content,
        str,
    ):
        raise ValueError(
            "Ollama 응답에 message.content가 "
            "없습니다."
        )

    parsed = _extract_json_object(
        content
    )

    return _validate_solution(
        parsed
    )


def generate_solution(
    db: DBSession,
    session_id: int,
) -> dict[str, Any]:
    """
    이미 구축된 Context Engine의 결과를 재사용해
    현재 사용자를 위한 해결책을 생성한다.

    Solution Agent가 raw browser activity를 다시
    해석하지 않는 것이 핵심이다.
    """

    context = infer_session_context(
        db,
        session_id,
    )

    state = context.get(
        "state"
    )

    confidence = float(
        context.get(
            "confidence"
        )
        or 0.0
    )

    goal = _normalize_text(
        context.get(
            "goal"
        )
    )

    task = _normalize_text(
        context.get(
            "task"
        )
    )

    blocker = _normalize_text(
        context.get(
            "blocker"
        )
    )

    if state == "idle":
        raise ValueError(
            "현재 세션이 비활성 상태라 "
            "해결책을 생성하지 않습니다."
        )

    if (
        not goal
        and not task
        and not blocker
    ):
        raise ValueError(
            "현재 작업 맥락이 충분하지 않아 "
            "해결책을 생성할 수 없습니다."
        )

    if confidence < 0.30:
        raise ValueError(
            "현재 작업 맥락의 신뢰도가 너무 낮아 "
            "해결책을 생성하지 않습니다."
        )

    solution = _call_qwen(
        context
    )

    return {
        "session_id": session_id,
        "context": {
            "goal": goal,
            "task": task,
            "state": state,
            "blocker": blocker,
            "confidence": confidence,
        },
        "solution": solution,
    }
