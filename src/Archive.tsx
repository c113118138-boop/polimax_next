import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, dateTime } from "./api";
import { useUser } from "./App";
import { can } from "./Access";
import { ErrorBox, Loading, Modal, PageHead, Field } from "./ui";

const fields: Record<string, string> = {
  id: "編號", ID: "編號", sn: "編號", form_id: "表單編號", plate: "車牌", license_plate: "車牌",
  created_at: "建立時間", create_at: "建立時間", updated_at: "更新時間", record_date: "紀錄日期",
  start: "開始時間", end: "結束時間", status: "狀態", company: "保險公司", validity_period: "到期日",
  reason: "事由", amount: "金額", notes: "備註", type: "類型", record_type: "維修類型",
  employees: "使用人員", applicant_ID: "申請人", place: "地點", client_id: "設備編號",
  title: "標題", content: "內容", timestamp: "記錄時間", latitude: "緯度", longitude: "經度",
};

function Values({ value }: { value: any }) {
  return <div className="table-scroll"><table><tbody>{Object.entries(value).map(([key, item]) =>
    <tr key={key}><th>{fields[key] || key}</th><td style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
      {item == null ? "—" : typeof item === "object" ? JSON.stringify(item) : String(item)}</td></tr>)}</tbody></table></div>;
}

export default function Archive() {
  const user = useUser();
  const catalog = useQuery({ queryKey: ["archive-catalog"], queryFn: () => api<any[]>("/archive/catalog") });
  const [name, setName] = useState("formio_responses"), [mode, setMode] = useState("history");
  const [page, setPage] = useState(0), [search, setSearch] = useState("");
  const [view, setView] = useState<any>(null), [complete, setComplete] = useState<any>(null);
  const [date, setDate] = useState(""), [note, setNote] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const selected = catalog.data?.find(row => row.name === name);
  const live = mode === "live" && selected?.manual;
  const list = useQuery({
    queryKey: ["archive", name, live, page, search], enabled: !!selected,
    queryFn: () => api(live ? `/archive/live/${name}?page=${page}&search=${encodeURIComponent(search)}` :
      `/archive/history?name=${name}&page=${page}&key=${encodeURIComponent(search)}`),
  });
  async function show(id: string) {
    setError("");
    try { setView(await api(`/archive/history/${id}`)); }
    catch (e) { setError((e as Error).message); }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api(`/archive/live/${name}/${encodeURIComponent(complete.key)}/completion`, "PUT", { completed_at: date, note });
      setComplete(null); await list.refetch();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function reopen(key: string) {
    setBusy(true); setError("");
    try { await api(`/archive/live/${name}/${encodeURIComponent(key)}/completion`, "DELETE"); await list.refetch(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <>
    <PageHead title="歷史封存" eyebrow="ARCHIVE" description="查閱已驗證保存的舊紀錄，或登記業務完成日期。完成後滿 90 天且符合保留條件，才會移入歷史資料。" />
    <section className="panel detail-content">
      <div className="form-grid">
        <Field label="資料類型"><select value={name} onChange={e => { setName(e.target.value); setPage(0); setSearch(""); }}>
          {catalog.data?.map(row => <option key={row.name} value={row.name}>{row.label}</option>)}
        </select></Field>
        <Field label="查詢範圍"><select value={live ? "live" : "history"} onChange={e => { setMode(e.target.value); setPage(0); setSearch(""); }}>
          <option value="history">已封存紀錄</option>{selected?.manual && <option value="live">正式資料與完成登記</option>}
        </select></Field>
        <Field label={live ? "搜尋編號或車牌" : "完整表單／紀錄編號（選填）"}>
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} />
        </Field>
      </div>
      {live && <p>完成登記代表費用已核對、維修已完成、保單無待辦理賠、文件已失效，或借用已歸還。仍有效或未完成的資料請保留。資料內容變更後，原完成登記會失效，需重新確認。</p>}
      <ErrorBox error={error || catalog.error || list.error} />
      {list.isPending ? <Loading /> : <div className="table-scroll"><table>
        <thead><tr><th>編號</th><th>{live ? "資料" : "封存時間"}</th><th>{live ? "完成登記" : "筆數"}</th><th>操作</th></tr></thead>
        <tbody>{list.data?.items?.map((item: any, i: number) => <tr key={item.id || `${item.key}-${i}`}>
          <td>{live ? item.key : item.record_key || "批次紀錄"}</td>
          <td>{live ? [item.row.plate, item.row.license_plate, item.row.reason, item.row.company, item.row.status].filter(Boolean).join(" · ") : dateTime(item.created_at)}</td>
          <td>{live ? item.completion ? dateTime(item.completion.completed_at) : "尚未登記" : item.row_count}</td>
          <td><button className="button compact" onClick={() => live ? setView({ payload: { rows: { [name]: [item.row] }, files: {} } }) : show(item.id)}>查看</button>
            {live && can(user, "Administration", "write") && <>
              <button className="button compact" onClick={() => { setComplete(item); setDate(""); setNote(""); setError(""); }}>登記完成／失效</button>
              {item.completion && <button disabled={busy} className="button compact" onClick={() => reopen(item.key)}>取消完成登記</button>}
            </>}
          </td></tr>)}</tbody>
      </table>{!list.data?.items?.length && <p>沒有符合條件的紀錄。</p>}</div>}
      <div className="actions"><button className="button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一頁</button>
        <span>第 {page + 1} 頁</span><button className="button" disabled={!list.data?.has_more} onClick={() => setPage(page + 1)}>下一頁</button></div>
    </section>
    <Modal open={!!complete} title="登記業務完成／文件失效" onClose={() => !busy && setComplete(null)}>
      <form onSubmit={save}>
        <p>此操作登記實際完成狀態，不會立即搬移或刪除資料。借用表單會整份連同流程與附件一起處理。</p>
        <Field label="實際完成／失效時間" required><input required type="datetime-local" value={date} onChange={e => setDate(e.target.value)} /></Field>
        <Field label="完成依據（例如核對完成、維修結案、已歸還、文件已取代）" required><textarea required maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></Field>
        <ErrorBox error={error} /><button disabled={busy} className="button primary">確認登記</button>
      </form>
    </Modal>
    <Modal open={!!view} title="紀錄內容" onClose={() => setView(null)}>
      {view && <>{Object.entries(view.payload.rows).map(([table, rows]) => <section key={table}>
        <h3>{catalog.data?.find(row => row.name === table)?.label || "流程紀錄"}</h3>
        {(rows as any[]).map((row, i) => <Values key={i} value={row} />)}
      </section>)}
      {Object.keys(view.payload.files).length > 0 && <><h3>表單原檔與附件</h3>
        <ul>{Object.keys(view.payload.files).map(path => <li key={path}><a href={`/api/archive/history/${view.id}/file?path=${encodeURIComponent(path)}`}>{path.split("/").pop()}</a></li>)}</ul></>}
      </>}
    </Modal>
  </>;
}
