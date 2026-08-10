import "./styles.css";

type World = {
  id: string;
  name: string;
  revision: number;
  description: string | null;
  source_scenario_id: string | null;
};

type Scenario = {
  id: string;
  title: string;
  description: string | null;
  created_at: string;
};

type Player = {
  id: string;
  world_id: string;
  kind: string;
  name: string;
  role: string;
  condition: string | null;
  disposition: string;
  location_id: string | null;
};

type EntitySummary = {
  id: string;
  kind: string;
  name: string;
  role: string | null;
  condition: string | null;
  disposition: string | null;
};

type Location = {
  id: string;
  world_id: string;
  name: string;
  description: string | null;
  revision: number;
  entities: EntitySummary[];
};

type WorldEvent = {
  id: string;
  event_type: string;
  actor_entity_id: string | null;
  summary: string;
  payload: Record<string, unknown>;
  world_revision: number;
  created_at: string;
};

type WorldMapLocation = {
  id: string;
  name: string;
  description: string | null;
  entity_kinds: Record<string, number>;
  linked_location_ids: string[];
};

type WorldMap = {
  world: World;
  player_location_id: string | null;
  locations: WorldMapLocation[];
};

type TurnResponse = {
  outcome: string;
  message: string | null;
  narration: string | null;
  revision_before: number | null;
  revision_after: number | null;
  attempts: number;
  mutation: Record<string, unknown> | null;
};

type WorldState = {
  world: World;
  player: Player;
  location: Location;
  events: WorldEvent[];
  map: WorldMap;
};

const POLL_INTERVAL_MS = 5_000;
const root = document.querySelector<HTMLDivElement>("#app");

if (root === null) {
  throw new Error("Application root is missing");
}

root.innerHTML = `
  <main class="app-shell">
    <header class="topbar">
      <div>
        <span class="eyebrow">Authoritative world state</span>
        <h1 class="brand-title">Mutable Realms</h1>
      </div>
      <div class="controls">
        <div class="view-toggle" role="group" aria-label="View">
          <button class="view-toggle-button is-active" id="view-play" type="button">Play</button>
          <button class="view-toggle-button" id="view-manage" type="button">Manage</button>
        </div>
        <label class="world-control">
          <span>World</span>
          <select id="world-select" aria-label="Select world"></select>
        </label>
        <span class="freshness" id="freshness">Not loaded</span>
        <button class="refresh-button" id="refresh" type="button">Refresh state</button>
      </div>
    </header>
    <div class="status-banner" id="status" role="alert" hidden></div>
    <section id="world-view" aria-live="polite"></section>
    <section class="panel narration-panel" id="narration-panel" aria-label="Narration">
      <div class="narration-heading">
        <div>
          <span class="eyebrow">Narration agent</span>
          <h2 class="section-title">What do you do?</h2>
        </div>
        <span class="revision-block" id="narration-revision"></span>
      </div>
      <div class="narration-log" id="narration-log" aria-live="polite"></div>
      <form class="action-form" id="action-form">
        <input
          class="action-input"
          id="action-input"
          type="text"
          placeholder="Type your action and press Enter…"
          autocomplete="off"
          aria-label="Your action"
        />
        <button class="action-button" id="action-submit" type="submit">Act</button>
      </form>
    </section>
    <section class="manage-view" id="manage-view" hidden aria-label="World management">
      <span class="eyebrow">World management</span>
      <h2 class="section-title">Scenarios</h2>
      <div class="manage-grid" id="scenario-list"></div>
      <h2 class="section-title">Worlds</h2>
      <div class="manage-grid" id="world-list"></div>
    </section>
  </main>
`;

const worldSelect = requireElement<HTMLSelectElement>("#world-select");
const refreshButton = requireElement<HTMLButtonElement>("#refresh");
const freshness = requireElement<HTMLSpanElement>("#freshness");
const statusBanner = requireElement<HTMLDivElement>("#status");
const worldView = requireElement<HTMLElement>("#world-view");
const narrationPanel = requireElement<HTMLElement>("#narration-panel");
const narrationLog = requireElement<HTMLDivElement>("#narration-log");
const narrationRevision = requireElement<HTMLSpanElement>("#narration-revision");
const actionForm = requireElement<HTMLFormElement>("#action-form");
const actionInput = requireElement<HTMLInputElement>("#action-input");
const actionSubmit = requireElement<HTMLButtonElement>("#action-submit");
const viewPlayButton = requireElement<HTMLButtonElement>("#view-play");
const viewManageButton = requireElement<HTMLButtonElement>("#view-manage");
const manageView = requireElement<HTMLElement>("#manage-view");
const scenarioList = requireElement<HTMLDivElement>("#scenario-list");
const worldList = requireElement<HTMLDivElement>("#world-list");

