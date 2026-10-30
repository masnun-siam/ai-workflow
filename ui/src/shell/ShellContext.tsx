import { createContext, useContext } from 'react';

interface ShellApi {
  openPalette: () => void;
  openShortcuts: () => void;
  /** Opens the repo switcher whose trigger is on screen (the top bar mounts a full and a compact one). */
  openRepoSwitcher: () => void;
  /** A switcher registers its trigger and opener while mounted; returns the unregister. */
  registerRepoSwitcher: (s: { trigger: () => HTMLElement | null; open: () => void }) => () => void;
}
export const ShellCtx = createContext<ShellApi>({ openPalette: () => {}, openShortcuts: () => {}, openRepoSwitcher: () => {}, registerRepoSwitcher: () => () => {} });
/** `const {openPalette, openShortcuts} = useShell()` */
export const useShell = () => useContext(ShellCtx);
