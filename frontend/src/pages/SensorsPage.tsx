import { useState, type SyntheticEvent } from "react";

import { sensorActions, useChange, useInventory, useMeta, useSensorDetail, useSensors } from "../api/queries";
import type { IssuedToken, Sensor } from "../api/types";
import { useAuth } from "../auth";
import {
  Actions,
  DemoBadge,
  Dialog,
  Empty,
  ErrorState,
  Field,
  FormError,
  FormGrid,
  Hint,
  Loading,
  Secret,
  TableWrap,
} from "../components/ui";
import { formatAge, formatDateTime, formatTemperature } from "../format";
import styles from "./Page.module.css";

const REFRESH = [["sensors"], ["sensor"], ["overview"], ["equipment"]];

function TokenNotice({ issued }: { issued: IssuedToken }) {
  return (
    <div>
      <p>Ключ показывается только сейчас — сохраните его. На сервере хранится только хеш, восстановить ключ нельзя.</p>
      <Field label="Ключ устройства">{() => <Secret>{issued.token}</Secret>}</Field>
      <p />
      <Field label="URL для HTTP push в настройках UnitX (метод POST)">
        {() => <Secret>{issued.ingest_url}</Secret>}
      </Field>
      <p>
        <Hint>
          Для работы через интернет нужен подтверждённый защищённый канал от устройства (HTTPS прошивки). До проверки
          подключайте реальный датчик только в доверенной сети.
        </Hint>
      </p>
    </div>
  );
}

function RegisterForm({ onIssued, onCancel }: { onIssued: (token: IssuedToken) => void; onCancel: () => void }) {
  const [hardwareId, setHardwareId] = useState("");
  const [kind, setKind] = useState<"physical" | "simulated">("physical");
  const [model, setModel] = useState("UnitX-T");
  const register = useChange(sensorActions.register, REFRESH);

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    register.mutate({ hardware_id: hardwareId.trim(), kind, model }, { onSuccess: onIssued });
  }

  return (
    <form onSubmit={submit}>
      <FormGrid>
        <Field label="Аппаратный ID" hint="Поле id из настроек устройства, например utx-ae4634">
          {(id) => <input id={id} value={hardwareId} onChange={(e) => setHardwareId(e.target.value)} required />}
        </Field>
        <Field label="Модель">
          {(id) => <input id={id} value={model} onChange={(e) => setModel(e.target.value)} />}
        </Field>
        <Field label="Источник" hint="Нельзя изменить после регистрации">
          {(id) => (
            <select id={id} value={kind} onChange={(e) => setKind(e.target.value as "physical" | "simulated")}>
              <option value="physical">Реальное устройство</option>
              <option value="simulated">Симулятор (демо)</option>
            </select>
          )}
        </Field>
      </FormGrid>
      <FormError error={register.error} />
      <Actions>
        <button type="button" className="secondary" onClick={onCancel}>
          Отмена
        </button>
        <button type="submit" disabled={register.isPending}>
          Зарегистрировать
        </button>
      </Actions>
    </form>
  );
}

