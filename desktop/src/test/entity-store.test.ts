import { describe, expect, it } from "vitest";
import { entityStore } from "../store/entityStore";

describe("entity store bootstrap", () => {
  it("finishes hydration when no IndexedDB snapshot exists", async () => {
    entityStore.clearStore();

    await entityStore.hydrate();

    expect(entityStore.getState().hydrated).toBe(true);
  });
});
