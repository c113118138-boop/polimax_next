import { createContext, useContext, useState } from "react";
import {
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  Navigate,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  CarFront,
  Layers,
  MapPin,
  Radio,
  Telescope,
  LogOut,
  Menu,
  ChevronDown,
  Plus,
  ClipboardList,
  Building2,
  ShieldCheck,
  PanelLeftClose,
  X,
  ArrowUpRight,
} from "lucide-react";
import { api, queryClient, User } from "./api";
import { ErrorBox, Loading, Modal } from "./ui";
import CalendarPage from "./Calendar";
import { BookingForm, BookingList, BookingDetail } from "./Bookings";
import { Assets, AssetDetail } from "./Assets";
import { Positions, Scans, FindMy } from "./Maps";
import { StageList, StagePage } from "./Stages";
import { Beacons, Integrations } from "./Admin";
import { Guard, can } from "./Access";
const UserContext = createContext<User>(null!);
export const useUser = () => useContext(UserContext);
const nav = [
  {
    title: "工作空間",
    items: [
      ["/", "預約日曆", CalendarDays],
      ["/bookings", "借用紀錄", ClipboardList],
      ["/stages", "出回程紀錄", ClipboardList],
      ["/bookings?history=1", "車輛使用歷史", ClipboardList],
    ],
  },
  {
    title: "資產管理",
    items: [
      ["/vehicles", "公務車輛", CarFront],
      ["/equipment", "儀器設備", Telescope],
    ],
  },
  {
    title: "定位與資訊",
    items: [
      ["/positions", "最新位置", MapPin],
      ["/scans", "場內掃描", Radio],
      ["/findmy", "Beacon 設備位置", MapPin],
      ["/beacons", "Beacon 清單", Radio],
      ["/integrations", "資料來源與通知", ShieldCheck],
    ],
  },
];
export default function App() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/auth/me"),
  });
  if (me.isPending) return <Loading />;
  if (!me.data) return <Login />;
  return (
    <UserContext.Provider value={me.data}>
      <Shell />
    </UserContext.Provider>
  );
}
function Login() {
  const auth = useQuery({ queryKey: ["auth-config"], queryFn: () => api("/auth/config") });
  const demo = ["test", "demo"].includes(auth.data?.mode);
  const [role, setRole] = useState("admin"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(new URLSearchParams(window.location.search).get("sso_error") || "");
  const navigate = useNavigate();
  async function login() {
    if (!demo) {
      const returnTo = window.location.pathname + (window.location.search.includes("sso_error") ? "" : window.location.search);
      window.location.assign("/api/auth/sso?return_to=" + encodeURIComponent(returnTo));
      return;
    }
    setBusy(true);
    try {
      const u = await api("/auth/login", "POST", { role });
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      queryClient.setQueryData(["me"], u);
      navigate("/");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <div className="login-visual">
        <Brand />
        <div className="login-art">
          <div className="orbit one" />
          <div className="orbit two" />
          <div className="orbit three" />
          <div className="orbit-center">
            <Layers size={54} />
          </div>
          <span className="orbit-label label-a">
            <CarFront />
            車輛
          </span>
          <span className="orbit-label label-b">
            <Building2 />
            空間
          </span>
          <span className="orbit-label label-c">
            <Telescope />
            設備
          </span>
        </div>
        <div>
          <div className="eyebrow">CONNECTED RESOURCES. BETTER WORK.</div>
          <h1>
            讓每一份資源，
            <br />
            都在對的位置。
          </h1>
          <p>預約、使用、歸還。把工作日常整理得井然有序。</p>
        </div>
        <small>POLIMAX ASSET MANAGEMENT SYSTEM</small>
      </div>
      <div className="login-form">
        <div className="login-card">
          <span className="pill">{demo ? "互動預覽 · 測試環境" : "POLIMAX · 公司帳號登入"}</span>
          <h1>歡迎回來</h1>
          <p>{demo ? "選擇測試身分，探索新的資源管理工作空間。" : "使用公司 SSO 帳號登入資源管理工作空間。"}</p>
          {demo && <div className="role-list">
            {[
              ["admin", "管理員", "完整管理、借用與資料維護"],
              ["borrower", "借用人", "建立預約、填寫車輛使用紀錄"],
              ["viewer", "唯讀使用者", "查看記錄；備註及假日切換受限"],
              ["draft", "草稿測試員", "可開啟新增表單，但無送出權限"],
            ].map(([id, label, desc]) => (
              <button
                key={id}
                className={"role-option " + (role === id ? "selected" : "")}
                onClick={() => setRole(id)}
              >
                <ShieldCheck size={22} />
                <span>
                  <strong>{label}</strong>
                  <small>{desc}</small>
                </span>
                <i />
              </button>
            ))}
          </div>}
          <ErrorBox error={error || auth.error || (auth.data && !auth.data.configured ? "SSO 設定尚未完成" : null)} />
          <button
            className="button primary login-submit"
            onClick={login}
            disabled={busy || auth.isPending || !auth.data?.configured}
          >
            {busy ? "正在登入…" : demo ? "進入工作空間" : "使用公司 SSO 登入"}
            <ArrowRight size={18} />
          </button>
          <div className="login-note">
            {demo ? "此入口採本地測試登入。" : "登入後依你的 AMS 權限顯示可使用的功能。"}
          </div>
        </div>
        <small className="login-footer">
          POLIMAX / AMS <span>{demo ? "設計預覽 01" : "資源管理系統"}</span>
        </small>
      </div>
    </div>
  );
}
function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">
        <span />
        <span />
        <span />
      </div>
      <div>
        POLIMAX<small>ASSET MANAGEMENT</small>
      </div>
    </div>
  );
}
function Shell() {
  const u = useUser(),
    location = useLocation(),
    navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false),
    [create, setCreate] = useState(false),
    [logout, setLogout] = useState(false),
    [logoutError, setLogoutError] = useState("");
  const title =
    location.pathname === "/"
      ? "預約日曆"
      : location.pathname.startsWith("/vehicles")
        ? "公務車輛"
        : location.pathname.startsWith("/equipment")
          ? "儀器設備"
          : location.pathname.startsWith("/positions")
            ? "最新位置"
            : location.pathname.startsWith("/scans")
              ? "場內掃描"
              : "借用管理";
  return (
    <div className={"app-shell" + (collapsed ? " sidebar-collapsed" : "")}>
      <div
        className={"sidebar-shade " + (mobile ? "visible" : "")}
        onClick={() => setMobile(false)}
      />
      <aside className={"sidebar " + (mobile ? "is-open" : "")}>
        <Brand />
        <button className="workspace">
          <div className="workspace-icon">
            <Building2 size={19} />
          </div>
          <span>
            企業資源管理<small>POLIMAX 工作空間</small>
          </span>
          <ChevronDown size={15} />
        </button>
        <nav>
          {nav.map((group) => (
            <div className="nav-group" key={group.title}>
              <div className="nav-label">{group.title}</div>
              {group.items
                .filter(
                  ([path]: any) =>
                    path !== "/integrations" || can(u, "Administration"),
                )
                .map(([path, label, Icon]: any) => (
                  <NavLink
                    key={path}
                    to={path}
                    end={path === "/"}
                    onClick={() => setMobile(false)}
                    className={({ isActive }) =>
                      "nav-item " +
                      (isActive &&
                      (path.startsWith("/bookings")
                        ? location.search.includes("history") ===
                          path.includes("history")
                        : true)
                        ? "active"
                        : "")
                    }
                  >
                    <Icon size={19} />
                    <span>{label}</span>
                    {path === "/" && <span className="nav-dot" />}
                  </NavLink>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment">
            <i />
            <span>
              POLIMAX AMS<small>公司資源管理</small>
            </span>
            <ArrowUpRight size={15} />
          </div>
          <button className="user-card" onClick={() => setLogout(true)}>
            <div className="avatar">{u.name.slice(0, 1)}</div>
            <span>
              <strong>{u.name}</strong>
              <small>
                {u.email} · {u.id}
              </small>
            </span>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="開啟選單"
              onClick={() => setMobile(true)}
            >
              <Menu size={22} />
            </button>
            <button
              className="icon-button desktop-icon"
              aria-label={collapsed ? "展開側欄" : "收合側欄"}
              onClick={() => setCollapsed((v) => !v)}
            >
              <PanelLeftClose size={17} />
            </button>
            <span>工作空間</span>
            <span className="slash">/</span>
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <div className="account-summary" aria-label="目前使用者">
              <div className="avatar small" aria-hidden="true">{u.name.slice(0, 1)}</div>
              <div className="account-details">
                <span className="account-caption">目前使用者</span>
                <strong title={u.name}>{u.name}</strong>
                {u.email && <small title={u.email}>{u.email}</small>}
              </div>
            </div>
            <button
              className="button compact account-logout"
              onClick={() => { setLogoutError(""); setLogout(true); }}
              aria-label="登出"
            >
              <LogOut size={17} aria-hidden="true" />
              登出
            </button>
          </div>
        </header>
        <main>
          <Routes>
            <Route
              path="/"
              element={<CalendarPage onCreate={() => setCreate(true)} />}
            />
            <Route path="/bookings" element={<BookingList onCreate={() => setCreate(true)} />} />
            <Route path="/bookings/new/:kind" element={<BookingForm />} />
            <Route path="/bookings/:id/edit" element={<BookingForm />} />
            <Route path="/bookings/:id" element={<BookingDetail />} />
            <Route
              path="/vehicles"
              element={
                <Guard doc="VehicleManagement">
                  <Assets kind="vehicle" />
                </Guard>
              }
            />
            <Route
              path="/vehicles/:id"
              element={
                <Guard doc="VehicleManagement">
                  <AssetDetail />
                </Guard>
              }
            />
            <Route
              path="/equipment"
              element={
                <Guard doc="EquipmentManagement">
                  <Assets kind="equipment" />
                </Guard>
              }
            />
            <Route
              path="/equipment/:id"
              element={
                <Guard doc="EquipmentManagement">
                  <AssetDetail />
                </Guard>
              }
            />
            <Route
              path="/positions"
              element={
                <Guard doc="CarUpdate">
                  <Positions />
                </Guard>
              }
            />
            <Route
              path="/findmy"
              element={
                <Guard doc="FindMy">
                  <FindMy />
                </Guard>
              }
            />
            <Route
              path="/beacons"
              element={
                <Guard doc="BeaconList">
                  <Beacons />
                </Guard>
              }
            />
            <Route
              path="/integrations"
              element={
                <Guard doc="Administration">
                  <Integrations />
                </Guard>
              }
            />
            <Route
              path="/stages"
              element={
                <Guard doc="Departure_query">
                  <StageList />
                </Guard>
              }
            />
            <Route path="/stages/:id" element={<StagePage />} />
            <Route
              path="/scans"
              element={
                <Guard doc="Latest_Device">
                  <Scans />
                </Guard>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <footer className="app-footer">
          <span>POLIMAX · 讓資源管理更有條理</span>
          <span>
            Asia / Taipei <i /> AMS PREVIEW
          </span>
        </footer>
      </div>
      <Modal open={create} title="建立新預約" onClose={() => setCreate(false)}>
        <p className="muted">選擇要預約的資源，開始安排下一項工作。</p>
        <div className="create-options">
          {[
            ["A", "車輛借用", "公務用車與完整出回程紀錄", CarFront],
            ["D", "租用作業區", "施工區、會議室與辦公空間", Building2],
            ["E", "儀器借用", "量測、保養與設備使用安排", Telescope],
          ].map(([k, name, desc, Icon]: any) => (
            <button
              key={k}
              onClick={() => {
                setCreate(false);
                navigate("/bookings/new/" + k);
              }}
            >
              <div className={"resource-icon type-" + k}>
                <Icon size={24} />
              </div>
              <span>
                <strong>{name}</strong>
                <small>{desc}</small>
              </span>
              <ArrowRight size={19} />
            </button>
          ))}
        </div>
      </Modal>
      <Modal
        open={logout}
        title="登出工作空間"
        onClose={() => setLogout(false)}
      >
        <p>確定要登出 {u.name} 的帳號嗎？</p>
        <ErrorBox error={logoutError} />
        <div className="actions">
          <button className="button" onClick={() => setLogout(false)}>
            取消
          </button>
          <button
            className="button primary"
            onClick={async () => {
              try {
                const result = await api("/auth/logout", "POST");
                queryClient.clear();
                if (result.logout_url) { window.location.assign(result.logout_url); return; }
                navigate("/");
                window.location.reload();
              } catch (e) {
                setLogoutError((e as Error).message);
              }
            }}
          >
            確認登出
          </button>
        </div>
      </Modal>
    </div>
  );
}
