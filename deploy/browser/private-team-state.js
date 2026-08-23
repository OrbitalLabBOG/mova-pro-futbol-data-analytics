(async () => {
  const teamId = __MOVA_TEAM_ID__;
  const origin = "https://fantasy.premierleague.com";
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

  if (teamResponse.status === 403) {
    throw new Error("FPL_AUTH_REQUIRED");
  }
  if (!teamResponse.ok || !bootstrapResponse.ok) {
    throw new Error(
      `FPL_API_ERROR team=${teamResponse.status} bootstrap=${bootstrapResponse.status}`,
    );
  }

  const [team, bootstrap] = await Promise.all([
    teamResponse.json(),
    bootstrapResponse.json(),
  ]);
  const now = new Date();
  const event =
    bootstrap.events.find((item) => item.is_next) ||
    bootstrap.events
      .filter((item) => item.deadline_time && new Date(item.deadline_time) > now)
      .sort((a, b) => new Date(a.deadline_time) - new Date(b.deadline_time))[0] ||
    bootstrap.events.find((item) => item.is_current);
  if (!event) throw new Error("FPL_EVENT_NOT_FOUND");

  // Explicit allowlist: credentials, cookies, storage and personal profile fields
  // never cross the browser boundary.
  return {
    schema: "mova-fpl-private-team-state-v1",
    observed_at: now.toISOString(),
    team_id: teamId,
    event: { id: event.id, deadline_time: event.deadline_time },
    picks_last_updated: team.picks_last_updated || null,
    picks: (team.picks || []).map((pick) => ({
      element: pick.element,
      element_type: pick.element_type,
      position: pick.position,
      multiplier: pick.multiplier,
      is_captain: Boolean(pick.is_captain),
      is_vice_captain: Boolean(pick.is_vice_captain),
      purchase_price: pick.purchase_price,
      selling_price: pick.selling_price,
    })),
    transfers: {
      bank: team.transfers?.bank,
      value: team.transfers?.value,
      limit: team.transfers?.limit,
      made: team.transfers?.made,
      cost: team.transfers?.cost,
      status: team.transfers?.status,
    },
    chips: (team.chips || []).map((chip) => ({
      name: chip.name,
      number: chip.number,
      status_for_entry: chip.status_for_entry,
      is_pending: Boolean(chip.is_pending),
      start_event: chip.start_event,
      stop_event: chip.stop_event,
    })),
  };
})()
