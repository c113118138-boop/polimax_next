import { useRef, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import listPlugin from "@fullcalendar/list";
import interactionPlugin from "@fullcalendar/interaction";
import luxonPlugin from "@fullcalendar/luxon3";
import { can } from "./Access";
import {
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  CarFront,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Plus,
  Building2,
  Telescope,
  SlidersHorizontal,
} from "lucide-react";
import {
  api,
  Booking,
  Resource,
  dateTime,
  localDate,
  kindNames,
  nextStates,
} from "./api";
import { Empty, ErrorBox, Loading, Modal, PageHead, Status } from "./ui";
import { useUser } from "./App";
const colors = ["#388976", "#547eb3", "#9570ad"];
export default function CalendarPage({ onCreate }: { onCreate: () => void }) {
  const navigate = useNavigate(),
    u = useUser(),
    ref = useRef<FullCalendar>(null);
  const resources = useQuery({
      queryKey: ["resources"],
      queryFn: () => api<Resource[]>("/resources"),
    }),
    bookings = useQuery({
      queryKey: ["bookings"],
      queryFn: () => api<Booking[]>("/bookings"),
    });
  const [selectedIds, setSelected] = useState<number[] | null>(null),
    [room, setRoom] = useState(true),
    [equipment, setEquipment] = useState(true),
    [holiday, setHoliday] = useState(true),
    [view, setView] = useState("dayGridMonth"),
    [title, setTitle] = useState(""),
    [detail, setDetail] = useState<Booking | null>(null),
    [day, setDay] = useState(localDate()),
    [selection, setSelection] = useState<{
      start: string;
      end: string;
      resource?: number;
    } | null>(null);
  const holidays = useQuery({
    queryKey: ["holidays"],
    queryFn: () => api<any[]>("/holidays"),
  });
  const showHoliday = ["Enabled", "Visible"].includes(
    u.permissions.ui["calendar.options.holidayToggle"],
  );
  useEffect(() => {
    const timer = setTimeout(() => {
      api("/notifications/check", "POST").catch(() => {});
    }, 2000);
    return () => clearTimeout(timer);
  }, []);
  const cars = resources.data?.filter((r) => r.kind === "vehicle") || [],
    rs = resources.data || [],
    bs = bookings.data || [];
  const selected = selectedIds ?? cars.map((car) => car.id);
  const visible = (b: Booking, s: { resource_id: number }) =>
    b.kind === "A"
      ? selected.includes(s.resource_id)
      : b.kind === "D"
        ? room
        : equipment;
  const events = bs.flatMap((b) =>
    b.slots
      .filter((s) => visible(b, s))
      .map((s, i) => {
        const r = rs.find((r) => r.id === s.resource_id);
        const color =
          b.kind === "D"
            ? "#be873f"
            : b.kind === "E"
              ? "#8970ad"
              : colors[cars.findIndex((c) => c.id === s.resource_id) % 3];
        return {
          id: b.id + "-" + i,
          title: `${b.content.applicant} · ${b.content.title} · ${b.kind === "D" ? r?.label : (b.content.details || []).map((d: any) => [d.city, d.district].filter(Boolean).join("")).join("、")}`,
          start: s.start,
          end: s.end,
          backgroundColor: color + "17",
          borderColor: color + "35",
          textColor: color,
          extendedProps: {
            booking: b,
            label: r?.label,
            resource_id: s.resource_id,
          },
        };
      }),
  );
  const today = localDate(),
    todayBookings = bs.filter((b) =>
      b.slots.some(
        (s) =>
          localDate(new Date(s.start)) <= today &&
          localDate(new Date(s.end)) >= today,
      ),
    ),
    upcoming = bs
      .filter((b) =>
        b.slots.some((s) => new Date(s.end).getTime() >= Date.now()),
      )
      .sort((a, b) => a.slots[0]?.start.localeCompare(b.slots[0]?.start))
      .slice(0, 4);
  function changeView(v: string) {
    setView(v);
    if (v !== "resourceDay") ref.current?.getApi().changeView(v);
    else setDay(localDate(ref.current?.getApi().getDate() || new Date()));
  }
  function shift(direction: number) {
    if (view === "resourceDay") {
      const d = new Date(day + "T12:00:00+08:00");
      d.setDate(d.getDate() + direction);
      setDay(localDate(d));
    } else if (direction < 0) ref.current?.getApi().prev();
    else ref.current?.getApi().next();
  }
  return (
    <>
      <PageHead
        eyebrow="YOUR RESOURCE WORKSPACE"
        title="每一段行程，都安排妥當。"
        description="一覽車輛與空間預約，讓團隊的下一步更從容。"
        action={
          (can(u, "Lending_form", "create") ||
            can(u, "Room_form", "create") ||
            can(u, "Equipment_form", "create")) && (
            <button className="button primary" onClick={onCreate}>
              <Plus size={18} />
              新增預約
            </button>
          )
        }
      />
      <div className="stats-grid">
        {[
          [
            CalendarDays,
            "今日預約",
            todayBookings.length,
            "筆安排",
            "包含車輛、空間與儀器",
            "green",
          ],
          [CarFront, "公務車輛", cars.length, "輛", "有效車輛資產", "blue"],
          [
            Clock3,
            "使用中",
            bs.filter(
              (b) =>
                b.kind === "A" &&
                !["PENDING", "RETURN_ARRIVED"].includes(b.status),
            ).length,
            "筆",
            "已發車，尚未完成還車",
            "orange",
          ],
          [
            Telescope,
            "儀器設備",
            rs.filter((r) => r.kind === "equipment").length,
            "項",
            "設備預約與資產管理",
            "purple",
          ],
        ].map(([Icon, label, count, unit, note, color]: any) => (
          <div className="stat-card" key={label}>
            <div className="stat-top">
              <span>{label}</span>
              <div className={"stat-icon " + color}>
                <Icon size={18} />
              </div>
            </div>
            <div className="stat-number">
              {String(count).padStart(2, "0")}
              <span>{unit}</span>
            </div>
            <div className="stat-note">{note}</div>
          </div>
        ))}
      </div>
      <div className="calendar-layout">
        <section className="panel calendar-panel">
          <div className="calendar-heading">
            <div>
              <h2>
                預約日曆 <span className="count-pill">{bs.length} 筆</span>
              </h2>
              <p>查看資源安排，選取時段即可建立預約</p>
            </div>
            <CalendarDays size={20} className="muted" />
          </div>
          <div className="calendar-controls">
            <div className="calendar-date">
              <h3>
                {view === "resourceDay" ? day.replaceAll("-", " / ") : title}
              </h3>
              <button
                className="icon-button"
                aria-label="上一期"
                onClick={() => shift(-1)}
              >
                <ChevronLeft size={17} />
              </button>
              <button
                className="icon-button"
                aria-label="下一期"
                onClick={() => shift(1)}
              >
                <ChevronRight size={17} />
              </button>
              <button
                className="button compact today-button"
                onClick={() => {
                  setDay(localDate());
                  ref.current?.getApi().today();
                }}
              >
                今天
              </button>
            </div>
            <div className="segmented">
              {[
                ["dayGridMonth", "月"],
                ["timeGridWeek", "週"],
                ["resourceDay", "資源日"],
                ["listWeek", "清單"],
              ].map(([v, label]) => (
                <button
                  key={v}
                  className={view === v ? "active" : ""}
                  onClick={() => changeView(v)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {selected.length === 0 && (
            <div className="calendar-hint">
              <SlidersHorizontal size={15} />
              請勾選右側車牌以顯示車輛預約。作業區預設顯示。
            </div>
          )}
          <ErrorBox error={bookings.error || resources.error} />
          {bookings.isPending ? (
            <Loading />
          ) : (
            <>
              <div
                style={{ display: view === "resourceDay" ? "none" : undefined }}
              >
                <FullCalendar
                  ref={ref}
                  plugins={[
                    dayGridPlugin,
                    timeGridPlugin,
                    listPlugin,
                    interactionPlugin,
                    luxonPlugin,
                  ]}
                  initialView="dayGridMonth"
                  locale="zh-tw"
                  timeZone="Asia/Taipei"
                  headerToolbar={false}
                  height="auto"
                  firstDay={1}
                  dayMaxEvents={3}
                  fixedWeekCount={false}
                  allDayText="全天"
                  noEventsContent="此週沒有符合篩選的預約"
                  buttonText={{
                    today: "今天",
                    month: "月",
                    week: "週",
                    day: "日",
                    list: "清單",
                  }}
                  events={[
                    ...events,
                    ...(holiday
                      ? (holidays.data || []).map((h, i) => ({
                          id: "holiday-" + i,
                          title: h.title,
                          start: h.date,
                          allDay: true,
                          display: "background",
                          backgroundColor: "#f5eedf",
                        }))
                      : []),
                  ]}
                  selectable={
                    can(u, "Lending_form", "create") ||
                    can(u, "Room_form", "create") ||
                    can(u, "Equipment_form", "create")
                  }
                  selectMirror
                  datesSet={(arg) =>
                    setTitle(
                      `${arg.view.currentStart.getFullYear()} 年 ${arg.view.currentStart.getMonth() + 1} 月`,
                    )
                  }
                  dateClick={(arg) => {
                    if (view === "dayGridMonth") {
                      setDay(arg.dateStr);
                      setView("resourceDay");
                    }
                  }}
                  select={(arg) => {
                    if (view === "dayGridMonth") return;
                    setSelection({ start: arg.startStr, end: arg.endStr });
                    ref.current?.getApi().unselect();
                  }}
                  eventClick={(arg) => {
                    if (arg.event.extendedProps.booking)
                      setDetail({
                        ...arg.event.extendedProps.booking,
                        eventResource: arg.event.extendedProps.resource_id,
                      });
                  }}
                  eventContent={(arg) => (
                    <div className="calendar-event">
                      <span>{arg.timeText}</span>
                      <strong>{arg.event.title}</strong>
                      <small>{arg.event.extendedProps.label}</small>
                    </div>
                  )}
                />
              </div>
              {view === "resourceDay" && (
                <div className="resource-grid-wrap">
                  <div
                    className="resource-grid"
                    style={{
                      gridTemplateColumns: `58px repeat(${selected.length + (room ? 1 : 0) + (equipment ? 1 : 0) || 1}, minmax(155px, 1fr))`,
                    }}
                  >
                    <div className="resource-head">時間</div>
                    {[
                      ...cars.filter((c) => selected.includes(c.id)),
                      ...(room ? [{ id: -1, label: "作業區" }] : []),
                      ...(equipment ? [{ id: -2, label: "儀器設備" }] : []),
                    ].map((r) => (
                      <div className="resource-head" key={r.id}>
                        {r.label}
                      </div>
                    ))}
                    {Array.from({ length: 24 }, (_, hour) => (
                      <ResourceHour
                        key={hour}
                        hour={hour}
                        day={day}
                        columns={[
                          ...cars.filter((c) => selected.includes(c.id)),
                          ...(room ? [{ id: -1, label: "作業區" }] : []),
                          ...(equipment ? [{ id: -2, label: "儀器設備" }] : []),
                        ]}
                        bookings={bs}
                        onEvent={setDetail}
                        onSelect={(id, h) => {
                          if (
                            can(u, "Lending_form", "create") ||
                            can(u, "Room_form", "create") ||
                            can(u, "Equipment_form", "create")
                          )
                            setSelection({
                              start: `${day}T${String(h).padStart(2, "0")}:00`,
                              end:
                                h === 23
                                  ? `${localDate(new Date(new Date(day + "T12:00:00+08:00").getTime() + 86400000))}T00:00`
                                  : `${day}T${String(h + 1).padStart(2, "0")}:00`,
                              resource: id > 0 ? id : undefined,
                            });
                        }}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          <div className="calendar-bottom">
            <span>
              <i className="legend-dot green" />
              車輛
            </span>
            <span>
              <i className="legend-dot orange" />
              作業區
            </span>
            <span>
              <i className="legend-dot purple" />
              儀器
            </span>
            <span className="calendar-timezone">時間顯示：臺北 UTC+8</span>
          </div>
        </section>
        <aside className="calendar-aside">
          <section className="panel filter-panel">
            <div className="section-title">
              <h3>資源篩選</h3>
              <SlidersHorizontal size={17} />
            </div>
            <div className="filter-label">
              公務車輛{" "}
              <button
                onClick={() =>
                  setSelected(
                    selected.length === cars.length
                      ? []
                      : cars.map((c) => c.id),
                  )
                }
              >
                {selected.length === cars.length ? "取消全選" : "全選"}
              </button>
            </div>
            {cars.map((car, i) => (
              <label className="resource-check" key={car.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(car.id)}
                  onChange={() =>
                    setSelected((previous) => {
                      const current = previous ?? cars.map((car) => car.id);
                      return current.includes(car.id)
                        ? current.filter((id) => id !== car.id)
                        : [...current, car.id];
                    })
                  }
                />
                <span
                  className="color-dot"
                  style={{ background: colors[i % 3] }}
                />
                <span>
                  <strong>{car.label}</strong>
                  <small>{car.model}</small>
                </span>
              </label>
            ))}
            <div className="filter-divider" />
            <label className="resource-check">
              <input
                type="checkbox"
                checked={room}
                onChange={(e) => setRoom(e.target.checked)}
              />
              <Building2 size={17} className="orange-text" />
              <span>作業區</span>
            </label>
            <label className="resource-check">
              <input
                type="checkbox"
                checked={equipment}
                onChange={(e) => setEquipment(e.target.checked)}
              />
              <Telescope size={17} className="purple-text" />
              <span>儀器設備</span>
            </label>
            <label
              style={{ display: showHoliday ? undefined : "none" }}
              className="resource-check"
            >
              <input
                type="checkbox"
                checked={holiday}
                onChange={(e) => setHoliday(e.target.checked)}
              />
              <CalendarDays size={17} />
              <span>測試假日</span>
            </label>
            <small className="muted">此環境假日為示範資料。</small>
          </section>
          <section className="panel upcoming-panel">
            <div className="section-title">
              <h3>接下來的安排</h3>
              <span className="live-dot" />
            </div>
            {upcoming.length ? (
              upcoming.map((b) => (
                <button
                  className="upcoming"
                  key={b.id}
                  onClick={() => setDetail(b)}
                >
                  <div className={"upcoming-line type-" + b.kind} />
                  <div>
                    <small>{dateTime(b.slots[0]?.start || "")}</small>
                    <strong>{b.content.title}</strong>
                    <span>
                      {b.content.applicant} <i /> {kindNames[b.kind]}
                    </span>
                  </div>
                  <ArrowUpRight size={15} />
                </button>
              ))
            ) : (
              <Empty
                title="暫無後續安排"
                description="新的預約會顯示在這裡。"
              />
            )}
            <button
              className="text-link all-bookings"
              onClick={() => navigate("/bookings")}
            >
              查看所有借用紀錄
              <ArrowRight size={15} />
            </button>
          </section>
          <div className="tip-card">
            <div className="tip-icon">
              <CalendarDays size={20} />
            </div>
            <h3>安排下一段工作</h3>
            <p>點選日曆日期查看資源日視圖，讓每個時段都有清楚的安排。</p>
          </div>
        </aside>
      </div>
      <Modal open={!!detail} title="預約詳情" onClose={() => setDetail(null)}>
        {detail && (
          <>
            <div className="detail-top">
              <span className="mono">{detail.id}</span>
              <Status status={detail.status} />
            </div>
            <h2>{detail.content.title}</h2>
            <div className="summary-grid">
              <div>
                <small>申請人</small>
                <strong>{detail.content.applicant}</strong>
              </div>
              <div>
                <small>預約類型</small>
                <strong>{kindNames[detail.kind]}</strong>
              </div>
            </div>
            {detail.slots.map((s, i) => (
              <div className="slot-summary" key={i}>
                <strong>
                  {rs.find((r) => r.id === s.resource_id)?.label || "歷史資源"}
                </strong>
                <span>
                  {dateTime(s.start)} → {dateTime(s.end)}
                </span>
              </div>
            ))}
            <div className="actions">
              <button
                className="button primary"
                onClick={() =>
                  navigate(
                    "/bookings/" +
                      detail.id +
                      ((detail as any).eventResource
                        ? "?resource=" + (detail as any).eventResource
                        : ""),
                  )
                }
              >
                查看完整申請
                <ArrowRight size={16} />
              </button>
            </div>
          </>
        )}
      </Modal>
      <Modal
        open={!!selection}
        title="預約所選時段"
        onClose={() => setSelection(null)}
      >
        <p className="muted">
          {selection?.start.replace("T", " ")} →{" "}
          {selection?.end.replace("T", " ")}
        </p>
        <div className="create-options">
          {Object.entries(kindNames).map(([k, name]) => (
            <button
              key={k}
              onClick={() =>
                navigate("/bookings/new/" + k, { state: selection })
              }
            >
              <strong>{name}</strong>
              <ArrowRight size={18} />
            </button>
          ))}
        </div>
      </Modal>
    </>
  );
}
function ResourceHour({
  hour,
  day,
  columns,
  bookings,
  onEvent,
  onSelect,
}: {
  hour: number;
  day: string;
  columns: { id: number; label: string }[];
  bookings: Booking[];
  onEvent: (b: Booking) => void;
  onSelect: (id: number, h: number) => void;
}) {
  const start = new Date(
      `${day}T${String(hour).padStart(2, "0")}:00:00+08:00`,
    ).getTime(),
    end = start + 3600000;
  return (
    <>
      <div className="resource-time">{String(hour).padStart(2, "0")}:00</div>
      {columns.map((r) => (
        <div className="resource-cell" key={r.id}>
          <button
            className="slot-add"
            aria-label={`預約 ${r.label} ${hour}:00`}
            onClick={() => onSelect(r.id, hour)}
          />
          {bookings
            .filter((b) =>
              b.slots.some(
                (s) =>
                  (r.id > 0
                    ? s.resource_id === r.id
                    : r.id === -1
                      ? b.kind === "D"
                      : b.kind === "E") &&
                  new Date(s.start).getTime() < end &&
                  new Date(s.end).getTime() >= start,
              ),
            )
            .map((b) => (
              <button
                className={"resource-event type-" + b.kind}
                key={b.id}
                onClick={() => onEvent(b)}
              >
                {b.content.applicant} · {b.content.title}
              </button>
            ))}
        </div>
      ))}
    </>
  );
}
