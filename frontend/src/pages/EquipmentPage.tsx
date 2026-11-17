import { useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "../api/client";
import { useChange, useEquipmentCard, useSeries } from "../api/queries";
import type { PointOverview, PointSettings } from "../api/types";
import { PointForm } from "../components/PointForm";
import { TemperatureChart } from "../components/TemperatureChart";
import { Card, DemoBadge, Dialog, Empty, ErrorState, Loading, StatusBadge } from "../components/ui";
import { useAuth } from "../auth";
import { EQUIPMENT_KINDS, formatAge, formatDateTime, formatDuration, formatTemperature } from "../format";
import styles from "./Page.module.css";

const RANGES = [
  { hours: 6, label: "6 часов" },
  { hours: 24, label: "Сутки" },
  { hours: 24 * 7, label: "7 дней" },
];

function PointChart({ point }: { point: PointOverview }) {
  const [hours, setHours] = useState(24);
  const series = useSeries(point.location.point_id, hours);
  return (
    <div>
      <div className={styles.tabs} role="group" aria-label="Период графика">
        {RANGES.map((range) => (
          <button
            key={range.hours}
            type="button"
            className={range.hours === hours ? styles.tabActive : styles.tab}
            aria-pressed={range.hours === hours}
            onClick={() => setHours(range.hours)}
          >
            {range.label}
          </button>
        ))}
      </div>
      {series.isPending && <Loading what="график" />}
      {series.isError && <ErrorState error={series.error} retry={() => void series.refetch()} />}
      {series.data && series.data.length === 0 && <Empty>За выбранный период измерений нет.</Empty>}
      {series.data && series.data.length > 0 && (
        <TemperatureChart
          points={series.data}
          low={point.settings.low_threshold}
          high={point.settings.high_threshold}
          timeZone={point.location.timezone}
          expectedIntervalSeconds={point.settings.expected_interval_seconds}
        />
      )}
    </div>
  );
}

function PointSection({ point }: { point: PointOverview }) {
  const { isOwner } = useAuth();
  const [editing, setEditing] = useState(false);
  const save = useChange(
    (args: { name: string; settings: PointSettings }) =>
      api.put(`/api/v1/points/${point.location.point_id}`, {
        equipment_id: point.location.equipment_id,
        name: args.name,
        settings: args.settings,
      }),
    [["equipment"], ["overview"], ["inventory"]],
  );
  const { settings, location } = point;
  return (
    <Card>
      <div className={styles.head}>
        <h2>{location.point_name}</h2>
        <div className={styles.row}>
          <StatusBadge status={point.status} />
          {point.is_demo && <DemoBadge />}
        </div>
      </div>
      <p>
        <span className={styles.temperature}>{formatTemperature(point.last_temperature)}</span>
      </p>
      <p className={styles.muted}>
        Последнее показание: {formatDateTime(point.last_measured_at, location.timezone)} · связь{" "}
        {formatAge(point.last_received_at)}
        {point.pending_since && ` · отклонение с ${formatDateTime(point.pending_since, location.timezone)}`}
      </p>
      <p className={styles.muted}>
        Допустимо {formatTemperature(settings.low_threshold)} … {formatTemperature(settings.high_threshold)}; тревога
        через {formatDuration(settings.deviation_seconds)} отклонения, восстановление через{" "}
        {formatDuration(settings.recovery_seconds)} нормы, нет связи после{" "}
        {formatDuration(settings.offline_timeout_seconds)}.
      </p>
      <p className={styles.muted}>
        Датчик:{" "}
        {point.sensor ? (
          <Link to="/sensors">
            {point.sensor.hardware_id} ({point.sensor.kind === "simulated" ? "симуляция" : "устройство"})
          </Link>
        ) : (
          "не привязан"
        )}
      </p>
      <PointChart point={point} />
      {isOwner && (
        <div className={styles.row}>
          <button type="button" className="secondary" onClick={() => setEditing(true)}>
            Изменить пороги и интервалы
          </button>
        </div>
      )}
      <Dialog title={`Настройки: ${location.point_name}`} open={editing} onClose={() => setEditing(false)}>
        <PointForm
          name={location.point_name}
          settings={settings}
          busy={save.isPending}
          error={save.error}
          onCancel={() => setEditing(false)}
          onSubmit={(name, values) => save.mutate({ name, settings: values }, { onSuccess: () => setEditing(false) })}
        />
      </Dialog>
    </Card>
  );
}

export function EquipmentPage() {
  const { equipmentId = "" } = useParams();
  const card = useEquipmentCard(equipmentId);
  if (card.isPending) return <Loading what="оборудование" />;
  if (card.isError) return <ErrorState error={card.error} retry={() => void card.refetch()} />;
  const { equipment, points } = card.data;
  const location = points[0]?.location;
  return (
    <div className={styles.stack}>
      <div className={styles.head}>
        <div>
          <h1>{equipment.name}</h1>
          <span className={styles.muted}>
            {EQUIPMENT_KINDS[equipment.kind]}
            {location && ` · ${location.room_name} · ${location.site_name}`}
          </span>
        </div>
        <Link to={`/journal?equipment=${equipment.id}`} className="no-print">
          Журнал этого оборудования
        </Link>
      </div>
      {points.length === 0 ? (
        <Empty>У оборудования нет точек измерения. Добавьте точку в разделе «Объекты и оборудование».</Empty>
      ) : (
        points.map((point) => <PointSection key={point.location.point_id} point={point} />)
      )}
    </div>
  );
}
