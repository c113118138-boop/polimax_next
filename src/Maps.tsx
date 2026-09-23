import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup,
  Polyline,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import {
  CarFront,
  MapPin,
  RefreshCw,
  Radio,
  Search,
  Signal,
  Clock3,
  ArrowRight,
  Telescope,
} from "lucide-react";
import { api, Resource, dateTime, localInput } from "./api";
import { Empty, ErrorBox, Field, Loading, PageHead } from "./ui";
function Focus({ points }: { points: any[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 1) map.setView([points[0].lat, points[0].lng], 14);
    else if (points.length > 1)
      map.fitBounds(
        points.map((p) => [p.lat, p.lng]),
        { padding: [45, 45], maxZoom: 15 },
      );
  }, [points, map]);
  return null;
}
function recentTrajectoryRange(days: number, end = new Date()) {
  return {
    from: localInput(
      new Date(end.getTime() - days * 24 * 60 * 60 * 1000).toISOString(),
    ),
    to: localInput(end.toISOString()),
  };
}
export function Positions() {
  const [params] = useSearchParams();
  const [initialRange] = useState(() => recentTrajectoryRange(30));
  const [range, setRange] = useState(
    params.get("start") || params.get("end") ? "custom" : "30",
  );
  const resources = useQuery({
      queryKey: ["resources"],
      queryFn: () => api<Resource[]>("/resources"),
    }),
    positions = useQuery({
      queryKey: ["positions"],
      queryFn: () => api<any[]>("/positions"),
    });
  const [selected, setSelected] = useState(Number(params.get("resource")) || 0),
    [mode, setMode] = useState(params.get("start") ? "history" : "latest"),
    [from, setFrom] = useState(
      params.get("start")
        ? localInput(params.get("start")!)
        : initialRange.from,
    ),
    [to, setTo] = useState(
      params.get("end") ? localInput(params.get("end")!) : initialRange.to,
    ),
    [points, setPoints] = useState<any[]>([]),
    [searched, setSearched] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState("");
  const rs = (resources.data || []).filter((r) =>
      ["vehicle", "equipment"].includes(r.kind),
    ),
    r = rs.find((r) => r.id === selected),
    position = positions.data?.find((p) => p.resource_id === selected),
    shown =
      mode === "history"
        ? points
        : position && position.lat != null && position.lng != null
          ? [position]
          : [];
  function clearHistory() {
    setPoints([]);
    setSearched(false);
    setError("");
  }
  function changeRange(value: string) {
    setRange(value);
    if (value !== "custom") {
      const dates = recentTrajectoryRange(Number(value));
      setFrom(dates.from);
      setTo(dates.to);
    }
    clearHistory();
  }
  async function history() {
    setPoints([]);
    setError("");
    setSearched(true);
    if (!selected || r?.kind !== "vehicle") {
      setError("請先選擇車輛");
      return;
    }
    setBusy(true);
    try {
      const result = await api(
        "/trajectory/" +
          selected +
          "?start=" +
          encodeURIComponent(from) +
          "&end=" +
          encodeURIComponent(to),
      );
      setPoints(result.points);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (params.get("start") && resources.data) history();
  }, [resources.data]);
  return (
    <>
      <PageHead
        eyebrow="LOCATION & ACTIVITY"
        title="資源在哪裡，一目瞭然。"
        description="查看最新收到的位置與車輛歷史軌跡，掌握資源動態。"
        action={
          <button
            className="button"
            disabled={positions.isFetching}
            onClick={() => positions.refetch()}
          >
            <RefreshCw
              size={16}
              className={positions.isFetching ? "spin" : ""}
            />
            刷新位置
          </button>
        }
      />
      <div className="info-note">
        <MapPin size={17} />
        此頁顯示已保存的測試報告；報告時間不會因刷新變動。外部圖資由
        OpenStreetMap 提供。
      </div>
      <div className="map-layout">
        <aside className="panel map-resources">
          <div className="section-title">
            <h3>選擇資源</h3>
            <span className="count-pill">{rs.length}</span>
          </div>
          <div className="search-input">
            <Search size={16} />
            <input
              placeholder="搜尋車牌或設備"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div
            className="map-resource-list"
            role="region"
            aria-label="資源清單"
            tabIndex={0}
          >
            {rs
              .filter((r) =>
                [r.label, r.name, r.model]
                  .join(" ")
                  .toLowerCase()
                  .includes(search.toLowerCase()),
              )
              .map((r) => (
                <button
                  key={r.id}
                  className={
                    "map-resource " + (selected === r.id ? "active" : "")
                  }
                  onClick={() => {
                    setSelected(r.id);
                    setPoints([]);
                    setSearched(false);
                    setError("");
                    if (r.kind !== "vehicle") setMode("latest");
                  }}
                >
                  <div
                    className={
                      "resource-icon " +
                      (r.kind === "vehicle" ? "type-A" : "type-E")
                    }
                  >
                    {r.kind === "vehicle" ? (
                      <CarFront size={21} />
                    ) : (
                      <Telescope size={21} />
                    )}
                  </div>
                  <span>
                    <strong>{r.label}</strong>
                    <small>{r.model || r.name}</small>
                  </span>
                  <Chevron />
                </button>
              ))}
          </div>
        </aside>
        <section className="panel map-panel">
          <div className="list-tabs">
            <button
              className={mode === "latest" ? "active" : ""}
              onClick={() => {
                setMode("latest");
                setError("");
              }}
            >
              最新位置
            </button>
            <button
              className={mode === "history" ? "active" : ""}
              onClick={() => {
                setMode("history");
                setPoints([]);
                setSearched(false);
              }}
            >
              車輛歷史軌跡
            </button>
          </div>
          {mode === "history" && (
            <form
              className="trajectory-filters"
              onSubmit={(e) => {
                e.preventDefault();
                history();
              }}
            >
              <Field label="時間範圍">
                <select
                  value={range}
                  disabled={busy}
                  onChange={(e) => changeRange(e.target.value)}
                >
                  <option value="30">30天</option>
                  <option value="60">60天</option>
                  <option value="90">90天</option>
                  <option value="custom">自訂時間</option>
                </select>
              </Field>
              <Field label="開始時間">
                <input
                  type="datetime-local"
                  step="1"
                  required
                  value={from}
                  disabled={busy}
                  onChange={(e) => {
                    setFrom(e.target.value);
                    setRange("custom");
                    clearHistory();
                  }}
                />
              </Field>
              <Field label="結束時間">
                <input
                  type="datetime-local"
                  step="1"
                  required
                  value={to}
                  disabled={busy}
                  onChange={(e) => {
                    setTo(e.target.value);
                    setRange("custom");
                    clearHistory();
                  }}
                />
              </Field>
              <button className="button primary" disabled={busy}>
                {busy ? "查詢中…" : "查詢軌跡"}
              </button>
            </form>
          )}
          <ErrorBox error={error || resources.error || positions.error} />
          <div className="map-canvas">
            <MapContainer
              center={[24.81, 120.98]}
              zoom={12}
              style={{ height: "100%", width: "100%" }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {shown.map((p, i) => (
                <CircleMarker
                  key={i}
                  center={[p.lat, p.lng]}
                  radius={i === 0 || i === shown.length - 1 ? 8 : 4}
                  pathOptions={{
                    color:
                      i === 0
                        ? "#29806a"
                        : i === shown.length - 1
                          ? "#c35b4d"
                          : "#5086b5",
                    fillOpacity: 0.9,
                  }}
                >
                  <Popup>
                    <strong>
                      {mode === "latest"
                        ? r?.label
                        : i === 0
                          ? "起點"
                          : i === shown.length - 1
                            ? "終點"
                            : "中繼點"}
                    </strong>
                    <br />
                    {dateTime(p.time)}
                    <br />
                    {p.lat.toFixed(5)}, {p.lng.toFixed(5)}
                    <br />
                    虛構測試點位
                  </Popup>
                </CircleMarker>
              ))}
              {shown.length > 1 && (
                <Polyline
                  positions={shown.map((p) => [p.lat, p.lng])}
                  pathOptions={{
                    color: "#388976",
                    weight: 3,
                    dashArray: "6 7",
                  }}
                />
              )}
              <Focus points={shown} />
            </MapContainer>
            {!selected && (
              <div className="map-overlay">
                <MapPin size={26} />
                <strong>選擇一項資源，查看位置</strong>
                <span>車輛與設備最新資料會顯示在這裡</span>
              </div>
            )}
          </div>
          {selected > 0 && mode === "latest" && (
            <div className="position-detail">
              <div>
                <small>目前資源</small>
                <strong>{r?.label}</strong>
              </div>
              <div>
                <small>座標</small>
                <strong>
                  {position?.lat != null && position?.lng != null
                    ? position.lat.toFixed(5) + ", " + position.lng.toFixed(5)
                    : "無有效座標資料"}
                </strong>
              </div>
              <div>
                <small>位置記錄時間</small>
                <strong>{position ? dateTime(position.time) : "—"}</strong>
              </div>
              <div>
                <small>最新接收時間</small>
                <strong>
                  {position?.updated_at ? dateTime(position.updated_at) : "—"}
                </strong>
              </div>
              <div>
                <small>來源</small>
                <strong>{position?.source || "N/A"}</strong>
              </div>
            </div>
          )}
          {mode === "history" &&
            searched &&
            !busy &&
            !error &&
            points.length === 0 && (
              <Empty title="查詢無結果" description="請調整搜尋條件後重試。" />
            )}
          {mode === "history" && points.length > 0 && (
            <div className="trajectory-results">
              <strong>共 {points.length} 個測試位置點</strong>
              <span>
                {dateTime(points[0].time)} → {dateTime(points.at(-1).time)}
              </span>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
function Chevron() {
  return <ArrowRight size={15} />;
}
export function Scans() {
  const [station, setStation] = useState("");
  const stations = useQuery({
    queryKey: ["stations"],
    queryFn: () => api<string[]>("/stations"),
  });
  const query = useQuery({
    queryKey: ["scans", station],
    queryFn: () => api<any[]>("/scans?station=" + station),
    enabled: !!station,
    refetchInterval: station ? 10000 : false,
  });
  const list = query.data || [],
    online = list.filter((x) => x.status === "online").length;
  return (
    <>
      <PageHead
        eyebrow="ON-SITE VISIBILITY"
        title="設備場內資訊"
        description="選擇掃描站，查看場內設備的最新回報與連線狀態。"
        action={
          <span className="pill">
            <Radio size={15} />每 10 秒刷新
          </span>
        }
      />
      <section className="panel scan-filter">
        <Field label="掃描站">
          <select value={station} onChange={(e) => setStation(e.target.value)}>
            <option value="">請選擇掃描站</option>
            {stations.data?.map((id) => (
              <option key={id}>{id}</option>
            ))}
          </select>
        </Field>
        <span className="muted">虛構測試資料 · 5 分鐘內有回報為在線</span>
        {station && (
          <button
            className="button compact"
            disabled={query.isFetching}
            onClick={() => query.refetch()}
          >
            <RefreshCw size={15} />
            刷新
          </button>
        )}
      </section>
      {!station ? (
        <section className="panel">
          <Empty
            title="先選擇一個掃描站"
            description="這裡會顯示設備名稱、訊號強度與最後回報時間。"
          />
        </section>
      ) : (
        <>
          <div className="stats-grid scan-stats">
            {[
              ["設備總數", list.length, "全部掃描到的設備"],
              ["在線設備", online, "最近 5 分鐘內有回報"],
              ["離線設備", list.length - online, "距離最後回報已達 5 分鐘"],
            ].map(([label, count, note]) => (
              <div className="stat-card" key={label}>
                <div className="stat-top">
                  {label}
                  <Signal size={18} />
                </div>
                <div className="stat-number">
                  {count}
                  <span>項</span>
                </div>
                <div className="stat-note">{note}</div>
              </div>
            ))}
          </div>
          <section className="panel">
            <div className="section-title padded">
              <h3>{station}</h3>
              <small className="muted">
                最近查詢：
                {query.dataUpdatedAt
                  ? dateTime(new Date(query.dataUpdatedAt).toISOString())
                  : "—"}
              </small>
            </div>
            <ErrorBox error={query.error} />
            {query.isPending ? (
              <Loading />
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>設備名稱</th>
                      <th>RSSI</th>
                      <th>ChargePower</th>
                      <th>最後掃描時間</th>
                      <th>狀態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <strong>{d.name}</strong>
                          <small>Major {d.id}</small>
                        </td>
                        <td>{d.rssi} dBm</td>
                        <td>
                          {d.power}
                          <small>來源原值</small>
                        </td>
                        <td>{dateTime(d.time)}</td>
                        <td>
                          <span
                            className={
                              "status " +
                              (d.status === "online"
                                ? "status-PENDING"
                                : "status-offline")
                            }
                          >
                            <i />
                            {d.status === "online" ? "在線" : "離線"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
export function FindMy() {
  const beacons = useQuery({
    queryKey: ["beacons"],
    queryFn: () => api<any[]>("/beacons"),
  });
  const [id, setId] = useState(""),
    [search, setSearch] = useState("");
  const report = useQuery({
    queryKey: ["findmy", id],
    queryFn: () => api<any>("/findmy/" + encodeURIComponent(id)),
    enabled: !!id,
  });
  const points = report.data?.points?.slice(0, 1) || [];
  return (
    <>
      <PageHead
        eyebrow="FINDMY REPORTS"
        title="Beacon 設備位置"
        description="依十六進位 Beacon ID 查詢最新保存的定位報告。"
      />
      <section className="panel detail-content">
        <div className="list-filters">
          <input
            placeholder="搜尋 Beacon 名稱或 ID"
            aria-label="搜尋定位設備"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            aria-label="定位設備"
            value={id}
            onChange={(e) => setId(e.target.value)}
          >
            <option value="">選擇設備</option>
            {beacons.data
              ?.filter((b) =>
                [b.id, b.owner]
                  .join(" ")
                  .toLowerCase()
                  .includes(search.toLowerCase()),
              )
              .map((b) => (
                <option key={b.id} value={b.id}>
                  {b.owner} · {b.id}
                </option>
              ))}
          </select>
          <button
            className="button"
            disabled={!id || report.isFetching}
            onClick={() => report.refetch()}
          >
            刷新
          </button>
        </div>
        <ErrorBox error={beacons.error || report.error} />
        {id && report.isPending ? (
          <Loading />
        ) : !id ? (
          <Empty title="請選擇設備" />
        ) : points.length ? (
          <>
            <p>
              {report.data.beacon.owner} · {id} → major{" "}
              {report.data.beacon.major}
            </p>
            <p>
              位置時間：{dateTime(points[0].time)} · 接收時間：
              {dateTime(points[0].created_at)}
            </p>
            <div style={{ height: 400 }}>
              <MapContainer
                center={[points[0].lat, points[0].lng]}
                zoom={14}
                style={{ height: "100%" }}
              >
                <TileLayer
                  attribution="© OpenStreetMap"
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <CircleMarker center={[points[0].lat, points[0].lng]}>
                  <Popup>
                    {report.data.beacon.owner}
                    <br />
                    {dateTime(points[0].time)}
                  </Popup>
                </CircleMarker>
                <Focus points={points} />
              </MapContainer>
            </div>
          </>
        ) : (
          <Empty title="此設備沒有有效定位報告" />
        )}
      </section>
    </>
  );
}
