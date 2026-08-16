import { ProviderSetup } from "./ProviderSetup";
import type { Course } from "../lib/types";

export function Studio({ onImportCourse }: { onImportCourse: (file: File) => Promise<Course | undefined> }) {
  return <main className="page studio">
    <div className="eyebrow">Clear English Speaking · 所有内容仅保存在本机</div>
    <h1>备课中心</h1>
    <p className="muted">选择已登录的助手或配置自己的 API；课程校验失败不会进入播放器，已有课程也不受影响。</p>
    <ProviderSetup onImportCourse={onImportCourse} />
  </main>;
}