let worlds: World[] = [];
let selectedWorldId: string | null = null;
let currentPlayerId: string | null = null;
let loading = false;
let actionPending = false;
let manageLoading = false;
let lastUpdated: Date | null = null;

function requireElement<T extends Element>(selector: string): T {
  const element = root?.querySelector<T>(selector);
  if (element === null || element === undefined) {
    throw new Error(`Required element is missing: ${selector}`);
  }
  return element;
}

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className !== undefined) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

function appendNarration(role: "player" | "agent", text: string): void {
  const entry = element("div", `narration-entry narration-entry--${role}`);
  entry.append(element("span", "narration-role", role === "player" ? "You" : "Narrator"));
  entry.append(element("p", "narration-text", text));
  narrationLog.append(entry);
  while (narrationLog.childElementCount > 50) {
    narrationLog.firstElementChild?.remove();
  }
  narrationLog.scrollTop = narrationLog.scrollHeight;
}

async function loadWorlds(): Promise<void> {
  worlds = await fetchJson<World[]>("/api/worlds");
  worldSelect.replaceChildren(
    ...worlds.map((world) => {
      const option = document.createElement("option");
      option.value = world.id;
      option.textContent = `${world.name} (${world.id})`;
      return option;
    }),
  );

  if (worlds.length === 0) {
    selectedWorldId = null;
    throw new Error("No worlds exist in the authoritative database");
  }

  const requested = new URL(window.location.href).searchParams.get("world");
  selectedWorldId = worlds.some((world) => world.id === requested)
    ? requested
    : worlds[0].id;
  worldSelect.value = selectedWorldId ?? worlds[0].id;
}

async function loadState(): Promise<WorldState> {
  if (selectedWorldId === null) throw new Error("No world is selected");
  const encodedWorld = encodeURIComponent(selectedWorldId);
  const [player, location, events, map] = await Promise.all([
    fetchJson<Player>(`/api/worlds/${encodedWorld}/player`),
    fetchJson<Location>(`/api/worlds/${encodedWorld}/locations/current`),
    fetchJson<WorldEvent[]>(`/api/worlds/${encodedWorld}/events?limit=20`),
    fetchJson<WorldMap>(`/api/worlds/${encodedWorld}/map`),
  ]);
  const world = worlds.find((candidate) => candidate.id === selectedWorldId);
  if (world === undefined) throw new Error("Selected world is unavailable");
  return { world: { ...world, revision: location.revision }, player, location, events, map };
}

function renderEntity(entityState: EntitySummary, playerId: string): HTMLElement {
  const card = element("article", "entity-card");
  const heading = element("div", "entity-heading");
  heading.append(element("h3", "entity-name", entityState.name));
  const badges = element("div", "badges");
  badges.append(element("span", "badge kind", entityState.kind));
  if (entityState.id === playerId) badges.append(element("span", "badge player", "you"));
  heading.append(badges);
  card.append(heading, element("code", "entity-id", entityState.id));

  const details = [entityState.role, entityState.condition, entityState.disposition].filter(
    (value): value is string => value !== null,
  );
  if (details.length > 0) card.append(element("p", "entity-details", details.join(" · ")));
  return card;
}

const MAP_WIDTH = 480;
const MAP_HEIGHT = 320;
const MAP_CENTER_X = MAP_WIDTH / 2;
const MAP_CENTER_Y = MAP_HEIGHT / 2;
const MAP_RADIUS = 110;

const KIND_COLORS: Record<string, string> = {
  character: "#4f8cff",
  item: "#e8a23c",
  animal: "#57b96b",
};

function mapPositions(count: number): Array<[number, number]> {
  return Array.from({ length: count }, (_, index) => {
    const angle = (index / Math.max(count, 1)) * Math.PI * 2 - Math.PI / 2;
    return [
      MAP_CENTER_X + MAP_RADIUS * Math.cos(angle),
      MAP_CENTER_Y + MAP_RADIUS * Math.sin(angle),
    ];
  });
}

function svgElement(
  tag: string,
  attributes: Record<string, string | number>,
): SVGElement {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, String(value));
  }
  return node;
}

