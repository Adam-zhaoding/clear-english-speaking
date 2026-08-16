import { BookOpen, Books, House, ShieldCheck, Sparkle, TrendUp } from "@phosphor-icons/react";

export type View = "home" | "practice" | "library" | "studio" | "review";

const items: { view: View; label: string; icon: typeof House }[] = [
  { view: "home", label: "首页", icon: House },
  { view: "practice", label: "训练", icon: BookOpen },
  { view: "library", label: "课程库", icon: Books },
  { view: "studio", label: "备课", icon: Sparkle },
  { view: "review", label: "复盘", icon: TrendUp }
];

export function Sidebar({ view, setView, courseCount }: { view: View; setView: (value: View) => void; courseCount: number }) {
  return <aside className="sidebar">
    <div className="brand"><span>CE</span><b>Clear English</b></div>
    <nav>
      {items.map(({ view: itemView, label, icon: Icon }) => (
        <button key={itemView} className={view === itemView ? "active" : ""} onClick={() => setView(itemView)}>
          <Icon size={22} weight="regular" />
          <span>{label}</span>
          {itemView === "library" && courseCount > 0 && <em className="count">{courseCount}</em>}
        </button>
      ))}
    </nav>
    <div className="calendar-note">
      <ShieldCheck size={20} />
      <span>课程、录音和记录<br /><b>只保存在本机</b></span>
    </div>
  </aside>;
}