function AssignForm({ sensor, onDone }: { sensor: Sensor; onDone: () => void }) {
  const inventory = useInventory();
  const [pointId, setPointId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const assign = useChange(sensorActions.assign, REFRESH);
  if (inventory.isPending) return <Loading what="точки" />;
  if (inventory.isError) return <ErrorState error={inventory.error} />;
  const { points, equipment } = inventory.data;
  const equipmentName = (id: string) => equipment.find((item) => item.id === id)?.name ?? "";

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    assign.mutate(
      { sensorId: sensor.id, pointId, startsAt: startsAt ? new Date(startsAt).toISOString() : null },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={submit}>
      <FormGrid>
        <Field label="Точка измерения">
          {(id) => (
            <select id={id} value={pointId} onChange={(e) => setPointId(e.target.value)} required>
              <option value="">Выберите точку</option>
              {points.map((point) => (
                <option key={point.id} value={point.id}>
                  {equipmentName(point.equipment_id)} — {point.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Начало привязки" hint="Пусто — с текущего момента. Не раньше последних сохранённых измерений">
          {(id) => (
            <input id={id} type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
          )}
        </Field>
      </FormGrid>
      <p>
        <Hint>
          Если у точки есть другой датчик, его привязка закончится в тот же момент. История остаётся за точкой с прежней
          пометкой источника и не переносится.
        </Hint>
      </p>
      <FormError error={assign.error} />
      <Actions>
        <button type="button" className="secondary" onClick={onDone}>
          Отмена
        </button>
        <button type="submit" disabled={assign.isPending}>
          Привязать
        </button>
      </Actions>
    </form>
  );
}

function History({ sensorId }: { sensorId: string }) {
  const detail = useSensorDetail(sensorId);
  const inventory = useInventory();
  if (detail.isPending) return <Loading what="историю" />;
  if (detail.isError) return <ErrorState error={detail.error} />;
  const pointName = (id: string) => inventory.data?.points.find((point) => point.id === id)?.name ?? id;
  if (detail.data.history.length === 0) return <Empty>Привязок не было.</Empty>;
  return (
    <TableWrap label="История привязок">
      <table>
        <thead>
          <tr>
            <th>Точка</th>
            <th>С</th>
            <th>По</th>
          </tr>
        </thead>
        <tbody>
          {detail.data.history.map((item) => (
            <tr key={item.id}>
              <td>{pointName(item.point_id)}</td>
              <td>{new Date(item.starts_at).toLocaleString("ru-RU")}</td>
              <td>{item.ends_at ? new Date(item.ends_at).toLocaleString("ru-RU") : "сейчас"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

type Modal =
  | { kind: "register" }
  | { kind: "token"; issued: IssuedToken }
  | { kind: "assign"; sensor: Sensor }
  | { kind: "history"; sensor: Sensor }
  | null;

export function SensorsPage() {
  const sensors = useSensors();
  const meta = useMeta();
  const { isOwner } = useAuth();
  const [modal, setModal] = useState<Modal>(null);
  const reissue = useChange(sensorActions.reissue, REFRESH);
  const revoke = useChange(sensorActions.revoke, REFRESH);
  const unassign = useChange(sensorActions.unassign, REFRESH);
  const close = () => setModal(null);

  if (sensors.isPending) return <Loading what="датчики" />;
  if (sensors.isError) return <ErrorState error={sensors.error} retry={() => void sensors.refetch()} />;

  return (
    <div>
      <div className={styles.head}>
        <h1>Датчики и привязки</h1>
        {isOwner && (
          <button type="button" onClick={() => setModal({ kind: "register" })}>
            Зарегистрировать датчик
          </button>
        )}
      </div>
      <p className={styles.muted}>
        Устройства отправляют показания на <code>{meta.data?.ingest_url ?? "/api/v1/ingest/unitx?token=<ключ>"}</code>.
        Источник (устройство или симулятор) задаётся при регистрации и не меняется.
      </p>
      <FormError error={reissue.error ?? revoke.error ?? unassign.error} />
      {sensors.data.length === 0 ? (
        <Empty>Датчиков пока нет.</Empty>
      ) : (
        <TableWrap label="Датчики">
          <table>
            <thead>
              <tr>
                <th>Аппаратный ID</th>
                <th>Источник</th>
                <th>Точка</th>
                <th>Последнее показание</th>
                <th>Ключ</th>
                <th className="no-print">Действия</th>
              </tr>
            </thead>
            <tbody>
              {sensors.data.map((sensor) => (
                <tr key={sensor.id}>
                  <td>
                    <code>{sensor.hardware_id}</code>
                    <div className={styles.muted}>{sensor.model}</div>
                  </td>
                  <td>{sensor.kind === "simulated" ? <DemoBadge title="Симулируемый датчик" /> : "Устройство"}</td>
                  <td>
                    {sensor.point ? (
                      `${sensor.point.equipment_name} — ${sensor.point.point_name}`
                    ) : (
                      <span className={styles.missing}>не привязан</span>
                    )}
                  </td>
                  <td>
                    {sensor.last_measured_at ? (
                      <>
                        {sensor.last_sensor_ok ? formatTemperature(sensor.last_temperature) : "ошибка датчика"} ·{" "}
                        {formatAge(sensor.last_measured_at)}
                        {sensor.last_unassigned && <div className={styles.muted}>получено без привязки к точке</div>}
                        <div className={styles.muted}>
                          {formatDateTime(sensor.last_measured_at, sensor.point?.timezone ?? "Asia/Vladivostok")}
                        </div>
                      </>
                    ) : (
                      <span className={styles.missing}>нет данных</span>
                    )}
                  </td>
                  <td>{sensor.has_token ? "выдан" : <span className={styles.missing}>отозван</span>}</td>
                  <td className="no-print">
                    <div className={styles.row}>
                      <button type="button" className="link" onClick={() => setModal({ kind: "history", sensor })}>
                        История
                      </button>
                      {isOwner && (
                        <>
                          <button type="button" className="link" onClick={() => setModal({ kind: "assign", sensor })}>
                            {sensor.assignment ? "Перепривязать" : "Привязать"}
                          </button>
                          {sensor.assignment && (
                            <button
                              type="button"
                              className="link"
                              onClick={() => {
                                if (window.confirm(`Отвязать ${sensor.hardware_id} от точки?`))
                                  unassign.mutate(sensor.id);
                              }}
                            >
                              Отвязать
                            </button>
                          )}
                          <button
                            type="button"
                            className="link"
                            onClick={() => {
                              if (window.confirm("Выпустить новый ключ? Старый сразу перестанет работать.")) {
                                reissue.mutate(sensor.id, {
                                  onSuccess: (issued) => setModal({ kind: "token", issued }),
                                });
                              }
                            }}
                          >
                            Новый ключ
                          </button>
                          {sensor.has_token && (
                            <button
                              type="button"
                              className="link"
                              onClick={() => {
                                if (window.confirm("Отозвать ключ? Устройство не сможет отправлять показания.")) {
                                  revoke.mutate(sensor.id);
                                }
                              }}
                            >
                              Отозвать ключ
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <Dialog title="Новый датчик" open={modal?.kind === "register"} onClose={close}>
        <RegisterForm onCancel={close} onIssued={(issued) => setModal({ kind: "token", issued })} />
      </Dialog>
      <Dialog title="Ключ устройства" open={modal?.kind === "token"} onClose={close}>
        {modal?.kind === "token" && <TokenNotice issued={modal.issued} />}
        <Actions>
          <button type="button" onClick={close}>
            Я сохранил ключ
          </button>
        </Actions>
      </Dialog>
      <Dialog title="Привязка к точке" open={modal?.kind === "assign"} onClose={close}>
        {modal?.kind === "assign" && <AssignForm sensor={modal.sensor} onDone={close} />}
      </Dialog>
      <Dialog
        title={modal?.kind === "history" ? `История ${modal.sensor.hardware_id}` : "История"}
        open={modal?.kind === "history"}
        onClose={close}
      >
        {modal?.kind === "history" && <History sensorId={modal.sensor.id} />}
      </Dialog>
    </div>
  );
}
