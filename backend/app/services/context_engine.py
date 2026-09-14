from __future__ import annotations

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
    tuple[int, str | None],
    dict[str, Any],
] = {}

_CONTEXT_CACHE_LOCK = threading.Lock()


def _make_cache_key(
    session_id: int,
    temporal_context: dict[str, Any],
) -> tuple[int, str | None]:
    return (
        session_id,
        temporal_context.get("last_activity_timestamp"),
    )


def _get_cached_context(
    cache_key: tuple[int, str | None],
) -> dict[str, Any] | None:
    with _CONTEXT_CACHE_LOCK:
        cached = _CONTEXT_CACHE.get(cache_key)

        if cached is None:
            return None

        return dict(cached)


def _set_cached_context(
    cache_key: tuple[int, str | None],
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
당신은 사용자의 최근 브라우저 검색 활동에서
현재 작업 맥락을 추출하는 엔진입니다.

입력 데이터는 이미 필요한 정보만 압축되어 있습니다.

반드시 아래 JSON 구조만 반환하세요.

{
  "goal": null,
  "task": null,
  "state": "unknown",
  "blocker": null,
  "confidence": 0.0
}

필드 의미:

goal:
사용자가 궁극적으로 해결하거나 달성하려는 것

task:
사용자가 현재 실제로 하고 있는 행동

state:
아래 중 하나

researching
reading
comparing
debugging
deciding
implementing
unknown

blocker:
최근 검색이나 제목에서 직접 확인되는 구체적인 문제

confidence:
0.0 ~ 1.0


==================================================
언어 규칙
==================================================

goal은 한국어로 작성합니다.
task는 한국어로 작성합니다.
blocker는 한국어로 작성합니다.

기술 용어는 영어 그대로 사용할 수 있습니다.

예:

PostgreSQL
SQLAlchemy
FastAPI
connection refused

state만 영어 enum을 사용합니다.


==================================================
중요 규칙
==================================================

입력 데이터를 분석하는 당신 자신의 임무를
사용자의 goal이나 task로 작성하지 마세요.

잘못된 예:

"입력 데이터를 분석하여 원인을 찾기"

"Analyze the provided data"

"Identify the root cause"

"사용자의 상태를 분석하기"


사용자가 실제로 하고 있는 일을 작성하세요.

예:

최근 검색어:

postgresql connection refused
fastapi postgresql connection refused
sqlalchemy postgresql connection refused

좋은 출력:

{
  "goal": "PostgreSQL 연결 오류 해결",
  "task": "PostgreSQL connection refused 오류를 조사하고 있음",
  "state": "debugging",
  "blocker": "PostgreSQL connection refused 오류",
  "confidence": 0.95
}


==================================================
debugging 규칙
==================================================

최근 검색어에 다음과 같은 명시적 오류가 반복되면
debugging으로 판단할 수 있습니다.

error
exception
failed
failure
connection refused
not working
timeout
cannot connect
오류
에러
실패


==================================================
blocker 규칙
==================================================

blocker에는 관찰된 문제만 작성하세요.

예:

"PostgreSQL connection refused 오류"

근본 원인은 추측하지 마세요.

다음은 입력에 직접 나타나지 않으면 작성하면 안 됩니다.

"PostgreSQL 서버가 꺼져 있음"

"포트가 잘못됨"

"방화벽 문제"

"네트워크 문제"


==================================================
금지
==================================================

해결 방법을 제시하지 마세요.
추천하지 마세요.
근본 원인을 추측하지 마세요.
stuck 여부를 판단하지 마세요.
intervention을 언급하지 마세요.

JSON 객체 하나만 반환하세요.
Markdown을 출력하지 마세요.
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
    text = text.strip()

    try:
        result = json.loads(text)

        if not isinstance(
            result,
            dict,
        ):
            raise ValueError(
                "Qwen 응답 JSON이 객체가 아닙니다."
            )

        return result

    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        text,
        re.DOTALL,
    )

    if not match:
        raise ValueError(
            "Qwen 응답에서 JSON 객체를 찾을 수 없습니다."
        )

    try:
        result = json.loads(
            match.group(0)
        )

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Qwen 응답 JSON 파싱 실패: {exc}"
        ) from exc

    if not isinstance(
        result,
        dict,
    ):
        raise ValueError(
            "Qwen 응답 JSON이 객체가 아닙니다."
        )

    return result


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
    # 한국어 descriptive output 검증
    # -----------------------------------------------------

    language_invalid = False

    for value in (
        goal,
        task,
        blocker,
    ):
        if (
            value
            and not _contains_korean(
                value
            )
        ):
            language_invalid = True

    if language_invalid:
        goal = None
        task = None
        blocker = None
        state = "unknown"
        confidence = 0.0

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
        "format": CONTEXT_JSON_SCHEMA,

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
    # 2. Snapshot cache
    # -----------------------------------------------------

    cache_key = _make_cache_key(
        session_id,
        temporal_context,
    )

    cached = _get_cached_context(
        cache_key
    )

    if cached is not None:
        print(
            "[CONTEXT CACHE HIT] "
            f"session={session_id} "
            f"snapshot={cache_key[1]}"
        )

        return cached

    # -----------------------------------------------------
    # 3. Evidence compression
    # -----------------------------------------------------

    compressed_evidence = (
        compress_context_evidence(
            temporal_context
        )
    )

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
    # 4. Qwen
    # -----------------------------------------------------

    raw_result = _call_qwen(
        compressed_evidence
    )

    validated = (
        validate_context_result(
            raw_result
        )
    )

    # -----------------------------------------------------
    # 5. Deterministic summary
    # -----------------------------------------------------

    final_context = {
        **validated,

        "summary": build_summary(
            validated
        ),
    }

    # -----------------------------------------------------
    # 6. Cache
    # -----------------------------------------------------

    _set_cached_context(
        cache_key,
        final_context,
    )

    return final_context