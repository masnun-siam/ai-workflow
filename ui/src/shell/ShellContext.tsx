import { createContext, useContext } from 'react';

interface ShellApi {
  openPalette: () => void;
  openShortcuts: () => void;
}
export const ShellCtx = createContext<ShellApi>({ openPalette: () => {}, openShortcuts: () => {} });
/** `const {openPalette, openShortcuts} = useShell()` */
export const useShell = () => useContext(ShellCtx);
