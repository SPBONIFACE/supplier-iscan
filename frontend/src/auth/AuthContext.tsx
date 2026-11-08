import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate } from "react-router";
import { api, type CurrentUser, setUnauthorizedHandler } from "../lib/api";
import { isPublicPath, LOGIN_PATH, loginUrl } from "./paths";

type AuthState = {
  /** "loading" until the first answer of GET /auth/me. */
  status: "loading" | "ready";
  user: CurrentUser | null;
  /** True when the last sign-out attempt could not reach the server (the session is still open). */
  signOutFailed: boolean;
  /** True after a deliberate sign-out: the login screen then has no "return to" target. */
  signedOutOnPurpose: boolean;
  setUser: (user: CurrentUser | null) => void;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthState["status"]>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [signOutFailed, setSignOutFailed] = useState(false);
  const [signedOutOnPurpose, setSignedOutOnPurpose] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const here = useRef(`${location.pathname}${location.search}`);
  here.current = `${location.pathname}${location.search}`;

  const refresh = useCallback(async () => {
    const result = await api.getCurrentUser();
    setUser(result.ok ? result.data : null);
    setStatus("ready");
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Any 401 from the API: forget the user and go to the login screen, remembering the page asked for.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      if (!isPublicPath(window.location.pathname)) {
        navigate(loginUrl(here.current), { replace: true });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  // A page restored from the browser's back/forward cache must not show protected content after sign-out.
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) void refresh();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [refresh]);

  const signOut = useCallback(async () => {
    const result = await api.logout();
    if (result.ok || result.kind === "unauthorized") {
      setSignOutFailed(false);
      setSignedOutOnPurpose(true);
      setUser(null);
      navigate(LOGIN_PATH, { replace: true });
    } else {
      setSignOutFailed(true);
    }
  }, [navigate]);

  const setUserAndReset = useCallback((next: CurrentUser | null) => {
    if (next) setSignedOutOnPurpose(false);
    setUser(next);
  }, []);

  const value = useMemo(
    () => ({ status, user, signOutFailed, signedOutOnPurpose, setUser: setUserAndReset, signOut }),
    [status, user, signOutFailed, signedOutOnPurpose, setUserAndReset, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
