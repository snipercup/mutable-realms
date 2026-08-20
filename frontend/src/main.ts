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

type ScenarioElement = {
  element_type: string;
  content: string;
  updated_at: string;
};

type ScenarioDetail = Scenario & {
  elements: ScenarioElement[];
};

type PlayerCharacter = {
  id: string;
  name: string;
  basic_info: string | null;
  created_at: string;
};

type WorldDetail = World & {
  elements: ScenarioElement[];
  player: PlayerSummary | null;
};

type PlayerSummary = {
  id: string;
  name: string;
  basic_info: string | null;
  character_definition_id: string | null;
  location_id: string | null;
  location_name: string | null;
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
  kind: string | null;
  is_map_scope: boolean;
  is_default_scope: boolean;
  is_neighbor: boolean;
  geography_role: string;
  direction: string | null;
  range_band: string | null;
  map_form: string | null;
  child_count: number;
  entity_kinds: Record<string, number>;
  linked_location_ids: string[];
};

type WorldMapBreadcrumb = {
  id: string;
  name: string;
  kind: string | null;
  is_map_scope: boolean;
  is_default_scope: boolean;
  map_form: string | null;
};

type WorldMapBoundaryLink = {
  from_location_id: string;
  to_location_id: string;
  to_location_name: string;
};

type WorldMapRoute = {
  route_id: string;
  chain_depth: number;
  name: string;
  description: string | null;
  route_kind: string;
  origin_location_id: string;
  destination_location_id: string;
  destination_name: string;
  geography_role: string;
  direction: string | null;
  range_band: string | null;
};

