const API_BASE_URL = "http://localhost:8000";

const EVENTS_API_URL =
  `${API_BASE_URL}/events`;

const INTERVENTION_API_URL =
  `${API_BASE_URL}/sessions/current/intervention`;


// ==========================================================
// Configuration
// ==========================================================

// Chrome alarms의 안정적인 최소 주기를 고려해
// MVP에서는 1분마다 확인한다.
const INTERVENTION_ALARM_NAME =
  "ambient-agent-intervention-check";

const INTERVENTION_CHECK_PERIOD_MINUTES = 1;


// 같은 문제에 대해 계속 알림이 뜨지 않도록 한다.
const INTERVENTION_COOLDOWN_MS =
  10 * 60 * 1000;


// Activity event deduplication
const DEDUP_WINDOW_MS = 3000;


// Intervention storage key
const LAST_INTERVENTION_KEY =
  "ambient_agent_last_intervention";


// ----------------------------------------------------------
// Event deduplication memory
// ----------------------------------------------------------

const recentEvents = new Map();


// ----------------------------------------------------------
// Blocked protocols
// ----------------------------------------------------------

const BLOCKED_PROTOCOLS = [
  "chrome:",
  "chrome-extension:",
  "edge:",
  "about:",
  "file:"
];


// ==========================================================
// URL filtering
// ==========================================================

