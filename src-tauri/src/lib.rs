use arboard::Clipboard;
use chrono::Utc;
use keyring::Entry;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{env, fs, io, io::BufRead, path::{Path, PathBuf}, process::{Command, Stdio}, thread};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use tauri::{AppHandle, Emitter, Manager};
use uuid::Uuid;

const APP_FOLDER: &str = "ClearEnglish";
const ENGINE_BINARY: &[u8] = include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/resources/bbc-course-agent.exe"));
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopStatus {
    desktop: bool,
    codex_available: bool,
    workbuddy_available: bool,
    workbuddy_home: String,
    data_directory: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct WorkBuddySetup {
    workspace: String,
    job_id: String,
    prompt: String,
    prompt_copied: bool,
    launch_attempted: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopJob {
    id: String,
    provider: String,
    status: String,
    created_at: String,
    updated_at: String,
    message: String,
    error: String,
    ready: bool,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct BuildProgress {
    job_id: String,
    stage: String,
    message: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ApiConfiguration {
    base_url: String,
    model: String,
    api_key: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ScheduleConfiguration {
    days: Vec<u8>,
    time: String,
    timezone: String,
    provider: String,
    enabled: bool,
}

fn local_app_data() -> Result<PathBuf, String> {
    let root = env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(PathBuf::from))
        .ok_or("无法找到当前用户的本机数据目录。")?;
    let path = root.join(APP_FOLDER);
    fs::create_dir_all(&path).map_err(|error| error.to_string())?;
    Ok(path)
}

fn engine_home() -> Result<PathBuf, String> {
    let path = local_app_data()?.join("engine");
    fs::create_dir_all(&path).map_err(|error| error.to_string())?;
    Ok(path)
}

fn workbuddy_home() -> PathBuf {
    env::var_os("USERPROFILE").map(PathBuf::from).or_else(|| env::var_os("HOME").map(PathBuf::from)).unwrap_or_default().join(".workbuddy")
}

fn workspace_root() -> Result<PathBuf, String> {
    let root = local_app_data()?.join("workbuddy-workspace");
    fs::create_dir_all(root.join(".clear-english-speaking").join("jobs")).map_err(|error| error.to_string())?;
    Ok(root)
}

fn now() -> String { Utc::now().to_rfc3339() }

fn run_without_console(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

fn command_exists(command: &str) -> bool {
    let mut lookup = Command::new("where.exe");
    run_without_console(lookup.arg(command)).output().map(|output| output.status.success()).unwrap_or(false)
}

fn copy_dir(source: &Path, destination: &Path) -> io::Result<()> {
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let target = destination.join(entry.file_name());
        if entry.file_type()?.is_dir() { copy_dir(&entry.path(), &target)?; }
        else { fs::copy(entry.path(), target)?; }
    }
    Ok(())
}

fn skill_source(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(resources) = app.path().resource_dir() {
        let packaged = resources.join("bbc-course-pack-builder");
        if packaged.is_dir() { return Ok(packaged); }
    }
    let development = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().ok_or("无法定位应用源目录。")?.join("skills").join("bbc-course-pack-builder");
    if development.is_dir() { Ok(development) } else { Err("缺少内置 BBC 课程构建 Skill。".into()) }
}

fn workbuddy_prompt(job_path: &Path) -> String {
    format!("请为 Clear English Speaking 完成一节 BBC 6 Minute English 备课任务。\n\n任务文件：{}\n\n请读取任务文件，选择一篇未学习过的 BBC Learning English 官方 6 Minute English 节目。仅从官方 Transcript 逐字选择 5–6 句，并生成中文释义、词汇、听力提示和理解检查。不要下载或分发音频、PDF、课程 ZIP，也不要写入工作区外的文件。\n\n将严格 JSON 草案写到任务文件中 output_draft 指定的路径。必须包含 bbc_page_url、title、sentences；每个 sentence 至少有 text 与 translation_zh。完成后只报告“草案已写入”。", job_path.display())
}

fn write_job(root: &Path, provider: &str) -> Result<(String, PathBuf, String), String> {
    let id = Uuid::new_v4().to_string();
    let job = root.join(".clear-english-speaking").join("jobs").join(&id);
    let output = job.join("output");
    fs::create_dir_all(&output).map_err(|error| error.to_string())?;
    let draft = output.join("lesson-draft.json");
    let value = json!({
        "schema_version": 1,
        "id": id,
        "provider": provider,
        "status": "awaiting_agent",
        "created_at": now(),
        "output_draft": draft,
        "course_directory": engine_home()?.join("courses"),
        "source_policy": "BBC Learning English official 6 Minute English only; official Transcript only; reject worksheet; choose 5-6 verbatim sentences."
    });
    let job_path = job.join("task.json");
    fs::write(&job_path, serde_json::to_vec_pretty(&value).map_err(|error| error.to_string())?).map_err(|error| error.to_string())?;
    let prompt = workbuddy_prompt(&job_path);
    fs::write(job.join("SEND_THIS_TO_WORKBUDDY.txt"), &prompt).map_err(|error| error.to_string())?;
    Ok((id, job_path, prompt))
}

fn workbuddy_candidates() -> Vec<PathBuf> {
    let mut candidates = vec![
        env::var_os("LOCALAPPDATA").map(PathBuf::from).map(|path| path.join("Programs").join("WorkBuddy").join("WorkBuddy.exe")),
        env::var_os("PROGRAMFILES").map(PathBuf::from).map(|path| path.join("WorkBuddy").join("WorkBuddy.exe")),
        env::var_os("ProgramW6432").map(PathBuf::from).map(|path| path.join("WorkBuddy").join("WorkBuddy.exe")),
        env::var_os("ProgramFiles(x86)").map(PathBuf::from).map(|path| path.join("WorkBuddy").join("WorkBuddy.exe")),
    ].into_iter().flatten().collect::<Vec<_>>();
    for letter in b'C'..=b'Z' {
        candidates.push(PathBuf::from(format!("{}:\\Program Files\\WorkBuddy\\WorkBuddy.exe", letter as char)));
    }
    candidates
}

fn workbuddy_executable() -> Option<PathBuf> {
    workbuddy_candidates().into_iter().find(|candidate| candidate.is_file())
}

fn try_open_workbuddy(workspace: &Path) -> Result<bool, String> {
    let executable = workbuddy_executable().ok_or("已创建备课工作区，但未找到 WorkBuddy 程序。请先安装或启动 WorkBuddy。")?;
    Command::new(executable).arg(workspace).spawn().map(|_| true).map_err(|error| format!("无法启动 WorkBuddy：{error}"))
}

#[tauri::command]
fn open_workbuddy() -> Result<(), String> {
    let workspace = workspace_root()?;
    try_open_workbuddy(&workspace)?;
    Ok(())
}

#[tauri::command]
fn desktop_status() -> Result<DesktopStatus, String> {
    let data = local_app_data()?;
    let buddy = workbuddy_home();
    Ok(DesktopStatus { desktop: true, codex_available: command_exists("codex"), workbuddy_available: workbuddy_executable().is_some(), workbuddy_home: buddy.display().to_string(), data_directory: data.display().to_string() })
}

#[tauri::command]
fn prepare_workbuddy(app: AppHandle) -> Result<WorkBuddySetup, String> {
    if workbuddy_executable().is_none() { return Err("没有检测到 WorkBuddy 程序。请先安装并至少启动一次 WorkBuddy。".into()); }
    let workspace = workspace_root()?;
    let target_skill = workspace.join(".workbuddy").join("skills").join("bbc-course-pack-builder");
    if !target_skill.is_dir() { copy_dir(&skill_source(&app)?, &target_skill).map_err(|error| error.to_string())?; }
    let (job_id, _job_path, prompt) = write_job(&workspace, "workbuddy")?;
    let prompt_copied = Clipboard::new().and_then(|mut clipboard| clipboard.set_text(prompt.clone())).is_ok();
    Ok(WorkBuddySetup { workspace: workspace.display().to_string(), job_id, prompt, prompt_copied, launch_attempted: false })
}

#[tauri::command]
fn start_codex_job() -> Result<String, String> {
    if !command_exists("codex") { return Err("没有检测到已登录的 Codex。请安装并登录 Codex，或选择 WorkBuddy / API 模式。".into()); }
    let workspace = workspace_root()?;
    let (id, job_path, _) = write_job(&workspace, "codex")?;
    let schema_path = job_path.parent().ok_or("任务目录无效。")?.join("draft-schema.json");
    let output_path = job_path.parent().ok_or("任务目录无效。")?.join("output").join("lesson-draft.json");
    let schema = json!({"type":"object","required":["bbc_page_url","sentences"],"properties":{"bbc_page_url":{"type":"string"},"title":{"type":"string"},"sentences":{"type":"array","minItems":5,"maxItems":6,"items":{"type":"object","required":["text","translation_zh"],"properties":{"text":{"type":"string"},"translation_zh":{"type":"string"},"glossary":{"type":"array"},"diagnosis_tags":{"type":"array"},"listening_focus":{"type":"string"},"comprehension_check":{"type":"string"}}}}}});
    fs::write(&schema_path, serde_json::to_vec_pretty(&schema).map_err(|error| error.to_string())?).map_err(|error| error.to_string())?;
    let prompt = format!("Read this local Clear English Speaking job specification: {}. Find one eligible official BBC Learning English 6 Minute English episode. Return only the required JSON draft. Do not write files, do not download BBC assets, and use only official Transcript wording for the 5-6 selected English sentences.", job_path.display());
    thread::spawn(move || {
        let mut command = Command::new("codex");
        let result = run_without_console(command
            .args(["exec", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check", "--output-schema"])
            .arg(schema_path)
            .arg("-o").arg(&output_path)
            .arg(prompt))
            .output();
        let log_path = output_path.parent().unwrap().join("codex.log");
        let log = match result { Ok(output) => String::from_utf8_lossy(&output.stderr).to_string(), Err(error) => error.to_string() };
        let _ = fs::write(log_path, log);
    });
    Ok(id)
}

fn job_dir(job_id: &str) -> Result<PathBuf, String> {
    // Job ids come from the UI, so refuse anything that is not the uuid we wrote.
    if job_id.is_empty() || !job_id.chars().all(|value| value.is_ascii_alphanumeric() || value == '-') {
        return Err("任务编号无效。".into());
    }
    let path = workspace_root()?.join(".clear-english-speaking").join("jobs").join(job_id);
    if !path.is_dir() { return Err("找不到这个备课任务，它可能已经被清理。".into()); }
    Ok(path)
}

/// Persist where a job got to, so a refresh or restart does not silently
/// rebuild a lesson or hide the reason a build stopped.
fn write_job_state(job: &Path, status: &str, error: &str) -> Result<(), String> {
    let value = json!({ "status": status, "error": error, "updated_at": now() });
    fs::write(job.join("state.json"), serde_json::to_vec_pretty(&value).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())
}

fn read_job_state(job: &Path) -> (String, String, String) {
    let value: Value = fs::read(job.join("state.json")).ok()
        .and_then(|raw| serde_json::from_slice(&raw).ok())
        .unwrap_or_else(|| json!({}));
    (
        value["status"].as_str().unwrap_or_default().to_string(),
        value["error"].as_str().unwrap_or_default().to_string(),
        value["updated_at"].as_str().unwrap_or_default().to_string(),
    )
}

fn job_message(status: &str, provider: &str) -> String {
    match status {
        "draft_ready" => "已收到备课草案，正在等待本地校验。".into(),
        "building" => "正在校验官方素材并生成课程，请不要关闭窗口。".into(),
        "imported" => "课程已通过校验并导入播放器。".into(),
        "failed" => "这次备课没有完成，已有课程不受影响。".into(),
        _ if provider == "workbuddy" => "等待你在 WorkBuddy 新建会话并发送一次任务。".into(),
        _ => "备课助手正在准备草案。".into(),
    }
}

#[tauri::command]
fn list_desktop_jobs() -> Result<Vec<DesktopJob>, String> {
    let root = workspace_root()?.join(".clear-english-speaking").join("jobs");
    let mut jobs = Vec::new();
    for entry in fs::read_dir(root).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let task = entry.path().join("task.json");
        if !task.is_file() { continue; }
        let value: Value = match fs::read(&task).ok().and_then(|raw| serde_json::from_slice(&raw).ok()) {
            Some(value) => value,
            None => continue,
        };
        let draft_present = entry.path().join("output").join("lesson-draft.json").is_file();
        let (stored, error, updated_at) = read_job_state(&entry.path());
        // A stored terminal state wins; otherwise the draft file decides.
        let status = match stored.as_str() {
            "imported" | "failed" | "building" => stored.clone(),
            _ if draft_present => "draft_ready".to_string(),
            _ => "awaiting_agent".to_string(),
        };
        let provider = value["provider"].as_str().unwrap_or_default().to_string();
        let created_at = value["created_at"].as_str().unwrap_or_default().to_string();
        jobs.push(DesktopJob {
            id: value["id"].as_str().unwrap_or_default().to_string(),
            message: job_message(&status, &provider),
            ready: status == "draft_ready",
            updated_at: if updated_at.is_empty() { created_at.clone() } else { updated_at },
            provider, status, created_at, error,
        });
    }
    jobs.sort_by(|left, right| right.created_at.cmp(&left.created_at));
    Ok(jobs)
}

#[tauri::command]
fn delete_desktop_job(job_id: String) -> Result<(), String> {
    fs::remove_dir_all(job_dir(&job_id)?).map_err(|error| error.to_string())
}

#[tauri::command]
fn retry_desktop_job(job_id: String) -> Result<(), String> {
    let job = job_dir(&job_id)?;
    write_job_state(&job, "draft_ready", "")
}

#[tauri::command]
fn mark_job_imported(job_id: String) -> Result<(), String> {
    let job = job_dir(&job_id)?;
    write_job_state(&job, "imported", "")
}

fn engine_command() -> Result<Command, String> {
    let path = engine_home()?.join("runtime").join("bbc-course-agent.exe");
    let needs_write = !path.is_file() || fs::metadata(&path).map(|metadata| metadata.len() != ENGINE_BINARY.len() as u64).unwrap_or(true);
    if needs_write {
        fs::create_dir_all(path.parent().ok_or("内部课程引擎目录无效。")?).map_err(|error| error.to_string())?;
        fs::write(&path, ENGINE_BINARY).map_err(|error| error.to_string())?;
    }
    let mut command = Command::new(path);
    run_without_console(&mut command);
    // Piped output defaults to the system code page on a Chinese Windows, which
    // would corrupt both the progress text and any course path containing
    // non-ASCII characters.
    command.env("PYTHONIOENCODING", "utf-8").env("PYTHONUTF8", "1");
    Ok(command)
}

fn engine_settings() -> Result<(PathBuf, Value), String> {
    let path = engine_home()?.join("settings.json");
    let value = if path.is_file() {
        serde_json::from_slice(&fs::read(&path).map_err(|error| error.to_string())?).unwrap_or_else(|_| json!({}))
    } else { json!({}) };
    Ok((path, value))
}

fn schedule_task_name() -> &'static str { "Clear English Speaking Background" }

fn scheduled_background() -> Result<(), String> {
    let (_, settings) = engine_settings()?;
    let provider = settings["desktop_provider"].as_str().unwrap_or("workbuddy");
    match provider {
        "api" => {
            let home = engine_home()?;
            let output = engine_command()?.arg("run-scheduled").env("CLEAR_ENGLISH_HOME", home).output().map_err(|error| error.to_string())?;
            if !output.status.success() { return Err(String::from_utf8_lossy(&output.stderr).trim().to_string()); }
        }
        "codex" => { let _ = start_codex_job()?; }
        "workbuddy" => { let workspace = workspace_root()?; let _ = write_job(&workspace, "workbuddy")?; }
        _ => return Err("自动计划的备课来源无效。".into()),
    }
    Ok(())
}

fn latest_course(home: &Path) -> Result<PathBuf, String> {
    let courses = home.join("courses");
    fs::read_dir(&courses)
        .map_err(|error| error.to_string())?
        .filter_map(Result::ok)
        .filter(|entry| entry.path().extension().and_then(|value| value.to_str()) == Some("zip"))
        .max_by_key(|entry| entry.metadata().and_then(|metadata| metadata.modified()).ok())
        .map(|entry| entry.path())
        .ok_or_else(|| "本地课程引擎没有生成课程包。".to_string())
}

/// Run the engine while forwarding its `PROGRESS` lines to the window, so a
/// multi-minute alignment shows what it is doing instead of looking frozen.
fn run_engine_with_progress(app: &AppHandle, job_id: &str, arguments: &[&str], draft: Option<&Path>) -> Result<String, String> {
    let home = engine_home()?;
    let mut command = engine_command()?;
    command.args(arguments);
    if let Some(path) = draft { command.arg(path); }
    let mut child = command
        .env("CLEAR_ENGLISH_HOME", home)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("课程引擎未启动：{error}"))?;

    let stderr = child.stderr.take().ok_or("无法读取课程引擎输出。")?;
    let handle = app.clone();
    let job = job_id.to_string();
    let reader = thread::spawn(move || {
        let mut diagnostics = Vec::new();
        let mut source = io::BufReader::new(stderr);
        let mut raw = Vec::new();
        // Decode leniently: one unexpected byte must not truncate the stream.
        while matches!(source.read_until(b'\n', &mut raw), Ok(read) if read > 0) {
            let line = String::from_utf8_lossy(&raw).trim_end_matches(['\r', '\n']).to_string();
            raw.clear();
            if let Some(rest) = line.strip_prefix("PROGRESS\t") {
                let mut parts = rest.splitn(2, '\t');
                let stage = parts.next().unwrap_or_default().to_string();
                let message = parts.next().unwrap_or_default().to_string();
                let _ = handle.emit("course-build-progress", BuildProgress { job_id: job.clone(), stage, message });
            } else if !line.trim().is_empty() {
                diagnostics.push(line);
            }
        }
        diagnostics
    });

    let output = child.wait_with_output().map_err(|error| error.to_string())?;
    let diagnostics = reader.join().unwrap_or_default();
    if !output.status.success() {
        // The engine's last diagnostic line carries the error code.
        return Err(diagnostics.last().cloned().unwrap_or_else(|| "课程引擎异常退出。".into()));
    }
    let course = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if course.is_empty() { return Err("课程引擎未返回课程包路径。".into()); }
    Ok(course)
}

#[tauri::command]
fn build_desktop_job(app: AppHandle, job_id: String) -> Result<String, String> {
    let job = job_dir(&job_id)?;
    let draft = job.join("output").join("lesson-draft.json");
    if !draft.is_file() { return Err("尚未收到备课草案。".into()); }
    write_job_state(&job, "building", "")?;
    match run_engine_with_progress(&app, &job_id, &["build-draft", "--draft"], Some(&draft)) {
        Ok(course) => Ok(course),
        Err(error) => {
            let _ = write_job_state(&job, "failed", &error);
            Err(error)
        }
    }
}

#[tauri::command]
fn ensure_demo_course() -> Result<String, String> {
    let home = engine_home()?;
    let target = home.join("courses").join("demo-local.zip");
    if target.is_file() { return Ok(target.display().to_string()); }
    fs::create_dir_all(target.parent().ok_or("课程目录无效。")?).map_err(|error| error.to_string())?;
    let output = engine_command()?
        .args(["demo-package", "--output"]).arg(&target)
        .env("CLEAR_ENGLISH_HOME", &home)
        .output().map_err(|error| format!("课程引擎未启动：{error}"))?;
    if !output.status.success() { return Err(String::from_utf8_lossy(&output.stderr).trim().to_string()); }
    Ok(target.display().to_string())
}

fn course_in_library(path: &str) -> Result<PathBuf, String> {
    let course = PathBuf::from(path);
    let allowed = engine_home()?.join("courses");
    let inside = course.parent().map(|parent| parent == allowed).unwrap_or(false);
    if !inside || course.extension().and_then(|value| value.to_str()) != Some("zip") {
        return Err("不允许访问该课程文件。".into());
    }
    Ok(course)
}

#[tauri::command]
fn delete_local_course(path: String) -> Result<(), String> {
    fs::remove_file(course_in_library(&path)?).map_err(|error| error.to_string())
}

/// Hand a file to whatever program the user opens that type with.
fn open_with_shell(path: &Path) -> Result<(), String> {
    // explorer.exe resolves the default handler and never shows a console.
    let mut command = Command::new("explorer.exe");
    command.arg(path);
    run_without_console(&mut command);
    command.spawn().map_err(|error| format!("无法打开这个文件：{error}"))?;
    Ok(())
}

/// Write the lesson transcript out of the course package and open it.
///
/// The web view cannot open a `blob:` URL in a new window, so the desktop
/// build has to put the PDF on disk before the user's PDF reader can show it.
/// Reduce a caller-supplied name to a plain PDF filename inside our folder.
fn transcript_file_name(file_name: &str) -> String {
    let stem: String = file_name
        .chars()
        .filter(|value| value.is_ascii_alphanumeric() || matches!(value, '-' | '_' | '.'))
        .collect();
    let stem = stem.trim_matches('.').to_string();
    let name = if stem.is_empty() { "transcript".to_string() } else { stem };
    if name.to_ascii_lowercase().ends_with(".pdf") { name } else { format!("{name}.pdf") }
}

#[tauri::command]
fn open_transcript(file_name: String, data: Vec<u8>) -> Result<String, String> {
    if data.is_empty() {
        return Err("这节课的原文文件是空的。".into());
    }
    let name = transcript_file_name(&file_name);
    let folder = engine_home()?.join("transcripts");
    fs::create_dir_all(&folder).map_err(|error| error.to_string())?;
    let path = folder.join(name);
    fs::write(&path, data).map_err(|error| error.to_string())?;
    open_with_shell(&path)?;
    Ok(path.display().to_string())
}

/// Open an official source page in the user's real browser.
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    if !url.starts_with("https://") {
        return Err("只允许打开 HTTPS 链接。".into());
    }
    let mut command = Command::new("cmd");
    command.args(["/C", "start", "", &url]);
    run_without_console(&mut command);
    command.spawn().map_err(|error| format!("无法打开链接：{error}"))?;
    Ok(())
}

#[tauri::command]
fn open_course_folder() -> Result<(), String> {
    let courses = engine_home()?.join("courses");
    fs::create_dir_all(&courses).map_err(|error| error.to_string())?;
    Command::new("explorer.exe").arg(&courses).spawn().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn list_local_courses() -> Result<Vec<String>, String> {
    let root = engine_home()?.join("courses");
    if !root.is_dir() { return Ok(Vec::new()); }
    let mut courses = fs::read_dir(root).map_err(|error| error.to_string())?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.extension().is_some_and(|extension| extension.eq_ignore_ascii_case("zip")))
        .collect::<Vec<_>>();
    courses.sort_by_key(|path| fs::metadata(path).and_then(|metadata| metadata.modified()).ok());
    courses.reverse();
    Ok(courses.into_iter().map(|path| path.to_string_lossy().to_string()).collect())
}

#[tauri::command]
fn start_api_course(app: AppHandle) -> Result<String, String> {
    let home = engine_home()?;
    let result = run_engine_with_progress(&app, "api", &["run-scheduled"], None)?;
    if !result.contains("已写入课程") { return Err(result.trim().to_string()); }
    Ok(latest_course(&home)?.display().to_string())
}

/// Hand a course ZIP to the player as raw bytes.
///
/// A real 6 Minute English package is ~14 MB, which becomes an ~18 MB base64
/// string if sent as JSON. That payload does not survive the IPC bridge, so
/// large courses silently failed to import while the tiny demo worked. Raw
/// binary responses avoid both the encoding and the size blow-up.
#[tauri::command]
fn read_course_bytes(path: String) -> Result<tauri::ipc::Response, String> {
    let data = fs::read(course_in_library(&path)?).map_err(|error| error.to_string())?;
    Ok(tauri::ipc::Response::new(data))
}

#[tauri::command]
fn configure_api(configuration: ApiConfiguration) -> Result<(), String> {
    if !configuration.base_url.starts_with("https://") || configuration.model.trim().is_empty() || configuration.api_key.trim().is_empty() { return Err("请填写 HTTPS 服务地址、模型名称和 API Key。".into()); }
    let entry = Entry::new("clear-english-speaking", "clear-english-model-key").map_err(|error| error.to_string())?;
    entry.set_password(&configuration.api_key).map_err(|error| error.to_string())?;
    let settings_path = engine_home()?.join("settings.json");
    let mut value = if settings_path.is_file() { serde_json::from_slice(&fs::read(&settings_path).map_err(|error| error.to_string())?).unwrap_or_else(|_| json!({})) } else { json!({}) };
    value["model"] = json!({"base_url": configuration.base_url.trim_end_matches('/'), "model": configuration.model.trim(), "api_key_ref": "clear-english-model-key"});
    fs::write(settings_path, serde_json::to_vec_pretty(&value).map_err(|error| error.to_string())?).map_err(|error| error.to_string())
}

#[tauri::command]
fn configure_schedule(configuration: ScheduleConfiguration) -> Result<String, String> {
    let valid_time = configuration.time.len() == 5 && configuration.time.chars().enumerate().all(|(index, character)| if index == 2 { character == ':' } else { character.is_ascii_digit() });
    let valid_days = !configuration.days.is_empty() && configuration.days.iter().all(|day| (1..=7).contains(day));
    if !valid_time || !valid_days || !matches!(configuration.provider.as_str(), "workbuddy" | "codex" | "api") {
        return Err("请填写有效的星期、时间和备课来源。".into());
    }
    let (settings_path, mut settings) = engine_settings()?;
    settings["schedule"] = json!({"days": configuration.days.clone(), "time": configuration.time.clone(), "timezone": configuration.timezone.clone()});
    settings["desktop_provider"] = json!(configuration.provider.clone());
    fs::write(&settings_path, serde_json::to_vec_pretty(&settings).map_err(|error| error.to_string())?).map_err(|error| error.to_string())?;
    if !configuration.enabled {
        let _ = Command::new("schtasks.exe").args(["/Delete", "/TN", schedule_task_name(), "/F"]).output();
        return Ok("自动计划已关闭。".into());
    }
    let executable = env::current_exe().map_err(|error| error.to_string())?;
    let task_command = format!("\"{}\" --background", executable.display());
    let day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
    let selected_days = configuration.days.iter().map(|day| day_names[usize::from(*day - 1)]).collect::<Vec<_>>().join(",");
    let output = Command::new("schtasks.exe")
        .args(["/Create", "/TN", schedule_task_name(), "/SC", "WEEKLY", "/D"])
        .arg(selected_days).args(["/ST", &configuration.time, "/TR"])
        .arg(task_command).args(["/F", "/RL", "LIMITED"])
        .output().map_err(|error| error.to_string())?;
    if !output.status.success() { return Err(String::from_utf8_lossy(&output.stderr).trim().to_string()); }
    Ok("自动计划已保存到 Windows 任务计划程序。WorkBuddy 到点只创建待办；Codex/API 会后台备课。".into())
}

pub fn run() {
    if env::args().any(|argument| argument == "--background") {
        if let Ok(path) = local_app_data() {
            let result = scheduled_background();
            let content = result.err().unwrap_or_else(|| now());
            let _ = fs::write(path.join("background-heartbeat.txt"), content);
        }
        return;
    }
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            desktop_status, prepare_workbuddy, open_workbuddy, start_codex_job,
            list_desktop_jobs, delete_desktop_job, retry_desktop_job, mark_job_imported,
            build_desktop_job, list_local_courses, delete_local_course, open_course_folder,
            ensure_demo_course, start_api_course, read_course_bytes, configure_api, configure_schedule,
            open_transcript, open_external
        ])
        .run(tauri::generate_context!())
        .expect("Clear English Speaking desktop application failed to start");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prompt_keeps_the_job_path_visible() {
        let prompt = workbuddy_prompt(Path::new("C:/job/task.json"));
        assert!(prompt.contains("C:/job/task.json"));
        assert!(prompt.contains("5–6"));
    }

    #[test]
    fn transcript_names_cannot_escape_the_transcript_folder() {
        for hostile in ["../../evil", "..\\..\\evil.pdf", "C:/Windows/system32/x.pdf", "a/b/c.pdf"] {
            let name = transcript_file_name(hostile);
            assert!(!name.contains('/') && !name.contains('\\') && !name.contains(':'), "{name}");
            assert!(!name.starts_with('.'), "{name}");
            assert!(name.to_ascii_lowercase().ends_with(".pdf"), "{name}");
        }
    }

    #[test]
    fn transcript_names_keep_the_episode_and_stay_pdf() {
        assert_eq!(transcript_file_name("260813-transcript.pdf"), "260813-transcript.pdf");
        assert_eq!(transcript_file_name("260813"), "260813.pdf");
        assert_eq!(transcript_file_name("..."), "transcript.pdf");
    }

    #[test]
    fn workbuddy_search_covers_non_system_drives() {
        assert!(workbuddy_candidates().iter().any(|candidate| candidate == Path::new("E:\\Program Files\\WorkBuddy\\WorkBuddy.exe")));
    }
}
