import { create } from "zustand";
import { persist } from "zustand/middleware";
export type Lens = "flow" | "quality" | "cost";
export const usePreferences = create(
  persist<{
    theme: "dark" | "light";
    lens: Lens;
    positions: Record<string, { x: number; y: number }>;
    hidden: string[];
    tourDone: boolean;
    set: (
      value: Partial<{
        theme: "dark" | "light";
        lens: Lens;
        positions: Record<string, { x: number; y: number }>;
        hidden: string[];
        tourDone: boolean;
      }>,
    ) => void;
  }>(
    (set) => ({
      theme: "dark",
      lens: "flow",
      positions: {},
      hidden: [],
      tourDone: false,
      set: (value) => set(value),
    }),
    { name: "tresata-canvas-v1" },
  ),
);
type Session = {
  overrides: Record<string, string | number | boolean | string[]>;
  mode: "live" | "replay";
  trace: boolean;
  selected: string | null;
  panel: string | null;
  help: number | null;
  drawer: boolean;
  error: string;
  set: (value: Partial<Omit<Session, "set">>) => void;
};
export const useSession = create<Session>((set) => ({
  overrides: {},
  mode: "live",
  trace: false,
  selected: null,
  panel: null,
  help: null,
  drawer: false,
  error: "",
  set: (value) => set(value),
}));
