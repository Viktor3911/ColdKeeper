import { useState } from "react";
import { useSearchParams } from "react-router";

import { withQuery } from "../api/client";
import { useDailyJournal, useInventory, useRawJournal, type JournalQuery } from "../api/queries";
import type { Journal, RawJournal } from "../api/types";
import { DemoBadge, Empty, ErrorState, Field, Loading, TableWrap, cx } from "../components/ui";
import { formatDay, formatDateTime, formatTemperature, formatTime, localDate, monthRange } from "../format";
import styles from "./Page.module.css";

const CONTROL_LABELS = { ok: "есть измерение", no_data: "нет данных", sensor_error: "ошибка датчика" } as const;
const SOURCE_LABELS = { device: "датчик", simulator: "симуляция" } as const;

function DailyTable({ journal }: { journal: Journal }) {
  if (journal.rows.length === 0) return <Empty>Нет точек измерения для выбранного фильтра.</Empty>;
  return (
    <TableWrap label="Ежедневный журнал">
      <table>
        <thead>
          <tr>
            <th>Дата</th>
            <th>Помещение / оборудование / точка</th>
            <th>Время</th>
            <th className="number">Температура</th>
            <th>Контроль</th>
            <th className="number">Мин.</th>
            <th className="number">Макс.</th>
            <th className="number">Показаний</th>
            <th className="number">Покрытие</th>
            <th>Источник</th>
          </tr>
        </thead>
        <tbody>
          {journal.rows.map((row) => (
            <tr
              key={`${row.location.point_id}-${row.day}`}
              className={cx(
                row.control_state === "no_data" && styles.noDataRow,
                row.control_state === "sensor_error" && styles.problemRow,
              )}
            >
              <td>{formatDay(row.day)}</td>
              <td>
                {row.location.room_name} / {row.location.equipment_name} / {row.location.point_name}
              </td>
              <td>{formatTime(row.control_measured_at, row.location.timezone)}</td>
              <td className="number">{formatTemperature(row.control_temperature)}</td>
              <td>{CONTROL_LABELS[row.control_state]}</td>
              <td className="number">{formatTemperature(row.minimum)}</td>
              <td className="number">{formatTemperature(row.maximum)}</td>
              <td className="number">{row.valid_count}</td>
              <td className="number">{Math.round(row.coverage * 100)} %</td>
              <td>{row.sources.length ? row.sources.map((source) => SOURCE_LABELS[source]).join(", ") : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

function RawTable({ journal }: { journal: RawJournal }) {
  if (journal.rows.length === 0) return <Empty>Измерений за период нет.</Empty>;
  return (
    <>
      {journal.total > journal.rows.length && (
        <p className={styles.muted}>
          Показаны последние {journal.rows.length} из {journal.total}. Полный список — в выгрузке.
        </p>
      )}
      <TableWrap label="Исходные измерения">
        <table>
          <thead>
            <tr>
              <th>Время (местное)</th>
              <th>Оборудование / точка</th>
              <th>Датчик</th>
              <th className="number">Температура</th>
              <th>Состояние</th>
              <th>Источник</th>
            </tr>
          </thead>
          <tbody>
            {journal.rows.map((row) => (
              <tr
                key={`${row.sensor_hardware_id}-${row.measured_at}`}
                className={cx(!row.sensor_ok && styles.problemRow)}
              >
                <td>{formatDateTime(row.measured_at, row.location.timezone)}</td>
                <td>
                  {row.location.equipment_name} / {row.location.point_name}
                </td>
                <td>
                  <code>{row.sensor_hardware_id}</code>
                </td>
                <td className="number">{formatTemperature(row.temperature)}</td>
                <td>{row.sensor_ok ? "норма" : "ошибка датчика"}</td>
                <td>{SOURCE_LABELS[row.source]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </>
  );
}

function Downloads({ kind, query }: { kind: "daily" | "raw"; query: JournalQuery }) {
  const href = (format: string) => withQuery(`/api/v1/journal/${kind}/export`, { ...query, format });
  return (
    <div className={cx(styles.row, "no-print")}>
      <a href={href("csv")} download>
        Скачать CSV
      </a>
      <a href={href("xlsx")} download>
        Скачать XLSX
      </a>
      {kind === "daily" && (
        <button type="button" className="secondary" onClick={() => window.print()}>
          Печать
        </button>
      )}
    </div>
  );
}

/** Monthly Word journal laid out like the SanPiN sample (appendix N 2): one page per site and month. */
function SanpinForm({ siteId, equipmentId }: { siteId: string; equipmentId: string }) {
  const [month, setMonth] = useState(localDate(0).slice(0, 7));
  const { first, last } = monthRange(month || localDate(0).slice(0, 7));
  const href = withQuery("/api/v1/journal/form/export", {
    first,
    last,
    site_id: siteId || undefined,
    equipment_id: equipmentId || undefined,
  });
  return (
    <div className={cx(styles.row, "no-print")}>
      <Field label="Месяц для печатной формы">
        {(id) => (
          <input
            id={id}
            type="month"
            value={month}
            max={localDate(0).slice(0, 7)}
            onChange={(e) => setMonth(e.target.value)}
          />
        )}
      </Field>
      <a href={href} download>
        Скачать журнал по форме СанПиН (Word)
      </a>
      <span className={styles.muted}>
        По образцу приложения № 2 к СанПиН 2.3/2.4.4282-26: строка на единицу оборудования, столбец на день месяца.
      </span>
    </div>
  );
}

export function JournalPage() {
  const [params] = useSearchParams();
  const inventory = useInventory();
  const [tab, setTab] = useState<"daily" | "raw">("daily");
  const [siteId, setSiteId] = useState("");
  const [equipmentId, setEquipmentId] = useState(params.get("equipment") ?? "");
  const [first, setFirst] = useState(localDate(6));
  const [last, setLast] = useState(localDate(0));
  const query: JournalQuery = { first, last, site_id: siteId || undefined, equipment_id: equipmentId || undefined };
  const daily = useDailyJournal(query);
  const raw = useRawJournal(query, tab === "raw");
  const current = tab === "daily" ? daily : raw;
  const equipment = (inventory.data?.equipment ?? []).filter(
    (item) => !siteId || inventory.data?.rooms.some((room) => room.id === item.room_id && room.site_id === siteId),
  );
  const organization = daily.data?.organization_name ?? "";
  const demo = tab === "daily" ? daily.data?.has_simulation : raw.data?.has_simulation;

  return (
    <div>
      <div className={styles.head}>
        <h1>Температурный журнал</h1>
        <Downloads kind={tab} query={query} />
      </div>
      <div className={styles.printHeader}>
        <p>
          {organization}. Период: {formatDay(first)} — {formatDay(last)}.
          {demo ? " Содержит симулированные данные (демо)." : ""}
        </p>
      </div>
      <div className={cx(styles.filters, "no-print")}>
        <Field label="Объект">
          {(id) => (
            <select
              id={id}
              value={siteId}
              onChange={(event) => {
                setSiteId(event.target.value);
                setEquipmentId("");
              }}
            >
              <option value="">Все объекты</option>
              {inventory.data?.sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Оборудование">
          {(id) => (
            <select id={id} value={equipmentId} onChange={(event) => setEquipmentId(event.target.value)}>
              <option value="">Всё оборудование</option>
              {equipment.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="С (местная дата)">
          {(id) => <input id={id} type="date" value={first} max={last} onChange={(e) => setFirst(e.target.value)} />}
        </Field>
        <Field label="По">
          {(id) => <input id={id} type="date" value={last} min={first} onChange={(e) => setLast(e.target.value)} />}
        </Field>
      </div>
      <div className={cx(styles.tabs, "no-print")} role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "daily"}
          className={tab === "daily" ? styles.tabActive : styles.tab}
          onClick={() => setTab("daily")}
        >
          Ежедневный журнал
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "raw"}
          className={tab === "raw" ? styles.tabActive : styles.tab}
          onClick={() => setTab("raw")}
        >
          Исходные измерения
        </button>
        {demo && <DemoBadge title="В периоде есть данные симулятора" />}
      </div>
      {tab === "daily" && (
        <p className={cx(styles.muted, "no-print")}>
          Контрольное значение суток — первое корректное измерение в окне после контрольного времени объекта (по
          умолчанию 10:00, 30 минут). Если такого нет — «нет данных»; пропуски не заполняются. Это правило настройки
          ColdKeeper для производственного контроля, а не требование нормативного документа.
        </p>
      )}
      {tab === "daily" && <SanpinForm siteId={siteId} equipmentId={equipmentId} />}
      {current.isPending && <Loading what="журнал" />}
      {current.isError && <ErrorState error={current.error} retry={() => void current.refetch()} />}
      {tab === "daily" && daily.data && <DailyTable journal={daily.data} />}
      {tab === "raw" && raw.data && <RawTable journal={raw.data} />}
    </div>
  );
}
