import { useState, type ReactNode, type SyntheticEvent } from "react";
import { Link } from "react-router";

import { api } from "../api/client";
import { useChange, useInventory } from "../api/queries";
import type { Equipment, EquipmentKind, Inventory, Point, PointSettings, Room, Site } from "../api/types";
import { DEFAULT_SETTINGS, PointForm } from "../components/PointForm";
import { Actions, Dialog, Empty, ErrorState, Field, FormError, FormGrid, Hint, Loading } from "../components/ui";
import { useAuth } from "../auth";
import { EQUIPMENT_KINDS, formatTemperature } from "../format";
import styles from "./Page.module.css";

const TIMEZONES = [
  "Asia/Vladivostok",
  "Asia/Sakhalin",
  "Asia/Magadan",
  "Asia/Kamchatka",
  "Asia/Yakutsk",
  "Asia/Irkutsk",
  "Asia/Krasnoyarsk",
  "Asia/Novosibirsk",
  "Asia/Omsk",
  "Asia/Yekaterinburg",
  "Europe/Samara",
  "Europe/Moscow",
  "Europe/Kaliningrad",
];

type Editor =
  | { kind: "site"; site?: Site }
  | { kind: "room"; siteId: string; room?: Room }
  | { kind: "equipment"; roomId: string; equipment?: Equipment }
  | { kind: "point"; equipmentId: string; point?: Point }
  | null;

const REFRESH = [["inventory"], ["overview"], ["equipment"]];