function shouldIgnoreUrl(url) {
  if (!url) {
    return true;
  }

  try {
    const parsedUrl =
      new URL(url);

    if (
      BLOCKED_PROTOCOLS.includes(
        parsedUrl.protocol
      )
    ) {
      return true;
    }

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


// ==========================================================
// Domain extraction
// ==========================================================

function getDomain(url) {
  try {
    return new URL(url).hostname;

  } catch (error) {
    return null;
  }
}


// ==========================================================
// Search query extraction
// ==========================================================

function extractSearchQuery(url) {
  if (!url) {
    return null;
  }

  try {
    const parsedUrl =
      new URL(url);

    const hostname =
      parsedUrl.hostname.toLowerCase();


    // Google
    if (
      hostname.includes("google.")
    ) {
      return (
        parsedUrl.searchParams.get("q") ||
        null
      );
    }


    // Naver
    if (
      hostname === "search.naver.com" ||
      hostname === "m.search.naver.com"
    ) {
      return (
        parsedUrl.searchParams.get(
          "query"
        ) ||
        null
      );
    }


    // Bing
    if (
      hostname.includes("bing.com")
    ) {
      return (
        parsedUrl.searchParams.get("q") ||
        null
      );
    }


    // DuckDuckGo
    if (
      hostname.includes(
        "duckduckgo.com"
      )
    ) {
      return (
        parsedUrl.searchParams.get("q") ||
        null
      );
    }


    // YouTube
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


// ==========================================================
// Event deduplication
// ==========================================================

function isDuplicate(
  eventType,
  url
) {
  const key =
    `${eventType}:${url}`;

  const now =
    Date.now();

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


// ==========================================================
// Send activity event
// ==========================================================

async function sendEvent(
  eventType,
  tab
) {
  if (!tab) {
    return;
  }


  // --------------------------------------------------------
  // Incognito
  // --------------------------------------------------------

  if (tab.incognito) {
    console.log(
      "[Ambient Agent] Skip incognito tab"
    );

    return;
  }


  // --------------------------------------------------------
  // URL filtering
  // --------------------------------------------------------

  if (
    shouldIgnoreUrl(
      tab.url
    )
  ) {
    return;
  }


  // --------------------------------------------------------
  // Deduplication
  // --------------------------------------------------------

  if (
    isDuplicate(
      eventType,
      tab.url
    )
  ) {
    return;
  }


  // --------------------------------------------------------
  // Payload
  // --------------------------------------------------------

  const payload = {
    source: "chrome",

    event_type: eventType,

    url:
      tab.url || null,

    title:
      tab.title || null,

    domain:
      getDomain(
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


  // --------------------------------------------------------
  // FastAPI
  // --------------------------------------------------------

  try {
    const response =
      await fetch(
        EVENTS_API_URL,
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json"
          },

          body:
            JSON.stringify(
              payload
            )
        }
      );


    if (!response.ok) {
      const errorText =
        await response.text();

      console.error(
        "[Ambient Agent] Event API error:",
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


// ==========================================================
// Intervention key
// ==========================================================

function buildInterventionKey(
  intervention
) {
  const sessionId =
    intervention.session_id ?? "unknown";

  const blocker =
    intervention.context?.blocker ??
    intervention.context?.task ??
    intervention.context?.goal ??
    "unknown";

  return `${sessionId}:${blocker}`;
}


// ==========================================================
// Cooldown check
// ==========================================================

async function canShowIntervention(
  intervention
) {
  const currentKey =
    buildInterventionKey(
      intervention
    );

  const stored =
    await chrome.storage.local.get(
      LAST_INTERVENTION_KEY
    );

  const previous =
    stored[
      LAST_INTERVENTION_KEY
    ];

  if (!previous) {
    return true;
  }


  const sameIntervention =
    previous.key === currentKey;

  const elapsed =
    Date.now() -
    previous.timestamp;


  // 같은 문제 + cooldown 이내
  if (
    sameIntervention &&
    elapsed < INTERVENTION_COOLDOWN_MS
  ) {
    console.log(
      "[Ambient Agent] Intervention suppressed by cooldown:",
      {
        key: currentKey,
        elapsed
      }
    );

    return false;
  }


  return true;
}


// ==========================================================
// Save intervention history
// ==========================================================

async function rememberIntervention(
  intervention
) {
  const value = {
    key:
      buildInterventionKey(
        intervention
      ),

    timestamp:
      Date.now(),

    session_id:
      intervention.session_id,

    blocker:
      intervention.context?.blocker ??
      null
  };


  await chrome.storage.local.set({
    [LAST_INTERVENTION_KEY]:
      value
  });
}


// ==========================================================
// Notification text
// ==========================================================

function buildNotificationMessage(
  intervention
) {
  const context =
    intervention.context || {};


  if (context.blocker) {
    return (
      `${context.blocker} 문제를 ` +
      `해결하는 데 도움을 드릴까요?`
    );
  }


  if (context.task) {
    return (
      `${context.task}. ` +
      `도움이 필요하신가요?`
    );
  }


  if (context.goal) {
    return (
      `${context.goal}와 관련해 ` +
      `도움을 드릴까요?`
    );
  }


  return (
    "현재 작업에서 막힌 것 같아요. " +
    "도움을 드릴까요?"
  );
}


// ==========================================================
// Show proactive notification
// ==========================================================

async function showInterventionNotification(
  intervention
) {
  const message =
    buildNotificationMessage(
      intervention
    );


  const notificationId =
    `ambient-agent-${Date.now()}`;


  await chrome.notifications.create(
    notificationId,
    {
      type: "basic",

      iconUrl:
        "icons/icon128.png",

      title:
        "Ambient Agent",

      message,

      priority: 2,

      requireInteraction: true
    }
  );


  await rememberIntervention(
    intervention
  );


  console.log(
    "[Ambient Agent] Proactive intervention shown:",
    {
      notificationId,
      intervention
    }
  );
}


// ==========================================================
// Check intervention
// ==========================================================

async function checkIntervention() {
  console.log(
    "[Ambient Agent] Checking intervention..."
  );


  try {
    const response =
      await fetch(
        INTERVENTION_API_URL,
        {
          method: "GET",

          cache: "no-store"
        }
      );


    if (!response.ok) {
      const errorText =
        await response.text();

      console.error(
        "[Ambient Agent] Intervention API error:",
        response.status,
        errorText
      );

      return;
    }


    const intervention =
      await response.json();


    console.log(
      "[Ambient Agent] Intervention result:",
      intervention
    );


    // ------------------------------------------------------
    // No intervention
    // ------------------------------------------------------

    if (
      !intervention.should_intervene
    ) {
      return;
    }


    // ------------------------------------------------------
    // Cooldown
    // ------------------------------------------------------

    const allowed =
      await canShowIntervention(
        intervention
      );


    if (!allowed) {
      return;
    }


    // ------------------------------------------------------
    // Show
    // ------------------------------------------------------

    await showInterventionNotification(
      intervention
    );

  } catch (error) {
    console.error(
      "[Ambient Agent] Intervention check failed:",
      error
    );
  }
}


// ==========================================================
// Alarm initialization
// ==========================================================

async function ensureInterventionAlarm() {
  const existing =
    await chrome.alarms.get(
      INTERVENTION_ALARM_NAME
    );


  if (existing) {
    console.log(
      "[Ambient Agent] Intervention alarm already exists."
    );

    return;
  }


  chrome.alarms.create(
    INTERVENTION_ALARM_NAME,
    {
      delayInMinutes:
        INTERVENTION_CHECK_PERIOD_MINUTES,

      periodInMinutes:
        INTERVENTION_CHECK_PERIOD_MINUTES
    }
  );


  console.log(
    "[Ambient Agent] Intervention alarm created."
  );
}


// ==========================================================
// Extension installed / updated
// ==========================================================

chrome.runtime.onInstalled.addListener(
  async () => {
    console.log(
      "[Ambient Agent] Extension installed/updated."
    );

    await ensureInterventionAlarm();

    // 개발 중에는 설치 직후 한 번 확인
    await checkIntervention();
  }
);


// ==========================================================
// Browser startup
// ==========================================================

chrome.runtime.onStartup.addListener(
  async () => {
    console.log(
      "[Ambient Agent] Browser started."
    );

    await ensureInterventionAlarm();
  }
);


// ==========================================================
// Alarm listener
// ==========================================================

chrome.alarms.onAlarm.addListener(
  async (alarm) => {
    if (
      alarm.name !==
      INTERVENTION_ALARM_NAME
    ) {
      return;
    }


    await checkIntervention();
  }
);


// ==========================================================
// TAB ACTIVATED
// ==========================================================

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


// ==========================================================
// PAGE VISIT
// ==========================================================

chrome.tabs.onUpdated.addListener(
  async (
    tabId,
    changeInfo,
    tab
  ) => {
    if (
      changeInfo.status !==
      "complete"
    ) {
      return;
    }


    await sendEvent(
      "page_visit",
      tab
    );
  }
);


// ==========================================================
// Service worker startup
// ==========================================================

console.log(
  "[Ambient Agent] Background service worker started."
);


// Service worker가 wake된 경우에도 alarm 존재 보장
ensureInterventionAlarm().catch(
  (error) => {
    console.error(
      "[Ambient Agent] Failed to ensure alarm:",
      error
    );
  }
);