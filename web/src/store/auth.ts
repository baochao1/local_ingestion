import { create } from 'zustand';

/**
 * Auth state. MOD-11 (RBAC) is not implemented yet, so the app degrades to
 * "no auth": `skipAuth` lets the login page enter directly (FE-01 §1).
 */
export interface AuthState {
  token: string | null;
  username: string | null;
  /** Permission codes from MOD-11. Empty => menu degrades to fully visible. */
  perms: string[];
  skipAuth: boolean;
  setSession: (token: string | null, username: string | null, perms?: string[]) => void;
  setPerms: (perms: string[]) => void;
  enterAsGuest: () => void;
  logout: () => void;
}

const TOKEN_KEY = 'mg.token';
const USER_KEY = 'mg.username';
const PERMS_KEY = 'mg.perms';

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(TOKEN_KEY),
  username: localStorage.getItem(USER_KEY),
  perms: (() => {
    try {
      return JSON.parse(localStorage.getItem(PERMS_KEY) ?? '[]') as string[];
    } catch {
      return [];
    }
  })(),
  skipAuth: true,
  setSession: (token, username, perms = []) => {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
    if (username) localStorage.setItem(USER_KEY, username);
    else localStorage.removeItem(USER_KEY);
    localStorage.setItem(PERMS_KEY, JSON.stringify(perms));
    set({ token, username, perms });
  },
  setPerms: (perms) => {
    localStorage.setItem(PERMS_KEY, JSON.stringify(perms));
    set({ perms });
  },
  enterAsGuest: () => set({ skipAuth: true, username: 'guest' }),
  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(PERMS_KEY);
    set({ token: null, username: null, perms: [] });
  },
}));

/** Permission gate helper: empty perm set (MOD-11 absent) grants everything. */
export function hasPerm(code: string | undefined): boolean {
  if (!code) return true;
  const { perms } = useAuthStore.getState();
  return perms.length === 0 || perms.includes(code);
}