function SiteForm({ site, onDone }: { site?: Site; onDone: () => void }) {
  const [name, setName] = useState(site?.name ?? "");
  const [address, setAddress] = useState(site?.address ?? "");
  const [timezone, setTimezone] = useState(site?.timezone ?? "Asia/Vladivostok");
  const [controlTime, setControlTime] = useState((site?.control_time ?? "10:00:00").slice(0, 5));
  const [windowMinutes, setWindowMinutes] = useState(String(site?.control_window_minutes ?? 30));
  const save = useChange(
    (body: object) => (site ? api.put(`/api/v1/sites/${site.id}`, body) : api.post("/api/v1/sites", body)),
    REFRESH,
  );

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    save.mutate(
      { name, address, timezone, control_time: `${controlTime}:00`, control_window_minutes: Number(windowMinutes) },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={submit}>
      <FormGrid>
        <Field label="Название объекта">
          {(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} required />}
        </Field>
        <Field label="Адрес">
          {(id) => <input id={id} value={address} onChange={(e) => setAddress(e.target.value)} />}
        </Field>
        <Field label="Часовой пояс" hint="Границы суток журнала считаются в этом поясе">
          {(id) => (
            <select id={id} value={timezone} onChange={(e) => setTimezone(e.target.value)}>
              {(TIMEZONES.includes(timezone) ? TIMEZONES : [timezone, ...TIMEZONES]).map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Контрольное время журнала" hint="Первое корректное измерение после этого времени">
          {(id) => (
            <input id={id} type="time" value={controlTime} onChange={(e) => setControlTime(e.target.value)} required />
          )}
        </Field>
        <Field label="Окно контрольного измерения, мин">
          {(id) => (
            <input
              id={id}
              type="number"
              min={1}
              max={360}
              value={windowMinutes}
              onChange={(e) => setWindowMinutes(e.target.value)}
            />
          )}
        </Field>
      </FormGrid>
      <p>
        <Hint>Правило ежедневного журнала — настройка ColdKeeper, а не требование нормативного документа.</Hint>
      </p>
      <FormError error={save.error} />
      <Actions>
        <button type="button" className="secondary" onClick={onDone}>
          Отмена
        </button>
        <button type="submit" disabled={save.isPending}>
          Сохранить
        </button>
      </Actions>
    </form>
  );
}

function NameForm({
  label,
  initial,
  busy,
  error,
  extra,
  onSubmit,
  onCancel,
}: {
  label: string;
  initial: string;
  busy: boolean;
  error: unknown;
  extra?: ReactNode;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(name);
      }}
    >
      <FormGrid>
        <Field label={label}>
          {(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} required />}
        </Field>
        {extra}
      </FormGrid>
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

function RoomForm({ siteId, room, onDone }: { siteId: string; room?: Room; onDone: () => void }) {
  const save = useChange((name: string) => {
    const body = { site_id: siteId, name };
    return room ? api.put(`/api/v1/rooms/${room.id}`, body) : api.post("/api/v1/rooms", body);
  }, REFRESH);
  return (
    <NameForm
      label="Название помещения"
      initial={room?.name ?? ""}
      busy={save.isPending}
      error={save.error}
      onCancel={onDone}
      onSubmit={(name) => save.mutate(name, { onSuccess: onDone })}
    />
  );
}

function EquipmentForm({ roomId, equipment, onDone }: { roomId: string; equipment?: Equipment; onDone: () => void }) {
  const [kind, setKind] = useState<EquipmentKind>(equipment?.kind ?? "refrigerator");
  const save = useChange((name: string) => {
    const body = { room_id: roomId, name, kind };
    return equipment ? api.put(`/api/v1/equipment/${equipment.id}`, body) : api.post("/api/v1/equipment", body);
  }, REFRESH);
  return (
    <NameForm
      label="Название оборудования"
      initial={equipment?.name ?? ""}
      busy={save.isPending}
      error={save.error}
      onCancel={onDone}
      onSubmit={(name) => save.mutate(name, { onSuccess: onDone })}
      extra={
        <Field label="Тип">
          {(id) => (
            <select id={id} value={kind} onChange={(e) => setKind(e.target.value as EquipmentKind)}>
              {Object.entries(EQUIPMENT_KINDS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
      }
    />
  );
}

function PointEditor({ equipmentId, point, onDone }: { equipmentId: string; point?: Point; onDone: () => void }) {
  const save = useChange((args: { name: string; settings: PointSettings }) => {
    const body = { equipment_id: equipmentId, ...args };
    return point ? api.put(`/api/v1/points/${point.id}`, body) : api.post("/api/v1/points", body);
  }, REFRESH);
  return (
    <PointForm
      name={point?.name ?? ""}
      settings={point?.settings ?? DEFAULT_SETTINGS}
      busy={save.isPending}
      error={save.error}
      onCancel={onDone}
      onSubmit={(name, settings) => save.mutate({ name, settings }, { onSuccess: onDone })}
    />
  );
}

const TITLES = { site: "объект", room: "помещение", equipment: "оборудование", point: "точку измерения" };

function editorTitle(editor: Editor): string {
  if (editor === null) return "";
  const existing =
    (editor.kind === "site" && editor.site) ||
    (editor.kind === "room" && editor.room) ||
    (editor.kind === "equipment" && editor.equipment) ||
    (editor.kind === "point" && editor.point);
  return `${existing ? "Изменить" : "Добавить"} ${TITLES[editor.kind]}`;
}
const PATHS = { site: "sites", room: "rooms", equipment: "equipment", point: "points" };

function Tree({ inventory, edit }: { inventory: Inventory; edit: (editor: Editor) => void }) {
  const { isOwner } = useAuth();
  const remove = useChange(
    (args: { kind: keyof typeof PATHS; id: string }) => api.delete(`/api/v1/${PATHS[args.kind]}/${args.id}`),
    REFRESH,
  );

  function controls(kind: keyof typeof PATHS, id: string, onEdit: () => void, name: string) {
    if (!isOwner) return null;
    return (
      <>
        <button type="button" className="link" onClick={onEdit}>
          Изменить
        </button>
        <button
          type="button"
          className="link"
          onClick={() => {
            if (window.confirm(`Удалить ${TITLES[kind]} «${name}»? Удалить можно только пустой элемент без истории.`)) {
              remove.mutate({ kind, id });
            }
          }}
        >
          Удалить
        </button>
      </>
    );
  }

  return (
    <>
      <FormError error={remove.error} />
      <ul className={styles.tree}>
        {inventory.sites.map((site) => (
          <li key={site.id}>
            <div className={styles.node}>
              <span className={styles.nodeName}>{site.name}</span>
              <span className={styles.muted}>
                {site.address || "адрес не указан"} · {site.timezone} · контроль {site.control_time.slice(0, 5)}
              </span>
              {controls("site", site.id, () => edit({ kind: "site", site }), site.name)}
              {isOwner && (
                <button type="button" className="link" onClick={() => edit({ kind: "room", siteId: site.id })}>
                  + помещение
                </button>
              )}
            </div>
            <ul>
              {inventory.rooms
                .filter((room) => room.site_id === site.id)
                .map((room) => (
                  <li key={room.id}>
                    <div className={styles.node}>
                      <span className={styles.nodeName}>{room.name}</span>
                      {controls("room", room.id, () => edit({ kind: "room", siteId: site.id, room }), room.name)}
                      {isOwner && (
                        <button
                          type="button"
                          className="link"
                          onClick={() => edit({ kind: "equipment", roomId: room.id })}
                        >
                          + оборудование
                        </button>
                      )}
                    </div>
                    <ul>
                      {inventory.equipment
                        .filter((item) => item.room_id === room.id)
                        .map((item) => (
                          <li key={item.id}>
                            <div className={styles.node}>
                              <Link to={`/equipment/${item.id}`} className={styles.nodeName}>
                                {item.name}
                              </Link>
                              <span className={styles.muted}>{EQUIPMENT_KINDS[item.kind]}</span>
                              {controls(
                                "equipment",
                                item.id,
                                () => edit({ kind: "equipment", roomId: room.id, equipment: item }),
                                item.name,
                              )}
                              {isOwner && (
                                <button
                                  type="button"
                                  className="link"
                                  onClick={() => edit({ kind: "point", equipmentId: item.id })}
                                >
                                  + точка
                                </button>
                              )}
                            </div>
                            <ul>
                              {inventory.points
                                .filter((point) => point.equipment_id === item.id)
                                .map((point) => (
                                  <li key={point.id} className={styles.node}>
                                    <span>{point.name}</span>
                                    <span className={styles.muted}>
                                      {formatTemperature(point.settings.low_threshold)} …{" "}
                                      {formatTemperature(point.settings.high_threshold)}
                                    </span>
                                    {controls(
                                      "point",
                                      point.id,
                                      () => edit({ kind: "point", equipmentId: item.id, point }),
                                      point.name,
                                    )}
                                  </li>
                                ))}
                            </ul>
                          </li>
                        ))}
                    </ul>
                  </li>
                ))}
            </ul>
          </li>
        ))}
      </ul>
    </>
  );
}

export function InventoryPage() {
  const inventory = useInventory();
  const { isOwner } = useAuth();
  const [editor, setEditor] = useState<Editor>(null);
  const close = () => setEditor(null);

  if (inventory.isPending) return <Loading what="объекты" />;
  if (inventory.isError) return <ErrorState error={inventory.error} retry={() => void inventory.refetch()} />;
  const editing = editorTitle(editor);

  return (
    <div>
      <div className={styles.head}>
        <h1>Объекты и оборудование</h1>
        {isOwner && (
          <button type="button" onClick={() => setEditor({ kind: "site" })}>
            Добавить объект
          </button>
        )}
      </div>
      {inventory.data.sites.length === 0 ? (
        <Empty>Объектов пока нет.{isOwner ? " Начните с кнопки «Добавить объект»." : ""}</Empty>
      ) : (
        <Tree inventory={inventory.data} edit={setEditor} />
      )}
      <Dialog title={editing} open={editor !== null} onClose={close}>
        {editor?.kind === "site" && <SiteForm site={editor.site} onDone={close} />}
        {editor?.kind === "room" && <RoomForm siteId={editor.siteId} room={editor.room} onDone={close} />}
        {editor?.kind === "equipment" && (
          <EquipmentForm roomId={editor.roomId} equipment={editor.equipment} onDone={close} />
        )}
        {editor?.kind === "point" && (
          <PointEditor equipmentId={editor.equipmentId} point={editor.point} onDone={close} />
        )}
      </Dialog>
    </div>
  );
}
