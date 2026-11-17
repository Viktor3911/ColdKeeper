import { useState } from "react";
import { Link } from "react-router";

import { useIncidents } from "../api/queries";
import type { Incident, IncidentEvent } from "../api/types";
import { Card, Empty, ErrorState, Loading, StatusBadge } from "../components/ui";
import { formatDateTime, formatTemperature } from "../format";
import styles from "./Page.module.css";

const TITLES = {
  temperature: "Температура вне диапазона",
  sensor_error: "Ошибка датчика",
  connection_lost: "Нет связи с датчиком",
} as const;
const DELIVERY = {
  pending: "ожидает отправки",
  sent: "отправлено",
  failed: "ошибка доставки",
  dry_run: "не отправлено: бот не подключён (dry-run)",
} as const;

function statusOf(incident: Incident) {
  if (incident.closed_at) return "normal" as const;
  if (incident.type === "temperature") return "alarm" as const;
  return incident.type === "sensor_error" ? ("sensor_error" as const) : ("offline" as const);
}

function Deliveries({ event }: { event: IncidentEvent }) {
  if (event.deliveries.length === 0) {
    return <p className={styles.muted}>Не отправлено: нет активных получателей Telegram.</p>;
  }
  return (
    <ul>
      {event.deliveries.map((delivery, index) => (
        <li key={index} className={styles.muted}>
          {delivery.recipient_title}: {DELIVERY[delivery.status]}
          {delivery.attempts > 1 && `, попыток: ${delivery.attempts}`}
          {delivery.last_error && ` — ${delivery.last_error}`}
        </li>
      ))}
    </ul>
  );
}

function IncidentCard({ incident }: { incident: Incident }) {
  const { location } = incident;
  const direction = incident.direction === "low" ? "ниже нижнего порога" : "выше верхнего порога";
  return (
    <Card>
      <div className={styles.head}>
        <h2>{TITLES[incident.type]}</h2>
        <StatusBadge status={statusOf(incident)} label={incident.closed_at ? "Закрыт" : "Открыт"} />
      </div>
      <p>
        <Link to={`/equipment/${location.equipment_id}`}>
          {location.site_name} · {location.room_name} · {location.equipment_name} · {location.point_name}
        </Link>
      </p>
      <p className={styles.muted}>
        Начало: {formatDateTime(incident.opened_at, location.timezone)}
        {incident.type === "temperature" && `, ${formatTemperature(incident.open_temperature)} (${direction})`}
        {incident.closed_at && ` · завершён: ${formatDateTime(incident.closed_at, location.timezone)}`}
        {incident.closed_at &&
          incident.close_temperature !== null &&
          `, ${formatTemperature(incident.close_temperature)}`}
      </p>
      <details>
        <summary>Уведомления ({incident.events.length})</summary>
        {incident.events.map((event, index) => (
          <div key={index}>
            <div className={styles.message}>{event.text}</div>
            <Deliveries event={event} />
          </div>
        ))}
      </details>
    </Card>
  );
}

export function IncidentsPage() {
  const [onlyOpen, setOnlyOpen] = useState(false);
  const incidents = useIncidents(onlyOpen);
  return (
    <div>
      <div className={styles.head}>
        <h1>Инциденты</h1>
        <label className={styles.row}>
          <input type="checkbox" checked={onlyOpen} onChange={(event) => setOnlyOpen(event.target.checked)} />
          Только открытые
        </label>
      </div>
      {incidents.isPending && <Loading what="инциденты" />}
      {incidents.isError && <ErrorState error={incidents.error} retry={() => void incidents.refetch()} />}
      {incidents.data?.length === 0 && (
        <Empty>{onlyOpen ? "Открытых инцидентов нет." : "Инцидентов пока не было."}</Empty>
      )}
      <div className={styles.stack}>
        {incidents.data?.map((incident) => (
          <IncidentCard key={incident.id} incident={incident} />
        ))}
      </div>
    </div>
  );
}
