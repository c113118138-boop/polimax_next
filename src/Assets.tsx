import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  CarFront,
  Telescope,
  Plus,
  Search,
  Pencil,
  Trash2,
  Users,
  MapPin,
  ShieldCheck,
  Wrench,
  FileText,
  Receipt,
  CalendarDays,
  ChevronRight,
  Package,
  Check,
} from "lucide-react";
import { api, Resource, invalidate, localDate } from "./api";
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
import { useUser } from "./App";
import { can, Scope } from "./Access";
const money = (v: any) =>
  v == null || v === ""
    ? "—"
    : new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 2 }).format(
        Number(v),
      );
const accessories = [
  "主機",
  "20V鋰電電池",
  "10.8V鋰電電池",
  "電池",
  "固定件",
  "充電座",
  "充電器",
  "防護罩",
  "校正模具",
  "電源線",
  "感測線",
  "磁性座",
  "鍊條",
  "螺絲攻",
  "鋼刷",
  "轉接頭",
  "輔助固定架",
  "壓接頭",
  "鉤錶",
];
export function Assets({ kind }: { kind: string }) {
  const u = useUser(),
    vehicle = kind === "vehicle";
  const query = useQuery({
    queryKey: ["resources"],
    queryFn: () => api<Resource[]>("/resources"),
    refetchInterval: 5000,
  });
  const [search, setSearch] = useState(""),
    [open, setOpen] = useState(false);
  const list = (query.data || []).filter(
    (r) =>
      r.kind === kind &&
      [r.label, r.name, r.model, r.holder, r.location]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHead
        eyebrow={vehicle ? "FLEET MANAGEMENT" : "EQUIPMENT MANAGEMENT"}
        title={vehicle ? "公務車輛" : "儀器設備"}
        description={
          vehicle
            ? "從基本資料到保險與維護，集中照顧每一輛車。"
            : "整理設備資訊與保管狀態，讓每項工具都找得到。"
        }
        action={
          can(
            u,
            vehicle ? "VehicleManagement" : "EquipmentManagement",
            "create",
          ) && (
            <button className="button primary" onClick={() => setOpen(true)}>
              <Plus size={18} />
              新增{vehicle ? "車輛" : "設備"}
            </button>
          )
        }
      />
      <div className="asset-toolbar">
        <div>
          <strong>{vehicle ? "車輛總覽" : "設備總覽"}</strong>
          <span className="count-pill">
            {list.length} {vehicle ? "輛" : "項"}
          </span>
        </div>
        <div className="search-input">
          <Search size={18} />
          <input
            placeholder={
              vehicle ? "搜尋車牌、型號或保管人" : "搜尋設備、位置或保管人"
            }
            aria-label="搜尋資產"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : list.length ? (
        <div className="asset-grid">
          {list.map((r, i) => (
            <Link
              className={
                "asset-card " + (vehicle ? "vehicle-card" : "equipment-card")
              }
              key={r.id}
              to={(vehicle ? "/vehicles/" : "/equipment/") + r.id}
            >
              <div className={"asset-illustration illustration-" + (i % 3)}>
                {vehicle ? (
                  <CarFront size={100} strokeWidth={1.1} />
                ) : (
                  <Telescope size={80} strokeWidth={1.2} />
                )}
                <span className="asset-label">
                  {vehicle
                    ? "FLEET / " + String(i + 1).padStart(2, "0")
                    : r.state || "列管"}
                </span>
                <span className="asset-arrow">
                  <ArrowRight size={18} />
                </span>
              </div>
              <div className="asset-card-body">
                <div className="asset-card-title">
                  <h2>{vehicle ? r.label : r.name}</h2>
                  <span className="available">
                    <i />
                    {r.state === "停用" ? "已停用" : "有效資產"}
                  </span>
                </div>
                <p>{vehicle ? r.model : r.label + " · " + r.brand}</p>
                <div className="asset-meta">
                  <span>
                    <Users size={15} />
                    {r.holder || r.owner || "未指定"}
                  </span>
                  <span>
                    {vehicle ? (
                      <>
                        <CarFront size={15} />
                        {r.passengers} 人座
                      </>
                    ) : (
                      <>
                        <MapPin size={15} />
                        {r.location}
                      </>
                    )}
                  </span>
                </div>
                <div className="asset-card-footer">
                  <span>查看完整資料</span>
                  <ChevronRight size={16} />
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <Empty
          title="找不到符合的資產"
          description="調整搜尋條件，或新增一筆資產資料。"
        />
      )}
      <AssetEditor open={open} close={() => setOpen(false)} kind={kind} />
    </>
  );
}
export function AssetDetail() {
  const { id } = useParams(),
    u = useUser(),
    navigate = useNavigate();
  const query = useQuery({
      queryKey: ["resources"],
      queryFn: () => api<Resource[]>("/resources"),
      refetchInterval: 5000,
    }),
    records = useQuery({
      queryKey: ["records", id],
      queryFn: () => api<any[]>("/resources/" + id + "/records"),
    });
  const [tab, setTab] = useState("basic"),
    [edit, setEdit] = useState(false),
    [remove, setRemove] = useState(false),
    [record, setRecord] = useState<any>(null),
    [deleteRecord, setDeleteRecord] = useState<any>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorBox error={query.error} />;
  const r = query.data?.find((r) => r.id === Number(id));
  if (!r)
    return (
      <Empty
        title="找不到這項資產"
        description="資產可能已刪除，請返回清單查看。"
      />
    );
  const vehicle = r.kind === "vehicle";
  const tabs = vehicle
    ? [
        ["basic", "基本資料"],
        ["insurance", "保險紀錄"],
        ["cost", "使用成本"],
        ["maintenance", "保養維護"],
        ["garage", "保養廠檔案"],
        ["manager", "管理人員"],
        ["usage", "使用紀錄"],
      ]
    : [
        ["basic", "基本資料"],
        ["usage", "預約紀錄"],
      ];
  async function del() {
    setBusy(true);
    try {
      await api("/resources/" + id, "DELETE");
      await invalidate();
      navigate(vehicle ? "/vehicles" : "/equipment");
    } catch (e) {
      setError((e as Error).message);
      setRemove(false);
    } finally {
      setBusy(false);
    }
  }
  const fields = vehicle
    ? [
        ["車牌", r.label],
        ["廠牌型號", r.model],
        ["車主", r.owner],
        ["保管人", r.holder],
        ["購買日期", r.purchase_date],
        ["購買金額", "NT$ " + money(r.amount)],
        ["乘客數", r.passengers + " 人"],
        ["追蹤器識別", r.client_id || "尚無定位映射"],
        ["聯絡人", r.contact_person],
        ["聯絡電話", r.phone],
        ["管理人", r.manager],
      ]
    : [
        ["設備編碼", r.label],
        ["設備名稱", r.name],
        ["工具位置編號", r.location],
        ["品牌廠商", r.brand],
        ["購買廠商", r.purchase_manufacturer],
        ["維修廠商", r.fix_manufacturer],
        ["保管人", r.holder],
        ["數量", r.quantity],
        ["用途", r.purpose],
        ["列管狀態", r.state],
        ["預估價值", "NT$ " + money(r.estimated_amount)],
        ["委外校正日期", r.fix_date],
        ["有效期限", r.valid_period],
      ];
  return (
    <>
      <Link className="back-link" to={vehicle ? "/vehicles" : "/equipment"}>
        <ArrowLeft size={16} />
        返回{vehicle ? "車輛" : "設備"}清單
      </Link>
      <PageHead
        eyebrow={vehicle ? "VEHICLE PROFILE" : "EQUIPMENT PROFILE"}
        title={vehicle ? r.label : r.name}
        description={vehicle ? r.model : r.label + " · " + r.location}
        action={
          can(
            u,
            vehicle ? "VehicleManagement" : "EquipmentManagement",
            "write",
          ) && (
            <div className="heading-actions">
              {can(
                u,
                vehicle ? "VehicleManagement" : "EquipmentManagement",
                "delete",
              ) && (
                <button className="button" onClick={() => setRemove(true)}>
                  <Trash2 size={16} />
                  刪除
                </button>
              )}
              <button className="button primary" onClick={() => setEdit(true)}>
                <Pencil size={16} />
                編輯資料
              </button>
            </div>
          )
        }
      />
      <ErrorBox error={error} />
      <section className="panel">
        <div className="list-tabs">
          {tabs.map(([v, l]) => (
            <button
              key={v}
              className={tab === v ? "active" : ""}
              onClick={() =>
                v === "usage" ? navigate("/bookings?resource=" + id) : setTab(v)
              }
            >
              {l}
            </button>
          ))}
        </div>
        {tab === "basic" ? (
          <div className="detail-content">
            <div className="asset-profile-head">
              <div className="profile-illustration">
                {vehicle ? (
                  <CarFront size={70} strokeWidth={1.2} />
                ) : (
                  <Telescope size={60} strokeWidth={1.3} />
                )}
              </div>
              <div>
                <span className="eyebrow">
                  {vehicle ? "VEHICLE" : "EQUIPMENT"} /{" "}
                  {String(r.id).padStart(3, "0")}
                </span>
                <h2>{vehicle ? r.model : r.name}</h2>
                <span className="status status-PENDING">
                  <i />
                  {r.state || "有效資產"}
                </span>
              </div>
            </div>
            <div className="summary-grid three">
              {fields.map(([name, value]) => (
                <div key={name}>
                  <small>{name}</small>
                  <strong>{value || "—"}</strong>
                </div>
              ))}
            </div>
            <h3 className="detail-section-title">
              {vehicle ? "隨車設備" : "設備配件"}
            </h3>
            <div className="tags">
              {(vehicle ? r.equipment || [] : r.accessories || []).map(
                (x: any, i: number) => (
                  <span key={i} className="resource-tag">
                    {typeof x === "string" ? x : x.name + " × " + x.quantity}
                  </span>
                ),
              )}
            </div>
            {"notes" in r && (
              <>
                <h3 className="detail-section-title">備註</h3>
                <p className="preserve-lines muted">{r.notes || "沒有備註"}</p>
              </>
            )}
            {vehicle &&
              [
                ["license_files", "行照附件"],
                ["vehicle_files", "車籍資料"],
                ["contract_files", "合約附件"],
              ].map(([key, label]) => (
                <div key={key}>
                  <h3 className="detail-section-title">{label}</h3>
                  <FileUpload
                    readOnly
                    value={r[key] || []}
                    onChange={() => {}}
                  />
                  {!r[key]?.length && <p className="muted">尚無附件</p>}
                </div>
              ))}
          </div>
        ) : (
          <div className="detail-content">
            <div className="section-title">
              <h2>{tabs.find((t) => t[0] === tab)?.[1]}</h2>
              {can(
                u,
                vehicle ? "VehicleManagement" : "EquipmentManagement",
                "write",
              ) && (
                <button
                  className="button compact"
                  onClick={() =>
                    setRecord({ category: tab, data: { attachments: [] } })
                  }
                >
                  <Plus size={16} />
                  新增紀錄
                </button>
              )}
            </div>
            <ErrorBox error={records.error} />
            {records.isPending ? (
              <Loading />
            ) : records.data?.filter((v) => v.category === tab).length ? (
              <div className="record-list">
                {records.data
                  .filter((v) => v.category === tab)
                  .map((rec) => (
                    <div className="record-card" key={rec.id}>
                      <div className="record-title">
                        <div className="record-icon">
                          {tab === "insurance" ? (
                            <ShieldCheck />
                          ) : tab === "cost" ? (
                            <Receipt />
                          ) : (
                            <Wrench />
                          )}
                        </div>
                        <div>
                          <h3>
                            {rec.company ||
                              rec.reason ||
                              rec.name ||
                              rec.type ||
                              "保養廠資料"}
                          </h3>
                          <small>
                            {rec.date ||
                              rec.expiry ||
                              rec.created_at?.slice(0, 10)}
                          </small>
                        </div>
                        {can(
                          u,
                          vehicle ? "VehicleManagement" : "EquipmentManagement",
                          "write",
                        ) && (
                          <div className="record-actions">
                            <button
                              className="icon-button"
                              aria-label={"編輯紀錄 " + rec.id}
                              onClick={() =>
                                setRecord({
                                  id: rec.id,
                                  category: tab,
                                  data: rec,
                                })
                              }
                            >
                              <Pencil size={17} />
                            </button>
                            {can(
                              u,
                              tab === "insurance" ? "Insurance" : "Cost",
                              "delete",
                            ) && (
                              <button
                                className="icon-button"
                                aria-label={"刪除紀錄 " + rec.id}
                                onClick={() => setDeleteRecord(rec)}
                              >
                                <Trash2 size={17} />
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                      {rec.expiry && <InsuranceStatus date={rec.expiry} />}
                      <div className="record-info">
                        {rec.amount !== undefined && (
                          <strong>NT$ {money(rec.amount)}</strong>
                        )}
                        {rec.phone && <span>聯絡電話：{rec.phone}</span>}
                        {rec.employee && (
                          <span>
                            業務：{rec.employee} {rec.employee_phone}
                          </span>
                        )}
                        {rec.roadside && <span>道路救援：{rec.roadside}</span>}
                      </div>
                      {"notes" in rec && (
                        <p className="preserve-lines muted">
                          {rec.notes || "無備註"}
                        </p>
                      )}
                      <FileUpload
                        value={rec.attachments || []}
                        onChange={() => {}}
                        readOnly
                      />
                      {tab === "insurance" &&
                        [
                          ["policy_files", "保單附件"],
                          ["claim_files", "理賠附件"],
                        ].map(([key, label]) => (
                          <div key={key}>
                            <h4>{label}</h4>
                            <FileUpload
                              readOnly
                              value={rec[key] || []}
                              onChange={() => {}}
                            />
                          </div>
                        ))}
                    </div>
                  ))}
              </div>
            ) : (
              <Empty
                title="尚無這類紀錄"
                description="新增紀錄後，附件與歷史資料都會保留在這輛車。"
              />
            )}
          </div>
        )}
      </section>
      <AssetEditor
        open={edit}
        close={() => setEdit(false)}
        kind={r.kind}
        resource={r}
      />
      <RecordEditor
        resourceId={r.id}
        record={record}
        close={() => setRecord(null)}
      />
      <Confirm
        open={remove}
        title="刪除資產？"
        description={`將停用 ${r.label}，新預約將無法選取此資產。歷史申請與附件仍保留。`}
        onClose={() => setRemove(false)}
        onConfirm={del}
        busy={busy}
      />
      <Confirm
        open={!!deleteRecord}
        title="刪除這筆紀錄？"
        description={`將刪除記錄 #${deleteRecord?.id}「${deleteRecord?.company || deleteRecord?.reason || deleteRecord?.name || deleteRecord?.type || "保養廠資料"}」。`}
        onClose={() => setDeleteRecord(null)}
        onConfirm={async () => {
          setBusy(true);
          try {
            await api("/records/" + deleteRecord.id, "DELETE");
            await invalidate();
            setDeleteRecord(null);
          } catch (e) {
            setError((e as Error).message);
            setDeleteRecord(null);
          } finally {
            setBusy(false);
          }
        }}
        busy={busy}
      />
    </>
  );
}
function InsuranceStatus({ date }: { date: string }) {
  const days = Math.round(
    (new Date(date + "T00:00:00+08:00").getTime() -
      new Date(localDate() + "T00:00:00+08:00").getTime()) /
      86400000,
  );
  return (
    <div className={"insurance-status " + (days <= 30 ? "due" : "")}>
      {days < 0
        ? "保險已過期 " + -days + " 天"
        : days === 0
          ? "保險今日到期"
          : days <= 7
            ? "保險即將到期 · 剩 " + days + " 天"
            : days <= 30
              ? "到期提醒 · 剩 " + days + " 天"
              : "保險有效 · 剩 " + days + " 天"}
      <small>預覽環境不發送外部通知</small>
    </div>
  );
}
function AssetEditor({
  open,
  close,
  kind,
  resource,
}: {
  open: boolean;
  close: () => void;
  kind: string;
  resource?: Resource;
}) {
  const navigate = useNavigate(),
    vehicle = kind === "vehicle";
  const [data, setData] = useState<any>({}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [accessory, setAccessory] = useState(""),
    [customEquipment, setCustomEquipment] = useState("");
  useEffect(() => {
    if (open) {
      setData(
        resource
          ? { ...resource }
          : {
              label: "",
              model: "",
              owner: "",
              purchase_date: localDate(),
              amount: "",
              passengers: 5,
              quantity: 1,
              state: "列管",
              equipment: [],
              accessories: [],
              license_files: [],
              vehicle_files: [],
              contract_files: [],
            },
      );
      setError("");
    }
  }, [open, resource?.id]);
  function set(k: string, v: any) {
    setData((d: any) => ({ ...d, [k]: v }));
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api<Resource>(
        "/resources" + (resource ? "/" + resource.id : ""),
        resource ? "PUT" : "POST",
        { kind, label: data.label, data },
      );
      await invalidate();
      close();
      if (!resource) navigate((vehicle ? "/vehicles/" : "/equipment/") + r.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const fields = vehicle
    ? [
        ["label", "車牌", "text", true],
        ["model", "廠牌型號", "text", true],
        ["owner", "車主", "text", true],
        ["holder", "保管人", "text", false],
        ["purchase_date", "購買日期", "date", true],
        ["amount", "購買金額", "number", true],
        ["passengers", "乘客數", "number", true],
        ["client_id", "追蹤器 client_id", "text", false],
        ["contact_person", "聯絡人", "text", false],
        ["phone", "聯絡電話", "text", false],
        ["manager", "管理人", "text", false],
      ]
    : [
        ["label", "設備編碼（可留空）", "text", false],
        ["name", "設備名稱", "text", true],
        ["location", "工具位置編號", "text", true],
        ["brand", "品牌廠商", "text", false],
        ["purchase_manufacturer", "購買廠商", "text", false],
        ["fix_manufacturer", "維修廠商", "text", false],
        ["holder", "保管人", "text", false],
        ["quantity", "數量", "number", false],
        ["purpose", "用途", "text", false],
        ["estimated_amount", "預估價值", "number", false],
        ["fix_date", "委外校正日期", "date", false],
        ["valid_period", "有效期限", "date", false],
      ];
  function addAccessory() {
    const name = accessory.trim();
    if (!name) return;
    const list = [...(data.accessories || [])];
    const index = list.findIndex((a: any) => a.name === name);
    if (index >= 0)
      list[index] = {
        ...list[index],
        quantity: Number(list[index].quantity) + 1,
      };
    else list.push({ name, quantity: 1 });
    set("accessories", list);
    setAccessory("");
  }
  return (
    <Modal
      open={open}
      title={(resource ? "編輯" : "新增") + (vehicle ? "車輛" : "設備")}
      onClose={() => !busy && close()}
      wide
    >
      <form onSubmit={submit}>
        <div className="fields-grid">
          {fields.map(([key, label, type, required]: any) => (
            <Field key={key} field={key} label={label} required={required}>
              <input
                type={type}
                min={type === "number" ? 0 : undefined}
                step={
                  ["amount", "estimated_amount"].includes(key)
                    ? "0.01"
                    : undefined
                }
                required={required}
                value={data[key] ?? ""}
                onChange={(e) => set(key, e.target.value)}
              />
            </Field>
          ))}
          {!vehicle && (
            <Field label="列管狀態">
              <select
                value={data.state || "列管"}
                onChange={(e) => set("state", e.target.value)}
              >
                <option>列管</option>
                <option>不列管</option>
                <option>停用</option>
              </select>
            </Field>
          )}
          <div className="span-2">
            {vehicle ? (
              <>
                <Field label="隨車設備">
                  <div className="purpose-grid">
                    {Array.from(
                      new Set([
                        "跨接電纜",
                        "汽車行動電源",
                        "電子設備",
                        "備胎",
                        ...(data.equipment || []),
                      ]),
                    ).map((name: any) => (
                      <label key={name}>
                        <input
                          type="checkbox"
                          checked={data.equipment?.includes(name) || false}
                          onChange={(e) =>
                            set(
                              "equipment",
                              e.target.checked
                                ? [...(data.equipment || []), name]
                                : data.equipment.filter(
                                    (x: string) => x !== name,
                                  ),
                            )
                          }
                        />
                        {name}
                      </label>
                    ))}
                  </div>
                </Field>
                <div className="inline-input">
                  <input
                    placeholder="自訂隨車設備"
                    value={customEquipment}
                    onChange={(e) => setCustomEquipment(e.target.value)}
                  />
                  <button
                    className="button compact"
                    type="button"
                    onClick={() => {
                      if (customEquipment.trim())
                        set(
                          "equipment",
                          Array.from(
                            new Set([
                              ...(data.equipment || []),
                              customEquipment.trim(),
                            ]),
                          ),
                        );
                      setCustomEquipment("");
                    }}
                  >
                    加入
                  </button>
                </div>
              </>
            ) : (
              <>
                <Field label="設備配件">
                  <div className="inline-input">
                    <input
                      list="accessories"
                      value={accessory}
                      onChange={(e) => setAccessory(e.target.value)}
                      placeholder="選擇或輸入配件名稱"
                    />
                    <datalist id="accessories">
                      {accessories.map((a) => (
                        <option key={a}>{a}</option>
                      ))}
                    </datalist>
                    <button
                      className="button compact"
                      type="button"
                      onClick={addAccessory}
                    >
                      <Plus size={16} />
                      加入
                    </button>
                  </div>
                </Field>
                {data.accessories?.map((a: any, i: number) => (
                  <div className="accessory-row" key={i}>
                    <Package size={17} />
                    <strong>{a.name}</strong>
                    <input
                      aria-label={a.name + "數量"}
                      type="number"
                      min={0}
                      value={a.quantity}
                      onChange={(e) => {
                        const count = Number(e.target.value);
                        set(
                          "accessories",
                          count <= 0
                            ? data.accessories.filter(
                                (_: any, j: number) => j !== i,
                              )
                            : data.accessories.map((x: any, j: number) =>
                                i === j ? { ...x, quantity: count } : x,
                              ),
                        );
                      }}
                    />
                    <button
                      className="icon-button"
                      type="button"
                      aria-label={"移除配件 " + a.name}
                      onClick={() =>
                        set(
                          "accessories",
                          data.accessories.filter(
                            (_: any, j: number) => j !== i,
                          ),
                        )
                      }
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </>
            )}
          </div>
          <div className="span-2">
            <Field label="備註">
              <textarea
                rows={3}
                value={data.notes || ""}
                onChange={(e) => set("notes", e.target.value)}
              />
            </Field>
          </div>
          {vehicle &&
            [
              ["license_files", "行照附件"],
              ["vehicle_files", "車籍資料"],
              ["contract_files", "合約附件"],
            ].map(([key, label]) => (
              <div className="span-2" key={key}>
                <Field label={label}>
                  <FileUpload
                    value={data[key] || []}
                    onChange={(v) => set(key, v)}
                  />
                </Field>
              </div>
            ))}
        </div>
        <ErrorBox error={error} />
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
            {busy ? "保存中…" : "儲存資料"}
            <Check size={16} />
          </button>
        </div>
      </form>
    </Modal>
  );
}
function RecordEditor({
  resourceId,
  record,
  close,
}: {
  resourceId: number;
  record: any;
  close: () => void;
}) {
  const [data, setData] = useState<any>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    if (record) {
      setData({ ...record.data });
      setError("");
    }
  }, [record]);
  const category = record?.category;
  const fields: any =
    category === "insurance"
      ? [
          ["company", "保險公司", "text", true],
          ["expiry", "有效期限", "date", true],
          ["phone", "公司電話", "text"],
          ["employee", "業務人員", "text"],
          ["employee_phone", "業務電話", "text"],
          ["roadside", "道路救援聯絡資訊", "text"],
        ]
      : category === "cost"
        ? [
            ["reason", "費用緣由", "text", true],
            ["amount", "金額", "number", true],
          ]
        : category === "maintenance"
          ? [["date", "紀錄日期", "date", true]]
          : category === "manager"
            ? [["name", "管理人員姓名", "text", true]]
            : [];
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api(
        record.id
          ? "/records/" + record.id
          : "/resources/" + resourceId + "/records",
        record.id ? "PUT" : "POST",
        { category, data },
      );
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
      open={!!record}
      title={(record?.id ? "編輯" : "新增") + "資產紀錄"}
      onClose={() => !busy && close()}
    >
      <form onSubmit={submit}>
        <div className="fields-grid">
          {["cost", "maintenance"].includes(category) && (
            <div className="span-2">
              <Field label="類型" required>
                <select
                  required
                  value={data.type || ""}
                  onChange={(e) => setData({ ...data, type: e.target.value })}
                >
                  <option value="">請選擇</option>
                  {(category === "cost"
                    ? ["保費", "保養", "維修"]
                    : ["驗車", "定期保養", "維修"]
                  ).map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </Field>
            </div>
          )}
          {fields.map(([key, label, type, required]: any) => (
            <Field key={key} field={key} label={label} required={required}>
              <input
                type={type}
                min={type === "number" ? 0 : undefined}
                step={type === "number" ? "0.01" : undefined}
                required={required}
                value={data[key] || ""}
                onChange={(e) => setData({ ...data, [key]: e.target.value })}
              />
            </Field>
          ))}
          <div className="span-2">
            <Field label="備註">
              <textarea
                rows={3}
                value={data.notes || ""}
                onChange={(e) => setData({ ...data, notes: e.target.value })}
              />
            </Field>
          </div>
          {category === "insurance" ? (
            <>
              {[
                ["policy_files", "保單附件"],
                ["claim_files", "理賠附件"],
              ].map(([key, label]) => (
                <div className="span-2" key={key}>
                  <Field label={label}>
                    <FileUpload
                      value={data[key] || []}
                      onChange={(v) => setData({ ...data, [key]: v })}
                    />
                  </Field>
                </div>
              ))}
              {data.attachments?.length > 0 && (
                <div className="span-2">
                  <Field label="舊版未分類附件">
                    <FileUpload
                      value={data.attachments}
                      onChange={(v) => setData({ ...data, attachments: v })}
                    />
                  </Field>
                </div>
              )}
            </>
          ) : (
            <div className="span-2">
              <Field label="附件">
                <FileUpload
                  value={data.attachments || []}
                  onChange={(v) => setData({ ...data, attachments: v })}
                />
              </Field>
            </div>
          )}
        </div>
        <ErrorBox error={error} />
        <div className="actions">
          <button
            type="button"
            className="button"
            onClick={close}
            disabled={busy}
          >
            取消
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? "儲存中…" : "儲存紀錄"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
