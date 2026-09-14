const API_URL = "http://localhost:8000/events";


// 너무 짧은 시간 안에 같은 이벤트가 여러 번 저장되는 것을 방지
const recentEvents = new Map();

const DEDUP_WINDOW_MS = 3000;


// 빠르게 반복 전환되는 브라우저 내부 페이지나
// 수집할 필요가 없는 scheme
const BLOCKED_PROTOCOLS = [
  "chrome:",
  "chrome-extension:",
  "edge:",
  "about:",
  "file:"
];


// --------------------------------------------------
// 수집 제외 URL 판단
// --------------------------------------------------

function shouldIgnoreUrl(url) {
  if (!url) {
    return true;
  }

  try {
    const parsedUrl = new URL(url);

    // 브라우저 내부 페이지 제외
    if (
      BLOCKED_PROTOCOLS.includes(
        parsedUrl.protocol
      )
    ) {
      return true;
    }

    // Ambient Agent 자체 페이지 제외
    if (
      parsedUrl.hostname === "localhost" ||
      parsedUrl.hostname === "127.0.0.1"
    ) {
      return true;
    }

    return false;

  } catch (error) {
    console.warn(
      "[Ambient Agent] Invalid URL:",
      url
    );

    return true;
  }
}


// --------------------------------------------------
// Domain 추출
// --------------------------------------------------

function getDomain(url) {
  try {
    return new URL(url).hostname;

  } catch (error) {
    return null;
  }
}


// --------------------------------------------------
// 검색어 추출
// --------------------------------------------------

function extractSearchQuery(url) {
  if (!url) {
    return null;
  }

  try {
    const parsedUrl = new URL(url);
    const hostname = parsedUrl.hostname.toLowerCase();

    if (
      hostname.includes("google.")
    ) {
      return (
        parsedUrl.searchParams.get("q") ||
        null
      );
    }

    if (
      hostname === "search.naver.com" ||
      hostname === "m.search.naver.com"
    ) {
      return (
        parsedUrl.searchParams.get("query") ||
        null
      );
    }

    if (
      hostname.includes("bing.com")
    ) {
      return (
        parsedUrl.searchParams.get("q") ||
        null
      );
    }

    if (
      hostname.includes("duckduckgo.com")
    ) {
      return (
        parsedUrl.searchParams.get("q") ||
        null
      );
    }

    if (
      hostname.includes("youtube.com") &&
      parsedUrl.pathname === "/results"
    ) {
      return (
        parsedUrl.searchParams.get(
          "search_query"
        ) ||
        null
      );
    }

    return null;

  } catch (error) {
    console.error(
      "[Ambient Agent] extractSearchQuery error:",
      error
    );

    return null;
  }
}


// --------------------------------------------------
// 중복 이벤트 판단
// --------------------------------------------------

function isDuplicate(
  eventType,
  url
) {
  const key = `${eventType}:${url}`;

  const now = Date.now();

  const previousTime =
    recentEvents.get(key);

  recentEvents.set(
    key,
    now
  );

  if (!previousTime) {
    return false;
  }

  return (
    now - previousTime
    < DEDUP_WINDOW_MS
  );
}


// --------------------------------------------------
// Event 전송
// --------------------------------------------------

async function sendEvent(
  eventType,
  tab
) {
  if (!tab) {
    return;
  }


  // ------------------------------
  // Incognito 제외
  // ------------------------------

  if (tab.incognito) {
    console.log(
      "[Ambient Agent] Skip incognito tab"
    );

    return;
  }


  // ------------------------------
  // 제외 대상 URL
  // ------------------------------

  if (shouldIgnoreUrl(tab.url)) {
    return;
  }


  // ------------------------------
  // 중복 이벤트 제외
  // ------------------------------

  if (
    isDuplicate(
      eventType,
      tab.url
    )
  ) {
    return;
  }


  // ------------------------------
  // Event payload
  // ------------------------------

  const payload = {
    source: "chrome",

    event_type: eventType,

    url: tab.url || null,

    title: tab.title || null,

    domain: getDomain(
      tab.url
    ),

    search_query:
      extractSearchQuery(
        tab.url
      ),

    is_sensitive: false
  };


  console.log(
    "[Ambient Agent] Sending event:",
    payload
  );


  // ------------------------------
  // FastAPI 전송
  // ------------------------------

  try {
    const response = await fetch(
      API_URL,
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json"
        },

        body: JSON.stringify(
          payload
        )
      }
    );


    if (!response.ok) {
      const errorText =
        await response.text();

      console.error(
        "[Ambient Agent] API error:",
        response.status,
        errorText
      );

      return;
    }


    const data =
      await response.json();


    console.log(
      "[Ambient Agent] Event saved:",
      data
    );

  } catch (error) {
    console.error(
      "[Ambient Agent] Failed to send event:",
      error
    );
  }
}


// --------------------------------------------------
// TAB ACTIVATED
// --------------------------------------------------

chrome.tabs.onActivated.addListener(
  async (activeInfo) => {

    try {
      const tab =
        await chrome.tabs.get(
          activeInfo.tabId
        );

      await sendEvent(
        "tab_activated",
        tab
      );

    } catch (error) {
      console.error(
        "[Ambient Agent] tab_activated error:",
        error
      );
    }
  }
);


// --------------------------------------------------
// PAGE VISIT
// --------------------------------------------------

chrome.tabs.onUpdated.addListener(
  async (
    tabId,
    changeInfo,
    tab
  ) => {

    // 페이지 로딩 완료 시점만 기록
    if (
      changeInfo.status
      !== "complete"
    ) {
      return;
    }


    await sendEvent(
      "page_visit",
      tab
    );
  }
);


// --------------------------------------------------
// Service Worker Start
// --------------------------------------------------

console.log(
  "[Ambient Agent] Background service worker started."
);