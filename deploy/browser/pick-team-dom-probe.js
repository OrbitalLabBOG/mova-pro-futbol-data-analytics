(() => {
  const teamId = __MOVA_TEAM_ID__;
  const stage = __MOVA_PROBE_STAGE__;
  const expected = __MOVA_PROBE_EXPECTED__;
  const origin = "https://fantasy.premierleague.com";
  const visible = (node) => Boolean(node && node.getClientRects().length > 0);
  const checkboxByLabel = (label) => [...document.querySelectorAll('input[type="checkbox"]')]
    .find((node) => visible(node) && [...(node.labels || [])].some(
      (candidate) => (candidate.innerText || candidate.textContent || "").trim() === label,
    ));
  const waitFor = async (predicate, code, timeoutMs) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const value = predicate();
      if (value) return value;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(code);
  };
  const closePlayerSheet = async () => {
    const control = checkboxByLabel("Captain") || checkboxByLabel("Vice Captain");
    const scope = control?.closest('[role="dialog"]') || document;
    const buttons = [...scope.querySelectorAll("button")].filter(visible);
    let close = buttons.filter(n => (n.getAttribute("aria-label") || "").trim() === "Dismiss");
    if (!close.length) close = buttons.filter(n => (n.getAttribute("aria-label") || "").trim() === "Close");
    if (close.length !== 1) throw new Error("FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS");
    close[0].click();
    await waitFor(() => !checkboxByLabel("Captain") && !checkboxByLabel("Vice Captain"),
      "FPL_PLAYER_SHEET_DID_NOT_CLOSE", 5000);
  };
  if (stage === "diagnose") return (async () => {
    const fpl = location.origin === origin;
    const knownPath = ["/", "/en/", "/en/my-team"].includes(location.pathname);
    let privateStatus = null;
    if (fpl) {
      try { privateStatus = (await fetch(origin + "/api/my-team/" + teamId + "/", {
        credentials:"include",cache:"no-store",signal:AbortSignal.timeout(5000),
      })).status; } catch (_) { privateStatus = "unavailable"; }
    }
    return {fpl_origin:fpl,path:knownPath?location.pathname:"other",ready:document.readyState,
      pitch_controls:document.querySelectorAll('button[data-pitch-element="true"]').length,
      private_http_status:privateStatus};
  })();
  if (stage === "page_gate") {
    return {ready: location.origin === origin && location.pathname === "/en/my-team" &&
      ["interactive", "complete"].includes(document.readyState) &&
      [...document.querySelectorAll('button[data-pitch-element="true"]')].filter(visible).length === 15};
  }
  if (stage === "navigate") {
    if (location.origin !== origin) throw new Error("FPL_AUTH_OR_ORIGIN_REQUIRED");
    if (location.pathname !== "/en/my-team") {
      // Return before the read-only navigation destroys this evaluation context.
      setTimeout(() => location.assign(origin + "/en/my-team"), 0);
      return {navigation_requested:true};
    }
    return {navigation_requested:false};
  }
  if (location.origin !== origin || location.pathname !== "/en/my-team") {
    throw new Error("FPL_PICK_TEAM_PAGE_REQUIRED");
  }
  const privateTeam = async () => {
    const response = await fetch(origin + "/api/my-team/" + teamId + "/", {
      credentials: "include", cache: "no-store", headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(12000),
    });
    if (response.status === 403) throw new Error("FPL_AUTH_REQUIRED");
    if (!response.ok) throw new Error("FPL_PRIVATE_API_ERROR");
    return response.json();
  };
  const pickSignature = team => [...(team.picks || [])].sort((a,b) => a.position-b.position)
    .map(p => [p.element, p.position, Boolean(p.is_captain), Boolean(p.is_vice_captain)]);
  if (stage === "base") return (async () => {
    if (checkboxByLabel("Captain") || checkboxByLabel("Vice Captain")) await closePlayerSheet();
    const [team, response] = await Promise.all([
      privateTeam(), fetch(origin + "/api/bootstrap-static/", {
        credentials: "omit", cache: "no-store", headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(12000),
      }),
    ]);
    if (!response.ok) throw new Error("FPL_BOOTSTRAP_API_ERROR");
    const bootstrap = await response.json();
    const players = new Map(bootstrap.elements.map(row => [row.id, row.web_name]));
    const picks = [...(team.picks || [])].sort((a,b) => a.position-b.position);
    const buttons = [...document.querySelectorAll('button[data-pitch-element="true"]')].filter(visible);
    const switches = [...document.querySelectorAll('button[aria-label="Switch player"]')].filter(visible);
    const slots = picks.map((pick,index) => ({
      position: pick.position, element: pick.element, web_name: players.get(pick.element) || null,
      player_button_index: index, switch_button_index: index,
      label_matches: Boolean(players.get(pick.element) && (buttons[index]?.innerText || "").includes(players.get(pick.element))),
    }));
    return {slots, signature: pickSignature(team), checks: {
      signed_in: true, fifteen_api_picks: picks.length === 15,
      fifteen_player_controls: buttons.length === 15, fifteen_switch_controls: switches.length === 15,
      positional_order_matches: slots.length === 15 && slots.every(row => row.label_matches),
    }};
  })();
  if (stage === "open_sheet") {
    if (!Number.isInteger(expected.index) || expected.index < 0 || expected.index > 10) {
      throw new Error("FPL_STARTER_INDEX_INVALID");
    }
    const buttons = [...document.querySelectorAll('button[data-pitch-element="true"]')].filter(visible);
    if (buttons.length !== 15 || !(buttons[expected.index].innerText || "").includes(expected.web_name)) {
      throw new Error("FPL_PLAYER_CONTROLS_CHANGED");
    }
    buttons[expected.index].click();
    return {opened:true};
  }
  if (stage === "sheet_state") {
    const captain = checkboxByLabel("Captain"), vice = checkboxByLabel("Vice Captain");
    if (!captain || !vice) return {available:false};
    return {available:true,position: expected.index+1, element: expected.element,
      player_button_index: expected.index, captain_checkbox:true, vice_captain_checkbox:true,
      captain_checked:Boolean(captain.checked),vice_captain_checked:Boolean(vice.checked)};
  }
  if (stage === "close_sheet") {
    const control = checkboxByLabel("Captain") || checkboxByLabel("Vice Captain");
    const scope = control?.closest('[role="dialog"]') || document;
    const buttons = [...scope.querySelectorAll("button")].filter(visible);
    let close = buttons.filter(n => (n.getAttribute("aria-label") || "").trim() === "Dismiss");
    if (!close.length) close = buttons.filter(n => (n.getAttribute("aria-label") || "").trim() === "Close");
    if (close.length !== 1) throw new Error("FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS");
    close[0].click();
    return {close_requested:true};
  }
  if (stage === "sheet_closed") {
    return {closed:!checkboxByLabel("Captain") && !checkboxByLabel("Vice Captain")};
  }
  if (stage === "verify") return (async () => {
    const team = await privateTeam();
    if (JSON.stringify(pickSignature(team)) !== JSON.stringify(expected.signature)) {
      throw new Error("FPL_TEAM_CHANGED_DURING_PROBE");
    }
    const buttons = [...document.querySelectorAll('button[data-pitch-element="true"]')].filter(visible);
    if (buttons.length !== 15 || !expected.slots.every((row,index) =>
      (buttons[index].innerText || "").includes(row.web_name))) throw new Error("FPL_PLAYER_CONTROLS_CHANGED");
    return {unchanged:true};
  })();
  throw new Error("FPL_PROBE_STAGE_INVALID");
})()
