(async () => {
  const teamId = __MOVA_TEAM_ID__;
  const origin = "https://fantasy.premierleague.com";
  const visible = (node) => Boolean(node && node.getClientRects().length > 0);
  const waitFor = async (predicate, code, timeoutMs = 2500) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const value = predicate();
      if (value) return value;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(code);
  };
  const checkboxByLabel = (label) => [...document.querySelectorAll('input[type="checkbox"]')]
    .find((node) => visible(node) && [...(node.labels || [])].some(
      (candidate) => (candidate.innerText || candidate.textContent || "").trim() === label,
  ));
  const closePlayerSheet = async () => {
    const buttons = [...document.querySelectorAll("button")].filter(visible);
    const close = buttons.find(
      (node) => (node.getAttribute("aria-label") || "").trim() === "Dismiss",
    ) || buttons.find(
      (node) => (node.getAttribute("aria-label") || "").trim() === "Close",
    );
    if (!close) throw new Error("FPL_PLAYER_SHEET_CLOSE_MISSING");
    close.click();
    await waitFor(
      () => !checkboxByLabel("Captain") && !checkboxByLabel("Vice Captain"),
      "FPL_PLAYER_SHEET_DID_NOT_CLOSE",
    );
  };
  if (location.origin !== origin || location.pathname !== "/en/my-team") {
    throw new Error("FPL_PICK_TEAM_PAGE_REQUIRED");
  }
  const [teamResponse, bootstrapResponse] = await Promise.all([
    fetch(`${origin}/api/my-team/${teamId}/`, {
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "application/json" },
    }),
    fetch(`${origin}/api/bootstrap-static/`, {
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json" },
    }),
  ]);
  if (teamResponse.status === 403) throw new Error("FPL_AUTH_REQUIRED");
  if (!teamResponse.ok || !bootstrapResponse.ok) {
    throw new Error(`FPL_API_ERROR team=${teamResponse.status} bootstrap=${bootstrapResponse.status}`);
  }
  const [team, bootstrap] = await Promise.all([
    teamResponse.json(), bootstrapResponse.json(),
  ]);
  if (checkboxByLabel("Captain") || checkboxByLabel("Vice Captain")) {
    await closePlayerSheet();
  }
  const players = new Map(bootstrap.elements.map((row) => [row.id, row.web_name]));
  const picks = [...(team.picks || [])].sort((a, b) => a.position - b.position);
  const playerButtons = [...document.querySelectorAll('button[data-pitch-element="true"]')]
    .filter((node) => node.getClientRects().length > 0);
  const switchButtons = [...document.querySelectorAll('button[aria-label="Switch player"]')]
    .filter((node) => node.getClientRects().length > 0);
  const signedIn = [...document.querySelectorAll("a")].some(
    (node) => node.textContent.trim() === "Sign Out" && node.getClientRects().length > 0,
  );
  const slots = picks.map((pick, index) => {
    const webName = players.get(pick.element) || null;
    const visibleLabel = (playerButtons[index]?.innerText || "").trim();
    return {
      position: pick.position,
      element: pick.element,
      web_name: webName,
      player_button_index: index,
      switch_button_index: index,
      label_matches: Boolean(webName && visibleLabel.includes(webName)),
    };
  });
  const checks = {
    signed_in: signedIn,
    fifteen_api_picks: picks.length === 15,
    fifteen_player_controls: playerButtons.length === 15,
    fifteen_switch_controls: switchButtons.length === 15,
    positional_order_matches: slots.length === 15 && slots.every((row) => row.label_matches),
  };
  const starterControls = [];
  for (let index = 0; index < Math.min(11, picks.length); index += 1) {
    const currentButtons = [...document.querySelectorAll('button[data-pitch-element="true"]')]
      .filter(visible);
    if (currentButtons.length !== 15) throw new Error("FPL_PLAYER_CONTROLS_CHANGED");
    currentButtons[index].click();
    const captain = await waitFor(
      () => checkboxByLabel("Captain"), "FPL_CAPTAIN_CHECKBOX_MISSING",
    );
    const vice = await waitFor(
      () => checkboxByLabel("Vice Captain"), "FPL_VICE_CAPTAIN_CHECKBOX_MISSING",
    );
    starterControls.push({
      position: picks[index].position,
      element: picks[index].element,
      player_button_index: index,
      captain_checkbox: true,
      vice_captain_checkbox: true,
      captain_checked: Boolean(captain.checked),
      vice_captain_checked: Boolean(vice.checked),
    });
    await closePlayerSheet();
  }
  const captainControlsChecks = {
    eleven_starter_sheets: starterControls.length === 11,
    semantic_checkboxes: starterControls.every(
      (row) => row.captain_checkbox && row.vice_captain_checkbox,
    ),
    one_captain: starterControls.filter((row) => row.captain_checked).length === 1,
    one_vice_captain: starterControls.filter((row) => row.vice_captain_checked).length === 1,
    captain_matches_api: starterControls.some(
      (row) => row.captain_checked && picks.find(
        (pick) => pick.element === row.element,
      )?.is_captain,
    ),
    vice_captain_matches_api: starterControls.some(
      (row) => row.vice_captain_checked && picks.find(
        (pick) => pick.element === row.element,
      )?.is_vice_captain,
    ),
  };
  checks.captain_controls = Object.values(captainControlsChecks).every(Boolean);
  return {
    schema: "mova-browser-dom-probe-v1",
    contract_version: "fpl-pick-team-a11y-2026.09.1",
    observed_at: new Date().toISOString(),
    team_id: teamId,
    status: Object.values(checks).every(Boolean) ? "pass" : "fail",
    checks,
    slots,
    captain_controls: {
      status: checks.captain_controls ? "pass" : "fail",
      selector_strategy: "player_button_index_then_accessible_checkbox",
      checks: captainControlsChecks,
      starters: starterControls,
    },
  };
})()
