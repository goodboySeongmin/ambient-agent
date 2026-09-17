from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from typing import Any

import httpx

from app.services.context_selector import build_context_selection


# =========================================================
# Ollama
# =========================================================

OLLAMA_URL = "http://192.168.128.1:11434/api/chat"
OLLAMA_MODEL = "qwen3:4b"


# =========================================================
# Context states
# =========================================================

ALLOWED_STATES = {
    "researching",
    "reading",
    "comparing",
    "debugging",
    "deciding",
    "implementing",
    "unknown",
}


NULL_LIKE_VALUES = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "unknown",
    "없음",
    "없다",
    "해당 없음",
}


# =========================================================
# Cache
# =========================================================

_CONTEXT_CACHE: dict[
    tuple[int, str],
    dict[str, Any],
] = {}

_CONTEXT_CACHE_LOCK = threading.Lock()

# Qwen inference single-flight.
# 여러 API 요청이 동시에 같은 snapshot을 요구해도
# 실제 Qwen 추론은 한 번에 하나만 수행한다.
_CONTEXT_INFERENCE_LOCK = threading.Lock()


def _make_cache_key(
    session_id: int,
    compressed_evidence: dict[str, Any],
) -> tuple[int, str]:
    """
    Raw event timestamp가 아니라 실제 Qwen 입력 evidence를
    fingerprint하여 semantic context cache key로 사용한다.
    """

    canonical_evidence = json.dumps(
        compressed_evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    evidence_fingerprint = hashlib.sha256(
        canonical_evidence.encode("utf-8")
    ).hexdigest()

    return (
        session_id,
        evidence_fingerprint,
    )


def _get_cached_context(
    cache_key: tuple[int, str],
) -> dict[str, Any] | None:
    with _CONTEXT_CACHE_LOCK:
        cached = _CONTEXT_CACHE.get(cache_key)

        if cached is None:
            return None

        return dict(cached)


def _set_cached_context(
    cache_key: tuple[int, str],
    context: dict[str, Any],
) -> None:
    with _CONTEXT_CACHE_LOCK:
        if len(_CONTEXT_CACHE) > 100:
            _CONTEXT_CACHE.clear()

        _CONTEXT_CACHE[cache_key] = dict(context)


# =========================================================
# Meta output guard
# =========================================================

META_CONTEXT_PATTERNS = (
    "analyze the user",
    "analyze user",
    "analyze the provided",
    "analyze the json",
    "provided json",
    "provided data",
    "identify the root cause",
    "determine the root cause",
    "provide actionable",
    "provide recommendations",
    "provide a solution",
    "step-by-step solution",
    "intervention",
    "stuck signal",
    "stuck score",
    "사용자의 활동을 분석",
    "사용자 활동을 분석",
    "사용자의 맥락을 분석",
    "근본 원인을 식별",
    "원인을 분석하여",
    "해결 방법을 제공",
    "해결책을 제공",
    "권장 사항을 제공",
)


# =========================================================
# Prompt
# =========================================================

SYSTEM_PROMPT = """
당신은 최근 브라우저 활동으로 사용자의 현재 작업 맥락을 추론하는 엔진입니다.

반드시 JSON 객체 하나만 반환하세요.

{
  "goal": null,
  "task": null,
  "state": "unknown",
  "blocker": null,
  "confidence": 0.0
}

필드:

goal:
사용자가 현재 달성하려는 목적

task:
사용자가 지금 수행하는 구체적인 작업

state:
researching
reading
comparing
debugging
deciding
implementing
unknown
중 하나

blocker:
evidence에서 직접 확인되는 문제.
명확한 문제가 없으면 null.

confidence:
현재 goal/task 추론의 확신도. 0.0 ~ 1.0.


핵심 판단 규칙:

1. current_search를 가장 중요하게 봅니다.

2. recent_searches와 search_related_titles가
current_search와 같은 주제를 반복해서 가리키면
그 공통 주제로 goal과 task를 추론합니다.

3. blocker가 없어도 goal과 task는 추론할 수 있습니다.

4. 오류 해결 활동이 명확하면 debugging,
정보나 설정 방법을 찾는 활동이면 researching으로 판단합니다.

5. unknown은 evidence가 부족하거나
서로 관련 없는 여러 주제가 섞여 현재 작업을 판단할 수 없을 때만 사용합니다.

6. 기술 검색어로부터 직접 알 수 있는 범위의 추론은 허용합니다.
evidence에 없는 구체적인 원인만 만들어내지 마세요.

7. goal과 task는 가능한 경우 한국어로 작성합니다.
기술 용어와 실제 오류 메시지는 영어 그대로 사용할 수 있습니다.


예시 1

EVIDENCE:
{
  "current_search": "fastapi allow origins localhost react",
  "recent_searches": [
    "fastapi cors 설정",
    "react cors error localhost api",
    "react fetch blocked by cors fastapi"
  ],
  "search_related_titles": [
    "CORS - FastAPI",
    "Sending request from React to FastAPI causes origin localhost:5173 has been blocked by CORS policy error"
  ]
}

OUTPUT:
{
  "goal": "React와 FastAPI 간 CORS 오류 해결",
  "task": "FastAPI의 CORS 설정 방법을 조사하고 있음",
  "state": "debugging",
  "blocker": "React 요청이 CORS policy에 의해 차단되는 오류",
  "confidence": 0.95
}


예시 2

EVIDENCE:
{
  "current_search": "best python web framework",
  "recent_searches": [
    "fastapi vs flask",
    "django vs fastapi"
  ],
  "search_related_titles": [
    "FastAPI vs Flask",
    "Django vs FastAPI"
  ]
}

OUTPUT:
{
  "goal": "Python 웹 프레임워크 선택",
  "task": "여러 Python 웹 프레임워크를 비교하고 있음",
  "state": "comparing",
  "blocker": null,
  "confidence": 0.9
}

JSON 이외의 텍스트는 출력하지 마세요.
""".strip()


CONTEXT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {
            "type": ["string", "null"],
        },
        "task": {
            "type": ["string", "null"],
        },
        "state": {
            "type": "string",
            "enum": [
                "researching",
                "reading",
                "comparing",
                "debugging",
                "deciding",
                "implementing",
                "unknown",
            ],
        },
        "blocker": {
            "type": ["string", "null"],
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
    "required": [
        "goal",
        "task",
        "state",
        "blocker",
        "confidence",
    ],
    "additionalProperties": False,
}


# =========================================================
# Basic helpers
# =========================================================

def _normalize_nullable_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    if text.lower() in NULL_LIKE_VALUES:
        return None

    return text


def _contains_korean(
    value: str | None,
) -> bool:
    if not value:
        return True

    return bool(
        re.search(
            r"[가-힣]",
            value,
        )
    )


def _contains_meta_context(
    value: str | None,
) -> bool:
    if not value:
        return False

    normalized = str(value).strip().lower()

    return any(
        pattern in normalized
        for pattern in META_CONTEXT_PATTERNS
    )


def _normalize_query(
    query: str,
) -> str:
    return " ".join(
        query.lower().strip().split()
    )


def _dedupe_preserve_order(
    values: list[str],
    limit: int,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        if not value:
            continue

        cleaned = str(value).strip()

        if not cleaned:
            continue

        key = cleaned.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

        if len(result) >= limit:
            break

    return result


# =========================================================
# Robust evidence parsing
# =========================================================

def _extract_query_from_value(
    value: Any,
) -> str | None:
    """
    search evidence가 다음 중 어떤 형태여도 처리한다.

    "postgresql connection refused"

    또는

    {
        "timestamp": "...",
        "query": "postgresql connection refused",
        "domain": "www.google.com"
    }

    또는

    {
        "search_query": "postgresql connection refused"
    }
    """

    if value is None:
        return None

    if isinstance(value, str):
        cleaned = value.strip()

        if not cleaned:
            return None

        return cleaned

    if isinstance(value, dict):
        for key in (
            "query",
            "search_query",
        ):
            candidate = value.get(key)

            if candidate:
                candidate = str(candidate).strip()

                if candidate:
                    return candidate

    return None


def _collect_queries_recursive(
    value: Any,
    output: list[str],
) -> None:
    """
    active/recent context 구조가 조금 달라져도
    query/search_query 값을 안전하게 찾는다.
    """

    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "query",
                "search_query",
            }:
                query = _extract_query_from_value(
                    {
                        key: item,
                    }
                )

                if query:
                    output.append(query)

            elif isinstance(
                item,
                (
                    dict,
                    list,
                    tuple,
                ),
            ):
                _collect_queries_recursive(
                    item,
                    output,
                )

    elif isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        for item in value:
            if isinstance(item, str):
                # 문자열 리스트가 실제 search evidence인 경우는
                # 별도 extractor에서 처리한다.
                continue

            _collect_queries_recursive(
                item,
                output,
            )


def _collect_titles_recursive(
    value: Any,
    output: list[str],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "title":
                if item:
                    title = str(item).strip()

                    if title:
                        output.append(title)

            elif isinstance(
                item,
                (
                    dict,
                    list,
                    tuple,
                ),
            ):
                _collect_titles_recursive(
                    item,
                    output,
                )

    elif isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        for item in value:
            _collect_titles_recursive(
                item,
                output,
            )


# =========================================================
# Search extraction
# =========================================================

def _extract_recent_searches(
    temporal_context: dict[str, Any],
) -> list[str]:
    active = temporal_context.get(
        "active_context",
        {},
    )

    recent = temporal_context.get(
        "recent_context",
        {},
    )

    queries: list[str] = []

    # -----------------------------------------------------
    # Active activities
    # -----------------------------------------------------

    for item in active.get(
        "recent_activities",
        [],
    ):
        query = _extract_query_from_value(
            item
        )

        if query:
            queries.append(query)

    # -----------------------------------------------------
    # Active recent_searches
    # -----------------------------------------------------

    for item in active.get(
        "recent_searches",
        [],
    ):
        query = _extract_query_from_value(
            item
        )

        if query:
            queries.append(query)

    # -----------------------------------------------------
    # Recent search_evidence
    # -----------------------------------------------------

    search_evidence = recent.get(
        "search_evidence",
        {},
    )

    for item in search_evidence.get(
        "searches",
        [],
    ):
        query = _extract_query_from_value(
            item
        )

        if query:
            queries.append(query)

    # -----------------------------------------------------
    # Recent activities
    # -----------------------------------------------------

    for item in recent.get(
        "activities",
        [],
    ):
        query = _extract_query_from_value(
            item
        )

        if query:
            queries.append(query)

    # -----------------------------------------------------
    # 구조가 바뀐 경우 fallback recursive search
    # -----------------------------------------------------

    recursive_queries: list[str] = []

    _collect_queries_recursive(
        active,
        recursive_queries,
    )

    _collect_queries_recursive(
        recent,
        recursive_queries,
    )

    queries.extend(
        recursive_queries
    )

    # 최신 evidence가 앞에 오는 구조를 유지
    return _dedupe_preserve_order(
        queries,
        limit=10,
    )


def _extract_all_recent_queries_with_duplicates(
    temporal_context: dict[str, Any],
) -> list[str]:
    active = temporal_context.get(
        "active_context",
        {},
    )

    recent = temporal_context.get(
        "recent_context",
        {},
    )

    queries: list[str] = []

    for container in (
        active.get(
            "recent_activities",
            [],
        ),
        recent.get(
            "activities",
            [],
        ),
    ):
        for item in container:
            query = _extract_query_from_value(
                item
            )

            if query:
                queries.append(query)

    search_evidence = recent.get(
        "search_evidence",
        {},
    )

    for item in search_evidence.get(
        "searches",
        [],
    ):
        query = _extract_query_from_value(
            item
        )

        if query:
            queries.append(query)

    return queries


def _extract_repeated_searches(
    temporal_context: dict[str, Any],
) -> list[str]:
    queries = (
        _extract_all_recent_queries_with_duplicates(
            temporal_context
        )
    )

    if not queries:
        return []

    normalized_to_original: dict[
        str,
        str,
    ] = {}

    normalized_queries: list[str] = []

    for query in queries:
        normalized = _normalize_query(
            query
        )

        if not normalized:
            continue

        normalized_to_original.setdefault(
            normalized,
            query,
        )

        normalized_queries.append(
            normalized
        )

    counter = Counter(
        normalized_queries
    )

    repeated: list[str] = []

    for normalized, count in counter.most_common():
        if count < 2:
            continue

        repeated.append(
            normalized_to_original[
                normalized
            ]
        )

        if len(repeated) >= 5:
            break

    return repeated


# =========================================================
# Search related titles
# =========================================================

def _extract_search_related_titles(
    temporal_context: dict[str, Any],
    recent_searches: list[str],
) -> list[str]:
    """
    모든 YouTube/ChatGPT 제목을 전달하지 않는다.

    최근 검색어와 단어가 겹치는 title만 Qwen에게 넘긴다.
    """

    if not recent_searches:
        return []

    active = temporal_context.get(
        "active_context",
        {},
    )

    recent = temporal_context.get(
        "recent_context",
        {},
    )

    titles: list[str] = []

    _collect_titles_recursive(
        active,
        titles,
    )

    _collect_titles_recursive(
        recent,
        titles,
    )

    search_tokens: set[str] = set()

    for query in recent_searches:
        for token in re.findall(
            r"[a-zA-Z0-9가-힣]+",
            query.lower(),
        ):
            if len(token) >= 3:
                search_tokens.add(token)

    relevant_titles: list[str] = []

    for title in titles:
        title_lower = title.lower()

        overlap = sum(
            1
            for token in search_tokens
            if token in title_lower
        )

        if overlap >= 1:
            relevant_titles.append(
                title
            )

    return _dedupe_preserve_order(
        relevant_titles,
        limit=5,
    )


# =========================================================
# Current search
# =========================================================

def _extract_current_search(
    temporal_context: dict[str, Any],
    recent_searches: list[str],
) -> str | None:
    """
    현재 page가 NAVER/Google 메인처럼 의미가 없더라도
    가장 최근 검색 evidence를 current_search로 사용한다.
    """

    active = temporal_context.get(
        "active_context",
        {},
    )

    current_activity = active.get(
        "current_activity"
    )

    if isinstance(
        current_activity,
        dict,
    ):
        query = _extract_query_from_value(
            current_activity
        )

        if query:
            return query

    if recent_searches:
        return recent_searches[0]

    return None


# =========================================================
# Evidence compressor v3.1
# =========================================================

def compress_context_evidence(
    temporal_context: dict[str, Any],
) -> dict[str, Any]:
    recent_searches = (
        _extract_recent_searches(
            temporal_context
        )
    )

    repeated_searches = (
        _extract_repeated_searches(
            temporal_context
        )
    )

    current_search = (
        _extract_current_search(
            temporal_context,
            recent_searches,
        )
    )

    related_titles = (
        _extract_search_related_titles(
            temporal_context,
            recent_searches,
        )
    )

    return {
        "current_search": (
            current_search
        ),

        "recent_searches": (
            recent_searches
        ),

        "repeated_searches": (
            repeated_searches
        ),

        "search_related_titles": (
            related_titles
        ),
    }


# =========================================================
# JSON parser
# =========================================================

def extract_json_object(
    text: str,
) -> dict[str, Any]:
    """
    Qwen 응답에서 최종 JSON 객체를 안전하게 추출한다.

    no-format generation에서는 reasoning text나
    <think>...</think>가 content에 포함될 수 있으므로
    마지막의 유효한 JSON 객체를 우선 사용한다.
    """

    text = text.strip()

    # -----------------------------------------------------
    # 1. 응답 전체가 JSON인 경우
    # -----------------------------------------------------

    try:
        result = json.loads(text)

        if not isinstance(result, dict):
            raise ValueError(
                "Qwen 응답 JSON이 객체가 아닙니다."
            )

        return result

    except json.JSONDecodeError:
        pass

    # -----------------------------------------------------
    # 2. think block 제거
    # -----------------------------------------------------

    cleaned = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()

    try:
        result = json.loads(cleaned)

        if not isinstance(result, dict):
            raise ValueError(
                "Qwen 응답 JSON이 객체가 아닙니다."
            )

        return result

    except json.JSONDecodeError:
        pass

    # -----------------------------------------------------
    # 3. JSONDecoder로 모든 객체 후보 탐색
    # -----------------------------------------------------

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []

    for index, char in enumerate(cleaned):
        if char != "{":
            continue

        try:
            candidate, _ = decoder.raw_decode(
                cleaned[index:]
            )
        except json.JSONDecodeError:
            continue

        if isinstance(candidate, dict):
            candidates.append(candidate)

    if not candidates:
        raise ValueError(
            "Qwen 응답에서 유효한 JSON 객체를 찾을 수 없습니다."
        )

    # 모델이 설명 뒤 마지막에 최종 답을 쓰는 패턴이므로
    # 마지막 유효 JSON 객체를 사용한다.
    return candidates[-1]


# =========================================================
# Result validation
# =========================================================

def validate_context_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    required = {
        "goal",
        "task",
        "state",
        "blocker",
        "confidence",
    }

    missing = (
        required
        - set(
            result.keys()
        )
    )

    if missing:
        raise ValueError(
            "Context 응답에 필수 필드가 없습니다: "
            + ", ".join(
                sorted(missing)
            )
        )

    goal = _normalize_nullable_text(
        result.get("goal")
    )

    task = _normalize_nullable_text(
        result.get("task")
    )

    blocker = _normalize_nullable_text(
        result.get("blocker")
    )

    state = str(
        result.get(
            "state",
            "unknown",
        )
    ).strip().lower()

    if state not in ALLOWED_STATES:
        state = "unknown"

    try:
        confidence = float(
            result.get(
                "confidence",
                0.0,
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        confidence = 0.0

    confidence = max(
        0.0,
        min(
            1.0,
            confidence,
        ),
    )

    # -----------------------------------------------------
    # Meta task 제거
    # -----------------------------------------------------

    if _contains_meta_context(
        goal
    ):
        goal = None

    if _contains_meta_context(
        task
    ):
        task = None

    if _contains_meta_context(
        blocker
    ):
        blocker = None

    # -----------------------------------------------------
    # Descriptive output language guard
    # -----------------------------------------------------
    #
    # goal/task는 사용자에게 보여주는 설명이므로
    # 한국어 출력을 기대한다.
    #
    # blocker는 실제 오류 메시지나 기술 문구일 수 있으므로
    # 영어-only 문자열도 정상 evidence로 허용한다.
    #
    # 한 필드의 언어 문제 때문에 전체 context를
    # 폐기하지 않는다.
    # -----------------------------------------------------

    if (
        goal
        and not _contains_korean(
            goal
        )
    ):
        goal = None

    if (
        task
        and not _contains_korean(
            task
        )
    ):
        task = None

    # blocker는 다음과 같은 실제 기술 오류를
    # 그대로 보존할 수 있다.
    #
    # "origin http://localhost:5173 has been blocked by CORS policy"
    # "ECONNREFUSED"
    # "ModuleNotFoundError"
    #
    # 따라서 한국어 포함 여부를 검증하지 않는다.

    # -----------------------------------------------------
    # Goal/task 둘 다 없으면 fail closed
    # -----------------------------------------------------

    if (
        goal is None
        and task is None
    ):
        state = "unknown"

        confidence = min(
            confidence,
            0.2,
        )

    return {
        "goal": goal,
        "task": task,
        "state": state,
        "blocker": blocker,
        "confidence": round(
            confidence,
            4,
        ),
    }


# =========================================================
# Deterministic summary
# =========================================================

def build_summary(
    context: dict[str, Any],
) -> str:
    goal = context.get("goal")
    task = context.get("task")
    blocker = context.get("blocker")
    state = context.get("state", "unknown")

    if (
        state == "unknown"
        and not goal
        and not task
    ):
        return (
            "현재 활동만으로는 명확한 작업 맥락을 "
            "판단하기 어렵습니다."
        )

    if task:
        task_clean = (
            task
            .replace("하고 있음", "하고 있습니다")
            .replace("중임", "중입니다")
            .rstrip(".")
        )

        if blocker:
            return (
                f"{task_clean}. "
                f"확인된 문제는 {blocker}입니다."
            )

        return f"{task_clean}."

    if goal:
        return (
            f"현재 {goal}와 관련된 활동을 진행하고 있습니다."
        )

    return "현재 작업 맥락을 일부만 확인할 수 있습니다."


# =========================================================
# Idle
# =========================================================

def _build_idle_context() -> dict[str, Any]:
    return {
        "goal": None,
        "task": None,
        "state": "idle",
        "blocker": None,
        "confidence": 1.0,
        "summary": (
            "최근 활동이 없어 현재 사용자는 "
            "비활성 상태입니다."
        ),
    }


# =========================================================
# Qwen call
# =========================================================

def _call_qwen(
    compressed_evidence: dict[str, Any],
) -> dict[str, Any]:
    user_prompt = (
        "아래 최근 검색 evidence만 사용해서 "
        "사용자의 현재 작업 맥락을 추출하세요.\n\n"
        "특히 repeated_searches와 recent_searches를 "
        "가장 중요하게 보세요.\n\n"
        "goal, task, blocker는 한국어로 작성하세요.\n"
        "state만 영어 enum으로 작성하세요.\n"
        "원인을 추측하지 마세요.\n"
        "해결책을 작성하지 마세요.\n"
        "JSON 객체 하나만 반환하세요.\n\n"
        "EVIDENCE:\n"
        + json.dumps(
            compressed_evidence,
            ensure_ascii=False,
            indent=2,
        )
    )

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,

        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],

        "options": {
            "temperature": 0.0,
            "num_predict": 2048,
        },
    }

    try:
        with httpx.Client(
            timeout=120.0,
        ) as client:
            response = client.post(
                OLLAMA_URL,
                json=payload,
            )

            response.raise_for_status()

    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Ollama 서버 연결 실패: {OLLAMA_URL}"
        ) from exc

    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "Ollama 응답 시간이 초과되었습니다."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Ollama API 오류: "
            f"{exc.response.status_code} "
            f"{exc.response.text}"
        ) from exc

    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Ollama API 호출 실패: {exc}"
        ) from exc

    try:
        data = response.json()

    except ValueError as exc:
        raise ValueError(
            "Ollama 응답 JSON 파싱 실패"
        ) from exc

    content = (
        data.get(
            "message",
            {},
        )
        .get(
            "content",
            "",
        )
        .strip()
    )

    if not content:
        raise ValueError(
            "Ollama message.content가 비어 있습니다."
        )

    print(
        "\n"
        + "=" * 80
    )

    print(
        "[QWEN COMPRESSED EVIDENCE V3.1]"
    )

    print(
        json.dumps(
            compressed_evidence,
            ensure_ascii=False,
            indent=2,
        )
    )

    print(
        "-" * 80
    )

    print(
        "[QWEN RAW CONTEXT]"
    )

    print(
        content
    )

    print(
        "=" * 80
        + "\n"
    )

    return extract_json_object(
        content
    )


