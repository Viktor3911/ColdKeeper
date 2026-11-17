// Names for the generated OpenAPI types (src/api/schema.d.ts is produced by `task api-types`).
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Session = Schemas["SessionOut"];
export type Meta = Schemas["MetaOut"];
export type Inventory = Schemas["InventoryOut"];
export type Site = Schemas["SiteOut"];
export type SiteInput = Schemas["SiteIn"];
export type Room = Schemas["RoomOut"];
export type Equipment = Schemas["EquipmentOut"];
export type EquipmentKind = Schemas["EquipmentKind"];
export type Point = Schemas["PointOut"];
export type PointSettings = Schemas["PointSettingsBody"];
export type PointOverview = Schemas["PointOverviewOut"];
export type PointStatus = Schemas["PointStatus"];
export type EquipmentCard = Schemas["EquipmentCardOut"];
export type SeriesPoint = Schemas["SeriesPointOut"];
export type Sensor = Schemas["SensorOut"];
export type SensorDetail = Schemas["SensorDetailOut"];
export type SensorKind = Schemas["SensorKind"];
export type IssuedToken = Schemas["TokenOut"];
export type Location = Schemas["LocationOut"];
export type Journal = Schemas["JournalOut"];
export type JournalRow = Schemas["JournalRowOut"];
export type RawJournal = Schemas["RawOut"];
export type Incident = Schemas["IncidentOut"];
export type IncidentEvent = Schemas["EventOut"];
export type Recipients = Schemas["RecipientsOut"];
export type Recipient = Schemas["RecipientOut"];
export type BindingCode = Schemas["BindingCodeOut"];