type WorldMap = {
  world: World;
  player_location_id: string | null;
  player_visible_location_id: string | null;
  scope_location: WorldMapBreadcrumb | null;
  breadcrumbs: WorldMapBreadcrumb[];
  child_total: number;
  has_more: boolean;
  boundary_links: WorldMapBoundaryLink[];
  route_chain: WorldMapRoute[];
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

type WorldStartResponse = {
  outcome: string;
  narration: string;
  world_id: string;
  character_id: string;
  player_id: string;
  location_id: string;
  location_name: string;
  revision_before: number;
  revision_after: number;
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
      <h2 class="section-title">Player characters</h2>
      <form class="manage-form" id="character-create-form">
        <input class="manage-input" id="character-create-id" placeholder="character id (kebab-case)" aria-label="Character id" required />
        <input class="manage-input" id="character-create-name" placeholder="Name" aria-label="Character name" required />
        <input class="manage-input" id="character-create-info" placeholder="Basic info (optional)" aria-label="Character basic info" />
        <button class="manage-button" type="submit">Create character</button>
      </form>
      <div class="manage-grid" id="character-list"></div>
      <div class="scenario-editor" id="character-editor" hidden>
        <div class="scenario-editor-heading">
          <h3 class="section-title" id="character-editor-name">Player character</h3>
          <button class="manage-button manage-button--ghost" id="character-editor-close" type="button">Close</button>
        </div>
        <label class="manage-field">Name<input class="manage-input" id="character-edit-name" /></label>
        <label class="manage-field">Basic info<textarea class="manage-textarea" id="character-edit-info"></textarea></label>
        <button class="manage-button" id="character-edit-save" type="button">Save character</button>
        <button class="manage-button manage-button--danger" id="character-delete" type="button">Delete character</button>
      </div>
      <h2 class="section-title">Scenarios</h2>
      <form class="manage-form" id="scenario-create-form">
        <input
          class="manage-input"
          id="scenario-create-id"
          placeholder="scenario id (kebab-case)"
          aria-label="Scenario id"
          required
        />
        <input
          class="manage-input"
          id="scenario-create-title"
          placeholder="Title"
          aria-label="Scenario title"
          required
        />
        <input
          class="manage-input"
          id="scenario-create-description"
          placeholder="Description (optional)"
          aria-label="Scenario description"
        />
        <button class="manage-button" type="submit">Create scenario</button>
      </form>
      <div class="manage-grid" id="scenario-list"></div>
      <div class="scenario-editor" id="scenario-editor" hidden>
        <div class="scenario-editor-heading">
          <h3 class="section-title" id="scenario-editor-name">Scenario</h3>
          <button class="manage-button manage-button--ghost" id="scenario-editor-close" type="button">Close</button>
        </div>
        <label class="manage-field">
          Title
          <input class="manage-input" id="scenario-edit-title" />
        </label>
        <label class="manage-field">
          Description
          <textarea class="manage-textarea" id="scenario-edit-description"></textarea>
        </label>
        <button class="manage-button" id="scenario-edit-save" type="button">Save title &amp; description</button>
        <div class="scenario-elements">
          <span class="eyebrow">Story elements</span>
          <label class="manage-field">
            Author's note
            <textarea class="manage-textarea" id="scenario-element-author_note"></textarea>
            <button class="manage-button" data-element-save="author_note" type="button">Save note</button>
          </label>
          <label class="manage-field">
            Plot essentials
            <textarea class="manage-textarea" id="scenario-element-plot_essentials"></textarea>
            <button class="manage-button" data-element-save="plot_essentials" type="button">Save</button>
          </label>
          <label class="manage-field">
            Opening scene
            <textarea class="manage-textarea" id="scenario-element-opening_scene"></textarea>
            <button class="manage-button" data-element-save="opening_scene" type="button">Save</button>
          </label>
        </div>
        <button class="manage-button manage-button--danger" id="scenario-delete" type="button">Delete scenario</button>
      </div>
      <h2 class="section-title">Worlds</h2>
      <form class="manage-form" id="world-create-form">
        <select class="manage-input" id="world-create-scenario" aria-label="Scenario to instance">
          <option value="">Select a scenario…</option>
        </select>
        <input
          class="manage-input"
          id="world-create-id"
          placeholder="world id (kebab-case)"
          aria-label="World id"
          required
        />
        <button class="manage-button" id="world-create-submit" type="submit">Instance world</button>
      </form>
      <div class="manage-grid" id="world-list"></div>
      <div class="scenario-editor" id="world-editor" hidden>
        <div class="scenario-editor-heading">
          <div>
            <h3 class="section-title" id="world-editor-name">World</h3>
            <span class="manage-meta" id="world-editor-revision"></span>
          </div>
          <button class="manage-button manage-button--ghost" id="world-editor-close" type="button">Close</button>
        </div>
        <label class="manage-field">
          Name (title)
          <input class="manage-input" id="world-edit-name" />
        </label>
        <label class="manage-field">
          Description
          <textarea class="manage-textarea" id="world-edit-description"></textarea>
        </label>
        <button class="manage-button" id="world-edit-save" type="button">Save name &amp; description</button>
        <div class="scenario-elements">
          <span class="eyebrow">Story elements</span>
          <label class="manage-field">
            Author's note
            <textarea class="manage-textarea" id="world-element-author_note"></textarea>
            <button class="manage-button" data-world-element-save="author_note" type="button">Save note</button>
          </label>
          <label class="manage-field">
            Plot essentials
            <textarea class="manage-textarea" id="world-element-plot_essentials"></textarea>
            <button class="manage-button" data-world-element-save="plot_essentials" type="button">Save</button>
          </label>
          <label class="manage-field">
            Opening scene
            <textarea class="manage-textarea" id="world-element-opening_scene"></textarea>
            <button class="manage-button" data-world-element-save="opening_scene" type="button">Save</button>
          </label>
        </div>
        <div class="scenario-elements">
          <span class="eyebrow">Player</span>
          <div id="world-player-info"></div>
          <form class="manage-form" id="world-player-form">
            <select class="manage-input" id="world-player-character" aria-label="Player character">
              <option value="">Select a player character…</option>
            </select>
            <input
              class="manage-input"
              id="world-player-location"
              placeholder="Starting location (e.g. Settlement)"
              aria-label="Starting location"
              required
            />
            <button class="manage-button" id="world-player-submit" type="submit">Instance character</button>
          </form>
        </div>
        <button class="manage-button manage-button--danger" id="world-delete" type="button">Delete world</button>
      </div>
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
const characterList = requireElement<HTMLDivElement>("#character-list");
const characterCreateForm = requireElement<HTMLFormElement>("#character-create-form");
const characterCreateId = requireElement<HTMLInputElement>("#character-create-id");
const characterCreateName = requireElement<HTMLInputElement>("#character-create-name");
const characterCreateInfo = requireElement<HTMLInputElement>("#character-create-info");
const characterEditor = requireElement<HTMLDivElement>("#character-editor");
const characterEditorName = requireElement<HTMLElement>("#character-editor-name");
const characterEditorClose = requireElement<HTMLButtonElement>("#character-editor-close");
const characterEditName = requireElement<HTMLInputElement>("#character-edit-name");
const characterEditInfo = requireElement<HTMLTextAreaElement>("#character-edit-info");
const characterEditSave = requireElement<HTMLButtonElement>("#character-edit-save");
const characterDelete = requireElement<HTMLButtonElement>("#character-delete");
const scenarioList = requireElement<HTMLDivElement>("#scenario-list");
const worldList = requireElement<HTMLDivElement>("#world-list");
const scenarioCreateForm = requireElement<HTMLFormElement>("#scenario-create-form");
const scenarioCreateId = requireElement<HTMLInputElement>("#scenario-create-id");
const scenarioCreateTitle = requireElement<HTMLInputElement>("#scenario-create-title");
const scenarioCreateDescription = requireElement<HTMLInputElement>("#scenario-create-description");
const scenarioEditor = requireElement<HTMLDivElement>("#scenario-editor");
const scenarioEditorName = requireElement<HTMLElement>("#scenario-editor-name");
const scenarioEditTitle = requireElement<HTMLInputElement>("#scenario-edit-title");
const scenarioEditDescription = requireElement<HTMLTextAreaElement>("#scenario-edit-description");
const scenarioEditSave = requireElement<HTMLButtonElement>("#scenario-edit-save");
const scenarioEditorClose = requireElement<HTMLButtonElement>("#scenario-editor-close");
const scenarioDelete = requireElement<HTMLButtonElement>("#scenario-delete");
const worldCreateForm = requireElement<HTMLFormElement>("#world-create-form");
const worldCreateScenario = requireElement<HTMLSelectElement>("#world-create-scenario");
const worldCreateId = requireElement<HTMLInputElement>("#world-create-id");
const worldCreateSubmit = requireElement<HTMLButtonElement>("#world-create-submit");
const worldEditor = requireElement<HTMLDivElement>("#world-editor");
const worldEditorName = requireElement<HTMLElement>("#world-editor-name");
const worldEditorRevision = requireElement<HTMLElement>("#world-editor-revision");
const worldEditName = requireElement<HTMLInputElement>("#world-edit-name");
const worldEditDescription = requireElement<HTMLTextAreaElement>("#world-edit-description");
const worldEditSave = requireElement<HTMLButtonElement>("#world-edit-save");
const worldEditorClose = requireElement<HTMLButtonElement>("#world-editor-close");
const worldDelete = requireElement<HTMLButtonElement>("#world-delete");
const worldPlayerInfo = requireElement<HTMLDivElement>("#world-player-info");
const worldPlayerForm = requireElement<HTMLFormElement>("#world-player-form");
const worldPlayerCharacter = requireElement<HTMLSelectElement>("#world-player-character");
const worldPlayerLocation = requireElement<HTMLInputElement>("#world-player-location");

let worlds: World[] = [];
let playerCharacters: PlayerCharacter[] = [];
let selectedWorldId: string | null = null;
let selectedMapScopeId: string | null = null;
let currentPlayerId: string | null = null;
let loading = false;
let actionPending = false;
let startPending = false;
let startError: string | null = null;
let manageLoading = false;
let editingScenarioId: string | null = null;
let editingWorldId: string | null = null;
let editingWorldRevision = 0;
let manageBusy = false;
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

async function requestJson<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
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

  const requested =
    new URL(window.location.href).searchParams.get("world") ?? worldSelect.value;
  selectedWorldId = worlds.some((world) => world.id === requested)
    ? requested
    : worlds[0].id;
  worldSelect.value = selectedWorldId ?? worlds[0].id;
}

async function loadState(): Promise<WorldState> {
  if (selectedWorldId === null) throw new Error("No world is selected");
  const encodedWorld = encodeURIComponent(selectedWorldId);
  const mapScopeQuery =
    selectedMapScopeId === null
      ? ""
      : `?scope_location_id=${encodeURIComponent(selectedMapScopeId)}`;
  const [player, location, events, map] = await Promise.all([
    fetchJson<Player>(`/api/worlds/${encodedWorld}/player`),
    fetchJson<Location>(`/api/worlds/${encodedWorld}/locations/current`),
    fetchJson<WorldEvent[]>(`/api/worlds/${encodedWorld}/events?limit=20`),
    fetchJson<WorldMap>(`/api/worlds/${encodedWorld}/map${mapScopeQuery}`),
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
const MAP_HEIGHT = 640;
const MAP_RENDER_LIMIT = 30;
const MAP_CENTER_X = MAP_WIDTH / 2;
const MAP_CENTER_Y = MAP_HEIGHT / 2;
const MAP_RADIUS = 110;
const MAP_CHILD_RADIUS = 66;
const MAP_BORDER_RADIUS = 140;
const MAP_BORDER_NODE_RADIUS = 14;

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

const MAP_DIRECTION_VECTORS: Record<string, [number, number]> = {
  north: [0, -1],
  northeast: [0.707, -0.707],
  east: [1, 0],
  southeast: [0.707, 0.707],
  south: [0, 1],
  southwest: [-0.707, 0.707],
  west: [-1, 0],
  northwest: [-0.707, -0.707],
};

const MAP_RANGE_RADIUS: Record<string, number> = { short: 72, mid: 108, long: 140 };

function orientedMapPositions(locations: WorldMapLocation[]): Map<string, [number, number]> {
  const positions = new Map<string, [number, number]>();
  const fallback = mapPositions(locations.length);
  const occupied = new Map<string, number>();
  locations.forEach((location, index) => {
    const vector = location.direction === null ? undefined : MAP_DIRECTION_VECTORS[location.direction];
    if (vector === undefined) {
      positions.set(location.id, fallback[index]);
      return;
    }
    const range = MAP_RANGE_RADIUS[location.range_band ?? ""] ?? MAP_RADIUS;
    const bucket = `${location.direction}:${location.range_band ?? "unspecified"}`;
    const collisionIndex = occupied.get(bucket) ?? 0;
    occupied.set(bucket, collisionIndex + 1);
    const perpendicular: [number, number] = [-vector[1], vector[0]];
    const offset = (collisionIndex - 0.5) * 28;
    positions.set(location.id, [
      MAP_CENTER_X + vector[0] * range + perpendicular[0] * offset,
      MAP_CENTER_Y + vector[1] * range + perpendicular[1] * offset,
    ]);
  });
  return positions;
}

function centerMapPositions(locations: WorldMapLocation[]): Map<string, [number, number]> {
  const positions = new Map<string, [number, number]>();
  const fallback = mapPositions(locations.length).map(([x, y]) => [
    MAP_CENTER_X + ((x - MAP_CENTER_X) * MAP_CHILD_RADIUS) / MAP_RADIUS,
    MAP_CENTER_Y + ((y - MAP_CENTER_Y) * MAP_CHILD_RADIUS) / MAP_RADIUS,
  ] as [number, number]);
  locations.forEach((location, index) => positions.set(location.id, fallback[index]));
  return positions;
}

function streetMapPositions(locations: WorldMapLocation[]): Map<string, [number, number]> {
  const positions = new Map<string, [number, number]>();
  const rowGap = Math.max(42, Math.min(58, 480 / Math.max(locations.length, 1)));
  const startY = MAP_CENTER_Y - ((locations.length - 1) * rowGap) / 2;
  locations.forEach((location, index) => {
    const side = index % 2 === 0 ? -1 : 1;
    const y = startY + Math.floor(index / 2) * rowGap;
    positions.set(location.id, [MAP_CENTER_X + side * 72, y]);
  });
  return positions;
}

function perimeterMapPositions(locations: WorldMapLocation[]): Map<string, [number, number]> {
  const positions = new Map<string, [number, number]>();
  const fallback = mapPositions(locations.length).map(([x, y]) => [
    MAP_CENTER_X + ((x - MAP_CENTER_X) * MAP_BORDER_RADIUS) / MAP_RADIUS,
    MAP_CENTER_Y + ((y - MAP_CENTER_Y) * MAP_BORDER_RADIUS) / MAP_RADIUS,
  ] as [number, number]);
  const directional = new Map<string, number>();
  locations.forEach((location, index) => {
    const direction = location.direction;
    const vector = direction === null ? undefined : MAP_DIRECTION_VECTORS[direction];
    if (direction === null || vector === undefined) {
      positions.set(location.id, fallback[index]);
      return;
    }
    const collisionIndex = directional.get(direction) ?? 0;
    directional.set(direction, collisionIndex + 1);
    const perpendicular: [number, number] = [-vector[1], vector[0]];
    const offset = (collisionIndex - 0.5) * 26;
    positions.set(location.id, [
      MAP_CENTER_X + vector[0] * MAP_BORDER_RADIUS + perpendicular[0] * offset,
      MAP_CENTER_Y + vector[1] * MAP_BORDER_RADIUS + perpendicular[1] * offset,
    ]);
  });
  return positions;
}

function edgeMapPositions(locations: WorldMapLocation[]): Map<string, [number, number]> {
  const positions = new Map<string, [number, number]>();
  const edgeInset = 26;
  const slots = new Map<string, number>();
  const fallback = mapPositions(locations.length).map(([x, y]) => [
    x < MAP_CENTER_X ? edgeInset : MAP_WIDTH - edgeInset,
    y < MAP_CENTER_Y ? edgeInset : MAP_HEIGHT - edgeInset,
  ] as [number, number]);
  locations.forEach((location, index) => {
    const direction = location.direction;
    if (direction === null || MAP_DIRECTION_VECTORS[direction] === undefined) {
      positions.set(location.id, fallback[index]);
      return;
    }
    const slot = slots.get(direction) ?? 0;
    slots.set(direction, slot + 1);
    const offset = (slot - 0.5) * 34;
    const [vx, vy] = MAP_DIRECTION_VECTORS[direction];
    let x = MAP_CENTER_X;
    let y = MAP_CENTER_Y;
    if (vy < 0) y = edgeInset;
    if (vy > 0) y = MAP_HEIGHT - edgeInset;
    if (vx < 0) x = edgeInset;
    if (vx > 0) x = MAP_WIDTH - edgeInset;
    if (vy === 0) y += offset;
    else if (vx === 0) x += offset;
    else {
      x += vx * offset;
      y += vy * offset;
    }
    positions.set(location.id, [x, y]);
  });
  return positions;
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

function mapShape(location: WorldMapLocation, isSibling: boolean): SVGElement {
  const form = location.map_form ?? (location.is_neighbor ? "landmark" : "building");
  const size = isSibling ? 14 : 20;
  const attributes = { class: "map-node-shape", "data-map-form": form };
  if (form === "building") {
    return svgElement("rect", { ...attributes, x: -size, y: -size * 0.7, width: size * 2, height: size * 1.4, rx: 2 });
  }
  if (form === "street") {
    return svgElement("path", { ...attributes, d: `M ${-size} ${size * 0.45} L ${size} ${-size * 0.45} L ${size} ${size * 0.45} L ${-size} ${-size * 0.45} Z` });
  }
  if (form === "district" || form === "city") {
    return svgElement("polygon", { ...attributes, points: `0,${-size} ${size},${-size * 0.35} ${size * 0.65},${size} ${-size * 0.65},${size} ${-size},${-size * 0.35}` });
  }
  if (form === "mine") {
    return svgElement("path", { ...attributes, d: `M ${-size} ${size} L 0 ${-size} L ${size} ${size} Z M ${-size * 0.35} ${size} L ${-size * 0.35} ${size * 0.1} L ${size * 0.35} ${size * 0.1} L ${size * 0.35} ${size} Z` });
  }
  if (form === "forest") {
    return svgElement("path", { ...attributes, d: `M 0 ${-size} L ${size * 0.65} ${size * 0.1} L ${size * 0.3} ${size * 0.1} L ${size} ${size} L 0 ${size * 0.55} L ${-size} ${size} L ${-size * 0.3} ${size * 0.1} L ${-size * 0.65} ${size * 0.1} Z` });
  }
  if (form === "water") {
    return svgElement("path", { ...attributes, d: `M ${-size} 0 Q ${-size * 0.5} ${-size * 0.5} 0 0 T ${size} 0 M ${-size} ${size * 0.5} Q ${-size * 0.5} 0 0 ${size * 0.5} T ${size} ${size * 0.5}` });
  }
  return svgElement("circle", { ...attributes, r: size });
}

function renderMap(state: WorldState): HTMLElement {
  const panel = element("section", "panel map-panel");
  const scopeName = state.map.scope_location?.name ?? state.world.name;
  panel.append(element("h2", "section-title", `Map of ${scopeName}`));

  if (state.map.scope_location !== null && state.map.breadcrumbs.length > 0) {
    const navigation = element("nav", "map-scope-nav");
    navigation.setAttribute("aria-label", "Map scope");
    for (const breadcrumb of state.map.breadcrumbs) {
      const button = element("button", "button subtle", breadcrumb.name);
      button.type = "button";
      button.dataset.scopeId = breadcrumb.id;
      button.addEventListener("click", () => {
        selectedMapScopeId = breadcrumb.id;
        void refresh();
      });
      navigation.append(button);
    }
    panel.append(navigation);
  }

  const renderedLocations = state.map.locations
    .filter((location) => location.id !== state.map.scope_location?.id)
    .slice(0, MAP_RENDER_LIMIT);
  if (state.map.locations.length > MAP_RENDER_LIMIT || state.map.has_more) {
    panel.append(
      element(
        "p",
        "muted map-overflow",
        `Showing ${renderedLocations.length} map nodes; ${state.map.child_total} child locations are available in this scope.`,
      ),
    );
  }

  const svg = svgElement("svg", {
    viewBox: `0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`,
    class: "map-svg",
    role: "img",
    "aria-label": `Map of ${scopeName}`,
  });

  const ordered = [...renderedLocations].sort((a, b) => a.name.localeCompare(b.name));
  const children = ordered.filter((location) => !location.is_neighbor);
  const siblings = ordered.filter((location) => location.is_neighbor);
  const isStreetScope = state.map.scope_location?.map_form === "street"
    || state.map.scope_location?.name.toLocaleLowerCase() === "main street";
  const positions = state.map.scope_location === null
    ? orientedMapPositions(ordered)
    : new Map([
        ...(isStreetScope
          ? streetMapPositions(children)
          : centerMapPositions(children)),
        ...edgeMapPositions(siblings),
      ]);

  if (state.map.scope_location !== null) {
    if (isStreetScope) {
      svg.append(
        svgElement("rect", {
          x: MAP_CENTER_X - 22,
          y: MAP_CENTER_Y - 250,
          width: 44,
          height: 500,
          rx: 10,
          class: "map-street-road",
          "data-map-layer": "road",
        }),
        svgElement("line", {
          x1: MAP_CENTER_X,
          y1: MAP_CENTER_Y - 250,
          x2: MAP_CENTER_X,
          y2: MAP_CENTER_Y + 250,
          class: "map-street-road-marking",
          "data-map-layer": "road-marking",
        }),
      );
    }
    svg.append(
      svgElement("circle", {
        cx: MAP_CENTER_X,
        cy: MAP_CENTER_Y,
        r: MAP_BORDER_RADIUS - MAP_BORDER_NODE_RADIUS,
        class: "map-scope-border",
        "data-map-layer": "border",
      }),
    );
  }

  if (state.map.scope_location === null) {
    const drawnEdges = new Set<string>();
    for (const location of renderedLocations) {
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
  }

  for (const location of ordered) {
    const [x, y] = positions.get(location.id) ?? [MAP_CENTER_X, MAP_CENTER_Y];
    const isSibling = state.map.scope_location !== null && location.is_neighbor;
    const isStreetChild = isStreetScope && !isSibling;
    const labelOnLeft = x < MAP_CENTER_X;
    const isTopEdge = y < 60;
    const isBottomEdge = y > MAP_HEIGHT - 60;
    const labelX = isSibling && !isTopEdge && !isBottomEdge
      ? (labelOnLeft ? 30 : -30)
      : isStreetChild ? (labelOnLeft ? -28 : 28) : 0;
    const labelY = isSibling && isTopEdge ? 28 : isSibling && isBottomEdge ? -28 : isStreetChild ? 4 : isSibling ? 4 : 40;
    const labelAnchor = isSibling && !isTopEdge && !isBottomEdge
      ? (labelOnLeft ? "start" : "end")
      : isStreetChild ? (labelOnLeft ? "end" : "start") : "middle";
    const group = svgElement("g", {
      class: isSibling ? "map-node map-node--neighbor" : "map-node",
      "data-map-layer": isSibling ? "perimeter" : "center",
      transform: `translate(${x}, ${y})`,
    });
    group.append(
      mapShape(location, isSibling),
      svgElement("text", {
        x: labelX,
        y: labelY,
        class: "map-label",
        "text-anchor": labelAnchor,
      }),
    );
    if (location.direction !== null || location.range_band !== null) {
      const routeMeta = svgElement("text", {
        x: labelX,
        y: labelY + (isBottomEdge ? -13 : 13),
        class: "map-route-meta",
        "text-anchor": labelAnchor,
      });
      routeMeta.textContent = [location.direction, location.range_band]
        .filter((value): value is string => value !== null)
        .join(" · ");
      group.append(routeMeta);
    }
    const label = group.querySelector("text");
    if (label !== null) label.textContent = location.name;

    const kinds = Object.entries(location.entity_kinds).sort(([a], [b]) =>
      a.localeCompare(b),
    );
    let glyphX = -((kinds.length - 1) * 16) / 2;
    for (const [kind, count] of kinds) {
      const glyphY = isSibling ? 47 : 60;
      const glyph = svgElement("g", { transform: `translate(${glyphX}, ${glyphY})` });
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

  if (state.map.scope_location !== null) {
    const browser = element("section", "map-location-browser");
    if (state.map.boundary_links.length > 0) {
      const exits = element("p", "muted map-boundary-summary");
      exits.textContent = `Exits from this view: ${state.map.boundary_links
        .map((link) => link.to_location_name)
        .join(", ")}.`;
      browser.append(exits);
    }
    if (state.map.route_chain.length > 0) {
      const routes = element("section", "map-route-chain");
      routes.append(element("h3", "map-route-heading", "Routes from here"));
      const rangeLabels: Record<string, string> = { short: "Short range", mid: "Mid range", long: "Long range" };
      const grouped = new Map<string, WorldMapRoute[]>();
      for (const route of state.map.route_chain) {
        const band = route.range_band ?? "unspecified";
        const bucket = grouped.get(band) ?? [];
        bucket.push(route);
        grouped.set(band, bucket);
      }
      for (const band of ["short", "mid", "long", "unspecified"]) {
        const routesInBand = grouped.get(band);
        if (routesInBand === undefined) continue;
        const lane = element("div", "map-route-lane");
        lane.append(element("strong", "map-route-band", rangeLabels[band] ?? "Other range"));
        for (const route of routesInBand) {
          const item = element("div", "map-route-item");
          const path = [route.direction, route.name, "→", route.destination_name]
            .filter((value): value is string => value !== null)
            .join(" ");
          item.append(element("span", "map-route-path", path));
          item.append(element("span", "map-route-kind", `${route.route_kind} · ${route.chain_depth} leg${route.chain_depth === 1 ? "" : "s"}`));
          lane.append(item);
        }
        routes.append(lane);
      }
      routes.append(element("p", "muted map-route-note", "Routes show authored connections only; travel remains narrator-driven."));
      browser.append(routes);
    }
  }
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

async function refresh(forceWorlds = false): Promise<void> {
  if (loading || startPending) return;
  loading = true;
  refreshButton.disabled = true;
  worldSelect.disabled = true;
  setError(startError);
  try {
    if (forceWorlds || worlds.length === 0) await loadWorlds();
    const state = await loadState();
    currentPlayerId = state.player.id;
    narrationRevision.textContent = `r${state.location.revision}`;
    renderState(state);
    lastUpdated = new Date();
    updateFreshness();
  } catch (error) {
    currentPlayerId = null;
    const message = error instanceof Error ? error.message : "Unable to read world state";
    if (message.includes("player not found") || message.includes("location not found")) {
      try {
        playerCharacters = await fetchJson<PlayerCharacter[]>("/api/player-characters");
      } catch {
        playerCharacters = [];
      }
      renderWorldStart();
      setError(startError);
    } else {
      setError(message);
    }
  } finally {
    loading = false;
    refreshButton.disabled = false;
    worldSelect.disabled = worlds.length === 0;
  }
}

function renderWorldStart(): void {
  worldView.replaceChildren();
  const panel = element("section", "panel world-empty");
  panel.append(element("span", "eyebrow", "Begin your story"));
  panel.append(element("h2", "section-title", "This world has no player yet."));
  panel.append(
    element(
      "p",
      "world-empty-hint",
      "Choose one of your reusable player characters. The narrator will establish the opening location from this world's story.",
    ),
  );
  const form = document.createElement("form");
  form.className = "manage-form";
  const select = document.createElement("select");
  select.className = "manage-input";
  select.setAttribute("aria-label", "Character for this world");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = playerCharacters.length === 0 ? "Create a character in Manage first" : "Select a character…";
  select.append(placeholder);
  for (const character of playerCharacters) {
    const option = document.createElement("option");
    option.value = character.id;
    option.textContent = `${character.name} — ${character.basic_info ?? "No basic info"}`;
    select.append(option);
  }
  const button = document.createElement("button");
  button.className = "manage-button";
  button.type = "submit";
  button.textContent = "Begin your story";
  button.disabled = playerCharacters.length === 0;
  form.append(select, button);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (select.value !== "") void startWorld(select.value, button);
  });
  panel.append(form);
  worldView.append(panel);
}

async function startWorld(characterId: string, button: HTMLButtonElement): Promise<void> {
  if (selectedWorldId === null || startPending) return;
  const world = worlds.find((candidate) => candidate.id === selectedWorldId);
  if (world === undefined) return;
  startPending = true;
  startError = null;
  button.disabled = true;
  worldSelect.disabled = true;
  refreshButton.disabled = true;
  setError("The narrator is preparing your arrival…");
  try {
    const response = await postJson<WorldStartResponse>(
      `/api/worlds/${encodeURIComponent(world.id)}/start`,
      {
        character_id: characterId,
        operation_id: crypto.randomUUID(),
        expected_revision: world.revision,
      },
    );
    appendNarration("agent", response.narration);
    narrationRevision.textContent = `r${response.revision_after}`;
    startPending = false;
    await refresh();
  } catch (error) {
    startError = error instanceof Error ? error.message : "The narrator could not start this world";
    startPending = false;
    setError(startError);
    button.disabled = false;
  } finally {
    startPending = false;
    refreshButton.disabled = false;
    worldSelect.disabled = worlds.length === 0;
  }
}

function renderWorldViewEmpty(message: string, hint: string): void {
  worldView.replaceChildren();
  const panel = element("section", "panel world-empty");
  panel.append(element("span", "eyebrow", "Derived from world state"));
  panel.append(element("h2", "section-title", message));
  panel.append(element("p", "world-empty-hint", hint));
  worldView.append(panel);
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
    const [characters, scenarios, allWorlds] = await Promise.all([
      fetchJson<PlayerCharacter[]>("/api/player-characters"),
      fetchJson<Scenario[]>("/api/scenarios"),
      fetchJson<World[]>("/api/worlds"),
    ]);
    renderCharacterList(characters);
    populateWorldCharacterSelect(characters);
    renderScenarioList(scenarios);
    populateWorldScenarioSelect(scenarios);
    renderWorldList(allWorlds);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to load management data");
  } finally {
    manageLoading = false;
  }
}

function renderCharacterList(characters: PlayerCharacter[]): void {
  characterList.replaceChildren();
  if (characters.length === 0) {
    characterList.append(element("p", "empty-state", "No player characters yet. Use the form above to create one."));
    return;
  }
  for (const character of characters) {
    const card = element("article", "manage-card");
    card.append(element("h3", "manage-name", character.name));
    card.append(element("code", "manage-id", character.id));
    if (character.basic_info !== null) card.append(element("p", "manage-description", character.basic_info));
    const editButton = element("button", "manage-button", "Edit");
    editButton.type = "button";
    editButton.addEventListener("click", () => void openCharacterEditor(character.id));
    card.append(editButton);
    characterList.append(card);
  }
}

function populateWorldCharacterSelect(characters: PlayerCharacter[]): void {
  const selected = worldPlayerCharacter.value;
  worldPlayerCharacter.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = characters.length === 0 ? "Create a character first" : "Select a player character…";
  worldPlayerCharacter.append(placeholder);
  for (const character of characters) {
    const option = document.createElement("option");
    option.value = character.id;
    option.textContent = `${character.name} (${character.id})`;
    worldPlayerCharacter.append(option);
  }
  worldPlayerCharacter.value = characters.some((character) => character.id === selected) ? selected : "";
}

async function openCharacterEditor(characterId: string): Promise<void> {
  characterEditor.hidden = false;
  characterEditorName.textContent = characterId;
  try {
    const character = await fetchJson<PlayerCharacter>(`/api/player-characters/${encodeURIComponent(characterId)}`);
    characterEditorName.textContent = character.id;
    characterEditName.value = character.name;
    characterEditInfo.value = character.basic_info ?? "";
    characterEditor.dataset.characterId = character.id;
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to load character");
  }
}

function closeCharacterEditor(): void {
  characterEditor.hidden = true;
  delete characterEditor.dataset.characterId;
}

async function saveCharacter(): Promise<void> {
  const characterId = characterEditor.dataset.characterId;
  if (characterId === undefined || manageBusy) return;
  const name = characterEditName.value.trim();
  if (name === "") {
    setError("Character name must not be blank");
    return;
  }
  manageBusy = true;
  setError(null);
  try {
    await requestJson("PATCH", `/api/player-characters/${encodeURIComponent(characterId)}`, {
      name,
      basic_info: characterEditInfo.value.trim() || null,
      operation_id: crypto.randomUUID(),
    });
    await loadManage();
    await openCharacterEditor(characterId);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to save character");
  } finally {
    manageBusy = false;
  }
}

async function deleteCharacter(): Promise<void> {
  const characterId = characterEditor.dataset.characterId;
  if (characterId === undefined || manageBusy) return;
  if (!window.confirm(`Delete character definition "${characterId}"? Existing world instances remain unchanged.`)) return;
  manageBusy = true;
  setError(null);
  try {
    await requestJson("DELETE", `/api/player-characters/${encodeURIComponent(characterId)}?operation_id=${crypto.randomUUID()}`);
    closeCharacterEditor();
    await loadManage();
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to delete character");
  } finally {
    manageBusy = false;
  }
}

async function createCharacter(): Promise<void> {
  if (manageBusy) return;
  const characterId = characterCreateId.value.trim();
  const name = characterCreateName.value.trim();
  if (characterId === "" || name === "") {
    setError("Character id and name are required");
    return;
  }
  manageBusy = true;
  setError(null);
  try {
    await postJson("/api/player-characters", {
      character_id: characterId,
      name,
      basic_info: characterCreateInfo.value.trim() || null,
      operation_id: crypto.randomUUID(),
    });
    characterCreateId.value = "";
    characterCreateName.value = "";
    characterCreateInfo.value = "";
    await loadManage();
    await openCharacterEditor(characterId);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to create character");
  } finally {
    manageBusy = false;
  }
}

characterCreateForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void createCharacter();
});
characterEditorClose.addEventListener("click", closeCharacterEditor);
characterEditSave.addEventListener("click", () => void saveCharacter());
characterDelete.addEventListener("click", () => void deleteCharacter());

function renderScenarioList(scenarios: Scenario[]): void {
  scenarioList.replaceChildren();
  if (scenarios.length === 0) {
    scenarioList.append(
      element("p", "empty-state", "No scenarios yet. Use the form above to create one."),
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
    const editButton = element("button", "manage-button", "Edit");
    editButton.type = "button";
    editButton.addEventListener("click", () => void openScenarioEditor(scenario.id));
    card.append(editButton);
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
    const editButton = element("button", "manage-button", "Edit");
    editButton.type = "button";
    editButton.addEventListener("click", () => void openWorldEditor(world.id));
    card.append(editButton);
    worldList.append(card);
  }
}

function populateWorldScenarioSelect(scenarios: Scenario[]): void {
  worldCreateScenario.replaceChildren();
  if (scenarios.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No scenarios yet — create one first";
    option.disabled = true;
    worldCreateScenario.append(option);
    worldCreateSubmit.disabled = true;
    return;
  }
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Select a scenario…";
  worldCreateScenario.append(placeholder);
  for (const scenario of scenarios) {
    const option = document.createElement("option");
    option.value = scenario.id;
    option.textContent = `${scenario.title} (${scenario.id})`;
    worldCreateScenario.append(option);
  }
  worldCreateSubmit.disabled = false;
}

function setViewMode(mode: "play" | "manage"): void {
  const playActive = mode === "play";
  worldView.hidden = !playActive;
  narrationPanel.hidden = !playActive;
  manageView.hidden = playActive;
  viewPlayButton.classList.toggle("is-active", playActive);
  viewManageButton.classList.toggle("is-active", !playActive);
  if (!playActive) {
    void loadManage();
  } else {
    void refresh(true);
  }
  const targetHash = playActive ? "" : "#manage";
  if (location.hash !== targetHash) location.hash = targetHash;
}

function elementTextarea(elementType: string): HTMLTextAreaElement {
  const textarea = root?.querySelector<HTMLTextAreaElement>(
    `#scenario-element-${elementType}`,
  );
  if (textarea === null || textarea === undefined) {
    throw new Error(`Missing element textarea: ${elementType}`);
  }
  return textarea;
}

async function openScenarioEditor(scenarioId: string): Promise<void> {
  editingScenarioId = scenarioId;
  scenarioEditor.hidden = false;
  scenarioEditorName.textContent = scenarioId;
  scenarioEditTitle.value = "";
  scenarioEditDescription.value = "";
  for (const elementType of ["author_note", "plot_essentials", "opening_scene"]) {
    elementTextarea(elementType).value = "";
  }
  setError(null);
  await loadScenarioDetail(scenarioId);
}

async function loadScenarioDetail(scenarioId: string): Promise<void> {
  try {
    const detail = await fetchJson<ScenarioDetail>(`/api/scenarios/${encodeURIComponent(scenarioId)}`);
    scenarioEditorName.textContent = detail.id;
    scenarioEditTitle.value = detail.title;
    scenarioEditDescription.value = detail.description ?? "";
    const byType = new Map(detail.elements.map((element) => [element.element_type, element.content]));
    for (const elementType of ["author_note", "plot_essentials", "opening_scene"]) {
      elementTextarea(elementType).value = byType.get(elementType) ?? "";
    }
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to load scenario");
  }
}

async function saveScenarioDetails(): Promise<void> {
  if (editingScenarioId === null || manageBusy) return;
  const title = scenarioEditTitle.value.trim();
  if (title === "") {
    setError("Title must not be blank");
    return;
  }
  setError(null);
  manageBusy = true;
  try {
    await requestJson("PATCH", `/api/scenarios/${encodeURIComponent(editingScenarioId)}`, {
      title,
      description: scenarioEditDescription.value.trim() || null,
      operation_id: crypto.randomUUID(),
    });
    await Promise.all([loadManage(), loadScenarioDetail(editingScenarioId)]);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to save scenario");
  } finally {
    manageBusy = false;
  }
}

async function saveScenarioElement(elementType: string): Promise<void> {
  if (editingScenarioId === null || manageBusy) return;
  const content = elementTextarea(elementType).value;
  setError(null);
  manageBusy = true;
  try {
    await requestJson(
      "PUT",
      `/api/scenarios/${encodeURIComponent(editingScenarioId)}/elements/${elementType}`,
      { content, operation_id: crypto.randomUUID() },
    );
    await Promise.all([loadManage(), loadScenarioDetail(editingScenarioId)]);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to save element");
  } finally {
    manageBusy = false;
  }
}

function closeScenarioEditor(): void {
  editingScenarioId = null;
  scenarioEditor.hidden = true;
}

async function deleteScenario(): Promise<void> {
  if (editingScenarioId === null || manageBusy) return;
  const scenarioId = editingScenarioId;
  if (!window.confirm(`Delete scenario "${scenarioId}"? This cannot be undone.`)) {
    return;
  }
  setError(null);
  manageBusy = true;
  try {
    await requestJson(
      "DELETE",
      `/api/scenarios/${encodeURIComponent(scenarioId)}?operation_id=${crypto.randomUUID()}`,
    );
    closeScenarioEditor();
    await loadManage();
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to delete scenario");
  } finally {
    manageBusy = false;
  }
}

async function createScenario(): Promise<void> {
  if (manageBusy) return;
  const scenarioId = scenarioCreateId.value.trim();
  const title = scenarioCreateTitle.value.trim();
  if (scenarioId === "" || title === "") {
    setError("Scenario id and title are required");
    return;
  }
  setError(null);
  manageBusy = true;
  try {
    await postJson("/api/scenarios", {
      scenario_id: scenarioId,
      title,
      description: scenarioCreateDescription.value.trim() || null,
      operation_id: crypto.randomUUID(),
    });
    scenarioCreateId.value = "";
    scenarioCreateTitle.value = "";
    scenarioCreateDescription.value = "";
    await loadManage();
    await openScenarioEditor(scenarioId);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to create scenario");
  } finally {
    manageBusy = false;
  }
}

scenarioCreateForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void createScenario();
});
scenarioEditSave.addEventListener("click", () => void saveScenarioDetails());
scenarioEditorClose.addEventListener("click", closeScenarioEditor);
scenarioDelete.addEventListener("click", () => void deleteScenario());
for (const button of root?.querySelectorAll<HTMLButtonElement>("[data-element-save]") ?? []) {
  const elementType = button.dataset.elementSave;
  if (elementType !== undefined) {
    button.addEventListener("click", () => void saveScenarioElement(elementType));
  }
}

function worldElementTextarea(elementType: string): HTMLTextAreaElement {
  const textarea = root?.querySelector<HTMLTextAreaElement>(
    `#world-element-${elementType}`,
  );
  if (textarea === null || textarea === undefined) {
    throw new Error(`Missing world element textarea: ${elementType}`);
  }
  return textarea;
}

async function openWorldEditor(worldId: string): Promise<void> {
  editingWorldId = worldId;
  editingWorldRevision = 0;
  worldEditor.hidden = false;
  worldEditorName.textContent = worldId;
  worldEditorRevision.textContent = "";
  worldEditName.value = "";
  worldEditDescription.value = "";
  for (const elementType of ["author_note", "plot_essentials", "opening_scene"]) {
    worldElementTextarea(elementType).value = "";
  }
  setError(null);
  await loadWorldDetail(worldId);
}

async function loadWorldDetail(worldId: string): Promise<void> {
  try {
    const detail = await fetchJson<WorldDetail>(`/api/worlds/${encodeURIComponent(worldId)}`);
    worldEditorName.textContent = detail.id;
    editingWorldRevision = detail.revision;
    worldEditorRevision.textContent = `revision ${detail.revision}`;
    worldEditName.value = detail.name;
    worldEditDescription.value = detail.description ?? "";
    const byType = new Map(detail.elements.map((element) => [element.element_type, element.content]));
    for (const elementType of ["author_note", "plot_essentials", "opening_scene"]) {
      worldElementTextarea(elementType).value = byType.get(elementType) ?? "";
    }
    renderWorldPlayer(detail);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to load world");
  }
}

function renderWorldPlayer(detail: WorldDetail): void {
  worldPlayerInfo.replaceChildren();
  if (detail.player !== null) {
    worldPlayerForm.hidden = true;
    worldPlayerInfo.append(
      element(
        "p",
        "manage-description",
        `Player: ${detail.player.name} at ${detail.player.location_name ?? "an unknown location"}`,
      ),
    );
  } else {
    worldPlayerForm.hidden = false;
    worldPlayerCharacter.value = "";
    worldPlayerInfo.append(
      element(
        "p",
        "manage-description",
        "This world has no player yet — select a reusable character and starting location.",
      ),
    );
  }
}

async function saveWorldDetails(): Promise<void> {
  if (editingWorldId === null || manageBusy) return;
  const title = worldEditName.value.trim();
  if (title === "") {
    setError("Name must not be blank");
    return;
  }
  setError(null);
  manageBusy = true;
  try {
    const response = await requestJson<{ world_revision: number }>(
      "PATCH",
      `/api/worlds/${encodeURIComponent(editingWorldId)}`,
      {
        title,
        description: worldEditDescription.value.trim() || null,
        operation_id: crypto.randomUUID(),
        expected_revision: editingWorldRevision,
      },
    );
    editingWorldRevision = response.world_revision;
    await Promise.all([loadManage(), loadWorldDetail(editingWorldId)]);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to save world");
  } finally {
    manageBusy = false;
  }
}

async function saveWorldElement(elementType: string): Promise<void> {
  if (editingWorldId === null || manageBusy) return;
  const content = worldElementTextarea(elementType).value;
  setError(null);
  manageBusy = true;
  try {
    const response = await requestJson<{ world_revision: number }>(
      "PUT",
      `/api/worlds/${encodeURIComponent(editingWorldId)}/elements/${elementType}`,
      {
        content,
        operation_id: crypto.randomUUID(),
        expected_revision: editingWorldRevision,
      },
    );
    editingWorldRevision = response.world_revision;
    await Promise.all([loadManage(), loadWorldDetail(editingWorldId)]);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to save element");
  } finally {
    manageBusy = false;
  }
}

function closeWorldEditor(): void {
  editingWorldId = null;
  editingWorldRevision = 0;
  worldEditor.hidden = true;
}

async function deleteWorld(): Promise<void> {
  if (editingWorldId === null || manageBusy) return;
  const worldId = editingWorldId;
  if (!window.confirm(`Delete world "${worldId}"? All of its state will be removed.`)) {
    return;
  }
  setError(null);
  manageBusy = true;
  try {
    await requestJson(
      "DELETE",
      `/api/worlds/${encodeURIComponent(worldId)}?operation_id=${crypto.randomUUID()}&expected_revision=${editingWorldRevision}`,
    );
    closeWorldEditor();
    await loadManage();
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to delete world");
  } finally {
    manageBusy = false;
  }
}

async function createWorldFromScenario(): Promise<void> {
  if (manageBusy) return;
  const scenarioId = worldCreateScenario.value;
  const worldId = worldCreateId.value.trim();
  if (scenarioId === "" || worldId === "") {
    setError("Choose a scenario and enter a world id");
    return;
  }
  setError(null);
  manageBusy = true;
  try {
    await postJson("/api/worlds", {
      world_id: worldId,
      scenario_id: scenarioId,
      operation_id: crypto.randomUUID(),
    });
    worldCreateId.value = "";
    await loadManage();
    await openWorldEditor(worldId);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to instance world");
  } finally {
    manageBusy = false;
  }
}

worldCreateForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void createWorldFromScenario();
});
worldEditSave.addEventListener("click", () => void saveWorldDetails());
worldEditorClose.addEventListener("click", closeWorldEditor);
worldDelete.addEventListener("click", () => void deleteWorld());
for (const button of root?.querySelectorAll<HTMLButtonElement>("[data-world-element-save]") ?? []) {
  const elementType = button.dataset.worldElementSave;
  if (elementType !== undefined) {
    button.addEventListener("click", () => void saveWorldElement(elementType));
  }
}

async function provisionPlayer(): Promise<void> {
  if (editingWorldId === null || manageBusy) return;
  const characterId = worldPlayerCharacter.value;
  const locationName = worldPlayerLocation.value.trim();
  if (characterId === "" || locationName === "") {
    setError("Select a player character and enter a starting location");
    return;
  }
  setError(null);
  manageBusy = true;
  try {
    const response = await requestJson<{ world_revision: number }>(
      "POST",
      `/api/worlds/${encodeURIComponent(editingWorldId)}/character-instance`,
      {
        character_id: characterId,
        location_name: locationName,
        operation_id: crypto.randomUUID(),
        expected_revision: editingWorldRevision,
      },
    );
    editingWorldRevision = response.world_revision;
    worldPlayerCharacter.value = "";
    worldPlayerLocation.value = "";
    await Promise.all([loadManage(), loadWorldDetail(editingWorldId)]);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Unable to provision player");
  } finally {
    manageBusy = false;
  }
}

worldPlayerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void provisionPlayer();
});

viewPlayButton.addEventListener("click", () => setViewMode("play"));
viewManageButton.addEventListener("click", () => setViewMode("manage"));

worldSelect.addEventListener("change", () => {
  selectedWorldId = worldSelect.value;
  selectedMapScopeId = null;
  currentPlayerId = null;
  startError = null;
  narrationLog.replaceChildren();
  narrationRevision.textContent = "";
  const url = new URL(window.location.href);
  url.searchParams.set("world", selectedWorldId);
  window.history.replaceState(null, "", url);
  void refresh();
});
refreshButton.addEventListener("click", () => void refresh());
window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
window.addEventListener("hashchange", () => {
  setViewMode(location.hash === "#manage" ? "manage" : "play");
});
void refresh();
if (location.hash === "#manage") setViewMode("manage");