# =========================================================
# Public API
# =========================================================

def infer_session_context(
    db,
    session_id: int,
) -> dict[str, Any]:
    temporal_context = (
        build_context_selection(
            db,
            session_id,
        )
    )

    # -----------------------------------------------------
    # 1. Deterministic idle
    # -----------------------------------------------------

    if temporal_context.get(
        "is_idle",
        False,
    ):
        return _build_idle_context()

    # -----------------------------------------------------
    # 2. Evidence compression
    # -----------------------------------------------------

    compressed_evidence = (
        compress_context_evidence(
            temporal_context
        )
    )

    # -----------------------------------------------------
    # 3. Semantic evidence cache
    # -----------------------------------------------------

    cache_key = _make_cache_key(
        session_id,
        compressed_evidence,
    )

    cached = _get_cached_context(
        cache_key
    )

    if cached is not None:
        print(
            "[CONTEXT EVIDENCE CACHE HIT] "
            f"session={session_id} "
            f"fingerprint={cache_key[1][:12]}"
        )

        return cached

    # 검색 증거조차 없다면 Qwen 호출 불필요
    has_semantic_evidence = any(
        [
            compressed_evidence.get(
                "current_search"
            ),
            compressed_evidence.get(
                "recent_searches"
            ),
            compressed_evidence.get(
                "search_related_titles"
            ),
        ]
    )

    if not has_semantic_evidence:
        final_context = {
            "goal": None,
            "task": None,
            "state": "unknown",
            "blocker": None,
            "confidence": 0.0,
            "summary": (
                "현재 활동만으로는 명확한 작업 맥락을 "
                "판단하기 어렵습니다."
            ),
        }

        _set_cached_context(
            cache_key,
            final_context,
        )

        return final_context

    # -----------------------------------------------------
    # 4. Qwen single-flight inference
    # -----------------------------------------------------

    with _CONTEXT_INFERENCE_LOCK:

        # lock을 기다리는 동안 다른 요청이 동일 snapshot의
        # 추론을 완료했을 수 있으므로 cache를 다시 확인한다.
        cached = _get_cached_context(
            cache_key
        )

        if cached is not None:
            print(
                "[CONTEXT CACHE HIT AFTER WAIT] "
                f"session={session_id} "
                f"fingerprint={cache_key[1][:12]}"
            )

            return cached

        print(
            "[CONTEXT QWEN START] "
            f"session={session_id} "
            f"fingerprint={cache_key[1][:12]}"
        )

        raw_result = _call_qwen(
            compressed_evidence
        )

        validated = (
            validate_context_result(
                raw_result
            )
        )

        # -------------------------------------------------
        # 5. Deterministic summary
        # -------------------------------------------------

        final_context = {
            **validated,
            "summary": build_summary(
                validated
            ),
        }

        # -------------------------------------------------
        # 6. Cache
        # -------------------------------------------------

        _set_cached_context(
            cache_key,
            final_context,
        )

        print(
            "[CONTEXT QWEN COMPLETE] "
            f"session={session_id} "
            f"fingerprint={cache_key[1][:12]}"
        )

        return final_context
