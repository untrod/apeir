import { createContext, useContext } from "react";

/** Ephemeral UI mode only. Never persisted as permission or Runtime state. */
export const StudioPresentation = createContext({ editing: false });
export const useStudioPresentation = () => useContext(StudioPresentation);
