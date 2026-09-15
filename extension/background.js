const API_BASE_URL = "http://localhost:8000";

const EVENTS_API_URL =
  `${API_BASE_URL}/events`;

const INTERVENTION_API_URL =
  `${API_BASE_URL}/sessions/current/intervention`;


// ==========================================================
// Configuration
// ==========================================================

const INTERVENTION_ALARM_NAME =
  "ambient-agent-intervention-check";

const INTERVENTION_CHECK_PERIOD_MINUTES = 1;

const INTERVENTION_COOLDOWN_MS =
  10 * 60 * 1000;

const DEDUP_WINDOW_MS = 3000;

const LAST_INTERVENTION_KEY =
  "ambient_agent_last_intervention";


// ==========================================================
// Runtime state
// ==========================================================

const recentEvents =
  new Map();

let latestAgentState =
  "unknown";

// DevTools / chrome://extensions 등이 포커스를 가져가도
// 마지막으로 사용한 실제 웹 탭을 기억한다.
let lastActiveWebTabId =
  null;


// ==========================================================
// URL filtering
// ==========================================================

const BLOCKED_PROTOCOLS = [
  "chrome:",
  "chrome-extension:",
  "edge:",
  "about:",
  "file:"
];


function shouldIgnoreUrl(url) {
  if (!url) {
    return true;
  }


  try {
    const parsedUrl =
      new URL(url);


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


// ==========================================================
// Domain
// ==========================================================

function getDomain(url) {
  try {
    return new URL(url).hostname;

  } catch (error) {
    return null;
  }
}


// ==========================================================
// Search query
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
    now - previousTime <
    DEDUP_WINDOW_MS
  );
}


// ==========================================================
// Event Collector
// ==========================================================

