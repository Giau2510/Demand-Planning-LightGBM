import {
  ArrowRightLeft, ArrowUpDown, BadgeCheck, Bell, BellOff, BookOpen, Brain, Calendar, CalendarClock, CalendarRange, Camera,
  ChartColumnBig, ChartLine, ChartNoAxesCombined,
  ChevronLeft, ChevronRight, CircleAlert, CircleCheck, CircleDashed, CircleX, Clock, Code, Database, DatabaseBackup, Download,
  ExternalLink, FileSpreadsheet, FileText, FileUp, FlaskConical, FolderClock, Funnel, FunnelX, Gauge, GitCompareArrows, HardDrive,
  History, Inbox, Info, KeyRound, Languages, Layers, LayoutDashboard, ListChecks, LoaderCircle, LogIn, LogOut, Menu, Package,
  PanelLeftClose, PanelLeftOpen, Percent, Play, Power, RefreshCw, Save, Search, Server, ShieldAlert, ShieldCheck, SlidersHorizontal,
  Trash2, TrendingUp, TriangleAlert, Undo2, Upload, Warehouse, X, type LucideIcon,
} from "lucide-react";

/** 1.2.5: the ONE icon set of the app (lucide, ISC licence, version pinned in package.json). Pages use these
 *  semantic names, never lucide directly, so one meaning always has one picture. Icons are decorative
 *  (aria-hidden): every icon sits next to a text label, or its button carries an aria-label + tooltip. */
export const ICON = {
  // pages (sidebar + page headers)
  dashboard: LayoutDashboard, results: TrendingUp, history: History, performance: Gauge, snapshots: Camera,
  methodology: BookOpen, import: FileUp, batches: FolderClock, quality: ShieldCheck, config: SlidersHorizontal,
  bigquery: Database, mapping: ArrowRightLeft, sql: Code, features: Layers, schedules: CalendarClock, jobs: ListChecks,
  system: Server, fhistory: GitCompareArrows,
  // business objects
  sku: Package, fc: Warehouse, model: Brain, chart: ChartLine, explain: ChartNoAxesCombined, calendar: Calendar,
  clock: Clock, demo: FlaskConical, file: FileText, backup: DatabaseBackup, disk: HardDrive, alerts: Bell,
  actual: ChartColumnBig, deviation: ArrowUpDown, percent: Percent, dateRange: CalendarRange,
  // actions
  export: FileSpreadsheet, download: Download, upload: Upload, search: Search, filter: Funnel, clearFilter: FunnelX,
  refresh: RefreshCw, run: Play, save: Save, delete: Trash2, reset: Undo2, power: Power, promote: BadgeCheck, ack: BellOff,
  signin: LogIn, signout: LogOut, key: KeyRound, close: X, menu: Menu, collapse: PanelLeftClose, expand: PanelLeftOpen,
  language: Languages, prev: ChevronLeft, next: ChevronRight, open: ExternalLink, settingsHistory: History,
  // production-affecting action marker (never a status on its own: the button text says what it does)
  prod: ShieldAlert,
  // states (always next to a text)
  ok: CircleCheck, warn: TriangleAlert, bad: CircleX, error: CircleAlert, info: Info, muted: CircleDashed,
  running: LoaderCircle, pending: Clock, empty: Inbox,
} satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICON;

/** Sizes of the design system: 12 (in badges), 14 (inline / small buttons), 16 (default), 20 (page headers). */
export function Icon({ name, size = 16, className }: { name: IconName; size?: 12 | 14 | 16 | 18 | 20 | 24 | 28; className?: string }) {
  const C = ICON[name];
  return <C size={size} strokeWidth={2} aria-hidden="true" focusable="false" className={className ? `ic ${className}` : "ic"} />;
}
