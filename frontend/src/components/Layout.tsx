import { NavLink, Outlet } from "react-router";

import { useMeta } from "../api/queries";
import { useAuth } from "../auth";
import styles from "./Layout.module.css";
import { cx } from "./ui";

const LINKS = [
  { to: "/", label: "Обзор", end: true },
  { to: "/inventory", label: "Объекты и оборудование", end: false },
  { to: "/sensors", label: "Датчики", end: false },
  { to: "/journal", label: "Журнал", end: false },
  { to: "/incidents", label: "Инциденты", end: false },
  { to: "/recipients", label: "Уведомления", end: false },
];

export function Layout() {
  const { session, logout } = useAuth();
  const meta = useMeta();
  return (
    <div className={styles.shell}>
      <header className={cx(styles.header, "no-print")}>
        <div className={styles.top}>
          <span className={styles.brand}>ColdKeeper</span>
          <span className={styles.org}>{session?.organization_name}</span>
          <span className={styles.user}>
            {session?.login} · {session?.role === "owner" ? "владелец" : "наблюдатель"}
          </span>
          <button type="button" className="secondary" onClick={() => void logout()}>
            Выйти
          </button>
        </div>
        <nav aria-label="Разделы" className={styles.nav}>
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) => cx(styles.link, isActive && styles.active)}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        {meta.data && meta.data.environment !== "production" && (
          <p className={styles.envNotice}>
            Среда: {meta.data.environment}. Данные с пометкой «Демо» получены от симулятора, а не от реальных датчиков.
          </p>
        )}
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
