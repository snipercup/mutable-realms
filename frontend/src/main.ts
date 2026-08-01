const root = document.querySelector<HTMLElement>("#app");

if (!root) {
  throw new Error("Mutable Realms application root was not found");
}

root.textContent = "Mutable Realms";
