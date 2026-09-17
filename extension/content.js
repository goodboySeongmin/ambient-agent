(() => {
  // ========================================================
  // Re-injection cleanup
  // ========================================================
  //
  // Extension reload / Service Worker restart 이후
  // 기존 UI DOM만 남아 있고 content-script listener는
  // 사라진 상태가 발생할 수 있다.
  //
  // 기존 구현은 root가 존재하면 즉시 return했기 때문에
  // listener가 다시 등록되지 않아
  // "Receiving end does not exist"가 발생했다.
  //
  // 재주입 시 기존 UI를 제거하고 전체 content script를
  // 깨끗하게 다시 초기화한다.
  // ========================================================

  const existingHost =
    document.getElementById(
      "ambient-agent-root"
    );


  if (existingHost) {
    console.log(
      "[Ambient Agent] Existing Presence found. Remounting."
    );


    existingHost.remove();
  }


  // ========================================================
  // Host + Shadow DOM
  // ========================================================

  const host = document.createElement("div");

  host.id = "ambient-agent-root";

  host.style.position = "fixed";
  host.style.right = "0";
  host.style.bottom = "150px";
  host.style.zIndex = "2147483647";

  document.documentElement.appendChild(host);


  const shadow = host.attachShadow({
    mode: "open"
  });


  // ========================================================
  // CSS
  // ========================================================

  const style = document.createElement("style");

  style.textContent = `
    :host {
      all: initial;
    }

    * {
      box-sizing: border-box;
    }


    /* ======================================================
       Root Presence
    ====================================================== */

    .ambient-presence {
      position: relative;

      display: flex;
      align-items: center;
      justify-content: flex-end;

      min-width: 76px;
      height: 72px;

      padding-right: 14px;

      font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        "Apple SD Gothic Neo",
        "Noto Sans KR",
        sans-serif;

      pointer-events: none;
    }


    /* ======================================================
       Edge Light
    ====================================================== */

    .edge-light {
      position: absolute;

      right: -5px;
      top: 15px;

      width: 3px;
      height: 42px;

      border-radius: 999px 0 0 999px;

      background:
        linear-gradient(
          180deg,
          transparent,
          rgba(205, 220, 255, 0.34),
          rgba(255, 255, 255, 0.90),
          rgba(180, 205, 255, 0.34),
          transparent
        );

      opacity: 0.34;

      filter: blur(0.2px);

      transition:
        height 500ms ease,
        opacity 500ms ease,
        filter 500ms ease,
        transform 500ms ease;
    }


    /* ======================================================
       Halo
    ====================================================== */

    .halo {
      position: absolute;

      right: -15px;

      width: 70px;
      height: 70px;

      border-radius: 50%;

      background:
        radial-gradient(
          circle,
          rgba(235, 242, 255, 0.22) 0%,
          rgba(175, 197, 235, 0.12) 30%,
          rgba(115, 145, 205, 0.045) 56%,
          transparent 72%
        );

      filter: blur(5px);

      opacity: 0.34;

      transform: scale(0.88);

      transition:
        opacity 600ms ease,
        transform 600ms ease,
        filter 600ms ease;
    }


    /* ======================================================
       Orb
    ====================================================== */

    .orb-shell {
      position: relative;

      width: 30px;
      height: 30px;

      display: flex;
      align-items: center;
      justify-content: center;

      pointer-events: auto;

      cursor: default;

      z-index: 3;
    }


    .orb-ring {
      position: absolute;

      width: 25px;
      height: 25px;

      border-radius: 50%;

      border:
        1px solid
        rgba(205, 218, 245, 0.18);

      opacity: 0.45;

      transform: scale(0.82);

      transition:
        opacity 500ms ease,
        transform 500ms ease,
        border-color 500ms ease;
    }


    .orb {
      position: relative;

      width: 15px;
      height: 15px;

      border-radius: 50%;

      background:
        radial-gradient(
          circle at 34% 27%,
          rgba(255, 255, 255, 1) 0%,
          rgba(245, 248, 255, 0.98) 16%,
          rgba(196, 211, 239, 0.88) 38%,
          rgba(125, 151, 199, 0.64) 62%,
          rgba(65, 81, 116, 0.32) 82%,
          rgba(40, 50, 72, 0.12) 100%
        );

      box-shadow:
        0 0 6px rgba(255, 255, 255, 0.48),
        0 0 16px rgba(167, 191, 235, 0.24),
        0 0 32px rgba(115, 150, 215, 0.10);

      opacity: 0.72;

      transform: scale(0.92);

      transition:
        width 450ms ease,
        height 450ms ease,
        opacity 450ms ease,
        transform 450ms ease,
        box-shadow 450ms ease;
    }


    .orb::after {
      content: "";

      position: absolute;

      left: 3px;
      top: 2px;

      width: 4px;
      height: 4px;

      border-radius: 50%;

      background:
        rgba(255, 255, 255, 0.94);

      filter: blur(0.4px);

      opacity: 0.88;
    }


    /* ======================================================
       Unknown / Normal
    ====================================================== */

    .ambient-presence[data-state="unknown"] .orb,
    .ambient-presence[data-state="normal"] .orb,
    .ambient-presence[data-state="reading"] .orb {
      animation:
        quietBreathing
        6s
        ease-in-out
        infinite;
    }


    /* ======================================================
       Researching
    ====================================================== */

    .ambient-presence[data-state="researching"] .orb,
    .ambient-presence[data-state="comparing"] .orb {
      opacity: 0.88;

      animation:
        researchBreathing
        3.8s
        ease-in-out
        infinite;

      box-shadow:
        0 0 7px rgba(255, 255, 255, 0.58),
        0 0 20px rgba(167, 191, 235, 0.30),
        0 0 38px rgba(115, 150, 215, 0.14);
    }


    .ambient-presence[data-state="researching"] .halo,
    .ambient-presence[data-state="comparing"] .halo {
      opacity: 0.48;

      animation:
        haloBreathing
        3.8s
        ease-in-out
        infinite;
    }


    /* ======================================================
       Debugging / Implementing / Deciding
    ====================================================== */

    .ambient-presence[data-state="debugging"] .orb,
    .ambient-presence[data-state="implementing"] .orb,
    .ambient-presence[data-state="deciding"] .orb {
      opacity: 0.96;

      transform: scale(1.02);

      animation:
        focusedBreathing
        2.6s
        ease-in-out
        infinite;

      box-shadow:
        0 0 8px rgba(255, 255, 255, 0.70),
        0 0 22px rgba(175, 199, 244, 0.38),
        0 0 44px rgba(110, 150, 225, 0.18);
    }


    .ambient-presence[data-state="debugging"] .orb-ring,
    .ambient-presence[data-state="implementing"] .orb-ring,
    .ambient-presence[data-state="deciding"] .orb-ring {
      opacity: 0.62;

      transform: scale(1);
    }


    .ambient-presence[data-state="debugging"] .edge-light,
    .ambient-presence[data-state="implementing"] .edge-light,
    .ambient-presence[data-state="deciding"] .edge-light {
      opacity: 0.62;

      height: 48px;
    }


    /* ======================================================
       Intervention state
    ====================================================== */

    .ambient-presence.intervening .orb {
      width: 17px;
      height: 17px;

      opacity: 1;

      animation:
        interventionBreathing
        2.1s
        ease-in-out
        infinite;

      box-shadow:
        0 0 8px rgba(255, 255, 255, 0.90),
        0 0 24px rgba(186, 208, 250, 0.55),
        0 0 54px rgba(118, 158, 235, 0.28);
    }


    .ambient-presence.intervening .orb-ring {
      opacity: 0.86;

      transform: scale(1.12);

      border-color:
        rgba(220, 230, 250, 0.40);
    }


    .ambient-presence.intervening .halo {
      opacity: 0.80;

      transform: scale(1.20);

      filter: blur(7px);
    }


    .ambient-presence.intervening .edge-light {
      opacity: 0.94;

      height: 56px;

      filter: blur(0px);
    }


    /* ======================================================
       Whisper
    ====================================================== */

    .whisper {
      position: absolute;

      right: 50px;
      top: 50%;

      width: 0;
      max-width: 340px;

      transform:
        translateY(-50%)
        translateX(12px);

      opacity: 0;

      overflow: hidden;

      pointer-events: none;

      transition:
        width 620ms cubic-bezier(0.16, 1, 0.3, 1),
        opacity 400ms ease,
        transform 620ms cubic-bezier(0.16, 1, 0.3, 1);
    }


    .whisper.visible {
      width: 320px;

      opacity: 1;

      transform:
        translateY(-50%)
        translateX(0);

      pointer-events: auto;
    }


    .whisper-surface {
      position: relative;

      width: 320px;

      padding:
        14px 16px
        13px 17px;

      border:
        1px solid
        rgba(255, 255, 255, 0.36);

      border-radius: 18px;

      background:
        linear-gradient(
          135deg,
          rgba(30, 34, 43, 0.82),
          rgba(22, 26, 34, 0.72)
        );

      box-shadow:
        0 12px 42px
        rgba(0, 0, 0, 0.18),
        inset 0 1px 0
        rgba(255, 255, 255, 0.10);

      backdrop-filter:
        blur(22px)
        saturate(125%);

      -webkit-backdrop-filter:
        blur(22px)
        saturate(125%);
    }


    .whisper-surface::after {
      content: "";

      position: absolute;

      right: -12px;
      top: 50%;

      width: 14px;
      height: 1px;

      background:
        linear-gradient(
          90deg,
          rgba(210, 224, 255, 0.55),
          transparent
        );
    }


    .whisper-eyebrow {
      margin-bottom: 6px;

      font-size: 10px;
      font-weight: 600;

      letter-spacing: 0.08em;

      color:
        rgba(218, 226, 241, 0.58);

      text-transform: uppercase;
    }


    .whisper-message {
      font-size: 13px;
      font-weight: 450;

      line-height: 1.55;

      letter-spacing: -0.015em;

      color:
        rgba(248, 250, 255, 0.96);

      word-break: keep-all;
    }


    .whisper-actions {
      display: flex;
      align-items: center;

      gap: 7px;

      margin-top: 11px;

      opacity: 0;

      transform:
        translateY(4px);

      transition:
        opacity 350ms ease 300ms,
        transform 350ms ease 300ms;
    }


    .whisper.visible
    .whisper-actions {
      opacity: 1;

      transform:
        translateY(0);
    }


    .ambient-button {
      appearance: none;

      border: 0;

      padding:
        6px 10px;

      border-radius: 999px;

      font-family: inherit;

      font-size: 11px;
      font-weight: 500;

      cursor: pointer;

      transition:
        background 180ms ease,
        opacity 180ms ease,
        transform 180ms ease;

      outline: none;
    }


    .ambient-button:hover {
      transform:
        translateY(-1px);
    }


    .ambient-button.primary {
      color:
        rgba(25, 29, 37, 0.96);

      background:
        rgba(242, 246, 255, 0.94);
    }


    .ambient-button.primary:hover {
      background:
        rgba(255, 255, 255, 1);
    }


    .ambient-button.secondary {
      color:
        rgba(226, 232, 244, 0.72);

      background:
        rgba(255, 255, 255, 0.07);
    }


    .ambient-button.secondary:hover {
      background:
        rgba(255, 255, 255, 0.11);
    }


    /* ======================================================
       Animations
    ====================================================== */

    @keyframes quietBreathing {
      0%,
      100% {
        transform:
          scale(0.90);

        opacity: 0.60;
      }

      50% {
        transform:
          scale(1.02);

        opacity: 0.80;
      }
    }


    @keyframes researchBreathing {
      0%,
      100% {
        transform:
          scale(0.92);
      }

      50% {
        transform:
          scale(1.08);
      }
    }


    @keyframes focusedBreathing {
      0%,
      100% {
        transform:
          scale(0.96);
      }

      50% {
        transform:
          scale(1.10);
      }
    }


    @keyframes interventionBreathing {
      0%,
      100% {
        transform:
          scale(0.98);
      }

      50% {
        transform:
          scale(1.14);
      }
    }


    @keyframes haloBreathing {
      0%,
      100% {
        transform:
          scale(0.92);
      }

      50% {
        transform:
          scale(1.12);
      }
    }


    @media (
      prefers-reduced-motion: reduce
    ) {
      .orb,
      .halo {
        animation: none !important;
      }

      .whisper,
      .whisper-actions {
        transition: none;
      }
    }
  

    /* ======================================================
       Solution View
    ====================================================== */

    .ambient-solution {
      display: none;
      margin-top: 2px;
    }

    .ambient-solution.visible {
      display: block;

      animation:
        ambientSolutionIn
        360ms
        cubic-bezier(0.22, 1, 0.36, 1)
        both;
    }

    .ambient-solution-title {
      margin-bottom: 8px;

      color:
        rgba(255, 255, 255, 0.96);

      font-size: 14px;
      font-weight: 650;
      line-height: 1.45;

      letter-spacing: -0.02em;
    }

    .ambient-solution-summary {
      margin-bottom: 13px;

      color:
        rgba(226, 232, 244, 0.76);

      font-size: 12px;
      line-height: 1.65;

      letter-spacing: -0.015em;
    }

    .ambient-solution-steps {
      display: flex;
      flex-direction: column;

      gap: 7px;

      margin-top: 4px;
    }

    .ambient-solution-step {
      display: grid;

      grid-template-columns:
        24px minmax(0, 1fr);

      gap: 7px;

      align-items: start;

      padding: 8px 9px;

      border:
        1px solid
        rgba(255, 255, 255, 0.07);

      border-radius: 9px;

      background:
        rgba(255, 255, 255, 0.035);
    }

    .ambient-solution-number {
      padding-top: 1px;

      color:
        rgba(176, 199, 241, 0.58);

      font-size: 9px;
      font-weight: 700;

      line-height: 1.55;

      letter-spacing: 0.06em;
    }

    .ambient-solution-step-body {
      min-width: 0;

      color:
        rgba(242, 245, 250, 0.88);

      font-size: 11px;
      line-height: 1.6;

      word-break: keep-all;
      overflow-wrap: anywhere;
    }

    .ambient-button:disabled {
      cursor: default;
      opacity: 0.56;
    }

    @keyframes ambientSolutionIn {
      from {
        opacity: 0;

        transform:
          translateY(4px);
      }

      to {
        opacity: 1;

        transform:
          translateY(0);
      }
    }
`;


  // ========================================================
  // DOM
  // ========================================================

  const presence =
    document.createElement("div");

  presence.className =
    "ambient-presence";

  presence.dataset.state =
    "unknown";


  const edgeLight =
    document.createElement("div");

  edgeLight.className =
    "edge-light";


  const halo =
    document.createElement("div");

  halo.className =
    "halo";


  const orbShell =
    document.createElement("div");

  orbShell.className =
    "orb-shell";


  const orbRing =
    document.createElement("div");

  orbRing.className =
    "orb-ring";


  const orb =
    document.createElement("div");

  orb.className =
    "orb";


  const whisper =
    document.createElement("div");

  whisper.className =
    "whisper";


  const whisperSurface =
    document.createElement("div");

  whisperSurface.className =
    "whisper-surface";


  const eyebrow =
    document.createElement("div");

  eyebrow.className =
    "whisper-eyebrow";

  eyebrow.textContent =
    "Ambient";


  const message =
    document.createElement("div");

  message.className =
    "whisper-message";


  const solutionView =
    document.createElement("div");

  solutionView.className =
    "ambient-solution";


  const solutionTitle =
    document.createElement("div");

  solutionTitle.className =
    "ambient-solution-title";


  const solutionSummary =
    document.createElement("div");

  solutionSummary.className =
    "ambient-solution-summary";


  const solutionSteps =
    document.createElement("div");

  solutionSteps.className =
    "ambient-solution-steps";


  solutionView.appendChild(
    solutionTitle
  );

  solutionView.appendChild(
    solutionSummary
  );

  solutionView.appendChild(
    solutionSteps
  );


  const actions =
    document.createElement("div");

  actions.className =
    "whisper-actions";


  const assistButton =
    document.createElement("button");

  assistButton.className =
    "ambient-button primary";

  assistButton.textContent =
    "같이 보기";


  const dismissButton =
    document.createElement("button");

  dismissButton.className =
    "ambient-button secondary";

  dismissButton.textContent =
    "괜찮아요";


  actions.appendChild(
    assistButton
  );

  actions.appendChild(
    dismissButton
  );


  whisperSurface.appendChild(
    eyebrow
  );

  whisperSurface.appendChild(
    message
  );

  whisperSurface.appendChild(
    solutionView
  );

  whisperSurface.appendChild(
    actions
  );

  whisper.appendChild(
    whisperSurface
  );


  orbShell.appendChild(
    orbRing
  );

  orbShell.appendChild(
    orb
  );


  presence.appendChild(
    whisper
  );

  presence.appendChild(
    edgeLight
  );

  presence.appendChild(
    halo
  );

  presence.appendChild(
    orbShell
  );


  shadow.appendChild(
    style
  );

  shadow.appendChild(
    presence
  );


  // ========================================================
  // State
  // ========================================================

  let currentIntervention = null;

  let solutionLoading = false;


  function normalizeState(state) {
    const allowed = new Set([
      "unknown",
      "normal",
      "reading",
      "researching",
      "comparing",
      "debugging",
      "implementing",
      "deciding"
    ]);


    if (!allowed.has(state)) {
      return "unknown";
    }


    return state;
  }


  function setAgentState(state) {
    const normalized =
      normalizeState(state);


    presence.dataset.state =
      normalized;


    console.log(
      "[Ambient Agent] Presence state:",
      normalized
    );
  }


  // ========================================================
  // Whisper
  // ========================================================

  function buildWhisperMessage(
    intervention
  ) {
    const context =
      intervention?.context || {};


    if (context.blocker) {
      return (
        `${context.blocker}에서 ` +
        `조금 막힌 것 같아요. 같이 볼까요?`
      );
    }


    if (context.task) {
      return (
        `${context.task}. ` +
        `필요하면 같이 볼게요.`
      );
    }


    if (context.goal) {
      return (
        `${context.goal}을 진행 중이네요. ` +
        `필요하면 같이 볼까요?`
      );
    }


    return (
      "조금 막힌 것 같아요. " +
      "필요하면 같이 볼까요?"
    );
  }


  function resetSolutionView() {
    solutionView.classList.remove(
      "visible"
    );

    solutionTitle.textContent = "";
    solutionSummary.textContent = "";
    solutionSteps.replaceChildren();

    message.style.display = "";

    assistButton.style.display = "";
    assistButton.disabled = false;
    assistButton.textContent =
      "같이 보기";

    dismissButton.textContent =
      "괜찮아요";

    solutionLoading = false;
  }


  function renderSolution(payload) {
    const solution =
      payload?.solution || {};

    solutionTitle.textContent =
      solution.title ||
      "같이 확인해볼게요";

    solutionSummary.textContent =
      solution.summary || "";

    solutionSteps.replaceChildren();

    const steps =
      Array.isArray(solution.steps)
        ? solution.steps
        : [];


    steps.forEach(
      (step, index) => {
        const row =
          document.createElement("div");

        row.className =
          "ambient-solution-step";


        const number =
          document.createElement("div");

        number.className =
          "ambient-solution-number";

        number.textContent =
          String(index + 1).padStart(
            2,
            "0"
          );


        const body =
          document.createElement("div");

        body.className =
          "ambient-solution-step-body";

        body.textContent =
          step;


        row.appendChild(number);
        row.appendChild(body);

        solutionSteps.appendChild(row);
      }
    );


    message.style.display = "none";

    solutionView.classList.add(
      "visible"
    );

    assistButton.style.display = "";
    assistButton.disabled = false;
    assistButton.textContent =
      "도움됐어요";

    dismissButton.textContent =
      "아쉬워요";

    solutionLoading = false;


    console.log(
      "[Ambient Agent] Solution rendered:",
      payload
    );
  }


  function renderSolutionError(error) {
    console.error(
      "[Ambient Agent] Solution request failed:",
      error
    );


    solutionTitle.textContent =
      "지금은 해결 방법을 불러오지 못했어요.";

    solutionSummary.textContent =
      "잠시 후 다시 시도해 주세요.";

    solutionSteps.replaceChildren();

    message.style.display = "none";

    solutionView.classList.add(
      "visible"
    );


    assistButton.style.display = "";
    assistButton.disabled = false;
    assistButton.textContent =
      "다시 시도";

    dismissButton.textContent =
      "닫기";

    solutionLoading = false;
  }


  async function postFeedback(
    feedbackType
  ) {
    if (!currentIntervention) {
      console.warn(
        "[Ambient Agent] Feedback skipped: no current intervention."
      );

      return false;
    }


    try {
      const response =
        await fetch(
          "http://localhost:8000/sessions/current/feedback",
          {
            method: "POST",
            headers: {
              "Content-Type":
                "application/json"
            },
            body: JSON.stringify({
              feedback_type:
                feedbackType,
              intervention:
                currentIntervention
            })
          }
        );


      let payload = null;

      try {
        payload =
          await response.json();
      } catch (_) {
        payload = null;
      }


      if (!response.ok) {
        throw new Error(
          payload?.detail ||
          `Feedback request failed: ${response.status}`
        );
      }


      console.log(
        "[Ambient Agent] Feedback saved:",
        payload
      );

      return true;

    } catch (error) {
      console.error(
        "[Ambient Agent] Feedback request failed:",
        error
      );

      return false;
    }
  }


  async function requestSolution() {
    if (solutionLoading) {
      return;
    }


    solutionLoading = true;

    assistButton.disabled = true;
    assistButton.textContent =
      "해결 방법 찾는 중...";


    try {
      const response =
        await fetch(
          "http://localhost:8000/sessions/current/solution",
          {
            method: "POST",
            headers: {
              "Content-Type":
                "application/json"
            }
          }
        );


      let payload = null;

      try {
        payload =
          await response.json();
      } catch (_) {
        payload = null;
      }


      if (!response.ok) {
        throw new Error(
          payload?.detail ||
          `HTTP ${response.status}`
        );
      }


      if (
        !payload?.solution ||
        !Array.isArray(
          payload.solution.steps
        )
      ) {
        throw new Error(
          "Solution 응답 형식이 올바르지 않습니다."
        );
      }


      renderSolution(payload);

    } catch (error) {
      renderSolutionError(error);
    }
  }


  function showWhisper(
    intervention
  ) {
    currentIntervention =
      intervention;

    resetSolutionView();


    if (
      intervention?.context?.state
    ) {
      setAgentState(
        intervention.context.state
      );
    }


    message.textContent =
      buildWhisperMessage(
        intervention
      );


    presence.classList.add(
      "intervening"
    );


    requestAnimationFrame(
      () => {
        whisper.classList.add(
          "visible"
        );
      }
    );


    console.log(
      "[Ambient Agent] Whisper shown:",
      intervention
    );
  }


  function hideWhisper() {
    whisper.classList.remove(
      "visible"
    );

    presence.classList.remove(
      "intervening"
    );


    window.setTimeout(
      () => {
        currentIntervention =
          null;
      },
      650
    );
  }


  // ========================================================
  // Actions
  // ========================================================

  assistButton.addEventListener(
    "click",
    async () => {
      if (
        assistButton.textContent ===
        "도움됐어요"
      ) {
        await postFeedback(
          "helpful"
        );

        hideWhisper();

        return;
      }


      console.log(
        "[Ambient Agent] User requested assistance:",
        currentIntervention
      );


      // Feedback 저장 실패가
      // 실제 도움 제공을 막지는 않는다.
      await postFeedback(
        "accepted"
      );

      await requestSolution();
    }
  );


  dismissButton.addEventListener(
    "click",
    async () => {
      if (
        dismissButton.textContent ===
        "아쉬워요"
      ) {
        await postFeedback(
          "not_helpful"
        );

        hideWhisper();

        return;
      }


      if (
        dismissButton.textContent ===
        "닫기"
      ) {
        hideWhisper();

        return;
      }


      console.log(
        "[Ambient Agent] User dismissed intervention:",
        currentIntervention
      );


      await postFeedback(
        "dismissed"
      );

      hideWhisper();
    }
  );


  // ========================================================
  // Messages from background.js
  // ========================================================

  chrome.runtime.onMessage.addListener(
    (
      payload,
      sender,
      sendResponse
    ) => {
      if (!payload?.type) {
        return;
      }


      if (
        payload.type ===
        "AMBIENT_STATE_UPDATE"
      ) {
        setAgentState(
          payload.state
        );


        sendResponse({
          ok: true
        });

        return;
      }


      if (
        payload.type ===
        "AMBIENT_INTERVENTION"
      ) {
        showWhisper(
          payload.intervention
        );


        sendResponse({
          ok: true
        });

        return;
      }


      if (
        payload.type ===
        "AMBIENT_HIDE_INTERVENTION"
      ) {
        hideWhisper();


        sendResponse({
          ok: true
        });
      }
    }
  );


  console.log(
    "[Ambient Agent] Ambient Presence mounted."
  );
})();