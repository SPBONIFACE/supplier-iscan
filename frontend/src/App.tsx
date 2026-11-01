import { useTranslation } from "react-i18next";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router";
import { useAuth } from "./auth/AuthContext";
import { homePath, LOGIN_PATH, loginUrl } from "./auth/paths";
import { Layout } from "./components/Layout";
import { LoadingIndicator } from "./components/ui";
import { InvitationPage } from "./pages/InvitationPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage, Placeholder } from "./pages/Simple";

/** Protected routes: nothing is rendered for a signed-out user, who is sent to login and back. */
function RequireAuth() {
  const { user, status, signedOutOnPurpose } = useAuth();
  const location = useLocation();
  if (status === "loading") return <LoadingIndicator />;
  if (!user) {
    const target = signedOutOnPurpose
      ? LOGIN_PATH
      : loginUrl(`${location.pathname}${location.search}`);
    return <Navigate to={target} replace />;
  }
  return <Outlet />;
}

function Home() {
  const { user } = useAuth();
  return user ? <Navigate to={homePath(user)} replace /> : null;
}

function AdminArea() {
  const { user } = useAuth();
  if (user?.role !== "admin") return <NotFoundPage />;
  return <Placeholder titleKey="titles.admin" bodyKey="placeholder.admin" />;
}

export function App() {
  useTranslation(); // re-render the tree when the language changes
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/invitations/:token" element={<InvitationPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Home />} />
          {/* Placeholders: #32 list, #33 new profile, #34 run, #35 to #37 card, #38 comparison, #48 admin. */}
          <Route
            path="/workspace"
            element={<Placeholder titleKey="workspace.title" bodyKey="placeholder.workspace" />}
          />
          <Route
            path="/profiles/new"
            element={<Placeholder titleKey="titles.newProfile" bodyKey="placeholder.newProfile" />}
          />
          <Route
            path="/profiles/:profileId/run"
            element={<Placeholder titleKey="titles.run" bodyKey="placeholder.run" />}
          />
          <Route
            path="/profiles/:profileId"
            element={<Placeholder titleKey="titles.card" bodyKey="placeholder.card" />}
          />
          <Route
            path="/compare"
            element={<Placeholder titleKey="titles.compare" bodyKey="placeholder.compare" />}
          />
          <Route path="/admin" element={<AdminArea />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
