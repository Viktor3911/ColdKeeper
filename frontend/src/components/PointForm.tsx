import { useState, type SyntheticEvent } from "react";

import type { PointSettings } from "../api/types";
import { Actions, Field, FormError, FormGrid, Hint } from "./ui";

export const DEFAULT_SETTINGS: PointSettings = {
  low_threshold: 2,
  high_threshold: 6,
  deviation_seconds: 300,
  recovery_seconds: 120,
  expected_interval_seconds: 60,
  offline_timeout_seconds: 300,
  profile: "normal",
};

interface Props {
  name: string;
  settings: PointSettings;
  busy: boolean;
  error: unknown;
  onSubmit: (name: string, settings: PointSettings) => void;
  onCancel: () => void;
}

/** Name, thresholds and timing of a measurement point (durations are entered in minutes/seconds). */
export function PointForm({ name: initialName, settings: initial, busy, error, onSubmit, onCancel }: Props) {
  const [name, setName] = useState(initialName);
  const [low, setLow] = useState(String(initial.low_threshold));
  const [high, setHigh] = useState(String(initial.high_threshold));
  const [deviation, setDeviation] = useState(String(initial.deviation_seconds / 60));
  const [recovery, setRecovery] = useState(String(initial.recovery_seconds / 60));
  const [interval, setIntervalSeconds] = useState(String(initial.expected_interval_seconds));
  const [offline, setOffline] = useState(String(initial.offline_timeout_seconds / 60));

  function number(value: string): number {
    return Number(value.replace(",", "."));
  }

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    onSubmit(name, {
      low_threshold: number(low),
      high_threshold: number(high),
      deviation_seconds: Math.round(number(deviation) * 60),
      recovery_seconds: Math.round(number(recovery) * 60),
      expected_interval_seconds: Math.round(number(interval)),
      offline_timeout_seconds: Math.round(number(offline) * 60),
      profile: initial.profile,
    });
  }

  return (
    <form onSubmit={submit}>
      <FormGrid>
        <Field label="Название точки" hint="Например: «Камера», «Морозильная секция»">
          {(id) => <input id={id} value={name} onChange={(event) => setName(event.target.value)} required />}
        </Field>
        <Field label="Нижний порог, °C">
          {(id) => <input id={id} inputMode="decimal" value={low} onChange={(e) => setLow(e.target.value)} required />}
        </Field>
        <Field label="Верхний порог, °C">
          {(id) => (
            <input id={id} inputMode="decimal" value={high} onChange={(e) => setHigh(e.target.value)} required />
          )}
        </Field>
        <Field label="Отклонение подтверждается через, мин">
          {(id) => (
            <input id={id} inputMode="decimal" value={deviation} onChange={(e) => setDeviation(e.target.value)} />
          )}
        </Field>
        <Field label="Восстановление подтверждается через, мин">
          {(id) => <input id={id} inputMode="decimal" value={recovery} onChange={(e) => setRecovery(e.target.value)} />}
        </Field>
        <Field label="Ожидаемый интервал показаний, с">
          {(id) => (
            <input id={id} inputMode="numeric" value={interval} onChange={(e) => setIntervalSeconds(e.target.value)} />
          )}
        </Field>
        <Field label="Нет связи после, мин" hint="Не меньше двух ожидаемых интервалов">
          {(id) => <input id={id} inputMode="decimal" value={offline} onChange={(e) => setOffline(e.target.value)} />}
        </Field>
      </FormGrid>
      {initial.profile === "demo" && (
        <p>
          <Hint>Демо-профиль: короткие таймауты для показа, значения помечены в интерфейсе и выгрузке.</Hint>
        </p>
      )}
      <p>
        <Hint>Пороги задаются для конкретного оборудования и продукции; универсального температурного режима нет.</Hint>
      </p>
      <FormError error={error} />
      <Actions>
        <button type="button" className="secondary" onClick={onCancel}>
          Отмена
        </button>
        <button type="submit" disabled={busy}>
          Сохранить
        </button>
      </Actions>
    </form>
  );
}
