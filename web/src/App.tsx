import { useState } from "react";
import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { auth } from "./lib/api";
import { useBranding } from "./lib/branding";
import AnalyticsPage from "./pages/AnalyticsPage";
import CamerasPage from "./pages/CamerasPage";
import Dashboard from "./pages/Dashboard";
import EventsPage from "./pages/EventsPage";
import LivePage from "./pages/LivePage";
import LoginPage from "./pages/LoginPage";
import EnginePage from "./pages/EnginePage";
import MapPage from "./pages/MapPage";
import NotificationsPage from "./pages/NotificationsPage";
import RoiConfiguratorPage from "./pages/RoiConfiguratorPage";
import SearchPage from "./pages/SearchPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const brand = useBranding();
  if (brand.auth_required && !auth.token()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const [wsConnected, setWsConnected] = useState(false);
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout wsConnected={wsConnected} />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="traffic/live" element={<LivePage onWsState={setWsConnected} domain="traffic" />} />
          <Route path="traffic/analytics" element={<AnalyticsPage domain="traffic" />} />
          <Route path="traffic/events" element={<EventsPage domain="traffic" />} />
          <Route path="people/live" element={<LivePage onWsState={setWsConnected} domain="people" />} />
          <Route path="people/analytics" element={<AnalyticsPage domain="people" />} />
          <Route path="people/events" element={<EventsPage domain="people" />} />
          <Route path="analytics" element={<Navigate to="/traffic/analytics" replace />} />
          <Route path="events" element={<Navigate to="/traffic/events" replace />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="map" element={<MapPage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="cameras" element={<CamerasPage />} />
          <Route path="cameras/:id/roi" element={<RoiConfiguratorPage />} />
          <Route path="engine" element={<EnginePage />} />
        </Route>
      </Routes>
    </Router>
  );
}
