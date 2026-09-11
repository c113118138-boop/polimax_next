import { createContext, ReactNode, useContext } from "react";
import { Link } from "react-router-dom";
import { useUser } from "./App";
export const AccessScope = createContext("Lending_form");
export function can(u: any, doc: string, op = "read") {
  return !!u?.permissions?.forms?.[doc]?.[op];
}
export const bookingDoc = (kind: string) =>
  ({
    A: "Lending_form",
    B: "departure_form",
    C: "back_form",
    D: "Room_form",
    E: "Equipment_form",
  })[kind] || "Lending_form";
export function Scope({ doc, children }: { doc: string; children: ReactNode }) {
  return <AccessScope.Provider value={doc}>{children}</AccessScope.Provider>;
}
export function Guard({
  doc,
  op = "read",
  children,
}: {
  doc: string;
  op?: string;
  children: ReactNode;
}) {
  const u = useUser();
  return can(u, doc, op) ? (
    <Scope doc={doc}>{children}</Scope>
  ) : (
    <div className="panel detail-content">
      <h2>權限不足</h2>
      <p>
        {doc} 缺少 {op} 權限。
      </p>
      <Link to="/">返回首頁</Link>
    </div>
  );
}
export function useFieldAccess(name: string) {
  const u = useUser(),
    doc = useContext(AccessScope);
  return !name
    ? { read: 1, write: 1 }
    : u?.permissions?.fields?.[doc]?.[name] || {
        read: 1,
        write: can(u, doc, "write") || can(u, doc, "create") ? 1 : 0,
      };
}