function renderMap(state: WorldState): HTMLElement {
  const panel = element("section", "panel map-panel");
  panel.append(
    element("span", "eyebrow", "Derived from world state"),
    element("h2", "section-title", `Map of ${state.world.name}`),
  );

  const svg = svgElement("svg", {
    viewBox: `0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`,
    class: "map-svg",
    role: "img",
    "aria-label": `Map of ${state.world.name}`,
  });

  const ordered = [...state.map.locations].sort((a, b) => a.name.localeCompare(b.name));
  const positions = new Map<string, [number, number]>();
  mapPositions(ordered.length).forEach((position, index) => {
    positions.set(ordered[index].id, position);
  });

  const drawnEdges = new Set<string>();
  for (const location of state.map.locations) {
    for (const linkedId of location.linked_location_ids) {
      const key = [location.id, linkedId].sort().join("|");
      if (drawnEdges.has(key)) continue;
      drawnEdges.add(key);
      const start = positions.get(location.id);
      const end = positions.get(linkedId);
      if (start === undefined || end === undefined) continue;
      svg.append(
        svgElement("line", {
          x1: start[0],
          y1: start[1],
          x2: end[0],
          y2: end[1],
          class: "map-edge",
        }),
      );
    }
  }

  for (const location of ordered) {
    const [x, y] = positions.get(location.id) ?? [MAP_CENTER_X, MAP_CENTER_Y];
    const playerHere = state.map.player_location_id === location.id;
    const group = svgElement("g", {
      class: playerHere ? "map-node map-node--player" : "map-node",
      transform: `translate(${x}, ${y})`,
    });
    group.append(
      svgElement("circle", { r: 20, class: "map-node-circle" }),
      svgElement("text", { y: 40, class: "map-label", "text-anchor": "middle" }),
    );
    if (playerHere) {
      group.append(svgElement("circle", { r: 27, class: "map-node-ring" }));
    }
    const label = group.querySelector("text");
    if (label !== null) label.textContent = location.name;

    const kinds = Object.entries(location.entity_kinds).sort(([a], [b]) =>
      a.localeCompare(b),
    );
    let glyphX = -((kinds.length - 1) * 16) / 2;
    for (const [kind, count] of kinds) {
      const glyph = svgElement("g", { transform: `translate(${glyphX}, 60)` });
      const color = KIND_COLORS[kind] ?? "#94a3b8";
      if (kind === "character") {
        glyph.append(svgElement("circle", { r: 5, fill: color }));
      } else if (kind === "item") {
        glyph.append(
          svgElement("rect", { x: -4, y: -4, width: 8, height: 8, fill: color, transform: "rotate(45)" }),
        );
      } else {
        glyph.append(
          svgElement("polygon", { points: "0,-5 5,4 -5,4", fill: color }),
        );
      }
      glyph.append(
        svgElement("text", { y: 4, class: "map-count", "text-anchor": "middle" }),
      );
      const countText = glyph.querySelector("text");
      if (countText !== null) countText.textContent = String(count);
      group.append(glyph);
      glyphX += 16;
    }

    svg.append(group);
  }

  panel.append(svg);
  return panel;
}

function renderState(state: WorldState): void {
  const locationPanel = element("section", "panel location-panel");
  const heading = element("div", "location-heading");
  const title = element("div");
  title.append(
    element("span", "eyebrow", state.world.name),
    element("h2", "location-name", state.location.name),
  );
  if (state.location.description !== null) {
    title.append(element("p", "location-description", state.location.description));
  }
  const revision = element("div", "revision-block");
  revision.append(element("strong", undefined, `r${state.location.revision}`));
  revision.append(element("span", undefined, "world revision"));
  heading.append(title, revision);

  const presence = element(
    "p",
    "player-presence",
    `${state.player.name} is currently at ${state.location.name}.`,
  );
  const entityHeading = element(
    "h2",
    "section-title",
    `Entities here (${state.location.entities.length})`,
  );
  const entityGrid = element("div", "entity-grid");
  if (state.location.entities.length === 0) {
    entityGrid.append(element("p", "empty-state", "This location contains no entities."));
  } else {
    entityGrid.append(
      ...state.location.entities.map((entityState) =>
        renderEntity(entityState, state.player.id),
      ),
    );
  }
  locationPanel.append(heading, presence, entityHeading, entityGrid);

  const eventsPanel = element("aside", "panel events-panel");
  eventsPanel.append(element("span", "eyebrow", "Persistent history"));
  eventsPanel.append(element("h2", "section-title", "Recent events"));
  if (state.events.length === 0) {
    eventsPanel.append(element("p", "empty-state", "No world-changing events yet."));
  } else {
    const eventList = element("ol", "event-list");
    eventList.append(
      ...state.events.map((worldEvent) => {
        const item = element("li", "event-item");
        item.append(element("p", "event-summary", worldEvent.summary));
        item.append(
          element(
            "span",
            "event-meta",
            `${worldEvent.event_type.replaceAll("_", " ")} · r${worldEvent.world_revision}`,
          ),
        );
        return item;
      }),
    );
    eventsPanel.append(eventList);
  }

  const layout = element("div", "content-grid");
  layout.append(locationPanel, eventsPanel);
  worldView.replaceChildren(renderMap(state), layout);
}

function setError(message: string | null): void {
  statusBanner.hidden = message === null;
  statusBanner.textContent = message ?? "";
}