async function sendEvent(
  eventType,
  tab
) {
  if (!tab) {
    return;
  }


  // --------------------------------------------------------
  // Incognito 제외
  // --------------------------------------------------------

  if (tab.incognito) {
    console.log(
      "[Ambient Agent] Skip incognito tab"
    );


    return;
  }


  // --------------------------------------------------------
  // 제외 대상 URL
  // --------------------------------------------------------

  if (
    shouldIgnoreUrl(
      tab.url
    )
  ) {
    return;
  }


  // --------------------------------------------------------
  // 중복 이벤트 제외
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
  // Event payload
  // --------------------------------------------------------

  const payload = {
    source:
      "chrome",

    event_type:
      eventType,

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

    is_sensitive:
      false
  };


  console.log(
    "[Ambient Agent] Sending event:",
    payload
  );


  // --------------------------------------------------------
  // FastAPI 전송
  // --------------------------------------------------------

  try {
    const response =
      await fetch(
        EVENTS_API_URL,
        {
          method:
            "POST",

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
// Active Web Tab Tracking
// ==========================================================

function rememberWebTab(tab) {
  if (!tab?.id) {
    return;
  }


  if (
    shouldIgnoreUrl(
      tab.url
    )
  ) {
    return;
  }


  lastActiveWebTabId =
    tab.id;


  console.debug(
    "[Ambient Agent] Remembered web tab:",
    {
      id:
        tab.id,

      title:
        tab.title,

      url:
        tab.url
    }
  );
}


// ==========================================================
// Find Active Web Tab
// ==========================================================

async function getActiveWebTab() {
  try {

    // ------------------------------------------------------
    // 1. 모든 Chrome Window의 active tab 확인
    //
    // lastFocusedWindow를 사용하지 않는다.
    // DevTools가 focus를 가져가도 실제 web tab을 찾기 위함.
    // ------------------------------------------------------

    const activeTabs =
      await chrome.tabs.query({
        active: true
      });


    const webTabs =
      activeTabs.filter(
        (tab) =>
          tab?.id &&
          !shouldIgnoreUrl(
            tab.url
          )
      );


    // ------------------------------------------------------
    // 2. 마지막으로 기억한 실제 Web Tab 우선
    // ------------------------------------------------------

    if (
      lastActiveWebTabId !== null
    ) {

      const rememberedActiveTab =
        webTabs.find(
          (tab) =>
            tab.id ===
            lastActiveWebTabId
        );


      if (rememberedActiveTab) {
        return rememberedActiveTab;
      }


      // active 목록에 없어도
      // 해당 tab이 아직 존재하면 사용한다.
      try {
        const rememberedTab =
          await chrome.tabs.get(
            lastActiveWebTabId
          );


        if (
          rememberedTab?.id &&
          !shouldIgnoreUrl(
            rememberedTab.url
          )
        ) {
          return rememberedTab;
        }

      } catch (error) {
        // 탭이 닫혔거나 더 이상 존재하지 않는 경우
        lastActiveWebTabId =
          null;
      }
    }


    // ------------------------------------------------------
    // 3. 현재 active 상태의 실제 Web Tab 사용
    // ------------------------------------------------------

    if (
      webTabs.length > 0
    ) {
      const tab =
        webTabs[0];


      rememberWebTab(
        tab
      );


      return tab;
    }


    // ------------------------------------------------------
    // 4. Fallback
    //
    // 일반 web tab 중 사용할 수 있는 탭을 찾는다.
    // ------------------------------------------------------

    const allTabs =
      await chrome.tabs.query({});


    let fallbackTab =
      allTabs.find(
        (tab) =>
          tab?.id &&
          tab.active &&
          !shouldIgnoreUrl(
            tab.url
          )
      );


    if (!fallbackTab) {
      fallbackTab =
        allTabs.find(
          (tab) =>
            tab?.id &&
            !shouldIgnoreUrl(
              tab.url
            )
        );
    }


    if (!fallbackTab) {
      console.warn(
        "[Ambient Agent] No usable web tab found."
      );


      return null;
    }


    rememberWebTab(
      fallbackTab
    );


    return fallbackTab;

  } catch (error) {
    console.error(
      "[Ambient Agent] Failed to get active web tab:",
      error
    );


    return null;
  }
}


// ==========================================================
// Content Script Injection
// ==========================================================

async function injectContentScript(
  tabId
) {
  if (!tabId) {
    return false;
  }


  try {
    console.log(
      "[Ambient Agent] Injecting content script:",
      tabId
    );


    await chrome.scripting.executeScript({
      target: {
        tabId
      },

      files: [
        "content.js"
      ]
    });


    console.log(
      "[Ambient Agent] Content script injected:",
      tabId
    );


    return true;

  } catch (error) {
    console.warn(
      "[Ambient Agent] Content script injection failed:",
      error?.message ||
      error
    );


    return false;
  }
}


// ==========================================================
// Content Script Messaging
// ==========================================================

async function sendMessageToTab(
  tabId,
  payload
) {
  if (!tabId) {
    return false;
  }


  // --------------------------------------------------------
  // 1차 메시지 전송
  // --------------------------------------------------------

  try {
    const response =
      await chrome.tabs.sendMessage(
        tabId,
        payload
      );


    console.debug(
      "[Ambient Agent] Content response:",
      response
    );


    return true;

  } catch (firstError) {
    console.debug(
      "[Ambient Agent] Initial message failed:",
      firstError?.message ||
      firstError
    );
  }


  // --------------------------------------------------------
  // Receiver가 없다면 content.js 동적 주입
  // --------------------------------------------------------

  const injected =
    await injectContentScript(
      tabId
    );


  if (!injected) {
    return false;
  }


  // content.js의 listener 등록 시간을 아주 조금 확보한다.
  await new Promise(
    (resolve) =>
      setTimeout(
        resolve,
        100
      )
  );


  // --------------------------------------------------------
  // 2차 메시지 전송
  // --------------------------------------------------------

  try {
    const response =
      await chrome.tabs.sendMessage(
        tabId,
        payload
      );


    console.log(
      "[Ambient Agent] Message delivered after reinjection:",
      payload.type,
      response
    );


    return true;

  } catch (secondError) {
    console.warn(
      "[Ambient Agent] Message failed after reinjection:",
      secondError?.message ||
      secondError
    );


    return false;
  }
}


// ==========================================================
// Send Message To Current Web Tab
// ==========================================================

async function sendMessageToActiveTab(
  payload
) {
  const tab =
    await getActiveWebTab();


  if (!tab?.id) {
    console.warn(
      "[Ambient Agent] No target tab for message:",
      payload.type
    );


    return false;
  }


  console.debug(
    "[Ambient Agent] Message target:",
    {
      type:
        payload.type,

      tab_id:
        tab.id,

      title:
        tab.title,

      url:
        tab.url
    }
  );


  const delivered =
    await sendMessageToTab(
      tab.id,
      payload
    );


  if (delivered) {
    rememberWebTab(
      tab
    );


    console.log(
      "[Ambient Agent] Message delivered:",
      payload.type,
      "→ tab",
      tab.id
    );
  }


  return delivered;
}


// ==========================================================
// Presence State
// ==========================================================

async function publishAgentState(
  state
) {
  latestAgentState =
    state ||
    "unknown";


  await sendMessageToActiveTab({
    type:
      "AMBIENT_STATE_UPDATE",

    state:
      latestAgentState
  });
}


// ==========================================================
// Intervention Identity
// ==========================================================

function buildInterventionKey(
  intervention
) {
  const sessionId =
    intervention.session_id ??
    "unknown";


  const context =
    intervention.context ||
    {};


  const subject =
    context.blocker ??
    context.task ??
    context.goal ??
    "unknown";


  return `${sessionId}:${subject}`;
}


// ==========================================================
// Intervention Cooldown
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
    previous.key ===
    currentKey;


  const elapsed =
    Date.now() -
    previous.timestamp;


  if (
    sameIntervention &&
    elapsed <
      INTERVENTION_COOLDOWN_MS
  ) {
    console.log(
      "[Ambient Agent] Intervention suppressed by cooldown:",
      {
        key:
          currentKey,

        elapsed_ms:
          elapsed,

        remaining_ms:
          INTERVENTION_COOLDOWN_MS -
          elapsed
      }
    );


    return false;
  }


  return true;
}


async function rememberIntervention(
  intervention
) {
  await chrome.storage.local.set({
    [LAST_INTERVENTION_KEY]: {
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
    }
  });
}


// ==========================================================
// Intervention Watcher
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
          method:
            "GET",

          cache:
            "no-store"
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
    // Context → Ambient Presence
    // ------------------------------------------------------

    const contextState =
      intervention.context?.state ||
      "unknown";


    await publishAgentState(
      contextState
    );


    // ------------------------------------------------------
    // Intervention 불필요
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
    // Ambient Whisper
    // ------------------------------------------------------

    const delivered =
      await sendMessageToActiveTab({
        type:
          "AMBIENT_INTERVENTION",

        intervention
      });


    if (!delivered) {
      console.warn(
        "[Ambient Agent] Whisper was not delivered."
      );


      // 실제 사용자 화면에 표시되지 않았으므로
      // cooldown을 기록하지 않는다.
      return;
    }


    // 실제 전달 성공 이후에만 cooldown 기록
    await rememberIntervention(
      intervention
    );


    console.log(
      "[Ambient Agent] Ambient Whisper shown.",
      {
        session_id:
          intervention.session_id,

        intervention_score:
          intervention.intervention_score,

        level:
          intervention.level
      }
    );

  } catch (error) {
    console.error(
      "[Ambient Agent] Intervention check failed:",
      error
    );
  }
}


// ==========================================================
// Intervention Alarm
// ==========================================================

async function ensureInterventionAlarm() {
  const existing =
    await chrome.alarms.get(
      INTERVENTION_ALARM_NAME
    );


  if (existing) {
    console.debug(
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
// Extension Installed / Updated
// ==========================================================

chrome.runtime.onInstalled.addListener(
  async () => {
    console.log(
      "[Ambient Agent] Extension installed/updated."
    );


    await ensureInterventionAlarm();


    // 개발 중에는 reload 직후 상태를 한 번 확인한다.
    await checkIntervention();
  }
);


// ==========================================================
// Browser Startup
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
// Alarm Listener
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


      // 마지막 실제 Web Tab 기억
      rememberWebTab(
        tab
      );


      // Activity Event 저장
      await sendEvent(
        "tab_activated",
        tab
      );


      // 이미 알고 있는 Agent state만
      // 새 탭의 Presence에 전달한다.
      if (
        !shouldIgnoreUrl(
          tab.url
        )
      ) {
        await sendMessageToTab(
          tab.id,
          {
            type:
              "AMBIENT_STATE_UPDATE",

            state:
              latestAgentState
          }
        );
      }

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

    // 페이지 로딩 완료 시점만 기록
    if (
      changeInfo.status !==
      "complete"
    ) {
      return;
    }


    // 마지막 실제 Web Tab 기억
    rememberWebTab(
      tab
    );


    // Activity Event 저장
    await sendEvent(
      "page_visit",
      tab
    );


    if (
      shouldIgnoreUrl(
        tab.url
      )
    ) {
      return;
    }


    // content.js가 document_idle에서 mount될 시간을
    // 조금 준 뒤 현재 state 전달
    setTimeout(
      async () => {
        await sendMessageToTab(
          tabId,
          {
            type:
              "AMBIENT_STATE_UPDATE",

            state:
              latestAgentState
          }
        );
      },

      300
    );
  }
);


// ==========================================================
// TAB REMOVED
// ==========================================================

chrome.tabs.onRemoved.addListener(
  (tabId) => {

    if (
      tabId ===
      lastActiveWebTabId
    ) {
      lastActiveWebTabId =
        null;


      console.debug(
        "[Ambient Agent] Remembered web tab closed."
      );
    }
  }
);


// ==========================================================
// Service Worker Start
// ==========================================================

console.log(
  "[Ambient Agent] Background service worker started."
);


ensureInterventionAlarm().catch(
  (error) => {
    console.error(
      "[Ambient Agent] Failed to ensure alarm:",
      error
    );
  }
);