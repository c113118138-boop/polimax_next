import { ReactNode, useState, Children, isValidElement } from "react";
import { Dialog } from "@mui/material";
import {
  AlertCircle,
  Check,
  X,
  Upload,
  FileText,
  LoaderCircle,
  Search,
  ArrowUpRight,
} from "lucide-react";
import { states } from "./api";
import { useFieldAccess } from "./Access";
export function PageHead({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function ErrorBox({ error }: { error: unknown }) {
  return error ? (
    <div className="error" role="alert">
      <AlertCircle size={18} />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  ) : null;
}
export function Loading() {
  return (
    <div className="empty">
      <LoaderCircle className="spin" />
      <p>正在載入資料…</p>
    </div>
  );
}
export function Empty({
  title = "目前沒有資料",
  description = "新增第一筆資料，開始管理。",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Search size={25} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}
export function Status({ status }: { status: string }) {
  return (
    <span className={"status status-" + status}>
      <i />
      {states[status] || status}
    </span>
  );
}
export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth={wide ? "md" : "sm"}
      fullWidth
      PaperProps={{ className: "modal-paper" }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="icon-button" onClick={onClose} aria-label="關閉">
          <X size={20} />
        </button>
      </div>
      <div className="modal-content">{children}</div>
    </Dialog>
  );
}
export function Field({
  label,
  children,
  hint,
  required = false,
  field,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
  required?: boolean;
  field?: string;
}) {
  const child = Children.toArray(children).find(isValidElement) as any;
  const name =
    field ||
    child?.props?.name?.split(".").at(-1) ||
    (
      {
        備註: "notes",
        補充資訊: "notes",
        申請人: "applicant",
        申請日期: "application_date",
      } as Record<string, string>
    )[label] ||
    "";
  const access = useFieldAccess(name);
  if (!access.read) return null;
  return (
    <label className="field">
      <span>
        {label}
        {required && <b className="required"> *</b>}
        {!access.write && <small>（唯讀）</small>}
      </span>
      <fieldset
        disabled={!access.write}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
      >
        {children}
      </fieldset>
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function Confirm({
  open,
  title,
  description,
  onClose,
  onConfirm,
  busy = false,
}: {
  open: boolean;
  title: string;
  description: string;
  onClose: () => void;
  onConfirm: () => void;
  busy?: boolean;
}) {
  return (
    <Modal open={open} title={title} onClose={() => !busy && onClose()}>
      <p className="confirm-copy">{description}</p>
      <div className="actions">
        <button className="button" onClick={onClose} disabled={busy}>
          返回
        </button>
        <button className="button danger" onClick={onConfirm} disabled={busy}>
          {busy ? "處理中…" : "確認刪除"}
        </button>
      </div>
    </Modal>
  );
}
export function FileUpload({
  value = [],
  onChange,
  readOnly = false,
  images = false,
}: {
  value: any[];
  onChange: (v: any[]) => void;
  readOnly?: boolean;
  images?: boolean;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function upload(files: FileList | null) {
    if (!files) return;
    setBusy(true);
    setError("");
    const next = [...value];
    let failures: string[] = [];
    for (const f of Array.from(files)) {
      try {
        const res = await fetch("/api/files", {
          method: "POST",
          headers: {
            "X-AMS-Client": "preview",
            "X-File-Name": encodeURIComponent(f.name),
            "Content-Type": f.type || "application/octet-stream",
            "X-File-Purpose": images ? "stage-photo" : "attachment",
          },
          body: f,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);
        next.push(data);
      } catch (e) {
        failures.push(f.name + "：" + (e as Error).message);
      }
    }
    onChange(next);
    setError(failures.join("；"));
    setBusy(false);
  }
  return (
    <div className="attachments">
      {!readOnly && (
        <label className="upload-box">
          <Upload size={22} />
          <strong>{busy ? "正在上傳，請稍候…" : "選擇檔案或照片"}</strong>
          <span>
            {images
              ? "圖片可多檔，每個檔案上限 1 GB"
              : "支援多檔，每個檔案上限 10 MB"}
          </span>
          <input
            aria-label="上傳附件"
            type="file"
            accept={images ? "image/*" : undefined}
            multiple
            disabled={busy}
            onChange={(e) => {
              upload(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      )}
      <ErrorBox error={error} />
      {value.map((file, i) => (
        <div className="file-row" key={file.id}>
          <FileText size={18} />
          <a href={"/api/files/" + file.id} target="_blank" rel="noreferrer">
            {file.name}
          </a>
          {file.mime?.startsWith("image/") && (
            <a
              title="預覽"
              href={"/api/files/" + file.id + "?preview=true"}
              target="_blank"
              rel="noreferrer"
            >
              <ArrowUpRight size={17} />
            </a>
          )}
          {!readOnly && (
            <button
              type="button"
              className="icon-button"
              aria-label={"移除 " + file.name}
              onClick={() => onChange(value.filter((_, j) => j !== i))}
            >
              <X size={16} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
export function Saved({ text }: { text: string }) {
  return (
    <div className="success">
      <Check size={18} />
      {text}
    </div>
  );
}