function updateFreshness(): void {
  freshness.textContent =
    lastUpdated === null ? "Not loaded" : `Updated ${lastUpdated.toLocaleTimeString()}`;
}

async function refresh(): Promise<void> {
  if (loading) return;
  loading = true;
  refreshButton.disabled = true;
  worldSelect.disabled = true;
  setError(null);
  try {
    if (worlds.length === 0) await loadWorlds();
    const state = await loadState();
    currentPlayerId = state.player.id;
    narrationRevision.textContent = `r${state.location.revision}`;
    renderState(state);
    lastUpdated = new Date();
    updateFreshness();
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to read world state");
  } finally {
    loading = false;
    refreshButton.disabled = false;
    worldSelect.disabled = worlds.length === 0;
  }
}

async function runPlayerAction(action: string): Promise<void> {
  if (selectedWorldId === null || currentPlayerId === null) return;
  actionPending = true;
  actionInput.disabled = true;
  actionSubmit.disabled = true;
  appendNarration("player", action);
  setError(null);
  try {
    const encodedWorld = encodeURIComponent(selectedWorldId);
    const response = await postJson<TurnResponse>(
      `/api/worlds/${encodedWorld}/turns`,
      { player_id: currentPlayerId, player_action: action },
    );
    const narration = response.narration ?? response.message ?? response.outcome;
    appendNarration("agent", narration);
    if (response.revision_after !== null) {
      narrationRevision.textContent = `r${response.revision_after}`;
    }
    void refresh();
  } catch (error) {
    setError(error instanceof Error ? error.message : "The narration agent could not be reached");
  } finally {
    actionPending = false;
    actionInput.disabled = false;
    actionSubmit.disabled = false;
    actionInput.focus();
  }
}

actionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const action = actionInput.value.trim();
  if (action === "" || actionPending) return;
  actionInput.value = "";
  void runPlayerAction(action);
});

async function loadManage(): Promise<void> {
  if (manageLoading) return;
  manageLoading = true;
  setError(null);
  try {
    const [scenarios, allWorlds] = await Promise.all([
      fetchJson<Scenario[]>("/api/scenarios"),
      fetchJson<World[]>("/api/worlds"),
    ]);
    renderScenarioList(scenarios);
    renderWorldList(allWorlds);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to load management data");
  } finally {
    manageLoading = false;
  }
}

function renderScenarioList(scenarios: Scenario[]): void {
  scenarioList.replaceChildren();
  if (scenarios.length === 0) {
    scenarioList.append(
      element("p", "empty-state", "No scenarios yet. Create one from the management page."),
    );
    return;
  }
  for (const scenario of scenarios) {
    const card = element("article", "manage-card");
    card.append(element("h3", "manage-name", scenario.title));
    card.append(element("code", "manage-id", scenario.id));
    if (scenario.description !== null) {
      card.append(element("p", "manage-description", scenario.description));
    }
    card.append(element("span", "manage-meta", `created ${scenario.created_at}`));
    scenarioList.append(card);
  }
}

function renderWorldList(allWorlds: World[]): void {
  worldList.replaceChildren();
  if (allWorlds.length === 0) {
    worldList.append(element("p", "empty-state", "No worlds exist yet."));
    return;
  }
  for (const world of allWorlds) {
    const card = element("article", "manage-card");
    card.append(element("h3", "manage-name", world.name));
    card.append(element("code", "manage-id", world.id));
    card.append(element("span", "manage-meta", `revision ${world.revision}`));
    if (world.source_scenario_id !== null) {
      card.append(element("span", "manage-meta", `from scenario ${world.source_scenario_id}`));
    }
    if (world.description !== null) {
      card.append(element("p", "manage-description", world.description));
    }
    worldList.append(card);
  }
}

function setViewMode(mode: "play" | "manage"): void {
  const playActive = mode === "play";
  worldView.hidden = !playActive;
  narrationPanel.hidden = !playActive;
  manageView.hidden = playActive;
  viewPlayButton.classList.toggle("is-active", playActive);
  viewManageButton.classList.toggle("is-active", !playActive);
  if (!playActive) void loadManage();
}

viewPlayButton.addEventListener("click", () => setViewMode("play"));
viewManageButton.addEventListener("click", () => setViewMode("manage"));

worldSelect.addEventListener("change", () => {
  selectedWorldId = worldSelect.value;
  currentPlayerId = null;
  narrationLog.replaceChildren();
  narrationRevision.textContent = "";
  const url = new URL(window.location.href);
  url.searchParams.set("world", selectedWorldId);
  window.history.replaceState(null, "", url);
  void refresh();
});
refreshButton.addEventListener("click", () => void refresh());
window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
void refresh();
