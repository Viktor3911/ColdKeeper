import { Link } from "react-router";

import { useOverview } from "../api/queries";
import type { PointOverview, PointStatus } from "../api/types";
import { DemoBadge, Empty, ErrorState, Loading, StatusBadge, cx } from "../components/ui";
import { formatAge, formatDateTime, formatTemperature } from "../format";
import styles from "./Page.module.css";

const PROBLEMS: PointStatus[] = ["alarm", "offline", "sensor_error", "pending"];

function alarmLabel(point: PointOverview): string | undefined {
  if (point.status !== "alarm") return undefined;
  return point.alarm_direction === "low" ? "Тревога: ниже нормы" : "Тревога: выше нормы";
}

function PointCard({ point }: { point: PointOverview }) {
  const { location, settings } = point;
  return (
    <Link
      to={`/equipment/${location.equipment_id}`}
      className={cx(styles.pointCard, styles[`edge-${point.status}`])}
      aria-label={`${location.equipment_name}, ${location.point_name}`}
    >
      <div className={styles.row}>
        <StatusBadge status={point.status} label={alarmLabel(point)} />
        {point.is_demo && <DemoBadge />}
      </div>
      <div>
        <div className={styles.title}>{location.equipment_name}</div>
        <div className={styles.subtitle}>
          {location.point_name} · {location.room_name} · {location.site_name}
        </div>
      </div>
      <div className={styles.temperature}>{formatTemperature(point.last_temperature)}</div>
      <div className={styles.subtitle}>
        Допустимо {formatTemperature(settings.low_threshold)} … {formatTemperature(settings.high_threshold)}
      </div>
      <div className={styles.subtitle}>
        Последнее показание: {formatDateTime(point.last_measured_at, location.timezone)} (
        {formatAge(point.last_received_at)})
      </div>
      {point.open_incidents > 0 && <div className={styles.subtitle}>Открытых инцидентов: {point.open_incidents}</div>}
    </Link>
  );
}

export function OverviewPage() {
  const overview = useOverview();
  if (overview.isPending) return <Loading what="обзор" />;
  if (overview.isError) return <ErrorState error={overview.error} retry={() => void overview.refetch()} />;
  const points = overview.data;
  const problems = points.filter((point) => PROBLEMS.includes(point.status));
  return (
    <div>
      <div className={styles.head}>
        <h1>Обзор</h1>
        <span className={styles.muted}>
          Обновляется автоматически · {new Date(overview.dataUpdatedAt).toLocaleTimeString("ru-RU")}
        </span>
      </div>
      {points.length === 0 ? (
        <Empty>
          Точек измерения пока нет. Добавьте объект, помещение, оборудование и точку в разделе{" "}
          <Link to="/inventory">«Объекты и оборудование»</Link>, затем привяжите датчик.
        </Empty>
      ) : (
        <>
          <p className={styles.summary}>
            {problems.length === 0
              ? `Все ${points.length} точек в норме или ждут первых данных.`
              : `Требуют внимания: ${problems.length} из ${points.length}.`}
          </p>
          <div className={styles.grid}>
            {points.map((point) => (
              <PointCard key={point.location.point_id} point={point} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
