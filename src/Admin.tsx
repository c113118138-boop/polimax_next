import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, dateTime, invalidate, Resource } from "./api";
import {
  Confirm,
  Empty,
  ErrorBox,
  Field,
  Loading,
  Modal,
  PageHead,
} from "./ui";
import { can, Scope } from "./Access";
import { useUser } from "./App";
export function Beacons() {
  const u = useUser(),
    q = useQuery({
      queryKey: ["beacons"],
      queryFn: () => api<any[]>("/beacons"),
      refetchInterval: 5000,
    }),
    resources = useQuery({
      queryKey: ["resources"],
      queryFn: () => api<Resource[]>("/resources"),
    });
  const [edit, setEdit] = useState<any>(null),
    [original, setOriginal] = useState<string | null>(null),
    [remove, setRemove] = useState<any>(null),
    [search, setSearch] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const rows = (q.data || []).filter((b) =>
    [b.id, b.owner].join(" ").toLowerCase().includes(search.toLowerCase()),
  );
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        "/beacons" + (original ? "/" + original : ""),
        original ? "PUT" : "POST",
        edit,
      );
      await invalidate();
      setEdit(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Scope doc="BeaconList">
      <PageHead
        eyebrow="BEACON DIRECTORY"
        title="Beacon 清單"
        description="每 5 秒更新清單；編輯中的內容會保留。"
        action={
          can(u, "BeaconList", "create") && (
            <button
              className="button primary"
              onClick={() => {
                setOriginal(null);
                setEdit({
                  id: "",
                  owner: "",
                  programmed: "n",
                  equipment_resource_id: null,
                  ble_mac: "",
                });
              }}
            >
              新增 Beacon
            </button>
          )
        }
      />
      <section className="panel detail-content">
        <input
          aria-label="搜尋 Beacon"
          placeholder="搜尋 ID 或名稱"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <ErrorBox error={error || q.error} />
        {q.isPending ? (
          <Loading />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>major</th>
                  <th>名稱／擁有者</th>
                  <th>已燒錄</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.id}>
                    <td>{b.id}</td>
                    <td>{b.major}</td>
                    <td>{b.owner}</td>
                    <td>{b.programmed === "y" ? "是" : "否"}</td>
                    <td>
                      {can(u, "BeaconList", "write") && (
                        <button
                          className="button compact"
                          onClick={() => {
                            setOriginal(b.id);
                            setEdit({ ...b });
                          }}
                        >
                          編輯
                        </button>
                      )}
                      {can(u, "BeaconList", "delete") && (
                        <button
                          className="button compact"
                          onClick={() => setRemove(b)}
                        >
                          刪除
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Modal
        open={!!edit}
        title={original ? "編輯 Beacon" : "新增 Beacon"}
        onClose={() => !busy && setEdit(null)}
      >
        {edit && (
          <form onSubmit={save}>
            <Field label="Beacon ID（十六進位）" required>
              <input
                required
                readOnly={!!original}
                value={edit.id}
                onChange={(e) => setEdit({ ...edit, id: e.target.value })}
              />
            </Field>
            <Field label="名稱／擁有者" required>
              <input
                required
                value={edit.owner}
                onChange={(e) => setEdit({ ...edit, owner: e.target.value })}
              />
            </Field>
            <Field label="已燒錄">
              <select
                value={edit.programmed}
                onChange={(e) =>
                  setEdit({ ...edit, programmed: e.target.value })
                }
              >
                <option value="n">否</option>
                <option value="y">是</option>
              </select>
            </Field>
            <Field label="關聯設備">
              <select
                value={edit.equipment_resource_id || ""}
                onChange={(e) =>
                  setEdit({
                    ...edit,
                    equipment_resource_id: e.target.value
                      ? Number(e.target.value)
                      : null,
                  })
                }
              >
                <option value="">無關聯</option>
                {resources.data
                  ?.filter((r) => r.kind === "equipment")
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} · {r.label}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="BLE MAC">
              <input
                value={edit.ble_mac || ""}
                onChange={(e) => setEdit({ ...edit, ble_mac: e.target.value })}
              />
            </Field>
            <ErrorBox error={error} />
            <div className="actions">
              <button
                className="button"
                type="button"
                disabled={busy}
                onClick={() => setEdit(null)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "保存中…" : "儲存"}
              </button>
            </div>
          </form>
        )}
      </Modal>
      <Confirm
        open={!!remove}
        title="刪除 Beacon？"
        description={`${remove?.id} ${remove?.owner} 將停用，歷史報告仍保留。`}
        onClose={() => setRemove(null)}
        busy={busy}
        onConfirm={async () => {
          setBusy(true);
          try {
            await api("/beacons/" + remove.id, "DELETE");
            await invalidate();
            setRemove(null);
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      />
    </Scope>
  );
}
export function Integrations() {
  const q = useQuery({
      queryKey: ["notifications"],
      queryFn: () => api<any[]>("/notifications"),
    }),
    policy = useQuery({
      queryKey: ["policyHealth"],
      queryFn: () => api<any>("/permissions/health"),
    });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  async function action(path: string, body?: any) {
    setBusy(true);
    setError("");
    try {
      const r = await api(path, "POST", body);
      setMessage(
        r.version
          ? "有效政策版本 " + r.version
          : r.inserted !== undefined
            ? `匯入 ${r.inserted} 筆，重複 ${r.duplicates} 筆`
            : `測試通知成功 ${r.sent}、失敗 ${r.failed}、略過 ${r.skipped}`,
      );
      await invalidate();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead
        eyebrow="SERVICE MANAGEMENT"
        title="資料來源與測試通知"
        description="報告會持久保存。通知僅寫入測試記錄，不向真實對象傳送。"
      />
      <section className="panel detail-content">
        <h2>權限政策</h2>
        <p>有效版本：{policy.data?.active_version || "未知"}</p>
        <button
          className="button"
          disabled={busy}
          onClick={() => action("/permissions/sync")}
        >
          同步政策
        </button>
        <h2>定位與掃描報告</h2>
        <p>選取符合報告契約的 JSON 檔案。相同來源與報告 ID 會去重。</p>
        <input
          aria-label="匯入報告"
          type="file"
          accept="application/json,.json"
          disabled={busy}
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            try {
              const body = JSON.parse(await f.text());
              await action("/reports/import", body);
            } catch (e) {
              setError("JSON 格式錯誤：" + (e as Error).message);
            }
          }}
        />
        <button
          className="button"
          disabled={busy}
          onClick={() => action("/reports/sync")}
        >
          從設定來源更新
        </button>
        <details>
          <summary>報告檔案範例</summary>
          <pre>
            {JSON.stringify(
              {
                reports: [
                  {
                    source: "gps",
                    report_id: "example-001",
                    client_id: "PLM-TEST-001",
                    lat: 24.81,
                    lng: 120.98,
                    record_time: "2026-09-10T09:00:00+08:00",
                    created_at: "2026-09-10T09:01:00+08:00",
                  },
                ],
              },
              null,
              2,
            )}
          </pre>
        </details>
        <h2>保險通知</h2>
        <button
          className="button"
          disabled={busy}
          onClick={() => action("/notifications/check")}
        >
          檢查到期並記錄測試通知
        </button>
        <ErrorBox error={error || q.error || policy.error} />
        {message && <p role="status">{message}</p>}
        {q.isPending ? (
          <Loading />
        ) : q.data?.length ? (
          <div className="record-list">
            {q.data.map((n) => (
              <article className="record-card" key={n.id}>
                <strong>{n.content.Title}</strong>
                <p>{n.content.Content}</p>
                <small>
                  收件識別：{n.content.UserID} · {dateTime(n.time)} ·{" "}
                  {n.success ? "已記錄成功" : "失敗，可重試：" + n.error}
                </small>
              </article>
            ))}
          </div>
        ) : (
          <Empty title="尚無測試通知" />
        )}
      </section>
    </>
  );
}
