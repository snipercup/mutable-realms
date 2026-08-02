import "./styles.css";

type World = {
  id: string;
  name: string;
  revision: number;
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

type WorldState = {
  world: World;
  player: Player;
  location: Location;
  events: WorldEvent[];
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
  </main>
`;

const worldSelect = requireElement<HTMLSelectElement>("#world-select");
const refreshButton = requireElement<HTMLButtonElement>("#refresh");
const freshness = requireElement<HTMLSpanElement>("#freshness");
const statusBanner = requireElement<HTMLDivElement>("#status");
const worldView = requireElement<HTMLElement>("#world-view");

let worlds: World[] = [];
let selectedWorldId: string | null = null;
let loading = false;
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
  const [player, location, events] = await Promise.all([
    fetchJson<Player>(`/api/worlds/${encodedWorld}/player`),
    fetchJson<Location>(`/api/worlds/${encodedWorld}/locations/current`),
    fetchJson<WorldEvent[]>(`/api/worlds/${encodedWorld}/events?limit=20`),
  ]);
  const world = worlds.find((candidate) => candidate.id === selectedWorldId);
  if (world === undefined) throw new Error("Selected world is unavailable");
  return { world: { ...world, revision: location.revision }, player, location, events };
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
  worldView.replaceChildren(layout);
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
    renderState(await loadState());
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

worldSelect.addEventListener("change", () => {
  selectedWorldId = worldSelect.value;
  const url = new URL(window.location.href);
  url.searchParams.set("world", selectedWorldId);
  window.history.replaceState(null, "", url);
  void refresh();
});
refreshButton.addEventListener("click", () => void refresh());
window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
void refresh();
