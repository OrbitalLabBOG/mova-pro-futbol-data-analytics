(async () => {
  const teamId = __MOVA_TEAM_ID__;
  const origin = "https://fantasy.premierleague.com";
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
  return {
    schema: "mova-browser-dom-probe-v1",
    contract_version: "fpl-pick-team-a11y-2026.08",
    observed_at: new Date().toISOString(),
    team_id: teamId,
    status: Object.values(checks).every(Boolean) ? "pass" : "fail",
    checks,
    slots,
  };
})()
