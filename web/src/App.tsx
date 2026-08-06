import { useState } from "react";
import { Route, BrowserRouter as Router, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AnalyticsPage from "./pages/AnalyticsPage";
import CamerasPage from "./pages/CamerasPage";
import EventsPage from "./pages/EventsPage";
import LivePage from "./pages/LivePage";
import RoiConfiguratorPage from "./pages/RoiConfiguratorPage";

export default function App() {
  const [wsConnected, setWsConnected] = useState(false);
  return (
    <Router>
      <Routes>
        <Route element={<Layout wsConnected={wsConnected} />}>
          <Route index element={<LivePage onWsState={setWsConnected} />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="events" element={<EventsPage />} />
          <Route path="cameras" element={<CamerasPage />} />
          <Route path="cameras/:id/roi" element={<RoiConfiguratorPage />} />
        </Route>
      </Routes>
    </Router>
  );
}
