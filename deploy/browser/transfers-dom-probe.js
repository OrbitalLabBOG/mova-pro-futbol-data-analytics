(async () => {
  const teamId = __MOVA_TEAM_ID__;
  const targetIds = __MOVA_TARGET_ELEMENTS__;
  const origin = "https://fantasy.premierleague.com";
  const visible = (node) => Boolean(node && node.getClientRects().length > 0);
  const text = (node) => (node?.innerText || node?.textContent || "").trim();
  const visibleButtons = () => [...document.querySelectorAll("button")].filter(visible);
  if (location.origin !== origin || location.pathname !== "/en/transfers") {
    throw new Error("FPL_TRANSFERS_PAGE_REQUIRED");
  }
  if (!Array.isArray(targetIds) || targetIds.some(
    (value) => !Number.isInteger(value) || value <= 0,
  ) || new Set(targetIds).size !== targetIds.length) {
    throw new Error("MOVA_TARGET_ELEMENTS_INVALID");
  }
  const [teamResponse, bootstrapResponse] = await Promise.all([
    fetch(`${origin}/api/my-team/${teamId}/`, {
      credentials: "include", cache: "no-store", headers: { Accept: "application/json" },
    }),
    fetch(`${origin}/api/bootstrap-static/`, {
      credentials: "omit", cache: "no-store", headers: { Accept: "application/json" },
    }),
  ]);
  if (teamResponse.status === 403) throw new Error("FPL_AUTH_REQUIRED");
  if (!teamResponse.ok || !bootstrapResponse.ok) {
    throw new Error(`FPL_API_ERROR team=${teamResponse.status} bootstrap=${bootstrapResponse.status}`);
  }
  const [team, bootstrap] = await Promise.all([teamResponse.json(), bootstrapResponse.json()]);
  const elements = new Map(bootstrap.elements.map((row) => [row.id, row]));
  const teams = new Map(bootstrap.teams.map((row) => [row.id, row.short_name || row.name]));
  const picks = [...(team.picks || [])].sort((a, b) => a.position - b.position);
  const removeButtons = visibleButtons().filter((node) => (
    (node.getAttribute("aria-label") || "").trim() === "Remove player"
    || text(node) === "Remove player"
  ));
  const signedIn = [...document.querySelectorAll("a")].some(
    (node) => visible(node) && text(node) === "Sign Out",
  );
  const buttonNames = new Set(visibleButtons().map((node) => (
    (node.getAttribute("aria-label") || "").trim() || text(node)
  )));
  const search = [...document.querySelectorAll('input[type="search"], input[role="searchbox"]')]
    .find((node) => visible(node) && (
      (node.getAttribute("aria-label") || "").trim() === "Find a player"
      || (node.getAttribute("placeholder") || "").trim() === "Find a player"
    ));
  const squad = picks.map((pick) => ({
    element: pick.element,
    position: pick.position,
    web_name: elements.get(pick.element)?.web_name || null,
  }));
  const targets = targetIds.map((element) => {
    const row = elements.get(element);
    return row ? {
      element: row.id, element_type: row.element_type, web_name: row.web_name,
      team: teams.get(row.team) || null, price: row.now_cost,
    } : null;
  }).filter(Boolean);
  const checks = {
    signed_in: signedIn,
    fifteen_api_picks: picks.length === 15,
    squad_remove_controls_present: removeButtons.length >= 15,
    squad_labels_complete: squad.every((row) => Boolean(row.web_name)),
    targets_complete: targets.length === targetIds.length,
    make_transfers: buttonNames.has("Make Transfers"),
    player_search: Boolean(search),
    wildcard: buttonNames.has("Wildcard Play"),
    free_hit: buttonNames.has("Free Hit Play"),
  };
  return {
    schema: "mova-browser-transfer-dom-probe-v1",
    contract_version: "fpl-transfers-a11y-2026.08.1",
    observed_at: new Date().toISOString(),
    team_id: teamId,
    status: Object.values(checks).every(Boolean) ? "pass" : "fail",
    checks,
    squad,
    targets,
    controls: {
      make_transfers: buttonNames.has("Make Transfers") ? "Make Transfers" : null,
      player_search: search ? "Find a player" : null,
      chip_buttons: ["Wildcard Play", "Free Hit Play"].filter((name) => buttonNames.has(name)),
    },
  };
})()
