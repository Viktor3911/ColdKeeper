import { Link, Route, Routes } from "react-router";

import { useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { Empty, Loading } from "./components/ui";
import { EquipmentPage } from "./pages/EquipmentPage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { InventoryPage } from "./pages/InventoryPage";
import { JournalPage } from "./pages/JournalPage";
import { LoginPage } from "./pages/LoginPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RecipientsPage } from "./pages/RecipientsPage";
import { SensorsPage } from "./pages/SensorsPage";

function NotFound() {
  return (
    <Empty>
      Страница не найдена. <Link to="/">Вернуться к обзору</Link>
    </Empty>
  );
}

export function App() {
  const { session, loading } = useAuth();
  if (loading) return <Loading what="сессию" />;
  if (!session) return <LoginPage />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="equipment/:equipmentId" element={<EquipmentPage />} />
        <Route path="sensors" element={<SensorsPage />} />
        <Route path="journal" element={<JournalPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="recipients" element={<RecipientsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
