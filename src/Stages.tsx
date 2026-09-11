import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  Booking,
  Resource,
  dateTime,
  localDate,
  nextStates,
  invalidate,
} from "./api";
import {
  Confirm,
  Empty,
  ErrorBox,
  Field,
  FileUpload,
  Loading,
  Modal,
  PageHead,
} from "./ui";
import { can, bookingDoc, Scope } from "./Access";
import { useUser } from "./App";
const checksB = [
  "擋風玻璃清潔",
  "照後鏡清潔",
  "油量檢查",
  "輪胎檢查",
  "車輛內部清潔",
  "車體外部檢查",
  "隨車設備檢查",
];
const checksC = [
  "車輛內部清潔",
  "車輛內部物品歸位",
  "車輛鑰匙歸位",
  "油量檢查",
  "車體外部檢查",
  "隨車設備檢查",
];
const photoFields = [
  ["interior_files", "車輛內部照片"],
  ["exterior_files", "車體外部異狀照片"],
  ["equipment_files", "設備異狀照片"],
  ["parking_files", "車輛停放地照片"],
];
const initial = () => ({
  driver: "",
  codriver: "",
  employees: [],
  place: "",
  mileage: "",
  confirmed: false,
  checks: [],
  anomalies: [],
  anomaly_details: {},
  attachments: [],
  notes: "",
  tires: "正常",
  interior: "正常",
  exterior: "正常",
  equipment: "正常",
  interior_files: [],
  exterior_files: [],
  equipment_files: [],
  parking_files: [],
});
function PartEditor({
  data: d,
  set,
  kind,
  part,
  booking,
  resources,
}: {
  data: any;
  set: (key: string, v: any) => void;
  kind: string;
  part: string;
  booking?: Booking;
  resources: Resource[];
}) {
  const u = useUser();
  const departure = part === "start";
  const cars =
    booking?.slots
      .map(
        (s) =>
          resources.find((r) => r.id === s.resource_id) ||
          booking.content.resource_snapshots?.find(
            (r: any) => r.id === s.resource_id,
          ),
      )
      .filter(
        (r: any, i: number, a: any[]) =>
          r && a.findIndex((x) => x?.id === r.id) === i,
      ) || [];
  return (
    <div className="fields-grid">
      {departure && (
        <>
          <Field label="車輛" required>
            {d.submitted_at ? (
              <input value={d.plate || ""} readOnly />
            ) : (
              <select
                required
                value={d.resource_id || ""}
                onChange={(e) => set("resource_id", Number(e.target.value))}
              >
                <option value="">選擇本次使用車輛</option>
                {cars.map((r: any) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="預約帶入時間">
            <input
              readOnly
              value={
                d.reservation_start
                  ? dateTime(d.reservation_start)
                  : dateTime(
                      booking?.slots.find(
                        (s) => s.resource_id === d.resource_id,
                      )?.start || "",
                    )
              }
            />
          </Field>
          <Field label="駕駛人員" required>
            <input required value={d.driver || ""} onChange={(e) => set("driver", e.target.value)} placeholder="請填寫駕駛姓名" />
          </Field>
          <Field label="副駕人員（兩人以上必填）">
            <input value={d.codriver || ""} onChange={(e) => set("codriver", e.target.value)} placeholder="請填寫副駕姓名" />
          </Field>
          <Field label="第一位借用人員" required>
            <input readOnly value={d.employees?.[0] || u.name} />
          </Field>
          <Field label="第二位借用人員（選填）">
            <input value={d.employees?.[1] || ""} placeholder="請填寫第二位借用人員姓名"
              onChange={(e) => set("employees", [d.employees?.[0] || u.name, ...(e.target.value ? [e.target.value] : [])])} />
          </Field>
          <div className="span-2">
            <Field
              label={kind === "C" ? "回程發車地點" : "去程發車地點"}
              required
            >
              <input
                required
                value={d.place}
                onChange={(e) => set("place", e.target.value)}
              />
            </Field>
          </div>
          <div className="span-2">
            <Field label="車輛檢查（全部必須確認）" required>
              <div className="purpose-grid">
                {(kind === "B" ? checksB : checksC).map((c) => (
                  <label key={c}>
                    <input
                      type="checkbox"
                      checked={d.checks?.includes(c) || false}
                      onChange={(e) =>
                        set(
                          "checks",
                          e.target.checked
                            ? [...(d.checks || []), c]
                            : d.checks.filter((x: string) => x !== c),
                        )
                      }
                    />
                    {c}
                  </label>
                ))}
              </div>
            </Field>
          </div>
          {(kind === "B"
            ? [
                ["tires", "輪胎"],
                ["interior", "車輛內部"],
                ["exterior", "車體外部"],
                ["equipment", "隨車設備"],
              ]
            : [
                ["exterior", "車體外部"],
                ["equipment", "隨車設備"],
              ]
          ).map(([key, label]) => (
            <div key={key}>
              <Field label={label + "狀況"} required>
                <select
                  value={d[key]}
                  onChange={(e) => set(key, e.target.value)}
                >
                  <option>正常</option>
                  <option>異狀</option>
                </select>
              </Field>
              {d[key] === "異狀" && (
                <Field label={label + "異狀說明"} required>
                  <textarea
                    required
                    value={d[key + "_note"] || ""}
                    onChange={(e) => set(key + "_note", e.target.value)}
                  />
                </Field>
              )}
            </div>
          ))}
          {kind === "C" &&
            photoFields
              .filter(
                ([key]) => key !== "exterior_files" || d.exterior === "異狀",
              )
              .filter(
                ([key]) => key !== "equipment_files" || d.equipment === "異狀",
              )
              .map(([key, label]) => (
                <div className="span-2" key={key}>
                  <Field label={label}>
                    <FileUpload
                      images
                      value={d[key] || []}
                      onChange={(v) => set(key, v)}
                    />
                  </Field>
                </div>
              ))}
        </>
      )}
      <Field label={departure ? "開始里程（km）" : "結束里程（km）"} required>
        <input
          type="number"
          min={0}
          step="0.1"
          required
          value={d.mileage}
          onChange={(e) => set("mileage", e.target.value)}
        />
      </Field>
      <div className="span-2">
        <label className="check-line">
          <input
            type="checkbox"
            required
            checked={d.confirmed}
            onChange={(e) => set("confirmed", e.target.checked)}
          />
          我已確認本階段里程
        </label>
      </div>
      {!departure && (
        <div className="span-2">
          <Field label="途中異常（可複選）">
            <div className="purpose-grid">
              {["維修", "違規", "事故"].map((a) => (
                <label key={a}>
                  <input
                    type="checkbox"
                    checked={d.anomalies?.includes(a) || false}
                    onChange={(e) =>
                      set(
                        "anomalies",
                        e.target.checked
                          ? [...(d.anomalies || []), a]
                          : d.anomalies.filter((v: string) => v !== a),
                      )
                    }
                  />
                  {a}
                </label>
              ))}
            </div>
          </Field>
          {d.anomalies?.map((a: string) => (
            <div className="repeat-card" key={a}>
              <h3>{a}資料</h3>
              {[
                "place",
                "reason",
                ...(a === "維修"
                  ? ["repair_shop"]
                  : a === "事故"
                    ? ["internal_injury", "external_injury"]
                    : []),
                "notes",
              ].map((key) => (
                <Field
                  key={key}
                  field={key}
                  label={
                    (
                      {
                        place: a === "維修" ? "故障地點" : "發生地點",
                        reason: a === "維修" ? "車輛問題部位" : "事由／原因",
                        repair_shop: "維修地點／維修廠",
                        internal_injury: "公司內部人員受傷狀況",
                        external_injury: "對方人員受傷狀況",
                        notes: "備註",
                      } as Record<string, string>
                    )[key]
                  }
                >
                  <input
                    value={d.anomaly_details?.[a]?.[key] || ""}
                    onChange={(e) =>
                      set("anomaly_details", {
                        ...d.anomaly_details,
                        [a]: {
                          ...d.anomaly_details?.[a],
                          [key]: e.target.value,
                        },
                      })
                    }
                  />
                </Field>
              ))}
            </div>
          ))}
        </div>
      )}
      <div className="span-2">
        <Field label="其他附件">
          <FileUpload
            value={d.attachments || []}
            onChange={(v) => set("attachments", v)}
          />
        </Field>
      </div>
      <div className="span-2">
        <Field label="備註">
          <textarea
            rows={3}
            value={d.notes || ""}
            onChange={(e) => set("notes", e.target.value)}
          />
        </Field>
      </div>

    </div>
  );
}
export function StageView({ stage }: { stage: any }) {
  if (!stage) return null;
  return (
    <>
      <span className="mono">
        {stage.id} · 父單 {stage.parent_id}
      </span>
      {["start", "arrival"].map((part) => {
        const d = stage.content[part];
        return (
          <section key={part} className="stage-view">
            <h3>{part === "start" ? "出發紀錄" : "抵達紀錄"}</h3>
            {d ? (
              <>
                <div className="summary-grid">
                  {[
                    ["車牌", d.plate],
                    [
                      "預約帶入時間",
                      d.reservation_start ? dateTime(d.reservation_start) : "—",
                    ],
                    ["里程", d.mileage + " km"],
                    ["階段提交時間", dateTime(d.submitted_at)],
                    [
                      "駕駛／副駕",
                      [d.driver, d.codriver].filter(Boolean).join("／"),
                    ],
                    ["使用人員", d.employees?.join("、")],
                    ["發車地點", d.place],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <small>{label}</small>
                      <strong>{value || "—"}</strong>
                    </div>
                  ))}
                </div>
                {d.checks?.length > 0 && <p>檢查確認：{d.checks.join("、")}</p>}
                {[
                  ["tires", "輪胎"],
                  ["interior", "車輛內部"],
                  ["exterior", "車體外部"],
                  ["equipment", "隨車設備"],
                ].map(
                  ([key, label]) =>
                    d[key] && (
                      <p key={key}>
                        {label}：{d[key]} {d[key + "_note"]}
                      </p>
                    ),
                )}
                {d.anomalies?.map((a: string) => (
                  <div className="review-detail" key={a}>
                    <strong>{a}</strong>
                    <span>
                      {Object.values(d.anomaly_details?.[a] || {})
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                ))}
                {photoFields.map(
                  ([key, label]) =>
                    d[key]?.length > 0 && (
                      <div key={key}>
                        <h4>{label}</h4>
                        <FileUpload
                          readOnly
                          value={d[key]}
                          onChange={() => {}}
                        />
                      </div>
                    ),
                )}
                {"notes" in d && (
                  <p className="preserve-lines">{d.notes || "無備註"}</p>
                )}
                <FileUpload
                  readOnly
                  value={d.attachments || []}
                  onChange={() => {}}
                />
              </>
            ) : (
              <p>尚未填寫抵達紀錄。</p>
            )}
          </section>
        );
      })}
    </>
  );
}
export function StageForm({
  open,
  close,
  booking: b,
}: {
  open: boolean;
  close: () => void;
  booking: Booking;
}) {
  const u = useUser();
  const kind = ["PENDING", "DEPARTURE"].includes(b.status) ? "B" : "C",
    part = ["PENDING", "DEPARTURE_ARRIVED"].includes(b.status)
      ? "start"
      : "arrival";
  const [data, setData] = useState<any>(initial()),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const resources = useQuery({
    queryKey: ["resources"],
    queryFn: () => api<Resource[]>("/resources"),
  });
  useEffect(() => {
    if (open) {
      const preferred = Number(
        new URLSearchParams(location.search).get("resource"),
      );
      const ids = Array.from(new Set(b.slots.map((s) => s.resource_id)));
      setData({
        ...initial(),
        driver: u.name,
        codriver: b.content.employees?.find((name: string) => name !== u.name) || "",
        employees: [u.name, ...(b.content.employees || []).filter((name: string) => name !== u.name).slice(0, 1)],
        resource_id: ids.includes(preferred)
          ? preferred
          : ids.length === 1
            ? ids[0]
            : undefined,
      });
      setError("");
    }
  }, [open]);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/bookings/" + b.id + "/advance", "POST", {
        expected_status: b.status,
        revision: b.revision,
        content: data,
      });
      await invalidate();
      close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open={open}
      title={nextStates[b.status] || "車輛使用紀錄"}
      onClose={() => !busy && close()}
      wide
    >
      <Scope
        doc={
          part === "arrival"
            ? kind === "B"
              ? "departure_arrive"
              : "back_arrive"
            : bookingDoc(kind)
        }
      >
        <p className="info-note">
          {b.id} · 多車主單共用一條流程；每次出發須確認使用車輛。
        </p>
        {part === "arrival" && (
          <details>
            <summary>查看原出發紀錄</summary>
            <StageView stage={b.stages?.find((s) => s.kind === kind)} />
          </details>
        )}
        <form onSubmit={submit}>
          <PartEditor
            data={data}
            set={(k, v) => setData((d: any) => ({ ...d, [k]: v }))}
            kind={kind}
            part={part}
            booking={b}
            resources={resources.data || []}
          />
          <ErrorBox error={error || resources.error} />
          <div className="actions">
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={close}
            >
              取消
            </button>
            <button className="button primary" disabled={busy}>
              {busy ? "保存中…" : "確認提交本階段"}
            </button>
          </div>
        </form>
      </Scope>
    </Modal>
  );
}
export function StagePage() {
  const { id } = useParams(),
    u = useUser();
  const query = useQuery({
    queryKey: ["stage", id],
    queryFn: () => api<any>("/stages/" + id),
  });
  const resources = useQuery({
    queryKey: ["resources"],
    queryFn: () => api<Resource[]>("/resources"),
  });
  const [editing, setEditing] = useState(false),
    [remove, setRemove] = useState(false),
    [data, setData] = useState<any>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorBox error={query.error} />;
  const s = query.data;
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/stages/" + id, "PUT", {
        revision: s.revision,
        content: data,
      });
      await invalidate();
      setEditing(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Scope doc={bookingDoc(s.kind)}>
      <Link to={"/bookings/" + s.parent_id}>返回父申請 {s.parent_id}</Link>
      <PageHead
        eyebrow={s.id}
        title={s.kind === "B" ? "發車與抵達紀錄" : "回程與抵達紀錄"}
        description="修正保留編號及舊版本，父單流程不倒退。"
        action={
          <div className="actions">
            {can(u, bookingDoc(s.kind), "write") && (
              <button
                className="button"
                onClick={() => {
                  setData(structuredClone(s.content));
                  setEditing(true);
                }}
              >
                修正階段內容
              </button>
            )}
            {can(u, bookingDoc(s.kind), "delete") && (
              <button className="button danger" onClick={() => setRemove(true)}>
                刪除階段
              </button>
            )}
          </div>
        }
      />
      <ErrorBox error={error} />
      <section className="panel detail-content">
        <StageView stage={s} />
        <h3>歷史版本</h3>
        {s.versions?.map((v: any) => (
          <details key={v.id}>
            <summary>
              {dateTime(v.time)} · {v.actor}
            </summary>
            <StageView stage={v.data} />
          </details>
        ))}
      </section>
      <Modal
        open={editing}
        title="修正階段內容"
        wide
        onClose={() => !busy && setEditing(false)}
      >
        <form onSubmit={save}>
          {["start", "arrival"]
            .filter((p) => data[p])
            .map((part) => (
              <section key={part}>
                <h3>{part === "start" ? "出發" : "抵達"}</h3>
                <PartEditor
                  data={data[part]}
                  set={(k, v) =>
                    setData((d: any) => ({
                      ...d,
                      [part]: { ...d[part], [k]: v },
                    }))
                  }
                  kind={s.kind}
                  part={part}
                  resources={resources.data || []}
                />
              </section>
            ))}
          <ErrorBox error={error} />
          <div className="actions">
            <button
              type="button"
              className="button"
              onClick={() => setEditing(false)}
              disabled={busy}
            >
              取消
            </button>
            <button className="button primary" disabled={busy}>
              {busy ? "保存中…" : "儲存修訂"}
            </button>
          </div>
        </form>
      </Modal>
      <Confirm
        open={remove}
        title="刪除階段紀錄？"
        description={`${s.id} 將軟刪除；父單會標示資料不完整並停止推進。`}
        onClose={() => setRemove(false)}
        busy={busy}
        onConfirm={async () => {
          setBusy(true);
          try {
            await api("/stages/" + id, "DELETE");
            await invalidate();
            location.href = "/bookings/" + s.parent_id;
          } catch (e) {
            setError((e as Error).message);
            setRemove(false);
          } finally {
            setBusy(false);
          }
        }}
      />
    </Scope>
  );
}
export function StageList() {
  const [params, setParams] = useSearchParams(),
    kind = params.get("kind") === "C" ? "C" : "B";
  const [search, setSearch] = useState(""),
    [from, setFrom] = useState(""),
    [to, setTo] = useState("");
  const q = useQuery({
    queryKey: ["stages", kind],
    queryFn: () => api<any[]>("/stages?kind=" + kind),
  });
  const rows = (q.data || []).filter((s) => {
    const d = localDate(new Date(s.created_at));
    return (
      (!from || d >= from) &&
      (!to || d <= to) &&
      [s.id, s.parent_id, s.content.start?.plate, s.content.start?.driver]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase())
    );
  });
  return (
    <>
      <PageHead
        eyebrow="WORKFLOW RECORDS"
        title="出回程紀錄"
        description="依父單關聯查詢有效 B／C；舊版本保留在個別紀錄。"
      />
      <section className="panel detail-content">
        <div className="list-tabs">
          <button
            onClick={() => setParams({ kind: "B" })}
            className={kind === "B" ? "active" : ""}
          >
            發車 B
          </button>
          <button
            onClick={() => setParams({ kind: "C" })}
            className={kind === "C" ? "active" : ""}
          >
            回程 C
          </button>
        </div>
        <div className="list-filters">
          <input
            aria-label="搜尋階段"
            placeholder="編號、車牌或駕駛"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <input
            aria-label="階段起日"
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <input
            aria-label="階段迄日"
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
          <button
            className="button"
            onClick={() => {
              setSearch("");
              setFrom("");
              setTo("");
            }}
          >
            清除
          </button>
        </div>
        <ErrorBox error={q.error} />
        {q.isPending ? (
          <Loading />
        ) : rows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>編號</th>
                  <th>父單</th>
                  <th>建立時間</th>
                  <th>車牌</th>
                  <th>駕駛</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <Link to={"/stages/" + s.id}>{s.id}</Link>
                    </td>
                    <td>
                      <Link to={"/bookings/" + s.parent_id}>{s.parent_id}</Link>
                    </td>
                    <td>{dateTime(s.created_at)}</td>
                    <td>{s.content.start?.plate}</td>
                    <td>{s.content.start?.driver}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty />
        )}
      </section>
    </>
  );
}
