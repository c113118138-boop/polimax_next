import { useEffect, useState } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  MapPin,
  Plus,
  Search,
  Trash2,
  Pencil,
  CarFront,
  Users,
  CalendarDays,
  History,
  ChevronDown,
} from "lucide-react";
import {
  api,
  Booking,
  Resource,
  dateTime,
  localDate,
  localInput,
  states,
  nextStates,
  kindNames,
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
  Status,
} from "./ui";
import { useUser } from "./App";
import { StageForm, StageView } from "./Stages";
import { can, bookingDoc, Scope } from "./Access";
const purposeOptions = [
  "廠內",
  "廠外施工",
  "廠外出差",
  "量測",
  "材料送貨",
  "載回工件",
  "送回工件",
  "動平衡（去）",
  "動平衡（回）",
  "加工（去）",
  "加工（回）",
  "五金採買",
  "廠務",
  "工件備品採購",
  "每月消耗品採購",
  "其他",
  "其他加工",
];
const requirements = [
  "工案",
  "材料送貨",
  "新開發案",
  "客戶拜訪",
  "成交案回訪",
  "參展",
  "其他",
];
const equipmentReasons = [
  "開案",
  "成案（施工前量測）",
  "成案（完工量測）",
  "成案（服務回訪）",
  "儀器設備保養／校正",
  "儀器設備維修",
  "其它",
];
const detailName: Record<string, string> = {
  工案: "工案編號／名稱",
  材料送貨: "業主名稱",
  新開發案: "開發案編號／名稱",
  客戶拜訪: "客戶名稱",
  成交案回訪: "工案編號／名稱",
  參展: "展覽名稱",
  其他: "備註",
  "儀器設備保養／校正": "保養／校正廠商",
  儀器設備維修: "維修廠商",
  其它: "地點與說明",
};
const schema = z.object({
  title: z.string().trim().min(1, "請填寫申請緣由"),
  applicant: z.string(),
  application_date: z.string(),
  total_people: z.coerce.number().min(1, "使用人數至少為 1"),
  reason: z.string().min(1, "請選擇使用需求"),
  details: z.array(
    z.object({
      name: z.string(),
      city: z.string(),
      district: z.string(),
      leader: z.string().optional(),
      sales: z.array(z.string()).optional(),
      notes: z.string().optional(),
      notes2: z.string().optional(),
    }),
  ),
  employees: z.array(z.string()),
  slots: z
    .array(
      z.object({
        resource_id: z.coerce.number().min(1, "請選擇資源"),
        start: z.string().min(1, "請填寫開始時間"),
        end: z.string().min(1, "請填寫結束時間"),
        detail_index: z.coerce.number().default(0),
      }),
    )
    .min(1, "請新增至少一個時段"),
  purposes: z.array(z.string()),
  other_purpose: z.string(),
  other_processing: z.string(),
  notes: z.string(),
  reason_drafts: z.record(z.any()).default({}),
});
type Values = z.infer<typeof schema>;
export function BookingForm() {
  const { kind: routeKind, id } = useParams(),
    navigate = useNavigate(),
    location = useLocation(),
    u = useUser();
  const [step, setStep] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const source = useQuery({
      queryKey: ["booking", id],
      queryFn: () => api<Booking>("/bookings/" + id),
      enabled: !!id,
    }),
    resources = useQuery({
      queryKey: ["resources"],
      queryFn: () => api<Resource[]>("/resources"),
    }),
    options = useQuery({
      queryKey: ["options"],
      queryFn: () => api("/options"),
    });
  const kind = source.data?.kind || routeKind || "A",
    isRoom = kind === "D",
    isEquipment = kind === "E",
    selection = location.state as {
      start?: string;
      end?: string;
      resource?: number;
    } | null;
  const initial: Values = {
    applicant: u.name,
    application_date: localDate(),
    total_people: 1,
    title: kind === "D" ? "作業區租用" : "",
    reason: kind === "D" ? "作業區租用" : kind === "E" ? "開案" : "工案",
    details: [
      { name: "", city: "", district: "", leader: "", sales: [u.name], notes: "" },
    ],
    employees: [u.name],
    slots: [
      {
        resource_id: kind === "A" ? selection?.resource || 0 : 0,
        start: selection?.start
          ? localInput(selection.start)
          : localDate() + "T09:00",
        end: selection?.end
          ? localInput(selection.end)
          : localDate() + "T17:00",
        detail_index: 0,
      },
    ],
    purposes: [],
    other_purpose: "",
    other_processing: "",
    notes: "",
    reason_drafts: {},
  };
  const {
    register,
    control,
    watch,
    setValue,
    reset,
    trigger,
    handleSubmit,
    formState: { errors, isDirty },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: initial,
  });
  const details = useFieldArray({ control, name: "details" }),
    slots = useFieldArray({ control, name: "slots" });
  const values = watch(),
    reason = watch("reason"),
    rs = resources.data || [],
    allowed = rs.filter(
      (r) =>
        r.kind === (isRoom ? "room" : isEquipment ? "equipment" : "vehicle") &&
        r.state !== "停用",
    );
  useEffect(() => {
    if (source.data)
      reset({
        ...initial,
        ...source.data.content,
        slots: source.data.slots.map((s, i) => ({
          ...s,
          start: localInput(s.start),
          end: localInput(s.end),
          detail_index: i,
        })),
      });
  }, [source.data]);
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);
  function cancel() {
    if (!isDirty || window.confirm("尚有未送出的填寫內容，確定離開嗎？"))
      navigate(id ? "/bookings/" + id : "/");
  }
  async function next() {
    setError("");
    let fields: any =
      step === 0
        ? ["title", "total_people"]
        : step === 1
          ? ["reason"]
          : step === 2
            ? ["slots"]
            : [];
    if (!(await trigger(fields))) return;
    if (
      step === 1 &&
      !isRoom &&
      values.details.some(
        (d) =>
          (reason !== "材料送貨" && !d.name.trim()) ||
          (!isEquipment && !d.city),
      )
    ) {
      setError("請填寫每筆明細的內容與縣市。");
      return;
    }
    if (step === 2) {
      if (!isRoom && !values.employees.length) {
        setError("請選擇至少一位使用人員。");
        return;
      }
      for (const s of values.slots) {
        if (s.start > s.end || (kind !== "A" && s.start === s.end)) {
          setError("請檢查開始與結束時間。");
          return;
        }
      }
      if (
        kind === "A" &&
        values.details.length !== 1 &&
        values.details.length !== values.slots.length
      ) {
        setError("請使用一筆明細對應多時段，或相同數量的明細與時段。");
        return;
      }
    }
    if (
      step === 3 &&
      ((values.purposes.includes("其他") && !values.other_purpose.trim()) ||
        (values.purposes.includes("其他加工") &&
          !values.other_processing.trim()))
    ) {
      setError("請填寫已勾選的其他用途或加工說明。");
      return;
    }
    setStep((s) => Math.min(4, s + 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  async function submit(data: Values) {
    data.employees = Array.from(new Set(data.employees.map((name) => name.trim()).filter(Boolean)));
    data.details = data.details.map((detail) => ({ ...detail, sales: Array.from(new Set((detail.sales || []).map((name) => name.trim()).filter(Boolean))) }));
    setBusy(true);
    setError("");
    try {
      const result = await api<Booking>(
        "/bookings" + (id ? "/" + id : ""),
        id ? "PUT" : "POST",
        { kind, content: data, revision: source.data?.revision },
      );
      await invalidate();
      reset(data);
      navigate("/bookings/" + result.id, { state: { saved: true } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!can(u, bookingDoc(kind), id ? "write" : "create"))
    return <ErrorBox error="權限不足：目前身分沒有新增或編輯權限。" />;
  if (id && source.isPending) return <Loading />;
  if (source.error) return <ErrorBox error={source.error} />;
  if (!["A", "D", "E"].includes(kind))
    return <ErrorBox error="不存在的表單類型" />;
  const steps = [
    "基本資料",
    "使用需求",
    isRoom ? "空間與時段" : "人員與時段",
    "用途與補充",
    "確認送出",
  ];
  return (
    <Scope doc={bookingDoc(kind)}>
      <button className="back-link" onClick={cancel}>
        <ArrowLeft size={16} />
        返回{id ? "申請詳情" : "預約日曆"}
      </button>
      <PageHead
        eyebrow={id ? "EDIT RESERVATION" : "NEW RESERVATION"}
        title={(id ? "編輯" : "新增") + kindNames[kind]}
        description="把需求填清楚，讓每一次使用都有完整的安排。"
        action={
          <span className="pill">
            {id ? source.data?.id : "新申請"} · {kind} 類表單
          </span>
        }
      />
      <div className="form-layout">
        <div className="form-main">
          <div className="steps">
            {steps.map((label, i) => (
              <div
                className={
                  "step " +
                  (i === step ? "current" : i < step ? "completed" : "")
                }
                key={label}
              >
                <span>{i < step ? <Check size={15} /> : i + 1}</span>
                <strong>{label}</strong>
                {i < 4 && <div />}
              </div>
            ))}
          </div>
          <form
            onSubmit={handleSubmit(submit, () =>
              setError("部分必要欄位未填寫，請返回前面的步驟檢查。"),
            )}
            className="panel form-panel"
          >
            <div className="form-section-head">
              <span className="section-number">0{step + 1}</span>
              <div>
                <h2>{steps[step]}</h2>
                <p>
                  {
                    [
                      "確認申請人資訊，說明這次的使用目的。",
                      "依使用需求填寫對應明細，可新增多筆。",
                      "安排資源與時段，可新增跨日或多筆預約。",
                      "補充用途與其他需要交代的資訊。",
                      "送出前，再確認一下這次的安排。",
                    ][step]
                  }
                </p>
              </div>
            </div>
            {step === 0 && (
              <div className="fields-grid">
                <Field label="申請日期">
                  <input {...register("application_date")} readOnly />
                </Field>
                <Field label="申請人">
                  <input {...register("applicant")} readOnly />
                </Field>
                <div className="span-2">
                  <Field label="申請緣由" required hint={errors.title?.message}>
                    <input
                      {...register("title")}
                      placeholder="例如：新竹廠區設備量測與客戶需求確認"
                    />
                  </Field>
                </div>
                {!isRoom && (
                  <Field
                    label="總使用人數"
                    required
                    hint={errors.total_people?.message}
                  >
                    <input
                      type="number"
                      min={1}
                      {...register("total_people")}
                    />
                  </Field>
                )}
                <div className="span-2 info-note">
                  <ShieldNote />
                  申請人依登入身分帶入，送出後由系統產生正式編號。
                </div>
              </div>
            )}
            {step === 1 && (
              <>
                {isRoom ? (
                  <>
                    <div className="room-intro">
                      <div className="resource-icon type-D">
                        <MapPin size={30} />
                      </div>
                      <h3>請先填寫作業區使用需求</h3>
                      <p>可複選用途，下一步再選擇實際空間與使用時段。</p>
                    </div>
                    <Field label="使用需求（可複選）" required>
                      <div className="purpose-grid">
                        {purposeOptions.map((purpose) => (
                          <label key={purpose}>
                            <input type="checkbox" value={purpose} {...register("purposes")} />
                            {purpose}
                          </label>
                        ))}
                      </div>
                    </Field>
                    <Field label="其他需求說明">
                      <textarea rows={3} {...register("other_purpose")} placeholder="若選擇其他，請補充說明作業內容" />
                    </Field>
                  </>
                ) : (
                  <>
                    <Field label="使用需求" required>
                      <select
                        {...register("reason", {
                          onChange: (e) => {
                            const next = e.target.value;
                            setValue("reason_drafts", {
                              ...values.reason_drafts,
                              [reason]: {
                                details: values.details,
                                slots: values.slots,
                              },
                            });
                            details.replace(
                              values.reason_drafts[next]?.details || [
                                {
                                  name: "",
                                  city: "",
                                  district: "",
                                  leader: "",
                                  sales: [u.name],
                                  notes: "",
                                  notes2: "",
                                },
                              ],
                            );
                            slots.replace(
                              values.reason_drafts[next]?.slots || values.slots,
                            );
                          },
                        })}
                      >
                        {(isEquipment ? equipmentReasons : requirements).map(
                          (r) => (
                            <option key={r}>{r}</option>
                          ),
                        )}
                      </select>
                    </Field>
                    <div className="repeat-heading">
                      <h3>
                        需求明細 <span>{details.fields.length} 筆</span>
                      </h3>
                      <button
                        type="button"
                        className="button compact"
                        onClick={() =>
                          details.append({
                            name: "",
                            city: "",
                            district: "",
                            leader: "",
                            sales: [u.name],
                            notes: "",
                          })
                        }
                      >
                        <Plus size={15} />
                        新增明細
                      </button>
                    </div>
                    {details.fields.map((d, i) => (
                      <div className="repeat-card" key={d.id}>
                        <div className="repeat-label">
                          <span>明細 {String(i + 1).padStart(2, "0")}</span>
                          <button
                            type="button"
                            className="icon-button"
                            aria-label={"移除明細 " + (i + 1)}
                            disabled={details.fields.length === 1}
                            onClick={() => details.remove(i)}
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                        <div className="fields-grid">
                          <div className="span-2">
                            <Field
                              label={detailName[reason] || "工案編號／名稱"}
                              required={reason !== "材料送貨"}
                            >
                              <input
                                {...register(`details.${i}.name`)}
                                placeholder={
                                  "請輸入" + (detailName[reason] || "案件內容")
                                }
                              />
                            </Field>
                          </div>
                          <Field label="縣市" required={!isEquipment}>
                            <select
                              {...register(`details.${i}.city`, {
                                onChange: () =>
                                  setValue(`details.${i}.district`, ""),
                              })}
                            >
                              <option value="">選擇縣市</option>
                              {Object.keys(options.data?.cities || {}).map(
                                (c) => (
                                  <option key={c}>{c}</option>
                                ),
                              )}
                            </select>
                          </Field>
                          <Field label="行政區">
                            <select
                              {...register(`details.${i}.district`)}
                              disabled={!values.details[i]?.city}
                            >
                              <option value="">選擇行政區</option>
                              {(
                                options.data?.cities[values.details[i]?.city] ||
                                []
                              ).map((c: string) => (
                                <option key={c}>{c}</option>
                              ))}
                            </select>
                          </Field>
                          {(["工案", "新開發案", "成交案回訪"].includes(
                            reason,
                          ) ||
                            (isEquipment &&
                              [
                                "開案",
                                "成案（施工前量測）",
                                "成案（完工量測）",
                                "成案（服務回訪）",
                              ].includes(reason))) && (
                            <Field label="工程組長">
                              <input {...register(`details.${i}.leader`)} placeholder="請填寫工程組長姓名" />
                            </Field>
                          )}
                          {([
                            "工案",
                            "材料送貨",
                            "新開發案",
                            "成交案回訪",
                          ].includes(reason) ||
                            (isEquipment &&
                              [
                                "開案",
                                "成案（施工前量測）",
                                "成案（完工量測）",
                                "成案（服務回訪）",
                              ].includes(reason))) && (
                            <Field label="業務人員">
                              <input readOnly value={values.details[i]?.sales?.[0] || u.name} />
                              <input aria-label="第二位業務人員" placeholder="第二位業務人員姓名（選填）"
                                value={values.details[i]?.sales?.[1] || ""}
                                onChange={(e) => setValue(`details.${i}.sales`, [values.details[i]?.sales?.[0] || u.name, ...(e.target.value ? [e.target.value] : [])], { shouldDirty: true })} />
                            </Field>
                          )}
                          <div className="span-2">
                            <Field label="備註">
                              <textarea
                                rows={2}
                                {...register(`details.${i}.notes`)}
                                placeholder="補充此筆需求的說明"
                              />
                            </Field>
                            {isEquipment && reason === "其它" && (
                              <Field label="第二備註">
                                <textarea
                                  {...register(`details.${i}.notes2`)}
                                />
                              </Field>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                    <small className="muted">
                      人員預設帶入目前登入者；如有第二位人員，請手動填寫。
                    </small>
                  </>
                )}
              </>
            )}
            {step === 2 && (
              <>
                {!isRoom && (
                  <div className="fields-grid">
                    <Field label="第一位借用人員" required>
                      <input readOnly value={values.employees[0] || u.name} />
                    </Field>
                    <Field label="第二位借用人員（選填）">
                      <input placeholder="請填寫第二位借用人員姓名"
                        value={values.employees[1] || ""}
                        onChange={(e) => {
                          const people = [values.employees[0] || u.name, ...(e.target.value ? [e.target.value] : [])];
                          setValue("employees", people, { shouldDirty: true });
                          setValue("total_people", people.length, { shouldDirty: true });
                        }} />
                    </Field>
                  </div>
                )}
                <div className="repeat-heading">
                  <h3>
                    {isRoom ? "空間" : "資源"}與時段{" "}
                    <span>{slots.fields.length} 筆</span>
                  </h3>
                  <button
                    type="button"
                    className="button compact"
                    onClick={() =>
                      slots.append({
                        resource_id: 0,
                        start: values.slots[0]?.start || localDate() + "T09:00",
                        end: values.slots[0]?.end || localDate() + "T17:00",
                        detail_index: 0,
                      })
                    }
                  >
                    <Plus size={15} />
                    新增時段
                  </button>
                </div>
                {slots.fields.map((s, i) => (
                  <div className="repeat-card" key={s.id}>
                    <div className="repeat-label">
                      <span>時段 {String(i + 1).padStart(2, "0")}</span>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={"移除時段 " + (i + 1)}
                        disabled={slots.fields.length === 1}
                        onClick={() => slots.remove(i)}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                    <div className="fields-grid">
                      <div className="span-2">
                        <Field
                          label={
                            isRoom
                              ? "使用空間"
                              : isEquipment
                                ? "儀器設備"
                                : "公務車牌"
                          }
                          required
                          hint={errors.slots?.[i]?.resource_id?.message}
                        >
                          <select {...register(`slots.${i}.resource_id`)}>
                            <option value={0}>
                              選擇
                              {isRoom ? "空間" : isEquipment ? "設備" : "車輛"}
                            </option>
                            {allowed.map((r) => (
                              <option key={r.id} value={r.id}>
                                {isEquipment
                                  ? r.name || r.label
                                  : r.label + (r.model ? " · " + r.model : "")}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </div>
                      <Field
                        label="借用開始"
                        required
                        hint={errors.slots?.[i]?.start?.message}
                      >
                        <input
                          type="datetime-local"
                          step="1"
                          {...register(`slots.${i}.start`)}
                        />
                      </Field>
                      <Field
                        label="借用結束"
                        required
                        hint={errors.slots?.[i]?.end?.message}
                      >
                        <input
                          type="datetime-local"
                          step="1"
                          {...register(`slots.${i}.end`)}
                        />
                      </Field>
                      {!isRoom && (
                        <div className="span-2 muted small-text">
                          對應明細：
                          {values.details.length === 1
                            ? values.details[0]?.name
                            : values.details[i]?.name ||
                              "請保持明細與時段數量一致"}
                        </div>
                      )}
                      {isEquipment &&
                        Number(values.slots[i]?.resource_id) > 0 && (
                          <div className="span-2 info-note">
                            位置：
                            {
                              rs.find(
                                (r) =>
                                  r.id === Number(values.slots[i].resource_id),
                              )?.location
                            }{" "}
                            · 保管人：
                            {
                              rs.find(
                                (r) =>
                                  r.id === Number(values.slots[i].resource_id),
                              )?.holder
                            }
                          </div>
                        )}
                    </div>
                  </div>
                ))}
                <div className="info-note">
                  <Clock3 size={17} />
                  同一資源首尾相接也算衝突，例如 09:00–10:00 與 10:00–11:00
                  無法重複預約。
                </div>
              </>
            )}
            {step === 3 && (
              <>
                {kind === "A" && (
                  <>
                    <Field label="用途檢查（可複選）">
                      <div className="purpose-grid">
                        {purposeOptions.map((p) => (
                          <label key={p}>
                            <input
                              type="checkbox"
                              value={p}
                              {...register("purposes")}
                            />
                            {p}
                          </label>
                        ))}
                      </div>
                    </Field>
                    {values.purposes.includes("其他") && (
                      <Field label="其他用途說明" required>
                        <input {...register("other_purpose")} />
                      </Field>
                    )}
                    {values.purposes.includes("其他加工") && (
                      <Field label="其他加工說明" required>
                        <input {...register("other_processing")} />
                      </Field>
                    )}
                  </>
                )}
                <Field label="補充資訊">
                  <textarea
                    rows={6}
                    {...register("notes")}
                    placeholder="例如：攜帶設備、工作注意事項或其他補充資訊"
                  />
                </Field>
              </>
            )}
            {step === 4 && (
              <>
                <div className="review-title">
                  <CheckCircle2 size={26} />
                  <div>
                    <h3>{values.title}</h3>
                    <p>
                      {kindNames[kind]} · {values.applicant} ·{" "}
                      {values.application_date}
                    </p>
                  </div>
                </div>
                <div className="summary-grid">
                  <div>
                    <small>使用需求</small>
                    <strong>{values.reason}</strong>
                  </div>
                  <div>
                    <small>使用人員</small>
                    <strong>
                      {values.employees.length
                        ? values.employees.join("、")
                        : "尚未填寫"}
                    </strong>
                  </div>
                </div>
                {values.details
                  .filter((d) => d.name)
                  .map((d, i) => (
                    <div className="review-detail" key={i}>
                      <span>明細 {i + 1}</span>
                      <strong>{d.name}</strong>
                      <small>
                        {d.city} {d.district}
                      </small>
                    </div>
                  ))}
                {values.slots.map((s, i) => (
                  <div className="slot-summary" key={i}>
                    <strong>
                      {rs.find((r) => r.id === Number(s.resource_id))?.label ||
                        "未選資源"}
                    </strong>
                    <span>
                      {dateTime(s.start)} → {dateTime(s.end)}
                    </span>
                  </div>
                ))}
                {values.purposes.length > 0 && (
                  <p className="muted">用途：{values.purposes.join("、")}</p>
                )}
                {values.notes && (
                  <p className="preserve-lines">{values.notes}</p>
                )}
                <div className="info-note">
                  送出時會再次檢查資源衝突。成功後可在日曆與借用紀錄中查看。
                </div>
              </>
            )}
            <ErrorBox error={error || resources.error || options.error} />
            <div className="form-actions">
              <button
                type="button"
                className="button"
                onClick={() => (step ? setStep((s) => s - 1) : cancel())}
                disabled={busy}
              >
                {step ? (
                  <>
                    <ArrowLeft size={16} />
                    上一步
                  </>
                ) : (
                  "取消"
                )}
              </button>
              <span className="muted small-text">步驟 {step + 1} / 5</span>
              {step < 4 ? (
                <button
                  key="next"
                  type="button"
                  className="button primary"
                  onClick={next}
                >
                  下一步
                  <ArrowRight size={16} />
                </button>
              ) : (
                <button
                  key="submit"
                  type="submit"
                  className="button primary"
                  disabled={
                    busy ||
                    (!id &&
                      ["A", "E"].includes(kind) &&
                      !can(u, bookingDoc(kind), "submit"))
                  }
                >
                  {busy
                    ? "正在保存…"
                    : !id && !can(u, bookingDoc(kind), "submit") && kind !== "D"
                      ? "權限不足：submit"
                      : id
                        ? "儲存變更"
                        : "確認送出"}
                  <Check size={17} />
                </button>
              )}
            </div>
          </form>
        </div>
        <aside className="form-aside">
          <div className="panel summary-panel">
            <span className="eyebrow">RESERVATION SUMMARY</span>
            <h3>這次的預約</h3>
            <div className={"resource-icon type-" + kind}>
              {kind === "A" ? (
                <CarFront size={24} />
              ) : kind === "D" ? (
                <MapPin size={24} />
              ) : (
                <FileText size={24} />
              )}
            </div>
            <strong>{kindNames[kind]}</strong>
            <div className="summary-item">
              <Users size={16} />
              <span>{values.applicant}</span>
            </div>
            <div className="summary-item">
              <CalendarDays size={16} />
              <span>{values.application_date}</span>
            </div>
            <hr />
            {values.slots.map((s, i) => (
              <div className="aside-slot" key={i}>
                <strong>
                  {rs.find((r) => r.id === Number(s.resource_id))?.label ||
                    "尚未選擇資源"}
                </strong>
                <small>{s.start.replace("T", " ")}</small>
                <small>至 {s.end.replace("T", " ")}</small>
              </div>
            ))}
          </div>
          <div className="tip-card">
            <h3>填寫小提醒</h3>
            <p>
              切換步驟會保留填寫內容。標示 *
              的欄位為必填，送出失敗時可以修改後重試。
            </p>
          </div>
        </aside>
      </div>
    </Scope>
  );
}
function ShieldNote() {
  return <CheckCircle2 size={17} />;
}

export function BookingList({ onCreate }: { onCreate: () => void }) {
  const u = useUser(),
    navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const historyMode = searchParams.has("history");
  const [reasonFilter, setReasonFilter] = useState(""),
    [placeFilter, setPlaceFilter] = useState(""),
    [personFilter, setPersonFilter] = useState(""),
    [plateFilter, setPlateFilter] = useState("");
  useEffect(() => {
    setStatus(historyMode ? "RETURN_ARRIVED" : "all");
    setKind(historyMode ? "A" : "all");
  }, [historyMode]);
  const [search, setSearch] = useState(""),
    [kind, setKind] = useState("all"),
    [status, setStatus] = useState(
      searchParams.get("history") ? "RETURN_ARRIVED" : "all",
    ),
    [from, setFrom] = useState(""),
    [to, setTo] = useState(""),
    [dateField, setDateField] = useState("start");
  const bookings = useQuery({
      queryKey: ["bookings"],
      queryFn: () => api<Booking[]>("/bookings"),
    }),
    resources = useQuery({
      queryKey: ["resources"],
      queryFn: () => api<Resource[]>("/resources"),
    });
  const rs = resources.data || [];
  const results = (bookings.data || []).filter((b) => {
    if (historyMode && (b.kind !== "A" || b.status !== "RETURN_ARRIVED"))
      return false;
    if (
      reasonFilter &&
      (reasonFilter === "其他"
        ? requirements.slice(0, 6).includes(b.content.reason)
        : b.content.reason !== reasonFilter)
    )
      return false;
    if (
      placeFilter &&
      !(b.content.details || []).some((d: any) =>
        [d.city, d.district]
          .join("")
          .toLowerCase()
          .includes(placeFilter.toLowerCase()),
      )
    )
      return false;
    if (
      personFilter &&
      ![
        b.content.applicant,
        ...(b.content.employees || []),
        ...(b.content.details || []).flatMap((d: any) => d.sales || []),
      ]
        .join(" ")
        .toLowerCase()
        .includes(personFilter.toLowerCase())
    )
      return false;
    if (
      plateFilter &&
      !b.slots.some((s) => String(s.resource_id) === plateFilter)
    )
      return false;
    if (
      (kind !== "all" && b.kind !== kind) ||
      (status !== "all" && b.status !== status)
    )
      return false;
    if (
      searchParams.get("resource") &&
      !b.slots.some(
        (s) => s.resource_id === Number(searchParams.get("resource")),
      )
    )
      return false;
    const dates =
      dateField === "created"
        ? [b.created_at]
        : b.slots.map((s) => (dateField === "end" ? s.end : s.start));
    if (
      (from || to) &&
      !dates.some(
        (d) =>
          (!from || localDate(new Date(d)) >= from) &&
          (!to || localDate(new Date(d)) <= to),
      )
    )
      return false;
    return [
      b.id,
      b.content.title,
      b.content.applicant,
      b.content.reason,
      ...(b.content.employees || []),
      ...(b.content.details || []).map(
        (d: any) => d.name + " " + d.city + " " + d.district,
      ),
      ...b.slots.map((s) => rs.find((r) => r.id === s.resource_id)?.label),
    ]
      .join(" ")
      .toLowerCase()
      .includes(search.toLowerCase());
  });
  return (
    <>
      <PageHead
        eyebrow="RESERVATIONS & RECORDS"
        title={historyMode ? "車輛使用歷史" : "借用紀錄"}
        description="每一次預約與使用，都有清楚的來龍去脈。"
        action={
          (can(u, "Lending_form", "create") || can(u, "Room_form", "create") || can(u, "Equipment_form", "create")) && (
            <button
              className="button primary"
              onClick={onCreate}
            >
              <Plus size={17} />
              新增預約
            </button>
          )
        }
      />
      <section className="panel">
        <div className="list-tabs">
          {[
            ["all", "全部預約"],
            ["A", "車輛借用"],
            ["D", "作業區"],
            ["E", "儀器借用"],
          ].map(([v, label]) => (
            <button
              key={v}
              className={kind === v ? "active" : ""}
              onClick={() => setKind(v)}
            >
              {label}
              {v === "all" && (
                <span className="count-pill">{bookings.data?.length || 0}</span>
              )}
            </button>
          ))}
        </div>
        <div className="list-filters">
          <select
            aria-label="緣由篩選"
            value={reasonFilter}
            onChange={(e) => setReasonFilter(e.target.value)}
          >
            <option value="">全部緣由</option>
            {requirements.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
          <select
            aria-label="車牌篩選"
            value={plateFilter}
            onChange={(e) => setPlateFilter(e.target.value)}
          >
            <option value="">全部車牌</option>
            {rs
              .filter((r) => r.kind === "vehicle")
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
          </select>
          <input
            aria-label="地點篩選"
            placeholder="縣市／行政區"
            value={placeFilter}
            onChange={(e) => setPlaceFilter(e.target.value)}
          />
          <input
            aria-label="人員篩選"
            placeholder="申請人／使用人員／業務"
            value={personFilter}
            onChange={(e) => setPersonFilter(e.target.value)}
          />
          <div className="search-input">
            <Search size={17} />
            <input
              aria-label="搜尋借用紀錄"
              placeholder="搜尋編號、車牌、申請人或緣由"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            aria-label="流程狀態"
            disabled={historyMode}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">所有狀態</option>
            {Object.entries(states).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <select
            aria-label="日期篩選欄位"
            value={dateField}
            onChange={(e) => setDateField(e.target.value)}
          >
            <option value="start">開始時間</option>
            <option value="end">結束時間</option>
            <option value="created">申請時間</option>
          </select>
          <input
            aria-label="篩選起日"
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <span>—</span>
          <input
            aria-label="篩選迄日"
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
          {(search ||
            status !== "all" ||
            from ||
            to ||
            reasonFilter ||
            placeFilter ||
            personFilter ||
            plateFilter) && (
            <button
              className="text-link"
              onClick={() => {
                setSearch("");
                setStatus(historyMode ? "RETURN_ARRIVED" : "all");
                setReasonFilter("");
                setPlaceFilter("");
                setPersonFilter("");
                setPlateFilter("");
                setFrom("");
                setTo("");
              }}
            >
              清除
            </button>
          )}
        </div>
        <ErrorBox error={bookings.error || resources.error} />
        {bookings.isPending ? (
          <Loading />
        ) : results.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>申請 / 緣由</th>
                  <th>使用資源</th>
                  <th>預約時間</th>
                  <th>申請人</th>
                  <th>狀態</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {results.map((b) => (
                  <tr key={b.id}>
                    <td>
                      <Link className="table-title" to={"/bookings/" + b.id}>
                        {b.content.title}
                      </Link>
                      <small className="mono">
                        {b.id} · {kindNames[b.kind]}
                      </small>
                    </td>
                    <td>
                      {b.slots.map((s, i) => (
                        <span className="resource-tag" key={i}>
                          {rs.find((r) => r.id === s.resource_id)?.label ||
                            b.content.resource_snapshots?.find(
                              (r: any) => r.id === s.resource_id,
                            )?.label ||
                            "歷史資源 #" + s.resource_id}
                        </span>
                      ))}
                    </td>
                    <td>
                      {b.slots.map((s, i) => (
                        <div className="time-range" key={i}>
                          <span>{dateTime(s.start)}</span>
                          <small>至 {dateTime(s.end)}</small>
                        </div>
                      ))}
                    </td>
                    <td>
                      <div className="person-cell">
                        <span className="avatar tiny">
                          {b.content.applicant?.slice(0, 1)}
                        </span>
                        {b.content.applicant}
                      </div>
                    </td>
                    <td>
                      <Status status={b.status} />
                    </td>
                    <td>
                      <Link
                        className="icon-button"
                        aria-label={"查看 " + b.id}
                        to={"/bookings/" + b.id}
                      >
                        <ChevronRight size={18} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="沒有符合條件的預約"
            description="調整搜尋條件，或建立一筆新的預約。"
          />
        )}
        <div className="table-footer">
          顯示 {results.length} 張申請，共 {bookings.data?.length || 0} 張
          <span>同一申請的多個資源合併顯示</span>
        </div>
      </section>
    </>
  );
}

export function BookingDetail() {
  const { id } = useParams(),
    navigate = useNavigate(),
    location = useLocation(),
    u = useUser();
  const query = useQuery({
      queryKey: ["booking", id],
      queryFn: () => api<Booking>("/bookings/" + id),
    }),
    resources = useQuery({
      queryKey: ["resources"],
      queryFn: () => api<Resource[]>("/resources"),
    });
  const [stage, setStage] = useState(false),
    [deleting, setDeleting] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [tab, setTab] = useState("main");
  if (query.isPending) return <Loading />;
  if (query.error || !query.data) return <ErrorBox error={query.error} />;
  const b = query.data,
    c = b.content,
    rs = resources.data || [],
    canEdit =
      can(u, bookingDoc(b.kind), "write") &&
      (b.kind !== "A" || b.status === "PENDING");
  const stages = b.stages || [],
    startMileage = stages.find((s) => s.kind === "B")?.content.start?.mileage,
    endMileage = stages.find((s) => s.kind === "C")?.content.arrival?.mileage,
    mileage =
      startMileage != null && endMileage != null
        ? (Number(endMileage) - Number(startMileage)).toFixed(1)
        : null;
  async function remove() {
    setBusy(true);
    try {
      await api("/bookings/" + id, "DELETE");
      await invalidate();
      navigate("/bookings");
    } catch (e) {
      setError((e as Error).message);
      setDeleting(false);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Link className="back-link" to="/bookings">
        <ArrowLeft size={16} />
        返回借用紀錄
      </Link>
      <PageHead
        eyebrow={b.id}
        title={c.title}
        description={`${kindNames[b.kind]} · 建立於 ${dateTime(b.created_at)} · 最近更新 ${dateTime(b.updated_at)}`}
        action={
          <div className="heading-actions">
            {canEdit && (
              <button
                className="button"
                onClick={() => navigate("/bookings/" + id + "/edit")}
              >
                <Pencil size={16} />
                編輯
              </button>
            )}
            {can(u, bookingDoc(b.kind), "delete") && (
              <button className="button" onClick={() => setDeleting(true)}>
                <Trash2 size={16} />
                刪除
              </button>
            )}
            {!(b as any).incomplete &&
              can(
                u,
                (
                  {
                    PENDING: "departure_form",
                    DEPARTURE: "departure_arrive",
                    DEPARTURE_ARRIVED: "back_form",
                    RETURN: "back_arrive",
                  } as Record<string, string>
                )[b.status],
                ["DEPARTURE", "RETURN"].includes(b.status) ? "write" : "create",
              ) &&
              b.kind === "A" &&
              nextStates[b.status] && (
                <button
                  className="button primary"
                  onClick={() => setStage(true)}
                >
                  {nextStates[b.status]}
                  <ArrowRight size={16} />
                </button>
              )}
          </div>
        }
      />
      {location.state?.saved && (
        <div className="success">
          <CheckCircle2 size={18} />
          申請已成功保存，編號 {b.id}。
        </div>
      )}
      <ErrorBox
        error={
          error ||
          ((b as any).incomplete
            ? "流程資料不完整：缺少必要 B／C 紀錄，已停止推進。"
            : null)
        }
      />
      {b.kind === "A" && (
        <div className="panel workflow">
          {Object.entries(states).map(([s, label], i) => {
            const current = Object.keys(states).indexOf(b.status);
            return (
              <div key={s} className={i <= current ? "reached" : ""}>
                <span>{i < current ? <Check size={16} /> : i + 1}</span>
                <strong>{label}</strong>
                {i < 4 && <i />}
              </div>
            );
          })}
        </div>
      )}
      <div className="detail-layout">
        <section className="panel">
          <div className="list-tabs">
            <button
              className={tab === "main" ? "active" : ""}
              onClick={() => setTab("main")}
            >
              申請內容
            </button>
            {stages.map((s) => (
              <button
                key={s.id}
                className={tab === s.id ? "active" : ""}
                onClick={() => setTab(s.id)}
              >
                {s.kind === "B" ? "發車與抵達" : "還車與抵達"}
              </button>
            ))}
            <button
              className={tab === "versions" ? "active" : ""}
              onClick={() => setTab("versions")}
            >
              修訂版本
            </button>
          </div>
          <div className="detail-content">
            {tab === "main" ? (
              <>
                <div className="detail-top">
                  <h2>基本資訊</h2>
                  <Status status={b.status} />
                </div>
                <div className="summary-grid three">
                  <div>
                    <small>申請人</small>
                    <strong>{c.applicant}</strong>
                  </div>
                  <div>
                    <small>使用需求</small>
                    <strong>{c.reason}</strong>
                  </div>
                  <div>
                    <small>總使用人數</small>
                    <strong>
                      {b.kind === "D" ? "—" : c.total_people + " 人"}
                    </strong>
                  </div>
                  <div>
                    <small>使用人員</small>
                    <strong>{c.employees?.join("、") || "—"}</strong>
                  </div>
                  <div>
                    <small>申請日期</small>
                    <strong>{c.application_date}</strong>
                  </div>
                  <div>
                    <small>總借用里程</small>
                    <strong>
                      {mileage === null
                        ? "N/A"
                        : Number(mileage) < 0
                          ? "資料異常"
                          : mileage + " km"}
                    </strong>
                  </div>
                </div>
                <h3 className="detail-section-title">使用需求明細</h3>
                {c.details?.map((d: any, i: number) => (
                  <div className="review-detail" key={i}>
                    <span>{String(i + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{d.name || "—"}</strong>
                      <small>
                        {d.city} {d.district}
                        {d.leader ? " · 組長 " + d.leader : ""}
                        {d.sales?.length ? " · 業務 " + d.sales.join("、") : ""}
                      </small>
                      {d.notes && <p>{d.notes}</p>}
                      {d.notes2 && <p>{d.notes2}</p>}
                    </div>
                  </div>
                ))}
                <h3 className="detail-section-title">資源與預約時段</h3>
                {b.slots.map((s, i) => (
                  <div className="slot-summary" key={i}>
                    <strong>
                      {rs.find((r) => r.id === s.resource_id)?.label ||
                        b.content.resource_snapshots?.find(
                          (r: any) => r.id === s.resource_id,
                        )?.label ||
                        "歷史資源 #" + s.resource_id}
                    </strong>
                    <span>
                      {dateTime(s.start)} → {dateTime(s.end)}
                    </span>
                    {b.kind === "A" && (
                      <Link
                        className="text-link"
                        to={
                          "/positions?resource=" +
                          s.resource_id +
                          "&start=" +
                          encodeURIComponent(s.start) +
                          "&end=" +
                          encodeURIComponent(s.end)
                        }
                      >
                        查看軌跡
                        <ArrowRight size={14} />
                      </Link>
                    )}
                  </div>
                ))}
                <h3 className="detail-section-title">用途與補充資訊</h3>
                <div className="tags">
                  {c.purposes?.map((p: string) => (
                    <span key={p} className="resource-tag">
                      {p}
                    </span>
                  ))}
                </div>
                {c.other_purpose && <p>其他用途：{c.other_purpose}</p>}
                {c.other_processing && <p>其他加工：{c.other_processing}</p>}
                {"notes" in c && (
                  <p className="preserve-lines muted">
                    {c.notes || "未填寫補充資訊"}
                  </p>
                )}
                {b.previous_id && (
                  <details>
                    <summary>此申請取代 {b.previous_id}，查看舊版</summary>
                    <pre>
                      {JSON.stringify(
                        (b as any).previous_version?.content,
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                )}
              </>
            ) : tab === "versions" ? (
              <>
                {b.versions?.length ? (
                  b.versions.map((v) => (
                    <details className="version" key={v.id}>
                      <summary>
                        {dateTime(v.time)} · {v.actor}
                        <ChevronDown size={16} />
                      </summary>
                      <pre>{JSON.stringify(v.data, null, 2)}</pre>
                    </details>
                  ))
                ) : (
                  <Empty
                    title="尚無修訂版本"
                    description="表單修改或流程更新前會保存原始內容。"
                  />
                )}
              </>
            ) : (
              <>
                <Link className="button" to={"/stages/" + tab}>
                  查看／修正此階段
                </Link>
                <StageView stage={stages.find((s) => s.id === tab)} />
              </>
            )}
          </div>
        </section>
        <aside>
          <div className="panel timeline-panel">
            <div className="section-title">
              <h3>操作歷程</h3>
              <History size={18} />
            </div>
            <div className="timeline">
              {b.history?.map((h, i) => (
                <div key={i}>
                  <i />
                  <strong>{h.action}</strong>
                  <span>{h.actor}</span>
                  <small>{dateTime(h.time)}</small>
                </div>
              ))}
            </div>
          </div>
          <div className="tip-card">
            <h3>資料持續保留</h3>
            <p>
              此預覽版本的申請、流程與附件會保存至伺服器，重新整理後仍可查看。
            </p>
          </div>
        </aside>
      </div>
      <StageForm open={stage} close={() => setStage(false)} booking={b} />
      <Confirm
        open={deleting}
        title="刪除這張預約？"
        description={`將取消 ${b.id}「${c.title}」並釋放全部資源時段。歷史資料會保留。`}
        onClose={() => setDeleting(false)}
        onConfirm={remove}
        busy={busy}
      />
    </>
  );
}
