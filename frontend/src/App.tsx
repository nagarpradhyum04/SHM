import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Loading } from "@/components/ui";
import DigitalTwin from "@/pages/DigitalTwin";

const Assets = lazy(() => import("@/pages/Assets"));
const Inspections = lazy(() => import("@/pages/Inspections"));
const Defects = lazy(() => import("@/pages/Defects"));
const Devices = lazy(() => import("@/pages/Devices"));
const Sensors = lazy(() => import("@/pages/Sensors"));
const Alerts = lazy(() => import("@/pages/Alerts"));
const HistoryPage = lazy(() => import("@/pages/History"));
const Reports = lazy(() => import("@/pages/Reports"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const RemainingLife = lazy(() => import("@/pages/RemainingLife"));

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/twin" replace />} />
        <Route path="/twin" element={<DigitalTwin />} />
        {[
          ["/assets", Assets], ["/inspections", Inspections], ["/defects", Defects], ["/devices", Devices], ["/sensors", Sensors],
          ["/alerts", Alerts], ["/rul", RemainingLife], ["/history", HistoryPage], ["/reports", Reports], ["/settings", SettingsPage],
        ].map(([path, C]) => {
          const Page = C as React.ComponentType;
          return <Route key={path as string} path={path as string} element={<Suspense fallback={<Loading />}><div className="h-full overflow-y-auto"><Page /></div></Suspense>} />;
        })}
        <Route path="*" element={<Navigate to="/twin" replace />} />
      </Route>
    </Routes>
  );
}
